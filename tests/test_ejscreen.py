"""EPA EJScreen: land whole -> derive tract-level environmental indicator
observations. Fixtures are small, real-shaped excerpts (real Autauga County AL
block group / tract GEOIDs) covering three column families: 2015 (lowercase/dotted
names), 2018 ("classic" ID/PM25/CANCER/RESP family), 2022 tract (classic + UST),
2024 tract (CANCER/RESP dropped, RSEI_AIR/NO2/DWATER added) -- see ejscreen.py
module docstring for what changed when.
"""

from pathlib import Path

import pytest
from pyiceberg.exceptions import NoSuchTableError
from pyiceberg.expressions import EqualTo

from cancerbasemap import ejscreen, merge

REL = "2026.08"
FIX = Path(__file__).parent
BG_2015 = str(FIX / "tiny_ejscreen_bg_2015.csv")
BG_2018 = str(FIX / "tiny_ejscreen_bg_2018.csv")
TRACT_2022 = str(FIX / "tiny_ejscreen_tract_2022.csv")
TRACT_2024 = str(FIX / "tiny_ejscreen_tract_2024.csv")


def rows(cat, identifier, **kw):
    return cat.load_table(identifier).scan(**kw).to_arrow().to_pylist()


def test_raw_blockgroup_is_verbatim_and_whole(cat):
    edition, n = ejscreen.land_raw(cat, REL, "2018", "blockgroup", url=BG_2018)
    assert edition == "2018"
    assert n == 2

    raw = rows(cat, "raw.ejscreen__blockgroup")
    assert len(raw) == 2
    assert {r["geo_id"] for r in raw} == {"010010201001", "010010202001"}
    assert {r["ejscreen_edition"] for r in raw} == {"2018"}
    assert {r["landed_in"] for r in raw} == {REL}
    # unparsed text, not a number
    a = next(r for r in raw if r["geo_id"] == "010010201001")
    assert a["pm25"] == "10.2"
    assert a["cancer"] == "25.3"
    # concepts this edition doesn't publish land NULL
    assert a["ust"] is None
    assert a["rsei_air"] is None
    assert a["no2"] is None
    # a blank real cell lands NULL, not '' or a sentinel
    b = next(r for r in raw if r["geo_id"] == "010010202001")
    assert b["cancer"] is None
    # every other published column survives, verbatim, in extra_json
    assert '"STATE_NAME":"Alabama"' in a["extra_json"]

    # re-landing the same edition replaces it rather than appending
    ejscreen.land_raw(cat, REL, "2018", "blockgroup", url=BG_2018)
    assert len(rows(cat, "raw.ejscreen__blockgroup")) == 2


def test_2015_lowercase_layout_maps_to_the_same_concepts(cat):
    ejscreen.land_raw(cat, REL, "2015", "blockgroup", url=BG_2015)
    raw = {r["geo_id"]: r for r in rows(cat, "raw.ejscreen__blockgroup")}
    a = raw["010010201001"]
    assert a["pm25"] == "10.5"
    assert a["ozone"] == "39.0"
    assert a["dslpm"] == "0.5"
    assert a["pwdis"] == "0.18"
    assert a["ust"] is None


def test_unknown_edition_or_tract_combo_rejected(cat):
    with pytest.raises(SystemExit, match="no known edition"):
        ejscreen.land_raw(cat, REL, "2010", "blockgroup", url=BG_2018)
    with pytest.raises(SystemExit, match="tract is only landed"):
        ejscreen.land_raw(cat, REL, "2018", "tract", url=TRACT_2022)


