"""US Census Bureau Gazetteer Files -> geography.unit, the non-geometry half
of the geography spine (SPEC.md § Geography).

Upstream: https://www.census.gov/geographies/reference-files/time-series/geo/gazetteer-files.html
lists one national county file and one national tract file per vintage year,
zipped tab- (or, from 2025, pipe-) delimited text under
https://www2.census.gov/geo/docs/maps-data/data/gazetteer/, e.g.
`2024_Gazetteer/2024_Gaz_counties_national.zip`. The 2010 files live at the
same host without a year folder or prefix (`Gaz_counties_national.zip`) and
carry two extra 2010-Census columns, POP10/HU10, that later vintages drop.

**Licence.** U.S. Census Bureau content is a federal government work. Per
resources.data.gov/open-licenses/ (the definition data.gov uses for every
federal agency's "Public Domain" listing): "Data and content created by
government employees within the scope of their employment are not subject to
domestic copyright protection under 17 U.S.C. § 105. Government works are by
default in the U.S. Public Domain." No registration or attribution is
required to redistribute.

**Version axis: release.** Each file is one dated annual (or decennial)
edition, e.g. "2024_Gazetteer" — a citable label the source itself publishes,
not a retrieval date, so `merge.manifest` is called with
`method="release_number"` and `version=<the gazetteer year>` (SPEC.md's
vintage rule for sources with no other version label).

**Geography vintage.** The gazetteer year *is* the boundary vintage: Census's
own TIGER/Line documentation states legal boundaries and names in a given
year's shapefiles are "as of January 1" of that year (confirmed against the
2020, 2022 and 2023 TIGER/Line pages), and the gazetteer files are released
under the same year label as extracts of the matching TIGER/Line vintage — the
switch from Connecticut's eight counties (present through the 2020 files) to
its nine planning regions, FIPS 09110-09190 (present from at least 2024),
lines up with Connecticut's real-world 2022 change and confirms the two
follow the same clock.

**Header quirk.** The 2010 and "modern" (2011-2024) layouts pad their last
header column, INTPTLONG, with trailing spaces before the newline; the 2025+
layout does not, and also gained a fully-qualified `GEOIDFQ` column and
switched delimiter from tab to pipe. Three real layouts, two file kinds ->
`COUNTY_COLUMNS`/`TRACT_COLUMNS` hold one COLUMNS contract per layout instead
of a single module-level COLUMNS (the source-common convention assumes one
layout per source; this source has three, verified 2026-09-18 against the
real 2010, 2020 and 2026 files). A header matching none of them raises
SystemExit before anything is read, same as a single-layout source.

**Encoding quirk.** The 2010 county file has one stray Latin-1 byte instead of
UTF-8 (NM 35013, "Doña Ana County"); every other vintage checked, and the 2010
tract file (which has no NAME column to carry the accent), are clean UTF-8.
`_ensure_utf8` decodes the whole file as Latin-1 on a UTF-8 failure — safe
because the rest of the file is plain ASCII, where Latin-1 and UTF-8 agree —
recovering the intended character exactly rather than raising or replacing it
with U+FFFD.

ponytail: only counties and tracts are landed (SPEC.md M1 asks for county +
tract, 2010 + 2020 + latest). Places, county subdivisions, ZCTAs, PUMAs and
every other gazetteer file are not — add one alongside these two if a later
milestone needs it.

ponytail: state names come from `raw.census__state_fips`
(https://www2.census.gov/geo/docs/reference/state.txt, landed once per
release, not per vintage — FIPS-to-state assignments don't move on the
gazetteer's cadence). If that file can't be reached, `land_state_fips` warns
and returns 0 rather than failing the whole ingest; `transform` then falls
back to the state's USPS code as its name, and says so in the same way.

ponytail: layout choice is decided purely by matching the file's own header
against the three known contracts, not by branching on the year — so a year
outside 2010/2011-2024/2025+ that happens to match a known layout still lands
correctly, and one that doesn't fails loudly rather than guessing.

ponytail: no `geography.crosswalk` row for the Connecticut county -> planning
region transition. Each vintage's units stand on their own; a weighted
crosswalk (SPEC.md Acceptance B) is a separate, still-open piece of work.

---

**Districts (#104).** The same Gazetteer host also carries one national
congressional-district (CD) file and one national state-legislative file per
chamber (SLDU/SLDL upper/lower) per vintage year, e.g.
`2024_Gazetteer/2024_Gaz_119CDs_national.zip`,
`2024_Gazetteer/2024_Gaz_sldu_national.zip` — confirmed 2026-09-19 against the
2024 and 2026 gazetteer directory listings. Same public-domain licence as
above (same host, same federal-agency doctrine); checked again 2026-09-19.

**CD version axis: Congress number, not the gazetteer year.** The issue's own
framing states it: "Congress number / redistricting cycle = the boundary
vintage." Census re-labels the CD file for whichever Congress its maps
currently serve (2024_Gazetteer → 119CDs, 2026_Gazetteer → 120CDs, even before
the 120th is sworn in) and updates it mid-cycle for court-ordered redraws —
confirmed real: North Carolina's district 3701 carries a materially different
ALAND/AWATER between the 2024 (119CDs) and 2026 (120CDs) files, the same
boundary vintage window the issue names (NC, AL, LA, NY, GA). `land_districts`
resolves the Congress number for a gazetteer year from `CD_CONGRESS`
(verified against the real directory listings, 2017-2026) rather than
guessing a formula, and skips CD (warn, continue) for a year outside it — the
same graceful-degradation shape `land_state_fips`/`transform` already use for
state names, so a district-less year never fails the whole ingest.
`geography.unit.vintage` stays the gazetteer year for cd/sldu/sldl too (not
the Congress number) — consistent with every other level, and sufficient:
landing two gazetteer years both lands and keeps both boundaries queryable,
Congress number or not, exactly like Connecticut's county -> planning-region
switch above.

**GEOID, not a NAME column, for CD.** Unlike SLDU/SLDL (which publish NAME,
e.g. "State Senate District 1"), the CD file has no NAME column (like tracts)
— `transform` synthesizes "Congressional District N" from the GEOID's
district digits, "Congressional District At Large" for the single-district
states (WY, VT, ... — GEOID's last two digits '00', verified against the real
file).

**No 2010 layout for districts.** ponytail: CD/SLDU/SLDL are only landed in
the "modern" (2011-2024) and "2025+" layouts — the same two the 2024/2026
files above are in. The 2010-era files exist (`Gaz_cd111_national.zip`,
`Gaz_sldu_national.zip`, `Gaz_sldl_national.zip`, confirmed 2026-09-19) but
add a third naming scheme (`cd111`, the Congress number *before* "CDs") and a
third column layout (POP10/HU10, like 2010 counties) for a vintage this
milestone doesn't need — add `CD_COLUMNS["2010"]`/a `_cd_zip_url` 2010 case
alongside `COUNTY_COLUMNS["2010"]`'s if a later milestone lands district
history back to 2010.

**Tract -> district weights: deferred to #25, not landed here.** An earlier
version of this module landed the 2020 redistricting-cycle Block Assignment
Files (`raw.census__baf`, one zip per state,
`https://www2.census.gov/geo/docs/maps-data/data/baf2020/`) and a
`tract_district_weights` recipe over them. Caught in review (2026-09-19):
that BAF product ties blocks to the *116th-Congress* CD lines (the map in
effect for the 2020 Census), not the 2024/2020-Gazetteer/2026-Gazetteer
vintages this module actually lands (119th/120th) — joining it against
`geography.unit`'s cd/sldu/sldl rows here would silently emit district ids
for the wrong vintage. Removed rather than shipped wrong. #25
(`geography.crosswalk`) should instead use the Census Block Equivalency
Files for the 118th/119th Congress cycle (correct vintage; not yet verified
against a live download) when it lands the weighted crosswalk — this module
stops at landing the district units themselves.
"""

