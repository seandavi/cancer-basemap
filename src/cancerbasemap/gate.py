"""Publish gate (ADR-0001 § The gate, #172): a release bundle against the previous release.

Ported from biocOnIce's gate.py, without cdsci-lake's contract checks. Reads the bundle and
the reference's manifest.json only. Required checks: every table's manifest row count and
columns match its Parquet; against the reference, no table is missing, row counts stay within
bounds and columns and types are unchanged; and the hard gate, `value` is NULL in
measure.observation whenever `value_status != 'reported'`. Sources own suppression, so
lower / upper / numerator / denominator are not checked. README ```sql bundle blocks run as
optional checks. A pass leaves gate.json in the bundle, bound to its manifest.json by sha256.
"""

import hashlib
import json
import re
import urllib.error
import urllib.request
from datetime import UTC, date, datetime
from pathlib import Path

import duckdb

from .publish import DEFAULT_BASE_URL, _lit

README = Path(__file__).parents[2] / "README.md"
DEFAULT_REFERENCE = DEFAULT_BASE_URL
# Proof of a pass, in the bundle. Re-running the gate later is no substitute: once uploaded,
# latest/ is the bundle itself, and the gate refuses a reference that is not older.
GATE_FILE = "gate.json"
# Against the reference, a table's row count may shrink to this fraction or grow to this multiple.
MIN_ROW_RATIO, MAX_ROW_RATIO = 0.8, 3.0


def readme_queries(path=README):
    """(line, sql) for each ```sql bundle block in the README: the queries the README marks as
    running against the bundle's tables (named schema.table, as in views.sql)."""
    text = path.read_text()
    return [(text[:m.start()].count("\n") + 2, m[1].strip().rstrip(";"))
            for m in re.finditer(r"```sql bundle\n(.*?)```", text, re.DOTALL)]


def bundle_con(bundle: Path, tables):
    """The bundle's local Parquet as `<schema>.<table>` views."""
    con = duckdb.connect()
    for s in sorted({t["schema"] for t in tables}):
        con.execute(f"CREATE SCHEMA {s}")
    for t in tables:
        con.execute(f"CREATE VIEW {t['schema']}.{t['table']} AS "
                    f"SELECT * FROM read_parquet({_lit(str(bundle / t['path']))})")
    return con


def _check(name, passed, detail="", required=True):
    return name, passed, required, detail


def bundle_checks(con, tables, queries):
    """(name, passed, required, detail) per check on the bundle alone."""
    checks = []
    for t in tables:
        name = f"{t['schema']}.{t['table']}"
        n = con.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
        columns = [tuple(c[:2]) for c in con.execute(f"DESCRIBE {name}").fetchall()]
        declared = [(c["name"], c["type"]) for c in t["columns"]]
        checks += [_check(f"{name}.manifest_row_count", n == t["row_count"],
                          f"parquet {n}, manifest {t['row_count']}"),
                   _check(f"{name}.manifest_columns", columns == declared,
                          "" if columns == declared else "manifest and Parquet differ")]
    if any(t["schema"] == "measure" and t["table"] == "observation" for t in tables):
        bad = con.execute("SELECT count(*) FROM measure.observation "
                          "WHERE value IS NOT NULL AND value_status != 'reported'").fetchone()[0]
        checks.append(_check("measure.observation.value_null_unless_reported", bad == 0,
                             f"{bad} rows" if bad else ""))
    else:
        checks.append(_check("measure.observation.value_null_unless_reported", False,
                             "measure.observation is not in the bundle"))
    for line, sql in queries:
        try:
            n, detail = len(con.execute(sql).fetchall()), ""
        except duckdb.Error as e:  # type name only: the message can carry a local path
            n, detail = None, type(e).__name__
        checks.append(_check(f"readme_query_line_{line}", n is not None, detail or f"{n} rows",
                             required=False))
    return checks


