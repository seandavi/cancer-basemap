"""`cancerbasemap upload`: a gated bundle into a local directory standing in for the R2 bucket, offline (#173)."""

import hashlib
import json
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
             "row_count": 1, "comment": None, "columns": [], "sha256": str(gene_id)}
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


def test_dry_run_writes_nothing_and_lists_puts_and_deletes(tmp_path, capsys):
    bucket, bundle = _bucket(tmp_path), _bundle(tmp_path)
    before = _snapshot(bucket)
    upload.upload(bundle, BUCKET_FS, str(bucket), today=TODAY, get_hf_manifest=on_hf(bundle))

    assert _snapshot(bucket) == before
    out = capsys.readouterr().out
    assert out.count("put ") == 12  # 6 files x (dated, latest)
    assert "dry run" in out


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


def test_a_completed_dated_release_of_other_files_is_never_overwritten(tmp_path):
    bucket, bundle = _bucket(tmp_path), _bundle(tmp_path)
    (bucket / f"v{RELEASE}").mkdir()
    other = {"release": RELEASE, "tables": [{"path": "annotation/gene.parquet", "sha256": "other"}]}
    (bucket / f"v{RELEASE}" / "manifest.json").write_text(json.dumps(other))
    with pytest.raises(SystemExit, match="completed release of other files"):
        upload.upload(bundle, BUCKET_FS, str(bucket), apply=True, today=TODAY, get_hf_manifest=on_hf(bundle))
    assert json.loads((bucket / f"v{RELEASE}" / "manifest.json").read_text()) == other
    assert not (bucket / "latest" / "views.sql").exists()


def test_an_interrupted_latest_upload_is_finished(tmp_path, capsys, monkeypatch):
    bucket, bundle = _bucket(tmp_path), _bundle(tmp_path)
    real = upload._folder

    def fail_on_latest(fs, root, bundle, manifest, folder, apply):
        if folder == "latest":
            raise OSError("connection reset")
        real(fs, root, bundle, manifest, folder, apply)
    monkeypatch.setattr(upload, "_folder", fail_on_latest)
    with pytest.raises(OSError):
        upload.upload(bundle, BUCKET_FS, str(bucket), apply=True, today=TODAY, get_hf_manifest=on_hf(bundle))
    monkeypatch.setattr(upload, "_folder", real)
    dated = (bucket / f"v{RELEASE}" / "manifest.json").read_text()
    capsys.readouterr()

    upload.upload(bundle, BUCKET_FS, str(bucket), apply=True, today=TODAY, get_hf_manifest=on_hf(bundle))
    assert (bucket / f"v{RELEASE}" / "manifest.json").read_text() == dated
    assert json.loads((bucket / "latest" / "manifest.json").read_text())["release"] == RELEASE
    assert f"/v{RELEASE}/" not in "".join(ln for ln in capsys.readouterr().out.splitlines()
                                           if ln.startswith("put"))


def test_prune_follows_the_retention_rule_and_leaves_latest_and_non_dates(tmp_path):
    bucket, bundle = _bucket(tmp_path), _bundle(tmp_path)
    for d in ("v2025-10-15", "v2025-10-20"):  # a month's release and its correction, long past
        (bucket / d).mkdir()
    upload.upload(bundle, BUCKET_FS, str(bucket), apply=True, today=TODAY, get_hf_manifest=on_hf(bundle))
    assert sorted(p.name for p in bucket.iterdir()) == [
        "latest", "v2025-10-20", "v2026-09-01", "v2026-10-04", "v2026-10-29",
        f"v{RELEASE}", "vnotadate"]  # 10-04: its successor 10-29 is 3 days old


def _keep(names, current, today):
    return upload.select_keep(names, current, date.fromisoformat(today))


def test_select_keep_newest_of_each_month_and_a_month_with_no_release_is_skipped():
    # no April, no May: the window still reaches back 12 months that have a release
    names = ["v2026-01-10", "v2026-01-20", "v2026-03-05", "v2026-06-30"]
    assert _keep(names, "v2026-06-30", "2026-07-30") == {"v2026-01-20", "v2026-03-05", "v2026-06-30"}


def test_select_keep_two_corrections_in_one_month_keep_only_the_newest_once_grace_has_passed():
    names = ["v2026-05-01", "v2026-05-10", "v2026-05-20"]
    assert _keep(names, "v2026-05-20", "2026-06-20") == {"v2026-05-20"}


@pytest.mark.parametrize("today, kept", [
    ("2026-05-16", {"v2026-05-01", "v2026-05-10"}),  # successor 6 days old: pinned release stays
    ("2026-05-17", {"v2026-05-10"}),  # successor 7 days old: it goes
])
def test_select_keep_successor_six_vs_seven_days_old(today, kept):
    assert _keep(["v2026-05-01", "v2026-05-10"], "v2026-05-10", today) == kept


def test_select_keep_grace_chains_through_corrections():
    # 05-12 replaced 05-10 4 days ago; 05-10 replaced 05-01 2 days before that: all three held
    assert _keep(["v2026-05-01", "v2026-05-10", "v2026-05-12"], "v2026-05-12", "2026-05-16") == {
        "v2026-05-01", "v2026-05-10", "v2026-05-12"}


def test_select_keep_year_boundary_counts_calendar_months():
    names = ["v2025-12-31", "v2026-01-01", "v2026-02-01"]
    assert _keep(names, "v2026-02-01", "2026-03-01") == set(names)  # Dec and Jan are different months


def test_select_keep_thirteen_months_prunes_the_oldest():
    names = [f"v2025-{m:02d}-01" for m in range(10, 13)] + [f"v2026-{m:02d}-01" for m in range(1, 11)]
    keep = _keep(names, "v2026-10-01", "2026-10-01")
    assert len(names) == 13 and keep == set(names) - {"v2025-10-01"}


def test_select_keep_never_prunes_the_folder_being_uploaded_even_if_older():
    names = ["v2026-05-01", "v2026-06-01"]
    assert "v2026-05-01" in _keep(names, "v2026-05-01", "2027-06-01")


def test_select_keep_ignores_names_that_are_not_real_dates():
    names = ["v2026-02-30", "vnotadate", "latest", "v2026-05-01"]
    assert _keep(names, "v2026-05-01", "2026-06-01") == {"v2026-05-01"}
