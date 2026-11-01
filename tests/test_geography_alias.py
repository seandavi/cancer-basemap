"""geography.alias: land the curated county-recode CSV whole -> derive
geography.alias, one row per real (non-boundary) FIPS recode.

The CSV under test is the real packaged file (src/cancerbasemap/data/
county_recodes.csv), not a separate fixture -- it IS the source of truth
here, the same way the curated file is the review artifact per #26. A
malformed variant is written to tmp_path only for the header-mismatch case.
"""

from pathlib import Path

import pyarrow as pa
import pytest
from pyiceberg.expressions import EqualTo

from cancerbasemap import geography_alias as ga
from cancerbasemap import merge

REL = "2026.09"


def rows(cat, identifier, **kw):
    return cat.load_table(identifier).scan(**kw).to_arrow().to_pylist()


def test_raw_is_verbatim_and_whole(cat):
    n = ga.land_raw(cat, REL)
    assert n == 3

    raw = rows(cat, "raw.geography__county_recodes")
    assert len(raw) == 3
    assert {r["old_fips"] for r in raw} == {"46113", "02270", "12025"}
    assert {r["landed_in"] for r in raw} == {REL}

    # re-landing replaces wholesale (no version axis to accumulate on)
    ga.land_raw(cat, REL)
    assert len(rows(cat, "raw.geography__county_recodes")) == 3


def test_a_changed_header_fails_before_landing(cat, tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("old_fips,old_name,new_fips,new_name,effective_year,change_type,url,note\n"
                   "46113,Shannon County,46102,Oglala Lakota County,2015,recode_and_rename,x,y\n")
    with pytest.raises(SystemExit, match="url"):
        ga.land_raw(cat, REL, path=str(bad))


def test_derives_one_alias_row_per_recode(cat):
    counts = ga.ingest(cat, REL)
    assert counts["raw.geography__county_recodes"] == 3

    alias = {(r["old_geo_id"], r["new_geo_id"]): r for r in rows(cat, "geography.alias")}
    assert set(alias) == {
        ("county:46113", "county:46102"),
        ("county:02270", "county:02158"),
        ("county:12025", "county:12086"),
    }

    shannon = alias[("county:46113", "county:46102")]
    assert shannon["effective_year"] == 2015
    assert shannon["change_type"] == "recode_and_rename"
    assert shannon["old_name"] == "Shannon County"
    assert shannon["new_name"] == "Oglala Lakota County"
    assert shannon["source"] == "CENSUS_COUNTY_CHANGES"
    assert "county-changes.2010" in shannon["source_url"]
    assert shannon["note"]  # a citation, not blank

    miami_dade = alias[("county:12025", "county:12086")]
    assert miami_dade["effective_year"] == 1997


def test_an_old_code_resolves_through_the_alias(cat):
    """SPEC.md Acceptance B: a join on an old FIPS code resolves rather than
    drops. Simulate a measure.observation row keyed to Shannon County's
    retired code and resolve it through geography.alias."""
    import duckdb

    ga.ingest(cat, REL)
    con = duckdb.connect()
    con.register("alias", cat.load_table("geography.alias").scan().to_arrow())
    con.register("obs", pa.Table.from_pylist([{"geo_id": "county:46113", "value": 1.0}]))
    resolved = con.sql("""
        SELECT coalesce(a.new_geo_id, o.geo_id) AS geo_id, o.value
        FROM obs o LEFT JOIN alias a ON a.old_geo_id = o.geo_id
    """).fetchall()
    assert resolved == [("county:46102", 1.0)]


def test_an_unknown_change_type_fails_loudly(cat, tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("old_fips,old_name,new_fips,new_name,effective_year,change_type,"
                   "source_url,note\n"
                   "01001,A,01002,B,2020,boundary_shift,http://x,note\n")
    ga.land_raw(cat, REL, path=str(bad))
    with pytest.raises(SystemExit, match="boundary_shift"):
        ga.transform(cat, REL)


def test_rerun_is_idempotent(cat):
    ga.ingest(cat, REL)
    counts = ga.ingest(cat, "2026.10")
    assert counts["geography.alias"]["written"] == 0
    assert counts["geography.alias"]["unchanged"] == 3


def other_alias_row():
    return dict(old_geo_id="county:99998", new_geo_id="county:99999", effective_year=2000,
               change_type="recode", old_name="X", new_name="Y", source="OTHER",
               source_url="http://x", note=None)


def test_does_not_retire_another_writer(cat):
    """geography.alias's merge scope is `source`, so a second source of
    aliases could stack here without retiring this one's rows."""
    other = pa.Table.from_pylist([other_alias_row()])
    merge.merge(cat, "geography.alias", other, REL, EqualTo("source", "OTHER"))

    ga.ingest(cat, REL)
    ga.ingest(cat, "2026.10")

    live_other = rows(cat, "geography.alias",
                      row_filter="source = 'OTHER' AND valid_to IS NULL")
    assert len(live_other) == 1
    assert live_other[0]["valid_from"] == REL


def test_every_column_is_documented(cat):
    ga.ingest(cat, REL)
    for identifier in ("raw.geography__county_recodes", "geography.alias"):
        table = cat.load_table(identifier)
        assert table.properties.get("comment")
        for f in table.schema().fields:
            assert f.doc, f"{identifier}.{f.name} has no doc"
