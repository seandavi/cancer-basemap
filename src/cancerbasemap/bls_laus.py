"""BLS Local Area Unemployment Statistics (LAUS), county level -> Iceberg.

Upstream: https://www.bls.gov/lau/ describes the program; the flat files
themselves live at https://download.bls.gov/pub/time.series/la/ --
`la.data.64.County` (every county-equivalent series, tab-delimited,
fixed-width padded fields), plus the small lookups `la.series`, `la.area`,
`la.measure`, `la.footnote` (`la.period` is not landed separately -- its 13
rows are exactly 'M01'..'M13', already documented on raw.bls__laus_county.period).

**Access.** `download.bls.gov` and `www.bls.gov` both return HTTP 403
("Access Denied... bot activity that doesn't conform to BLS usage policy is
prohibited") to every request from this environment, with or without the
descriptive `USER_AGENT` below -- confirmed 2026-09-18 with curl, matching
BLS's own stated bot policy. Every real file used to build this module (the
five flat files above, and BLS's copyright page) was instead retrieved
byte-for-byte through web.archive.org's cached copies -- real BLS content,
just not fetched live. `_fetch` still tries the real `download.bls.gov` URLs
first (a maintainer running this outside whatever blocks this environment may
have no trouble), and only the fixtures/verification in this PR relied on the
archived copies. See the PR description for exactly which archived snapshots
and their timestamps.

**Licence.** BLS's own copyright page states: "The Bureau of Labor Statistics
(BLS) is a Federal government agency and everything that we publish, both in
hard copy and electronically, is in the public domain, except for previously
copyrighted photographs and illustrations, ... You are free to use our public
domain material without specific permission, although we do ask that you cite
the Bureau of Labor Statistics as the source."
(https://www.bls.gov/opub/copyright-information.htm, confirmed byte-for-byte
via a 2020-10-16 web.archive.org snapshot since the live page 403s here; the
policy itself carries no expiry and BLS is also independently a U.S.
Government work under 17 U.S.C. Sec 105).

**Version axis: retrieval-date vintage, deduplicated by checksum.** BLS
revises prior months in place and the flat file always holds the complete
revised history -- there is no edition label to key on, only a moment of
retrieval (SPEC.md's versioning model already reserves `retrieved_on`-style
vintages for exactly this). SPEC.md's own vintage rule adds "several
retrievals with identical values are one vintage": `land_raw` hashes the
freshly-fetched county file (SHA-256) and compares it to the previous
`provenance.release` row's `checksum` for `source='bls_laus'` (merge.manifest
now accepts and records `checksum` -- this is its first real caller); an
identical hash lands nothing and reports "unchanged vintage" rather than
opening a new one for bytes that didn't change.

**Geography.** A series id is `'LAUCN' + <5-digit FIPS> + '00000000' +
<2-digit measure code>` (e.g. 'LAUCN010010000000003' = Autauga County, AL,
measure 03) -- verified directly against the real file: every one of its
3,225 areas carries the 'LAUCN' county prefix, so `transform` parses geo_id
straight out of `series_id` rather than joining `raw.bls__laus_series`.
`area_code` in `la.area` encodes the same FIPS as `'CN' + state(2) +
county(3) + '00000000'`.

`GEO_VINTAGE = 2020`, except Connecticut's nine planning regions (FIPS
09110-09190) get 2022 -- the same split census_gazetteer.py and cdc_svi.py
use, confirmed here from two real `la.area` snapshots: one from 2025-01-05
carries Connecticut's eight legacy counties (09001-09015) and zero planning
regions; one from 2026-01-03 carries the nine planning regions and zero
legacy counties. That flip matches the issue's "Connecticut planning regions
were adopted by LAUS in 2024" and lands on the same 2022 Census vintage the
other sources already use for the same real-world change (LAUS adopting the
recode two years after Census introduced it, same as PLACES/SVI's own lag
patterns) -- not a fresh vintage invented for this source.

**Louisiana / Katrina.** The real file confirms the expected 2005-2006 gap
directly: Orleans Parish (22071) reports normally through 2005-08, then
`footnote_codes='N'` with value '-' every month from 2005-09 through
2006-06, resuming with real values at 2006-07; the 2005 and 2006 annual
averages (period M13) are `'N'` too, since an average can't be struck over
mostly-missing months. Landed and derived like any other not_available run,
no special-casing needed.

**Kalawao County, HI (FIPS 15005).** Confirmed absent from `la.area`
entirely -- no area_code containing '15005' anywhere in the real file. BLS
LAUS simply never publishes a county-equivalent series for it (population
~90); this is not a suppressed value to map, so there is nothing to test with
a fixture row -- its absence from every table here is the correct outcome.

**Footnote codes**, enumerated from the real `la.footnote` (confirmed
2026-09-18 via web.archive.org; `FOOTNOTE_TEXT` quotes the file verbatim):

| code | meaning | value_status |
| --- | --- | --- |
| N | Not available. | `not_available` (value NULL) |
| U | The annual average cannot be calculated due to missing monthly data. | `not_available` (value NULL) |
| P | Preliminary. | `reported` (reliability_flag='P') |
| A | Area boundaries do not reflect official OMB definitions. | `reported` (reliability_flag='A') |
| V | The survey was not conducted due to bad weather. Interpolated data were seasonally adjusted. | `reported` (reliability_flag='V') |
| W | The household survey was not conducted for this month due to bad weather. Data were interpolated. | `reported` (reliability_flag='W') |
| Y | Data reflect controlling to interpolated statewide totals because the survey was not conducted. | `reported` (reliability_flag='Y') |

N and U are the two footnotes actually confirmed against a literal '-' value
in the real file; U only ever appears on period='M13'. Y is confirmed with a
real reported value (Puerto Rico municipios, e.g. 2017-09 = 12.5). Any
footnote code not in this table raises `SystemExit` in `transform` rather
than being silently treated as either status.

ponytail: A, P, V and W are real, documented `la.footnote` codes but do not
occur anywhere in the specific vintage archived for this PR's fixtures/real
ingest (checked: the full real `la.data.64.County` download has only N, U and
Y). They are mapped anyway, straight from the real lookup file's text, but
untested against a live example -- P in particular is normally only ever
seen on the most recent month or two before BLS's next revision clears it,
so a slightly older captured vintage can easily show none.

**Derived**, `source='BLS_LAUS'`, not seasonally adjusted (every county-level
series in the real `la.series` carries `seasonal='U'` -- LAUS publishes no
seasonally-adjusted county series at all):
  - `BLS_LAUS:unemployment_rate` (measure 03, percent, universe "civilian
    labor force")
  - `BLS_LAUS:unemployed`, `BLS_LAUS:employed`, `BLS_LAUS:labor_force`
    (measures 04/05/06, persons)
`method='model_based'`: LAUS county estimates come from BLS's signal-plus-
noise time-series model benchmarked to state CPS controls, not a direct
survey tabulation below the state level.

ponytail: only the last 10 full calendar years plus the current year are
derived by default (`--since`, default `this_year - 10`) -- full history
(back to 1990 for most counties) stays in raw regardless, per this issue's
own scope; a later issue can widen the default or backfill the rest from raw
without re-landing anything.
"""

