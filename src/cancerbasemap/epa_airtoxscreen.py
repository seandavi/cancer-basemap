"""EPA AirToxScreen: modeled lifetime cancer risk from ambient air toxics -> Iceberg,
tract level.

Upstream: https://www.epa.gov/AirToxScreen -- assessment-results pages by year
(`/AirToxScreen/<year>-airtoxscreen-assessment-results`), each linking a "National
Cancer Risk by Source Group" and "National Cancer Risk by Pollutant" national xlsx
(SPEC.md § Sources — second tranche companion, issue #98: "modeled lifetime cancer
risk per million from ambient air toxics, by census tract").

**Licence.** Public domain. EPA's own Standard Open Data License
(https://edg.epa.gov/epa_data_license.html, checked 2026-09-19) states verbatim:
"Unless otherwise specified, all data produced by the U.S EPA is by default in the
public domain and is not subject to domestic copyright protection under 17 U.S.C.
Sec 105." No registration or attribution is required to redistribute (same basis
`epa_sdwis.py` already uses for this publisher).

**EPA's own caveat** (`https://www.epa.gov/AirToxScreen/airtoxscreen-overview`,
checked 2026-09-19), carried into every derived measure's `doc`: "AirToxScreen
can't give precise exposures and risks for a specific person." "Results for
smaller areas, such as a census tract or census block, are best used to guide
follow-up local studies." "You should use caution when comparing assessments for
different years" -- SPEC.md's own versioning model already treats each assessment
year as a separate measure family for the same reason (`source_release` = the
assessment year; never pooled across years).

**Version axis: the assessment year is `source_release`.** `YEARS` records every
year this module lands (module scope below); each is its own pair of national
xlsx files, not one URL with a rolling version.

**Years landed: 2018 and 2019 only.** Verified 2026-09-19 by downloading the real
2017, 2018, 2019 and 2020 pages/files directly:
  - **2018 and 2019 share one real header**, byte-for-byte identical on both the
    source-group file (45 columns) and the pollutant file (79 columns) -- one
    `SRCGRP_COLUMNS`/`POLL_COLUMNS` contract covers both years.
  - **2017 is excluded**: its real header is a genuinely different layout, not a
    scrape artifact -- `FIPs` (lowercase `s`) where 2018/2019 have `FIPS`; the
    total-risk column is named `'Total Risk\\n (in a million)'` (with a literal
    embedded newline) rather than `'Total Cancer Risk (per million)'`; it is
    missing the `BENZOAPYRENE` pollutant column 2018/2019 carry; and its
    `1,2-Diphenylhydrazine` column is differently cased than 2019's
    `1,2-DIPHENYLHYDRAZINE`. A third real `SRCGRP_COLUMNS`/`POLL_COLUMNS` layout
    is more machinery than this PR's scope; not landed here, tracked as a
    follow-up (reported on the issue).
  - **2020 onward is excluded**: EPA's own 2020 assessment-results page states
    results move to **census block** grain ("Block-level cancer risk by region and
    source group" / "...by region and pollutant"), distributed as per-EPA-region
    files under `gaftp.epa.gov/rtrmodeling_public/AirToxScreen/2020/Cancer/`, not
    one national tract file -- a different geography level entirely (census block
    is not even in `geography.unit`'s level enum, SPEC.md § Geography) and a
    different download shape. Out of scope; a block-level source would be its own
    module and its own SPEC.md discussion, not an extension of this one.
  - **Pre-2017 (predecessor NATA, 1996-2014)** is a different program/branding
    with its own file formats (issue #98's own text: "Access downloads") -- not
    verified, out of scope.

**Geography vintage: 2010-vintage tracts, both landed years** (`GEO_VINTAGE`).
Verified directly against the real 2018 and 2019 files, the same two markers
`cdc_svi.py`/`places.py` use: Alaska's pre-2019-split Valdez-Cordova (FIPS 02261)
is present (not its post-2019 Chugach/Copper River split), and Connecticut carries
its eight legacy counties (09001-09015), not the nine planning regions that
appear starting with the 2022-vintage sources elsewhere in this lake. Both years'
real tract row count is 73,449, confirming neither is a partial update. (2020's
switch to census block grain -- not landed here -- would also have been a tract
*vintage* discontinuity had it stayed at tract grain; moot since it's out of
scope for the grain reason above.)

**File shape: national, state, county AND tract rows share one file.** Each xlsx
carries one national-total row (`FIPS='00000'`), one row per state
(`FIPS='<2-digit state>000'`), one county-aggregate row per county (`Tract` =
the county's own `FIPS` + `'000000'`) -- and the real per-tract rows this issue
asks for (`Tract` an 11-digit code NOT ending `'000000'`; a real census tract
number is never coded all-zero). `land_raw` lands every row verbatim (ADR-0002:
land raw whole); `transform` derives only the real tract rows
(`tract NOT LIKE '%000000'`), matching the issue's "by census tract" scope.

**No suppression at all.** Checked directly against both real files (every
column of `total_cancer_risk` and the three derived pollutants): zero NULLs,
zero non-numeric cells, in ~76,700 rows each. AirToxScreen publishes a modeled
value for every unit; unlike `cdc_svi.py`/`places.py` there is no sentinel to
detect, so every derived row is `value_status = 'reported'`.

**`total_cancer_risk` is published pre-rounded to a small set of risk bins**
(5, 6, 7, 8, 9, 10, 20, 30, ..., 100, 200, 300, 400 -- the complete set found in
the real 2019 file), not a continuous value. That is EPA's own publication
convention (it appears identically in both the source-group and pollutant
files for the same tract, verified), not a landing defect -- documented on the
column, not silently smoothed over.

**Two raw tables, landed and required together.** `raw.airtoxscreen__tract_risk`
(the source-group file) and `raw.airtoxscreen__tract_risk_pollutant` (the
pollutant file) describe the *same* geography and year from two angles, unlike
`cdc_svi.py`/`places.py`'s county/tract levels (which are independently useful
partial state). `transform` requires both to be landed for a year before
deriving anything -- there is no useful partial derive here, so it does not
carry that union-of-whichever-is-landed machinery.

**Derived: four measures per year**, `source='AIRTOXSCREEN'`, `method='model_based'`,
`rate_basis='per_1000000'` (SPEC.md's rate_basis enum gains this value in this PR;
edited in the same commit per AGENTS.md):
  - `AIRTOXSCREEN:total_cancer_risk`, from the source-group file's own
    `total_cancer_risk` column (identical in the pollutant file too, verified;
    read from the source-group table to avoid picking one arbitrarily).
  - `AIRTOXSCREEN:benzene`, `AIRTOXSCREEN:formaldehyde`, `AIRTOXSCREEN:ethylene_oxide`
    -- the three pollutants issue #98 names by name, from the pollutant file.

ponytail: the other 38 source-group columns and 69 other pollutant columns land
in raw (full width, every column documented -- SPEC.md ADR-0003) but are not
derived into measure.observation. Add more alongside `SRCGRP_CANON`/`POLL_CANON`
below if a later measure needs them; this PR's scope is the flagship total risk
plus the three pollutants the issue itself names.

`measure.observation`'s merge scope is `(source, source_release)` -- unlike
`cdc_svi.py`/`places.py`, this module's measure_id set never varies by year (it
is always the same four ids), so `measure.definition`/`measure.stratum` are
overwritten wholesale per `source = 'AIRTOXSCREEN'` (`ers_ruca.py`'s simpler
pattern), not scoped to an `In(...)` id list -- there is no #76 risk here since
no year ever asserts a different id set.
"""

