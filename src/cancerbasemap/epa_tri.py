"""EPA Toxics Release Inventory (TRI) Basic Data Files -> Iceberg.

Upstream: one national CSV per reporting year, 1987-present
(https://www.epa.gov/toxics-release-inventory-tri-program/tri-basic-data-files-calendar-years-1987-present).
That page's own download links are JavaScript dropdowns with no stable URL;
the keyless bulk route underneath them (found via web search and verified
2026-09-19 by downloading the 1987, 1988, 1995, 2001, 2022 and 2023 files) is
`https://data.epa.gov/efservice/downloads/tri/mv_tri_basic_download/<year>_US/csv`
-- no API key, no login, no contact field of any kind in the request.

**Licence.** EPA's own data licence (https://edg.epa.gov/EPA_Data_License.html,
checked 2026-09-19, the same page epa_sdwis.py cites): "Unless otherwise
specified, all data produced by the U.S EPA is by default in the public
domain and is not subject to domestic copyright protection under 17 U.S.C.
Sec 105." No registration or attribution is required to redistribute.

**No individual-contact columns.** The issue asked this module to check the
real header for individual contact fields and exclude them, the way
epa_sdwis.py does for SDWIS's admin-contact block. Checked: the real,
complete 122-column header is identical across every reporting year sampled
(1987, 1988, 1995, 2001, 2023) and holds no preparer, certifier, technical-
contact, phone or email column of any kind -- only facility identity
(FACILITY NAME, STREET ADDRESS/CITY/COUNTY/ST/ZIP) and organisation names
(PARENT CO NAME and its standardised/foreign siblings). That differs from
EPA's separate "TRI Basic Plus" product (not requested by this issue, not
landed here), which does carry a certifying-official block. Nothing is
excluded here because nothing personal was found; `COLUMNS` below is the
declared contract, so a column EPA adds later that doesn't match it fails
`_check_header` before landing, rather than landing silently.

**Header quirk.** EPA's efservice export writes a literal ordinal prefix
into the header row itself, e.g. `"1. YEAR"`, `"2. TRIFD"` -- verified
against every year downloaded. `COLUMNS` keeps that literal text (the real
header is the contract, `_check_header`'s job); `_clean` strips the
`"<n>. "` prefix for the Iceberg column name, so `raw.epa__tri_basic.YEAR`
is `"1. YEAR"` in the source file.

**Versioning: reporting year is the release, not retrieval date.** Unlike
HRSA/FDA's continuously-refreshed snapshots, YEAR is a real, citable label
TRI itself publishes (`raw.epa__tri_basic` is scoped and replaced wholesale
per value of YEAR; `merge.manifest` gets `version=year,
method="release_number"`). The issue's other note -- "EPA refreshes prior
years (the file's own `as of` date) -> record it" -- is handled by landing
`retrieved_on` (this ingest's UTC date) as an ordinary column: informational,
not the merge scope, since EPA publishes no separate revision label and
re-landing a year is exactly how a later revision is captured (the same
`retrieved_on`-is-informational choice hrsa_sites.py and fda_mqsa.py made,
just keyed by YEAR here instead of by retrieval date, because TRI's own
label is real).

**Units: Grams vs Pounds.** `UNIT OF MEASURE` is 'Pounds' for every
CLASSIFICATION except 'Dioxin', which reports in Grams (verified against the
real 2023 file: 770/78,647 rows, all Dioxin). The issue asks for pounds, so
`transform` converts Grams rows (`* GRAMS_TO_LB`) before summing; Pounds
rows pass through unchanged.

**Form A rows report zero, by construction.** `FORM TYPE` 'A' is a
certification statement filed when a facility is below the threshold that
requires quantities; every real Form A row's release columns are '0.000'
(verified against the full 2023 file, all 8,838 Form A rows). They are
landed and summed like any other row -- they simply contribute nothing.

**An unparseable ON-SITE RELEASE TOTAL never reads as a reported zero.**
Every row's real value parses cleanly in every year checked, but `TRY_CAST`
is silent on failure, and SQL's `sum()` skips a NULL rather than propagating
it -- so a row that failed to parse would otherwise vanish from a county-
year's total without changing its `value_status`, silently understating a
"reported" sum. `_measures` tracks whether any contributing row's cast
failed and marks that whole county-year total (or, independently, its
carcinogen-only total) `value_status='not_available'` with `value=NULL`
instead, never `'reported'` with a value that quietly dropped a row
(SPEC.md Acceptance C, the other direction from suppression).

**Geography: county name + state, matched against geography.unit --
never fuzzy.** The file carries no FIPS column, only `COUNTY` (a name) and
`ST` (a USPS state abbreviation). `_geo_match` resolves each distinct
(COUNTY, ST) pair to `county:<fips>` by joining `raw.census__state_fips`
(for the state FIPS) and `geography.unit` (level='county', vintage=
GEO_VINTAGE) on a normalised name: uppercase, accents stripped, periods
removed, and `"(CITY)"` folded to `" CITY"` (TRI's own independent-city
marker, e.g. `"ST LOUIS (CITY)"` for the city vs. the bare `"ST LOUIS"`
county -- both real St. Louis, MO entities, verified they resolve to their
two distinct real FIPS, 29510 and 29189). A row matches if its normalised
text equals geography.unit's normalised full name (catches Louisiana's
`"ACADIA PARISH"` / Puerto Rico's `"AGUADILLA MUNICIPIO"`, which TRI already
suffixes) OR its normalised name with a trailing County/Parish/Borough/
Census Area/Municipality/Municipio/City and Borough/Planning Region suffix
stripped (catches the common case of a bare `"AUTAUGA"`). Nothing beyond
that documented, deterministic normalisation is tried -- SPEC.md: never
fuzzy-matched.

Verified end-to-end against the real 2023 national file, joined against a
real `cancerbasemap gazetteer --year 2020` landing (GEO_VINTAGE = 2020,
hrsa_sites.py's precedent -- a real 2020-dated gazetteer file predates
Connecticut's October 2022 county-to-planning-region switch, so it still
carries the eight legacy counties TRI itself reports): 2,464 distinct
(COUNTY, ST) pairs, 2,451 resolve (99.5%). The real, reported misses, none
guessed around: a handful of Alaska county-equivalent names truncated to 26
characters by EPA's own export (e.g. `"FAIRBANKS NORTH STAR BORO"`), plus
one (`"VALDEZ-CORDOVA CENSUS AREA"`) that was itself split into the Chugach
and Copper River census areas before 2020; Guam, the Northern Mariana
Islands, American Samoa and the U.S. Virgin Islands, none of which carry a
county-level entry in the Census gazetteer; one Louisiana parish spelled
without a space (`"LA SALLE PARISH"` vs. the Census `"LaSalle Parish"`); and
a small number of rows where TRI's own COUNTY/ST pairing looks wrong (e.g. a
Wisconsin-state row naming an Alaska borough). Facility rows with an
unresolved county still land in facility.site with geo_id/geo_vintage NULL
(the FDA_MQSA precedent for "no reliable geography"); unresolved rows are
excluded from measure.observation and the miss rate is printed, exactly as
epa_sdwis.py does for its own unmatched ANSI rows.

**facility.site: latest landed year, not the year just landed.** `TRIFD` is
TRI's own stable per-facility id (no hashing needed, unlike FDA_MQSA).
Deriving from the SAME year every call -- the maximum YEAR currently present
in raw.epa__tri_basic, recomputed from scratch each time, not the `year`
just landed by this invocation -- is what keeps a single `merge.merge` call
(scope `source='TRI'`) safe regardless of landing order (issue #118's
danger is two calls sharing one scope; deriving from a moving "latest raw
year" target instead of "whatever I just landed" means backfilling an
OLDER year never retires a newer year's facilities, and landing a NEWER
year correctly advances the live list). A facility reports many rows (one
per chemical, sometimes more than one row per chemical too -- 660 real
TRIFD+CHEMICAL duplicate groups in the 2023 file, e.g. a chemical reported
once per plant unit); `QUALIFY row_number() ... = 1` picks one
deterministically, `ORDER BY CHEMICAL, DOC_CTRL_NUM` -- `DOC_CTRL_NUM` is
EPA's own per-submission document id, verified globally unique across every
row of the real 2023 file, so it is a real tiebreak, not an arbitrary one.
Every facility-level column (name, address, parent company, ...) is
identical across a TRIFD's rows within one year regardless of which row
wins the tiebreak (verified against the real file).

**measure.observation: every landed year, independently.** Each YEAR's
county totals are merged under scope `(source='TRI', source_release=year)`
-- SCP's per-vintage pattern (scp.py), not SVI's shared-scope one -- since
distinct reporting years never share a scope, landing 2024 can never retire
2023's rows.
"""

