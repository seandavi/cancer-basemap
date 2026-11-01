"""CDC TeenVaxView / NIS-Teen HPV vaccination coverage: land whole (every
vaccine/year) -> derive HPV >=1 dose / up-to-date, checksum-deduplicated
vintages, county-mappable local areas (#105).

Fixtures are real rows copied verbatim out of the live Socrata dataset
(ee48-w5t6, fetched 2026-09-19): Colorado's pooled-window Overall estimates
for both derived measures, a real Age breakdown, TX-Bexar County and
PA-Philadelphia (the two county-mappable local areas exercised here --
Philadelphia because it is coextensive with Philadelphia County, unlike
every other city-named local area), a real suppressed 'NA' cell (TX-El Paso
County, Up-to-Date Females, 13-15 Years, 2023), a real Insurance Coverage
breakdown, IL-City of Chicago and HHS Region 1 (both genuinely unmapped
geographies), a real '>=2 Doses' row (a known-but-not-derived HPV dose
family), and a real non-HPV row (Tetanus) confirming raw lands every
vaccine even though only HPV is derived.
"""

import csv
import io

import pyarrow as pa
import pytest
from pyiceberg.expressions import EqualTo

from cancerbasemap import merge, teenvaxview

REL = "2026.09"


def line(**cells):
    row = [cells.get(c, "") for c in teenvaxview.COLUMNS]
    buf = io.StringIO()
    csv.writer(buf, lineterminator="").writerow(row)
    return buf.getvalue()


# Real rows, verbatim, fetched from https://data.cdc.gov/resource/ee48-w5t6.json
# 2026-09-19 (module docstring).
DATA_V1 = [
    line(**{"Vaccine/Sample": "HPV", "Dose": "≥1 Dose, Males and Females",
           "Geography Type": "States/Local Areas", "Geography": "Colorado",
           "Survey Year": "2018-2022", "Dimension Type": "Overall", "Dimension": "Overall",
           "Estimate (%)": "79.7", "95% CI (%)": "77.1 to 82.2", "Sample Size": "1534"}),
    line(**{"Vaccine/Sample": "HPV", "Dose": "Up-to-Date, Males and Females",
           "Geography Type": "States/Local Areas", "Geography": "Colorado",
           "Survey Year": "2018-2022", "Dimension Type": "Overall", "Dimension": "Overall",
           "Estimate (%)": "65.5", "95% CI (%)": "62.4 to 68.5", "Sample Size": "1534"}),
    line(**{"Vaccine/Sample": "HPV", "Dose": "Up-to-Date, Females",
           "Geography Type": "States/Local Areas", "Geography": "Colorado",
           "Survey Year": "2025", "Dimension Type": "Age", "Dimension": "13-17 Years",
           "Estimate (%)": "68.4", "95% CI (%)": "59.3 to 76.3", "Sample Size": "135"}),
    line(**{"Vaccine/Sample": "HPV", "Dose": "≥1 Dose, Males and Females",
           "Geography Type": "States/Local Areas", "Geography": "TX-Bexar County",
           "Survey Year": "2025", "Dimension Type": "Age", "Dimension": "13-17 Years",
           "Estimate (%)": "78.0", "95% CI (%)": "72.6 to 82.6", "Sample Size": "306"}),
    line(**{"Vaccine/Sample": "HPV", "Dose": "≥1 Dose, Males and Females",
           "Geography Type": "States/Local Areas", "Geography": "PA-Philadelphia",
           "Survey Year": "2025", "Dimension Type": "Age", "Dimension": "13-17 Years",
           "Estimate (%)": "87.8", "95% CI (%)": "83.5 to 91.1", "Sample Size": "344"}),
    line(**{"Vaccine/Sample": "HPV", "Dose": "Up-to-Date, Females",
           "Geography Type": "States/Local Areas", "Geography": "TX-El Paso County",
           "Survey Year": "2023", "Dimension Type": "Age", "Dimension": "13-15 Years",
           "Estimate (%)": "NA"}),  # real suppressed cell: blank CI/Sample Size
    line(**{"Vaccine/Sample": "HPV", "Dose": "Up-to-Date, Males and Females",
           "Geography Type": "States/Local Areas", "Geography": "Colorado",
           "Survey Year": "2018-2022", "Dimension Type": "Insurance Coverage",
           "Dimension": "Uninsured", "Estimate (%)": "56.3", "95% CI (%)": "37.9 to 73.1",
           "Sample Size": "37"}),
    line(**{"Vaccine/Sample": "HPV", "Dose": "≥1 Dose, Males and Females",
           "Geography Type": "States/Local Areas", "Geography": "IL-City of Chicago",
           "Survey Year": "2025", "Dimension Type": "Age", "Dimension": "13-17 Years",
           "Estimate (%)": "88.9", "95% CI (%)": "82.8 to 93.0", "Sample Size": "264"}),
    line(**{"Vaccine/Sample": "HPV", "Dose": "≥2 Doses, Females",
           "Geography Type": "States/Local Areas", "Geography": "Colorado",
           "Survey Year": "2008", "Dimension Type": "Age", "Dimension": "13-17 Years",
           "Estimate (%)": "24.5", "95% CI (%)": "17.5 to 33.2", "Sample Size": "181"}),
    line(**{"Vaccine/Sample": "HPV", "Dose": "≥1 Dose, Males and Females",
           "Geography Type": "HHS Regions/National", "Geography": "United States",
           "Survey Year": "2018-2022", "Dimension Type": "Overall", "Dimension": "Overall",
           "Estimate (%)": "73.5", "95% CI (%)": "73.0 to 74.1", "Sample Size": "91696"}),
    line(**{"Vaccine/Sample": "HPV", "Dose": "Up-to-Date, Males and Females",
           "Geography Type": "HHS Regions/National", "Geography": "Region 1",
           "Survey Year": "2023", "Dimension Type": "Age", "Dimension": "13-17 Years",
           "Estimate (%)": "76.1", "95% CI (%)": "72.5 to 79.4", "Sample Size": "1504"}),
    line(**{"Vaccine/Sample": "Tetanus", "Dose": "≥1 Dose Tdap",
           "Geography Type": "States/Local Areas", "Geography": "Colorado",
           "Survey Year": "2018-2022", "Dimension Type": "Insurance Coverage",
           "Dimension": "Uninsured", "Estimate (%)": "75.0", "95% CI (%)": "55.9 to 87.6",
           "Sample Size": "37"}),
]

