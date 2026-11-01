"""CDC TeenVaxView / NIS-Teen HPV vaccination coverage -> Iceberg (#105).

Upstream: data.cdc.gov "Vaccination Coverage among Adolescents (13-17 Years)",
dataset id `ee48-w5t6` (found via web search against data.cdc.gov, confirmed by
downloading the live file, 2026-09-19):
https://data.cdc.gov/Teen-Vaccinations/Vaccination-Coverage-among-Adolescents-13-17-Years/ee48-w5t6.
It is ONE continuously-refreshed Socrata dataset covering every vaccine and
survey year (2006-2025 seen live) -- unlike places.py/cdc_svi.py, there is no
per-year dataset id to pick from.

**Licence.** This dataset's own Socrata metadata carries no `license` field
(checked directly against https://data.cdc.gov/api/views/ee48-w5t6.json,
2026-09-19: both `license` and `licenseId` are absent) -- the same gap
fda_mqsa.py hit for FDA's list. CDC's site-wide content-usage page states:
"Most of the information on the CDC and ATSDR websites is not subject to
copyright, is in the public domain, and may be freely used or reproduced
without obtaining copyright permission," with "Attribution to the agency
that developed the material must be provided in your use of the materials.
Such attribution should clearly state the materials were developed by CDC
ATSDR and/or HHS" (https://www.cdc.gov/other/agencymaterials.html, checked
2026-09-19) -- the same basis cdc_svi.py uses, plus this being a U.S.
Government work under 17 U.S.C. Sec 105 (NCIRD employees' official duties).
Attribution per the dataset's own Socrata `attribution` field: "National
Center for Immunization and Respiratory Diseases (NCIRD)".

**Version axis: retrieval-date vintage, deduplicated by checksum.** The
issue's own instruction ("appended yearly and occasionally revised -> vintage
by retrieval, survey year as the period") is exactly bls_laus.py's pattern:
`land_raw` hashes the downloaded bytes and compares against the most recent
`provenance.release` checksum for `source='teenvaxview'`; an identical hash
lands nothing (SPEC.md's vintage rule: "several scrapes that captured
identical values are one vintage").

**Header, verified against the live file 2026-09-19:** `Vaccine/Sample,Dose,
Geography Type,Geography,Survey Year,Dimension Type,Dimension,Estimate (%),
95% CI (%),Sample Size`. Landed under the same field names data.cdc.gov's own
SODA API uses (https://data.cdc.gov/resource/ee48-w5t6.json's fieldNames) --
`vaccine`/`dose`/`geography_type`/`geography`/`year_season`/`dimension_type`/
`dimension`/`coverage_estimate`/`ci_95`/`sample_size` -- rather than inventing
new names for columns the source already names sensibly.

**Scope: only vaccine='HPV' is derived, per the issue title and body** ("CDC
TeenVaxView / NIS-Teen HPV vaccination coverage"; the issue's SCP cross-
reference is HPV-specific too). Raw lands the WHOLE file, all 7 vaccines
(HPV, MenACWY, Tdap/Td, MMR, HepA, HepB, Varicella) verbatim (ADR-0002) --
`land_raw` does not filter by vaccine. `transform` filters to HPV.

**Dose: only >=1 Dose and Up-to-Date are derived, per the issue body**
("by vaccine/dose (HPV >=1 dose, up-to-date)"). HPV's other three published
dose families -- >=2 Doses, >=3 Doses, and "Series Completion (3 Dose) Among
HPV Vaccination Initiators" (verified against the live file: exactly these 5
dose families exist for vaccine='HPV') -- land in raw but are not derived,
the same choice cdc_svi.py makes for PCI and the structural variables #40
doesn't ask for. `DOSE_TYPE` maps the two derived families; an HPV dose
family not in `DOSE_TYPE` or `DOSE_TYPE_NOT_DERIVED` raises `SystemExit`
rather than silently landing nothing (a real upstream addition should be
noticed, not skipped quietly).

**Sex rides in the `Dose` cell, not a `Dimension`.** The live file has no
`dimension_type='Sex'` at all -- every dose string ends ", Males" / ", Females"
/ ", Males and Females" (verified: HPV's six >=1-Dose/Up-to-Date rows split
cleanly on the LAST ", "). `dose_type_text`/`sex_text` are that split;
`SEX_CODE` is the closed map (validated the same way as `DOSE_TYPE`) used to
build a compact `stratum_id`.

**Six real `Dimension Type` values, verified against the live file:**
'Overall' (one row, no breakdown), 'Age' ('13-15 Years' | '13-17 Years' --
published for every dose/sex, unlike the other four), 'Race and Ethnicity',
'Insurance Coverage', 'Poverty', 'Urbanicity' -- each published only for the
pooled-sex dose ("...Males and Females") except Age. `DIMENSION_TYPE` is the
closed map (short key -> `measure.stratum` field -> scheme suffix); an
unrecognised `Dimension Type` raises `SystemExit`. Insurance/Poverty/
Urbanicity all land in `measure.stratum.other` (no dedicated column for any
of the three) -- prefixed with the dimension type name (e.g. "Insurance
Coverage: Uninsured") so the three don't collide in one free-text field.
Source-native throughout (SPEC.md): the source's own category text is kept,
never recoded into a cross-source scheme.

**Period.** `Survey Year` is a single year ("2022") for almost every row, and
one pooled window ("2018-2022", verified: used for HPV's Insurance/Poverty/
Urbanicity/Overall breakdowns) for the rest -- split generically on '-'
(`period_start`/`period_end`) rather than hardcoding which years pool, so a
future pooled window needs no code change here.

**Suppression.** `Estimate (%)` is the literal sentinel `NA` when withheld (no
separate footnote column, unlike places.py/cdc_svi.py) -- verified: every NA
row also has blank `95% CI (%)`/`Sample Size`. CDC's own technical notes name
the reason: "If the unweighted sample size for the numerator was less than 30
or the [(CI half-width)/Estimate] was greater than 0.6, the estimate may not
be reliable or precise" (https://www.cdc.gov/teenvaxview/publications/
technical-notes-nis-teen-vaccination-coverage.html, checked 2026-09-19) -- a
reliability/precision threshold, not a privacy-driven small-count rule like
PLACES', so `value_status = 'suppressed_reliability'` (SPEC.md's enum), never
'suppressed_small_count'.

ponytail: `Sample Size` is NIS-Teen's own unweighted survey respondent count
underlying a *survey-weighted* percent estimate -- not a numerator/denominator
pair for `value` (same reasoning as PLACES' TotalPopulation, places.py's
module docstring). It lands in raw and stays there; `numerator`/`denominator`
are NULL in measure.observation.

**Geography.** Per the issue: "state and the NIS local areas (some are
cities/counties -- map the ones that are counties; leave the rest at their
published names in raw; report what did not map)." The live file's
`Geography Type='States/Local Areas'` carries 68 distinct values: 50 states +
DC + Puerto Rico + Guam + U.S. Virgin Islands (54, all mapped via the closed
`STATE_FIPS`) plus 14 named local areas. Of those 14, exactly seven are a
real single county and map via `LOCAL_COUNTY_FIPS`: TX-Bexar/Dallas/El Paso/
Hidalgo/Tarrant/Travis County, and PA-Philadelphia (the City of Philadelphia
is coextensive with Philadelphia County, FIPS 42101 -- confirmed against the
Census county list). The other seven -- IL-City of Chicago (overlaps but is
not coextensive with Cook County), NY-City of New York (five boroughs = five
counties), TX-City of Houston (spans Harris/Fort Bend/Montgomery), and the
four "...-Rest of state" residuals -- are not one county and stay unmapped
(`geo_id` NULL; excluded from measure.observation, left in raw only, same
technique as any other row `transform` can't place). `Geography
Type='HHS Regions/National'` carries 'United States' (-> `nation:US`) plus
ten `Region N` rows, which have no geo_id in the current spine and are left
unmapped too -- the issue's geography instruction names only "state and the
NIS local areas", not HHS regions. `transform` prints every distinct
unmapped `Geography` value it saw, per the issue's "report what did not map".

**geo_vintage is the constant 2020** (not tracked per row): none of the
mapped geographies (54 states/DC/territories at the state level, seven
counties) fall inside a FIPS range that changed vintage in this window --
Connecticut, the one state whose county FIPS moved (2022 planning regions,
places.py/cdc_svi.py's GEO_VINTAGE), only ever appears here as the whole
state (FIPS 09, unaffected), never as a TeenVaxView local area.

**Relation to State Cancer Profiles' own HPV measure (#27, per the issue).**
SCP's risk topic `vaccine` (`risk='v282'`, "Percent with Up-to-Date HPV
Vaccination Coverage") is drawn from this SAME NIS-Teen survey, at the state
level -- but `raw.scp__risk` is landed to raw only, not yet derived into
measure.observation (scp.py's module docstring: its geography/race vocabulary
need their own investigation first). `NIS_TEEN:HPV:uptodate` here is
therefore the first *live* up-to-date HPV vaccination measure in
measure.observation; once SCP's risk topic is derived, the two states-level
series should closely agree (same survey, same "up-to-date" definition) and
diverge only in vintage/rounding -- see each definition's `doc`.
"""

