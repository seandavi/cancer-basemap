"""FDA MQSA certified mammography facility list -> Iceberg, landed weekly.

Upstream: FDA's "Search for a Certified Facility" page --
https://www.fda.gov/radiation-emitting-products/consumer-information-mqsa/
search-certified-facility (redirects to a renamed slug on fda.gov, checked
2026-09-18) -- links "download the mammography facilities zip file ...
This file is replaced weekly" (fda.gov, same page, checked 2026-09-18) to
the historical, still-live URL http://www.accessdata.fda.gov/premarket/
ftparea/public.zip. The zip's own `Last-Modified` header read 2026-09-14
when checked 2026-09-18, consistent with a weekly refresh.

**Licence.** FDA is a federal agency; its site-wide policy
(https://www.fda.gov/about-fda/about-website/website-policies, checked
2026-09-18) states: "Unless otherwise noted, the contents of the FDA
website (www.fda.gov) -- both text and graphics -- are not copyrighted.
They are in the public domain and may be republished, reprinted and
otherwise used freely by anyone without the need to obtain permission from
FDA." There is no dataset-specific terms page for this listing (unlike
HRSA's per-dataset Data Usage Terms, hrsa_sites.py) -- this site-wide
statement, plus 17 U.S.C. Sec 105 (federal-employee works are not subject
to domestic copyright), is the licence basis, same as every other federal
source landed here.

**No individual records.** Every field is Facility Name / Address 1-3 /
City / State / Zip / Phone / Fax (verified against the live file
2026-09-18, and matches the field list FDA's own page publishes) -- no
clinician or patient data. FDA's page also notes Veterans Health
Administration facilities are excluded (MQSA does not apply to VHA).

**Version axis: retrieval date.** FDA replaces the whole file weekly with
no edition label -- the same shape as HRSA's two live snapshots
(hrsa_sites.py): `retrieved_on` is raw's version column, and
`merge.manifest` is called with method="retrieval_date".

**File format, verified 2026-09-18 by downloading the live zip.** One
member, `public.txt`: 9 pipe-delimited fields, in the order FDA's own page
documents (Facility Name(75) / Address 1(50) / Address 2(50) / Address
3(50) / City(50) / State(2) / Zip Code(15) / Phone(50) / Fax(50)) --
COLUMNS below. There is NO header row (confirmed against all 9,131 live
rows: none is the field-name list). CRLF line endings; every byte checked
across all 9,131 rows is plain ASCII (no Latin-1 gotcha here, unlike two
other sources in this repo); no quote characters or embedded delimiters
anywhere in the file, so `quote=''` (no quoting at all) is the honest
dialect rather than DuckDB's `"` default. `_check_layout` verifies the
first line still splits into exactly 9 pipe-delimited fields before
landing; a field added or removed upstream raises SystemExit rather than
silently misaligning every column that follows it.

**No facility id.** The file carries no id column of any kind. `facility_id`
is therefore 'FDA_MQSA:' + an md5 of the normalised (uppercased, internal
whitespace collapsed to one space) Facility Name + Address 1/2/3 + City +
State + the zip's first 5 digits -- phone/fax are excluded from the key
deliberately, see the next paragraph.

**Collision, seen in the real file (2026-09-18).** "Invision Diagnostics -
Mobile", Charlotte NC 28277, is listed three times: two rows share the
exact name/address text (differing only in phone number and one having
"MOBILE" capitalised) and collapse to the SAME key here; the third
differs in the address itself ("Elm Ln." vs "Elm Lane") and keeps its own
key. That is real untidiness in FDA's own list, not a bug in this
key -- deduplication keeps one row per key (`QUALIFY row_number() ...
= 1`, deterministic tie-break on name then address) and the ingest report
says how many raw rows collapsed.

ponytail: a facility that renames, or has its address re-typed, between
two snapshots looks exactly like the old one closing and a new one
opening (merge.merge's 'retired' + 'new', never 'changed'), because the
key IS the name+address text -- there is no id underneath to prove
continuity. That is the ceiling of any name+address key, not something
this module can compute around; the fix is FDA publishing a real id. A
direct consequence: facility.site's only non-key attributes for this
source are the always-'mammography' `kind` and the always-NULL
`lat`/`lon`/`geo_id`/`geo_vintage`, so a 'changed' row (same facility_id,
different attributes) structurally never happens for FDA_MQSA -- every
real edit surfaces as retire+new instead.

**Geography.** No coordinates, no FIPS anywhere in the file -- `lat`,
`lon`, `geo_id` and `geo_vintage` all land NULL; `zip`, `city`, `state`
go into `attributes_json` instead. Deriving `geo_id` needs a ZIP -> county
step (a ZCTA/ZIP crosswalk) that this module deliberately does not
perform: no geocoder dependency and no external geocoding API (AGENTS.md:
no new dependencies), and SPEC.md's own Open Questions flags ZIP/ZCTA
crosswalks as "the usual licence trap" -- issue #64 tracks that decision
and has not made it yet.

**facility.site.source_release is NULL for FDA_MQSA**, for the same
reason as HRSA_HC (hrsa_sites.py, issue #19): source_release is not part
of facility.site's business key, so an unchanged facility merges as
'unchanged' across retrieval dates instead of opening a fresh version
every single week purely because the snapshot date moved. The retrieval
date itself is recorded in provenance.release and in raw's own
retrieved_on, per SPEC.md's versioning model.
"""

