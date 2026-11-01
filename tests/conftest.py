import pytest

from cancerbasemap import catalog


@pytest.fixture
def cat(tmp_path, monkeypatch):
    monkeypatch.setenv("CANCERBASEMAP_WAREHOUSE", str(tmp_path))
    monkeypatch.delenv("CANCERBASEMAP_URI", raising=False)
    return catalog()