import hashlib
import tempfile
import urllib.request
from datetime import date

import duckdb
import pyarrow as pa
from pyiceberg.exceptions import NoSuchTableError
from pyiceberg.expressions import And, EqualTo, In

from . import merge

USER_AGENT = "cancerbasemap/1.0 (+https://github.com/seandavi/cancer-basemap)"
URL = "https://data.cdc.gov/api/views/ee48-w5t6/rows.csv?accessType=DOWNLOAD"

COLUMNS = ("Vaccine/Sample", "Dose", "Geography Type", "Geography", "Survey Year",
           "Dimension Type", "Dimension", "Estimate (%)", "95% CI (%)", "Sample Size")

# Raw header cell -> the field name this module lands it under, matching
# data.cdc.gov's own SODA API fieldName for each column (module docstring).
ALIAS = dict(zip(COLUMNS, ("vaccine", "dose", "geography_type", "geography", "year_season",
                          "dimension_type", "dimension", "coverage_estimate", "ci_95",
                          "sample_size")))

# HPV dose families that ARE derived (module docstring: only what the issue names).
DOSE_TYPE = {"≥1 Dose": "1dose", "Up-to-Date": "uptodate"}
# HPV dose families that land in raw but are NOT derived here -- known, deliberately
# out of scope, distinct from a genuinely unrecognised value (module docstring).
DOSE_TYPE_NOT_DERIVED = {
    "≥2 Doses", "≥3 Doses",
    "Series Completion (3 Dose) Among HPV Vaccination Initiators",
}

