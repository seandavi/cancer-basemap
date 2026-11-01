"""CDC PLACES: land whole -> derive definitions/stratum/observations, two
releases coexisting.

The fixtures are handcrafted at test time from real rows copied verbatim out
of the actual 2024 and 2025 county-data CSVs (fu4u-a9bh, swc5-untb) — the
header, a Colorado county in both releases, a Connecticut planning region, an
Alaska county (leading-zero FIPS), the national aggregate row (LocationID
'59'), a suppressed cell with its real footnote text, and the real
ISOLATION->LONELINESS measure rename — so the test never touches the network.

Tract fixtures (#30) are the same technique against the real 2024/2025
tract-data CSVs (ai6z-tcin, cwsq-ngmh): a Denver, CO tract sharing CSMOKING
with the county fixture (so the derived observation shares the county row's
measure_id but not its geo_id), a Connecticut planning-region tract, an
Alaska tract (leading-zero FIPS), and a Doña Ana County, NM tract
(non-ASCII name). Both real tract releases landed here have zero suppressed
rows (verified via the Socrata SODA API against the whole file, places.py
module docstring), so no suppressed tract row is faked into a fixture.
"""

import pytest
from pyiceberg.expressions import EqualTo

from cancerbasemap import catalog, places

REL1, REL2 = "2026.08", "2026.09"


def line(**cells):
    return ",".join(cells.get(c, "") for c in places.COLUMNS)


def tract_line(**cells):
    return ",".join(cells.get(c, "") for c in places.TRACT_COLUMNS)


# 2024 release (fu4u-a9bh): Denver County both prevalence types, a Connecticut
# planning region (09110 -- 2024 already uses the post-2022 regions), an
# Alaska county with a leading-zero FIPS, the national row, and ISOLATION
# (renamed to LONELINESS in 2025).
DATA_2024 = [
    line(Year="2022", StateAbbr="CO", StateDesc="Colorado", LocationName="Denver",
         DataSource="BRFSS", Category="Health Risk Behaviors",
         Measure="Current cigarette smoking among adults", Data_Value_Unit="%",
         Data_Value_Type="Crude prevalence", Data_Value="14.2",
         Low_Confidence_Limit="12.6", High_Confidence_Limit="15.9",
         TotalPopulation="713252", TotalPop18plus="584904", LocationID="08031",
         CategoryID="RISKBEH", MeasureId="CSMOKING", DataValueTypeID="CrdPrv",
         Short_Question_Text="Current Cigarette Smoking",
         Geolocation="POINT (-104.876829827118 39.7613507378355)"),
    line(Year="2022", StateAbbr="CO", StateDesc="Colorado", LocationName="Denver",
         DataSource="BRFSS", Category="Health Risk Behaviors",
         Measure="Current cigarette smoking among adults", Data_Value_Unit="%",
         Data_Value_Type="Age-adjusted prevalence", Data_Value="14.3",
         Low_Confidence_Limit="12.6", High_Confidence_Limit="16.0",
         TotalPopulation="713252", TotalPop18plus="584904", LocationID="08031",
         CategoryID="RISKBEH", MeasureId="CSMOKING", DataValueTypeID="AgeAdjPrv",
         Short_Question_Text="Current Cigarette Smoking",
         Geolocation="POINT (-104.876829827118 39.7613507378355)"),
    line(Year="2022", StateAbbr="CT", StateDesc="Connecticut", LocationName="Capitol",
         DataSource="BRFSS", Category="Health Risk Behaviors",
         Measure="Current cigarette smoking among adults", Data_Value_Unit="%",
         Data_Value_Type="Crude prevalence", Data_Value="12.1",
         Low_Confidence_Limit="10.9", High_Confidence_Limit="13.4",
         TotalPopulation="981447", TotalPop18plus="783914", LocationID="09110",
         CategoryID="RISKBEH", MeasureId="CSMOKING", DataValueTypeID="CrdPrv",
         Short_Question_Text="Current Cigarette Smoking",
         Geolocation="POINT (-72.5720699045246 41.8184543884154)"),
    line(Year="2022", StateAbbr="AK", StateDesc="Alaska", LocationName="Anchorage",
         DataSource="BRFSS", Category="Health Risk Behaviors",
         Measure="Current cigarette smoking among adults", Data_Value_Unit="%",
         Data_Value_Type="Crude prevalence", Data_Value="13.4",
         Low_Confidence_Limit="12.0", High_Confidence_Limit="14.9",
         TotalPopulation="287145", TotalPop18plus="219637", LocationID="02020",
         CategoryID="RISKBEH", MeasureId="CSMOKING", DataValueTypeID="CrdPrv",
         Short_Question_Text="Current Cigarette Smoking",
         Geolocation="POINT (-149.112545841578 61.150482370682)"),
    line(Year="2022", StateAbbr="US", StateDesc="United States", LocationName="",
         DataSource="BRFSS", Category="Prevention",
         Measure="Mammography use among women aged 50-74 years", Data_Value_Unit="%",
         Data_Value_Type="Age-adjusted prevalence", Data_Value="76.0",
         Low_Confidence_Limit="75.4", High_Confidence_Limit="76.7",
         TotalPopulation="333287557", TotalPop18plus="260836730", LocationID="59",
         CategoryID="PREVENT", MeasureId="MAMMOUSE", DataValueTypeID="AgeAdjPrv",
         Short_Question_Text="Mammography", Geolocation=""),
    line(Year="2022", StateAbbr="AL", StateDesc="Alabama", LocationName="Franklin",
         DataSource="BRFSS", Category="Health-Related Social Needs",
         Measure="Feeling socially isolated among adults", Data_Value_Unit="%",
         Data_Value_Type="Crude prevalence", Data_Value="34.2",
         Low_Confidence_Limit="29.2", High_Confidence_Limit="39.4",
         TotalPopulation="31932", TotalPop18plus="24099", LocationID="01059",
         CategoryID="SOCLNEED", MeasureId="ISOLATION", DataValueTypeID="CrdPrv",
         Short_Question_Text="Social Isolation",
         Geolocation="POINT (-87.8436750232892 34.4417388803873)"),
]

