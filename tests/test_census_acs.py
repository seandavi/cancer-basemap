"""US Census ACS 5-year Summary File -> raw.acs__{county,tract} -> the
Cancer InFocus indicator subset in measure.observation (source='ACS'),
including insurance/Medicaid (#125: B27001, C27007).

The fixtures (tests/tiny_acs/acsdt5y2023-<table>.dat) are real byte-for-byte
excerpts of the downloaded 2023 5-year table-based Summary File, one file per
detailed table, for six real geographies chosen for their edge cases:
  - county:01001 (Autauga, AL) and county:08031 (Denver, CO) -- plain rows.
  - county:09110 (Connecticut's Capitol Planning Region) -- the 2022+
    Connecticut geography, confirming geo_vintage = 2020.
  - county:32009 (Esmeralda, NV, population ~962) -- B19013's real
    -666666666/-222222222 estimate-not-computed sentinel.
  - tract:08001988700 and tract:08005005636 (real Colorado tracts) -- the
    former has B19013 -666666666/-222222222 too; the latter has the real
    median-in-open-interval case, B19013_E001=250001 (the artificial upper
    boundary) with B19013_M001=-333333333.
Every other table's B01003_M001 is -555555555 for nearly every county in the
real data (population totals are "controlled" estimates with no sampling
error, per the Census Bureau's own MOE documentation) -- exercised here as
the ubiquitous "value stays reported, interval unavailable" case.
"""

from pathlib import Path

import pytest

from cancerbasemap import census_acs

REL = "2026.09"
DAT_DIR = str(Path(__file__).parent / "tiny_acs")


def rows(cat, identifier, **kw):
    return cat.load_table(identifier).scan(**kw).to_arrow().to_pylist()


def test_raw_county_is_verbatim_and_whole(cat):
    year, n = census_acs.land_raw(cat, REL, 2023, "county", dat_dir=DAT_DIR)
    assert year == 2023
    assert n == 4  # 01001, 08031, 09110, 32009 -- the tract rows are filtered out

    raw = rows(cat, "raw.acs__county")
    assert len(raw) == 4
    assert {r["geo_id"] for r in raw} == {"county:01001", "county:08031",
                                          "county:09110", "county:32009"}
    assert {r["acs_year"] for r in raw} == {2023}
    assert {r["landed_in"] for r in raw} == {REL}
    row = next(r for r in raw if r["geo_id"] == "county:01001")
    assert row["B01003_E001"] == "59285"  # unparsed string, verbatim
    assert row["B19013_E001"] == "69841"

    # re-landing the same year replaces it rather than appending
    census_acs.land_raw(cat, REL, 2023, "county", dat_dir=DAT_DIR)
    assert len(rows(cat, "raw.acs__county")) == 4


def test_raw_tract_filters_to_tract_rows(cat):
    year, n = census_acs.land_raw(cat, REL, 2023, "tract", dat_dir=DAT_DIR)
    assert n == 2
    raw = rows(cat, "raw.acs__tract")
    assert {r["geo_id"] for r in raw} == {"tract:08001988700", "tract:08005005636"}


def test_county_and_tract_share_a_release_without_retiring_each_other(cat):
    """County and tract land into separate raw tables but derive into the
    SAME measure.observation scope (source='ACS', source_release='2019-2023')
    -- transform() must rebuild from both raw tables every time it runs, or
    landing the second level makes `incoming` look like an incomplete state
    for that scope and merge.merge retires the first level's rows (caught in
    this PR's own real nationwide ingest: landing tract after county silently
    deleted every county observation for the release)."""
    census_acs.ingest(cat, REL, 2023, "county", dat_dir=DAT_DIR)
    census_acs.ingest(cat, REL, 2023, "tract", dat_dir=DAT_DIR)

    live = rows(cat, "measure.observation",
               row_filter="source = 'ACS' AND source_release = '2019-2023' AND valid_to IS NULL")
    county_rows = [r for r in live if r["geo_id"].startswith("county:")]
    tract_rows = [r for r in live if r["geo_id"].startswith("tract:")]
    assert len(county_rows) == 4 * 23
    assert len(tract_rows) == 2 * 23

    # re-landing county alone afterwards must not retire the tract rows either
    census_acs.ingest(cat, "2026.10", 2023, "county", dat_dir=DAT_DIR)
    live = rows(cat, "measure.observation",
               row_filter="source = 'ACS' AND source_release = '2019-2023' AND valid_to IS NULL")
    assert len([r for r in live if r["geo_id"].startswith("tract:")]) == 2 * 23