import tempfile
import urllib.request
from pathlib import Path

import duckdb
import pyarrow as pa
from pyiceberg.exceptions import NoSuchTableError
from pyiceberg.expressions import And, EqualTo

from . import merge

USER_AGENT = "cancerbasemap/1.0 (+https://github.com/seandavi/cancer-basemap)"

YEARS = ("2018", "2019")

# Both landed years are 2010-vintage census tracts (module docstring: verified via
# Alaska's pre-2019 Valdez-Cordova FIPS and Connecticut's eight legacy counties,
# both real files).
GEO_VINTAGE = {"2018": 2010, "2019": 2010}

# National download URLs, found on each year's own
# epa.gov/AirToxScreen/<year>-airtoxscreen-assessment-results page, checked
# 2026-09-19. No predictable pattern across years (EPA's own file-naming and
# upload-date paths vary) -- one explicit id per (year, kind), same approach as
# `places.py`'s RELEASES / `ers_ruca.py`'s EDITIONS.
SRCGRP_URLS = {
    "2018": "https://www.epa.gov/system/files/documents/2022-12/2018_National_CancerRisk_by_tract_srcgrp.xlsx",
    "2019": "https://www.epa.gov/system/files/documents/2022-12/2019_National_CancerRisk_by_tract_srcgrp.xlsx",
}
POLLUTANT_URLS = {
    "2018": "https://www.epa.gov/system/files/documents/2022-08/2018%20National_CancerRisk_by_tract_poll.xlsx",
    "2019": "https://www.epa.gov/system/files/documents/2022-12/2019_National_CancerRisk_by_tract_poll.xlsx",
}

