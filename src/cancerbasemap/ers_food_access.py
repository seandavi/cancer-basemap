"""USDA ERS Food Access Research Atlas -> Iceberg, in the same two phases as
the other sources.

Upstream: https://www.ers.usda.gov/data-products/food-access-research-atlas/
download-the-data -- census-tract low-income/low-access ("food desert") flags
and the population counts behind them (SPEC.md § Sources -- first tranche).
As of the site's 2026-07-27 update, ERS has renamed the 2019 product "Large
Retailer Access Map (LRAM) (formerly known as the Food Access Research Atlas
(FARA))" and added a 2025 "SNAP-authorized Retailer Access Map (SRAM)" on
2020 tracts; both still link the original 2019/2015/2010/2006 FARA files
under "Archived Versions" (checked 2026-09-18). This module lands 2019,
2015 and the 2025 SRAM (issue #112, see below); 2010 and the archived 2006
file stay out (ponytail note below). `source` stays 'FARA' downstream since
that is the name issue #42 and every fixture/measure_id here use.

**Licence.** USDA ERS is a federal agency; its work product is a U.S.
Government work. Per resources.data.gov/open-licenses/ (the definition
data.gov uses for every federal agency's "Public Domain" listing, already
the basis for ers_rucc.py's licence in this repo): "Data and content created
by government employees within the scope of their employment are not
subject to domestic copyright protection under 17 U.S.C. Sec 105. Government
works are by default in the U.S. Public Domain." (checked 2026-09-18). No
registration or attribution is required to redistribute.

**Version axis is the edition.** Verified by downloading each file
(2026-09-18) from the Download-the-Data page's real links:
  - 2019: https://www.ers.usda.gov/media/5627/2019-large-retailer-access-map-
    lram-formerly-known-as-the-food-access-research-atlas-fara-data.zip --
    a zip of a 147-column, comma-delimited, UTF-8 CSV (`Food Access Research
    Atlas.csv`) plus a ReadMe and a VariableLookup sheet, 72,531 data rows.
  - 2015: https://www.ers.usda.gov/media/5623/2015-food-access-research-
    atlas-fara-data-and-documentation.zip -- a zip of a 147-column .xlsx
    (`FoodAccessResearchAtlasData2015.xlsx`, sheet "Food Access Research
    Atlas") plus its PDF documentation, 72,864 data rows. Read with DuckDB's
    `excel` extension (`INSTALL excel; LOAD excel;`) via `read_xlsx` --
    `.xls`-only sources (2006, below) stay out rather than adding a
    dependency, same call as ers_rucc.py's 2013 omission.

Both editions publish the exact same 147 columns in the exact same order --
verified by diffing the two real headers column-for-column -- differing only
in the case of one column: 2019 spells it `Pop2010`, 2015 spells it
`POP2010`. `COLUMNS` below carries the two real (verified) headers keyed by
edition; the landed `raw.ers__food_access` table uses 2019's spelling as the
canonical column name for that field, so `PROVENANCE` needs no separate
union-schema handling the way census_gazetteer.py's three real layouts do.

ponytail: **2010 and the archived 2006 "Food Desert Locator" are not
landed.** 2010 (https://www.ers.usda.gov/media/5624/... .zip, verified
2026-09-18) is a real *third* layout -- 65 columns in a different order, no
race/ethnicity breakdown, no PovertyRate/MedianFamilyIncome, plus `Rural`
and `UATYP10` columns the later editions drop -- tractable in principle but
a third COLUMNS layout is more than this module needs for #42's ask (2019
"and 2015 if its layout is tractable", which it is). 2006
(https://www.ers.usda.gov/media/5625/archived-2006-food-desert-locator.zip)
ships only as a legacy `.xls`, unreadable by DuckDB's `excel` extension
(`.xlsx`-only), same constraint as ers_rucc.py's 2013. Revisit either if a
later milestone needs pre-2015 food-access history.

**Geography vintage: 2010 census tracts for 2019 and 2015 (2025 SRAM moves to
2020 tracts -- see below).** ERS's own Documentation page states the 2019
(LRAM) estimates are "based on ... the 2010 Decennial Census" and the 2015
estimates likewise "based on ... the 2010 Decennial Census" -- checked against
https://www.ers.usda.gov/data-products/food-access-
research-atlas/documentation, 2026-09-18. The downloaded files confirm it
directly: Connecticut's tracts in both editions keep the legacy county-based
11-digit FIPS prefix 09001-09015 (e.g. tract 09001010101, Fairfield County),
not the 2022 planning-region prefixes (09110-09190) that show up in
county-level sources landed elsewhere in this repo from their 2022+ releases
(ers_rucc.py, places.py) -- 2010-vintage Census *tract* geography is
unaffected by that later *county-level* administrative reorganization.

**Missing-value sentinel differs by edition -- enumerated, not guessed.**
2019's CSV uses the literal text `NULL` for every missing count/share cell
(e.g. 71,025 of 72,531 rows for `lapop20`); there are zero genuinely blank
cells anywhere in the file (checked with DuckDB's `nullstr=''`, i.e. an
empty field would already read as SQL NULL and none do). 2015's xlsx has no
missing-value sentinel at all for any column this module derives -- every
cell holds a real number, 0 where a distance threshold has no low-access
population, confirmed by reading the raw sheet XML directly (e.g. `lapop20`
cells are literal `<v>0</v>`, not blank). `_check_sentinels` fails loudly on
any non-numeric, non-'NULL' text in a derived column, rather than silently
mis-parsing a third convention this module hasn't seen.

**Share columns are on different scales per edition -- a real landmine.**
Recomputing from the published counts: 2015's `...share` columns are 0-1
fractions (tract 01001020100's `lapop1share` = 0.70998, and
`lapop1` / `Pop2010` = 1357.48 / 1912 = 0.70998 exactly); 2019's are 0-100
percentages (the same tract's `lapop1` / `Pop2010` * 100 = 1896 / 1912 * 100
= 99.16, rounding to the published 99.19 -- the small residual is the
published integer counts themselves being rounded from the same underlying
floats 2015 keeps unrounded). `SHARE_SCALE` normalizes both onto the 0-100
percent scale for `measure.observation.value` (`rate_basis='percent'`) so
the two editions are comparable there; `raw.ers__food_access` keeps each
edition's own published scale verbatim, unmodified (SPEC.md: raw lands
whole).

ponytail: only 10 of the 147 columns are derived into `measure.observation`
-- the 4 LILA flags plus the half-mile and 1-mile population / low-income /
no-vehicle share triples, the distance thresholds a catchment access-gap
recipe (SPEC.md § Recipes #3) actually reaches for. The 10-mile and 20-mile
thresholds, every race/ethnicity breakdown (`la*1`, `la*10`, `la*20`, `la*half`
per race), SNAP, poverty rate, median family income, and the group-quarters
columns all land in `raw.ers__food_access` and stay queryable there via SQL;
add a `measure.definition` row alongside these if a later recipe needs one.

**2025 edition: the SNAP-authorized Retailer Access Map (SRAM) (issue
#112).** CIF's food-desert layer cites "USDA ERS, 2025" on 2020 census
tracts; #112 asked whether ERS had published a post-2019 FARA edition #87
missed. It has. The Download-the-Data page
(https://www.ers.usda.gov/data-products/food-access-research-atlas/
download-the-data, checked 2026-09-19) lists the 2019 file under "Current
Versions" alongside a new "2025 SNAP-authorized Retailer Access Map (SRAM)
Data", last updated 7/27/2026; its own ReadMe recommends the citation "U.S.
Department of Agriculture, Economic Research Service. Food Access Research
Atlas, SNAP-authorized Retailer Access Map" -- the same product family CIF
is citing. The Documentation page states: "Estimates in the Large Retailer
Access Map (LRAM) for 2019 are based on ... the 2010 Decennial Census ...";
"Estimates in the ... SNAP-authorized Retailer Access Map (SRAM) for 2025
are based on ... the 2020 Decennial Census; the LandScan USA 2020 nighttime
dataset; and the 2020-24 American Community Survey (ACS)" (both checked
2026-09-19). Verified directly against the downloaded file too: 84,119 rows
(vs. 72,531 for 2019), and CensusTract20 11060xxxxxxx-style values that only
exist in `geography.unit`'s 2020 vintage -- resolving #112's open question:
CIF's 2020-tract food-desert layer is this SRAM release, not a crosswalk of
2019 data (that would have been #25's territory; it is not needed here).

SRAM is not a header change to the same 147-column layout -- it is a
genuinely different upstream product, same house rule as `ers_ruca.py`'s
2010-vs-2020 layouts: **SRAM measures access to any SNAP-authorized
retailer** ("all store types (e.g., smaller grocery stores, specialty food
stores, convenience stores, neighborhood markets, dollar stores)," per the
Documentation page), not the 2019 LRAM's supermarkets/supercenters/large
grocery stores only, and it ships as three separate CSVs inside one zip
(https://www.ers.usda.gov/media/29395/2025-snap-authorized-retailer-access-
map-sram-data.zip, verified 2026-09-19) rather than one: "SRAM General Tract
Characteristics Data.csv" (27 columns, `GENERAL_COLUMNS_2025`), "SRAM
Straight Line Distance Data.csv" (135 columns incl. 4 join keys,
`SD_COLUMNS_2025`) and "SRAM Driving Distance Data.csv". This module lands
the first two, joined on `CensusTract20`, into their own table --
`raw.ers__food_access_sram`, USDA's own column names verbatim, no aliasing
onto the 147-column layout's names (their meaning genuinely differs: 2020
Census/2020-24 ACS inputs, 2020 tracts, SNAP retailers, not 2010/2019
supermarkets). `transform` maps the FARA:* measure ids this module already
derives onto SRAM's SD_SRAM_-prefixed straight-line-distance columns and
POP2020/OHU2020 denominators, so the same measure_id is comparable across
all three editions via `source_release`.

ponytail: **the Driving (Network-Based) Distance file is not landed.** It is
a wholly new distance methodology (road-network travel time) with no analog
in any earlier edition and nothing in this module's existing derivation
reaches for it -- same reasoning as the 2010/2006 omissions above. Revisit
if a later recipe wants network-distance food access.

ponytail: **`County24` (the SRAM general file's 2024-vintage county name) is
not landed.** Nothing here needs a second county name alongside `County20`;
add it if a later join wants 2024 county boundaries specifically.

**Missing-value sentinel, third convention.** SRAM's own Read Me: "Cells are
intentionally left blank when data are unavailable or not applicable" --
neither 2019's literal `'NULL'` text nor 2015's always-populated cells.
Verified directly: e.g. tract 01015981903 (a zero-population Calhoun County,
AL tract) has `SD_SRAM_lapop1 = '0'` but a genuinely blank
`SD_SRAM_lapop1share`. `nullstr=''` on the CSV read turns a blank cell into
SQL NULL directly, so `_check_sentinels`/`TRY_CAST`'s existing "anything
that isn't a number is a hard stop unless it's the enumerated sentinel"
logic already covers this convention with no code change -- a real NULL
never reaches the "unmapped non-numeric" check at all.

**Encoding.** Both SRAM files have the same stray-Latin-1-byte issue as
`census_gazetteer.py`'s 2010 county file and `ers_ruca.py`'s 2020 CSV: "Do\xf1a
Ana County" (tract 35013001103) is not valid UTF-8. `_ensure_utf8` recovers
it the same way -- decode the whole file as Latin-1 on a UTF-8 failure, safe
because the rest of each file is plain ASCII.

**Share scale.** SRAM's share columns are already 0-100 percentages, like
2019's (recomputed: tract 01001020100's `SD_SRAM_lapop1` / `POP2020` * 100 =
1080 / 1775 * 100 = 60.85, matching the published `SD_SRAM_lapop1share`
exactly) -- `SHARE_SCALE["2025"] = 1`, no rescaling.
"""

