"""HRSA Area Health Resources Files (AHRF), county level -> Iceberg.

County-level workforce and facility supply data -- the supply-side context
for a catchment (SPEC.md § Sources -- first tranche). Upstream:
https://data.hrsa.gov/topics/health-workforce/ahrf (topic page) and
https://data.hrsa.gov/data/download?data=AHRF (downloads), annual releases.

**Distribution format, checked 2026-09-18.** The download page's real hrefs
(fetched directly, not summarized) show county-level AHRF as ASCII fixed-width
for 1999-2018, and CSV + SAS + ASCII from the 2022-2023 release on
(`AHRF_CSV_2022-2023.zip`, `AHRF%202023-2024%20CSV.zip`,
`AHRF_2024-2025_CSV.zip`). Only those three CSV-format releases are ever
in scope for this module; earlier fixed-width-only editions are left out.

ponytail: only the current 2024-2025 release is landed. 2022-2023 and
2023-2024 are also CSV-format and could be added the same way RUCC's editions
would be, by declaring their own header/COLUMNS constants first -- not done
here since nothing yet needs the history.

**The CSV zip is one enormous county-row-per-file plus redundant subset
extracts, not several independent thematic files.** Downloaded and inspected
directly: `AHRF_2024-2025_CSV.zip` contains `AHRF2025.csv` (3,235 rows x
4,352 columns -- one row per county/county-equivalent, every field) plus
seven "thematic" files (`env`, `exp`, `geo`, `hf`, `hp`, `pop`, `utl`) that
are column *subsets* of the same master file, for people who only want one
category -- verified column-for-column identical to the master file (a
handful of last-column mismatches turned out to be a CRLF artifact of the
comparison, not real data). Landing the one master file is landing the whole
release; the thematic files add nothing.

## Licence -- this is the load-bearing finding of this module

The topic page states, verbatim: "Usage limitations: None" (checked
2026-09-18, https://data.hrsa.gov/topics/health-workforce/ahrf, rendered
page). That is the generic, page-level claim the issue's `license:cleared`
label was presumably set from.

The release's OWN bundled technical documentation
(`AHRF_USER_TECH_2024-2025.zip` -> `Technical Documentation/AHRF 2024-2025
Technical Documentation.xlsx`, downloaded and opened directly, 2026-09-18)
says something narrower and, for two entire categories of field, contrary:

> "The Area Health Resources Files are made available by the Bureau of
> Health Workforce. Reproduction for re-use or sale is not authorized
> without the expressed permission of the Bureau. Further, data from the
> American Dental Association, the American Hospital Association, and the
> American Medical Association are subject to copyright restrictions; these
> data may not be copied or reproduced in whole or in part without the
> prior consent of the copyright owner."

and its own source-abbreviation glossary, in the same file:

> "AHA Survey Database = American Hospital Association Hospital Facilities
> Database (Copyright)"
> "AMA Phys Master File = American Medical Association Physician Master
> File (Copyright)"

The per-field data dictionary in the same document (columns FIELD/CAT/YEAR OF
DATA/VARIABLE NAME/CHARACTERISTICS/SOURCE/DATE ON) names, for every one of
AHRF's 4,352 county columns, which of 45 distinct sources it came from (6
more columns list no source at all). **The gate below is an ALLOWLIST, not a
blocklist**: a column lands only if its source is on `ALLOWED_SOURCES` (or is
one of the 6 no-source structural fields, `NO_SOURCE_LISTED_ALLOWED`) --
anything else is excluded by default, whether this module has a documented
reason for it (`EXCLUDED_SOURCES`) or has simply never seen that source
before (reported by `land_raw`, never landed silently). Every one of the 45
distinct sources in the real 2024-2025 file, checked 2026-09-18:

| Source (as the documentation spells it) | Cols | Verdict | Why |
| --- | ---: | --- | --- |
| AMA Phys Master File | 1815 | EXCLUDED | American Medical Association Physician Masterfile -- glossary-flagged `(Copyright)`; named in the cover-page restriction quoted above. Every physician-specialty count (oncology, radiation oncology, gastroenterology, radiology, dermatology, total M.D.s) is this source. |
| AHA Survey Database 23 | 493 | EXCLUDED | American Hospital Association survey -- `(Copyright)`, same restriction. Every hospital/bed count is this source. |
| AHA Survey Database 22 | 295 | EXCLUDED | as above. |
| ADA Masterfile | 50 | EXCLUDED | American Dental Association Masterfile -- named directly in the cover-page restriction (its glossary entry omits the `(Copyright)` tag the other two carry, but the prose names it all the same). |
| County Health Rankings File | 2 | EXCLUDED | Third party (County Health Rankings & Roadmaps, U Wisconsin PHI / RWJF) -- SPEC.md's Licence gate already lists this source as "Needs review before ingest ... confirm the record's licence", repo-wide and unresolved. |
| System Sciences Study | 1 | EXCLUDED | One 1976-77 elevation field from a private contractor's environmental-mortality study -- no redistribution terms found. |
| DDH,9-33 | 1 | EXCLUDED | One field (`cnty_name`) citing an internal document code not resolved in the documentation's own glossary -- excluded for lack of a verifiable source, not suspected proprietary (the county name is also carried, allowed, as part of `cnty_name_st_abbrev`, "Derived From GSA"). |
| NCHS Mortality File | 88 | EXCLUDED (pending review) | National Center for Health Statistics (CDC/HHS) -- federal settles copyright but NOT NCHS's own vital-statistics data-use agreement: the AHRF User Guide confirms "NCHS restrictions prohibit release of any subnational data with fewer than 10 occurrences". SPEC.md's Licence gate already treats CDC WONDER as "Needs review before ingest" for exactly this restriction. This is a review hold, not a finding that the data is actually restricted -- revisit once that agreement's redistribution terms (as opposed to its publication-threshold rule) are checked. |
| NCHS Natality File | 42 | EXCLUDED (pending review) | same NCHS vital-statistics data-use agreement as NCHS Mortality File above. |
| NCHS Mort/Nat File | 2 | EXCLUDED (pending review) | same, a combined mortality/natality-file citation. |
| 2019-23 Census ACS | 338 | allowed | U.S. Census Bureau, federal. |
| 2018-22 Census ACS | 338 | allowed | ditto. |
| Census SAHIE | 152 | allowed | ditto (Small Area Health Insurance Estimates). |
| 2010 Census SF1 | 129 | allowed | ditto. |
| 2020 Census DHC | 124 | allowed | ditto. |
| CMS NPI File | 60 | allowed | CMS NPPES provider registry, federal. |
| Census County Char File | 54 | allowed | U.S. Census Bureau, federal. |
| 2020 Census Redistrict | 48 | allowed | ditto (PL 94-171). |
| CMS Marketplace | 44 | allowed | CMS, federal. |
| 2010 Census Redistrict | 42 | allowed | ditto. |
| Medicare Geographic Var | 40 | allowed | CMS, federal. |
| CMS Provider of Services | 24 | allowed | CMS, federal (already used for FQHC/RHC/hospice/ASC counts). |
| HRSA DNHSC | 18 | allowed | HRSA, federal. |
| ERS Dept of Agriculture | 16 | allowed | USDA, federal (same source `ers_rucc.py` already treats as public domain). |
| Census Map | 14 | allowed | U.S. Census Bureau, federal. |
| Census SAIPE | 14 | allowed | ditto. |
| Dept of Veterans Affairs | 10 | allowed | federal. |
| OMB-23-01 | 8 | allowed | Office of Management and Budget, federal. |
| HRSA Data Warehouse | 8 | allowed | HRSA, federal (already used for HPSA codes). |
| Census County Pop Est | 8 | allowed | U.S. Census Bureau, federal. |
| Bureau of Labor Stats | 8 | allowed | federal. |
| CMS | 7 | allowed | federal. |
| LAPI | 6 | allowed | U.S. Bureau of Economic Analysis, federal (Local Area Personal Income). |
| CMS Monthly Enroll Dashbrd | 6 | allowed | CMS, federal. |
| CMS MA Penetration | 6 | allowed | CMS, federal. |
| EPA | 6 | allowed | federal. |
| EPA Air Qual Index Rep | 6 | allowed | federal. |
| Derived From GSA | 5 | allowed | General Services Administration, federal -- includes `fips_st_cnty` itself, which becomes raw's `fips` key column rather than a `column_name`/`value` cell. |
| Census Bureau | 4 | allowed | federal. |
| CMS PDP Penetration | 4 | allowed | CMS, federal. |
| CDC EPH Tracking Network | 4 | allowed | federal. |
| Census SNAP File | 2 | allowed | U.S. Census Bureau, federal. |
| Census Housing Unit File | 2 | allowed | ditto. |
| U.S. Post Office | 1 | allowed | USPS state abbreviations -- standard postal codes, the same ones `census_gazetteer.py`/`ers_rucc.py` already carry unremarked. |
| DHHS | 1 | allowed | federal. |
| *(no source listed)* | 6 | allowed | AHRF's own file-structural fields (`blank`, `date_cretn`, `date_file`, `entity_file`, `file_length`, `st_name`) -- not content from any dataset. |

2,789 excluded + 1,563 allowed = 4,352, the whole header. `raw.hrsa__ahrf` lands
1,562 of the 1,563 allowed columns as `(column_name, value)` cells -- the
1,563rd, `fips_st_cnty`, becomes the `fips` key column instead (see the
`Derived From GSA` row). Checked against the real 2024-2025 file
programmatically (not just this table by hand): zero columns fell into the
"unrecognised source" bucket -- every one of the 45 distinct sources above
is accounted for by `ALLOWED_SOURCES` or `EXCLUDED_SOURCES`. Three of those
45 (the NCHS rows above, 132 columns) are a deliberate REVIEW HOLD, not a
finding of restriction -- see their row for why.

**Consequence for this module, and for the issue that asked for it (#39):**
the issue's requested curated list -- "active MDs, primary-care physicians,
oncologists, gastroenterologists, radiologists, dermatologists, hospitals,
hospital beds" -- is drawn entirely from the AMA/AHA rows above and is NOT
landed here, in raw or derived, under any circumstance (AGENTS.md hard gate:
"License before ingest... license:unknown is a hard stop"; here the finding
is stronger than "unknown" -- it is affirmatively not cleared). What ships
instead is the curated set built from AHRF's genuinely allowed columns (see
`MEASURE_DEFINITIONS` below and the PR description).

The allowed sources above are U.S. government work, public domain per 17
U.S.C. Sec 105 ("Data and content created by government employees within the
scope of their employment are not subject to domestic copyright
protection... Government works are by default in the U.S. Public Domain.",
https://resources.data.gov/open-licenses/) -- the same standing quote the
other sources in this repo cite -- except `U.S. Post Office`, treated as
allowed for the same reason the repo's other sources already carry USPS
state codes unremarked (a standardized, non-creative 2-letter code, not the
Postal Service's copyrightable content). `land_raw` computes the eligible
column set itself, at ingest time, straight from the release's own technical
documentation (see `_classify_columns`), rather than trusting a hand-copied
list to stay in sync with it.

## Landing WHOLE, in LONG form

AHRF is very wide even after the licence gate: 1,562 allowed columns x 3,235
counties. Measured locally against the real file: declaring one NestedField
(with a `doc`, per house rule) for each of ~1,700 columns is not a schema
anyone could review or maintain, and the vast majority would never be read
by anything this repo derives. So raw lands LONG instead -- `(ahrf_release,
file, fips, column_name, value)`, one row per (county, field) cell, verbatim
strings -- which is still landing every eligible cell of the release whole
(SPEC.md ADR-0002's "land raw whole", just at cell rather than wide-row
granularity; ADR-0002 doesn't mandate one physical column per source field,
only that nothing is thrown away or pre-filtered by guessing what will
matter later). Measured: unpivoting the real release takes ~5s and produces
5,053,070 rows locally (1,562 columns x 3,235 counties).

ponytail: because raw is long and every cell is addressed by name rather than
position, this module's header check does NOT reproduce AHRF's 4,352-column
header verbatim the way the other sources' COLUMNS contracts do (that would
be ~100KB of literal column names for no real safety gain here: a reordered
or additional column is harmless to a name-addressed unpivot). Instead
`land_raw` checks that `fips_st_cnty` exists and that every column this
module actually reads (`CURATED_FIELDS`, below) is present and allowed, and
fails loudly naming exactly which ones are not -- the part of "drift" that
would actually break something downstream.

## Version axis and the three time axes (SPEC.md § Versioning)

`source_release` is the release label itself, `"2024-2025"` -- AHRF's own
citable edition name (`method="release_number"`), the same for every row
regardless of which data year a given column describes. `period_start` /
`period_end` come from each column's OWN year suffix instead (e.g.
`hospcs_24` describes 2024, `pers_noins_lt65_pct_21` describes 2021) --
exactly the SPEC.md distinction the issue calls out ("One release carries
many data years: the period comes from each field's year suffix, not the
release"). Getting this backwards (using 2024-2025 as the period) would
silently claim every measure describes the same year, which is false --
`np_npi_24` and `np_npi_23`, both in the SAME 2024-2025 release, describe
different data years AND (see below) different geography.

## Geography vintage: inferred per ROW from the real file, not per column family

AHRF's HPSA fields state no vintage of their own, so this is inferred
directly, as SPEC.md requires when a source doesn't document one. The real
2024-2025 file carries BOTH Connecticut's 8 pre-2022 counties (09001-09015)
AND its 9 post-2022 planning regions (09110-09190) as separate rows in the
SAME file -- and likewise both Alaska's pre-2019 Valdez-Cordova (02261) and
its current Chugach/Copper River census areas (02063/02066) -- verified by
downloading and querying the real CSV directly. Different source families
populate different halves of that split: CMS Provider of Services and HRSA
Data Warehouse fields (FQHC/RHC/hospice/ambulatory-surgery-center counts,
HPSA codes) are non-NULL on the legacy CT counties and NULL on the planning
regions; Census SAHIE and CMS NPI File fields are the reverse. More
tellingly, the split isn't even fixed per source: `np_npi_24` (2024 data)
populates only the 9 planning regions, while `np_npi_23` (2023 data, same
column FAMILY, same release) populates only the 8 legacy counties --
confirming Connecticut's real 2022 transition actually reached this
particular CMS feed between the 2023 and 2024 data years. So geo_vintage
here is a property of which FIPS code a ROW carries, not of which measure or
year produced it: `LEGACY_FIPS` (the pre-2022 CT counties plus
Valdez-Cordova) get `2010`; everything else gets `2020`. This one rule
correctly reproduces every case above without touching source family or
year at all.

## Missing data

Every curated column, checked directly against the real file: a source cell
is either a plain non-negative integer/decimal string, or blank. Blank is
AHRF's only missing marker for these columns (no `.`, `-999`, `*` sentinel
seen) and is mapped to `value_status = 'not_available'`, never a number and
never silently dropped -- a blank cell for a county still gets a raw row
(`value = NULL`) and a `measure.observation` row, because AHRF publishes a
column for every county row; it just leaves some cells empty rather than
omitting the row (unlike RUCC's Rose Island, which omits the row entirely).
A `0` (e.g. Chugach's `fedly_qualfd_hlth_ctr_24 = 0`) is a real reported
zero, never read as missing. `value_status` is derived from the same
`TRY_CAST` that produces `value` (not from the raw cell's presence), so a
hypothetical present-but-non-numeric cell -- never seen in the real curated
columns, but not something the source format rules out -- lands as
`not_available` rather than a numberless `'reported'` row (issue #148).
"""

