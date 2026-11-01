"""USDA ERS Food Access Research Atlas: land whole (two real layouts, one per
edition) -> derive the 4 LILA flags and 6 half-mile/1-mile share measures,
scoped as a writer to the stacked measure.observation table.

Fixtures:
  tests/tiny_ers_food_access_2019.csv -- a real byte-for-byte excerpt of the
    downloaded 2019 CSV: a plain metro tract (Autauga County, AL), a
    Connecticut tract on the legacy county FIPS prefix with the 'NULL'
    sentinel on its 1-mile measures (Fairfield County), and a
    low-income/low-access-flagged tract with a non-ASCII county name (Doña
    Ana County, NM).
  tests/tiny_ers_food_access_2015.xlsx -- xlsx is a zip-of-XML container, not
    a flat text format, so a byte slice isn't possible; this is a minimal
    valid xlsx built with the same 147-column real header and the real
    values for the same three tracts (see make_tiny_xlsx.py in the PR),
    demonstrating 2015's own quirks: CensusTract already zero-padded, and
    every share column a 0-1 fraction rather than a 0-100 percentage.
  tests/tiny_ers_food_access_sram_general.csv, _sd.csv -- real byte-for-byte
    excerpts of the downloaded 2025 SRAM files (issue #112) for the same
    Autauga County, AL tract as above plus a zero-population Calhoun County,
    AL tract (SRAM's blank-cell missing-value convention: `SD_SRAM_lapop1`
    is '0' but `SD_SRAM_lapop1share` is genuinely blank) and the same
    Doña Ana County, NM tract, now LILA-flagged and with the same stray
    Latin-1 byte as ers_ruca.py's 2020 CSV. `sram_zip` packages these into
    a zip the way upstream ships it (General + SD + Driving Distance +
    ReadMe), the shape `_sram_members` must pick apart.
"""

import zipfile
from pathlib import Path

import pyarrow as pa
import pytest
from pyiceberg.expressions import EqualTo

from cancerbasemap import ers_food_access, merge

REL = "2026.08"
CSV_2019 = str(Path(__file__).parent / "tiny_ers_food_access_2019.csv")
XLSX_2015 = str(Path(__file__).parent / "tiny_ers_food_access_2015.xlsx")
SRAM_GENERAL = Path(__file__).parent / "tiny_ers_food_access_sram_general.csv"
SRAM_SD = Path(__file__).parent / "tiny_ers_food_access_sram_sd.csv"


def sram_zip(tmp_path, general=SRAM_GENERAL, sd=SRAM_SD, name="sram.zip"):
    """A local zip shaped like upstream's real SRAM download: the two files
    this module lands plus a Driving Distance file and a ReadMe it must
    ignore (module docstring -- SRAM_MEMBERS)."""
    zpath = tmp_path / name
    with zipfile.ZipFile(zpath, "w") as z:
        z.write(general, arcname="SRAM General Tract Characteristics Data.csv")
        z.write(sd, arcname="SRAM Straight Line Distance Data.csv")
        z.writestr("SRAM Driving Distance Data.csv", "CensusTract20,State\n")
        z.writestr("SRAM Read Me.txt", "notes")
    return str(zpath)


def rows(cat, identifier, **kw):
    return cat.load_table(identifier).scan(**kw).to_arrow().to_pylist()


def test_raw_is_verbatim_and_whole_2019(cat):
    edition, n = ers_food_access.land_raw(cat, REL, edition="2019", url=CSV_2019)
    assert edition == "2019"
    assert n == 3

    raw = {r["CensusTract"]: r for r in rows(cat, "raw.ers__food_access")}
    assert set(raw) == {"1001020100", "9001010600", "35013000102"}
    assert {r["atlas_edition"] for r in raw.values()} == {"2019"}
    assert {r["landed_in"] for r in raw.values()} == {REL}
    assert raw["1001020100"]["County"] == "Autauga County"
    assert raw["35013000102"]["County"] == "Doña Ana County"  # non-ASCII, verbatim
    assert raw["1001020100"]["lapop1share"] == "99.19"  # unparsed string
    assert raw["9001010600"]["lapop1"] == "NULL"  # source's own sentinel, unparsed

    # re-landing the same edition replaces it rather than appending
    ers_food_access.land_raw(cat, REL, edition="2019", url=CSV_2019)
    assert len(rows(cat, "raw.ers__food_access")) == 3


