"""`cancerbasemap gate`: the cancer policy on top of cdsci.publish.gate, offline (#172).

The mechanics (manifest vs Parquet, missing tables, column drift, reference fetch, gate.json
binding) are tested in cdsci-lake; this covers the hard gate, the row bounds, the README
fence, the User-Agent and the CLI wiring. Bundles are tiny Parquet + manifest.json in the
`publish` layout, under tmp_path.
"""

import hashlib
import io
import json
import sys
import urllib.error
import urllib.request

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
    readme = tmp_path / "README.md"
    readme.write_text("```sql\nSELECT 1\n```\n")
    monkeypatch.setattr(gate, "README", readme)
    assert _run(monkeypatch, str(bundle), "--reference", reference.as_uri()) == 0
    out = capsys.readouterr().out
    assert f"release 2026-11-01 against {reference.as_uri()} (release 2026-10-01)\n" in out
    assert "  ok    value_null_unless_reported" in out and out.endswith("PASS\n")
    assert "marks no ```sql bundle queries: skipping" in out
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


def test_a_bundle_without_measure_observation_fails_the_hard_gate(tmp_path, monkeypatch, capsys):
    bundle = _bundle(tmp_path / "candidate", "2026-11-01", {"geography.unit": GEO.format(n=33)})
    assert _run(monkeypatch, str(bundle), "--reference", "none") == 1
    assert "  FAIL  value_null_unless_reported  (measure.observation is not in the bundle)" in capsys.readouterr().out


def test_reference_none_runs_bundle_checks_only(tmp_path, monkeypatch, capsys):
    bundle = candidate(tmp_path)
    assert _run(monkeypatch, str(bundle), "--reference", "none") == 0
    assert "bundle checks only, no reference given" in capsys.readouterr().out
    assert json.loads((bundle / gate.GATE_FILE).read_text())["reference"] is None


def test_readme_queries_run_only_when_marked_for_the_bundle(tmp_path, monkeypatch, capsys):
    readme = tmp_path / "README.md"
    readme.write_text("```sql\nSELECT * FROM coi.measure.observation\n```\n\n"
                      "```sql bundle\nSELECT count(*) FROM measure.observation;\n```\n")
    assert gate.readme_queries(readme) == [(6, "SELECT count(*) FROM measure.observation")]
    monkeypatch.setattr(gate, "README", readme)
    assert _run(monkeypatch, str(candidate(tmp_path)), "--reference", "none") == 0
    assert "  ok    readme_query_line_6  (1 rows)" in capsys.readouterr().out


def test_the_real_readme_marks_bundle_queries():
    assert gate.readme_queries(), f"{gate.README} marks no ```sql bundle query for the gate to run"


def _observation_bundle(tmp_path, sql):
    return _bundle(tmp_path / "candidate", "2026-11-01", {
        "measure.observation": sql, "geography.unit": GEO.format(n=33)})


def test_a_null_value_status_fails_the_hard_gate(tmp_path, monkeypatch, capsys):
    bundle = _observation_bundle(tmp_path, "SELECT 1 AS geo_id, NULL::VARCHAR AS value_status, 4.2 AS value")
    assert _run(monkeypatch, str(bundle), "--reference", "none") == 1
    assert "  FAIL  value_null_unless_reported  (1 rows)" in capsys.readouterr().out
    assert not (bundle / gate.GATE_FILE).exists()


def test_a_missing_readme_skips_the_readme_checks(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(gate, "README", tmp_path / "nonexistent" / "README.md")
    assert _run(monkeypatch, str(candidate(tmp_path)), "--reference", "none") == 0
    assert "README not found" in capsys.readouterr().out


@pytest.mark.parametrize("ref_rows, rows, code, expect", [
    (0, 5, 0, "  ok    row_count_growth"),
    (1000, 700, 1, "  FAIL  row_count_bounds  (700 rows, reference 1000, bounds (0.8, 3.0))"),
    (1000, 5000, 0, "  warn  row_count_growth  (5000 rows, reference 1000, bounds (0.8, 3.0))"),
])
def test_row_count_bounds_shrink_fails_growth_warns(tmp_path, monkeypatch, capsys, ref_rows, rows, code, expect):
    ref = _bundle(tmp_path / "ref", "2026-10-01", {"geography.unit": GEO.format(n=ref_rows),
                                                   "measure.observation": OBSERVATION.format(value="NULL")})
    bundle = _bundle(tmp_path / "candidate", "2026-11-01", {"geography.unit": GEO.format(n=rows),
                                                            "measure.observation": OBSERVATION.format(value="NULL")})
    assert _run(monkeypatch, str(bundle), "--reference", ref.as_uri()) == code
    assert expect in capsys.readouterr().out


def test_the_reference_is_fetched_with_our_own_user_agent(tmp_path, monkeypatch, capsys):
    """Cloudflare refuses urllib's default User-Agent (HTTP 403, error 1010) on the data host;
    the 2026-11-03 scheduled release failed at the gate because of it."""
    ref = _bundle(tmp_path / "ref", "2026-10-01", {"geography.unit": GEO.format(n=10),
                                                   "measure.observation": OBSERVATION.format(value="NULL")})
    manifest = (ref / "manifest.json").read_bytes()
    agents = []

    def urlopen(req):
        ua = req.get_header("User-agent") if isinstance(req, urllib.request.Request) else None
        agents.append(ua)
        if not ua or ua.startswith("Python-urllib"):
            raise urllib.error.HTTPError(str(req), 403, "error code: 1010", {}, None)
        return io.BytesIO(manifest)

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    bundle = _bundle(tmp_path / "candidate", "2026-11-01", {"geography.unit": GEO.format(n=10),
                                                            "measure.observation": OBSERVATION.format(value="NULL")})
    assert _run(monkeypatch, str(bundle), "--reference", "https://basemap.example/data/latest") == 0
    assert agents == [gate.USER_AGENT]
