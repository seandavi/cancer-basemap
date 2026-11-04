"""Release bundle (ADR-0001, #171): every published table as flat Parquet, plus
`cancerbasemap.duckdb`, `views.sql`, `restore.sql` and `manifest.json`, in one local directory.

The mechanics (COPY to Parquet, views.sql, restore.sql, the DuckDB file, manifest.json) are
`cdsci.publish`, shared with biocOnIce (cdsci-lake ADR-0027). This module is the cancer
policy: which tables, with which SELECT, documented how, and where the bundle will live.
`TABLES` is (schema, table, SELECT) against whatever DuckDB has attached as `coi` (the live
Iceberg catalog). A table moves to cdsci-lake by changing its SELECT. Nothing is uploaded here.

Type-2 tables (those with `valid_to`) publish current rows only and drop `valid_from` /
`valid_to`; raw tables ship whole.
"""

from pathlib import Path

import cdsci.publish
import duckdb

from .schemas import TABLES as DECLARED

DEFAULT_BASE_URL = "https://basemap.cancerdatasci.org/data/latest"
DB_FILE = "cancerbasemap.duckdb"
# README "Query it": anonymous, read-only.
ATTACH_LIVE = (
    "INSTALL iceberg; LOAD iceberg; ATTACH 'canceronice' AS coi (TYPE ICEBERG, "
    "ENDPOINT 'https://icegate-canceronice.seandavi.workers.dev', AUTHORIZATION_TYPE 'none')"
)
HISTORY_COLUMNS = ("valid_from", "valid_to")
HISTORY_NOTE = " In the release bundle: current rows only, without valid_from / valid_to."
# what the data was built from: every provenance.release row at build time
PROVENANCE_SQL = "SELECT * FROM coi.provenance.release ORDER BY ALL"

# Declared tables that are not published, each with its reason. None yet.
EXCLUDED: dict[str, str] = {}


# measure.observation is read in the browser by byte range, and a catchment profile wants a
# few dozen geographies out of 30M rows. Sorting by geography level and state first puts one
# state's counties and tracts in a few row groups, whose geo_id min/max then prune the rest;
# the old (source_release, measure_id, geo_id) order scattered them over every row group of
# every measure. Replaying one center's queries (#206): 47 MB -> 8 MB read natively, ~160 -> ~59
# MB under a 16 MB read-ahead model. One-measure-all-counties reads 1 -> 5 MB. Smaller row
# groups did not help: the footer grows and requests multiply (docs/adr/0001, Layout).
ORDER_BY = {
    "measure.observation": "left(geo_id, instr(geo_id, ':') + 2), source, source_release, measure_id, geo_id",
}


def _select(name, d):
    """Type-2 tables: current rows, validity columns dropped. Everything else: whole."""
    if any(f.name == "valid_to" for f in d.schema.fields):
        sql = (f"SELECT * EXCLUDE ({', '.join(HISTORY_COLUMNS)}) FROM coi.{name} "
               "WHERE valid_to IS NULL")
    else:
        sql = f"SELECT * FROM coi.{name}"
    return f"{sql} ORDER BY {ORDER_BY[name]}" if name in ORDER_BY else sql


TABLES = [(*name.split("."), _select(name, d)) for name, d in DECLARED.items()
          if name not in EXCLUDED]


def connect():
    """DuckDB with the live Iceberg catalog attached as `coi`."""
    con = duckdb.connect()
    con.execute(ATTACH_LIVE)
    return con


def _docs(name):
    """(table comment, {column: doc}) from the declarations."""
    d = DECLARED[name]
    versioned = any(f.name == "valid_to" for f in d.schema.fields)
    return d.comment + (HISTORY_NOTE if versioned else ""), {f.name: f.doc for f in d.schema.fields if f.doc}


def _lit(s):
    return "'" + s.replace("'", "''") + "'"


def publish(con, out: Path, base_url: str = DEFAULT_BASE_URL, only=None) -> dict:
    """Build one release bundle in `out` from `con`, which has the catalog attached as `coi`.

    `out` must be new or empty, so nothing from an earlier run sits beside a manifest that
    does not list it (biocOnIce's release script re-runs into one directory; ours does not).
    """
    if out.exists() and any(out.iterdir()):
        raise ValueError(f"{out} is not empty: publish into a new directory")
    out.mkdir(parents=True, exist_ok=True)
    return cdsci.publish.publish(con, out, tables=TABLES, docs=_docs, base_url=base_url,
                                 db_file=DB_FILE, code_dir=Path(__file__).parent,
                                 provenance_sql=PROVENANCE_SQL, only=only)
