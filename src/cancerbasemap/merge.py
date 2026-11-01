"""Release-scoped merge maintaining full Type 2 history.

A row is one **version** of a record, valid over `[valid_from, valid_to)` in
Cancer Basemap release coordinates. Merging the complete upstream state for a
scope sorts every record into one of five outcomes:

  new         business key absent      -> insert, valid_from = this release
  unchanged   present, attrs identical -> carried forward untouched
  changed     present, attrs differ    -> close the old row at this release
                                          and insert a new version
  retired     absent upstream          -> close the old row at this release
  history     already closed           -> untouched

Within the release being built, all of that is a draft: a row opened at this
release is replaced rather than superseded, and one retired at this release
that comes back identical is reopened. One opened and retired at this release
existed in no release, so `merge` refuses to drop it silently (#118) unless
the caller opts in with `allow_draft_drop` -- see `merge()`. Only earlier
releases are history.

Nothing is ever updated in place. That is the point: overwriting a changed
attribute is Kimball Type 1, which destroys history, and it is what made a
point-in-time query return transcripts pointing at genes that did not yet
exist. Closing and reopening also collapses "changed" and "reappeared" into one
rule rather than two — see biocOnIce ADR-0006.

Which columns form the business key comes from the table's own declaration, so
this works for any table in `schemas.TABLES` without being told about it.

ponytail: column names are `valid_from`/`valid_to`, ported unchanged from
bioc-on-ice. SPEC.md's `first_seen`/`retired_in` naming and the versioning
semantics generally are deliberately unsettled for this repo — see the
tracking issue for renaming (or reconciling) once that's decided; don't
invent new versioning logic here in the meantime.

ponytail: recomputes the scope's complete state and overwrites the scope rather
than writing only changed rows. PyIceberg's `upsert` derives a filter predicate
from every join key and does not complete on five million rows. Storage is
unaffected once snapshots expire, because history lives in the rows. Upgrade
path if write time matters — first choice: DuckDB MERGE INTO pushed down
against the Iceberg REST catalog (duckdb-iceberg supports MERGE per the DuckDB
release notes), gated on two verifications: it must work through icegate
against R2 Data Catalog (beta; delete-file support unverified), and the
offline test substrate — the local sqlite PyIceberg catalog — cannot take
DuckDB writes, so the local path stays PyIceberg regardless. Second choice:
go insert-only and compute `valid_to` as a `LEAD()` window in a view, which
is where Data Vault has moved.
"""

import time
from datetime import datetime, timezone

import duckdb
from pyiceberg.exceptions import CommitFailedException, RESTError
from pyiceberg.expressions import AlwaysTrue, And, EqualTo

from . import schemas


def sort_for_write(identifier, arrow, arrow_schema):
    """Order `arrow` by the table's declared `sort_by` (issue #120), one DuckDB
    `ORDER BY ... NULLS LAST`.

    This is the one place both `write` and `merge` funnel through before an
    Iceberg overwrite, so declaring `sort_by` on a TableDef is all a caller
    needs to do. PyIceberg records a table sort order in metadata (see
    `schemas._evolve`) but never enforces it when writing Parquet files — this
    ORDER BY is what actually makes a sorted column's row-group min/max
    statistics exclude anything.
    """
    keys = schemas.TABLES[identifier].sort_by
    if not keys:
        return arrow
    con = duckdb.connect()
    con.register("t", arrow)
    order = ", ".join(f'"{k}" NULLS LAST' for k in keys)
    return con.sql(f"SELECT * FROM t ORDER BY {order}").to_arrow_table().cast(arrow_schema)


