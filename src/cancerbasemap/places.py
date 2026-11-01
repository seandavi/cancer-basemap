"""CDC PLACES: Local Data for Better Health, COUNTY data -> Iceberg.

Model-based small-area estimates for chronic disease, screening and behavioral
risk factors, at (county, measure, stratification-type) grain (SPEC.md §
Sources — first tranche: "model-based tract/county screening & behaviors").

**Licence.** Public domain. The dataset's own Socrata metadata states
`"license": {"name": "Public Domain"}` (checked against
https://data.cdc.gov/api/views/swc5-untb.json, 2026-09-18), attributed to
"Centers for Disease Control and Prevention, National Center for Chronic
Disease Prevention and Health Promotion, Division of Population Health"; see
also https://www.cdc.gov/places.

**Version axis: the annual release is a separate Socrata dataset.** PLACES
does not version one URL — each year's county file is its own dataset id on
data.cdc.gov, discovered via the Socrata catalog API
(`https://api.us.socrata.com/api/catalog/v1?domains=data.cdc.gov&q=PLACES
county data release`, checked 2026-09-18). `RELEASES` records every
long-format "...County Data <year> release" id found that way — NOT the
parallel "County Data (GIS Friendly Format)" datasets, which are wide
(one row per county) rather than the long (one row per county/measure/type)
shape this module wants. `source_release` downstream is the release year
label itself (PLACES publishes no separate release-number scheme).

**The header is not stable across editions.** `COLUMNS` states the CURRENT
shape — verified identical on the 2024 and 2025 releases, the two this module
actually lands (see docstring below) — and lands only those; an older
release fails the header check by design rather than silently mis-landing
(mirrors hgnc.py's dated-archive handling):
  - the 2020 export (`dv4u-3x3q`) has no `LocationID` at all — a `Latitude`
    column holding real latitude text sits in its place, and its point column
    is misspelled `Geolocatioin` — upstream's own defect, confirmed against
    https://data.cdc.gov/api/views/dv4u-3x3q.json's column list, not a scrape
    artifact.
  - 2021-2023 lack `TotalPop18plus` (added starting with the 2024 release).
ponytail: only the 2024/2025 header is supported. Landing an older release
means declaring its own COLUMNS first, same as hgnc.py's dated archives.

**Geography vintage moves mid-series.** Connecticut's `LocationID`s are the
legacy 8 counties (09001-09015) through the 2023 release and the 9 planning
regions (09110-09190) from the 2024 release on — verified directly against
each release's real file (PLACES' own methodology notes the 2022 Census
change but not which release picks it up). `GEO_VINTAGE` records 2010 for the
legacy-county releases and 2020 for the planning-region ones, the same two
vintage labels SPEC.md's Milestones use for the pre/post-2022 Census county
definitions.

**Suppression.** The only footnote either landed release carries is
"Estimates suppressed for population less than 50" (0 rows in the 2024
release, 66 in 2025) -> `value_status = 'suppressed_small_count'`.
`FOOTNOTE_STATUS` enumerates it explicitly; any other footnote text raises
`SystemExit` in `transform` rather than guessing. `value_status` is derived
from the same `TRY_CAST` that produces `value` (a genuinely empty cell looks
up its footnote; a present-but-non-numeric one -- never seen in the real
files, verified 2026-09-19 -- falls back to `not_available` rather than
guessing "suppressed"), not from `Data_Value`'s raw presence: the two used to
disagree, landing a present-but-malformed cell as a numberless 'reported' row
(#148; `merge.check_observations`'s reverse guard now catches any regression).

**No cervix/lung screening measure in county data.** The county file's 40
measures include `COLON_SCREEN` (colorectal) and `MAMMOUSE` (mammography) but
no cervical-cancer-screening measure — BRFSS dropped that module from the
data years this dataset draws on. All 40 measures land and derive regardless
of cancer relevance, per instructions.

ponytail: `TotalPopulation`/`TotalPop18plus` are NOT this measure's
denominator — PLACES publishes model-based prevalence with no published
numerator/denominator pair, only the population the estimate covers. They
land in raw and stay there; `measure.observation.denominator` is NULL.

ponytail: `measure.definition` has no `valid_from`/`valid_to` — it is a
lookup table, not Type-2 versioned (SPEC.md). Interim fix for #76: this
module overwrites only the `measure_id`s it asserts this release
(`And(EqualTo("source", "PLACES"), In("measure_id", ids))`), not the whole
`source = 'PLACES'` scope, so a later release that drops a measure
(`ISOLATION` -> `LONELINESS` in 2025 — same slot, different MeasureId, real
data, checked directly) no longer deletes the earlier definition its still-
live 2024 `measure.observation` rows reference. It does NOT give
measure.definition history: if a `measure_id` that persists across releases
changes its label/universe text, the newer release's text still silently
overwrites the older one in place. The real fix (Type-2 measure.definition,
or another option) is part of #19's versioning decision.

**Tract data (#30), the same house rules extended, not copied.** `TRACT_RELEASES`
records every "...Census Tract Data <year> release" dataset id, found the same way
as `RELEASES` (Socrata catalog API, `q=PLACES Census Tract Data release`, plus a
follow-up query for 2024 specifically since one catalog page missed it; checked
2026-09-18):
    2020 4ai3-zynv, 2021 373s-ayzu, 2022 nw2y-v4gm, 2023 em5e-5hvn,
    2024 ai6z-tcin, 2025 cwsq-ngmh.
Same licence (each dataset's own Socrata metadata: `"license": {"name": "Public
Domain"}`, checked directly on cwsq-ngmh and ai6z-tcin, 2026-09-18).

**The tract header is its own contract, verified against the real files, not
guessed from the county shape.** `TRACT_COLUMNS` is the 2024/2025 tract header —
only these two are landed, same policy as county and for the same reason (2020-2023
lack `TotalPop18plus`, confirmed against each real file's first line). It is NOT
`COLUMNS` plus a `TractFIPS` column: the real tract file has no such column.
`CountyFIPS`/`CountyName` are new (the county file has neither, since it *is* the
county); `LocationID` holds the 11-digit tract FIPS, and — an upstream quirk,
verified against real rows — `LocationName` holds that same 11-digit tract FIPS
again, not a human name, unlike the county file where `LocationName` is the county
name.

**Tract publishes crude prevalence only.** Verified via the Socrata SODA API
against every landed release (`$select=distinct(data_value_type)` on cwsq-ngmh
returns only "Crude prevalence"; `count(distinct(measureid))` is 40, matching
county's measure count). `transform` therefore reuses the *same*
`PLACES:<MeasureId>:crude` ids county's crude rows already assert — tract mints no
measure_ids of its own. To make that safe when both levels feed one `defs` query,
`transform` raises `SystemExit` if county and tract ever disagree on a measure's
label/category/unit text for the same id, rather than silently picking one (they
agree on every id checked: e.g. CSMOKING's `Measure` text is verbatim identical in
both files).

**No suppression in the tract editions actually landed.** Checked directly via the
SODA API (`count(*) where data_value_footnote is not null` and
`where data_value is null`, both 0) against cwsq-ngmh (2025) and ai6z-tcin (2024) —
every one of ~3M rows in each is `reported`. (2020-2022 do have exactly one
unfootnoted-but-null row each — a genuine upstream anomaly — but those releases
aren't landed here anyway.) `FOOTNOTE_STATUS` is still enforced on tract rows via
the same shared `raise SystemExit` path as county, in case a future release
introduces one.

**Geography vintage moves at the same release as county, verified independently
for tract.** Tract count jumps from 72,337 (2023, `em5e-5hvn`) to 83,522 (2024,
`ai6z-tcin`) — consistent with the 2010-vintage (~73k) to 2020-vintage (~85k) tract
count change, not a partial update. Connecticut's `CountyFIPS` values confirm it
directly: 09001-09015 (legacy counties) in the 2023 file, 09110-09190 (planning
regions) in the 2024 file — the identical switch point `GEO_VINTAGE` already
records for county, so tract reuses that same dict rather than a second one.

**Tract files are large: ~2.9M-3.2M rows per release** (2,555,113 in 2023;
3,183,048 in 2024; 3,047,284 in 2025 — SODA `count(*)`), 40 measures x ~72-84k
tracts x crude-only, versus county's few hundred thousand. `land_raw` streams a
remote tract download to a temp file in fixed-size chunks (`_download`) before
DuckDB parses it from disk, rather than handing DuckDB the URL directly the way
the much smaller county file does: the two don't need to hold the whole response
in memory as bytes *and* as an Arrow table at once. Measured against the real 2025
files end to end (`land_raw` + `transform`, county then tract, county's 229,298
raw rows + tract's 3,047,284): peak RSS 15.4 GB, wall clock 15.8s (`/usr/bin/time
-v` on the ingest host, 2026-09-18) — tract's own `land_raw`+`transform` alone
peaks at 10.1 GB in 3s. Comfortably one process's job at that size; not the
71.5M-row scale (25x this) where `bioc-on-ice`'s `ncbi.py::_land` batches reads
and commits — that's the upgrade path if a future tract file's row count grows
into that range, not needed here.

ponytail: tract shares `land_raw`'s county code path via a `level` parameter
(mirrors `cdc_svi.py`'s single `land_raw(..., level=...)`) rather than a second
function, since the only real differences are the dataset-id table, the column
contract, and (tract only) the temp-file download. `transform` similarly derives
from a `raw` view that unions whichever of `raw.places__county` /
`raw.places__tract` are landed for a release (`cdc_svi.py`'s same fix for the same
problem: `measure.observation`'s merge scope is `(source, source_release)`, not
per-level, so deriving from one level alone would retire the other level's rows
landed earlier under the same release).
"""

