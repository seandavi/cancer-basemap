"""US Census ACS 5-year Summary File (detailed tables) -> Iceberg (SPEC.md
§ Sources: "ACS 5-year (curated table subset) -- demographics, insurance,
poverty, vehicle access | public domain; MOE -> interval_level = 0.90").

**Indicator-set decision (#29 was held on "which table subset?").** The subset
is the indicator set Cancer InFocus (CIF) publishes, since CIF parity is the
adoption path SPEC.md's Landscape section names ("an export recipe that writes
CIFTools-shaped files ... is a better adoption path than a rival dashboard"):
age (under 18, 18-64, 65+), race/ethnicity (Hispanic, NH White, NH Black, NH
Asian, other), educational attainment (no HS diploma; bachelor's+), median
household income, poverty, unemployment and labor-force participation,
vehicle access (no vehicle households), vacant housing, rent burden (>=30%
and >=50% of income), the Gini index, limited English, plus total population
as a universe. **Health insurance and Medicaid are NOT landed in this PR** --
see "Dropped: health insurance / Medicaid" below.

**Upstream, and why this module does not call the Census Data API.** The
issue's brief assumed "the Census Data API ... works without a key for low
volume." That is no longer true, verified 2026-09-18: every endpoint tried
(`https://api.census.gov/data/2023/acs/acs5[/profile|/subject]?get=...`),
including a single-variable, single-state request, HTTP 302-redirects to
`https://api.census.gov/data/missing_key.html` with header
`X-DataWebAPI-KeyError: 1`. Only the *metadata* endpoints
(`/variables.json`, `/groups/<table>.json`) are still keyless -- used here at
authoring time to look up variable labels, never at ingest time. Per this
issue's instructions ("if a key is demanded, stop and report (never commit a
key)"), this module uses the brief's documented fallback instead: the ACS
**table-based Summary File**, a bulk, keyless, per-table download --

    https://www2.census.gov/programs-surveys/acs/summary_file/<year>/table-based-SF/data/5YRData/acsdt5y<year>-<table>.dat

-- one pipe-delimited `.dat` file per detailed table, nationwide (every
summary level in one file), verified 2026-09-18 by downloading the tables
below for the 2023 and 2021 releases. Because no Census Data API endpoint is
ever called, the API Terms of Service attribution sentence the issue asked to
quote does not currently apply; quoted here anyway for the record, and for
whoever adds a keyed API lander for the Data Profile/Subject tables later:
"This product uses the Census Bureau Data API but is not endorsed or
certified by the Census Bureau." (https://www.census.gov/data/developers/about/terms-of-service.html).

**Why detailed (B/C) tables, not Data Profile (DP) or Subject (S) tables.**
CIF's own indicators map most directly onto DP02/DP03/DP04/DP05 (education,
income, poverty, employment, insurance, housing) and S0101/S2701/S2704 (age,
insurance) -- confirmed by inspecting their variable labels via the metadata
endpoints. But the table-based Summary File **only ships detailed tables**
(confirmed: its `5YRData/` directory lists ~1,193 `acsdt5y<year>-b*.dat` /
`-c*.dat` files and zero `dp*`/`s*` files) -- Data Profile and Subject tables
are a data.census.gov/API-only convenience layer computed from the detailed
tables, unreachable without a key. This module uses the closest detailed-table
equivalent of each CIF indicator instead (table -> concept, verified against
each table's real header and variable labels, 2026-09-18):

    B01003  Total population                          (universe)
    B09001  Population under 18 years by age           (age: under 18)
    B09020  Population 65 years and over ...            (age: 65 and over)
    B03002  Hispanic or Latino origin by race           (race/ethnicity)
    B15003  Educational attainment for the population
            25 years and over                          (no HS diploma; bachelor's+)
    B19013  Median household income in the past 12
            months                                      (median household income)
    C17002  Ratio of income to poverty level in the
            past 12 months                              (poverty)
    B23025  Employment status for the population
            16 years and over                           (labor force participation; unemployment)
    B25044  Tenure by vehicles available                (no vehicle households)
    B25002  Occupancy status                            (vacant housing)
    B25070  Gross rent as a percentage of household
            income (GRAPI)                              (rent burden >=30%, >=50%)
    C16002  Household language by household limited
            English speaking status                     (limited English)
    B19083  Gini Index of Income Inequality             (Gini index)
    B27001  Health Insurance Coverage Status
            by Sex by Age                                (uninsured)
    C27007  Medicaid/Means-Tested Public
            Coverage by Sex by Age                        (Medicaid coverage)

Age 18-64 is not published anywhere in ACS as a single variable (every age
table bins in 5- or 10-year spans that straddle 18); it is derived as the
residual `B01003_E001 - B09001_E001 - B09020_E001` (see "Margins of error"
below). Race/ethnicity "other" sums NH American Indian/Alaska Native + NH
Native Hawaiian/Pacific Islander + NH Some Other Race + NH Two-or-more.
Education's "no HS diploma" sums B15003's 15 sub-diploma categories (rows
002-016: no schooling through "12th grade, no diploma"); "bachelor's or
higher" sums bachelor's + master's + professional + doctorate (022-025).
Rent burden's denominator is `B25070_E001 - B25070_E011` (excluding "Not
computed"), matching DP04's own GRAPI universe definition.

**Health insurance / Medicaid (#125).** CIF's insurance indicators
(uninsured; Medicaid) map cleanly onto Subject tables S2701/S2704 (a single
"Percent Uninsured" / "Percent Public Coverage, Medicaid row" variable each)
-- but those are API-only (see above). #29/#124 dropped this rather than
land either of the two detailed-table equivalents whole: the Census API's
`/groups/<table>.json` metadata endpoint reports B27001 as "230 variables"
and B27010 as "266 variables", which is what that decision was made on --
but that count includes the four E/M/EA/MA suffix variants the *API* serves
per cell; the table-based Summary File this module actually reads ships only
E/M, verified directly against the real 2023/2021 downloads' headers:
B27001 is 57 variable-pairs (114 + GEO_ID columns) and C27007 -- "Medicaid/
Means-Tested Public Coverage by Sex by Age", the smaller table that already
carries the with/without-Medicaid split CIF needs, so B27010's 66
variable-pairs (with/without/by *type* of coverage -- employer, Medicare,
Medicaid, TRICARE, ... -- strictly more than CIF's single Medicaid rate
needs) is not landed -- is 21. At ~4MB/variable-pair (see the size-scaling
note this replaces), that is ~228MB (B27001) + ~84MB (C27007) per release,
not the 250-580MB the #29/#124 estimate assumed. Landed whole, this
module's own convention: every "No health insurance coverage" cell (9 age
brackets x 2 sexes = 18 leaves) summed over B27001's own total universe for
`ACS:uninsured`; every "With Medicaid/means-tested public coverage" cell (3
age brackets x 2 sexes = 6 leaves) summed over C27007's own total universe
for `ACS:medicaid_coverage`. Both tables share B27001's "civilian
noninstitutionalized population" universe (verified against both tables'
real `/groups/<table>.json` `universe` field, 2026-09-19).

**Licence.** U.S. Census Bureau content is a federal government work. Per
resources.data.gov/open-licenses/: "Data and content created by government
employees within the scope of their employment are not subject to domestic
copyright protection under 17 U.S.C. Sec 105. Government works are by default
in the U.S. Public Domain." (checked 2026-09-18, same citation as
census_gazetteer.py and ers_rucc.py.)

**Version axis and geo_vintage.** `acs_year` is the 5-year release's END
year (e.g. 2023 for "the 2019-2023 release"); `source_release` downstream is
`f"{year-4}-{year}"`. Two releases are landed: **2023** (2019-2023, the
latest reachable) and **2021** (2017-2021) -- NOT 2018 (2014-2018): the
table-based Summary File format only exists from the "2021" vintage onward
(`https://www2.census.gov/programs-surveys/acs/summary_file/<year>/table-based-SF/`
404s for 2020 and earlier, 200 from 2021, checked 2026-09-18); 2014-2018 is
only published in the older sequence-based format (per-state fixed-layout
files joined against a sequence-to-variable crosswalk), a different enough
parser that supporting it is out of scope here. 2019-2023 and 2017-2021
overlap by three years -- the closest "non-overlapping-ish" pair this format
reaches, exactly as the issue brief anticipated might be necessary.
**#125 part 2 (pre-2021 releases) stays out of scope in this PR** for the
same reason: the sequence-based format is a genuinely different parser (per-
state fixed-layout files against a sequence-to-variable crosswalk, not one
national pipe-delimited file per table), and #125's own text says CIF parity
does not need it -- there is no keyless blocker here to work around, just a
second format not worth building speculatively.
`geo_vintage` is verified directly against each release's own Connecticut
county rows, not assumed from a landed Gazetteer vintage (SPEC.md): the
2019-2023 file's county rows for state 09 are the nine 2022 planning regions
(09110-09190) -> `GEO_VINTAGE[2023] = 2020`; the 2017-2021 file's are the
eight legacy counties (09001-09015) -> `GEO_VINTAGE[2021] = 2010` -- the same
two vintage labels PLACES and the Gazetteer use for the pre/post-2022
Census county definitions.

**Geography scope: county and tract, filtered mechanically, not landed
whole.** The table-based Summary File interleaves every summary level (nation,
state, county, place, tract, block group, ...) in one national file per
table -- unlike census_gazetteer.py's or cdc_svi.py's upstream, which ship a
separate file per level. `land_raw` filters each downloaded file to the
`GEO_ID` prefix for the requested `--level` (`0500000US` = county,
`1400000US` = tract) before landing -- a mechanical geography-level split
applied uniformly to every column, not a curated row subset, and the same two
levels SPEC.md's Sources table declares for ACS.

**Margins of error.** Per U.S. Census Bureau, *Understanding and Using
American Community Survey Data: What All Data Users Need to Know* (2020),
Chapter 8, "Calculating Measures of Error for Derived Estimates"
(https://www.census.gov/content/dam/Census/library/publications/2020/acs/acs_general_handbook_2020_ch08.pdf):
  - **Sums** (formula 1): MOE = sqrt(sum of each component's MOE squared).
    Chapter 8 also notes that a *difference* of two estimates uses the same
    formula as a sum "ignoring covariance" (the sum/difference formulas
    differ only in the sign of a covariance term this approximation already
    drops) -- so the age 18-64 residual and the rent-burden GRAPI-computable
    denominator (both differences) reuse the sum formula rather than a
    separate one.
  - **Proportions/percentages** (formula 6, numerator a subset of the
    denominator): `MOE(P) = (1/Y) * sqrt(MOE(X)^2 - P^2 * MOE(Y)^2)`, and "if
    the value under the square root is negative, ... substitute a 'plus' for
    the 'minus' sign" -- both implemented in `_pct` below.
All of this module's percentages (age, race/ethnicity, education, poverty,
labor force, vehicle, vacancy, rent burden, limited English) are nested
proportions in this sense; the Gini index and median household income are
landed as single cells with their own published MOE, no combination needed.

**Sentinels (ACS "jam values").** Per the Census Bureau's official
"Jam Value Specifications for the 2023 American Community Survey"
(https://www2.census.gov/programs-surveys/acs/tech_docs/jam_values/2023_Jam_Values.xlsx,
downloaded and parsed 2026-09-18 -- the same values are also documented,
without the full table, at
https://www.census.gov/content/dam/Census/library/publications/2023/acs/acs_table_based_summary_file_handbook_ch03.pdf):

    Estimate jam values (all present in the real 2023/2021 downloads):
      -666666666  "Estimate not computed due to insufficient number of
                   sample cases."                    -> suppressed_small_count
      -999999999  "Estimate not displayed due to insufficient number of
                   sample cases for selected geography."
                                                       -> suppressed_small_count
      -888888888  "Estimate not applicable or available."  -> not_applicable
    MOE jam values (all reachable via the same source; -222222222 and
    -333333333 confirmed present in the real B19013/B19083 downloads):
      -222222222  "MOE not computed due to insufficient number of sample
                   cases."                            -> value stays reported,
                                                          lower/upper = NULL
      -333333333  "MOE not computed for medians in lower or upper interval"
                   -- i.e. the estimate itself is an artificial open-interval
                   boundary, not a real median               -> not_available,
                                                          value = NULL too
      -555555555  "MOE not appropriate - estimate is controlled ... MOE may
                   be treated as zero"                -> value stays reported,
                                                          lower/upper = NULL
      (MOE also reuses -888888888 / -999999999 for "MOE not applicable" /
      "MOE not displayed" -- same NULL-the-interval-only treatment.)

Per this issue's instructions, an unmapped negative-jam-looking cell
(`-\\d{6,}` matching none of the six values above) raises `SystemExit` in
`land_raw` rather than landing silently -- see `_check_sentinels`.
`median_household_income` is the one measure with a real median (a $-value
that ACS artificially pins to $2,500 or $250,001 when the true median falls
in an unbounded bracket): it gets the extra `-333333333 -> not_available`
rule; every other measure treats a jammed MOE as "value reported, interval
unavailable" per the brief.

**Composed-measure suppression, resolved (#125 part 3).** Measures built by
summing or ratio-ing several raw cells (race "other", education, poverty,
vehicle access, rent burden, limited English, uninsured, Medicaid) collapse
any contributing jam value to `suppressed_small_count`, rather than
distinguishing `not_applicable` per-leaf. #29/#124 left this as a ponytail
note pending real volumes; #125 checked directly against every landed row so
far (2019-2023 county + tract, 2017-2021 county -- 91,823 rows, all 216
estimate columns across all 15 tables, every level and release this module
lands): `-666666666` ("insufficient sample cases") is the ONLY estimate jam
value that occurs anywhere, 2,749 times; `-888888888` ("not applicable") and
`-999999999` never occur once, in any table, at either geography level. So
the collapse is not losing information in practice, not just "acceptable" --
every real `suppressed_small_count` in a composed measure genuinely is a
small-sample suppression, matching the status's own documented meaning
exactly. No further work item here; re-run this same check
(`_check_sentinels` already hard-stops on an unmapped jam shape, so a future
edition introducing `-888888888` for the first time would be caught, not
silently mis-classified) if a future release changes that.
"""

