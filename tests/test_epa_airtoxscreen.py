"""EPA AirToxScreen: land both national files (source-group + pollutant) for one
assessment year, then derive the flagship total-risk measure plus benzene,
formaldehyde and ethylene oxide -- two real years coexisting, no suppression
anywhere in this source.

Fixtures are real byte-for-byte excerpts of the actual downloaded 2018/2019
national xlsx files (verified 2026-09-19 against epa.gov's real files):
  - tiny_airtoxscreen_<year>_srcgrp.xlsx / _pollutant.xlsx: the national-total row
    (FIPS 00000), the Alabama state row, Autauga County AL's county-aggregate row
    plus two of its real tracts (01001020100, 01001020200), an Alaska tract
    (02050000200, Bethel Census Area) with a genuine zero ethylene-oxide risk, a
    Connecticut tract (09001010101, Fairfield County -- still the legacy county in
    both landed years) and a Puerto Rico tract (72001956300).
"""

from pathlib import Path

import pytest
from pyiceberg.expressions import EqualTo

from cancerbasemap import epa_airtoxscreen as airtox, merge

REL = "2026.08"
FIX = Path(__file__).parent
SRCGRP_2018 = str(FIX / "tiny_airtoxscreen_2018_srcgrp.xlsx")
POLL_2018 = str(FIX / "tiny_airtoxscreen_2018_pollutant.xlsx")
SRCGRP_2019 = str(FIX / "tiny_airtoxscreen_2019_srcgrp.xlsx")
POLL_2019 = str(FIX / "tiny_airtoxscreen_2019_pollutant.xlsx")


def rows(cat, identifier, **kw):
    return cat.load_table(identifier).scan(**kw).to_arrow().to_pylist()


def test_raw_is_verbatim_and_whole_both_files(cat):
    year, n = airtox.land_raw(cat, REL, "2019", "srcgrp", url=SRCGRP_2019)
    assert year == "2019"
    assert n == 11
    year, n = airtox.land_raw(cat, REL, "2019", "pollutant", url=POLL_2019)
    assert year == "2019"
    assert n == 11

    srcgrp = rows(cat, "raw.airtoxscreen__tract_risk")
    assert len(srcgrp) == 11
    assert {r["assessment_year"] for r in srcgrp} == {"2019"}
    assert {r["landed_in"] for r in srcgrp} == {REL}
    # unparsed: the real risk value lands as text, not a number
    autauga = next(r for r in srcgrp if r["tract"] == "01001020100")
    assert autauga["total_cancer_risk"] == "40"
    assert autauga["fips"] == "01001"

    poll = rows(cat, "raw.airtoxscreen__tract_risk_pollutant")
    assert len(poll) == 11
    autauga_poll = next(r for r in poll if r["tract"] == "01001020100")
    assert autauga_poll["benzene"] is not None
    assert autauga_poll["ethylene_oxide"] is not None

    # re-landing the same year replaces it rather than appending
    airtox.land_raw(cat, REL, "2019", "srcgrp", url=SRCGRP_2019)
    assert len(rows(cat, "raw.airtoxscreen__tract_risk")) == 11