import re
import shutil
import tempfile
import urllib.request

import duckdb
import pyarrow as pa
from pyiceberg.exceptions import NoSuchTableError
from pyiceberg.expressions import And, EqualTo, In

from . import lineage, merge

# data.cdc.gov dataset id for each "PLACES: Local Data for Better Health,
# County Data <year> release" (long format; NOT "GIS Friendly Format", which
# is wide). Found via the Socrata catalog API, confirmed against each
# dataset's own metadata, 2026-09-18.
RELEASES = {
    "2020": "dv4u-3x3q",
    "2021": "pqpp-u99h",
    "2022": "duw2-7jbt",
    "2023": "h3ej-a9ec",
    "2024": "fu4u-a9bh",
    "2025": "swc5-untb",
}

# Connecticut's county -> planning-region switch (Census, 2022) lands in the
# 2024 PLACES release (LocationIDs 09110-09190); 2020-2023 still carry the 8
# legacy counties (09001-09015) — checked against each release's real file.
GEO_VINTAGE = {"2020": 2010, "2021": 2010, "2022": 2010, "2023": 2010,
               "2024": 2020, "2025": 2020}

# The CSV header, in file order — the 2024/2025 shape (see module docstring
# for why earlier releases differ and are not supported by this contract).
COLUMNS = (
    "Year", "StateAbbr", "StateDesc", "LocationName", "DataSource", "Category",
    "Measure", "Data_Value_Unit", "Data_Value_Type", "Data_Value",
    "Data_Value_Footnote_Symbol", "Data_Value_Footnote", "Low_Confidence_Limit",
    "High_Confidence_Limit", "TotalPopulation", "TotalPop18plus", "LocationID",
    "CategoryID", "MeasureId", "DataValueTypeID", "Short_Question_Text",
    "Geolocation",
)