import re
import tempfile
import urllib.request
import zipfile
from pathlib import Path

import duckdb
import pyarrow as pa
from pyiceberg.expressions import And, EqualTo

from . import merge

USER_AGENT = "cancerbasemap/1.0 (+https://github.com/seandavi/cancer-basemap)"

# AHRF release label -> (CSV zip URL, technical documentation zip URL). Only
# the current release is populated; 2023-2024 and 2022-2023 are also
# CSV-format (see module docstring) and could be added the same way, by
# declaring their own header/CURATED_FIELDS check first -- not done here
# since nothing yet needs the history.
RELEASES = {
    "2024-2025": ("https://data.hrsa.gov/DataDownload/AHRF/AHRF_2024-2025_CSV.zip",
                 "https://data.hrsa.gov/DataDownload/AHRF/AHRF_USER_TECH_2024-2025.zip"),
}

CSV_MEMBER = re.compile(r"^AHRF\d{4}\.csv$", re.IGNORECASE)
# The tech-doc zip also carries a data-dictionary CROSSWALK workbook
# (AHRFCrosswalk2025.xlsx) alongside the technical documentation itself --
# verified 2026-09-18 against the real zip -- so match on name, not just
# extension.
TECHDOC_MEMBER = re.compile(r"Technical Documentation.*\.xlsx$", re.IGNORECASE)

