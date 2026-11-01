"""EPA SDWIS Federal (drinking-water violations) -> Iceberg.

Upstream: EPA ECHO's SDWA bulk download
(https://echo.epa.gov/tools/data-downloads -> "Safe Drinking Water Act
(SDWA)"), a single zip refreshed quarterly:
`https://echo.epa.gov/files/echodownloads/SDWA_latest_downloads.zip`
(verified 2026-09-18: HTTP header `content-length: 423774232`,
`last-modified: Thu, 09 Jul 2026`). Column definitions are documented at
https://echo.epa.gov/tools/data-downloads/sdwa-download-summary ("SDWA Data
Download Summary and Data Element Dictionary"), which also states the files
are "refreshed quarterly." **The real downloaded header is the contract
checked here, not that page's own listing** -- the page's column list
differs slightly from the actual 2026Q2 file for two of the four files
(missing COMPL_PER_BEGIN_DATE/COMPL_PER_END_DATE/PWS_DEACTIVATION_DATE in
the violations file; page order and real order both verified by downloading
the real 424 MB zip, not by trusting the page).

Chosen over Envirofacts' `efservice` REST tables (the paged alternative
SPEC.md's issue #53 raised): the ECHO zip is one dated, complete extract:
`SUBMISSIONYEARQUARTER = '2026Q2'` on every row of every file in the real
download, a real citable version label the source itself publishes. Paging
`efservice` over 15M+ violation rows has no documented per-call limit *and*
a 15-minute request timeout, so a completeness guarantee would have to be
built by hand; the bulk zip already is one.

**Licence.** Public domain. The SDWIS dataset's own catalog.data.gov record
(https://catalog.data.gov/dataset/safe-drinking-water-information-system-sdwis,
checked 2026-09-18) names its License as
https://edg.epa.gov/EPA_Data_License.html, which states verbatim: "Unless
otherwise specified, all data produced by the U.S EPA is by default in the
public domain and is not subject to domestic copyright protection under 17
U.S.C. § 105." No registration or attribution is required to redistribute.

**Version axis.** `SUBMISSIONYEARQUARTER` ('2026Q2' in the checked download)
is a column in every one of the four files, not a per-source constant this
module invents -- unlike RUCC or the Gazetteer, whose editions live only in
the file name/URL. It is used directly as the raw overwrite-scope column
(no redundant edition column added) and as `source_release`/`merge.manifest`'s
`version` (`method="release_number"`).

**The four files landed.** `SDWA_PUB_WATER_SYSTEMS.csv`,
`SDWA_VIOLATIONS_ENFORCEMENT.csv` and `SDWA_GEOGRAPHIC_AREAS.csv` are the
three the issue named. A fourth, `SDWA_REF_ANSI_AREAS.csv`, is landed too
(`raw.sdwis__ref_ansi_areas`) -- it is EPA's own small (~86 KB, ~3,000-row)
ANSI/FIPS county reference table, bundled in the very same zip, and it is
what makes `ANSI_ENTITY_CODE` (a real FIPS/ANSI code column, per SPEC's
preference over name-matching) resolvable to a full county FIPS: see
"Geography" below for why it is necessary rather than a hardcoded lookup.
`SDWA_EVENTS_MILESTONES.csv`, `SDWA_FACILITIES.csv`, `SDWA_LCR_SAMPLES.csv`,
`SDWA_PN_VIOLATION_ASSOC.csv`, `SDWA_REF_CODE_VALUES.csv`,
`SDWA_SERVICE_AREAS.csv` and `SDWA_SITE_VISITS.csv` are also in the zip and
are NOT landed -- out of scope for this issue's violations-by-county ask.

**Individual columns excluded.** `SDWA_PUB_WATER_SYSTEMS.csv`'s real header
carries an administrative-contact block that is personal data for a large
share of the ~434,000 systems in the real download, not just its obviously-named
contact fields. Nine columns are excluded from `raw.sdwis__pub_water_systems`
entirely (SPEC.md/AGENTS.md: public aggregates and organisations only, never
individuals):
  - `ADMIN_NAME`, `EMAIL_ADDR`, `PHONE_NUMBER`, `PHONE_EXT_NUMBER`,
    `FAX_NUMBER`, `ALT_PHONE_NUMBER` -- verified to hold individual people's
    names, emails and phone numbers directly (e.g. `ADMIN_NAME` "KLINGMAN,
    KEN" with a personal-looking email).
  - `ORG_NAME` -- verified NOT to be reliably an organisation name: of the
    276,273 systems that are both privately owned (`OWNER_TYPE_CODE = 'P'`)
    and small (`POPULATION_SERVED_COUNT <= 500`), 84,140 (30%) have an
    `ORG_NAME` matching a `"LASTNAME, FIRSTNAME"` pattern rather than a
    business name; across the whole file, 123,992 rows (29%) match that
    pattern, and of those, 116,976 (94%) have `ORG_NAME` identical to
    `ADMIN_NAME` -- the same individual, not a coincidentally name-shaped
    company. This reverses an earlier version of this module, which kept
    `ORG_NAME` reasoning it was purely an organisational field; the real
    prevalence here says otherwise.
  - `ADDRESS_LINE1`, `ADDRESS_LINE2` -- of those same personal-`ORG_NAME`
    rows, 116,370 (94%) carry a populated `ADDRESS_LINE1`, which for a
    small, individually-owned system (a private well, a mobile-home park)
    is very often that person's own mailing address, not a facility address
    distinct from a residence.
`PWS_NAME` (the system's own name), `CITY_NAME`, `STATE_CODE`, `ZIP_CODE`
and every geography/derivation field are kept -- the system itself is an
organisation and a place, and nothing derived here reads any of the nine
excluded columns.

**Geography: PWSIDs are not counties, and this module counts violations
against counties served.** `SDWA_GEOGRAPHIC_AREAS.csv` gives each PWSID's
served areas, `AREA_TYPE_CODE = 'CN'` marking a county-served row. That row
carries `ANSI_ENTITY_CODE` -- a real FIPS/ANSI county entity code, preferred
per SPEC over a county-name match -- but it is a bare 3-digit code with no
state attached, and `STATE_SERVED` ("state that the facility is serving",
per EPA's own field description) is **empty on every CN row in the real
2026Q2 download** (verified: 0 of 411,651 county-served rows have it
populated). The state instead comes from `PWSID`'s own two-letter prefix
(EPA's documented PWSID format: "a two-letter state or region code followed
by seven digits"), joined against `raw.sdwis__ref_ansi_areas.STATE_CODE` to
recover the matching `ANSI_STATE_CODE`, which concatenates with
`ANSI_ENTITY_CODE` into a 5-digit county FIPS. `raw.sdwis__ref_ansi_areas`
also catches invalid codes -- verified against the real file: ~5,000
`ANSI_ENTITY_CODE` values (mostly a block of New Jersey rows carrying even
codes like '002', '004', ... where every real NJ county FIPS is odd) do not
correspond to any real county for their state, and PWSID prefixes that are
not a real postal state (numeric EPA-region codes, 'NN' for Navajo Nation,
etc. -- 1,124 of 411,651 rows) cannot be resolved this way at all. Both
kinds are counted, reported (`transform` prints the unmatched rate) and
excluded -- never fuzzy-matched, per SPEC.md. A system serving several
counties counts once in each (verified against real PWSIDs with multiple CN
rows); this over-counts a single violation across a multi-county system's
service area rather than apportioning it, and is called out explicitly here
per the issue's own instruction.

**Why a fourth raw table instead of a hardcoded state-FIPS constant.** A
static `{"CT": "09", ...}` dict would resolve the state half cheaply, but it
cannot also validate `ANSI_ENTITY_CODE` against a real county list -- doing
that would need either landing this same reference data by another name, or
silently trusting whatever 3-digit code the row carries (which is exactly
how the ~5,000 bad New Jersey codes above would turn into wrong FIPS values
read as real ones). Landing EPA's own reference file, from the same zip
under the same licence and version, catches that instead of trusting it.

**Geography vintage: 2010.** `raw.sdwis__ref_ansi_areas` carries Alaska's
pre-2019 Valdez-Cordova Census Area (`02261`) rather than the Chugach
(`02063`)/Copper River (`02066`) census areas that replaced it in 2019, and
Connecticut's eight legacy counties (`09001`-`09015`) rather than the nine
planning regions (`09110`-`09190`) that replaced them in 2022 -- both
verified directly against the real downloaded file. `census_gazetteer.py`
documents the same two markers for its own 2010-vintage file (2020-vintage
carries the post-2019 Alaska areas; CT's planning regions arrive with a
2022-vintage source), so `GEO_VINTAGE = 2010` here matches an already-landed
`geography.unit` vintage rather than inventing a new one.

**No zero-count rows.** Only (county, year) pairs with at least one matched
health-based violation get a row; a county with none in a given year is
absent, not present with `value = 0`. This is a plain count of what the
source reports, not a survey needing an explicit non-response marker, and
there is no complete county-by-vintage universe available here to fill in
against (unlike RUCC, which has one row per FIPS in its own file).

**What is NOT derived, and why.** The issue also asked, "if defensible,"
for a count of active community water systems and the population served by
systems with a health-based violation, per county-year. Neither is: SDWIS's
system-level fields (`PWS_ACTIVITY_CODE`, `POPULATION_SERVED_COUNT`) are a
**current snapshot**, not a per-year history -- SDWA_PUB_WATER_SYSTEMS.csv
carries no historical activity or population column at all. Attaching
today's activity/population to a 2016 violation would misrepresent a
present-day fact as a historical one, the opposite of the derivation this
measure earns by reading violation dates directly. Left out; only the
violation-count measure below is derived.

ponytail: violations before the earliest year Cancer InFocus expects (2016)
or in `quarter`'s own (necessarily incomplete) calendar year are landed in
raw like everything else but excluded from the derived measure -- verified
against the real file that the extract quarter's own year is a fraction of
every prior year's row count (4,967 health-based violations begun in 2026 vs.
32,346-70,695 per prior year), confirming it is a partial year, not that
violations stopped.

ponytail: `SDWA_VIOLATIONS_ENFORCEMENT.csv` (15,432,737 rows / ~4.1 GB /
~5.1 GB as Arrow in the real 2026Q2 download) fits in memory whole
(measured locally: 1.5s, ~20 GB peak RSS against the local sqlite
warehouse), but is landed in batches anyway -- ported from bioc-on-ice's
`ncbi.py::_land` -- because the production target is R2 Data Catalog, which
rate-limits commits per table and, per that module's own experience, does
not want one multi-GB single-commit overwrite.
"""