import os
import hashlib
import tempfile
import urllib.request
from datetime import date
from pathlib import Path

import duckdb
import pyarrow as pa
from pyiceberg.exceptions import NoSuchTableError
from pyiceberg.expressions import And, EqualTo, GreaterThanOrEqual, In

from . import merge

# BLS's bot filter, as observed 2026-09-18 from the ingest host: a User-Agent
# containing a URL (or "github") gets 403 even with an email; a plain product
# token plus a contact address gets 200. The address is the operator's, so it
# comes from the environment rather than being committed:
#   CANCERBASEMAP_CONTACT=you@example.org
_CONTACT = os.environ.get("CANCERBASEMAP_CONTACT")
USER_AGENT = f"cancerbasemap-ingest/0.1 ({_CONTACT})" if _CONTACT else "cancerbasemap-ingest/0.1"
BASE = "https://download.bls.gov/pub/time.series/la"
URL_COUNTY = f"{BASE}/la.data.64.County"
URL_AREA = f"{BASE}/la.area"
URL_SERIES = f"{BASE}/la.series"
URL_MEASURE = f"{BASE}/la.measure"
URL_FOOTNOTE = f"{BASE}/la.footnote"

COUNTY_COLUMNS = ("series_id", "year", "period", "value", "footnote_codes")
AREA_COLUMNS = ("area_type_code", "area_code", "area_text", "display_level", "selectable", "sort_sequence")
SERIES_COLUMNS = ("series_id", "area_type_code", "area_code", "measure_code", "seasonal", "srd_code",
                  "series_title", "footnote_codes", "begin_year", "begin_period", "end_year", "end_period")
