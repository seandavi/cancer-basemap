"""provenance.lineage (#140): sqlglot-resolved lineage captured at ingest.

Covers `lineage.record()` directly (a hand-written CTE + UNION + CASE, and a
deliberately unparseable SQL string), then the two wired modules against their
existing tiny fixtures: ers_rucc.py (a plain SELECT with a literal measure_id)
and places.py (a UNIONed `raw` CTAS view, no literal measure_id).
"""

from pathlib import Path

import pytest

from cancerbasemap import catalog, ers_rucc, lineage, places

REL = "2026.08"
RUCC_CSV = str(Path(__file__).parent / "tiny_ers_rucc.csv")


@pytest.fixture
def cat(tmp_path, monkeypatch):
    monkeypatch.setenv("CANCERBASEMAP_WAREHOUSE", str(tmp_path / "warehouse"))
    monkeypatch.delenv("CANCERBASEMAP_URI", raising=False)
    return catalog()


def edges(cat, **filters):
    rows = cat.load_table("provenance.lineage").scan().to_arrow().to_pylist()
    return [r for r in rows if all(r[k] == v for k, v in filters.items())]


# --- record() directly, no real module involved ---

def test_record_resolves_cte_union_and_case(cat):
    """sqlglot's own machinery handles the CTE and the UNION; the one thing
    `record()` does by hand is attach each branch's literal measure_id to
    that branch's own edges (#140's `_leaf_edges`). Uses two real declared
    raw tables (FIPS/LocationID are real columns of each) so the from_column
    validation (against the source table's own declared schema) passes."""
    con = lineage.connect()
    con.tables = {"raw1": "raw.ers__rucc", "raw2": "raw.places__county"}
    sql = """
        WITH src AS (
            SELECT 'X' AS measure_id, TRY_CAST(FIPS AS DOUBLE) AS value FROM raw1
            UNION ALL
            SELECT 'Y' AS measure_id, CASE WHEN LocationID > '0' THEN 1 ELSE NULL END AS value
            FROM raw2
        )
        SELECT measure_id, value FROM src
    """
    lineage.record(cat, REL, "unit", con, {"measure.observation": sql})

    rows = {(r["from_table"], r["to_variable"], r["expression"])
            for r in edges(cat, to_table="measure.observation", to_column="value")}
    assert rows == {
        ("raw.ers__rucc", "X", "TRY_CAST(raw1.fips AS DOUBLE)"),
        ("raw.places__county", "Y", "CASE WHEN raw2.locationid > '0' THEN 1 ELSE NULL END"),
    }


def test_unparseable_sql_is_unresolved_not_fatal(cat, capsys):
    """A lineage capture failure never aborts or corrupts an ingest (#140):
    the good output's edges are still written, and the bad one is counted,
    not raised."""
    con = lineage.connect()
    con.tables = {"raw1": "raw.ers__rucc"}
    good = "SELECT 'X' AS measure_id, TRY_CAST(FIPS AS DOUBLE) AS value FROM raw1"
    bad = "SELEC BROKEN((( FROM WHERE"

    lineage.record(cat, REL, "unit", con, {"measure.observation": good, "measure.definition": bad})

    assert "1 edge(s) unresolved" in capsys.readouterr().out
    rows = cat.load_table("provenance.lineage").scan().to_arrow().to_pylist()
    assert len(rows) == 1 and rows[0]["to_table"] == "measure.observation"


def test_unresolvable_column_is_unresolved_not_written(cat, capsys):
    """A leaf column that doesn't exist on the source table's own declared
    schema (a stale or wrong reference) is counted as unresolved and not
    written, rather than trusted unvalidated (#140 review)."""
    con = lineage.connect()
    con.tables = {"raw1": "raw.ers__rucc"}
    sql = "SELECT 'X' AS measure_id, TRY_CAST(not_a_real_column AS DOUBLE) AS value FROM raw1"

    lineage.record(cat, REL, "unit", con, {"measure.observation": sql})

    assert "1 edge(s) unresolved" in capsys.readouterr().out
    assert edges(cat, to_table="measure.observation", to_column="value") == []


# --- ers_rucc.py: a plain SELECT, literal measure_id ---

def test_ers_rucc_lineage(cat, capsys):
    ers_rucc.ingest(cat, REL, url=RUCC_CSV)
    out = capsys.readouterr().out
    assert "unresolved" not in out  # (a) zero unresolved edges

    # (b) a specific column edge, verified by hand against ers_rucc.py's
    # `TRY_CAST(r.Value AS DOUBLE) AS value` in `transform`'s observation SQL.
    value_edges = edges(cat, to_table="measure.observation", to_column="value")
    assert [(e["from_table"], e["from_column"], e["to_variable"], e["expression"])
            for e in value_edges] == [
        ("raw.ers__rucc", "value", "RUCC:code", "TRY_CAST(r.value AS DOUBLE)"),
    ]

    # (c) the table-level DAG
    rows = cat.load_table("provenance.lineage").scan().to_arrow().to_pylist()
    dag = {(r["from_table"], r["to_table"]) for r in rows}
    assert dag == {(RUCC_CSV, "raw.ers__rucc"), ("raw.ers__rucc", "measure.observation")}

    # (e) the raw table's own root edge
    [root] = edges(cat, to_table="raw.ers__rucc")
    assert (root["from_kind"], root["from_table"], root["to_column"]) == ("url", RUCC_CSV, None)

    # (d) idempotence
    before = sorted(rows, key=str)
    ers_rucc.ingest(cat, REL, url=RUCC_CSV)
    after = sorted(cat.load_table("provenance.lineage").scan().to_arrow().to_pylist(), key=str)
    assert before == after