# A later, revised retrieval: Colorado's pooled >=1 Dose Overall estimate ticks up
# (79.7 -> 80.1) -- a real kind of revision this source makes (module docstring:
# "appended yearly and occasionally revised"), enough of a byte difference to not
# be an unchanged-checksum vintage.
DATA_V2 = list(DATA_V1)
DATA_V2[0] = line(**{"Vaccine/Sample": "HPV", "Dose": "≥1 Dose, Males and Females",
                    "Geography Type": "States/Local Areas", "Geography": "Colorado",
                    "Survey Year": "2018-2022", "Dimension Type": "Overall",
                    "Dimension": "Overall", "Estimate (%)": "80.1",
                    "95% CI (%)": "77.5 to 82.6", "Sample Size": "1540"})


def write(path, data):
    path.write_text("\n".join([",".join(teenvaxview.COLUMNS), *data]) + "\n")
    return str(path)


@pytest.fixture
def csv_v1(tmp_path):
    return write(tmp_path / "tiny_teenvaxview_v1.csv", DATA_V1)


@pytest.fixture
def csv_v2(tmp_path):
    return write(tmp_path / "tiny_teenvaxview_v2.csv", DATA_V2)


def rows(cat, identifier, **kw):
    return cat.load_table(identifier).scan(**kw).to_arrow().to_pylist()


def _ingest(cat, csv_path, release=REL, vintage="2026-09-01"):
    return teenvaxview.ingest(cat, release, vintage=vintage, url=csv_path)


def test_raw_is_verbatim_and_whole(cat, csv_v1):
    vintage, n = teenvaxview.land_raw(cat, REL, vintage="2026-09-01", url=csv_v1)
    assert vintage == "2026-09-01" and n == len(DATA_V1)

    raw = rows(cat, "raw.teenvaxview__coverage")
    assert len(raw) == len(DATA_V1)
    # every vaccine lands, not just HPV
    assert {r["vaccine"] for r in raw} == {"HPV", "Tetanus"}
    # the suppression sentinel is landed as literal text, not parsed away
    suppressed = next(r for r in raw if r["geography"] == "TX-El Paso County")
    assert suppressed["coverage_estimate"] == "NA"
    assert suppressed["ci_95"] is None and suppressed["sample_size"] is None  # blank -> NULL

    # re-landing byte-identical content is a no-op (SPEC.md's vintage rule)
    v2, n2 = teenvaxview.land_raw(cat, "2026.10", vintage="2026-10-01", url=csv_v1)
    assert v2 is None and n2 == 0
    assert len(rows(cat, "raw.teenvaxview__coverage")) == len(DATA_V1)
    manifest_rows = rows(cat, "provenance.release", row_filter="source = 'teenvaxview'")
    assert len(manifest_rows) == 1 and manifest_rows[0]["checksum"]


