"""State Cancer Profiles (SCP) -> Iceberg, all vintages (#27, the flagship).

**Upstream has no API, bulk download or archive.** statecancerprofiles.cancer.gov
serves only its current numbers; `seandavi/state-cancer-profile-scraper` scrapes it
and republishes each captured edition as a versioned Zenodo deposit -- a **vintage**
(`~/Documents/git/state-cancer-profile-scraper/CLAUDE.md`/`docs/releases.md`: "A
vintage is one edition of the upstream estimates ... Several dated scrapes that
captured identical values belong to one vintage."). This module lands from those
public Zenodo deposits directly (anonymous HTTPS, no credentials, no tailnet) --
never from cdsci-lake, even though cdsci-lake already curates SCP under its own
ADR-0012 (`~/Documents/git/cdsci-lake/src/cdsci/lake/sources/scp/`, confirmed to
exist by filename only, not read, per this issue's explicit instruction to source
the public deposits for this PR).

**Licence.** SCP's own site states only a re-identification restriction (42 U.S.C.
Sec 242m(d), statecancerprofiles.cancer.gov/dataUseRestrictions.html, checked
2026-09-18) -- irrelevant here since it publishes aggregates only. SCP is produced
by NCI/CDC as part of employees' official duties: a U.S. Government work, public
domain under 17 U.S.C. Sec 105 (resources.data.gov/open-licenses/, the same basis
already used for RUCC/RUCA/SEER in this repo), plus NCI's own reuse policy: "all
text within National Cancer Institute (NCI) products is free of copyright and may
be reused without our permission" (cancer.gov/policies/copyright-reuse). **This is
a republished scrape, not the original archive** (#65): the scraper's own MIT
licence covers its code; its Zenodo deposits (the bytes this module reads) are
CC-BY-4.0; the underlying content they carry is the public-domain SCP data above.
That sentence is repeated verbatim in each raw table's own `comment` (#65's ask),
since this module cannot edit the shared `provenance.release` declaration.

**Vintages found (`data/vintages.json` in the scraper repo, checked 2026-09-18)**:
V1 (2024-08-02-1 capture), V2 (2025-02-10 .. 2026-02-01, 13 captures), V3
(2026-04-01 .. 2026-08-24, 6 captures). Each Zenodo record's own metadata was
fetched live (`https://zenodo.org/api/records/<id>`) to get its DOI and file list
-- not read from a doc, which `docs/schema-drift.md` in that repo turned out to be
one day stale about V3's own column set (see below).

**Topics differ by vintage.** V1/V2 ship `incidence`+`mortality` only, as
`.csv.gz`; V3 adds `demographics`+`risk` and also ships Parquet. This module reads
the `.csv.gz` form for every vintage/topic it lands (`all_varchar=true`, same as
every other CSV source here) rather than V3's Parquet, deliberately: the real V3
Parquet's own column *types* are inconsistent within one topic (verified directly
-- `age_adjusted_rate_per_100_000` is a native DOUBLE, but `lower_ci_rate` in the
same file is VARCHAR because it must hold the literal sentinel `"*"` while the main
rate column represents the same suppression as a plain NULL) -- reading the CSV
keeps one column type (VARCHAR) throughout, verbatim, with no per-column type
inconsistency to reconcile.

**Only `incidence`, `mortality` and `risk` are landed here; `demographics` is
not.** ponytail: demographics is ACS/Census population-composition data (poverty,
education, crowding, income), not a cancer measure, its real column set is very
wide (dozens of topic-specific value columns keyed by a long/sparse `topic`/`demo`
pair) and unexplored in the depth the other topics got, and this repo already has
a dedicated, better-scoped home for ACS data (#29). Landing it here would
duplicate that source under a worse contract. Revisit as its own issue if a
downstream consumer specifically wants SCP's own ACS extract rather than a
directly-landed ACS release.

**Three real column layouts per topic, one raw table per topic (house rule:
"one COLUMNS layout per real upstream layout, detected by header match").**
Verified against real bytes for every vintage/topic landed (not from
`docs/schema-drift.md`, whose "V3 = 29 cols, unchanged from V2" claim is stale --
written the day before the 2026-08-24 scrape that this V3 deposit actually holds,
which added `suppression_reason` and, for mortality, dropped `stage` entirely).
`raw.scp__incidence`/`raw.scp__mortality` are the union of every vintage's real
columns; a column absent from a given vintage's real layout lands `NULL`, same
technique as `cdc_svi.py`. `raw.scp__risk` has one layout (V3 only).

**Suppression -- differs completely by vintage, this is the hard part (#27).**
V1 and V2 carry **no suppression marker of any kind** -- verified: every row's
`age_adjusted_rate_per_100_000` is non-NULL, and no CI/trend cell is the sentinel
`"*"`, in the complete real V1 and V2 files (both topics). Per the scraper's own
`docs/schema-drift.md`: "Suppressed cells are absent rows, not marked cells ...
There is no suppression-reason column and no reason information survives
anywhere" for those two vintages -- every landed V1/V2 row is honestly
`value_status='reported'`; there is nothing to enumerate for them, not an
oversight. **V3 adds a real `suppression_reason` column** with exactly two
non-NULL values (verified by a full `GROUP BY` over the real V3 incidence,
mortality and risk files -- zero unmapped, zero counter-examples of a non-NULL
`value` alongside either):
  - `suppressed_small_count` -> `value_status='suppressed_small_count'`. Per
    `notes_incidence.txt` (fetched from the V3 deposit, 2026-09-18): "Data has
    been suppressed to ensure confidentiality and stability of rate estimates.
    Counts are suppressed if fewer than 16 records were reported in a specific
    area-sex-race category."
  - `withheld_state_law` (incidence only) -> `value_status='not_available'`. Same
    file's `[P1 note]`: "Data not available because of state legislation and
    regulations which prohibit the release of county level data to outside
    entities." -- the state declined to submit, which is exactly SPEC.md's own
    example for `not_available`.
No `"3 or fewer"`, `"¶"` or `"§§"` sentinel forms exist anywhere in the real V1/V2/V3
bytes checked -- the brief's list of examples doesn't match this source; only the
two strings above are coded, and an unmapped third would raise `SystemExit` rather
than guess. `value_status` is derived from the same `TRY_CAST` that produces
`value`, not from `suppression_reason`'s presence alone (#148): a present rate
cell with no known `suppression_reason` that still fails to parse -- never
observed in the real files, but not ruled out by the schema -- lands
`not_available` rather than a numberless `reported` row.

**A real duplicate-row artifact, found only at full scale (Acceptance A).** SCP's
"By County" and "By State" comparison-report modes BOTH capture the national
aggregate row and DC's/Puerto Rico's rows (each is simultaneously a state and a
county-equivalent), so the real V3 file lands two raw rows for the same (fips,
sex, age, race, stage, cancer) -- verified exhaustively: every such duplicate key
has exactly one row of each `areatype`, never more. Values are identical in the
overwhelming majority (all 3,978 mortality duplicate groups; 7,293 of 7,683
incidence groups) but differ in a small remainder (390 incidence groups) -- SCP's
live data evidently drifted between the two capture times, which are hours apart
within one scrape run. Both raw rows are landed verbatim regardless (`raw.scp__*`
keeps both, unmodified); `_topic_frames` deterministically prefers the 'By
County' capture before deriving, so `measure.observation`'s business key stays
unique. This means the row COUNT that reproduces the vintage exactly is raw's
count minus these 11,661 real duplicate rows (7,683 incidence + 3,978
mortality), not raw's own count -- reported precisely in the PR's real-ingest
numbers, not hidden in an average.

**No `not_applicable` case, contrary to the brief's assumption.** `cancer='Cervix'
AND sex='Male'` and `cancer='Prostate' AND sex='Female'` are NOT suppressed or
flagged specially -- verified directly in the real V3 file: both combinations have
thousands of ordinary `reported` and `suppressed_small_count` rows, like any other
combination. SCP evidently still serves (or suppresses on count, same as any
county) these cells rather than marking them not-applicable. Reported honestly
rather than inventing a mapping with no evidence behind it; `not_applicable` is
simply never produced by this module.

**`recent_trend`** carries the source's trend call (`stable`/`rising`/`falling`)
verbatim, or two non-trend markers landed as `trend=NULL`: `"*"` (trend itself
could not be computed/is suppressed -- co-occurs with a suppressed rate in most
but not all rows: 198,574 V3 incidence rows have `recent_trend='*'` while the rate
is present and reported, i.e. trend suppression is independent of value
suppression) and `"[P1 note]"` (the same state-law withholding as above, on the
trend field). No `reliability_flag` exists anywhere in the real files -- SCP
publishes no separate reliability signal on the rate itself; always NULL here.

**`period_start`/`period_end` -- a genuine gap, not guessed around.** No row in
any vintage carries a real year: the `year` column is the literal constant
`"Latest 5-year average"` in every row of every vintage (verified). The actual
five-year window is stated only in `notes_incidence.txt`/`notes_mortality.txt`,
which exist **only in the V3 deposit** (added by the same 2026-08-24 scrape that
added `suppression_reason`); V1 and V2 ship no notes file and no period text
anywhere in their bytes. Quoting the real V3 notes (fetched 2026-09-18):
incidence `"All Cancer Sites (All Stages^), 2018-2022"`, mortality `"All Cancer
Sites, 2019-2023"` -- one constant window per topic, since SCP's own report
generation uses one current submission's window for every cancer site queried in
the same run (confirmed: the scraper always passes `year=0`, "latest", to every
query). **This module therefore only derives `measure.observation` for V3.** V1
and V2 land verbatim in raw (preserving them is the entire point of a vintage
lake) but are never turned into observation rows here -- inventing a V1/V2 period
with no evidence would violate AGENTS.md's "report honestly" gate. Revisit if a
real V1/V2 period surfaces (e.g. from the Internet Archive's own capture
metadata, per the scraper's `docs/wayback-assessment.md`, which found none either).

**Geography.** `areatype` and `locale_type` are both unreliable for level
(verified: `areatype='By County'` is constant even on the national aggregate row
in V1; `locale_type` misclassifies many real counties as `'other'` -- Louisiana
parishes, Alaska boroughs, DC, Puerto Rico -- per the scraper's own
`docs/coverage-drift.md`). Level is derived from the `fips` code's own shape
instead, which is unambiguous in the real data: `'00000'` -> nation; a 5-digit
code ending `'000'` -> state (its first two digits); anything else -> county. No
real county FIPS ends in `'000'` by construction, so this never misclassifies a
county as a state.

**`geo_vintage=2010`, uniformly, for every vintage (#22).** Verified directly in
both V1 (2024-08-02) and V3 (2026-08-24) real files: Connecticut carries only the
8 legacy counties (09001-09015) -- confirmed explicitly by `notes_incidence.txt`,
"This website still uses Connecticut counties instead of planning regions ... If/
when all data sources have new planning regions, then this website will switch to
using them" -- never the 9 planning regions (09110-09190); Alaska carries the
pre-2019 `02261 Valdez-Cordova`, not the post-split `02063`/`02066`; South Dakota
already carries the 2015 rename, `46102 Oglala Lakota`, not `46113 Shannon County`,
from the earliest vintage on. All three checks land in the same place (between the
2015 SD rename and the 2019 AK / 2022 CT changes) in every vintage checked -- no
drift observed between V1 and V3, so one constant applies to all three.

**Cancer sites** use SCP's own numeric codes (`select_options.json` in each Zenodo
deposit, verified byte-identical between V1 and V3) for `measure_id`, and are
bridged to `measure.cancer_site` (#31) by hand-translating SCP's combined-category
label to the matching SEER site-recode label already curated there (e.g. SCP's
"Colon & Rectum" -> SEER's "Colon and Rectum") and taking the lowest-numbered SEER
leaf code sharing that label as the representative FK -- several SEER leaf codes
share one SCP category, and any one of them names the same site. `"All Cancer
Sites"`, `"Breast (Female in situ)"`, the two `"Childhood ..."` age-based
aggregates, and `"Oral Cavity & Pharynx"` (verified: SEER's own "Oral Cavity and
Pharynx" text is a group heading with no numeric recode of its own, same as
`cancer_site.py` already found for other headings) resolve to no single leaf code
and stay NULL, per the issue's own "leave NULL otherwise". The lookup reads
`cancer_site.py`'s curated CSV directly (not a live `measure.cancer_site` scan --
its own `label` column holds each numeric code's individual SEER site_group text,
e.g. "Ascending Colon", not the rolled-up category name the CSV groups by), so it
resolves whether or not #31 has actually been ingested into this warehouse.

**Strata.** SCP crosses sex x age x race/ethnicity x stage (stage only where the
topic/vintage publishes one); `select_options.json` gives one closed vocabulary,
identical between V1 and V3, so one `scheme='SCP_RACE_2024'` covers every vintage
landed here (the "2024" reflects the vintages' own "based on the 2024 submission"
footnote, the newest hard evidence found, not a claim the categories themselves
will keep this name forever). An unmapped sex/age/race/stage value raises
`SystemExit` rather than silently landing as a NULL-keyed stratum.

**`risk` (screening & risk factors, V3 only) is landed to raw but not derived
here.** ponytail: its real geography split is messier than incidence/mortality --
`locale_type='county'` rows are DC/Puerto Rico only (BRFSS is state-level, not
county-level), and 41% of its rows carry `locale_type='other'` with unclear real
geography; its own race vocabulary also differs from (and contains a verbatim
upstream typo in) incidence/mortality's ("Asian /Pacifice Islander"). Deriving it
correctly needs its own investigation; land-only here so the vintage is at least
preserved. Follow-up: derive `raw.scp__risk` into `measure.observation`.

ponytail: `ci_rank`/`lower_ci_rank`/`upper_ci_rank` and
`percent_of_cases_with_late_stage` land in raw only -- distinct published
statistics from the main rate, out of this issue's scope to derive.
"""

