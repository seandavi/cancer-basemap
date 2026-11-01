# Cancer Basemap Explorer

A static page that reads the live Cancer Basemap catalog through icegate,
anonymously, and shows what's in it: namespaces, tables, column docs,
business keys, partition specs, snapshot history, a copyable DuckDB snippet
per table, worked recipe queries, and an in-browser DuckDB-WASM query tab
that actually reads table data. Plain HTML/CSS/JS, no framework, no build
step. Nothing here writes to the catalog; nothing here is a backend — it
makes the same anonymous, read-only REST calls a browser could always make
against `https://icegate-canceronice.seandavi.workers.dev`
(`icegate.yaml`'s `cors: origins: ["*"]` exists for exactly this). Ported
from [bioc-on-ice](https://github.com/seandavi/bioc-on-ice)'s explorer
(#50).

## Serve it locally

```sh
cd explorer/public
python3 -m http.server 8000
# open http://localhost:8000
```

No server-side code, no build, no `npm install` — everything is fetched
from the live catalog and (for the Query tab) a CDN at request time.

## Deploy

This ships as a Cloudflare Worker with **Workers Static Assets**
(`explorer/wrangler.jsonc`: `assets.directory: ./public`, no Worker script —
an assets-only Worker is allowed), the same account and deploy credentials
`docs/DEPLOY.md` uses for the gateway, kept as a separate Worker so a change
to one never risks the other:

```sh
cd explorer
export CLOUDFLARE_API_TOKEN=$(gcloud secrets versions access latest --secret cdsci-cloudflare-workers-token --project cdsci-infra)
export CLOUDFLARE_ACCOUNT_ID=$(gcloud secrets versions access latest --secret cdsci-r2-account-id --project cdsci-infra)
npx wrangler deploy
```

First deploy creates the Worker under the name in `wrangler.jsonc`
(`canceronice-explorer`) and serves it at
`https://canceronice-explorer.<account-subdomain>.workers.dev`; a later
deploy just ships a new version, no downtime. **Not deployed as part of
#50** — the maintainer deploys.

`wrangler pages deploy explorer/public --project-name canceronice-explorer`
(Cloudflare Pages) or `gh-pages`/GitHub Pages Actions on `explorer/public`
both work too, if the Worker path is ever not preferred — the page has zero
platform-specific code — but Workers Static Assets is what this repo is
configured for.

## In-browser DuckDB-WASM queries: verified working

**Finding (tested live in a real browser, 2026-09-18): both `ATTACH` and
table *data* reads succeed anonymously.** This is the opposite of
bioc-on-ice's finding for its own bucket, and it's why this port's Query tab
is on by default rather than opt-in:

1. `duckdb-wasm` (`@duckdb/duckdb-wasm@1.33.1-dev57.0`, same version pinned
   by bioc-on-ice's explorer) loads in the browser via ESM from jsdelivr,
   using the same `<script type="importmap">` for the bare `apache-arrow`
   specifier (`index.html`).
2. `INSTALL iceberg; LOAD iceberg; INSTALL httpfs; LOAD httpfs;` succeeds.
3. `ATTACH 'canceronice' AS coi (TYPE ICEBERG, ENDPOINT '...', AUTHORIZATION_TYPE 'none')`
   succeeds — this pinned DuckDB-WASM version rejects `URI` in favour of
   `ENDPOINT` (checked directly: the Python `duckdb` 1.5.5 in this repo's
   `pyproject.toml` also only accepts `ENDPOINT`, so the WASM build, being
   older, needs it too).
4. `SELECT * FROM coi.measure.observation LIMIT 25` **succeeds**, returning
   25 real rows in ~9 seconds — the `canceronice` R2 bucket's CORS policy
   (allowing anonymous `GET`/`HEAD` from any origin, set at bucket creation
   per #8) lets the browser's preflight and the subsequent data-file GET
   both through. No CORS error, no 404 — this is the exact failure mode
   #50 and bioc-on-ice's explorer hit, and it does not reproduce here.

Verified with the Playwright browser tools against `explorer/public` served
locally: namespace/table browsing (metadata), then the Query tab's default
`SELECT * FROM coi.measure.observation LIMIT 25;` run to completion with a
real result table rendered — not just the `ATTACH` succeeding.

**Consequence for this page, vs. bioc-on-ice's port**: the Query tab
(`app.js`, `buildQueryPanel`) is **on by default** (`localStorage`-backed
opt-*out*, not opt-in — flip it off on the Recipes page if you'd rather not
run DuckDB-WASM). `provenance.release`'s release×source matrix is still
shown as a copyable `PIVOT` query on the table's Overview tab rather than
rendered inline (this static page still has no query engine of its own
outside the Query tab), but a visitor can now actually run it themselves.

## What's verified vs. what isn't

Every column doc, table comment, partition spec and snapshot on the page is
read live from the REST catalog at view time (`app.js`'s `api()`), never
copied from `src/cancerbasemap/*`. The five recipe queries in
`public/recipes.js` were run against the live catalog with the `duckdb`
Python API (`uv run python`) on 2026-09-18, and separately confirmed to run
in the browser via the Query tab; the numbers in the "Verified" line under
each recipe are what DuckDB actually returned that day — re-run them
yourself to check currency (row counts will drift as more sources and
releases land).

This repo's own tests stay offline (AGENTS.md — fixtures over network
calls), so nothing here is wired into CI against the live catalog; the
verification above was done by hand this session, live, not automated.

## Deviations from bioc-on-ice's explorer (#50)

- Branding: title "Cancer Basemap", subtitle "the Cancer Basemap
  catalog" (SPEC.md § Names).
- `CATALOG_ENDPOINT` → `https://icegate-canceronice.seandavi.workers.dev`,
  `WAREHOUSE` → `canceronice`, ATTACH alias `bioc` → `coi`, Worker name
  `canceronice-explorer`, `localStorage` key `bioconice_query_tab` →
  `cancerbasemap_query_tab`.
- Property-key prefixes read from table metadata (`bioc.license`,
  `bioc.column.*.prefix`/`.coordinate_system`) renamed to `coi.*` for
  consistency; Cancer Basemap's catalog doesn't currently set any of these
  properties, so this code path renders nothing either way — kept for
  parity in case a future table sets them.
- Query tab flipped from opt-in/off-by-default to opt-out/on-by-default,
  and its warning copy rewritten from "known broken" to "verified working",
  because the `canceronice` bucket (unlike `bioconice`'s) has a CORS policy
  from creation (#8) — see the section above.
- `recipes.js` fully replaced: bioc-on-ice's four gene/citation/ontology
  recipes don't apply to this catalog's schema. Five new recipes against
  tables live today (`geography.unit`, `measure.observation`,
  `measure.definition`/`measure.stratum` implicitly via `measure_id`/
  `stratum_id`, `provenance.release`): state screening + rurality (the
  README query), a PLACES release-to-release diff, suppressed/unavailable
  cells, a Gazetteer-vintage boundary-history showcase (Connecticut), and
  provenance. All five carry the issue #21 caveat where relevant: PLACES/
  RUCC rows tag `geo_vintage=2020` but their `geo_id`s are actually
  2026-vintage — joins name `u.vintage = 2026` explicitly rather than
  trusting `geo_vintage`.
- No genomic/ontology assumptions to remove from `app.js` — its schema
  handling (columns, business key, partition spec, snapshots, `valid_to`
  detection) is fully generic and needed no changes beyond the renames
  above.
