"""EPA Superfund National Priorities List (NPL) sites -> Iceberg, kind='superfund'.

Upstream: EPA's "Superfund Data and Reports" page
(https://www.epa.gov/superfund/superfund-data-and-reports, checked
2026-09-18) points at the Superfund Enterprise Management System (SEMS).
Two anonymous, keyless ArcGIS REST Feature Services (no bulk file, no API
key -- queried directly, verified live 2026-09-18) cover it:

  - **"Superfund National Priorities List (NPL) Sites with Status
    Information"** (owner `whumbert_EPA`, item
    https://www.arcgis.com/home/item.html?id=c2b7cdff579c41bbba4898400aa38815):
    "National Priorities List (NPL) Sites with Status Information CSV file
    for the EPA's Where You Live page under the Superfund web area" -- the
    dataset issue #99 names ("NPL 'Where You Live'"). One row per site, every
    status (proposed / final / deleted), with the site's own real dates
    (Proposed_Date, Listing_Date, Deletion_Date, NOID_Date) and a
    Latitude/Longitude pair, but only a county *name* (text), not a FIPS
    code. 1,840 rows at check time, one query (see PAGE_SIZE below).
  - **"EPA Facility Registry Service - Superfund National Priorities List
    (SEMS NPL)"** (owner `EPA_GEO`, item
    https://www.arcgis.com/home/item.html?id=29c2d40eda9c4734bafa450d4d596c2f):
    FRS's own subset for NPL facilities, carrying `FIPS_CODE` (a real county
    FIPS, SPEC.md's preferred geography key) and `REGISTRY_ID` (FRS's
    cross-program facility id), but no listing/proposal/deletion dates.
    1,837 rows at check time.

**Both landed and joined, not one picked over the other.** Neither file
alone has what SPEC.md's issue asks for (real per-site dates AND a county
FIPS); joining `Site_EPA_ID` (status layer) to `PGM_SYS_ID` (FRS layer) --
both the same EPA Site/Facility ID string, e.g. 'CTD009717604' -- gives
both. Verified 2026-09-18: every `PGM_SYS_ID` in the live FRS file has a
matching `Site_EPA_ID` in the status file (1,837/1,837), and the status
file has exactly 3 ids the FRS file lacks entirely (e.g. 'NJD002173276',
American Cyanamid Co., NJ -- a real, currently-listed site simply not yet
FRS-synced). A further 8 FRS rows match by id but carry a NULL `FIPS_CODE`
themselves -- mostly territories with no county-equivalent FIPS at all
(American Samoa's 'Taputimu Farm', the Northern Mariana Islands' 'PCB
Warehouse'), plus a few mainland rows FRS simply has not coded (e.g. Iowa's
'Midwest Manufacturing Company'). A further 9 FRS rows carry a `FIPS_CODE`
that is neither NULL nor a real FIPS -- see "FIPS_CODE is not consistently
zero-padded, and is sometimes not a FIPS code at all" below. All 20/1,840
land in `facility.site` with `geo_id`/`geo_vintage` NULL rather than a
guessed county -- `transform` prints the real total, mirroring
epa_sdwis.py's "report the unmatched rate honestly" rule.

**Licence.** Both ArcGIS items' own `licenseInfo` (checked 2026-09-18): the
status layer states "Security Classification: Public - Data asset is or
could be made publicly available to all without restriction. Access
Constraints: None"; the FRS layer states "Unless otherwise specified, all
data produced by the U.S EPA is by default in the public domain and is not
subject to domestic copyright protection under 17 U.S.C. § 105." Both are
also independently U.S. Government works under 17 U.S.C. § 105, the same
basis as every other federal source in this repo (see epa_sdwis.py).

**No individual records.** Every field on both layers is site- or
facility-level (name, address, county, EPA/FRS ids, dates, coordinates) --
no clinician, resident or individual-owner data of any kind.

**No API key.** Both are anonymous, publicly queryable ArcGIS Feature
Services (`allowAnonymousToQuery: true`) -- no registration, token or
contact email of any kind, verified by querying both live and unauthenticated
2026-09-18.

**Version axis: retrieval date.** SEMS is a continuously-updated roster with
no edition label of its own -- the same shape as HRSA's and FDA's live
snapshots (hrsa_sites.py, fda_mqsa.py): `retrieved_on` is raw's version
column and `merge.manifest` is called with `method="retrieval_date"`.

**The real dates live in attributes_json, not source_release.** Unlike
HRSA_HC/FDA_MQSA, this source *does* carry real per-site dates (proposed /
listed / construction-completion / NOID / deletion) -- but SPEC.md's
`facility.site.source_release` is a table-wide "edition label" column, not a
per-row date, and NPL has no single edition label to put there. These are
exactly the "real dates" issue #19 (source_release vs. true event dates) is
about; they land in `attributes_json` (status/site_score/proposed_date/
listing_date/construction_completion_date/noid_date/deletion_date/
partial_deletion/region_id/county_name/registry_id) rather than forcing one
of them into source_release. `source_release` itself stays NULL here for
the same reason it is NULL for HRSA_HC/FDA_MQSA (issue #19): it is not part
of facility.site's business key, and an unchanged site must merge as
'unchanged' across retrieval dates rather than opening a fresh version
every ingest purely because the snapshot date moved.

**Geography vintage: 2010.** FRS's `FIPS_CODE` carries Connecticut's eight
legacy counties (verified 2026-09-18: '09001' Fairfield, '09003' Hartford,
'09005' Litchfield, ... -- never the nine 2022 planning regions), the same
marker epa_sdwis.py's `raw.sdwis__ref_ansi_areas` uses for its own
`GEO_VINTAGE = 2010` -- so this module matches that already-landed
`geography.unit` vintage rather than inventing a new one.

**FIPS_CODE is not consistently zero-padded, and is sometimes not a FIPS
code at all.** Verified 2026-09-18: some rows carry '9003' (Hartford
County, CT), others '01013'. Verified again 2026-09-19, against the live
file, that a handful are not a county FIPS in any padding: 8 rows carry a
2-letter state postal abbreviation glued to a 3-digit county code instead
of a numeric state FIPS (e.g. 'NJ017' for Hudson County, NJ -- the real
FIPS is '34017'; also 'MI149', 'FL079', 'MS035', 'IL119', 'ME019', 'KY157',
'NJ023'), and one ('S', Delaware's 'Georgetown North Groundwater') is not a
county code at all. `FIPS_CODE` is validated against `[0-9]{1,5}` before
`lpad(..., 5, '0')`; a value that fails this (including the 9 above) is
treated exactly like a NULL `FIPS_CODE` -- `geo_id` NULL, counted in the
unmatched diagnostic -- rather than reassembled from `STATE_CODE` plus the
trailing digits, per SPEC.md's "never fuzzy-matched" rule (the same
principle epa_sdwis.py's own ANSI-code validation follows).

**One point per site, even for a multi-county site.** A handful of real
sites (e.g. 'Triana/Tennessee River', whose `County` text reads "Limestone,
Madison, Morgan") span more than one county; FRS registers exactly one
`FIPS_CODE` for these (Morgan, in that example) and this module lands that
one point -- facility.site has no multi-geo_id shape (SPEC.md), and this is
the same single-point limitation every point facility source in this repo
has, not something this module computes around.

ponytail: only `Latitude`/`Longitude` (status layer, populated on every row)
are landed into facility.site.lat/lon, not FRS's own `LATITUDE83`/
`LONGITUDE83` (populated only on the 1,837 matched rows and, checked
2026-09-18, identical to 5 decimal places wherever both exist) -- no
geometry x/y is parsed from either service (`returnGeometry=false`) since
both already publish plain lat/lon attribute columns.

ponytail: the ArcGIS system/editing bookkeeping fields (`OBJECTID`,
`CreationDate`, `Creator`, `EditDate`, `Editor`, `ObjectId2` on the status
layer; `OBJECTID` on the FRS layer) are excluded from `COLUMNS`/
`FRS_COLUMNS` -- verified 2026-09-18 that every one of them is NULL on
every row of the live services; they are ArcGIS Online plumbing, not EPA
site data.
"""

