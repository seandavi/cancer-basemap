"""EPA TRI Basic Data Files: land one reporting year whole -> derive
facility.site (kind='tri') and county-year on-site release totals.

Fixtures (tests/tiny_epa_tri_2023_data.csv, tiny_epa_tri_2022_data.csv) are
real byte-for-byte excerpts of the live 2023 and 2022 national downloads
(https://data.epa.gov/efservice/downloads/tri/mv_tri_basic_download/<year>_US/csv),
covering:
  - 94539NDCXX47533 (CONFLUENT MEDICAL TECHNOLOGIES, Alameda County CA):
    CARCINOGEN='YES', 5.000 lb -- the carcinogen-sum case.
  - 94587NTDST1295W (US PIPE & FOUNDRY CO LLC, Alameda County CA): two real
    rows (two chemicals, 5.680 and 26.120 lb, both CARCINOGEN='NO') -- the
    facility.site dedup case.
  - 9458WSNLXX7999A (MISSION VALLEY ROCK, Alameda County CA): present in
    both years (3.799 lb in 2023, 0.030 lb in 2022) -- the multi-year case.
  - 94606RMCPC33323 (CEMEX OAKLAND, Alameda County CA): FORM TYPE='A',
    0.000 lb -- the Form A zero case.
  - 27107CRNPR4501O (INGREDION INC, Forsyth County NC): CLASSIFICATION=
    'Dioxin', UNIT OF MEASURE='Grams', 3.170 -- the gram-to-pound conversion
    case.
  - 70075MRPHY2500E (VALERO REFINING, St. Bernard Parish LA): COUNTY carries
    its own 'PARISH' suffix -- the Louisiana-parish geography-match case.
  - 06497HMPFR292LO (HAMPFORD RESEARCH INC, Fairfield County CT): the
    unmatched-geography case (module docstring: this test's tiny
    geography.unit fixture deliberately omits Connecticut).
  - 94538NWNTD45500 (TESLA INC, Alameda County CA, 2022 only): 41176.000 lb
    -- present only in the older year, so it must NOT appear in facility.site
    (module docstring: facility.site always derives from the latest landed
    year).
"""

import csv
from pathlib import Path

import pyarrow as pa
import pytest
from pyiceberg.expressions import AlwaysTrue, EqualTo

from cancerbasemap import epa_tri, merge

REL = "2026.09"
DIR = Path(__file__).parent
URL_2023 = str(DIR / "tiny_epa_tri_2023_data.csv")
URL_2022 = str(DIR / "tiny_epa_tri_2022_data.csv")

GRAMS_TO_LB = epa_tri.GRAMS_TO_LB


def rows(cat, identifier, **kw):
    return cat.load_table(identifier).scan(**kw).to_arrow().to_pylist()


def _county(geo_id, fips, name, parent_geo_id):
    return dict(geo_id=geo_id, level="county", fips=fips, vintage=2020, name=name,
                parent_geo_id=parent_geo_id, aland_m2=None, awater_m2=None,
                centroid_lat=None, centroid_lon=None, geometry_uri=None)


def _seed_geo(cat):
    """A tiny, real geography.unit + raw.census__state_fips: Alameda County
    CA, Forsyth County NC and St. Bernard Parish LA -- Connecticut is present
    in state_fips (its state resolves) but has no county here, so Fairfield
    County CT (module docstring) is a real, reported miss, not a hole in the
    test setup."""
    geo = pa.Table.from_pylist([
        _county("county:06001", "06001", "Alameda County", "state:06"),
        _county("county:37067", "37067", "Forsyth County", "state:37"),
        _county("county:22087", "22087", "St. Bernard Parish", "state:22"),
    ])
    merge.merge(cat, "geography.unit", geo, REL, AlwaysTrue())

    sf = pa.Table.from_pylist([
        dict(state="06", stusab="CA", state_name="California", statens="1779778", landed_in=REL),
        dict(state="37", stusab="NC", state_name="North Carolina", statens="1027616", landed_in=REL),
        dict(state="22", stusab="LA", state_name="Louisiana", statens="1629543", landed_in=REL),
        dict(state="09", stusab="CT", state_name="Connecticut", statens="1779780", landed_in=REL),
    ])
    merge.write(cat, "raw.census__state_fips", sf, AlwaysTrue())


