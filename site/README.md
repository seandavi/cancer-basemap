# Cancer Basemap docs site

A [Quarto](https://quarto.org/) website: static pages plus build-time
queries against the live catalog (Dictionary, Sources, Concepts, the Home
page's map extract) and live in-browser DuckDB-WASM queries (Recipes).
Nothing here writes to the catalog.

Supersedes the throwaway prototype from #119 — that PR is not merged; this
is the real skeleton (#122).

## Set up the build-time Python kernel

Build-time chunks (`jupyter: coi-docs` in a page's front matter) run this
repo's own `cancerbasemap` package against the live catalog. Set up a small
`uv`-managed venv once, registered as a Jupyter kernel — cheaper than
compiling R's `duckdb` package, and this repo's own dependency is already
`duckdb` + `pyiceberg`, not R:

```sh
cd site
uv venv .venv-docs
uv pip install --python .venv-docs duckdb pandas ipykernel pyyaml nbformat nbclient jupyter_client  # last four: quarto's own jupyter control script needs them
uv pip install --python .venv-docs -e ..                          # `import cancerbasemap.schemas` for the Dictionary/Sources pages
.venv-docs/bin/python -m ipykernel install --user --name coi-docs --display-name "Cancer Basemap docs"
```

`.venv-docs/` is gitignored; re-run the commands above on a fresh checkout
before rendering locally. Quarto picks its Python by its own detection
(`quarto check jupyter`), which may not land on `.venv-docs` automatically —
point it there explicitly if `quarto check jupyter` doesn't already show
`coi-docs` under Kernels:

```sh
export QUARTO_PYTHON=$(pwd)/.venv-docs/bin/python   # from site/
```

## Render

```sh
cd site
quarto render .
```

`execute: { freeze: auto }` (`_quarto.yml`) means Quarto reuses each page's
*previously rendered* code output from the committed `_freeze/` directory
unless that page's source changed — so a clean render with no network access
and no `coi-docs` kernel still succeeds (this is what CI does; see below). A
page whose source did change re-executes for real, against the live
catalog, and needs the kernel above plus network access.

The Home page's map data (`site/data/home_map.json`) is a build-time side
effect, not a cached cell *output* — `freeze` doesn't reconstruct it the way
it reconstructs a Dictionary table, so `data/home_map.json` is committed to
the repo directly. Regenerate it (and the `_freeze/` entries for every page
whose numbers it feeds) with a real network render whenever the underlying
catalog changes meaningfully:

```sh
rm -rf _freeze/index _freeze/dictionary _freeze/sources* _freeze/concepts _freeze/start
quarto render .
git add data/home_map.json _freeze
```

## Preview

```sh
cd site
quarto preview .
```

Or serve the rendered output directly:

```sh
python3 -m http.server --directory _site 8000
```

## Deploy

This ships as a Cloudflare Worker with **Workers Static Assets**
(`assets.directory` pointing at `_site`), the same pattern
[`explorer/README.md`](../explorer/README.md) uses and the same account and
deploy credentials `docs/DEPLOY.md` uses for the gateway, as its own Worker
(`canceronice-docs`) so a change here never risks the gateway or the
explorer:

```sh
cd site
quarto render .
export CLOUDFLARE_API_TOKEN=$(gcloud secrets versions access latest --secret cdsci-cloudflare-workers-token --project cdsci-infra)
export CLOUDFLARE_ACCOUNT_ID=$(gcloud secrets versions access latest --secret cdsci-r2-account-id --project cdsci-infra)
npx wrangler deploy
```

First deploy creates the Worker under the name in `wrangler.jsonc` (not yet
added — see below) and serves it at
`https://canceronice-docs.<account-subdomain>.workers.dev`. **Not deployed
as part of #122** — the maintainer deploys; a custom domain and a CI deploy
step are follow-up work.

A `wrangler.jsonc` (`{"name": "canceronice-docs", "assets": {"directory": "./_site"}}`,
mirroring `explorer/wrangler.jsonc`) still needs adding here before the
command above works — deliberately left out of this PR since it isn't used
until someone actually deploys.

## CI

`.github/workflows/ci.yml` runs `quarto render site` on every push/PR. It
relies on the committed `_freeze/` cache and `data/home_map.json` above for
actual page content, so it needs no network access and no working
`duckdb`/`cancerbasemap` install. It does, however, still need a *registered*
`coi-docs` kernel — Quarto's Jupyter engine resolves a kernel by name before
it will even consult the freeze cache, confirmed to fail (even with
`--no-execute` and a fully up-to-date freeze entry) if no kernel by that
name exists. It doesn't need a *working* one: with valid freeze results, a
whole-project render never actually launches it. So the `docs` job installs
a lightweight `jupyter_core`/`jupyter_client`/`nbclient`/`ipykernel` shim
and registers `coi-docs` against it — no `duckdb`, `pandas`, or this
project's own package. If a page's `.qmd` source changes without its
`_freeze/` entry being regenerated locally first, CI will try to
re-execute it, fail (the shim kernel has none of the real dependencies),
and tell you which page needs a real local re-render.
