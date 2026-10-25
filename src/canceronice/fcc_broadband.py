"""FCC Broadband Data Collection (BDC): nationwide fixed-broadband summary-by-
geography file -> Iceberg (#54).

Upstream: https://broadbandmap.fcc.gov/data-download -- the National Broadband
Map. Form 477 is retired (SPEC.md); BDC is filed biannually, as-of June 30 and
December 31 each year. This module lands the "Fixed Broadband Summary by
Geography Type - Other Geographies" file: one CSV per filing giving, for every
National/State/County/CBSA/Congressional District/Tribal geography, the
percent of broadband-serviceable locations with fixed broadband available at
each published speed tier -- an aggregate, not a location-level record.

**What was NOT landed, and why (SPEC.md § Licence gate).** The map's
Fabric-keyed *location*-level availability files (one row per broadband-
serviceable location, joined to a proprietary location_id) are a separate,
much larger download on the same page. The location Fabric behind them is
licensed from CostQuest, not FCC's to redistribute -- CostQuest's own FAQ:
"The Licensee will not permit the export or publication of raw Data from the
online interface," "only location_id from the Fabric Data can be provided in
any Derivative Data Record," and the Fabric "may be used only as necessary to
fulfill [a] statutory broadband-related obligation... No trademark nor any of
the Fabric Data or Cost Data...may be used for any other purpose(s)"
(https://www.costquest.com/broadband-serviceable-location-fabric/fabric-faq/,
checked 2026-09-18). The file this module lands carries no location_id, no
address, and no lat/lon -- only geography-level percentages -- so it never
touches that restriction.

**Licence for the summary file itself -- weaker than most sources in this
repo, and worth a human reading FCC's own terms before this merges.** BDC
availability data is FILED BY PRIVATE BROADBAND PROVIDERS under a statutory
reporting requirement and compiled/published by the FCC; it is not, like
ers_rucc.py's or cdc_svi.py's data, authored by government employees in the
course of their duties, so the usual "U.S. Government work under 17 U.S.C.
Sec 105" reasoning applies less directly here -- it covers the FCC's
compilation and the summary percentages it computes, but the underlying
provider-reported facts are not obviously a government work themselves.
FCC.gov's own data-download and terms-of-use pages could NOT be read to
check for a more specific statement: every fetch attempt (`www.fcc.gov`,
`help.bdc.fcc.gov`, `broadbandmap.fcc.gov`'s non-API pages) got a bare edge
WAF 403, checked 2026-09-18. Issue #54 carries `license:cleared`, set by the
maintainer before this module was written; this module does not change that
label, but flags the reasoning gap above for a human to resolve by reading
FCC's actual data-download terms in a browser (something this agent cannot
do) before merging.

**Getting the file: two sanctioned routes, no bot-detection workarounds.**
This module does not scrape or replicate any undocumented endpoint, and does
not send headers designed to make an automated request look like a browser
to an edge WAF -- both would be a bypass this repo shouldn't depend on, even
for public, non-restricted data. The two routes:

  (a) **`--file`, downloaded by a human.** Visit
      https://broadbandmap.fcc.gov/data-download/nationwide-data in a
      browser, pick a filing, and download "Fixed Broadband" under "Summary
      by Geography Type - Other Geographies." Pass the resulting
      `.csv`/`.csv.zip` as `--file`, with `--as-of` (there's no filing list
      to resolve "latest" from without a filing already in hand).

  (b) **The FCC's documented, token-gated Public Data API**, used when
      `FCC_BDC_USERNAME`/`FCC_BDC_TOKEN` are set (free FCC User Registration
      + a token generated in the BDC system's "Manage API Access" page; see
      "National Broadband Map Public Data API Specifications and
      Instructions," Apr 2025,
      https://www.fcc.gov/sites/default/files/bdc-public-data-api-spec.pdf):
        - `GET https://bdc.fcc.gov/api/public/map/listAsOfDates`
        - `GET https://bdc.fcc.gov/api/public/map/downloads/
          listAvailabilityData/{as_of_date}?category=Summary&subcategory=
          Summary+by+Geography+Type+-+Other+Geographies&technology_type=
          Fixed+Broadband`
        - `GET https://bdc.fcc.gov/api/public/map/downloads/downloadFile/
          availability/{file_id}`
      each with `username`/`hash_value` request headers. **This path is
      implemented directly from the FCC's own published spec, but has NOT
      been exercised against a live account -- this agent has no FCC User
      Registration credentials to test with.** In particular, `downloadFile`'s
      trailing `{file_type}` path segment is documented as optional and only
      meaningful for GIS downloads (`1`/`2`); it is omitted here for this csv
      export, which is this module's own untested reading of "optional," not
      something the spec states outright. A maintainer with an account
      should run it once against a real `--as-of` and compare the row counts
      against a route-(a) download before relying on it unattended.

```
canceronice fcc-broadband --release 2026.10 --as-of 2025-12-31 \\
    --file bdc_us_fixed_broadband_summary_by_geography_D25_15sep2026.csv.zip
# -- or, with FCC_BDC_USERNAME / FCC_BDC_TOKEN set --
canceronice fcc-broadband --release 2026.10
```

`bdc_data_vintage` lands NULL either way unless `--data-vintage` is also
passed -- neither route above surfaces `last_updated_date` (BDC's own
`api/reference/map_processing_updates/{uuid}` endpoint, which does, sits
behind the same bot detection as the rest of the anonymous website and was
deliberately not built around; see the git history of this file for that
investigation and why it was dropped).

**Table name departs from the issue's `raw.fcc__bdc_summary_<level>`
suggestion.** Verified 2026-09-18: upstream ships every geography level
(National/State/County/CBSA/Congressional District/Tribal) stacked in ONE
CSV per filing, distinguished by its own `geography_type` column -- there is
no per-level file to land per-level tables from. `raw.fcc__bdc_summary` lands
that one real file whole, same as every other single-file source in this
repo (ers_rucc.py, places.py); `geography_type` is exactly the column a
per-level reader would filter on.

**No tract-level summary is published.** Checked directly: this file's
`geography_type` values are National, State, CBSA (MSA), Congressional
District, County, Tribal -- never Tract. SPEC.md's "(and tract if published)"
therefore lands nothing extra; if FCC ever adds a tract cut, `GEOGRAPHY_TYPE`
below is where it plugs in.

**Version axis: `bdc_as_of`, not retrieval date (SPEC.md).** The as-of date
(e.g. '2025-12-31') is the release a filing represents and is what raw is
replaced wholesale per. FCC also revises a filing's public files after its
availability-challenge process closes -- the same as-of date can be
republished later with corrected numbers (this module's own test filing,
Dec 31 2025, carries `last_updated_date` 2026-09-15, eight and a half months
after the as-of date). That revision date lands as `bdc_data_vintage`, an
audit column, NOT part of the merge scope or the business key -- re-running
this module against a later data_vintage of the SAME as-of date is meant to
overwrite the earlier cut, not accumulate a second version of it.

**Geography vintage -- verified with Connecticut, per SPEC.md.** The
Dec 31, 2025 filing's County rows carry Connecticut's 8 legacy counties
(FIPS 09001-09015), NOT the 9 planning regions (09110-09190) that replaced
them in the Census Bureau's county-equivalent geography starting 2022 --
checked directly against the downloaded file. `places.py` established the
precedent this module follows: legacy counties -> `geo_vintage = 2010`,
planning regions -> `geo_vintage = 2020` (its own `GEO_VINTAGE` table).
`transform` checks this from the landed rows on every run rather than
hard-coding it per as-of date, in case a later filing switches.

**Suppression: none published.** Checked directly against the whole
downloaded file (616,170 rows): zero NULL or blank cells in `total_units` or
any `speed_*` column. Every cell is a real number, including literal `0`
(e.g. a rural county's `speed_1000_100` for `All Fixed Wireless`) -- a real
zero, never a missing value, and never suppressed (SPEC.md § Suppression:
issue #54 itself: "unserved is a real 0, not a missing value"). `transform`
still checks the landed rows it derives from for a blank cell before writing
and raises `SystemExit` if it ever finds one, the same "don't guess" stance
`places.py`/`cdc_svi.py` take for footnote/type enumeration -- there is no
enumerated sentinel to map an unexpected one to.

**What's derived, and what stays raw-only.** SPEC.md and issue #54 ask for
county percent-of-units at >=25/3, >=100/20 and >=1000/100 Mbps, "all
technologies and by wired/fixed-wireless": `TIER` picks those three of the
six published speed columns (2/0.2 and 10/1 are legacy FCC benchmarks, 250/25
an intermediate one -- all three stay in raw); `TECHNOLOGY` picks "Any
Technology" (the requested all-technology aggregate) plus the "All Wired" /
"All Fixed Wireless" split -- the file's 12 more granular technology
breakdowns (Fiber, Cable, Copper, GSO/NGSO satellite, licensed/unlicensed
fixed wireless, ...) stay in raw and are queryable there.

ponytail: only `geography_type = 'County'` and `area_data_type = 'Total'`
(the whole county, not its Urban/Rural/Tribal/Nontribal sub-splits) are
derived. State/CBSA/Congressional District/Tribal geography rows, and the
Urban/Rural/Tribal/Nontribal area splits, all stay in raw only -- none of
them are geography.unit levels this catalog resolves yet (SPEC.md's
geography spine is county/tract). Add a writer for them once there's a
geo_id to hang them on.

**`biz_res` kept native, not expanded.** The file's own two-value residential/
business location-category code ('R' / 'B') lands unmodified as
`measure.stratum.other` (`FCC_BDC:R` / `FCC_BDC:B`) -- this module could not
independently verify FCC's exact prose for what 'R'/'B' mean (the BDC data
dictionary lives behind the same box.com viewer that would not render text
for this fetch); expanding it to "Residential"/"Business" here would assert a
gloss that isn't independently checked. SPEC.md: source-native categories are
never harmonized in place.

**`method = 'derived'`, not `survey_direct`.** These are provider-reported
regulatory filings aggregated by FCC into geography percentages -- not a
direct tabulation of a survey response (`survey_direct`) nor a single
model-based point estimate (`model_based`); `measure.definition`'s own column
doc already lists `derived` as a valid value, so no SPEC.md change is needed
(flagged in the PR per issue #54's request anyway, for visibility).
"""