# 2025 release (swc5-untb): the same Denver measure with a changed value, the
# national row, LONELINESS (ISOLATION's real successor), and a genuinely
# suppressed cell with its real footnote text.
DATA_2025 = [
    line(Year="2023", StateAbbr="CO", StateDesc="Colorado", LocationName="Denver",
         DataSource="BRFSS", Category="Health Risk Behaviors",
         Measure="Current cigarette smoking among adults", Data_Value_Unit="%",
         Data_Value_Type="Crude prevalence", Data_Value="10.3",
         Low_Confidence_Limit="7.9", High_Confidence_Limit="13.0",
         TotalPopulation="716577", TotalPop18plus="589711", LocationID="08031",
         CategoryID="RISKBEH", MeasureId="CSMOKING", DataValueTypeID="CrdPrv",
         Short_Question_Text="Current Cigarette Smoking",
         Geolocation="POINT (-104.876829827118 39.7613507378355)"),
    line(Year="2022", StateAbbr="US", StateDesc="United States", LocationName="",
         DataSource="BRFSS", Category="Prevention",
         Measure="Mammography use among women aged 50-74 years", Data_Value_Unit="%",
         Data_Value_Type="Age-adjusted prevalence", Data_Value="76.0",
         Low_Confidence_Limit="75.4", High_Confidence_Limit="76.7",
         TotalPopulation="334914895", TotalPop18plus="262083034", LocationID="59",
         CategoryID="PREVENT", MeasureId="MAMMOUSE", DataValueTypeID="AgeAdjPrv",
         Short_Question_Text="Mammography", Geolocation=""),
    line(Year="2023", StateAbbr="AL", StateDesc="Alabama", LocationName="Franklin",
         DataSource="BRFSS", Category="Health-Related Social Needs",
         Measure="Loneliness among adults", Data_Value_Unit="%",
         Data_Value_Type="Crude prevalence", Data_Value="35.9",
         Low_Confidence_Limit="30.6", High_Confidence_Limit="41.7",
         TotalPopulation="31802", TotalPop18plus="23799", LocationID="01059",
         CategoryID="SOCLNEED", MeasureId="LONELINESS", DataValueTypeID="CrdPrv",
         Short_Question_Text="Loneliness",
         Geolocation="POINT (-87.8436750232892 34.4417388803873)"),
    line(Year="2023", StateAbbr="TX", StateDesc="Texas", LocationName="Loving",
         DataSource="BRFSS", Category="Health Risk Behaviors",
         Measure="No leisure-time physical activity among adults", Data_Value_Unit="%",
         Data_Value_Type="Age-adjusted prevalence", Data_Value="",
         Data_Value_Footnote_Symbol="*",
         Data_Value_Footnote="Estimates suppressed for population less than 50",
         Low_Confidence_Limit="", High_Confidence_Limit="",
         TotalPopulation="43", TotalPop18plus="30", LocationID="48301",
         CategoryID="RISKBEH", MeasureId="LPA", DataValueTypeID="AgeAdjPrv",
         Short_Question_Text="Physical Inactivity",
         Geolocation="POINT (-103.579939867014 31.8491416757447)"),
]