import re
import tempfile
import urllib.request
from pathlib import Path

import duckdb
from pyiceberg.exceptions import NoSuchTableError
from pyiceberg.expressions import And, EqualTo, In

from . import merge

USER_AGENT = "cancerbasemap/1.0 (+https://github.com/seandavi/cancer-basemap)"
BASE = "https://www2.census.gov/programs-surveys/acs/summary_file"

# Detailed (B/C) table -> variable count, verified against the real header of
# both the 2023 and 2021 5-year table-based Summary File downloads (identical
# layout in both vintages for every table below).
TABLE_VARS = {
    "B01003": 1, "B09001": 10, "B09020": 21, "B03002": 21, "B15003": 25,
    "B19013": 1, "C17002": 8, "B23025": 7, "B25044": 15, "B25002": 3,
    "B25070": 11, "C16002": 14, "B19083": 1, "B27001": 57, "C27007": 21,
}

# 5-year release end year -> boundary vintage, verified directly against each
# release's own Connecticut county rows (see module docstring).
GEO_VINTAGE = {2023: 2020, 2021: 2010}

LEVEL_PREFIX = {"county": "0500000US", "tract": "1400000US"}

# Estimate/MOE jam values, from the Census Bureau's "Jam Value Specifications"
# (see module docstring for the exact quoted meaning of each).
EST_JAM = ("-666666666", "-888888888", "-999999999")
MOE_JAM = ("-222222222", "-333333333", "-555555555", "-888888888", "-999999999")
_JAM_RE = re.compile(r"^-\d{6,}$")
_KNOWN_JAM = set(EST_JAM) | set(MOE_JAM)