import json
import os
import tempfile
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

import duckdb
from pyiceberg.expressions import And, EqualTo, In

from . import merge

# Route (b), the documented Public Data API (module docstring). Credentials
# come from the environment, never from a CLI flag or a committed file.
BDC_API_HOST = "https://bdc.fcc.gov"
SUMMARY_CATEGORY = "Summary"
SUMMARY_SUBCATEGORY = "Summary by Geography Type - Other Geographies"
SUMMARY_TECHNOLOGY = "Fixed Broadband"

# The file's header, in file order (verified 2026-09-18 against the Dec 31,
# 2025 filing).
COLUMNS = (
    "area_data_type", "geography_type", "geography_id", "geography_desc",
    "geography_desc_full", "total_units", "biz_res", "technology",
    "speed_02_02", "speed_10_1", "speed_25_3", "speed_100_20",
    "speed_250_25", "speed_1000_100",
)

# tier key -> the raw speed column it derives from. Only the three benchmarks
# issue #54 names; 2/0.2, 10/1 and 250/25 stay in raw only.
TIER = {"25_3": "speed_25_3", "100_20": "speed_100_20", "1000_100": "speed_1000_100"}
TIER_LABEL = {"25_3": ">=25/3 Mbps", "100_20": ">=100/20 Mbps", "1000_100": ">=1000/100 Mbps"}