# data.cdc.gov dataset id for each "PLACES: Local Data for Better Health, Census
# Tract Data <year> release" (#30). Found the same way as RELEASES.
TRACT_RELEASES = {
    "2020": "4ai3-zynv",
    "2021": "373s-ayzu",
    "2022": "nw2y-v4gm",
    "2023": "em5e-5hvn",
    "2024": "ai6z-tcin",
    "2025": "cwsq-ngmh",
}

# The tract CSV header, in file order — the 2024/2025 shape (module docstring:
# only these two are landed, for the same TotalPop18plus reason as county). Its
# own contract: CountyFIPS/CountyName are new, there is no Geolocation-adjacent
# TractFIPS column, and LocationName duplicates LocationID rather than naming
# anything (both hold the 11-digit tract FIPS).
TRACT_COLUMNS = (
    "Year", "StateAbbr", "StateDesc", "CountyName", "CountyFIPS", "LocationName",
    "DataSource", "Category", "Measure", "Data_Value_Unit", "Data_Value_Type",
    "Data_Value", "Data_Value_Footnote_Symbol", "Data_Value_Footnote",
    "Low_Confidence_Limit", "High_Confidence_Limit", "TotalPopulation",
    "TotalPop18plus", "Geolocation", "LocationID", "CategoryID", "MeasureId",
    "DataValueTypeID", "Short_Question_Text",
)

DATA_VALUE_TYPE = {"Crude prevalence": "crude", "Age-adjusted prevalence": "age_adjusted"}

