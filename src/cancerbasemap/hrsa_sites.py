"""HRSA health-center sites + primary-care HPSA designations -> Iceberg.

Upstream: https://data.hrsa.gov/data/download lists both as CSV downloads.
Direct URLs (stable, verified 2026-09-18 via HTTP HEAD -- both respond
`Last-Modified` as of the same day, confirming they are refreshed in place
daily rather than published as dated editions):
  - Health Center Service Delivery and Look-Alike Sites (FQHC sites):
    https://data.hrsa.gov/DataDownload/DD_Files/Health_Center_Service_Delivery_and_LookAlike_Sites.csv
  - Primary-care HPSA designations (dental/mental-health siblings exist as
    BCD_HPSA_FCT_DET_DH.csv / _MH.csv but are not landed here -- issue #38
    asks for primary care "at minimum"):
    https://data.hrsa.gov/DataDownload/DD_Files/BCD_HPSA_FCT_DET_PC.csv

**Licence.** HRSA's own Data Usage Terms & Conditions, shown on the download
page for each dataset (https://data.hrsa.gov/data/download, checked
2026-09-18): "Health Center Service Delivery Sites (HCSD)" (Data Published
by: HRSA, Bureau of Primary Health Care (BPHC)) and "Health Professional
Shortage Areas (HPSA)" (Data Published by: HRSA, Bureau of Health Workforce
(BHW), Division of Policy and Shortage Designation (DPSD)) both state
"Usage limitations: None". HRSA is also a federal agency, so both are
independently a U.S. Government work: "Data and content created by
government employees within the scope of their employment are not subject
to domestic copyright protection under 17 U.S.C. Sec 105. Government works
are by default in the U.S. Public Domain." (https://resources.data.gov/
open-licenses/, checked 2026-09-18).

**No individual-provider records.** Every column of both files was read
2026-09-18: site/grantee/organization names and addresses only (e.g. "Site
Name", "Health Center Name", "HPSA Name", "HPSA Component Name"); no column
names or holds an individual clinician.

**Version axis: retrieval date.** Neither file publishes an edition label --
each is a live snapshot HRSA overwrites in place -- so `retrieved_on` (this
ingest's UTC date) is the version column raw is scoped and replaced by, and
`merge.manifest` is called with `method="retrieval_date"` (SPEC.md's
versioning model already reserves this for exactly this case).

**Header quirk, both files.** The real header line ends in a stray trailing
comma, producing a spurious empty final column name, while every data row
has one fewer field than the header (verified 2026-09-18 against the live
downloads and reproduced byte-for-byte in the fixtures). `COLUMNS`/
`HPSA_COLUMNS` hold the real columns only; `_check_header` tolerates exactly
that one trailing empty field (mirrors census_gazetteer.py's trailing-
whitespace quirk) and `null_padding=true` in the read_csv call pads it with
NULL rather than shifting every real column over.

**facility_id.** HRSA's "BPHC Assigned Number" (e.g. 'BPS-H80-000078') is
the per-site id: verified unique across all 19,246 rows of the live file
(2026-09-18). "Health Center Location Identification Number" looks similar
but is a lookup code (only 3 distinct values file-wide) -- not a site id.

**Geography.** SPEC.md's facility.site calls for a tract-level geo_id;
HRSA's health-center file publishes only county FIPS, so `geo_id` here is
'county:'+FIPS -- a documented gap, not a tract lookup this module performs.
`GEO_VINTAGE = 2020`: the live file's Connecticut rows carry only the nine
2022 planning regions (09110-09190, never the eight legacy counties
09001-09015) and its Alaska rows carry only current census areas (e.g.
02063 Chugach, 02066 Copper River, never the retired 02261 Valdez-Cordova),
both markers of 2020-vintage Census geography (2026-09-18).

**attributes_json, not a map.** SPEC.md's facility.site declared `attributes
map<string,string>`. A DuckDB MAP value cast through Arrow into that Iceberg
schema aborts the process outright -- Arrow's C++ validator fails a check
("Map array keys array should have no nulls") that is not a catchable
Python exception, confirmed with a minimal repro 2026-09-18 -- so
facility.site.attributes_json is a JSON string column instead (this PR
edits SPEC.md's facility.site declaration to match).

**HPSA: geographic designations only.** Only 'Geographic HPSA' and 'High
Needs Geographic HPSA' rows carry a usable county FIPS on every row;
'HPSA Population', 'Federally Qualified Health Center', its Look-Alike
sibling, 'Rural Health Clinic', 'Correctional Facility', 'Other Facility'
and the IHS/Tribal designation type are population-group or facility
designations that don't fit geo_id (SPEC.md's own note on issue #38) -- they
land in raw but are not derived. A HPSA with sub-county components (Census
Tract / County Subdivision) repeats one row per component, all sharing the
same county FIPS; `transform` deduplicates on (HPSA ID, FIPS) before
counting so a multi-component HPSA counts once per county, not once per row.

ponytail: only two measures are derived from HPSA -- a per-county count of
currently-designated ('HPSA Status' = 'Designated') primary-care geographic
HPSAs and their max HPSA Score -- rather than reconstructing HRSA's own
shortage-index math (SPEC.md non-goal: republish, don't compute). period is
the retrieval date, since HRSA HPSA designations are a live roster with no
published period of their own.

ponytail: a currently-Designated geographic HPSA with a masked/placeholder
FIPS ('XXXXX'/'XXX', seen only on Withdrawn / Proposed For Withdrawal rows
as of 2026-09-18) is silently excluded from the county aggregation rather
than raising -- that combination doesn't exist in the real file today, and
would be a HRSA data-quality anomaly if it appeared, not something this
ingest should hard-stop on.

**facility.site.source_release is NULL for HRSA_HC.** facility.site's
business key is (facility_id, source) -- source_release is deliberately
excluded from it (issue #19). An earlier version of this module set
source_release to the retrieval date, which -- since merge.merge diffs every
non-key column -- made every unchanged site open a fresh Type-2 version on
every single ingest: 19k rows of churn per run for zero real change. HRSA_HC
writes NULL there instead: the snapshot date is already recorded in
provenance.release and in raw.hrsa__health_center_sites.retrieved_on, so an
unchanged site now merges as 'unchanged' across retrieval dates the way
RUCC/PLACES rows do, and a site's *actual* content change still opens a new
version. This is an interim fix under issue #19, not a resolution of it --
see merge.py's and schemas.py's own notes on that.
"""

