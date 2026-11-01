"""EPA Map of Radon Zones (county) -> Iceberg.

Upstream: https://www.epa.gov/radon/epa-map-radon-zones links "Text Version -
Radon Zones Map (xls)" -- the only bulk, machine-readable form (the other
link is a PDF map image). The real download (verified 2026-09-19; HTTP
`last-modified: Mon, 22 Sep 2025`, `content-length: 658944`) is
`https://www.epa.gov/system/files/documents/2024-05/radon_zones-spreadsheet.xls`,
a legacy Excel 97-2003 binary (`.xls`, OLE2/BIFF8) file -- not the OOXML
`.xlsx` DuckDB's `excel` extension reads (verified: `read_xlsx` on it fails
with "No xl/workbook.xml found in xlsx file"; DuckDB's `spatial` extension's
GDAL driver also fails to open it). No CSV or `.xlsx` form of this dataset
exists anywhere on epa.gov (checked 2026-09-19: the per-state "supporting
documents" page links only PDFs). This is the same wall `ers_rucc.py` hit for
its 2013 edition, but here the legacy file *is* the only edition there is --
skipping it skips this issue's entire measure, not one optional extra vintage
-- so `xlrd` (the standard, single-purpose, pure-Python BIFF reader; zero
transitive dependencies) is added as a real, recorded new dependency
(AGENTS.md: "No new dependencies without a recorded reason") rather than
leaving the issue unimplemented.

**Licence.** EPA's own data licence page
(https://edg.epa.gov/EPA_Data_License.html, checked 2026-09-19) states
verbatim: "Unless otherwise specified, all data produced by the U.S EPA is by
default in the public domain and is not subject to domestic copyright
protection." No registration or attribution is required to redistribute --
the same authority `epa_sdwis.py` cites for the same agency.

**The two sheets.** The workbook carries three sheets: `un-filtered-raw-data`,
`filtered-raw data`, and an empty `Sheet3`. The first two are row-aligned
(verified against the real 3,222-row file: identical `County,State`,
`COUNTY LABEL`, `STATE` and `Region` columns in every row) and differ only in
`Zone`, for exactly 9 of 3,144 real county rows (e.g. Anchorage Municipality,
AK: 3 unfiltered vs. 2 filtered). Both are landed verbatim (ADR-0002); the
derived measure reads `zone_filtered` -- the sheet name reads as the
post-QA/final product, `un-filtered-raw-data` as its working input -- and
`zone_unfiltered` is kept in raw so a future PR can revisit that choice
without re-fetching upstream.

**Row filter.** Real per-entity rows are the only ones with a numeric `Zone`
cell (`xlrd.XL_CELL_NUMBER`); a `UNITED STATES` or state-name row (e.g.
`ALABAMA`) carries the literal string `'.'` in `Zone` (EPA's own print-layout
subtotal marker) and a blank trailer row carries nothing at all. Neither is a
county observation, so neither is landed -- the same treatment this project
already gives a plain header row (e.g. `census_gazetteer.py`'s `skip=1`),
extended to the source's own mid-file subtotal rows since they carry no more
information than one.

**Versioning: single 1993 edition** (SPEC.md's own instruction for this
issue). EPA developed the map in 1993 (EPA+USGS: indoor radon measurements,
geology, aerial radioactivity, soil parameters, foundation types) and has
never issued a second national assessment; the file's September 2025
`last-modified` date reflects administrative corrections to county identity
(new counties, renames, mergers -- see "Geography" below), not a re-run of
the underlying science. `merge.manifest` records `version='1993'`,
`method='release_number'` -- a real, citable label EPA's own page states, not
this project inventing an edition. Raw is replaced wholesale (`AlwaysTrue()`)
each time, like `raw.geography__county_recodes` -- there is no second edition
to keep side by side.

**Zone definitions**, verbatim from EPA's per-state supporting documents
(e.g. https://www.epa.gov/sites/default/files/2014-08/documents/alabama.pdf,
checked 2026-09-19 -- identical boilerplate text across every state's PDF,
linked from https://www.epa.gov/radon/epa-maps-radon-zones-and-supporting-documents-state):
"Zone 1 (red zones) Highest potential: Counties have a predicted average
indoor screening level > (greater) than 4 pCi/L... Zone 2 (orange zones)
Moderate potential: Counties have a predicted average screening level >=
(greater than or equal to) 2 pCi/L and <= (less than or equal to) 4 pCi/L...
Zone 3 (yellow zones) Low potential: Counties have a predicted average indoor
screening level < (less than) 2 pCi/L." See `CODE_DOC`.

**Geography: no FIPS in the source at all** -- only a state name and a county
label (`.Autauga County`), unlike every other county source this project has
landed. This really is the crosswalk exercise the issue calls for: rows are
matched by (state name, county name) against `geography.unit` at
`GEO_VINTAGE = 2010` -- the same vintage `epa_sdwis.py` already chose for the
same reason (its own module docstring): 2010 predates Alaska's 2019
Valdez-Cordova split and Connecticut's 2022 planning-region switch, and this
source's own county labels confirm it still uses the *pre*-recode names for
everything that has since been renamed or split (verified against the real
file): `Shannon County` (SD, not 2015's Oglala Lakota), `Wade Hampton Census
Area` (AK, not 2015's Kusilvak), `Valdez-Cordova Census Area` (AK, not 2019's
Chugach/Copper River split), the 8 legacy Connecticut counties (not the 9
2022 planning regions). `geography.alias` (#26) already carries the first two
recodes, so a reader joining through it resolves them to their current code
without this module doing anything special -- landing the FIPS as it stood at
the 2010 vintage *is* "resolving old FIPS through geography.alias", per the
issue's own instruction, not a separate step this module performs itself. A
few entities are already spelled post-recode in the source (`Miami-Dade
County` FL, `Broomfield County` CO -- created 2001), which resolve directly
since 2010 postdates both.

Matching itself: `strip_accents()` on both sides of the name comparison (the
source spells New Mexico's `Dona Ana County` without its tilde; the 2010
Gazetteer has `Doña Ana County` -- `census_gazetteer.py`'s own documented
encoding quirk) -- an accent-insensitive comparison, not a hardcoded
substitution for this one county, so it also covers any other diacritic the
1990s-era source dropped. Virginia's 41 independent cities are a genuine row
shape different from every other row (verified against the real file):
`STATE = 'VA-CITY'` instead of `'Virginia'`, and `COUNTY LABEL` repeats the
`'<City>, VA'` label verbatim instead of a dot-prefixed county name (e.g. row
`('Alexandria, VA', 'Alexandria, VA', 'VA-CITY', ...)`). These are matched by
stripping the trailing `', VA'` and appending `' city'` (`census_gazetteer`'s
own naming: `Alexandria city`, `Baltimore city`, `Carson City` -- Nevada's
consolidated city-county is a normal dot-prefixed row and needs no special
case) -- the same census-conventioned FIPS entity, just published in a
different column layout.

**Unmatched: reported, not guessed** (SPEC.md; issue: "report every county
that does not resolve"). Verified against the real download: 5 of 3,144 real
rows do not resolve against the 2010-vintage `geography.unit`, all for
reasons pre-dating that vintage or unrelated to it, none from a matching bug:
  - `Prince of Wales-Outer Ketchikan, AK` and `Wrangell-Petersburg, AK` --
    both real boundary changes (annexation-with-rename, and a two-way split)
    that `geography_alias.py`'s own docstring already excludes from
    `geography.alias` as not a pure recode; unresolvable by name match at any
    vintage without a weighted crosswalk (`geography.crosswalk`, #25).
  - `Clifton Forge, VA` and `South Boston, VA` -- both independent cities
    that merged into their surrounding county (2001 and 1995 respectively)
    *before* the 2010 vintage this module matches against, so 2010's
    `geography.unit` never carried them.
  - `Yellowstone National Park, MT` -- not a county or county-equivalent at
    all; a standing EPA data quirk (the park spans three states and has no
    FIPS code of its own).
`transform` prints each unmatched `county_state` label and excludes it from
the derived measure -- the same pattern `epa_sdwis.py` uses for its own
unresolved rows.

ponytail: matching is exact (post accent-stripping), not fuzzy -- SPEC.md's
"never fuzzy-matched" rule for geography resolution (`epa_sdwis.py`'s own
module docstring states the same principle for its ANSI-code join). The 5
genuinely unresolved counties above are reported and dropped rather than
guessed at.
"""

