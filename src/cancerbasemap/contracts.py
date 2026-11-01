"""Release contracts (cdsci-lake `TableContract`) for the PLACES dataset release.

`schemas.py` stays the single source of table structure: every column here is
DERIVED from its `TableDef` (name, type, doc, required-ness), never copied by
hand, and `tests/test_places_release.py` asserts the two stay equal (minus the
catalog's `valid_from`/`valid_to`, which a release does not carry). This module
only adds what the Iceberg schema cannot say and cdsci-lake's contract can: the
temporal model by name, FK namespaces, closed enums, and what a NULL means
(SPEC.md § Suppression is a value, not a NULL).

Lives beside `schemas.py` so the ingest path never imports cdsci-lake; nothing
in it imports this module.

**Temporal model.** Each table is a current-state snapshot
(`upsert_latest_snapshot`): a dataset release is an immutable full snapshot, and
the release id is the only catalog validity. Of the three time axes in SPEC.md §
Versioning model, two remain data columns -- `period_start`/`period_end` (what
the estimate describes) and `source_release` (the upstream edition that
published it) -- and the third, when Cancer Basemap served the row, is the release
itself. Row-level `valid_from`/`valid_to` are not part of a release.

Domain values (namespaces, enums, suppression meaning, licence) are this
repository's; cdsci-lake supplies the dataclasses and the mechanics only.
"""

from cdsci.lake.contracts import (
    ColumnContract,
    DatasetContract,
    TableContract,
    TemporalModel,
)
from pyiceberg.types import (
    BooleanType,
    DoubleType,
    IntegerType,
    LongType,
    StringType,
)

from . import schemas

# Row-history columns of the live Iceberg tables; not part of a release.
VALIDITY_COLUMNS = ("valid_from", "valid_to")

# Iceberg primitive -> cdsci-lake's canonical Arrow type string.
_ARROW = {StringType: "string", IntegerType: "int32", LongType: "int64",
          DoubleType: "double", BooleanType: "bool"}

# What NULL means, per column, where a NULL is a statement and not an absence.
# The suppression invariant lives on `value`: a NULL there is never "unknown".
_OBSERVATION = {
    "measure_id": dict(identifier_namespace="measure.definition"),
    "geo_id": dict(identifier_namespace="geography.unit"),
    "stratum_id": dict(identifier_namespace="measure.stratum"),
    "value": dict(null_meaning="value_status != 'reported': the source suppressed or did not "
                               "publish this cell (SPEC.md Acceptance C). Never a number."),
    "lower": dict(null_meaning="No interval published, or the cell is not 'reported'."),
    "upper": dict(null_meaning="No interval published, or the cell is not 'reported'."),
    "interval_level": dict(null_meaning="No interval published."),
    "numerator": dict(null_meaning="Not published by the source."),
    "denominator": dict(null_meaning="Not published by the source."),
    "value_status": dict(enum=schemas.VALUE_STATUSES),
    "reliability_flag": dict(null_meaning="No reliability flag published."),
    "trend": dict(null_meaning="No trend call published."),
}

_DEFINITION = {
    "measure_id": dict(identifier_namespace="measure.definition"),
    "rate_basis": dict(enum=("per_100000", "per_1000000", "percent", "count", "index", "sum")),
    "age_adjustment": dict(null_meaning="Not age-adjusted."),
    "method": dict(enum=("direct", "model_based", "survey_direct", "derived")),
    "cancer_site_code": dict(identifier_namespace="measure.cancer_site",
                             null_meaning="Not cancer-site-specific."),
}

# PLACES is public domain (places.py module docstring: Socrata metadata
# `"license": {"name": "Public Domain"}`, checked 2026-09-18). A source with
# no cleared licence never gets a contract (AGENTS.md: license:unknown is a
# hard stop).
PLACES_LICENSE = "public-domain"


def _columns(fields, overrides):
    unknown = set(overrides) - {f.name for f in fields}
    if unknown:
        raise ValueError(f"overrides for columns not in the TableDef: {sorted(unknown)}")
    return tuple(
        ColumnContract(f.name, _ARROW[type(f.field_type)], f.doc, nullable=not f.required,
                       **overrides.get(f.name, {}))
        for f in fields
    )


def _table(identifier, overrides, grain, description):
    d = schemas.TABLES[identifier]
    fields = tuple(f for f in d.schema.fields if f.name not in VALIDITY_COLUMNS)
    return TableContract(
        name=identifier,
        description=description,
        grain=grain,
        primary_key=d.business_key,
        temporal_model=TemporalModel.UPSERT_LATEST_SNAPSHOT,
        owner="cancer-basemap",
        license=PLACES_LICENSE,
        columns=_columns(fields, overrides),
        sort_by=d.sort_by,
        # ponytail: TableDef.partition_by ('source') is dropped -- cdsci-lake's
        # release builder refuses partition_by (single file per table, cdsci-lake#100);
        # partitioning is a pruning hint there, not a correctness mechanism.
    )


OBSERVATION = _table(
    "measure.observation", _OBSERVATION,
    grain="one row per (source, source_release, measure_id, geo_id, geo_vintage, period_start, "
          "period_end, stratum_id); source_release is in the key, so a later PLACES edition's "
          "revised estimate is a distinct row, never a change to an earlier edition's row",
    description="Every PLACES-published number, one stacked long table (SPEC.md § Measures). "
                "Two data time axes: period_start/period_end (what the estimate describes) "
                "and source_release (the PLACES edition that published it); the dataset "
                "release id is the third.",
)

DEFINITION = _table(
    "measure.definition", _DEFINITION,
    grain="one row per measure_id",
    description="One row per PLACES measure definition (SPEC.md § Measures), the lookup "
                "every observation.measure_id resolves into.",
)

PLACES = DatasetContract(
    id="canceronice-places",
    title="Cancer Basemap: CDC PLACES slice",
    description="CDC PLACES county/tract model-based estimates as measure.observation, every "
                "landed PLACES edition included, plus their measure.definition rows.",
    publisher="cancer-basemap",
    tables={"measure.observation": OBSERVATION, "measure.definition": DEFINITION},
)