# The real 2018/2019 source-group file's header, in file order -- verified
# 2026-09-19 by downloading both files. 2017's real header differs (module
# docstring) and is not supported by this contract.
SRCGRP_COLUMNS = (
    'State', 'EPA Region', 'County', 'FIPS', 'Tract', 'Population',
    'Total Cancer Risk (per million)', 'PT-StationaryPoint Cancer Risk (per million)',
    'OR-LightDuty-OffNetwork-Gas Cancer Risk (per million)',
    'OR-LightDuty-OffNetwork-Diesel Cancer Risk (per million)',
    'OR-HeavyDuty-OffNetwork-Gas Cancer Risk (per million)',
    'OR-HeavyDuty-OffNetwork-Diesel Cancer Risk (per million)',
    'OR-LightDuty-OnNetwork-Gas Cancer Risk (per million)',
    'OR-LightDuty-OnNetwork-Diesel Cancer Risk (per million)',
    'OR-HeavyDuty-OnNetwork-Gas Cancer Risk (per million)',
    'OR-HeavyDuty-OnNetwork-Diesel Cancer Risk (per million)',
    'OR-Refueling Cancer Risk (per million)',
    'OR-HeavyDuty-Hoteling Cancer Risk (per million)',
    'NR-Recreational-inc-PleasureCraft Cancer Risk (per million)',
    'NR-Construction Cancer Risk (per million)',
    'NR-CommercialLawnGarden Cancer Risk (per million)',
    'NR-ResidentialLawnGarden Cancer Risk (per million)',
    'NR-Agriculture Cancer Risk (per million)',
    'NR-CommercialEquipment Cancer Risk (per million)',
    'NR-AllOther Cancer Risk (per million)', 'NR-CMV_C1C2_ports Cancer Risk (per million)',
    'NR-CMV_C3_ports Cancer Risk (per million)',
    'NR-CMV_C1C2C3_underway Cancer Risk (per million)',
    'NR-Locomotives Cancer Risk (per million)', 'NR-Point-Airports Cancer Risk (per million)',
    'NR- Point-Railyards Cancer Risk (per million)', 'NP-industrial Cancer Risk (per million)',
    'NP-CommercialCooking Cancer Risk (per million)', 'NP-OilGas Cancer Risk (per million)',
    'NP-SolventsCoatings Cancer Risk (per million)',
    'NP-StorageTransfer_BulkTerminals_GasStage1 Cancer Risk (per million)',
    'NP-MiscellaneousNonindustrial Cancer Risk (per million)',
    'NP-FuelCombustion_not_RWC Cancer Risk (per million)',
    'NP-ResidentialWoodCombustionRWC Cancer Risk (per million)',
    'NP-WasteDisposal Cancer Risk (per million)',
    'NP-AgricultureLivestock Cancer Risk (per million)', 'FIRE Cancer Risk (per million)',
    'BIOGENICS Cancer Risk (per million)', 'SECONDARY Cancer Risk (per million)',
    'BACKGROUND Cancer Risk (per million)',
)

