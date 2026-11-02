"""NCI catchment areas: land the shapefile whole -> derive catchment.center and
catchment.member by overlay on Census 2020 counties.

Fixtures are shapefiles written in the test (no network): four 1x1-degree
"counties" side by side (x 0-4, y 40-41) and catchments drawn against them.
"""

import zipfile

import duckdb
import pytest

from cancerbasemap import nci_catchment

REL = "2026.08"

# id, name, x range: catchment 1 is county 01001 exactly; 2 is county 01002 plus a
# 0.005 sliver of 01003; 3 is half of 01004; 4 is 2% of 01003; 5 is Mayo-style
# duplicate of name 1.
CATCHMENTS = [
    (1, "Whole County Center", 0, 1),
    (2, "Sliver Center", 1, 2.005),
    (3, "Half County Center", 3, 3.5),
    (4, "Edge Center", 2, 2.02),
    (5, "Whole County Center", 1, 2),
]


def box(x0, x1):
    return f"ST_GeomFromText('POLYGON(({x0} 40, {x1} 40, {x1} 41, {x0} 41, {x0} 40))')"


def write_zip(tmp_path, name, select):
    con = duckdb.connect()
    con.execute("INSTALL spatial")
    con.execute("LOAD spatial")
    out = tmp_path / name
    out.mkdir()
    con.execute(f"COPY ({select}) TO '{out / name}.shp' WITH (FORMAT GDAL, "
                f"DRIVER 'ESRI Shapefile', SRS '{'EPSG:4269' if name == 'counties' else 'EPSG:4326'}')")
    zpath = tmp_path / f"{name}.zip"
    with zipfile.ZipFile(zpath, "w") as z:
        for f in out.iterdir():
            z.write(f, f.name)
    return str(zpath)


@pytest.fixture
def catchment_zip(tmp_path):
    rows = " UNION ALL ".join(
        f"SELECT '{n}' AS name, {i} AS ID, 'Comprehensive Cancer Center' AS type, "
        f"'1 Main St\r\nTown, ST' AS address, 'Alabama' AS state, 'Sub-State' AS GeoDesc, "
        f"'https://x.example/{i}' AS url, 0 AS draworder, {box(x0, x1)} AS geom"
        for i, n, x0, x1 in CATCHMENTS)
    stats = " UNION ALL ".join(
        f"SELECT '{n}', {i}, NULL, NULL, NULL, NULL, NULL, 0, NULL::GEOMETRY"
        for i, n in ((100, "Total US Stat"), (101, "All Catchment Areas Stat")))
    return write_zip(tmp_path, "catchments", f"{rows} UNION ALL {stats}")


@pytest.fixture
def counties_zip(tmp_path):
    rows = " UNION ALL ".join(f"SELECT '0100{i + 1}' AS GEOID, {box(i, i + 1)} AS geom"
                              for i in range(4))
    return write_zip(tmp_path, "counties", rows)


def rows(cat, identifier, **kw):
    return cat.load_table(identifier).scan(**kw).to_arrow().to_pylist()


def test_raw_keeps_every_row_attribute_and_the_geometry(cat, catchment_zip):
    version, n = nci_catchment.land_raw(cat, REL, url=catchment_zip, retrieved_on="2026-08-01")
    assert (version, n) == ("2026-08-01", 7)

    raw = {r["ID"]: r for r in rows(cat, "raw.nci__catchment_areas")}
    assert set(raw) == {"1", "2", "3", "4", "5", "100", "101"}
    assert raw["1"]["address"] == "1 Main St\r\nTown, ST"  # verbatim
    assert raw["1"]["GeoDesc"] == "Sub-State" and raw["1"]["draworder"] == "0"
    assert raw["1"]["geometry_crs"] == "EPSG:4326"
    assert raw["100"]["geometry_wkb"] is None  # the stat rows are kept, geometry-less
    assert raw["1"]["geometry_wkb"][:1] == b"\x01"  # WKB, little-endian

    nci_catchment.land_raw(cat, REL, url=catchment_zip, retrieved_on="2026-08-01")
    assert len(rows(cat, "raw.nci__catchment_areas")) == 7  # replaced, not appended


