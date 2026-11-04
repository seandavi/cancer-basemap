"""Hugging Face archive (ADR-0001 § Hugging Face, #174): every gated release bundle pushed to
hf.co/datasets/seandavis/cancerbasemap as one commit, tagged with its release date `YYYY-MM-DD`.

Ported from biocOnIce's hf.py. The bundle is the local directory `cancerbasemap publish` wrote
and `cancerbasemap gate` passed (its gate.json matches its manifest.json, and each Parquet file
its manifest sha256). It pushes the Parquet, manifest.json and gate.json as they are, and
generates views.sql and restore.sql over paths relative to the download directory, and
README.md, the dataset card. It does not push cancerbasemap.duckdb, whose views read R2.
Nothing points at `hf://`: anonymous reads there are rate-limited (HTTP 429).
If the tag exists with the same manifest.json, the push does nothing, so a re-fired timer is
harmless; with a different one it fails. Tags are never deleted. DOIs are not minted.
"""

import hashlib
import json
import os
import time
import subprocess
from datetime import date
from pathlib import Path

from cdsci.publish import restore_sql, views_sql
from huggingface_hub import CommitOperationAdd, CommitOperationDelete
from huggingface_hub.errors import HfHubHTTPError, RepositoryNotFoundError

from .gate import GATE_FILE

REPO = "seandavis/cancerbasemap"
TAG_ATTEMPTS, TAG_WAIT_S = 5, 10
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
    manifest_bytes = (release / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    tag = date.fromisoformat(manifest["release"]).isoformat()
    proof = release / GATE_FILE
    if not proof.exists():
        raise SystemExit(f"{release}: no {GATE_FILE}; only a release that passed "
                         "`cancerbasemap gate` is pushed")
    gate = json.loads(proof.read_text())
    if gate.get("manifest_sha256") != hashlib.sha256(manifest_bytes).hexdigest():
        raise SystemExit(f"{release}/{GATE_FILE} is for another manifest.json; "
                         "re-run `cancerbasemap gate` on this bundle")
    if apply:
        api.create_repo(repo, repo_type="dataset", private=False, exist_ok=True)
    try:
        tags = {t.name for t in api.list_repo_refs(repo, repo_type="dataset").tags}
        remote = api.list_repo_files(repo, repo_type="dataset")
    except RepositoryNotFoundError:  # a dry run before the first push
        tags, remote = set(), []
    if tag in tags:
        pushed = Path(api.hf_hub_download(repo, "manifest.json", repo_type="dataset", revision=tag))
        if pushed.read_bytes() != manifest_bytes:
            raise SystemExit(f"{repo}@{tag} exists with a different manifest.json; a release "
                             "is never replaced: publish the changes as the next release")
        print(f"{repo}@{tag} already exists with this manifest.json; nothing to do")
        return
    # gate.json binds manifest.json, not the Parquet: re-hash every file against its manifest
    # sha256, streamed.
    for t in manifest["tables"]:
        with (release / t["path"]).open("rb") as f:
            if hashlib.file_digest(f, "sha256").hexdigest() != t["sha256"]:
                raise SystemExit(f"{release}/{t['path']} does not match its manifest.json "
                                 "sha256; re-publish and re-gate this bundle")

    tables = [{**t, "bytes": (release / t["path"]).stat().st_size} for t in manifest["tables"]]
    generated = {
        "views.sql": views_sql(tables, "."),
        "restore.sql": restore_sql(tables, "."),
        "README.md": build_card(tag, manifest, gate, tables, repo),
    }
    files = [t["path"] for t in tables] + ["manifest.json", GATE_FILE]
    # create_commit, not upload_folder: with hf_xet installed, upload_folder splits a large
    # upload into several commits; a release is exactly one. Remote files not in this
    # release leave main (they stay reachable at older tags).
    ops = [CommitOperationAdd(p, release / p) for p in files]
    ops += [CommitOperationAdd(p, text.encode()) for p, text in generated.items()]
    keep = {*files, *generated}
    deletes = [CommitOperationDelete(p) for p in remote if p not in keep and p != ".gitattributes"]
    for p in files:
        print(f"put    {p}  ({(release / p).stat().st_size:,} bytes)", flush=True)
    for p, text in generated.items():
        print(f"put    {p}  (generated, {len(text.encode()):,} bytes)", flush=True)
    for d in deletes:
        print(f"delete {d.path_in_repo}", flush=True)
    message = f"Cancer Basemap release {tag}"
    if not apply:
        print(f"dry run: would push {repo}@{tag}; nothing written; --apply to push")
        return
    commit = api.create_commit(repo, ops + deletes, repo_type="dataset", commit_message=message)
    # The Hub can answer 409 Conflict to a tag on a commit it made a moment ago (the
    # 2026-11-03 scheduled release failed here; the same call succeeded a minute later).
    for attempt in range(TAG_ATTEMPTS):
        try:
            api.create_tag(repo, repo_type="dataset", tag=tag, revision=commit.oid, tag_message=message)
            break
        except HfHubHTTPError as e:
            if getattr(e.response, "status_code", None) != 409 or attempt == TAG_ATTEMPTS - 1:
                raise
            time.sleep(TAG_WAIT_S * (attempt + 1))
    print(f"pushed {repo}@{tag} ({commit.oid})")