def overwrite(cat, identifier, table, arrow, overwrite_filter):
    """One filtered overwrite, riding out the two transient commit failures.

    Two production loads commit to the same R2 Data Catalog at once — every
    ingest writes its manifest row to provenance.release, and the catalog
    rate-limits writes catalog-wide — so a commit can fail for reasons that
    have nothing to do with the data: a 429, or another writer's snapshot
    landing first (CommitFailedException). Both are safe to retry because the
    overwrite is a filtered replace of the scope: on a conflict the table is
    reloaded so the retry commits against the new current snapshot.
    """
    arrow = sort_for_write(identifier, arrow, arrow.schema)
    for attempt in range(8):
        try:
            table.overwrite(arrow, overwrite_filter=overwrite_filter)
            return
        except CommitFailedException:
            time.sleep(2 ** attempt)
            table = cat.load_table(identifier)
        except RESTError as err:
            if not schemas.is_rate_limit(err):
                raise
            time.sleep(65)
            table = cat.load_table(identifier)
    raise RuntimeError(f"{identifier}: commit still failing after {attempt + 1} retries")

VALIDITY = ("valid_from", "valid_to")


def _columns(identifier, schema):
    """Business key and attributes.

    The join key is the *business* key, not the Iceberg identifier fields —
    those additionally carry `valid_from`, since each change opens a new
    version. Joining on the row key would make every record look new.
    """
    keys = list(schemas.TABLES[identifier].business_key)
    attrs = [f.name for f in schema.fields if f.name not in keys and f.name not in VALIDITY]
    return keys, attrs


def _cols(schema, side, release, opened=None):
    """Column list in declared order, sourced per branch of the merge.

    `live` reads the incoming row; `closing` and `history` read the stored one.
    """
    out = []
    for f in schema.fields:
        n = f.name
        if n == "valid_from":
            out.append(opened if side == "live" else "c.valid_from")
        elif n == "valid_to":
            out.append(f"'{release}'" if side == "closing"
                       else "c.valid_to" if side == "history" else "NULL::VARCHAR")
        else:
            out.append(f'{"i" if side == "live" else "c"}."{n}"')
        out[-1] += f' AS "{n}"'
    return ", ".join(out)


