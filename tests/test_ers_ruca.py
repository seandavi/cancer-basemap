"""USDA ERS RUCA: two genuinely different upstream layouts (2010 xlsx, 2020
csv) landed into one raw table, derived into primary/secondary observations.

Fixtures:
- tests/tiny_ruca_2010.xlsx: a real 'Data' sheet excerpt of the downloaded
  2010 (revised 2019) workbook -- errata row, real header row, and five real
  data rows (a plain county, Connecticut's legacy Fairfield County, Alaska's
  legacy Valdez-Cordova, a code-99 zero-population tract, and a decimal
  secondary code). Xlsx is a zip container, so this can't be a byte-for-byte
  slice like a CSV fixture; it is a small workbook built with openpyxl from
  those five real rows' actual cell values.
- tests/tiny_ruca_2020.csv: a real byte-for-byte excerpt of the downloaded
  2020 CSV -- header plus five real rows, including the non-ASCII "Cañon
  City, CO" destination name (the Latin-1 encoding check) and a Connecticut
  tract showing both the legacy (TractFIPS20) and planning-region
  (TractFIPS23) codes for the same physical tract.
- tests/tiny_ruca_2020_malformed.csv: synthetic, not a real excerpt -- ERS's
  real file has never published a non-numeric, present PrimaryRUCA/
  SecondaryRUCA value other than '99' (verified 2026-09-18). Built only to
  exercise the present-but-non-numeric case (#148's bug class).
"""

from pathlib import Path

import pyarrow as pa
import pytest
from pyiceberg.expressions import EqualTo

from cancerbasemap import ers_ruca, merge

REL = "2026.08"
XLSX_2010 = str(Path(__file__).parent / "tiny_ruca_2010.xlsx")
CSV_2020 = str(Path(__file__).parent / "tiny_ruca_2020.csv")
MALFORMED_2020 = str(Path(__file__).parent / "tiny_ruca_2020_malformed.csv")


def rows(cat, identifier, **kw):
    return cat.load_table(identifier).scan(**kw).to_arrow().to_pylist()


def test_raw_2010_is_verbatim_and_whole(cat):
    edition, n = ers_ruca.land_raw(cat, REL, edition="2010", url=XLSX_2010)
    assert edition == "2010"
    assert n == 5

    raw = rows(cat, "raw.ers__ruca_tract")
    assert len(raw) == 5
    assert {r["ruca_edition"] for r in raw} == {"2010"}
    assert {r["landed_in"] for r in raw} == {REL}
    # 2020-only columns are NULL on 2010 rows
    assert all(r["TractFIPS20"] is None for r in raw)

    ct = next(r for r in raw if r["fips_2010"] == "09001")
    assert ct["tract_fips_2010"] == "09001010101"
    ak = next(r for r in raw if r["fips_2010"] == "02261")
    assert ak["county_name_2010"] == "Valdez-Cordova Census Area"
    code99 = next(r for r in raw if r["primary_ruca_2010"] == "99")
    assert code99["pop_density_2010"] is None  # blank cell in the source (land area 0)
    secdec = next(r for r in raw if r["fips_2010"] == "04011")
    # the excel-extension float quirk (10.199999999999999) does not survive landing
    assert secdec["secondary_ruca_2010"] == "7.2"
    assert secdec["primary_ruca_2010"] == "7"  # no trailing '.0'

    # re-landing the same edition replaces it rather than appending
    ers_ruca.land_raw(cat, REL, edition="2010", url=XLSX_2010)
    assert len(rows(cat, "raw.ers__ruca_tract")) == 5