import tempfile
import urllib.request
import zipfile
from pathlib import Path

import duckdb
import pyarrow as pa
from pyiceberg.expressions import And, EqualTo

from . import merge

USER_AGENT = "cancerbasemap/1.0 (+https://github.com/seandavi/cancer-basemap)"
# Census-tract boundary vintage each edition classifies (module docstring).
GEO_VINTAGE = {"2019": 2010, "2015": 2010, "2025": 2020}

EDITIONS = {
    "2019": dict(
        url="https://www.ers.usda.gov/media/5627/2019-large-retailer-access-map-lram-"
            "formerly-known-as-the-food-access-research-atlas-fara-data.zip",
        suffix=".csv",
    ),
    "2015": dict(
        url="https://www.ers.usda.gov/media/5623/2015-food-access-research-atlas-fara-"
            "data-and-documentation.zip",
        suffix=".xlsx",
        sheet="Food Access Research Atlas",
    ),
    "2025": dict(
        url="https://www.ers.usda.gov/media/29395/2025-snap-authorized-retailer-access-"
            "map-sram-data.zip",
    ),
}
# The two SRAM member files this module lands, by exact name (module
# docstring -- the Driving Distance member is excluded).
SRAM_MEMBERS = {
    "general": "SRAM General Tract Characteristics Data.csv",
    "sd": "SRAM Straight Line Distance Data.csv",
}