def merge(cat, identifier, incoming, release, scope, allow_draft_drop=False):
    """Merge `incoming` — the complete upstream state within `scope` — into a table.

    `scope` bounds what this ingest is responsible for, typically one source.
    Records outside it are never read and so are never wrongly retired.

    A row opened at this release that `incoming` doesn't mention raises by
    default (#118): from inside one call, a sibling slice (two `merge` calls
    sharing a scope, e.g. county then tract rows under one `source_release`)
    and a deliberate correction (this release's ingest re-run with a fixed
    `incoming` that drops a row it wrongly created) look identical — both are
    a live, `valid_from == release` row absent from `incoming`. #118 asks that
    the ambiguous case raise, since a sibling slice is the far more common
    accident. Pass `allow_draft_drop=True` to get the old behaviour back for
    the deliberate-correction case: such a row is dropped as if it never
    existed in any release, as documented above.
    """
    table = schemas.create(cat, identifier)
    schema = table.schema()
    keys, attrs = _columns(identifier, schema)

    con = duckdb.connect()
    con.register("inc", incoming)
    con.register("stored", table.scan(row_filter=scope).to_arrow())

    on = " AND ".join(f'i."{k}" = c."{k}"' for k in keys)
    # IS DISTINCT FROM, so a NULL becoming a value (or the reverse) counts as a
    # change; plain <> would silently treat it as unchanged.
    differs = " OR ".join(f'i."{a}" IS DISTINCT FROM c."{a}"' for a in attrs) or "false"
    live = "c.valid_to IS NULL"
    k0 = f'"{keys[0]}"'
    kq = ", ".join(f'"{k}"' for k in keys)

    # The release being merged is still under construction, so anything recorded
    # in it is a draft that a later merge of the same release may correct:
    #   - a live row opened at this release is replaced, not superseded;
    #   - a row retired at this release that reappears identical is reopened,
    #     not re-created as a new version (its interval never really closed);
    #   - a row opened and retired at this release existed in no release, so it
    #     is dropped only under allow_draft_drop (#118 guard below); the same
    #     goes for such zero-width rows already stored, dropped unconditionally
    #     since they were never live to begin with.
    # Only earlier releases are history. This is what makes the merge safe to
    # rerun within a release, and (with allow_draft_drop) what lets a mistaken
    # ingest be undone by the correct one.
    con.execute("CREATE OR REPLACE TABLE cur AS "
                "SELECT * FROM stored WHERE valid_from IS DISTINCT FROM valid_to")

    # #118: a row opened at this release -- by an earlier merge call sharing
    # this scope, e.g. county then tract rows under one source_release -- that
    # this call's `incoming` doesn't mention matches none of the five outcomes
    # below: too new for 'retired'/'superseded' ({supersede} is false), not
    # closed for 'history', and absent from `inc` for 'new'/'changed'/
    # 'unchanged'. It would simply be missing from `final`, and the
    # scope-filtered overwrite would then erase it -- silently, since nothing
    # about that looks like an error. Raise instead of losing it, unless the
    # caller opted into that drop (allow_draft_drop) -- the documented way to
    # undo a mistaken ingest within the same release.
    if not allow_draft_drop:
        cq = ", ".join(f'c."{k}"' for k in keys)
        missing = con.sql(f"""
            SELECT {cq} FROM cur c LEFT JOIN inc i ON {on}
            WHERE c.valid_to IS NULL AND c.valid_from = '{release}' AND i.{k0} IS NULL
        """).fetchall()
        if missing:
            sample = ", ".join(str(tuple(r)) for r in missing[:5])
            raise ValueError(
                f"{identifier}: {len(missing)} row(s) opened in release {release!r} are "
                f"absent from this incoming and would be silently dropped. Either this "
                f"ingest made two `merge.merge` calls sharing one scope (#118 -- combine "
                f"this source's slices into one incoming table, or narrow `scope` to name "
                f"the slice; see AGENTS.md), or this is a deliberate same-release "
                f"correction, in which case pass allow_draft_drop=True. e.g. {sample}"
            )

    # One stored row per incoming key to match against, by priority: a row
    # retired at this release that is identical (reopen it, and thereby drop any
    # replacement opened at this release), else the live row, else a row retired
    # at this release that differs (history; the incoming opens a new version).
    keq = " AND ".join(f'l."{k}" = c."{k}"' for k in keys)
    con.execute(f"""
        CREATE OR REPLACE TABLE cand AS
        SELECT c.*, CASE WHEN c.valid_to = '{release}' AND NOT ({differs}) THEN 0
                         WHEN c.valid_to IS NULL THEN 1 ELSE 2 END AS _prio
        FROM cur c JOIN inc i ON {on}
        WHERE c.valid_to IS NULL OR c.valid_to = '{release}'
        QUALIFY row_number() OVER (PARTITION BY {", ".join(f'c."{k}"' for k in keys)} ORDER BY _prio) = 1
    """)
    is_new = f"c.{k0} IS NULL"
    reopen = f"c.valid_to = '{release}' AND NOT ({differs})"
    # A new key, a changed one, or a retired one coming back changed starts a
    # version at this release; unchanged and reopened rows keep their start.
    opened = (f"CASE WHEN {is_new} OR ({differs}) THEN '{release}' ELSE c.valid_from END")
    supersede = f"c.valid_from < '{release}'"

    con.execute(f"""
        CREATE OR REPLACE TABLE merged AS
        SELECT {_cols(schema, 'live', release, opened)},
               CASE WHEN {is_new} THEN 'new'
                    WHEN {reopen} THEN 'reopened'
                    WHEN {differs} THEN 'changed' ELSE 'unchanged' END AS _state
        FROM inc i LEFT JOIN cand c ON {on}
      UNION ALL
        SELECT {_cols(schema, 'closing', release)}, 'superseded' AS _state
        FROM inc i JOIN cur c ON {on} AND {live}
        WHERE ({differs}) AND {supersede}
      UNION ALL
        SELECT {_cols(schema, 'closing', release)}, 'retired' AS _state
        FROM cur c LEFT JOIN inc i ON {on}
        WHERE {live} AND i.{k0} IS NULL AND {supersede}
      UNION ALL
        SELECT {_cols(schema, 'history', release)}, 'history' AS _state
        FROM cur c
        WHERE c.valid_to IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM cand l WHERE l._prio = 0 AND {keq}
                          AND l.valid_from = c.valid_from)
    """)

    # Iceberg declares identifier fields and enforces nothing, so both
    # invariants are ours. Violating either corrupts silently: the current view
    # still reads correctly while joins fan out.
    for what, sql in (
        ("more than one live row",
         f"SELECT {kq} FROM merged WHERE valid_to IS NULL GROUP BY ALL HAVING count(*) > 1"),
        ("duplicate row keys",
         f"SELECT {kq}, valid_from FROM merged GROUP BY ALL HAVING count(*) > 1"),
    ):
        n = con.sql(f"SELECT count(*) FROM ({sql})").fetchone()[0]
        if n:
            raise ValueError(f"{identifier}: {n} business keys would have {what}. Either "
                             f"`incoming` contains duplicate keys, or a version boundary "
                             f"is wrong.")

    stats = dict(con.sql("SELECT _state, count(*) FROM merged GROUP BY 1").fetchall())
    cols = ", ".join(f'"{f.name}"' for f in schema.fields)
    final = con.sql(f"SELECT {cols} FROM merged").to_arrow_table()
    overwrite(cat, identifier, table, final.cast(table.schema().as_arrow()), scope)

    return {"written": sum(stats.get(s, 0) for s in ("new", "changed", "reopened", "superseded", "retired")),
            "unchanged": stats.get("unchanged", 0),
            **{s: n for s, n in stats.items() if s != "history"}}