import urllib.request
from datetime import date

import duckdb
from pyiceberg.expressions import And, EqualTo

from . import merge

USER_AGENT = "cancerbasemap/1.0 (+https://github.com/seandavi/cancer-basemap)"
URL_HC_SITES = ("https://data.hrsa.gov/DataDownload/DD_Files/"
               "Health_Center_Service_Delivery_and_LookAlike_Sites.csv")
URL_HPSA_PC = "https://data.hrsa.gov/DataDownload/DD_Files/BCD_HPSA_FCT_DET_PC.csv"
GEO_VINTAGE = 2020

# The health-center file's real 55 columns, file order (see module docstring
# for the trailing spurious 56th).
COLUMNS = (
    "Health Center Type", "Health Center Number", "BHCMIS Organization Identification Number",
    "BPHC Assigned Number", "Site Name", "Site Address", "Site City", "Site State Abbreviation",
    "Site Postal Code", "Site Telephone Number", "Site Web Address", "Operating Hours per Week",
    "Health Center Location Setting Identification Number",
    "Health Center Service Delivery Site Location Setting Description",
    "Health Center Status Identification Number", "Site Status Description",
    "FQHC Site Medicare Billing Number", "FQHC Site NPI Number",
    "Health Center Location Identification Number", "Health Center Location Type Description",
    "Health Center Type Identification Number", "Health Center Type Description",
    "Health Center Operator Identification Number", "Health Center Operator Description",
    "Health Center Operating Schedule Identification Number",
    "Health Center Operational Schedule Description", "Health Center Operating Calendar Surrogate Key",
    "Health Center Operating Calendar", "Site Added to Scope this Date", "Health Center Name",
    "Health Center Organization Street Address", "Health Center Organization City",
    "Health Center Organization State", "Health Center Organization ZIP Code",
    "Grantee Organization Type Description", "Geocoding Artifact Address Primary X Coordinate",
    "Geocoding Artifact Address Primary Y Coordinate", "U.S. - Mexico Border 100 Kilometer Indicator",
    "U.S. - Mexico Border County Indicator", "State and County Federal Information Processing Standard Code",
    "Complete County Name", "County Equivalent Name", "County Description", "HHS Region Code",
    "HHS Region Name", "State FIPS Code", "State Name",
    "State FIPS and Congressional District Number Code", "Congressional District Number",
    "Congressional District Name", "Congressional District Code",
    "U.S. Congressional Representative Name", "Name of U.S. Senator Number One",
    "Name of U.S. Senator Number Two", "Data Warehouse Record Create Date",
)