# derived key -> the source's own `technology` value.
TECHNOLOGY = {"any": "Any Technology", "wired": "All Wired", "fixed_wireless": "All Fixed Wireless"}

GEOGRAPHY_TYPE = "County"
AREA_DATA_TYPE = "Total"

# Connecticut's legacy 8 counties vs. the 9 planning regions that replaced
# them in 2022 (SPEC.md; same sets `places.py` checks against).
CT_LEGACY_COUNTIES = {"09001", "09003", "09005", "09007", "09009", "09011", "09013", "09015"}
CT_PLANNING_REGIONS = {"09110", "09120", "09130", "09140", "09150", "09160", "09170", "09180", "09190"}


def _extract_csv(zip_path, tmpdir):
    with zipfile.ZipFile(zip_path) as z:
        names = [n for n in z.namelist() if n.endswith(".csv")]
        if len(names) != 1:
            raise SystemExit(f"fcc_broadband: expected exactly one .csv in {zip_path}, "
                             f"found {names}")
        z.extract(names[0], tmpdir)
        return Path(tmpdir) / names[0]


def _resolve_csv(url, tmpdir):
    """An already-downloaded local .csv or .csv.zip -- route (a) (module
    docstring)."""
    src = Path(url)
    return _extract_csv(src, tmpdir) if src.suffix == ".zip" else src