import json
import urllib.request
from datetime import date

import duckdb
import pyarrow as pa
from pyiceberg.expressions import EqualTo

from . import merge

USER_AGENT = "cancerbasemap/1.0 (+https://github.com/seandavi/cancer-basemap)"
URL_STATUS = ("https://services.arcgis.com/cJ9YHowT8TU7DUyn/arcgis/rest/services/"
             "Superfund_National_Priorities_List_(NPL)_Sites_with_Status_Information/"
             "FeatureServer/0/query")
URL_FRS = ("https://services.arcgis.com/cJ9YHowT8TU7DUyn/arcgis/rest/services/"
          "FRS_INTERESTS_SEMS_NPL/FeatureServer/0/query")
GEO_VINTAGE = 2010
PAGE_SIZE = 2000  # both services' own maxRecordCount, verified 2026-09-18

# The status layer's real columns, minus the always-NULL ArcGIS bookkeeping
# fields (module docstring).
COLUMNS = (
    "Site_Name", "Site_Score", "Site_EPA_ID", "SEMS_ID", "SITS_ID", "Region_ID", "State",
    "City", "County", "Status", "Longitude", "Latitude", "Proposed_Date", "Listing_Date",
    "Construction_Completion_Date", "Construction_Completion_Number", "NOID_Date",
    "Deletion_Date", "Site_Listing_Narrative", "Site_Progress_Profile",
    "Notice_of_Data_Availability", "Proposed_FR_Notice", "Deletion_FR_Notice",
    "Final_FR_Notice", "NOID_FR_Notice", "Restoration_FR_Notice_Jumper_Page",
    "Site_has_had_a_Partial_Deletion",
)