# The HPSA primary-care file's real 65 columns, file order.
HPSA_COLUMNS = (
    "HPSA Name", "HPSA ID", "Designation Type", "HPSA Discipline Class", "HPSA Score",
    "PC MCTA Score", "Primary State Abbreviation", "HPSA Status", "HPSA Designation Date",
    "HPSA Designation Last Update Date", "Metropolitan Indicator",
    "HPSA Geography Identification Number", "HPSA Degree of Shortage", "Withdrawn Date",
    "HPSA FTE", "HPSA Designation Population", "% of Population Below 100% Poverty",
    "HPSA Formal Ratio", "HPSA Population Type", "Rural Status", "Longitude", "Latitude",
    "BHCMIS Organization Identification Number", "Break in Designation", "Common County Name",
    "Common Postal Code", "Common Region Name", "Common State Abbreviation",
    "Common State County FIPS Code", "Common State FIPS Code", "Common State Name",
    "County Equivalent Name", "County or County Equivalent Federal Information Processing Standard Code",
    "Discipline Class Number", "HPSA Address", "HPSA City", "HPSA Component Name",
    "HPSA Component Source Identification Number", "HPSA Component State Abbreviation",
    "HPSA Component Type Code", "HPSA Component Type Description",
    "HPSA Designation Population Type Description", "HPSA Estimated Served Population",
    "HPSA Estimated Underserved Population", "HPSA Metropolitan Indicator Code",
    "HPSA Population Type Code", "HPSA Postal Code", "HPSA Provider Ratio Goal",
    "HPSA Resident Civilian Population", "HPSA Shortage", "HPSA Status Code", "HPSA Type Code",
    "HPSA Withdrawn Date String", "Primary State FIPS Code", "Primary State Name", "Provider Type",
    "Rural Status Code", "State Abbreviation",
    "State and County Federal Information Processing Standard Code", "State FIPS Code", "State Name",
    "U.S. - Mexico Border 100 Kilometer Indicator", "U.S. - Mexico Border County Indicator",
    "Data Warehouse Record Create Date", "Data Warehouse Record Create Date Text",
)

GEOGRAPHIC_DESIGNATION_TYPES = ("Geographic HPSA", "High Needs Geographic HPSA")


def _header(url):
    """The file's first line, split on comma. Only that line is fetched --
    both files are tens of megabytes."""
    if url.startswith("http"):
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req) as r:
            first = r.readline()
    else:
        with open(url, "rb") as r:
            first = r.readline()
    return tuple(first.decode("utf-8").rstrip("\r\n").split(","))


def _check_header(url, columns, label):
    """Compare against `columns`, tolerating the one documented trailing
    empty field (module docstring) whichever way it lands."""
    header = _header(url)
    trimmed = header[:-1] if header and header[-1] == "" else header
    if trimmed != columns:
        raise SystemExit(f"hrsa_sites: {label} header at {url} is not the declared one; "
                         f"differs in {sorted(set(trimmed) ^ set(columns))}")