# value_status for every distinct suppression footnote seen in the two landed
# releases (SPEC.md Acceptance C). An unmapped footnote is a hard stop, not a
# silent default.
FOOTNOTE_STATUS = {
    "Estimates suppressed for population less than 50": "suppressed_small_count",
}


def _url(dataset_id):
    return f"https://data.cdc.gov/api/views/{dataset_id}/rows.csv?accessType=DOWNLOAD"


def _header(url):
    """The file's first line, split on comma. Only that line is fetched."""
    if url.startswith("http"):
        req = urllib.request.Request(url, headers={"User-Agent": "cancerbasemap/0.1"})
        with urllib.request.urlopen(req) as r:
            first = r.readline()
    else:
        with open(url) as r:
            first = r.readline()
    if isinstance(first, bytes):
        first = first.decode("utf-8", "replace")
    return tuple(first.rstrip("\r\n").split(","))


def _case(column, mapping):
    """SQL CASE over an explicit {value: mapped_value} dict — no ELSE, so an
    unmapped input surfaces as NULL for the caller to catch, never a guess."""
    whens = " ".join(f"WHEN {column} = '{k}' THEN '{v}'" for k, v in mapping.items())
    return f"CASE {whens} END"


def _download(url, dest):
    """Stream `url`'s bytes to the local path `dest`, chunked. Tract files are large
    (module docstring: ~2.9-3.2M rows) -- unlike `_header`'s one-line peek, downloading
    the whole thing must not hold it as one bytes object in memory at the same time
    DuckDB is about to materialize it again as an Arrow table."""
    req = urllib.request.Request(url, headers={"User-Agent": "cancerbasemap/0.1"})
    with urllib.request.urlopen(req) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f, length=1024 * 1024)


def _load(cat, identifier, source, columns, places_release):
    """Phase 1's DuckDB read, shared by both levels: parse `source` (a URL or local
    path) under `columns`' contract and overwrite `identifier`'s rows for this release."""
    con = duckdb.connect()
    select = ", ".join(f'"{c}"' for c in columns)
    # Dialect stated, not sniffed: plain comma-delimited, double-quoted where a
    # cell needs it (Measure text never contains a comma; Geolocation's WKT
    # POINT does not either). all_varchar keeps raw unparsed; an empty cell is
    # PLACES' missing marker and reads as NULL.
    arrow = con.sql(f"""
        SELECT {select}, '{places_release}' AS places_release
        FROM read_csv('{source}', header=true, all_varchar=true, delim=',',
                      quote='"', escape='"', nullstr='')
    """).to_arrow_table()
    if not arrow.num_rows:
        raise SystemExit(f"places: {source} yielded no rows")
    return merge.write(cat, identifier, arrow, EqualTo("places_release", places_release))


def land_raw(cat, release, places_release=None, level="county", url=None):
    """Phase 1: one county- or tract-data release, verbatim and whole.

    `places_release` selects a year from RELEASES/TRACT_RELEASES (default: the
    latest known for `level`); `url` overrides the download, e.g. an
    already-fetched fixture in tests. A remote tract download is streamed to a
    temp file before DuckDB parses it (module docstring: tract files are too
    large to treat like county's direct URL read). Returns (places_release, rows).
    """
    releases = RELEASES if level == "county" else TRACT_RELEASES
    columns = COLUMNS if level == "county" else TRACT_COLUMNS
    identifier = f"raw.places__{level}"

    places_release = places_release or max(releases, key=int)
    if places_release not in releases:
        raise SystemExit(f"places: no known {level} dataset id for release {places_release!r}; "
                         f"known releases: {sorted(releases)}")
    fetch_url = url or _url(releases[places_release])
    if (header := _header(fetch_url)) != columns:
        raise SystemExit(f"places: {fetch_url} header is not the declared one; "
                         f"differs in {sorted(set(header) ^ set(columns))}")

    if level == "tract" and fetch_url.startswith("http"):
        with tempfile.NamedTemporaryFile(suffix=".csv") as tmp:
            _download(fetch_url, tmp.name)
            n = _load(cat, identifier, tmp.name, columns, places_release)
    else:
        n = _load(cat, identifier, fetch_url, columns, places_release)

    merge.manifest(cat, release, "places" if level == "county" else "places_tract",
                   fetch_url, n, version=places_release, method="release_number")
    lineage.record(cat, release, "places", None, {identifier: fetch_url})
    return places_release, n


