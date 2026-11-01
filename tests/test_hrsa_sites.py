"""HRSA health-center sites + primary-care HPSA: land whole -> derive
facility.site (a Type-2, retire-on-disappearance table) and county-level HPSA
measures.

Fixtures are real byte-for-byte excerpts of the live downloads (2026-09-18):
tests/tiny_hrsa_hc_sites.csv (a plain FQHC, a Connecticut planning-region
site, a Puerto Rico site with non-ASCII characters, a site with no published
coordinates, and a FQHC Look-Alike) and tests/tiny_hrsa_hpsa_pc.csv (two
Connecticut Designated geographic HPSAs; a HPSA spanning two counties with a
same-county duplicate tract row to prove the count is deduplicated; a
Withdrawn row with HRSA's masked 'XXXXX' FIPS; a Proposed For Withdrawal
row; and a Designated-but-population-type (non-geographic) row with a
non-ASCII name, to prove non-geographic HPSAs are excluded from the derived
county measures even when Designated).
"""

import json
from pathlib import Path

import pyarrow as pa
import pytest
from pyiceberg.expressions import EqualTo

from cancerbasemap import hrsa_sites, merge

REL = "2026.09"
HC_CSV = str(Path(__file__).parent / "tiny_hrsa_hc_sites.csv")
HPSA_CSV = str(Path(__file__).parent / "tiny_hrsa_hpsa_pc.csv")


def rows(cat, identifier, **kw):
    return cat.load_table(identifier).scan(**kw).to_arrow().to_pylist()


def test_raw_is_verbatim_and_whole(cat):
    retrieved_on, counts = hrsa_sites.land_raw(cat, REL, HC_CSV, HPSA_CSV, retrieved_on="2026-09-18")
    assert retrieved_on == "2026-09-18"
    assert counts == {"raw.hrsa__health_center_sites": 5, "raw.hrsa__hpsa_primary_care": 9}

    hc = rows(cat, "raw.hrsa__health_center_sites")
    assert len(hc) == 5
    assert {r["retrieved_on"] for r in hc} == {"2026-09-18"}
    assert {r["landed_in"] for r in hc} == {REL}
    ct_row = next(r for r in hc if r["BPHC Assigned Number"] == "BPS-H80-000090")
    assert ct_row["State and County Federal Information Processing Standard Code"] == "09170"

    hpsa = rows(cat, "raw.hrsa__hpsa_primary_care")
    assert len(hpsa) == 9
    # Withdrawn / masked FIPS carried verbatim, never dropped at landing
    withdrawn = next(r for r in hpsa if r["HPSA ID"] == "1358347079")
    assert withdrawn["HPSA Status"] == "Withdrawn"
    assert withdrawn["State and County Federal Information Processing Standard Code"] == "XXXXX"

    # re-landing the same retrieval date replaces it rather than appending
    hrsa_sites.land_raw(cat, REL, HC_CSV, HPSA_CSV, retrieved_on="2026-09-18")
    assert len(rows(cat, "raw.hrsa__health_center_sites")) == 5
    assert len(rows(cat, "raw.hrsa__hpsa_primary_care")) == 9


