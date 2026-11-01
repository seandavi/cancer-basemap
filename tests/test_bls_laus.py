"""BLS LAUS county: land whole (data file + 4 lookups) -> derive four measures,
checksum-deduplicated vintages, real footnote sentinels.

Fixtures are real byte-for-byte excerpts (module docstring: fetched via
web.archive.org since download.bls.gov 403s this environment) of the actual
BLS files:
  - tiny_bls_laus_county.txt: Autauga County AL (01001, all four measures, one
    month plus its annual average), a Connecticut planning region (09110, the
    2022-vintage geography), Orleans Parish LA (22071) spanning the real 2005
    Katrina gap (a reported month, then footnote 'N' for both a month and an
    annual average), and a Puerto Rico municipio (72001) with a real footnote
    'Y' (reported) row and a real footnote 'U' (not_available) annual average.
  - tiny_bls_laus_area.txt / _series.txt: the matching area/series rows.
  - tiny_bls_laus_measure.txt / _footnote.txt: the complete real lookup files
    (only 7 and 8 rows respectively).
"""

from pathlib import Path

import pyarrow as pa
import pytest
from pyiceberg.expressions import EqualTo

from cancerbasemap import bls_laus, merge

REL = "2026.09"
FIX = Path(__file__).parent
COUNTY = str(FIX / "tiny_bls_laus_county.txt")
AREA = str(FIX / "tiny_bls_laus_area.txt")
SERIES = str(FIX / "tiny_bls_laus_series.txt")
MEASURE = str(FIX / "tiny_bls_laus_measure.txt")
FOOTNOTE = str(FIX / "tiny_bls_laus_footnote.txt")


def rows(cat, identifier, **kw):
    return cat.load_table(identifier).scan(**kw).to_arrow().to_pylist()


def _ingest(cat, release="2026.09", vintage="2026-09-18", since=2000):
    return bls_laus.ingest(cat, release, COUNTY, AREA, SERIES, MEASURE, FOOTNOTE,
                           vintage=vintage, since=since)


def test_raw_is_verbatim_and_whole(cat):
    vintage, counts = bls_laus.land_raw(cat, REL, COUNTY, AREA, SERIES, MEASURE, FOOTNOTE,
                                        vintage="2026-09-18")
    assert vintage == "2026-09-18"
    assert counts == {"raw.bls__laus_county": 11, "raw.bls__laus_area": 4,
                      "raw.bls__laus_series": 7, "raw.bls__laus_measure": 7,
                      "raw.bls__laus_footnote": 7}

    county = rows(cat, "raw.bls__laus_county")
    assert len(county) == 11
    assert {r["laus_vintage"] for r in county} == {"2026-09-18"}
    # series_id/value are landed with their fixed-width padding trimmed, not reparsed
    katrina = next(r for r in county if r["series_id"] == "LAUCN220710000000003"
                   and r["year"] == "2005" and r["period"] == "M09")
    assert katrina["value"] == "-"
    assert katrina["footnote_codes"] == "N"

    footnote = rows(cat, "raw.bls__laus_footnote")
    assert {r["footnote_code"] for r in footnote} == set(bls_laus.FOOTNOTE_TEXT)

    # re-landing the same vintage replaces it rather than appending
    bls_laus.land_raw(cat, REL, COUNTY, AREA, SERIES, MEASURE, FOOTNOTE, vintage="2026-09-18")
    assert len(rows(cat, "raw.bls__laus_county")) == 11


def test_unchanged_vintage_lands_nothing(cat):
    """SPEC.md's vintage rule: several retrievals with identical bytes are one
    vintage -- a second retrieval of byte-identical upstream data is a no-op,
    not a second vintage."""
    v1, counts1 = bls_laus.land_raw(cat, REL, COUNTY, AREA, SERIES, MEASURE, FOOTNOTE,
                                    vintage="2026-09-18")
    assert v1 is not None and counts1["raw.bls__laus_county"] == 11

    v2, counts2 = bls_laus.land_raw(cat, "2026.10", COUNTY, AREA, SERIES, MEASURE, FOOTNOTE,
                                    vintage="2026-10-18")
    assert v2 is None
    assert counts2 == {}
    assert len(rows(cat, "raw.bls__laus_county")) == 11  # no second vintage landed

    manifest_rows = rows(cat, "provenance.release", row_filter="source = 'bls_laus'")
    assert len(manifest_rows) == 1
    assert manifest_rows[0]["source_version"] == "2026-09-18"
    assert manifest_rows[0]["checksum"]  # populated, not NULL