# The FRS layer's real columns, minus OBJECTID (module docstring).
FRS_COLUMNS = (
    "REGISTRY_ID", "PRIMARY_NAME", "LOCATION_ADDRESS", "CITY_NAME", "COUNTY_NAME",
    "FIPS_CODE", "STATE_CODE", "POSTAL_CODE", "LATITUDE83", "LONGITUDE83", "HUC8_CODE",
    "ACCURACY_VALUE", "COLLECT_MTH_DESC", "REF_POINT_DESC", "CREATE_DATE", "UPDATE_DATE",
    "LAST_REPORTED_DATE", "FAC_URL", "PGM_SYS_ID", "PGM_SYS_ACRNM", "INTEREST_TYPE",
    "PROGRAM_URL", "PGM_REPORT_URL", "PUBLIC_IND", "ACTIVE_STATUS", "FEDERAL_AGENCY_NAME",
    "HUC_12", "FEDERAL_LAND_IND", "FED_FACILITY_CODE", "EPA_REGION_CODE", "KEY_FIELD",
)


def _fetch_features(url, columns, label):
    """Every row of one ArcGIS FeatureServer layer, attributes only (module
    docstring: no geometry parse needed -- both layers publish WGS84
    lat/lon as plain attribute columns).

    A non-http `url` (how the offline tests stay offline) is a local path to
    one page of the same JSON shape the live query returns
    (`{"features": [{"attributes": {...}}, ...]}`). The live endpoint is
    paged with `resultOffset` until a page returns fewer features than
    requested -- ArcGIS's own end-of-results signal.
    """
    if url.startswith("http"):
        fields = ",".join(columns)
        rows = []
        offset = 0
        while True:
            page_url = (f"{url}?f=json&where=1%3D1&outFields={fields}"
                       f"&returnGeometry=false&resultRecordCount={PAGE_SIZE}"
                       f"&resultOffset={offset}")
            req = urllib.request.Request(page_url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req) as r:
                page = json.load(r)
            if "error" in page:
                raise SystemExit(f"epa_superfund: {label} query failed: {page['error']}")
            feats = page["features"]
            rows.extend(f["attributes"] for f in feats)
            if len(feats) < PAGE_SIZE:
                break
            offset += len(feats)
    else:
        with open(url, encoding="utf-8") as f:
            rows = [feat["attributes"] for feat in json.load(f)["features"]]

    if not rows:
        raise SystemExit(f"epa_superfund: {label} at {url} yielded no rows")
    bad = next((r for r in rows if set(r) != set(columns)), None)
    if bad is not None:
        raise SystemExit(f"epa_superfund: {label} at {url} fields are not the declared "
                         f"ones; differs in {sorted(set(bad) ^ set(columns))}")
    return rows


def _land(cat, identifier, rows, columns, retrieved_on, release):
    con = duckdb.connect()
    con.register("t", pa.Table.from_pylist(rows))
    select = ", ".join(f'"{c}"' for c in columns)
    arrow = con.sql(f"""
        SELECT {select}, '{retrieved_on}' AS retrieved_on, '{release}' AS landed_in
        FROM t
    """).to_arrow_table()
    return merge.write(cat, identifier, arrow, EqualTo("retrieved_on", retrieved_on))


def land_raw(cat, release, status_url=None, frs_url=None, retrieved_on=None):
    """Phase 1: both layers, verbatim and whole, replaced per retrieval date."""
    retrieved_on = retrieved_on or date.today().isoformat()
    status_url = status_url or URL_STATUS
    frs_url = frs_url or URL_FRS

    n_status = _land(cat, "raw.superfund__npl_status", _fetch_features(status_url, COLUMNS, "NPL status"),
                     COLUMNS, retrieved_on, release)
    n_frs = _land(cat, "raw.superfund__npl_frs", _fetch_features(frs_url, FRS_COLUMNS, "FRS SEMS_NPL"),
                 FRS_COLUMNS, retrieved_on, release)
    merge.manifest(cat, release, "epa_superfund", status_url, n_status, version=retrieved_on,
                   method="retrieval_date")
    return retrieved_on, {"raw.superfund__npl_status": n_status, "raw.superfund__npl_frs": n_frs}


