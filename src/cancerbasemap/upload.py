"""Upload a gated bundle to R2 (ADR-0001 § Cadence, § R2, #173): `v{release}/`, then `latest/`.

Ported from biocOnIce's upload.py. Each folder gets the bundle's Parquet plus its own
views.sql, restore.sql and cancerbasemap.duckdb, regenerated for that folder's public URL,
so a pinned `v{release}/` keeps reading its own Parquet and `latest/` reads `latest/`.
gate.json and then manifest.json go last in each folder: manifest.json marks it complete.

Refused before anything is written: a bundle without a gate.json for its manifest.json, one
with a file not matching its manifest.json sha256, one whose manifest.json is not the one at its Hugging Face tag (`hf-push` runs first, so nothing
on R2 lacks a permanent copy), and a finished dated folder of other files. Afterwards `v*/`
folders are pruned by `select_keep`. latest/ loses its manifest.json before being overwritten. Dry-run unless `apply`: everything is built and listed,
nothing is written to the bucket.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from datetime import UTC, date, datetime
from pathlib import Path

from cdsci.publish import restore_sql, views_sql
# ponytail: cdsci.publish exports no public build_db yet; upload re-points the views at each
# folder's URL, so it needs the same build-before-upload trick publish uses.
from cdsci.publish.bundle import _build_db
from pyarrow import fs as pafs

from .gate import GATE_FILE
from .publish import DB_FILE

BUCKET = "data-cancerbasemap"
PUBLIC_URL = "https://basemap.cancerdatasci.org/data"
HF_REPO = "seandavis/cancerbasemap"
DATED = re.compile(r"v\d{4}-\d{2}-\d{2}")
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
    account, key, secret = (_secret(env, name) for env, name in R2_SECRETS.items())
    return pafs.S3FileSystem(access_key=key, secret_key=secret,
                             endpoint_override=f"{account}.r2.cloudflarestorage.com", region="auto")


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


def _put(fs, local, key, apply, attempts=3):
    """One file to its exact key; retried, since that is idempotent.

    R2 rejects a multipart upload whose non-trailing parts differ in length (omicidx's
    buffered `.open("wb")` hit it). pyarrow 25 sends uniform 10 MiB parts: checked against
    a request-logging stand-in, a 3.7 GB file went as 352 x 10,485,760 B plus one shorter
    trailing part, and S3's 10,000-part cap puts the ceiling near 100 GiB per file.
    """
    print(f"put    {key}  ({Path(local).stat().st_size:,} bytes)", flush=True)
    if not apply:
        return
    for attempt in range(1, attempts + 1):
        try:
            pafs.copy_files(str(local), key, source_filesystem=pafs.LocalFileSystem(),
                            destination_filesystem=fs)
            return
        except OSError as e:
            if attempt == attempts or isinstance(e, FileNotFoundError):
                raise
            print(f"  retry {attempt}/{attempts - 1} after: {e}", flush=True)
            time.sleep(10 * attempt)


def _folder(fs, root, bundle, manifest, folder, apply):
    """Upload the bundle into `root/folder/`, with its SQL, DuckDB and manifest for that URL."""
    base = f"{PUBLIC_URL}/{folder}"
    # latest/ is replaced in place: drop its manifest.json (the completeness marker) before
    # overwriting anything, so an interrupted replacement never looks complete.
    stale = f"{root}/{folder}/manifest.json"
    if folder == "latest" and fs.get_file_info(stale).type != pafs.FileType.NotFound:
        print(f"delete {stale}", flush=True)
        if apply:
            fs.delete_file(stale)
    # ponytail: latest/ gets a second upload from the local bundle, not a server-side copy
    # of v{release}/: R2 times out / 502s copying multi-GB objects (omicidx parquet_export).
    for t in manifest["tables"]:
        _put(fs, bundle / t["path"], f"{root}/{folder}/{t['path']}", apply)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        views = views_sql(manifest["tables"], base)
        (tmp / "views.sql").write_text(views)
        (tmp / "restore.sql").write_text(restore_sql(manifest["tables"], base))
        (tmp / "manifest.json").write_text(json.dumps({**manifest, "base_url": base}, indent=2) + "\n")
        shutil.copy(bundle / GATE_FILE, tmp / GATE_FILE)
        _build_db(tmp / DB_FILE, views, base, bundle)
        for name in ("views.sql", "restore.sql", DB_FILE, GATE_FILE, "manifest.json"):
            _put(fs, tmp / name, f"{root}/{folder}/{name}", apply)


def _dated(name):
    """True for `v{YYYY-MM-DD}` naming a real calendar date; anything else is never pruned."""
    try:
        return bool(DATED.fullmatch(name)) and bool(datetime.strptime(name[1:], "%Y-%m-%d"))
    except ValueError:
        return False


def select_keep(complete_folders, current, today: date):
    """The `v{date}` names to keep out of `complete_folders` (those with a manifest.json),
    `current`, being uploaded, counted.

    The newest of each of the MONTHS newest calendar months that have a release; any other
    whose same-month successor is under GRACE_DAYS old (UTC days); and `current`, always.
    """
    names = sorted({n for n in (*complete_folders, current) if _dated(n)})
    by_month: dict[str, list[str]] = {}
    for n in names:
        by_month.setdefault(n[1:8], []).append(n)
    keep = {current}
    for month in sorted(by_month, reverse=True)[:MONTHS]:
        keep.add(by_month[month][-1])
    for group in by_month.values():
        for n, successor in zip(group, group[1:]):
            if (today - date.fromisoformat(successor[1:])).days < GRACE_DAYS:
                keep.add(n)
    return keep


def _expired(fs, root, current, today):
    """`v{date}` folders under `root` to delete; `current` never is.

    Only completed folders (with a manifest.json) are retention candidates, so an interrupted
    upload never stands in for a complete release. Incomplete ones older than `current` are
    pruned outright: nothing pins them and a retry of that release would be re-uploaded whole.
    Incomplete ones newer than `current` are left alone.
    """
    names = {i.base_name for i in fs.get_file_info(pafs.FileSelector(root))
             if i.type == pafs.FileType.Directory and _dated(i.base_name)}
    complete = {n for n in names
                if fs.get_file_info(f"{root}/{n}/manifest.json").type != pafs.FileType.NotFound}
    keep = select_keep(complete, current, today)
    return sorted(n for n in names if n not in keep and (n in complete or n < current))


def _files(manifest):
    return sorted((t["path"], t.get("sha256")) for t in manifest["tables"])


def _check_gate(bundle, manifest_bytes):
    """gate.json must certify exactly these manifest.json bytes."""
    try:
        gate = json.loads((bundle / GATE_FILE).read_text())
    except FileNotFoundError:
        raise SystemExit(f"{bundle}: no {GATE_FILE}; only a bundle that passed `cancerbasemap gate` "
                         "is uploaded") from None
    if gate.get("manifest_sha256") != hashlib.sha256(manifest_bytes).hexdigest():
        raise SystemExit(f"{bundle}/{GATE_FILE} is for another manifest.json; "
                         "re-run `cancerbasemap gate` on this bundle")


def _check_files(bundle, manifest):
    """gate.json binds manifest.json, not the Parquet: rehash every file against its sha256, streamed."""
    for t in manifest["tables"]:
        with (bundle / t["path"]).open("rb") as f:
            if hashlib.file_digest(f, "sha256").hexdigest() != t["sha256"]:
                raise SystemExit(f"{bundle}/{t['path']} does not match its manifest.json "
                                 "sha256; re-publish and re-gate this bundle")


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
    manifest = json.loads(manifest_bytes)
    _check_gate(bundle, manifest_bytes)
    _check_files(bundle, manifest)
    if get_hf_manifest is not None:  # None only for a dry run (`--skip-hf-check`)
        _check_hf(manifest["release"], manifest_bytes, get_hf_manifest)
    dated = f"v{manifest['release']}"
    if not _dated(dated):
        raise SystemExit(f"manifest.json release {manifest['release']!r} is not a YYYY-MM-DD date")
    # A completed dated release (manifest.json present) is immutable: users pin it and the next
    # release is checked against it. A folder without a manifest is an interrupted upload: retry it.
    # A completed one with this bundle's exact files means latest/ was interrupted: finish only that.
    folders = (dated, "latest")
    done = f"{root}/{dated}/manifest.json"
    if fs.get_file_info(done).type != pafs.FileType.NotFound:
        with fs.open_input_stream(done) as f:
            remote = json.loads(f.read())
        if _files(remote) != _files(manifest):
            raise SystemExit(f"{root}/{dated}/ is a completed release of other files; "
                             "dated releases are never overwritten")
        print(f"{root}/{dated}/ already complete with this bundle; finishing latest/", flush=True)
        folders = ("latest",)
    for folder in folders:
        _folder(fs, root, bundle, manifest, folder, apply)
    for name in _expired(fs, root, dated, today or datetime.now(UTC).date()):
        print(f"delete {root}/{name}/", flush=True)
        if apply:
            fs.delete_dir(f"{root}/{name}")
    if not apply:
        print("dry run: nothing written; --apply to upload")