import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

import duckdb
from pyiceberg.exceptions import NoSuchTableError
from pyiceberg.expressions import AlwaysTrue, EqualTo

from . import merge

USER_AGENT = "cancerbasemap/0.1 (+https://github.com/seandavi/cancer-basemap)"
BASE = "https://www2.census.gov/geo/docs/maps-data/data/gazetteer"
STATE_FIPS_URL = "https://www2.census.gov/geo/docs/reference/state.txt"
STATE_COLUMNS = ("STATE", "STUSAB", "STATE_NAME", "STATENS")

# One COLUMNS contract per real layout (see module docstring). Order matches
# the file, header names exactly as Census spells them.
COUNTY_COLUMNS = {
    "2010": ("USPS", "GEOID", "ANSICODE", "NAME", "POP10", "HU10", "ALAND", "AWATER",
             "ALAND_SQMI", "AWATER_SQMI", "INTPTLAT", "INTPTLONG"),
    "modern": ("USPS", "GEOID", "ANSICODE", "NAME", "ALAND", "AWATER",
               "ALAND_SQMI", "AWATER_SQMI", "INTPTLAT", "INTPTLONG"),
    "2025": ("USPS", "GEOID", "GEOIDFQ", "ANSICODE", "NAME", "ALAND", "AWATER",
             "ALAND_SQMI", "AWATER_SQMI", "INTPTLAT", "INTPTLONG"),
}
TRACT_COLUMNS = {
    "2010": ("USPS", "GEOID", "POP10", "HU10", "ALAND", "AWATER",
             "ALAND_SQMI", "AWATER_SQMI", "INTPTLAT", "INTPTLONG"),
    "modern": ("USPS", "GEOID", "ALAND", "AWATER", "ALAND_SQMI", "AWATER_SQMI",
               "INTPTLAT", "INTPTLONG"),
    "2025": ("USPS", "GEOID", "GEOIDFQ", "ALAND", "AWATER", "ALAND_SQMI", "AWATER_SQMI",
             "INTPTLAT", "INTPTLONG"),
}
# raw.census__gazetteer_{counties,tracts}' own column order: the union of
# every layout, so a layout missing a column (POP10/HU10 outside 2010,
# GEOIDFQ before 2025) just lands NULL for it there.
FULL_COUNTY_COLUMNS = ("usps", "geoid", "geoidfq", "ansicode", "name", "pop10", "hu10",
                       "aland", "awater", "aland_sqmi", "awater_sqmi", "intptlat", "intptlong")
