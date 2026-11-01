"""CDC/ATSDR Social Vulnerability Index (SVI) -> Iceberg.

Upstream: https://www.atsdr.cdc.gov/place-health/php/svi/ -- county and tract CSVs for
US-wide editions 2000, 2010, 2014, 2016, 2018, 2020, 2022 (SPEC.md § Sources: "area-level
context index... land every published edition"). The download page
(svi-data-documentation-download.html) is a form; the underlying files were found by
reading its `js/loadXML.js` and live at
`https://svi.cdc.gov/Documents/Data/<edition>/csv/states_counties/SVI_<edition>_US_county.csv`
(county) and `.../csv/states/SVI_<edition>_US.csv` (tract), verified 2026-09-18 by
downloading all 14 real files.

**Licence.** CDC/ATSDR's own materials-use page states: "Most of the information on the
CDC and ATSDR websites is not subject to copyright, is in the public domain, and may be
freely used or reproduced without obtaining copyright permission."
(https://www.cdc.gov/other/agencymaterials.html, checked 2026-09-18). SVI is produced by
ATSDR's Geospatial Research, Analysis & Services Program, a federal agency, in the course
of employees' official duties -- also a U.S. Government work under 17 U.S.C. § 105.

**Version axis: the edition** (2000, 2010, 2014, 2016, 2018, 2020, 2022), landed as
`svi_edition`. "Methods and themes changed between editions, so an edition is a different
measure definition, not just a new period" (#40) -- verified directly: theme membership
(which raw variables feed RPL_THEME1-4) differs between the two landed layout families
(see below), so derived measure_ids embed the family, not just the edition.

**Editions landed: 2000, 2010, 2014, 2016, 2018, 2020, 2022 (county); same for tract (#92
lands 2000 and 2010's tract files too -- both are real, keyless bulk files at the same URL
pattern as the rest, verified 2026-09-19).**

**2000 and 2010 land into their own per-layout tables, not the shared raw.svi__county /
raw.svi__tract union (#92, following on from #40's deferral).** Neither fits safely into
the "2014"/"2020" layouts unioned below:
  - 2010's real header names a column "STATE" holding the 2-digit state FIPS code (e.g.
    '01'), while every 2014+ layout names its full state NAME column "STATE" (e.g.
    'Alabama') -- the same column name means a different kind of value depending on
    edition. Worse, 2000's OWN "STATE" column holds the full name (like 2014+, unlike
    2010) while its "ST" column holds the 2-digit FIPS (unlike 2014+, where ST is the USPS
    abbreviation) -- three editions, three different (ST, STATE) meanings, verified
    directly against all three real files. Landing any two of them under one shared
    column name would be a silent semantic trap for anyone querying raw directly, so 2000
    and 2010 each get a dedicated table (`raw.svi__county_2000`, `raw.svi__tract_2000`,
    `raw.svi__county_2010`, `raw.svi__tract_2010`) with their own real column names,
    matching the issue's suggested resolution.
  - 2010 has no E_/M_ ACS estimates or MOEs at all for several concepts this issue derives
    (structural Census 2010 SF1 100%-count only, no sampling error: AGE65, AGE17,
    SNGPRNT, MINORITY, GROUPQ have no M_ column in 2010 -- confirmed against the real file
    and against SVI-2010-Documentation-H.pdf's own "Based on 100% counts - no sampling
    error" notes). 2010 also has no disability variable at all -- the Census Bureau
    collected no tract-level disability data for either the 2010 Census or the 2006-2010
    ACS (same PDF), so 2010's theme 2 is Household Composition only (age 65+, age 17-,
    single-parent), one fewer component than every other edition's Household
    Composition/Disability theme.
  - **The 2000 county/tract CSVs ship with two header lines**, verified by downloading the
    real files: line 1 (`STATE_FIPS,CNTY_FIPS,...,G1V1R,...,USG1V1P,...`) does not match
    the data that follows it at all (its columns don't correspond to the values in any
    row); line 2 (`ST,COU,STCNTY,...,P_POV,...,RPL_THEME1,...,F_POV,...`) does -- e.g.
    Autauga County, AL's row 3 gives P_POV=0.1092, a plausible real 2000 poverty rate,
    lining up with line 2's column names, not line 1's. Line 1 appears to be a stale,
    vestigial header CDC never removed (its columns match the SVI 2000 Data Dictionary
    in SVI2000Documentation-H.pdf almost exactly -- an older naming CDC superseded without
    updating the file). `land_raw` skips line 1 (`HEADER_SKIP`) and verifies the real
    line 2 against the declared layout. 2000 has no E_/M_ raw ACS variables at all
    (understandable -- SVI 2000 draws on Census 2000, not a 5-year survey), so no MOE is
    ever published, matching 2010's MOE-less structural concepts in spirit but for every
    variable.

**Real documentation, fetched and read directly 2026-09-19** (neither is linked from the
current download page, but both are still live at their historical `map25` URLs, found via
a general web search rather than the page's own links):
`https://svi.cdc.gov/map25/data/docs/SVI-2010-Documentation-H.pdf` ("SVI 2010
Documentation - 3/31/2015") and
`https://svi.cdc.gov/map25/data/docs/SVI2000Documentation-H.pdf` ("About the Data /
Social Vulnerability Index 2000"). Also fetched: the CDC/ATSDR-published
`Comparison-of-Source-Data-and-Variables.csv`
(https://www.atsdr.cdc.gov/place-health/media/pdfs/2024/Comparison-of-Source-Data-and-Variables.csv),
which tabulates data source (Census vs. ACS) and theme membership per variable per
edition and confirms every composition claim below.

**Three real column contracts (`LAYOUT`/`COUNTY_COLUMNS`), two methodology families
(`FAMILY`).** A layout is what header a real file has; a family is which measure_ids and
theme composition an edition asserts (module code keeps these separate on purpose --
collapsing them loses the fact that 2016/2018 share 2014's methodology but not its exact
header):
  - layout `"2014"` -- county 2014 only (127 columns, includes AFFGEOID and the trailing
    Shape/Shape.STArea()/Shape.STLength(), excluded from the union below).
  - layout `"2016"` -- county 2016, 2018 (verified byte-identical to each other; 2014's
    127 columns minus those same 4).
  - layout `"2020"` -- county 2020, 2022, and **tract 2022** (verified: the 2022 tract
    file's header is byte-identical to the 2020/2022 county header -- same layout,
    different geography grain -- so tract lands via the same code path with no new
    layout to declare; this is why tract landing extends past 2022 trivially but isn't
    wired up for other editions here).
  - family `"2014"` -- editions 2014, 2016, 2018 (layouts "2014" and "2016": identical
    concept columns and theme composition, verified from each real header's column
    order, despite the "2014"-only geometry/AFFGEOID columns).
  - family `"2020"` -- editions 2020, 2022 (layout "2020").
`raw.svi__county` unions all three layouts' columns (the "2020" layout plus the 13
columns unique to "2014": AFFGEOID and the POV/PCI group, since 2020 renamed poverty to
POV150 and dropped PCI from the methodology -- ArcGIS geometry columns excluded, per
SPEC.md's geometry non-goal); `raw.svi__tract` is exactly the "2020" layout.

Two more layouts, `"2000"` and `"2010"`, land into their own dedicated tables instead
(module docstring above) and so double as their own families -- `FAMILY["2000"] ==
"2000"`, `FAMILY["2010"] == "2010"`, each edition its own family, matching #92's
instruction that theme composition differs again from both the 2014 and 2020 families.

**Geography vintage is the edition's own year, not a landed Gazetteer vintage.** Each
edition's own data dictionary states its `AREA_SQMI` column is computed from "Census
Cartographic Boundary File - U.S. Tracts `<edition>` 500K" (SVI2014Documentation,
SVI2016Documentation, SVI2018Documentation, SVI2020Documentation, SVI2022Documentation,
all checked 2026-09-18) -- i.e. SVI documents each edition against its own year's Census
geography, not against the nearest 2010/2020 decennial vintage. Collapsing that into two
buckets is wrong at the edges, confirmed empirically against the real files:
  - **Alaska**: pre-2019 Valdez-Cordova (02261) appears through the 2018 edition; the
    2019 split into Chugach (02063) and Copper River (02066) appears starting with the
    **2020** edition (county count rises 3,142 -> 3,143, +1 net) -- this alone rules out
    treating 2020 as 2010-vintage, since a 2010-vintage file cannot contain a 2019 split.
  - **South Dakota**: the 2015 Shannon -> Oglala Lakota recode (46113 -> 46102) appears
    starting with the **2016** edition; 2014 still carries 46113.
  - **Connecticut**: the legacy 8 counties (09001-09015) persist through the **2020**
    edition; the 9 planning regions (09110-09190) appear starting with **2022** (county
    count rises 3,143 -> 3,144, net +1) -- same pattern as places.py and
    census_gazetteer.py, just landing at a different edition.
  These three changes account for the entire county-count sequence (3,142, 3,142, 3,142,
  3,143, 3,144) and each shows up at a distinct edition, confirming the vintage moves
  edition-by-edition rather than in two 2010/2020 steps. `GEO_VINTAGE` is therefore each
  edition's own year -- `{2014: 2014, 2016: 2016, 2018: 2018, 2020: 2020, 2022: 2022}` --
  for both county and tract (tract 2022 confirmed on the same file: STCNTY carries the
  planning regions there too). `GEO_VINTAGE["2000"] = 2000` and `GEO_VINTAGE["2010"] =
  2010` follow the same rule (each edition its own year) -- **2000 is not one of
  `geography.unit`'s landed vintages (2010/14/16/18/20/22/26)**, so a 2000 SVI row's
  `geo_id`/`geo_vintage` currently has no matching row to join against there. This module
  does not join to geography.unit for any edition (`geo_id`/`geo_vintage` are recorded as
  asserted by the source, per SPEC.md's model, not FK-checked at ingest time), so nothing
  here is *broken* by 2000's absence -- but it is worth flagging rather than silently
  forcing 2000 onto the nearest landed vintage (2010), which would misrepresent which
  boundaries its FIPS codes actually describe.

**Period**: the ACS 5-year window each edition's own documentation states under "Methods
> Variables Used" (svi.cdc.gov/map25/data/docs/SVI<edition>Documentation*.pdf, checked
2026-09-18): 2014 -> "2010-2014 (5-year)"; 2016 -> "2012-2016"; 2018 -> "2014-2018";
2020 -> "2016-2020"; 2022 -> "2018-2022". 2010 -> "2006-2010", per
SVI-2010-Documentation-H.pdf's "Methods > Variables Used": "American Community Survey
(ACS), 2006-2010 (5-year) data" for the ACS-sourced variables. 2000 -> "2000" (a single
year, not a 5-year window): SVI 2000 draws on Census 2000 directly, no ACS involved at
all (SVI2000Documentation-H.pdf). `PERIOD_OVERRIDE` corrects two of 2010's concepts away
from that family default: `age_65_plus` and `minority` are 2010 Census SF1 100%-count
variables in the 2010 edition specifically (unlike every other landed edition, where
both are ACS 5-year estimates), so their true period is the single year 2010, not
2006-2010 -- stated explicitly in the same PDF ("Based on 100% counts - no sampling
error"; "AGE65 ... 2010 SF1"). The RPL_THEME/RPL_THEMES percentile rows for the 2010
family keep the family's ACS window (2006-2010) since the published index itself blends
both sources into one score without attributing a period to the blend.

**Suppression.** -999 is SVI's numeric missing sentinel, published in both raw estimate
(E_/M_) and percent/percentile (EP_/MP_/EPL_/RPL_/SPL_) columns, confirmed present in
every landed edition's real file -> `not_available`, never a number (SPEC.md Acceptance
C). A margin of error can be -999 while its paired estimate is valid (or vice versa) --
each is checked independently; a suppressed EP_ value never derives a lower/upper from a
present MP_, and a present EP_ with a suppressed MP_ still derives `value` with no
interval.

**Derived**: `RPL_THEMES`/`RPL_THEME1-4` (rate_basis='index', method='derived') as
`measure_id = 'SVI:RPL_THEMES:<family>'` / `'SVI:RPL_THEME<n>:<family>'`, family '2000',
'2010', '2014' or '2020' (`FAMILY[edition]`) since theme composition genuinely differs
between all four (see `THEME_DESC`) -- plus the simple E_/EP_/P_ component variables
named in #40: poverty (100% threshold through 2018 (and 2000, 2010) as `SVI:poverty`,
150% threshold from 2020 as `SVI:poverty150` -- CDC's own renamed variable, confirmed
EP_POV -> EP_POV150 in the real files), no HS diploma, no vehicle, age 65+, minority,
limited English -- all five of the latter keep one stable measure_id across all four
families (verified: identical concept meaning in every layout, per
Comparison-of-Source-Data-and-Variables.csv). `SVI:uninsured` is not asserted by the
2000 or 2010 families at all -- neither publishes an uninsured variable (confirmed absent
from both real headers and from the comparison CSV). `interval_level=0.90` (ACS MOE)
where both a percent estimate and its MOE column are present and unsuppressed; 2000
publishes no MOE for anything, and 2010 publishes none for `age_65_plus`/`minority`
(100%-count, module docstring above), so those rows always land with `interval_level`
NULL, `lower`/`upper` NULL, and just a bare `value`.

ponytail: `age_65_plus` and `minority` are true 100%-count Census variables (no sampling
error) in the 2000 and 2010 editions specifically, versus ACS 5-year sample estimates
(`method='survey_direct'`) in every other landed edition -- `measure.definition.method`
still reads `'survey_direct'` for both regardless of which edition wrote it last, since
splitting these two concepts into their own family-suffixed measure_ids just to carry a
more precise `method` felt like more machinery than the nuance is worth (a 100%-count
value is if anything *more* certain than a sampled one, so nothing here overstates
precision the way a wrong period or a suppressed value read as zero would). Upgrade path
if a consumer needs a single method value per source_release: mint `SVI:age_65_plus:2000`/
`:2010` and `SVI:minority:2000`/`:2010` alongside the stable ids.

`measure.definition`/`measure.stratum` writes are scoped to the measure_ids this edition's
family actually asserts (`In("measure_id", ids)`), never wholesale per source -- SPEC.md's
"never replace wholesale per source" rule (issue #76): ingesting the 2020-family after the
2014-family must not delete the 2014-family's own theme definitions, since a 2014
`measure.observation` row's FK still points at them.

ponytail: `PCI` (per capita income, all editions through 2018 including 2000/2010) and
the structural variables this issue doesn't ask for (age17, disability, single-parent,
group quarters, housing type, crowding, race breakdowns added 2020, no-internet) land in
raw but are not derived -- "simple and cancer-relevant" per #40 names the six concepts
above; add more alongside `CONCEPT_COLUMN`/`CONCEPT_LABEL` if a later measure needs them.
"""