import tempfile
import urllib.request
import zipfile
from datetime import date
from pathlib import Path

import duckdb
from pyiceberg.expressions import EqualTo

from . import merge

USER_AGENT = "cancerbasemap/1.0 (+https://github.com/seandavi/cancer-basemap)"
URL = "http://www.accessdata.fda.gov/premarket/ftparea/public.zip"

# The file's real 9 columns, in file order (no header row -- see module docstring).
COLUMNS = ("Facility Name", "Address 1", "Address 2", "Address 3",
          "City", "State", "Zip Code", "Phone", "Fax")


def _fetch_txt(url, tmpdir):
    """The MQSA text file at `url`: downloaded and unzipped if it's the
    remote zip (the live upstream); used as-is otherwise (a local .txt, how
    the offline tests stay offline). Mirrors census_gazetteer.py's helper."""
    if url.startswith("http"):
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        zpath = Path(tmpdir) / "public.zip"
        with urllib.request.urlopen(req) as r, open(zpath, "wb") as f:
            f.write(r.read())
        src = zpath
    else:
        src = Path(url)
    if src.suffix != ".zip":
        return src
    with zipfile.ZipFile(src) as z:
        names = z.namelist()
        if len(names) != 1:
            raise SystemExit(f"fda_mqsa: {url} has {len(names)} member(s), expected 1")
        z.extract(names[0], tmpdir)
        return Path(tmpdir) / names[0]


def _check_layout(path, columns):
    """The file's contract is its field COUNT, not a header -- there is none
    (module docstring). A field added or removed upstream changes this
    before it can misalign every column after it."""
    with open(path, "rb") as f:
        first = f.readline()
    fields = first.decode("utf-8").rstrip("\r\n").split("|")
    if len(fields) != len(columns):
        raise SystemExit(f"fda_mqsa: {path} has {len(fields)} pipe-delimited fields "
                         f"on its first line, expected {len(columns)} {columns} -- "
                         f"upstream layout may have changed")