import csv
import shutil
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

import duckdb
import pyarrow as pa
from pyiceberg.exceptions import CommitFailedException, RESTError
from pyiceberg.expressions import AlwaysTrue, And, EqualTo, In

from . import merge, schemas

URL = "https://echo.epa.gov/files/echodownloads/SDWA_latest_downloads.zip"
USER_AGENT = "cancerbasemap/1.0 (+https://github.com/seandavi/cancer-basemap)"
GEO_VINTAGE = 2010
MEASURE_ID = "SDWIS:violations_health_based"
STRATUM_ID = "SDWIS:none"

MEMBERS = {
    "pws": "SDWA_PUB_WATER_SYSTEMS.csv",
    "geo": "SDWA_GEOGRAPHIC_AREAS.csv",
    "viol": "SDWA_VIOLATIONS_ENFORCEMENT.csv",
    "ansi": "SDWA_REF_ANSI_AREAS.csv",
}

# The nine individual columns excluded from raw.sdwis__pub_water_systems
# (module docstring). Every other real header column lands, in file order.
PWS_EXCLUDE = ("ORG_NAME", "ADMIN_NAME", "EMAIL_ADDR", "PHONE_NUMBER", "PHONE_EXT_NUMBER",
               "FAX_NUMBER", "ALT_PHONE_NUMBER", "ADDRESS_LINE1", "ADDRESS_LINE2")