def test_a_changed_header_fails_before_landing(cat, tmp_path):
    (tmp_path / "acsdt5y2023-b01003.dat").write_text("GEO_ID|B01003_E001\n0500000US01001|59285\n")
    for table_id, n in census_acs.TABLE_VARS.items():
        if table_id == "B01003":
            continue
        src = Path(DAT_DIR) / f"acsdt5y2023-{table_id.lower()}.dat"
        (tmp_path / src.name).write_bytes(src.read_bytes())
    with pytest.raises(SystemExit, match="B01003"):
        census_acs.land_raw(cat, REL, 2023, "county", dat_dir=str(tmp_path))


def test_derives_definition_stratum_and_observations(cat):
    counts = census_acs.ingest(cat, REL, 2023, "county", dat_dir=DAT_DIR)
    assert counts["raw.acs__county"] == 4

    defs = {d["measure_id"]: d for d in rows(cat, "measure.definition", row_filter="source = 'ACS'")}
    assert len(defs) == 17  # 15 unstratified + age_distribution + race_ethnicity
    assert defs["ACS:gini_index"]["rate_basis"] == "index"
    assert defs["ACS:total_population"]["method"] == "survey_direct"
    assert "18-64" in defs["ACS:age_distribution"]["doc"] or "residual" in defs["ACS:age_distribution"]["doc"]

    strata = {s["stratum_id"] for s in rows(cat, "measure.stratum", row_filter="source = 'ACS'")}
    assert strata == {"ACS:ALL", "ACS:age:under_18", "ACS:age:age_18_64", "ACS:age:age_65_plus",
                      "ACS:race:hispanic", "ACS:race:nh_white", "ACS:race:nh_black",
                      "ACS:race:nh_asian", "ACS:race:other"}

    obs = rows(cat, "measure.observation", row_filter="source = 'ACS'")
    assert len(obs) == 4 * 23  # 4 counties x 23 (measure_id, stratum_id) rows
    by_geo_measure = {(r["geo_id"], r["measure_id"], r["stratum_id"]): r for r in obs}

    autauga = by_geo_measure[("county:01001", "ACS:total_population", "ACS:ALL")]
    assert autauga["value"] == 59285.0
    assert autauga["value_status"] == "reported"
    assert autauga["geo_vintage"] == 2020
    assert autauga["source_release"] == "2019-2023"
    assert autauga["period_start"] == "2019" and autauga["period_end"] == "2023"
    # B01003_M001 = -555555555 (controlled estimate) for every real county here:
    # value stays reported, the interval is unavailable -- never dropped, never zeroed.
    assert autauga["lower"] is None and autauga["upper"] is None and autauga["interval_level"] is None

    # #125: insurance/Medicaid, composed the same way as every other rate --
    # 4,268 of 57,953 (B27001) uninsured, 9,518 of 57,953 (C27007) on Medicaid.
    autauga_uninsured = by_geo_measure[("county:01001", "ACS:uninsured", "ACS:ALL")]
    assert autauga_uninsured["value"] == pytest.approx(100.0 * 4268 / 57953)
    assert autauga_uninsured["value_status"] == "reported"
    assert autauga_uninsured["numerator"] == 4268.0
    assert autauga_uninsured["denominator"] == 57953.0

    autauga_medicaid = by_geo_measure[("county:01001", "ACS:medicaid_coverage", "ACS:ALL")]
    assert autauga_medicaid["value"] == pytest.approx(100.0 * 9518 / 57953)
    assert autauga_medicaid["value_status"] == "reported"

    # Connecticut's 2022 planning region lands fine, same vintage
    assert by_geo_measure[("county:09110", "ACS:total_population", "ACS:ALL")]["geo_vintage"] == 2020

    # Esmeralda NV: B19013 is -666666666/-222222222 -- suppressed, never a number
    esmeralda_income = by_geo_measure[("county:32009", "ACS:median_household_income", "ACS:ALL")]
    assert esmeralda_income["value"] is None
    assert esmeralda_income["value_status"] == "suppressed_small_count"

    # a real income value combines with a real MOE into a genuine interval
    denver_income = by_geo_measure[("county:08031", "ACS:median_household_income", "ACS:ALL")]
    assert denver_income["value"] == 91681.0
    assert denver_income["lower"] == pytest.approx(91681.0 - 1359.0)
    assert denver_income["upper"] == pytest.approx(91681.0 + 1359.0)
    assert denver_income["interval_level"] == 0.90

    # age distribution: under-18 and 65+ are direct ACS proportions; 18-64 is
    # the derived residual, and the three strata sum close to 100%
    age = {r["stratum_id"]: r for r in obs
          if r["geo_id"] == "county:08031" and r["measure_id"] == "ACS:age_distribution"}
    total_pct = sum(r["value"] for r in age.values())
    assert total_pct == pytest.approx(100.0, abs=0.5)
    assert age["ACS:age:under_18"]["numerator"] is not None
    assert age["ACS:age:age_18_64"]["numerator"] is not None