# ALLOWLIST, not a blocklist: a column lands only if its SOURCE (from the
# release's own technical documentation) is one of these -- U.S. federal
# government sources this module has verified as public domain, per column
# count against the real 2024-2025 file (2026-09-18). See module docstring
# for the full source -> {allowed | excluded: reason} table and the evidence
# for each row. A source not in EITHER this set or EXCLUDED_SOURCES below is
# unrecognised and excluded by default (fails closed) -- see _classify_columns.
ALLOWED_SOURCES = frozenset({
    "2018-22 Census ACS", "2019-23 Census ACS", "2010 Census SF1", "2020 Census DHC",
    "2010 Census Redistrict", "2020 Census Redistrict", "Census Bureau", "Census Map",
    "Census SAHIE", "Census SAIPE", "Census SNAP File", "Census Housing Unit File",
    "Census County Char File", "Census County Pop Est",
    "CMS", "CMS NPI File", "CMS Provider of Services", "CMS Marketplace",
    "CMS MA Penetration", "CMS PDP Penetration", "CMS Monthly Enroll Dashbrd",
    "Medicare Geographic Var",
    "HRSA Data Warehouse", "HRSA DNHSC",
    "ERS Dept of Agriculture", "Bureau of Labor Stats", "LAPI",
    "EPA", "EPA Air Qual Index Rep", "CDC EPH Tracking Network",
    "Dept of Veterans Affairs", "DHHS", "OMB-23-01", "Derived From GSA",
    "U.S. Post Office",
})