import csv
import gzip
import io
import tempfile
import urllib.request
from pathlib import Path

import duckdb
import pyarrow as pa
from pyiceberg.expressions import And, EqualTo, In

from . import cancer_site, merge

USER_AGENT = "cancerbasemap/1.0 (+https://github.com/seandavi/cancer-basemap)"

# Vintage -> Zenodo record id / DOI. state-cancer-profile-scraper's data/vintages.json,
# cross-checked live against https://zenodo.org/api/records/<id>, 2026-09-18.
VINTAGES = {
    "V1": {"record": "12685787", "doi": "10.5281/zenodo.12685787"},
    "V2": {"record": "22085047", "doi": "10.5281/zenodo.22085047"},
    "V3": {"record": "22085273", "doi": "10.5281/zenodo.22085273"},
}

# The topics each vintage actually ships (verified against each record's file list).
VINTAGE_TOPICS = {
    "V1": ("incidence", "mortality"),
    "V2": ("incidence", "mortality"),
    "V3": ("incidence", "mortality", "risk"),
}

# Only vintages with a real, evidenced period (module docstring) get derived.
DERIVABLE_VINTAGES = {"V3"}
PERIOD = {
    ("incidence", "V3"): ("2018", "2022"),
    ("mortality", "V3"): ("2019", "2023"),
}