def check_observations(arrow_table):
    """SPEC.md Acceptance C, enforced before write: `value` is NULL exactly
    when value_status != 'reported' -- checked in both directions -- and
    value_status is always one of the closed enum.

    The reverse direction (`value_status='reported'` but `value` NULL) is a
    source deriving `value_status` from something other than whether its own
    value expression actually parsed -- e.g. a raw cell's nullness/sentinel
    checked directly while `value` goes through a separate `TRY_CAST` that can
    fail independently. Caught here, once, rather than per source: schemas.py
    documents `value` as "NULL whenever value_status != 'reported'", and that
    promise runs both ways or a NULL cell reads as a silently missing
    'reported' observation rather than the suppressed/unavailable/whatever
    reading it actually got.

    Sources call this on their measure.observation Arrow table before handing
    it to `write` or `merge`.
    """
    con = duckdb.connect()
    con.register("obs", arrow_table)
    statuses = ", ".join(f"'{s}'" for s in schemas.VALUE_STATUSES)
    bad = con.sql(f"""
        SELECT count(*) FROM obs
        WHERE value_status NOT IN ({statuses})
           OR (value_status != 'reported' AND value IS NOT NULL)
           OR (value_status = 'reported' AND value IS NULL)
    """).fetchone()[0]
    if bad:
        raise ValueError(f"measure.observation: {bad} row(s) have an unknown value_status, "
                         f"a non-NULL value under a non-reported value_status, or a NULL "
                         f"value under value_status='reported'")


def write(cat, identifier, arrow, overwrite_filter):
    """Create-if-missing, cast to the declared schema, overwrite the filter's rows."""
    table = schemas.create(cat, identifier)
    # Casting to the declared schema is the check: a column we failed to produce,
    # or a null in an identifier field, fails here rather than landing quietly.
    overwrite(cat, identifier, table, arrow.cast(table.schema().as_arrow()), overwrite_filter)
    return arrow.num_rows