def test_raw_2020_is_verbatim_and_whole(cat):
    edition, n = ers_ruca.land_raw(cat, REL, edition="2020", url=CSV_2020)
    assert edition == "2020"
    assert n == 5

    raw = rows(cat, "raw.ers__ruca_tract")
    assert len(raw) == 5
    assert {r["ruca_edition"] for r in raw} == {"2020"}
    # 2010-only columns are NULL on 2020 rows
    assert all(r["tract_fips_2010"] is None for r in raw)

    canon = next(r for r in raw if r["PrimaryDestinationName"] == "Cañon City, CO")
    assert canon["CountyName20"] == "Fremont County"  # Latin-1 decoded correctly

    ct = next(r for r in raw if r["StateName20"] == "Connecticut")
    assert ct["TractFIPS20"] == "09001010101"  # legacy county prefix
    assert ct["TractFIPS23"] == "09190010101"  # planning-region prefix, same physical tract


def test_both_editions_coexist(cat):
    ers_ruca.land_raw(cat, REL, edition="2010", url=XLSX_2010)
    ers_ruca.land_raw(cat, REL, edition="2020", url=CSV_2020)
    raw = rows(cat, "raw.ers__ruca_tract")
    assert len(raw) == 10
    assert {r["ruca_edition"] for r in raw} == {"2010", "2020"}


def test_a_changed_header_fails_before_landing(cat, tmp_path):
    bad_header = list(ers_ruca.COLUMNS_2020)
    bad_header[-1] = "PopDens"
    bad = tmp_path / "bad.csv"
    bad.write_text(",".join(bad_header) + "\n")
    with pytest.raises(SystemExit, match="2020 edition"):
        ers_ruca.land_raw(cat, REL, edition="2020", url=str(bad))


def test_unknown_edition_is_a_hard_stop(cat):
    with pytest.raises(SystemExit, match="unknown edition"):
        ers_ruca.land_raw(cat, REL, edition="2015", url=CSV_2020)


def test_derives_definitions_stratum_and_observations_2020(cat):
    counts = ers_ruca.ingest(cat, REL, edition="2020", url=CSV_2020)
    assert counts["raw.ers__ruca_tract"] == 5

    defs = {d["measure_id"]: d for d in rows(cat, "measure.definition")}
    assert set(defs) == {"RUCA:primary", "RUCA:secondary"}
    assert defs["RUCA:primary"]["source"] == "RUCA"
    assert defs["RUCA:primary"]["rate_basis"] == "index"
    assert defs["RUCA:primary"]["method"] == "derived"
    assert "not coded" in defs["RUCA:primary"]["doc"]
    assert "7.2" in defs["RUCA:secondary"]["doc"]

    strata = rows(cat, "measure.stratum")
    assert len(strata) == 1
    assert (strata[0]["stratum_id"], strata[0]["scheme"]) == ("RUCA:none", "RUCA_NONE")

    obs = rows(cat, "measure.observation", row_filter="source = 'RUCA'")
    assert len(obs) == 10  # 5 tracts x (primary, secondary)
    by_geo = {(o["geo_id"], o["measure_id"]): o for o in obs}

    # 09001010101 is the legacy-prefix tract FIPS (TractFIPS20), not TractFIPS23
    ct_primary = by_geo[("tract:09001010101", "RUCA:primary")]
    assert ct_primary["value"] == 2.0
    assert ct_primary["value_status"] == "reported"
    assert ct_primary["geo_vintage"] == 2020
    assert ct_primary["period_start"] == ct_primary["period_end"] == "2020"

    # the secondary-decimal tract (08087000700, SecondaryRUCA = 7.2)
    secdec = by_geo[("tract:08087000700", "RUCA:secondary")]
    assert secdec["value"] == 7.2

    # the code-99 tract: not_applicable, never the number 99, on both measures
    notcoded_p = by_geo[("tract:01003990000", "RUCA:primary")]
    notcoded_s = by_geo[("tract:01003990000", "RUCA:secondary")]
    assert notcoded_p["value"] is None and notcoded_p["value_status"] == "not_applicable"
    assert notcoded_s["value"] is None and notcoded_s["value_status"] == "not_applicable"