# The real 2018/2019 pollutant file's header, in file order -- verified 2026-09-19.
POLL_COLUMNS = (
    'State', 'EPA Region', 'County', 'FIPS', 'Tract', 'Population',
    'Total Cancer Risk (per million)', '1,1,2-TRICHLOROETHANE', '1,2-DIBROMO-3-CHLOROPROPANE',
    '1,2-DIPHENYLHYDRAZINE', '1,2,3,4,5,6-HEXACHLOROCYCLYHEXANE', '1,3-BUTADIENE',
    '1,3-DICHLOROPROPENE', '1,3-PROPANE SULTONE', '1,4-DICHLOROBENZENE',
    '2-ACETYLAMINOFLUORENE', '2-NITROPROPANE', '2,4-DINITROTOLUENE',
    '2,4-TOLUENE DIISOCYANATE', '2,4,6-TRICHLOROPHENOL', "3,3'-DICHLOROBENZIDINE",
    '4-DIMETHYLAMINOAZOBENZENE', "4,4'-METHYLENE BIS(2-CHLOROANILINE)",
    "4,4'-METHYLENEDIANILINE", 'ACETALDEHYDE', 'ACETAMIDE', 'ACRYLAMIDE', 'ACRYLONITRILE',
    'ALLYL CHLORIDE', 'ANILINE', 'ARSENIC COMPOUNDS(INORGANIC INCLUDING ARSINE)',
    'BENZOAPYRENE', 'BENZENE', 'BENZIDINE', 'BENZYL CHLORIDE', 'BERYLLIUM COMPOUNDS',
    'BIS(2-ETHYLHEXYL)PHTHALATE (DEHP)', 'BIS(CHLOROMETHYL) ETHER', 'BROMOFORM',
    'CHROMIUM VI (HEXAVALENT)', 'CADMIUM COMPOUNDS', 'CARBON TETRACHLORIDE', 'CHLORDANE',
    'CHLOROBENZILATE', 'CHLOROPRENE', 'COKE OVEN EMISSIONS',
    'DICHLOROETHYL ETHER (BIS[2-CHLOROETHYL]ETHER)', 'EPICHLOROHYDRIN', 'ETHYLBENZENE',
    'ETHYL CARBAMATE (URETHANE) CHLORIDE (CHLOROETHANE)', 'ETHYLENE DIBROMIDE (DIBROMOETHANE)',
    'ETHYLENE DICHLORIDE (1,2-DICHLOROETHANE)', 'ETHYLENE OXIDE', 'ETHYLENE THIOUREA',
    'ETHYLIDENE DICHLORIDE (1,1-DICHLOROETHANE)', 'FORMALDEHYDE', 'HEPTACHLOR',
    'HEXACHLOROBENZENE', 'HEXACHLOROBUTADIENE', 'HYDRAZINE', 'METHYL TERT-BUTYL ETHER',
    'METHYLENE CHLORIDE', 'N-NITROSODIMETHYLAMINE', 'N-NITROSOMORPHOLINE', 'NICKEL COMPOUNDS',
    'NAPHTHALENE', 'NITROBENZENE', 'POLYCHLORINATED BIPHENYLS (AROCLORS)', 'PENTACHLOROPHENOL',
    'PROPYLENE OXIDE', 'TETRACHLOROETHYLENE', '2,4-TOLUENE DIAMINE',
    'TOXAPHENE (CHLORINATED CAMPHENE)', 'TRICHLOROETHYLENE', 'VINYL BROMIDE', 'VINYL CHLORIDE',
    'O-TOLUIDINE', '1,4-DIOXANE', 'PAHPOM',
)

# (original header, canonical raw column name) -- the physical raw column names
# are sanitized snake_case (this is the first source in the lake whose real
# headers carry spaces/parens/hyphens); the original text is preserved verbatim
# in each column's `doc` in schemas.py. Shared by both files' first 7 columns.
_CORE = (
    ('State', 'state'), ('EPA Region', 'epa_region'), ('County', 'county'),
    ('FIPS', 'fips'), ('Tract', 'tract'), ('Population', 'population'),
    ('Total Cancer Risk (per million)', 'total_cancer_risk'),
)

