"""measure.cancer_site_group: land the curated grouping CSV whole -> derive
measure.cancer_site_group, checked against already-landed measure.cancer_site
codes.

The CSV under test for the real-data assertions is the real packaged file
(src/cancerbasemap/data/cancer_site_groups.csv), the same way test_geography_alias.py
uses the real county_recodes.csv -- it IS the review artifact for #126. A tiny
fixture (tests/tiny_cancer_site_groups.csv) exercises the mechanics against a
small, fast measure.cancer_site built from the existing cancer_site fixtures.
"""

from pathlib import Path

import pyarrow as pa
import pytest
from pyiceberg.expressions import EqualTo

from cancerbasemap import cancer_site, cancer_site_group, merge

REL = "2026.09"
SITE_TXT = str(Path(__file__).parent / "tiny_seer_site_recode.txt")
COD_TXT = str(Path(__file__).parent / "tiny_seer_cod_recode.txt")
ONTOLOGY_CSV = str(Path(__file__).parent / "tiny_cancer_site_ontology.csv")
GROUPS_CSV = str(Path(__file__).parent / "tiny_cancer_site_groups.csv")


def rows(cat, identifier, **kw):
    return cat.load_table(identifier).scan(**kw).to_arrow().to_pylist()


def _land_cancer_site(cat):
    """The tiny cancer_site fixture already used by test_cancer_site.py --
    cancer_site_group is checked against it (#126's memberships are FKs into
    measure.cancer_site)."""
    cancer_site.ingest(cat, REL, site_url=SITE_TXT, cod_url=COD_TXT, ontology_csv=ONTOLOGY_CSV)


def test_raw_is_verbatim_and_whole(cat):
    _land_cancer_site(cat)
    n = cancer_site_group.land_raw(cat, REL, path=GROUPS_CSV)
    assert n == 3

    raw = rows(cat, "raw.canceronice__cancer_site_group")
    assert len(raw) == 3
    assert {r["group_id"] for r in raw} == {"test_group_a", "test_group_b"}
    assert {r["landed_in"] for r in raw} == {REL}

    # re-landing replaces wholesale (no version axis to accumulate on)
    cancer_site_group.land_raw(cat, REL, path=GROUPS_CSV)
    assert len(rows(cat, "raw.canceronice__cancer_site_group")) == 3


def test_a_changed_header_fails_before_landing(cat, tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("group_id,group_label,cancer_site_code,mapping_relation,basis,url,note\n"
                   "g,G,21010,exact,x,y,\n")
    with pytest.raises(SystemExit, match="source_url"):
        cancer_site_group.land_raw(cat, REL, path=str(bad))


def test_derives_one_group_row_per_membership(cat):
    _land_cancer_site(cat)
    counts = cancer_site_group.ingest(cat, REL, path=GROUPS_CSV)
    assert counts["raw.canceronice__cancer_site_group"] == 3

    group = {(r["group_id"], r["cancer_site_code"]): r for r in rows(cat, "measure.cancer_site_group")}
    assert set(group) == {
        ("test_group_a", "21010"), ("test_group_a", "21041"), ("test_group_b", "34000"),
    }

    esophagus = group[("test_group_a", "21010")]
    assert esophagus["mapping_relation"] == "exact"
    assert esophagus["group_label"] == "Test Group A"
    assert esophagus["source"] == "CANCERONICE"
    assert esophagus["basis"]  # a citation, not blank
    assert esophagus["source_url"] == "http://example.org/a"

    cecum = group[("test_group_a", "21041")]
    assert cecum["mapping_relation"] == "broader"
    assert cecum["note"]  # broader mapping carries an explanatory note


def test_an_unknown_relation_fails_loudly(cat, tmp_path):
    _land_cancer_site(cat)
    bad = tmp_path / "bad.csv"
    bad.write_text("group_id,group_label,cancer_site_code,mapping_relation,basis,source_url,note\n"
                   "g,G,21010,similar,x,http://x,\n")
    cancer_site_group.land_raw(cat, REL, path=str(bad))
    with pytest.raises(SystemExit, match="similar"):
        cancer_site_group.transform(cat, REL)


def test_an_unknown_cancer_site_code_is_a_hard_stop(cat, tmp_path):
    """#126's memberships must resolve to a real measure.cancer_site row --
    never a typo landing an orphan FK."""
    _land_cancer_site(cat)
    bad = tmp_path / "bad.csv"
    bad.write_text("group_id,group_label,cancer_site_code,mapping_relation,basis,source_url,note\n"
                   "g,G,99998,exact,x,http://x,\n")
    cancer_site_group.land_raw(cat, REL, path=str(bad))
    with pytest.raises(SystemExit, match="99998"):
        cancer_site_group.transform(cat, REL)


def test_rerun_is_idempotent(cat):
    _land_cancer_site(cat)
    cancer_site_group.ingest(cat, REL, path=GROUPS_CSV)
    counts = cancer_site_group.ingest(cat, "2026.10", path=GROUPS_CSV)
    assert counts["measure.cancer_site_group"]["written"] == 0
    assert counts["measure.cancer_site_group"]["unchanged"] == 3


def other_group_row():
    return dict(group_id="other_group", group_label="Other Group", cancer_site_code="21010",
               mapping_relation="exact", basis="x", source_url="http://x", note=None,
               source="OTHER")


def test_does_not_retire_another_writer(cat):
    """measure.cancer_site_group's merge scope is `source`, so a second
    curator/source of groupings could stack here without retiring this one's
    rows."""
    _land_cancer_site(cat)
    other = pa.Table.from_pylist([other_group_row()])
    merge.merge(cat, "measure.cancer_site_group", other, REL, EqualTo("source", "OTHER"))

    cancer_site_group.ingest(cat, REL, path=GROUPS_CSV)
    cancer_site_group.ingest(cat, "2026.10", path=GROUPS_CSV)

    live_other = rows(cat, "measure.cancer_site_group",
                      row_filter="source = 'OTHER' AND valid_to IS NULL")
    assert len(live_other) == 1
    assert live_other[0]["valid_from"] == REL


def test_every_column_is_documented(cat):
    _land_cancer_site(cat)
    cancer_site_group.ingest(cat, REL, path=GROUPS_CSV)
    for identifier in ("raw.canceronice__cancer_site_group", "measure.cancer_site_group"):
        table = cat.load_table(identifier)
        assert table.properties.get("comment")
        for f in table.schema().fields:
            assert f.doc, f"{identifier}.{f.name} has no doc"


def test_real_curated_csv_covers_every_declared_group(cat):
    """The real packaged CSV (not the tiny fixture): every group named in
    the issue is present, every mapping_relation is valid, and every row
    resolves against the real cancer_site.py fixture-free ingest is left to
    a manual end-to-end run (SPEC.md/AGENTS.md: tests stay offline) -- this
    only checks the CSV's own internal shape."""
    from cancerbasemap import cancer_site_group as m
    import csv as csv_module
    with open(m.DATA_FILE, newline="") as f:
        real_rows = list(csv_module.DictReader(f))
    assert len(real_rows) > 100
    groups = {r["group_id"] for r in real_rows}
    assert groups == {
        "tobacco_associated", "hpv_associated", "obesity_associated",
        "alcohol_associated", "alcohol_associated_limited_evidence",
        "uspstf_screenable", "vaccine_preventable", "uv_associated",
    }
    assert all(r["mapping_relation"] in ("exact", "broader") for r in real_rows)
    assert all(r["basis"] and r["source_url"] for r in real_rows)
