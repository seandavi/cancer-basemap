"""USDA ERS Rural-Urban Commuting Area codes -> Iceberg, tract level.

Upstream: https://www.ers.usda.gov/data-products/rural-urban-commuting-area-codes
Sub-county rurality: primary and secondary RUCA codes at census-tract grain
(SPEC.md § Sources — first tranche: "rurality, food access"). Third writer in
the ERS family after RUCC (`ers_rucc.py`, #13) -- same publisher, same
licence basis, same Latin-1 caveat on the CSV edition.

**Licence.** Neither the product page, the documentation page nor the users'
guide (https://www.ers.usda.gov/data-products/rural-urban-commuting-area-codes,
its `/documentation` and `/users-guide` pages, all checked 2026-09-18) states
a licence -- same as RUCC. USDA ERS is a federal agency; the RUCA
documentation page's own byline credits federal staff ("Elizabeth A. Dobis
or Austin Sanders", division RRED). "Data and content created by government
employees within the scope of their employment are not subject to domestic
copyright protection under 17 U.S.C. Sec 105. Government works are by default
in the U.S. Public Domain." (https://resources.data.gov/open-licenses/,
checked 2026-09-18).

**Version axis is the edition.** ERS publishes tract-level RUCA for 1990,
2000, 2010 (revised 2019) and 2020 (verified 2026-09-18 by fetching the
product page and listing every `/media/*.{csv,xlsx,xls}` link on it). Only
1990 and 2000 have no CSV/XLSX form -- `.xls` only, unreadable with DuckDB's
`excel` extension (`.xlsx`-only) and no new dependency is allowed, mirroring
`ers_rucc.py`'s 2013 omission.

ponytail: 1990/2000 not landed -- legacy `.xls` only, same reasoning as
`ers_rucc.py`'s 2013 omission. Revisit if ERS ever republishes either as CSV
or XLSX.

ponytail: the ZIP-code RUCA approximation (also on this product page) is OUT
OF SCOPE. It is keyed by ZIP code, and issue #64 has not yet settled what a
ZIP-keyed measure means in this lake (crosswalk to ZCTA? land ZIP as its own
geography level?) -- landing it here would prejudge that. Only the census
-tract files are landed.

**The two landed editions are genuinely different upstream layouts**, not
a header that merely drifted -- house rule "one COLUMNS layout per real
upstream layout, detected by header match" (AGENTS.md) applies literally:

- **2010** (revised 3 Jul 2019, per the workbook's own errata note) is an
  `.xlsx` with a 9-column `Data` sheet: `COLUMNS_2010`, read via DuckDB's
  `excel` extension (`INSTALL excel; LOAD excel;`). Row 1 of that sheet is
  the errata note, not data -- the real header is row 2 (`range='A2:...'`,
  `stop_at_empty=true` so the read stops at the sheet's actual last row
  rather than padding to Excel's 1,048,576-row ceiling). Reading it typed
  (not `all_varchar`) and then formatting numeric cells to VARCHAR ourselves
  avoids a DuckDB `excel`-extension quirk: `all_varchar=true` converts an
  Excel float to text at full double precision (`10.199999999999999` for a
  cell displaying `10.2`); casting a typed DOUBLE straight to VARCHAR does
  not have that problem (verified against the real file, 2026-09-18).
- **2020** is a plain CSV, `COLUMNS_2020`, encoded Latin-1 like RUCC's CSV
  (verified 2026-09-18: "Ca\xf1on City, CO" in `PrimaryDestinationName`)
  despite the server's `Content-Type` claiming
  UTF-8 -- decoding the header line as Latin-1 is safe regardless, since the
  header itself is plain ASCII.

Both editions land into the one `raw.ers__ruca_tract` table, discriminated by
`ruca_edition`; each edition's own columns are NULL on the other edition's
rows (`schemas.py`'s "a column exists here only once something populates it"
already anticipates exactly this: both editions are landed by this same PR's
end-to-end run, so every declared column is in fact populated by some row).

**Geography vintage.** `GEO_VINTAGE` maps each edition to the census-tract
boundary year it classifies (2010 tracts for the 2010 edition, 2020 tracts
for the 2020 edition) -- verified directly against each downloaded file, not
inferred from the edition label alone:

- **2010 edition**: Connecticut carries its eight *legacy* counties
  (09001-09015, e.g. "09001,CT,Fairfield County") and Alaska carries the
  pre-2019 "02261,AK,Valdez-Cordova Census Area" rather than its current
  Chugach (02063) / Copper River (02066) split -- both markers of 2010-vintage
  Census geography, confirmed in the downloaded workbook.
- **2020 edition**: this file carries TWO tract-FIPS columns, `TractFIPS20`
  (built on each tract's 2020-vintage county code: Connecticut's eight legacy
  counties, Alaska's post-2019 areas) and `TractFIPS23` (the same tracts
  under the county-equivalent codes ERS uses as of 2023 -- Connecticut's nine
  planning regions, 09110-09190). Both are genuinely present in the real file
  (verified 2026-09-18): e.g. tract 09001010101 (Fairfield County, legacy)
  appears as `TractFIPS20`, the same physical tract appearing as
  `TractFIPS23 = 09190010101` (Western Connecticut Planning Region); four
  zero-population Connecticut water tracts have `TractFIPS23 = 'N/A'`
  (no defined 2023 county assignment) while `TractFIPS20` is always
  populated. `geo_id` is derived from **`TractFIPS20`**, not `TractFIPS23`:
  it is always present, and it is what lines up with the 2020-vintage
  geography this Cancer Basemap release already carries elsewhere
  (`census_gazetteer.py`'s vintage-2020 landing also uses Connecticut's
  legacy counties, "present through the 2020 files" per its own docstring)
  -- consistent by verification, not forced to match (AGENTS.md: "Do not
  force it to a landed Gazetteer vintage"). `TractFIPS23` and its
  `CountyFIPS23`/`CountyCode23`/`CountyName23` siblings still land in raw,
  verbatim, for whoever needs to join this file to a 2023-planning-region
  -keyed product (e.g. `ers_rucc.py`'s 2023 edition) later.

**Suppression.** Both editions use code `99` on both PrimaryRUCA and
SecondaryRUCA for the same thing: a zero-population tract with no
rural-urban identifier (`UrbanCoreType = 'Water'` on every `99` row checked)
-- `value_status = 'not_applicable'`, `value` NULL, never landed as the
number 99. No other sentinel (blank, `-999`, `*`) appears in either edition's
RUCA columns (checked directly, both files).

ponytail: `Population`/`LandArea`/`PopDensity` (2020) and the `_2010`
equivalents land in raw (they are part of the file) but are not derived into
`measure.observation` -- population denominators come from SEER/ACS
elsewhere in the lake, matching `ers_rucc.py`'s identical choice.
"""