SRCGRP_CANON = _CORE + (
    ('PT-StationaryPoint Cancer Risk (per million)', 'pt_stationarypoint'),
    ('OR-LightDuty-OffNetwork-Gas Cancer Risk (per million)', 'or_lightduty_offnetwork_gas'),
    ('OR-LightDuty-OffNetwork-Diesel Cancer Risk (per million)', 'or_lightduty_offnetwork_diesel'),
    ('OR-HeavyDuty-OffNetwork-Gas Cancer Risk (per million)', 'or_heavyduty_offnetwork_gas'),
    ('OR-HeavyDuty-OffNetwork-Diesel Cancer Risk (per million)', 'or_heavyduty_offnetwork_diesel'),
    ('OR-LightDuty-OnNetwork-Gas Cancer Risk (per million)', 'or_lightduty_onnetwork_gas'),
    ('OR-LightDuty-OnNetwork-Diesel Cancer Risk (per million)', 'or_lightduty_onnetwork_diesel'),
    ('OR-HeavyDuty-OnNetwork-Gas Cancer Risk (per million)', 'or_heavyduty_onnetwork_gas'),
    ('OR-HeavyDuty-OnNetwork-Diesel Cancer Risk (per million)', 'or_heavyduty_onnetwork_diesel'),
    ('OR-Refueling Cancer Risk (per million)', 'or_refueling'),
    ('OR-HeavyDuty-Hoteling Cancer Risk (per million)', 'or_heavyduty_hoteling'),
    ('NR-Recreational-inc-PleasureCraft Cancer Risk (per million)', 'nr_recreational_inc_pleasurecraft'),
    ('NR-Construction Cancer Risk (per million)', 'nr_construction'),
    ('NR-CommercialLawnGarden Cancer Risk (per million)', 'nr_commerciallawngarden'),
    ('NR-ResidentialLawnGarden Cancer Risk (per million)', 'nr_residentiallawngarden'),
    ('NR-Agriculture Cancer Risk (per million)', 'nr_agriculture'),
    ('NR-CommercialEquipment Cancer Risk (per million)', 'nr_commercialequipment'),
    ('NR-AllOther Cancer Risk (per million)', 'nr_allother'),
    ('NR-CMV_C1C2_ports Cancer Risk (per million)', 'nr_cmv_c1c2_ports'),
    ('NR-CMV_C3_ports Cancer Risk (per million)', 'nr_cmv_c3_ports'),
    ('NR-CMV_C1C2C3_underway Cancer Risk (per million)', 'nr_cmv_c1c2c3_underway'),
    ('NR-Locomotives Cancer Risk (per million)', 'nr_locomotives'),
    ('NR-Point-Airports Cancer Risk (per million)', 'nr_point_airports'),
    ('NR- Point-Railyards Cancer Risk (per million)', 'nr_point_railyards'),
    ('NP-industrial Cancer Risk (per million)', 'np_industrial'),
    ('NP-CommercialCooking Cancer Risk (per million)', 'np_commercialcooking'),
    ('NP-OilGas Cancer Risk (per million)', 'np_oilgas'),
    ('NP-SolventsCoatings Cancer Risk (per million)', 'np_solventscoatings'),
    ('NP-StorageTransfer_BulkTerminals_GasStage1 Cancer Risk (per million)', 'np_storagetransfer_bulkterminals_gasstage1'),
    ('NP-MiscellaneousNonindustrial Cancer Risk (per million)', 'np_miscellaneousnonindustrial'),
    ('NP-FuelCombustion_not_RWC Cancer Risk (per million)', 'np_fuelcombustion_not_rwc'),
    ('NP-ResidentialWoodCombustionRWC Cancer Risk (per million)', 'np_residentialwoodcombustionrwc'),
    ('NP-WasteDisposal Cancer Risk (per million)', 'np_wastedisposal'),
    ('NP-AgricultureLivestock Cancer Risk (per million)', 'np_agriculturelivestock'),
    ('FIRE Cancer Risk (per million)', 'fire'),
    ('BIOGENICS Cancer Risk (per million)', 'biogenics'),
    ('SECONDARY Cancer Risk (per million)', 'secondary'),
    ('BACKGROUND Cancer Risk (per million)', 'background'),
)

