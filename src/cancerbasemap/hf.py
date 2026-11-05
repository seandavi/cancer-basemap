"""Hugging Face archive (ADR-0001 § Hugging Face, #174): every gated release bundle pushed to
hf.co/datasets/seandavis/cancerbasemap as one commit, tagged with its release date `YYYY-MM-DD`.

The mechanics are `cdsci.publish.hf`, shared with biocOnIce (cdsci-lake ADR-0027): one commit
of the Parquet, manifest.json and gate.json as they are, views.sql and restore.sql over paths
relative to the download directory, and README.md, the dataset card; cancerbasemap.duckdb
(whose views read R2) is not pushed, and nothing points at `hf://` (anonymous reads there are
rate-limited, HTTP 429). If the tag exists with the same manifest.json the push does nothing,
so a re-fired timer is harmless; with a different one it fails. Tags are never deleted.

This module is the cancer policy: the repo, the tag (the release date), the card, the token
from GSM, and that only a bundle whose gate.json certifies its manifest.json is pushed. DOIs
are not minted.
"""

import json
import os
import subprocess
from datetime import date
from pathlib import Path

import cdsci.publish.hf
from cdsci.publish.gate import GATE_FILE, check_proof

REPO = "seandavis/cancerbasemap"
TOKEN_SECRET = "cdsci-huggingface-token"
TOKEN_PROJECT = "cdsci-infra"
CODE_URL = "https://github.com/seandavi/cancer-basemap"


def hf_token():
    """HF_TOKEN if set, else GSM secret cdsci-huggingface-token in cdsci-infra (via gcloud)."""
    return os.environ.get("HF_TOKEN") or subprocess.run(
        ["gcloud", "secrets", "versions", "access", "latest", f"--secret={TOKEN_SECRET}",
         f"--project={TOKEN_PROJECT}"], capture_output=True, text=True, check=True).stdout.strip()


def build_card(tag, manifest, gate, tables, repo=REPO):
    """Dataset card. `gate`: the bundle's gate.json; `tables`: the manifest's tables, each
    with its file's `bytes`."""
    configs = "\n".join(f"- config_name: {t['schema']}_{t['table']}\n  data_files: {t['path']}"
                        for t in tables)
    rows = "\n".join(f"| `{t['schema']}.{t['table']}` | `{t['path']}` | {t['row_count']:,} "
                     f"| {t['bytes'] / 1e6:,.1f} |" for t in tables)
    sources = sorted({(p.get("source"), p.get("source_version"))
                      for p in manifest.get("provenance", [])}, key=str)
    source_rows = "\n".join(f"| {s} | {v or ''} |" for s, v in sources)
    gb = sum(t["bytes"] for t in tables) / 1e9
    local = f"cancerbasemap-{tag}"
    return f"""---
license: other
license_name: mixed-upstream-terms
license_link: https://huggingface.co/datasets/{repo}/blob/{tag}/manifest.json
pretty_name: Cancer Basemap
tags:
- cancer
- epidemiology
- public-health
- geography
configs:
{configs}
---

# Cancer Basemap {tag}

Cancer Basemap is public population cancer data (incidence, mortality, screening,
risk factors, health-care access and the geography they are keyed on) as flat Parquet,
one file per table. The code is at {CODE_URL}.

This is release **`{tag}`**, which passed `cancerbasemap gate` (see
[`gate.json`](gate.json)). Every gated release is archived here under its release date.
Cite and pin it by the `{tag}` revision. Tags are never deleted.

## Download, then query

Download the release, then query the local files. Do not query `hf://` paths in place:
anonymous requests are rate-limited, and one query makes many requests, so repeated
queries fail with HTTP 429.

```bash
hf download {repo} --repo-type dataset --revision {tag} --local-dir {local}
```

One table only:

```bash
hf download {repo} --repo-type dataset --revision {tag} --local-dir {local} \\
  --include measure/observation.parquet
```

DuckDB: `views.sql` creates one view per table over paths relative to the download
directory, so run it from there:

```bash
cd {local}
duckdb cancerbasemap.duckdb < views.sql
duckdb cancerbasemap.duckdb -c "SELECT count(*) FROM measure.observation"
```

`restore.sql` materialises every table into the database instead and checks the row
counts against `manifest.json`: `duckdb cancerbasemap-local.duckdb < restore.sql`, from
the same directory.

Python (polars):

```python
import polars as pl

obs = pl.scan_parquet("{local}/measure/observation.parquet").head(10).collect()
```

R (arrow):

```r
obs <- arrow::read_parquet("{local}/measure/observation.parquet")
```

## Provenance

| | |
|---|---|
| Release | {manifest["release"]} |
| Published at | {manifest.get("published_at", "")} |
| Code (git SHA) | `{manifest.get("git_sha") or ""}` |
| Gate reference | {gate.get("reference") or ""} |
| Gate passed at | {gate.get("passed_at", "")} |

Sources and their upstream versions:

| Source | Version |
|---|---|
{source_rows}

The full record is [`manifest.json`](manifest.json): per table its row count, sha256,
columns and their documentation, and every `provenance.release` row.

## Tables

{len(tables)} files, {gb:.2f} GB in total.

| Table | File | Rows | Size (MB) |
|---|---|---:|---:|
{rows}

## License

The terms are mixed. Each source keeps its own terms; the sources and versions are
listed above and in `manifest.json` (`provenance`). Where a source requires a notice to
travel with its data, the table comment carries it (`views.sql`).

## Citation

DOIs are not minted. Cite the tag:

```bibtex
@misc{{cancerbasemap_{tag.replace("-", "_")},
  title  = {{Cancer Basemap, release {tag}}},
  author = {{Davis, Sean}},
  year   = {{{tag[:4]}}},
  url    = {{https://huggingface.co/datasets/{repo}/tree/{tag}}}
}}
```
"""


def hf_push(release: Path, api, repo=REPO, apply=False):
    """Push the gated bundle `release` to `repo` as one commit tagged with its release date.
    Dry run unless `apply`: the plan is printed, and nothing is created or written on
    Hugging Face."""
    gate = check_proof(release)
    tag = date.fromisoformat(json.loads((release / "manifest.json").read_text())["release"]).isoformat()
    cdsci.publish.hf.hf_push(
        release, api, repo=repo, tag=tag, apply=apply, extra_files=(GATE_FILE,),
        card=lambda tag, manifest, tables: build_card(tag, manifest, gate, tables, repo),
        message=f"Cancer Basemap release {tag}")
