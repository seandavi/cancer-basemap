# 0001 — Cancer Basemap public releases: monthly Parquet bundles, a year on R2, every one on Hugging Face

**Status**: Accepted — owner decision, 2026-11-01.
**Adopts**: biocOnIce [ADR-0014](https://github.com/seandavi/bioc-on-ice/blob/main/docs/adr/0014-public-releases-are-parquet-plus-duckdb-views.md)
(Parquet + DuckDB views), [ADR-0015](https://github.com/seandavi/bioc-on-ice/blob/main/docs/adr/0015-sources-write-to-cdsci-lake-products-derive-at-release.md)
(sources write to cdsci-lake, the product derives at release) and the shape of
[ADR-0016](https://github.com/seandavi/bioc-on-ice/blob/main/docs/adr/0016-release-cadence-weekly-r2-monthly-hf.md)
(R2 for querying, Hugging Face for the archive), with the differences below.
**Supersedes**: for serving, the inherited ADR-0005 and ADR-0011 once icegate is retired;
SPEC.md § Versioning model's per-dataset releases (`keep_last`, "pinned releases are never
pruned") and with them the local-only `canceronice-places` pilot (#165, #166); the route of
#159 (shared DuckLake releases). **Settles** #66 (cadence).

## Context

The public surface is an Iceberg catalog on R2 behind `icegate-canceronice`, with
anonymous read and vended credentials (SPEC.md § Architecture). Both siblings have left
that design. omicidx serves dated Parquet bundles with `views.sql` and archives a release
a month to Hugging Face (omicidx ADR-0004, ADR-0007). biocOnIce adopted the same bundle on
2026-10-30, decided to move its writers into cdsci-lake (its publisher still reads its
Iceberg catalog while they move), and is retiring Iceberg, icegate and credential
vending (biocOnIce ADR-0014 to 0016). Their reasons apply here unchanged: a
public bucket of static files vends nothing, every engine reads Parquet, and the frozen
DuckLake copy had no readers in three months of omicidx's Worker analytics.

The PLACES pilot (#165) built a per-dataset `cdsci.lake.publish` release locally; nothing
was published. biocOnIce took that route first (its ADR-0013) and replaced it, for the
public product, with one whole-product bundle.

What differs here is how the data changes. Nearly every source publishes once a year or
less: ACS, PLACES, SVI, RUCA/RUCC, AHRF, TRI, EJScreen, the SCP vintages. Two, FDA MQSA
(weekly) and HRSA sites (daily), overwrite themselves upstream and keep no archive; both
are landed weekly (#107). Users are
catchment offices and cancer-centre analysts, who work on an annual reporting cycle.

The catalog on 2026-11-01 held 59 tables and 78,551,989 rows, Type-2 history included,
counted with `SELECT count(*)` over every table through the anonymous `ATTACH`
(`measure.observation` 29.6M; `raw.sdwis__violations_enforcement` 15.4M;
`raw.scp__incidence` 13.0M). Bundle bytes were not measured; the first `publish` run
records them.

## Decision

### The bundle

The public product is biocOnIce's bundle, unchanged in shape: dated, immutable
`v{YYYY-MM-DD}/` folders plus `latest/`, each holding flat Parquet per table,
`cancerbasemap.duckdb`, `views.sql`, `restore.sql`, `manifest.json` and `gate.json`. Each
folder's views read that folder's own files. A release is dated by its UTC day; a
finished dated folder is never overwritten, so a second release the same day waits for
the next date. Parquet is the contract; the views are a DuckDB convenience.

The code is copied from biocOnIce with these changes, each covered by a test: Type-2
tables drop their validity columns (biocOnIce publishes `SELECT *`); `upload` puts
`gate.json` beside `manifest.json`; the Hugging Face tag is the release date, not the
month; the push comes before the upload; and the retention rule below.

- **Current rows only** for the six Type-2 tables (`geography.unit`, `geography.alias`,
  `measure.observation`, `measure.cancer_site`, `measure.cancer_site_group`,
  `facility.site`): `valid_to IS NULL`. This loses less here than it sounds.
  `source_release` and `period_start`/`period_end` are columns, so every derived SCP
  vintage, PLACES release and ACS release is a current row in every bundle. (SCP V1 and
  V2 are landed raw only, #117; their raw rows ship.) Acceptance A becomes a check on one
  bundle: the raw SCP tables filtered on `scp_vintage = 'V3'` reproduce the V3 deposit's
  landed topics exactly, and `measure.observation` filtered on `source_release = 'V3'`
  is their documented derivation (not every topic is derived, and derivation drops
  duplicate captures). What current-only does lose is a correction within one
  `source_release`: the corrected rows replace the old ones. Values that were published
  stay in earlier releases on Hugging Face; a value corrected before any release
  published it was never public, and survives only in the final Iceberg archive.
- **Raw ships whole**, every snapshot included. The weekly MQSA and HRSA snapshots are
  rows keyed by `retrieved_on`, so their history is in every bundle and no weekly
  snapshot depends on the release cadence.
- **Product tables are release SELECTs** (biocOnIce ADR-0015 (b)). `publish.TABLES` is
  (schema, table, SELECT). The first releases SELECT from the live Iceberg catalog; a
  table moves to cdsci-lake by changing its SELECT, read at one pinned lake snapshot
  recorded in `manifest.json`. `measure.observation`, the stack across sources, is the
  clearest case of product shape: it stays a SELECT, not a lake table, unless a second
  consumer asks for it.
- **Layout.** `measure.observation` is written sorted by (geography level and state, `source`,
  `source_release`, `measure_id`, `geo_id`), where the level and state are the first two
  characters after the colon of `geo_id` (`county:08`, `tract:08`, `nation:US`), at DuckDB's default row
  group size. The first release sorted by `(source_release, measure_id, geo_id)` in 247 row groups, so
  the Catchment Profiles app (#206) read ~125 MB to draw one center: a few dozen counties of every
  measure touch every row group. Replaying that app's eight queries for one 64-county center over
  HTTP range reads against the 29.6M-row dev bundle: 46.7 MB read before, 8.1 MB after; under a
  model of DuckDB-Wasm's 16 MB read-ahead (which gives 160 MB for the old file, near the observed
  125) 59 MB after. The cost is a one-measure, all-counties query: 0.9 -> 5.2 MB read, 23 -> 42 MB
  under the same model. Row groups of 16k or 4k rows did not help: the footer grows from 0.4 to 2.8
  or 11 MB and requests multiply 3 to 12 times. Sorting by `source` first kept measure queries as
  cheap as before but left a profile at 98 MB under the model. The Parquet path and columns are
  unchanged. Numbers: #206.

### The gate

`cancerbasemap gate` checks each bundle against the previous published release, as
biocOnIce's does, and adds the hard gate this repo exists for, checked on the Parquet
users get: **in `measure.observation`, `value` is NULL whenever `value_status !=
'reported'`**. A release that fails is not uploaded or archived.

**Amended 2026-11-01 (owner):** every source publishes aggregates it has already
suppressed, so this repo never re-suppresses. The gate does not NULL-check `lower`,
`upper`, `numerator` or `denominator` (an earlier draft did, following #162): those carry
what the source itself published for the cell, and clearing them would drop public
numbers. The first real bundle has such rows (ACS `suppressed_small_count` with
numerator and denominator, 17,735 rows; FARA `not_available` with a denominator, 75,622),
and they stand. What the gate guards is presentation: a cell the source did not report
never reads as a number in `value`.

### Cadence

One scheduled release a month, on the 1st (UTC): publish → gate → Hugging Face push →
upload dry run → upload `--apply`, the same day. The archive comes first so that nothing
reaches R2, and so nothing can be pruned from it, without a permanent copy: `upload`
refuses a bundle whose `manifest.json` is not the one at its Hugging Face tag. Landers keep their own clocks; the
snapshot landers stay weekly. A release can also be cut by hand mid-month, for a
correction or a large source release (a new SCP vintage, a new PLACES year).

### R2: the newest release of each of the last 12 months

R2 serves queries in place. `upload` keeps:

- the newest `v{date}/` of each of the 12 newest calendar months that have one;
- any other `v{date}/` whose successor in the same month is less than 7 days old, so a
  pin on a release that a correction replaced keeps working for a week after the
  correction;
- `latest/`, which is not counted, and the folder being uploaded.

Everything else is deleted. Dates and ages are UTC days. Months are counted, not folders,
so a mid-month correction replaces its month instead of pushing out a year-old one; and a
month with no release does not shorten the window.

Twelve is a starting point. If Worker analytics later show months nobody reads, the
window can shrink by amending this ADR with that data. Nothing is lost when it does,
because every release is on Hugging Face.

### Hugging Face: every published release, forever

Every release that passes the gate is pushed to the Hugging Face dataset repo as one
commit, tagged with its release date `YYYY-MM-DD`: the R2 folder `v2026-12-01/` is the
tag `2026-12-01`. Tags are never deleted. If the tag exists and holds the same
`manifest.json`, the push does nothing; if it holds a different one, the push fails. The push follows biocOnIce's `hf-push`:
it refuses a bundle whose `gate.json` does not match its `manifest.json`, generates
`views.sql`/`restore.sql` over download-relative paths and a dataset card from
`manifest.json`, skips `cancerbasemap.duckdb`, and is idempotent as above. Docs tell
users to download a tag, not to query `hf://` in place (HTTP 429).

### Retiring Iceberg

The bundle ships first, read from the live catalog, so clients move before any writer
does. Then:

1. Anonymous read on `icegate-canceronice` is switched off once clients read the bundle.
   `publish` then reads the catalog with the read-only key, so releases keep building.
2. Landers move to cdsci-lake source by source (biocOnIce ADR-0015 (a)), SCP first, since
   cdsci-lake already curates it. A source's Iceberg tables get no writes once it moves.
3. When no lander writes to Iceberg, every table, validity columns and closed rows
   included, is exported as one archive release on Hugging Face, and its row counts are
   checked against the catalog. Archiving last means no closed row is created after it.
4. Then the catalog, icegate, the vending tokens, PyIceberg and `merge.py` go, and
   SPEC.md § Architecture / § Versioning model and AGENTS.md's writer rules are
   rewritten. Until then they describe the writers that still exist.

### Infrastructure of its own

The public product is renamed **Cancer Basemap** before its first release. "cancerOnIce"
read as frozen biospecimens and said nothing about geography; "Catchment Lake" collides
with a hydrology term and no longer describes a product that is not a lake. A basemap is
the common reference layer a map is drawn on, which is what this is under catchment
dashboards such as Cancer InFocus. The Python package and CLI are `cancerbasemap`
(`basemap` on PyPI is matplotlib's toolkit). The Iceberg-side names (`canceronice`
bucket, `icegate-canceronice`, `canceronice-*` secrets) keep their names until they are
retired.

It gets its own serving infrastructure, parallel to biocOnIce's, in the same Cloudflare
account (still acceptable only because nothing restricted lands, inherited ADR-0005):

| Thing | Name |
| --- | --- |
| R2 bucket (public releases) | `data-cancerbasemap`, created by monode OpenTofu like `data-bioconice` |
| Worker (site at `/`, bucket at `/data/`) | `data-cancerbasemap` |
| Site | `https://basemap.cancerdatasci.org/` |
| Data | `https://basemap.cancerdatasci.org/data/` (`latest/`, `v{YYYY-MM-DD}/`) |
| Analytics Engine dataset | `data_cancerbasemap_usage` |
| Hugging Face dataset repo | `seandavis/cancerbasemap` |
| Secrets | GSM project `cdsci-infra`, prefix `cancerbasemap-`; R2 writes use the existing account-scoped `cdsci-r2-*` credentials, as biocOnIce's do |

One host, no separate data host (the zone does not use four-level names, and omicidx
retired its separate data host for `/data/`). Because bundle views and every Hugging Face
copy hard-code `/data/` URLs, two rules hold for good: **`/data/` belongs to the bucket**,
so no page is ever routed under it; and **`/data/` serves bytes and never redirects**,
since DuckDB range reads and DuckDB-Wasm `If-Match` requests depend on it. If the bytes
ever move, the Worker keeps `/data/` as a pass-through.

The release bucket is new, not the Iceberg bucket `canceronice`, so that the catalog can
be deleted whole at retirement without touching a release. The Worker replaces the docs
Worker at `canceronice-docs.seandavi.workers.dev`.

### Logging

- **Access** follows monode's standard for Worker sites (monode #67): R2 first,
  ClickHouse as the place it all comes together. The account's `http_requests` Logpush
  already ships every `cancerdatasci.org` request, Worker responses included, to the
  private bucket `cdsci-cf-logs`, kept indefinitely; the Worker adds bioc-edge's
  versioned `accessRecord` line per request with `logpush = true`, landing beside it; and
  monode #108 loads both into ClickHouse. That record is the year of reads retention
  decisions need. Each bucket request also writes an Analytics Engine data point, as in
  both siblings, for quick download counts (it keeps about three months). Pages use the
  shared GA4 property through Quarto's `google-analytics:`.
- **Jobs**: the systemd `--user` units log to the journal, which vector already ships to
  ClickHouse (`systemd_user_jobs`, monode); failures alert through `ntfy-notify@`. Nothing
  new to build.

### The site

The Worker serves a Quarto site modelled on biocOnIce's and omicidx's: landing page,
releases (R2 folders and Hugging Face tags), DuckDB-Wasm playground, guides and per-source
pages, the archify structure, and light and dark themes. Its palette is its own, so the
three sites are told apart at a glance: omicidx is emerald, biocOnIce indigo and violet,
cancerOnIce **glacier blue with an ember accent**. Dark: navy canvas `#0b1220`, panel
`#111a2e`, sky `#38bdf8` primary, orange `#fb923c` accent (8.1–8.7:1 and 7.7–8.3:1 on
canvas and panel). Light: canvas `#f8fafc`, sky `#0369a1` primary (5.7:1), orange
`#c2410c` accent (5.0:1). Text in either colour clears WCAG AA's 4.5:1.

## Why not weekly releases (biocOnIce)

Almost every source changes once a year. A weekly release would re-upload the same bytes
51 times in 52 to make two facility tables a few weeks fresher, and the facility
snapshots are kept anyway: they land weekly and ship in the next monthly release. No
user here works on a weekly cycle.

## Why not daily releases (omicidx)

omicidx publishes daily because GEO and SRA change daily. Nothing here does.

## Why not keep the newest N folders (biocOnIce's keep 4)

Counting folders lets a mid-month correction push the oldest month out early. Counting
months keeps the window a year regardless of how many releases a month had.

## Why not keep every release on R2

Unbounded storage on the serving bucket, for releases that are already permanent on
Hugging Face. A year matches the annual reporting cycle: an analysis from last year's
report re-runs in place against its pinned URL; anything older, or anything cited, uses
the tag.

## Why not archive only the monthly release on Hugging Face (biocOnIce)

Then a hand-cut correction would exist only on R2 and disappear when its month aged out.
Pushing every release keeps the rule simple: R2 can drop anything, because Hugging Face
has it.

## Why not keep Iceberg and icegate, or publish a frozen DuckLake (#159)

The reasons in biocOnIce ADR-0014 hold, and one is specific to this repo: boundaries as
GeoParquet (#158) are blocked on PyIceberg's Iceberg v3 write support, and a Parquet
bundle needs no catalog support at all.

## Consequences

- Acceptance E changes from anonymous Iceberg `ATTACH` to reading the bundle from DuckDB
  and DuckDB-WASM without credentials: `.read views.sql`, or `ATTACH` of
  `cancerbasemap.duckdb` over HTTPS. ECCO reads the bundle's Parquet.
- The federation registry entry (#62) loses its basis, as biocOnIce ADR-0014 says of its
  own.
- #19 (what the validity columns are called) stops mattering for public users once the
  bundle ships, since releases carry no validity columns. It still governs the writer
  until Iceberg retires.
- The `canceronice-places` dataset release (#166) is replaced by the bundle.
- `publish`, `gate`, `upload` and `hf-push` are copied from biocOnIce, which copied them
  from omicidx. That is the third copy. No shared release builder now (biocOnIce
  ADR-0015 (a)); the parts that are identical in all three are a candidate to move into
  cdsci-lake when one of them next changes.
- A source update can take up to a month to reach `latest/`. A hand-cut release closes
  the gap when it matters.