# --- places.py: a UNIONed `raw` CTAS view, no literal measure_id ---

def line(columns, **cells):
    return ",".join(cells.get(c, "") for c in columns)


COUNTY_ROW = dict(
    Year="2022", StateAbbr="CO", StateDesc="Colorado", LocationName="Denver",
    DataSource="BRFSS", Category="Health Risk Behaviors",
    Measure="Current cigarette smoking among adults", Data_Value_Unit="%",
    Data_Value_Type="Crude prevalence", Data_Value="14.2",
    Low_Confidence_Limit="12.6", High_Confidence_Limit="15.9",
    TotalPopulation="713252", TotalPop18plus="584904", LocationID="08031",
    CategoryID="RISKBEH", MeasureId="CSMOKING", DataValueTypeID="CrdPrv",
    Short_Question_Text="Current Cigarette Smoking",
    Geolocation="POINT (-104.9 39.7)",
)
TRACT_ROW = dict(
    Year="2022", StateAbbr="CO", StateDesc="Colorado", CountyName="Denver",
    CountyFIPS="08031", LocationName="08031007800", DataSource="BRFSS",
    Category="Health Risk Behaviors",
    Measure="Current cigarette smoking among adults", Data_Value_Unit="%",
    Data_Value_Type="Crude prevalence", Data_Value="13.5",
    Low_Confidence_Limit="11.9", High_Confidence_Limit="15.1",
    TotalPopulation="4048", TotalPop18plus="3453", Geolocation="POINT (-104.9 39.7)",
    LocationID="08031007800", CategoryID="RISKBEH", MeasureId="CSMOKING",
    DataValueTypeID="CrdPrv", Short_Question_Text="Current Cigarette Smoking",
)


@pytest.fixture
def places_csv(tmp_path):
    path = tmp_path / "places_county.csv"
    path.write_text("\n".join([",".join(places.COLUMNS), line(places.COLUMNS, **COUNTY_ROW)]) + "\n")
    return str(path)


@pytest.fixture
def places_tract_csv(tmp_path):
    path = tmp_path / "places_tract.csv"
    path.write_text(
        "\n".join([",".join(places.TRACT_COLUMNS), line(places.TRACT_COLUMNS, **TRACT_ROW)]) + "\n")
    return str(path)


def test_places_lineage(cat, capsys, places_csv, places_tract_csv):
    places.ingest(cat, REL, places_release="2024", url=places_csv)
    places.ingest(cat, REL, places_release="2024", url=places_tract_csv, level="tract")
    out = capsys.readouterr().out
    assert "unresolved" not in out  # (a) zero unresolved edges

    # (b) a specific column edge, verified by hand against places.py's
    # `TRY_CAST(Data_Value AS DOUBLE) AS value` in `transform`'s observation SQL.
    # No to_variable: PLACES' measure_id is built from two columns
    # (MeasureId || Data_Value_Type), never asserted as one literal per branch
    # -- module docstring's own caveat, not a bug in the resolver.
    value_edges = {(e["from_table"], e["from_column"], e["to_variable"], e["expression"])
                   for e in edges(cat, to_table="measure.observation", to_column="value")}
    assert value_edges == {
        ("raw.places__county", "data_value", None, "TRY_CAST(raw.data_value AS DOUBLE)"),
        ("raw.places__tract", "data_value", None, "TRY_CAST(raw.data_value AS DOUBLE)"),
    }

    # measure.definition is built in Python from a query's *rows* (module
    # docstring: `pa.Table.from_pylist(definition_rows)`), not by column alias
    # -- an honest table-level-only edge (to_column NULL), not a guess.
    definition_edges = edges(cat, to_table="measure.definition")
    assert {(e["from_table"], e["to_column"]) for e in definition_edges} == {
        ("raw.places__county", None), ("raw.places__tract", None),
    }
    # measure.stratum has no SQL behind it at all (a hand-written Python
    # literal) -- no lineage claimed for it, honestly.
    assert edges(cat, to_table="measure.stratum") == []

    # (c) the table-level DAG
    rows = cat.load_table("provenance.lineage").scan().to_arrow().to_pylist()
    dag = {(r["from_table"], r["to_table"]) for r in rows}
    assert dag == {
        (places_csv, "raw.places__county"), (places_tract_csv, "raw.places__tract"),
        ("raw.places__county", "measure.definition"), ("raw.places__tract", "measure.definition"),
        ("raw.places__county", "measure.observation"), ("raw.places__tract", "measure.observation"),
    }

    # (e) each raw table's own root edge
    [county_root] = edges(cat, to_table="raw.places__county")
    [tract_root] = edges(cat, to_table="raw.places__tract")
    assert county_root["from_kind"] == tract_root["from_kind"] == "url"
    assert (county_root["from_table"], tract_root["from_table"]) == (places_csv, places_tract_csv)

    # (d) idempotence
    before = sorted(rows, key=str)
    places.ingest(cat, REL, places_release="2024", url=places_csv)
    places.ingest(cat, REL, places_release="2024", url=places_tract_csv, level="tract")
    after = sorted(cat.load_table("provenance.lineage").scan().to_arrow().to_pylist(), key=str)
    assert before == after