def _universe(measure_text):
    """The population a measure is computed over, read off the source's own
    sentence (SPEC.md: 'universe from the measure text where it states one').
    PLACES states it as '... among <universe>'; a bare 'adults' is BRFSS' own
    shorthand for 'adults aged >=18 years', confirmed against the PLACES data
    dictionary's fuller historical measure names (m35w-spkz, 2026-09-18)."""
    m = re.search(r"among (.+)$", measure_text)
    if not m:
        return None
    text = m.group(1)
    return "adults aged >=18 years" if text == "adults" else text


def _level_select(level):
    """One level's rows from `{level}_raw`, with geo_id computed to a shared shape so
    the rest of `transform` doesn't need to know which level produced a row (tract has
    no county/nation split: every LocationID there is an 11-digit tract FIPS)."""
    geo_expr = ("CASE WHEN StateAbbr = 'US' THEN 'nation:US' "
                "ELSE 'county:' || lpad(LocationID, 5, '0') END" if level == "county"
               else "'tract:' || lpad(LocationID, 11, '0')")
    return f"""
        SELECT Year, MeasureId, Data_Value_Type, Measure, Category, Data_Value_Unit,
               Short_Question_Text, Data_Value, Low_Confidence_Limit,
               High_Confidence_Limit, Data_Value_Footnote, {geo_expr} AS geo_id
        FROM {level}_raw
    """


