"""HRSA AHRF: land long-form (with the copyright exclusion) -> derive the
curated cancer-relevant measures.

Fixtures are real excerpts of the downloaded 2024-2025 release, both byte-
for-byte from the actual files:
- tests/tiny_hrsa_ahrf.csv: fips_st_cnty + cnty_name_st_abbrev + every
  curated field + one AMA-sourced column (md_nf_23) and one AHA-sourced
  column (hosp_23), for five real counties -- a plain metro county
  (01001), a Connecticut legacy county (09001) and its 2022 planning-region
  successor (09110), and an Alaska legacy area (02261, Valdez-Cordova) and
  its current census-area successor (02063, Chugach).
- tests/tiny_hrsa_ahrf_techdoc.xlsx: the same rows of the real technical
  documentation's per-field SOURCE dictionary, verbatim.
- tests/tiny_hrsa_ahrf_malformed.csv: synthetic (see #148) -- AHRF's real
  file has never published a non-numeric, present value in any curated
  column (verified 2026-09-18); built only to exercise that case.
"""

from pathlib import Path

import pytest
from pyiceberg.expressions import EqualTo

from cancerbasemap import hrsa_ahrf, merge

REL = "2026.08"
CSV = str(Path(__file__).parent / "tiny_hrsa_ahrf.csv")
TECHDOC = str(Path(__file__).parent / "tiny_hrsa_ahrf_techdoc.xlsx")
MALFORMED_CSV = str(Path(__file__).parent / "tiny_hrsa_ahrf_malformed.csv")


def rows(cat, identifier, **kw):
    return cat.load_table(identifier).scan(**kw).to_arrow().to_pylist()


def test_raw_is_long_whole_and_excludes_copyrighted_columns(cat):
    ahrf_release, n = hrsa_ahrf.land_raw(cat, REL, csv_url=CSV, techdoc_url=TECHDOC)
    assert ahrf_release == "2024-2025"

    raw = rows(cat, "raw.hrsa__ahrf")
    column_names = {r["column_name"] for r in raw}
    # md_nf_23 (AMA Phys Master File) and hosp_23 (AHA Survey Database) are
    # excluded entirely -- never landed, per the licence finding.
    assert "md_nf_23" not in column_names
    assert "hosp_23" not in column_names
    # every curated field, and the non-key metadata column, DID land
    assert "cnty_name_st_abbrev" in column_names
    for col, _, _ in hrsa_ahrf.CURATED_FIELDS:
        assert col in column_names

    # 5 counties x (24 fixture columns - fips_st_cnty key - 2 excluded) = 5 x 21
    assert n == 5 * 21
    assert len(raw) == n
    assert {r["ahrf_release"] for r in raw} == {"2024-2025"}
    assert {r["landed_in"] for r in raw} == {REL}
    assert {r["file"] for r in raw} == {"tiny_hrsa_ahrf.csv"}

    # a real blank cell lands as a present row with value=NULL, not omitted
    blank = next(r for r in raw if r["fips"] == "09001" and r["column_name"] == "np_npi_24")
    assert blank["value"] is None
    # a real reported zero is never confused with missing
    zero = next(r for r in raw if r["fips"] == "02063" and r["column_name"] == "fedly_qualfd_hlth_ctr_24")
    assert zero["value"] == "0"

    # re-landing the same release replaces it rather than appending
    hrsa_ahrf.land_raw(cat, REL, csv_url=CSV, techdoc_url=TECHDOC)
    assert len(rows(cat, "raw.hrsa__ahrf")) == n