# The real headers, in file order -- the drift-detection contract (verified
# 2026-09-18 against the actual 2026Q2 download, not the summary page).
PWS_COLUMNS = (
    "SUBMISSIONYEARQUARTER", "PWSID", "PWS_NAME", "PRIMACY_AGENCY_CODE", "EPA_REGION",
    "SEASON_BEGIN_DATE", "SEASON_END_DATE", "PWS_ACTIVITY_CODE", "PWS_DEACTIVATION_DATE",
    "PWS_TYPE_CODE", "DBPR_SCHEDULE_CAT_CODE", "CDS_ID", "GW_SW_CODE", "LT2_SCHEDULE_CAT_CODE",
    "OWNER_TYPE_CODE", "POPULATION_SERVED_COUNT", "POP_CAT_2_CODE", "POP_CAT_3_CODE",
    "POP_CAT_4_CODE", "POP_CAT_5_CODE", "POP_CAT_11_CODE", "PRIMACY_TYPE", "PRIMARY_SOURCE_CODE",
    "IS_GRANT_ELIGIBLE_IND", "IS_WHOLESALER_IND", "IS_SCHOOL_OR_DAYCARE_IND",
    "SERVICE_CONNECTIONS_COUNT", "SUBMISSION_STATUS_CODE", "ORG_NAME", "ADMIN_NAME",
    "EMAIL_ADDR", "PHONE_NUMBER", "PHONE_EXT_NUMBER", "FAX_NUMBER", "ALT_PHONE_NUMBER",
    "ADDRESS_LINE1", "ADDRESS_LINE2", "CITY_NAME", "ZIP_CODE", "COUNTRY_CODE",
    "FIRST_REPORTED_DATE", "LAST_REPORTED_DATE", "STATE_CODE", "SOURCE_WATER_PROTECTION_CODE",
    "SOURCE_PROTECTION_BEGIN_DATE", "OUTSTANDING_PERFORMER", "OUTSTANDING_PERFORM_BEGIN_DATE",
    "REDUCED_RTCR_MONITORING", "REDUCED_MONITORING_BEGIN_DATE", "REDUCED_MONITORING_END_DATE",
    "SEASONAL_STARTUP_SYSTEM",
)
GEO_COLUMNS = (
    "SUBMISSIONYEARQUARTER", "PWSID", "GEO_ID", "AREA_TYPE_CODE", "TRIBAL_CODE", "STATE_SERVED",
    "ANSI_ENTITY_CODE", "ZIP_CODE_SERVED", "CITY_SERVED", "COUNTY_SERVED", "LAST_REPORTED_DATE",
)
VIOL_COLUMNS = (
    "SUBMISSIONYEARQUARTER", "PWSID", "VIOLATION_ID", "FACILITY_ID", "COMPL_PER_BEGIN_DATE",
    "COMPL_PER_END_DATE", "NON_COMPL_PER_BEGIN_DATE", "NON_COMPL_PER_END_DATE",
    "PWS_DEACTIVATION_DATE", "VIOLATION_CODE", "VIOLATION_CATEGORY_CODE", "IS_HEALTH_BASED_IND",
    "CONTAMINANT_CODE", "VIOL_MEASURE", "UNIT_OF_MEASURE", "FEDERAL_MCL", "STATE_MCL",
    "IS_MAJOR_VIOL_IND", "SEVERITY_IND_CNT", "CALCULATED_RTC_DATE", "VIOLATION_STATUS",
    "PUBLIC_NOTIFICATION_TIER", "CALCULATED_PUB_NOTIF_TIER", "VIOL_ORIGINATOR_CODE",
    "SAMPLE_RESULT_ID", "CORRECTIVE_ACTION_ID", "RULE_CODE", "RULE_GROUP_CODE",
    "RULE_FAMILY_CODE", "VIOL_FIRST_REPORTED_DATE", "VIOL_LAST_REPORTED_DATE", "ENFORCEMENT_ID",
    "ENFORCEMENT_DATE", "ENFORCEMENT_ACTION_TYPE_CODE", "ENF_ACTION_CATEGORY",
    "ENF_ORIGINATOR_CODE", "ENF_FIRST_REPORTED_DATE", "ENF_LAST_REPORTED_DATE",
)
ANSI_COLUMNS = ("ANSI_STATE_CODE", "ANSI_ENTITY_CODE", "ANSI_NAME", "STATE_CODE")