def _table_columns(table_id, n):
    cols = ["GEO_ID"]
    for i in range(1, n + 1):
        cols += [f"{table_id}_E{i:03d}", f"{table_id}_M{i:03d}"]
    return tuple(cols)


def _table_url(year, table_id):
    return f"{BASE}/{year}/table-based-SF/data/5YRData/acsdt5y{year}-{table_id.lower()}.dat"


def _fetch_table(year, table_id, dest_dir, dat_dir=None):
    """The table's national bulk file, as a local path. `dat_dir` (tests, or a
    pre-populated cache for a real ingest that lands both --level values from
    one download) supplies an already-downloaded file instead of fetching."""
    if dat_dir is not None:
        path = Path(dat_dir) / f"acsdt5y{year}-{table_id.lower()}.dat"
        if not path.exists():
            raise SystemExit(f"census_acs: {path} not found in --dat-dir")
        return path
    url = _table_url(year, table_id)
    dest = dest_dir / f"acsdt5y{year}-{table_id.lower()}.dat"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req) as r, open(dest, "wb") as f:
        f.write(r.read())
    return dest


def _check_sentinels(con, view, table_id, columns):
    """SystemExit on any negative jam-value-shaped string this module doesn't
    already know how to map (AGENTS.md: an unmapped sentinel is a hard stop,
    not a guess)."""
    checks = " UNION ALL ".join(f'SELECT DISTINCT "{c}" AS v FROM {view}' for c in columns[1:])
    bad = con.sql(f"""
        SELECT DISTINCT v FROM ({checks}) WHERE v IS NOT NULL
    """).fetchall()
    unknown = sorted({v for (v,) in bad if _JAM_RE.match(v) and v not in _KNOWN_JAM})
    if unknown:
        raise SystemExit(f"census_acs: {table_id} has unmapped sentinel value(s) {unknown}; "
                         f"known jam values are {sorted(_KNOWN_JAM)}")