TOPIC_FILE = {
    "incidence": "state_cancer_profiles_incidence.csv.gz",
    "mortality": "state_cancer_profiles_mortality.csv.gz",
    "risk": "state_cancer_profiles_risk.csv.gz",
}

GEO_VINTAGE = 2010

# --- real column layouts, verified against actual downloaded bytes, 2026-09-18 ---

FULL_INCIDENCE_COLUMNS = (
    "reported_locale", "fips", "2023_rural_urban_continuum_codesrural_urban_note",
    "age_adjusted_rate_per_100_000", "lower_ci_rate", "upper_ci_rate", "ci_rank",
    "lower_ci_rank", "upper_ci_rank", "average_annual_count", "recent_trend",
    "recent_5_year_trend_in_rate", "lower_ci_trend_in_rate", "upper_ci_trend_in_rate",
    "year", "sex", "stage", "race", "cancer", "areatype", "age", "state_fips",
    "measurement", "locale_type", "_extracted_at", "url", "suppression_reason",
    "percent_of_cases_with_late_stage", "locale", "state",
)  # V3's real header -- the superset; V1/V2 lack some of these (filled NULL on landing).

INCIDENCE_COLUMNS = {
    "V1": tuple(c for c in FULL_INCIDENCE_COLUMNS
                if c not in ("2023_rural_urban_continuum_codesrural_urban_note",
                             "suppression_reason")),
    "V2": tuple(c for c in FULL_INCIDENCE_COLUMNS if c != "suppression_reason"),
    "V3": FULL_INCIDENCE_COLUMNS,
}