# Dialect stated, not sniffed: plain comma-delimited, double-quoted, UTF-8
# (verified 2026-09-18 against the real download; all_varchar=true keeps
# every FIPS-shaped code a zero-padded string).
_CSV_OPTS = "header=true, all_varchar=true, delim=',', quote='\"', escape='\"', encoding='utf-8'"


def _read(path, select="*"):
    return f"SELECT {select} FROM read_csv('{path}', {_CSV_OPTS})"

MEASURE_DOC = (
    "Count of health-based drinking-water violations (SDWA_VIOLATIONS_ENFORCEMENT."
    "IS_HEALTH_BASED_IND = Y) begun in the given year, attributed to each county a "
    "public water system reports serving. A system serving several counties is counted "
    "once in each (over-counts a single violation across a multi-county service area "
    "rather than apportioning it). A light republished count of a public enforcement "
    "list, not a computed statistic: no rate, denominator or modeling is applied. Rows "
    "with an ANSI_ENTITY_CODE that does not resolve to a real county for its state, or "
    "a PWSID prefix that is not a postal state code, are excluded (see epa_sdwis.py "
    "module docstring for the real, reported unmatched rate) rather than guessed."
)

BATCH = 1_000_000
# Rows accumulated per Iceberg commit -- see module docstring on why this is batched
# at all despite fitting in memory whole locally. Same constant bioc-on-ice's
# ncbi.py uses for its own multi-GB dumps.
ROWS_PER_COMMIT = 5_000_000


