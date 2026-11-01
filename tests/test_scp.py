"""State Cancer Profiles: land three vintages' real column layouts whole ->
derive incidence/mortality into one combined measure.observation write per
vintage (module docstring on why it must be combined, not per-topic).

Fixtures are real byte-for-byte excerpts of the actual Zenodo deposits
(downloaded and verified 2026-09-18; `scp.VINTAGES` for the DOIs):
- tiny_scp_v1_incidence.csv / tiny_scp_v1_mortality.csv: a real Denver County,
  CO "Colon & Rectum" row (both topics) and the national "All Cancer Sites"
  aggregate row (incidence only) -- V1's 27/28-column layout, no suppression
  marker at all (V1 carries none, module docstring).
- tiny_scp_v2_incidence.csv / tiny_scp_v2_mortality.csv: the same Denver row
  from V2, proving the "2023_rural_urban..." column landed and the two
  vintages coexist without either retiring the other.
- tiny_scp_v3_incidence.csv: a reported Denver row; a real
  `suppression_reason='suppressed_small_count'` row (Aleutians East Borough,
  AK); a real `suppression_reason='withheld_state_law'` / `recent_trend='[P1
  note]'` row (Allen County, KS); a real by-state row (Kentucky, fips
  '21000'); a real Connecticut row (legacy county 09003, not a 2022 planning
  region); a real South Dakota row (46102 Oglala Lakota, the 2015 rename
  already in place); a real Alaska row (02261 Valdez-Cordova, the pre-2019
  code) -- together the geo_vintage=2010 evidence (module docstring).
- tiny_scp_v3_mortality.csv: a reported Denver row (no `stage` column at all
  -- V3 dropped it) and a real suppressed Aleutians East Borough row
  (`lower_ci_rate`/`upper_ci_rate` literally '*').
- tiny_scp_v3_risk.csv: a real national row (screening & risk factors,
  landed but not derived -- module docstring).
- tiny_scp_v3_incidence_malformed.csv: SYNTHETIC, not a real excerpt -- a
  present `age_adjusted_rate_per_100_000` cell ('N/A') with no
  `suppression_reason`, to exercise #148's guard. The real V1/V2/V3 files
  have never published this combination (verified 2026-09-18: `rate IS NULL
  AND suppression_reason IS NULL` is 0 rows in every landed file).
"""

from pathlib import Path

import pytest
from pyiceberg.expressions import EqualTo

from cancerbasemap import cancer_site, catalog, scp

FIX = Path(__file__).parent
V1_INC, V1_MORT = str(FIX / "tiny_scp_v1_incidence.csv"), str(FIX / "tiny_scp_v1_mortality.csv")
V2_INC, V2_MORT = str(FIX / "tiny_scp_v2_incidence.csv"), str(FIX / "tiny_scp_v2_mortality.csv")
V3_INC, V3_MORT = str(FIX / "tiny_scp_v3_incidence.csv"), str(FIX / "tiny_scp_v3_mortality.csv")
V3_RISK = str(FIX / "tiny_scp_v3_risk.csv")
V3_INC_MALFORMED = str(FIX / "tiny_scp_v3_incidence_malformed.csv")
REL = "2026.09"


@pytest.fixture
def cat(tmp_path, monkeypatch):
    monkeypatch.setenv("CANCERBASEMAP_WAREHOUSE", str(tmp_path))
    monkeypatch.delenv("CANCERBASEMAP_URI", raising=False)
    return catalog()


def rows(cat, identifier, **kw):
    return cat.load_table(identifier).scan(**kw).to_arrow().to_pylist()


def test_v1_lands_raw_verbatim_with_no_suppression_marker(cat):
    vintage, counts = scp.land_raw(cat, REL, vintage="V1", incidence_url=V1_INC,
                                   mortality_url=V1_MORT)
    assert vintage == "V1"
    assert counts == {"raw.scp__incidence": 2, "raw.scp__mortality": 1}

    inc = rows(cat, "raw.scp__incidence")
    assert len(inc) == 2
    denver = next(r for r in inc if r["fips"] == "08031")
    assert denver["cancer"] == "Colon & Rectum" and denver["scp_vintage"] == "V1"
    # V1 has no rural/urban or suppression_reason column at all -- NULL-filled.
    assert denver["2023_rural_urban_continuum_codesrural_urban_note"] is None
    assert denver["suppression_reason"] is None
    # V1 genuinely has no suppressed rows (module docstring) -- confirmed on the
    # real full files; this fixture's two rows are both fully populated.
    assert all(r["age_adjusted_rate_per_100_000"] is not None for r in inc)


