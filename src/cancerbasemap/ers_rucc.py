"""USDA ERS Rural-Urban Continuum Codes -> Iceberg, in the same two phases as
the other sources.

Upstream: https://www.ers.usda.gov/data-products/rural-urban-continuum-codes
County-level rurality classification (codes 1-9: metro by population size,
nonmetro by urban-population size and adjacency to a metro area), published
per edition. ERS's own product and documentation pages carry no licence
statement (checked 2026-09-18). RUCC is produced by USDA ERS, a federal
agency, as part of employees' official duties, so it is a U.S. Government
work: "Data and content created by government employees within the scope of
their employment are not subject to domestic copyright protection under 17
U.S.C. Sec 105. Government works are by default in the U.S. Public Domain."
(https://resources.data.gov/open-licenses/, checked 2026-09-18).

**Version axis is the edition** (ERS republishes RUCC roughly once a decade:
1974, 1983, 1993, 2003, 2013, 2023), not a retrieval date -- the edition is
in the file name and in the published attribute name (`RUCC_2023`), so it is
a real citable label, landed as `rucc_edition`.

Only the 2023 edition is landed. It is published as a long-format CSV,
verified 2026-09-18 by downloading it: header `FIPS,State,County_Name,
Attribute,Value`, comma-delimited, iso-8859-1 encoded (not UTF-8 -- e.g.
"Do\xf1a Ana County"), one row per (county, attribute) with `Attribute` in
`Population_2020` | `RUCC_2023` | `Description`. 2013 is published only as a
legacy `.xls` (verified 2026-09-18: ERS lists no CSV or `.xlsx` form for it,
only for 2023 and the rolling current file -- `/media/5767/...xlsx` exists
for 2023 alongside the CSV, but 2013's only sibling is `/media/5769/
2013-rural-urban-continuum-codes.xls`). DuckDB cannot read legacy `.xls`
(`excel` extension is `.xlsx`-only) and no new dependency is allowed, so
2013 is left out.

ponytail: 2013 not landed -- no CSV/XLSX form exists upstream and adding an
`.xls` reader is a new dependency. Revisit if ERS ever republishes it, or if
a later source needs pre-2020 rurality and a hand conversion becomes
worthwhile.

**Geography vintage: 2020**, for the 2023 edition. ERS's documentation says
the codes classify counties "based on the 2023 Office of Management and
Budget (OMB) delineation of metro areas," itself built on "2020 Census and
the 2016-20 American Community Survey (ACS)" geography, and that in 2022
"planning regions in Connecticut replaced counties in the Census Bureau's
county-level geography." The downloaded file confirms this directly: it
carries Connecticut's nine 2022 planning regions (FIPS 09110-09190, e.g.
"09110,CT,Capitol Planning Region") rather than the six legacy counties
(09001-09015), and Alaska's current census areas -- Chugach (02063) and
Copper River (02066) -- rather than the pre-2019 Valdez-Cordova (02261) they
replaced. Both are 2020-vintage Census geography markers.

Two American Samoa entities (Rose Island 60030, Swains Island 60040) report
zero 2020 population and carry no `RUCC_2023` attribute row at all --
verified in the downloaded file. That is a missing code, not a suppressed
one; it lands as `value_status = 'not_available'`, never as a number and
never silently dropped.

ponytail: `Population_2020` is landed in raw (it is part of the file) but
not derived into `measure.observation` -- population denominators come from
SEER/ACS elsewhere in the lake, not from RUCC.
"""

import tempfile
import urllib.request
from pathlib import Path

import duckdb
from pyiceberg.expressions import And, EqualTo, In

from . import lineage, merge

URL = "https://www.ers.usda.gov/media/5768/2023-rural-urban-continuum-codes.csv"
EDITION = "2023"
GEO_VINTAGE = 2020
USER_AGENT = "cancerbasemap/1.0 (+https://github.com/seandavi/cancer-basemap)"

# The file's header, in file order. Long format: one row per (county, attribute).
COLUMNS = ("FIPS", "State", "County_Name", "Attribute", "Value")

# Verbatim from ERS documentation (https://www.ers.usda.gov/data-products/
# rural-urban-continuum-codes/documentation), checked 2026-09-18.
CODE_DOC = (
    "USDA ERS Rural-Urban Continuum Code. Metro counties: 1 = counties in metro "
    "areas of 1 million population or more; 2 = counties in metro areas of "
    "250,000 to 1 million population; 3 = counties in metro areas of fewer than "
    "250,000 population. Nonmetro counties: 4 = urban population of 20,000 or "
    "more, adjacent to a metro area; 5 = urban population of 20,000 or more, "
    "not adjacent to a metro area; 6 = urban population of 5,000 to 20,000, "
    "adjacent to a metro area; 7 = urban population of 5,000 to 20,000, not "
    "adjacent to a metro area; 8 = urban population of fewer than 5,000, "
    "adjacent to a metro area; 9 = urban population of fewer than 5,000, not "
    "adjacent to a metro area."
)


def _fetch(url):
    """The file's bytes. A local path (tests) is read directly; a remote URL
    goes through urllib with a descriptive User-Agent -- ERS's default urllib
    UA works fine as checked 2026-09-18, but a UA that identifies the project
    is set anyway rather than relying on that continuing to be true."""
    if not url.startswith("http"):
        return Path(url).read_bytes()
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req) as r:
        return r.read()


