"""EPA Superfund NPL site status + FRS FIPS lookup: land both -> derive
facility.site (a Type-2, retire-on-disappearance table, kind='superfund').

Fixtures are real byte-for-byte excerpts of the live ArcGIS Feature Service
queries (2026-09-18, PJP Landfill added 2026-09-19):
tests/tiny_epa_superfund_status.json (7 real sites -- American Cyanamid Co.
NJ, which has no FRS match at all; Solvents Recovery Service of New England
CT, whose FRS FIPS_CODE is the real non-zero-padded '9003'; Mowbray
Engineering Co. AL, Deleted; 35th Avenue AL, Proposed; Triana/Tennessee
River AL, whose County text spans three counties but whose single FRS
FIPS_CODE is only one of them; Taputimu Farm, American Samoa, whose FRS row
matches by id but itself carries a NULL FIPS_CODE (territories have no
county-equivalent FIPS); and PJP Landfill NJ, whose FRS row matches but
whose FIPS_CODE is the real malformed 'NJ017' -- a state postal
abbreviation glued to a county code, not a FIPS code at all) and
tests/tiny_epa_superfund_frs.json (the matching FRS rows for six of those
seven).
"""

import json
import re
from pathlib import Path

import pyarrow as pa
import pytest
from pyiceberg.expressions import EqualTo

from cancerbasemap import epa_superfund, merge

REL = "2026.09"
STATUS_JSON = str(Path(__file__).parent / "tiny_epa_superfund_status.json")
FRS_JSON = str(Path(__file__).parent / "tiny_epa_superfund_frs.json")


def rows(cat, identifier, **kw):
    return cat.load_table(identifier).scan(**kw).to_arrow().to_pylist()


def test_raw_is_verbatim_and_whole(cat):
    retrieved_on, counts = epa_superfund.land_raw(cat, REL, STATUS_JSON, FRS_JSON,
                                                   retrieved_on="2026-09-18")
    assert retrieved_on == "2026-09-18"
    assert counts == {"raw.superfund__npl_status": 7, "raw.superfund__npl_frs": 6}

    status = rows(cat, "raw.superfund__npl_status")
    assert len(status) == 7
    assert {r["retrieved_on"] for r in status} == {"2026-09-18"}
    assert {r["landed_in"] for r in status} == {REL}

    ct = next(r for r in status if r["Site_EPA_ID"] == "CTD009717604")
    assert ct["Status"] == "NPL Site"

    frs = rows(cat, "raw.superfund__npl_frs")
    assert len(frs) == 6
    ct_frs = next(r for r in frs if r["PGM_SYS_ID"] == "CTD009717604")
    assert ct_frs["FIPS_CODE"] == "9003"  # non-zero-padded, landed verbatim
    samoa_frs = next(r for r in frs if r["PGM_SYS_ID"] == "ASD980637656")
    assert samoa_frs["FIPS_CODE"] is None  # a real FRS match with no county FIPS at all
    pjp_frs = next(r for r in frs if r["PGM_SYS_ID"] == "NJD980505648")
    assert pjp_frs["FIPS_CODE"] == "NJ017"  # malformed, landed verbatim -- see module docstring

    # re-landing the same retrieval date replaces it rather than appending
    epa_superfund.land_raw(cat, REL, STATUS_JSON, FRS_JSON, retrieved_on="2026-09-18")
    assert len(rows(cat, "raw.superfund__npl_status")) == 7
    assert len(rows(cat, "raw.superfund__npl_frs")) == 6


def test_a_changed_field_set_fails_before_landing(cat, tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"features": [{"attributes": {"Site_Name": "X"}}]}))
    with pytest.raises(SystemExit, match="NPL status"):
        epa_superfund.land_raw(cat, REL, status_url=str(bad), frs_url=FRS_JSON)