FULL_TRACT_COLUMNS = ("usps", "geoid", "geoidfq", "pop10", "hu10",
                      "aland", "awater", "aland_sqmi", "awater_sqmi", "intptlat", "intptlong")

# Districts (#104): CD has no NAME column (like tracts); SLDU/SLDL do (like
# counties). No "2010" layout -- see module docstring.
CD_COLUMNS = {
    "modern": ("USPS", "GEOID", "ALAND", "AWATER", "ALAND_SQMI", "AWATER_SQMI",
               "INTPTLAT", "INTPTLONG"),
    "2025": ("USPS", "GEOID", "GEOIDFQ", "ALAND", "AWATER", "ALAND_SQMI", "AWATER_SQMI",
             "INTPTLAT", "INTPTLONG"),
}
SLD_COLUMNS = {
    "modern": ("USPS", "GEOID", "NAME", "ALAND", "AWATER", "ALAND_SQMI", "AWATER_SQMI",
               "INTPTLAT", "INTPTLONG"),
    "2025": ("USPS", "GEOID", "GEOIDFQ", "NAME", "ALAND", "AWATER", "ALAND_SQMI", "AWATER_SQMI",
             "INTPTLAT", "INTPTLONG"),
}
FULL_CD_COLUMNS = ("usps", "geoid", "geoidfq",
                   "aland", "awater", "aland_sqmi", "awater_sqmi", "intptlat", "intptlong")