def test_raw_is_verbatim_and_whole(cat):
    year, n = epa_tri.land_raw(cat, REL, 2023, url=URL_2023, retrieved_on="2026-09-19")
    assert year == "2023"
    assert n == 8

    raw = rows(cat, "raw.epa__tri_basic")
    assert len(raw) == 8
    assert {r["TRIFD"] for r in raw} == {
        "94539NDCXX47533", "94587NTDST1295W", "06497HMPFR292LO", "70075MRPHY2500E",
        "94606RMCPC33323", "9458WSNLXX7999A", "27107CRNPR4501O",
    }
    assert {r["retrieved_on"] for r in raw} == {"2026-09-19"}
    assert {r["landed_in"] for r in raw} == {REL}

    # Re-landing the same year replaces it rather than appending.
    epa_tri.land_raw(cat, REL, 2023, url=URL_2023, retrieved_on="2026-09-19")
    assert len(rows(cat, "raw.epa__tri_basic")) == 8


def test_a_changed_header_fails_before_landing(cat, tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text('"1. YEAR","2. TRIFD"\n"2023","X0000001"\n')
    with pytest.raises(SystemExit, match="epa_tri"):
        epa_tri.land_raw(cat, REL, 2023, url=str(bad))


def test_derives_facility_site_and_county_measures(cat, capsys):
    _seed_geo(cat)
    counts = epa_tri.ingest(cat, REL, 2023, url=URL_2023, retrieved_on="2026-09-19")
    assert counts["raw.epa__tri_basic"] == 8

    site = rows(cat, "facility.site", row_filter=EqualTo("source", "TRI"))
    # 94587NTDST1295W's two chemical rows collapse into one facility.
    assert len(site) == 7
    assert all(r["kind"] == "tri" and r["source_release"] is None for r in site)

    us_pipe = next(r for r in site if r["facility_id"] == "94587NTDST1295W")
    assert us_pipe["geo_id"] == "county:06001"
    assert us_pipe["geo_vintage"] == 2020
    assert us_pipe["name"] == "US PIPE & FOUNDRY CO LLC"

    valero = next(r for r in site if r["facility_id"] == "70075MRPHY2500E")
    assert valero["geo_id"] == "county:22087"  # St. Bernard Parish, LA

    hampford = next(r for r in site if r["facility_id"] == "06497HMPFR292LO")
    assert hampford["geo_id"] is None and hampford["geo_vintage"] is None  # Fairfield, CT: unmatched

    defs = {r["measure_id"]: r for r in rows(cat, "measure.definition", row_filter=EqualTo("source", "TRI"))}
    assert set(defs) == {"TRI:onsite_release_total", "TRI:onsite_carcinogen_release_total"}
    assert defs["TRI:onsite_release_total"]["units"] == "lb"

    obs = {(r["measure_id"], r["geo_id"]): r
          for r in rows(cat, "measure.observation", row_filter=EqualTo("source", "TRI"))}
    assert len(obs) == 6  # 3 matched counties x 2 measures; Fairfield CT excluded

    alameda_total = 5.000 + 26.120 + 5.680 + 0.000 + 3.799  # every Alameda row (Form A contributes 0)
    r = obs[("TRI:onsite_release_total", "county:06001")]
    assert r["value"] == pytest.approx(alameda_total)
    assert r["source_release"] == "2023"
    assert r["value_status"] == "reported"

    # Only 94539NDCXX47533 (5.000 lb) is CARCINOGEN='YES' in Alameda.
    assert obs[("TRI:onsite_carcinogen_release_total", "county:06001")]["value"] == pytest.approx(5.000)

    # Dioxin/Grams -> pounds conversion, Forsyth County NC.
    forsyth_lb = 3.170 * GRAMS_TO_LB
    assert obs[("TRI:onsite_release_total", "county:37067")]["value"] == pytest.approx(forsyth_lb)
    assert obs[("TRI:onsite_carcinogen_release_total", "county:37067")]["value"] == pytest.approx(forsyth_lb)

    # St. Bernard Parish, LA -- COUNTY already carries 'PARISH' in the source text.
    assert obs[("TRI:onsite_release_total", "county:22087")]["value"] == pytest.approx(108.000)

    # No county:XXXXX row for Fairfield, CT.
    assert not any(gid is None for (_, gid) in obs)

    # The real, reported miss rate: 3 of 4 distinct (COUNTY, ST) pairs resolved.
    out = capsys.readouterr().out
    assert "3/4" in out and "75.0%" in out


def test_unparseable_release_total_is_not_available_not_a_silent_zero(cat, tmp_path):
    """A row whose ON-SITE RELEASE TOTAL fails to parse never happens in any
    real year checked (module docstring), but TRY_CAST is silent and sum()
    skips a NULL rather than propagating it -- so this is a synthetic fixture
    (the real 2023 excerpt with 94539NDCXX47533's release total corrupted to
    'N/A'), not a real byte-for-byte one, to exercise the guard directly."""
    _seed_geo(cat)
    with open(URL_2023, newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        col = header.index("65. ON-SITE RELEASE TOTAL")
        trifd = header.index("2. TRIFD")
        data = list(reader)
    for row in data:
        if row[trifd] == "94539NDCXX47533":
            assert row[col] == "5.000"
            row[col] = "N/A"
    bad = tmp_path / "bad_release_total.csv"
    with open(bad, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(data)

    epa_tri.ingest(cat, REL, 2023, url=str(bad), retrieved_on="2026-09-19")
    obs = {r["measure_id"]: r for r in rows(cat, "measure.observation", row_filter=EqualTo("source", "TRI"))
          if r["geo_id"] == "county:06001"}

    # Alameda's total AND carcinogen total both had 94539NDCXX47533 contribute
    # to them -- an unparseable row in either must not silently drop out of a
    # sum that still claims 'reported'.
    for measure_id in ("TRI:onsite_release_total", "TRI:onsite_carcinogen_release_total"):
        assert obs[measure_id]["value_status"] == "not_available"
        assert obs[measure_id]["value"] is None

    # A county untouched by the corrupted row is unaffected.
    forsyth = next(r for r in rows(cat, "measure.observation", row_filter=EqualTo("source", "TRI"))
                   if r["geo_id"] == "county:37067" and r["measure_id"] == "TRI:onsite_release_total")
    assert forsyth["value_status"] == "reported"
    assert forsyth["value"] == pytest.approx(3.170 * GRAMS_TO_LB)


def test_second_year_does_not_retire_facility_site_or_the_first_years_measures(cat):
    _seed_geo(cat)
    epa_tri.ingest(cat, REL, 2023, url=URL_2023, retrieved_on="2026-09-19")
    epa_tri.ingest(cat, "2026.10", 2022, url=URL_2022, retrieved_on="2026-10-01")

    site = rows(cat, "facility.site", row_filter=EqualTo("source", "TRI"))
    # facility.site always derives from the latest landed year (2023): still
    # 7 facilities, TESLA INC (2022-only) never appears.
    assert len(site) == 7
    assert "94538NWNTD45500" not in {r["facility_id"] for r in site}

    obs = rows(cat, "measure.observation", row_filter=EqualTo("source", "TRI"))
    assert {r["source_release"] for r in obs} == {"2023", "2022"}
    assert len(obs) == 6 + 2  # 2023's 3 counties x 2 measures, plus 2022's 1 county x 2

    by_key = {(r["source_release"], r["measure_id"]): r for r in obs
             if r["geo_id"] == "county:06001"}
    r2022 = by_key[("2022", "TRI:onsite_release_total")]
    assert r2022["value"] == pytest.approx(0.030 + 41176.000)
    assert by_key[("2022", "TRI:onsite_carcinogen_release_total")]["value"] == 0.0  # both rows CARCINOGEN='NO'

    # 2023's Alameda total is untouched by landing 2022.
    r2023 = by_key[("2023", "TRI:onsite_release_total")]
    assert r2023["value"] == pytest.approx(5.000 + 26.120 + 5.680 + 0.000 + 3.799)


def test_every_column_is_documented(cat):
    _seed_geo(cat)
    epa_tri.ingest(cat, REL, 2023, url=URL_2023, retrieved_on="2026-09-19")
    table = cat.load_table("raw.epa__tri_basic")
    assert table.properties.get("comment")
    for f in table.schema().fields:
        assert f.doc, f"raw.epa__tri_basic.{f.name} has no doc"