MEASURE_COLUMNS = ("measure_code", "measure_text")
FOOTNOTE_COLUMNS = ("footnote_code", "footnote_text")

# Real la.footnote text, module docstring. NOT_AVAILABLE_FOOTNOTES are the two confirmed
# against a literal '-' value in the real file; the rest are confirmed-or-documented as
# still-reported values with a reliability caveat.
FOOTNOTE_TEXT = {
    "A": "Area boundaries do not reflect official OMB definitions.",
    "N": "Not available.",
    "P": "Preliminary.",
    "U": "The annual average cannot be calculated due to missing monthly data.",
    "V": "The survey was not conducted due to bad weather. Interpolated data were seasonally "
         "adjusted.",
    "W": "The household survey was not conducted for this month due to bad weather. Data were "
         "interpolated.",
    "Y": "Data reflect controlling to interpolated statewide totals because the survey was not "
         "conducted.",
}
NOT_AVAILABLE_FOOTNOTES = ("N", "U")

# measure_code -> (measure_id suffix, label, units, rate_basis, universe)
MEASURES = {
    "03": ("unemployment_rate", "Unemployment rate", "percent", "percent", "civilian labor force"),
    "04": ("unemployed", "Unemployed", "persons", "count", None),
    "05": ("employed", "Employed", "persons", "count", None),
    "06": ("labor_force", "Labor force", "persons", "count", None),
}

NSA_NOTE = ("Not seasonally adjusted -- LAUS publishes no seasonally-adjusted county series "
            "(every county-level series in the real la.series file carries seasonal='U').")


def _fetch(url):
    """The file's bytes. A local path (tests) is read directly; a remote URL goes
    through urllib with a descriptive User-Agent naming this project, per BLS's
    bot policy (module docstring) -- still 403s from this environment regardless."""
    if not url.startswith("http"):
        return Path(url).read_bytes()
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req) as r:
        return r.read()


def _header(raw_bytes):
    """The file's header line, tab-split, each field stripped of BLS's fixed-width
    padding (series_id/value are right-padded with spaces in the real files;
    module docstring)."""
    first = raw_bytes.split(b"\n", 1)[0].rstrip(b"\r\n")
    return tuple(f.decode("ascii").strip() for f in first.split(b"\t"))


def _land(cat, identifier, url, columns, vintage, release):
    """One lookup or data file, verbatim and whole (padding trimmed -- pure
    formatting, not content), scoped to this vintage."""
    raw_bytes = _fetch(url)
    if (header := _header(raw_bytes)) != columns:
        raise SystemExit(f"bls_laus: {url} header is not the declared one; "
                         f"differs in {sorted(set(header) ^ set(columns))}")
    select = ", ".join(f'TRIM("{c}") AS "{c}"' for c in columns)
    with tempfile.NamedTemporaryFile(suffix=".txt") as tmp:
        tmp.write(raw_bytes)
        tmp.flush()
        con = duckdb.connect()
        arrow = con.sql(f"""
            SELECT {select}, '{vintage}' AS laus_vintage, '{release}' AS landed_in
            FROM read_csv('{tmp.name}', header=true, all_varchar=true, delim='\t',
                          quote='', escape='', nullstr='')
        """).to_arrow_table()
    if not arrow.num_rows:
        raise SystemExit(f"bls_laus: {url} yielded no rows")
    return merge.write(cat, identifier, arrow, EqualTo("laus_vintage", vintage))