def land_raw(cat, release, year, level, dat_dir=None):
    """Phase 1: every configured detailed table's national bulk file,
    filtered to `level`'s rows, joined on GEO_ID into one wide raw table
    (`raw.acs__county` or `raw.acs__tract`), landed verbatim and whole --
    every estimate/MOE variable of every requested table, as the jam-value
    strings ACS itself publishes (all_varchar; sentinels resolved in
    `transform`, never here). Returns (year, rows).
    """
    if level not in LEVEL_PREFIX:
        raise SystemExit(f"census_acs: level must be one of {sorted(LEVEL_PREFIX)}, got {level!r}")
    prefix = LEVEL_PREFIX[level]
    con = duckdb.connect()
    views = []
    with tempfile.TemporaryDirectory() as tmp:
        for table_id, n in TABLE_VARS.items():
            path = _fetch_table(year, table_id, Path(tmp), dat_dir)
            columns = _table_columns(table_id, n)
            with open(path, "rb") as fh:
                header = tuple(fh.readline().decode("utf-8").rstrip("\r\n").split("|"))
            if header != columns:
                raise SystemExit(f"census_acs: {path} header is not the declared one for "
                                 f"{table_id}; differs in {sorted(set(header) ^ set(columns))}")
            select = ", ".join(f'"{c}"' for c in columns)
            view = f"t_{table_id}"
            # quote/escape disabled: these files are never quoted, and every
            # cell is either a plain GEO_ID or a signed integer/decimal string.
            con.execute(f"""
                CREATE TEMP VIEW {view} AS
                SELECT {select} FROM read_csv('{path}', header=true, delim='|',
                                              quote='', escape='', all_varchar=true)
                WHERE GEO_ID LIKE '{prefix}%'
            """)
            _check_sentinels(con, view, table_id, columns)
            views.append(view)

        join_sql = views[0]
        for view in views[1:]:
            join_sql += f" JOIN {view} USING (GEO_ID)"
        var_cols = [c for t, n in TABLE_VARS.items() for c in _table_columns(t, n)[1:]]
        select = ", ".join(f'"{c}"' for c in var_cols)
        arrow = con.sql(f"""
            SELECT '{level}:' || substr(GEO_ID, 10) AS geo_id, {year} AS acs_year,
                   '{release}' AS landed_in, {select}
            FROM {join_sql}
        """).to_arrow_table()

    if not arrow.num_rows:
        raise SystemExit(f"census_acs: no {level} rows landed for {year} -- upstream layout "
                         f"or GEO_ID prefix may have changed")

    identifier = f"raw.acs__{level}"
    n = merge.write(cat, identifier, arrow, EqualTo("acs_year", year))
    merge.manifest(cat, release, f"census_acs_{level}", _table_url(year, "B01003"), n,
                   version=str(year), method="release_number")
    return year, n


# ---------------------------------------------------------------------------
# transform(): jam-value resolution and Compass-handbook MOE combination.
#
# Every raw cell is resolved to est_<col>/moe_<col>/status_<col> ONCE, in a
# single wide "resolved" TEMP TABLE (`_build_resolved`) -- not inline in each
# measure's SQL. Composed measures (race "other", education, poverty,
# vehicle access, rent burden, limited English, uninsured, Medicaid) reference
# several cells at once, and each of _combine/_pct below re-embeds its inputs
# a few times (once per branch of a CASE); inlining raw CASE-over-jam-values
# expressions directly would re-embed THOSE, several cells deep, at every
# reuse -- textually small per measure, but multiplying across every measure's
# nested composition made DuckDB's query planner take minutes on a two-ROW
# table (observed directly: fixed by this indirection). `resolved` is a TEMP
# TABLE rather than a VIEW for the same reason one level up (#125): a VIEW is
# inlined at each reference, so transform()'s ~23-branch UNION ALL was
# re-planning/re-optimizing the whole wide CASE-expression tree once per
# measure anyway -- 138s in a single transform() call once B27001/C27007
# widened `resolved`, confirmed by swapping VIEW for TABLE with nothing else
# changed (0.05s afterward for the same union).
# ---------------------------------------------------------------------------

def _build_resolved(con):
    """A TEMP TABLE (not a view -- #125 found this materializes once instead
    of being re-planned/re-inlined by every one of the 23 measures' branches
    in transform()'s big UNION ALL, which is what "indirection" above was
    counting on but a view doesn't actually give you: DuckDB inlines a view's
    definition at each reference, so a VIEW here re-optimized the whole wide
    CASE-expression tree once per measure -- 138s in a single transform()
    call for one 4-row table, confirmed directly by swapping VIEW for TABLE
    with everything else unchanged, 0.05s afterward) with est_<col>/
    moe_<col>/status_<col> DOUBLE/VARCHAR columns for every declared ACS
    variable, resolved from its jam values exactly once (module docstring's
    sentinel table). Also passes through geo_id and B19013_M001's raw string
    (needed unresolved for the median-in-open-interval special case in
    `transform`).

    Built as one materialized TABLE per source table, joined into the final
    `resolved` TABLE, rather than a single CREATE TABLE with all ~650
    columns' CASE expressions at once -- CI (a much smaller box than this
    was developed on) ran the single-statement version out of memory
    (`Out of Memory Error ... 12.4 GiB/12.4 GiB used`) planning ONE query
    with the whole table set's nested CASE/IN expressions simultaneously, on
    fixture data of a few rows -- a planning-time cost, not a data-volume
    one. Splitting per table bounds any one CREATE TABLE's expression count
    to that table's own variable count (at most B27001's 57 -- ~171 output
    columns -- instead of all ~216 variables' ~650 at once); the final join
    only copies already-resolved columns, no CASE trees left to plan. Also
    faster where it didn't OOM: a single transform() call dropped from 138s
    (VIEW) to 21s (one wide TABLE) to 1.8s (this per-table-then-join form)."""
    per_table = ['resolved_base']
    con.execute('CREATE OR REPLACE TEMP TABLE resolved_base AS '
               'SELECT geo_id, "B19013_M001" AS "raw_B19013_M001" FROM raw')
    for table_id, n in TABLE_VARS.items():
        cols = ["geo_id"]
        for i in range(1, n + 1):
            e_col = f"{table_id}_E{i:03d}"
            m_col = f"{table_id}_M{i:03d}"
            cols.append(f'CASE WHEN "{e_col}" IN {EST_JAM} THEN NULL '
                       f'ELSE TRY_CAST("{e_col}" AS DOUBLE) END AS "est_{e_col}"')
            cols.append(f'CASE WHEN "{e_col}" IN {EST_JAM} OR "{m_col}" IN {MOE_JAM} THEN NULL '
                       f'ELSE TRY_CAST("{m_col}" AS DOUBLE) END AS "moe_{e_col}"')
            cols.append(f'CASE WHEN "{e_col}" IN {("-666666666", "-999999999")} '
                       f"THEN 'suppressed_small_count' WHEN \"{e_col}\" = '-888888888' "
                       f"THEN 'not_applicable' ELSE 'reported' END AS \"status_{e_col}\"")
        tbl = f"resolved_{table_id}"
        con.execute(f"CREATE OR REPLACE TEMP TABLE {tbl} AS SELECT {', '.join(cols)} FROM raw")
        per_table.append(tbl)

    join_sql = " JOIN ".join(f"{t} USING (geo_id)" if i else t for i, t in enumerate(per_table))
    con.execute(f"CREATE OR REPLACE TEMP TABLE resolved AS SELECT * FROM {join_sql}")
    for t in per_table:
        con.execute(f"DROP TABLE {t}")


