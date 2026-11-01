"""Census Gazetteer: land three real layouts whole -> derive geography.unit.

Fixtures (tests/tiny_gazetteer_*.txt) are real excerpts, byte-for-byte, of the
2010, 2020 and 2026 national county/tract files and of state.txt: same header
padding, same fixed-width trailing spaces on data rows, same CT
county->planning-region transition, same Alaska antimeridian '+' longitude,
same Puerto Rico municipios. Nothing here touches the network.

Districts (#104): tiny_gazetteer_{cd,sldu,sldl}_{modern,current}.txt are the
same kind of real excerpt, for 2020 (modern) and 2026 (current) -- Alabama's
1st/2nd CD and Senate/House District 1/2, Wyoming's at-large CD, and North
Carolina's 3rd CD across all three known vintages (2020/2024/2026), which
really did redraw each time (confirmed against the live files 2026-09-19).
Tract -> district weights (a block-to-district relationship file) are
deferred to #25 -- see census_gazetteer.py's module docstring -- so there is
no crosswalk/BAF fixture or test here.
"""

from pathlib import Path

import pytest

from cancerbasemap import census_gazetteer as gz

REL = "2026.09"
FIX = Path(__file__).parent


def urls(year):
    suffix = {2010: "2010", 2020: "modern", 2026: "current"}[year]
    return (str(FIX / f"tiny_gazetteer_counties_{suffix}.txt"),
           str(FIX / f"tiny_gazetteer_tracts_{suffix}.txt"))


def district_urls(year):
    suffix = {2020: "modern", 2026: "current"}[year]
    return (str(FIX / f"tiny_gazetteer_cd_{suffix}.txt"),
           str(FIX / f"tiny_gazetteer_sldu_{suffix}.txt"),
           str(FIX / f"tiny_gazetteer_sldl_{suffix}.txt"))


STATE_URL = str(FIX / "tiny_gazetteer_state.txt")


def rows(cat, identifier, **kw):
    return cat.load_table(identifier).scan(**kw).to_arrow().to_pylist()


def test_raw_lands_verbatim_across_all_three_layouts(cat):
    for year in (2010, 2020, 2026):
        county_url, tract_url = urls(year)
        got_year, counts = gz.land_raw(cat, REL, year, county_url, tract_url)
        assert got_year == year
        assert counts == {"raw.census__gazetteer_counties": 5 if year != 2026 else 6,
                          "raw.census__gazetteer_tracts": 4}

    counties = {(r["geoid"], r["gazetteer_year"]): r for r in rows(cat, "raw.census__gazetteer_counties")}
    # 2010 carries POP10/HU10; later vintages land NULL for them
    al2010 = counties[("01001", 2010)]
    assert al2010["pop10"] == "54571" and al2010["hu10"] == "22135" and al2010["geoidfq"] is None
    al2020 = counties[("01001", 2020)]
    assert al2020["pop10"] is None and al2020["hu10"] is None
    # 2026 carries GEOIDFQ; earlier vintages land NULL for it
    al2026 = counties[("01001", 2026)]
    assert al2026["geoidfq"] == "0500000US01001" and al2026["pop10"] is None
    # every column is a raw string, unparsed, including the fixed-width padding
    assert al2010["aland_sqmi"] == "     594.436"
    # every landed vintage accumulates rather than overwriting the last
    assert {r["gazetteer_year"] for r in counties.values()} == {2010, 2020, 2026}

    # the CT county->planning-region transition lands as different geoids,
    # not a rewrite of the same row
    assert ("09001", 2020) in counties and ("09001", 2026) not in counties
    assert ("09110", 2026) in counties and ("09110", 2020) not in counties

    # re-landing the same vintage replaces it rather than appending
    gz.land_raw(cat, REL, 2010, *urls(2010))
    relanded = rows(cat, "raw.census__gazetteer_counties")
    assert sum(1 for r in relanded if r["gazetteer_year"] == 2010) == 5


def test_header_drift_fails_before_landing(cat, tmp_path):
    """A column Census adds or removes must fail loudly, not shift silently."""
    bad = tmp_path / "bad_counties.txt"
    real = (FIX / "tiny_gazetteer_counties_modern.txt").read_text().splitlines()
    bad.write_text("\n".join(["USPS\tGEOID\tEXTRA_COLUMN\t" + real[0].split("\t", 1)[1], *real[1:]]))
    with pytest.raises(SystemExit, match="matches no known layout"):
        gz.land_raw(cat, REL, 2020, str(bad), urls(2020)[1])


def test_manifest_records_a_release_number_not_a_retrieval_date(cat):
    gz.land_raw(cat, REL, 2020, *urls(2020))
    m = next(r for r in rows(cat, "provenance.release") if r["source"] == "census_gazetteer")
    assert (m["version_method"], m["source_version"]) == ("release_number", "2020")