FULL_SLD_COLUMNS = ("usps", "geoid", "geoidfq", "name",
                    "aland", "awater", "aland_sqmi", "awater_sqmi", "intptlat", "intptlong")

# gazetteer year -> the Congress number Census labels that year's CD file
# with (module docstring), verified 2026-09-19 against the real directory
# listings for every year here. A year outside this dict has its CD file
# skipped (land_districts warns, continues) rather than guessed.
CD_CONGRESS = {2017: 115, 2018: 116, 2019: 116, 2020: 116, 2021: 116, 2022: 116,
              2023: 118, 2024: 119, 2025: 119, 2026: 120}


def _zip_url(kind, year):
    if year == 2010:
        return f"{BASE}/Gaz_{kind}_national.zip"
    return f"{BASE}/{year}_Gazetteer/{year}_Gaz_{kind}_national.zip"


def _cd_zip_url(year):
    """CD's file name embeds the serving Congress (module docstring), not a
    fixed word, so it doesn't fit `_zip_url`'s formula. None for a year
    outside `CD_CONGRESS` -- the caller decides what a missing Congress
    number means (`land_districts` skips CD and warns)."""
    congress = CD_CONGRESS.get(year)
    return None if congress is None else f"{BASE}/{year}_Gazetteer/{year}_Gaz_{congress}CDs_national.zip"


def _download(url, tmpdir, name):
    """`url` as a local path: downloaded to `tmpdir/name` if it's `https://`,
    used as-is otherwise (a local file, how the offline tests stay offline)."""
    if not url.startswith("http"):
        return Path(url)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    dest = Path(tmpdir) / name
    with urllib.request.urlopen(req) as r, open(dest, "wb") as f:
        f.write(r.read())
    return dest


def _fetch_txt(url, tmpdir):
    """The gazetteer text file at `url`: downloaded and unzipped if it's an
    `https://` zip, used as-is otherwise (a local .txt, how the offline tests
    stay offline)."""
    src = _download(url, tmpdir, "gazetteer.zip")
    if src.suffix != ".zip":
        return src
    with zipfile.ZipFile(src) as z:
        names = [n for n in z.namelist() if n.endswith(".txt")]
        if len(names) != 1:
            raise SystemExit(f"census gazetteer: {url} has {len(names)} .txt member(s), expected 1")
        z.extract(names[0], tmpdir)
        return Path(tmpdir) / names[0]


def _ensure_utf8(path):
    """The 2010 county file has one stray Latin-1 byte instead of UTF-8: NM
    35013 is 'Do\\xf1a Ana County' (verified 2026-09-18 against the real
    download; every other byte in every layout checked is plain ASCII).
    Decoding the whole file as Latin-1 on a UTF-8 failure recovers the
    intended character ('Doña Ana County') exactly rather than dropping or
    corrupting the row, since Latin-1 and ASCII agree on every byte the file
    otherwise uses."""
    raw = path.read_bytes()
    try:
        raw.decode("utf-8")
        return path
    except UnicodeDecodeError:
        fixed = path.with_name(path.stem + ".utf8" + path.suffix)
        fixed.write_text(raw.decode("latin-1"), encoding="utf-8")
        return fixed


def _detect(path, columns_by_layout):
    """Which of this file kind's known layouts `path`'s header matches, and its
    delimiter. Whitespace Census pads the last header column with (see module
    docstring) is stripped before comparing; a header matching none of the
    known layouts fails loudly rather than landing a guessed shape."""
    with open(path, "rb") as f:
        first = f.readline().decode("utf-8", "replace")
    delim = "|" if "|" in first.splitlines()[0] else "\t"
    header = tuple(first.rstrip().split(delim))
    for layout, cols in columns_by_layout.items():
        if header == cols:
            return layout, delim
    raise SystemExit(f"census gazetteer: header {header} matches no known layout "
                     f"(known: {columns_by_layout})")


