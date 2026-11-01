# Deploying the Cancer Basemap catalog

Written 2026-09-18 while provisioning, from the commands actually run. biocOnIce
never recorded how its bucket and catalog were created; this is that runbook.

## What exists

| Thing | Value |
| --- | --- |
| R2 bucket | `canceronice` (location `wnam`, same account as `bioconice`) |
| R2 Data Catalog | enabled on the bucket; backend warehouse `<account>_canceronice` |
| icegate catalog key / client `warehouse` | `canceronice` |
| Gateway Worker | `icegate-canceronice` → `https://icegate-canceronice.seandavi.workers.dev` |
| Gateway config | [`icegate.yaml`](../icegate.yaml) in this repo, baked into the Worker at deploy |

Same Cloudflare account as biocOnIce is acceptable **only because** nothing
restricted ever lands here (biocOnIce ADR-0005; SPEC.md § Licence gate).

## Secrets (Google Secret Manager, project `cdsci-infra`)

Naming and labels follow `monode/infrastructure/terraform/README.md`.

| Secret | Holds | Status |
| --- | --- | --- |
| `canceronice-icegate-key-seandavi` | ingest API key (read+write); digest in `icegate.yaml` | created 2026-09-18 |
| `canceronice-icegate-key-seandavi-ro` | personal read-only API key | created 2026-09-18 |
| `canceronice-cf-vending-ro` | bucket-scoped RO backend token (`icegate-canceronice-ro`) | minted 2026-09-18 |
| `canceronice-cf-vending-rw` | bucket-scoped RW backend token (`icegate-canceronice-rw`) | minted 2026-09-18 |
| `cdsci-cloudflare-workers-token`, `cdsci-r2-account-id` | shared deploy credentials | pre-existing |