import re
import urllib.request
from datetime import date

import duckdb
from pyiceberg.exceptions import NoSuchTableError
from pyiceberg.expressions import And, EqualTo, In

from . import merge

USER_AGENT = "cancerbasemap/1.0 (+https://github.com/seandavi/cancer-basemap)"
URL_TEMPLATE = "https://data.epa.gov/efservice/downloads/tri/mv_tri_basic_download/{year}_US/csv"
GEO_VINTAGE = 2020
GRAMS_TO_LB = 0.0022046226218488

# The real 122 columns, file order, literal EPA header text including its own
# "<n>. " ordinal prefix (module docstring).
COLUMNS = (
    "1. YEAR", "2. TRIFD", "3. FRS ID", "4. FACILITY NAME", "5. STREET ADDRESS", "6. CITY",
    "7. COUNTY", "8. ST", "9. ZIP", "10. BIA", "11. TRIBE", "12. LATITUDE", "13. LONGITUDE",
    "14. HORIZONTAL DATUM", "15. PARENT CO NAME", "16. PARENT CO DB NUM",
    "17. STANDARD PARENT CO NAME", "18. FOREIGN PARENT CO NAME", "19. FOREIGN PARENT CO DB NUM",
    "20. STANDARD FOREIGN PARENT CO NAME", "21. FEDERAL FACILITY", "22. INDUSTRY SECTOR CODE",
    "23. INDUSTRY SECTOR", "24. PRIMARY SIC", "25. SIC 2", "26. SIC 3", "27. SIC 4", "28. SIC 5",
    "29. SIC 6", "30. PRIMARY NAICS", "31. NAICS 2", "32. NAICS 3", "33. NAICS 4", "34. NAICS 5",
    "35. NAICS 6", "36. DOC_CTRL_NUM", "37. CHEMICAL", "38. ELEMENTAL METAL INCLUDED",
    "39. TRI CHEMICAL/COMPOUND ID", "40. CAS#", "41. SRS ID", "42. CLEAN AIR ACT CHEMICAL",
    "43. CLASSIFICATION", "44. METAL", "45. METAL CATEGORY", "46. CARCINOGEN", "47. PBT",
    "48. PFAS", "49. FORM TYPE", "50. UNIT OF MEASURE", "51. 5.1 - FUGITIVE AIR",
    "52. 5.2 - STACK AIR", "53. 5.3 - WATER", "54. 5.4 - UNDERGROUND",
    "55. 5.4.1 - UNDERGROUND CL I", "56. 5.4.2 - UNDERGROUND C II-V", "57. 5.5.1 - LANDFILLS",
    "58. 5.5.1A - RCRA C LANDFILL", "59. 5.5.1B - OTHER LANDFILLS", "60. 5.5.2 - LAND TREATMENT",
    "61. 5.5.3 - SURFACE IMPNDMNT", "62. 5.5.3A - RCRA SURFACE IM", "63. 5.5.3B - OTHER SURFACE I",
    "64. 5.5.4 - OTHER DISPOSAL", "65. ON-SITE RELEASE TOTAL", "66. 6.1 - POTW - TRNS RLSE",
    "67. 6.1 - POTW - TRNS TRT", "68. POTW - TOTAL TRANSFERS", "69. 6.2 - M10", "70. 6.2 - M41",
    "71. 6.2 - M62", "72. 6.2 - M40 METAL", "73. 6.2 - M61 METAL", "74. 6.2 - M71",
    "75. 6.2 - M81", "76. 6.2 - M82", "77. 6.2 - M72", "78. 6.2 - M63", "79. 6.2 - M66",
    "80. 6.2 - M67", "81. 6.2 - M64", "82. 6.2 - M65", "83. 6.2 - M73", "84. 6.2 - M79",
    "85. 6.2 - M90", "86. 6.2 - M94", "87. 6.2 - M99", "88. OFF-SITE RELEASE TOTAL",
    "89. 6.2 - M20", "90. 6.2 - M24", "91. 6.2 - M26", "92. 6.2 - M28", "93. 6.2 - M93",
    "94. OFF-SITE RECYCLED TOTAL", "95. 6.2 - M56", "96. 6.2 - M92",
    "97. OFF-SITE ENERGY RECOVERY T", "98. 6.2 - M40 NON-METAL", "99. 6.2 - M50",
    "100. 6.2 - M54", "101. 6.2 - M61 NON-METAL", "102. 6.2 - M69", "103. 6.2 - M95",
    "104. OFF-SITE TREATED TOTAL", "105. 6.2 - UNCLASSIFIED", "106. 6.2 - TOTAL TRANSFER",
    "107. TOTAL RELEASES", "108. 8.1 - RELEASES", "109. 8.1A - ON-SITE CONTAINED",
    "110. 8.1B - ON-SITE OTHER", "111. 8.1C - OFF-SITE CONTAIN", "112. 8.1D - OFF-SITE OTHER R",
    "113. 8.2 - ENERGY RECOVER ON", "114. 8.3 - ENERGY RECOVER OF",
    "115. 8.4 - RECYCLING ON SITE", "116. 8.5 - RECYCLING OFF SIT",
    "117. 8.6 - TREATMENT ON SITE", "118. 8.7 - TREATMENT OFF SITE",
    "119. PRODUCTION WSTE (8.1-8.7)", "120. 8.8 - ONE-TIME RELEASE",
    "121. PROD_RATIO_OR_ ACTIVITY", "122. 8.9 - PRODUCTION RATIO",
)