def _land_file(cat, release, year, url, tmpdir, columns_by_layout, full_columns, identifier):
    path = _ensure_utf8(_fetch_txt(url, tmpdir))
    layout, delim = _detect(path, columns_by_layout)
    names = [c.lower() for c in columns_by_layout[layout]]
    select = ", ".join(c if c in names else f"NULL::VARCHAR AS {c}" for c in full_columns)
    con = duckdb.connect()
    # quote='' and escape='' — these files are never quoted, and letting DuckDB
    # sniff a quote character (its default when one isn't stated) can pair a
    # stray byte with an unrelated later line into one bad multi-line record.
    arrow = con.sql(f"""
        SELECT {select}, {year} AS gazetteer_year, '{release}' AS landed_in
        FROM read_csv('{path}', header=false, skip=1, delim='{delim}', quote='', escape='',
                      names={names!r}, all_varchar=true)
    """).to_arrow_table()
    if not arrow.num_rows:
        raise SystemExit(f"census gazetteer: {url} yielded no rows")
    return merge.write(cat, identifier, arrow, EqualTo("gazetteer_year", year))


def land_raw(cat, release, year, county_url=None, tract_url=None):
    """Phase 1: one boundary vintage's county and tract files, landed verbatim
    and whole. Both are small enough (85k rows at most) to read in one shot —
    nothing here needs the NCBI dumps' streaming machinery. Returns
    `(year, {identifier: rows})`.
    """
    county_url = county_url or _zip_url("counties", year)
    tract_url = tract_url or _zip_url("tracts", year)
    with tempfile.TemporaryDirectory() as tmp:
        n_counties = _land_file(cat, release, year, county_url, tmp,
                                COUNTY_COLUMNS, FULL_COUNTY_COLUMNS,
                                "raw.census__gazetteer_counties")
        n_tracts = _land_file(cat, release, year, tract_url, tmp,
                              TRACT_COLUMNS, FULL_TRACT_COLUMNS,
                              "raw.census__gazetteer_tracts")
    # version_method='release_number': the gazetteer year is a citable label
    # Census itself publishes, not a retrieval date.
    merge.manifest(cat, release, "census_gazetteer", county_url, n_counties,
                   version=str(year), method="release_number")
    return year, {"raw.census__gazetteer_counties": n_counties,
                 "raw.census__gazetteer_tracts": n_tracts}


def land_state_fips(cat, release, url=None):
    """State FIPS reference, landed once per release (not per gazetteer year —
    FIPS-to-state assignments don't move on the gazetteer's cadence). A source
    that can't be reached at ingest time is not a reason to fail the whole
    ingest: warn and return 0; `transform` falls back to the USPS code as the
    state's name and says so.
    """
    url = url or STATE_FIPS_URL
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT}) if url.startswith("http") else url
        opener = urllib.request.urlopen if url.startswith("http") else open
        with opener(req) as r:
            first = r.readline()
    except urllib.error.URLError as err:
        print(f"census gazetteer: state.txt unreachable ({err}); "
             f"state names will fall back to USPS codes")
        return 0
    if isinstance(first, bytes):
        first = first.decode("utf-8", "replace")
    header = tuple(first.rstrip("\r\n").split("|"))
    if header != STATE_COLUMNS:
        raise SystemExit(f"census gazetteer: {url} header {header} is not {STATE_COLUMNS}")

    con = duckdb.connect()
    arrow = con.sql(f"""
        SELECT state AS state, stusab AS stusab, state_name AS state_name, statens AS statens,
               '{release}' AS landed_in
        FROM read_csv('{url}', header=true, delim='|', quote='', escape='', all_varchar=true)
    """).to_arrow_table()
    return merge.write(cat, "raw.census__state_fips", arrow, AlwaysTrue())