import tempfile
import urllib.request
from pathlib import Path

import duckdb
import pyarrow as pa
from pyiceberg.exceptions import NoSuchTableError
from pyiceberg.expressions import And, EqualTo, In

from . import merge

USER_AGENT = "cancerbasemap/1.0 (+https://github.com/seandavi/cancer-basemap)"
BASE = "https://svi.cdc.gov/Documents/Data"

EDITIONS = ("2000", "2010", "2014", "2016", "2018", "2020", "2022")
TRACT_EDITIONS = ("2000", "2010", "2022")

# 2000 and 2010 land into their own per-layout tables, not the shared raw.svi__county /
# raw.svi__tract union (module docstring: real column-name collisions between the two,
# and between each of them and the 2014+ layouts).
EARLY_EDITIONS = ("2000", "2010")

# Editions whose real CSV carries an extra, non-matching header line before the real one
# (module docstring: 2000's line 1 is a stale header CDC never removed) -- number of
# lines `land_raw` skips before the real header/data.
HEADER_SKIP = {"2000": 1}

# Which COUNTY_COLUMNS/TRACT_COLUMNS layout each edition's file uses (module docstring).
# 2016 and 2018 are verified byte-identical to each other but NOT to 2014 -- 2014 alone
# carries AFFGEOID and the trailing Shape/Shape.STArea()/Shape.STLength() columns -- so
# they get their own "2016" layout key, distinct from "2014"'s.
LAYOUT = {"2000": "2000", "2010": "2010", "2014": "2014", "2016": "2016", "2018": "2016",
          "2020": "2020", "2022": "2020"}

