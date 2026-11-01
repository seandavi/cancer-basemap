"""SEER site recode + cause-of-death recode: land whole -> derive
measure.cancer_site.

The fixtures (tests/tiny_seer_site_recode.txt, tests/tiny_seer_cod_recode.txt)
are real excerpts of the downloaded upstream text files -- the header, a
group heading with no code, a hierarchy example (Digestive System > Colon and
Rectum > Colon excluding Rectum > Cecum), a code defined by two physical rows
(Cranial Nerves Other Nervous System, 31040), a histology-only code with no
ICD-O-3 site restriction (Myeloma), and the 'Invalid' sentinel (99999). Every
line was checked against the real file byte-for-byte.
tests/tiny_cancer_site_ontology.csv is the real curated CSV's own rows for the
three codes the fixture covers.
"""

from pathlib import Path

import pyarrow as pa
import pytest
from pyiceberg.expressions import EqualTo

from cancerbasemap import cancer_site, merge

REL = "2026.08"
SITE_TXT = str(Path(__file__).parent / "tiny_seer_site_recode.txt")
COD_TXT = str(Path(__file__).parent / "tiny_seer_cod_recode.txt")
ONTOLOGY_CSV = str(Path(__file__).parent / "tiny_cancer_site_ontology.csv")


def rows(cat, identifier, **kw):
    return cat.load_table(identifier).scan(**kw).to_arrow().to_pylist()


def test_raw_is_verbatim_and_whole(cat):
    counts = cancer_site.land_raw(cat, REL, site_url=SITE_TXT, cod_url=COD_TXT)
    assert counts["raw.seer__site_recode"] == 11
    assert counts["raw.seer__cod_recode"] == 5

    site_raw = rows(cat, "raw.seer__site_recode")
    assert len(site_raw) == 11
    # the source's own leading-space indentation is kept, not trimmed
    cecum = next(r for r in site_raw if r["recode"].strip() == "21041")
    assert cecum["site_group"] == "            Cecum"
    assert cecum["icdo3_site"] == "C180"
    # a group heading has no recode at all
    heading = next(r for r in site_raw if r["site_group"].strip() == "Colon and Rectum")
    assert heading["recode"].strip() == ""

    cod_raw = rows(cat, "raw.seer__cod_recode")
    assert len(cod_raw) == 5
    sentinel = next(r for r in cod_raw if r["cod_group"] == "All Malignant Cancers")
    assert sentinel["recode"] == "--"

    # re-landing the same edition replaces it rather than appending
    cancer_site.land_raw(cat, REL, site_url=SITE_TXT, cod_url=COD_TXT)
    assert len(rows(cat, "raw.seer__site_recode")) == 11
    assert len(rows(cat, "raw.seer__cod_recode")) == 5


def test_a_changed_header_fails_before_landing(cat, tmp_path):
    bad = tmp_path / "bad.txt"
    bad.write_text("Site Group;ICD-O-3 Site;Recode\nLip;C000-C009;20010;\n")
    with pytest.raises(SystemExit, match="header"):
        cancer_site.land_raw(cat, REL, site_url=str(bad), cod_url=COD_TXT)


def test_derives_one_row_per_numeric_code(cat):
    counts = cancer_site.ingest(cat, REL, site_url=SITE_TXT, cod_url=COD_TXT,
                                ontology_csv=ONTOLOGY_CSV)
    assert counts["raw.seer__site_recode"] == 11
    sites = {r["cancer_site_code"]: r for r in rows(cat, "measure.cancer_site")}
    # 21010 Esophagus, 21041 Cecum, 31040 Cranial Nerves ONS, 34000 Myeloma,
    # 99999 Invalid -- exactly the 5 numeric codes in the fixture, no row for
    # any group heading (Oral Cavity and Pharynx, Digestive System, Colon and
    # Rectum, Colon excluding Rectum, Brain and Other Nervous System)
    assert set(sites) == {"21010", "21041", "31040", "34000", "99999"}

    esophagus = sites["21010"]
    assert esophagus["label"] == "Esophagus"
    assert esophagus["icdo3_topography"] == "C150-C159"
    assert esophagus["icdo3_histology_exclusions"] == "excluding 9050-9055, 9140, 9590-9993"
    assert esophagus["parent_code"] is None
    assert esophagus["source"] == "SEER"
    assert esophagus["source_release"] == "icdo3_dwhoheme"

    # Myeloma has no ICD-O-3 site restriction at all -- histology only
    myeloma = sites["34000"]
    assert myeloma["icdo3_topography"] is None
    assert myeloma["icdo3_histology_exclusions"] == "9731-9732, 9734"


def test_multi_row_code_is_consolidated(cat):
    cancer_site.ingest(cat, REL, site_url=SITE_TXT, cod_url=COD_TXT, ontology_csv=ONTOLOGY_CSV)
    cranial = next(r for r in rows(cat, "measure.cancer_site") if r["cancer_site_code"] == "31040")
    # two physical rows in the source, each with a different (site, histology)
    # clause -- both survive, concatenated in document order
    assert cranial["icdo3_topography"] == "C710-C719; C700-C709, C720-C729"
    assert cranial["icdo3_histology_exclusions"] == "9530-9539; excluding 9050-9055, 9140, 9590-9993"