# 2019's header, in file order -- also the canonical column-name spelling for
# raw.ers__food_access (see module docstring: the two editions publish the
# same 147 columns in the same order, differing only in Pop2010's case).
COLUMNS_2019 = (
    'CensusTract', 'State', 'County', 'Urban', 'Pop2010',
    'OHU2010', 'GroupQuartersFlag', 'NUMGQTRS', 'PCTGQTRS', 'LILATracts_1And10',
    'LILATracts_halfAnd10', 'LILATracts_1And20', 'LILATracts_Vehicle', 'HUNVFlag', 'LowIncomeTracts',
    'PovertyRate', 'MedianFamilyIncome', 'LA1and10', 'LAhalfand10', 'LA1and20',
    'LATracts_half', 'LATracts1', 'LATracts10', 'LATracts20', 'LATractsVehicle_20',
    'LAPOP1_10', 'LAPOP05_10', 'LAPOP1_20', 'LALOWI1_10', 'LALOWI05_10',
    'LALOWI1_20', 'lapophalf', 'lapophalfshare', 'lalowihalf', 'lalowihalfshare',
    'lakidshalf', 'lakidshalfshare', 'laseniorshalf', 'laseniorshalfshare', 'lawhitehalf',
    'lawhitehalfshare', 'lablackhalf', 'lablackhalfshare', 'laasianhalf', 'laasianhalfshare',
    'lanhopihalf', 'lanhopihalfshare', 'laaianhalf', 'laaianhalfshare', 'laomultirhalf',
    'laomultirhalfshare', 'lahisphalf', 'lahisphalfshare', 'lahunvhalf', 'lahunvhalfshare',
    'lasnaphalf', 'lasnaphalfshare', 'lapop1', 'lapop1share', 'lalowi1',
    'lalowi1share', 'lakids1', 'lakids1share', 'laseniors1', 'laseniors1share',
    'lawhite1', 'lawhite1share', 'lablack1', 'lablack1share', 'laasian1',
    'laasian1share', 'lanhopi1', 'lanhopi1share', 'laaian1', 'laaian1share',
    'laomultir1', 'laomultir1share', 'lahisp1', 'lahisp1share', 'lahunv1',
    'lahunv1share', 'lasnap1', 'lasnap1share', 'lapop10', 'lapop10share',
    'lalowi10', 'lalowi10share', 'lakids10', 'lakids10share', 'laseniors10',
    'laseniors10share', 'lawhite10', 'lawhite10share', 'lablack10', 'lablack10share',
    'laasian10', 'laasian10share', 'lanhopi10', 'lanhopi10share', 'laaian10',
    'laaian10share', 'laomultir10', 'laomultir10share', 'lahisp10', 'lahisp10share',
    'lahunv10', 'lahunv10share', 'lasnap10', 'lasnap10share', 'lapop20',
    'lapop20share', 'lalowi20', 'lalowi20share', 'lakids20', 'lakids20share',
    'laseniors20', 'laseniors20share', 'lawhite20', 'lawhite20share', 'lablack20',
    'lablack20share', 'laasian20', 'laasian20share', 'lanhopi20', 'lanhopi20share',
    'laaian20', 'laaian20share', 'laomultir20', 'laomultir20share', 'lahisp20',
    'lahisp20share', 'lahunv20', 'lahunv20share', 'lasnap20', 'lasnap20share',
    'TractLOWI', 'TractKids', 'TractSeniors', 'TractWhite', 'TractBlack',
    'TractAsian', 'TractNHOPI', 'TractAIAN', 'TractOMultir', 'TractHispanic',
    'TractHUNV', 'TractSNAP',
)
# 2015's only difference from 2019 is POP2010's case (see module docstring).
COLUMNS = {
    "2019": COLUMNS_2019,
    "2015": tuple("POP2010" if c == "Pop2010" else c for c in COLUMNS_2019),
}