def test_state_fips_lands_and_names_states(cat):
    n = gz.land_state_fips(cat, REL, STATE_URL)
    assert n == 4
    states = {r["state"]: r["state_name"] for r in rows(cat, "raw.census__state_fips")}
    assert states == {"01": "Alabama", "02": "Alaska", "09": "Connecticut", "72": "Puerto Rico"}


def test_state_fips_unreachable_warns_and_does_not_fail(cat, capsys):
    n = gz.land_state_fips(cat, REL, "http://localhost:1/does-not-exist")
    assert n == 0
    assert "unreachable" in capsys.readouterr().out


def test_derives_geography_unit_with_state_names(cat):
    gz.ingest(cat, REL, 2026, *urls(2026), state_url=STATE_URL)

    unit = {r["geo_id"]: r for r in rows(cat, "geography.unit")}
    nation = unit["nation:US"]
    assert (nation["level"], nation["vintage"], nation["parent_geo_id"]) == ("nation", 2026, None)

    ct = unit["state:09"]
    assert (ct["level"], ct["name"], ct["parent_geo_id"]) == ("state", "Connecticut", "nation:US")

    # Connecticut's 2022 move to planning regions: the 2026 vintage carries the
    # new geoids, parented under the state, not the old counties
    region = unit["county:09110"]
    assert (region["level"], region["name"], region["parent_geo_id"]) == (
        "county", "Capitol Planning Region", "state:09")
    assert region["aland_m2"] == pytest.approx(2660846205)
    assert "county:09001" not in unit

    tract = unit["tract:09110400101"]
    assert (tract["level"], tract["name"], tract["parent_geo_id"]) == (
        "tract", None, "county:09110")

    # Alaska's Aleutians West crosses the antimeridian: a '+' longitude parses
    al = unit["county:02016"]
    assert al["centroid_lon"] == pytest.approx(179.621188)

    pr_state = unit["state:72"]
    assert pr_state["name"] == "Puerto Rico"
    assert unit["county:72001"]["parent_geo_id"] == "state:72"


def test_state_name_falls_back_to_usps_without_state_fips(cat):
    """raw.census__state_fips never landed (unreachable) -> state name is the USPS code."""
    gz.ingest(cat, REL, 2020, *urls(2020), state_url="http://localhost:1/does-not-exist")
    unit = {r["geo_id"]: r for r in rows(cat, "geography.unit")}
    assert unit["state:09"]["name"] == "CT"


def test_a_later_vintage_never_retires_an_earlier_one(cat):
    """SPEC.md Acceptance B: loading a new vintage must not touch another's rows."""
    gz.ingest(cat, REL, 2020, *urls(2020), state_url=STATE_URL)
    before = {r["geo_id"] for r in rows(cat, "geography.unit") if r["vintage"] == 2020}

    gz.ingest(cat, "2026.10", 2026, *urls(2026), state_url=STATE_URL)

    after_2020 = {r["geo_id"] for r in rows(cat, "geography.unit")
                 if r["vintage"] == 2020 and r["valid_to"] is None}
    assert after_2020 == before
    after_2026 = {r["geo_id"] for r in rows(cat, "geography.unit")
                 if r["vintage"] == 2026 and r["valid_to"] is None}
    assert "county:09110" in after_2026 and "county:09001" not in after_2026


def test_rerun_is_a_noop(cat):
    gz.ingest(cat, REL, 2020, *urls(2020), state_url=STATE_URL)
    counts = gz.ingest(cat, "2026.10", 2020, *urls(2020), state_url=STATE_URL)
    assert counts["geography.unit"]["written"] == 0


def test_every_column_is_documented(cat):
    gz.ingest(cat, REL, 2020, *urls(2020), state_url=STATE_URL)
    for identifier in ("raw.census__gazetteer_counties", "raw.census__gazetteer_tracts",
                      "raw.census__state_fips"):
        table = cat.load_table(identifier)
        assert table.properties.get("comment"), identifier
        for f in table.schema().fields:
            assert f.doc, f"{identifier}.{f.name} has no doc"


# --- districts (#104) ---

def test_land_districts_lands_three_raw_tables_across_both_layouts(cat):
    for year in (2020, 2026):
        cd_url, sldu_url, sldl_url = district_urls(year)
        got_year, counts = gz.land_districts(cat, REL, year, cd_url, sldu_url, sldl_url)
        assert got_year == year
        assert counts == {"raw.census__gazetteer_cd": 10, "raw.census__gazetteer_sldu": 2,
                          "raw.census__gazetteer_sldl": 2}

    cd = {(r["geoid"], r["gazetteer_year"]): r for r in rows(cat, "raw.census__gazetteer_cd")}
    assert cd[("0101", 2020)]["geoidfq"] is None
    assert cd[("0101", 2026)]["geoidfq"] == "5001900US0101"
    # every column is a raw string, unparsed
    assert cd[("0101", 2020)]["aland"] == "15713789479"

    sldu = {r["geoid"]: r for r in rows(cat, "raw.census__gazetteer_sldu")
            if r["gazetteer_year"] == 2020}
    assert sldu["01001"]["name"] == "State Senate District 1"