import tempfile
import urllib.request
from pathlib import Path

import duckdb
import pyarrow as pa
import xlrd
from pyiceberg.expressions import AlwaysTrue, And, EqualTo, In

from . import merge

URL = "https://www.epa.gov/system/files/documents/2024-05/radon_zones-spreadsheet.xls"
USER_AGENT = "cancerbasemap/1.0 (+https://github.com/seandavi/cancer-basemap)"
EDITION = "1993"
GEO_VINTAGE = 2010
MEASURE_ID = "EPA_RADON:zone"
STRATUM_ID = "EPA_RADON:none"

SHEET_FILTERED = "filtered-raw data"
SHEET_UNFILTERED = "un-filtered-raw-data"
# The header's first 5 columns, in file order -- both sheets share this exact
# prefix (verified 2026-09-19); trailing columns are blank/inconsistent
# noise (module docstring) and not read.
HEADER = ("County,State", "COUNTY LABEL", "STATE", "Region", "Zone")

CODE_DOC = (
    "EPA Map of Radon Zones (developed 1993 by EPA and USGS). Zone 1 (red zones) "
    "Highest potential: Counties have a predicted average indoor screening level > "
    "(greater) than 4 pCi/L (picocuries per liter) (150 Bq/m3 (becquerels per meter "
    "cubed)). Zone 2 (orange zones) Moderate potential: Counties have a predicted "
    "average screening level >= (greater than or equal to) 2 pCi/L (75 Bq/m3) and <= "
    "(less than or equal to) 4 pCi/L (150 Bq/m3). Zone 3 (yellow zones) Low "
    "potential: Counties have a predicted average indoor screening level < (less "
    "than) 2 pCi/L (75 Bq/m3)."
)


