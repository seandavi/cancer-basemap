# AGENTS.md

Conventions for AI agents (and humans) working on Cancer Basemap.

## What this project is

Ingest pipelines that turn public population cancer data into Iceberg tables
keyed on geography and time, plus the thin client helper for reading them.
**SPEC.md is the design source of truth** — read it before writing code. If a
change contradicts the SPEC, edit SPEC.md in the same commit and say so in your
report.

Cancer Basemap is the sibling of [biocOnIce](https://github.com/seandavi/bioc-on-ice)
and adopts its ADRs by reference (SPEC.md § Architecture). Decisions specific
to this repo are recorded in `docs/adr/`. Contradicting an ADR — here or
inherited — is allowed and sometimes right, but it should be argued rather
than drifted into.

Cancer Basemap is the *data*; [icegate](https://github.com/seandavi/icegate) is
the gateway that serves it. Nothing here should grow gateway concerns (auth,
routing, credential vending) — that boundary is deliberate.

## Hard gates

- **Public aggregates only.** Nothing record-level, DUA-gated or restricted
  ever lands, in any namespace, even temporarily (SPEC.md § Licence gate). The
  Cloudflare account is the trust domain (biocOnIce ADR-0005).
- **Licence before ingest.** A data-source issue carries `license:cleared`
  before any of its code merges. `license:unknown` is a hard stop.
- **No suppressed cell ever reads as a number.** `value` is NULL whenever
  `value_status != 'reported'`, and every source's suppression sentinels are
  covered by a fixture test.

## Coding rules

- Lazy and minimal: smallest working diff, no speculative abstractions, no
  scaffolding "for later". Deletion beats addition.
- **New sources are SQL, not frameworks.** Each source is one module that
  parses with DuckDB and hands Arrow tables to `merge.write` / `merge.merge`.
  If a second source needs something from the first, move that one thing —
  don't build an ingestion framework for two pipelines.
- No new dependencies without a recorded reason. DuckDB does the parsing;
  PyIceberg does the writing; argparse does the CLI.
- Non-trivial logic lands with a test, and tests stay offline: fixtures over
  network calls (`tests/tiny_*`). Before pushing: `uv run pytest`.
- Ingest must stay idempotent and scoped — overwrite filtered on the merge
  scope (the writer's `source`, plus `source_release` where the table carries
  one), never blind append.
- **One `merge.merge` call per scope per ingest.** `merge.merge` recomputes
  the complete state of `scope`; a second call sharing a scope with the first
  (e.g. county then tract rows under one `source_release`) now raises rather
  than silently dropping the first call's rows (#118). If a source writes
  several slices, either combine them into one incoming table, or narrow
  `scope` to name the slice. To deliberately undo a mistaken ingest within
  the same release (drop a row this release wrongly created), pass
  `merge.merge(..., allow_draft_drop=True)`.
- **PyIceberg is the only writer to the lake.** Never `DELETE`/`UPDATE`/`MERGE`
  a live table through DuckDB or any other engine, even to test (biocOnIce
  learned this the hard way; see its AGENTS.md).
- Report honestly: if something wasn't verified against real data, say so.
  Row counts in docs come from an actual run.

## Workflow

- Every change lands through a pull request that names its issue
  (`Closes #N`). Branches are `area/topic`; commit subjects are
  `area: lowercase imperative summary (#issue)`.
- Milestones M1–M3 mirror SPEC.md § Milestones; each has one tracking issue
  (`wayfinder:map`) whose sub-issues are the work.