COUNTY_SUFFIX_RE = (r" (COUNTY|PARISH|BOROUGH|CENSUS AREA|MUNICIPALITY|MUNICIPIO|"
                    r"CITY AND BOROUGH|PLANNING REGION)$")


def _clean(name):
    """Strip EPA's own literal ordinal prefix, e.g. '51. 5.1 - FUGITIVE AIR' ->
    '5.1 - FUGITIVE AIR' (module docstring)."""
    return re.sub(r"^\d+\.\s*", "", name)


def _header(url):
    if url.startswith("http"):
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req) as r:
            first = r.readline()
    else:
        with open(url, "rb") as r:
            first = r.readline()
    return tuple(first.decode("utf-8").rstrip("\r\n").split(","))


def _check_header(url):
    header = _header(url)
    if header != COLUMNS:
        raise SystemExit(f"epa_tri: {url} header is not the declared one; "
                         f"differs in {sorted(set(header) ^ set(COLUMNS))}")


def land_raw(cat, release, year, url=None, retrieved_on=None):
    """Phase 1: one reporting year's national file, verbatim and whole, replaced
    per value of YEAR (module docstring: reporting year is the real release)."""
    year = str(year)
    url = url or URL_TEMPLATE.format(year=year)
    retrieved_on = retrieved_on or date.today().isoformat()
    _check_header(url)

    select = ", ".join(f'"{c}" AS "{_clean(c)}"' for c in COLUMNS)
    con = duckdb.connect()
    arrow = con.sql(f"""
        SELECT {select}, '{retrieved_on}' AS retrieved_on, '{release}' AS landed_in
        FROM read_csv('{url}', header=true, all_varchar=true, delim=',', quote='"', escape='"')
        WHERE "1. YEAR" = '{year}'
    """).to_arrow_table()
    if not arrow.num_rows:
        raise SystemExit(f"epa_tri: {url} yielded no YEAR={year} rows")

    n = merge.write(cat, "raw.epa__tri_basic", arrow, EqualTo("YEAR", year))
    merge.manifest(cat, release, "epa_tri", url, n, version=year, method="release_number")
    return year, n