def _leaf(e_col, m_col):
    """(est_sql, moe_sql, status_sql): simple references into `resolved`."""
    return f'"est_{e_col}"', f'"moe_{e_col}"', f'"status_{e_col}"'


def _combine(pairs, signs=None):
    """(est_sql, moe_sql) for a sum (or, with signs, a difference) of raw
    cells -- Compass handbook formula (1); a difference reuses the sum
    formula (module docstring)."""
    signs = signs or [1] * len(pairs)
    leaves = [_leaf(e, m) for e, m in pairs]
    ests = [l[0] for l in leaves]
    moes = [l[1] for l in leaves]
    any_est_null = " OR ".join(f"(({e}) IS NULL)" for e in ests)
    any_moe_null = " OR ".join(f"(({m}) IS NULL)" for m in moes)
    terms = " + ".join(f"(({s})*({e}))" for s, e in zip(signs, ests))
    est = f"CASE WHEN {any_est_null} THEN NULL ELSE ({terms}) END"
    sq = " + ".join(f"pow({m}, 2)" for m in moes)
    moe = f"CASE WHEN {any_est_null} OR {any_moe_null} THEN NULL ELSE sqrt({sq}) END"
    return est, moe


def _pct(num, den):
    """(pct_sql, pct_moe_sql) for 100 * num/den, num a nested subset of den --
    Compass handbook formula (6), with its documented fallback (add instead of
    subtract under the square root when the subtraction would go negative)."""
    ne, nm = num
    de, dm = den
    bad = f"(({ne}) IS NULL OR ({de}) IS NULL OR ({de}) = 0)"
    p = f"(({ne}) / NULLIF({de}, 0))"
    inside = f"(pow({nm}, 2) - pow({p}, 2) * pow({dm}, 2))"
    moe_p = f"CASE WHEN ({inside}) >= 0 THEN sqrt({inside}) ELSE sqrt(pow({nm}, 2) + pow({p}, 2) * pow({dm}, 2)) END"
    pct = f"CASE WHEN {bad} THEN NULL ELSE 100.0 * {p} END"
    pct_moe = f"CASE WHEN {bad} OR ({nm}) IS NULL OR ({dm}) IS NULL THEN NULL ELSE 100.0 * {moe_p} END"
    return pct, pct_moe


def _composed_status(est_sql):
    return f"CASE WHEN ({est_sql}) IS NOT NULL THEN 'reported' ELSE 'suppressed_small_count' END"


class _Measure:
    """One (measure_id, stratum_id) row-family: a value/moe SQL pair, plus
    enough to fill measure.definition/measure.stratum once per measure_id."""

    def __init__(self, measure_id, stratum_id, label, universe, rate_basis, doc,
                 value, moe, status, numerator="NULL", denominator="NULL", median=False):
        self.measure_id = measure_id
        self.stratum_id = stratum_id
        self.label = label
        self.universe = universe
        self.rate_basis = rate_basis
        self.doc = doc
        self.value = value
        self.moe = moe
        self.status = status
        self.numerator = numerator
        self.denominator = denominator
        self.median = median