def test_derives_facility_site(cat):
    counts = epa_superfund.ingest(cat, REL, STATUS_JSON, FRS_JSON, retrieved_on="2026-09-18")
    assert counts["facility.site"]["written"] == 7
    # 3 unmatched: NJD002173276 (no FRS row at all), ASD980637656 (FRS row
    # matches but its own FIPS_CODE is NULL), and NJD980505648 (FRS row
    # matches but its FIPS_CODE is malformed, 'NJ017') -- module docstring.
    assert counts["facility.site frs unmatched"] == 3

    sites = {r["facility_id"]: r for r in rows(cat, "facility.site")}
    assert set(sites) == {
        "EPA_SUPERFUND:NJD002173276", "EPA_SUPERFUND:CTD009717604",
        "EPA_SUPERFUND:ALD031618069", "EPA_SUPERFUND:ALN000410750",
        "EPA_SUPERFUND:ALD983166299", "EPA_SUPERFUND:ASD980637656",
        "EPA_SUPERFUND:NJD980505648",
    }

    ct = sites["EPA_SUPERFUND:CTD009717604"]
    assert ct["source"] == "EPA_SUPERFUND"
    assert ct["source_release"] is None  # not part of the business key -- see module docstring
    assert ct["kind"] == "superfund"
    assert ct["geo_id"] == "county:09003"  # lpad'd from FRS's non-padded '9003'
    assert ct["geo_vintage"] == 2010
    assert ct["lat"] == pytest.approx(41.6196)
    assert ct["lon"] == pytest.approx(-72.878)
    assert "LAZY LANE" in ct["address"]
    attrs = json.loads(ct["attributes_json"])
    assert attrs["status"] == "NPL Site"
    assert attrs["registry_id"] == "110071099796"
    assert attrs["listing_date"] == "09/08/1983"

    # American Cyanamid Co.: no FRS match -> geo_id/geo_vintage NULL, not guessed;
    # address falls back to city/state text; registry_id NULL.
    nj = sites["EPA_SUPERFUND:NJD002173276"]
    assert nj["geo_id"] is None and nj["geo_vintage"] is None
    assert nj["lat"] == pytest.approx(40.555561)  # status layer's own lat/lon, still present
    assert "Bound Brook" in nj["address"] and "New Jersey" in nj["address"]
    assert json.loads(nj["attributes_json"])["registry_id"] is None

    deleted = sites["EPA_SUPERFUND:ALD031618069"]
    assert json.loads(deleted["attributes_json"])["status"] == "Deleted NPL Site"
    assert json.loads(deleted["attributes_json"])["deletion_date"] == "12/30/1993"

    proposed = sites["EPA_SUPERFUND:ALN000410750"]
    assert json.loads(proposed["attributes_json"])["status"] == "Proposed NPL Site"
    assert json.loads(proposed["attributes_json"])["listing_date"] is None

    # Triana/Tennessee River: County text spans three counties, but the single
    # FRS-registered FIPS (Morgan, 01089) is what geo_id gets -- the
    # single-point limitation the module docstring documents.
    multi = sites["EPA_SUPERFUND:ALD983166299"]
    assert multi["geo_id"] == "county:01089"
    assert "Limestone, Madison, Morgan" in json.loads(multi["attributes_json"])["county_name"]

    # Taputimu Farm: a real FRS match (registry_id present), but FIPS_CODE
    # itself is NULL (territories have no county-equivalent FIPS) -> geo_id
    # NULL too, not guessed.
    samoa = sites["EPA_SUPERFUND:ASD980637656"]
    assert samoa["geo_id"] is None and samoa["geo_vintage"] is None
    assert json.loads(samoa["attributes_json"])["registry_id"] == "110009332365"

    # PJP Landfill: a real FRS match, but its FIPS_CODE ('NJ017') is a state
    # postal abbreviation glued to a county code, not a real FIPS -- validated
    # and rejected, not lpad'd into a malformed geo_id like 'county:0NJ017'.
    pjp = sites["EPA_SUPERFUND:NJD980505648"]
    assert pjp["geo_id"] is None and pjp["geo_vintage"] is None
    assert json.loads(pjp["attributes_json"])["registry_id"] == "110009299749"