def _bdc_api_get(path, username, token, **query):
    """One GET against the documented Public Data API -- route (b) (module
    docstring). `username`/`hash_value` are request headers, per the spec,
    never query parameters or a bearer token."""
    url = f"{BDC_API_HOST}{path}"
    if query:
        url += "?" + urllib.parse.urlencode(query)
    req = urllib.request.Request(url, headers={"username": username, "hash_value": token})
    with urllib.request.urlopen(req) as r:
        return json.load(r)


def list_as_of_dates(username, token):
    """Every published BDC as-of date, per the documented `listAsOfDates`
    API (module docstring route (b))."""
    data = _bdc_api_get("/api/public/map/listAsOfDates", username, token)["data"]
    return sorted({d["as_of_date"] for d in data if d["data_type"] == "availability"})


def _summary_file_id(as_of, username, token):
    """The one nationwide fixed-broadband summary-by-geography file's id for
    this as-of date, via the documented `listAvailabilityData` API."""
    data = _bdc_api_get(f"/api/public/map/downloads/listAvailabilityData/{as_of}",
                        username, token, category=SUMMARY_CATEGORY,
                        subcategory=SUMMARY_SUBCATEGORY, technology_type=SUMMARY_TECHNOLOGY)["data"]
    matches = [r for r in data if r.get("category") == SUMMARY_CATEGORY
               and r.get("subcategory") == SUMMARY_SUBCATEGORY]
    if len(matches) != 1:
        raise SystemExit(f"fcc_broadband: expected exactly 1 nationwide summary file for "
                         f"as-of {as_of}, found {len(matches)} (documented API; module docstring)")
    return matches[0]["file_id"]


def _download_via_api(as_of, username, token, tmpdir):
    """Route (b): resolve this as-of date's file id and download it through
    the documented `downloadFile` API. UNVERIFIED against a live account --
    module docstring, including the `file_type` path segment this omits."""
    file_id = _summary_file_id(as_of, username, token)
    url = f"{BDC_API_HOST}/api/public/map/downloads/downloadFile/availability/{file_id}"
    req = urllib.request.Request(url, headers={"username": username, "hash_value": token})
    zpath = Path(tmpdir) / "bdc_summary.zip"
    with urllib.request.urlopen(req) as r, open(zpath, "wb") as f:
        f.write(r.read())
    return _extract_csv(zpath, tmpdir), url


def _header(path):
    with open(path, encoding="utf-8") as f:
        return tuple(f.readline().rstrip("\r\n").split(","))


def _parse(csv_path, as_of, data_vintage, release):
    header = _header(csv_path)
    if header != COLUMNS:
        raise SystemExit(f"fcc_broadband: {csv_path} header is not the declared one; "
                         f"differs in {sorted(set(header) ^ set(COLUMNS))}")
    con = duckdb.connect()
    select = ", ".join(f'"{c}"' for c in COLUMNS)
    vintage_sql = f"'{data_vintage}'" if data_vintage else "NULL"
    # Dialect stated, not sniffed: comma-delimited, double-quoted where a cell
    # needs it (geography_desc_full has commas, e.g. "Aberdeen, SD"). UTF-8 is
    # DuckDB's default and matches the real file (verified 2026-09-18).
    return con.sql(f"""
        SELECT {select}, '{as_of}' AS bdc_as_of, {vintage_sql}::VARCHAR AS bdc_data_vintage,
               '{release}' AS landed_in
        FROM read_csv('{csv_path}', header=true, all_varchar=true, delim=',',
                      quote='"', escape='"', nullstr='')
    """).to_arrow_table()


