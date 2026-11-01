"""EPA Map of Radon Zones: land both sheets whole -> derive one observation
per county resolved by name against geography.unit.

The fixture (tests/tiny_epa_radon_zones.xls), generated with `xlwt` (not a
project dependency -- see the PR body), mirrors the real file's shape:
  - a UNITED STATES / ALABAMA state-subtotal pair and blank trailer rows
    (never landed -- module docstring)
  - two ordinary counties (Autauga, Baldwin AL)
  - Anchorage, AK: the real file's own filtered/unfiltered zone-value
    mismatch (3 vs 2)
  - Wade Hampton, AK and Shannon, SD: pre-2015-recode names that still
    resolve against the 2010-vintage geography.unit fixture
  - Fairfield, CT: a legacy county name (not a 2022 planning region)
  - Miami-Dade, FL and Broomfield, CO: already-current names
  - Dona Ana, NM: the accent-dropped spelling, matched via strip_accents
    against the fixture's 'Doña Ana County'
  - Alexandria, VA: the VA-CITY anomalous row shape
  - Yellowstone National Park, MT: never resolves (not a real county) --
    seeded with no matching geography.unit row on purpose
"""

from pathlib import Path

import pyarrow as pa
import pytest
from pyiceberg.expressions import EqualTo

from cancerbasemap import epa_radon, merge

REL = "2026.09"
XLS = str(Path(__file__).parent / "tiny_epa_radon_zones.xls")

# (geo_id, level, fips, name, parent_geo_id) at GEO_VINTAGE -- enough of
# geography.unit for the fixture's rows to resolve, deliberately omitting
# anything for Yellowstone National Park.
STATES = [
    ("state:01", "state", "01", "Alabama", None),
    ("state:02", "state", "02", "Alaska", None),
    ("state:08", "state", "08", "Colorado", None),
    ("state:09", "state", "09", "Connecticut", None),
    ("state:12", "state", "12", "Florida", None),
    ("state:35", "state", "35", "New Mexico", None),
    ("state:46", "state", "46", "South Dakota", None),
    ("state:51", "state", "51", "Virginia", None),
]
COUNTIES = [
    ("county:01001", "county", "01001", "Autauga County", "state:01"),
    ("county:01003", "county", "01003", "Baldwin County", "state:01"),
    ("county:02020", "county", "02020", "Anchorage Municipality", "state:02"),
    ("county:02270", "county", "02270", "Wade Hampton Census Area", "state:02"),
    ("county:08014", "county", "08014", "Broomfield County", "state:08"),
    ("county:09001", "county", "09001", "Fairfield County", "state:09"),
    ("county:12086", "county", "12086", "Miami-Dade County", "state:12"),
    ("county:35013", "county", "35013", "Doña Ana County", "state:35"),
    ("county:46113", "county", "46113", "Shannon County", "state:46"),
    ("county:51510", "county", "51510", "Alexandria city", "state:51"),
]


def _unit(geo_id, level, fips, name, parent_geo_id):
    return dict(geo_id=geo_id, level=level, fips=fips, vintage=epa_radon.GEO_VINTAGE, name=name,
               parent_geo_id=parent_geo_id, aland_m2=None, awater_m2=None, centroid_lat=None,
               centroid_lon=None, geometry_uri=None)


@pytest.fixture(autouse=True)
def geography(cat):
    """Seeds geography.unit at GEO_VINTAGE with just what the fixture needs
    (radon.py reads it as an input, the same way epa_sdwis.py reads its own
    bundled ANSI reference table -- module docstring)."""
    rows = pa.Table.from_pylist([_unit(*a) for a in STATES + COUNTIES])
    merge.merge(cat, "geography.unit", rows, REL, EqualTo("vintage", epa_radon.GEO_VINTAGE))


def rows(cat, identifier, **kw):
    return cat.load_table(identifier).scan(**kw).to_arrow().to_pylist()


def test_raw_is_verbatim_and_whole(cat):
    n = epa_radon.land_raw(cat, REL, url=XLS)
    assert n == 11  # every real (numeric-Zone) row; state-subtotal/blank rows excluded

    raw = {r["county_state"]: r for r in rows(cat, "raw.epa__radon_zones")}
    assert set(raw) == {
        "Autauga, AL", "Baldwin, AL", "Anchorage, AK", "Wade Hampton, AK", "Shannon, SD",
        "Fairfield, CT", "Miami-Dade, FL", "Broomfield, CO", "Dona Ana, NM",
        "Alexandria, VA", "Yellowstone National Park, MT",
    }
    # the two-row state-subtotal pair (UNITED STATES, ALABAMA) carries no
    # numeric Zone and is never landed (module docstring)
    assert "UNITED STATES" not in raw and "ALABAMA" not in raw
    assert {r["landed_in"] for r in raw.values()} == {REL}

    # the real file's own filtered/unfiltered discrepancy, preserved in raw
    assert raw["Anchorage, AK"]["zone_unfiltered"] == 3.0
    assert raw["Anchorage, AK"]["zone_filtered"] == 2.0

    # VA independent city: the anomalous row shape lands verbatim too
    assert raw["Alexandria, VA"]["county_label"] == "Alexandria, VA"
    assert raw["Alexandria, VA"]["state"] == "VA-CITY"

    # re-landing replaces rather than appends (single, ever-only edition)
    epa_radon.land_raw(cat, REL, url=XLS)
    assert len(rows(cat, "raw.epa__radon_zones")) == 11