FULL_MORTALITY_COLUMNS = (
    "reported_locale", "fips", "2023_rural_urban_continuum_codesrural_urban_note",
    "age_adjusted_rate_per_100_000", "lower_ci_rate", "upper_ci_rate", "ci_rank",
    "lower_ci_rank", "upper_ci_rank", "average_annual_count", "recent_trend",
    "recent_5_year_trend_in_rate", "lower_ci_trend_in_rate", "upper_ci_trend_in_rate",
    "year", "sex", "stage", "race", "cancer", "areatype", "age", "state_fips",
    "measurement", "locale_type", "_extracted_at", "url", "suppression_reason",
    "locale", "state",
)  # union of V1/V2 (which carry `stage`) and V3 (which drops it, adds suppression_reason).

MORTALITY_COLUMNS = {
    "V1": tuple(c for c in FULL_MORTALITY_COLUMNS
                if c not in ("2023_rural_urban_continuum_codesrural_urban_note",
                             "suppression_reason")),
    "V2": tuple(c for c in FULL_MORTALITY_COLUMNS if c != "suppression_reason"),
    "V3": tuple(c for c in FULL_MORTALITY_COLUMNS if c != "stage"),
}

FULL_RISK_COLUMNS = (
    "reported_locale", "fips", "percent", "lower_ci_percent", "upper_ci_percent",
    "respondents", "topic", "topic_label", "risk", "risk_label", "race", "sex",
    "datatype", "statefips_query", "state_fips", "locale_type", "_extracted_at",
    "url", "suppression_reason", "model_based_percent3",
)  # V3 only -- no earlier vintage ships this topic.

RISK_COLUMNS = {"V3": FULL_RISK_COLUMNS}

TOPIC_COLUMNS = {"incidence": INCIDENCE_COLUMNS, "mortality": MORTALITY_COLUMNS,
                 "risk": RISK_COLUMNS}
TOPIC_FULL_COLUMNS = {"incidence": FULL_INCIDENCE_COLUMNS,
                      "mortality": FULL_MORTALITY_COLUMNS, "risk": FULL_RISK_COLUMNS}