# Synthetic -- PLACES' real files have never published a non-numeric, present
# Data_Value with no footnote (verified 2026-09-19); built only to exercise
# the malformed-but-present case merge.check_observations' reverse guard
# protects against (#148, same shape as ers_rucc.py's fix in #149).
DATA_2025_MALFORMED = [*DATA_2025, line(
    Year="2023", StateAbbr="CO", StateDesc="Colorado", LocationName="Boulder",
    DataSource="BRFSS", Category="Health Risk Behaviors",
    Measure="Current cigarette smoking among adults", Data_Value_Unit="%",
    Data_Value_Type="Age-adjusted prevalence", Data_Value="N/A",
    Low_Confidence_Limit="", High_Confidence_Limit="",
    TotalPopulation="331567", TotalPop18plus="272577", LocationID="08013",
    CategoryID="RISKBEH", MeasureId="CSMOKING", DataValueTypeID="AgeAdjPrv",
    Short_Question_Text="Current Cigarette Smoking",
    Geolocation="POINT (-105.358159 40.0946089)")]


@pytest.fixture
def cat(tmp_path, monkeypatch):
    monkeypatch.setenv("CANCERBASEMAP_WAREHOUSE", str(tmp_path / "warehouse"))
    monkeypatch.delenv("CANCERBASEMAP_URI", raising=False)
    return catalog()


def write(path, data):
    path.write_text("\n".join([",".join(places.COLUMNS), *data]) + "\n")
    return str(path)


@pytest.fixture
def csv2024(tmp_path):
    return write(tmp_path / "tiny_places_2024.csv", DATA_2024)


@pytest.fixture
def csv2025(tmp_path):
    return write(tmp_path / "tiny_places_2025.csv", DATA_2025)


@pytest.fixture
def csv2025_malformed(tmp_path):
    return write(tmp_path / "tiny_places_2025_malformed.csv", DATA_2025_MALFORMED)