# Sources checked and found NOT landable, with why -- kept distinct from an
# unrecognised source (see _classify_columns) so the reason is on record
# rather than folded into a generic "unknown" bucket.
EXCLUDED_SOURCES = {
    "AMA Phys Master File": "American Medical Association Physician Masterfile -- "
        "flagged '(Copyright)' in the documentation's own source glossary; the "
        "documentation's cover page names the AMA explicitly as one of three sources "
        "whose data 'may not be copied or reproduced in whole or in part without the "
        "prior consent of the copyright owner' (see module docstring).",
    "AHA Survey Database 22": "American Hospital Association hospital survey -- same "
        "copyright restriction as AMA Phys Master File above.",
    "AHA Survey Database 23": "American Hospital Association hospital survey -- same "
        "copyright restriction as AMA Phys Master File above.",
    "ADA Masterfile": "American Dental Association Masterfile -- the documentation's "
        "cover page names the ADA explicitly in the same copyright restriction as AMA "
        "and AHA above (its glossary entry omits the '(Copyright)' tag the other two "
        "carry, but the cover-page prose names it directly).",
    "County Health Rankings File": "third-party (County Health Rankings & Roadmaps, "
        "University of Wisconsin Population Health Institute / RWJF) -- SPEC.md's "
        "Licence gate already lists 'County Health Rankings' under 'Needs review before "
        "ingest: now on Zenodo; confirm the record's licence', repo-wide, unresolved.",
    "System Sciences Study": "a single 1976-77 elevation-data field (elevtn_feet_76) "
        "from an environmental-correlates-of-mortality study by System Sciences, Inc., "
        "a private contractor -- no redistribution terms found for that study.",
    "DDH,9-33": "a single field (cnty_name) citing an internal document code not "
        "resolved anywhere in the technical documentation's own source glossary -- "
        "excluded for lack of a verifiable source/licence, not because it's suspected "
        "proprietary (cnty_name_st_abbrev, landed separately, is the same name, "
        "'Derived From GSA' and allowed).",
    "NCHS Mortality File": "pending licence review -- NOT a finding of restriction, a "
        "review hold: NCHS vital statistics (mortality/natality) carry their own "
        "data-use agreement on small-cell county data (the AHRF User Guide confirms "
        "NCHS 'restrictions prohibit release of any subnational data with fewer than "
        "10 occurrences'), and 'federal' settles copyright but not that separate "
        "agreement's terms. SPEC.md's Licence gate already treats CDC WONDER -- "
        "governed by the same NCHS vital-statistics restrictions -- as 'Needs review "
        "before ingest' for exactly this reason.",
    "NCHS Natality File": "pending licence review -- same NCHS vital-statistics "
        "data-use agreement as NCHS Mortality File above.",
    "NCHS Mort/Nat File": "pending licence review -- same NCHS vital-statistics "
        "data-use agreement as NCHS Mortality File above (a combined citation).",
}