# select_options.json's own vocabulary (identical between the V1 and V3 deposits,
# checked 2026-09-18) -- SCP's own numeric codes, used to build compact, stable ids.
CANCER_CODES = {
    "All Cancer Sites": "001", "Bladder": "071", "Brain & ONS": "076",
    "Breast (Female)": "055", "Breast (Female in situ)": "400", "Cervix": "057",
    "Childhood (Ages <15, All Sites)": "516", "Childhood (Ages <20, All Sites)": "515",
    "Colon & Rectum": "020", "Esophagus": "017", "Kidney & Renal Pelvis": "072",
    "Leukemia": "090", "Liver & Bile Duct": "035", "Lung & Bronchus": "047",
    "Melanoma of the Skin": "053", "Non-Hodgkin Lymphoma": "086",
    "Oral Cavity & Pharynx": "003", "Ovary": "061", "Pancreas": "040",
    "Prostate": "066", "Stomach": "018", "Thyroid": "080",
    "Uterus (Corpus & Uterus, NOS)": "058",
}
SEX_CODES = {"Both Sexes": "0", "Male": "1", "Female": "2"}
AGE_CODES = {"All Ages": "001", "<50": "009", "50+": "136", "<65": "006",
             "65+": "157", "Age < 15": "016", "Age < 20": "015"}
RACE_CODES = {"All Races (includes Hispanic)": "00", "White (Non-Hispanic)": "07",
              "Black (Non-Hispanic)": "28", "Amer. Indian / AK Native (Non-Hispanic)": "38",
              "Asian / Pacific Islander (Non-Hispanic)": "48", "Hispanic (any race)": "05"}
STAGE_CODES = {"All Stages": "999", "Late Stage (Regional & Distant)": "211"}

# SCP's combined-category label -> the matching SEER site-recode label already
# curated in measure.cancer_site (cancer_site.py). A handful of SCP categories
# (module docstring) have no single matching SEER leaf label and are omitted here
# on purpose -- they resolve to NULL, never a guess.
SCP_TO_SEER_LABEL = {
    "Bladder": "Urinary Bladder",
    "Brain & ONS": "Brain and Other Nervous System",
    "Breast (Female)": "Breast",
    "Cervix": "Cervix Uteri",
    "Colon & Rectum": "Colon and Rectum",
    "Esophagus": "Esophagus",
    "Kidney & Renal Pelvis": "Kidney and Renal Pelvis",
    "Leukemia": "Leukemia",
    "Liver & Bile Duct": "Liver and Intrahepatic Bile Duct",
    "Lung & Bronchus": "Lung and Bronchus",
    "Melanoma of the Skin": "Melanoma of the Skin",
    "Non-Hodgkin Lymphoma": "Non-Hodgkin Lymphoma",
    "Ovary": "Ovary",
    "Pancreas": "Pancreas",
    "Prostate": "Prostate",
    "Stomach": "Stomach",
    "Thyroid": "Thyroid",
    "Uterus (Corpus & Uterus, NOS)": "Corpus and Uterus, NOS",
}

# V3's real suppression_reason values -> the closed value_status enum (module
# docstring). Anything else found in a real file is a hard stop, not a guess.
SUPPRESSION_STATUS = {
    "suppressed_small_count": "suppressed_small_count",
    "withheld_state_law": "not_available",
}

UNITS = {"incidence": "per 100,000", "mortality": "per 100,000"}
AGE_ADJUSTMENT_NOTE = {
    "incidence": ("age-adjusted to the 2000 US standard population (SEER areas use "
                  "20 age groups and NPCR areas use 19 age groups)"),
    "mortality": "age-adjusted to the 2000 US standard population (20 age groups)",
}


def _zenodo_url(record, filename):
    return f"https://zenodo.org/api/records/{record}/files/{filename}/content"


def _fetch(url):
    """The file's bytes. A local path (tests) is read directly; a remote URL goes
    through urllib with a descriptive User-Agent."""
    if not url.startswith("http"):
        return Path(url).read_bytes()
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req) as r:
        return r.read()


def _header(raw_bytes, is_gz):
    """The file's header line, split on comma -- read straight from bytes rather
    than asked of DuckDB (mirrors places.py/cdc_svi.py's `_header`), since asking
    DuckDB to sniff a dialect from a `LIMIT 0` read is unreliable once delim/quote/
    escape are all pinned explicitly (verified: it refuses to sniff at all). For a
    `.gz` file, `GzipFile.readline()` decompresses only as much of the stream as
    the first line needs, not the whole file."""
    if is_gz:
        with gzip.GzipFile(fileobj=io.BytesIO(raw_bytes)) as gz:
            first = gz.readline()
    else:
        first = raw_bytes.split(b"\n", 1)[0]
    return tuple(first.decode("utf-8").rstrip("\r\n").split(","))