def test_a_changed_header_fails_before_landing(cat, tmp_path):
    bad = tmp_path / "bad.txt"
    bad.write_bytes(b"series_id\tyear\tperiod\tval\tfootnote_codes\r\n"
                    b"LAUCN010010000000003\t2024\tM01\t2.6\t\r\n")
    with pytest.raises(SystemExit, match="val"):
        bls_laus.land_raw(cat, REL, str(bad), AREA, SERIES, MEASURE, FOOTNOTE, vintage="2026-09-18")


def test_derives_four_measures(cat):
    counts = _ingest(cat)
    assert counts["raw.bls__laus_county"] == 11

    defs = {d["measure_id"]: d for d in rows(cat, "measure.definition")}
    assert set(defs) == {"BLS_LAUS:unemployment_rate", "BLS_LAUS:unemployed",
                         "BLS_LAUS:employed", "BLS_LAUS:labor_force"}
    assert defs["BLS_LAUS:unemployment_rate"]["rate_basis"] == "percent"
    assert defs["BLS_LAUS:unemployed"]["rate_basis"] == "count"
    assert all(d["method"] == "model_based" for d in defs.values())
    assert all("seasonally adjusted" in d["doc"] for d in defs.values())

    strata = rows(cat, "measure.stratum")
    assert [s["stratum_id"] for s in strata] == ["BLS_LAUS:ALL"]

    obs = {(r["geo_id"], r["measure_id"], r["period_start"]): r
          for r in rows(cat, "measure.observation", row_filter="source = 'BLS_LAUS'")}

    # Autauga County, AL: a plain monthly value and its annual average, all four measures
    rate = obs[("county:01001", "BLS_LAUS:unemployment_rate", "2024-01-01")]
    assert rate["value"] == 2.6
    assert rate["value_status"] == "reported"
    assert rate["period_end"] == "2024-01-31"
    assert rate["geo_vintage"] == 2020
    annual = obs[("county:01001", "BLS_LAUS:unemployment_rate", "2024")]
    assert annual["value"] == 2.7
    assert annual["period_end"] == "2024"  # M13 periods are a bare year, like ers_rucc/cdc_svi
    assert obs[("county:01001", "BLS_LAUS:unemployed", "2024-01-01")]["value"] == 717.0
    assert obs[("county:01001", "BLS_LAUS:employed", "2024-01-01")]["value"] == 27396.0
    assert obs[("county:01001", "BLS_LAUS:labor_force", "2024-01-01")]["value"] == 28113.0

    # Connecticut planning region: 2022-vintage geography, not 2020
    ct = obs[("county:09110", "BLS_LAUS:unemployment_rate", "2024-01-01")]
    assert ct["geo_vintage"] == 2022
    assert ct["value"] == 3.7

    # Orleans Parish, LA: real value before Katrina, real 'N' gap after (monthly + annual)
    before = obs[("county:22071", "BLS_LAUS:unemployment_rate", "2005-08-01")]
    assert before["value"] == 6.0 and before["value_status"] == "reported"
    gap = obs[("county:22071", "BLS_LAUS:unemployment_rate", "2005-09-01")]
    assert gap["value"] is None
    assert gap["value_status"] == "not_available"
    assert gap["reliability_flag"] == "N"
    gap_annual = obs[("county:22071", "BLS_LAUS:unemployment_rate", "2005")]
    assert gap_annual["value"] is None and gap_annual["value_status"] == "not_available"

    # Puerto Rico municipio: 'Y' footnote is still a reported value; 'U' annual is not
    y_row = obs[("county:72001", "BLS_LAUS:unemployment_rate", "2017-09-01")]
    assert y_row["value"] == 12.5
    assert y_row["value_status"] == "reported"
    assert y_row["reliability_flag"] == "Y"
    u_row = obs[("county:72001", "BLS_LAUS:unemployment_rate", "2020")]
    assert u_row["value"] is None
    assert u_row["value_status"] == "not_available"
    assert u_row["reliability_flag"] == "U"


