"""CDC/ATSDR SVI: land whole -> derive percentile + component observations, two
real layout families coexisting without one clobbering the other's definitions.

Fixtures are real byte-for-byte excerpts of the actual downloaded CSVs (verified
2026-09-18 against svi.cdc.gov's real files):
  - tiny_svi_county_2018.csv (2014-family layout): Autauga County AL, Fairfield
    County CT (still the legacy county FIPS in 2018), Doña Ana County NM (non-ASCII
    name), and Rio Arriba County NM with a real partial suppression (POV/theme1/
    overall RPL_THEMES = -999, every other concept still reported).
  - tiny_svi_county_2020.csv / tiny_svi_county_2022.csv (2020-family layout):
    Autauga, a Connecticut county/planning-region row (09001 legacy in 2020, 09110
    planning region in 2022 -- the real geo_vintage switch), Doña Ana.
  - tiny_svi_tract_2022.csv (2020-family layout, tract grain): an Autauga County
    tract, a Connecticut (Capitol) planning-region tract, and a real fully/partially
    suppressed tract (Trigg County, KY 21221980100: poverty150 reported, no high
    school diploma and no vehicle suppressed, RPL_THEME1/2/4 and RPL_THEMES
    suppressed but RPL_THEME3 = 0.0).

Added for #92, same "real excerpt" rule, verified 2026-09-19:
  - tiny_svi_county_2000.csv / tiny_svi_tract_2000.csv (2000 layout, its own two-header-
    line real files verbatim): Autauga County AL, Fairfield County CT -- the real
    download has zero -999 rows anywhere (county or tract, checked directly), so
    suppression-sentinel handling for the 2000 family is covered by a separate,
    explicitly synthetic fixture built in-test (test_2000_suppression_is_synthetic_
    because_the_real_files_have_none) rather than faked into this real excerpt.
  - tiny_svi_county_2010.csv: Autauga County AL, Clearfield County PA (42033) with a
    real partial suppression (E_PCI/M_PCI = -999, cascading to RPL_THEME1/S_PL_THEME1
    = -999) while POV/NOHSDIP/AGE65/MINORITY/etc. and RPL_THEME2-4 stay reported.
  - tiny_svi_tract_2010.csv: an Autauga County tract, and Calhoun County AL tract
    9819.01 (01015981901) with the same real PCI-only suppression pattern plus a
    genuine 0.0 (not suppressed) on RPL_THEME3 and RPL_THEME4, and a genuine 0.0 (not
    suppressed) reported poverty rate.
"""

from pathlib import Path

import pyarrow as pa
import pytest
from pyiceberg.expressions import EqualTo

from cancerbasemap import cdc_svi, merge

REL = "2026.08"
FIX = Path(__file__).parent
COUNTY_2018 = str(FIX / "tiny_svi_county_2018.csv")
COUNTY_2020 = str(FIX / "tiny_svi_county_2020.csv")
COUNTY_2022 = str(FIX / "tiny_svi_county_2022.csv")
TRACT_2022 = str(FIX / "tiny_svi_tract_2022.csv")
COUNTY_2000 = str(FIX / "tiny_svi_county_2000.csv")
TRACT_2000 = str(FIX / "tiny_svi_tract_2000.csv")
COUNTY_2010 = str(FIX / "tiny_svi_county_2010.csv")
TRACT_2010 = str(FIX / "tiny_svi_tract_2010.csv")


def rows(cat, identifier, **kw):
    return cat.load_table(identifier).scan(**kw).to_arrow().to_pylist()


def test_raw_is_verbatim_and_whole(cat):
    edition, n = cdc_svi.land_raw(cat, REL, "2018", "county", url=COUNTY_2018)
    assert edition == "2018"
    assert n == 4

    raw = rows(cat, "raw.svi__county")
    assert len(raw) == 4
    assert {r["FIPS"] for r in raw} == {"01001", "09001", "35013", "35039"}
    assert {r["svi_edition"] for r in raw} == {"2018"}
    assert {r["landed_in"] for r in raw} == {REL}
    # unparsed: the real -999 sentinel lands as text, not a number
    rio_arriba = next(r for r in raw if r["FIPS"] == "35039")
    assert rio_arriba["EP_POV"] == "-999.0"
    assert rio_arriba["RPL_THEMES"] == "-999.0"
    # a column only the "2020" layout has is NULL for a 2014-family edition
    assert rio_arriba["STCNTY"] is None
    # non-ASCII name survives verbatim
    assert next(r for r in raw if r["FIPS"] == "35013")["LOCATION"] == "Doña Ana County, New Mexico"

    # re-landing the same edition replaces it rather than appending
    cdc_svi.land_raw(cat, REL, "2018", "county", url=COUNTY_2018)
    assert len(rows(cat, "raw.svi__county")) == 4