# 2024 tract release (ai6z-tcin): a Denver, CO tract with CSMOKING crude -- the
# same measure_id as DATA_2024's county CSMOKING row, different geo_id -- a
# Connecticut planning-region tract, an Alaska tract (leading-zero FIPS), and a
# Doña Ana County, NM tract (non-ASCII name).
DATA_TRACT_2024 = [
    tract_line(Year="2022", StateAbbr="CO", StateDesc="Colorado", CountyName="Denver",
              CountyFIPS="08031", LocationName="08031002709", DataSource="BRFSS",
              Category="Health Risk Behaviors",
              Measure="Current cigarette smoking among adults", Data_Value_Unit="%",
              Data_Value_Type="Crude prevalence", Data_Value="11.8",
              Low_Confidence_Limit="10.5", High_Confidence_Limit="13.3",
              TotalPopulation="2284", TotalPop18plus="2167", LocationID="08031002709",
              CategoryID="RISKBEH", MeasureId="CSMOKING", DataValueTypeID="CrdPrv",
              Short_Question_Text="Current Cigarette Smoking",
              Geolocation="POINT (-104.9764225 39.7335935)"),
    tract_line(Year="2022", StateAbbr="CT", StateDesc="Connecticut", CountyName="Capitol",
              CountyFIPS="09110", LocationName="09110400101", DataSource="BRFSS",
              Category="Health Outcomes", Measure="Stroke among adults",
              Data_Value_Unit="%", Data_Value_Type="Crude prevalence", Data_Value="4.0",
              Low_Confidence_Limit="3.6", High_Confidence_Limit="4.4",
              TotalPopulation="2928", TotalPop18plus="2483", LocationID="09110400101",
              CategoryID="HLTHOUT", MeasureId="STROKE", DataValueTypeID="CrdPrv",
              Short_Question_Text="Stroke", Geolocation="POINT (-72.7305122 41.6296007)"),
    tract_line(Year="2022", StateAbbr="AK", StateDesc="Alaska", CountyName="Anchorage",
              CountyFIPS="02020", LocationName="02020000102", DataSource="BRFSS",
              Category="Health Outcomes", Measure="Arthritis among adults",
              Data_Value_Unit="%", Data_Value_Type="Crude prevalence", Data_Value="26.5",
              Low_Confidence_Limit="24.3", High_Confidence_Limit="28.8",
              TotalPopulation="5215", TotalPop18plus="3978", LocationID="02020000102",
              CategoryID="HLTHOUT", MeasureId="ARTHRITIS", DataValueTypeID="CrdPrv",
              Short_Question_Text="Arthritis", Geolocation="POINT (-149.3997998 61.3488237)"),
    tract_line(Year="2022", StateAbbr="NM", StateDesc="New Mexico", CountyName="Doña Ana",
              CountyFIPS="35013", LocationName="35013001807", DataSource="BRFSS",
              Category="Health Outcomes", Measure="Current asthma among adults",
              Data_Value_Unit="%", Data_Value_Type="Crude prevalence", Data_Value="13.6",
              Low_Confidence_Limit="12.0", High_Confidence_Limit="15.3",
              TotalPopulation="2294", TotalPop18plus="1559", LocationID="35013001807",
              CategoryID="HLTHOUT", MeasureId="CASTHMA", DataValueTypeID="CrdPrv",
              Short_Question_Text="Current Asthma", Geolocation="POINT (-106.6100698 32.0056269)"),
]

# 2025 tract release (cwsq-ngmh): the same four geographies, different values.
DATA_TRACT_2025 = [
    tract_line(Year="2023", StateAbbr="CO", StateDesc="Colorado", CountyName="Denver",
              CountyFIPS="08031", LocationName="08031000102", DataSource="BRFSS",
              Category="Health Risk Behaviors",
              Measure="Current cigarette smoking among adults", Data_Value_Unit="%",
              Data_Value_Type="Crude prevalence", Data_Value="9.3",
              Low_Confidence_Limit="7.1", High_Confidence_Limit="11.8",
              TotalPopulation="3622", TotalPop18plus="3017", LocationID="08031000102",
              CategoryID="RISKBEH", MeasureId="CSMOKING", DataValueTypeID="CrdPrv",
              Short_Question_Text="Current Cigarette Smoking",
              Geolocation="POINT (-105.03984 39.7811473)"),
    tract_line(Year="2023", StateAbbr="CT", StateDesc="Connecticut", CountyName="Capitol",
              CountyFIPS="09110", LocationName="09110415600", DataSource="BRFSS",
              Category="Health Outcomes", Measure="Depression among adults",
              Data_Value_Unit="%", Data_Value_Type="Crude prevalence", Data_Value="23.5",
              Low_Confidence_Limit="20.9", High_Confidence_Limit="26.2",
              TotalPopulation="4198", TotalPop18plus="3108", LocationID="09110415600",
              CategoryID="HLTHOUT", MeasureId="DEPRESSION", DataValueTypeID="CrdPrv",
              Short_Question_Text="Depression", Geolocation="POINT (-72.779282 41.6528417)"),
    tract_line(Year="2023", StateAbbr="AK", StateDesc="Alaska", CountyName="Anchorage",
              CountyFIPS="02020", LocationName="02020001000", DataSource="BRFSS",
              Category="Health Outcomes", Measure="Depression among adults",
              Data_Value_Unit="%", Data_Value_Type="Crude prevalence", Data_Value="21.8",
              Low_Confidence_Limit="19.5", High_Confidence_Limit="24.6",
              TotalPopulation="3942", TotalPop18plus="3426", LocationID="02020001000",
              CategoryID="HLTHOUT", MeasureId="DEPRESSION", DataValueTypeID="CrdPrv",
              Short_Question_Text="Depression", Geolocation="POINT (-149.8759839 61.2102868)"),
    tract_line(Year="2023", StateAbbr="NM", StateDesc="New Mexico", CountyName="Doña Ana",
              CountyFIPS="35013", LocationName="35013000204", DataSource="BRFSS",
              Category="Health Outcomes", Measure="Stroke among adults",
              Data_Value_Unit="%", Data_Value_Type="Crude prevalence", Data_Value="2.5",
              Low_Confidence_Limit="2.2", High_Confidence_Limit="2.7",
              TotalPopulation="4665", TotalPop18plus="3313", LocationID="35013000204",
              CategoryID="HLTHOUT", MeasureId="STROKE", DataValueTypeID="CrdPrv",
              Short_Question_Text="Stroke", Geolocation="POINT (-106.8206533 32.3193469)"),
]