def test_icd10_mortality_only_where_labels_align_exactly(cat):
    cancer_site.ingest(cat, REL, site_url=SITE_TXT, cod_url=COD_TXT, ontology_csv=ONTOLOGY_CSV)
    sites = {r["cancer_site_code"]: r for r in rows(cat, "measure.cancer_site")}
    # Esophagus: the exact label appears as a leaf in the COD fixture too
    assert sites["21010"]["icd10_mortality"] == "C15"
    # Cecum: COD only defines the coarser aggregate "Colon excluding Rectum"
    # (a different code, 21040) -- no label match, so NULL rather than guessed
    assert sites["21041"]["icd10_mortality"] is None
    # codes with no COD equivalent at all in the fixture
    assert sites["31040"]["icd10_mortality"] is None
    assert sites["99999"]["icd10_mortality"] is None


def test_curated_ontology_bridge(cat):
    cancer_site.ingest(cat, REL, site_url=SITE_TXT, cod_url=COD_TXT, ontology_csv=ONTOLOGY_CSV)
    sites = {r["cancer_site_code"]: r for r in rows(cat, "measure.cancer_site")}

    esophagus = sites["21010"]
    assert esophagus["ncit_id"] == "NCIT:C7478"
    assert esophagus["mondo_id"] == "MONDO:0007576"
    assert esophagus["mapping_basis"] == "curated"
    assert esophagus["mapping_relation"] == "exact"  # single-site 1:1 match (#90)

    # Cecum is one of Colon & Rectum's constituent SEER codes -- same curated
    # ontology term as every other constituent code would get
    cecum = sites["21041"]
    assert cecum["ncit_id"] == "NCIT:C4978"
    assert cecum["mondo_id"] == "MONDO:0005575"
    assert cecum["mapping_basis"] == "curated"
    assert cecum["mapping_relation"] == "broader"  # subsite -> combined category term (#90)

    # not in the curated CSV at all -- left NULL, not guessed
    myeloma = sites["34000"]
    assert myeloma["ncit_id"] is None
    assert myeloma["mondo_id"] is None
    assert myeloma["mapping_basis"] is None
    assert myeloma["mapping_relation"] is None


def test_unknown_curated_code_is_a_hard_stop(cat, tmp_path):
    cancer_site.land_raw(cat, REL, site_url=SITE_TXT, cod_url=COD_TXT)
    bad_csv = tmp_path / "bad_ontology.csv"
    bad_csv.write_text("cancer_site_code,label,ncit_id,ncit_label,mondo_id,mondo_label,"
                       "mapping_relation,note\n"
                       "99998,Nonexistent,NCIT:C1,x,MONDO:1,y,exact,\n")
    with pytest.raises(SystemExit, match="99998"):
        cancer_site.transform(cat, REL, ontology_csv=str(bad_csv))


def test_rerun_is_idempotent(cat):
    cancer_site.ingest(cat, REL, site_url=SITE_TXT, cod_url=COD_TXT, ontology_csv=ONTOLOGY_CSV)
    counts = cancer_site.ingest(cat, "2026.09", site_url=SITE_TXT, cod_url=COD_TXT,
                                ontology_csv=ONTOLOGY_CSV)
    assert counts["measure.cancer_site"]["written"] == 0
    assert counts["measure.cancer_site"]["unchanged"] == 5


def other_cancer_site_row():
    return dict(cancer_site_code="00000", label="A future edition's own code",
               parent_code=None, icdo3_topography=None, icdo3_histology_exclusions=None,
               icd10_mortality=None, ncit_id=None, mondo_id=None, mapping_basis=None,
               source="SEER", source_release="OTHER_EDITION", mapping_relation=None)


def test_does_not_retire_a_different_source_release(cat):
    """measure.cancer_site's merge scope is (source, source_release), matching
    SPEC.md's rule for measure.observation -- a future SEER edition landing
    under a new source_release must not retire this edition's rows, or the
    reverse."""
    other = pa.Table.from_pylist([other_cancer_site_row()])
    merge.merge(cat, "measure.cancer_site", other, REL, EqualTo("source_release", "OTHER_EDITION"))

    cancer_site.ingest(cat, REL, site_url=SITE_TXT, cod_url=COD_TXT, ontology_csv=ONTOLOGY_CSV)
    cancer_site.ingest(cat, "2026.09", site_url=SITE_TXT, cod_url=COD_TXT, ontology_csv=ONTOLOGY_CSV)

    live_other = rows(cat, "measure.cancer_site",
                      row_filter="source_release = 'OTHER_EDITION' AND valid_to IS NULL")
    assert len(live_other) == 1
    assert live_other[0]["valid_from"] == REL


def test_every_column_is_documented(cat):
    cancer_site.ingest(cat, REL, site_url=SITE_TXT, cod_url=COD_TXT, ontology_csv=ONTOLOGY_CSV)
    for identifier in ("raw.seer__site_recode", "raw.seer__cod_recode", "measure.cancer_site"):
        table = cat.load_table(identifier)
        assert table.properties.get("comment")
        for f in table.schema().fields:
            assert f.doc, f"{identifier}.{f.name} has no doc"