def test_a_changed_header_fails_before_landing(cat, tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("Health Center Type,Health Center Number\n")
    with pytest.raises(SystemExit, match="health center sites"):
        hrsa_sites.land_raw(cat, REL, hc_url=str(bad), hpsa_url=HPSA_CSV)


def test_derives_facility_site(cat):
    counts = hrsa_sites.ingest(cat, REL, HC_CSV, HPSA_CSV, retrieved_on="2026-09-18")
    assert counts["facility.site"]["written"] == 5

    sites = {r["facility_id"]: r for r in rows(cat, "facility.site")}
    assert set(sites) == {"BPS-H80-000078", "BPS-H80-000090", "BPS-H80-041998",
                          "BPS-H80-029419", "BPS-LAL-038982"}

    plain = sites["BPS-H80-000078"]
    assert plain["source"] == "HRSA_HC"
    # NULL, not the retrieval date: source_release isn't part of the business
    # key, and repeating the retrieval date here would make every unchanged
    # site look changed on every ingest (see hrsa_sites.py docstring). The
    # snapshot date lives in provenance.release / raw's own retrieved_on.
    assert plain["source_release"] is None
    assert plain["kind"] == "fqhc"
    assert plain["geo_id"] == "county:12031"
    assert plain["geo_vintage"] == 2020
    assert plain["lat"] == pytest.approx(30.32697002)
    assert plain["lon"] == pytest.approx(-81.64899457)
    attrs = json.loads(plain["attributes_json"])
    assert attrs == {
        "site_type": "Permanent",
        "operating_hours_reported": "true",
        "grantee_name": "I.M. SULZBACHER CENTER FOR THE HOMELESS, INC",
        "grantee_id": "H80CS00305",
        "status": "Active",
    }

    ct = sites["BPS-H80-000090"]
    assert ct["geo_id"] == "county:09170"  # leading-zero FIPS, 2022 planning region

    pr = sites["BPS-H80-041998"]
    assert "Ramón" in pr["name"] or "Ramón" in pr["address"]  # non-ASCII survives

    no_coords = sites["BPS-H80-029419"]
    assert no_coords["lat"] is None and no_coords["lon"] is None

    lookalike = sites["BPS-LAL-038982"]
    assert lookalike["kind"] == "fqhc"  # both FQHC and Look-Alike land as 'fqhc'


def test_facility_site_retires_dropped_and_versions_changed_sites_only(cat, tmp_path):
    """SPEC.md's facility history case, issue #38, with the issue #19 interim
    fix (source_release NULL for HRSA_HC): two snapshots on different
    retrieval dates where one site is dropped and one site's own data
    changes must produce exactly one retirement, exactly one new version --
    and every other, truly-unchanged site must stay on its original row
    (same valid_from, still live), not churn a fresh version just because
    the retrieval date moved."""
    hrsa_sites.ingest(cat, REL, HC_CSV, HPSA_CSV, retrieved_on="2026-09-18")
    live_day1 = {r["facility_id"] for r in rows(cat, "facility.site", row_filter="valid_to IS NULL")}
    assert live_day1 == {"BPS-H80-000078", "BPS-H80-000090", "BPS-H80-041998",
                         "BPS-H80-029419", "BPS-LAL-038982"}

    # Day 2's snapshot: BPS-H80-029419 (COSSMA San Lorenzo) has closed, and
    # BPS-H80-000078 (Duval) was renamed -- everything else is byte-identical.
    lines = Path(HC_CSV).read_text(encoding="utf-8").splitlines(keepends=True)
    lines = [l for l in lines if "BPS-H80-029419" not in l]
    lines = [l.replace('"Duval Family Health Center - Enterprise"',
                       '"Duval Family Health Center - Enterprise (Renamed)"') for l in lines]
    day2 = tmp_path / "day2.csv"
    day2.write_text("".join(lines), encoding="utf-8")

    counts = hrsa_sites.ingest(cat, "2026.10", str(day2), HPSA_CSV, retrieved_on="2026-09-19")

    # One retirement (closing) + one new version + its closing companion = 3
    # written rows; the three genuinely untouched sites are 'unchanged'.
    assert counts["facility.site"]["written"] == 3
    assert counts["facility.site"]["unchanged"] == 3
    assert counts["facility.site"]["retired"] == 1
    assert counts["facility.site"]["changed"] == 1
    assert counts["facility.site"]["superseded"] == 1

    live_day2 = {r["facility_id"] for r in rows(cat, "facility.site", row_filter="valid_to IS NULL")}
    assert live_day2 == {"BPS-H80-000078", "BPS-H80-000090", "BPS-H80-041998", "BPS-LAL-038982"}

    # The dropped site: exactly one row, now closed.
    dropped = rows(cat, "facility.site", row_filter="facility_id = 'BPS-H80-029419'")
    assert len(dropped) == 1
    assert dropped[0]["valid_to"] == "2026.10"

    # The changed site: exactly one new version, the old one closed at day 2.
    changed = rows(cat, "facility.site", row_filter="facility_id = 'BPS-H80-000078'")
    assert len(changed) == 2
    old, new = sorted(changed, key=lambda r: r["valid_from"])
    assert old["valid_from"] == REL and old["valid_to"] == "2026.10"
    assert new["valid_from"] == "2026.10" and new["valid_to"] is None
    assert new["name"] == "Duval Family Health Center - Enterprise (Renamed)"

    # Every genuinely untouched site: still exactly one row, still open from
    # day 1 -- no version churn just because the retrieval date moved.
    for facility_id in ("BPS-H80-000090", "BPS-H80-041998", "BPS-LAL-038982"):
        untouched = rows(cat, "facility.site", row_filter=f"facility_id = '{facility_id}'")
        assert len(untouched) == 1
        assert untouched[0]["valid_from"] == REL
        assert untouched[0]["valid_to"] is None


def test_derives_hpsa_county_measures(cat):
    counts = hrsa_sites.ingest(cat, REL, HC_CSV, HPSA_CSV, retrieved_on="2026-09-18")
    assert counts["measure.definition"] == 2
    assert counts["measure.stratum"] == 1

    defs = {d["measure_id"]: d for d in rows(cat, "measure.definition", row_filter="source = 'HPSA'")}
    assert set(defs) == {"HPSA:pc_count", "HPSA:pc_max_score"}
    assert defs["HPSA:pc_count"]["rate_basis"] == "count"
    assert defs["HPSA:pc_max_score"]["rate_basis"] == "index"

    obs = rows(cat, "measure.observation", row_filter="source = 'HPSA'")
    by_geo = {(r["geo_id"], r["measure_id"]): r for r in obs}

    # county:04013 is touched by two distinct HPSAs (Gila River, twice via a
    # duplicate tract row that must be deduplicated, and Surprise) -> count 2,
    # max score 19 (Gila River's, not Surprise's lower 11).
    assert by_geo[("county:04013", "HPSA:pc_count")]["value"] == 2.0
    assert by_geo[("county:04013", "HPSA:pc_max_score")]["value"] == 19.0
    # county:04021 is Gila River's second, cross-county component -> counts there too
    assert by_geo[("county:04021", "HPSA:pc_count")]["value"] == 1.0

    for geo_id, expect_score in (("county:09150", 8.0), ("county:09160", 9.0)):
        assert by_geo[(geo_id, "HPSA:pc_count")]["value"] == 1.0
        assert by_geo[(geo_id, "HPSA:pc_max_score")]["value"] == expect_score
        assert by_geo[(geo_id, "HPSA:pc_count")]["geo_vintage"] == 2020
        assert by_geo[(geo_id, "HPSA:pc_count")]["period_start"] == "2026-09-18"

    # Withdrawn (masked FIPS), Proposed For Withdrawal, and Designated-but-
    # population-type rows never surface as a county -- confirm no stray
    # county picked up their (non-existent or wrong) geography.
    seen_geo_ids = {geo_id for geo_id, _ in by_geo}
    assert "county:XXXXX" not in seen_geo_ids
    assert "county:55059" not in seen_geo_ids   # Kenosha: Proposed For Withdrawal
    assert "county:72083" not in seen_geo_ids   # Las Marías: Designated but HPSA Population

    merge.check_observations(pa.Table.from_pylist(obs).select(
        [f.name for f in pa.Table.from_pylist(obs).schema
         if f.name not in ("valid_from", "valid_to")]))


def test_rerun_is_idempotent(cat):
    hrsa_sites.ingest(cat, REL, HC_CSV, HPSA_CSV, retrieved_on="2026-09-18")
    counts = hrsa_sites.ingest(cat, REL, HC_CSV, HPSA_CSV, retrieved_on="2026-09-18")
    assert counts["facility.site"]["written"] == 0
    assert counts["facility.site"]["unchanged"] == 5
    assert counts["measure.observation"]["written"] == 0
    assert counts["measure.definition"] == 2
    assert counts["measure.stratum"] == 1


def other_site():
    return dict(facility_id="OTHER:1", source="OTHER", source_release="V0", kind="hospital",
               name="Other Hospital", address=None, lat=None, lon=None, geo_id="county:99999",
               geo_vintage=2020, attributes_json=None)


def test_hrsa_hc_does_not_retire_another_writer(cat):
    """facility.site is a stacked, multi-writer table (SPEC.md § Facilities):
    the merge scope must be `source`, not unscoped, or one source's re-ingest
    would retire another source's rows."""
    other = pa.Table.from_pylist([other_site()])
    merge.merge(cat, "facility.site", other, REL, EqualTo("source", "OTHER"))

    hrsa_sites.ingest(cat, REL, HC_CSV, HPSA_CSV, retrieved_on="2026-09-18")

    live_other = rows(cat, "facility.site", row_filter="source = 'OTHER' AND valid_to IS NULL")
    assert len(live_other) == 1
    assert live_other[0]["valid_from"] == REL


def test_every_column_is_documented(cat):
    hrsa_sites.ingest(cat, REL, HC_CSV, HPSA_CSV, retrieved_on="2026-09-18")
    for identifier in ("raw.hrsa__health_center_sites", "raw.hrsa__hpsa_primary_care", "facility.site"):
        table = cat.load_table(identifier)
        assert table.properties.get("comment")
        for f in table.schema().fields:
            assert f.doc, f"{identifier}.{f.name} has no doc"