def _land(cat, identifier, url, columns, retrieved_on, release, label):
    _check_header(url, columns, label)
    select = ", ".join(f'"{c}"' for c in columns)
    con = duckdb.connect()
    # Dialect stated, not sniffed: comma-delimited, double-quoted. null_padding
    # absorbs the trailing spurious column (module docstring); strict_mode=false
    # is required alongside it -- DuckDB's sniffer otherwise refuses the file
    # outright rather than padding the short rows.
    arrow = con.sql(f"""
        SELECT {select}, '{retrieved_on}' AS retrieved_on, '{release}' AS landed_in
        FROM read_csv('{url}', header=true, all_varchar=true, delim=',', quote='"', escape='"',
                      strict_mode=false, null_padding=true)
    """).to_arrow_table()
    if not arrow.num_rows:
        raise SystemExit(f"hrsa_sites: {url} yielded no rows")
    return merge.write(cat, identifier, arrow, EqualTo("retrieved_on", retrieved_on))


def land_raw(cat, release, hc_url=None, hpsa_url=None, retrieved_on=None):
    """Phase 1: both files, verbatim and whole, replaced per retrieval date."""
    retrieved_on = retrieved_on or date.today().isoformat()
    hc_url = hc_url or URL_HC_SITES
    hpsa_url = hpsa_url or URL_HPSA_PC

    n_hc = _land(cat, "raw.hrsa__health_center_sites", hc_url, COLUMNS, retrieved_on, release,
                "health center sites")
    n_hpsa = _land(cat, "raw.hrsa__hpsa_primary_care", hpsa_url, HPSA_COLUMNS, retrieved_on, release,
                   "HPSA primary care")
    merge.manifest(cat, release, "hrsa_sites", hc_url, n_hc, version=retrieved_on,
                   method="retrieval_date")
    return retrieved_on, {"raw.hrsa__health_center_sites": n_hc,
                          "raw.hrsa__hpsa_primary_care": n_hpsa}


def transform(cat, release, retrieved_on):
    """Phase 2: facility.site from the health-center file, county-level HPSA
    measures from the primary-care file. Both scoped to `retrieved_on`."""
    con = duckdb.connect()
    con.register("hc", cat.load_table("raw.hrsa__health_center_sites").scan(
        row_filter=EqualTo("retrieved_on", retrieved_on)).to_arrow())
    con.register("hpsa", cat.load_table("raw.hrsa__hpsa_primary_care").scan(
        row_filter=EqualTo("retrieved_on", retrieved_on)).to_arrow())

    site = con.sql(f"""
        SELECT "BPHC Assigned Number" AS facility_id, 'HRSA_HC' AS source,
               NULL::VARCHAR AS source_release, 'fqhc' AS kind, "Site Name" AS name,
               "Site Address" || ', ' || "Site City" || ', ' || "Site State Abbreviation"
                   || ' ' || "Site Postal Code" AS address,
               TRY_CAST("Geocoding Artifact Address Primary Y Coordinate" AS DOUBLE) AS lat,
               TRY_CAST("Geocoding Artifact Address Primary X Coordinate" AS DOUBLE) AS lon,
               'county:' || lpad("State and County Federal Information Processing Standard Code", 5, '0')
                   AS geo_id,
               {GEO_VINTAGE} AS geo_vintage,
               to_json({{
                   'site_type': "Health Center Location Type Description",
                   'operating_hours_reported':
                       CASE WHEN "Operating Hours per Week" IS NULL THEN 'false' ELSE 'true' END,
                   'grantee_name': "Health Center Name",
                   'grantee_id': "Health Center Number",
                   'status': "Site Status Description"
               }}) AS attributes_json
        FROM hc
    """).to_arrow_table()

    counts = {"facility.site": merge.merge(cat, "facility.site", site, release,
                                           EqualTo("source", "HRSA_HC"))}
    counts.update(_hpsa_measures(con, cat, release, retrieved_on))
    return counts