# Which measure-definition/theme-composition FAMILY each edition belongs to -- coarser
# than LAYOUT: 2014, 2016 and 2018 use three different raw column *contracts* (LAYOUT)
# but share one *methodology* (identical theme composition and concept columns; module
# docstring), so they share one family and its measure_ids. 2020 and 2022 share the
# other family (and, unlike 2014-vs-2016, also share their raw column contract). 2000 and
# 2010 are each their own family, one edition each (#92, module docstring).
FAMILY = {"2000": "2000", "2010": "2010", "2014": "2014", "2016": "2014", "2018": "2014",
          "2020": "2020", "2022": "2020"}

# Each edition's own year, per its own documentation ("Census Cartographic Boundary
# File - U.S. Tracts <edition> 500K") and confirmed empirically (module docstring: the
# Alaska 02261->02063/02066 split lands at 2020, the Connecticut county->planning-region
# switch lands at 2022, the South Dakota 46113->46102 recode by 2016) -- NOT a landed
# Gazetteer vintage; every edition gets its own real boundary year. Same value for
# county and tract (verified: 2022 tract STCNTY also carries 09110-09190). 2000 and 2010
# follow the same rule; 2000's vintage (2000) is not among geography.unit's landed
# vintages (module docstring) -- recorded as-is, not forced onto a nearby one.
GEO_VINTAGE = {edition: int(edition) for edition in EDITIONS}

# The ACS 5-year window each edition documents under "Methods > Variables Used" in its
# own PDF (module docstring), as (period_start, period_end). 2010 is the family default
# for its ACS-sourced concepts; PERIOD_OVERRIDE below corrects the two that aren't.
ACS_WINDOW = {
    "2000": ("2000", "2000"), "2010": ("2006", "2010"),
    "2014": ("2010", "2014"), "2016": ("2012", "2016"), "2018": ("2014", "2018"),
    "2020": ("2016", "2020"), "2022": ("2018", "2022"),
}

# Per-(family, concept) period override for a concept whose true period differs from its
# family's own ACS_WINDOW default (module docstring: 2010's age_65_plus/minority are 2010
# Census SF1 100%-count, a single year, not the family's 2006-2010 ACS window).
PERIOD_OVERRIDE = {
    ("2010", "age_65_plus"): ("2010", "2010"),
    ("2010", "minority"): ("2010", "2010"),
}

# Which real column each family's tables key geography on -- default "FIPS" (every
# layout except 2000's county file, which has no FIPS column and uses STCNTY, its own
# county-grain identifier, instead; module docstring).
GEO_ID_COLUMN = {"2000": {"county": "STCNTY"}}

# RPL_THEME*/RPL_THEMES column names per family -- default the "RPL_THEME<n>"/
# "RPL_THEMES" spelling (2000, 2014, 2020 families); 2010's real header uses the
# underscored "R_PL_THEME<n>"/"R_PL_THEMES" spelling instead (verified against the real
# file and SVI-2010-Documentation-H.pdf's own data dictionary).
RPL_COLUMN_DEFAULT = {"themes": "RPL_THEMES", 1: "RPL_THEME1", 2: "RPL_THEME2",
                       3: "RPL_THEME3", 4: "RPL_THEME4"}
RPL_COLUMN = {
    "2010": {"themes": "R_PL_THEMES", 1: "R_PL_THEME1", 2: "R_PL_THEME2",
             3: "R_PL_THEME3", 4: "R_PL_THEME4"},
}