# The 2025 SRAM edition's two landed files' real headers, in file order,
# verified 2026-09-19 (module docstring). Landed into their own table
# (raw.ers__food_access_sram) rather than COLUMNS/COLUMNS_2019 -- SRAM is a
# different real layout, not a header drift on the same one.
GENERAL_COLUMNS_2025 = (
    'CensusTract20', 'State', 'County20', 'County24', 'Urban', 'POP2020', 'OHU2020',
    'GroupQuartersFlag', 'NUMGQTRS', 'PCTGQTRS', 'LowIncomeTracts', 'PovertyRate',
    'MedianFamilyIncome', 'TractLOWI', 'TractKids', 'TractSeniors', 'TractWhite',
    'TractBlack', 'TractAsian', 'TractNHOPI', 'TractAIAN', 'TractOMultir', 'TractHispanic',
    'TractHUNV', 'TractSNAP', 'TractVeteran', 'TractTribalArea',
)

SD_COLUMNS_2025 = (
    'CensusTract20', 'State', 'County20', 'County24', 'SD_SRAM_LILATracts_1And10',
    'SD_SRAM_LILATracts_halfAnd10', 'SD_SRAM_LILATracts_1And20',
    'SD_SRAM_LILATracts_Vehicle', 'SD_SRAM_HUNVFlag', 'SD_SRAM_LA1and10',
    'SD_SRAM_LAhalfand10', 'SD_SRAM_LA1and20', 'SD_SRAM_LATracts_half',
    'SD_SRAM_LATracts1', 'SD_SRAM_LATracts10', 'SD_SRAM_LATracts20',
    'SD_SRAM_LATractsVehicle_20', 'SD_SRAM_LAPOP1_10', 'SD_SRAM_LAPOP05_10',
    'SD_SRAM_LAPOP1_20', 'SD_SRAM_LALOWI1_10', 'SD_SRAM_LALOWI05_10', 'SD_SRAM_LALOWI1_20',
    'SD_SRAM_lapophalf', 'SD_SRAM_lapophalfshare', 'SD_SRAM_lalowihalf',
    'SD_SRAM_lalowihalfshare', 'SD_SRAM_lakidshalf', 'SD_SRAM_lakidshalfshare',
    'SD_SRAM_laseniorshalf', 'SD_SRAM_laseniorshalfshare', 'SD_SRAM_lawhitehalf',
    'SD_SRAM_lawhitehalfshare', 'SD_SRAM_lablackhalf', 'SD_SRAM_lablackhalfshare',
    'SD_SRAM_laasianhalf', 'SD_SRAM_laasianhalfshare', 'SD_SRAM_lanhopihalf',
    'SD_SRAM_lanhopihalfshare', 'SD_SRAM_laaianhalf', 'SD_SRAM_laaianhalfshare',
    'SD_SRAM_laomultirhalf', 'SD_SRAM_laomultirhalfshare', 'SD_SRAM_lahisphalf',
    'SD_SRAM_lahisphalfshare', 'SD_SRAM_lahunvhalf', 'SD_SRAM_lahunvhalfshare',
    'SD_SRAM_lasnaphalf', 'SD_SRAM_lasnaphalfshare', 'SD_SRAM_laveteranhalf',
    'SD_SRAM_laveteranhalfshare', 'SD_SRAM_lapop1', 'SD_SRAM_lapop1share',
    'SD_SRAM_lalowi1', 'SD_SRAM_lalowi1share', 'SD_SRAM_lakids1', 'SD_SRAM_lakids1share',
    'SD_SRAM_laseniors1', 'SD_SRAM_laseniors1share', 'SD_SRAM_lawhite1',
    'SD_SRAM_lawhite1share', 'SD_SRAM_lablack1', 'SD_SRAM_lablack1share',
    'SD_SRAM_laasian1', 'SD_SRAM_laasian1share', 'SD_SRAM_lanhopi1',
    'SD_SRAM_lanhopi1share', 'SD_SRAM_laaian1', 'SD_SRAM_laaian1share',
    'SD_SRAM_laomultir1', 'SD_SRAM_laomultir1share', 'SD_SRAM_lahisp1',
    'SD_SRAM_lahisp1share', 'SD_SRAM_lahunv1', 'SD_SRAM_lahunv1share', 'SD_SRAM_lasnap1',
    'SD_SRAM_lasnap1share', 'SD_SRAM_laveteran1', 'SD_SRAM_laveteran1share',
    'SD_SRAM_lapop10', 'SD_SRAM_lapop10share', 'SD_SRAM_lalowi10', 'SD_SRAM_lalowi10share',
    'SD_SRAM_lakids10', 'SD_SRAM_lakids10share', 'SD_SRAM_laseniors10',
    'SD_SRAM_laseniors10share', 'SD_SRAM_lawhite10', 'SD_SRAM_lawhite10share',
    'SD_SRAM_lablack10', 'SD_SRAM_lablack10share', 'SD_SRAM_laasian10',
    'SD_SRAM_laasian10share', 'SD_SRAM_lanhopi10', 'SD_SRAM_lanhopi10share',
    'SD_SRAM_laaian10', 'SD_SRAM_laaian10share', 'SD_SRAM_laomultir10',
    'SD_SRAM_laomultir10share', 'SD_SRAM_lahisp10', 'SD_SRAM_lahisp10share',
    'SD_SRAM_lahunv10', 'SD_SRAM_lahunv10share', 'SD_SRAM_lasnap10',
    'SD_SRAM_lasnap10share', 'SD_SRAM_laveteran10', 'SD_SRAM_laveteran10share',
    'SD_SRAM_lapop20', 'SD_SRAM_lapop20share', 'SD_SRAM_lalowi20', 'SD_SRAM_lalowi20share',
    'SD_SRAM_lakids20', 'SD_SRAM_lakids20share', 'SD_SRAM_laseniors20',
    'SD_SRAM_laseniors20share', 'SD_SRAM_lawhite20', 'SD_SRAM_lawhite20share',
    'SD_SRAM_lablack20', 'SD_SRAM_lablack20share', 'SD_SRAM_laasian20',
    'SD_SRAM_laasian20share', 'SD_SRAM_lanhopi20', 'SD_SRAM_lanhopi20share',
    'SD_SRAM_laaian20', 'SD_SRAM_laaian20share', 'SD_SRAM_laomultir20',
    'SD_SRAM_laomultir20share', 'SD_SRAM_lahisp20', 'SD_SRAM_lahisp20share',
    'SD_SRAM_lahunv20', 'SD_SRAM_lahunv20share', 'SD_SRAM_lasnap20',
    'SD_SRAM_lasnap20share', 'SD_SRAM_laveteran20', 'SD_SRAM_laveteran20share',
)