def _case(column, mapping):
    """SQL CASE over an explicit {value: mapped} dict -- no ELSE, so an unmapped
    input surfaces as NULL for the caller to catch (mirrors places.py's `_case`;
    duplicated rather than imported, since it's three lines)."""
    whens = " ".join(f"WHEN {column} = '{k}' THEN '{v}'" for k, v in mapping.items())
    return f"CASE {whens} END"


def _land_topic(cat, release, vintage, topic, url=None):
    """Phase 1 for one (vintage, topic): verbatim and whole, replaced per
    (scp_vintage, topic)."""
    columns = TOPIC_COLUMNS[topic][vintage]
    full_columns = TOPIC_FULL_COLUMNS[topic]
    identifier = f"raw.scp__{topic}"

    fetch_url = url or _zenodo_url(VINTAGES[vintage]["record"], TOPIC_FILE[topic])
    raw_bytes = _fetch(fetch_url)
    # Zenodo's own API URL (.../files/<name>/content) never ends in ".gz" even
    # though the file it serves is gzipped -- check the real topic filename when
    # no override was given; an explicit `url` override (tests: a local plain-text
    # fixture) is judged on its own extension instead.
    is_gz = TOPIC_FILE[topic].endswith(".gz") if url is None else url.endswith(".gz")
    if (header := _header(raw_bytes, is_gz)) != columns:
        raise SystemExit(f"scp: {fetch_url} header is not the declared {vintage} "
                         f"{topic} layout; differs in {sorted(set(header) ^ set(columns))}")

    with tempfile.NamedTemporaryFile(suffix=".csv.gz" if is_gz else ".csv") as tmp:
        tmp.write(raw_bytes)
        tmp.flush()
        con = duckdb.connect()
        # Dialect stated, not sniffed: comma-delimited, double-quoted where a cell
        # needs it (reported_locale carries a comma, e.g. "Autauga County, Alabama").
        # all_varchar keeps every sentinel ("*", "[P1 note]") as text, not a guess.
        select = ", ".join(f'"{c}"' if c in columns else f'NULL::VARCHAR AS "{c}"'
                           for c in full_columns)
        arrow = con.sql(f"""
            SELECT {select}, '{vintage}' AS scp_vintage, '{release}' AS landed_in
            FROM read_csv('{tmp.name}', header=true, all_varchar=true, delim=',',
                          quote='"', escape='"', nullstr='')
        """).to_arrow_table()
    if not arrow.num_rows:
        raise SystemExit(f"scp: {fetch_url} yielded no rows")

    n = merge.write(cat, identifier, arrow, EqualTo("scp_vintage", vintage))
    doi_url = f"https://doi.org/{VINTAGES[vintage]['doi']}"
    merge.manifest(cat, release, f"scp_{topic}", doi_url, n, version=vintage,
                   method="release_number")
    return n


def land_raw(cat, release, vintage=None, incidence_url=None, mortality_url=None,
            risk_url=None):
    """Phase 1: every topic one vintage publishes, verbatim and whole."""
    vintage = vintage or max(VINTAGES)
    if vintage not in VINTAGES:
        raise SystemExit(f"scp: unknown vintage {vintage!r}; known vintages: "
                         f"{sorted(VINTAGES)}")
    urls = {"incidence": incidence_url, "mortality": mortality_url, "risk": risk_url}
    counts = {f"raw.scp__{topic}": _land_topic(cat, release, vintage, topic, urls[topic])
             for topic in VINTAGE_TOPICS[vintage]}
    return vintage, counts


def _cancer_site_codes():
    """SEER combined-category label (cancer_site.py's curated CSV's own `label`
    column, e.g. 'Colon and Rectum') -> the lowest-numbered constituent
    cancer_site_code sharing that label. Read from the packaged CSV directly, not
    from a live `measure.cancer_site` scan: that table's own `label` column holds
    each numeric code's individual SEER site_group text (e.g. 'Ascending Colon'),
    not the rolled-up category name -- only the curated CSV groups codes by the
    combined name SCP's own site list uses. The codes are static curation, not
    runtime data, so this has no dependency on #31 having been ingested."""
    with open(cancer_site.CURATED_CSV, newline="") as f:
        by_label = {}
        for row in csv.DictReader(f):
            by_label.setdefault(row["label"], []).append(row["cancer_site_code"])
    return {label: min(codes) for label, codes in by_label.items()}