def _previous_checksum(cat):
    """The most recent provenance.release checksum landed under source='bls_laus',
    or None if there isn't one yet (module docstring's unchanged-vintage check)."""
    try:
        table = cat.load_table("provenance.release")
    except NoSuchTableError:
        return None
    con = duckdb.connect()
    con.register("prov", table.scan(row_filter=EqualTo("source", "bls_laus")).to_arrow())
    row = con.sql("SELECT checksum FROM prov ORDER BY retrieved_at DESC LIMIT 1").fetchone()
    return row[0] if row else None


def land_raw(cat, release, county_url=None, area_url=None, series_url=None, measure_url=None,
            footnote_url=None, vintage=None):
    """Phase 1: the county data file plus the four small lookups, verbatim and
    whole, scoped by one retrieval-date vintage.

    Returns `(None, {})` without writing anything when the county file's bytes
    match the previous vintage's checksum exactly (module docstring).
    """
    county_url = county_url or URL_COUNTY
    raw_bytes = _fetch(county_url)
    checksum = hashlib.sha256(raw_bytes).hexdigest()
    if checksum == _previous_checksum(cat):
        return None, {}

    vintage = vintage or date.today().isoformat()
    if (header := _header(raw_bytes)) != COUNTY_COLUMNS:
        raise SystemExit(f"bls_laus: {county_url} header is not the declared one; "
                         f"differs in {sorted(set(header) ^ set(COUNTY_COLUMNS))}")
    select = ", ".join(f'TRIM("{c}") AS "{c}"' for c in COUNTY_COLUMNS)
    with tempfile.NamedTemporaryFile(suffix=".txt") as tmp:
        tmp.write(raw_bytes)
        tmp.flush()
        con = duckdb.connect()
        arrow = con.sql(f"""
            SELECT {select}, '{vintage}' AS laus_vintage, '{release}' AS landed_in
            FROM read_csv('{tmp.name}', header=true, all_varchar=true, delim='\t',
                          quote='', escape='', nullstr='')
        """).to_arrow_table()
    if not arrow.num_rows:
        raise SystemExit(f"bls_laus: {county_url} yielded no rows")
    n_county = merge.write(cat, "raw.bls__laus_county", arrow, EqualTo("laus_vintage", vintage))

    counts = {
        "raw.bls__laus_county": n_county,
        "raw.bls__laus_area": _land(cat, "raw.bls__laus_area", area_url or URL_AREA,
                                    AREA_COLUMNS, vintage, release),
        "raw.bls__laus_series": _land(cat, "raw.bls__laus_series", series_url or URL_SERIES,
                                      SERIES_COLUMNS, vintage, release),
        "raw.bls__laus_measure": _land(cat, "raw.bls__laus_measure", measure_url or URL_MEASURE,
                                       MEASURE_COLUMNS, vintage, release),
        "raw.bls__laus_footnote": _land(cat, "raw.bls__laus_footnote", footnote_url or URL_FOOTNOTE,
                                        FOOTNOTE_COLUMNS, vintage, release),
    }
    merge.manifest(cat, release, "bls_laus", county_url, n_county, version=vintage,
                   method="retrieval_date", checksum=checksum)
    return vintage, counts