def transform(cat, release, places_release):
    """Phase 2: measure.definition / measure.stratum / measure.observation.

    Derives from a `raw` view that unions whichever of raw.places__county /
    raw.places__tract are actually landed for `places_release` (cdc_svi.py's fix
    for the same problem): measure.observation's merge scope below is (source,
    source_release), not per-level, so deriving from one level's raw table alone
    would retire the other level's rows landed earlier under the same release.
    """
    geo_vintage = GEO_VINTAGE[places_release]
    con = lineage.connect()
    selects = []
    for level in ("county", "tract"):
        try:
            lineage.load(con, cat, f"{level}_raw", f"raw.places__{level}",
                        row_filter=EqualTo("places_release", places_release))
        except NoSuchTableError:
            continue  # this level has never been landed at all yet
        selects.append(_level_select(level))
    if not selects:
        raise SystemExit(f"places: neither raw.places__county nor raw.places__tract "
                         f"is landed for release {places_release!r}")
    con.execute(f"CREATE OR REPLACE TABLE raw AS {' UNION ALL '.join(selects)}")

    # Checked in Python, not SQL: a plain membership test sidesteps quoting a
    # dict of arbitrary text into an IN-list (and an empty dict, when a test
    # wants to force the "unmapped" branch, breaks IN()'s SQL syntax anyway).
    seen_types = {t for (t,) in con.sql("SELECT DISTINCT Data_Value_Type FROM raw").fetchall()}
    if bad_type := seen_types - set(DATA_VALUE_TYPE):
        raise SystemExit(f"places: unknown Data_Value_Type(s): {sorted(bad_type)}")

    footnotes = con.sql("SELECT DISTINCT Data_Value_Footnote FROM raw "
                        "WHERE Data_Value IS NULL").fetchall()
    if unmapped := {f for (f,) in footnotes if f not in FOOTNOTE_STATUS}:
        raise SystemExit(f"places: unmapped suppression footnote(s) in {places_release}: "
                         f"{sorted(unmapped, key=str)}")

    dvt_case = _case("Data_Value_Type", DATA_VALUE_TYPE)

    # County and tract are unioned above into one `raw`, and tract reuses county's
    # own measure_ids (module docstring: no tract-specific ids minted) -- so before
    # trusting DISTINCT to give one definition row per id, check the two levels
    # actually agree on its text; a real disagreement should fail loudly, not pick
    # one arbitrarily.
    ambiguous = con.sql(f"""
        SELECT MeasureId, {dvt_case} AS variant
        FROM raw
        GROUP BY 1, 2
        HAVING count(DISTINCT Measure || '|' || Category || '|' || Data_Value_Unit
                     || '|' || Short_Question_Text) > 1
    """).fetchall()
    if ambiguous:
        raise SystemExit(f"places: county and tract disagree on measure text for "
                         f"{ambiguous}")

    # One measure.definition row per (MeasureId, Data_Value_Type) — the two
    # variants are different measures (crude vs. age-adjusted prevalence of
    # the same thing), not a stratification of one.
    defs_sql = f"""
        SELECT DISTINCT MeasureId, {dvt_case} AS variant, Measure, Category,
               Data_Value_Unit, Short_Question_Text
        FROM raw
    """
    defs = con.sql(defs_sql).fetchall()
    definition_rows = [
        dict(measure_id=f"PLACES:{measure_id}:{variant}", source="PLACES",
             label=short_text, units=unit, universe=_universe(measure_text),
             rate_basis="percent",
             age_adjustment="2000 US standard population" if variant == "age_adjusted" else None,
             method="model_based", cancer_site_code=None,
             doc=f"{measure_text}. Category: {category}.")
        for measure_id, variant, measure_text, category, unit, short_text in defs
    ]
    definition = pa.Table.from_pylist(definition_rows)

    # PLACES publishes no stratification within a county estimate — one
    # all-persons stratum covers every row.
    stratum_rows = [dict(
        stratum_id="PLACES:ALL", source="PLACES", sex=None, age_group=None,
        race_ethnicity=None, stage=None, other=None, scheme="PLACES_TOTAL",
    )]
    stratum = pa.Table.from_pylist(stratum_rows)

    value_status = _case("Data_Value_Footnote", FOOTNOTE_STATUS)
    observation_sql = f"""
        SELECT 'PLACES' AS source, '{places_release}' AS source_release,
               'PLACES:' || MeasureId || ':' || {dvt_case} AS measure_id,
               geo_id,
               {geo_vintage} AS geo_vintage,
               Year AS period_start, Year AS period_end,
               'PLACES:ALL' AS stratum_id,
               TRY_CAST(Data_Value AS DOUBLE) AS value,
               TRY_CAST(Low_Confidence_Limit AS DOUBLE) AS lower,
               TRY_CAST(High_Confidence_Limit AS DOUBLE) AS upper,
               0.95 AS interval_level,
               NULL::DOUBLE AS numerator,
               -- TotalPopulation/TotalPop18plus are not this measure's
               -- denominator (see module docstring); they stay in raw only.
               NULL::DOUBLE AS denominator,
               -- Status follows the same TRY_CAST that produces `value`, not
               -- the raw cell's presence -- a present-but-non-numeric
               -- Data_Value (never seen in the real files, verified
               -- 2026-09-19) must not land as a numberless 'reported' row
               -- (merge.check_observations; #148). The footnote case only
               -- ever runs for a genuinely empty cell (pre-checked above
               -- against FOOTNOTE_STATUS); 'not_available' is the fallback
               -- for the never-seen malformed-but-present case, matching
               -- ers_rucc.py's fix for the same shape.
               CASE WHEN TRY_CAST(Data_Value AS DOUBLE) IS NOT NULL THEN 'reported'
                    WHEN Data_Value IS NULL THEN {value_status}
                    ELSE 'not_available' END AS value_status,
               NULL::VARCHAR AS reliability_flag,
               NULL::VARCHAR AS trend
        FROM raw
    """
    observation = con.sql(observation_sql).to_arrow_table()
    merge.check_observations(observation)

    # Overwrite only the ids this release asserts, not the whole `source =
    # 'PLACES'` scope — a wholesale replace deleted a live definition a live
    # observation still referenced (#76).
    result = {
        "measure.definition": merge.write(
            cat, "measure.definition", definition,
            And(EqualTo("source", "PLACES"),
                In("measure_id", [r["measure_id"] for r in definition_rows]))),
        "measure.stratum": merge.write(
            cat, "measure.stratum", stratum,
            And(EqualTo("source", "PLACES"),
                In("stratum_id", [r["stratum_id"] for r in stratum_rows]))),
        "measure.observation": merge.merge(
            cat, "measure.observation", observation, release,
            And(EqualTo("source", "PLACES"), EqualTo("source_release", places_release))),
    }
    # measure.stratum has no SQL behind it at all (stratum_rows is a hand-written
    # Python literal, module docstring) -- no lineage to honestly claim for it.
    lineage.record(cat, release, "places", con, {
        "measure.definition": defs_sql,
        "measure.stratum": None,
        "measure.observation": observation_sql,
    })
    return result


def ingest(cat, release, places_release=None, url=None, level="county"):
    places_release, n = land_raw(cat, release, places_release, level, url)
    return {f"raw.places__{level}": n, **transform(cat, release, places_release)}