# The sex suffix every HPV Dose cell ends with (module docstring).
SEX_CODE = {"Males": "M", "Females": "F", "Males and Females": "MF"}

# dimension_type -> (short key for stratum_id/scheme, the measure.stratum column it
# fills). 'other' is shared by Insurance/Poverty/Urbanicity (module docstring).
DIMENSION_TYPE = {
    "Overall": ("total", None),
    "Age": ("age", "age_group"),
    "Race and Ethnicity": ("race_ethnicity", "race_ethnicity"),
    "Insurance Coverage": ("insurance", "other"),
    "Poverty": ("poverty", "other"),
    "Urbanicity": ("urbanicity", "other"),
}

# 50 states + DC + the 3 territories TeenVaxView actually publishes (module
# docstring) -- standard Census state FIPS codes.
STATE_FIPS = {
    "Alabama": "01", "Alaska": "02", "Arizona": "04", "Arkansas": "05", "California": "06",
    "Colorado": "08", "Connecticut": "09", "Delaware": "10", "District of Columbia": "11",
    "Florida": "12", "Georgia": "13", "Hawaii": "15", "Idaho": "16", "Illinois": "17",
    "Indiana": "18", "Iowa": "19", "Kansas": "20", "Kentucky": "21", "Louisiana": "22",
    "Maine": "23", "Maryland": "24", "Massachusetts": "25", "Michigan": "26",
    "Minnesota": "27", "Mississippi": "28", "Missouri": "29", "Montana": "30",
    "Nebraska": "31", "Nevada": "32", "New Hampshire": "33", "New Jersey": "34",
    "New Mexico": "35", "New York": "36", "North Carolina": "37", "North Dakota": "38",
    "Ohio": "39", "Oklahoma": "40", "Oregon": "41", "Pennsylvania": "42",
    "Rhode Island": "44", "South Carolina": "45", "South Dakota": "46", "Tennessee": "47",
    "Texas": "48", "Utah": "49", "Vermont": "50", "Virginia": "51", "Washington": "53",
    "West Virginia": "54", "Wisconsin": "55", "Wyoming": "56",
    "Puerto Rico": "72", "Guam": "66", "U.S. Virgin Islands": "78",
}