def test_a_changed_header_fails_before_landing(cat):
    bad = str(Path(__file__).parent / "tiny_epa_radon_zones_bad_header.xls")
    with pytest.raises(SystemExit, match="Zon"):
        epa_radon.land_raw(cat, REL, url=bad)


def test_derives_definition_stratum_and_observations(cat, capsys):
    counts = epa_radon.ingest(cat, REL, url=XLS)
    assert counts["raw.epa__radon_zones"] == 11

    defs = rows(cat, "measure.definition")
    assert len(defs) == 1
    assert defs[0]["measure_id"] == "EPA_RADON:zone"
    assert defs[0]["rate_basis"] == "index"
    assert "Zone 1" in defs[0]["doc"] and "Zone 3" in defs[0]["doc"]

    strata = rows(cat, "measure.stratum")
    assert len(strata) == 1 and strata[0]["stratum_id"] == "EPA_RADON:none"

    obs = {r["geo_id"]: r for r in rows(cat, "measure.observation", row_filter="source = 'EPA_RADON'")}
    # 10 of the 11 real (landed) rows resolve; Yellowstone National Park
    # never resolves (module docstring)
    assert len(obs) == 10
    assert set(obs) == {
        "county:01001", "county:01003", "county:02020", "county:02270", "county:08014",
        "county:09001", "county:12086", "county:35013", "county:46113", "county:51510",
    }
    # 'zone_filtered' is what the measure derives from, not 'zone_unfiltered'
    assert obs["county:02020"]["value"] == 2.0
    # pre-2015-recode names resolve directly against the 2010-vintage fixture,
    # landing under their OLD fips -- exactly what lets geography.alias (#26)
    # resolve them downstream, per the issue's own instruction
    assert obs["county:46113"]["value"] == 2.0  # Shannon County, SD
    assert obs["county:02270"]["value"] == 3.0  # Wade Hampton Census Area, AK
    # accent-insensitive match: 'Dona Ana' (source) -> 'Doña Ana County' (fixture)
    assert obs["county:35013"]["value"] == 2.0
    # VA independent city, resolved via the VA-CITY row shape
    assert obs["county:51510"]["value"] == 3.0
    for r in obs.values():
        assert r["source_release"] == "1993"
        assert r["period_start"] == r["period_end"] == "1993"
        assert r["geo_vintage"] == 2010
        assert r["value_status"] == "reported"

    # Yellowstone National Park is reported, not silently dropped
    err = capsys.readouterr().out
    assert "Yellowstone National Park, MT" in err
    assert "1/11" in err


def test_rerun_is_idempotent(cat):
    epa_radon.ingest(cat, REL, url=XLS)
    counts = epa_radon.ingest(cat, "2026.10", url=XLS)
    assert counts["measure.observation"]["written"] == 0
    assert counts["measure.observation"]["unchanged"] == 10
    assert counts["measure.definition"] == 1
    assert counts["measure.stratum"] == 1


def other_observation():
    return dict(source="OTHER", source_release="V0", measure_id="OTHER:x", geo_id="county:99999",
               geo_vintage=2020, period_start="2020", period_end="2020", stratum_id="OTHER:none",
               value=1.0, lower=None, upper=None, interval_level=None, numerator=None,
               denominator=None, value_status="reported", reliability_flag=None, trend=None)


def test_radon_does_not_retire_another_writer(cat):
    other = pa.Table.from_pylist([other_observation()])
    merge.merge(cat, "measure.observation", other, REL, EqualTo("source", "OTHER"))

    epa_radon.ingest(cat, REL, url=XLS)
    epa_radon.ingest(cat, "2026.10", url=XLS)

    live_other = rows(cat, "measure.observation",
                      row_filter="source = 'OTHER' AND valid_to IS NULL")
    assert len(live_other) == 1
    assert live_other[0]["valid_from"] == REL


def test_no_suppressed_cell_reads_as_a_number(cat):
    """SPEC.md Acceptance C: value_status is always 'reported' here (EPA
    publishes no suppression for this classification) and merge.check_observations
    still runs -- a fixture test of the invariant, not a claim this source
    ever suppresses."""
    epa_radon.ingest(cat, REL, url=XLS)
    obs = rows(cat, "measure.observation", row_filter="source = 'EPA_RADON'")
    assert all(r["value_status"] == "reported" for r in obs)
    assert all(r["value"] is not None for r in obs)


def test_every_column_is_documented(cat):
    epa_radon.ingest(cat, REL, url=XLS)
    table = cat.load_table("raw.epa__radon_zones")
    assert table.properties.get("comment")
    for f in table.schema().fields:
        assert f.doc, f"raw.epa__radon_zones.{f.name} has no doc"
