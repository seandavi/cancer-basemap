"""Release bundle (ADR-0001, #171): every published table as flat Parquet, plus
`cancerbasemap.duckdb`, `views.sql`, `restore.sql` and `manifest.json`, in one local directory.

Ported from biocOnIce's publish.py (ADR-0014). Tables are SQL: `TABLES` is (schema, table,
SELECT) against whatever DuckDB has attached as `coi` (the live Iceberg catalog). A table
moves to cdsci-lake by changing its SELECT. Nothing is uploaded here.

Type-2 tables (those with `valid_to`) publish current rows only and drop `valid_from` /
`valid_to`; raw tables ship whole.
"""

import hashlib
import json
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import duckdb
from fsspec.implementations.dirfs import DirFileSystem
from fsspec.implementations.local import LocalFileSystem

from .schemas import TABLES as DECLARED

DEFAULT_BASE_URL = "https://basemap.cancerdatasci.org/data/latest"
DB_FILE = "cancerbasemap.duckdb"
# README "Query it": anonymous, read-only.
ATTACH_LIVE = (
    "INSTALL iceberg; LOAD iceberg; ATTACH 'canceronice' AS coi (TYPE ICEBERG, "
    "ENDPOINT 'https://icegate-canceronice.seandavi.workers.dev', AUTHORIZATION_TYPE 'none')"
)
HISTORY_COLUMNS = ("valid_from", "valid_to")
HISTORY_NOTE = " In the release bundle: current rows only, without valid_from / valid_to."

# Declared tables that are not published, each with its reason. None yet.
EXCLUDED: dict[str, str] = {}


# measure.observation is read in the browser by byte range, and a catchment profile wants a
# few dozen geographies out of 30M rows. Sorting by geography level and state first puts one
# state's counties and tracts in a few row groups, whose geo_id min/max then prune the rest;
# the old (source_release, measure_id, geo_id) order scattered them over every row group of
# every measure. Replaying one center's queries (#206): 47 MB -> 8 MB read natively, ~160 -> ~59
# MB under a 16 MB read-ahead model. One-measure-all-counties reads 1 -> 5 MB. Smaller row
# groups did not help: the footer grows and requests multiply (docs/adr/0001, Layout).
ORDER_BY = {
    "measure.observation": "left(geo_id, instr(geo_id, ':') + 2), source, source_release, measure_id, geo_id",
}


def _select(name, d):
    """Type-2 tables: current rows, validity columns dropped. Everything else: whole."""
    if any(f.name == "valid_to" for f in d.schema.fields):
        sql = (f"SELECT * EXCLUDE ({', '.join(HISTORY_COLUMNS)}) FROM coi.{name} "
               "WHERE valid_to IS NULL")
    else:
        sql = f"SELECT * FROM coi.{name}"
    return f"{sql} ORDER BY {ORDER_BY[name]}" if name in ORDER_BY else sql


TABLES = [(*name.split("."), _select(name, d)) for name, d in DECLARED.items()
          if name not in EXCLUDED]


def connect():
    """DuckDB with the live Iceberg catalog attached as `coi`."""
    con = duckdb.connect()
    con.execute(ATTACH_LIVE)
    return con


def _docs(name):
    """(table comment, {column: doc}) from the declarations."""
    d = DECLARED[name]
    versioned = any(f.name == "valid_to" for f in d.schema.fields)
    return d.comment + (HISTORY_NOTE if versioned else ""), {f.name: f.doc for f in d.schema.fields if f.doc}


def _lit(s):
    return "'" + s.replace("'", "''") + "'"


def _url(base_url, t):
    return f"{base_url}/{t['schema']}/{t['table']}.parquet"


def views_sql(tables, base_url):
    """One view per table over its absolute Parquet URL, with the declared comments."""
    stmts = [f"CREATE SCHEMA IF NOT EXISTS {s}" for s in sorted({t["schema"] for t in tables})]
    for t in tables:
        name = f"{t['schema']}.{t['table']}"
        stmts.append(f"CREATE OR REPLACE VIEW {name} AS SELECT * FROM read_parquet({_lit(_url(base_url, t))})")
        if t["comment"]:
            stmts.append(f"COMMENT ON VIEW {name} IS {_lit(t['comment'])}")
        stmts += [f'COMMENT ON COLUMN {name}."{c["name"]}" IS {_lit(c["doc"])}'
                  for c in t["columns"] if c["doc"]]
    return ";\n".join(stmts) + ";\n"