# The seven TeenVaxView local areas that are a real, single county (module
# docstring); the other seven local-area names are deliberately absent here.
LOCAL_COUNTY_FIPS = {
    "PA-Philadelphia": "42101",
    "TX-Bexar County": "48029",
    "TX-Dallas County": "48113",
    "TX-El Paso County": "48141",
    "TX-Hidalgo County": "48215",
    "TX-Tarrant County": "48439",
    "TX-Travis County": "48453",
}

GEO_VINTAGE = 2020  # module docstring: constant, no in-scope FIPS change applies


def _case(column, mapping):
    """SQL CASE over an explicit {value: mapped} dict -- no ELSE, so an unmapped
    input surfaces as NULL for the caller to catch (places.py's `_case`;
    duplicated per scp.py's convention, since it's three lines)."""
    whens = " ".join(f"WHEN {column} = '{k}' THEN '{v}'" for k, v in mapping.items())
    return f"CASE {whens} END"


def _fetch(url):
    """The file's bytes. A local path (tests) is read directly; a remote URL goes
    through urllib with a descriptive User-Agent."""
    if not url.startswith("http"):
        with open(url, "rb") as f:
            return f.read()
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req) as r:
        return r.read()


def _header(raw_bytes):
    """The file's header line, comma-split (no header cell contains a comma)."""
    first = raw_bytes.split(b"\n", 1)[0].rstrip(b"\r\n")
    return tuple(first.decode("utf-8").split(","))


def _previous_checksum(cat):
    """The most recent provenance.release checksum landed under
    source='teenvaxview', or None if there isn't one yet (module docstring's
    unchanged-vintage check, bls_laus.py's pattern)."""
    try:
        table = cat.load_table("provenance.release")
    except NoSuchTableError:
        return None
    con = duckdb.connect()
    con.register("prov", table.scan(row_filter=EqualTo("source", "teenvaxview")).to_arrow())
    row = con.sql("SELECT checksum FROM prov ORDER BY retrieved_at DESC LIMIT 1").fetchone()
    return row[0] if row else None


def land_raw(cat, release, vintage=None, url=None):
    """Phase 1: the whole file, verbatim, scoped by one retrieval-date vintage.

    Returns `(None, 0)` without writing anything when the file's bytes match
    the previous vintage's checksum exactly (module docstring).
    """
    url = url or URL
    raw_bytes = _fetch(url)
    checksum = hashlib.sha256(raw_bytes).hexdigest()
    if checksum == _previous_checksum(cat):
        return None, 0

    vintage = vintage or date.today().isoformat()
    if (header := _header(raw_bytes)) != COLUMNS:
        raise SystemExit(f"teenvaxview: {url} header is not the declared one; "
                         f"differs in {sorted(set(header) ^ set(COLUMNS))}")

    select = ", ".join(f'"{c}" AS {alias}' for c, alias in ALIAS.items())
    with tempfile.NamedTemporaryFile(suffix=".csv") as tmp:
        tmp.write(raw_bytes)
        tmp.flush()
        con = duckdb.connect()
        # Dialect stated, not sniffed: comma-delimited, double-quoted where a cell
        # needs it (Dose contains commas, e.g. "≥1 Dose, Males and Females").
        # all_varchar keeps 'NA' (the suppression sentinel) landed as text, not
        # silently parsed; a genuinely empty cell (CI/Sample Size when suppressed)
        # reads as NULL.
        arrow = con.sql(f"""
            SELECT {select}, '{vintage}' AS teenvax_vintage, '{release}' AS landed_in
            FROM read_csv('{tmp.name}', header=true, all_varchar=true, delim=',',
                          quote='"', escape='"', nullstr='')
        """).to_arrow_table()
    if not arrow.num_rows:
        raise SystemExit(f"teenvaxview: {url} yielded no rows")

    n = merge.write(cat, "raw.teenvaxview__coverage", arrow, EqualTo("teenvax_vintage", vintage))
    merge.manifest(cat, release, "teenvaxview", url, n, version=vintage,
                   method="retrieval_date", checksum=checksum)
    return vintage, n