def write_tract(path, data):
    path.write_text("\n".join([",".join(places.TRACT_COLUMNS), *data]) + "\n")
    return str(path)


@pytest.fixture
def tract_csv2024(tmp_path):
    return write_tract(tmp_path / "tiny_places_tract_2024.csv", DATA_TRACT_2024)


@pytest.fixture
def tract_csv2025(tmp_path):
    return write_tract(tmp_path / "tiny_places_tract_2025.csv", DATA_TRACT_2025)


def rows(cat, identifier, **kw):
    return cat.load_table(identifier).scan(**kw).to_arrow().to_pylist()


def test_raw_is_verbatim_and_whole(cat, csv2024):
    places_release, n = places.land_raw(cat, REL1, places_release="2024", url=csv2024)
    assert places_release == "2024" and n == 6

    raw = rows(cat, "raw.places__county")
    assert len(raw) == 6
    denver = next(r for r in raw if r["LocationID"] == "08031" and r["Data_Value_Type"] == "Crude prevalence")
    assert denver["Data_Value"] == "14.2" and denver["places_release"] == "2024"
    # an empty cell is PLACES' missing marker and reads as NULL
    assert denver["Data_Value_Footnote"] is None
    # leading zeros survive on both a county and a national-row FIPS-like code
    assert {r["LocationID"] for r in raw if r["StateAbbr"] == "AK"} == {"02020"}

    # re-landing the same release replaces it rather than appending
    places.land_raw(cat, REL1, places_release="2024", url=csv2024)
    assert len(rows(cat, "raw.places__county")) == 6


def test_a_changed_header_fails_before_landing(cat, tmp_path):
    header = [c for c in places.COLUMNS if c != "TotalPop18plus"]  # the 2021-2023 shape
    bad = tmp_path / "old.csv"
    bad.write_text(",".join(header) + "\n")
    with pytest.raises(SystemExit, match="TotalPop18plus"):
        places.land_raw(cat, REL1, places_release="2024", url=str(bad))


def test_unknown_places_release_fails(cat):
    with pytest.raises(SystemExit, match="2019"):
        places.land_raw(cat, REL1, places_release="2019")


