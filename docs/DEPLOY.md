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

## Public releases (ADR-0001, #168)

Created 2026-11-01. Nothing is published yet; the first release is #178.

| Thing | Value | How it was made |
| --- | --- | --- |
| R2 bucket | `data-cancerbasemap` (ENAM hint) | monode `infrastructure/terraform/apps/cancerbasemap/` (monode#139); from the monode main checkout: `tofu plan -target=module.cancerbasemap` (1 to add), then `tofu apply` of that plan |
| R2 write credentials | the account-scoped `cdsci-r2-*` keys in GSM, as biocOnIce's `upload` uses | pre-existing; no new token |
| Hugging Face dataset repo | [`seandavis/cancerbasemap`](https://huggingface.co/datasets/seandavis/cancerbasemap), public, empty | `HfApi.create_repo('seandavis/cancerbasemap', repo_type='dataset')` with `HF_TOKEN` from GSM `cdsci-huggingface-token` |
| Worker, site and `/data/` | `data-cancerbasemap` on `basemap.cancerdatasci.org` | not yet: #175 (creates the custom domain on deploy) |
| Analytics Engine dataset | `data_cancerbasemap_usage` | created by the Worker's first write (#175) |
| Access logs | the account `http_requests` Logpush already covers `cancerdatasci.org` into `cdsci-cf-logs` | pre-existing (monode `apps/cloudflare_logs`). The Worker also `console.log`s one monode #67 access record (v1, raw `c_ip` included) per request, shipped by `logpush = true`; delivery needs a Workers-trace Logpush job for this script (monode #67), so read a row back from R2 after deploy (#177) |

The catalog above keeps its `canceronice` names until it is retired (#183).

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

## Monthly release (#179)

[ADR-0001](adr/0001-public-releases-monthly-parquet-bundles.md) § Cadence: on the 1st
of the month, 00:00 UTC, `cancerbasemap-release.timer` runs `systemd/release.sh`:
publish → gate (against `latest/`) → `hf-push --apply` → `upload` dry run →
`upload --apply`, stopping at the first failure, then deleting the local bundle. It is
built in `/data/davsean/tmp/cancerbasemap-release-<UTC date>/` (`/tmp` is small and
noexec). No credentials are configured: publish reads the catalog anonymously, and
gate, hf-push and upload fetch theirs from GSM through `gcloud`, so the gcloud login
on onclappc02 must be current. The unit runs the checkout at
`~/Documents/git/cancer-on-ice`, whatever is checked out there: keep it on an
up-to-date `main`.

```sh
cp systemd/cancerbasemap-release.{service,timer} ~/.config/systemd/user/   # re-copy on change
systemctl --user daemon-reload
systemctl --user start ntfy-notify@cancerbasemap-release.service   # test alert reaches cdsci-lake-ops
systemctl --user start cancerbasemap-release.service    # one real run by hand, first
journalctl --user -u cancerbasemap-release -f
systemctl --user enable --now cancerbasemap-release.timer
systemctl --user list-timers cancerbasemap-release.timer   # next: the 1st, 00:00 UTC
```

Start the service by hand before trusting the timer: `systemd-analyze --user verify`
passes a unit whose `ExecStart=` is wrong. That run also times the steps; tighten
`TimeoutStartSec=` from the journal.

**Logs**: the journal, which vector ships to ClickHouse (`systemd_user_jobs`, monode).
**Failure**: `OnFailure=ntfy-notify@%N.service` posts to the `cdsci-lake-ops` ntfy
topic. The notifier uses the same gcloud login, so an expired login fails the release
*and* silences its alert; a missing alert is not a clean run. Check `systemctl --user
status cancerbasemap-release.service`.

**When the gate fails**, nothing was archived or uploaded. Read the report in the
journal. If the data is at fault, fix it, delete the bundle directory so the re-run
rebuilds it, and `systemctl --user start cancerbasemap-release.service`. If a required
check is wrong, fix the gate through a PR. Re-runs the same day reuse a complete bundle
(so `hf-push` sees the manifest already tagged); other failures (network, R2, Hugging
Face) are fixed by simply re-running. A re-run after `latest/` became today's release
fails the gate ("not older"): the release is already out.

After the upload, the same run rebuilds and deploys the site (`basemap.cancerdatasci.org`)
so the landing page's numbers describe the new release. It renders in a throwaway
worktree of `origin/main`, re-executes only `site/index.qmd`, and deploys with
`npx wrangler deploy` under the OAuth login in `~/.config/.wrangler`. The docs venv is
`~/.local/share/cancerbasemap/docs-venv` (outside `$TMPDIR`, which is cleaned weekly), and
the `coi-docs` Jupyter kernel is re-pointed at it each run. If a release succeeds but the
site step fails, the data is already published; fix the step and rerun the last block of
`systemd/release.sh` by hand.

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