def test_a_changed_header_fails_before_landing(cat, tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("AFFGEOID,ST,STATE\n0500000US01001,01,ALABAMA\n")
    with pytest.raises(SystemExit, match="header is not the declared"):
        cdc_svi.land_raw(cat, REL, "2018", "county", url=str(bad))


def test_unknown_edition_or_tract_combo_rejected(cat):
    with pytest.raises(SystemExit, match="no known layout"):
        cdc_svi.land_raw(cat, REL, "2012", "county", url=COUNTY_2018)
    with pytest.raises(SystemExit, match="tract is only landed"):
        cdc_svi.land_raw(cat, REL, "2018", "tract", url=COUNTY_2018)


def test_2020_family_lands_into_the_same_union_table(cat):
    cdc_svi.land_raw(cat, REL, "2020", "county", url=COUNTY_2020)
    raw = {r["FIPS"]: r for r in rows(cat, "raw.svi__county",
                                       row_filter=EqualTo("svi_edition", "2020"))}
    assert set(raw) == {"01001", "09001", "35013"}
    # Connecticut is still the legacy county FIPS in 2020 (planning regions from 2022)
    assert raw["09001"]["STCNTY"] == "09001"
    # a column only the "2014" layout has is NULL for a 2020-family edition
    assert raw["01001"]["AFFGEOID"] is None
    assert raw["01001"]["EP_POV150"] is not None


def test_derives_definitions_stratum_and_observations(cat):
    counts = cdc_svi.ingest(cat, REL, "2018", "county", url=COUNTY_2018)
    assert counts["raw.svi__county"] == 4

    defs = {d["measure_id"]: d for d in rows(cat, "measure.definition", row_filter="source = 'SVI'")}
    assert len(defs) == 12  # 5 percentile + 7 component measures, 2014-family
    assert defs["SVI:RPL_THEMES:2014"]["rate_basis"] == "index"
    assert defs["SVI:RPL_THEMES:2014"]["method"] == "derived"
    assert defs["SVI:poverty"]["rate_basis"] == "percent"
    assert defs["SVI:poverty"]["method"] == "survey_direct"
    assert "SVI:poverty150" not in defs  # 2014-family never asserts the 2020 variant

    strata = rows(cat, "measure.stratum", row_filter="source = 'SVI'")
    assert [s["stratum_id"] for s in strata] == ["SVI:ALL"]

    obs = {(r["geo_id"], r["measure_id"]): r
           for r in rows(cat, "measure.observation", row_filter="source = 'SVI'")}
    assert obs[("county:01001", "SVI:RPL_THEMES:2014")]["value"] == pytest.approx(0.4354)
    assert obs[("county:01001", "SVI:RPL_THEMES:2014")]["geo_vintage"] == 2018  # the fixture's own edition year
    assert obs[("county:01001", "SVI:RPL_THEMES:2014")]["period_start"] == "2014"
    assert obs[("county:01001", "SVI:RPL_THEMES:2014")]["period_end"] == "2018"
    assert obs[("county:01001", "SVI:RPL_THEMES:2014")]["interval_level"] is None

    # SPEC.md Acceptance C: the real -999 sentinel never reads as a number, and it is
    # checked independently per measure -- Rio Arriba's poverty/theme1/overall are
    # suppressed but its other themes and components are not.
    assert obs[("county:35039", "SVI:poverty")]["value"] is None
    assert obs[("county:35039", "SVI:poverty")]["value_status"] == "not_available"
    assert obs[("county:35039", "SVI:RPL_THEME1:2014")]["value_status"] == "not_available"
    assert obs[("county:35039", "SVI:RPL_THEMES:2014")]["value_status"] == "not_available"
    assert obs[("county:35039", "SVI:RPL_THEME2:2014")]["value_status"] == "reported"
    assert obs[("county:35039", "SVI:no_hs_diploma")]["value_status"] == "reported"
    assert obs[("county:35039", "SVI:no_hs_diploma")]["value"] == pytest.approx(13.8)

    # MOE -> lower/upper at interval_level 0.90 (ACS convention)
    ok = obs[("county:01001", "SVI:poverty")]
    assert ok["interval_level"] == 0.90
    assert ok["lower"] == pytest.approx(ok["value"] - obs_moe(cat, "01001", "MP_POV"))


def obs_moe(cat, fips, column):
    raw = next(r for r in rows(cat, "raw.svi__county") if r["FIPS"] == fips)
    return float(raw[column])


def test_two_families_coexist_without_clobbering_definitions(cat):
    """SPEC.md / AGENTS.md: measure.definition is never replaced wholesale per source
    (issue #76) -- deriving the 2020-family after the 2014-family must not delete the
    2014-family's own theme/percentile definitions."""
    cdc_svi.ingest(cat, REL, "2018", "county", url=COUNTY_2018)
    cdc_svi.ingest(cat, REL, "2020", "county", url=COUNTY_2020)

    ids = {d["measure_id"] for d in rows(cat, "measure.definition", row_filter="source = 'SVI'")}
    assert "SVI:RPL_THEMES:2014" in ids
    assert "SVI:RPL_THEMES:2020" in ids
    assert "SVI:poverty" in ids
    assert "SVI:poverty150" in ids
    # stable across both families
    assert ids.issuperset({"SVI:no_hs_diploma", "SVI:uninsured", "SVI:no_vehicle",
                           "SVI:age_65_plus", "SVI:minority", "SVI:limited_english"})


def test_county_and_tract_combine_without_retiring_each_other(cat):
    """measure.observation's merge scope is (source, source_release), not per-level --
    landing county then tract (or vice versa) for the same edition must accumulate,
    never retire the other level's rows (module docstring)."""
    cdc_svi.ingest(cat, REL, "2022", "county", url=COUNTY_2022)
    cdc_svi.ingest(cat, REL, "2022", "tract", url=TRACT_2022)

    live = rows(cat, "measure.observation",
               row_filter="source = 'SVI' AND source_release = '2022' AND valid_to IS NULL")
    levels = {r["geo_id"].split(":")[0] for r in live}
    assert levels == {"county", "tract"}

    # re-deriving from county alone (e.g. a county-only re-ingest) must not retire tract
    cdc_svi.ingest(cat, "2026.09", "2022", "county", url=COUNTY_2022)
    live2 = rows(cat, "measure.observation",
                row_filter="source = 'SVI' AND source_release = '2022' AND valid_to IS NULL")
    assert {r["geo_id"].split(":")[0] for r in live2} == {"county", "tract"}
    assert len(live2) == len(live)

    # the 2022 geography switch: county FIPS 09110 is a planning region, vintage is the
    # edition's own year (2022), not a landed Gazetteer vintage
    ct = next(r for r in live2 if r["geo_id"] == "county:09110")
    assert ct["geo_vintage"] == 2022
    ct_tract = next(r for r in live2 if r["geo_id"].startswith("tract:09110"))
    assert ct_tract["geo_vintage"] == 2022

    # a real partially-suppressed tract row: poverty150 reported, two concepts and
    # three of the five percentile measures suppressed, one theme percentile is a
    # genuine 0.0 (not suppressed) -- 0.0 must not be mistaken for NULL/not_available.
    trigg = {r["measure_id"]: r for r in live2 if r["geo_id"] == "tract:21221980100"}
    assert trigg["SVI:poverty150"]["value"] == 100.0
    assert trigg["SVI:poverty150"]["value_status"] == "reported"
    assert trigg["SVI:no_hs_diploma"]["value_status"] == "not_available"
    assert trigg["SVI:RPL_THEME3:2020"]["value"] == 0.0
    assert trigg["SVI:RPL_THEME3:2020"]["value_status"] == "reported"
    assert trigg["SVI:RPL_THEMES:2020"]["value_status"] == "not_available"


def test_rerun_is_idempotent(cat):
    cdc_svi.ingest(cat, REL, "2018", "county", url=COUNTY_2018)
    counts = cdc_svi.ingest(cat, "2026.09", "2018", "county", url=COUNTY_2018)
    assert counts["measure.observation"]["written"] == 0
    assert counts["measure.observation"]["unchanged"] == 48  # 4 counties x 12 measures
    assert counts["measure.definition"] == 12
    assert counts["measure.stratum"] == 1


def other_observation():
    return dict(source="OTHER", source_release="V0", measure_id="OTHER:x", geo_id="county:99999",
               geo_vintage=2020, period_start="2020", period_end="2020", stratum_id="OTHER:none",
               value=1.0, lower=None, upper=None, interval_level=None, numerator=None,
               denominator=None, value_status="reported", reliability_flag=None, trend=None)


def test_svi_does_not_retire_another_writer(cat):
    other = pa.Table.from_pylist([other_observation()])
    merge.merge(cat, "measure.observation", other, REL, EqualTo("source", "OTHER"))

    cdc_svi.ingest(cat, REL, "2018", "county", url=COUNTY_2018)
    cdc_svi.ingest(cat, "2026.09", "2018", "county", url=COUNTY_2018)

    live_other = rows(cat, "measure.observation",
                      row_filter="source = 'OTHER' AND valid_to IS NULL")
    assert len(live_other) == 1
    assert live_other[0]["valid_from"] == REL


def test_every_column_is_documented(cat):
    cdc_svi.ingest(cat, REL, "2018", "county", url=COUNTY_2018)
    cdc_svi.ingest(cat, REL, "2022", "tract", url=TRACT_2022)
    cdc_svi.ingest(cat, REL, "2000", "county", url=COUNTY_2000)
    cdc_svi.ingest(cat, REL, "2000", "tract", url=TRACT_2000)
    cdc_svi.ingest(cat, REL, "2010", "county", url=COUNTY_2010)
    cdc_svi.ingest(cat, REL, "2010", "tract", url=TRACT_2010)
    for identifier in ("raw.svi__county", "raw.svi__tract", "raw.svi__county_2000",
                       "raw.svi__tract_2000", "raw.svi__county_2010", "raw.svi__tract_2010"):
        table = cat.load_table(identifier)
        assert table.properties.get("comment")
        for f in table.schema().fields:
            assert f.doc, f"{identifier}.{f.name} has no doc"


# ---------------------------------------------------------------------------
# #92: SVI 2000 and 2010, landed into their own dedicated tables (module docstring).

def test_2000_lands_verbatim_skipping_the_stale_header_line(cat):
    """The real 2000 file's line 1 doesn't match its own data (module docstring) --
    land_raw must skip it and land the real line 2 header/data, not line 1's names."""
    edition, n = cdc_svi.land_raw(cat, REL, "2000", "county", url=COUNTY_2000)
    assert edition == "2000"
    assert n == 2

    raw = rows(cat, "raw.svi__county_2000")
    assert {r["STCNTY"] for r in raw} == {"01001", "09001"}
    assert {r["svi_edition"] for r in raw} == {"2000"}
    # the real line-2 header's own columns, not line 1's stale "G1V1R"-style names
    assert "P_POV" in cat.load_table("raw.svi__county_2000").schema().column_names
    assert "G1V1R" not in cat.load_table("raw.svi__county_2000").schema().column_names
    # 2000's "STATE" holds the full name (unlike 2010's, see below) -- landed verbatim
    autauga = next(r for r in raw if r["STCNTY"] == "01001")
    assert autauga["STATE"] == "Alabama"
    assert autauga["ST"] == "01"  # 2-digit FIPS in 2000, NOT the USPS abbreviation
    # unparsed text, not silently cast
    assert autauga["P_POV"] == "0.1092"

    # 2000 county has no FIPS column at all -- STCNTY is the county-grain identifier
    assert "FIPS" not in cat.load_table("raw.svi__county_2000").schema().column_names

    # re-landing replaces rather than appends
    cdc_svi.land_raw(cat, REL, "2000", "county", url=COUNTY_2000)
    assert len(rows(cat, "raw.svi__county_2000")) == 2


def test_2010_state_column_is_the_fips_code_not_the_name(cat):
    """The exact collision documented in the module docstring for why 2010 isn't
    unioned into raw.svi__county: 2010's STATE column holds the 2-digit FIPS code,
    the opposite of every 2014+ layout's STATE (the state name)."""
    cdc_svi.land_raw(cat, REL, "2010", "county", url=COUNTY_2010)
    raw = {r["FIPS"]: r for r in rows(cat, "raw.svi__county_2010")}
    assert raw["01001"]["STATE"] == "01"
    assert raw["01001"]["ST"] == "AL"  # opposite of 2000's (ST, STATE) meaning above


def test_2000_and_2010_derive_stable_ids_alongside_family_suffixed_themes(cat):
    cdc_svi.ingest(cat, REL, "2000", "county", url=COUNTY_2000)
    cdc_svi.ingest(cat, REL, "2010", "county", url=COUNTY_2010)
    cdc_svi.ingest(cat, REL, "2018", "county", url=COUNTY_2018)  # a third, ACS family

    defs = {d["measure_id"]: d for d in rows(cat, "measure.definition", row_filter="source = 'SVI'")}
    # the six concepts shared verbatim across every family that asserts them (module
    # docstring) -- one shared definition, not one per family
    for concept_id in ("SVI:poverty", "SVI:no_hs_diploma", "SVI:no_vehicle",
                       "SVI:age_65_plus", "SVI:minority", "SVI:limited_english"):
        assert concept_id in defs
    # neither 2000 nor 2010 publishes an uninsured variable (module docstring); the
    # 2014-family ingest above is what would assert it, and this proves it's still the
    # only source of it
    assert defs["SVI:uninsured"]["method"] == "survey_direct"
    # theme/percentile ids are family-suffixed, one full set per family, none shared
    for family in ("2000", "2010", "2014"):
        assert f"SVI:RPL_THEMES:{family}" in defs
        for n in (1, 2, 3, 4):
            assert f"SVI:RPL_THEME{n}:{family}" in defs
    assert "SVI:RPL_THEMES" not in defs  # never unsuffixed


def test_2010_age65_and_minority_have_no_interval_but_poverty_does(cat):
    """2010's age_65_plus/minority are 2010 Census SF1 100%-count (no MOE at all);
    poverty is ACS 2006-2010 (has MOE) -- module docstring."""
    cdc_svi.ingest(cat, REL, "2010", "county", url=COUNTY_2010)
    obs = {(r["geo_id"], r["measure_id"]): r
           for r in rows(cat, "measure.observation", row_filter="source = 'SVI'")}

    age65 = obs[("county:42033", "SVI:age_65_plus")]
    assert age65["value"] == pytest.approx(0.1746)
    assert age65["interval_level"] is None
    assert age65["lower"] is None and age65["upper"] is None
    assert age65["period_start"] == "2010" and age65["period_end"] == "2010"

    minority = obs[("county:42033", "SVI:minority")]
    assert minority["interval_level"] is None
    assert minority["period_start"] == "2010" and minority["period_end"] == "2010"

    poverty = obs[("county:42033", "SVI:poverty")]
    assert poverty["value"] == pytest.approx(0.14687701)
    assert poverty["interval_level"] == 0.90
    assert poverty["lower"] == pytest.approx(0.14687701 - 0.01284473)
    assert poverty["upper"] == pytest.approx(0.14687701 + 0.01284473)
    assert poverty["period_start"] == "2006" and poverty["period_end"] == "2010"


def test_2010_theme1_suppressed_via_pci_does_not_suppress_other_themes(cat):
    """Real partial suppression (Clearfield County PA, 42033): E_PCI/M_PCI = -999
    cascades to RPL_THEME1 = not_available, but themes 2-4 (which don't depend on PCI)
    stay reported -- each theme is checked independently, same invariant as the
    2014/2020 fixtures' county/tract suppression tests."""
    cdc_svi.ingest(cat, REL, "2010", "county", url=COUNTY_2010)
    obs = {r["measure_id"]: r for r in rows(cat, "measure.observation",
           row_filter="source = 'SVI' AND geo_id = 'county:42033'")}
    assert obs["SVI:RPL_THEME1:2010"]["value_status"] == "not_available"
    assert obs["SVI:RPL_THEME1:2010"]["value"] is None
    assert obs["SVI:RPL_THEMES:2010"]["value_status"] == "not_available"
    assert obs["SVI:RPL_THEME2:2010"]["value_status"] == "reported"
    assert obs["SVI:RPL_THEME2:2010"]["value"] == pytest.approx(0.176)
    assert obs["SVI:RPL_THEME3:2010"]["value_status"] == "reported"
    assert obs["SVI:RPL_THEME4:2010"]["value_status"] == "reported"


def test_2010_tract_zero_values_are_not_mistaken_for_suppressed(cat):
    """Calhoun County AL tract 9819.01 (01015981901): the same PCI-only suppression as
    the county case above, plus a genuine 0.0 poverty rate and 0.0 RPL_THEME3/4 -- 0.0
    must read as reported, not as a missing/suppressed sentinel (SPEC.md Acceptance C)."""
    cdc_svi.ingest(cat, REL, "2010", "tract", url=TRACT_2010)
    obs = {r["measure_id"]: r for r in rows(cat, "measure.observation",
           row_filter="source = 'SVI' AND geo_id = 'tract:01015981901'")}
    assert obs["SVI:poverty"]["value"] == 0.0
    assert obs["SVI:poverty"]["value_status"] == "reported"
    assert obs["SVI:RPL_THEME1:2010"]["value_status"] == "not_available"
    assert obs["SVI:RPL_THEME3:2010"]["value"] == 0.0
    assert obs["SVI:RPL_THEME3:2010"]["value_status"] == "reported"
    assert obs["SVI:RPL_THEME4:2010"]["value"] == 0.0
    assert obs["SVI:RPL_THEME4:2010"]["value_status"] == "reported"


def test_2000_period_is_a_single_year_not_a_five_year_window(cat):
    """2000 draws on Census 2000 directly, no ACS at all (module docstring)."""
    cdc_svi.ingest(cat, REL, "2000", "county", url=COUNTY_2000)
    poverty = next(r for r in rows(cat, "measure.observation",
                   row_filter="source = 'SVI' AND geo_id = 'county:01001'")
                   if r["measure_id"] == "SVI:poverty")
    assert poverty["period_start"] == "2000"
    assert poverty["period_end"] == "2000"
    assert poverty["interval_level"] is None  # no MOE published for anything in 2000


def test_2000_county_and_tract_combine_like_every_other_edition(cat):
    """Same merge-scope accumulation behavior as the 2022 case already covered
    (module docstring: transform rebuilds from every landed level every time)."""
    cdc_svi.ingest(cat, REL, "2000", "county", url=COUNTY_2000)
    cdc_svi.ingest(cat, REL, "2000", "tract", url=TRACT_2000)
    live = rows(cat, "measure.observation",
               row_filter="source = 'SVI' AND source_release = '2000' AND valid_to IS NULL")
    assert {r["geo_id"].split(":")[0] for r in live} == {"county", "tract"}


def test_2000_suppression_is_synthetic_because_the_real_files_have_none(cat, tmp_path):
    """The real 2000 county/tract downloads (both checked whole, 2026-09-19) contain
    zero -999 sentinel rows -- unlike every other landed edition, there is no real
    excerpt to demonstrate suppression with. SPEC.md Acceptance C still requires the
    2000 family's suppression handling to be covered, so this builds one synthetic row
    (real header, fabricated -999 cells) rather than faking one into the "real excerpt"
    fixture above."""
    header_line1 = ",".join("X" for _ in cdc_svi.COUNTY_COLUMNS["2000"])  # stale, unread
    header_line2 = ",".join(cdc_svi.COUNTY_COLUMNS["2000"])
    values = {c: "0" for c in cdc_svi.COUNTY_COLUMNS["2000"]}
    values.update(ST="01", COU="099", STCNTY="01099", STATE="Alabama", ST_ABBR="AL",
                  COUNTY="Synthetic", P_POV="-999", PL_POV="-999", RPL_THEME1="-999",
                  RPL_THEMES="-999", P_AGE65="0.15", PL_AGE65="0.5", RPL_THEME2="0.5")
    row = ",".join(values[c] for c in cdc_svi.COUNTY_COLUMNS["2000"])
    synthetic = tmp_path / "synthetic_2000_county.csv"
    synthetic.write_text(f"{header_line1}\n{header_line2}\n{row}\n")

    cdc_svi.ingest(cat, REL, "2000", "county", url=str(synthetic))
    obs = {r["measure_id"]: r for r in rows(cat, "measure.observation",
           row_filter="source = 'SVI' AND geo_id = 'county:01099'")}
    assert obs["SVI:poverty"]["value"] is None
    assert obs["SVI:poverty"]["value_status"] == "not_available"
    assert obs["SVI:RPL_THEME1:2000"]["value_status"] == "not_available"
    assert obs["SVI:RPL_THEMES:2000"]["value_status"] == "not_available"
    assert obs["SVI:age_65_plus"]["value"] == pytest.approx(0.15)
    assert obs["SVI:age_65_plus"]["value_status"] == "reported"
    assert obs["SVI:RPL_THEME2:2000"]["value_status"] == "reported"


def test_ingest_reports_the_right_raw_table_key(cat):
    """2000/2010 land into raw.svi__{level}_{edition}, not the shared raw.svi__{level}
    (module docstring) -- ingest()'s summary dict must key on the table it actually
    wrote, not the shared name every other edition uses."""
    counts = cdc_svi.ingest(cat, REL, "2010", "county", url=COUNTY_2010)
    assert "raw.svi__county_2010" in counts
    assert "raw.svi__county" not in counts

    counts = cdc_svi.ingest(cat, REL, "2018", "county", url=COUNTY_2018)
    assert "raw.svi__county" in counts
    assert "raw.svi__county_2018" not in counts