def test_derives_definitions_stratum_and_observations(cat, csv2024):
    counts = places.ingest(cat, REL1, places_release="2024", url=csv2024)
    assert counts["raw.places__county"] == 6

    defs = {d["measure_id"]: d for d in rows(cat, "measure.definition")}
    assert {"PLACES:CSMOKING:crude", "PLACES:CSMOKING:age_adjusted",
            "PLACES:MAMMOUSE:age_adjusted", "PLACES:ISOLATION:crude"} <= set(defs)
    crude = defs["PLACES:CSMOKING:crude"]
    assert crude["universe"] == "adults aged >=18 years" and crude["age_adjustment"] is None
    assert crude["method"] == "model_based" and crude["rate_basis"] == "percent"
    age = defs["PLACES:CSMOKING:age_adjusted"]
    assert age["age_adjustment"] == "2000 US standard population"
    mammo = defs["PLACES:MAMMOUSE:age_adjusted"]
    assert mammo["universe"] == "women aged 50-74 years"

    strata = rows(cat, "measure.stratum")
    assert [s["stratum_id"] for s in strata] == ["PLACES:ALL"]
    assert strata[0]["scheme"] == "PLACES_TOTAL"

    obs = {(o["measure_id"], o["geo_id"]): o
           for o in rows(cat, "measure.observation", row_filter=EqualTo("source", "PLACES"))}
    denver = obs[("PLACES:CSMOKING:crude", "county:08031")]
    assert (denver["value"], denver["lower"], denver["upper"]) == (14.2, 12.6, 15.9)
    assert denver["interval_level"] == 0.95 and denver["denominator"] is None
    assert denver["value_status"] == "reported" and denver["geo_vintage"] == 2020
    assert denver["period_start"] == denver["period_end"] == "2022"
    assert denver["source_release"] == "2024" and denver["stratum_id"] == "PLACES:ALL"

    ct = obs[("PLACES:CSMOKING:crude", "county:09110")]  # planning region, not zero-padded further
    assert ct["geo_id"] == "county:09110"
    us = obs[("PLACES:MAMMOUSE:age_adjusted", "nation:US")]
    assert us["value"] == 76.0


def test_suppression_maps_status_and_leaves_value_null(cat, csv2025):
    places.ingest(cat, REL2, places_release="2025", url=csv2025)
    obs = rows(cat, "measure.observation", row_filter=EqualTo("source_release", "2025"))
    lpa = next(o for o in obs if o["measure_id"] == "PLACES:LPA:age_adjusted")
    assert lpa["value_status"] == "suppressed_small_count"
    assert lpa["value"] is None and lpa["lower"] is None and lpa["upper"] is None

    reported = [o for o in obs if o["value_status"] == "reported"]
    assert all(o["value"] is not None for o in reported)


def test_a_present_non_numeric_value_lands_not_available_not_reported(cat, csv2025_malformed):
    """A cell that is present but doesn't parse as a number must not read as a
    numberless 'reported' row: value_status used to be derived from the raw
    cell's presence (`Data_Value IS NOT NULL`) while `value` went through a
    separate `TRY_CAST`, so a present-but-non-numeric cell landed as
    value_status='reported' with value NULL -- the shape #148 flagged in this
    module, and what merge.check_observations' reverse guard now catches for
    any source that regresses to it."""
    places.ingest(cat, REL2, places_release="2025", url=csv2025_malformed)
    obs = rows(cat, "measure.observation", row_filter=EqualTo("source_release", "2025"))
    boulder = next(o for o in obs if o["measure_id"] == "PLACES:CSMOKING:age_adjusted"
                   and o["geo_id"] == "county:08013")
    assert boulder["value"] is None
    assert boulder["value_status"] == "not_available"


def test_unmapped_footnote_raises(cat, csv2025, monkeypatch):
    monkeypatch.setattr(places, "FOOTNOTE_STATUS", {})
    places.land_raw(cat, REL2, places_release="2025", url=csv2025)
    with pytest.raises(SystemExit, match="unmapped suppression footnote"):
        places.transform(cat, REL2, "2025")


