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
log "done; removed $dir"