def _fetch(url):
    """The file's bytes. A local path (tests) is read directly; a remote URL
    goes through urllib with a descriptive User-Agent."""
    if not url.startswith("http"):
        return Path(url).read_bytes()
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req) as r:
        return r.read()


def _read_sheet(wb, name):
    """One sheet's real per-entity rows: (county_state, county_label, state,
    zone) -- kept only where Zone is a real number, which is exactly what
    marks a genuine county-or-equivalent row rather than a state-subtotal or
    blank trailer row (module docstring)."""
    sh = wb.sheet_by_name(name)
    header = tuple(sh.cell_value(0, c) for c in range(len(HEADER)))
    if header != HEADER:
        raise SystemExit(f"epa_radon: sheet {name!r} header is not the declared one; "
                         f"differs in {sorted(set(header) ^ set(HEADER))}")
    return [(sh.cell_value(r, 0), sh.cell_value(r, 1), sh.cell_value(r, 2), sh.cell_value(r, 4))
            for r in range(1, sh.nrows) if sh.cell_type(r, 4) == xlrd.XL_CELL_NUMBER]


def land_raw(cat, release, url=None):
    """Phase 1: both sheets' real rows, landed verbatim and whole (module
    docstring on why both). Single, ever-only edition (SPEC.md's own
    instruction), so raw is replaced wholesale each time."""
    url = url or URL
    with tempfile.NamedTemporaryFile(suffix=".xls") as tmp:
        tmp.write(_fetch(url))
        tmp.flush()
        wb = xlrd.open_workbook(tmp.name)

    unfiltered = {(cs, cl, st): zone for cs, cl, st, zone in _read_sheet(wb, SHEET_UNFILTERED)}
    filtered = _read_sheet(wb, SHEET_FILTERED)
    if len(unfiltered) != len(filtered):
        raise SystemExit(f"epa_radon: {url} sheets carry a different number of real rows "
                         f"({len(unfiltered)} vs {len(filtered)})")

    con = duckdb.connect()
    con.register("t", pa.Table.from_pylist([
        dict(county_state=cs, county_label=cl, state=st,
             zone_unfiltered=unfiltered.get((cs, cl, st)), zone_filtered=zf)
        for cs, cl, st, zf in filtered
    ]))
    arrow = con.sql(f"SELECT *, '{release}' AS landed_in FROM t").to_arrow_table()
    if not arrow.num_rows:
        raise SystemExit(f"epa_radon: {url} yielded no rows")

    n = merge.write(cat, "raw.epa__radon_zones", arrow, AlwaysTrue())
    merge.manifest(cat, release, "epa_radon", url, n, version=EDITION, method="release_number")
    return n