def test_a_present_non_numeric_value_lands_not_available_not_reported(cat):
    """A cell that is present but doesn't parse as a number must not read as a
    numberless 'reported' row: value_status used to be derived from the
    footnote_codes flag alone while `value` went through a separate
    TRY_CAST -- the same class of bug #148 found across several sources
    (ers_rucc.py, ers_ruca.py, hrsa_ahrf.py, scp.py, places.py, and this
    module) -- so a present-but-non-numeric cell with no N/U footnote used to
    land as value_status='reported' with value NULL, which
    merge.check_observations' reverse guard now catches for any source that
    regresses to it."""
    malformed = str(FIX / "tiny_bls_laus_county_malformed.txt")
    bls_laus.land_raw(cat, REL, malformed, AREA, SERIES, MEASURE, FOOTNOTE, vintage="2026-09-18")
    counts = bls_laus.transform(cat, REL, "2026-09-18", since=2000)
    assert counts["measure.observation"]["written"] == 1
    obs = rows(cat, "measure.observation", row_filter="source = 'BLS_LAUS'")
    assert len(obs) == 1
    assert obs[0]["value"] is None
    assert obs[0]["value_status"] == "not_available"


def test_since_filters_derived_history(cat):
    """Full history stays in raw; only years >= `since` are derived (module
    docstring's ponytail note)."""
    counts = _ingest(cat, since=2020)
    obs = rows(cat, "measure.observation", row_filter="source = 'BLS_LAUS'")
    years = {r["period_start"][:4] for r in obs}
    assert years == {"2020", "2024"}  # 2005 and 2017 rows fall before `since`; 2020 itself stays
    assert len(rows(cat, "raw.bls__laus_county")) == 11  # raw keeps everything regardless


def test_an_unknown_footnote_code_fails_the_derive(cat, tmp_path):
    bad = tmp_path / "county_bad.txt"
    bad.write_bytes(b"series_id                     \tyear\tperiod\t       value\tfootnote_codes\r\n"
                    b"LAUCN010010000000003          \t2024\tM01\t         2.6\tZ\r\n")
    bls_laus.land_raw(cat, REL, str(bad), AREA, SERIES, MEASURE, FOOTNOTE, vintage="2026-09-18")
    with pytest.raises(SystemExit, match="Z"):
        bls_laus.transform(cat, REL, "2026-09-18", since=2000)


def test_rerun_is_idempotent(cat):
    """Re-running `ingest` against byte-identical upstream data is the
    unchanged-vintage no-op (test_unchanged_vintage_lands_nothing); re-deriving
    the same already-landed vintage under a later release is the ordinary
    idempotent-merge case, exercised directly here."""
    _ingest(cat, release="2026.09", vintage="2026-09-18")
    counts = bls_laus.transform(cat, "2026.10", "2026-09-18", since=2000)
    assert counts["measure.observation"]["written"] == 0
    assert counts["measure.observation"]["unchanged"] == 11
    assert counts["measure.definition"] == 4
    assert counts["measure.stratum"] == 1


def other_observation():
    return dict(source="OTHER", source_release="V0", measure_id="OTHER:x", geo_id="county:99999",
               geo_vintage=2020, period_start="2020", period_end="2020", stratum_id="OTHER:none",
               value=1.0, lower=None, upper=None, interval_level=None, numerator=None,
               denominator=None, value_status="reported", reliability_flag=None, trend=None)


def test_bls_laus_does_not_retire_another_writer(cat):
    other = pa.Table.from_pylist([other_observation()])
    merge.merge(cat, "measure.observation", other, REL, EqualTo("source", "OTHER"))

    _ingest(cat, release="2026.09", vintage="2026-09-18")

    live_other = rows(cat, "measure.observation",
                      row_filter="source = 'OTHER' AND valid_to IS NULL")
    assert len(live_other) == 1


def test_every_column_is_documented(cat):
    _ingest(cat)
    for identifier in ("raw.bls__laus_county", "raw.bls__laus_area", "raw.bls__laus_series",
                      "raw.bls__laus_measure", "raw.bls__laus_footnote"):
        table = cat.load_table(identifier)
        assert table.properties.get("comment")
        for f in table.schema().fields:
            assert f.doc, f"{identifier}.{f.name} has no doc"