def test_a_changed_header_fails_before_landing(cat, tmp_path):
    bad = tmp_path / "bad.csv"
    header = [c for c in teenvaxview.COLUMNS if c != "Sample Size"]
    bad.write_text(",".join(header) + "\n")
    with pytest.raises(SystemExit, match="Sample Size"):
        teenvaxview.land_raw(cat, REL, vintage="2026-09-01", url=str(bad))


def test_derives_hpv_measures_only(cat, csv_v1):
    counts = teenvaxview.ingest(cat, REL, vintage="2026-09-01", url=csv_v1)
    assert counts["raw.teenvaxview__coverage"] == len(DATA_V1)

    defs = {d["measure_id"] for d in rows(cat, "measure.definition")}
    assert defs == {"NIS_TEEN:HPV:1dose", "NIS_TEEN:HPV:uptodate"}  # not >=2 Doses

    obs = rows(cat, "measure.observation", row_filter=EqualTo("source", "NIS_TEEN"))
    assert all(o["measure_id"] in defs for o in obs)
    assert all(o["source_release"] == "2026-09-01" for o in obs)


def test_state_and_county_geography(cat, csv_v1):
    teenvaxview.ingest(cat, REL, vintage="2026-09-01", url=csv_v1)
    obs = {(o["measure_id"], o["geo_id"], o["stratum_id"]): o
           for o in rows(cat, "measure.observation", row_filter=EqualTo("source", "NIS_TEEN"))}

    co = next(o for (mid, gid, sid), o in obs.items()
             if mid == "NIS_TEEN:HPV:1dose" and gid == "state:08" and sid.endswith(":total:overall"))
    assert co["value"] == 79.7 and co["lower"] == 77.1 and co["upper"] == 82.2
    assert co["interval_level"] == 0.95 and co["geo_vintage"] == 2020
    assert co["period_start"] == "2018" and co["period_end"] == "2022"
    assert co["denominator"] is None and co["numerator"] is None
    assert co["value_status"] == "reported"

    bexar = next(o for (mid, gid, sid), o in obs.items()
                if mid == "NIS_TEEN:HPV:1dose" and gid == "county:48029")
    assert bexar["value"] == 78.0

    philly = next(o for (mid, gid, sid), o in obs.items()
                 if mid == "NIS_TEEN:HPV:1dose" and gid == "county:42101")
    assert philly["value"] == 87.8  # Philadelphia city == Philadelphia County

    us = next(o for (mid, gid, sid), o in obs.items()
             if mid == "NIS_TEEN:HPV:1dose" and gid == "nation:US")
    assert us["value"] == 73.5


def test_unmapped_geography_stays_in_raw_only(cat, csv_v1, capsys):
    teenvaxview.ingest(cat, REL, vintage="2026-09-01", url=csv_v1)
    obs = rows(cat, "measure.observation", row_filter=EqualTo("source", "NIS_TEEN"))
    geographies = {o["geo_id"] for o in obs}
    assert "county:17031" not in geographies  # IL-City of Chicago is NOT Cook County alone
    assert not any(g is None for g in geographies)

    raw = rows(cat, "raw.teenvaxview__coverage")
    assert any(r["geography"] == "IL-City of Chicago" for r in raw)
    assert any(r["geography"] == "Region 1" for r in raw)

    err = capsys.readouterr().out
    assert "IL-City of Chicago" in err and "Region 1" in err


def test_not_derived_dose_family_stays_in_raw_only(cat, csv_v1):
    teenvaxview.ingest(cat, REL, vintage="2026-09-01", url=csv_v1)
    raw = rows(cat, "raw.teenvaxview__coverage")
    assert any(r["dose"] == "≥2 Doses, Females" for r in raw)

    obs = rows(cat, "measure.observation", row_filter=EqualTo("source", "NIS_TEEN"))
    assert not any(o["value"] == 24.5 for o in obs)  # the >=2 Doses row's value