def transform(cat, release, year):
    """Phase 2: this vintage's nation/state/county/tract(/cd/sldu/sldl) rows
    into geography.unit, in ONE merge call scoped to `vintage = year` —
    loading a later vintage never retires an earlier one's rows (SPEC.md
    Acceptance B). Districts (#104) are folded into this same call, not a
    second `merge.merge(..., EqualTo("vintage", year))`: two calls sharing one
    scope is exactly issue #118 (the second retires the first's rows), so
    every level landed for this vintage is re-derived here every time
    (cdc_svi.py / census_acs.py do the same for their own scopes). A district
    raw table not landed for this vintage (NoSuchTableError, same guard as
    state_fips below) is simply left out of the UNION — the county/tract-only
    behaviour every existing caller relies on is unchanged.
    """
    con = duckdb.connect()
    con.register("counties", cat.load_table("raw.census__gazetteer_counties").scan(
        row_filter=EqualTo("gazetteer_year", year)).to_arrow())
    con.register("tracts", cat.load_table("raw.census__gazetteer_tracts").scan(
        row_filter=EqualTo("gazetteer_year", year)).to_arrow())

    try:
        con.register("state_fips", cat.load_table("raw.census__state_fips").scan().to_arrow())
        name_expr, join_sql = "coalesce(sf.state_name, sk.usps)", \
            "LEFT JOIN state_fips sf ON sf.state = sk.fips"
    except NoSuchTableError:
        print("census gazetteer: raw.census__state_fips not landed; "
             "state names will fall back to USPS codes")
        name_expr, join_sql = "sk.usps", ""

    # cd has no NAME column (module docstring): "Congressional District N" /
    # "...At Large" is synthesized from the GEOID's district digits. A few
    # rows per gazetteer year carry Census's own 'ZZ' sentinel (verified
    # 2026-09-19 against the real 2024 file: CT/IL/NH each have one, ALAND=0
    # -- water assigned to no district) instead of a number; TRY_CAST falls
    # back to the raw code rather than failing the whole transform on it.
    district_blocks = []
    for level, table_id, name_sql in (
        ("cd", "raw.census__gazetteer_cd",
         "'Congressional District ' || CASE WHEN substr(d.geoid, 3, 2) = '00' THEN 'At Large' "
         "ELSE coalesce(CAST(TRY_CAST(substr(d.geoid, 3, 2) AS INTEGER) AS VARCHAR), "
         "substr(d.geoid, 3, 2)) END"),
        ("sldu", "raw.census__gazetteer_sldu", "d.name"),
        ("sldl", "raw.census__gazetteer_sldl", "d.name"),
    ):
        try:
            con.register(f"{level}_raw", cat.load_table(table_id).scan(
                row_filter=EqualTo("gazetteer_year", year)).to_arrow())
        except NoSuchTableError:
            continue
        district_blocks.append(f"""
      UNION ALL
        SELECT '{level}:' || d.geoid, '{level}', d.geoid, {year}, {name_sql},
               'state:' || substr(d.geoid, 1, 2),
               TRY_CAST(d.aland AS DOUBLE), TRY_CAST(d.awater AS DOUBLE),
               TRY_CAST(d.intptlat AS DOUBLE), TRY_CAST(d.intptlong AS DOUBLE),
               CAST(NULL AS VARCHAR)
        FROM {level}_raw d""")

    unit = con.sql(f"""
        SELECT 'nation:US' AS geo_id, 'nation' AS level, 'US' AS fips, {year} AS vintage,
               'United States' AS name, CAST(NULL AS VARCHAR) AS parent_geo_id,
               CAST(NULL AS DOUBLE) AS aland_m2, CAST(NULL AS DOUBLE) AS awater_m2,
               CAST(NULL AS DOUBLE) AS centroid_lat, CAST(NULL AS DOUBLE) AS centroid_lon,
               CAST(NULL AS VARCHAR) AS geometry_uri
      UNION ALL
        SELECT 'state:' || sk.fips, 'state', sk.fips, {year}, {name_expr}, 'nation:US',
               NULL, NULL, NULL, NULL, NULL
        FROM (SELECT DISTINCT substr(geoid, 1, 2) AS fips, usps FROM counties) sk
        {join_sql}
      UNION ALL
        SELECT 'county:' || c.geoid, 'county', c.geoid, {year}, c.name,
               'state:' || substr(c.geoid, 1, 2),
               TRY_CAST(c.aland AS DOUBLE), TRY_CAST(c.awater AS DOUBLE),
               TRY_CAST(c.intptlat AS DOUBLE), TRY_CAST(c.intptlong AS DOUBLE),
               CAST(NULL AS VARCHAR)
        FROM counties c
      UNION ALL
        SELECT 'tract:' || t.geoid, 'tract', t.geoid, {year}, CAST(NULL AS VARCHAR),
               'county:' || substr(t.geoid, 1, 5),
               TRY_CAST(t.aland AS DOUBLE), TRY_CAST(t.awater AS DOUBLE),
               TRY_CAST(t.intptlat AS DOUBLE), TRY_CAST(t.intptlong AS DOUBLE),
               CAST(NULL AS VARCHAR)
        FROM tracts t
        {"".join(district_blocks)}
    """).to_arrow_table()

    return {"geography.unit": merge.merge(cat, "geography.unit", unit, release, EqualTo("vintage", year))}


