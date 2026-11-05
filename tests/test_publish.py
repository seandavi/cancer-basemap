"""`cancerbasemap publish`: a release bundle from the local sqlite warehouse, offline.

The bundle mechanics are cdsci.publish's and tested there (cdsci-lake); this covers the
cancer policy on top: which rows a type-2 table ships, the declared docs, the table list,
and measure.observation's layout.
"""

import json

import duckdb
import pytest
from pyiceberg.expressions import EqualTo

from cancerbasemap import geography_alias, merge, publish, schemas

ONLY = ["geography.alias", "raw.geography__county_recodes", "provenance.release"]


@pytest.fixture
def con(cat):
    """geography.alias after two releases (the second drops one recode, closing its row),
    copied into DuckDB as the `coi` catalog."""
    geography_alias.ingest(cat, "2026.09")
    alias = cat.load_table("geography.alias").scan().to_arrow()
    incoming = alias.slice(1).select([c for c in alias.column_names if not c.startswith("valid_")])
    merge.merge(cat, "geography.alias", incoming, "2026.10", EqualTo("source", geography_alias.SOURCE))
    c = duckdb.connect()
    c.execute("ATTACH ':memory:' AS coi")
    for ns in cat.list_namespaces():
        c.execute(f"CREATE SCHEMA coi.{ns[0]}")
        for ident in cat.list_tables(ns):
            arrow = cat.load_table(ident).scan().to_arrow()  # noqa: F841 (read by DuckDB)
            c.execute(f"CREATE TABLE coi.{'.'.join(ident)} AS SELECT * FROM arrow")
    return c


def test_type2_table_ships_current_rows_without_validity_columns(con, tmp_path):
    assert con.sql("SELECT count(*) FROM coi.geography.alias").fetchone()[0] == 3
    assert con.sql("SELECT count(*) FROM coi.geography.alias WHERE valid_to IS NOT NULL").fetchone()[0] == 1
    closed = con.sql("SELECT old_geo_id FROM coi.geography.alias WHERE valid_to IS NOT NULL").fetchone()[0]

    out = tmp_path / "release"
    m = publish.publish(con, out, out.as_uri(), ONLY)

    parquet = out / "geography/alias.parquet"
    cols = {r[0] for r in duckdb.sql(f"DESCRIBE SELECT * FROM '{parquet}'").fetchall()}
    assert not cols & {"valid_from", "valid_to"}
    ids = {r[0] for r in duckdb.sql(f"SELECT old_geo_id FROM '{parquet}'").fetchall()}
    assert len(ids) == 2 and closed not in ids
    alias = next(t for t in m["tables"] if t["table"] == "alias")
    assert alias["row_count"] == 2
    assert not {c["name"] for c in alias["columns"]} & {"valid_from", "valid_to"}
    assert "current rows only" in alias["comment"]


def test_raw_and_provenance_ship_whole_with_the_declared_docs(con, tmp_path):
    out = tmp_path / "release"
    m = publish.publish(con, out, out.as_uri(), ONLY)

    assert m["manifest_version"] == 1
    want = {"geography.alias": 2,
            "raw.geography__county_recodes": con.sql("SELECT count(*) FROM coi.raw.geography__county_recodes").fetchone()[0],
            "provenance.release": con.sql("SELECT count(*) FROM coi.provenance.release").fetchone()[0]}
    assert {f"{t['schema']}.{t['table']}": t["row_count"] for t in m["tables"]} == want
    # per-source provenance from provenance.release, dates serialised
    assert {p["source"] for p in m["provenance"]} == {"geography_alias"}
    assert json.loads((out / "manifest.json").read_text())["provenance"] == json.loads(json.dumps(m["provenance"], default=str))

    # the declared column docs reach cancerbasemap.duckdb
    db = duckdb.connect()
    db.execute(f"ATTACH '{out / publish.DB_FILE}' AS rel (READ_ONLY)")
    docs = dict(db.sql("SELECT column_name, comment FROM duckdb_columns() WHERE database_name = 'rel' "
                       "AND schema_name = 'geography' AND table_name = 'alias'").fetchall())
    assert docs["change_type"].startswith("One of: recode")


def test_every_declared_table_is_published_unless_excluded_with_a_reason():
    published = {f"{s}.{t}" for s, t, _ in publish.TABLES}
    assert published | set(publish.EXCLUDED) == set(schemas.TABLES)
    assert not published & set(publish.EXCLUDED)
    assert all(publish.EXCLUDED.values())


def test_selects_drop_history_only_for_type_2_tables():
    sql = {f"{s}.{t}": q for s, t, q in publish.TABLES}
    for name, d in schemas.TABLES.items():
        type2 = any(f.name == "valid_to" for f in d.schema.fields)
        assert ("WHERE valid_to IS NULL" in sql[name]) == type2
        assert ("EXCLUDE (valid_from, valid_to)" in sql[name]) == type2
    assert {n for n, q in sql.items() if "valid_to" in q} == {
        "geography.unit", "geography.alias", "measure.observation", "measure.cancer_site",
        "measure.cancer_site_group", "facility.site", "catchment.center", "catchment.member"}


def test_observation_is_written_clustered_by_geography_level_and_state(tmp_path):
    c = duckdb.connect()
    c.execute("ATTACH ':memory:' AS coi")
    c.execute("CREATE SCHEMA coi.measure")
    c.execute("CREATE SCHEMA coi.provenance")
    c.execute("CREATE TABLE coi.provenance.release (release VARCHAR)")
    c.execute("CREATE TABLE coi.measure.observation (source VARCHAR, source_release VARCHAR, measure_id VARCHAR, "
              "geo_id VARCHAR, value DOUBLE, valid_from VARCHAR, valid_to VARCHAR)")
    c.execute("INSERT INTO coi.measure.observation VALUES "
              "('B', '1', 'B:m', 'county:08001', 1, NULL, NULL), ('A', '1', 'A:m', 'tract:08001000100', 2, NULL, NULL), "
              "('A', '1', 'A:m', 'county:12001', 3, NULL, NULL), ('A', '1', 'A:m', 'county:08003', 4, NULL, NULL), "
              "('A', '1', 'A:m', 'nation:US', 5, NULL, NULL), ('A', '1', 'A:m', 'state:08', 6, NULL, NULL), "
              "('A', '1', 'A:m', 'county:08001', 7, NULL, NULL), ('A', '1', 'A:old', 'county:08001', 8, NULL, 'closed')")
    out = tmp_path / "release"
    publish.publish(c, out, out.as_uri(), ["measure.observation"])

    rows = duckdb.sql(f"SELECT source, geo_id, value FROM '{out / 'measure/observation.parquet'}'").fetchall()
    assert rows == [("A", "county:08001", 7), ("A", "county:08003", 4), ("B", "county:08001", 1),
                    ("A", "county:12001", 3), ("A", "nation:US", 5), ("A", "state:08", 6),
                    ("A", "tract:08001000100", 2)]