def test_v3_incidence_header_mismatch_fails_before_landing(cat, tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text(",".join(c for c in scp.INCIDENCE_COLUMNS["V3"]
                            if c != "suppression_reason") + "\n")
    with pytest.raises(SystemExit, match="header is not the declared V3 incidence layout"):
        scp.land_raw(cat, REL, vintage="V3", incidence_url=str(bad), mortality_url=V3_MORT,
                    risk_url=V3_RISK)


def test_unknown_vintage_fails(cat):
    with pytest.raises(SystemExit, match="V9"):
        scp.land_raw(cat, REL, vintage="V9")


def test_transform_refuses_a_vintage_with_no_evidenced_period(cat):
    scp.land_raw(cat, REL, vintage="V1", incidence_url=V1_INC, mortality_url=V1_MORT)
    with pytest.raises(SystemExit, match="no evidenced period_start/period_end"):
        scp.transform(cat, REL, "V1")


def test_v3_derives_definitions_stratum_and_combined_observation(cat):
    counts = scp.ingest(cat, REL, vintage="V3", incidence_url=V3_INC,
                        mortality_url=V3_MORT, risk_url=V3_RISK)
    assert counts["raw.scp__incidence"] == 7 and counts["raw.scp__mortality"] == 2
    assert counts["raw.scp__risk"] == 1
    # risk lands but is not derived (module docstring) -- no measure.observation
    # rows with source_release='V3' come from it; only incidence+mortality do.
    assert counts["measure.observation"]["written"] == 9

    obs = {(o["measure_id"], o["geo_id"]): o
          for o in rows(cat, "measure.observation", row_filter=EqualTo("source", "SCP"))}
    denver_inc = obs[("SCP:incidence:020", "county:08031")]
    assert denver_inc["value"] == 32.5 and denver_inc["value_status"] == "reported"
    assert denver_inc["period_start"] == "2018" and denver_inc["period_end"] == "2022"
    assert denver_inc["geo_vintage"] == 2010 and denver_inc["interval_level"] == 0.95
    assert denver_inc["numerator"] == 220.0 and denver_inc["trend"] == "falling"

    denver_mort = obs[("SCP:mortality:001", "county:08031")]
    assert denver_mort["value"] == 133.7 and denver_mort["period_start"] == "2019"
    assert denver_mort["period_end"] == "2023"

    ky = obs[("SCP:incidence:001", "state:21")]
    assert ky["geo_id"] == "state:21" and ky["value"] == 519.0

    ct = obs[("SCP:incidence:020", "county:09003")]
    assert ct["geo_id"] == "county:09003"  # legacy county, not a 2022 planning region

    sd = obs[("SCP:incidence:020", "county:46102")]
    assert sd["geo_id"] == "county:46102"  # 2015 rename already in place

    ak = obs[("SCP:incidence:001", "county:02261")]
    assert ak["geo_id"] == "county:02261"  # pre-2019 code, not the post-split areas


def test_suppression_sentinels_map_to_value_status_never_a_number(cat):
    scp.ingest(cat, REL, vintage="V3", incidence_url=V3_INC, mortality_url=V3_MORT,
              risk_url=V3_RISK)
    obs = rows(cat, "measure.observation", row_filter=EqualTo("source_release", "V3"))

    small_count = next(o for o in obs if o["geo_id"] == "county:02013"
                       and o["measure_id"] == "SCP:incidence:001")
    assert small_count["value_status"] == "suppressed_small_count"
    assert small_count["value"] is None and small_count["lower"] is None
    assert small_count["numerator"] is None  # average_annual_count is '*', TRY_CAST -> NULL

    withheld = next(o for o in obs if o["geo_id"] == "county:20001")
    assert withheld["value_status"] == "not_available"
    assert withheld["value"] is None and withheld["trend"] is None  # '[P1 note]' -> NULL

    mort_suppressed = next(o for o in rows(cat, "measure.observation",
                                           row_filter=EqualTo("source", "SCP"))
                           if o["measure_id"] == "SCP:mortality:001"
                           and o["geo_id"] == "county:02013")
    assert mort_suppressed["value_status"] == "suppressed_small_count"
    assert mort_suppressed["value"] is None and mort_suppressed["lower"] is None

    reported = [o for o in obs if o["value_status"] == "reported"]
    assert all(o["value"] is not None for o in reported)


def test_a_present_non_numeric_rate_lands_not_available_not_reported(cat):
    """A rate cell that is present but doesn't parse as a number, with no
    known `suppression_reason`, must not read as a numberless 'reported' row
    (#148): value_status used to be derived from `suppression_reason IS NULL`
    alone, independent of whether `TRY_CAST(age_adjusted_rate_per_100_000 AS
    DOUBLE)` actually produced `value` -- the same class of bug already fixed
    in ers_rucc.py. Synthetic fixture; the real files have never published
    this combination (module docstring)."""
    scp.ingest(cat, REL, vintage="V3", incidence_url=V3_INC_MALFORMED,
              mortality_url=V3_MORT, risk_url=V3_RISK)
    obs = rows(cat, "measure.observation", row_filter=EqualTo("source_release", "V3"))
    boulder = next(o for o in obs if o["geo_id"] == "county:08013")
    assert boulder["value"] is None
    assert boulder["value_status"] == "not_available"


def test_unmapped_suppression_reason_raises(cat, monkeypatch):
    scp.land_raw(cat, REL, vintage="V3", incidence_url=V3_INC, mortality_url=V3_MORT,
                risk_url=V3_RISK)
    monkeypatch.setattr(scp, "SUPPRESSION_STATUS", {})
    with pytest.raises(SystemExit, match="unknown suppression_reason"):
        scp.transform(cat, REL, "V3")


def test_unmapped_cancer_category_raises(cat, monkeypatch):
    scp.land_raw(cat, REL, vintage="V3", incidence_url=V3_INC, mortality_url=V3_MORT,
                risk_url=V3_RISK)
    monkeypatch.setattr(scp, "CANCER_CODES", {})
    with pytest.raises(SystemExit, match="unknown cancer"):
        scp.transform(cat, REL, "V3")


def test_cancer_site_code_resolves_from_the_curated_bridge(cat):
    # _cancer_site_codes() reads cancer_site.py's curated CSV directly (module
    # docstring) -- the FK resolves whether or not #31 has been ingested into
    # this particular warehouse; landing it here just confirms the resolved
    # code is a real, live measure.cancer_site row too.
    cancer_site.ingest(cat, REL)
    scp.ingest(cat, "2026.10", vintage="V3", incidence_url=V3_INC, mortality_url=V3_MORT,
              risk_url=V3_RISK)
    defs = {d["measure_id"]: d for d in rows(cat, "measure.definition")}
    assert defs["SCP:incidence:020"]["cancer_site_code"] == "21041"  # Colon & Rectum
    assert defs["SCP:incidence:001"]["cancer_site_code"] is None  # All Cancer Sites -- no code


def test_two_vintages_coexist_and_neither_retires_the_other(cat):
    scp.land_raw(cat, "2026.08", vintage="V2", incidence_url=V2_INC, mortality_url=V2_MORT)
    scp.ingest(cat, REL, vintage="V3", incidence_url=V3_INC, mortality_url=V3_MORT,
              risk_url=V3_RISK)

    # V2 only lands (no evidenced period, module docstring) -- raw is preserved.
    v2 = rows(cat, "raw.scp__incidence", row_filter=EqualTo("scp_vintage", "V2"))
    assert len(v2) == 1 and v2[0]["cancer"] == "Colon & Rectum"

    v3_denver = next(o for o in rows(cat, "measure.observation")
                     if o["measure_id"] == "SCP:incidence:020" and o["geo_id"] == "county:08031")
    assert v3_denver["source_release"] == "V3" and v3_denver["valid_to"] is None


def test_rerun_is_idempotent(cat):
    scp.ingest(cat, REL, vintage="V3", incidence_url=V3_INC, mortality_url=V3_MORT,
              risk_url=V3_RISK)
    counts = scp.ingest(cat, "2026.10", vintage="V3", incidence_url=V3_INC,
                        mortality_url=V3_MORT, risk_url=V3_RISK)
    assert counts["measure.observation"]["written"] == 0
    assert counts["measure.observation"]["unchanged"] == 9


def test_every_column_is_documented(cat):
    scp.ingest(cat, REL, vintage="V3", incidence_url=V3_INC, mortality_url=V3_MORT,
              risk_url=V3_RISK)
    for identifier in ("raw.scp__incidence", "raw.scp__mortality", "raw.scp__risk",
                      "measure.definition", "measure.stratum", "measure.observation"):
        table = cat.load_table(identifier)
        assert table.properties.get("comment"), identifier
        for f in table.schema().fields:
            assert f.doc, f"{identifier}.{f.name} has no doc"