def land_raw(cat, release, as_of=None, url=None, data_vintage=None):
    """Phase 1: one filing's nationwide summary-by-geography file, verbatim
    and whole, replaced per `bdc_as_of`.

    `url` is route (a): an already-downloaded .csv or .csv.zip; `as_of` is
    then required, since there's no filing list to resolve "latest" from.
    With `url` omitted, route (b) is used instead: `FCC_BDC_USERNAME`/
    `FCC_BDC_TOKEN` must be set, and `as_of` defaults to the latest published
    date (module docstring covers both routes, and why there's no third,
    unauthenticated auto-download). `data_vintage` is always optional; NULL
    when not supplied.
    """
    if url is not None:
        if not as_of:
            raise SystemExit("fcc_broadband: --as-of is required together with --file "
                             "(there's no filing list to resolve it from)")
        fetch_url = url
        with tempfile.TemporaryDirectory() as tmpdir:
            arrow = _parse(_resolve_csv(url, tmpdir), as_of, data_vintage, release)
    else:
        username, token = os.environ.get("FCC_BDC_USERNAME"), os.environ.get("FCC_BDC_TOKEN")
        if not (username and token):
            raise SystemExit("fcc_broadband: no --file given, and FCC_BDC_USERNAME/"
                             "FCC_BDC_TOKEN aren't set -- see module docstring for the two "
                             "ways to get this file (a browser download passed via --file, "
                             "or registering for the FCC's Public Data API).")
        as_of = as_of or max(list_as_of_dates(username, token))
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path, fetch_url = _download_via_api(as_of, username, token, tmpdir)
            arrow = _parse(csv_path, as_of, data_vintage, release)

    if not arrow.num_rows:
        raise SystemExit(f"fcc_broadband: {fetch_url} yielded no rows")
    n = merge.write(cat, "raw.fcc__bdc_summary", arrow, EqualTo("bdc_as_of", as_of))
    merge.manifest(cat, release, "fcc_broadband", fetch_url, n, version=as_of, method="release_number")
    return as_of, n


def _geo_vintage(con):
    """SPEC.md: verify against Connecticut rather than hard-code per as-of
    date, in case a later filing switches (module docstring)."""
    ct = {r[0] for r in con.sql(f"""
        SELECT DISTINCT geography_id FROM raw
        WHERE geography_type = '{GEOGRAPHY_TYPE}' AND geography_id LIKE '09%'
    """).fetchall()}
    if ct and ct <= CT_LEGACY_COUNTIES:
        return 2010
    if ct and ct <= CT_PLANNING_REGIONS:
        return 2020
    raise SystemExit(f"fcc_broadband: unexpected Connecticut county codes {sorted(ct)}; "
                     "can't determine geo_vintage (module docstring)")