def _measures():
    total = _leaf("B01003_E001", "B01003_M001")
    total_pair = (total[0], total[1])

    def leaf_pair(e, m):
        l = _leaf(e, m)
        return (l[0], l[1]), l[2]

    under18_pair, _ = leaf_pair("B09001_E001", "B09001_M001")
    over65_pair, _ = leaf_pair("B09020_E001", "B09020_M001")
    age1864 = _combine([("B01003_E001", "B01003_M001"), ("B09001_E001", "B09001_M001"),
                        ("B09020_E001", "B09020_M001")], signs=[1, -1, -1])

    race_total_pair, _ = leaf_pair("B03002_E001", "B03002_M001")
    hispanic_pair, _ = leaf_pair("B03002_E012", "B03002_M012")
    nh_white_pair, _ = leaf_pair("B03002_E003", "B03002_M003")
    nh_black_pair, _ = leaf_pair("B03002_E004", "B03002_M004")
    nh_asian_pair, _ = leaf_pair("B03002_E006", "B03002_M006")
    other_race = _combine([("B03002_E005", "B03002_M005"), ("B03002_E007", "B03002_M007"),
                           ("B03002_E008", "B03002_M008"), ("B03002_E009", "B03002_M009")])

    edu_total_pair, _ = leaf_pair("B15003_E001", "B15003_M001")
    no_hs = _combine([(f"B15003_E{i:03d}", f"B15003_M{i:03d}") for i in range(2, 17)])
    bachelors_plus = _combine([(f"B15003_E{i:03d}", f"B15003_M{i:03d}") for i in (22, 23, 24, 25)])

    poverty_below = _combine([("C17002_E002", "C17002_M002"), ("C17002_E003", "C17002_M003")])
    poverty_total_pair, _ = leaf_pair("C17002_E001", "C17002_M001")

    lfpr_num_pair, _ = leaf_pair("B23025_E002", "B23025_M002")
    lfpr_den_pair, _ = leaf_pair("B23025_E001", "B23025_M001")
    unemp_num_pair, _ = leaf_pair("B23025_E005", "B23025_M005")
    unemp_den_pair, _ = leaf_pair("B23025_E003", "B23025_M003")

    novehicle = _combine([("B25044_E003", "B25044_M003"), ("B25044_E010", "B25044_M010")])
    occ_total_pair, _ = leaf_pair("B25044_E001", "B25044_M001")

    vacant_pair, _ = leaf_pair("B25002_E003", "B25002_M003")
    housing_total_pair, _ = leaf_pair("B25002_E001", "B25002_M001")

    rent_ge30 = _combine([(f"B25070_E{i:03d}", f"B25070_M{i:03d}") for i in (7, 8, 9, 10)])
    rent_ge50_pair, _ = leaf_pair("B25070_E010", "B25070_M010")
    rent_den = _combine([("B25070_E001", "B25070_M001"), ("B25070_E011", "B25070_M011")],
                        signs=[1, -1])

    limited_english = _combine([(f"C16002_E{i:03d}", f"C16002_M{i:03d}") for i in (4, 7, 10, 13)])
    households_pair, _ = leaf_pair("C16002_E001", "C16002_M001")

    uninsured = _combine([(f"B27001_E{i:03d}", f"B27001_M{i:03d}")
                          for i in (5, 8, 11, 14, 17, 20, 23, 26, 29,
                                    33, 36, 39, 42, 45, 48, 51, 54, 57)])
    insurance_universe_pair, _ = leaf_pair("B27001_E001", "B27001_M001")

    medicaid = _combine([(f"C27007_E{i:03d}", f"C27007_M{i:03d}") for i in (4, 7, 10, 14, 17, 20)])
    medicaid_universe_pair, _ = leaf_pair("C27007_E001", "C27007_M001")

    income_e, income_m, income_status = _leaf("B19013_E001", "B19013_M001")
    gini_e, gini_m, gini_status = _leaf("B19083_E001", "B19083_M001")

    m = []
    m.append(_Measure("ACS:total_population", "ACS:ALL", "Total population",
                      "Total population", "count",
                      "Total population (B01003_001).",
                      *total))

    age_universe = "Total population"
    age_pct = {"under_18": _pct(under18_pair, total_pair),
              "age_18_64": _pct(age1864, total_pair),
              "age_65_plus": _pct(over65_pair, total_pair)}
    age_doc = ("Share of total population in a CIF-parity age bracket. Under 18 (B09001_001) "
              "and 65 and over (B09020_001) are ACS's own published bracket totals; 18-64 is "
              "not published anywhere in ACS (every age table bins in spans that straddle 18) "
              "and is derived as the residual total - under18 - 65plus.")
    for stratum, (val, moe) in age_pct.items():
        num = {"under_18": under18_pair[0], "age_18_64": age1864[0],
              "age_65_plus": over65_pair[0]}[stratum]
        m.append(_Measure("ACS:age_distribution", f"ACS:age:{stratum}",
                          "Age distribution", age_universe, "percent", age_doc,
                          val, moe, _composed_status(val), numerator=num, denominator=total[0]))

    race_universe = "Total population"
    race_doc = ("Share of total population by CIF-parity race/ethnicity bucket (B03002, OMB "
               "1997-style categories). 'other' sums NH American Indian/Alaska Native, NH "
               "Native Hawaiian/Pacific Islander, NH Some Other Race and NH Two-or-more races.")
    race_rows = {"hispanic": (hispanic_pair, hispanic_pair[0]),
                "nh_white": (nh_white_pair, nh_white_pair[0]),
                "nh_black": (nh_black_pair, nh_black_pair[0]),
                "nh_asian": (nh_asian_pair, nh_asian_pair[0]),
                "other": (other_race, other_race[0])}
    for stratum, (pair, num) in race_rows.items():
        val, moe = _pct(pair, race_total_pair)
        m.append(_Measure("ACS:race_ethnicity", f"ACS:race:{stratum}",
                          "Race/ethnicity distribution", race_universe, "percent", race_doc,
                          val, moe, _composed_status(val), numerator=num, denominator=race_total_pair[0]))

    val, moe = _pct(no_hs, edu_total_pair)
    m.append(_Measure("ACS:no_hs_diploma", "ACS:ALL", "No high school diploma",
                      "Population 25 years and over", "percent",
                      "Percent of the population 25+ with less than a high school diploma "
                      "(B15003, sum of 'no schooling completed' through '12th grade, no diploma').",
                      val, moe, _composed_status(val), numerator=no_hs[0], denominator=edu_total_pair[0]))

    val, moe = _pct(bachelors_plus, edu_total_pair)
    m.append(_Measure("ACS:bachelors_or_higher", "ACS:ALL", "Bachelor's degree or higher",
                      "Population 25 years and over", "percent",
                      "Percent of the population 25+ with a bachelor's degree or higher "
                      "(B15003, sum of bachelor's/master's/professional/doctorate degrees).",
                      val, moe, _composed_status(val), numerator=bachelors_plus[0], denominator=edu_total_pair[0]))

    m.append(_Measure("ACS:median_household_income", "ACS:ALL", "Median household income",
                      "Households", "count",
                      "Median household income in the past 12 months, in the release's own "
                      "inflation-adjusted dollars (B19013_001).",
                      income_e, income_m, income_status, median=True))

    val, moe = _pct(poverty_below, poverty_total_pair)
    m.append(_Measure("ACS:poverty_rate", "ACS:ALL", "Poverty rate",
                      "Population for whom poverty status is determined", "percent",
                      "Percent of the population with income-to-poverty ratio below 1.00 "
                      "(C17002, 'Under .50' + '.50 to .99').",
                      val, moe, _composed_status(val), numerator=poverty_below[0], denominator=poverty_total_pair[0]))

    val, moe = _pct(lfpr_num_pair, lfpr_den_pair)
    m.append(_Measure("ACS:labor_force_participation", "ACS:ALL", "Labor force participation rate",
                      "Population 16 years and over", "percent",
                      "Percent of the population 16+ in the labor force (B23025_002 / B23025_001).",
                      val, moe, _composed_status(val), numerator=lfpr_num_pair[0], denominator=lfpr_den_pair[0]))

    val, moe = _pct(unemp_num_pair, unemp_den_pair)
    m.append(_Measure("ACS:unemployment_rate", "ACS:ALL", "Unemployment rate",
                      "Civilian labor force", "percent",
                      "Percent of the civilian labor force unemployed (B23025_005 / B23025_003).",
                      val, moe, _composed_status(val), numerator=unemp_num_pair[0], denominator=unemp_den_pair[0]))

    val, moe = _pct(novehicle, occ_total_pair)
    m.append(_Measure("ACS:no_vehicle_households", "ACS:ALL", "Households with no vehicle available",
                      "Occupied housing units", "percent",
                      "Percent of occupied housing units with no vehicle available (B25044, "
                      "owner-occupied + renter-occupied 'no vehicle available' rows).",
                      val, moe, _composed_status(val), numerator=novehicle[0], denominator=occ_total_pair[0]))

    val, moe = _pct(vacant_pair, housing_total_pair)
    m.append(_Measure("ACS:vacant_housing", "ACS:ALL", "Vacant housing units",
                      "Total housing units", "percent",
                      "Percent of total housing units that are vacant (B25002_003 / B25002_001).",
                      val, moe, _composed_status(val), numerator=vacant_pair[0], denominator=housing_total_pair[0]))

    val, moe = _pct(rent_ge30, rent_den)
    m.append(_Measure("ACS:rent_burden_30", "ACS:ALL", "Rent burden (>=30% of income)",
                      "Occupied units paying rent, excluding units where GRAPI cannot be computed",
                      "percent",
                      "Percent of GRAPI-computable renter units paying 30% or more of household "
                      "income in gross rent (B25070, '30.0 to 34.9' + '35.0 to 39.9' + "
                      "'40.0 to 49.9' + '50.0 percent or more').",
                      val, moe, _composed_status(val), numerator=rent_ge30[0], denominator=rent_den[0]))

    val, moe = _pct(rent_ge50_pair, rent_den)
    m.append(_Measure("ACS:rent_burden_50", "ACS:ALL", "Rent burden (>=50% of income)",
                      "Occupied units paying rent, excluding units where GRAPI cannot be computed",
                      "percent",
                      "Percent of GRAPI-computable renter units paying 50% or more of household "
                      "income in gross rent (B25070_010).",
                      val, moe, _composed_status(val), numerator=rent_ge50_pair[0], denominator=rent_den[0]))

    m.append(_Measure("ACS:gini_index", "ACS:ALL", "Gini index of income inequality",
                      "Households", "index",
                      "Gini index of household income inequality, 0 (perfect equality) to 1 "
                      "(perfect inequality) (B19083_001).",
                      gini_e, gini_m, gini_status))

    val, moe = _pct(limited_english, households_pair)
    m.append(_Measure("ACS:limited_english_households", "ACS:ALL", "Limited English speaking households",
                      "Households", "percent",
                      "Percent of households that are 'limited English speaking households' "
                      "(C16002, summed across Spanish/other Indo-European/Asian-Pacific/other "
                      "language groups).",
                      val, moe, _composed_status(val), numerator=limited_english[0], denominator=households_pair[0]))

    val, moe = _pct(uninsured, insurance_universe_pair)
    m.append(_Measure("ACS:uninsured", "ACS:ALL", "Uninsured",
                      "Civilian noninstitutionalized population", "percent",
                      "Percent of the civilian noninstitutionalized population with no health "
                      "insurance coverage (B27001, summed 'No health insurance coverage' cells "
                      "across all 9 age brackets x 2 sexes).",
                      val, moe, _composed_status(val), numerator=uninsured[0], denominator=insurance_universe_pair[0]))

    val, moe = _pct(medicaid, medicaid_universe_pair)
    m.append(_Measure("ACS:medicaid_coverage", "ACS:ALL", "Medicaid or means-tested public coverage",
                      "Civilian noninstitutionalized population", "percent",
                      "Percent of the civilian noninstitutionalized population with Medicaid or "
                      "other means-tested public health insurance coverage (C27007, summed 'With "
                      "Medicaid/means-tested public coverage' cells across all 3 age brackets x 2 "
                      "sexes).",
                      val, moe, _composed_status(val), numerator=medicaid[0], denominator=medicaid_universe_pair[0]))
    return m