import tempfile
import urllib.request
from pathlib import Path

import duckdb
from pyiceberg.expressions import And, EqualTo

from . import merge

# media IDs found by listing every /media/*.{csv,xlsx,xls} link on
# https://www.ers.usda.gov/data-products/rural-urban-commuting-area-codes,
# checked 2026-09-18. 1990/2000 omitted (see module docstring).
EDITIONS = {
    "2010": "https://www.ers.usda.gov/media/5438/2010-rural-urban-commuting-area-codes-revised-732019.xlsx",
    "2020": "https://www.ers.usda.gov/media/5443/2020-rural-urban-commuting-area-codes-census-tracts.csv",
}
DEFAULT_EDITION = "2020"
USER_AGENT = "cancerbasemap/1.0 (+https://github.com/seandavi/cancer-basemap)"

# Census-tract boundary vintage each edition classifies -- see module
# docstring "Geography vintage" for the evidence.
GEO_VINTAGE = {"2010": 2010, "2020": 2020}

# The 2010 workbook's `Data` sheet header (row 2; row 1 is an errata note),
# in file order, verified 2026-09-18.
COLUMNS_2010 = (
    "State-County FIPS Code", "Select State", "Select County",
    "State-County-Tract FIPS Code (lookup by address at http://www.ffiec.gov/Geocode/)",
    "Primary RUCA Code 2010", "Secondary RUCA Code, 2010 (see errata)",
    "Tract Population, 2010", "Land Area (square miles), 2010",
    "Population Density (per square mile), 2010",
)
# 2010-edition column names in the shared raw table, same order as COLUMNS_2010.
_2010_FIELDS = (
    "fips_2010", "state_2010", "county_name_2010", "tract_fips_2010",
    "primary_ruca_2010", "secondary_ruca_2010", "population_2010",
    "land_area_2010", "pop_density_2010",
)