def _geo_match(con):
    """(COUNTY, ST) -> geo_id for every distinct pair currently in `raw`
    (module docstring: normalised name + state, never fuzzy). `geo_unit` and
    `state_fips` must already be registered on `con`. Registers `geo_match`
    and prints the real miss rate."""
    con.execute(f"""
        CREATE OR REPLACE TABLE geo_norm AS
        SELECT geo_id, substr(geo_id, 8, 2) AS state_fips,
               upper(trim(strip_accents(replace(name, '.', '')))) AS norm_full,
               regexp_replace(upper(trim(strip_accents(replace(name, '.', '')))),
                              '{COUNTY_SUFFIX_RE}', '', 'i') AS norm_stripped
        FROM geo_unit
    """)
    con.execute("""
        CREATE OR REPLACE TABLE tri_county AS
        SELECT DISTINCT "COUNTY" AS county, "ST" AS st,
               regexp_replace(upper(trim(strip_accents(replace("COUNTY", '.', '')))),
                              '\\(CITY\\)', 'CITY') AS norm
        FROM raw
    """)
    con.execute("""
        CREATE OR REPLACE TABLE geo_match AS
        SELECT t.county, t.st, coalesce(gf.geo_id, gs.geo_id) AS geo_id
        FROM tri_county t
        JOIN state_fips sf ON sf.stusab = t.st
        LEFT JOIN geo_norm gf ON gf.state_fips = sf.state AND gf.norm_full = t.norm
        LEFT JOIN geo_norm gs ON gs.state_fips = sf.state AND gs.norm_stripped = t.norm
    """)
    total, matched = con.sql(
        "SELECT count(*), sum((geo_id IS NOT NULL)::INT) FROM geo_match").fetchone()
    if total:
        print(f"epa_tri: {matched:,}/{total:,} ({matched / total:.1%}) distinct (COUNTY, ST) "
             f"pairs resolved to a geography.unit county (vintage {GEO_VINTAGE}); the rest are "
             f"excluded from measure.observation, not fuzzy-matched (see module docstring).")