# Columns the technical documentation lists with NO source at all (verified
# 2026-09-18): AHRF's own file-structural/administrative fields, not content
# from any dataset -- not third-party in any sense, so allowed by name rather
# than by an empty SOURCE value (an empty SOURCE elsewhere would be surprising
# and is NOT auto-allowed; see _classify_columns).
NO_SOURCE_LISTED_ALLOWED = frozenset({
    "blank", "date_cretn", "date_file", "entity_file", "file_length", "st_name",
})

# Connecticut's 8 pre-2022 counties and Alaska's pre-2019 Valdez-Cordova --
# still carried as separate rows in the current file by some source feeds
# (see module docstring). Everything else is the current (2020-vintage)
# county geography.
LEGACY_FIPS = frozenset({
    "09001", "09003", "09005", "09007", "09009", "09011", "09013", "09015", "02261",
})
LEGACY_GEO_VINTAGE = 2010
CURRENT_GEO_VINTAGE = 2020

SENTINEL = "__CANCERBASEMAP_NULL_SENTINEL__"

# The cancer-relevant curated set (issue #39), restricted to fields NOT
# sourced from AMA/AHA/ADA (see module docstring): (AHRF column, measure_id,
# the data year the column's OWN suffix encodes -- period, not source_release).
CURATED_FIELDS = (
    ("fedly_qualfd_hlth_ctr_24", "AHRF:FQHC", 2024),
    ("fedly_qualfd_hlth_ctr_23", "AHRF:FQHC", 2023),
    ("rural_hlth_clincs_24", "AHRF:RHC", 2024),
    ("rural_hlth_clincs_23", "AHRF:RHC", 2023),
    ("hospcs_24", "AHRF:HOSPICE", 2024),
    ("hospcs_23", "AHRF:HOSPICE", 2023),
    ("ambultry_surg_ctr_24", "AHRF:AMB_SURG_CTR", 2024),
    ("ambultry_surg_ctr_23", "AHRF:AMB_SURG_CTR", 2023),
    ("pers_noins_lt65_pct_22", "AHRF:UNINSURED_LT65_PCT", 2022),
    ("pers_noins_lt65_pct_21", "AHRF:UNINSURED_LT65_PCT", 2021),
    ("hpsa_prim_care_25", "AHRF:HPSA_PRIM_CARE", 2025),
    ("hpsa_prim_care_24", "AHRF:HPSA_PRIM_CARE", 2024),
    ("hpsa_mentl_hlth_25", "AHRF:HPSA_MENTAL_HEALTH", 2025),
    ("hpsa_mentl_hlth_24", "AHRF:HPSA_MENTAL_HEALTH", 2024),
    ("np_npi_24", "AHRF:NP_NPI", 2024),
    ("np_npi_23", "AHRF:NP_NPI", 2023),
    ("pa_npi_24", "AHRF:PA_NPI", 2024),
    ("pa_npi_23", "AHRF:PA_NPI", 2023),
    ("aprn_npi_24", "AHRF:APRN_NPI", 2024),
    ("aprn_npi_23", "AHRF:APRN_NPI", 2023),
)