POLL_CANON = _CORE + (
    ('1,1,2-TRICHLOROETHANE', '1_1_2_trichloroethane'),
    ('1,2-DIBROMO-3-CHLOROPROPANE', '1_2_dibromo_3_chloropropane'),
    ('1,2-DIPHENYLHYDRAZINE', '1_2_diphenylhydrazine'),
    ('1,2,3,4,5,6-HEXACHLOROCYCLYHEXANE', '1_2_3_4_5_6_hexachlorocyclyhexane'),
    ('1,3-BUTADIENE', '1_3_butadiene'),
    ('1,3-DICHLOROPROPENE', '1_3_dichloropropene'),
    ('1,3-PROPANE SULTONE', '1_3_propane_sultone'),
    ('1,4-DICHLOROBENZENE', '1_4_dichlorobenzene'),
    ('2-ACETYLAMINOFLUORENE', '2_acetylaminofluorene'),
    ('2-NITROPROPANE', '2_nitropropane'),
    ('2,4-DINITROTOLUENE', '2_4_dinitrotoluene'),
    ('2,4-TOLUENE DIISOCYANATE', '2_4_toluene_diisocyanate'),
    ('2,4,6-TRICHLOROPHENOL', '2_4_6_trichlorophenol'),
    ("3,3'-DICHLOROBENZIDINE", '3_3_dichlorobenzidine'),
    ('4-DIMETHYLAMINOAZOBENZENE', '4_dimethylaminoazobenzene'),
    ("4,4'-METHYLENE BIS(2-CHLOROANILINE)", '4_4_methylene_bis_2_chloroaniline'),
    ("4,4'-METHYLENEDIANILINE", '4_4_methylenedianiline'),
    ('ACETALDEHYDE', 'acetaldehyde'),
    ('ACETAMIDE', 'acetamide'),
    ('ACRYLAMIDE', 'acrylamide'),
    ('ACRYLONITRILE', 'acrylonitrile'),
    ('ALLYL CHLORIDE', 'allyl_chloride'),
    ('ANILINE', 'aniline'),
    ('ARSENIC COMPOUNDS(INORGANIC INCLUDING ARSINE)', 'arsenic_compounds_inorganic_including_arsine'),
    ('BENZOAPYRENE', 'benzoapyrene'),
    ('BENZENE', 'benzene'),
    ('BENZIDINE', 'benzidine'),
    ('BENZYL CHLORIDE', 'benzyl_chloride'),
    ('BERYLLIUM COMPOUNDS', 'beryllium_compounds'),
    ('BIS(2-ETHYLHEXYL)PHTHALATE (DEHP)', 'bis_2_ethylhexyl_phthalate_dehp'),
    ('BIS(CHLOROMETHYL) ETHER', 'bis_chloromethyl_ether'),
    ('BROMOFORM', 'bromoform'),
    ('CHROMIUM VI (HEXAVALENT)', 'chromium_vi_hexavalent'),
    ('CADMIUM COMPOUNDS', 'cadmium_compounds'),
    ('CARBON TETRACHLORIDE', 'carbon_tetrachloride'),
    ('CHLORDANE', 'chlordane'),
    ('CHLOROBENZILATE', 'chlorobenzilate'),
    ('CHLOROPRENE', 'chloroprene'),
    ('COKE OVEN EMISSIONS', 'coke_oven_emissions'),
    ('DICHLOROETHYL ETHER (BIS[2-CHLOROETHYL]ETHER)', 'dichloroethyl_ether_bis_2_chloroethyl_ether'),
    ('EPICHLOROHYDRIN', 'epichlorohydrin'),
    ('ETHYLBENZENE', 'ethylbenzene'),
    ('ETHYL CARBAMATE (URETHANE) CHLORIDE (CHLOROETHANE)', 'ethyl_carbamate_urethane_chloride_chloroethane'),
    ('ETHYLENE DIBROMIDE (DIBROMOETHANE)', 'ethylene_dibromide_dibromoethane'),
    ('ETHYLENE DICHLORIDE (1,2-DICHLOROETHANE)', 'ethylene_dichloride_1_2_dichloroethane'),
    ('ETHYLENE OXIDE', 'ethylene_oxide'),
    ('ETHYLENE THIOUREA', 'ethylene_thiourea'),
    ('ETHYLIDENE DICHLORIDE (1,1-DICHLOROETHANE)', 'ethylidene_dichloride_1_1_dichloroethane'),
    ('FORMALDEHYDE', 'formaldehyde'),
    ('HEPTACHLOR', 'heptachlor'),
    ('HEXACHLOROBENZENE', 'hexachlorobenzene'),
    ('HEXACHLOROBUTADIENE', 'hexachlorobutadiene'),
    ('HYDRAZINE', 'hydrazine'),
    ('METHYL TERT-BUTYL ETHER', 'methyl_tert_butyl_ether'),
    ('METHYLENE CHLORIDE', 'methylene_chloride'),
    ('N-NITROSODIMETHYLAMINE', 'n_nitrosodimethylamine'),
    ('N-NITROSOMORPHOLINE', 'n_nitrosomorpholine'),
    ('NICKEL COMPOUNDS', 'nickel_compounds'),
    ('NAPHTHALENE', 'naphthalene'),
    ('NITROBENZENE', 'nitrobenzene'),
    ('POLYCHLORINATED BIPHENYLS (AROCLORS)', 'polychlorinated_biphenyls_aroclors'),
    ('PENTACHLOROPHENOL', 'pentachlorophenol'),
    ('PROPYLENE OXIDE', 'propylene_oxide'),
    ('TETRACHLOROETHYLENE', 'tetrachloroethylene'),
    ('2,4-TOLUENE DIAMINE', '2_4_toluene_diamine'),
    ('TOXAPHENE (CHLORINATED CAMPHENE)', 'toxaphene_chlorinated_camphene'),
    ('TRICHLOROETHYLENE', 'trichloroethylene'),
    ('VINYL BROMIDE', 'vinyl_bromide'),
    ('VINYL CHLORIDE', 'vinyl_chloride'),
    ('O-TOLUIDINE', 'o_toluidine'),
    ('1,4-DIOXANE', '1_4_dioxane'),
    ('PAHPOM', 'pahpom'),
)

# EPA's own caveat (module docstring), condensed into every measure.definition.doc.
_CAVEAT = (
    "EPA's own caveat: AirToxScreen is a screening tool, not a precise exposure or "
    "risk estimate for any individual; results for a tract are best used to guide "
    "follow-up local study, and a change between assessment years may reflect a "
    "modeling-method update rather than a real emissions change -- use caution "
    "comparing across assessment years "
    "(https://www.epa.gov/AirToxScreen/airtoxscreen-overview, checked 2026-09-19)."
)