def manifest(cat, release, source, url, rows, version=None, method="retrieval_date", checksum=None):
    """Record what this release was built from — SPEC.md provenance namespace,
    adopted from biocOnIce ADR-0007.

    Every lander writes under its own `source` key: they land independently,
    and one overwriting another's manifest row would misreport what either was
    built from. A source with no version of its own is versioned by the
    retrieval date; one with a real, citable release label passes `version` and
    method="release_number", so the version the source itself uses is kept.

    `checksum` (SHA-256 of the retrieved bytes) is optional and NULL unless a
    caller computes it — most sources don't need to. A source versioned by
    retrieval date, where the upstream file can come back byte-identical
    (SPEC.md's vintage rule: "several scrapes that captured identical values
    are one vintage"), passes it so it can read the previous manifest row's
    checksum back and skip landing a new vintage that changed nothing (see
    bls_laus.py for the first caller).
    """
    now = datetime.now(timezone.utc)
    source_version = str(version) if version is not None else str(now.date())
    con = duckdb.connect()
    checksum_sql = f"'{checksum}'" if checksum is not None else "NULL::VARCHAR"
    arrow = con.sql(f"""
        SELECT '{release}' AS release, '{source}' AS source,
               '{source_version}' AS source_version,
               '{method}' AS version_method,
               '{now.isoformat(timespec="seconds")}' AS retrieved_at,
               '{url}' AS url, {checksum_sql} AS checksum, {rows}::BIGINT AS row_count
    """).to_arrow_table()
    # A manifest row states what a completed ingest used; it is not versioned,
    # so it is replaced wholesale for its (release, source, source_version)
    # rather than merged. source_version is part of the key (#78): several
    # source releases can land under one catalog release, and keying on
    # (release, source) alone kept only the last one landed.
    write(cat, "provenance.release", arrow,
          And(EqualTo("release", release), EqualTo("source", source),
              EqualTo("source_version", source_version)))


def _checksum(arrow):
    """Order-independent (count, hash) fingerprint of every column of every
    row: bit_xor is commutative, so it doesn't care what order the rows come
    in, which is exactly what a rewrite that only reorders rows needs."""
    con = duckdb.connect()
    con.register("t", arrow)
    return con.sql("SELECT count(*), bit_xor(hash(t)) FROM t AS t").fetchone()


def _partition_scopes(table, d):
    """One overwrite_filter per distinct value of `d.partition_by`, so
    `rewrite` can bound memory to one partition's rows at a time. Unpartitioned
    tables get a single AlwaysTrue() scope."""
    if not d.partition_by:
        return [AlwaysTrue()]
    con = duckdb.connect()
    con.register("t", table.scan(selected_fields=d.partition_by).to_arrow())
    cols = ", ".join(f'"{c}"' for c in d.partition_by)
    combos = con.sql(f"SELECT DISTINCT {cols} FROM t ORDER BY {cols}").fetchall()
    return [And(*(EqualTo(c, v) for c, v in zip(d.partition_by, combo)))
            if len(d.partition_by) > 1 else EqualTo(d.partition_by[0], combo[0])
            for combo in combos]


def rewrite(cat, identifier):
    """One-time PyIceberg-only rewrite of a live table's data files onto its
    current `sort_by` and row-group-limit properties (issue #120).

    An idempotent re-ingest reports 'unchanged' and touches no data files, so
    a table written before #120 keeps its old, unsorted physical layout until
    this runs once. PyIceberg is the only writer touched (AGENTS.md): this
    reads a scope with `table.scan`, sorts it exactly as `overwrite` would,
    and commits with `table.overwrite` -- never DELETE/UPDATE/MERGE.

    Before every commit this asserts the sorted data is the identical set of
    rows (`_checksum`, order-independent) as what was read, and refuses to
    commit a scope where it isn't -- a rewrite must not change any row, only
    where it physically lives.

    measure.observation is the only partitioned table today; rewriting it one
    `source` at a time (`_partition_scopes`) bounds memory to one source's
    rows rather than the whole ~23M-row table at once.
    """
    table = schemas.create(cat, identifier)
    d = schemas.TABLES[identifier]
    for scope in _partition_scopes(table, d):
        arrow = table.scan(row_filter=scope).to_arrow()
        if arrow.num_rows == 0:
            continue
        before = _checksum(arrow)
        sorted_arrow = sort_for_write(identifier, arrow, table.schema().as_arrow())
        after = _checksum(sorted_arrow)
        if before != after:
            raise RuntimeError(f"{identifier}: rewrite would change the data under {scope} "
                               f"(before={before}, after={after}); refusing to commit")
        overwrite(cat, identifier, table, sorted_arrow, scope)
    return table