# The 2020 CSV's header, in file order, verified 2026-09-18.
COLUMNS_2020 = (
    "TractFIPS23", "CountyFIPS23", "CountyCode23", "CountyName23",
    "TractFIPS20", "TractCode20", "TractName20", "CountyFIPS20", "CountyCode20",
    "CountyName20", "StateFIPS20", "StateName20", "UrbanAreaCode20",
    "UrbanAreaName20", "UrbanCore", "UrbanCoreType", "PrimaryRUCA",
    "PrimaryRUCADescription", "PrimaryDestinationCode", "PrimaryDestinationName",
    "SecondaryRUCA", "SecondaryRUCADescription", "SecondaryDestinationCode",
    "SecondaryDestinationName", "Population", "LandArea", "PopDensity",
)

# Verbatim from ERS's own files (2010 workbook's "RUCA code description"
# sheet; corroborated by the 2020 CSV's Primary/SecondaryRUCADescription
# columns, which use terser wording for the same scheme), checked 2026-09-18.
# No apostrophes/single quotes in either doc: both are spliced into a SQL
# string literal in transform() below.
PRIMARY_DOC = (
    "USDA ERS RUCA primary code (stable across the 2010 and 2020 editions). "
    "Metropolitan area codes: 1 = core, primary flow within an urbanized area (UA); "
    "2 = high commuting, primary flow 30% or more to a UA; 3 = low commuting, primary "
    "flow 10% to 30% to a UA. Micropolitan area codes (Urban Cluster of 10,000-49,999): "
    "4 = core, primary flow within the UC; 5 = high commuting, 30% or more to a large UC; "
    "6 = low commuting, 10% to 30% to a large UC. Small town codes (Urban Cluster of "
    "2,500-9,999): 7 = core, primary flow within the UC; 8 = high commuting, 30% or more "
    "to a small UC; 9 = low commuting, 10% to 30% to a small UC. 10 = rural area, primary "
    "flow to a tract outside any UA or UC. 99 = not coded: census tract has zero "
    "population and no rural-urban identifier information -- lands as value_status "
    "\"not_applicable\", never as the number 99."
)
SECONDARY_DOC = (
    "USDA ERS RUCA secondary code (same source and vintage as the RUCA:primary doc). The "
    "whole-number codes (1-10) mean \"no additional code\" -- the same category as the "
    "matching primary code, with no secondary commuting flow. A decimal suffix means a "
    "secondary flow of 30% to 50% to a larger place in the hierarchy: x.1 to a (larger) "
    "urbanized area, x.2 to a large Urban Cluster, x.3 to a small Urban Cluster -- e.g. "
    "7.2 = small town core with a secondary flow to a large UC. Only 1.1, 2.1, 4.1, 5.1, "
    "7.1, 7.2, 8.1, 8.2, 10.1, 10.2 and 10.3 occur (checked against both landed editions); "
    "no other primary code has a defined secondary sub-flow. 99 = not coded, same "
    "zero-population tracts as the primary code -- value_status \"not_applicable\", never "
    "the number 99."
)


def _fetch(url):
    """The file's bytes. A local path (tests) is read directly; a remote URL
    goes through urllib with a descriptive User-Agent, same as ers_rucc.py."""
    if not url.startswith("http"):
        return Path(url).read_bytes()
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req) as r:
        return r.read()


def _trim(col):
    """SQL for a typed DOUBLE column -> clean VARCHAR, whole numbers without a
    trailing '.0' (see module docstring: avoids the excel extension's
    all_varchar float-precision quirk without reintroducing it by hand)."""
    return (f'CASE WHEN "{col}" = trunc("{col}") '
            f'THEN CAST(CAST("{col}" AS BIGINT) AS VARCHAR) '
            f'ELSE CAST("{col}" AS VARCHAR) END')