def test_two_releases_coexist_and_first_is_not_retired(cat, csv2024, csv2025):
    places.ingest(cat, REL1, places_release="2024", url=csv2024)
    places.ingest(cat, REL2, places_release="2025", url=csv2025)

    releases = {o["source_release"] for o in
               rows(cat, "measure.observation", row_filter=EqualTo("source", "PLACES"))}
    assert releases == {"2024", "2025"}

    # geo_id pins this to the Denver, CO county row: several other counties
    # share this measure_id, and issue #120's sort-by-geo_id write order means
    # a plain next() would otherwise land on whichever of them sorts first.
    denver_2024 = next(o for o in rows(cat, "measure.observation") if
                       o["measure_id"] == "PLACES:CSMOKING:crude" and o["source_release"] == "2024"
                       and o["geo_id"] == "county:08031")
    denver_2025 = next(o for o in rows(cat, "measure.observation") if
                       o["measure_id"] == "PLACES:CSMOKING:crude" and o["source_release"] == "2025"
                       and o["geo_id"] == "county:08031")
    assert denver_2024["value"] == 14.2 and denver_2024["valid_to"] is None  # untouched
    assert denver_2025["value"] == 10.3 and denver_2025["valid_to"] is None  # a distinct business key

    # measure.definition still has no history (SPEC.md: replaced wholesale per
    # source), but the write is now scoped to the ids each release asserts
    # (#76 interim fix), so the 2025 ingest -- which asserts LONELINESS, not
    # ISOLATION -- no longer deletes the 2024-only ISOLATION definition that
    # its still-live 2024 observation row references.
    defs = {d["measure_id"] for d in rows(cat, "measure.definition")}
    assert "PLACES:ISOLATION:crude" in defs and "PLACES:LONELINESS:crude" in defs
    still_there = [o for o in rows(cat, "measure.observation")
                  if o["measure_id"] == "PLACES:ISOLATION:crude"]
    assert len(still_there) == 1


def test_rerun_is_idempotent(cat, csv2024):
    places.ingest(cat, REL1, places_release="2024", url=csv2024)
    counts = places.ingest(cat, "2026.10", places_release="2024", url=csv2024)
    assert counts["measure.observation"]["written"] == 0
    assert counts["measure.observation"]["unchanged"] == 6


def test_every_column_is_documented(cat, csv2024, tract_csv2024):
    places.ingest(cat, REL1, places_release="2024", url=csv2024)
    places.ingest(cat, REL1, places_release="2024", url=tract_csv2024, level="tract")
    for identifier in ("raw.places__county", "raw.places__tract", "measure.definition",
                      "measure.stratum", "measure.observation"):
        table = cat.load_table(identifier)
        assert table.properties.get("comment"), identifier
        for f in table.schema().fields:
            assert f.doc, f"{identifier}.{f.name} has no doc"


# --- tract (#30) ---

def test_tract_raw_is_verbatim_and_whole(cat, tract_csv2025):
    places_release, n = places.land_raw(cat, REL1, places_release="2025",
                                        level="tract", url=tract_csv2025)
    assert places_release == "2025" and n == 4

    raw = rows(cat, "raw.places__tract")
    assert len(raw) == 4
    denver = next(r for r in raw if r["LocationID"] == "08031000102")
    assert denver["Data_Value"] == "9.3" and denver["places_release"] == "2025"
    # upstream's own quirk: LocationName duplicates LocationID (the tract FIPS),
    # not a human name the way the county file's LocationName is
    assert denver["LocationName"] == denver["LocationID"] == "08031000102"
    assert denver["CountyFIPS"] == "08031" and denver["CountyName"] == "Denver"
    # leading zeros survive on a tract FIPS
    assert {r["LocationID"] for r in raw if r["StateAbbr"] == "AK"} == {"02020001000"}
    # non-ASCII county name survives verbatim
    dona_ana = next(r for r in raw if r["CountyFIPS"] == "35013")
    assert dona_ana["CountyName"] == "Doña Ana"

    # re-landing the same release replaces it rather than appending
    places.land_raw(cat, REL1, places_release="2025", level="tract", url=tract_csv2025)
    assert len(rows(cat, "raw.places__tract")) == 4


def test_tract_header_check_uses_its_own_contract(cat, tmp_path):
    # the county header is a real, different contract -- not the tract one
    bad = tmp_path / "county_shaped.csv"
    bad.write_text(",".join(places.COLUMNS) + "\n")
    with pytest.raises(SystemExit, match="header is not the declared one"):
        places.land_raw(cat, REL1, places_release="2025", level="tract", url=str(bad))