def transform(cat, release, year):
    """Phase 2: facility.site (kind='tri', latest landed year) and this year's
    county totals in measure.observation (module docstring on why each part
    reads a different slice of raw)."""
    con = duckdb.connect()
    con.register("raw", cat.load_table("raw.epa__tri_basic").scan().to_arrow())
    try:
        con.register("geo_unit", cat.load_table("geography.unit").scan(
            row_filter=And(EqualTo("level", "county"), EqualTo("vintage", GEO_VINTAGE))).to_arrow())
        con.register("state_fips", cat.load_table("raw.census__state_fips").scan().to_arrow())
    except NoSuchTableError:
        raise SystemExit("epa_tri: geography.unit / raw.census__state_fips not landed -- "
                         "land the Census Gazetteer first (`cancerbasemap gazetteer`)")
    _geo_match(con)

    latest_year = con.sql("SELECT max(TRY_CAST(YEAR AS INTEGER)) FROM raw").fetchone()[0]
    site = con.sql(f"""
        SELECT r.TRIFD AS facility_id, 'TRI' AS source, NULL::VARCHAR AS source_release,
               'tri' AS kind, r."FACILITY NAME" AS name,
               r."STREET ADDRESS" || ', ' || r.CITY || ', ' || r.ST || ' ' || r.ZIP AS address,
               TRY_CAST(r.LATITUDE AS DOUBLE) AS lat, TRY_CAST(r.LONGITUDE AS DOUBLE) AS lon,
               m.geo_id, CASE WHEN m.geo_id IS NOT NULL THEN {GEO_VINTAGE} END AS geo_vintage,
               to_json({{
                   'parent_co_name': r."PARENT CO NAME",
                   'industry_sector': r."INDUSTRY SECTOR",
                   'primary_naics': r."PRIMARY NAICS",
                   'federal_facility': r."FEDERAL FACILITY"
               }}) AS attributes_json
        FROM raw r
        LEFT JOIN geo_match m ON m.county = r.COUNTY AND m.st = r.ST
        WHERE TRY_CAST(r.YEAR AS INTEGER) = {latest_year}
        QUALIFY row_number() OVER (PARTITION BY r.TRIFD ORDER BY r.CHEMICAL, r."DOC_CTRL_NUM") = 1
    """).to_arrow_table()
    counts = {"facility.site": merge.merge(cat, "facility.site", site, release,
                                           EqualTo("source", "TRI"))}
    counts.update(_measures(con, cat, release, year))
    return counts


MEASURE_DOC = {
    "TRI:onsite_release_total":
        "Sum of ON-SITE RELEASE TOTAL (on-site fugitive/stack air, water, underground "
        "injection and land disposal) across every chemical a facility reported in this "
        "county-year, converted to pounds (Dioxin-classified rows report in Grams; module "
        "docstring). A republished sum of a public list -- pounds are not exposure: no "
        "toxicity, dispersion or population weighting is applied.",
    "TRI:onsite_carcinogen_release_total":
        "Same as TRI:onsite_release_total, restricted to chemicals TRI itself flags as "
        "carcinogens (CARCINOGEN = YES). A republished flag, not an independent hazard "
        "assessment; pounds are not exposure.",
}