def transform(cat, release, vintage):
    """Phase 2: measure.definition / measure.stratum / measure.observation, for
    vaccine='HPV' and the two dose families the issue names (module docstring)."""
    con = duckdb.connect()
    con.register("raw", cat.load_table("raw.teenvaxview__coverage").scan(
        row_filter=And(EqualTo("teenvax_vintage", vintage), EqualTo("vaccine", "HPV"))
    ).to_arrow())

    con.execute(f"""
        CREATE OR REPLACE TABLE mapped AS
        SELECT *,
               split_part(dose, ', ', 1) AS dose_type_text,
               split_part(dose, ', ', 2) AS sex_text,
               lower(regexp_replace(trim(dimension), '[^A-Za-z0-9]+', '_', 'g')) AS dim_slug,
               CASE WHEN geography_type = 'HHS Regions/National' AND geography = 'United States'
                        THEN 'nation:US'
                    WHEN geography_type = 'States/Local Areas'
                        THEN COALESCE({_case('geography', {k: f'state:{v}' for k, v in STATE_FIPS.items()})},
                                      {_case('geography', {k: f'county:{v}' for k, v in LOCAL_COUNTY_FIPS.items()})})
               END AS geo_id
        FROM raw
    """)

    # Every distinct value actually present must be a known one -- an upstream
    # addition (a new dose family, a renamed sex/dimension category) surfaces as
    # SystemExit, never a silently dropped row (places.py/scp.py's convention).
    def _known(column, known, label):
        seen = {v for (v,) in con.sql(f"SELECT DISTINCT {column} FROM mapped").fetchall()}
        if bad := seen - known:
            raise SystemExit(f"teenvaxview: unknown {label} in {vintage}: {sorted(bad)}")

    _known("dose_type_text", set(DOSE_TYPE) | DOSE_TYPE_NOT_DERIVED, "HPV dose family")
    _known("sex_text", set(SEX_CODE), "sex value")
    _known("dimension_type", set(DIMENSION_TYPE), "Dimension Type")
    # `!=` is NULL-unsafe (`NULL != 'NA'` is NULL, not TRUE), so an actual blank
    # cell -- landed as SQL NULL, not the 'NA' sentinel text -- would silently
    # skip this check and fall through to the observation query's ELSE branch as
    # a NULL value under value_status='reported' (the #132/#136/#141 bug class:
    # a non-numeric/unparseable estimate must never be marked 'reported'). `IS
    # NULL` is checked explicitly so a blank cell raises here instead.
    bad_estimates = con.sql("""
        SELECT DISTINCT coverage_estimate FROM mapped
        WHERE coverage_estimate IS NULL
           OR (coverage_estimate != 'NA' AND TRY_CAST(coverage_estimate AS DOUBLE) IS NULL)
    """).fetchall()
    if bad_estimates:
        raise SystemExit(f"teenvaxview: unparseable Estimate (%) value(s) in {vintage}: "
                         f"{sorted((v for (v,) in bad_estimates), key=lambda v: (v is None, v))}")

    unmapped = con.sql("SELECT DISTINCT geography FROM mapped WHERE geo_id IS NULL "
                       "ORDER BY 1").fetchall()
    if unmapped:
        print(f"teenvaxview: {len(unmapped)} geography value(s) left unmapped in raw "
             f"(no geo_id derived, per the issue's 'report what did not map'): "
             f"{[g for (g,) in unmapped]}")

    dose_case = _case("dose_type_text", DOSE_TYPE)
    dimkey_case = _case("dimension_type", {k: v[0] for k, v in DIMENSION_TYPE.items()})
    con.execute(f"""
        CREATE OR REPLACE TABLE final AS
        SELECT *, {dose_case} AS dose_code, {dimkey_case} AS dim_key
        FROM mapped
        WHERE {dose_case} IS NOT NULL AND geo_id IS NOT NULL
    """)

    definition = pa.Table.from_pylist([
        dict(measure_id="NIS_TEEN:HPV:1dose", source="NIS_TEEN",
             label="HPV vaccination, >=1 dose", units="percent",
             universe="adolescents aged 13-17 years", rate_basis="percent",
             age_adjustment=None, method="survey_direct", cancer_site_code=None,
             doc="Percent of adolescents who received at least one dose of HPV "
                 "vaccine, NIS-Teen (module docstring on relation to SCP's own "
                 "state-level HPV measure, #27)."),
        dict(measure_id="NIS_TEEN:HPV:uptodate", source="NIS_TEEN",
             label="HPV vaccination, up-to-date", units="percent",
             universe="adolescents aged 13-17 years", rate_basis="percent",
             age_adjustment=None, method="survey_direct", cancer_site_code=None,
             doc="Percent of adolescents up to date on HPV vaccination -- NIS-Teen's "
                 "own definition: >=3 doses, or >=2 doses with the first dose before "
                 "age 15. The same survey and definition State Cancer Profiles' risk "
                 "topic 'vaccine' (risk='v282') reports at the state level, though "
                 "that topic is landed (raw.scp__risk) but not yet derived (#27) -- "
                 "see module docstring."),
    ])
    def_ids = definition.column("measure_id").to_pylist()

    stratum = con.sql(f"""
        SELECT DISTINCT
               'NIS_TEEN:' || {_case('sex_text', SEX_CODE)} || ':' || dim_key || ':' ||
                   dim_slug AS stratum_id,
               'NIS_TEEN' AS source, sex_text AS sex,
               CASE WHEN dimension_type = 'Age' THEN dimension END AS age_group,
               CASE WHEN dimension_type = 'Race and Ethnicity' THEN dimension END AS race_ethnicity,
               NULL::VARCHAR AS stage,
               CASE WHEN dimension_type IN ('Insurance Coverage', 'Poverty', 'Urbanicity')
                        THEN dimension_type || ': ' || dimension END AS other,
               'NIS_TEEN_' || upper(dim_key) AS scheme
        FROM final
    """).to_arrow_table()
    stratum_ids = stratum.column("stratum_id").to_pylist()

    observation = con.sql(f"""
        SELECT 'NIS_TEEN' AS source, '{vintage}' AS source_release,
               'NIS_TEEN:HPV:' || dose_code AS measure_id,
               geo_id, {GEO_VINTAGE} AS geo_vintage,
               split_part(year_season, '-', 1) AS period_start,
               CASE WHEN year_season LIKE '%-%' THEN split_part(year_season, '-', 2)
                    ELSE year_season END AS period_end,
               'NIS_TEEN:' || {_case('sex_text', SEX_CODE)} || ':' || dim_key || ':' ||
                   dim_slug AS stratum_id,
               TRY_CAST(coverage_estimate AS DOUBLE) AS value,
               CASE WHEN ci_95 IS NULL THEN NULL
                    ELSE TRY_CAST(split_part(ci_95, ' to ', 1) AS DOUBLE) END AS lower,
               CASE WHEN ci_95 IS NULL THEN NULL
                    ELSE TRY_CAST(split_part(ci_95, ' to ', 2) AS DOUBLE) END AS upper,
               CASE WHEN ci_95 IS NULL THEN NULL ELSE 0.95 END AS interval_level,
               NULL::DOUBLE AS numerator, NULL::DOUBLE AS denominator,
               -- Derived from the SAME TRY_CAST as `value`, not a separate
               -- `coverage_estimate = 'NA'` check, so the two can never
               -- disagree (the bad_estimates guard above already means the
               -- only way TRY_CAST fails here is the real 'NA' sentinel).
               CASE WHEN TRY_CAST(coverage_estimate AS DOUBLE) IS NULL
                        THEN 'suppressed_reliability' ELSE 'reported' END AS value_status,
               NULL::VARCHAR AS reliability_flag, NULL::VARCHAR AS trend
        FROM final
    """).to_arrow_table()
    merge.check_observations(observation)

    scope = EqualTo("source", "NIS_TEEN")
    return {
        "measure.definition": merge.write(cat, "measure.definition", definition,
                                          And(scope, In("measure_id", def_ids))),
        "measure.stratum": merge.write(cat, "measure.stratum", stratum,
                                       And(scope, In("stratum_id", stratum_ids))),
        "measure.observation": merge.merge(
            cat, "measure.observation", observation, release,
            And(scope, EqualTo("source_release", vintage))),
    }


def ingest(cat, release, vintage=None, url=None):
    vintage, n = land_raw(cat, release, vintage, url)
    if vintage is None:
        print("teenvaxview: unchanged vintage (checksum matches the previous "
             "manifest row); nothing landed")
        return {}
    return {"raw.teenvaxview__coverage": n, **transform(cat, release, vintage)}
