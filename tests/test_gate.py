"""`cancerbasemap gate`: a release bundle against the previous release, offline (#172).

Bundles are tiny Parquet + manifest.json in the `publish` layout, under tmp_path.
"""

import hashlib
import json
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import duckdb
import pytest

from cancerbasemap import gate
from cancerbasemap.__main__ import main

# value_status / value / numerator / denominator / lower / upper of one row each
OBSERVATION = (
    "SELECT * FROM (VALUES "
    "(1, 'reported', 12.5, 5, 40, 10.0, 15.0), "
    "(2, 'suppressed_small_count', {value}, 3, 100, 1.0, 9.0), "
    "(3, 'not_available', NULL, NULL, 77, NULL, NULL)"
    ") t(geo_id, value_status, value, numerator, denominator, lower, upper)"
)
GEO = "SELECT i::BIGINT AS id FROM range({n}) t(i)"


def _bundle(root, release, tables):
    """Write `tables` (name -> SELECT) as a release bundle under `root`."""
    con = duckdb.connect()
    entries = []
    for name, sql in tables.items():
        schema, table = name.split(".")
        rel = f"{schema}/{table}.parquet"
        (root / schema).mkdir(parents=True, exist_ok=True)
        n = con.execute(f"COPY ({sql}) TO '{root / rel}' (FORMAT parquet)").fetchone()[0]
        cols = con.execute(f"DESCRIBE SELECT * FROM read_parquet('{root / rel}')").fetchall()
        with (root / rel).open("rb") as f:
            sha256 = hashlib.file_digest(f, "sha256").hexdigest()
        entries.append({"schema": schema, "table": table, "path": rel, "row_count": n,
                        "sha256": sha256, "comment": None,
                        "columns": [{"name": c[0], "type": c[1], "doc": None} for c in cols]})
    (root / "manifest.json").write_text(json.dumps({"release": release, "tables": entries}))
    return root


def _run(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["cancerbasemap", "gate", *argv])
    with pytest.raises(SystemExit) as e:
        main()
    return e.value.code


@pytest.fixture
def reference(tmp_path):
    return _bundle(tmp_path / "v2026-10-01", "2026-10-01", {
        "measure.observation": OBSERVATION.format(value="NULL"),
        "geography.unit": GEO.format(n=30)})


def candidate(tmp_path, **tables):
    return _bundle(tmp_path / "candidate", "2026-11-01", {
        "measure.observation": OBSERVATION.format(value="NULL"),
        "geography.unit": GEO.format(n=33), **tables})


def test_clean_bundle_passes_and_gate_json_binds_the_manifest(tmp_path, reference, monkeypatch, capsys):
    bundle = candidate(tmp_path)
    assert _run(monkeypatch, str(bundle), "--reference", reference.as_uri()) == 0
    out = capsys.readouterr().out
    assert out.startswith(f"release 2026-11-01 against {reference.as_uri()} (release 2026-10-01)\n")
    assert "  ok    value_null_unless_reported" in out and out.endswith("PASS\n")
    assert "README marks no ```sql bundle queries: skipping" in out
    g = json.loads((bundle / gate.GATE_FILE).read_text())
    assert g["manifest_sha256"] == hashlib.sha256((bundle / "manifest.json").read_bytes()).hexdigest()
    assert g["release"] == "2026-11-01" and g["reference_release"] == "2026-10-01"


def test_a_number_in_value_on_a_non_reported_row_fails_and_writes_no_gate_json(
        tmp_path, reference, monkeypatch, capsys):
    bundle = _bundle(tmp_path / "candidate", "2026-11-01", {
        "measure.observation": OBSERVATION.format(value="4.2"),
        "geography.unit": GEO.format(n=33)})
    (bundle / gate.GATE_FILE).write_text("stale")
    assert _run(monkeypatch, str(bundle), "--reference", reference.as_uri()) == 1
    out = capsys.readouterr().out
    assert "  FAIL  value_null_unless_reported  (1 rows)" in out
    assert "FAIL: 1 required check(s) failed" in out
    assert not (bundle / gate.GATE_FILE).exists()


def test_source_published_numbers_beside_a_null_value_pass(tmp_path, reference, monkeypatch):
    # OBSERVATION's non-reported rows carry numerator, denominator, lower and upper (#172 amendment).
    bundle = candidate(tmp_path)
    assert _run(monkeypatch, str(bundle), "--reference", reference.as_uri()) == 0


def test_a_table_missing_from_the_bundle_fails(tmp_path, reference, monkeypatch, capsys):
    bundle = _bundle(tmp_path / "candidate", "2026-11-01",
                     {"measure.observation": OBSERVATION.format(value="NULL")})
    assert _run(monkeypatch, str(bundle), "--reference", reference.as_uri()) == 1
    assert "  FAIL  present" in capsys.readouterr().out


def test_row_count_outside_bounds_and_schema_drift_fail(tmp_path, reference, monkeypatch, capsys):
    bundle = _bundle(tmp_path / "candidate", "2026-11-01", {
        "measure.observation": OBSERVATION.format(value="NULL"),
        "geography.unit": "SELECT i::VARCHAR AS id FROM range(10) t(i)"})
    assert _run(monkeypatch, str(bundle), "--reference", reference.as_uri()) == 1
    out = capsys.readouterr().out
    assert "  FAIL  row_count_bounds  (10 rows, reference 30)" in out
    assert "  FAIL  schema_unchanged" in out


def test_a_reference_not_older_than_the_bundle_is_refused(reference, monkeypatch, capsys):
    assert _run(monkeypatch, str(reference), "--reference", reference.as_uri()) == 1
    assert "is not older than 2026-10-01" in capsys.readouterr().out


def test_manifest_row_count_that_disagrees_with_its_parquet_fails(tmp_path, monkeypatch, capsys):
    bundle = candidate(tmp_path)
    m = json.loads((bundle / "manifest.json").read_text())
    m["tables"][1]["row_count"] = 31
    (bundle / "manifest.json").write_text(json.dumps(m))
    assert _run(monkeypatch, str(bundle), "--reference", "none") == 1
    assert "  FAIL  manifest_row_count  (parquet 33, manifest 31)" in capsys.readouterr().out


def test_reference_none_runs_bundle_checks_only(tmp_path, monkeypatch, capsys):
    bundle = candidate(tmp_path)
    assert _run(monkeypatch, str(bundle), "--reference", "none") == 0
    assert "bundle checks only, no reference given" in capsys.readouterr().out
    assert json.loads((bundle / gate.GATE_FILE).read_text())["reference"] is None


def test_no_published_release_404_runs_bundle_checks_only(tmp_path, monkeypatch, capsys):
    served = tmp_path / "served"
    served.mkdir()
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(served)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}/data/latest"
    try:
        assert _run(monkeypatch, str(candidate(tmp_path)), "--reference", url) == 0
    finally:
        server.shutdown()
    assert f"bundle checks only, no published release at {url}" in capsys.readouterr().out


def test_readme_queries_run_only_when_marked_for_the_bundle(tmp_path, monkeypatch, capsys):
    readme = tmp_path / "README.md"
    readme.write_text("```sql\nSELECT * FROM coi.measure.observation\n```\n\n"
                      "```sql bundle\nSELECT count(*) FROM measure.observation;\n```\n")
    assert gate.readme_queries(readme) == [(6, "SELECT count(*) FROM measure.observation")]
    monkeypatch.setattr(gate, "README", readme)
    assert _run(monkeypatch, str(candidate(tmp_path)), "--reference", "none") == 0
    assert "  ok    readme_query_line_6  (1 rows)" in capsys.readouterr().out