COUNTY_COLUMNS = {
    # Real line-2 header (module docstring: line 1 is stale and never landed).
    "2000": (
        "ST", "COU", "STCNTY", "STATE", "ST_ABBR", "COUNTY", "P_POV", "P_UNEMP", "P_PCI",
        "P_NOHSDP", "P_AGE65", "P_AGE17", "P_DISABL", "P_SNGPNT", "P_MINRTY", "P_LIMENG",
        "P_MUNIT", "P_MOBILE", "P_CROWD", "P_NOVEH", "P_GROUPQ", "PL_POV", "PL_UNEMP",
        "PL_PCI", "PL_NOHSDP", "RPL_THEME1", "PL_AGE65", "PL_AGE17", "PL_DISABL",
        "PL_SNGPNT", "RPL_THEME2", "PL_MINRTY", "PL_LIMENG", "RPL_THEME3", "PL_MUNIT",
        "PL_MOBILE", "PL_CROWD", "PL_NOVEH", "PL_GROUPQ", "RPL_THEME4", "RPL_THEMES",
        "F_POV", "F_UNEMP", "F_PCI", "F_NOHSDP", "F_THEME1", "F_AGE65", "F_AGE17",
        "F_DISABL", "F_SNGPNT", "F_THEME2", "F_MINRTY", "F_LIMENG", "F_THEME3", "F_MUNIT",
        "F_MOBILE", "F_CROWD", "F_NOVEH", "F_GROUPQ", "F_THEME4", "F_TOTAL", "TOTPOP", "HU",
        "POV", "UNEMP", "NOHSDP", "AGE65", "AGE17", "DISABL", "SNGPNT", "MINRTY", "LIMENG",
        "MUNIT", "MOBILE", "CROWD", "NOVEH", "GROUPQ",
    ),
    "2010": (
        "ST", "STATE", "FIPS", "LOCATION", "TOTPOP", "E_TOTPOP", "M_TOTPOP", "HU", "E_HU",
        "M_HU", "HH", "E_POV", "M_POV", "E_UNEMP", "M_UNEMP", "E_PCI", "M_PCI", "E_NOHSDIP",
        "M_NOHSDIP", "AGE65", "AGE17", "SNGPRNT", "MINORITY", "E_LIMENG", "M_LIMENG",
        "E_MUNIT", "M_MUNIT", "E_MOBILE", "M_MOBILE", "E_CROWD", "M_CROWD", "E_NOVEH",
        "M_NOVEH", "GROUPQ", "E_P_POV", "M_P_POV", "E_P_UNEMP", "M_P_UNEMP", "E_P_PCI",
        "M_P_PCI", "E_P_NOHSDIP", "M_P_NOHSDIP", "P_AGE65", "P_AGE17", "P_SNGPRNT",
        "P_MINORITY", "E_P_LIMENG", "M_P_LIMENG", "E_P_MUNIT", "M_P_MUNIT", "E_P_MOBILE",
        "M_P_MOBILE", "E_P_CROWD", "M_P_CROWD", "E_P_NOVEH", "M_P_NOVEH", "P_GROUPQ",
        "E_PL_POV", "E_PL_UNEMP", "E_PL_PCI", "E_PL_NOHSDIP", "S_PL_THEME1", "R_PL_THEME1",
        "PL_AGE65", "PL_AGE17", "PL_SNGPRNT", "S_PL_THEME2", "R_PL_THEME2", "PL_MINORITY",
        "E_PL_LIMENG", "S_PL_THEME3", "R_PL_THEME3", "E_PL_MUNIT", "E_PL_MOBILE",
        "E_PL_CROWD", "E_PL_NOVEH", "PL_GROUPQ", "S_PL_THEME4", "R_PL_THEME4",
        "S_PL_THEMES", "R_PL_THEMES", "F_PL_POV", "F_PL_UNEMP", "F_PL_PCI", "F_PL_NOHSDIP",
        "F_PL_THEME1", "F_PL_AGE65", "F_PL_AGE17", "F_PLSNGPRNT", "F_PL_THEME2",
        "F_PL_MINORITY", "F_PL_LIMENG", "F_PL_THEME3", "F_PL_MUNIT", "F_PL_MOBILE",
        "F_PL_CROWD", "F_PL_NOVEH", "F_PL_GROUPQ", "F_PL_THEME4", "F_PL_TOTAL", "Shape",
        "Shape.STArea()", "Shape.STLength()",
    ),
    "2014": (
        "AFFGEOID", "ST", "STATE", "ST_ABBR", "COUNTY", "FIPS", "LOCATION", "AREA_SQMI",
        "E_TOTPOP", "M_TOTPOP", "E_HU", "M_HU", "E_HH", "M_HH", "E_POV", "M_POV",
        "E_UNEMP", "M_UNEMP", "E_PCI", "M_PCI", "E_NOHSDP", "M_NOHSDP", "E_AGE65",
        "M_AGE65", "E_AGE17", "M_AGE17", "E_DISABL", "M_DISABL", "E_SNGPNT", "M_SNGPNT",
        "E_MINRTY", "M_MINRTY", "E_LIMENG", "M_LIMENG", "E_MUNIT", "M_MUNIT", "E_MOBILE",
        "M_MOBILE", "E_CROWD", "M_CROWD", "E_NOVEH", "M_NOVEH", "E_GROUPQ", "M_GROUPQ",
        "EP_POV", "MP_POV", "EP_UNEMP", "MP_UNEMP", "EP_PCI", "MP_PCI", "EP_NOHSDP",
        "MP_NOHSDP", "EP_AGE65", "MP_AGE65", "EP_AGE17", "MP_AGE17", "EP_DISABL",
        "MP_DISABL", "EP_SNGPNT", "MP_SNGPNT", "EP_MINRTY", "MP_MINRTY", "EP_LIMENG",
        "MP_LIMENG", "EP_MUNIT", "MP_MUNIT", "EP_MOBILE", "MP_MOBILE", "EP_CROWD",
        "MP_CROWD", "EP_NOVEH", "MP_NOVEH", "EP_GROUPQ", "MP_GROUPQ", "EPL_POV",
        "EPL_UNEMP", "EPL_PCI", "EPL_NOHSDP", "SPL_THEME1", "RPL_THEME1", "EPL_AGE65",
        "EPL_AGE17", "EPL_DISABL", "EPL_SNGPNT", "SPL_THEME2", "RPL_THEME2", "EPL_MINRTY",
        "EPL_LIMENG", "SPL_THEME3", "RPL_THEME3", "EPL_MUNIT", "EPL_MOBILE", "EPL_CROWD",
        "EPL_NOVEH", "EPL_GROUPQ", "SPL_THEME4", "RPL_THEME4", "SPL_THEMES", "RPL_THEMES",
        "F_POV", "F_UNEMP", "F_PCI", "F_NOHSDP", "F_THEME1", "F_AGE65", "F_AGE17",
        "F_DISABL", "F_SNGPNT", "F_THEME2", "F_MINRTY", "F_LIMENG", "F_THEME3", "F_MUNIT",
        "F_MOBILE", "F_CROWD", "F_NOVEH", "F_GROUPQ", "F_THEME4", "F_TOTAL", "E_UNINSUR",
        "M_UNINSUR", "EP_UNINSUR", "MP_UNINSUR", "E_DAYPOP", "Shape", "Shape.STArea()",
        "Shape.STLength()",
    ),
    "2020": (
        "ST", "STATE", "ST_ABBR", "STCNTY", "COUNTY", "FIPS", "LOCATION", "AREA_SQMI",
        "E_TOTPOP", "M_TOTPOP", "E_HU", "M_HU", "E_HH", "M_HH", "E_POV150", "M_POV150",
        "E_UNEMP", "M_UNEMP", "E_HBURD", "M_HBURD", "E_NOHSDP", "M_NOHSDP", "E_UNINSUR",
        "M_UNINSUR", "E_AGE65", "M_AGE65", "E_AGE17", "M_AGE17", "E_DISABL", "M_DISABL",
        "E_SNGPNT", "M_SNGPNT", "E_LIMENG", "M_LIMENG", "E_MINRTY", "M_MINRTY", "E_MUNIT",
        "M_MUNIT", "E_MOBILE", "M_MOBILE", "E_CROWD", "M_CROWD", "E_NOVEH", "M_NOVEH",
        "E_GROUPQ", "M_GROUPQ", "EP_POV150", "MP_POV150", "EP_UNEMP", "MP_UNEMP",
        "EP_HBURD", "MP_HBURD", "EP_NOHSDP", "MP_NOHSDP", "EP_UNINSUR", "MP_UNINSUR",
        "EP_AGE65", "MP_AGE65", "EP_AGE17", "MP_AGE17", "EP_DISABL", "MP_DISABL",
        "EP_SNGPNT", "MP_SNGPNT", "EP_LIMENG", "MP_LIMENG", "EP_MINRTY", "MP_MINRTY",
        "EP_MUNIT", "MP_MUNIT", "EP_MOBILE", "MP_MOBILE", "EP_CROWD", "MP_CROWD",
        "EP_NOVEH", "MP_NOVEH", "EP_GROUPQ", "MP_GROUPQ", "EPL_POV150", "EPL_UNEMP",
        "EPL_HBURD", "EPL_NOHSDP", "EPL_UNINSUR", "SPL_THEME1", "RPL_THEME1", "EPL_AGE65",
        "EPL_AGE17", "EPL_DISABL", "EPL_SNGPNT", "EPL_LIMENG", "SPL_THEME2", "RPL_THEME2",
        "EPL_MINRTY", "SPL_THEME3", "RPL_THEME3", "EPL_MUNIT", "EPL_MOBILE", "EPL_CROWD",
        "EPL_NOVEH", "EPL_GROUPQ", "SPL_THEME4", "RPL_THEME4", "SPL_THEMES", "RPL_THEMES",
        "F_POV150", "F_UNEMP", "F_HBURD", "F_NOHSDP", "F_UNINSUR", "F_THEME1", "F_AGE65",
        "F_AGE17", "F_DISABL", "F_SNGPNT", "F_LIMENG", "F_THEME2", "F_MINRTY", "F_THEME3",
        "F_MUNIT", "F_MOBILE", "F_CROWD", "F_NOVEH", "F_GROUPQ", "F_THEME4", "F_TOTAL",
        "E_DAYPOP", "E_NOINT", "M_NOINT", "E_AFAM", "M_AFAM", "E_HISP", "M_HISP",
        "E_ASIAN", "M_ASIAN", "E_AIAN", "M_AIAN", "E_NHPI", "M_NHPI", "E_TWOMORE",
        "M_TWOMORE", "E_OTHERRACE", "M_OTHERRACE", "EP_NOINT", "MP_NOINT", "EP_AFAM",
        "MP_AFAM", "EP_HISP", "MP_HISP", "EP_ASIAN", "MP_ASIAN", "EP_AIAN", "MP_AIAN",
        "EP_NHPI", "MP_NHPI", "EP_TWOMORE", "MP_TWOMORE", "EP_OTHERRACE", "MP_OTHERRACE",
    ),
}
# 2016 and 2018's real header (verified byte-identical to each other) is 2014's layout
# minus AFFGEOID and the trailing Shape/Shape.STArea()/Shape.STLength() columns.
_DROP_2014_GEOMETRY = ("AFFGEOID", "Shape", "Shape.STArea()", "Shape.STLength()")
COUNTY_COLUMNS["2016"] = tuple(c for c in COUNTY_COLUMNS["2014"] if c not in _DROP_2014_GEOMETRY)