def ingest(cat, release, year, county_url=None, tract_url=None, state_url=None):
    year, raw_counts = land_raw(cat, release, year, county_url, tract_url)
    n_state = land_state_fips(cat, release, state_url)
    return {**raw_counts, "raw.census__state_fips": n_state, **transform(cat, release, year)}


def land_districts(cat, release, year, cd_url=None, sldu_url=None, sldl_url=None):
    """Phase 1 for the three district levels (#104): CD/SLDU/SLDL Gazetteer
    files, same file family and layouts as counties/tracts (module docstring),
    landed into their own raw tables. Separate from `land_raw`/`ingest` so a
    year with no known Congress number, or the unsupported 2010 layout,
    never breaks plain county/tract landing (call this only when you want
    districts too; `transform` re-derives geography.unit safely either way).
    """
    sldu_url = sldu_url or _zip_url("sldu", year)
    sldl_url = sldl_url or _zip_url("sldl", year)
    with tempfile.TemporaryDirectory() as tmp:
        n_sldu = _land_file(cat, release, year, sldu_url, tmp,
                            SLD_COLUMNS, FULL_SLD_COLUMNS, "raw.census__gazetteer_sldu")
        n_sldl = _land_file(cat, release, year, sldl_url, tmp,
                            SLD_COLUMNS, FULL_SLD_COLUMNS, "raw.census__gazetteer_sldl")
        cd_url = cd_url or _cd_zip_url(year)
        if cd_url is None:
            print(f"census gazetteer: no known Congress number for gazetteer year {year} "
                 f"(CD_CONGRESS); skipping raw.census__gazetteer_cd")
            n_cd = 0
        else:
            n_cd = _land_file(cat, release, year, cd_url, tmp,
                              CD_COLUMNS, FULL_CD_COLUMNS, "raw.census__gazetteer_cd")
    merge.manifest(cat, release, "census_gazetteer_districts", sldu_url, n_sldu,
                   version=str(year), method="release_number")
    return year, {"raw.census__gazetteer_cd": n_cd, "raw.census__gazetteer_sldu": n_sldu,
                 "raw.census__gazetteer_sldl": n_sldl}


def ingest_districts(cat, release, year, cd_url=None, sldu_url=None, sldl_url=None):
    """Phase 1+2 for districts, callable on its own (see `land_districts`)."""
    _, district_counts = land_districts(cat, release, year, cd_url, sldu_url, sldl_url)
    return {**district_counts, **transform(cat, release, year)}
