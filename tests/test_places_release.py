"""PLACES through the dataset release path, offline (cdsci-lake ADR-0025).

Reuses `test_places.py`'s handcrafted 2024/2025 fixtures. Both editions are
ingested into a tmp local Iceberg catalog via `places.ingest`, then
`release.release_places` publishes the product's current rows into a local
directory. Nothing here touches the network, a live catalog, or a lake.
"""

from datetime import date

import duckdb
import pytest
from cdsci.lake.publish.builder import LocalDirStore
from cdsci.lake.publish.verify import verify_release
from pyiceberg.expressions import And, EqualTo
from test_places import (  # noqa: F401 -- fixtures
    DATA_2025,
    REL1,
    REL2,
    cat,
    csv2024,
    csv2025,
    rows,
)

from cancerbasemap import contracts, places, release, schemas

TABLES = ("measure.observation", "measure.definition")
TODAY = date(2026, 10, 2)


@pytest.fixture
def lake(cat, csv2024, csv2025):  # noqa: F811 -- imported fixtures
    places.ingest(cat, REL1, places_release="2024", url=csv2024)
    places.ingest(cat, REL2, places_release="2025", url=csv2025)
    return cat


def _live(cat, identifier):
    return [r for r in rows(cat, identifier, row_filter=EqualTo("source", "PLACES"))
            if r.get("valid_to") is None]


def _built(out, identifier):
    parquet = out / "canceronice-places" / "2026-10-02" / "tables" / identifier / "data"
    return duckdb.sql(f"SELECT * FROM read_parquet('{parquet}/*.parquet')"
                      ).to_arrow_table().to_pylist()


# --- 1. contracts derive from schemas.py, not copied ---

def test_contract_columns_equal_tabledef_columns():
    for identifier, contract in contracts.PLACES.tables.items():
        d = schemas.TABLES[identifier]
        expected = [(f.name, f.doc, not f.required) for f in d.schema.fields
                    if f.name not in ("valid_from", "valid_to")]
        assert [(c.name, c.description, c.nullable) for c in contract.columns] == expected
        assert contract.primary_key == d.business_key
        assert contract.sort_by == d.sort_by
        assert contract.temporal_model.value == "upsert_latest_snapshot"
        assert all(c.description for c in contract.columns)

    obs = {c.name: c for c in contracts.OBSERVATION.columns}
    assert obs["measure_id"].identifier_namespace == "measure.definition"
    assert obs["geo_id"].identifier_namespace == "geography.unit"
    assert obs["stratum_id"].identifier_namespace == "measure.stratum"
    assert obs["value_status"].enum == schemas.VALUE_STATUSES
    assert obs["value"].null_meaning and "reported" in obs["value"].null_meaning
    assert obs["geo_vintage"].arrow_type == "int32" and obs["value"].arrow_type == "double"
    assert "source_release is in the key" in contracts.OBSERVATION.grain
    assert "valid_from" not in obs and "valid_to" not in obs
    assert all(c.coordinate_system is None for c in contracts.OBSERVATION.columns)
    assert contracts.PLACES.required_artifacts == {"parquet", "ducklake"}


# --- 2. cancer gates over the built observation rows ---

def test_built_rows_pass_cancer_gates(lake, tmp_path):
    release.release_places(lake, tmp_path / "pub", today=TODAY)
    obs = _built(tmp_path / "pub", "measure.observation")
    assert len(obs) == 10

    numeric = ("value", "lower", "upper", "numerator", "denominator")
    assert all(o["value_status"] in schemas.VALUE_STATUSES for o in obs)
    assert all(o[c] is None for o in obs if o["value_status"] != "reported" for c in numeric)
    assert all(o["value"] is not None for o in obs if o["value_status"] == "reported")
    lpa = next(o for o in obs if o["measure_id"] == "PLACES:LPA:age_adjusted")
    assert lpa["value_status"] == "suppressed_small_count"
    assert sum(o["value_status"] != "reported" for o in obs) == 1

    # source_release and the estimate period are distinct, populated columns
    for o in obs:
        assert None not in (o["source_release"], o["period_start"], o["period_end"])
        assert o["source_release"] != o["period_start"]
    denver = next(o for o in obs if o["geo_id"] == "county:08031" and o["source_release"] == "2025")
    assert (denver["period_start"], denver["source_release"]) == ("2023", "2025")

    # geography carries a level and a vintage
    assert all(o["geo_id"].split(":")[0] in ("nation", "county", "tract") for o in obs)
    assert {o["geo_vintage"] for o in obs} == {2020}

    # licence gate: every source in the release is cleared
    assert {o["source"] for o in obs} == {"PLACES"}
    assert all(t.license == "public-domain" for t in contracts.PLACES.tables.values())


# --- 3. publish, verify, parity with the product ---

def test_release_publishes_verifies_and_matches_product_rows(lake, tmp_path):
    out = tmp_path / "pub"
    manifest = release.release_places(lake, out, today=TODAY)
    assert manifest.release == "2026-10-02" and manifest.status.value == "published"

    counts = {t.name: t.row_count for t in manifest.tables}
    product_obs, product_defs = _live(lake, TABLES[0]), _live(lake, TABLES[1])
    assert counts["measure.observation"] == len(product_obs) == 10
    assert counts["measure.definition"] == len(product_defs) == 6

    key = (*schemas.TABLES["measure.observation"].business_key, "value", "value_status")
    assert {tuple(r[f] for f in key) for r in _built(out, TABLES[0])} == {
        tuple(r[f] for f in key) for r in product_obs}
    assert {(d["measure_id"], d["label"]) for d in _built(out, TABLES[1])} == {
        (d["measure_id"], d["label"]) for d in product_defs}

    assert verify_release(LocalDirStore(out), "canceronice-places", "2026-10-02",
                          contract=contracts.PLACES).passed  # cold reload
    assert {v.ref for v in manifest.source_asset_versions} == {
        "canceronice.measure.observation", "canceronice.measure.definition"}


# --- 4. FK gate ---

def test_dangling_measure_id_raises_and_publishes_nothing(lake, tmp_path):
    t = lake.load_table("measure.definition")
    t.delete(And(EqualTo("source", "PLACES"), EqualTo("measure_id", "PLACES:LPA:age_adjusted")))
    out = tmp_path / "pub"
    with pytest.raises(ValueError, match="dangling measure_id"):
        release.release_places(lake, out, today=TODAY)
    assert not (out / "canceronice-places" / "releases.json").exists()