def test_a_present_non_numeric_code_lands_not_available_not_reported(cat):
    """A PrimaryRUCA/SecondaryRUCA cell that is present but neither '99' nor
    numeric must not read as a numberless 'reported' row: value_status used to
    be derived from the '99' check alone, independent of whether TRY_CAST
    actually produced `value` -- the same class of bug #148 fixed generally in
    merge.check_observations (a present-but-non-numeric cell has never been
    published by ERS, verified 2026-09-18, but the derivation should not
    silently mislabel one if it ever is)."""
    ers_ruca.ingest(cat, REL, edition="2020", url=MALFORMED_2020)
    obs = {o["measure_id"]: o for o in rows(cat, "measure.observation", row_filter="source = 'RUCA'")}
    assert len(obs) == 2
    for o in obs.values():
        assert o["value"] is None
        assert o["value_status"] == "not_available"


def test_derives_observations_2010(cat):
    counts = ers_ruca.ingest(cat, REL, edition="2010", url=XLSX_2010)
    assert counts["raw.ers__ruca_tract"] == 5

    obs = {(o["geo_id"], o["measure_id"]): o
           for o in rows(cat, "measure.observation", row_filter="source = 'RUCA'")}
    assert len(obs) == 10
    ak_primary = obs[("tract:02261000100", "RUCA:primary")]
    assert ak_primary["value"] == 10.0
    assert ak_primary["geo_vintage"] == 2010
    assert ak_primary["period_start"] == ak_primary["period_end"] == "2010"

    secdec = obs[("tract:04011960100", "RUCA:secondary")]
    assert secdec["value"] == 7.2  # the excel-extension float quirk does not survive


def test_editions_do_not_retire_each_other(cat):
    ers_ruca.ingest(cat, REL, edition="2010", url=XLSX_2010)
    ers_ruca.ingest(cat, "2026.09", edition="2020", url=CSV_2020)
    obs = rows(cat, "measure.observation", row_filter="source = 'RUCA' AND valid_to IS NULL")
    assert len(obs) == 20  # 10 from each edition, both still live
    assert {o["source_release"] for o in obs} == {"2010", "2020"}


def test_rerun_is_idempotent(cat):
    ers_ruca.ingest(cat, REL, edition="2020", url=CSV_2020)
    counts = ers_ruca.ingest(cat, "2026.09", edition="2020", url=CSV_2020)
    assert counts["measure.observation"]["written"] == 0
    assert counts["measure.observation"]["unchanged"] == 10
    assert counts["measure.definition"] == 2
    assert counts["measure.stratum"] == 1


def other_observation():
    return dict(source="OTHER", source_release="V0", measure_id="OTHER:x", geo_id="tract:99999999999",
               geo_vintage=2020, period_start="2020", period_end="2020", stratum_id="OTHER:none",
               value=1.0, lower=None, upper=None, interval_level=None, numerator=None,
               denominator=None, value_status="reported", reliability_flag=None, trend=None)


def test_ruca_does_not_retire_another_writer(cat):
    """measure.observation is a stacked, multi-writer table (SPEC.md § Measures):
    the merge scope must be (source, source_release), not source_release alone,
    or one source's re-ingest would retire another source's rows."""
    other = pa.Table.from_pylist([other_observation()])
    merge.merge(cat, "measure.observation", other, REL, EqualTo("source", "OTHER"))

    ers_ruca.ingest(cat, REL, edition="2020", url=CSV_2020)
    ers_ruca.ingest(cat, "2026.09", edition="2020", url=CSV_2020)

    live_other = rows(cat, "measure.observation",
                      row_filter="source = 'OTHER' AND valid_to IS NULL")
    assert len(live_other) == 1
    assert live_other[0]["valid_from"] == REL


def test_every_column_is_documented(cat):
    ers_ruca.ingest(cat, REL, edition="2020", url=CSV_2020)
    ers_ruca.ingest(cat, REL, edition="2010", url=XLSX_2010)
    table = cat.load_table("raw.ers__ruca_tract")
    assert table.properties.get("comment")
    for f in table.schema().fields:
        assert f.doc, f"raw.ers__ruca_tract.{f.name} has no doc"