# measure.definition content, one entry per measure_id above. All method =
# 'direct': every one is a plain administrative count or code, not modeled,
# except UNINSURED_LT65_PCT (Census SAHIE is itself a small-area *model*).
MEASURE_DEFINITIONS = {
    "AHRF:FQHC": dict(
        label="Federally Qualified Health Centers", units=None, rate_basis="count",
        method="direct",
        doc="Count of Medicare-certified Federally Qualified Health Centers in the county. "
            "Source: CMS Provider of Services file (AHRF field fedly_qualfd_hlth_ctr_*)."),
    "AHRF:RHC": dict(
        label="Rural Health Clinics", units=None, rate_basis="count", method="direct",
        doc="Count of Medicare-certified Rural Health Clinics in the county. "
            "Source: CMS Provider of Services file (AHRF field rural_hlth_clincs_*)."),
    "AHRF:HOSPICE": dict(
        label="Hospices", units=None, rate_basis="count", method="direct",
        doc="Count of Medicare-certified hospice providers in the county -- end-of-life "
            "cancer care access. Source: CMS Provider of Services file (AHRF field hospcs_*)."),
    "AHRF:AMB_SURG_CTR": dict(
        label="Ambulatory Surgery Centers", units=None, rate_basis="count", method="direct",
        doc="Count of Medicare-certified ambulatory surgery centers in the county -- "
            "outpatient surgical/procedural oncology access. Source: CMS Provider of "
            "Services file (AHRF field ambultry_surg_ctr_*)."),
    "AHRF:UNINSURED_LT65_PCT": dict(
        label="Percent uninsured, under age 65", units="percent", rate_basis="percent",
        method="model_based", universe="civilian population under age 65",
        doc="Small-area estimate of the percent of the population under 65 without health "
            "insurance. Source: U.S. Census Bureau Small Area Health Insurance Estimates "
            "(SAHIE) (AHRF field pers_noins_lt65_pct_*)."),
    "AHRF:HPSA_PRIM_CARE": dict(
        label="Primary Care Health Professional Shortage Area designation",
        units="code 0-2", rate_basis="index", method="direct",
        doc="HRSA Health Professional Shortage Area code for primary care: 0 = county not "
            "designated, 1 = whole county designated, 2 = part of county designated. "
            "Source: HRSA Data Warehouse (AHRF field hpsa_prim_care_*)."),
    "AHRF:HPSA_MENTAL_HEALTH": dict(
        label="Mental Health Health Professional Shortage Area designation",
        units="code 0-2", rate_basis="index", method="direct",
        doc="HRSA Health Professional Shortage Area code for mental health: 0 = county not "
            "designated, 1 = whole county designated, 2 = part of county designated -- "
            "supportive/psychosocial oncology care access. Source: HRSA Data Warehouse "
            "(AHRF field hpsa_mentl_hlth_*)."),
    "AHRF:NP_NPI": dict(
        label="Nurse practitioners with an active NPI", units=None, rate_basis="count",
        method="direct",
        doc="Count of nurse practitioners with an active National Provider Identifier in "
            "the county -- advanced-practice primary-care workforce supply. Source: CMS "
            "NPI File / NPPES (AHRF field np_npi_*)."),
    "AHRF:PA_NPI": dict(
        label="Physician assistants with an active NPI", units=None, rate_basis="count",
        method="direct",
        doc="Count of physician assistants with an active National Provider Identifier in "
            "the county. Source: CMS NPI File / NPPES (AHRF field pa_npi_*)."),
    "AHRF:APRN_NPI": dict(
        label="Advanced practice registered nurses with an active NPI", units=None,
        rate_basis="count", method="direct",
        doc="Count of advanced practice registered nurses with an active National Provider "
            "Identifier in the county. Source: CMS NPI File / NPPES (AHRF field aprn_npi_*)."),
}


def _fetch_member(url, tmpdir, pattern, tag):
    """The one file inside `url` (a zip, downloaded and cached in `tmpdir`)
    whose basename matches `pattern`. A local, non-zip path (tests) is used
    directly."""
    if not url.startswith("http"):
        path = Path(url)
        if path.suffix != ".zip":
            return path
        src = path
    else:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        zpath = Path(tmpdir) / f"{tag}.zip"
        with urllib.request.urlopen(req) as r, open(zpath, "wb") as f:
            f.write(r.read())
        src = zpath
    with zipfile.ZipFile(src) as z:
        names = [n for n in z.namelist() if pattern.search(Path(n).name)]
        if len(names) != 1:
            raise SystemExit(f"hrsa_ahrf: {url} has {len(names)} member(s) matching "
                             f"{pattern.pattern!r}, expected 1")
        z.extract(names[0], tmpdir)
        return Path(tmpdir) / names[0]