def _topic_frames(cat, release, vintage, topic):
    """One topic's measure.definition / measure.stratum / measure.observation
    Arrow tables -- no writes yet. Only called for vintages in DERIVABLE_VINTAGES
    (module docstring: period_start/period_end has no real evidence for V1/V2).

    Building frames separately from writing them is what lets `transform` combine
    incidence and mortality into ONE measure.observation write per vintage: SPEC.md's
    merge scope for that table is `(source, source_release)`, not `(source,
    source_release, topic)` -- two separate `merge.merge` calls sharing that scope
    would each treat the OTHER topic's already-stored rows as missing from its own
    "complete upstream state" and retire them (and since both calls land in the same
    release, `merge.merge`'s own "opened and retired in the same release is dropped"
    rule would then silently delete the first topic's rows entirely, verified by
    hand while building this module)."""
    period_start, period_end = PERIOD[(topic, vintage)]
    con = duckdb.connect()
    con.register("raw_landed", cat.load_table(f"raw.scp__{topic}").scan(
        row_filter=EqualTo("scp_vintage", vintage)).to_arrow())

    # SCP's "By County" and "By State" comparison-report modes BOTH capture the
    # national aggregate row and DC's/Puerto Rico's rows (each is simultaneously
    # a state and a county-equivalent), so the real file lands two raw rows for
    # the same (fips, sex, age, race, stage, cancer) -- verified at full scale on
    # the real V3 files: every such duplicate key has exactly one row of each
    # areatype, never more; values are identical in the overwhelming majority
    # (all of mortality's duplicates, 7293/7683 of incidence's) but differ in a
    # small remainder (390/7683 incidence groups) -- SCP's live data evidently
    # drifted between the two capture times, hours apart within one scrape run.
    # Both raw rows are landed verbatim regardless (raw.scp__* keeps both); this
    # deterministically prefers the 'By County' capture so measure.observation's
    # business key stays unique, rather than the merge failing on a real
    # upstream artifact this module cannot land two versions of within one key.
    con.execute("""
        CREATE OR REPLACE TABLE raw AS
        SELECT * FROM raw_landed
        QUALIFY row_number() OVER (
            PARTITION BY fips, sex, age, race, stage, cancer
            ORDER BY (areatype = 'By County') DESC
        ) = 1
    """)

    # Every distinct value actually present must be a known one -- an upstream
    # addition surfaces as SystemExit, never a silently NULL-keyed row.
    def _known(column, mapping, allow_null=False):
        seen = {v for (v,) in con.sql(f"SELECT DISTINCT {column} FROM raw").fetchall()
               if not (allow_null and v is None)}
        if bad := seen - set(mapping):
            raise SystemExit(f"scp: unknown {column} value(s) in {vintage} {topic}: "
                             f"{sorted(bad, key=str)}")

    _known("cancer", CANCER_CODES)
    _known("sex", SEX_CODES)
    _known("age", AGE_CODES)
    _known("race", RACE_CODES)
    _known("stage", STAGE_CODES, allow_null=True)
    suppression_seen = {v for (v,) in
                        con.sql("SELECT DISTINCT suppression_reason FROM raw "
                               "WHERE suppression_reason IS NOT NULL").fetchall()}
    if bad := suppression_seen - set(SUPPRESSION_STATUS):
        raise SystemExit(f"scp: unknown suppression_reason value(s) in {vintage} "
                         f"{topic}: {sorted(bad)}")

    cancer_case = _case("cancer", CANCER_CODES)
    sex_case = _case("sex", SEX_CODES)
    age_case = _case("age", AGE_CODES)
    race_case = _case("race", RACE_CODES)
    stage_case = _case("stage", STAGE_CODES)
    status_case = _case("suppression_reason", SUPPRESSION_STATUS)

    seer_codes = _cancer_site_codes()
    site_map = {scp_label: seer_codes[seer_label]
               for scp_label, seer_label in SCP_TO_SEER_LABEL.items()
               if seer_label in seer_codes}
    # _case's CASE...END has no ELSE, so an empty mapping would be a bare
    # "CASE END" -- invalid SQL (site_map is never actually empty against the
    # real curated CSV; this guard is only for a test that empties it).
    # NULL::VARCHAR stands in for "nothing resolves", the same outcome.
    site_code_case = _case("cancer", site_map) if site_map else "NULL::VARCHAR"

    definition = con.sql(f"""
        SELECT DISTINCT
               'SCP:{topic}:' || {cancer_case} AS measure_id, 'SCP' AS source,
               cancer AS label, '{UNITS[topic]}' AS units, NULL::VARCHAR AS universe,
               'per_100000' AS rate_basis, '2000 US standard population' AS age_adjustment,
               'direct' AS method, {site_code_case} AS cancer_site_code,
               'State Cancer Profiles ' || '{topic}' || ' rate for ' || cancer ||
                   ', {AGE_ADJUSTMENT_NOTE[topic]}.' AS doc
        FROM raw
    """).to_arrow_table()

    stratum = con.sql(f"""
        SELECT DISTINCT
               'SCP:' || {sex_case} || ':' || {age_case} || ':' || {race_case} || ':' ||
                   COALESCE({stage_case}, 'NA') AS stratum_id, 'SCP' AS source,
               sex AS sex, age AS age_group, race AS race_ethnicity, stage AS stage,
               NULL::VARCHAR AS other, 'SCP_RACE_2024' AS scheme
        FROM raw
    """).to_arrow_table()

    observation = con.sql(f"""
        SELECT 'SCP' AS source, '{vintage}' AS source_release,
               'SCP:{topic}:' || {cancer_case} AS measure_id,
               CASE WHEN fips = '00000' THEN 'nation:US'
                    WHEN fips LIKE '%000' THEN 'state:' || substr(fips, 1, 2)
                    ELSE 'county:' || fips END AS geo_id,
               {GEO_VINTAGE} AS geo_vintage,
               '{period_start}' AS period_start, '{period_end}' AS period_end,
               'SCP:' || {sex_case} || ':' || {age_case} || ':' || {race_case} || ':' ||
                   COALESCE({stage_case}, 'NA') AS stratum_id,
               TRY_CAST(age_adjusted_rate_per_100_000 AS DOUBLE) AS value,
               TRY_CAST(lower_ci_rate AS DOUBLE) AS lower,
               TRY_CAST(upper_ci_rate AS DOUBLE) AS upper,
               0.95 AS interval_level,
               TRY_CAST(average_annual_count AS DOUBLE) AS numerator,
               NULL::DOUBLE AS denominator,
               -- Status follows the same TRY_CAST that produces `value`, not just
               -- suppression_reason's presence -- a present-but-non-numeric rate
               -- cell with no known suppression_reason (never seen in the real
               -- V1/V2/V3 files, verified 2026-09-18) must not land as a
               -- numberless 'reported' row (#148, merge.check_observations).
               CASE WHEN suppression_reason IS NOT NULL THEN {status_case}
                    WHEN TRY_CAST(age_adjusted_rate_per_100_000 AS DOUBLE) IS NOT NULL
                        THEN 'reported'
                    ELSE 'not_available' END
                   AS value_status,
               NULL::VARCHAR AS reliability_flag,
               CASE WHEN recent_trend IN ('*', '[P1 note]') THEN NULL ELSE recent_trend END
                   AS trend
        FROM raw
    """).to_arrow_table()
    return definition, stratum, observation


