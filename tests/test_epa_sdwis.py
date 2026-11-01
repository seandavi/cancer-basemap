"""EPA SDWIS Federal: land four SDWA files whole -> derive county-year counts
of health-based drinking-water violations.

Fixtures (tests/tiny_epa_sdwis_*.csv) are real byte-for-byte excerpts of the
2026Q2 ECHO SDWA bulk download, covering:
  - PA4340323 / Juniata County, PA (42067): a health-based violation
    (1817206) with 7 real duplicate enforcement-action rows in 2018 -- the
    dedup case (must count as 1 violation, not 7).
  - CT1680051 / Litchfield County, CT (09005): a health-based violation
    (53308, also duplicated across enforcement rows) begun in 2009 -- before
    2016, the year-range case. Also carries a non-county (AREA_TYPE_CODE='CT',
    city) row for the same PWSID.
  - MI2293063 / Oakland County, MI (26125): a violation (1) that is NOT
    health-based (IS_HEALTH_BASED_IND='N') -- the health-flag case.
  - NJ1219304: a county-served row whose real ANSI_ENTITY_CODE ('012') does
    not correspond to any real New Jersey county -- the unmatched-geography
    case (verified against the real SDWA_REF_ANSI_AREAS.csv: no NJ row has
    entity code '012'). Also carries a non-county (city) row.
  - 010502002: two real enforcement-only rows with VIOLATION_ID NULL.
  - 070000002: a health-based violation (11830) begun in 2026 -- the
    extract's own (incomplete) year, excluded like the pre-2016 case.

Only PA4340323's violation survives every filter, so the derived measure
should hold exactly one row: county:42067, 2018, value=1.
"""

from pathlib import Path

import pytest
from pyiceberg.expressions import EqualTo

from cancerbasemap import epa_sdwis

REL = "2026.09"
DIR = Path(__file__).parent
URLS = dict(
    pws_url=str(DIR / "tiny_epa_sdwis_pub_water_systems.csv"),
    geo_url=str(DIR / "tiny_epa_sdwis_geographic_areas.csv"),
    viol_url=str(DIR / "tiny_epa_sdwis_violations_enforcement.csv"),
    ansi_url=str(DIR / "tiny_epa_sdwis_ref_ansi_areas.csv"),
)


def rows(cat, identifier, **kw):
    return cat.load_table(identifier).scan(**kw).to_arrow().to_pylist()


def test_raw_is_verbatim_and_whole(cat):
    quarter, n = epa_sdwis.land_raw(cat, REL, **URLS)
    assert quarter == "2026Q2"
    assert n == {
        "raw.sdwis__pub_water_systems": 4,
        "raw.sdwis__geographic_areas": 6,
        "raw.sdwis__ref_ansi_areas": 6,
        "raw.sdwis__violations_enforcement": 19,
    }

    pws = rows(cat, "raw.sdwis__pub_water_systems")
    assert len(pws) == 4
    assert {r["PWSID"] for r in pws} == {"PA4340323", "CT1680051", "MI2293063", "NJ1219304"}
    assert {r["landed_in"] for r in pws} == {REL}
    # A real sole-proprietor row (its real ORG_NAME/ADMIN_NAME was "KLINGMAN,
    # KEN", its real ADDRESS_LINE1 a street address): PWS_NAME kept, all nine
    # individual columns gone.
    woodbury = next(r for r in pws if r["PWSID"] == "CT1680051")
    assert woodbury["PWS_NAME"] == "WOODBURY KNOLL, LLC."
    for excluded in ("ORG_NAME", "ADMIN_NAME", "EMAIL_ADDR", "PHONE_NUMBER",
                     "PHONE_EXT_NUMBER", "FAX_NUMBER", "ALT_PHONE_NUMBER",
                     "ADDRESS_LINE1", "ADDRESS_LINE2"):
        assert excluded not in woodbury

    viol = rows(cat, "raw.sdwis__violations_enforcement")
    assert len(viol) == 19
    assert sum(1 for r in viol if r["VIOLATION_ID"] is None) == 2

    # Re-landing the same quarter replaces it rather than appending.
    epa_sdwis.land_raw(cat, REL, **URLS)
    assert len(rows(cat, "raw.sdwis__pub_water_systems")) == 4
    assert len(rows(cat, "raw.sdwis__violations_enforcement")) == 19


def test_a_changed_header_fails_before_landing(cat, tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text('"SUBMISSIONYEARQUARTER","PWSID"\n"2026Q2","X0000001"\n')
    bad_urls = {**URLS, "pws_url": str(bad)}
    with pytest.raises(SystemExit, match="pub_water_systems"):
        epa_sdwis.land_raw(cat, REL, **bad_urls)


def test_derives_county_year_violation_counts(cat, capsys):
    counts = epa_sdwis.ingest(cat, REL, **URLS)
    assert counts["raw.sdwis__violations_enforcement"] == 19

    defs = rows(cat, "measure.definition")
    assert len(defs) == 1
    assert (defs[0]["measure_id"], defs[0]["source"], defs[0]["rate_basis"], defs[0]["method"]) == (
        "SDWIS:violations_health_based", "SDWIS", "count", "derived")

    strata = rows(cat, "measure.stratum")
    assert len(strata) == 1
    assert (strata[0]["stratum_id"], strata[0]["scheme"]) == ("SDWIS:none", "SDWIS_NONE")

    obs = rows(cat, "measure.observation", row_filter="source = 'SDWIS'")
    # Every other candidate violation is filtered out: CT1680051/53308 (2009,
    # before 2016), MI2293063/1 (not health-based), 070000002/11830 (2026,
    # the extract's own incomplete year), the two NULL-VIOLATION_ID rows, and
    # NJ1219304 (its only CN row's ANSI_ENTITY_CODE does not resolve). Only
    # PA4340323/1817206 (2018, deduped from 7 rows to 1 violation) survives.
    assert len(obs) == 1
    o = obs[0]
    assert o["geo_id"] == "county:42067"
    assert o["geo_vintage"] == 2010
    assert o["period_start"] == o["period_end"] == "2018"
    assert o["value"] == 1.0
    assert o["value_status"] == "reported"
    assert o["source_release"] == "2026Q2"

    # The unmatched geography (NJ1219304's bad ANSI_ENTITY_CODE) is reported,
    # not silently dropped: 1 of the 4 real CN rows (CT, MI, NJ, PA) fails to
    # resolve.
    out = capsys.readouterr().out
    assert "1/4" in out and "25.0%" in out


def test_rerun_is_idempotent(cat):
    epa_sdwis.ingest(cat, REL, **URLS)
    counts = epa_sdwis.ingest(cat, "2026.10", **URLS)
    assert counts["measure.observation"]["written"] == 0
    assert counts["measure.observation"]["unchanged"] == 1
    assert counts["measure.definition"] == 1
    assert counts["measure.stratum"] == 1


def test_every_column_is_documented(cat):
    epa_sdwis.ingest(cat, REL, **URLS)
    for identifier in ("raw.sdwis__pub_water_systems", "raw.sdwis__geographic_areas",
                       "raw.sdwis__violations_enforcement", "raw.sdwis__ref_ansi_areas"):
        table = cat.load_table(identifier)
        assert table.properties.get("comment")
        for f in table.schema().fields:
            assert f.doc, f"{identifier}.{f.name} has no doc"
