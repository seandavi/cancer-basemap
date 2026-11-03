"""`cancerbasemap hf-push`: a gated bundle to a stand-in for the Hugging Face API, offline (#174)."""

import json
import shutil
import sys
from types import SimpleNamespace

import duckdb
import httpx2
import pytest
from huggingface_hub.errors import RepositoryNotFoundError
from test_gate import GEO, OBSERVATION, _bundle

from cancerbasemap import gate, hf
from cancerbasemap.__main__ import main


class FakeHub:
    """The HfApi calls hf_push makes; `files` None means the repo does not exist.
    `manifests` maps a tag to the manifest.json bytes held at it."""

    def __init__(self, manifests=None, files=None, fail_tag=False):
        self.manifests, self.files, self.calls, self.fail_tag = dict(manifests or {}), files, [], fail_tag

    def create_repo(self, repo, **kw):
        self.calls.append(("create_repo", repo, kw))
        self.files = self.files if self.files is not None else [".gitattributes"]

    def _repo(self):
        if self.files is None:
            raise RepositoryNotFoundError("404", response=httpx2.Response(
                404, request=httpx2.Request("GET", "https://huggingface.co")))

    def list_repo_refs(self, repo, **kw):
        self._repo()
        return SimpleNamespace(tags=[SimpleNamespace(name=t) for t in self.manifests])

    def list_repo_files(self, repo, **kw):
        self._repo()
        return self.files

    def hf_hub_download(self, repo, filename, revision, **kw):
        self.calls.append(("hf_hub_download", repo, filename, revision))
        path = self.tmp / f"{revision}-{filename}"
        path.write_bytes(self.manifests[revision])
        return str(path)

    def create_commit(self, repo, ops, **kw):
        self.calls.append(("create_commit", repo, ops, kw))
        return SimpleNamespace(oid="abc123")

    def create_tag(self, repo, **kw):
        self.calls.append(("create_tag", repo, kw))
        if self.fail_tag:
            self.fail_tag = False
            raise OSError("tag failed")
        self.manifests[kw["tag"]] = (self.release / "manifest.json").read_bytes()


@pytest.fixture
def gated(tmp_path):
    """A 2026-11-17 bundle (not the 1st: the tag is the date, not the month) that passed the gate."""
    release = _bundle(tmp_path / "release", "2026-11-17", {
        "measure.observation": OBSERVATION.format(value="NULL"),
        "geography.unit": GEO.format(n=33)})
    m = json.loads((release / "manifest.json").read_text())
    m["provenance"] = [{"source": "places", "source_version": "2024"},
                       {"source": "acs", "source_version": "2023"}]
    (release / "manifest.json").write_text(json.dumps(m))
    assert gate.gate(release, None)
    return release


@pytest.fixture
def hub(gated, tmp_path):
    """FakeHub factory bound to the gated bundle and a scratch directory for downloads."""
    def make(**kw):
        h = FakeHub(**kw)
        h.release, h.tmp = gated, tmp_path
        return h
    return make


def test_dry_run_writes_nothing_even_before_the_repo_exists(gated, hub, capsys):
    h = hub()
    hf.hf_push(gated, h)
    assert h.calls == []
    out = capsys.readouterr().out
    assert "put    measure/observation.parquet" in out and "put    gate.json" in out
    assert "cancerbasemap.duckdb" not in out
    assert out.endswith("dry run: would push seandavis/cancerbasemap@2026-11-17; nothing written; "
                        "--apply to push\n")


def test_apply_is_one_commit_tagged_with_the_release_date(gated, hub, tmp_path, monkeypatch):
    h = hub(manifests={"2026-10-01": b"{}"}, files=[".gitattributes", "README.md", "old/dropped.parquet"])
    hf.hf_push(gated, h, apply=True)
    assert [c[0] for c in h.calls] == ["create_repo", "create_commit", "create_tag"]
    _, _, ops, _ = h.calls[1]
    added = {o.path_in_repo: o.path_or_fileobj for o in ops if hasattr(o, "path_or_fileobj")}
    assert set(added) == {"measure/observation.parquet", "geography/unit.parquet",
                          "manifest.json", "gate.json", "views.sql", "restore.sql", "README.md"}
    assert [o.path_in_repo for o in ops if o.path_in_repo not in added] == ["old/dropped.parquet"]
    assert h.calls[2][2]["tag"] == "2026-11-17" and h.calls[2][2]["revision"] == "abc123"
    card = added["README.md"].decode()
    assert "hf download seandavis/cancerbasemap --repo-type dataset --revision 2026-11-17" in card
    assert "hf://" not in card.replace("Do not query `hf://` paths in place", "")
    assert "license: other\n" in card and "Each source keeps its own terms" in card
    assert "- config_name: measure_observation\n  data_files: measure/observation.parquet" in card
    assert "| places | 2024 |" in card and "| acs | 2023 |" in card
    assert ("license_link: https://huggingface.co/datasets/seandavis/cancerbasemap/blob/2026-11-17/"
            "manifest.json\n") in card

    # The archived SQL reads the downloaded files, relative to the download directory.
    download = tmp_path / "download"
    shutil.copytree(gated, download)
    monkeypatch.chdir(download)
    con = duckdb.connect()
    con.execute(added["views.sql"].decode())
    assert con.execute("SELECT count(*) FROM geography.unit").fetchone()[0] == 33
    duckdb.connect().execute(added["restore.sql"].decode())  # errors if a row count differs from manifest


