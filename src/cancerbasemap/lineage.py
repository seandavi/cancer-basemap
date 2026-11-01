"""Table- and column-level lineage, captured at ingest with sqlglot (#140).

`provenance.release` says *what* a release was built from; this says *how* a
column got its values, as a DAG over the SQL a module already writes -- no
inference from read/write order (that over-reports: it would claim
`measure.definition <- raw.*` for a table built from Python literals), no
monkeypatching of `duckdb.connect`.

A module opts in explicitly, in three small steps:
  - `connect()` instead of `duckdb.connect()` -- records every SQL statement
    executed (so a CTAS/VIEW intermediate like `combined` or `raw` can be
    resolved) and the local-name -> catalog-table map `load()` builds.
  - `load(con, cat, name, identifier, **scan_kwargs)` instead of
    `con.register(name, cat.load_table(identifier).scan(**kw).to_arrow())`.
  - one `record(cat, release, job, con, outputs)` call at the end of
    `transform`, `outputs` mapping each table it wrote to the exact SQL text
    that produced it. A `raw.*` output maps to the upstream URL instead (the
    DAG's root); an output built in Python rather than SQL (no query at all)
    maps to `None` and gets no lineage, honestly, rather than a guess.

sqlglot's own lineage/scope machinery does the walking (CTEs, subqueries,
CTAS/UNION branches, `SELECT *`); the one thing it can't do is notice that one
UNION branch's literal key column (`measure_id`) belongs with that branch's
`value`/`lower`/... edges -- `_literal_key` does that, small, by hand.

A capture failure never aborts or corrupts an ingest: whatever resolved is
still written, and the unresolved count is printed, not raised.
"""

import subprocess
from importlib.metadata import version as _pkg_version
from pathlib import Path

import duckdb
import pyarrow as pa
import sqlglot
from pyiceberg.expressions import And, EqualTo, In
from sqlglot import exp
from sqlglot.lineage import lineage as _sqlglot_lineage

from . import merge, schemas

DIALECT = "duckdb"


class _Recording:
    """Thin proxy over a real DuckDB connection: logs every `.sql()`/`.execute()`
    statement and the local-name -> catalog-identifier map `load()` fills in.
    Everything else passes straight through -- this is what lets a wired module
    keep using `con.sql(...)` unchanged."""

    def __init__(self):
        self._con = duckdb.connect()
        self.statements = []
        self.tables = {}

    def sql(self, query, *a, **kw):
        self.statements.append(query)
        return self._con.sql(query, *a, **kw)

    def execute(self, query, *a, **kw):
        self.statements.append(query)
        return self._con.execute(query, *a, **kw)

    def __getattr__(self, name):
        return getattr(self._con, name)


def connect():
    """A DuckDB connection wrapper for lineage capture -- drop-in for `duckdb.connect()`."""
    return _Recording()


def load(con, cat, name, identifier, **scan_kwargs):
    """Register `identifier`'s scan as `name` and remember the mapping, so a
    later `record()` can turn a leaf reference to `name` back into a real
    catalog table."""
    con.register(name, cat.load_table(identifier).scan(**scan_kwargs).to_arrow())
    con.tables[name] = identifier


def _code_version():
    try:
        got = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=Path(__file__).parent,
                             capture_output=True, text=True, timeout=5, check=True)
        return got.stdout.strip()
    except Exception:
        return _pkg_version("cancerbasemap")


def _ctas_sources(statements):
    """name -> its defining SELECT, for every `CREATE [OR REPLACE] TABLE name AS
    SELECT ...` this connection ran -- what lets sqlglot see through an
    intermediate like `combined` or a UNIONed `raw` view."""
    sources = {}
    for stmt in statements:
        try:
            parsed = sqlglot.parse_one(stmt, read=DIALECT)
        except Exception:
            continue
        if isinstance(parsed, exp.Create) and parsed.kind == "TABLE" and parsed.expression:
            sources[parsed.this.name] = parsed.expression
    return sources


def _resolve(name, tables, from_column=None):
    """A leaf reference's local name -> (catalog identifier, 'table'), or None
    when it isn't one this connection registered, or when `from_column` isn't
    really one of that table's declared columns -- sqlglot resolves a column
    reference syntactically, with no real schema behind it, so a misspelled or
    stale one would otherwise be written to provenance.lineage unvalidated."""
    if name not in tables:
        return None
    identifier = tables[name]
    if from_column is not None:
        d = schemas.TABLES.get(identifier)
        if d is None or from_column.lower() not in {f.name.lower() for f in d.schema.fields}:
            return None
    return identifier, "table"


def _literal_key(select, key_col):
    """The literal value of `key_col` in one branch's SELECT, or None. PLACES'
    `measure_id` is a computed expression, not a literal, so this legitimately
    returns None there; RUCC's and SVI's are literals and this resolves them."""
    for proj in select.expressions:
        if proj.alias_or_name == key_col:
            val = proj.unalias() if isinstance(proj, exp.Alias) else proj
            return val.this if isinstance(val, exp.Literal) else None
    return None


def _leaf_edges(node, key_col, variable=None, expr_sql=None):
    """DFS to every leaf, carrying down the nearest enclosing branch's literal
    key value and the nearest enclosing REAL expression -- wherever a UNION
    branch sits (a flat top-level UNION, RUCC/PLACES/SVI's own shape, or one
    buried inside a CTE), and skipping past a merely-passthrough alias (a
    subquery re-projecting a column under the same or a new name) so the
    outer, actual transformation isn't discarded in favour of the inner
    passthrough sqlglot happens to walk through next."""
    if key_col and isinstance(node.source, exp.Select):
        lit = _literal_key(node.source, key_col)
        if lit is not None:
            variable = lit
    if not node.downstream:
        if isinstance(node.expression, exp.Table):
            yield node, variable, expr_sql
        return
    inner = node.expression.unalias() if isinstance(node.expression, exp.Alias) else node.expression
    if not isinstance(inner, exp.Column):
        expr_sql = inner.sql(dialect=DIALECT)
    for child in node.downstream:
        yield from _leaf_edges(child, key_col, variable, expr_sql)