def test_a_changed_header_fails_before_landing(cat, tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("not an xlsx file")
    with pytest.raises(Exception):
        airtox.land_raw(cat, REL, "2019", "srcgrp", url=str(bad))


def test_unknown_year_or_kind_rejected(cat):
    with pytest.raises(SystemExit, match="no known layout"):
        airtox.land_raw(cat, REL, "2017", "srcgrp", url=SRCGRP_2019)
    with pytest.raises(SystemExit, match="unknown kind"):
        airtox.land_raw(cat, REL, "2019", "county", url=SRCGRP_2019)


def test_transform_requires_both_files_landed(cat):
    airtox.land_raw(cat, REL, "2019", "srcgrp", url=SRCGRP_2019)
    with pytest.raises(SystemExit, match="must be landed"):
        airtox.transform(cat, REL, "2019")


def test_derives_definitions_stratum_and_observations(cat):
    counts = airtox.ingest(cat, REL, "2019", srcgrp_url=SRCGRP_2019, pollutant_url=POLL_2019)
    assert counts["raw.airtoxscreen__tract_risk"] == 11
    assert counts["raw.airtoxscreen__tract_risk_pollutant"] == 11
    assert counts["measure.observation"]["written"] == 20  # 5 tracts x 4 measures

    defs = {d["measure_id"]: d for d in rows(cat, "measure.definition",
                                             row_filter="source = 'AIRTOXSCREEN'")}
    assert len(defs) == 4
    assert defs["AIRTOXSCREEN:total_cancer_risk"]["rate_basis"] == "per_1000000"
    assert defs["AIRTOXSCREEN:total_cancer_risk"]["method"] == "model_based"
    assert defs["AIRTOXSCREEN:benzene"]["units"] == "chances per million"

    strata = rows(cat, "measure.stratum", row_filter="source = 'AIRTOXSCREEN'")
    assert [s["stratum_id"] for s in strata] == ["AIRTOXSCREEN:ALL"]

    obs = {(r["geo_id"], r["measure_id"]): r
           for r in rows(cat, "measure.observation", row_filter="source = 'AIRTOXSCREEN'")}
    # only the five real tracts appear -- the national/state/county aggregate rows
    # in the fixture are landed to raw but never derived
    tracts = {geo_id for geo_id, _ in obs}
    assert tracts == {"tract:01001020100", "tract:01001020200", "tract:02050000200",
                      "tract:09001010101", "tract:72001956300"}

    total = obs[("tract:01001020100", "AIRTOXSCREEN:total_cancer_risk")]
    assert total["value"] == 40.0
    assert total["value_status"] == "reported"
    assert total["geo_vintage"] == 2010
    assert total["period_start"] == "2019"
    assert total["period_end"] == "2019"
    assert total["source_release"] == "2019"
    assert total["lower"] is None and total["interval_level"] is None

    # SPEC.md Acceptance C sanity check: no suppression exists in this source, but
    # a genuine 0.0 must still read as 'reported', never be mistaken for missing
    # (the same lesson cdc_svi.py/ers_ruca.py had to encode explicitly)
    ak = obs[("tract:02050000200", "AIRTOXSCREEN:ethylene_oxide")]
    assert ak["value"] == 0.0
    assert ak["value_status"] == "reported"

    assert obs[("tract:01001020100", "AIRTOXSCREEN:benzene")]["value"] == pytest.approx(1.470398521279686)
    assert obs[("tract:01001020100", "AIRTOXSCREEN:formaldehyde")]["value"] == pytest.approx(24.63569350805332)


def test_two_years_coexist(cat):
    """measure.observation's merge scope is (source, source_release) -- 2018 must
    not retire 2019's rows or vice versa."""
    airtox.ingest(cat, REL, "2018", srcgrp_url=SRCGRP_2018, pollutant_url=POLL_2018)
    airtox.ingest(cat, REL, "2019", srcgrp_url=SRCGRP_2019, pollutant_url=POLL_2019)

    live = rows(cat, "measure.observation",
               row_filter="source = 'AIRTOXSCREEN' AND valid_to IS NULL")
    releases = {r["source_release"] for r in live}
    assert releases == {"2018", "2019"}
    assert len(live) == 40  # 2 years x 5 tracts x 4 measures

    # measure.definition/stratum are never year-scoped (module docstring: the id
    # set never varies by year) -- still exactly 4 definitions after both years
    defs = rows(cat, "measure.definition", row_filter="source = 'AIRTOXSCREEN'")
    assert len(defs) == 4


def test_rerun_is_idempotent(cat):
    airtox.ingest(cat, REL, "2019", srcgrp_url=SRCGRP_2019, pollutant_url=POLL_2019)
    counts = airtox.ingest(cat, "2026.09", "2019", srcgrp_url=SRCGRP_2019, pollutant_url=POLL_2019)
    assert counts["measure.observation"]["written"] == 0
    assert counts["measure.observation"]["unchanged"] == 20
    assert counts["measure.definition"] == 4
    assert counts["measure.stratum"] == 1


def other_observation():
    return dict(source="OTHER", source_release="V0", measure_id="OTHER:x", geo_id="county:99999",
               geo_vintage=2020, period_start="2020", period_end="2020", stratum_id="OTHER:none",
               value=1.0, lower=None, upper=None, interval_level=None, numerator=None,
               denominator=None, value_status="reported", reliability_flag=None, trend=None)


def test_airtoxscreen_does_not_retire_another_writer(cat):
    import pyarrow as pa
    other = pa.Table.from_pylist([other_observation()])
    merge.merge(cat, "measure.observation", other, REL, EqualTo("source", "OTHER"))

    airtox.ingest(cat, REL, "2019", srcgrp_url=SRCGRP_2019, pollutant_url=POLL_2019)
    airtox.ingest(cat, "2026.09", "2019", srcgrp_url=SRCGRP_2019, pollutant_url=POLL_2019)

    live_other = rows(cat, "measure.observation",
                      row_filter="source = 'OTHER' AND valid_to IS NULL")
    assert len(live_other) == 1
    assert live_other[0]["valid_from"] == REL


def test_every_column_is_documented(cat):
    airtox.ingest(cat, REL, "2019", srcgrp_url=SRCGRP_2019, pollutant_url=POLL_2019)
    for identifier in ("raw.airtoxscreen__tract_risk", "raw.airtoxscreen__tract_risk_pollutant"):
        table = cat.load_table(identifier)
        assert table.properties.get("comment")
        for f in table.schema().fields:
            assert f.doc, f"{identifier}.{f.name} has no doc"