_DEFINITIONS = (
    ("AIRTOXSCREEN:total_cancer_risk",
     "Total modeled lifetime cancer risk from ambient air toxics",
     "Total modeled lifetime cancer risk (chances per million) from ambient air "
     "toxics, all source groups and pollutants combined. Published pre-rounded to "
     "a small set of risk bins (module docstring), not a continuous value. "
     f"{_CAVEAT}"),
    ("AIRTOXSCREEN:benzene",
     "Modeled lifetime cancer risk from ambient benzene",
     f"Modeled lifetime cancer risk (chances per million) attributable to ambient "
     f"benzene, one of the pollutants issue #98 names by name. {_CAVEAT}"),
    ("AIRTOXSCREEN:formaldehyde",
     "Modeled lifetime cancer risk from ambient formaldehyde",
     f"Modeled lifetime cancer risk (chances per million) attributable to ambient "
     f"formaldehyde, one of the pollutants issue #98 names by name. {_CAVEAT}"),
    ("AIRTOXSCREEN:ethylene_oxide",
     "Modeled lifetime cancer risk from ambient ethylene oxide",
     f"Modeled lifetime cancer risk (chances per million) attributable to ambient "
     f"ethylene oxide, one of the pollutants issue #98 names by name. {_CAVEAT}"),
)


def _fetch(url):
    """The file's bytes. A local path (tests) is read directly; a remote URL goes
    through urllib with a descriptive User-Agent."""
    if not url.startswith("http"):
        return Path(url).read_bytes()
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req) as r:
        return r.read()


def land_raw(cat, release, year=None, kind="srcgrp", url=None):
    """Phase 1: one assessment year's source-group or pollutant national file,
    verbatim and whole, replaced per (kind, assessment_year)."""
    year = year or max(YEARS, key=int)
    if year not in YEARS:
        raise SystemExit(f"epa_airtoxscreen: no known layout for year {year!r}; "
                         f"landed years: {sorted(YEARS, key=int)}")
    if kind == "srcgrp":
        columns, canon, urls = SRCGRP_COLUMNS, SRCGRP_CANON, SRCGRP_URLS
        identifier = "raw.airtoxscreen__tract_risk"
    elif kind == "pollutant":
        columns, canon, urls = POLL_COLUMNS, POLL_CANON, POLLUTANT_URLS
        identifier = "raw.airtoxscreen__tract_risk_pollutant"
    else:
        raise SystemExit(f"epa_airtoxscreen: unknown kind {kind!r}; expected "
                         f"'srcgrp' or 'pollutant'")

    fetch_url = url or urls[year]
    raw_bytes = _fetch(fetch_url)
    with tempfile.NamedTemporaryFile(suffix=".xlsx") as tmp:
        tmp.write(raw_bytes)
        tmp.flush()
        con = duckdb.connect()
        con.sql("INSTALL excel; LOAD excel;")
        header = tuple(con.sql(f"SELECT * FROM read_xlsx('{tmp.name}', all_varchar=true) "
                               f"LIMIT 0").columns)
        if header != columns:
            raise SystemExit(f"epa_airtoxscreen: {fetch_url} ({kind} {year}) header is not "
                             f"the declared layout; differs in "
                             f"{sorted(set(header) ^ set(columns))}")
        select = ", ".join(f'"{orig}" AS "{name}"' for orig, name in canon)
        arrow = con.sql(f"""
            SELECT {select}, '{year}' AS assessment_year, '{release}' AS landed_in
            FROM read_xlsx('{tmp.name}', all_varchar=true)
        """).to_arrow_table()
    if not arrow.num_rows:
        raise SystemExit(f"epa_airtoxscreen: {fetch_url} yielded no rows")

    n = merge.write(cat, identifier, arrow, EqualTo("assessment_year", year))
    merge.manifest(cat, release, f"airtoxscreen_{kind}", fetch_url, n, version=year,
                   method="release_number")
    return year, n