def _classify_columns(con, techdoc_path, header):
    """Split `header` (minus the fips key) into (eligible, excluded_unknown),
    per-column, against the release's own technical documentation's SOURCE
    field -- an ALLOWLIST, not a blocklist: a column lands only if its source
    is in `ALLOWED_SOURCES` (or it's one of the no-source structural fields in
    `NO_SOURCE_LISTED_ALLOWED`). Anything else is excluded, whether that's a
    documented reason in `EXCLUDED_SOURCES` or a source this module has never
    seen before -- `excluded_unknown` carries only the latter, for `land_raw`
    to report (SPEC.md/AGENTS.md: license:unknown is a hard stop, so an
    unrecognised source must never silently land).
    """
    con.execute("INSTALL excel; LOAD excel;")
    doc_rows = con.sql(f"""
        SELECT trim(A) AS field, trim(F) AS source
        FROM read_xlsx('{techdoc_path}', all_varchar=true, header=false, range='A1:G8000')
        WHERE trim(A) IS NOT NULL AND trim(A) != ''
    """).fetchall()
    if not doc_rows:
        raise SystemExit(f"hrsa_ahrf: {techdoc_path} yielded no field rows at all -- the "
                         f"technical documentation parse is probably broken -- refusing to "
                         f"land, since that would silently include unlicensed data")
    source_of = {field: source for field, source in doc_rows if source}

    eligible, excluded_unknown = [], {}
    for c in header:
        if c == "fips_st_cnty":
            continue
        source = source_of.get(c)
        if source is None:
            if c in NO_SOURCE_LISTED_ALLOWED:
                eligible.append(c)
            else:
                excluded_unknown.setdefault("(no source listed)", []).append(c)
        elif source in ALLOWED_SOURCES:
            eligible.append(c)
        elif source in EXCLUDED_SOURCES:
            pass  # documented and deliberate; nothing to report
        else:
            excluded_unknown.setdefault(source, []).append(c)
    return eligible, excluded_unknown


def land_raw(cat, release, ahrf_release=None, csv_url=None, techdoc_url=None):
    """Phase 1: the master county CSV, landed LONG and whole -- every column
    whose source (per the release's own technical documentation) is on the
    `ALLOWED_SOURCES` allowlist (see module docstring). A column with no
    listed source, or an unrecognised one, is excluded and reported, never
    landed by default. Returns (ahrf_release, rows).
    """
    ahrf_release = ahrf_release or max(RELEASES)
    if ahrf_release not in RELEASES:
        raise SystemExit(f"hrsa_ahrf: no known AHRF release {ahrf_release!r}; "
                         f"known releases: {sorted(RELEASES)}")
    default_csv_url, default_techdoc_url = RELEASES[ahrf_release]
    csv_url = csv_url or default_csv_url
    techdoc_url = techdoc_url or default_techdoc_url
    con = duckdb.connect()
    with tempfile.TemporaryDirectory() as tmp:
        csv_path = _fetch_member(csv_url, tmp, CSV_MEMBER, "csv")
        techdoc_path = _fetch_member(techdoc_url, tmp, TECHDOC_MEMBER, "techdoc")

        header = con.sql(f"SELECT * FROM read_csv('{csv_path}', header=true, "
                         f"all_varchar=true) LIMIT 0").columns
        if "fips_st_cnty" not in header:
            raise SystemExit(f"hrsa_ahrf: {csv_url} has no fips_st_cnty column")

        eligible, excluded_unknown = _classify_columns(con, techdoc_path, header)
        for source, cols in sorted(excluded_unknown.items()):
            print(f"hrsa_ahrf: excluding {len(cols)} column(s) with an unrecognised "
                 f"source ({source!r}), not on ALLOWED_SOURCES or EXCLUDED_SOURCES -- "
                 f"check its licence and add it to one of those before landing it: "
                 f"{cols[:5]}{', ...' if len(cols) > 5 else ''}")

        bad = sorted({f for f, _, _ in CURATED_FIELDS} - set(eligible))
        if bad:
            raise SystemExit(f"hrsa_ahrf: curated field(s) {bad} are not landable from "
                             f"{csv_url} (missing from the file, or not on ALLOWED_SOURCES) "
                             f"-- update CURATED_FIELDS/MEASURE_DEFINITIONS")

        # coalesce/CASE round-trip keeps a blank source cell as NULL through
        # UNPIVOT, which otherwise drops NULL cells outright rather than
        # keeping a (fips, column_name, NULL) row -- AHRF's blank cells are
        # real, present cells (see module docstring), not absent ones.
        coalesced = ", ".join(f'coalesce("{c}", \'{SENTINEL}\') AS "{c}"' for c in eligible)
        collist = ", ".join(f'"{c}"' for c in eligible)
        arrow = con.sql(f"""
            SELECT '{ahrf_release}' AS ahrf_release, '{csv_path.name}' AS file,
                   fips_st_cnty AS fips, column_name,
                   CASE WHEN value = '{SENTINEL}' THEN NULL ELSE value END AS value,
                   '{release}' AS landed_in
            FROM (
                UNPIVOT (SELECT fips_st_cnty, {coalesced}
                         FROM read_csv('{csv_path}', header=true, all_varchar=true))
                ON {collist}
                INTO NAME column_name VALUE value
            )
        """).to_arrow_table()
    if not arrow.num_rows:
        raise SystemExit(f"hrsa_ahrf: {csv_url} yielded no rows")

    n = merge.write(cat, "raw.hrsa__ahrf", arrow, EqualTo("ahrf_release", ahrf_release))
    merge.manifest(cat, release, "hrsa_ahrf", csv_url, n, version=ahrf_release,
                   method="release_number")
    return ahrf_release, n