def _measures(con, cat, release, year):
    definition = con.sql(f"""
        SELECT measure_id, 'TRI' AS source, label, 'lb' AS units, NULL::VARCHAR AS universe,
               'sum' AS rate_basis, NULL::VARCHAR AS age_adjustment, 'derived' AS method,
               NULL::VARCHAR AS cancer_site_code, doc
        FROM (VALUES
            ('TRI:onsite_release_total', 'On-site TRI release total (lb)',
             '{MEASURE_DOC["TRI:onsite_release_total"]}'),
            ('TRI:onsite_carcinogen_release_total', 'On-site TRI carcinogen release total (lb)',
             '{MEASURE_DOC["TRI:onsite_carcinogen_release_total"]}')
        ) AS t(measure_id, label, doc)
    """).to_arrow_table()
    stratum = con.sql("""
        SELECT 'TRI:none' AS stratum_id, 'TRI' AS source, NULL::VARCHAR AS sex,
               NULL::VARCHAR AS age_group, NULL::VARCHAR AS race_ethnicity,
               NULL::VARCHAR AS stage, NULL::VARCHAR AS other, 'TRI_NONE' AS scheme
    """).to_arrow_table()

    # raw_lb IS NULL marks a row whose ON-SITE RELEASE TOTAL failed to parse
    # (never seen in any real year checked -- module docstring -- but TRY_CAST
    # is silent, so this is tracked rather than assumed). sum() skips NULLs,
    # which would otherwise understate a group's total without any signal;
    # `any_bad`/`any_bad_carc` instead mark the whole group's total (or
    # carcinogen-only total) 'not_available' with a NULL value, never
    # 'reported' with a value that silently dropped a row.
    observation = con.sql(f"""
        WITH lb AS (
            SELECT m.geo_id,
                   TRY_CAST(r."ON-SITE RELEASE TOTAL" AS DOUBLE) AS raw_lb,
                   TRY_CAST(r."ON-SITE RELEASE TOTAL" AS DOUBLE) *
                       CASE WHEN r."UNIT OF MEASURE" = 'Grams' THEN {GRAMS_TO_LB} ELSE 1 END AS value_lb,
                   r.CARCINOGEN = 'YES' AS is_carcinogen
            FROM raw r
            JOIN geo_match m ON m.county = r.COUNTY AND m.st = r.ST
            WHERE r.YEAR = '{year}' AND m.geo_id IS NOT NULL
        ),
        agg AS (
            SELECT geo_id, sum(value_lb) AS total,
                   bool_or(raw_lb IS NULL) AS any_bad,
                   sum(value_lb) FILTER (WHERE is_carcinogen) AS carcinogen_total,
                   bool_or(raw_lb IS NULL AND is_carcinogen) AS any_bad_carc
            FROM lb GROUP BY geo_id
        )
        SELECT 'TRI' AS source, '{year}' AS source_release, 'TRI:onsite_release_total' AS measure_id,
               geo_id, {GEO_VINTAGE} AS geo_vintage, '{year}' AS period_start, '{year}' AS period_end,
               'TRI:none' AS stratum_id, CASE WHEN any_bad THEN NULL ELSE total END AS value,
               NULL::DOUBLE AS lower, NULL::DOUBLE AS upper, NULL::DOUBLE AS interval_level,
               NULL::DOUBLE AS numerator, NULL::DOUBLE AS denominator,
               CASE WHEN any_bad THEN 'not_available' ELSE 'reported' END AS value_status,
               NULL::VARCHAR AS reliability_flag, NULL::VARCHAR AS trend
        FROM agg
      UNION ALL
        SELECT 'TRI', '{year}', 'TRI:onsite_carcinogen_release_total', geo_id, {GEO_VINTAGE},
               '{year}', '{year}', 'TRI:none',
               CASE WHEN any_bad_carc THEN NULL ELSE coalesce(carcinogen_total, 0.0) END,
               NULL, NULL, NULL, NULL, NULL,
               CASE WHEN any_bad_carc THEN 'not_available' ELSE 'reported' END, NULL, NULL
        FROM agg
    """).to_arrow_table()
    merge.check_observations(observation)

    scope = EqualTo("source", "TRI")
    return {
        # Scoped to the ids this call writes (#76), not the whole source='TRI'
        # scope -- both are a fixed, constant list here, unlike a data-derived one.
        "measure.definition": merge.write(cat, "measure.definition", definition,
                                          And(scope, In("measure_id", list(MEASURE_DOC)))),
        "measure.stratum": merge.write(cat, "measure.stratum", stratum,
                                       And(scope, In("stratum_id", ["TRI:none"]))),
        "measure.observation": merge.merge(
            cat, "measure.observation", observation, release,
            And(scope, EqualTo("source_release", year))),
    }


def ingest(cat, release, year, url=None, retrieved_on=None):
    year, n_raw = land_raw(cat, release, year, url, retrieved_on)
    return {"raw.epa__tri_basic": n_raw, **transform(cat, release, year)}