def restore_sql(tables, base_url):
    """A materialised local copy of every table, then a row-count check against manifest.json."""
    stmts = [f"CREATE SCHEMA IF NOT EXISTS {s}" for s in sorted({t["schema"] for t in tables})]
    stmts += [f"CREATE OR REPLACE TABLE {t['schema']}.{t['table']} AS "
              f"SELECT * FROM read_parquet({_lit(_url(base_url, t))})" for t in tables]
    counts = "\n    UNION ALL ".join(
        f"SELECT '{t['schema']}' AS schema, '{t['table']}' AS \"table\", count(*) AS n "
        f"FROM {t['schema']}.{t['table']}" for t in tables)
    stmts.append(
        "SELECT CASE WHEN count(*) = 0 THEN 'row counts match manifest.json'\n"
        "  ELSE error('row counts differ from manifest.json: ' || "
        "string_agg(r.schema || '.' || r.\"table\", ', ')) END AS restore_check\n"
        f"FROM (\n    {counts}\n) r\n"
        "LEFT JOIN (SELECT t.schema, t.\"table\", t.row_count FROM "
        f"(SELECT unnest(tables) AS t FROM read_json({_lit(base_url + '/manifest.json')}))) m\n"
        '  ON r.schema = m.schema AND r."table" = m."table"\n'
        "WHERE m.row_count IS DISTINCT FROM r.n")
    return ";\n".join(stmts) + ";\n"


def _git_sha():
    """The build's code version; None outside a checkout."""
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=Path(__file__).parent,
                              capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


class _HttpAsLocal(DirFileSystem):
    protocol = ("http", "https")


def _build_db(path, sql, base_url, out):
    """Write cancerbasemap.duckdb from views.sql before anything is at `base_url`.

    DuckDB binds a view (reads the Parquet footer) when it is created, so an https base
    that is not uploaded yet would fail. For the build only, http(s) reads are served
    from `out` by an fsspec filesystem standing in for httpfs; the stored view SQL
    keeps the absolute URL.
    """
    path.unlink(missing_ok=True)
    con = duckdb.connect(str(path), config={"autoload_known_extensions": False})
    with tempfile.TemporaryDirectory() as root:
        scheme, rest = base_url.split("://", 1)
        if scheme in ("http", "https"):
            link = Path(root, rest)
            link.parent.mkdir(parents=True, exist_ok=True)
            link.symlink_to(out.absolute())
            con.register_filesystem(_HttpAsLocal(root, LocalFileSystem()))
        con.execute(sql)
    con.close()


def publish(con, out: Path, base_url: str = DEFAULT_BASE_URL, only=None) -> dict:
    """Build one release bundle in `out` from `con`, which has the catalog attached as `coi`.

    Each table streams to `<schema>/<table>.parquet` (ZSTD) through COPY, so nothing is
    materialised in Python. manifest.json is written last, atomically: it marks the bundle
    complete. `out` must be new or empty, so nothing from an earlier run sits beside a
    manifest that does not list it.
    """
    selected = [t for t in TABLES if only is None or f"{t[0]}.{t[1]}" in only]
    unknown = set(only or ()) - {f"{s}.{t}" for s, t, _ in TABLES}
    if unknown:
        raise ValueError(f"not a published table: {sorted(unknown)}")
    base_url = base_url.rstrip("/")
    if out.exists() and any(out.iterdir()):
        raise ValueError(f"{out} is not empty: publish into a new directory")
    out.mkdir(parents=True, exist_ok=True)
    # Row order is not part of the bundle, and keeping it makes COPY buffer much more.
    con.execute("SET preserve_insertion_order = false")
    tables = []
    for schema, table, sql in selected:
        name = f"{schema}.{table}"
        path = out / schema / f"{table}.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        n = con.execute(f"COPY ({sql}) TO {_lit(str(path))} (FORMAT parquet, COMPRESSION zstd)").fetchone()[0]
        with path.open("rb") as f:
            sha256 = hashlib.file_digest(f, "sha256").hexdigest()
        comment, docs = _docs(name)
        cols = con.sql(f"DESCRIBE SELECT * FROM read_parquet({_lit(str(path))})").fetchall()
        tables.append({"schema": schema, "table": table, "path": f"{schema}/{table}.parquet",
                       "row_count": n, "bytes": path.stat().st_size, "sha256": sha256,
                       "comment": comment,
                       "columns": [{"name": c[0], "type": c[1], "doc": docs.get(c[0])} for c in cols]})
        print(f"{name:45} {n:>14,} rows {path.stat().st_size:>16,} bytes", flush=True)

    prov = con.sql("SELECT * FROM coi.provenance.release ORDER BY ALL")
    now = datetime.now(UTC)
    manifest = {
        "release": now.date().isoformat(),
        "published_at": now.isoformat(timespec="seconds"),
        "git_sha": _git_sha(),
        "base_url": base_url,
        "tables": tables,
        # what the data was built from: every provenance.release row at build time
        "provenance": [dict(zip(prov.columns, r)) for r in prov.fetchall()],
    }
    views = views_sql(tables, base_url)
    (out / "views.sql").write_text(views)
    (out / "restore.sql").write_text(restore_sql(tables, base_url))
    _build_db(out / DB_FILE, views, base_url, out)
    (out / "manifest.json.tmp").write_text(json.dumps(manifest, indent=2, default=str) + "\n")
    (out / "manifest.json.tmp").replace(out / "manifest.json")
    print(f"{len(tables)} tables, {sum(t['row_count'] for t in tables):,} rows, "
          f"{sum(t['bytes'] for t in tables):,} bytes -> {out}")
    return manifest