# column -> doc, for the four 0/1 low-income-low-access flags (rate_basis='index').
FLAG_MEASURES = {
    "LILATracts_1And10": "Low-income and low-access tract, measured at 1 mile for urban "
        "areas and 10 miles for rural areas.",
    "LILATracts_halfAnd10": "Low-income and low-access tract, measured at 1/2 mile for "
        "urban areas and 10 miles for rural areas.",
    "LILATracts_1And20": "Low-income and low-access tract, measured at 1 mile for urban "
        "areas and 20 miles for rural areas.",
    "LILATracts_Vehicle": "Low-income and low-access tract using vehicle access, or "
        "low-income and low-access tract measured at 20 miles.",
}
# column -> (numerator column, denominator column, universe, doc), for the
# half-mile and 1-mile share measures (rate_basis='percent').
SHARE_MEASURES = {
    "lapophalfshare": ("lapophalf", "Pop2010", "tract total population (2010 Census)",
        "Share of tract population living beyond 1/2 mile from the nearest supermarket."),
    "lalowihalfshare": ("lalowihalf", "Pop2010", "tract total population (2010 Census)",
        "Share of tract population that is low-income, living beyond 1/2 mile from the "
        "nearest supermarket."),
    "lahunvhalfshare": ("lahunvhalf", "OHU2010", "tract occupied housing units (2010 Census)",
        "Share of tract housing units without a vehicle, living beyond 1/2 mile from the "
        "nearest supermarket."),
    "lapop1share": ("lapop1", "Pop2010", "tract total population (2010 Census)",
        "Share of tract population living beyond 1 mile from the nearest supermarket."),
    "lalowi1share": ("lalowi1", "Pop2010", "tract total population (2010 Census)",
        "Share of tract population that is low-income, living beyond 1 mile from the "
        "nearest supermarket."),
    "lahunv1share": ("lahunv1", "OHU2010", "tract occupied housing units (2010 Census)",
        "Share of tract housing units without a vehicle, living beyond 1 mile from the "
        "nearest supermarket."),
}
# 2015's shares are 0-1 fractions, 2019's are 0-100 percentages (module
# docstring); this normalizes measure.observation.value to percent for both.
SHARE_SCALE = {"2019": 1, "2015": 100, "2025": 1}

# SHARE_MEASURES' denominator column ("Pop2010"/"OHU2010") by edition -- 2025's
# General Tract Characteristics file spells these POP2020/OHU2020 (a
# different Census year, not just a prefix; module docstring).
DENOMINATOR_COLUMNS = {
    "2019": {"Pop2010": "Pop2010", "OHU2010": "OHU2010"},
    "2015": {"Pop2010": "Pop2010", "OHU2010": "OHU2010"},
    "2025": {"Pop2010": "POP2020", "OHU2010": "OHU2020"},
}
# 2025's methodology note, appended to the SRAM-variant measure.definition
# docs below -- SRAM measures access to any SNAP-authorized retailer, not
# just the 2019/2015 editions' large grocery stores/supermarkets (module
# docstring), so it is a different statistic even where the flag/share
# definition text is otherwise identical.
SRAM_NOTE = (" 2025 SRAM edition: access is measured to any SNAP-authorized retailer "
    "(convenience and dollar stores included), not just large grocery stores/supermarkets "
    "as in the 2019/2015 editions -- see source_release.")