# The 2022 tract file's header is byte-identical to the 2020/2022 county header
# (verified 2026-09-18) -- same layout, different geography grain. 2000 and 2010's tract
# files are NOT identical to their own county files (module docstring: extra identifying
# columns), so they get their own real headers.
TRACT_COLUMNS = {
    "2020": COUNTY_COLUMNS["2020"],
    "2000": (
        "ST", "COU", "STCNTY", "TRACT", "FIPS", "STATE", "ST_ABBR", "COUNTY",
    ) + COUNTY_COLUMNS["2000"][6:],
    "2010": (
        "GEO_ID", "STATE_FIPS", "CNTY_FIPS", "TRACT", "CENSUSAREA", "STCOFIPS", "FIPS",
        "STATE_ABBR", "STATE_NAME", "COUNTY", "LOCATION", "TOTPOP", "E_TOTPOP", "M_TOTPOP",
        "HU", "E_HU", "M_HU", "HH", "E_POV", "M_POV", "E_UNEMP", "M_UNEMP", "E_PCI",
        "M_PCI", "E_NOHSDIP", "M_NOHSDIP", "AGE65", "AGE17", "SNGPRNT", "MINORITY",
        "E_LIMENG", "M_LIMENG", "E_MUNIT", "M_MUNIT", "E_MOBILE", "M_MOBILE", "E_CROWD",
        "M_CROWD", "E_NOVEH", "M_NOVEH", "GROUPQ", "E_P_POV", "M_P_POV", "E_P_UNEMP",
        "M_P_UNEMP", "E_P_PCI", "M_P_PCI", "E_P_NOHSDIP", "M_P_NOHSDIP", "P_AGE65",
        "P_AGE17", "P_SNGPRNT", "P_MINORITY", "E_P_LIMENG", "M_P_LIMENG", "E_P_MUNIT",
        "M_P_MUNIT", "E_P_MOBILE", "M_P_MOBILE", "E_P_CROWD", "M_P_CROWD", "E_P_NOVEH",
        "M_P_NOVEH", "P_GROUPQ", "E_PL_POV", "E_PL_UNEMP", "E_PL_PCI", "E_PL_NOHSDIP",
        "S_PL_THEME1", "R_PL_THEME1", "PL_AGE65", "PL_AGE17", "PL_SNGPRNT", "S_PL_THEME2",
        "R_PL_THEME2", "PL_MINORITY", "E_PL_LIMENG", "S_PL_THEME3", "R_PL_THEME3",
        "E_PL_MUNIT", "E_PL_MOBILE", "E_PL_CROWD", "E_PL_NOVEH", "PL_GROUPQ", "S_PL_THEME4",
        "R_PL_THEME4", "S_PL_THEMES", "R_PL_THEMES", "F_PL_POV", "F_PL_UNEMP", "F_PL_PCI",
        "F_PL_NOHSDIP", "F_PL_THEME1", "F_PL_AGE65", "F_PL_AGE17", "F_PL_SNGPRNT",
        "F_PL_THEME2", "F_PL_MINORITY", "F_PL_LIMENG", "F_PL_THEME3", "F_PL_MUNIT",
        "F_PL_MOBILE", "F_PL_CROWD", "F_PL_NOVEH", "F_PL_GROUPQ", "F_PL_THEME4",
        "F_PL_TOTAL", "Shape", "Shape.STArea()", "Shape.STLength()",
    ),
    # tract's F_PL_SNGPRNT is correctly spelled where county's F_PLSNGPRNT is not
    # (verified against both real files) -- one more reason these are separate tables.
}

