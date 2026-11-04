"""Publish gate (ADR-0001 § The gate, #172): a release bundle against the previous release.

The mechanics are `cdsci.publish.gate`, shared with biocOnIce (cdsci-lake ADR-0027): manifest
row counts and columns against the Parquet, and against the reference's manifest.json no table
missing, columns and types unchanged, row counts within bounds, README queries as optional
checks, and gate.json on a pass, bound to manifest.json by sha256. This module is the cancer
policy: the bounds (shrinking below 0.8x fails; growing past 3x only warns, since whole new
vintages are legitimate growth), the README fence, our User-Agent, and the hard gate, `value`
NULL in measure.observation whenever `value_status != 'reported'`. Sources own suppression, so
lower / upper / numerator / denominator are not checked.
"""

from pathlib import Path

import cdsci.publish.gate
from cdsci.publish.gate import GATE_FILE, Check  # noqa: F401 (GATE_FILE re-exported for upload / hf)

from .publish import DEFAULT_BASE_URL

README = Path(__file__).parents[2] / "README.md"
DEFAULT_REFERENCE = DEFAULT_BASE_URL
# Against the reference, a table's row count may shrink to this fraction or grow to this multiple.
MIN_ROW_RATIO, MAX_ROW_RATIO = 0.8, 3.0
# Cloudflare answers urllib's default User-Agent with 403 (error 1010) on cancerdatasci.org,
# so name ourselves (the 2026-11-03 release failed here).
USER_AGENT = "cancerbasemap-gate (+https://github.com/seandavi/cancer-basemap)"


def readme_queries(path=None):
    """(line, sql) for each ```sql bundle block in the README: the queries the README marks as
    running against the bundle's tables (named schema.table, as in views.sql)."""
    return cdsci.publish.gate.readme_queries(README if path is None else path, fence="sql bundle")


def value_gate(con, manifest, ref):
    """The hard gate: no suppressed cell ever reads as a number (AGENTS.md)."""
    name = "measure.observation.value_null_unless_reported"
    if not any(t["schema"] == "measure" and t["table"] == "observation" for t in manifest["tables"]):
        return [Check(name, False, detail="measure.observation is not in the bundle")]
    bad = con.execute("SELECT count(*) FROM measure.observation "
                      "WHERE value_status IS NULL "
                      "OR (value_status != 'reported' AND value IS NOT NULL)").fetchone()[0]
    return [Check(name, bad == 0, detail=f"{bad} rows" if bad else "")]


def gate(bundle: Path, reference: str | None = DEFAULT_REFERENCE) -> bool:
    """Print the gate report for `bundle` against `reference` (a release base URL; None for the
    bundle checks only); True when every required check passes, and then write gate.json."""
    queries = readme_queries()
    if not queries:  # an installed wheel has no README
        print("README not found or marks no ```sql bundle queries: skipping the README query checks")
    passed, _ = cdsci.publish.gate.gate(
        bundle, reference, queries=queries, row_bounds=(MIN_ROW_RATIO, MAX_ROW_RATIO),
        growth_required=False, extra_checks=value_gate, user_agent=USER_AGENT)
    return passed