def _measure_id(col, edition):
    """The FARA:* measure_id for canonical column `col` under `edition` --
    'FARA:SRAM_{col}' for 2025, since it is a different retailer-universe
    statistic from the 2019/2015 editions' 'FARA:{col}' (module docstring),
    not just a later vintage of the same one."""
    return f"FARA:SRAM_{col}" if edition == "2025" else f"FARA:{col}"


def _physical(col, edition):
    """The real raw-table column for canonical (2019-spelling) column `col`
    under `edition`. 2019 and 2015 share raw.ers__food_access under this
    literal name (module docstring); 2025 lands in raw.ers__food_access_sram
    under USDA's own SD_SRAM_ prefix (straight-line distance), verbatim."""
    return f"SD_SRAM_{col}" if edition == "2025" else col


def _member(url, tmpdir, suffix):
    """The edition's data file at `url`: downloaded and unzipped if it's a
    zip, used as-is otherwise (a local .csv/.xlsx, how offline tests stay
    offline)."""
    if url.startswith("http"):
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        zpath = Path(tmpdir) / "atlas.zip"
        with urllib.request.urlopen(req) as r, open(zpath, "wb") as f:
            f.write(r.read())
        src = zpath
    else:
        src = Path(url)
    if src.suffix != ".zip":
        return src
    with zipfile.ZipFile(src) as z:
        # Each zip also carries a ReadMe and a VariableLookup sheet (2019) or
        # the PDF documentation (2015) -- excluded by name so exactly one
        # member matches the data file's own suffix.
        names = [n for n in z.namelist() if n.endswith(suffix)
                 and "readme" not in n.lower() and "variablelookup" not in n.lower()]
        if len(names) != 1:
            raise SystemExit(f"ers_food_access: {url} has {len(names)} {suffix} data "
                             f"member(s) among {z.namelist()}, expected 1")
        z.extract(names[0], tmpdir)
        return Path(tmpdir) / names[0]


def _source_sql(path, meta):
    if meta["suffix"] == ".csv":
        # Dialect stated, not sniffed: plain comma-delimited, double-quoted
        # where a cell needs it. nullstr='' -- a genuinely blank cell (none
        # seen in the real files) is NULL; the 'NULL' sentinel text is not.
        return (f"read_csv('{path}', header=true, all_varchar=true, delim=',', "
                f"quote='\"', escape='\"', nullstr='')")
    return f"read_xlsx('{path}', sheet='{meta['sheet']}', all_varchar=true)"


def _header(con, path, meta):
    if meta["suffix"] == ".csv":
        with open(path, encoding="utf-8") as f:
            return tuple(f.readline().rstrip("\r\n").split(","))
    return tuple(con.sql(f"SELECT * FROM {_source_sql(path, meta)} LIMIT 0").columns)


def _ensure_utf8(path):
    """Both SRAM files have one stray Latin-1 byte for a New Mexico county
    name ('Do\\xf1a Ana County', tract 35013001103) -- the same quirk
    census_gazetteer.py's 2010 county file and ers_ruca.py's 2020 CSV have
    (module docstring). Decoding the whole file as Latin-1 on a UTF-8
    failure recovers the intended character exactly, safe because the rest
    of each file is plain ASCII."""
    raw = path.read_bytes()
    try:
        raw.decode("utf-8")
        return path
    except UnicodeDecodeError:
        fixed = path.with_name(path.stem + ".utf8" + path.suffix)
        fixed.write_text(raw.decode("latin-1"), encoding="utf-8")
        return fixed


def _sram_members(url, tmpdir):
    """The two SRAM files this module lands (SRAM_MEMBERS; module docstring
    -- Driving Distance is excluded), downloaded and unzipped if `url` is a
    zip, read from a local zip otherwise (how offline tests stay offline)."""
    if url.startswith("http"):
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        zpath = Path(tmpdir) / "sram.zip"
        with urllib.request.urlopen(req) as r, open(zpath, "wb") as f:
            f.write(r.read())
    else:
        zpath = Path(url)
    paths = {}
    with zipfile.ZipFile(zpath) as z:
        names = set(z.namelist())
        for kind, name in SRAM_MEMBERS.items():
            if name not in names:
                raise SystemExit(f"ers_food_access: {url} has no member {name!r} "
                                 f"among {sorted(names)}")
            z.extract(name, tmpdir)
            paths[kind] = _ensure_utf8(Path(tmpdir) / name)
    return paths