def transform(cat, release, retrieved_on):
    """Phase 2: facility.site, kind='superfund' -- status layer's real dates
    joined to FRS's county FIPS on the shared EPA Site/Facility ID (module
    docstring)."""
    con = duckdb.connect()
    con.register("status", cat.load_table("raw.superfund__npl_status").scan(
        row_filter=EqualTo("retrieved_on", retrieved_on)).to_arrow())
    con.register("frs", cat.load_table("raw.superfund__npl_frs").scan(
        row_filter=EqualTo("retrieved_on", retrieved_on)).to_arrow())

    # `fips`: FIPS_CODE validated to 1-5 ASCII digits before lpad, not trusted
    # blind. Verified 2026-09-19 against the live file: 9 rows carry something
    # else entirely -- 8 are a state postal abbreviation glued to a 3-digit
    # county code instead of a numeric state FIPS (e.g. 'NJ017' for Hudson
    # County, NJ -- the real FIPS is '34017'; 'MI149', 'FL079', ... same
    # shape), and one ('S', Delaware's 'Georgetown North Groundwater') is not
    # a county code at all. None is guessed or reassembled from STATE_CODE --
    # SPEC.md's "never fuzzy-matched" rule (epa_sdwis.py's own ANSI-code
    # validation is the precedent) -- they fail the digits-only check here
    # and fall into the same NULL-geo_id, reported-not-guessed path as an
    # unmatched or FIPS-less row.
    con.execute("""
        CREATE OR REPLACE TABLE frs2 AS
        SELECT *, CASE WHEN "FIPS_CODE" SIMILAR TO '[0-9]{1,5}' THEN lpad("FIPS_CODE", 5, '0') END
                   AS fips
        FROM frs
    """)

    # count(f.fips), not count(f."PGM_SYS_ID") or count(f."FIPS_CODE"): a real
    # FRS row can match and still carry no usable FIPS -- either NULL outright
    # (verified 2026-09-18 -- mostly territories with no county-equivalent
    # FIPS, e.g. American Samoa's 'Taputimu Farm') or malformed (see `fips`
    # above) -- and both cases must count as unmatched here too, or this print
    # (and the returned diagnostic) would understate how many sites get a
    # NULL geo_id -- the same "report it honestly" rule epa_sdwis.py follows
    # for its own unmatched rate.
    n_status, n_matched = con.sql("""
        SELECT count(*), count(f.fips)
        FROM status s LEFT JOIN frs2 f ON f."PGM_SYS_ID" = s."Site_EPA_ID"
    """).fetchone()
    unmatched = n_status - n_matched
    if unmatched:
        print(f"epa_superfund: {unmatched:,}/{n_status:,} NPL status rows have no usable "
             f"county FIPS (no matching FRS SEMS_NPL record, a matched one with a NULL or "
             f"malformed FIPS_CODE) and land with geo_id/geo_vintage NULL rather than a "
             f"guessed county.")

    site = con.sql(f"""
        SELECT 'EPA_SUPERFUND:' || s."Site_EPA_ID" AS facility_id, 'EPA_SUPERFUND' AS source,
               NULL::VARCHAR AS source_release, 'superfund' AS kind, s."Site_Name" AS name,
               concat_ws(', ', f."LOCATION_ADDRESS", coalesce(f."CITY_NAME", s."City"),
                        coalesce(f."STATE_CODE", s."State"), f."POSTAL_CODE") AS address,
               s."Latitude" AS lat, s."Longitude" AS lon,
               CASE WHEN f.fips IS NOT NULL THEN 'county:' || f.fips END AS geo_id,
               CASE WHEN f.fips IS NOT NULL THEN {GEO_VINTAGE} END AS geo_vintage,
               to_json({{
                   'status': s."Status",
                   'site_score': CAST(s."Site_Score" AS VARCHAR),
                   'proposed_date': s."Proposed_Date",
                   'listing_date': s."Listing_Date",
                   'construction_completion_date': s."Construction_Completion_Date",
                   'noid_date': s."NOID_Date",
                   'deletion_date': s."Deletion_Date",
                   'partial_deletion': s."Site_has_had_a_Partial_Deletion",
                   'region_id': CAST(s."Region_ID" AS VARCHAR),
                   'county_name': s."County",
                   'registry_id': f."REGISTRY_ID"
               }}) AS attributes_json
        FROM status s LEFT JOIN frs2 f ON f."PGM_SYS_ID" = s."Site_EPA_ID"
    """).to_arrow_table()

    counts = {"facility.site": merge.merge(cat, "facility.site", site, release,
                                           EqualTo("source", "EPA_SUPERFUND"))}
    if unmatched:
        counts["facility.site frs unmatched"] = unmatched
    return counts


def ingest(cat, release, status_url=None, frs_url=None, retrieved_on=None):
    retrieved_on, raw_counts = land_raw(cat, release, status_url, frs_url, retrieved_on)
    return {**raw_counts, **transform(cat, release, retrieved_on)}
