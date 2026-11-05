"""`cancerbasemap upload`: the cancer policy on top of cdsci.publish.upload, into a local
directory standing in for the R2 bucket, offline (#173).

The mechanics (folder layout, interrupted uploads, sha256 re-hash, pruning) and `keep_monthly`
are tested in cdsci-lake; this covers the pre-upload checks (gate proof, Hugging Face tag), the
bucket parameters, the retention rule as configured, and the credentials.
"""

import hashlib
import json
import os
import subprocess
import sys
from datetime import date

import duckdb
import pytest
from fsspec.implementations.local import LocalFileSystem
from pyarrow import fs as pafs

from cancerbasemap import gate, publish, upload

RELEASE = "2026-11-01"
TODAY = date.fromisoformat(RELEASE)
# Like S3, writes a key without its parent "directory" existing first.
BUCKET_FS = pafs.PyFileSystem(pafs.FSSpecHandler(LocalFileSystem(auto_mkdir=True)))


def _bundle(tmp_path, release=RELEASE, gene_id=1, gated=True):
    out = tmp_path / f"release-{release}"
    (out / "annotation").mkdir(parents=True)
    duckdb.sql(f"COPY (SELECT {gene_id} AS gene_id) TO '{out}/annotation/gene.parquet' (FORMAT parquet)")
    table = {"schema": "annotation", "table": "gene", "path": "annotation/gene.parquet",
             "row_count": 1, "comment": None, "columns": [],
             "sha256": hashlib.sha256((out / "annotation/gene.parquet").read_bytes()).hexdigest()}
    manifest = json.dumps({"release": release, "base_url": "https://example.org/x", "tables": [table]})
    (out / "manifest.json").write_text(manifest)
    if gated:
        (out / gate.GATE_FILE).write_text(json.dumps(
            {"release": release, "manifest_sha256": hashlib.sha256(manifest.encode()).hexdigest()}))
    return out


def on_hf(bundle):
    """A Hugging Face stand-in holding this bundle's manifest.json at its tag."""
    return lambda release: (bundle / "manifest.json").read_bytes()


def _bucket(tmp_path):
    bucket = tmp_path / "bucket"
    for d in ("v2026-09-01", "v2026-10-04", "v2026-10-29", "vnotadate", "latest"):
        (bucket / d).mkdir(parents=True)
        (bucket / d / "manifest.json").write_text("{}")
    return bucket


def _snapshot(bucket):
    return sorted(p.relative_to(bucket) for p in bucket.rglob("*"))


def test_each_folder_reads_its_own_parquet_with_gate_json_and_manifest_last(tmp_path, capsys):
    bucket, bundle = _bucket(tmp_path), _bundle(tmp_path)
    upload.upload(bundle, BUCKET_FS, str(bucket), apply=True, today=TODAY, get_hf_manifest=on_hf(bundle))

    for folder in (f"v{RELEASE}", "latest"):
        url = f"{upload.PUBLIC_URL}/{folder}/annotation/gene.parquet"
        assert f"read_parquet('{url}')" in (bucket / folder / "views.sql").read_text()
        assert f"read_parquet('{url}')" in (bucket / folder / "restore.sql").read_text()
        db = duckdb.connect(str(bucket / folder / publish.DB_FILE), read_only=True)
        assert url in db.sql("SELECT sql FROM duckdb_views() WHERE view_name = 'gene'").fetchone()[0]
        m = json.loads((bucket / folder / "manifest.json").read_text())
        assert m["base_url"] == f"{upload.PUBLIC_URL}/{folder}" and m["release"] == RELEASE
        assert (bucket / folder / gate.GATE_FILE).read_bytes() == (bundle / gate.GATE_FILE).read_bytes()
        assert (bucket / folder / "annotation/gene.parquet").exists()

    puts = [line.split()[1] for line in capsys.readouterr().out.splitlines() if line.startswith("put")]
    assert puts[4:6] == [f"{bucket}/v{RELEASE}/gate.json", f"{bucket}/v{RELEASE}/manifest.json"]
    assert puts[-2:] == [f"{bucket}/latest/gate.json", f"{bucket}/latest/manifest.json"]
    assert all("/latest/" not in p for p in puts[:6]) and all("/latest/" in p for p in puts[6:])


