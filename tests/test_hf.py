"""`cancerbasemap hf-push`: the cancer policy on top of cdsci.publish.hf, against a stand-in
for the Hugging Face API, offline (#174).

The mechanics (one commit, deletes, the tag no-op / conflict rules, sha256 re-hash) are
tested in cdsci-lake; this covers the gate proof, the tag (the release date), what is pushed
and the card.
"""

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

    def __init__(self, manifests=None, files=None):
        self.manifests, self.files, self.calls = dict(manifests or {}), files, []

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
    _, _, ops, kw = h.calls[1]
    assert kw["commit_message"] == "Cancer Basemap release 2026-11-17"
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
    passed_at = json.loads((gated / gate.GATE_FILE).read_text())["passed_at"]
    assert f"| Gate passed at | {passed_at} |" in card

    # The archived SQL reads the downloaded files, relative to the download directory.
    download = tmp_path / "download"
    shutil.copytree(gated, download)
    monkeypatch.chdir(download)
    con = duckdb.connect()
    con.execute(added["views.sql"].decode())
    assert con.execute("SELECT count(*) FROM geography.unit").fetchone()[0] == 33
    duckdb.connect().execute(added["restore.sql"].decode())  # errors if a row count differs from manifest


def test_an_ungated_bundle_is_refused(gated, hub):
    (gated / gate.GATE_FILE).unlink()
    h = hub()
    with pytest.raises(SystemExit, match="no gate.json; only a bundle that passed the gate"):
        hf.hf_push(gated, h, apply=True)
    assert h.calls == []


def test_a_proof_for_another_manifest_is_refused(gated, hub):
    m = json.loads((gated / "manifest.json").read_text())
    (gated / "manifest.json").write_text(json.dumps({**m, "git_sha": "edited"}))
    h = hub(files=[".gitattributes"])
    with pytest.raises(SystemExit, match="is for another manifest.json"):
        hf.hf_push(gated, h, apply=True)
    assert h.calls == []


def test_cli_dry_run(gated, hub, monkeypatch, capsys):
    h = hub()
    monkeypatch.setattr(hf, "hf_token", lambda: "token")
    monkeypatch.setattr("huggingface_hub.HfApi", lambda token: h)
    monkeypatch.setattr(sys, "argv", ["cancerbasemap", "hf-push", str(gated), "--repo", "me/scratch"])
    main()
    assert h.calls == [] and "dry run: would push me/scratch@2026-11-17" in capsys.readouterr().out