def _land_sram(cat, release, url):
    """Phase 1 for the 2025 SRAM edition: General Tract Characteristics and
    Straight-Line Distance, joined on CensusTract20, landed whole and
    verbatim into their own table (module docstring)."""
    with tempfile.TemporaryDirectory() as tmp:
        paths = _sram_members(url, tmp)
        con = duckdb.connect()
        gen_header = tuple(con.sql(
            f"SELECT * FROM read_csv('{paths['general']}', header=true, "
            f"all_varchar=true) LIMIT 0").columns)
        sd_header = tuple(con.sql(
            f"SELECT * FROM read_csv('{paths['sd']}', header=true, "
            f"all_varchar=true) LIMIT 0").columns)
        if gen_header != GENERAL_COLUMNS_2025:
            raise SystemExit(f"ers_food_access: {url} General Tract Characteristics header "
                             f"is not the declared 2025 layout; differs in "
                             f"{sorted(set(gen_header) ^ set(GENERAL_COLUMNS_2025))}")
        if sd_header != SD_COLUMNS_2025:
            raise SystemExit(f"ers_food_access: {url} Straight Line Distance header is not "
                             f"the declared 2025 layout; differs in "
                             f"{sorted(set(sd_header) ^ set(SD_COLUMNS_2025))}")

        # SD's own copies of the 4 join/geo columns are dropped -- General's
        # are landed instead (module docstring: General + SD are joined,
        # not concatenated).
        join_cols = ("CensusTract20", "State", "County20", "County24")
        select_general = ", ".join(f'g."{c}"' for c in GENERAL_COLUMNS_2025)
        select_sd = ", ".join(f's."{c}"' for c in SD_COLUMNS_2025 if c not in join_cols)
        arrow = con.sql(f"""
            SELECT {select_general}, {select_sd}, '2025' AS atlas_edition,
                   '{release}' AS landed_in
            FROM read_csv('{paths["general"]}', header=true, all_varchar=true,
                          nullstr='') g
            JOIN read_csv('{paths["sd"]}', header=true, all_varchar=true, nullstr='') s
              ON lpad(g.CensusTract20, 11, '0') = lpad(s.CensusTract20, 11, '0')
        """).to_arrow_table()
    if not arrow.num_rows:
        raise SystemExit(f"ers_food_access: {url} yielded no rows")

    n = merge.write(cat, "raw.ers__food_access_sram", arrow, EqualTo("atlas_edition", "2025"))
    merge.manifest(cat, release, "ers_food_access", url, n, version="2025",
                   method="release_number")
    return "2025", n


def land_raw(cat, release, edition=None, url=None):
    """Phase 1: one FARA edition, verbatim and whole, replaced per edition."""
    edition = edition or max(EDITIONS, key=int)
    if edition not in EDITIONS:
        raise SystemExit(f"ers_food_access: unknown edition {edition!r}; "
                         f"known editions: {sorted(EDITIONS)}")
    meta = EDITIONS[edition]
    fetch_url = url or meta["url"]
    if edition == "2025":
        return _land_sram(cat, release, fetch_url)

    con = duckdb.connect()
    if meta["suffix"] == ".xlsx":
        con.sql("INSTALL excel; LOAD excel;")
    with tempfile.TemporaryDirectory() as tmp:
        path = _member(fetch_url, tmp, meta["suffix"])
        if (header := _header(con, path, meta)) != COLUMNS[edition]:
            raise SystemExit(f"ers_food_access: {fetch_url} header is not the declared "
                             f"{edition} layout; differs in "
                             f"{sorted(set(header) ^ set(COLUMNS[edition]))}")

        # Select in the source's own column order, aliased to 2019's spelling
        # (the one case difference -- see module docstring).
        select = ", ".join(f'"{src}" AS "{canon}"'
                           for src, canon in zip(COLUMNS[edition], COLUMNS_2019))
        arrow = con.sql(f"""
            SELECT {select}, '{edition}' AS atlas_edition, '{release}' AS landed_in
            FROM {_source_sql(path, meta)}
        """).to_arrow_table()
    if not arrow.num_rows:
        raise SystemExit(f"ers_food_access: {fetch_url} yielded no rows")

    n = merge.write(cat, "raw.ers__food_access", arrow, EqualTo("atlas_edition", edition))
    merge.manifest(cat, release, "ers_food_access", fetch_url, n, version=edition,
                   method="release_number")
    return edition, n


def _check_sentinels(con, edition, columns):
    """Every value in `columns` must be either the edition's 'NULL' sentinel
    (see module docstring -- 2015 has none) or something TRY_CAST can parse
    as a number. Anything else is a missing-value convention this module
    hasn't enumerated, and is a hard stop rather than a silent NULL."""
    checks = " UNION ALL ".join(
        f'SELECT \'{c}\' AS col, "{c}" AS val FROM raw '
        f'WHERE "{c}" != \'NULL\' AND TRY_CAST("{c}" AS DOUBLE) IS NULL'
        for c in columns)
    bad = con.sql(checks).fetchall()
    if bad:
        raise SystemExit(f"ers_food_access: unmapped non-numeric value(s) in {edition}: "
                         f"{sorted(set(bad))}")