def transform(cat, release, as_of):
    """Phase 2: county percent-of-units observations for the tiers/
    technologies in TIER/TECHNOLOGY, plus their measure definitions and the
    biz_res stratum.

    Scoped to `as_of`'s rows: raw accumulates every landed filing, so an
    unscoped read would derive from all of them at once.
    """
    con = duckdb.connect()
    con.register("raw", cat.load_table("raw.fcc__bdc_summary").scan(
        row_filter=EqualTo("bdc_as_of", as_of)).to_arrow())

    tech_list = ", ".join(f"'{t}'" for t in TECHNOLOGY.values())
    missing = con.sql(f"""
        SELECT count(*) FROM raw
        WHERE geography_type = '{GEOGRAPHY_TYPE}' AND area_data_type = '{AREA_DATA_TYPE}'
          AND technology IN ({tech_list})
          AND (speed_25_3 IS NULL OR speed_100_20 IS NULL OR speed_1000_100 IS NULL
               OR total_units IS NULL)
    """).fetchone()[0]
    if missing:
        raise SystemExit(f"fcc_broadband: {missing} county row(s) in the {as_of} filing have "
                         "a blank speed or total_units cell -- this file may publish a "
                         "suppression sentinel this module doesn't enumerate yet (module docstring)")

    geo_vintage = _geo_vintage(con)

    def_rows = ", ".join(
        f"('FCC_BDC:{tier}:{tech}', 'Percent of broadband-serviceable locations with fixed "
        f"broadband available at {TIER_LABEL[tier]} ({TECHNOLOGY[tech]})', '{TECHNOLOGY[tech]}')"
        for tier in TIER for tech in TECHNOLOGY
    )
    definition = con.sql(f"""
        SELECT measure_id, 'FCC_BDC' AS source, label AS label,
               '%' AS units, 'broadband-serviceable locations (FCC BDC Fabric)' AS universe,
               'percent' AS rate_basis, NULL::VARCHAR AS age_adjustment, 'derived' AS method,
               NULL::VARCHAR AS cancer_site_code,
               'FCC Broadband Data Collection biannual filing, aggregated by FCC from '
               || 'provider-reported location-level availability into geography percentages. '
               || 'Technology: ' || tech || '.' AS doc
        FROM (VALUES {def_rows}) AS t(measure_id, label, tech)
    """).to_arrow_table()

    stratum = con.sql("""
        SELECT * FROM (VALUES
            ('FCC_BDC:R', 'FCC_BDC', NULL::VARCHAR, NULL::VARCHAR, NULL::VARCHAR,
             NULL::VARCHAR, 'R', 'FCC_BDC_BIZ_RES'),
            ('FCC_BDC:B', 'FCC_BDC', NULL::VARCHAR, NULL::VARCHAR, NULL::VARCHAR,
             NULL::VARCHAR, 'B', 'FCC_BDC_BIZ_RES')
        ) AS t(stratum_id, source, sex, age_group, race_ethnicity, stage, other, scheme)
    """).to_arrow_table()

    observation = con.sql(f"""
        WITH melted AS (
            SELECT geography_id, biz_res, technology, total_units, tier_col, pct
            FROM (SELECT geography_id, biz_res, technology, total_units,
                         speed_25_3, speed_100_20, speed_1000_100
                  FROM raw
                  WHERE geography_type = '{GEOGRAPHY_TYPE}' AND area_data_type = '{AREA_DATA_TYPE}'
                    AND technology IN ({tech_list}))
            UNPIVOT (pct FOR tier_col IN (speed_25_3, speed_100_20, speed_1000_100))
        )
        SELECT 'FCC_BDC' AS source, '{as_of}' AS source_release,
               'FCC_BDC:' ||
                 CASE tier_col WHEN 'speed_25_3' THEN '25_3' WHEN 'speed_100_20' THEN '100_20'
                               ELSE '1000_100' END || ':' ||
                 CASE technology WHEN 'Any Technology' THEN 'any' WHEN 'All Wired' THEN 'wired'
                                 ELSE 'fixed_wireless' END AS measure_id,
               'county:' || lpad(geography_id, 5, '0') AS geo_id, {geo_vintage} AS geo_vintage,
               '{as_of}' AS period_start, '{as_of}' AS period_end,
               'FCC_BDC:' || biz_res AS stratum_id,
               TRY_CAST(pct AS DOUBLE) * 100 AS value,
               NULL::DOUBLE AS lower, NULL::DOUBLE AS upper, NULL::DOUBLE AS interval_level,
               NULL::DOUBLE AS numerator, TRY_CAST(total_units AS DOUBLE) AS denominator,
               'reported' AS value_status,
               NULL::VARCHAR AS reliability_flag, NULL::VARCHAR AS trend
        FROM melted
    """).to_arrow_table()
    merge.check_observations(observation)

    scope = EqualTo("source", "FCC_BDC")
    def_ids = [f"FCC_BDC:{tier}:{tech}" for tier in TIER for tech in TECHNOLOGY]
    stratum_ids = ["FCC_BDC:R", "FCC_BDC:B"]
    return {
        "measure.definition": merge.write(cat, "measure.definition", definition,
                                          And(scope, In("measure_id", def_ids))),
        "measure.stratum": merge.write(cat, "measure.stratum", stratum,
                                       And(scope, In("stratum_id", stratum_ids))),
        "measure.observation": merge.merge(
            cat, "measure.observation", observation, release,
            And(scope, EqualTo("source_release", as_of))),
    }


def ingest(cat, release, as_of=None, url=None, data_vintage=None):
    as_of, n = land_raw(cat, release, as_of, url, data_vintage)
    return {"raw.fcc__bdc_summary": n, **transform(cat, release, as_of)}