def _download_zip(url, tmpdir):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    path = Path(tmpdir) / "sdwa.zip"
    with urllib.request.urlopen(req) as r, open(path, "wb") as f:
        shutil.copyfileobj(r, f)
    return path


def _paths(url, overrides, tmpdir):
    """Paths to the four SDWA member files. A per-file override (a local CSV,
    how the offline tests avoid zipping up four tiny fixtures) wins; any file
    left over comes from one zip -- downloaded if `url` is remote, opened
    directly if it is already a local zip path."""
    paths = {k: Path(v) for k, v in overrides.items() if v is not None}
    need = {k: name for k, name in MEMBERS.items() if k not in paths}
    if need:
        zpath = _download_zip(url, tmpdir) if url.startswith("http") else Path(url)
        with zipfile.ZipFile(zpath) as z:
            for k, name in need.items():
                z.extract(name, tmpdir)
                paths[k] = Path(tmpdir) / name
    return paths


def _check_header(path, expected, label):
    with open(path, encoding="utf-8", newline="") as f:
        header = tuple(next(csv.reader(f)))
    if header != expected:
        raise SystemExit(f"epa_sdwis: {path} ({label}) header is not the declared one; "
                         f"differs in {sorted(set(header) ^ set(expected))}")


def _quarter(path):
    """SUBMISSIONYEARQUARTER, read from the pub_water_systems file and trusted
    for the other three -- all four are one dated extract from one zip."""
    con = duckdb.connect()
    row = con.sql(_read(path, "SUBMISSIONYEARQUARTER") + " LIMIT 1").fetchone()
    if not row or not row[0]:
        raise SystemExit(f"epa_sdwis: {path} has no SUBMISSIONYEARQUARTER value")
    return row[0]


def _commit(cat, identifier, table, arrow, first, scope):
    """One commit, riding out the same transient failures merge.overwrite
    retries (see its docstring) -- reimplemented here (not called through
    merge.write/merge.overwrite) because landing >5M rows needs several
    commits, the first an overwrite and the rest plain appends."""
    for attempt in range(8):
        try:
            (table.overwrite if first else table.append)(
                arrow, **({"overwrite_filter": scope} if first else {}))
            return table
        except CommitFailedException:
            time.sleep(2 ** attempt)
            table = cat.load_table(identifier)
        except RESTError as err:
            if not schemas.is_rate_limit(err):
                raise
            time.sleep(65)
            table = cat.load_table(identifier)
    raise RuntimeError(f"{identifier}: commit still failing after {attempt + 1} retries")