def test_a_missing_fips_column_fails_before_landing(cat, tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("st_fips,cnty_name\n01001,Autauga\n")
    with pytest.raises(SystemExit, match="fips_st_cnty"):
        hrsa_ahrf.land_raw(cat, REL, csv_url=str(bad), techdoc_url=TECHDOC)


def test_a_curated_field_missing_from_the_csv_fails_before_landing(cat, tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("fips_st_cnty,cnty_name_st_abbrev\n01001,\"Autauga, AL\"\n")
    with pytest.raises(SystemExit, match="fedly_qualfd_hlth_ctr_24"):
        hrsa_ahrf.land_raw(cat, REL, csv_url=str(bad), techdoc_url=TECHDOC)


def _write_xlsx(path, rows):
    """A tiny FIELD/CAT/YEAR OF DATA/VARIABLE NAME/CHARACTERISTICS/SOURCE/DATE ON
    workbook, built with DuckDB's own excel extension (no new test dependency)
    rather than a checked-in binary fixture -- used only for synthetic edge
    cases below, not real excerpts (those are tests/tiny_hrsa_ahrf_techdoc.xlsx)."""
    import duckdb as ddb
    con = ddb.connect()
    con.execute("INSTALL excel; LOAD excel;")
    con.execute("""
        CREATE TABLE t(FIELD VARCHAR, CAT VARCHAR, "YEAR OF DATA" INTEGER,
                       "VARIABLE NAME" VARCHAR, CHARACTERISTICS VARCHAR, SOURCE VARCHAR,
                       "DATE ON" VARCHAR)
    """)
    for row in rows:
        con.execute("INSERT INTO t VALUES (?, ?, ?, ?, ?, ?, ?)", row)
    con.execute(f"COPY t TO '{path}' WITH (FORMAT xlsx, HEADER false)")


def test_a_broken_techdoc_parse_is_a_hard_stop(cat, tmp_path):
    """If the technical-documentation parse ever silently returned zero field
    rows (a broken parse: wrong range, wrong sheet, corrupt file), landing raw
    would have nothing to check any column's licence against -- this must
    never proceed quietly."""
    empty = tmp_path / "empty.xlsx"
    _write_xlsx(empty, [(None, None, None, None, None, None, None),
                        ("", "", None, "", "", "", None)])
    with pytest.raises(SystemExit, match="no field rows at all"):
        hrsa_ahrf.land_raw(cat, REL, csv_url=CSV, techdoc_url=str(empty))


def test_an_unrecognised_source_is_excluded_and_reported(cat, tmp_path, capsys):
    """A column sourced from something not on ALLOWED_SOURCES or
    EXCLUDED_SOURCES -- a source this module has never been told about, e.g.
    a future AHRF release adding a new commercial data partner -- must be
    excluded by default (fail closed) rather than landed, and reported so a
    human notices and classifies it. Synthetic: no such field exists in the
    real 2024-2025 file (every one of its 45 real sources is already
    classified, see the module docstring's table)."""
    csv_with_extra = tmp_path / "extra.csv"
    header = Path(CSV).read_text().splitlines()[0]
    lines = Path(CSV).read_text().splitlines()[1:]
    csv_with_extra.write_text(
        header + ",unknown_src_field_24\n" +
        "\n".join(f"{line},{n}" for line, n in zip(lines, [99, 1, 5, "", ""])) + "\n")

    techdoc_with_extra = tmp_path / "extra_techdoc.xlsx"
    real_rows = [(col, "HP", 2024, " placeholder", "", " CMS Provider of Services", "07/25")
                for col, _, _ in hrsa_ahrf.CURATED_FIELDS] + [
        ("fips_st_cnty", "GEO", None, " Header", "", " Derived From GSA", None),
        ("cnty_name_st_abbrev", "GEO", None, " County Name", "", " Derived From GSA", None),
        ("md_nf_23", "HP", 2023, " Total M.D.'s", "", " AMA Phys Master File", "07/25"),
        ("hosp_23", "HF", 2023, " Total Number Hospitals", "", " AHA Survey Database 23", "07/25"),
        ("unknown_src_field_24", "HP", 2024, " Synthetic Unrecognised Field", "",
         " Fictional Vendor Database", "07/25"),
    ]
    _write_xlsx(techdoc_with_extra, real_rows)

    ahrf_release, n = hrsa_ahrf.land_raw(cat, REL, csv_url=str(csv_with_extra),
                                         techdoc_url=str(techdoc_with_extra))
    out = capsys.readouterr().out
    assert "Fictional Vendor Database" in out
    assert "unknown_src_field_24" in out

    raw = rows(cat, "raw.hrsa__ahrf")
    assert "unknown_src_field_24" not in {r["column_name"] for r in raw}


def test_derives_curated_measures_with_correct_period_and_geo_vintage(cat):
    counts = hrsa_ahrf.ingest(cat, REL, csv_url=CSV, techdoc_url=TECHDOC)
    assert counts["raw.hrsa__ahrf"] == 5 * 21

    defs = {d["measure_id"]: d for d in rows(cat, "measure.definition",
                                             row_filter="source = 'AHRF'")}
    assert set(defs) == set(hrsa_ahrf.MEASURE_DEFINITIONS)
    assert defs["AHRF:FQHC"]["rate_basis"] == "count"
    assert defs["AHRF:UNINSURED_LT65_PCT"]["rate_basis"] == "percent"

    strata = rows(cat, "measure.stratum", row_filter="source = 'AHRF'")
    assert [s["stratum_id"] for s in strata] == ["AHRF:ALL"]

    obs = rows(cat, "measure.observation", row_filter="source = 'AHRF'")
    by_key = {(o["measure_id"], o["geo_id"], o["period_start"]): o for o in obs}

    # source_release is the AHRF EDITION, never the data year -- the three
    # time axes point (SPEC.md § Versioning): np_npi_24 and np_npi_23 both
    # carry source_release='2024-2025' despite describing different years.
    assert {o["source_release"] for o in obs} == {"2024-2025"}
    fqhc_24 = by_key[("AHRF:FQHC", "county:01001", "2024")]
    assert fqhc_24["period_start"] == fqhc_24["period_end"] == "2024"
    assert fqhc_24["source_release"] == "2024-2025"
    assert fqhc_24["value"] == 2.0
    assert fqhc_24["value_status"] == "reported"

    # geo_vintage is decided per FIPS, not per source column or year: the
    # SAME measure family (NP_NPI) lands 2010-vintage geography for the
    # legacy Connecticut county's 2023 data and 2020-vintage geography for
    # its 2024 data at the planning region -- because that's genuinely what
    # the real file does (Connecticut's transition reached this CMS feed
    # between the 2023 and 2024 data years).
    np_2023_legacy = by_key[("AHRF:NP_NPI", "county:09001", "2023")]
    assert np_2023_legacy["geo_vintage"] == 2010
    assert np_2023_legacy["value"] == 1003.0
    assert np_2023_legacy["value_status"] == "reported"

    np_2024_legacy = by_key[("AHRF:NP_NPI", "county:09001", "2024")]
    assert np_2024_legacy["geo_vintage"] == 2010
    assert np_2024_legacy["value"] is None
    assert np_2024_legacy["value_status"] == "not_available"

    np_2024_pr = by_key[("AHRF:NP_NPI", "county:09110", "2024")]
    assert np_2024_pr["geo_vintage"] == 2020
    assert np_2024_pr["value"] == 1862.0
    assert np_2024_pr["value_status"] == "reported"

    # Alaska's retired Valdez-Cordova is legacy (2010); its current
    # successor Chugach is current (2020).
    assert by_key[("AHRF:HPSA_PRIM_CARE", "county:02261", "2025")]["geo_vintage"] == 2010
    assert by_key[("AHRF:HPSA_PRIM_CARE", "county:02063", "2025")]["geo_vintage"] == 2020

    # a real reported 0 is a value, never suppressed or dropped
    zero = by_key[("AHRF:FQHC", "county:02063", "2024")]
    assert zero["value"] == 0.0
    assert zero["value_status"] == "reported"


def test_a_present_non_numeric_value_lands_not_available_not_reported(cat):
    """A cell that is present but doesn't parse as a number must not read as
    a numberless 'reported' row: value_status used to be derived from the
    sentinel-restored raw cell's presence (`r.value IS NOT NULL`) while
    `value` went through a separate `TRY_CAST`, so a present-but-non-numeric
    cell would have landed as value_status='reported' with value NULL --
    issue #148's finding in this module, and what
    merge.check_observations' reverse guard now catches for any source that
    regresses to it."""
    hrsa_ahrf.ingest(cat, REL, csv_url=MALFORMED_CSV, techdoc_url=TECHDOC)
    obs = rows(cat, "measure.observation",
              row_filter="source = 'AHRF' AND measure_id = 'AHRF:FQHC' "
                         "AND geo_id = 'county:01001' AND period_start = '2024'")
    assert len(obs) == 1
    assert obs[0]["value"] is None
    assert obs[0]["value_status"] == "not_available"
    # the OTHER period for the same county/measure, a real number, is untouched
    still_reported = rows(cat, "measure.observation",
                          row_filter="source = 'AHRF' AND measure_id = 'AHRF:FQHC' "
                                     "AND geo_id = 'county:01001' AND period_start = '2023'")
    assert still_reported[0]["value"] == 2.0
    assert still_reported[0]["value_status"] == "reported"


def test_rerun_is_idempotent(cat):
    hrsa_ahrf.ingest(cat, REL, csv_url=CSV, techdoc_url=TECHDOC)
    counts = hrsa_ahrf.ingest(cat, "2026.09", csv_url=CSV, techdoc_url=TECHDOC)
    assert counts["measure.observation"]["written"] == 0
    assert counts["measure.definition"] == len(hrsa_ahrf.MEASURE_DEFINITIONS)
    assert counts["measure.stratum"] == 1


def other_observation():
    return dict(source="OTHER", source_release="V0", measure_id="OTHER:x", geo_id="county:99999",
               geo_vintage=2020, period_start="2020", period_end="2020", stratum_id="OTHER:none",
               value=1.0, lower=None, upper=None, interval_level=None, numerator=None,
               denominator=None, value_status="reported", reliability_flag=None, trend=None)


def test_ahrf_does_not_retire_another_writer(cat):
    import pyarrow as pa
    other = pa.Table.from_pylist([other_observation()])
    merge.merge(cat, "measure.observation", other, REL, EqualTo("source", "OTHER"))

    hrsa_ahrf.ingest(cat, REL, csv_url=CSV, techdoc_url=TECHDOC)
    hrsa_ahrf.ingest(cat, "2026.09", csv_url=CSV, techdoc_url=TECHDOC)

    live_other = rows(cat, "measure.observation",
                      row_filter="source = 'OTHER' AND valid_to IS NULL")
    assert len(live_other) == 1
    assert live_other[0]["valid_from"] == REL


def test_every_column_is_documented(cat):
    hrsa_ahrf.ingest(cat, REL, csv_url=CSV, techdoc_url=TECHDOC)
    table = cat.load_table("raw.hrsa__ahrf")
    assert table.properties.get("comment")
    for f in table.schema().fields:
        assert f.doc, f"raw.hrsa__ahrf.{f.name} has no doc"
