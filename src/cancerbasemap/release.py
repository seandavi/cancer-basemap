"""Publish the `canceronice-places` dataset release (cdsci-lake ADR-0025).

Reads the product's own Iceberg current rows (the catalog is not in the lake),
drops the row-history columns, and hands full snapshots of `measure.observation`
and `measure.definition` to `cdsci.lake.publish.pipeline.publish_release`.
Output is local only: a temporary directory removed when the run ends, or the
explicit `out` tree.
"""

import tempfile
import uuid
from datetime import date
from pathlib import Path

import duckdb
from cdsci.lake.publish.builder import LocalDirStore
from cdsci.lake.publish.pipeline import publish_release
from cdsci.lake.publish.release import ReleaseManifest, SourceAssetVersion, release_date
from pyiceberg.expressions import And, EqualTo, IsNull

from . import contracts

SOURCE = "PLACES"


def _scan(cat, identifier, row_filter):
    t = cat.load_table(identifier)
    arrow = t.scan(row_filter=row_filter).to_arrow()
    schema = contracts.PLACES.tables[identifier].arrow_schema()
    return t, arrow.select(schema.names).cast(schema)


def release_places(cat, out: Path | None = None, *, today: date | None = None) -> ReleaseManifest:
    obs_t, obs = _scan(cat, "measure.observation",
                       And(EqualTo("source", SOURCE), IsNull("valid_to")))
    def_t = cat.load_table("measure.definition")
    def_filter = EqualTo("source", SOURCE)
    if "valid_to" in {f.name for f in def_t.schema().fields}:
        def_filter = And(def_filter, IsNull("valid_to"))
    def_t, defs = _scan(cat, "measure.definition", def_filter)

    missing = set(obs["measure_id"].to_pylist()) - set(defs["measure_id"].to_pylist())
    if missing:
        raise ValueError(f"dangling measure_id(s): {sorted(missing)}")

    con = duckdb.connect()
    tables = {"measure.observation": con.from_arrow(obs),
              "measure.definition": con.from_arrow(defs)}
    versions = tuple(
        SourceAssetVersion(ref=f"canceronice.{ident}",
                           version=f"snapshot:{t.current_snapshot().snapshot_id}")
        for ident, t in (("measure.observation", obs_t), ("measure.definition", def_t)))

    def run(root):
        return publish_release(
            LocalDirStore(root), contract=contracts.PLACES, tables=tables,
            source_asset_versions=versions, run_id=str(uuid.uuid4()), today=today, con=None)

    if out is None:
        with tempfile.TemporaryDirectory(prefix="canceronice-places-") as tmp:
            manifest = run(Path(tmp))
        where = "temporary, removed"
    else:
        manifest = run(out)
        where = str(out)
    for t in manifest.tables:
        print(f"{manifest.dataset} {manifest.release} ({release_date(manifest.release)}): "
              f"{t.name} {t.row_count:,} rows; output {where}")
    return manifest