def land_raw(cat, release, url=None, retrieved_on=None):
    """Phase 1: the whole file, verbatim, replaced per retrieval date -- FDA
    publishes no edition label (module docstring)."""
    retrieved_on = retrieved_on or date.today().isoformat()
    url = url or URL
    names_sql = "[" + ", ".join(f"'{c}'" for c in COLUMNS) + "]"
    with tempfile.TemporaryDirectory() as tmpdir:
        path = _fetch_txt(url, tmpdir)
        _check_layout(path, COLUMNS)
        con = duckdb.connect()
        arrow = con.sql(f"""
            SELECT *, '{retrieved_on}' AS retrieved_on, '{release}' AS landed_in
            FROM read_csv('{path}', header=false, all_varchar=true, delim='|',
                          quote='', names={names_sql})
        """).to_arrow_table()
    if not arrow.num_rows:
        raise SystemExit(f"fda_mqsa: {url} yielded no rows")

    n = merge.write(cat, "raw.fda__mqsa_facilities", arrow, EqualTo("retrieved_on", retrieved_on))
    merge.manifest(cat, release, "fda_mqsa", url, n, version=retrieved_on, method="retrieval_date")
    return retrieved_on, n


def transform(cat, release, retrieved_on):
    """Phase 2: facility.site, kind='mammography'. Keyed and deduplicated on
    the normalised name+address+zip hash -- see module docstring for why
    (no upstream id) and for the real collision it resolves."""
    con = duckdb.connect()
    con.register("raw", cat.load_table("raw.fda__mqsa_facilities").scan(
        row_filter=EqualTo("retrieved_on", retrieved_on)).to_arrow())

    # chr(31) (unit separator) joins the normalised fields before hashing --
    # never appears in the source text, so it can't create a false collision
    # the way a printable delimiter could (e.g. "AB"+"C" vs "A"+"BC").
    keyed = con.sql("""
        SELECT *,
               'FDA_MQSA:' || md5(concat_ws(chr(31),
                   regexp_replace(upper(trim("Facility Name")), '\\s+', ' ', 'g'),
                   regexp_replace(upper(trim(coalesce("Address 1", ''))), '\\s+', ' ', 'g'),
                   regexp_replace(upper(trim(coalesce("Address 2", ''))), '\\s+', ' ', 'g'),
                   regexp_replace(upper(trim(coalesce("Address 3", ''))), '\\s+', ' ', 'g'),
                   regexp_replace(upper(trim(coalesce("City", ''))), '\\s+', ' ', 'g'),
                   regexp_replace(upper(trim(coalesce("State", ''))), '\\s+', ' ', 'g'),
                   substr(coalesce("Zip Code", ''), 1, 5)
               )) AS facility_id
        FROM raw
    """)
    con.register("keyed", keyed)
    n_raw, n_keys = con.sql(
        "SELECT count(*), count(DISTINCT facility_id) FROM keyed").fetchone()
    collisions = n_raw - n_keys

    site = con.sql("""
        SELECT facility_id, 'FDA_MQSA' AS source, NULL::VARCHAR AS source_release,
               'mammography' AS kind, "Facility Name" AS name,
               concat_ws(', ', "Address 1", "Address 2", "Address 3", "City", "State", "Zip Code")
                   AS address,
               NULL::DOUBLE AS lat, NULL::DOUBLE AS lon,
               NULL::VARCHAR AS geo_id, NULL::INTEGER AS geo_vintage,
               to_json({'zip': "Zip Code", 'city': "City", 'state': "State"}) AS attributes_json
        FROM keyed
        QUALIFY row_number() OVER (PARTITION BY facility_id ORDER BY "Facility Name", "Address 1") = 1
    """).to_arrow_table()

    counts = {"facility.site": merge.merge(cat, "facility.site", site, release,
                                           EqualTo("source", "FDA_MQSA"))}
    if collisions:
        # Not a table -- a diagnostic the caller (and __main__'s _print) surfaces
        # as a plain row count, per the module docstring's real-file example.
        counts["facility.site key collisions"] = collisions
    return counts


def ingest(cat, release, url=None, retrieved_on=None):
    retrieved_on, n_raw = land_raw(cat, release, url, retrieved_on)
    return {"raw.fda__mqsa_facilities": n_raw, **transform(cat, release, retrieved_on)}