def _land_2010(raw_bytes, url, release):
    with tempfile.NamedTemporaryFile(suffix=".xlsx") as tmp:
        tmp.write(raw_bytes)
        tmp.flush()
        con = duckdb.connect()
        con.sql("INSTALL excel; LOAD excel;")
        # Row 1 of the 'Data' sheet is an errata note, not the header (see
        # module docstring); stop_at_empty avoids padding to Excel's row ceiling.
        con.sql(f"""
            CREATE VIEW v AS SELECT * FROM read_xlsx('{tmp.name}', sheet='Data',
                header=true, range='A2:I1048576', stop_at_empty=true)
        """)
        header = tuple(con.sql("SELECT * FROM v LIMIT 0").columns)
        if header != COLUMNS_2010:
            raise SystemExit(f"ers_ruca: {url} (2010 edition) header is not the "
                             f"declared one; differs in {sorted(set(header) ^ set(COLUMNS_2010))}")
        c = COLUMNS_2010
        null_2020 = ", ".join(f"NULL::VARCHAR AS {name}" for name in COLUMNS_2020)
        return con.sql(f"""
            SELECT '2010' AS ruca_edition, '{release}' AS landed_in,
                   "{c[0]}" AS fips_2010, "{c[1]}" AS state_2010,
                   "{c[2]}" AS county_name_2010, "{c[3]}" AS tract_fips_2010,
                   {_trim(c[4])} AS primary_ruca_2010,
                   {_trim(c[5])} AS secondary_ruca_2010,
                   {_trim(c[6])} AS population_2010,
                   {_trim(c[7])} AS land_area_2010,
                   {_trim(c[8])} AS pop_density_2010,
                   {null_2020}
            FROM v
        """).to_arrow_table()


def _land_2020(raw_bytes, url, release):
    # Latin-1, not UTF-8 (see module docstring); the header line is pure
    # ASCII, so decoding it as Latin-1 to validate is safe either way.
    header = tuple(raw_bytes.splitlines()[0].decode("latin-1").split(","))
    if header != COLUMNS_2020:
        raise SystemExit(f"ers_ruca: {url} (2020 edition) header is not the "
                         f"declared one; differs in {sorted(set(header) ^ set(COLUMNS_2020))}")
    with tempfile.NamedTemporaryFile(suffix=".csv") as tmp:
        tmp.write(raw_bytes)
        tmp.flush()
        con = duckdb.connect()
        select_2020 = ", ".join(f'"{col}"' for col in COLUMNS_2020)
        null_2010 = ", ".join(f"NULL::VARCHAR AS {name}" for name in _2010_FIELDS)
        return con.sql(f"""
            SELECT '2020' AS ruca_edition, '{release}' AS landed_in,
                   {null_2010},
                   {select_2020}
            FROM read_csv('{tmp.name}', header=true, all_varchar=true, delim=',',
                          quote='"', escape='"', nullstr='', encoding='latin-1')
        """).to_arrow_table()


def land_raw(cat, release, edition=None, url=None):
    """Phase 1: one edition, verbatim and whole, replaced per edition."""
    edition = edition or DEFAULT_EDITION
    if edition not in EDITIONS:
        raise SystemExit(f"ers_ruca: unknown edition {edition!r}; known editions: "
                         f"{sorted(EDITIONS)}")
    fetch_url = url or EDITIONS[edition]
    raw_bytes = _fetch(fetch_url)
    arrow = (_land_2010 if edition == "2010" else _land_2020)(raw_bytes, fetch_url, release)
    if not arrow.num_rows:
        raise SystemExit(f"ers_ruca: {fetch_url} yielded no rows")

    n = merge.write(cat, "raw.ers__ruca_tract", arrow, EqualTo("ruca_edition", edition))
    merge.manifest(cat, release, "ers_ruca", fetch_url, n, version=edition, method="release_number")
    return edition, n


