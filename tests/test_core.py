"""Offline tests for the core machinery: schema declarations, merge, and the
suppression invariant (SPEC.md Acceptance C). Uses the local sqlite warehouse
only, via the shared `cat` fixture in conftest.py.
"""

import dataclasses

import pyarrow as pa
import pytest
from pyiceberg.expressions import AlwaysTrue
from pyiceberg.schema import Schema
from pyiceberg.types import NestedField

from cancerbasemap import merge, schemas

REL1, REL2 = "2026.08", "2026.09"


def rows(cat, identifier, **kw):
    return cat.load_table(identifier).scan(**kw).to_arrow().to_pylist()


def test_tables_create_from_declarations(cat):
    for identifier in schemas.TABLES:
        table = schemas.create(cat, identifier)
        assert table.properties.get("comment"), identifier
        for f in table.schema().fields:
            assert f.doc, f"{identifier}.{f.name} has no doc"


def county(geo_id, fips, name, parent="state:08"):
    return dict(geo_id=geo_id, level="county", fips=fips, vintage=2020, name=name,
                parent_geo_id=parent, aland_m2=None, awater_m2=None,
                centroid_lat=None, centroid_lon=None, geometry_uri=None)


def test_geography_unit_merge_round_trip(cat):
    """Type-2 merge on geography.unit: added, retired and unchanged rows."""
    v1 = pa.Table.from_pylist([
        county("county:08031", "08031", "Denver County"),
        county("county:08013", "08013", "Boulder County"),
    ])
    merge.merge(cat, "geography.unit", v1, REL1, AlwaysTrue())

    v2 = pa.Table.from_pylist([
        county("county:08031", "08031", "Denver County"),   # unchanged
        county("county:08059", "08059", "Jefferson County"),  # new
        # 08013 dropped -> retired
    ])
    counts = merge.merge(cat, "geography.unit", v2, REL2, AlwaysTrue())

    versions = {(r["geo_id"], r["valid_from"], r["valid_to"]) for r in rows(cat, "geography.unit")}
    assert ("county:08031", REL1, None) in versions       # unchanged row, untouched
    assert ("county:08013", REL1, REL2) in versions        # retired at REL2
    assert ("county:08059", REL2, None) in versions        # added at REL2
    assert counts["written"] == 2  # new + retired
    assert counts["unchanged"] == 1


def test_merge_raises_rather_than_drop_a_sibling_calls_rows(cat):
    """#118: merge.merge recomputes the *complete* state of `scope`, so two
    calls sharing one scope in the same release (e.g. county then tract rows
    under one source_release) silently lose the first call's rows -- they're
    too new (valid_from == this release) to be 'retired', but absent from the
    second call's `incoming` so also not 'new'/'changed'/'unchanged'. They
    match none of the five outcomes, and the scope-filtered overwrite then
    erases them. The guard must raise instead of losing them."""
    v1 = pa.Table.from_pylist([county("county:08031", "08031", "Denver County")])
    merge.merge(cat, "geography.unit", v1, REL1, AlwaysTrue())

    v2 = pa.Table.from_pylist([county("county:08059", "08059", "Jefferson County")])
    with pytest.raises(ValueError, match="08031"):
        merge.merge(cat, "geography.unit", v2, REL1, AlwaysTrue())

    # the first call's row must still be there, untouched
    versions = {(r["geo_id"], r["valid_from"], r["valid_to"]) for r in rows(cat, "geography.unit")}
    assert ("county:08031", REL1, None) in versions


def test_merge_allow_draft_drop_opts_out_of_the_118_guard(cat):
    """The #118 guard can't tell a sibling slice from a deliberate same-release
    correction -- both are a live row opened this release and absent from
    `incoming`. allow_draft_drop=True keeps the documented draft-drop
    behaviour for the latter: a mistaken row is dropped as if it never
    existed in any release, rather than raising."""
    v1 = pa.Table.from_pylist([
        county("county:08031", "08031", "Denver County"),
        county("county:08999", "08999", "Parser Bug County"),  # bad row, this release
    ])
    merge.merge(cat, "geography.unit", v1, REL1, AlwaysTrue())

    corrected = pa.Table.from_pylist([county("county:08031", "08031", "Denver County")])
    merge.merge(cat, "geography.unit", corrected, REL1, AlwaysTrue(), allow_draft_drop=True)

    versions = rows(cat, "geography.unit")
    assert {(r["geo_id"], r["valid_from"], r["valid_to"]) for r in versions} == {
        ("county:08031", REL1, None),
    }