def test_raw_is_verbatim_and_whole_2015(cat):
    """2015 ships as .xlsx (read via DuckDB's excel extension) and its
    header spells the population column POP2010, not Pop2010 -- landed
    under 2019's canonical spelling (module docstring)."""
    edition, n = ers_food_access.land_raw(cat, REL, edition="2015", url=XLSX_2015)
    assert edition == "2015"
    assert n == 3

    raw = {r["CensusTract"]: r for r in rows(cat, "raw.ers__food_access",
                                             row_filter=EqualTo("atlas_edition", "2015"))}
    assert set(raw) == {"01001020100", "09001010101", "35013000102"}
    assert raw["01001020100"]["Pop2010"] == "1912"  # POP2010 -> Pop2010
    assert raw["35013000102"]["County"] == "Dona Ana"  # 2015 drops the diacritic upstream
    # 2015's own scale: a 0-1 fraction, landed verbatim (unlike 2019's 0-100).
    assert raw["01001020100"]["lapop1share"] == "0.709979570989139"


def test_lands_from_a_local_zip_like_upstream_ships_it(cat, tmp_path):
    """Production URLs are zips containing the data file plus a ReadMe/
    VariableLookup sheet (2019) or the PDF documentation (2015); `_member`
    must find the one real data member and ignore the others."""
    zpath = tmp_path / "atlas.zip"
    with zipfile.ZipFile(zpath, "w") as z:
        z.write(CSV_2019, arcname="Food Access Research Atlas.csv")
        z.writestr("ReadMe.csv", "notes")
        z.writestr("VariableLookup.csv", "Field,LongName,Description\n")
    edition, n = ers_food_access.land_raw(cat, REL, edition="2019", url=str(zpath))
    assert (edition, n) == ("2019", 3)