def test_a_second_run_with_the_same_manifest_is_a_no_op(gated, hub, capsys):
    h = hub(files=[".gitattributes"])
    hf.hf_push(gated, h, apply=True)
    hf.hf_push(gated, h, apply=True)
    assert [c[0] for c in h.calls] == ["create_repo", "create_commit", "create_tag",
                                       "create_repo", "hf_hub_download"]
    assert capsys.readouterr().out.endswith(
        "seandavis/cancerbasemap@2026-11-17 already exists with this manifest.json; nothing to do\n")


def test_an_existing_tag_with_another_manifest_fails(gated, hub):
    h = hub(manifests={"2026-11-17": b'{"release": "2026-11-17", "other": true}'}, files=[".gitattributes"])
    with pytest.raises(SystemExit, match="exists with a different manifest.json"):
        hf.hf_push(gated, h, apply=True)
    assert [c[0] for c in h.calls] == ["create_repo", "hf_hub_download"]


def test_a_changed_manifest_is_refused_after_its_release_was_pushed(gated, hub):
    h = hub(files=[".gitattributes"])
    hf.hf_push(gated, h, apply=True)
    m = json.loads((gated / "manifest.json").read_text())
    (gated / "manifest.json").write_text(json.dumps({**m, "git_sha": "edited"}))
    assert gate.gate(gated, None)  # re-gated: the proof matches, the tag still holds the old manifest
    with pytest.raises(SystemExit, match="exists with a different manifest.json"):
        hf.hf_push(gated, h, apply=True)


def test_an_ungated_bundle_is_refused(gated, hub):
    (gated / gate.GATE_FILE).unlink()
    h = hub()
    with pytest.raises(SystemExit, match="only a release that passed `cancerbasemap gate`"):
        hf.hf_push(gated, h, apply=True)
    assert h.calls == []


def test_a_proof_for_another_manifest_is_refused(gated, hub):
    m = json.loads((gated / "manifest.json").read_text())
    (gated / "manifest.json").write_text(json.dumps({**m, "git_sha": "edited"}))
    h = hub(files=[".gitattributes"])
    with pytest.raises(SystemExit, match="is for another manifest.json"):
        hf.hf_push(gated, h, apply=True)
    assert h.calls == []


def test_parquet_changed_after_the_gate_is_refused(gated, hub):
    (gated / "geography/unit.parquet").write_bytes(b"not the gated file")
    h = hub(files=[".gitattributes"])
    with pytest.raises(SystemExit, match="unit.parquet does not match its manifest"):
        hf.hf_push(gated, h, apply=True)
    assert [c[0] for c in h.calls] == ["create_repo"]


def test_a_failed_tag_is_retried_by_the_next_run(gated, hub):
    h = hub(files=[".gitattributes"], fail_tag=True)
    with pytest.raises(OSError, match="tag failed"):
        hf.hf_push(gated, h, apply=True)
    hf.hf_push(gated, h, apply=True)  # no tag yet: commit again (a no-op on the Hub), then tag
    assert [c[0] for c in h.calls] == ["create_repo", "create_commit", "create_tag"] * 2
    assert list(h.manifests) == ["2026-11-17"]


def test_cli_dry_run(gated, hub, monkeypatch, capsys):
    h = hub()
    monkeypatch.setattr(hf, "hf_token", lambda: "token")
    monkeypatch.setattr("huggingface_hub.HfApi", lambda token: h)
    monkeypatch.setattr(sys, "argv", ["cancerbasemap", "hf-push", str(gated), "--repo", "me/scratch"])
    main()
    assert h.calls == [] and "dry run: would push me/scratch@2026-11-17" in capsys.readouterr().out


def _hub_error(status):
    from huggingface_hub.errors import HfHubHTTPError
    req = httpx2.Request("POST", "https://huggingface.co/api/datasets/x/tag/abc123")
    return HfHubHTTPError(f"{status}", response=httpx2.Response(status, request=req))


def test_a_409_on_the_tag_right_after_the_commit_is_retried(gated, hub, monkeypatch):
    """The Hub answered 409 to the tag of a commit it had just made (scheduled release
    2026-11-03); the same call succeeded a minute later."""
    h = hub()
    tag = h.create_tag
    fails = [_hub_error(409), _hub_error(409)]

    def flaky(repo, **kw):
        if fails:
            h.calls.append(("create_tag", repo, kw))
            raise fails.pop(0)
        return tag(repo, **kw)

    h.create_tag = flaky
    monkeypatch.setattr(hf, "TAG_WAIT_S", 0)
    hf.hf_push(gated, h, apply=True)
    assert [c[0] for c in h.calls] == ["create_repo", "create_commit"] + ["create_tag"] * 3
    assert "2026-11-17" in h.manifests


def test_other_tag_errors_are_not_retried(gated, hub, monkeypatch):
    h = hub()

    def denied(repo, **kw):
        h.calls.append(("create_tag", repo, kw))
        raise _hub_error(403)

    h.create_tag = denied
    monkeypatch.setattr(hf, "TAG_WAIT_S", 0)
    with pytest.raises(Exception):
        hf.hf_push(gated, h, apply=True)
    assert [c[0] for c in h.calls].count("create_tag") == 1