# raw.svi__county's own column order: the "2020" layout plus the columns unique to
# "2014" (module docstring), excluding the ArcGIS geometry byproducts (AFFGEOID is kept
# -- a real, useful identifier, unlike the other three). Missing-in-an-edition columns
# land NULL, same technique as census_gazetteer.py's FULL_COUNTY_COLUMNS.
_COUNTY_2014_ONLY = tuple(c for c in COUNTY_COLUMNS["2014"]
                          if c not in COUNTY_COLUMNS["2020"]
                          and c not in ("Shape", "Shape.STArea()", "Shape.STLength()"))
FULL_COUNTY_COLUMNS = COUNTY_COLUMNS["2020"] + _COUNTY_2014_ONLY
FULL_TRACT_COLUMNS = TRACT_COLUMNS["2020"]

# Per concept, per family: either a bare root variable name (after E_/M_/EP_/MP_, the
# 2014/2020 families' own naming convention) or an explicit (ep_column, mp_column) pair of
# real column names, mp_column NULL if this family/concept has no margin of error at all
# (2000: none published for anything; 2010: none for age_65_plus/minority, both 2010
# Census SF1 100%-count -- module docstring). The six not ending in "150" are identically
# defined across every family that asserts them (verified: same concept meaning per
# Comparison-of-Source-Data-and-Variables.csv); 2000 and 2010 assert five of six --
# neither publishes an uninsured variable at all.
CONCEPT_COLUMN = {
    "2014": {"poverty": "POV", "no_hs_diploma": "NOHSDP", "uninsured": "UNINSUR",
             "no_vehicle": "NOVEH", "age_65_plus": "AGE65", "minority": "MINRTY",
             "limited_english": "LIMENG"},
    "2020": {"poverty150": "POV150", "no_hs_diploma": "NOHSDP", "uninsured": "UNINSUR",
             "no_vehicle": "NOVEH", "age_65_plus": "AGE65", "minority": "MINRTY",
             "limited_english": "LIMENG"},
    "2000": {
        "poverty": ("P_POV", None), "no_hs_diploma": ("P_NOHSDP", None),
        "no_vehicle": ("P_NOVEH", None), "age_65_plus": ("P_AGE65", None),
        "minority": ("P_MINRTY", None), "limited_english": ("P_LIMENG", None),
    },
    "2010": {
        "poverty": ("E_P_POV", "M_P_POV"), "no_hs_diploma": ("E_P_NOHSDIP", "M_P_NOHSDIP"),
        "no_vehicle": ("E_P_NOVEH", "M_P_NOVEH"), "age_65_plus": ("P_AGE65", None),
        "minority": ("P_MINORITY", None),
        "limited_english": ("E_P_LIMENG", "M_P_LIMENG"),
    },
}

# (label, universe) for measure.definition, keyed by concept.
CONCEPT_LABEL = {
    "poverty": ("Persons below the poverty threshold (100% of the federal poverty "
                "level)", "population for whom poverty status is determined"),
    "poverty150": ("Persons below 150% of the federal poverty level",
                   "population for whom poverty status is determined"),
    "no_hs_diploma": ("Persons age 25+ with no high school diploma",
                       "population age 25 and older"),
    "uninsured": ("Civilian noninstitutionalized population with no health insurance",
                  "civilian noninstitutionalized population"),
    "no_vehicle": ("Households with no vehicle available", "occupied housing units"),
    "age_65_plus": ("Persons aged 65 and older", "total population"),
    "minority": ("Minority population (all persons except white, non-Hispanic)",
                 "total population"),
    "limited_english": ('Persons age 5+ who speak English "less than well"',
                        "population age 5 and older"),
}

# Theme composition per family, read directly off each real header's column order
# (module docstring) -- not from CDC's prose, which this module doesn't otherwise parse.
THEME_DESC = {
    "2014": {
        1: "Socioeconomic Status (poverty, unemployment, income, education)",
        2: "Household Composition & Disability (age 65+, age 17 and under, disability, "
           "single-parent households)",
        3: "Minority Status & Language (minority population, limited English)",
        4: "Housing Type & Transportation (multi-unit housing, mobile homes, crowding, "
           "no vehicle, group quarters)",
    },
    "2020": {
        1: "Socioeconomic Status (poverty, unemployment, housing cost burden, education, "
           "uninsured)",
        2: "Household Characteristics (age 65+, age 17 and under, disability, "
           "single-parent households, limited English)",
        3: "Racial & Ethnic Minority Status (minority population)",
        4: "Housing Type & Transportation (multi-unit housing, mobile homes, crowding, "
           "no vehicle, group quarters)",
    },
    "2000": {
        1: "Socioeconomic (poverty, unemployment, per capita income, no high school "
           "diploma)",
        2: "Household Composition/Disability (age 65+, age 17 and under, disability, "
           "single-parent households)",
        3: "Minority Status/Language (minority population, limited English)",
        4: "Housing Type/Transportation (multi-unit housing, mobile homes, crowding, no "
           "vehicle, group quarters)",
    },
    "2010": {
        1: "Socioeconomic (poverty, unemployment, per capita income, no high school "
           "diploma)",
        2: "Household Composition (age 65+, age 17 and under, single-parent households "
           "-- no disability variable in this edition; module docstring)",
        3: "Minority Status/Language (minority population, limited English)",
        4: "Housing Type/Transportation (multi-unit housing, mobile homes, crowding, no "
           "vehicle, group quarters)",
    },
}


def _url(edition, level):
    if level == "county":
        return f"{BASE}/{edition}/csv/states_counties/SVI_{edition}_US_county.csv"
    return f"{BASE}/{edition}/csv/states/SVI_{edition}_US.csv"


def _fetch(url):
    """The file's bytes. A local path (tests) is read directly; a remote URL goes
    through urllib with a descriptive User-Agent."""
    if not url.startswith("http"):
        return Path(url).read_bytes()
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req) as r:
        return r.read()


