"""Upload a gated bundle to R2 (ADR-0001 § Cadence, § R2, #173): `v{release}/`, then `latest/`.

Ported from biocOnIce's upload.py. Each folder gets the bundle's Parquet plus its own
views.sql, restore.sql and cancerbasemap.duckdb, regenerated for that folder's public URL,
so a pinned `v{release}/` keeps reading its own Parquet and `latest/` reads `latest/`.
gate.json and then manifest.json go last in each folder: manifest.json marks it complete.

Refused before anything is written: a bundle without a gate.json for its manifest.json, one
whose manifest.json is not the one at its Hugging Face tag (`hf-push` runs first, so nothing
on R2 lacks a permanent copy), and a finished dated folder of other files. Afterwards `v*/`
folders are pruned by `select_keep`. Dry-run unless `apply`: everything is built and listed,
nothing is written to the bucket.
"""

import hashlib
import json
import re
import shutil
import tempfile
import time
from datetime import UTC, date, datetime
from pathlib import Path

from pyarrow import fs as pafs

from . import publish
from .gate import GATE_FILE

BUCKET = "data-cancerbasemap"
PUBLIC_URL = "https://basemap.cancerdatasci.org/data"
HF_REPO = "seandavis/cancerbasemap"
DATED = re.compile(r"v\d{4}-\d{2}-\d{2}")
MONTHS = 12  # calendar months of releases kept (ADR-0001 § R2)
GRACE_DAYS = 7  # a replaced release stays this long after its same-month successor


def r2_filesystem():
    """pyarrow's S3 client on the cdsci R2 account, credentials as cdsci-lake resolves them.

    Each of CU_OPENALEX_R2_ACCOUNT_ID / _R2_ACCESS_KEY_ID / _R2_SECRET_ACCESS_KEY (env or
    .env) if set, else its cdsci-r2-* secret in GSM project cdsci-infra.
    """
    from cdsci.lake.config import get_settings
    from cdsci.lake.secrets import get_secret

    s = get_settings()
    account = s.r2_account_id or get_secret(s.r2_account_id_secret, s.gsm_project)
    return pafs.S3FileSystem(
        access_key=s.r2_access_key_id or get_secret(s.r2_access_key_secret, s.gsm_project),
        secret_key=s.r2_secret_access_key or get_secret(s.r2_secret_key_secret, s.gsm_project),
        endpoint_override=f"{account}.r2.cloudflarestorage.com", region="auto")


def hf_manifest(release):
    """manifest.json bytes at the Hugging Face tag `release`, or None when the tag does not exist."""
    from huggingface_hub import hf_hub_download
    from huggingface_hub.errors import EntryNotFoundError, RepositoryNotFoundError, RevisionNotFoundError

    try:
        return Path(hf_hub_download(HF_REPO, "manifest.json", repo_type="dataset",
                                    revision=release)).read_bytes()
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
    # ponytail: latest/ gets a second upload from the local bundle, not a server-side copy
    # of v{release}/: R2 times out / 502s copying multi-GB objects (omicidx parquet_export).
    for t in manifest["tables"]:
        _put(fs, bundle / t["path"], f"{root}/{folder}/{t['path']}", apply)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        views = publish.views_sql(manifest["tables"], base)
        (tmp / "views.sql").write_text(views)
        (tmp / "restore.sql").write_text(publish.restore_sql(manifest["tables"], base))
        (tmp / "manifest.json").write_text(json.dumps({**manifest, "base_url": base}, indent=2) + "\n")
        shutil.copy(bundle / GATE_FILE, tmp / GATE_FILE)
        publish._build_db(tmp / publish.DB_FILE, views, base, bundle)
        for name in ("views.sql", "restore.sql", publish.DB_FILE, GATE_FILE, "manifest.json"):
            _put(fs, tmp / name, f"{root}/{folder}/{name}", apply)


def _dated(name):
    """True for `v{YYYY-MM-DD}` naming a real calendar date; anything else is never pruned."""
    try:
        return bool(DATED.fullmatch(name)) and bool(datetime.strptime(name[1:], "%Y-%m-%d"))
    except ValueError:
        return False


def select_keep(dated_folders, current, today: date):
    """The `v{date}` names to keep out of `dated_folders` (`current`, being uploaded, counted).

    The newest of each of the MONTHS newest calendar months that have a release; any other
    whose same-month successor is under GRACE_DAYS old (UTC days); and `current`, always.
    """
    names = sorted({n for n in (*dated_folders, current) if _dated(n)})
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
    """`v{date}` folders under `root` that `select_keep` does not keep; `current` never is."""
    names = {i.base_name for i in fs.get_file_info(pafs.FileSelector(root))
             if i.type == pafs.FileType.Directory}
    return sorted(n for n in names if _dated(n) and n not in select_keep(names, current, today))


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
