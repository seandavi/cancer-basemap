"""NCI cancer center catchment areas -> Iceberg: the shapefile republished whole,
then `catchment.center` and `catchment.member` derived from it.

Upstream: https://gis.cancer.gov/ncicatchment/ (NCI GIS Portal for Cancer
Research). The shapefile zip is
https://gis.cancer.gov/ncicatchment/NCI_Catchment_Areas_2026.zip.

**Licence.** Produced by NCI staff, a U.S. Government work (17 U.S.C. Sec 105);
the portal and the dataset's metadata state no use limitation, and the owner
cleared reuse on 2026-11-02 (issue #195) with attribution. The portal asks
users to cite: DelNero PF, Buller ID, Jones RR, Tatalovich Z, Vanderpool RC,
Ciolino HP, Croyle RT. A National Map of NCI-Designated Cancer Center Catchment
Areas on the 50th Anniversary of the Cancer Centers Program. Cancer Epidemiol
Biomarkers Prev 2022;31(5):965-71, doi:10.1158/1055-9965.EPI-21-1230. Credit
National Cancer Institute as the source. The portal also says "these
visualization efforts are not NCI policy statements".

**Version axis: the zip's HTTP `Last-Modified` date.** The file name carries a
year (`..._2026`) but is not a release label, so `merge.manifest` records
method="http_last_modified" and the zip's SHA-256. The ETag is not stored
(`provenance.release` has no column for it; the checksum is the stronger
validator).

**Raw is the shapefile, whole.** `raw.nci__catchment_areas` has all 69 records
(the two summary rows 'Total US Stat' and 'All Catchment Areas Stat', which
carry no geometry, included) and every attribute column, plus `geometry_wkb`
in the shapefile's own CRS (EPSG:4326, recorded in `geometry_crs`) so the
release bundle republishes the shapefile. Values are text, as in the other
raw tables. DuckDB's `OGC_FID` row counter is not a shapefile attribute and is
not landed.

**Membership by overlay, county vintage 2020.** NCI publishes polygons, not
county lists (the 2025 file's FIPS list columns were removed upstream). The
portal draws on Census 2020 counties and 64 of the 67 polygons are exact
unions of whole 2020 counties (the 2026-11-01 review), so a county is a
member when the catchment covers at least 1% of its area (`overlap_fraction`
>= 0.01); below that is boundary sliver noise (cartographic vs TIGER edges,
NAD83 vs WGS84), above it the true fraction is kept so Memorial Sloan Kettering's
drawn circle (14 whole counties plus partial ones) and Norris's 43% of Orange
County, CA are not rounded into whole counties.

The counties are Census `cb_2020_us_county_500k` (public domain, 3,234 rows,
the same file the portal ships). It is read as a transient input and not
landed: `geography.unit` carries no polygons, and republishing 18 MB of Census
boundaries would be a second dataset in the bundle; its URL and SHA-256 go in
`provenance.release` under source `nci_catchment_counties`. Areas are computed
in EPSG:5070 (equal-area, so a ratio within one county is exact anywhere,
including Alaska and the Pacific).

**Hawai'i (ID 17)** is a multipart polygon that includes Pacific territories;
members are the Census county-equivalents it covers (the five Hawai'i counties
and the American Samoa, Guam and Northern Mariana Islands equivalents). Palau,
the Federated States of Micronesia and the Marshall Islands have no Census
county and so no member row; the center row says so.

The two summary rows are not centers and are left out of center/member.
"""

import hashlib
import tempfile
import urllib.request
from datetime import date
from email.utils import parsedate_to_datetime
from pathlib import Path

import duckdb
from pyiceberg.expressions import EqualTo

from . import lineage, merge

URL = "https://gis.cancer.gov/ncicatchment/NCI_Catchment_Areas_2026.zip"
URL_COUNTIES = "https://www2.census.gov/geo/tiger/GENZ2020/shp/cb_2020_us_county_500k.zip"
USER_AGENT = "cancerbasemap/1.0 (+https://github.com/seandavi/cancer-basemap)"
GEO_VINTAGE = 2020
SOURCE = "NCI_OCC"
MIN_OVERLAP = 0.01

# The shapefile's attribute columns, file order (geometry excluded).
COLUMNS = ("name", "ID", "type", "address", "state", "GeoDesc", "url", "draworder")

NOTE_HAWAII = ("Catchment includes Pacific territories; members are the Census county-equivalents "
               "it covers. Palau, the Federated States of Micronesia and the Marshall Islands "
               "have no Census county and so no member row.")


def _fetch(url):
    """(bytes, Last-Modified or None). A local path (tests) is read directly."""
    if not url.startswith("http"):
        return Path(url).read_bytes(), None
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req) as r:
        return r.read(), r.headers.get("Last-Modified")


def _spatial():
    con = lineage.connect()
    con.execute("INSTALL spatial")
    con.execute("LOAD spatial")
    return con