def transform(cat, release, edition):
    """Phase 2: the 4 LILA flags + 6 half-mile/1-mile share measures (module
    docstring), plus their measure.definition and shared stratum.

    Scoped to `edition`'s rows: raw accumulates every landed edition, so an
    unscoped read would derive from all of them at once. 2025 reads from
    raw.ers__food_access_sram (its own table -- module docstring) under
    USDA's own SD_SRAM_ column names (`_physical`) and 'FARA:SRAM_*' measure
    ids (`_measure_id`), a different retailer-universe statistic from the
    2019/2015 editions' 'FARA:*' ids.

    measure.definition is written by `merge.write` (a flat scope overwrite,
    not the history-preserving `merge.merge`), so it always carries both id
    families regardless of which single edition this call landed -- an
    edition-conditional definition table would let one edition's re-ingest
    silently erase the other's definitions.
    """
    scale = SHARE_SCALE[edition]
    geo_vintage = GEO_VINTAGE[edition]
    raw_table = "raw.ers__food_access_sram" if edition == "2025" else "raw.ers__food_access"
    tract_col = "CensusTract20" if edition == "2025" else "CensusTract"
    con = duckdb.connect()
    con.register("raw", cat.load_table(raw_table).scan(
        row_filter=EqualTo("atlas_edition", edition)).to_arrow())

    numeric_cols = {_physical(c, edition) for c in FLAG_MEASURES}
    numeric_cols |= {_physical(c, edition) for c in SHARE_MEASURES}
    for num, den, _, _ in SHARE_MEASURES.values():
        numeric_cols |= {_physical(num, edition), DENOMINATOR_COLUMNS[edition][den]}
    _check_sentinels(con, edition, numeric_cols)

    definition = pa.Table.from_pylist(
        [dict(measure_id=f"FARA:{col}", source="FARA", label=col, units="flag (0/1)",
              universe="census tract", rate_basis="index", age_adjustment=None,
              method="derived", cancer_site_code=None, doc=doc)
         for col, doc in FLAG_MEASURES.items()] +
        [dict(measure_id=f"FARA:SRAM_{col}", source="FARA", label=col, units="flag (0/1)",
              universe="census tract", rate_basis="index", age_adjustment=None,
              method="derived", cancer_site_code=None, doc=doc + SRAM_NOTE)
         for col, doc in FLAG_MEASURES.items()] +
        [dict(measure_id=f"FARA:{col}", source="FARA", label=col, units="percent",
              universe=universe, rate_basis="percent", age_adjustment=None,
              method="derived", cancer_site_code=None, doc=doc)
         for col, (_, _, universe, doc) in SHARE_MEASURES.items()] +
        [dict(measure_id=f"FARA:SRAM_{col}", source="FARA", label=col, units="percent",
              universe=universe.replace("2010 Census", "2020 Census"), rate_basis="percent",
              age_adjustment=None, method="derived", cancer_site_code=None, doc=doc + SRAM_NOTE)
         for col, (_, _, universe, doc) in SHARE_MEASURES.items()])

    # FARA publishes no stratification within a tract estimate -- one
    # all-persons stratum covers every row (same pattern as ers_rucc.py).
    stratum = pa.Table.from_pylist([dict(
        stratum_id="FARA:ALL", source="FARA", sex=None, age_group=None,
        race_ethnicity=None, stage=None, other=None, scheme="FARA_NONE",
    )])

    geo_id = f"'tract:' || lpad({tract_col}, 11, '0')"
    flag_sql = " UNION ALL ".join(f"""
        SELECT 'FARA' AS source, '{edition}' AS source_release,
               '{_measure_id(col, edition)}' AS measure_id,
               {geo_id} AS geo_id, {geo_vintage} AS geo_vintage,
               '{edition}' AS period_start, '{edition}' AS period_end, 'FARA:ALL' AS stratum_id,
               TRY_CAST("{_physical(col, edition)}" AS DOUBLE) AS value,
               NULL::DOUBLE AS lower, NULL::DOUBLE AS upper, NULL::DOUBLE AS interval_level,
               NULL::DOUBLE AS numerator, NULL::DOUBLE AS denominator,
               CASE WHEN TRY_CAST("{_physical(col, edition)}" AS DOUBLE) IS NOT NULL
                    THEN 'reported' ELSE 'not_available' END AS value_status,
               NULL::VARCHAR AS reliability_flag, NULL::VARCHAR AS trend
        FROM raw
    """ for col in FLAG_MEASURES)
    share_sql = " UNION ALL ".join(f"""
        SELECT 'FARA' AS source, '{edition}' AS source_release,
               '{_measure_id(col, edition)}' AS measure_id,
               {geo_id} AS geo_id, {geo_vintage} AS geo_vintage,
               '{edition}' AS period_start, '{edition}' AS period_end, 'FARA:ALL' AS stratum_id,
               TRY_CAST("{_physical(col, edition)}" AS DOUBLE) * {scale} AS value,
               NULL::DOUBLE AS lower, NULL::DOUBLE AS upper, NULL::DOUBLE AS interval_level,
               TRY_CAST("{_physical(num, edition)}" AS DOUBLE) AS numerator,
               TRY_CAST("{DENOMINATOR_COLUMNS[edition][den]}" AS DOUBLE) AS denominator,
               CASE WHEN TRY_CAST("{_physical(col, edition)}" AS DOUBLE) IS NOT NULL
                    THEN 'reported' ELSE 'not_available' END AS value_status,
               NULL::VARCHAR AS reliability_flag, NULL::VARCHAR AS trend
        FROM raw
    """ for col, (num, den, _, _) in SHARE_MEASURES.items())
    observation = con.sql(f"{flag_sql} UNION ALL {share_sql}").to_arrow_table()
    merge.check_observations(observation)

    scope = EqualTo("source", "FARA")
    return {
        "measure.definition": merge.write(cat, "measure.definition", definition, scope),
        "measure.stratum": merge.write(cat, "measure.stratum", stratum, scope),
        "measure.observation": merge.merge(
            cat, "measure.observation", observation, release,
            And(scope, EqualTo("source_release", edition))),
    }


def ingest(cat, release, edition=None, url=None):
    edition, n = land_raw(cat, release, edition, url)
    raw_table = "raw.ers__food_access_sram" if edition == "2025" else "raw.ers__food_access"
    return {raw_table: n, **transform(cat, release, edition)}
