"""`cancerbasemap publish`: a release bundle from the local sqlite warehouse, offline."""

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


def test_raw_and_provenance_ship_whole_and_manifest_counts_match(con, tmp_path):
    out = tmp_path / "release"
    m = publish.publish(con, out, out.as_uri(), ONLY)

    assert json.loads((out / "manifest.json").read_text()) == json.loads(json.dumps(m, default=str))
    assert len(m["release"]) == 10
    want = {"geography.alias": 2,
            "raw.geography__county_recodes": con.sql("SELECT count(*) FROM coi.raw.geography__county_recodes").fetchone()[0],
            "provenance.release": con.sql("SELECT count(*) FROM coi.provenance.release").fetchone()[0]}
    assert {f"{t['schema']}.{t['table']}": t["row_count"] for t in m["tables"]} == want
    for t in m["tables"]:
        assert t["bytes"] == (out / t["path"]).stat().st_size and len(t["sha256"]) == 64
    # per-source provenance from provenance.release
    assert {p["source"] for p in m["provenance"]} == {"geography_alias"}
    assert "git_sha" in m and "base_url" in m

    # the views in cancerbasemap.duckdb resolve against the written Parquet
    db = duckdb.connect()
    db.execute(f"ATTACH '{out / publish.DB_FILE}' AS rel (READ_ONLY)")
    assert {n: db.sql(f"SELECT count(*) FROM rel.{n}").fetchone()[0] for n in want} == want
    docs = dict(db.sql("SELECT column_name, comment FROM duckdb_columns() WHERE database_name = 'rel' "
                       "AND schema_name = 'geography' AND table_name = 'alias'").fetchall())
    assert docs["change_type"].startswith("One of: recode")

    # restore.sql builds a local copy and checks it against manifest.json
    local = duckdb.connect()
    local.execute((out / "restore.sql").read_text())
    assert local.sql("SELECT count(*) FROM geography.alias").fetchone()[0] == 2


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
        "measure.cancer_site_group", "facility.site"}


def test_a_non_empty_output_directory_is_refused(con, tmp_path):
    out = tmp_path / "release"
    publish.publish(con, out, out.as_uri(), ONLY)
    with pytest.raises(ValueError, match="not empty"):
        publish.publish(con, out, out.as_uri(), ["geography.alias"])
    assert len(json.loads((out / "manifest.json").read_text())["tables"]) == len(ONLY)


def test_views_keep_the_https_url_before_it_is_uploaded(con, tmp_path):
    out = tmp_path / "release"
    publish.publish(con, out, "https://basemap.example.org/data/latest/", ["geography.alias"])
    url = "https://basemap.example.org/data/latest/geography/alias.parquet"
    assert f"read_parquet('{url}')" in (out / "views.sql").read_text()
    db = duckdb.connect(str(out / publish.DB_FILE), read_only=True)
    assert url in db.sql("SELECT sql FROM duckdb_views() WHERE view_name = 'alias'").fetchone()[0]


def test_unknown_table_is_refused(con, tmp_path):
    with pytest.raises(ValueError, match="not a published table"):
        publish.publish(con, tmp_path, tmp_path.as_uri(), ["geography.nope"])