def transform(cat, release, year):
    """Phase 2: measure.definition / measure.stratum / measure.observation for
    one `year`, rebuilt from WHICHEVER of raw.acs__county / raw.acs__tract are
    landed for it (not just the level `ingest` was just called for).

    County and tract share one `source_release` (they're the same ACS
    release, just two geography grains), and measure.observation's merge
    scope is (source, source_release) -- not per-level, matching
    measure.observation's declared business key. Deriving from only the
    level just landed would make `incoming` an INCOMPLETE state for that
    scope, and merge.merge retires whatever's missing from it: landing tract
    after county silently deleted every county row for the release (caught
    in this PR's own real ingest; see cdc_svi.py's identical fix/comment for
    the same two-level-one-scope shape). Scoped to `acs_year = year`: raw
    accumulates every landed release, so an unscoped read would derive from
    all of them at once.
    """
    con = duckdb.connect()
    levels = []
    for level in ("county", "tract"):
        try:
            con.register(f"{level}_raw", cat.load_table(f"raw.acs__{level}").scan(
                row_filter=EqualTo("acs_year", year)).to_arrow())
            levels.append(level)
        except NoSuchTableError:
            pass
    if not levels:
        raise SystemExit(f"census_acs: neither raw.acs__county nor raw.acs__tract has "
                         f"acs_year = {year} landed yet")
    con.execute("CREATE OR REPLACE VIEW raw AS " +
               " UNION ALL ".join(f"SELECT * FROM {lvl}_raw" for lvl in levels))
    _build_resolved(con)

    geo_vintage = GEO_VINTAGE[year]
    source_release = f"{year - 4}-{year}"
    measures = _measures()

    definition_rows = {}
    stratum_rows = {}
    obs_selects = []
    for meas in measures:
        definition_rows[meas.measure_id] = (
            meas.measure_id, meas.label, meas.universe, meas.rate_basis, meas.doc)
        stratum_rows[meas.stratum_id] = meas.stratum_id

        if meas.median:
            # The one true median in this table set: an artificial
            # open-interval boundary (jam -333333333) is not a real value.
            value_sql = (f"CASE WHEN {meas.status} != 'reported' THEN NULL "
                        f"WHEN \"raw_B19013_M001\" = '-333333333' THEN NULL ELSE ({meas.value}) END")
            status_sql = (f"CASE WHEN \"raw_B19013_M001\" = '-333333333' THEN 'not_available' "
                         f"ELSE ({meas.status}) END")
            moe_sql = f"CASE WHEN \"raw_B19013_M001\" = '-333333333' THEN NULL ELSE ({meas.moe}) END"
        else:
            value_sql = f"CASE WHEN ({meas.status}) = 'reported' THEN ({meas.value}) ELSE NULL END"
            status_sql = meas.status
            moe_sql = meas.moe

        obs_selects.append(f"""
            SELECT 'ACS' AS source, '{source_release}' AS source_release,
                   '{meas.measure_id}' AS measure_id,
                   geo_id, {geo_vintage} AS geo_vintage,
                   '{year - 4}' AS period_start, '{year}' AS period_end,
                   '{meas.stratum_id}' AS stratum_id,
                   {value_sql} AS value,
                   CASE WHEN ({moe_sql}) IS NULL THEN NULL ELSE ({value_sql}) - ({moe_sql}) END AS lower,
                   CASE WHEN ({moe_sql}) IS NULL THEN NULL ELSE ({value_sql}) + ({moe_sql}) END AS upper,
                   CASE WHEN ({moe_sql}) IS NULL THEN NULL ELSE 0.90 END AS interval_level,
                   {meas.numerator} AS numerator, {meas.denominator} AS denominator,
                   ({status_sql}) AS value_status,
                   NULL::VARCHAR AS reliability_flag, NULL::VARCHAR AS trend
            FROM resolved
        """)

    observation = con.sql(" UNION ALL ".join(obs_selects)).to_arrow_table()
    merge.check_observations(observation)

    def _sqs(s):
        """A SQL single-quoted string literal, embedded apostrophes doubled --
        several labels/docs below are plain English prose with real ones
        ('Bachelor's degree'), and Python's repr() would emit those as a
        double-quoted string, which DuckDB parses as an identifier, not a
        literal."""
        return "'" + s.replace("'", "''") + "'"

    def_values = ", ".join(
        f"('{mid}', {_sqs(lbl)}, {_sqs(uni)}, '{rb}', {_sqs(doc)})"
        for mid, lbl, uni, rb, doc in definition_rows.values())
    definition = con.sql(f"""
        SELECT measure_id, 'ACS' AS source, label, NULL::VARCHAR AS units, universe, rate_basis,
               NULL::VARCHAR AS age_adjustment, 'survey_direct' AS method,
               NULL::VARCHAR AS cancer_site_code, doc
        FROM (VALUES {def_values}) AS t(measure_id, label, universe, rate_basis, doc)
    """).to_arrow_table()

    stratum_scheme = {sid: ("ACS_RACE_OMB1997" if sid.startswith("ACS:race:")
                            else "ACS_AGE_CIF" if sid.startswith("ACS:age:")
                            else "ACS_NONE")
                      for sid in stratum_rows}
    stratum_values = ", ".join(f"('{sid}', '{scheme}')" for sid, scheme in stratum_scheme.items())
    stratum = con.sql(f"""
        SELECT stratum_id, 'ACS' AS source, NULL::VARCHAR AS sex, NULL::VARCHAR AS age_group,
               NULL::VARCHAR AS race_ethnicity, NULL::VARCHAR AS stage, NULL::VARCHAR AS other,
               scheme
        FROM (VALUES {stratum_values}) AS t(stratum_id, scheme)
    """).to_arrow_table()

    scope = EqualTo("source", "ACS")
    # Overwrite only the ids this ingest asserts, not the whole `source =
    # 'ACS'` scope -- the wholesale-replace shape that deleted a live
    # definition a live observation still referenced (#76).
    return {
        "measure.definition": merge.write(
            cat, "measure.definition", definition,
            And(scope, In("measure_id", list(definition_rows)))),
        "measure.stratum": merge.write(
            cat, "measure.stratum", stratum,
            And(scope, In("stratum_id", list(stratum_rows)))),
        "measure.observation": merge.merge(
            cat, "measure.observation", observation, release,
            And(scope, EqualTo("source_release", source_release))),
    }


def ingest(cat, release, year, level, dat_dir=None):
    year, n = land_raw(cat, release, year, level, dat_dir)
    return {f"raw.acs__{level}": n, **transform(cat, release, year)}