def _hpsa_measures(con, cat, release, retrieved_on):
    """County-level 'currently touched by a designated primary-care
    geographic HPSA' count and max score (module docstring: a simple,
    defensible republish, not a reconstruction of HRSA's shortage math)."""
    definition = con.sql(f"""
        SELECT 'HPSA:pc_count' AS measure_id, 'HPSA' AS source,
               'Primary care HPSA count' AS label, 'count' AS units,
               NULL::VARCHAR AS universe, 'count' AS rate_basis, NULL::VARCHAR AS age_adjustment,
               'derived' AS method, NULL::VARCHAR AS cancer_site_code,
               'Count of currently-designated (HPSA Status = Designated) primary-care Geographic '
               'or High Needs Geographic HPSAs whose county FIPS (as HRSA publishes it) includes '
               'this county, as of the retrieval date in period_start/period_end. A HPSA spanning '
               'several sub-county components in one county counts once.' AS doc
      UNION ALL
        SELECT 'HPSA:pc_max_score', 'HPSA', 'Primary care HPSA max score', 'index',
               NULL, 'index', NULL, 'derived', NULL,
               'Maximum HRSA HPSA Score among this county''s currently-designated primary-care '
               'Geographic/High Needs Geographic HPSAs (HRSA''s own 0-26 shortage-severity scale; '
               'higher means a more severe shortage), as of the retrieval date.'
    """).to_arrow_table()

    stratum = con.sql("""
        SELECT 'HPSA:none' AS stratum_id, 'HPSA' AS source, NULL::VARCHAR AS sex,
               NULL::VARCHAR AS age_group, NULL::VARCHAR AS race_ethnicity, NULL::VARCHAR AS stage,
               NULL::VARCHAR AS other, 'HPSA_NONE' AS scheme
    """).to_arrow_table()

    # DISTINCT on (HPSA ID, FIPS): a multi-component HPSA (Census Tract /
    # County Subdivision) repeats one row per component, all sharing the same
    # county FIPS -- counted once per county, not once per component row.
    # The FIPS regex excludes the masked 'XXXXX'/'XXX' placeholder seen on
    # Withdrawn/Proposed rows (module docstring); no currently-Designated row
    # carries one as of 2026-09-18.
    observation = con.sql(f"""
        WITH geo AS (
            SELECT DISTINCT "HPSA ID" AS hpsa_id,
                   "State and County Federal Information Processing Standard Code" AS fips,
                   TRY_CAST("HPSA Score" AS DOUBLE) AS score
            FROM hpsa
            WHERE "Designation Type" IN {GEOGRAPHIC_DESIGNATION_TYPES}
              AND "HPSA Status" = 'Designated'
              AND "State and County Federal Information Processing Standard Code" SIMILAR TO '[0-9]{{5}}'
        ),
        agg AS (SELECT fips, count(*) AS n_hpsa, max(score) AS max_score FROM geo GROUP BY fips)
        SELECT 'HPSA' AS source, '{retrieved_on}' AS source_release, 'HPSA:pc_count' AS measure_id,
               'county:' || fips AS geo_id, {GEO_VINTAGE} AS geo_vintage,
               '{retrieved_on}' AS period_start, '{retrieved_on}' AS period_end,
               'HPSA:none' AS stratum_id, n_hpsa::DOUBLE AS value,
               NULL::DOUBLE AS lower, NULL::DOUBLE AS upper, NULL::DOUBLE AS interval_level,
               NULL::DOUBLE AS numerator, NULL::DOUBLE AS denominator, 'reported' AS value_status,
               NULL::VARCHAR AS reliability_flag, NULL::VARCHAR AS trend
        FROM agg
      UNION ALL
        SELECT 'HPSA', '{retrieved_on}', 'HPSA:pc_max_score', 'county:' || fips, {GEO_VINTAGE},
               '{retrieved_on}', '{retrieved_on}', 'HPSA:none', max_score,
               NULL, NULL, NULL, NULL, NULL,
               CASE WHEN max_score IS NULL THEN 'not_available' ELSE 'reported' END,
               NULL, NULL
        FROM agg
    """).to_arrow_table()
    merge.check_observations(observation)

    scope = EqualTo("source", "HPSA")
    return {
        "measure.definition": merge.write(cat, "measure.definition", definition, scope),
        "measure.stratum": merge.write(cat, "measure.stratum", stratum, scope),
        "measure.observation": merge.merge(
            cat, "measure.observation", observation, release,
            And(scope, EqualTo("source_release", retrieved_on))),
    }


def ingest(cat, release, hc_url=None, hpsa_url=None, retrieved_on=None):
    retrieved_on, raw_counts = land_raw(cat, release, hc_url, hpsa_url, retrieved_on)
    return {**raw_counts, **transform(cat, release, retrieved_on)}