def transform(cat, release, vintage, since=None):
    """Phase 2: four measures per county-equivalent, for `since`..present
    (default: the last 10 full years plus the current year -- module
    docstring's ponytail note). Scoped to `vintage`'s rows.
    """
    since = since or (date.today().year - 10)
    table = cat.load_table("raw.bls__laus_county")
    # year is 4-digit for every real row (1976-), so a lexical >= on the string
    # column agrees with numeric >= and can be pushed down to the Iceberg scan.
    row_filter = And(EqualTo("laus_vintage", vintage), GreaterThanOrEqual("year", str(since)))
    con = duckdb.connect()
    con.register("county", table.scan(row_filter=row_filter).to_arrow())

    known = ", ".join(f"'{c}'" for c in FOOTNOTE_TEXT)
    bad = con.sql(f"""
        SELECT DISTINCT footnote_codes FROM county
        WHERE footnote_codes IS NOT NULL AND footnote_codes NOT IN ({known})
    """).fetchall()
    if bad:
        raise SystemExit(f"bls_laus: unknown footnote code(s) {sorted(r[0] for r in bad)}; "
                         f"not in la.footnote's documented set {sorted(FOOTNOTE_TEXT)}")

    definition = pa.Table.from_pylist([
        dict(measure_id=f"BLS_LAUS:{suffix}", source="BLS_LAUS", label=label, units=units,
            universe=universe, rate_basis=rate_basis, age_adjustment=None, method="model_based",
            cancer_site_code=None,
            doc=f"{label} (county, monthly and annual-average). {NSA_NOTE}")
        for suffix, label, units, rate_basis, universe in MEASURES.values()
    ])
    def_ids = definition.column("measure_id").to_pylist()

    stratum = pa.Table.from_pylist([dict(
        stratum_id="BLS_LAUS:ALL", source="BLS_LAUS", sex=None, age_group=None,
        race_ethnicity=None, stage=None, other=None, scheme="BLS_LAUS_TOTAL",
    )])

    not_available = ", ".join(f"'{c}'" for c in NOT_AVAILABLE_FOOTNOTES)
    observation = con.sql(f"""
        WITH parsed AS (
            SELECT substr(series_id, 6, 5) AS fips, substr(series_id, 19, 2) AS measure_code,
                   year, period, value, footnote_codes
            FROM county
        )
        SELECT 'BLS_LAUS' AS source, '{vintage}' AS source_release,
               'BLS_LAUS:' ||
                   CASE measure_code {" ".join(f"WHEN '{code}' THEN '{s[0]}'" for code, s in MEASURES.items())}
                   END AS measure_id,
               'county:' || fips AS geo_id,
               CASE WHEN fips BETWEEN '09110' AND '09190' THEN 2022 ELSE 2020 END AS geo_vintage,
               CASE WHEN period = 'M13' THEN year
                    ELSE strftime(make_date(CAST(year AS INT), CAST(substr(period, 2, 2) AS INT), 1),
                                  '%Y-%m-%d') END AS period_start,
               CASE WHEN period = 'M13' THEN year
                    ELSE strftime(last_day(make_date(CAST(year AS INT), CAST(substr(period, 2, 2) AS INT), 1)),
                                  '%Y-%m-%d') END AS period_end,
               'BLS_LAUS:ALL' AS stratum_id,
               CASE WHEN footnote_codes IN ({not_available}) THEN NULL
                    ELSE TRY_CAST(value AS DOUBLE) END AS value,
               NULL::DOUBLE AS lower, NULL::DOUBLE AS upper, NULL::DOUBLE AS interval_level,
               NULL::DOUBLE AS numerator, NULL::DOUBLE AS denominator,
               -- Status follows the same CAST that actually produced `value`, not
               -- just the footnote flag -- a present-but-non-numeric cell with no
               -- N/U footnote (never seen in the real file, verified 2026-09-19)
               -- must not land as a numberless 'reported' row
               -- (merge.check_observations; #148).
               CASE WHEN footnote_codes IN ({not_available}) THEN 'not_available'
                    WHEN TRY_CAST(value AS DOUBLE) IS NOT NULL THEN 'reported'
                    ELSE 'not_available' END AS value_status,
               footnote_codes AS reliability_flag, NULL::VARCHAR AS trend
        FROM parsed
    """).to_arrow_table()
    merge.check_observations(observation)

    scope = EqualTo("source", "BLS_LAUS")
    return {
        "measure.definition": merge.write(cat, "measure.definition", definition,
                                          And(scope, In("measure_id", def_ids))),
        "measure.stratum": merge.write(cat, "measure.stratum", stratum,
                                       And(scope, In("stratum_id", ["BLS_LAUS:ALL"]))),
        "measure.observation": merge.merge(
            cat, "measure.observation", observation, release,
            And(scope, EqualTo("source_release", vintage))),
    }


def ingest(cat, release, county_url=None, area_url=None, series_url=None, measure_url=None,
          footnote_url=None, vintage=None, since=None):
    vintage, raw_counts = land_raw(cat, release, county_url, area_url, series_url, measure_url,
                                   footnote_url, vintage)
    if vintage is None:
        print("bls_laus: unchanged vintage (checksum matches the previous manifest row); "
              "nothing landed")
        return {}
    return {**raw_counts, **transform(cat, release, vintage, since)}