def transform(cat, release, edition):
    """Phase 2: primary and secondary RUCA observations, one row per tract per
    measure, plus their measure definitions and shared (not-applicable) stratum.

    Scoped to `edition`'s rows: raw accumulates every landed edition, so an
    unscoped read would derive from all of them at once.
    """
    geo_vintage = GEO_VINTAGE[edition]
    tract_col, primary_col, secondary_col = (
        ("tract_fips_2010", "primary_ruca_2010", "secondary_ruca_2010") if edition == "2010"
        else ("TractFIPS20", "PrimaryRUCA", "SecondaryRUCA"))

    con = duckdb.connect()
    con.register("raw", cat.load_table("raw.ers__ruca_tract").scan(
        row_filter=EqualTo("ruca_edition", edition)).to_arrow())

    definition = con.sql(f"""
        SELECT 'RUCA:primary' AS measure_id, 'RUCA' AS source,
               'RUCA primary code' AS label, 'code 1-10 or 99' AS units,
               NULL::VARCHAR AS universe, 'index' AS rate_basis,
               NULL::VARCHAR AS age_adjustment, 'derived' AS method,
               NULL::VARCHAR AS cancer_site_code, '{PRIMARY_DOC}' AS doc
        UNION ALL
        SELECT 'RUCA:secondary', 'RUCA', 'RUCA secondary code',
               'code 1-10, 99, or a decimal sub-flag (e.g. 7.2)',
               NULL, 'index', NULL, 'derived', NULL, '{SECONDARY_DOC}'
    """).to_arrow_table()

    stratum = con.sql("""
        SELECT 'RUCA:none' AS stratum_id, 'RUCA' AS source,
               NULL::VARCHAR AS sex, NULL::VARCHAR AS age_group,
               NULL::VARCHAR AS race_ethnicity, NULL::VARCHAR AS stage,
               NULL::VARCHAR AS other, 'RUCA_NONE' AS scheme
    """).to_arrow_table()

    # One row per (tract, RUCA:primary/secondary) -- code 99 is the source's
    # own "not coded" sentinel (zero-population, water tracts): value_status
    # = 'not_applicable', value stays NULL, never landed as the number 99.
    # value_status follows the same TRY_CAST that produces `value`, not just
    # the '99' check, so a present-but-non-numeric cell (never seen in either
    # real file, verified 2026-09-18, but not something to assume forever)
    # can't land as a numberless 'reported' row (merge.check_observations).
    observation = con.sql(f"""
        SELECT 'RUCA' AS source, '{edition}' AS source_release, 'RUCA:primary' AS measure_id,
               'tract:' || lpad("{tract_col}", 11, '0') AS geo_id, {geo_vintage} AS geo_vintage,
               '{edition}' AS period_start, '{edition}' AS period_end,
               'RUCA:none' AS stratum_id,
               CASE WHEN "{primary_col}" = '99' THEN NULL ELSE TRY_CAST("{primary_col}" AS DOUBLE) END AS value,
               NULL::DOUBLE AS lower, NULL::DOUBLE AS upper, NULL::DOUBLE AS interval_level,
               NULL::DOUBLE AS numerator, NULL::DOUBLE AS denominator,
               CASE WHEN "{primary_col}" = '99' THEN 'not_applicable'
                    WHEN TRY_CAST("{primary_col}" AS DOUBLE) IS NOT NULL THEN 'reported'
                    ELSE 'not_available' END AS value_status,
               NULL::VARCHAR AS reliability_flag, NULL::VARCHAR AS trend
        FROM raw
        UNION ALL
        SELECT 'RUCA', '{edition}', 'RUCA:secondary',
               'tract:' || lpad("{tract_col}", 11, '0'), {geo_vintage},
               '{edition}', '{edition}', 'RUCA:none',
               CASE WHEN "{secondary_col}" = '99' THEN NULL ELSE TRY_CAST("{secondary_col}" AS DOUBLE) END,
               NULL, NULL, NULL, NULL, NULL,
               CASE WHEN "{secondary_col}" = '99' THEN 'not_applicable'
                    WHEN TRY_CAST("{secondary_col}" AS DOUBLE) IS NOT NULL THEN 'reported'
                    ELSE 'not_available' END,
               NULL, NULL
        FROM raw
    """).to_arrow_table()
    merge.check_observations(observation)

    scope = EqualTo("source", "RUCA")
    return {
        "measure.definition": merge.write(cat, "measure.definition", definition, scope),
        "measure.stratum": merge.write(cat, "measure.stratum", stratum, scope),
        "measure.observation": merge.merge(
            cat, "measure.observation", observation, release,
            And(scope, EqualTo("source_release", edition))),
    }


def ingest(cat, release, edition=None, url=None):
    edition, n = land_raw(cat, release, edition, url)
    return {"raw.ers__ruca_tract": n, **transform(cat, release, edition)}