def observation(value_status, value):
    return dict(value_status=value_status, value=value)


def test_check_observations_rejects_suppressed_value_and_unknown_status():
    arrow = pa.Table.from_pylist([
        observation("reported", 1.0),
        observation("suppressed_small_count", 5.0),     # a suppressed row carrying a value
        observation("not_a_real_status", None),          # not in the closed enum
    ])
    with pytest.raises(ValueError, match="2 row"):
        merge.check_observations(arrow)


def test_check_observations_rejects_null_value_under_reported_status():
    """The reverse direction: value_status='reported' promises a value, per
    schemas.py's doc on the column. A source that derives value_status from
    something other than its own value expression's nullness (e.g. a raw
    cell's presence, checked separately from a TRY_CAST that can fail) can
    produce this -- caught here rather than per source (#132/#135/#136/#141
    all hit some form of this)."""
    arrow = pa.Table.from_pylist([
        observation("reported", 1.0),
        observation("reported", None),          # promises a value, has none
    ])
    with pytest.raises(ValueError, match="1 row"):
        merge.check_observations(arrow)


def test_check_observations_accepts_valid_rows():
    arrow = pa.Table.from_pylist([
        observation("reported", 1.0),
        observation("suppressed_reliability", None),
        observation("not_applicable", None),
    ])
    merge.check_observations(arrow)  # does not raise


def test_manifest_writes_a_provenance_release_row(cat):
    merge.manifest(cat, REL2, "test_source", "http://example.org/data", 42,
                   version="v1", method="release_number")
    row = next(r for r in rows(cat, "provenance.release") if r["source"] == "test_source")
    assert row["release"] == REL2
    assert row["row_count"] == 42
    assert row["source_version"] == "v1"
    assert row["version_method"] == "release_number"


def test_manifest_keeps_one_row_per_source_version(cat):
    """#78: several source releases can land under one catalog release; the
    manifest keyed on (release, source, source_version) keeps a row for each,
    rather than the last one landed overwriting the rest."""
    for version in ("2024", "2025", "2026"):
        merge.manifest(cat, REL1, "places", "http://example.org/places", 10,
                       version=version, method="release_number")
    landed = {r["source_version"]: r for r in rows(cat, "provenance.release")
             if r["source"] == "places"}
    assert set(landed) == {"2024", "2025", "2026"}
    assert all(r["release"] == REL1 for r in landed.values())


def test_manifest_same_version_twice_overwrites_its_own_row(cat):
    merge.manifest(cat, REL1, "places", "http://example.org/places", 10,
                   version="2024", method="release_number")
    merge.manifest(cat, REL1, "places", "http://example.org/places", 20,
                   version="2024", method="release_number")
    landed = [r for r in rows(cat, "provenance.release")
             if r["source"] == "places" and r["source_version"] == "2024"]
    assert len(landed) == 1
    assert landed[0]["row_count"] == 20


def test_evolve_refuses_to_promote_business_key_field_to_required(cat, monkeypatch):
    """#78 changed provenance.release's business key to include
    source_version, which Iceberg requires to be `required` as an identifier
    field. Simulates the real live table: created under the OLD declaration
    (business_key=(release, source), source_version optional) as the first
    live ingest actually did, then asked to evolve under the current one.
    _evolve should refuse rather than silently force the promotion."""
    live_def = schemas.TABLES["provenance.release"]
    old_fields = tuple(
        NestedField(f.field_id, f.name, f.field_type, required=False, doc=f.doc)
        if f.name == "source_version" else f
        for f in live_def.schema.fields
    )
    old_def = dataclasses.replace(live_def, schema=Schema(*old_fields),
                                  business_key=("release", "source"))

    monkeypatch.setitem(schemas.TABLES, "provenance.release", old_def)
    schemas.create(cat, "provenance.release")  # the pre-#78 live table

    monkeypatch.setitem(schemas.TABLES, "provenance.release", live_def)
    with pytest.raises(ValueError, match="source_version.*optional"):
        schemas.create(cat, "provenance.release")
