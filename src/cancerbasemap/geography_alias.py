"""geography.alias -- FIPS renames and re-codings that are not boundary
changes (SPEC.md § geography.alias, #26), so a join on an old FIPS code
resolves to the new one rather than silently dropping (SPEC.md Acceptance B).

Upstream: the Census Bureau's "Substantial Changes to Counties and County
Equivalent Entities: 1970-Present" landing page
(https://www.census.gov/programs-surveys/geography/technical-documentation/
county-changes.html) and its decade sub-pages
(.../county-changes.1990.html, .../county-changes.2000.html,
.../county-changes.2010.html, .../county-changes.January_2020.html).
Checked 2026-09-18: none of these pages, nor the index page, link to a
machine-readable (CSV/XLS) file of name/code changes -- the only linked data
files are Connecticut's county-to-subdivision crosswalk (a boundary
crosswalk, not a rename/recode list; that belongs to geography.crosswalk,
#25). The page content itself is prose tables, so this source is a small
curated CSV committed in the package (`data/county_recodes.csv`), one row
per recode, each row's `note` column quoting the exact Census sentence it
was transcribed from with the decade page it came from as `source_url`.

**Licence.** census.gov carries no per-page copyright statement (checked
2026-09-18 against the index and every decade page used here), but it is a
federal agency site and the Bureau is a federal agency: "Data and content
created by government employees within the scope of their employment are
not subject to domestic copyright protection under 17 U.S.C. Sec 105.
Government works are by default in the U.S. Public Domain."
(https://resources.data.gov/open-licenses/, checked 2026-09-18) -- the same
authority the other Census/USDA sources in this package cite.

**Version axis.** Census publishes no edition label for this page (it is a
living document, amended as changes occur), so it is versioned like
`raw.census__state_fips`: `merge.manifest` records `version_method
="retrieval_date"` with the date this transcription was checked
(2026-09-18), and the raw table is replaced wholesale (`AlwaysTrue()`) each
time the curated CSV is revised, rather than accumulating "editions" that do
not exist upstream.

**Geography.** `old_geo_id`/`new_geo_id` carry no vintage: unlike
geography.unit (keyed on geo_id + vintage, since boundaries move), an alias
is a pure code mapping that a join resolves regardless of which vintage the
observation's geo_id came from.

Included -- pure recodes/renames since 2000, plus one 1997 recode still
carried by SCP-era data (per issue #26):
  - Shannon County, SD 46113 -> Oglala Lakota County, SD 46102 (2015)
  - Wade Hampton Census Area, AK 02270 -> Kusilvak Census Area, AK 02158 (2015)
  - Dade County, FL 12025 -> Miami-Dade County, FL 12086 (1997)
All three are Census's own "Name and/or Code Changes" category: the area is
untouched, only the FIPS code and name change.

Excluded -- real boundary changes, verified against the same decade pages,
left for geography.crosswalk (#25) because a weighted crosswalk, not a 1:1
alias, is the honest representation:
  - Connecticut's eight counties -> nine planning regions (2022): the
    planning regions do not share the counties' boundaries.
  - Valdez-Cordova Census Area, AK 02261 -> split into Chugach 02063 and
    Copper River 02066 (2019): one code becomes two areas, not a rename.
  - Bedford (independent) city, VA 51515 -> merged into Bedford County
    51019 (2013): a real annexation (~6,222 people), not a pure recode.
  - Broomfield County, CO 08014 (2001): a new entity assembled from parts of
    four other counties (Adams, Boulder, Jefferson, Weld), not a rename of
    any one of them.
  - Prince of Wales-Outer Ketchikan Census Area, AK 02201 -> Prince of
    Wales-Hyder 02198 (2008): the "rename" happened only because Ketchikan
    Gateway Borough annexed most of the area first -- a boundary change with
    a new name attached, not a pure recode.
  - Skagway-Hoonah-Angoon (02232, 2007) and Wrangell-Petersburg (02280,
    2008) census areas: each split into two new entities.
  - LaSalle Parish, LA (22059); LaSalle County, IL (17099); Doña Ana County,
    NM (35013): spelling corrections with NO FIPS code change -- a join on
    the "old" code already resolves, so there is nothing for this table to
    fix.

ponytail: only decade pages back to 1990 were checked (far enough to cover
every SCP-era recode named in #26); 1970/1980 are not read. Add a row --
citing the matching decade page -- if an older pure recode turns out to
matter to a landed source.

Verified against the real Gazetteer (2026-09-18, `cancerbasemap gazetteer
--year 2010` and `--year 2026`, ad hoc -- not a pytest test, since it hits
the network): every `old_geo_id` here that postdates the 2010 vintage
(Shannon/Oglala Lakota, Wade Hampton/Kusilvak, both 2015) is present in the
landed 2010 geography.unit and absent from 2026's, with `new_geo_id` the
reverse. Dade/Miami-Dade (1997) predates 2010, so its `new_geo_id` is
present in BOTH landed vintages and `old_geo_id` in neither -- the Gazetteer
has never carried the retired code, which is the correct outcome for a
recode that happened before Cancer Basemap's earliest landed vintage, not a
gap in this table.

A join that resolves an old code before it ever reaches geography.unit
(SPEC.md Acceptance B):

    SELECT coalesce(a.new_geo_id, o.geo_id) AS geo_id, o.value
    FROM measure.observation o
    LEFT JOIN geography.alias a ON a.old_geo_id = o.geo_id
    -- now join geo_id (not o.geo_id) to geography.unit; a row keyed to
    -- Shannon County's old code (county:46113) resolves to Oglala Lakota's
    -- current one (county:46102) instead of dropping.
"""