def test_a_site_being_listed_is_a_changed_row_not_retire_plus_new(cat, tmp_path):
    """Unlike FDA_MQSA (no id -> rename looks like retire+new), this source
    has a real per-site id, so a genuine attribute change on the SAME site --
    here, '35th Avenue' moving from Proposed to listed -- must show up as
    'changed', with every untouched site staying on its original row."""
    epa_superfund.ingest(cat, REL, STATUS_JSON, FRS_JSON, retrieved_on="2026-09-18")

    day2_status = json.loads(Path(STATUS_JSON).read_text(encoding="utf-8"))
    for feat in day2_status["features"]:
        if feat["attributes"]["Site_EPA_ID"] == "ALN000410750":
            feat["attributes"]["Status"] = "NPL Site"
            feat["attributes"]["Listing_Date"] = "01/15/2026"
    day2_path = tmp_path / "day2_status.json"
    day2_path.write_text(json.dumps(day2_status), encoding="utf-8")

    counts = epa_superfund.ingest(cat, "2026.10", str(day2_path), FRS_JSON, retrieved_on="2026-09-25")

    assert counts["facility.site"]["written"] == 2  # the new version + its closing companion
    assert counts["facility.site"]["changed"] == 1
    assert counts["facility.site"]["superseded"] == 1
    assert counts["facility.site"]["unchanged"] == 6
    assert "retired" not in counts["facility.site"]
    assert "new" not in counts["facility.site"]

    versions = rows(cat, "facility.site", row_filter="facility_id = 'EPA_SUPERFUND:ALN000410750'")
    assert len(versions) == 2
    old, new = sorted(versions, key=lambda r: r["valid_from"])
    assert old["valid_from"] == REL and old["valid_to"] == "2026.10"
    assert json.loads(old["attributes_json"])["status"] == "Proposed NPL Site"
    assert new["valid_from"] == "2026.10" and new["valid_to"] is None
    assert json.loads(new["attributes_json"])["status"] == "NPL Site"

    untouched = rows(cat, "facility.site", row_filter="facility_id = 'EPA_SUPERFUND:CTD009717604'")
    assert len(untouched) == 1
    assert untouched[0]["valid_from"] == REL and untouched[0]["valid_to"] is None


def other_site():
    return dict(facility_id="OTHER:1", source="OTHER", source_release="V0", kind="hospital",
               name="Other Hospital", address=None, lat=None, lon=None, geo_id="county:99999",
               geo_vintage=2020, attributes_json=None)


def test_epa_superfund_does_not_retire_another_writer(cat):
    """facility.site is a stacked, multi-writer table (SPEC.md § Facilities):
    the merge scope must be `source`, not unscoped."""
    other = pa.Table.from_pylist([other_site()])
    merge.merge(cat, "facility.site", other, REL, EqualTo("source", "OTHER"))

    epa_superfund.ingest(cat, REL, STATUS_JSON, FRS_JSON, retrieved_on="2026-09-18")

    live_other = rows(cat, "facility.site", row_filter="source = 'OTHER' AND valid_to IS NULL")
    assert len(live_other) == 1
    assert live_other[0]["valid_from"] == REL


def test_every_geo_id_is_a_real_looking_county_fips(cat):
    """Regression: FIPS_CODE was previously lpad'd without validation, so a
    malformed value like 'NJ017' or 'S' produced a garbage geo_id
    ('county:0NJ017', 'county:0000S') instead of NULL. Every populated
    geo_id must be 'county:' + exactly 5 digits."""
    epa_superfund.ingest(cat, REL, STATUS_JSON, FRS_JSON, retrieved_on="2026-09-18")
    for r in rows(cat, "facility.site", row_filter="source = 'EPA_SUPERFUND'"):
        if r["geo_id"] is not None:
            assert re.fullmatch(r"county:[0-9]{5}", r["geo_id"]), r["geo_id"]


def test_rerun_is_idempotent(cat):
    epa_superfund.ingest(cat, REL, STATUS_JSON, FRS_JSON, retrieved_on="2026-09-18")
    counts = epa_superfund.ingest(cat, REL, STATUS_JSON, FRS_JSON, retrieved_on="2026-09-18")
    assert counts["facility.site"]["written"] == 0
    assert counts["facility.site"]["unchanged"] == 7


def test_every_column_is_documented(cat):
    epa_superfund.ingest(cat, REL, STATUS_JSON, FRS_JSON, retrieved_on="2026-09-18")
    for identifier in ("raw.superfund__npl_status", "raw.superfund__npl_frs", "facility.site"):
        table = cat.load_table(identifier)
        assert table.properties.get("comment")
        for f in table.schema().fields:
            assert f.doc, f"{identifier}.{f.name} has no doc"