def transform(cat, release):
    """Phase 2: one radon-zone observation per county resolved by name against
    `geography.unit` at GEO_VINTAGE (module docstring -- the source publishes
    no FIPS code at all)."""
    con = duckdb.connect()
    con.register("raw", cat.load_table("raw.epa__radon_zones").scan().to_arrow())
    con.register("county", cat.load_table("geography.unit").scan(
        row_filter=And(EqualTo("vintage", GEO_VINTAGE), EqualTo("level", "county"))).to_arrow())
    con.register("state", cat.load_table("geography.unit").scan(
        row_filter=And(EqualTo("vintage", GEO_VINTAGE), EqualTo("level", "state"))).to_arrow())

    dup = con.sql("""
        SELECT s.name, c.name, count(*) FROM county c JOIN state s ON s.geo_id = c.parent_geo_id
        GROUP BY 1, 2 HAVING count(*) > 1
    """).fetchall()
    if dup:
        raise SystemExit(f"epa_radon: geography.unit vintage={GEO_VINTAGE} has ambiguous "
                         f"(state, county) names {dup}; name matching cannot be trusted")

    resolved = con.sql("""
        WITH named AS (
            SELECT *,
                   CASE WHEN county_label LIKE '.%' THEN substr(county_label, 2)
                        WHEN state = 'VA-CITY' THEN regexp_replace(county_state, ', VA$', '') || ' city'
                        ELSE county_label END AS name,
                   CASE WHEN state = 'VA-CITY' THEN 'Virginia' ELSE state END AS join_state
            FROM raw
        ),
        county_named AS (
            SELECT c.fips, c.name, s.name AS state_name
            FROM county c JOIN state s ON s.geo_id = c.parent_geo_id
        )
        SELECT n.county_state, n.zone_filtered, cn.fips
        FROM named n
        LEFT JOIN county_named cn
          ON strip_accents(cn.name) = strip_accents(n.name) AND cn.state_name = n.join_state
    """).to_arrow_table()
    con.register("resolved", resolved)

    total = resolved.num_rows
    unmatched = con.sql("SELECT county_state FROM resolved WHERE fips IS NULL ORDER BY 1").fetchall()
    if unmatched:
        names = ", ".join(r[0] for r in unmatched)
        print(f"epa_radon: {len(unmatched):,}/{total:,} ({len(unmatched) / total:.1%}) county "
             f"rows did not resolve to a known FIPS code against geography.unit "
             f"vintage={GEO_VINTAGE} (name-matched) and are excluded from the derived measure, "
             f"not fuzzy-matched: {names}")

    observation = con.sql(f"""
        SELECT 'EPA_RADON' AS source, '{EDITION}' AS source_release, '{MEASURE_ID}' AS measure_id,
               'county:' || fips AS geo_id, {GEO_VINTAGE} AS geo_vintage,
               '{EDITION}' AS period_start, '{EDITION}' AS period_end,
               '{STRATUM_ID}' AS stratum_id, zone_filtered AS value,
               NULL::DOUBLE AS lower, NULL::DOUBLE AS upper, NULL::DOUBLE AS interval_level,
               NULL::DOUBLE AS numerator, NULL::DOUBLE AS denominator,
               'reported' AS value_status, NULL::VARCHAR AS reliability_flag, NULL::VARCHAR AS trend
        FROM resolved
        WHERE fips IS NOT NULL
    """).to_arrow_table()
    merge.check_observations(observation)

    definition = con.sql(f"""
        SELECT '{MEASURE_ID}' AS measure_id, 'EPA_RADON' AS source,
               'EPA Predicted Radon Zone' AS label, 'zone 1-3' AS units,
               NULL::VARCHAR AS universe, 'index' AS rate_basis,
               NULL::VARCHAR AS age_adjustment, 'derived' AS method,
               NULL::VARCHAR AS cancer_site_code, '{CODE_DOC}' AS doc
    """).to_arrow_table()
    stratum = con.sql(f"""
        SELECT '{STRATUM_ID}' AS stratum_id, 'EPA_RADON' AS source,
               NULL::VARCHAR AS sex, NULL::VARCHAR AS age_group,
               NULL::VARCHAR AS race_ethnicity, NULL::VARCHAR AS stage,
               NULL::VARCHAR AS other, 'EPA_RADON_NONE' AS scheme
    """).to_arrow_table()

    scope = EqualTo("source", "EPA_RADON")
    # Overwrite only the ids this release asserts (#76), not the whole
    # source = 'EPA_RADON' scope.
    return {
        "measure.definition": merge.write(cat, "measure.definition", definition,
                                          And(scope, In("measure_id", [MEASURE_ID]))),
        "measure.stratum": merge.write(cat, "measure.stratum", stratum,
                                       And(scope, In("stratum_id", [STRATUM_ID]))),
        "measure.observation": merge.merge(
            cat, "measure.observation", observation, release,
            And(scope, EqualTo("source_release", EDITION))),
    }


def ingest(cat, release, url=None):
    n = land_raw(cat, release, url)
    return {"raw.epa__radon_zones": n, **transform(cat, release)}