def transform(cat, release, ahrf_release):
    """Phase 2: the curated cancer-relevant measures (see module docstring),
    unpivoted back out of the long raw table by column name.

    Scoped to `ahrf_release`'s rows: raw accumulates every landed release, so
    an unscoped read would derive from all of them at once.
    """
    con = duckdb.connect()
    con.register("raw", cat.load_table("raw.hrsa__ahrf").scan(
        row_filter=EqualTo("ahrf_release", ahrf_release)).to_arrow())

    definition = pa.Table.from_pylist([
        dict(measure_id=mid, source="AHRF", label=d["label"], units=d["units"],
             universe=d.get("universe"), rate_basis=d["rate_basis"], age_adjustment=None,
             method=d["method"], cancer_site_code=None, doc=d["doc"])
        for mid, d in MEASURE_DEFINITIONS.items()
    ])

    # AHRF publishes county totals with no stratification.
    stratum = pa.Table.from_pylist([dict(
        stratum_id="AHRF:ALL", source="AHRF", sex=None, age_group=None,
        race_ethnicity=None, stage=None, other=None, scheme="AHRF_TOTAL")])

    field_map = ", ".join(f"('{col}', '{mid}', {year})" for col, mid, year in CURATED_FIELDS)
    legacy_fips = ", ".join(f"'{f}'" for f in LEGACY_FIPS)
    # geo_vintage is a property of the FIPS code itself (see module
    # docstring), not of which measure or period produced the row.
    observation = con.sql(f"""
        WITH field_map(column_name, measure_id, period_year) AS (VALUES {field_map})
        SELECT 'AHRF' AS source, '{ahrf_release}' AS source_release, m.measure_id,
               'county:' || lpad(r.fips, 5, '0') AS geo_id,
               CASE WHEN r.fips IN ({legacy_fips}) THEN {LEGACY_GEO_VINTAGE}
                    ELSE {CURRENT_GEO_VINTAGE} END AS geo_vintage,
               m.period_year::VARCHAR AS period_start, m.period_year::VARCHAR AS period_end,
               'AHRF:ALL' AS stratum_id,
               TRY_CAST(r.value AS DOUBLE) AS value,
               NULL::DOUBLE AS lower, NULL::DOUBLE AS upper, NULL::DOUBLE AS interval_level,
               NULL::DOUBLE AS numerator, NULL::DOUBLE AS denominator,
               -- Status follows the CAST that actually produced `value`, not
               -- the raw cell's presence -- a present-but-non-numeric cell
               -- (never seen in the real file, verified 2026-09-19) must not
               -- land as a numberless 'reported' row (merge.check_observations).
               CASE WHEN TRY_CAST(r.value AS DOUBLE) IS NOT NULL THEN 'reported'
                    ELSE 'not_available' END AS value_status,
               NULL::VARCHAR AS reliability_flag, NULL::VARCHAR AS trend
        FROM raw r JOIN field_map m ON r.column_name = m.column_name
    """).to_arrow_table()
    merge.check_observations(observation)

    scope = EqualTo("source", "AHRF")
    return {
        "measure.definition": merge.write(cat, "measure.definition", definition, scope),
        "measure.stratum": merge.write(cat, "measure.stratum", stratum, scope),
        "measure.observation": merge.merge(
            cat, "measure.observation", observation, release,
            And(scope, EqualTo("source_release", ahrf_release))),
    }


def ingest(cat, release, ahrf_release=None, csv_url=None, techdoc_url=None):
    ahrf_release, n = land_raw(cat, release, ahrf_release, csv_url, techdoc_url)
    return {"raw.hrsa__ahrf": n, **transform(cat, release, ahrf_release)}