def _land_violations(cat, release, path, quarter):
    """Stream the violations file into raw in batches (ported from
    bioc-on-ice's ncbi.py::_land -- see module docstring on why)."""
    identifier = "raw.sdwis__violations_enforcement"
    table = schemas.create(cat, identifier)
    arrow_schema = table.schema().as_arrow()
    scope = EqualTo("SUBMISSIONYEARQUARTER", quarter)
    con = duckdb.connect()
    reader = con.sql(_read(path, f"*, '{release}' AS landed_in")).to_arrow_reader(BATCH)

    n = 0
    pending = []
    for batch in reader:
        pending.append(pa.Table.from_batches([batch]).cast(arrow_schema))
        if sum(t.num_rows for t in pending) >= ROWS_PER_COMMIT:
            chunk = pa.concat_tables(pending)
            table = _commit(cat, identifier, table, chunk, first=not n, scope=scope)
            n += chunk.num_rows
            pending = []
    if pending:
        chunk = pa.concat_tables(pending)
        table = _commit(cat, identifier, table, chunk, first=not n, scope=scope)
        n += chunk.num_rows
    return n


def land_raw(cat, release, url=None, pws_url=None, geo_url=None, viol_url=None, ansi_url=None):
    """Phase 1: this quarter's four SDWA files, landed verbatim and whole
    (minus the nine excluded individual columns -- module docstring).
    Returns `(quarter, {identifier: rows})`.
    """
    with tempfile.TemporaryDirectory() as tmp:
        paths = _paths(url or URL, dict(pws=pws_url, geo=geo_url, viol=viol_url, ansi=ansi_url), tmp)
        _check_header(paths["pws"], PWS_COLUMNS, "pub_water_systems")
        _check_header(paths["geo"], GEO_COLUMNS, "geographic_areas")
        _check_header(paths["viol"], VIOL_COLUMNS, "violations_enforcement")
        _check_header(paths["ansi"], ANSI_COLUMNS, "ref_ansi_areas")
        quarter = _quarter(paths["pws"])

        con = duckdb.connect()
        pws_select = ", ".join(c for c in PWS_COLUMNS if c not in PWS_EXCLUDE)
        n = {
            "raw.sdwis__pub_water_systems": merge.write(
                cat, "raw.sdwis__pub_water_systems",
                con.sql(_read(paths["pws"], f"{pws_select}, '{release}' AS landed_in")).to_arrow_table(),
                EqualTo("SUBMISSIONYEARQUARTER", quarter)),
            "raw.sdwis__geographic_areas": merge.write(
                cat, "raw.sdwis__geographic_areas",
                con.sql(_read(paths["geo"], f"*, '{release}' AS landed_in")).to_arrow_table(),
                EqualTo("SUBMISSIONYEARQUARTER", quarter)),
            "raw.sdwis__ref_ansi_areas": merge.write(
                cat, "raw.sdwis__ref_ansi_areas",
                con.sql(_read(paths["ansi"], f"*, '{release}' AS landed_in")).to_arrow_table(),
                AlwaysTrue()),
            "raw.sdwis__violations_enforcement": _land_violations(
                cat, release, paths["viol"], quarter),
        }

    merge.manifest(cat, release, "epa_sdwis", url or URL, sum(n.values()),
                   version=quarter, method="release_number")
    return quarter, n