def test_a_bundle_without_a_matching_gate_json_is_refused_before_the_bucket(tmp_path, capsys):
    bucket = _bucket(tmp_path)
    before = _snapshot(bucket)
    ungated = _bundle(tmp_path, gated=False)
    with pytest.raises(SystemExit, match="no gate.json"):
        upload.upload(ungated, BUCKET_FS, str(bucket), apply=True, today=TODAY, get_hf_manifest=on_hf(ungated))

    stale = _bundle(tmp_path / "other")
    (stale / "manifest.json").write_text((stale / "manifest.json").read_text() + " ")
    with pytest.raises(SystemExit, match="gate.json is for another manifest.json"):
        upload.upload(stale, BUCKET_FS, str(bucket), apply=True, today=TODAY, get_hf_manifest=on_hf(stale))
    assert _snapshot(bucket) == before and capsys.readouterr().out == ""


def test_a_bundle_not_at_its_hugging_face_tag_is_refused(tmp_path, capsys):
    bucket, bundle = _bucket(tmp_path), _bundle(tmp_path)
    before = _snapshot(bucket)
    asked = []

    def no_tag(release):
        asked.append(release)

    with pytest.raises(SystemExit, match="no tag 2026-11-01; run hf-push first"):
        upload.upload(bundle, BUCKET_FS, str(bucket), apply=True, today=TODAY, get_hf_manifest=no_tag)
    assert asked == [RELEASE]

    with pytest.raises(SystemExit, match="holds a different manifest.json"):
        upload.upload(bundle, BUCKET_FS, str(bucket), apply=True, today=TODAY,
                      get_hf_manifest=lambda release: b'{"release": "2026-11-01"}')
    assert _snapshot(bucket) == before and capsys.readouterr().out == ""


def test_prune_follows_the_retention_rule_and_leaves_latest_and_non_dates(tmp_path):
    bucket, bundle = _bucket(tmp_path), _bundle(tmp_path)
    for d in ("v2025-10-15", "v2025-10-20"):  # a month's release and its correction, long past
        (bucket / d).mkdir()
        (bucket / d / "manifest.json").write_text("{}")
    upload.upload(bundle, BUCKET_FS, str(bucket), apply=True, today=TODAY, get_hf_manifest=on_hf(bundle))
    assert sorted(p.name for p in bucket.iterdir()) == [
        "latest", "v2025-10-20", "v2026-09-01", "v2026-10-04", "v2026-10-29",
        f"v{RELEASE}", "vnotadate"]  # 10-04: its successor 10-29 is 3 days old


def test_r2_credentials_come_from_env_else_gcloud_and_are_never_printed(monkeypatch, capsys):
    calls = []

    def gcloud(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="from-gsm\n")
    monkeypatch.setattr(upload.subprocess, "run", gcloud)
    monkeypatch.setenv("CU_OPENALEX_R2_ACCESS_KEY_ID", "from-env")
    monkeypatch.delenv("CU_OPENALEX_R2_ACCOUNT_ID", raising=False)
    monkeypatch.delenv("CU_OPENALEX_R2_SECRET_ACCESS_KEY", raising=False)
    upload.r2_filesystem()
    assert [c[5] for c in calls] == ["--secret=cdsci-r2-account-id", "--secret=cdsci-r2-secret-access-key"]
    assert all(c[-1] == "--project=cdsci-infra" for c in calls)
    out = capsys.readouterr()
    assert "from-gsm" not in out.out + out.err and "from-env" not in out.out + out.err


@pytest.mark.parametrize("force", [True, False])
def test_an_unreachable_hugging_face_refuses_even_with_a_cached_manifest(tmp_path, force):
    # A subprocess, since huggingface_hub reads HF_ENDPOINT / HF_HUB_CACHE at import. Without
    # force_download the cached copy is returned (force=False shows the cache is really hit).
    snap = tmp_path / "cache" / "datasets--seandavis--cancerbasemap"
    (snap / "snapshots" / "abc").mkdir(parents=True)
    (snap / "snapshots" / "abc" / "manifest.json").write_text("cached")
    (snap / "refs").mkdir()
    (snap / "refs" / RELEASE).write_text("abc")
    fetch = ("upload.hf_manifest" if force else
             "lambda r: hf_hub_download(upload.HF_REPO, 'manifest.json', repo_type='dataset', revision=r)")
    code = ("from huggingface_hub import hf_hub_download\nfrom cancerbasemap import upload\n"
            f"print(({fetch})('{RELEASE}'))")
    env = {**os.environ, "HF_ENDPOINT": "http://127.0.0.1:9", "HF_HUB_CACHE": str(tmp_path / "cache")}
    r = subprocess.run([sys.executable, "-I", "-c", code], env=env, capture_output=True, text=True)
    if force:
        assert r.returncode != 0 and "cannot reach Hugging Face" in r.stderr and "cached" not in r.stdout
    else:
        assert r.returncode == 0 and "snapshots/abc/manifest.json" in r.stdout