def land_raw(cat, release, url=None, retrieved_on=None):
    """Phase 1: the shapefile, verbatim and whole, replaced per version."""
    url = url or URL
    raw_bytes, last_modified = _fetch(url)
    checksum = hashlib.sha256(raw_bytes).hexdigest()
    if last_modified:
        version, method = parsedate_to_datetime(last_modified).date().isoformat(), "http_last_modified"
    else:
        version, method = retrieved_on or date.today().isoformat(), "retrieval_date"

    with tempfile.TemporaryDirectory() as tmp:
        zpath = Path(tmp) / "catchments.zip"
        zpath.write_bytes(raw_bytes)
        con = _spatial()
        shp = f"/vsizip/{zpath}"  # GDAL finds the one .shp inside the zip
        found = tuple(c[0] for c in con.sql(
            f"DESCRIBE SELECT * EXCLUDE (OGC_FID, geom) FROM ST_Read('{shp}')").fetchall())
        if found != COLUMNS:
            raise SystemExit(f"nci_catchment: {url} columns are not the declared ones; "
                             f"differ in {sorted(set(found) ^ set(COLUMNS))}")
        arrow = con.sql(f"""
            SELECT name, ID::VARCHAR AS ID, type, address, state, GeoDesc, url,
                   draworder::VARCHAR AS draworder, ST_AsWKB(geom) AS geometry_wkb,
                   ST_CRS(geom) AS geometry_crs,
                   '{version}' AS source_version, '{release}' AS landed_in
            FROM ST_Read('{shp}')
        """).to_arrow_table()
    if not arrow.num_rows:
        raise SystemExit(f"nci_catchment: {url} yielded no rows")

    n = merge.write(cat, "raw.nci__catchment_areas", arrow, EqualTo("source_version", version))
    merge.manifest(cat, release, "nci_catchment", url, n, version=version, method=method,
                   checksum=checksum)
    lineage.record(cat, release, "nci_catchment", None, {"raw.nci__catchment_areas": url})
    return version, n


def _land_counties(tmp, url):
    """The Census county file, downloaded to `tmp`; returns its GDAL path."""
    raw_bytes, _ = _fetch(url)
    zpath = Path(tmp) / "counties.zip"
    zpath.write_bytes(raw_bytes)
    return f"/vsizip/{zpath}", hashlib.sha256(raw_bytes).hexdigest()


def transform(cat, release, version, counties_url=None):
    """Phase 2: catchment.center and catchment.member, scoped to `version`'s
    raw rows and to this declarer."""
    counties_url = counties_url or URL_COUNTIES
    con = _spatial()
    lineage.load(con, cat, "raw", "raw.nci__catchment_areas",
                 row_filter=EqualTo("source_version", version))

    # The two summary rows ('Total US Stat', 'All Catchment Areas Stat') have no
    # geometry and are not centers.
    center_sql = f"""
        SELECT ID AS center_id, '{SOURCE}' AS source, name, type AS designation_type, state,
               GeoDesc AS geo_description,
               regexp_replace(address, '\\s*[\\r\\n]+\\s*', ', ', 'g') AS address, url,
               CASE WHEN ID = '17' THEN '{NOTE_HAWAII}' END AS notes
        FROM raw
        WHERE geometry_wkb IS NOT NULL
    """
    center = con.sql(center_sql).to_arrow_table()

    with tempfile.TemporaryDirectory() as tmp:
        shp, county_checksum = _land_counties(tmp, counties_url)
        # Both sides to EPSG:5070 (equal-area) before measuring; the Census file
        # is NAD83, the catchments WGS84 (metre-level difference, below MIN_OVERLAP's noise).
        member_sql = f"""
            WITH catchment AS (
                SELECT ID AS center_id,
                       ST_MakeValid(ST_Transform(ST_GeomFromWKB(geometry_wkb), geometry_crs,
                                                 'EPSG:5070', always_xy := true)) AS geom
                FROM raw WHERE geometry_wkb IS NOT NULL
            ),
            county AS (
                SELECT 'county:' || GEOID AS geo_id,
                       ST_MakeValid(ST_Transform(geom, 'EPSG:4269', 'EPSG:5070',
                                                 always_xy := true)) AS geom
                FROM ST_Read('{shp}')
            ),
            overlap AS (
                SELECT a.center_id, c.geo_id,
                       least(1.0, ST_Area(ST_Intersection(a.geom, c.geom)) / ST_Area(c.geom))
                           AS overlap_fraction
                FROM catchment a JOIN county c ON ST_Intersects(a.geom, c.geom)
            )
            SELECT center_id, geo_id, {GEO_VINTAGE} AS geo_vintage, '{SOURCE}' AS declared_by,
                   overlap_fraction
            FROM overlap
            WHERE overlap_fraction >= {MIN_OVERLAP}
        """
        member = con.sql(member_sql).to_arrow_table()
        n_counties = con.sql(f"SELECT count(*) FROM ST_Read('{shp}')").fetchone()[0]

    scope = EqualTo("source", SOURCE)
    result = {
        "catchment.center": merge.merge(cat, "catchment.center", center, release, scope),
        "catchment.member": merge.merge(cat, "catchment.member", member, release,
                                        EqualTo("declared_by", SOURCE)),
    }
    merge.manifest(cat, release, "nci_catchment_counties", counties_url, n_counties, version="2020",
                   method="release_number", checksum=county_checksum)
    lineage.record(cat, release, "nci_catchment", con, {
        "catchment.center": center_sql,
        "catchment.member": member_sql,
    })
    return result


def ingest(cat, release, url=None, counties_url=None, retrieved_on=None):
    version, n = land_raw(cat, release, url, retrieved_on)
    return {"raw.nci__catchment_areas": n, **transform(cat, release, version, counties_url)}
