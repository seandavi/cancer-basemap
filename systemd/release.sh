#!/usr/bin/env bash
# Monthly release (ADR-0001 § Cadence, #179): publish -> gate -> hf-push -> upload dry run ->
# upload --apply, stopping at the first failing step, so a bundle that fails the gate is
# never archived or uploaded. Run by cancerbasemap-release.service; by hand,
# `systemd/release.sh` from the checkout.
#
# No credentials here: publish reads the catalog anonymously, and gate, hf-push and upload
# fetch their own from GSM (project cdsci-infra) through gcloud.
#
# A re-run the same day reuses a complete bundle (publish writes manifest.json last), so
# hf-push sees the manifest already tagged. A bundle that failed the gate because of the
# data must be deleted by hand so the re-run rebuilds it.
set -euo pipefail

dir=${TMPDIR:?set TMPDIR to scratch with room for a bundle}/cancerbasemap-release-$(date -u +%F)
log() { echo "$(date -u +%FT%TZ) release: $*"; }
cb() { "$HOME/.local/bin/uv" run cancerbasemap "$@"; }

if python3 -c 'import json, sys; json.load(open(sys.argv[1]))["tables"]' "$dir/manifest.json" 2>/dev/null; then
  log "complete bundle already in $dir; not rebuilding it"
else
  log "publish -> $dir"
  rm -rf "$dir"
  cb publish "$dir"
fi
log "gate against latest/"
cb gate "$dir"
log "hf-push --apply"
cb hf-push "$dir" --apply
log "upload, dry run"
cb upload "$dir"
log "upload --apply"
cb upload "$dir" --apply
rm -rf "$dir"
log "release done; removed $dir"

# Rebuild and deploy the site, so the landing page's numbers describe the release just
# published. Built in a throwaway worktree of origin/main so the checkout stays clean
# (rendering rewrites site/_freeze/index). The docs venv lives outside $TMPDIR, which is
# cleaned weekly; the coi-docs kernel the pages name is pointed at it each run. Only
# index.qmd re-executes (quarto runs a document named on the command line even when
# frozen); every other page renders from its committed freeze.
docs=$HOME/.local/share/cancerbasemap/docs-venv
quarto=$HOME/.local/opt/quarto-1.8.25/bin/quarto
[ -x "$docs/bin/python" ] || "$HOME/.local/bin/uv" venv -q -p 3.12 "$docs"
"$HOME/.local/bin/uv" pip install -q -p "$docs" jupyter_core jupyter_client nbclient nbformat ipykernel pyyaml duckdb
"$docs/bin/python" -m ipykernel install --user --name coi-docs --display-name "Cancer Basemap docs" >/dev/null
site=${TMPDIR}/cancerbasemap-site-$(date -u +%F)
git fetch -q origin
rm -rf "$site"; git worktree prune
git worktree add -q --detach "$site" origin/main
trap 'git worktree remove --force "$site" 2>/dev/null || true' EXIT
log "render site in $site"
( cd "$site" && export QUARTO_PYTHON="$docs/bin/python" PATH="$docs/bin:$PATH" \
    && "$quarto" render site >/dev/null && "$quarto" render site/index.qmd >/dev/null )
log "deploy site"
# node/npx come from nvm, which a systemd unit's PATH does not include; use the newest.
node_bin=$(ls -d "$HOME"/.nvm/versions/node/*/bin | sort -V | tail -1)
( cd "$site/worker" && export PATH="$node_bin:$PATH" && npm ci --silent && npx wrangler deploy )
log "site deployed"