def _try_lineage(col, parsed, sources, trim_selects=True):
    """`sqlglot.lineage.lineage`, wrapped: a target column absent from this
    query's own output list is benign (sqlglot's own "Cannot find column"
    check) -- most of a table's declared columns aren't produced by any one
    output's SQL -- and resolves to no edges, not an unresolved count. Any
    other failure (a real parse/resolution problem) is a genuine unresolved
    edge, counted rather than silently dropped."""
    try:
        return _sqlglot_lineage(col, parsed, sources=sources, dialect=DIALECT,
                                trim_selects=trim_selects), 0
    except sqlglot.errors.SqlglotError as err:
        return (None, 0) if "Cannot find column" in str(err) else (None, 1)
    except Exception:
        return None, 1


def _column_edges(parsed, sources, tables, col, key_col):
    """Every (table, from_column, kind, expression, to_variable) `col` resolves
    to, plus how many leaves didn't resolve to a known table and column."""
    node, unresolved = _try_lineage(col, parsed, sources, trim_selects=False)
    if node is None:
        return [], unresolved
    edges = []
    for leaf, variable, expr_sql in _leaf_edges(node, key_col):
        from_col = leaf.name.rsplit(".", 1)[-1]
        found = _resolve(leaf.expression.name, tables, from_col)
        if not found:
            unresolved += 1
            continue
        table, kind = found
        edges.append((table, from_col, kind, expr_sql, variable))
    return edges, unresolved


def _leaves(node):
    return (n for n in node.walk() if not n.downstream and isinstance(n.expression, exp.Table))


def _table_edges(parsed, sources, tables, covered):
    """One (table, kind) per source table the query touches that a column-level
    pass didn't already cover -- so the table-level DAG never stores a pair
    twice, and an output with no matching declared column (built in Python from
    a query's tuples, e.g. `measure.definition`) still gets an honest,
    table-level-only edge."""
    edges, unresolved = [], 0
    for name in parsed.named_selects:
        node, n = _try_lineage(name, parsed, sources)
        unresolved += n
        if node is None:
            continue
        for leaf in _leaves(node):
            found = _resolve(leaf.expression.name, tables)
            if not found:
                unresolved += 1
                continue
            table, kind = found
            if table not in covered:
                covered.add(table)
                edges.append((table, kind))
    return edges, unresolved


def _row(release, job, to_table, to_column, to_variable, from_table, from_column,
         from_kind, expression, code_version):
    return dict(release=release, job=job, to_table=to_table, to_column=to_column,
                to_variable=to_variable, from_table=from_table, from_column=from_column,
                from_kind=from_kind, expression=expression, code_version=code_version)


def record(cat, release, job, con, outputs):
    """Resolve lineage for one ingest's outputs and write `provenance.lineage`.

    `outputs` maps a target table identifier to one of:
      - the exact SQL SELECT whose result became that table (str);
      - the upstream URL, for a `raw.*` table (its DAG root -- dispatched on
        the `raw` namespace, not on the string's shape, so a local fixture
        path in tests roots an edge exactly like a real URL in production);
      - `None`, when the output has no SQL behind it at all (built purely from
        Python literals) -- no lineage is recorded for it, honestly.

    Written scoped on (release, job, to_table): a module calls `record()` once
    per phase (once from `land_raw` for its raw table(s), once from
    `transform` for its derived ones), and scoping only on (release, job) --
    as if one job wrote its whole lineage in a single call -- would have the
    later call's overwrite erase the earlier call's rows for the same job.
    Idempotent per to_table: rerunning an unchanged ingest writes back the
    same rows for the same to_tables.
    """
    try:
        _record(cat, release, job, con, outputs)
    except Exception as err:
        print(f"lineage: {job}: capture failed ({err}); ingest continues without it")


def _record(cat, release, job, con, outputs):
    sources = _ctas_sources(getattr(con, "statements", []))
    tables = getattr(con, "tables", {})
    code_version = _code_version()
    rows, unresolved = [], 0

    for to_table, val in outputs.items():
        if val is None:
            continue
        if to_table.split(".", 1)[0] == "raw":
            rows.append(_row(release, job, to_table, None, None, val, None,
                             "url", None, code_version))
            continue
        try:
            parsed = sqlglot.parse_one(val, read=DIALECT)
        except Exception:
            unresolved += 1
            continue

        key_col = "measure_id" if to_table == "measure.observation" else None
        covered = set()
        for col in (f.name for f in schemas.TABLES[to_table].schema.fields):
            edges, n = _column_edges(parsed, sources, tables, col, key_col)
            unresolved += n
            for table, from_col, kind, expr, variable in edges:
                covered.add(table)
                rows.append(_row(release, job, to_table, col, variable, table,
                                 from_col, kind, expr, code_version))

        table_edges, n = _table_edges(parsed, sources, tables, covered)
        unresolved += n
        for table, kind in table_edges:
            rows.append(_row(release, job, to_table, None, None, table, None,
                             kind, None, code_version))

    if unresolved:
        print(f"lineage: {job}: {unresolved} edge(s) unresolved")
    if not rows:
        return
    scope = And(EqualTo("release", release), EqualTo("job", job), In("to_table", list(outputs)))
    merge.write(cat, "provenance.lineage", pa.Table.from_pylist(rows), scope)