def test_non_hpv_vaccine_lands_but_is_not_derived(cat, csv_v1):
    teenvaxview.ingest(cat, REL, vintage="2026-09-01", url=csv_v1)
    raw = rows(cat, "raw.teenvaxview__coverage")
    assert any(r["vaccine"] == "Tetanus" for r in raw)
    obs = rows(cat, "measure.observation", row_filter=EqualTo("source", "NIS_TEEN"))
    assert not any(o["value"] == 75.0 for o in obs)  # the Tetanus row's value


def test_suppression_maps_status_and_leaves_value_null(cat, csv_v1):
    teenvaxview.ingest(cat, REL, vintage="2026-09-01", url=csv_v1)
    obs = rows(cat, "measure.observation", row_filter=EqualTo("source", "NIS_TEEN"))
    suppressed = next(o for o in obs if o["geo_id"] == "county:48141")  # TX-El Paso
    assert suppressed["value_status"] == "suppressed_reliability"
    assert suppressed["value"] is None
    assert suppressed["lower"] is None and suppressed["upper"] is None
    assert suppressed["interval_level"] is None

    reported = [o for o in obs if o["value_status"] == "reported"]
    assert all(o["value"] is not None for o in reported)


def test_stratum_fields_by_dimension_type(cat, csv_v1):
    teenvaxview.ingest(cat, REL, vintage="2026-09-01", url=csv_v1)
    strata = {s["stratum_id"]: s for s in rows(cat, "measure.stratum",
                                               row_filter=EqualTo("source", "NIS_TEEN"))}

    overall = next(s for sid, s in strata.items() if sid.endswith(":total:overall"))
    assert overall["sex"] == "Males and Females"
    assert overall["age_group"] is None and overall["race_ethnicity"] is None
    assert overall["other"] is None and overall["scheme"] == "NIS_TEEN_TOTAL"

    age = next(s for s in strata.values() if s["age_group"] == "13-17 Years")
    assert age["scheme"] == "NIS_TEEN_AGE" and age["sex"] in ("Females", "Males and Females")

    insurance = next(s for s in strata.values() if s["other"] == "Insurance Coverage: Uninsured")
    assert insurance["scheme"] == "NIS_TEEN_INSURANCE"
    assert insurance["age_group"] is None and insurance["race_ethnicity"] is None


def test_two_vintages_coexist_and_first_is_not_retired(cat, csv_v1, csv_v2):
    teenvaxview.ingest(cat, REL, vintage="2026-09-01", url=csv_v1)
    teenvaxview.ingest(cat, "2026.10", vintage="2026-09-15", url=csv_v2)

    releases = {o["source_release"] for o in
               rows(cat, "measure.observation", row_filter=EqualTo("source", "NIS_TEEN"))}
    assert releases == {"2026-09-01", "2026-09-15"}

    v1_co = next(o for o in rows(cat, "measure.observation")
                if o["measure_id"] == "NIS_TEEN:HPV:1dose" and o["geo_id"] == "state:08"
                and o["source_release"] == "2026-09-01" and o["stratum_id"].endswith(":total:overall"))
    v2_co = next(o for o in rows(cat, "measure.observation")
                if o["measure_id"] == "NIS_TEEN:HPV:1dose" and o["geo_id"] == "state:08"
                and o["source_release"] == "2026-09-15" and o["stratum_id"].endswith(":total:overall"))
    assert v1_co["value"] == 79.7 and v1_co["valid_to"] is None
    assert v2_co["value"] == 80.1 and v2_co["valid_to"] is None


def test_rerun_is_idempotent(cat, csv_v1):
    teenvaxview.ingest(cat, REL, vintage="2026-09-01", url=csv_v1)
    counts = teenvaxview.transform(cat, "2026.10", "2026-09-01")
    assert counts["measure.observation"]["written"] == 0
    n_obs = len(rows(cat, "measure.observation", row_filter=EqualTo("source", "NIS_TEEN")))
    assert counts["measure.observation"]["unchanged"] == n_obs


