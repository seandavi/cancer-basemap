"""Offline tests for issue #120's sort-on-write layout: the ORDER BY every
overwrite applies, the row-group-limit property, the Iceberg sort order
recorded in table metadata, and the `rewrite` CLI verb's exactness check.
"""

import dataclasses
import unittest.mock

import pyarrow as pa
import pytest
from pyiceberg.expressions import AlwaysTrue
from pyiceberg.table import TableProperties

from cancerbasemap import merge, schemas

REL1 = "2026.08"


def rows(cat, identifier, **kw):
    return cat.load_table(identifier).scan(**kw).to_arrow().to_pylist()


def county(geo_id, fips, vintage=2020, level="county", name="x"):
    return dict(geo_id=geo_id, level=level, fips=fips, vintage=vintage, name=name,
                parent_geo_id=None, aland_m2=None, awater_m2=None,
                centroid_lat=None, centroid_lon=None, geometry_uri=None)


def test_sort_for_write_orders_by_declared_columns():
    # geography.unit declares sort_by=(vintage, level, geo_id).
    arrow = pa.Table.from_pylist([
        {"level": "county", "vintage": 2020, "geo_id": "county:08059"},
        {"level": "county", "vintage": 2020, "geo_id": "county:08013"},
        {"level": "county", "vintage": 2010, "geo_id": "county:08031"},
    ])
    out = merge.sort_for_write("geography.unit", arrow, arrow.schema).to_pylist()
    assert [r["geo_id"] for r in out] == ["county:08031", "county:08013", "county:08059"]


def test_sort_for_write_is_a_noop_without_sort_by():
    arrow = pa.Table.from_pylist([{"a": 2}, {"a": 1}])
    no_key = dataclasses.replace(schemas.TABLES["geography.unit"], sort_by=())
    with unittest.mock.patch.dict(schemas.TABLES, {"geography.unit": no_key}):
        out = merge.sort_for_write("geography.unit", arrow, arrow.schema)
    assert out.to_pylist() == [{"a": 2}, {"a": 1}]  # untouched, including order


def test_sort_for_write_nulls_last():
    arrow = pa.Table.from_pylist([
        {"level": "county", "vintage": None, "geo_id": "county:08013"},
        {"level": "county", "vintage": 2020, "geo_id": "county:08031"},
    ])
    out = merge.sort_for_write("geography.unit", arrow, arrow.schema).to_pylist()
    assert [r["vintage"] for r in out] == [2020, None]


def test_merge_write_lands_rows_sorted(cat):
    v1 = pa.Table.from_pylist([
        county("county:08059", "08059"),
        county("county:08013", "08013"),
        county("county:08031", "08031"),
    ])
    merge.merge(cat, "geography.unit", v1, REL1, AlwaysTrue())
    ordered = [r["geo_id"] for r in rows(cat, "geography.unit")]
    assert ordered == sorted(ordered)  # (vintage, level, geo_id) all equal but geo_id here


def test_create_sets_row_group_limit_property(cat):
    table = schemas.create(cat, "geography.unit")
    assert table.properties[TableProperties.PARQUET_ROW_GROUP_LIMIT] == str(schemas.ROW_GROUP_ROWS)


def test_evolve_sets_row_group_limit_on_a_live_table_missing_it(cat):
    """Simulates a table created before #120: no row-group property set."""
    d = schemas.TABLES["geography.unit"]
    ns = "geography"
    cat.create_namespace_if_not_exists(ns)
    cat.create_table_if_not_exists("geography.unit", schema=d.iceberg_schema(),
                                   properties={"comment": d.comment})
    table = cat.load_table("geography.unit")
    assert TableProperties.PARQUET_ROW_GROUP_LIMIT not in table.properties

    schemas.create(cat, "geography.unit")  # runs _evolve
    table = cat.load_table("geography.unit")
    assert table.properties[TableProperties.PARQUET_ROW_GROUP_LIMIT] == str(schemas.ROW_GROUP_ROWS)


def test_create_sets_iceberg_sort_order(cat):
    table = schemas.create(cat, "geography.unit")
    cols = [table.schema().find_field(f.source_id).name for f in table.sort_order().fields]
    assert cols == list(schemas.TABLES["geography.unit"].sort_by)


def test_evolve_reconciles_sort_order_on_a_live_table_missing_it(cat):
    d = schemas.TABLES["geography.unit"]
    cat.create_namespace_if_not_exists("geography")
    cat.create_table_if_not_exists("geography.unit", schema=d.iceberg_schema(),
                                   properties={"comment": d.comment})
    table = cat.load_table("geography.unit")
    assert table.sort_order().is_unsorted

    schemas.create(cat, "geography.unit")
    table = cat.load_table("geography.unit")
    assert not table.sort_order().is_unsorted


def test_rewrite_preserves_rows_exactly(cat):
    v1 = pa.Table.from_pylist([
        county("county:08059", "08059"),
        county("county:08013", "08013"),
        county("county:08031", "08031"),
    ])
    merge.merge(cat, "geography.unit", v1, REL1, AlwaysTrue())
    before = {tuple(sorted(r.items())) for r in rows(cat, "geography.unit")}

    merge.rewrite(cat, "geography.unit")

    after = {tuple(sorted(r.items())) for r in rows(cat, "geography.unit")}
    assert before == after


def test_rewrite_refuses_to_commit_on_checksum_mismatch(cat, monkeypatch):
    v1 = pa.Table.from_pylist([county("county:08013", "08013")])
    merge.merge(cat, "geography.unit", v1, REL1, AlwaysTrue())

    real_checksum = merge._checksum
    calls = []

    def fake_checksum(arrow):
        calls.append(1)
        # Corrupt only the second call (the post-sort check), simulating a bug
        # that silently drops or changes a row during sort_for_write.
        if len(calls) == 2:
            return (999, 0)
        return real_checksum(arrow)

    monkeypatch.setattr(merge, "_checksum", fake_checksum)
    with pytest.raises(RuntimeError, match="refusing to commit"):
        merge.rewrite(cat, "geography.unit")


def test_rewrite_bounds_a_partitioned_table_to_one_partition_at_a_time(cat):
    """measure.observation's only partition column is `source` -- rewriting it
    scope-by-scope is what keeps memory bounded on the real table (#120)."""
    common = dict(geo_vintage=2020, period_start="2020", period_end="2020",
                 stratum_id="ALL", value=1.0, lower=None, upper=None,
                 interval_level=None, numerator=None, denominator=None,
                 value_status="reported", reliability_flag=None, trend=None,
                 valid_from=REL1, valid_to=None)
    arrow = pa.Table.from_pylist([
        dict(source="A", source_release="2024", measure_id="A:1", geo_id="county:08013", **common),
        dict(source="B", source_release="2024", measure_id="B:1", geo_id="county:08031", **common),
    ])
    merge.write(cat, "measure.observation", arrow, AlwaysTrue())

    table = schemas.create(cat, "measure.observation")
    d = schemas.TABLES["measure.observation"]
    scopes = merge._partition_scopes(table, d)
    assert len(scopes) == 2  # one per distinct `source`

    merge.rewrite(cat, "measure.observation")
    sources = {r["source"] for r in rows(cat, "measure.observation")}
    assert sources == {"A", "B"}