def test_a_changed_column_set_fails_before_landing(cat, tmp_path):
    bad = write_zip(tmp_path, "catchments", "SELECT 'x' AS name, 1 AS ID, " + box(0, 1) + " AS geom")
    with pytest.raises(SystemExit, match="type"):
        nci_catchment.land_raw(cat, REL, url=bad)


def test_members_are_counties_at_least_one_percent_covered(cat, catchment_zip, counties_zip):
    counts = nci_catchment.ingest(cat, REL, catchment_zip, counties_zip, retrieved_on="2026-08-01")
    assert counts["raw.nci__catchment_areas"] == 7

    member = {(r["center_id"], r["geo_id"]): r for r in rows(cat, "catchment.member")}
    # whole county 1.0; a neighbour touching only along an edge is not a member
    assert member[("1", "county:01001")]["overlap_fraction"] == pytest.approx(1.0, abs=1e-4)
    assert ("1", "county:01002") not in member
    # 0.5% of 01003 is below the 1% floor; 01002 is whole
    assert set(k for k in member if k[0] == "2") == {("2", "county:01002")}
    # half a county keeps its true fraction
    assert member[("3", "county:01004")]["overlap_fraction"] == pytest.approx(0.5, abs=1e-3)
    # 2% of 01003 is above the floor
    assert member[("4", "county:01003")]["overlap_fraction"] == pytest.approx(0.02, abs=1e-3)
    assert {r["declared_by"] for r in member.values()} == {"NCI_OCC"}
    assert {r["geo_vintage"] for r in member.values()} == {2020}
    assert len(member) == 5


def test_centers_exclude_stat_rows_and_keep_duplicate_names_apart(cat, catchment_zip, counties_zip):
    nci_catchment.ingest(cat, REL, catchment_zip, counties_zip, retrieved_on="2026-08-01")
    center = {r["center_id"]: r for r in rows(cat, "catchment.center")}
    assert set(center) == {"1", "2", "3", "4", "5"}  # no 100/101
    assert center["1"]["name"] == center["5"]["name"]
    assert center["1"]["source"] == "NCI_OCC"
    assert center["1"]["designation_type"] == "Comprehensive Cancer Center"
    assert center["1"]["address"] == "1 Main St, Town, ST"
    assert center["1"]["notes"] is None


def test_hawaii_center_carries_the_pacific_note(cat, tmp_path, counties_zip):
    hi = write_zip(tmp_path, "catchments",
                   "SELECT 'University of Hawaii Cancer Center' AS name, 17 AS ID, 'Cancer Center' "
                   "AS type, 'x' AS address, 'Hawaii' AS state, 'Full-Inter-State' AS GeoDesc, "
                   f"'u' AS url, 0 AS draworder, {box(0, 1)} AS geom")
    nci_catchment.ingest(cat, REL, hi, counties_zip, retrieved_on="2026-08-01")
    assert "Palau" in rows(cat, "catchment.center")[0]["notes"]


def test_provenance_records_checksum_and_version(cat, catchment_zip, counties_zip):
    nci_catchment.ingest(cat, REL, catchment_zip, counties_zip, retrieved_on="2026-08-01")
    prov = {r["source"]: r for r in rows(cat, "provenance.release")}
    assert prov["nci_catchment"]["source_version"] == "2026-08-01"
    assert prov["nci_catchment"]["version_method"] == "retrieval_date"
    assert len(prov["nci_catchment"]["checksum"]) == 64
    assert prov["nci_catchment_counties"]["source_version"] == "2020"


def test_reingest_is_idempotent(cat, catchment_zip, counties_zip):
    nci_catchment.ingest(cat, REL, catchment_zip, counties_zip, retrieved_on="2026-08-01")
    again = nci_catchment.ingest(cat, REL, catchment_zip, counties_zip, retrieved_on="2026-08-01")
    assert again["catchment.member"]["unchanged"] == 5
    assert again["catchment.center"]["unchanged"] == 5
    assert len(rows(cat, "catchment.member")) == 5


def test_raw_columns_all_have_docs():
    from cancerbasemap import schemas
    for identifier in ("raw.nci__catchment_areas", "catchment.center", "catchment.member"):
        for f in schemas.TABLES[identifier].schema.fields:
            assert f.doc, f"{identifier}.{f.name} has no doc"