from pathlib import Path

import duckdb
from pyiceberg.expressions import AlwaysTrue, EqualTo

from . import merge

SOURCE = "CENSUS_COUNTY_CHANGES"
CHECKED = "2026-09-18"
DATA_FILE = Path(__file__).parent / "data" / "county_recodes.csv"

# The curated CSV's own header, in file order -- this module's contract, same
# as an upstream file's header would be for a landed source.
COLUMNS = ("old_fips", "old_name", "new_fips", "new_name", "effective_year",
           "change_type", "source_url", "note")
CHANGE_TYPES = ("recode", "rename", "recode_and_rename")


def land_raw(cat, release, path=None):
    """Phase 1: the curated CSV, verbatim and whole. Replaced wholesale each
    time (like raw.census__state_fips) -- there is no upstream edition axis
    to key an overwrite scope on, only our own re-curation.
    """
    path = Path(path) if path else DATA_FILE
    header = tuple(path.read_text(encoding="utf-8").splitlines()[0].split(","))
    if header != COLUMNS:
        raise SystemExit(f"geography_alias: {path} header is not the declared one; "
                         f"differs in {sorted(set(header) ^ set(COLUMNS))}")

    con = duckdb.connect()
    arrow = con.sql(f"""
        SELECT {", ".join(COLUMNS)}, '{release}' AS landed_in
        FROM read_csv('{path}', header=true, all_varchar=true, delim=',',
                      quote='"', escape='"', nullstr='')
    """).to_arrow_table()
    if not arrow.num_rows:
        raise SystemExit(f"geography_alias: {path} yielded no rows")

    n = merge.write(cat, "raw.geography__county_recodes", arrow, AlwaysTrue())
    merge.manifest(cat, release, "geography_alias", str(path), n,
                   version=CHECKED, method="retrieval_date")
    return n


def transform(cat, release):
    """Phase 2: one geography.alias row per curated recode."""
    con = duckdb.connect()
    con.register("raw", cat.load_table("raw.geography__county_recodes").scan().to_arrow())

    bad = con.sql(f"""
        SELECT DISTINCT change_type FROM raw
        WHERE change_type NOT IN ({", ".join(f"'{t}'" for t in CHANGE_TYPES)})
    """).fetchall()
    if bad:
        raise SystemExit(f"geography_alias: unknown change_type(s) {[b[0] for b in bad]}; "
                         f"expected one of {CHANGE_TYPES}")

    alias = con.sql(f"""
        SELECT 'county:' || lpad(old_fips, 5, '0') AS old_geo_id,
               'county:' || lpad(new_fips, 5, '0') AS new_geo_id,
               CAST(effective_year AS INTEGER) AS effective_year,
               change_type, old_name, new_name,
               '{SOURCE}' AS source, source_url, note
        FROM raw
    """).to_arrow_table()

    scope = EqualTo("source", SOURCE)
    return {"geography.alias": merge.merge(cat, "geography.alias", alias, release, scope)}


def ingest(cat, release, path=None):
    n = land_raw(cat, release, path)
    return {"raw.geography__county_recodes": n, **transform(cat, release)}