def test_median_in_open_interval_is_not_available(cat):
    """B19013 pins the estimate to an artificial boundary ($250,001) with MOE
    -333333333 when the true median falls above the table's top bracket --
    not a real reported value (module docstring's median-specific rule)."""
    census_acs.ingest(cat, REL, 2023, "tract", dat_dir=DAT_DIR)
    obs = {r["geo_id"]: r for r in rows(cat, "measure.observation",
                                        row_filter="source = 'ACS' AND measure_id = 'ACS:median_household_income'")}
    open_interval_tract = obs["tract:08005005636"]
    assert open_interval_tract["value"] is None
    assert open_interval_tract["value_status"] == "not_available"
    assert open_interval_tract["lower"] is None and open_interval_tract["upper"] is None

    suppressed_tract = obs["tract:08001988700"]
    assert suppressed_tract["value"] is None
    assert suppressed_tract["value_status"] == "suppressed_small_count"


def test_rerun_is_idempotent(cat):
    census_acs.ingest(cat, REL, 2023, "county", dat_dir=DAT_DIR)
    counts = census_acs.ingest(cat, "2026.10", 2023, "county", dat_dir=DAT_DIR)
    assert counts["measure.observation"]["written"] == 0
    assert counts["measure.observation"]["unchanged"] == 4 * 23


def test_second_release_does_not_retire_the_first(cat):
    """measure.observation's merge scope is (source, source_release) -- a new
    ACS release must never retire another release's rows (SPEC.md § Measures)."""
    census_acs.ingest(cat, REL, 2023, "county", dat_dir=DAT_DIR)
    census_acs.ingest(cat, REL, 2021, "county", dat_dir=DAT_DIR)

    live_2023 = rows(cat, "measure.observation",
                     row_filter="source = 'ACS' AND source_release = '2019-2023' AND valid_to IS NULL")
    live_2021 = rows(cat, "measure.observation",
                     row_filter="source = 'ACS' AND source_release = '2017-2021' AND valid_to IS NULL")
    assert len(live_2023) == 4 * 23
    assert len(live_2021) == 4 * 23


def test_every_column_is_documented(cat):
    census_acs.ingest(cat, REL, 2023, "county", dat_dir=DAT_DIR)
    table = cat.load_table("raw.acs__county")
    assert table.properties.get("comment")
    for f in table.schema().fields:
        assert f.doc, f"raw.acs__county.{f.name} has no doc"