def land_raw(cat, release, url=None):
    """Phase 1: the 2023 edition, verbatim and whole, replaced per edition."""
    url = url or URL
    with tempfile.NamedTemporaryFile(suffix=".csv") as tmp:
        raw_bytes = _fetch(url)
        tmp.write(raw_bytes)
        tmp.flush()
        # The file is iso-8859-1 (verified 2026-09-18: e.g. "Do\xf1a Ana County"),
        # not UTF-8 -- decoding the header line as latin-1 is safe either way
        # since the header itself is plain ASCII.
        header = tuple(raw_bytes.splitlines()[0].decode("latin-1").split(","))
        if header != COLUMNS:
            raise SystemExit(f"ers_rucc: {url} header is not the declared one; "
                             f"differs in {sorted(set(header) ^ set(COLUMNS))}")

        con = duckdb.connect()
        arrow = con.sql(f"""
            SELECT FIPS, State, County_Name, Attribute, Value,
                   '{EDITION}' AS rucc_edition, '{release}' AS landed_in
            FROM read_csv('{tmp.name}', header=true, all_varchar=true, delim=',',
                          quote='"', escape='"', nullstr='', encoding='latin-1')
        """).to_arrow_table()
    if not arrow.num_rows:
        raise SystemExit(f"ers_rucc: {url} yielded no rows")

    n = merge.write(cat, "raw.ers__rucc", arrow, EqualTo("rucc_edition", EDITION))
    merge.manifest(cat, release, "ers_rucc", url, n, version=EDITION, method="release_number")
    lineage.record(cat, release, "ers_rucc", None, {"raw.ers__rucc": url})
    return EDITION, n


def transform(cat, release, edition):
    """Phase 2: one RUCC observation per county, plus the measure definition
    and its (not-applicable) stratum.

    Scoped to `edition`'s rows: raw accumulates every landed edition, so an
    unscoped read would derive from all of them at once.
    """
    con = lineage.connect()
    lineage.load(con, cat, "raw", "raw.ers__rucc", row_filter=EqualTo("rucc_edition", edition))

    definition_sql = f"""
        SELECT 'RUCC:code' AS measure_id, 'RUCC' AS source,
               'Rural-Urban Continuum Code' AS label, 'code 1-9' AS units,
               NULL::VARCHAR AS universe, 'index' AS rate_basis,
               NULL::VARCHAR AS age_adjustment, 'derived' AS method,
               NULL::VARCHAR AS cancer_site_code, '{CODE_DOC}' AS doc
    """
    definition = con.sql(definition_sql).to_arrow_table()

    stratum_sql = """
        SELECT 'RUCC:none' AS stratum_id, 'RUCC' AS source,
               NULL::VARCHAR AS sex, NULL::VARCHAR AS age_group,
               NULL::VARCHAR AS race_ethnicity, NULL::VARCHAR AS stage,
               NULL::VARCHAR AS other, 'RUCC_NONE' AS scheme
    """
    stratum = con.sql(stratum_sql).to_arrow_table()

    # One row per county (from any attribute) LEFT JOINed to its RUCC value --
    # Rose Island and Swains Island carry no RUCC_2023 row at all, so the join
    # leaves Value NULL rather than dropping them or inventing a code.
    observation_sql = f"""
        SELECT 'RUCC' AS source, '{edition}' AS source_release, 'RUCC:code' AS measure_id,
               'county:' || lpad(c.FIPS, 5, '0') AS geo_id, {GEO_VINTAGE} AS geo_vintage,
               '{edition}' AS period_start, '{edition}' AS period_end,
               'RUCC:none' AS stratum_id, TRY_CAST(r.Value AS DOUBLE) AS value,
               NULL::DOUBLE AS lower, NULL::DOUBLE AS upper,
               NULL::DOUBLE AS interval_level, NULL::DOUBLE AS numerator,
               NULL::DOUBLE AS denominator,
               -- Status follows the CAST that actually produced `value`, not
               -- the raw cell's presence -- a present-but-non-numeric cell
               -- (never seen in the real file, verified 2026-09-18) must not
               -- land as a numberless 'reported' row (merge.check_observations).
               CASE WHEN TRY_CAST(r.Value AS DOUBLE) IS NOT NULL THEN 'reported'
                    ELSE 'not_available' END AS value_status,
               NULL::VARCHAR AS reliability_flag, NULL::VARCHAR AS trend
        FROM (SELECT DISTINCT FIPS FROM raw) c
        LEFT JOIN raw r ON r.FIPS = c.FIPS AND r.Attribute = 'RUCC_{edition}'
    """
    observation = con.sql(observation_sql).to_arrow_table()
    merge.check_observations(observation)

    scope = EqualTo("source", "RUCC")
    # Overwrite only the ids this edition asserts, not the whole `source =
    # 'RUCC'` scope — the same wholesale-replace shape PLACES hit in #76 (RUCC
    # has only ever published one measure_id/stratum_id, but the scope should
    # not depend on that staying true).
    result = {
        "measure.definition": merge.write(cat, "measure.definition", definition,
                                          And(scope, In("measure_id", ["RUCC:code"]))),
        "measure.stratum": merge.write(cat, "measure.stratum", stratum,
                                       And(scope, In("stratum_id", ["RUCC:none"]))),
        "measure.observation": merge.merge(
            cat, "measure.observation", observation, release,
            And(scope, EqualTo("source_release", edition))),
    }
    lineage.record(cat, release, "ers_rucc", con, {
        "measure.definition": definition_sql,
        "measure.stratum": stratum_sql,
        "measure.observation": observation_sql,
    })
    return result


def ingest(cat, release, url=None):
    edition, n = land_raw(cat, release, url)
    return {"raw.ers__rucc": n, **transform(cat, release, edition)}
