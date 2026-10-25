"""FCC BDC nationwide summary-by-geography file: land whole -> derive county
percent-of-units at >=25/3, >=100/20, >=1000/100 Mbps for Any Technology /
All Wired / All Fixed Wireless, stratified by the source's own R/B code.

The fixture (tests/tiny_fcc_broadband.csv) is a real byte-for-byte excerpt of
the downloaded Dec 31, 2025 filing's
bdc_us_fixed_broadband_summary_by_geography file: Autauga County, AL (both
biz_res values, all three derived technologies), Fairfield County, CT (a
legacy 8-county FIPS, 09001 -- the geo_vintage=2010 case), Las Marías
Municipio, PR (a non-ASCII name), a National row (not derived, but landed),
and an 'Urban' area_data_type row for Autauga (also not derived, only
'Total' is).
"""

import io
import json
import zipfile
from pathlib import Path

import pytest
from pyiceberg.expressions import EqualTo

from canceronice import fcc_broadband, merge
import pyarrow as pa

REL = "2026.09"
AS_OF = "2025-12-31"
CSV = str(Path(__file__).parent / "tiny_fcc_broadband.csv")


def rows(cat, identifier, **kw):
    return cat.load_table(identifier).scan(**kw).to_arrow().to_pylist()


def test_raw_is_verbatim_and_whole(cat):
    as_of, n = fcc_broadband.land_raw(cat, REL, as_of=AS_OF, url=CSV)
    assert as_of == AS_OF
    assert n == 12

    raw = rows(cat, "raw.fcc__bdc_summary")
    assert len(raw) == 12
    assert {r["bdc_as_of"] for r in raw} == {AS_OF}
    assert {r["landed_in"] for r in raw} == {REL}
    assert all(r["bdc_data_vintage"] is None for r in raw)  # url= path: no vintage API call
    assert {r["geography_type"] for r in raw} == {"County", "National"}
    autauga_any = next(r for r in raw if r["geography_id"] == "01001"
                       and r["biz_res"] == "R" and r["technology"] == "Any Technology"
                       and r["area_data_type"] == "Total")
    assert autauga_any["speed_1000_100"] == "0.600107277"  # unparsed string
    pr = next(r for r in raw if r["geography_id"] == "72083")
    assert pr["geography_desc"] == "Las Marías Municipio"

    # re-landing the same as-of date replaces it rather than appending
    fcc_broadband.land_raw(cat, REL, as_of=AS_OF, url=CSV)
    assert len(rows(cat, "raw.fcc__bdc_summary")) == 12