def reference_checks(tables, ref_tables):
    """(name, passed, required, detail) per table of the reference, against the bundle's."""
    have = {f"{t['schema']}.{t['table']}": t for t in tables}
    checks = []
    for r in ref_tables:
        name = f"{r['schema']}.{r['table']}"
        t = have.get(name)
        checks.append(_check(f"{name}.present", t is not None))
        if t is None:
            continue
        lo, hi = r["row_count"] * MIN_ROW_RATIO, r["row_count"] * MAX_ROW_RATIO
        checks.append(_check(f"{name}.row_count_bounds", lo <= t["row_count"] <= hi,
                             f"{t['row_count']} rows, reference {r['row_count']}"))
        same = [(c["name"], c["type"]) for c in t["columns"]] == [(c["name"], c["type"]) for c in r["columns"]]
        checks.append(_check(f"{name}.schema_unchanged", same, "" if same else "columns or types differ"))
    return checks


def manifest_sha256(bundle: Path) -> str:
    return hashlib.sha256((bundle / "manifest.json").read_bytes()).hexdigest()


def _reference_manifest(reference):
    """The reference's manifest.json, or None when no release is published there (404)."""
    try:
        with urllib.request.urlopen(f"{reference.rstrip('/')}/manifest.json") as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def gate(bundle: Path, reference: str | None = DEFAULT_REFERENCE) -> bool:
    """Print the gate report for `bundle` against `reference` (a release base URL; None for the
    bundle checks only); True when every required check passes, and then write gate.json."""
    (bundle / GATE_FILE).unlink(missing_ok=True)
    manifest = json.loads((bundle / "manifest.json").read_text())
    ref = None
    if reference is not None:
        try:
            ref = _reference_manifest(reference)
        except (OSError, ValueError) as e:
            print(f"FAIL: reference {reference}: no readable manifest.json ({type(e).__name__})")
            return False
    if ref is None:
        print(f"release {manifest['release']}: bundle checks only, "
              + ("no reference given" if reference is None else f"no published release at {reference}"))
    else:
        print(f"release {manifest['release']} against {reference} (release {ref['release']})")
        try:
            older = date.fromisoformat(ref["release"]) < date.fromisoformat(manifest["release"])
        except (TypeError, ValueError):
            print(f"FAIL: release ids must be YYYY-MM-DD dates: reference {ref['release']!r}, "
                  f"release {manifest['release']!r}")
            return False
        # latest/ after an upload is the bundle itself.
        if not older:
            print(f"FAIL: reference release {ref['release']} is not older than {manifest['release']}; "
                  f"pass --reference with an earlier release's folder")
            return False
    queries = readme_queries(README)
    if not queries:
        print("README marks no ```sql bundle queries: skipping the README query checks")
    con = bundle_con(bundle, manifest["tables"])
    checks = bundle_checks(con, manifest["tables"], queries)
    if ref is not None:
        checks += reference_checks(manifest["tables"], ref["tables"])
    by_table: dict[str, list] = {}
    for name, passed, required, detail in checks:
        # Table checks are named `<schema>.<table>.<check>`; release-wide ones have no dot.
        parts = name.split(".", 2)
        table, check = (".".join(parts[:2]), parts[2]) if len(parts) == 3 else ("(release)", name)
        by_table.setdefault(table, []).append((check, passed, required, detail))
    for table, rows in by_table.items():
        print(table)
        for check, passed, required, detail in rows:
            status = "ok" if passed else "FAIL" if required else "warn"
            print(f"  {status:4}  {check}" + (f"  ({detail})" if detail else ""))
    failed = sum(required and not passed for _, passed, required, _ in checks)
    print(f"FAIL: {failed} required check(s) failed" if failed else "PASS")
    if not failed:
        (bundle / GATE_FILE).write_text(json.dumps({
            "release": manifest["release"], "manifest_sha256": manifest_sha256(bundle),
            "reference": reference, "reference_release": ref and ref["release"],
            "passed_at": datetime.now(UTC).isoformat(timespec="seconds")}, indent=2) + "\n")
    return not failed