def other_observation():
    return dict(source="OTHER", source_release="V0", measure_id="OTHER:x", geo_id="county:99999",
               geo_vintage=2020, period_start="2020", period_end="2020", stratum_id="OTHER:none",
               value=1.0, lower=None, upper=None, interval_level=None, numerator=None,
               denominator=None, value_status="reported", reliability_flag=None, trend=None)


def test_teenvaxview_does_not_retire_another_writer(cat, csv_v1):
    other = pa.Table.from_pylist([other_observation()])
    merge.merge(cat, "measure.observation", other, REL, EqualTo("source", "OTHER"))

    teenvaxview.ingest(cat, REL, vintage="2026-09-01", url=csv_v1)

    live_other = rows(cat, "measure.observation",
                      row_filter="source = 'OTHER' AND valid_to IS NULL")
    assert len(live_other) == 1


def test_unknown_dose_family_raises(cat, tmp_path):
    bad = [line(**{"Vaccine/Sample": "HPV", "Dose": "≥4 Dose, Males and Females",
                  "Geography Type": "States/Local Areas", "Geography": "Colorado",
                  "Survey Year": "2025", "Dimension Type": "Overall", "Dimension": "Overall",
                  "Estimate (%)": "50.0", "95% CI (%)": "45.0 to 55.0", "Sample Size": "100"})]
    csv_path = write(tmp_path / "bad_dose.csv", bad)
    teenvaxview.land_raw(cat, REL, vintage="2026-09-01", url=csv_path)
    with pytest.raises(SystemExit, match="unknown HPV dose family"):
        teenvaxview.transform(cat, REL, "2026-09-01")


def test_unparseable_estimate_raises(cat, tmp_path):
    bad = [line(**{"Vaccine/Sample": "HPV", "Dose": "≥1 Dose, Males and Females",
                  "Geography Type": "States/Local Areas", "Geography": "Colorado",
                  "Survey Year": "2025", "Dimension Type": "Overall", "Dimension": "Overall",
                  "Estimate (%)": "N/A", "95% CI (%)": "", "Sample Size": ""})]
    csv_path = write(tmp_path / "bad_estimate.csv", bad)
    teenvaxview.land_raw(cat, REL, vintage="2026-09-01", url=csv_path)
    with pytest.raises(SystemExit, match="unparseable Estimate"):
        teenvaxview.transform(cat, REL, "2026-09-01")


def test_blank_estimate_is_rejected_at_landing(cat, tmp_path):
    """A genuinely blank Estimate (%) cell lands as SQL NULL (nullstr=''), not
    the 'NA' sentinel text. `coverage_estimate` is declared required=True
    (schemas.py) precisely so this is rejected here, at land_raw, before
    transform ever sees it -- the first of two guards against the
    #132/#136/#141 bug class (an unparseable estimate silently landing as
    value=NULL under value_status='reported'). transform's own
    bad_estimates/value_status guard (test_unparseable_estimate_raises) is
    the second, independent guard: it also checks `coverage_estimate IS
    NULL` explicitly (a plain `!= 'NA'` is NULL-unsafe -- `NULL != 'NA'` is
    NULL, not TRUE, so it would silently miss a NULL row) and derives
    value_status from the very same TRY_CAST that produces `value`, so the
    two can never disagree even if a future landing path relaxes this
    column's nullability."""
    bad = [line(**{"Vaccine/Sample": "HPV", "Dose": "≥1 Dose, Males and Females",
                  "Geography Type": "States/Local Areas", "Geography": "Colorado",
                  "Survey Year": "2025", "Dimension Type": "Overall", "Dimension": "Overall",
                  "95% CI (%)": "", "Sample Size": ""})]  # Estimate (%) omitted -> blank -> NULL
    csv_path = write(tmp_path / "blank_estimate.csv", bad)
    with pytest.raises(ValueError, match="coverage_estimate"):
        teenvaxview.land_raw(cat, REL, vintage="2026-09-01", url=csv_path)


def test_every_column_is_documented(cat, csv_v1):
    teenvaxview.ingest(cat, REL, vintage="2026-09-01", url=csv_v1)
    for identifier in ("raw.teenvaxview__coverage", "measure.definition",
                      "measure.stratum", "measure.observation"):
        table = cat.load_table(identifier)
        assert table.properties.get("comment"), identifier
        for f in table.schema().fields:
            assert f.doc, f"{identifier}.{f.name} has no doc"