def test_manifest_records_districts_under_their_own_source(cat):
    gz.land_districts(cat, REL, 2020, *district_urls(2020))
    m = next(r for r in rows(cat, "provenance.release") if r["source"] == "census_gazetteer_districts")
    assert (m["version_method"], m["source_version"]) == ("release_number", "2020")


def test_unknown_congress_year_skips_cd_only(cat, capsys):
    cd_url, sldu_url, sldl_url = district_urls(2020)
    year, counts = gz.land_districts(cat, REL, 1999, None, sldu_url, sldl_url)
    assert counts == {"raw.census__gazetteer_cd": 0, "raw.census__gazetteer_sldu": 2,
                      "raw.census__gazetteer_sldl": 2}
    assert "no known Congress number" in capsys.readouterr().out


def test_derives_geography_unit_for_districts(cat):
    gz.ingest(cat, REL, 2020, *urls(2020), state_url=STATE_URL)
    gz.ingest_districts(cat, REL, 2020, *district_urls(2020))

    unit = {r["geo_id"]: r for r in rows(cat, "geography.unit") if r["vintage"] == 2020}
    cd1 = unit["cd:0101"]
    assert (cd1["level"], cd1["name"], cd1["parent_geo_id"]) == ("cd", "Congressional District 1", "state:01")
    assert cd1["aland_m2"] == pytest.approx(15713789479)

    at_large = unit["cd:5600"]
    assert at_large["name"] == "Congressional District At Large"

    # 'ZZ' sentinel (water assigned to no district, real rows in CT/IL/NH/MI --
    # module docstring) falls back to the raw code rather than failing TRY_CAST
    unassigned = unit["cd:09ZZ"]
    assert unassigned["name"] == "Congressional District ZZ"

    sldu1 = unit["sldu:01001"]
    assert (sldu1["level"], sldu1["name"], sldu1["parent_geo_id"]) == (
        "sldu", "State Senate District 1", "state:01")
    sldl1 = unit["sldl:01001"]
    assert sldl1["name"] == "State House District 1"

    # the county/tract rows from the same vintage's earlier ingest() are
    # untouched -- one merge call carries both (module docstring, #118)
    assert unit["county:01001"]["name"] == "Autauga County"
    assert unit["state:01"]["level"] == "state"


def test_a_county_tract_only_ingest_is_unaffected_by_districts(cat):
    """No raw.census__gazetteer_cd/sldu/sldl landed for this vintage -> transform's
    NoSuchTableError guard leaves geography.unit exactly as before (#118-safe)."""
    counts = gz.ingest(cat, REL, 2020, *urls(2020), state_url=STATE_URL)
    assert counts["geography.unit"]["written"] > 0
    assert not any(r["level"] in ("cd", "sldu", "sldl") for r in rows(cat, "geography.unit"))


def test_a_later_district_vintage_never_retires_an_earlier_one(cat):
    """SPEC.md Acceptance B, for districts too: the real mid-decade NC/AL CD
    redraw between 2020 and 2026 lands as two coexisting vintages, and landing
    2026 must not touch 2020's rows -- the shared vintage=year merge scope
    (issue #118) is exactly what a second, separate merge call would break."""
    gz.ingest(cat, REL, 2020, *urls(2020), state_url=STATE_URL)
    gz.ingest_districts(cat, REL, 2020, *district_urls(2020))
    before = {r["geo_id"] for r in rows(cat, "geography.unit")
             if r["vintage"] == 2020 and r["valid_to"] is None}

    gz.ingest(cat, "2026.10", 2026, *urls(2026), state_url=STATE_URL)
    gz.ingest_districts(cat, "2026.10", 2026, *district_urls(2026))

    after_2020 = {r["geo_id"] for r in rows(cat, "geography.unit")
                 if r["vintage"] == 2020 and r["valid_to"] is None}
    assert after_2020 == before
    assert "cd:0101" in after_2020

    nc_2020 = next(r for r in rows(cat, "geography.unit")
                   if r["geo_id"] == "cd:3701" and r["vintage"] == 2020)
    nc_2026 = next(r for r in rows(cat, "geography.unit")
                   if r["geo_id"] == "cd:3701" and r["vintage"] == 2026)
    assert nc_2020["aland_m2"] != nc_2026["aland_m2"]  # the real redraw (module docstring)


def test_every_district_column_is_documented(cat):
    gz.land_districts(cat, REL, 2020, *district_urls(2020))
    for identifier in ("raw.census__gazetteer_cd", "raw.census__gazetteer_sldu",
                      "raw.census__gazetteer_sldl"):
        table = cat.load_table(identifier)
        assert table.properties.get("comment"), identifier
        for f in table.schema().fields:
            assert f.doc, f"{identifier}.{f.name} has no doc"