def test_a_changed_header_fails_before_landing(cat, tmp_path):
    header = Path(CSV_2019).read_text(encoding="utf-8").splitlines()[0]
    bad = tmp_path / "bad.csv"
    bad.write_text(header.replace("Urban", "URBAN_FLAG") + "\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="header is not the declared 2019 layout"):
        ers_food_access.land_raw(cat, REL, edition="2019", url=str(bad))


def test_unknown_edition_raises(cat):
    with pytest.raises(SystemExit, match="unknown edition"):
        ers_food_access.land_raw(cat, REL, edition="1999", url=CSV_2019)


def test_derives_definition_stratum_and_observations_2019(cat):
    counts = ers_food_access.ingest(cat, REL, edition="2019", url=CSV_2019)
    assert counts["raw.ers__food_access"] == 3

    defs = {d["measure_id"]: d for d in rows(cat, "measure.definition")}
    # 4 LILA flags + 6 half-mile/1-mile share measures, times two id families
    # (FARA:* and FARA:SRAM_*, module docstring: transform always writes
    # both regardless of which single edition triggered this ingest).
    assert len(defs) == 20
    assert defs["FARA:LILATracts_1And10"]["rate_basis"] == "index"
    assert defs["FARA:lapop1share"]["rate_basis"] == "percent"
    assert defs["FARA:lapop1share"]["universe"] == "tract total population (2010 Census)"
    assert defs["FARA:lahunv1share"]["universe"] == "tract occupied housing units (2010 Census)"
    assert {d["source"] for d in defs.values()} == {"FARA"}
    assert {d["method"] for d in defs.values()} == {"derived"}

    strata = rows(cat, "measure.stratum")
    assert len(strata) == 1
    assert (strata[0]["stratum_id"], strata[0]["scheme"]) == ("FARA:ALL", "FARA_NONE")

    obs = {(r["geo_id"], r["measure_id"]): r
          for r in rows(cat, "measure.observation", row_filter="source = 'FARA'")}
    assert len(obs) == 30  # 3 tracts * 10 measures
    assert {r["geo_vintage"] for r in obs.values()} == {2010}
    assert {r["period_start"] for r in obs.values()} == {"2019"}

    # Autauga County: no LILA flag set, every share reported.
    autauga = "tract:01001020100"
    assert obs[(autauga, "FARA:LILATracts_1And10")]["value"] == 0.0
    assert obs[(autauga, "FARA:LILATracts_1And10")]["value_status"] == "reported"
    lapop1 = obs[(autauga, "FARA:lapop1share")]
    assert lapop1["value"] == pytest.approx(99.19)
    assert lapop1["numerator"] == pytest.approx(1896)
    assert lapop1["denominator"] == pytest.approx(1912)
    assert lapop1["value_status"] == "reported"

    # Doña Ana County: LILA-flagged (1And10/halfAnd10/1And20), non-ASCII name.
    dona_ana = "tract:35013000102"
    assert obs[(dona_ana, "FARA:LILATracts_1And10")]["value"] == 1.0
    assert obs[(dona_ana, "FARA:LILATracts_Vehicle")]["value"] == 0.0
    assert obs[(dona_ana, "FARA:lahunv1share")]["value"] == pytest.approx(0.58)

    # Fairfield County (CT, legacy county FIPS 09001): 'NULL' on its 1-mile
    # measures -- never a number, but its half-mile measures (real values in
    # the same row) still land as reported.
    fairfield = "tract:09001010600"
    onemile = obs[(fairfield, "FARA:lapop1share")]
    assert onemile["value"] is None
    assert onemile["value_status"] == "not_available"
    assert onemile["numerator"] is None
    halfmile = obs[(fairfield, "FARA:lapophalfshare")]
    assert halfmile["value"] == pytest.approx(0.62)
    assert halfmile["value_status"] == "reported"


def test_derives_observations_2015_on_the_percent_scale(cat):
    """2015's share columns are 0-1 fractions in the file (see
    test_raw_is_verbatim_and_whole_2015); SHARE_SCALE normalizes
    measure.observation.value to the same 0-100 percent scale as 2019."""
    ers_food_access.ingest(cat, REL, edition="2015", url=XLSX_2015)
    obs = {(r["geo_id"], r["measure_id"]): r
          for r in rows(cat, "measure.observation",
                        row_filter="source = 'FARA' AND source_release = '2015'")}
    autauga = obs[("tract:01001020100", "FARA:lapop1share")]
    assert autauga["value"] == pytest.approx(70.9979570989139)
    assert autauga["numerator"] == pytest.approx(1357.4809397312299)
    assert autauga["denominator"] == pytest.approx(1912)
    assert autauga["value_status"] == "reported"
    # 2015 has no missing sentinel for these columns (module docstring) --
    # every tract's 1-mile measures are 'reported', including this one,
    # which is 'NULL' (not_available) in the 2019 edition.
    fairfield_2019_tract = "tract:09001010101"
    assert obs[(fairfield_2019_tract, "FARA:lapop1share")]["value_status"] == "reported"


def test_unmapped_sentinel_raises(cat, tmp_path):
    """A non-numeric value that isn't the enumerated 'NULL' sentinel is a
    missing-value convention this module hasn't seen -- hard stop, not a
    silently-dropped row (AGENTS.md: no suppressed cell reads as a number,
    and unmapped sentinels are a hard stop)."""
    text = Path(CSV_2019).read_text(encoding="utf-8")
    assert text.count(",99.19,") == 1
    bad = tmp_path / "bad_sentinel.csv"
    bad.write_text(text.replace(",99.19,", ",N/A,"), encoding="utf-8")
    with pytest.raises(SystemExit, match="unmapped non-numeric value"):
        ers_food_access.ingest(cat, REL, edition="2019", url=str(bad))


def test_rerun_is_idempotent(cat):
    ers_food_access.ingest(cat, REL, edition="2019", url=CSV_2019)
    counts = ers_food_access.ingest(cat, "2026.09", edition="2019", url=CSV_2019)
    assert counts["measure.observation"]["written"] == 0
    assert counts["measure.observation"]["unchanged"] == 30
    assert counts["measure.definition"] == 20  # both id families -- see docstring
    assert counts["measure.stratum"] == 1


def other_observation():
    return dict(source="OTHER", source_release="V0", measure_id="OTHER:x", geo_id="county:99999",
               geo_vintage=2020, period_start="2020", period_end="2020", stratum_id="OTHER:none",
               value=1.0, lower=None, upper=None, interval_level=None, numerator=None,
               denominator=None, value_status="reported", reliability_flag=None, trend=None)


def test_fara_does_not_retire_another_writer(cat):
    """measure.observation is a stacked, multi-writer table (SPEC.md §
    Measures): the merge scope must be (source, source_release), not
    source_release alone, or one source's re-ingest would retire another
    source's rows."""
    other = pa.Table.from_pylist([other_observation()])
    merge.merge(cat, "measure.observation", other, REL, EqualTo("source", "OTHER"))

    ers_food_access.ingest(cat, REL, edition="2019", url=CSV_2019)
    ers_food_access.ingest(cat, "2026.09", edition="2019", url=CSV_2019)

    live_other = rows(cat, "measure.observation",
                      row_filter="source = 'OTHER' AND valid_to IS NULL")
    assert len(live_other) == 1
    assert live_other[0]["valid_from"] == REL


def test_every_column_is_documented(cat):
    ers_food_access.ingest(cat, REL, edition="2019", url=CSV_2019)
    table = cat.load_table("raw.ers__food_access")
    assert table.properties.get("comment")
    for f in table.schema().fields:
        assert f.doc, f"raw.ers__food_access.{f.name} has no doc"


# --- 2025 SRAM edition (issue #112) ---

def test_raw_is_verbatim_and_whole_sram(cat, tmp_path):
    """General Tract Characteristics and Straight-Line Distance, joined on
    CensusTract20, into their own table -- not the 147-column layout's
    (module docstring)."""
    edition, n = ers_food_access.land_raw(cat, REL, edition="2025", url=sram_zip(tmp_path))
    assert edition == "2025"
    assert n == 3

    raw = {r["CensusTract20"]: r for r in rows(cat, "raw.ers__food_access_sram")}
    assert set(raw) == {"1001020100", "1015981903", "35013001103"}
    assert {r["atlas_edition"] for r in raw.values()} == {"2025"}
    assert {r["landed_in"] for r in raw.values()} == {REL}
    # General's columns, verbatim (no aliasing onto Pop2010/OHU2010/CensusTract).
    assert raw["1001020100"]["POP2020"] == "1775"
    assert raw["1001020100"]["OHU2020"] == "646"
    assert raw["35013001103"]["County20"] == "Doña Ana County"  # Latin-1 byte, recovered
    # SD's columns, verbatim under USDA's SD_SRAM_ prefix.
    assert raw["1001020100"]["SD_SRAM_lapop1"] == "1080"
    assert raw["1001020100"]["SD_SRAM_lapop1share"] == "60.85"  # unparsed string
    assert raw["1015981903"]["SD_SRAM_lapop1"] == "0"
    assert raw["1015981903"]["SD_SRAM_lapop1share"] is None  # source's own blank sentinel
    assert raw["35013001103"]["SD_SRAM_LILATracts_1And10"] == "1"

    # re-landing replaces rather than appending
    ers_food_access.land_raw(cat, REL, edition="2025", url=sram_zip(tmp_path))
    assert len(rows(cat, "raw.ers__food_access_sram")) == 3


def test_a_changed_sram_header_fails_before_landing(cat, tmp_path):
    # bytes, not text: the real file has a stray Latin-1 byte (module docstring).
    data = SRAM_GENERAL.read_bytes()
    bad = tmp_path / "bad_general.csv"
    bad.write_bytes(data.replace(b"Urban", b"URBAN_FLAG"))
    with pytest.raises(SystemExit, match="General Tract Characteristics header is not"):
        ers_food_access.land_raw(cat, REL, edition="2025", url=sram_zip(tmp_path, general=bad))


def test_a_driving_distance_only_zip_fails_before_landing(cat, tmp_path):
    """`_sram_members` looks for the two files this module lands by exact
    name; a zip missing one (e.g. upstream drops/renames a member) is a hard
    stop, not a silently short join."""
    zpath = tmp_path / "incomplete.zip"
    with zipfile.ZipFile(zpath, "w") as z:
        z.write(SRAM_GENERAL, arcname="SRAM General Tract Characteristics Data.csv")
    with pytest.raises(SystemExit, match="has no member"):
        ers_food_access.land_raw(cat, REL, edition="2025", url=str(zpath))


def test_derives_definition_and_observations_sram(cat, tmp_path):
    counts = ers_food_access.ingest(cat, REL, edition="2025", url=sram_zip(tmp_path))
    assert counts["raw.ers__food_access_sram"] == 3

    defs = {d["measure_id"]: d for d in rows(cat, "measure.definition")}
    # Both id families are always written (module docstring: merge.write is a
    # flat scope overwrite, so a single-edition call can't leave the other
    # edition's definitions half-written).
    assert len(defs) == 20  # 10 FARA:* + 10 FARA:SRAM_*
    assert defs["FARA:SRAM_LILATracts_1And10"]["rate_basis"] == "index"
    assert "SNAP-authorized retailer" in defs["FARA:SRAM_LILATracts_1And10"]["doc"]
    assert defs["FARA:SRAM_lapop1share"]["universe"] == "tract total population (2020 Census)"
    assert "SNAP-authorized retailer" in defs["FARA:SRAM_lapop1share"]["doc"]
    # The 2019/2015 definitions are untouched -- still the large-retailer wording.
    assert defs["FARA:lapop1share"]["universe"] == "tract total population (2010 Census)"

    obs = {(r["geo_id"], r["measure_id"]): r
          for r in rows(cat, "measure.observation", row_filter="source_release = '2025'")}
    assert len(obs) == 30  # 3 tracts * 10 SRAM measures
    assert {r["geo_vintage"] for r in obs.values()} == {2020}
    assert {m for _, m in obs} == {f"FARA:SRAM_{c}" for c in
                                   (*ers_food_access.FLAG_MEASURES, *ers_food_access.SHARE_MEASURES)}

    autauga = obs[("tract:01001020100", "FARA:SRAM_lapop1share")]
    assert autauga["value"] == pytest.approx(60.85)
    assert autauga["numerator"] == pytest.approx(1080)
    assert autauga["denominator"] == pytest.approx(1775)  # POP2020, not Pop2010
    assert autauga["value_status"] == "reported"

    dona_ana = obs[("tract:35013001103", "FARA:SRAM_LILATracts_1And10")]
    assert dona_ana["value"] == 1.0

    # Calhoun County water tract: lapop1 itself is a real reported '0', but
    # lapop1share is genuinely blank (SRAM's own convention, module
    # docstring) -- the share lands NULL/not_available even though its own
    # numerator is available.
    calhoun = obs[("tract:01015981903", "FARA:SRAM_lapop1share")]
    assert calhoun["value"] is None
    assert calhoun["value_status"] == "not_available"
    assert calhoun["numerator"] == pytest.approx(0)


def test_reingesting_one_edition_does_not_erase_the_others_definitions(cat, tmp_path):
    ers_food_access.ingest(cat, REL, edition="2019", url=CSV_2019)
    ers_food_access.ingest(cat, REL, edition="2025", url=sram_zip(tmp_path))
    # Re-running only the 2019 edition must not wipe out FARA:SRAM_* --
    # measure.definition is a flat overwrite of the whole 'FARA' scope.
    ers_food_access.ingest(cat, "2026.09", edition="2019", url=CSV_2019)
    defs = {d["measure_id"] for d in rows(cat, "measure.definition")}
    assert "FARA:SRAM_lapop1share" in defs
    assert "FARA:lapop1share" in defs


def test_every_column_is_documented_sram(cat, tmp_path):
    ers_food_access.ingest(cat, REL, edition="2025", url=sram_zip(tmp_path))
    table = cat.load_table("raw.ers__food_access_sram")
    assert table.properties.get("comment")
    for f in table.schema().fields:
        assert f.doc, f"raw.ers__food_access_sram.{f.name} has no doc"