def transform(cat, release, vintage):
    """Phase 2 for one vintage: measure.definition / measure.stratum / one combined
    measure.observation write across every derivable topic (incidence, mortality --
    module docstring on why risk is excluded and why this must be one write)."""
    if vintage not in DERIVABLE_VINTAGES:
        raise SystemExit(f"scp: {vintage} has no evidenced period_start/period_end "
                         f"(module docstring); only {sorted(DERIVABLE_VINTAGES)} can "
                         f"be derived into measure.observation. Use land_raw to land "
                         f"{vintage} verbatim without deriving it.")
    topics = [t for t in ("incidence", "mortality") if (t, vintage) in PERIOD]
    frames = [_topic_frames(cat, release, vintage, topic) for topic in topics]
    definition = pa.concat_tables([f[0] for f in frames])
    # Different topics can share a (sex, age, race, stage) combination and so the
    # same stratum_id -- dedupe on the business key before writing, rather than
    # handing the table duplicate rows for one id.
    con = duckdb.connect()
    con.register("concatenated_stratum", pa.concat_tables([f[1] for f in frames]))
    stratum = con.sql("SELECT * FROM concatenated_stratum "
                      "QUALIFY row_number() OVER (PARTITION BY stratum_id) = 1"
                      ).to_arrow_table()
    observation = pa.concat_tables([f[2] for f in frames])
    merge.check_observations(observation)

    scope = EqualTo("source", "SCP")
    def_ids = definition.column("measure_id").to_pylist()
    stratum_ids = stratum.column("stratum_id").to_pylist()
    return {
        "measure.definition": merge.write(cat, "measure.definition", definition,
                                          And(scope, In("measure_id", def_ids))),
        "measure.stratum": merge.write(cat, "measure.stratum", stratum,
                                       And(scope, In("stratum_id", stratum_ids))),
        "measure.observation": merge.merge(
            cat, "measure.observation", observation, release,
            And(scope, EqualTo("source_release", vintage))),
    }


def ingest(cat, release, vintage=None, incidence_url=None, mortality_url=None,
          risk_url=None):
    """Land every topic one vintage publishes; derive measure.* only where the
    vintage's period is real evidence, not a guess (module docstring)."""
    vintage, counts = land_raw(cat, release, vintage, incidence_url, mortality_url,
                               risk_url)
    if vintage in DERIVABLE_VINTAGES:
        counts.update(transform(cat, release, vintage))
    return counts