def test_a_missing_declared_column_fails_before_landing(cat, tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("ID,PM25\n010010201001,10.0\n")
    with pytest.raises(SystemExit, match="missing declared column"):
        ejscreen.land_raw(cat, REL, "2018", "blockgroup", url=str(bad))


def test_tract_derives_measure_observation(cat):
    ejscreen.ingest(cat, REL, "2022", "tract", url=TRACT_2022)

    raw = rows(cat, "raw.ejscreen__tract")
    assert len(raw) == 2

    obs = rows(cat, "measure.observation", row_filter=EqualTo("source", "EJSCREEN"))
    by_measure_geo = {(o["measure_id"], o["geo_id"]): o for o in obs}

    pm25 = by_measure_geo[("EJSCREEN:pm25", "tract:01001020100")]
    assert pm25["value"] == pytest.approx(10.1)
    assert pm25["value_status"] == "reported"
    assert pm25["source_release"] == "2022"
    assert pm25["geo_vintage"] == 2020  # 2022 edition -> 2020-vintage geography
    assert pm25["period_start"] == pm25["period_end"] == "2022"

    # a real blank cell (UST for the second tract) -> not_available, never a number
    ust = by_measure_geo[("EJSCREEN:ust", "tract:01001020200")]
    assert ust["value"] is None
    assert ust["value_status"] == "not_available"

    # concepts this edition doesn't publish (rsei_air, no2, dwater) get no row at all
    assert ("EJSCREEN:rsei_air", "tract:01001020100") not in by_measure_geo
    assert ("EJSCREEN:no2", "tract:01001020100") not in by_measure_geo

    definitions = {d["measure_id"] for d in rows(cat, "measure.definition")}
    assert "EJSCREEN:pm25" in definitions and "EJSCREEN:ust" in definitions


def test_2024_family_drops_cancer_resp_for_rsei_air(cat):
    ejscreen.ingest(cat, REL, "2024", "tract", url=TRACT_2024)
    obs = rows(cat, "measure.observation", row_filter=EqualTo("source_release", "2024"))
    ids = {o["measure_id"] for o in obs}
    assert "EJSCREEN:rsei_air" in ids and "EJSCREEN:no2" in ids and "EJSCREEN:dwater" in ids
    assert "EJSCREEN:cancer" not in ids and "EJSCREEN:resp" not in ids
    # 2024 tract geometry matches the Gazetteer's "2022" vintage (Connecticut's
    # planning regions), not "2020" (GEO_VINTAGE's own comment)
    assert {o["geo_vintage"] for o in obs} == {2022}


def test_ptraf_and_pwdis_split_by_definition_family(cat):
    """Same column name (PTRAF/PWDIS), incompatible definitions -- verified against
    real data (module docstring: ~9,400x and ~34,000x median jumps exactly at 2024).
    One id must never span both."""
    ejscreen.ingest(cat, REL, "2022", "tract", url=TRACT_2022)
    ejscreen.ingest(cat, REL, "2024", "tract", url=TRACT_2024)
    obs = rows(cat, "measure.observation", row_filter=EqualTo("source", "EJSCREEN"))
    ids_2022 = {o["measure_id"] for o in obs if o["source_release"] == "2022"}
    ids_2024 = {o["measure_id"] for o in obs if o["source_release"] == "2024"}
    assert "EJSCREEN:ptraf:pre2024" in ids_2022 and "EJSCREEN:ptraf:2024" not in ids_2022
    assert "EJSCREEN:ptraf:2024" in ids_2024 and "EJSCREEN:ptraf:pre2024" not in ids_2024
    assert "EJSCREEN:pwdis:pre2024" in ids_2022
    assert "EJSCREEN:pwdis:2024" in ids_2024
    # every other concept keeps one plain id across both editions
    assert "EJSCREEN:pm25" in ids_2022 and "EJSCREEN:pm25" in ids_2024

    definitions = {d["measure_id"] for d in rows(cat, "measure.definition")}
    assert {"EJSCREEN:ptraf:pre2024", "EJSCREEN:ptraf:2024",
            "EJSCREEN:pwdis:pre2024", "EJSCREEN:pwdis:2024"} <= definitions
    assert "EJSCREEN:ptraf" not in definitions  # the old unsplit id is gone


def test_malformed_territory_geo_id_is_excluded_not_guessed(cat):
    """A real EPA data-quality issue (module docstring: 1,977 AS/GU/MP/VI rows,
    never PR, verified against the real 2022-2024 tract files) -- landed verbatim in
    raw, excluded (not guessed at) when deriving measure.observation."""
    result = ejscreen.ingest(cat, REL, "2024", "tract", url=TRACT_2024)

    raw = rows(cat, "raw.ejscreen__tract")
    assert "6000100" in {r["geo_id"] for r in raw}  # landed verbatim, malformed and all

    obs = rows(cat, "measure.observation", row_filter=EqualTo("source", "EJSCREEN"))
    assert not any("6000100" in o["geo_id"] for o in obs)
    assert result["excluded_malformed_geo_id"] == 1


def test_blockgroup_is_not_derived(cat):
    """geography.unit carries no block_group level yet (module docstring) -- landing
    block group raw must not write measure.observation rows for it."""
    result = ejscreen.ingest(cat, REL, "2018", "blockgroup", url=BG_2018)
    assert "measure.observation" not in result
    try:
        assert rows(cat, "measure.observation", row_filter=EqualTo("source", "EJSCREEN")) == []
    except NoSuchTableError:
        pass  # nothing ever derived a measure.observation row in this test -- fine too


def test_latin1_file_decodes_correctly_not_replacement_chars(cat, tmp_path):
    """The real 2023 block group file is Latin-1 throughout, not UTF-8 with one
    stray byte (module docstring: checked for the UTF-8 two-byte accented-character
    encoding and any latin-1-misdecoded-as-utf-8 mojibake elsewhere in the file --
    found neither, so the whole file is decoded as Latin-1). A fixture with a
    Latin-1 "Do\xf1a Ana"-style byte, comma-separated same as the real file, must
    come back as the real accented character -- not U+FFFD (what an
    errors='replace' UTF-8 decode would produce, silently mangling real place names
    the earlier version of this fix corrupted -- 687 of them, per the PR review that
    caught it)."""
    raw = ("ID,STATE_NAME,PM25,OZONE,DSLPM,CANCER,RESP,PTRAF,PRE1960PCT,PNPL,PRMP,"
           "PTSDF,PWDIS\n010010201001,Do\xf1a Ana County,10.0,38.0,0.4,20.0,0.3,"
           "80.0,15.0,0.02,0.01,0.01,0.1\n").encode("latin-1")
    bad = tmp_path / "latin1.csv"
    bad.write_bytes(raw)
    ejscreen.land_raw(cat, REL, "2018", "blockgroup", url=str(bad))
    row = rows(cat, "raw.ejscreen__blockgroup")[0]
    assert "Doña Ana County" in row["extra_json"]
    assert "�" not in row["extra_json"]


def test_no_suppressed_cell_reads_as_a_number(cat):
    ejscreen.ingest(cat, REL, "2022", "tract", url=TRACT_2022)
    obs = rows(cat, "measure.observation", row_filter=EqualTo("source", "EJSCREEN"))
    for o in obs:
        if o["value_status"] != "reported":
            assert o["value"] is None
    merge.check_observations(cat.load_table("measure.observation").scan(
        row_filter=EqualTo("source", "EJSCREEN")).to_arrow())