def test_a_changed_header_fails_before_landing(cat, tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("area_data_type,geography_type,geography_id\nTotal,County,01001\n")
    with pytest.raises(SystemExit, match="geography_desc"):
        fcc_broadband.land_raw(cat, REL, as_of=AS_OF, url=str(bad))


def test_as_of_is_required(cat):
    with pytest.raises(SystemExit, match="as-of"):
        fcc_broadband.land_raw(cat, REL, None, CSV)


def test_file_is_required_without_api_credentials(cat, monkeypatch):
    monkeypatch.delenv("FCC_BDC_USERNAME", raising=False)
    monkeypatch.delenv("FCC_BDC_TOKEN", raising=False)
    with pytest.raises(SystemExit, match="FCC_BDC_USERNAME"):
        fcc_broadband.land_raw(cat, REL, AS_OF, None)


def _fake_zip_bytes():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.write(CSV, arcname="bdc_us_fixed_broadband_summary_by_geography_D25_15sep2026.csv")
    return buf.getvalue()


def test_documented_api_route_offline(cat, monkeypatch):
    """Route (b) (module docstring), exercised entirely offline: urlopen is
    mocked to return the same fixture bytes route (a)'s tests use, over the
    three documented endpoints, so this checks the URLs/headers this module
    builds without ever touching bdc.fcc.gov -- it does NOT confirm the FCC's
    real API behaves as documented (unverified without a live account; see
    module docstring)."""
    monkeypatch.setenv("FCC_BDC_USERNAME", "test-user")
    monkeypatch.setenv("FCC_BDC_TOKEN", "test-token")
    seen = []

    def fake_urlopen(req):
        seen.append(req.full_url)
        assert req.get_header("Username") == "test-user"
        assert req.get_header("Hash_value") == "test-token"
        if "listAsOfDates" in req.full_url:
            body = json.dumps({"data": [{"data_type": "availability", "as_of_date": AS_OF},
                                        {"data_type": "challenge", "as_of_date": "2099-01-01"}]}).encode()
        elif "listAvailabilityData" in req.full_url:
            assert f"/{AS_OF}?" in req.full_url
            assert "subcategory=Summary+by+Geography+Type+-+Other+Geographies" in req.full_url
            body = json.dumps({"data": [{"file_id": 424242, "category": "Summary",
                                        "subcategory": "Summary by Geography Type - Other Geographies"}]}).encode()
        elif "downloadFile/availability/424242" in req.full_url:
            body = _fake_zip_bytes()
        else:
            raise AssertionError(f"unexpected URL: {req.full_url}")
        return io.BytesIO(body)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    as_of, n = fcc_broadband.land_raw(cat, REL, url=None)
    assert as_of == AS_OF  # 2099-01-01 challenge date correctly excluded from "latest"
    assert n == 12
    assert len(seen) == 3


def test_derives_definitions_stratum_and_observations(cat):
    counts = fcc_broadband.ingest(cat, REL, as_of=AS_OF, url=CSV)
    assert counts["raw.fcc__bdc_summary"] == 12

    defs = {d["measure_id"]: d for d in rows(cat, "measure.definition")}
    assert len(defs) == 9  # 3 tiers x 3 technologies
    d = defs["FCC_BDC:25_3:wired"]
    assert (d["source"], d["rate_basis"], d["method"], d["units"]) == (
        "FCC_BDC", "percent", "derived", "%")
    assert "All Wired" in d["doc"]

    strata = {s["stratum_id"]: s for s in rows(cat, "measure.stratum")}
    assert set(strata) == {"FCC_BDC:R", "FCC_BDC:B"}
    assert strata["FCC_BDC:R"]["other"] == "R"
    assert strata["FCC_BDC:R"]["scheme"] == "FCC_BDC_BIZ_RES"

    obs = rows(cat, "measure.observation", row_filter="source = 'FCC_BDC'")
    # Autauga (R+B) x 3 tiers x 3 technologies = 18; Fairfield (R only) x 3 x 3 = 9;
    # Las Marías (R only, Any Technology only) x 3 tiers = 3. National and the
    # Urban-area_data_type row are never derived.
    assert len(obs) == 18 + 9 + 3
    assert {o["geo_id"] for o in obs} == {"county:01001", "county:09001", "county:72083"}

    autauga_25_3_wired_r = next(
        o for o in obs if o["geo_id"] == "county:01001" and o["measure_id"] == "FCC_BDC:25_3:wired"
        and o["stratum_id"] == "FCC_BDC:R")
    assert autauga_25_3_wired_r["value"] == pytest.approx(96.1165743)
    assert autauga_25_3_wired_r["value_status"] == "reported"
    assert autauga_25_3_wired_r["denominator"] == 27965.0
    assert autauga_25_3_wired_r["numerator"] is None
    assert autauga_25_3_wired_r["source_release"] == AS_OF
    assert autauga_25_3_wired_r["period_start"] == autauga_25_3_wired_r["period_end"] == AS_OF

    # A real 0% (fixed wireless gigabit in a rural county) lands as a real
    # number, not suppressed.
    autauga_gig_fw_r = next(
        o for o in obs if o["geo_id"] == "county:01001"
        and o["measure_id"] == "FCC_BDC:1000_100:fixed_wireless" and o["stratum_id"] == "FCC_BDC:R")
    assert autauga_gig_fw_r["value"] == 0.0
    assert autauga_gig_fw_r["value_status"] == "reported"

    # Connecticut's legacy county FIPS (09001, not a 09110-09190 planning
    # region) -> geo_vintage 2010, per the precedent places.py established.
    assert all(o["geo_vintage"] == 2010 for o in obs)


def test_geo_vintage_detects_connecticut_planning_regions(cat, tmp_path):
    """If a future filing carries CT's 2022 planning regions instead of its
    legacy counties, geo_vintage flips to 2020 -- verified from the data,
    not hard-coded per as-of date (SPEC.md; module docstring)."""
    header = Path(CSV).read_text().splitlines()[0]
    row = ("Total,County,09110,Capitol Planning Region,\"Capitol Planning Region, CT\","
           "100000,R,Any Technology,1.0,1.0,1.0,1.0,1.0,1.0")
    alt = tmp_path / "alt.csv"
    alt.write_text(header + "\n" + row + "\n")
    fcc_broadband.ingest(cat, REL, as_of="2026-06-30", url=str(alt))
    obs = rows(cat, "measure.observation",
              row_filter="source = 'FCC_BDC' AND source_release = '2026-06-30'")
    assert all(o["geo_vintage"] == 2020 for o in obs)


def test_unmapped_blank_cell_raises(cat, tmp_path):
    """SPEC.md Acceptance C: this file publishes no suppression sentinel
    (module docstring) -- an unexpected blank cell must stop the ingest,
    never silently become a NULL or a guessed status."""
    header = Path(CSV).read_text().splitlines()[0]
    row = ("Total,County,01003,Baldwin County,\"Baldwin County, AL\","
           "1000,R,Any Technology,1.0,1.0,,1.0,1.0,1.0")
    bad = tmp_path / "blank_cell.csv"
    bad.write_text(header + "\n" + row + "\n")
    fcc_broadband.land_raw(cat, REL, as_of="2026-01-01", url=str(bad))
    with pytest.raises(SystemExit, match="blank"):
        fcc_broadband.transform(cat, REL, "2026-01-01")


def test_rerun_is_idempotent(cat):
    fcc_broadband.ingest(cat, REL, as_of=AS_OF, url=CSV)
    counts = fcc_broadband.ingest(cat, "2026.10", as_of=AS_OF, url=CSV)
    assert counts["measure.observation"]["written"] == 0
    assert counts["measure.observation"]["unchanged"] == 30
    assert counts["measure.definition"] == 9
    assert counts["measure.stratum"] == 2


def other_observation():
    return dict(source="OTHER", source_release="V0", measure_id="OTHER:x", geo_id="county:99999",
               geo_vintage=2020, period_start="2020", period_end="2020", stratum_id="OTHER:none",
               value=1.0, lower=None, upper=None, interval_level=None, numerator=None,
               denominator=None, value_status="reported", reliability_flag=None, trend=None)


def test_fcc_broadband_does_not_retire_another_writer(cat):
    """measure.observation is a stacked, multi-writer table (SPEC.md § Measures):
    the merge scope must be (source, source_release), not source_release alone."""
    other = pa.Table.from_pylist([other_observation()])
    merge.merge(cat, "measure.observation", other, REL, EqualTo("source", "OTHER"))

    fcc_broadband.ingest(cat, REL, as_of=AS_OF, url=CSV)
    fcc_broadband.ingest(cat, "2026.10", as_of=AS_OF, url=CSV)

    live_other = rows(cat, "measure.observation",
                      row_filter="source = 'OTHER' AND valid_to IS NULL")
    assert len(live_other) == 1
    assert live_other[0]["valid_from"] == REL


def test_every_column_is_documented(cat):
    fcc_broadband.ingest(cat, REL, as_of=AS_OF, url=CSV)
    table = cat.load_table("raw.fcc__bdc_summary")
    assert table.properties.get("comment")
    for f in table.schema().fields:
        assert f.doc, f"raw.fcc__bdc_summary.{f.name} has no doc"