def _header(raw_bytes, skip=0):
    """The file's real header line, BOM stripped (every real SVI CSV checked carries a
    UTF-8 BOM) and split on comma. `skip` lines are dropped first -- 2000's real files
    carry one stale, non-matching line before the real header (module docstring,
    `HEADER_SKIP`)."""
    line = raw_bytes.split(b"\n")[skip].rstrip(b"\r")
    return tuple(line.decode("utf-8-sig").split(","))


def land_raw(cat, release, edition=None, level="county", url=None):
    """Phase 1: one edition's county or tract file, verbatim and whole, replaced per
    (edition, level)."""
    edition = edition or max(EDITIONS, key=int)
    if edition not in EDITIONS:
        raise SystemExit(f"cdc_svi: no known layout for edition {edition!r}; "
                         f"landed editions: {sorted(EDITIONS, key=int)}")
    if level == "tract" and edition not in TRACT_EDITIONS:
        raise SystemExit(f"cdc_svi: tract is only landed for {TRACT_EDITIONS}; "
                         f"{edition!r} is not one of them")
    layout = LAYOUT[edition]
    columns = (COUNTY_COLUMNS if level == "county" else TRACT_COLUMNS)[layout]
    if edition in EARLY_EDITIONS:
        # Dedicated per-layout table (module docstring): landed exactly as its own real
        # columns, no union/NULL-padding needed.
        full_columns = columns
        identifier = f"raw.svi__{level}_{edition}"
    else:
        full_columns = FULL_COUNTY_COLUMNS if level == "county" else FULL_TRACT_COLUMNS
        identifier = f"raw.svi__{level}"
    skip = HEADER_SKIP.get(edition, 0)

    url = url or _url(edition, level)
    raw_bytes = _fetch(url)
    if (header := _header(raw_bytes, skip)) != columns:
        raise SystemExit(f"cdc_svi: {url} header is not the declared {layout!r} layout; "
                         f"differs in {sorted(set(header) ^ set(columns))}")

    with tempfile.NamedTemporaryFile(suffix=".csv") as tmp:
        tmp.write(raw_bytes)
        tmp.flush()
        # raw.svi__county's schema is the union of every layout landed (module
        # docstring); a column this edition's own layout doesn't have lands NULL, same
        # technique as census_gazetteer.py's _land_file. The three ArcGIS geometry
        # columns (2014 only) are deliberately never selected, even though the real file
        # has them -- excluded from the union entirely, not just NULLed. 2000/2010 select
        # every one of their own columns verbatim (full_columns == columns above).
        select = ", ".join(f'"{c}"' if c in columns else f'NULL::VARCHAR AS "{c}"'
                           for c in full_columns)
        con = duckdb.connect()
        # Dialect stated, not sniffed: comma-delimited, double-quoted where a cell needs
        # it (LOCATION contains a comma, e.g. "Autauga County, Alabama"). all_varchar
        # keeps raw unparsed and -999 landed as text, not silently cast to a number.
        # `skip` drops 2000's stale first header line (module docstring) before DuckDB
        # reads the next line as the real header.
        arrow = con.sql(f"""
            SELECT {select}, '{edition}' AS svi_edition, '{release}' AS landed_in
            FROM read_csv('{tmp.name}', header=true, all_varchar=true, delim=',',
                          quote='"', escape='"', nullstr='', skip={skip})
        """).to_arrow_table()
    if not arrow.num_rows:
        raise SystemExit(f"cdc_svi: {url} yielded no rows")

    n = merge.write(cat, identifier, arrow, EqualTo("svi_edition", edition))
    merge.manifest(cat, release, f"svi_{level}", url, n, version=edition,
                   method="release_number")
    return edition, n


def _concept_select(level, geo_vintage, family):
    """One level's rows, columns aliased to family-neutral names (geo_id/geo_vintage plus
    TRY_CAST'd rpl_theme*/ep_*/mp_* for this family's concepts) so the rest of `transform`
    doesn't need to know which family produced them, or whether it publishes a margin of
    error at all.

    A `CONCEPT_COLUMN[family]` value is either a bare root string (2014/2020: the real
    columns are `EP_{root}`/`MP_{root}`) or an explicit (ep_column, mp_column) pair of
    real column names (2000/2010: their real naming doesn't follow that pattern; module
    docstring) -- mp_column NULL where this family/concept has no margin of error at all,
    in which case mp_{c} below is a literal SQL NULL, never a suppressed/missing value.
    """
    concepts = CONCEPT_COLUMN[family]
    parts = []
    for c, spec in concepts.items():
        ep_col, mp_col = spec if isinstance(spec, tuple) else (f"EP_{spec}", f"MP_{spec}")
        parts.append(f'TRY_CAST("{ep_col}" AS DOUBLE) AS ep_{c}')
        parts.append(f'TRY_CAST("{mp_col}" AS DOUBLE) AS mp_{c}' if mp_col
                     else f'NULL::DOUBLE AS mp_{c}')
    concept_cols = ", ".join(parts)

    rpl = RPL_COLUMN.get(family, RPL_COLUMN_DEFAULT)
    id_col = GEO_ID_COLUMN.get(family, {}).get(level, "FIPS")
    return f"""
        SELECT '{level}:' || "{id_col}" AS geo_id, {geo_vintage} AS geo_vintage,
               TRY_CAST("{rpl['themes']}" AS DOUBLE) AS rpl_themes,
               TRY_CAST("{rpl[1]}" AS DOUBLE) AS rpl_theme1,
               TRY_CAST("{rpl[2]}" AS DOUBLE) AS rpl_theme2,
               TRY_CAST("{rpl[3]}" AS DOUBLE) AS rpl_theme3,
               TRY_CAST("{rpl[4]}" AS DOUBLE) AS rpl_theme4,
               {concept_cols}
        FROM {level}_raw
    """


def _has_moe(family, concept):
    """Whether this family publishes a margin of error for this concept -- true for
    every 2014/2020-family concept (bare root string, always ACS) and for a (ep, mp)
    pair whose mp is not None; false for a (ep, None) pair (module docstring: 2000
    publishes none at all, 2010 publishes none for age_65_plus/minority specifically).
    Used only to word measure.definition.doc accurately (ACS vs Census)."""
    spec = CONCEPT_COLUMN[family][concept]
    return not isinstance(spec, tuple) or spec[1] is not None