def test_unknown_tract_release_fails(cat):
    with pytest.raises(SystemExit, match="2019"):
        places.land_raw(cat, REL1, places_release="2019", level="tract")


def test_tract_reuses_county_crude_measure_ids(cat, csv2024, tract_csv2024):
    """#30: tract mints no measure_ids of its own -- its CSMOKING crude row asserts
    the SAME 'PLACES:CSMOKING:crude' id the county fixture's crude row does, just a
    different geo_id."""
    places.ingest(cat, REL1, places_release="2024", url=csv2024)
    places.ingest(cat, REL1, places_release="2024", url=tract_csv2024, level="tract")

    defs = {d["measure_id"] for d in rows(cat, "measure.definition")}
    assert "PLACES:CSMOKING:crude" in defs
    # exactly one definition row for it, not one per level
    matches = [d for d in rows(cat, "measure.definition") if d["measure_id"] == "PLACES:CSMOKING:crude"]
    assert len(matches) == 1

    obs = {(o["measure_id"], o["geo_id"]): o
           for o in rows(cat, "measure.observation", row_filter=EqualTo("source", "PLACES"))}
    county_row = obs[("PLACES:CSMOKING:crude", "county:08031")]
    tract_row = obs[("PLACES:CSMOKING:crude", "tract:08031002709")]
    assert county_row["value"] == 14.2  # DATA_2024's county-level value
    assert tract_row["value"] == 11.8   # DATA_TRACT_2024's tract-level value, same measure_id
    assert tract_row["geo_vintage"] == 2020  # same GEO_VINTAGE dict as county for 2024

    ct_tract = obs[("PLACES:STROKE:crude", "tract:09110400101")]
    assert ct_tract["geo_id"] == "tract:09110400101"  # planning-region prefix, not zero-padded further


def test_county_and_tract_combine_without_retiring_each_other(cat, csv2024, tract_csv2024):
    """measure.observation's merge scope is (source, source_release), not per-level --
    landing county then tract (or vice versa) for the same release must accumulate,
    never retire the other level's rows (module docstring, same fix as cdc_svi.py)."""
    places.ingest(cat, REL1, places_release="2024", url=csv2024)
    places.ingest(cat, REL1, places_release="2024", url=tract_csv2024, level="tract")

    live = rows(cat, "measure.observation",
               row_filter="source = 'PLACES' AND source_release = '2024' AND valid_to IS NULL")
    levels = {o["geo_id"].split(":")[0] for o in live}
    assert levels == {"county", "tract", "nation"}

    # re-deriving from county alone (e.g. a county-only re-ingest) must not retire tract
    places.ingest(cat, "2026.10", places_release="2024", url=csv2024)
    live2 = rows(cat, "measure.observation",
                row_filter="source = 'PLACES' AND source_release = '2024' AND valid_to IS NULL")
    assert {o["geo_id"].split(":")[0] for o in live2} == {"county", "tract", "nation"}
    assert len(live2) == len(live)


def test_tract_then_county_also_combine(cat, csv2024, tract_csv2024):
    """The reverse order: landing tract before county must not retire county rows
    either, and must pick them up once county lands."""
    places.ingest(cat, REL1, places_release="2024", url=tract_csv2024, level="tract")
    tract_only = rows(cat, "measure.observation",
                      row_filter="source = 'PLACES' AND valid_to IS NULL")
    assert {o["geo_id"].split(":")[0] for o in tract_only} == {"tract"}

    places.ingest(cat, "2026.10", places_release="2024", url=csv2024)
    combined = rows(cat, "measure.observation",
                    row_filter="source = 'PLACES' AND valid_to IS NULL")
    assert {o["geo_id"].split(":")[0] for o in combined} == {"county", "tract", "nation"}
    assert len(combined) == len(tract_only) + 6  # DATA_2024's 6 county rows all land


def test_tract_every_column_is_documented(cat, tract_csv2025):
    places.ingest(cat, REL1, places_release="2025", url=tract_csv2025, level="tract")
    table = cat.load_table("raw.places__tract")
    assert table.properties.get("comment")
    for f in table.schema().fields:
        assert f.doc, f"raw.places__tract.{f.name} has no doc"