def transform(cat, release, year):
    """Phase 2: measure.definition / measure.stratum / measure.observation for one
    assessment year, from both raw tables together (module docstring: no useful
    partial derive from just one of the two)."""
    geo_vintage = GEO_VINTAGE[year]
    con = duckdb.connect()
    scope = EqualTo("assessment_year", year)
    try:
        srcgrp = cat.load_table("raw.airtoxscreen__tract_risk").scan(row_filter=scope).to_arrow()
        poll = cat.load_table("raw.airtoxscreen__tract_risk_pollutant").scan(row_filter=scope).to_arrow()
    except NoSuchTableError:
        srcgrp = poll = None
    if srcgrp is None or poll is None or not srcgrp.num_rows or not poll.num_rows:
        raise SystemExit(f"epa_airtoxscreen: both raw.airtoxscreen__tract_risk and "
                         f"raw.airtoxscreen__tract_risk_pollutant must be landed for "
                         f"{year!r} before deriving (land_raw kind='srcgrp' and "
                         f"kind='pollutant')")
    con.register("srcgrp_raw", srcgrp)
    con.register("poll_raw", poll)

    definition = pa.Table.from_pylist([
        dict(measure_id=measure_id, source="AIRTOXSCREEN", label=label,
             units="chances per million", universe="resident population of the tract",
             rate_basis="per_1000000", age_adjustment=None, method="model_based",
             cancer_site_code=None, doc=doc)
        for measure_id, label, doc in _DEFINITIONS
    ])
    stratum = pa.Table.from_pylist([dict(
        stratum_id="AIRTOXSCREEN:ALL", source="AIRTOXSCREEN", sex=None, age_group=None,
        race_ethnicity=None, stage=None, other=None, scheme="AIRTOXSCREEN_TOTAL",
    )])

    # Real tract rows only -- a real census tract number is never coded all-zero,
    # unlike the national/state/county aggregate rows also present in each file
    # (module docstring). Total risk comes from the source-group table (identical
    # in the pollutant table, verified); the three pollutants from the pollutant
    # table. No suppression anywhere in this source (module docstring), so
    # value_status is always 'reported'.
    observation = con.sql(f"""
        SELECT 'AIRTOXSCREEN' AS source, '{year}' AS source_release,
               'AIRTOXSCREEN:total_cancer_risk' AS measure_id,
               'tract:' || tract AS geo_id, {geo_vintage} AS geo_vintage,
               '{year}' AS period_start, '{year}' AS period_end,
               'AIRTOXSCREEN:ALL' AS stratum_id,
               TRY_CAST(total_cancer_risk AS DOUBLE) AS value,
               NULL::DOUBLE AS lower, NULL::DOUBLE AS upper, NULL::DOUBLE AS interval_level,
               NULL::DOUBLE AS numerator, NULL::DOUBLE AS denominator,
               'reported' AS value_status, NULL::VARCHAR AS reliability_flag,
               NULL::VARCHAR AS trend
        FROM srcgrp_raw WHERE tract NOT LIKE '%000000'
      UNION ALL
        SELECT 'AIRTOXSCREEN', '{year}', 'AIRTOXSCREEN:benzene',
               'tract:' || tract, {geo_vintage}, '{year}', '{year}', 'AIRTOXSCREEN:ALL',
               TRY_CAST(benzene AS DOUBLE), NULL, NULL, NULL, NULL, NULL,
               'reported', NULL, NULL
        FROM poll_raw WHERE tract NOT LIKE '%000000'
      UNION ALL
        SELECT 'AIRTOXSCREEN', '{year}', 'AIRTOXSCREEN:formaldehyde',
               'tract:' || tract, {geo_vintage}, '{year}', '{year}', 'AIRTOXSCREEN:ALL',
               TRY_CAST(formaldehyde AS DOUBLE), NULL, NULL, NULL, NULL, NULL,
               'reported', NULL, NULL
        FROM poll_raw WHERE tract NOT LIKE '%000000'
      UNION ALL
        SELECT 'AIRTOXSCREEN', '{year}', 'AIRTOXSCREEN:ethylene_oxide',
               'tract:' || tract, {geo_vintage}, '{year}', '{year}', 'AIRTOXSCREEN:ALL',
               TRY_CAST(ethylene_oxide AS DOUBLE), NULL, NULL, NULL, NULL, NULL,
               'reported', NULL, NULL
        FROM poll_raw WHERE tract NOT LIKE '%000000'
    """).to_arrow_table()
    merge.check_observations(observation)

    scope = EqualTo("source", "AIRTOXSCREEN")
    return {
        "measure.definition": merge.write(cat, "measure.definition", definition, scope),
        "measure.stratum": merge.write(cat, "measure.stratum", stratum, scope),
        "measure.observation": merge.merge(
            cat, "measure.observation", observation, release,
            And(scope, EqualTo("source_release", year))),
    }


def ingest(cat, release, year=None, srcgrp_url=None, pollutant_url=None):
    year = year or max(YEARS, key=int)
    _, n1 = land_raw(cat, release, year, "srcgrp", srcgrp_url)
    _, n2 = land_raw(cat, release, year, "pollutant", pollutant_url)
    return {
        "raw.airtoxscreen__tract_risk": n1,
        "raw.airtoxscreen__tract_risk_pollutant": n2,
        **transform(cat, release, year),
    }