def transform(cat, release, edition):
    """Phase 2: measure.definition / measure.stratum / measure.observation for one
    edition, from whichever of raw.svi__county / raw.svi__tract are landed for it.

    Rebuilding from raw every time (rather than only the level just landed) is what
    keeps this idempotent and safe to call after landing either level alone: measure.
    observation's merge scope is (source, source_release) -- not per-level -- so a
    tract-only re-derive would otherwise retire the county rows landed earlier for the
    same edition, and vice versa (merge.merge's `incoming` must be the complete state
    within its scope).
    """
    family = FAMILY[edition]
    geo_vintage = GEO_VINTAGE[edition]
    period_start, period_end = ACS_WINDOW[edition]
    con = duckdb.connect()

    # 2000/2010 read from their own dedicated tables (module docstring); every other
    # edition still shares the raw.svi__county/raw.svi__tract union.
    county_id = f"raw.svi__county_{edition}" if edition in EARLY_EDITIONS else "raw.svi__county"
    tract_id = f"raw.svi__tract_{edition}" if edition in EARLY_EDITIONS else "raw.svi__tract"

    # Try both levels' raw tables rather than assuming county always exists: the shared
    # raw.svi__county/raw.svi__tract union table is usually created already (some other
    # edition landed county first), but 2000/2010's dedicated per-edition tables
    # (EARLY_EDITIONS) have no such cross-edition table to ride on -- a tract-only
    # ingest as the very first call for an edition finds no county table at all yet.
    wanted_levels = ("county", "tract") if edition in TRACT_EDITIONS else ("county",)
    levels = []
    for lvl, table_id in zip(wanted_levels, (county_id, tract_id)):
        try:
            con.register(f"{lvl}_raw", cat.load_table(table_id).scan(
                row_filter=EqualTo("svi_edition", edition)).to_arrow())
            levels.append(_concept_select(lvl, geo_vintage, family))
        except NoSuchTableError:
            pass  # this level not landed yet for this edition; the other is still valid
    if not levels:
        raise SystemExit(f"cdc_svi: no raw.svi__{{county,tract}} table landed yet for "
                         f"edition {edition!r}; land at least one level first")
    con.execute(f"CREATE OR REPLACE TABLE combined AS {' UNION ALL '.join(levels)}")

    concepts = CONCEPT_COLUMN[family]
    theme_desc = THEME_DESC[family]

    definition = pa.Table.from_pylist(
        [dict(measure_id=f"SVI:RPL_THEMES:{family}", source="SVI",
              label="Overall SVI percentile ranking", units="percentile (0-1)",
              universe=None, rate_basis="index", age_adjustment=None, method="derived",
              cancer_site_code=None,
              doc=f"Overall SVI vulnerability percentile ranking across all four themes, "
                  f"{family}-family methodology (editions in this family: "
                  f"{[e for e, fam in FAMILY.items() if fam == family]}).")] +
        [dict(measure_id=f"SVI:RPL_THEME{n}:{family}", source="SVI",
              label=f"Theme {n} percentile ranking", units="percentile (0-1)",
              universe=None, rate_basis="index", age_adjustment=None, method="derived",
              cancer_site_code=None,
              doc=f"Theme {n} vulnerability percentile ranking: {theme_desc[n]}.")
         for n in (1, 2, 3, 4)] +
        [dict(measure_id=f"SVI:{c}", source="SVI", label=CONCEPT_LABEL[c][0],
              units="percent", universe=CONCEPT_LABEL[c][1], rate_basis="percent",
              age_adjustment=None, method="survey_direct", cancer_site_code=None,
              doc=f"{CONCEPT_LABEL[c][0]}, as a percent of {CONCEPT_LABEL[c][1]} "
                  f"({'ACS' if _has_moe(family, c) else 'Census'} estimate).")
         for c in concepts]
    )
    def_ids = definition.column("measure_id").to_pylist()

    stratum = pa.Table.from_pylist([dict(
        stratum_id="SVI:ALL", source="SVI", sex=None, age_group=None, race_ethnicity=None,
        stage=None, other=None, scheme="SVI_TOTAL",
    )])

    theme_obs = " UNION ALL ".join(f"""
        SELECT 'SVI' AS source, '{edition}' AS source_release,
               'SVI:RPL_THEME{suffix}:{family}' AS measure_id, geo_id, geo_vintage,
               '{period_start}' AS period_start, '{period_end}' AS period_end,
               'SVI:ALL' AS stratum_id,
               CASE WHEN {col} = -999 THEN NULL ELSE {col} END AS value,
               NULL::DOUBLE AS lower, NULL::DOUBLE AS upper, NULL::DOUBLE AS interval_level,
               NULL::DOUBLE AS numerator, NULL::DOUBLE AS denominator,
               CASE WHEN {col} = -999 THEN 'not_available' ELSE 'reported' END AS value_status,
               NULL::VARCHAR AS reliability_flag, NULL::VARCHAR AS trend
        FROM combined
    """ for suffix, col in [("S", "rpl_themes")] + [(n, f"rpl_theme{n}") for n in (1, 2, 3, 4)])

    # Per-concept period: the family's own ACS_WINDOW, unless PERIOD_OVERRIDE names a
    # different true period for this (family, concept) pair (module docstring: 2010's
    # age_65_plus/minority are single-year 2010 Census SF1, not the family's 2006-2010
    # ACS window).
    concept_obs = " UNION ALL ".join(f"""
        SELECT 'SVI' AS source, '{edition}' AS source_release, 'SVI:{c}' AS measure_id,
               geo_id, geo_vintage, '{c_start}' AS period_start,
               '{c_end}' AS period_end, 'SVI:ALL' AS stratum_id,
               CASE WHEN ep_{c} = -999 THEN NULL ELSE ep_{c} END AS value,
               CASE WHEN ep_{c} = -999 OR mp_{c} IS NULL OR mp_{c} = -999 THEN NULL
                    ELSE ep_{c} - mp_{c} END AS lower,
               CASE WHEN ep_{c} = -999 OR mp_{c} IS NULL OR mp_{c} = -999 THEN NULL
                    ELSE ep_{c} + mp_{c} END AS upper,
               CASE WHEN ep_{c} = -999 OR mp_{c} IS NULL OR mp_{c} = -999 THEN NULL
                    ELSE 0.90 END AS interval_level,
               NULL::DOUBLE AS numerator, NULL::DOUBLE AS denominator,
               CASE WHEN ep_{c} = -999 THEN 'not_available' ELSE 'reported' END AS value_status,
               NULL::VARCHAR AS reliability_flag, NULL::VARCHAR AS trend
        FROM combined
    """ for c in concepts
          for c_start, c_end in [PERIOD_OVERRIDE.get((family, c), (period_start, period_end))])

    observation = con.sql(f"{theme_obs} UNION ALL {concept_obs}").to_arrow_table()
    merge.check_observations(observation)

    scope = EqualTo("source", "SVI")
    return {
        "measure.definition": merge.write(cat, "measure.definition", definition,
                                          And(scope, In("measure_id", def_ids))),
        "measure.stratum": merge.write(cat, "measure.stratum", stratum,
                                       And(scope, In("stratum_id", ["SVI:ALL"]))),
        "measure.observation": merge.merge(
            cat, "measure.observation", observation, release,
            And(scope, EqualTo("source_release", edition))),
    }


def ingest(cat, release, edition=None, level="county", url=None):
    edition, n = land_raw(cat, release, edition, level, url)
    raw_key = f"raw.svi__{level}_{edition}" if edition in EARLY_EDITIONS else f"raw.svi__{level}"
    return {raw_key: n, **transform(cat, release, edition)}