def transform(cat, release, quarter):
    """Phase 2: county-year counts of health-based drinking-water violations,
    2016 through the last complete calendar year before `quarter`'s own year
    (module docstring explains why no other measure is derived here)."""
    last_year = int(quarter[:4]) - 1

    con = duckdb.connect()
    con.register("v", cat.load_table("raw.sdwis__violations_enforcement").scan(
        row_filter=EqualTo("SUBMISSIONYEARQUARTER", quarter)).to_arrow())
    con.register("geo", cat.load_table("raw.sdwis__geographic_areas").scan(
        row_filter=EqualTo("SUBMISSIONYEARQUARTER", quarter)).to_arrow())
    con.register("ansi", cat.load_table("raw.sdwis__ref_ansi_areas").scan().to_arrow())

    cn_total = con.sql("SELECT count(*) FROM geo WHERE AREA_TYPE_CODE = 'CN'").fetchone()[0]
    # Every real, EPA-recognized county a PWSID reports serving -- state comes
    # from PWSID's own prefix (STATE_SERVED is blank on every CN row observed;
    # module docstring), validated against raw.sdwis__ref_ansi_areas rather
    # than trusted blind.
    resolved = con.sql("""
        SELECT g.PWSID, a.ANSI_STATE_CODE || g.ANSI_ENTITY_CODE AS fips
        FROM geo g
        JOIN ansi a ON a.STATE_CODE = substr(g.PWSID, 1, 2)
                   AND a.ANSI_ENTITY_CODE = g.ANSI_ENTITY_CODE
        WHERE g.AREA_TYPE_CODE = 'CN'
    """).to_arrow_table()
    con.register("resolved", resolved)
    unmatched = cn_total - resolved.num_rows
    if cn_total:
        print(f"epa_sdwis: {unmatched:,}/{cn_total:,} ({unmatched / cn_total:.1%}) "
             f"county-served rows did not resolve to a known FIPS code (PWSID prefix + "
             f"ANSI_ENTITY_CODE not found in raw.sdwis__ref_ansi_areas) and are excluded "
             f"from the derived measure, not fuzzy-matched.")

    # DISTINCT (PWSID, VIOLATION_ID): the file's grain is (violation,
    # enforcement action), not (violation) -- see VIOLATION_ID's column doc.
    observation = con.sql(f"""
        SELECT 'SDWIS' AS source, '{quarter}' AS source_release, '{MEASURE_ID}' AS measure_id,
               'county:' || r.fips AS geo_id, {GEO_VINTAGE} AS geo_vintage,
               CAST(yr AS VARCHAR) AS period_start, CAST(yr AS VARCHAR) AS period_end,
               '{STRATUM_ID}' AS stratum_id, count(*)::DOUBLE AS value,
               NULL::DOUBLE AS lower, NULL::DOUBLE AS upper, NULL::DOUBLE AS interval_level,
               NULL::DOUBLE AS numerator, NULL::DOUBLE AS denominator,
               'reported' AS value_status, NULL::VARCHAR AS reliability_flag,
               NULL::VARCHAR AS trend
        FROM (
            SELECT DISTINCT PWSID, VIOLATION_ID,
                   CAST(substr(NON_COMPL_PER_BEGIN_DATE, 7, 4) AS INTEGER) AS yr
            FROM v
            WHERE IS_HEALTH_BASED_IND = 'Y' AND VIOLATION_ID IS NOT NULL
        ) dv
        JOIN resolved r ON r.PWSID = dv.PWSID
        WHERE yr BETWEEN 2016 AND {last_year}
        GROUP BY r.fips, yr
    """).to_arrow_table()
    merge.check_observations(observation)

    definition = con.sql(f"""
        SELECT '{MEASURE_ID}' AS measure_id, 'SDWIS' AS source,
               'Health-based drinking water violations' AS label, 'count' AS units,
               NULL::VARCHAR AS universe, 'count' AS rate_basis,
               NULL::VARCHAR AS age_adjustment, 'derived' AS method,
               NULL::VARCHAR AS cancer_site_code, '{MEASURE_DOC}' AS doc
    """).to_arrow_table()
    stratum = con.sql(f"""
        SELECT '{STRATUM_ID}' AS stratum_id, 'SDWIS' AS source,
               NULL::VARCHAR AS sex, NULL::VARCHAR AS age_group,
               NULL::VARCHAR AS race_ethnicity, NULL::VARCHAR AS stage,
               NULL::VARCHAR AS other, 'SDWIS_NONE' AS scheme
    """).to_arrow_table()

    scope = EqualTo("source", "SDWIS")
    # Overwrite only the ids this release asserts (#76), not the whole
    # source = 'SDWIS' scope.
    return {
        "measure.definition": merge.write(cat, "measure.definition", definition,
                                          And(scope, In("measure_id", [MEASURE_ID]))),
        "measure.stratum": merge.write(cat, "measure.stratum", stratum,
                                       And(scope, In("stratum_id", [STRATUM_ID]))),
        "measure.observation": merge.merge(
            cat, "measure.observation", observation, release,
            And(scope, EqualTo("source_release", quarter))),
    }


def ingest(cat, release, url=None, pws_url=None, geo_url=None, viol_url=None, ansi_url=None):
    quarter, n = land_raw(cat, release, url, pws_url, geo_url, viol_url, ansi_url)
    return {**n, **transform(cat, release, quarter)}
