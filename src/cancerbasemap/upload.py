"""Upload a gated bundle to R2 (ADR-0001 § Cadence, § R2, #173): `v{release}/`, then `latest/`.

The mechanics are `cdsci.publish.upload`, shared with biocOnIce (cdsci-lake ADR-0027): each
folder gets the bundle's Parquet plus its own views.sql, restore.sql and cancerbasemap.duckdb
for that folder's URL, gate.json and then manifest.json last; every Parquet is re-hashed
against its manifest sha256 first; a finished dated folder of other files is never
overwritten; latest/ loses its manifest.json before being overwritten; afterwards complete
`v*/` folders the retention rule does not keep are pruned. Dry run unless `apply`.

This module is the cancer policy: the bucket and its public URL, the retention rule (the
newest release of each of the 12 newest months, plus a 7-day grace for a replaced release),
the R2 credentials from GSM, and what must hold before anything is written: a gate.json for
this manifest.json (`check_proof`), and that manifest.json already at the bundle's Hugging
Face tag (`hf-push` runs first, so nothing on R2 lacks a permanent copy).
"""

import json
import os
import subprocess
from pathlib import Path

import cdsci.publish.upload
from cdsci.publish.gate import GATE_FILE, check_proof
from cdsci.publish.upload import keep_monthly

from .publish import DB_FILE

BUCKET = "data-cancerbasemap"
PUBLIC_URL = "https://basemap.cancerdatasci.org/data"
HF_REPO = "seandavis/cancerbasemap"
MONTHS = 12  # calendar months of releases kept (ADR-0001 § R2)
GRACE_DAYS = 7  # a replaced release stays this long after its same-month successor
PROJECT = "cdsci-infra"
# R2 credentials, as biocOnIce's: env var if set, else this GSM secret in PROJECT.
R2_SECRETS = {"CU_OPENALEX_R2_ACCOUNT_ID": "cdsci-r2-account-id",
              "CU_OPENALEX_R2_ACCESS_KEY_ID": "cdsci-r2-access-key-id",
              "CU_OPENALEX_R2_SECRET_ACCESS_KEY": "cdsci-r2-secret-access-key"}


def _secret(env, name):
    """The env var `env` if set, else GSM secret `name` in PROJECT (via gcloud). Never printed."""
    return os.environ.get(env) or subprocess.run(
        ["gcloud", "secrets", "versions", "access", "latest", f"--secret={name}",
         f"--project={PROJECT}"], capture_output=True, text=True, check=True).stdout.strip()


def r2_filesystem():
    """pyarrow's S3 client on the cdsci R2 account (credentials as `_secret` resolves them)."""
    return cdsci.publish.upload.r2_filesystem(*(_secret(env, name) for env, name in R2_SECRETS.items()))


def hf_manifest(release):
    """manifest.json bytes at the Hugging Face tag `release`, or None when the tag does not exist.

    Always fetched from the Hub, never from the local cache: an unreachable Hub refuses the upload.
    """
    from huggingface_hub import hf_hub_download
    from huggingface_hub.errors import (EntryNotFoundError, LocalEntryNotFoundError,
                                        RepositoryNotFoundError, RevisionNotFoundError)

    try:
        return Path(hf_hub_download(HF_REPO, "manifest.json", repo_type="dataset",
                                    revision=release, force_download=True)).read_bytes()
    # LocalEntryNotFoundError subclasses EntryNotFoundError, and a failed forced download is a
    # ValueError: both mean no network, not no tag.
    except (LocalEntryNotFoundError, ValueError) as e:
        raise SystemExit(f"cannot reach Hugging Face to check {HF_REPO}@{release}: {e}") from e
    except (EntryNotFoundError, RepositoryNotFoundError, RevisionNotFoundError):
        return None


def _check_hf(release, manifest_bytes, get_hf_manifest):
    """The Hugging Face tag `release` must hold this bundle's manifest.json, byte for byte."""
    remote = get_hf_manifest(release)
    if remote is None:
        raise SystemExit(f"{HF_REPO} has no tag {release}; run hf-push first")
    if remote != manifest_bytes:
        raise SystemExit(f"{HF_REPO}@{release} holds a different manifest.json than this bundle; "
                         "not uploading")


def upload(bundle: Path, fs, root=BUCKET, apply=False, today=None, get_hf_manifest=hf_manifest):
    """Upload `bundle` (a gated `cancerbasemap publish` directory) to `v{release}/` and `latest/`, then prune.

    `get_hf_manifest(release)` returns the manifest.json bytes at that Hugging Face tag, or None.
    """
    manifest_bytes = (bundle / "manifest.json").read_bytes()
    check_proof(bundle)
    if get_hf_manifest is not None:  # None only for a dry run (`--skip-hf-check`)
        _check_hf(json.loads(manifest_bytes)["release"], manifest_bytes, get_hf_manifest)
    cdsci.publish.upload.upload(bundle, fs, root, public_url=PUBLIC_URL, db_file=DB_FILE,
                                retention=keep_monthly(MONTHS, GRACE_DAYS), apply=apply,
                                extra_files=(GATE_FILE,), today=today)
