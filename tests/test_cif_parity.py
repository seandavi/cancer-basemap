"""Offline check for recipes/cif_parity.py's join/comparison logic. No real
Cancer InFocus data is used anywhere here -- tests/tiny_cif_dir/*.csv is a
synthetic fixture this test invents (values and geographies made up), and the
lake side is a local in-memory stub of the `cbm` schema instead of a real
ATTACH, following tests/test_clients_examples.py's pattern.
"""
import importlib.util
from pathlib import Path

import duckdb
import pytest

REPO_ROOT = Path(__file__).parent.parent
CIF_DIR = str(Path(__file__).parent / "tiny_cif_dir")

spec = importlib.util.spec_from_file_location("cif_parity", REPO_ROOT / "recipes/cif_parity.py")
cif_parity = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cif_parity)


@pytest.fixture
def con():
    con = duckdb.connect()
    con.execute("ATTACH ':memory:' AS cbm")
    con.execute("""
        CREATE SCHEMA cbm.geography;
        CREATE TABLE cbm.geography.unit (geo_id VARCHAR, level VARCHAR, fips VARCHAR);
        INSERT INTO cbm.geography.unit VALUES
            ('county:08001', 'county', '08001'),
            ('county:08003', 'county', '08003'),
            ('tract:08001960100', 'tract', '08001960100'),
            ('tract:08001960200', 'tract', '08001960200'),
            ('tract:08001960300', 'tract', '08001960300');

        CREATE SCHEMA cbm.measure;
        CREATE TABLE cbm.measure.observation (
            geo_id VARCHAR, source VARCHAR, source_release VARCHAR,
            measure_id VARCHAR, value DOUBLE);
        INSERT INTO cbm.measure.observation VALUES
            -- PLACES: one exact match, one deliberate mismatch, one lake-only
            ('county:08001', 'PLACES', '2024', 'PLACES:CANCER:crude', 6.5),
            ('county:08001', 'PLACES', '2024', 'PLACES:CSMOKING:crude', 21.0),
            ('county:08003', 'PLACES', '2024', 'PLACES:CANCER:crude', 7.0),
            ('county:08003', 'PLACES', '2024', 'PLACES:OBESITY:crude', 30.0),
            -- SVI: both exact
            ('county:08001', 'SVI', '2022', 'SVI:RPL_THEME1:2020', 0.55),
            ('county:08001', 'SVI', '2022', 'SVI:RPL_THEMES:2020', 0.60),
            -- FARA: one exact, one mismatch, one lake-only
            ('tract:08001960100', 'FARA', '2019', 'FARA:LILATracts_Vehicle', 1),
            ('tract:08001960200', 'FARA', '2019', 'FARA:LILATracts_Vehicle', 1),
            ('tract:08001960300', 'FARA', '2019', 'FARA:LILATracts_Vehicle', 1),
            -- RUCC: one exact, one mismatch
            ('county:08001', 'RUCC', '2023', 'RUCC:code', 1),
            ('county:08003', 'RUCC', '2023', 'RUCC:code', 4),
            -- RUCA: primary exact, secondary mismatch
            ('tract:08001960100', 'RUCA', '2020', 'RUCA:primary', 1),
            ('tract:08001960100', 'RUCA', '2020', 'RUCA:secondary', 2);

        CREATE SCHEMA cbm.facility;
        CREATE TABLE cbm.facility.site (geo_id VARCHAR, kind VARCHAR, attributes_json VARCHAR);
        INSERT INTO cbm.facility.site VALUES
            ('county:08001', 'fqhc', NULL),
            ('county:08001', 'fqhc', NULL),
            ('county:08003', 'fqhc', NULL),
            (NULL, 'mammography', '{"state":"CO"}'),
            (NULL, 'mammography', '{"state":"CO"}');
    """)
    con.execute(cif_parity.GEO_FIPS_VIEW_SQL)
    return con


def test_places_exact_match_and_flagged_mismatch(con):
    r = cif_parity.compare_places(con, CIF_DIR, ["08"])
    assert r["n_compared"] == 3
    # 08003/CANCER: 0.07*100 == 7.000000000000001 in float -- the same
    # 1e-14 rounding noise the real CIF diff saw (REPORT.md), so it lands
    # in n_within_rounding rather than n_exact; both are "matches".
    assert r["n_exact"] + r["n_within_rounding"] == 2
    assert r["n_different"] == 1
    assert r["max_abs_diff"] == 1.0
    assert r["n_lake_only"] == 1  # OBESITY: lake carries topics CIF doesn't
    assert r["n_cif_only"] == 0


def test_svi_perfect_match(con):
    r = cif_parity.compare_svi(con, CIF_DIR, ["08"])
    assert r["n_compared"] == 2
    assert r["n_exact"] == 2
    assert r["n_different"] == 0


def test_fara_tract_vintage_mismatch_pattern(con):
    r = cif_parity.compare_fara(con, CIF_DIR, ["08"])
    assert r["n_compared"] == 2
    assert r["n_exact"] == 1
    assert r["n_different"] == 1
    assert r["n_cif_only"] == 1  # 08001960400: CIF-only tract
    assert r["n_lake_only"] == 1  # 08001960300: lake-only tract


def test_rucc_county(con):
    r = cif_parity.compare_rucc(con, CIF_DIR, ["08"])
    assert r["n_compared"] == 2
    assert r["n_exact"] == 1
    assert r["n_different"] == 1
    assert r["max_abs_diff"] == 1.0


def test_ruca_tract_primary_and_secondary(con):
    r = cif_parity.compare_ruca(con, CIF_DIR, ["08"])
    assert r["n_compared"] == 2
    assert r["n_exact"] == 1
    assert r["n_different"] == 1


def test_facilities_counts_by_state(con):
    r = cif_parity.compare_facilities(con, CIF_DIR, ["08"], "FQHC", "fqhc", "FQHC sites")
    assert r["cif_counts_by_state"] == [("CO", 3)]
    assert r["lake_counts_by_state"] == [("CO", 3)]

    r = cif_parity.compare_facilities(con, CIF_DIR, ["08"], "Mammography", "mammography", "Mammo")
    assert r["cif_counts_by_state"] == [("CO", 2)]
    assert r["lake_counts_by_state"] == [("CO", 2)]  # attributes_json fallback for NULL geo_id


def test_run_covers_every_comparison_without_crashing(con):
    results = cif_parity.run(con, CIF_DIR, ["08"])
    labels = [r["label"] for r in results]
    assert len(results) == 7  # 5 measure comparisons + 2 facility comparisons
    assert not any("error" in r for r in results), [r for r in results if "error" in r]
    assert "FQHC sites" in labels
    assert "Mammography facilities" in labels