Worker secrets (set by icegate's `scripts/deploy-catalog.sh`):
`CF_ACCOUNT_ID`, `R2_CATALOG_PREFIX`, `CF_API_TOKEN_RO`, `CF_API_TOKEN_RW`.
Unlike `icegate-bioconice`, no Admin-level token enters this Worker.

## Runbook

Standing up (or re-deploying) this catalog is two commands from a sibling
checkout of [icegate](https://github.com/seandavi/icegate), which owns the
generic scripts since icegate#36; this repo keeps only `icegate.yaml`.

```sh
# once: bucket, bucket CORS, R2 Data Catalog, icegate API keys -> starter config
../icegate/scripts/new-catalog.sh canceronice provenance raw geography population \
    measure facility catchment resource > icegate.yaml
# every config change: commit icegate.yaml, then
../icegate/scripts/deploy-catalog.sh canceronice icegate.yaml            # --dry-run to bundle only
../icegate/scripts/deploy-catalog.sh canceronice icegate.yaml --secrets  # re-push Worker secrets (rotation)
```

The first `deploy-catalog.sh` run minted the bucket-scoped backend tokens and
set the Worker secrets; later runs only deploy. Both scripts are idempotent —
on 2026-09-18 `new-catalog.sh` was re-run against this catalog, found every
resource present, and regenerated a config equal to the deployed one.

What they do, for the record (this catalog was provisioned by hand on
2026-09-18, before the scripts existed, with the equivalent calls):

1. `POST /accounts/<id>/r2/buckets` — bucket `canceronice`, location `wnam`.
2. `PUT  …/r2/buckets/canceronice/cors` — GET/HEAD from any origin. DuckDB-WASM
   reads data files straight from R2, and icegate's CORS covers metadata only.
3. `POST …/r2-catalog/canceronice/enable`.
4. icegate API keys (`icegate_` + 32 base62) → Secret Manager; SHA-256 digests
   into `icegate.yaml`. To rotate: `gcloud secrets versions add`, replace the
   digest, redeploy.
5. `wrangler deploy --name icegate-canceronice` with `icegate.yaml` baked in —
   before any secret, because wrangler will not set a secret on a Worker that
   does not exist.
6. Backend tokens `icegate-canceronice-ro` / `-rw` (biocOnIce ADR-0011) minted
   with a token holding *Account · API Tokens · Edit*, archived in Secret
   Manager, and pushed as Worker secrets with the discovered catalog prefix.
7. Verify: `/health`, `/v1/config`, anonymous namespace listing; access-control
   evidence is on issue #15.

## Ingest

```sh
export CANCERBASEMAP_URI=https://icegate-canceronice.seandavi.workers.dev
export CANCERBASEMAP_TOKEN=$(gcloud secrets versions access latest --secret canceronice-icegate-key-seandavi --project cdsci-infra)
uv run cancerbasemap init
```

## Scheduled snapshot landers (#107)

FDA MQSA and HRSA sites/HPSA have no upstream archive, so they run weekly on
onclappc02 as a systemd `--user` timer with an ntfy failure alert — the platform
convention in `monode/infrastructure/SCHEDULING.md`, which also explains why units
are copied, not symlinked. The shared `ntfy-notify@.service` is already installed
there by cdsci-lake. Each run writes under a dated label (`2026.09.19`), which
sorts between the monthly labels `2026.09` and `2026.10`.

```sh
cp systemd/cancerbasemap-snapshots.{service,timer} ~/.config/systemd/user/   # re-copy on change
systemctl --user daemon-reload
systemctl --user enable --now cancerbasemap-snapshots.timer
systemctl --user start cancerbasemap-snapshots.service    # once by hand, then:
journalctl --user -u cancerbasemap-snapshots -n 50
```

Not scheduled yet: the monthly "is there a new edition?" check for release-axis
sources, and BLS LAUS / SDWIS refreshes (#94, #53).

## Table layout (#120)

Every table declares a `sort_by` (`schemas.TableDef`), and `merge.overwrite`
ORDER BYs the final Arrow table by it before every write. `schemas.create` /
`_evolve` also set `write.parquet.row-group-limit` (122,880 rows — DuckDB's
own default) and record the sort as the table's Iceberg sort order, but
neither of those alone changes existing data files: a table written before
#120 keeps its old, unsorted, 1,048,576-row-group layout until its data files
are actually rewritten, because an idempotent re-ingest reports "unchanged"
and touches nothing.

Run this once against the live catalog, after deploying this PR's code, for
every table that has real data:

```sh
export CANCERBASEMAP_URI=https://icegate-canceronice.seandavi.workers.dev
export CANCERBASEMAP_TOKEN=$(gcloud secrets versions access latest --secret canceronice-icegate-key-seandavi --project cdsci-infra)
uv run cancerbasemap rewrite --all
```

It reads each table's current data, sorts it, and commits one Iceberg
overwrite per partition (per `source`, for `measure.observation`) — PyIceberg
only, never a DuckDB write against a live table (AGENTS.md). Before every
commit it checks the sorted data is the identical set of rows (row count plus
an order-independent checksum) as what it read, and refuses to commit a
partition where it isn't, so a bug here fails loud rather than silently
corrupting the table. Safe to re-run: once every table is genuinely sorted, a
second run is a no-op past the checksum check (it still re-reads and re-sorts
each partition, so it costs time but changes nothing).

## Rebuilding provenance.release for the source_version key (#78)

`provenance.release`'s business key changed from `(release, source)` to
`(release, source, source_version)`, and `source_version` had to become a
required column to be a valid Iceberg identifier field. The live table was
created under the old declaration, with `source_version` optional — `_evolve`
(`schemas.py`) detects this and refuses to promote it in place, because
pyiceberg cannot verify no existing row is actually NULL there. In practice
every row written so far does have a `source_version` (`merge.manifest`
always supplies one, defaulting to the retrieval date), so the rebuild below
is a schema-only change, not a backfill:

```python
from cancerbasemap import catalog

cat = catalog()  # CANCERBASEMAP_URI / CANCERBASEMAP_TOKEN set, as in "Ingest" above
table = cat.load_table("provenance.release")
# allow_incompatible_changes=True: pyiceberg refuses optional -> required by
# default because it cannot check existing rows for NULL; every row here
# already has a source_version (see above), so this is safe.
with table.update_schema(allow_incompatible_changes=True) as update:
    update.update_column("source_version", required=True)
    update.set_identifier_fields("release", "source", "source_version")
```

Run once, before deploying code built on this PR. After it, `_evolve` sees
`source_version` already required and reconciles automatically on any future
declaration change.

## Known gaps

1. Steps 1–7 done 2026-09-18; access-control evidence is recorded on issue #15.
2. The bucket is not in OpenTofu, on purpose (#18): icegate buckets are
   created by icegate's `new-catalog.sh`; OpenTofu owns the uptime check.
3. No GCP uptime check on `/health` yet (tracked).
4. `icegate-canceronice` not yet listed in `INDEX.md`'s Cloudflare-hosted table (tracked).
5. `logpush: true` is uncommitted in the local icegate checkout; a deploy from
   a fresh clone silently loses access logs (inherited from biocOnIce).
