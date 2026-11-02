#!/usr/bin/env python3
"""Parity diff between a locally-supplied Cancer InFocus (CIF) national
archive extraction and the Cancer Basemap release bundle, attached read-only over
HTTPS (see docs/clients/duckdb-cli.md).

Usage:
    uv run --with duckdb python recipes/cif_parity.py --cif-dir cif/stats --states 08,21

Only prints aggregate comparison stats (n compared, n exact, n within
rounding, n differing + max abs diff, n one-side-only) -- never dumps raw CIF
cell values, so its output is safe to paste into a public report.

**No CIF data is ever committed, stored, or redistributed by this script or
this repo.** It reads a CIF archive from a local path the caller supplies at
run time (the user's own download) and discards it after printing aggregates.
CIF's own `instructions.txt` (https://cancerinfocus.org/public-data/instructions.txt,
checked 2026-09-19) documents exactly this local download-and-read use: "All
of the zip files available on https://cancerinfocus.org are also available
for direct download through https://cancerinfocus.org/public-data ... Sample
code for downloading and unzipping files is posted as
`sample_zip_download_code.R`." No separate terms-of-use or redistribution
notice exists on that download path; distinct from CIF's *gatherer* code
(CIFTools), which is licensed separately and is not used here at all -- this
script only reads CIF's published output files.

ponytail: one flat script, no framework -- this is a one-shot analytical
recipe, not a library. Promote to a scheduled check later if parity needs to
run on a cadence; for now this *is* the runnable check.
"""
import argparse
import glob
import os
import sys

import duckdb

BUNDLE_URL = "https://basemap.cancerdatasci.org/data/latest/cancerbasemap.duckdb"

# geography.unit carries one row per (geo_id, boundary vintage) -- e.g.
# county:08001 appears for TIGER vintages 2010/2020/2026 -- so joining
# straight to geo_id triples every observation row. Collapse to one fips per
# geo_id first; shared by the module and its offline test.
GEO_FIPS_VIEW_SQL = (
    "CREATE OR REPLACE TEMP VIEW geo_fips AS "
    "SELECT DISTINCT geo_id, level, fips FROM cbm.geography.unit"
)

# CIF rf_and_screening measure -> lake PLACES topic code (both are CDC PLACES
# short codes; CIF just re-cases/renames them).
PLACES_MAP = {
    "Cancer_Prevalence": "CANCER",
    "Binge_Drinking": "BINGE",
    "Met_Breast_Screen": "MAMMOUSE",
    "BMI_Obese": "OBESITY",
    "Currently_Smoke": "CSMOKING",
    "Met_Colon_Screen": "COLON_SCREEN",
    "High_BP": "BPHIGH",
    "BP_Medicine": "BPMED",
    "High_Cholesterol": "HIGHCHOL",
    "Asthma": "CASTHMA",
    "CHD": "CHD",
    "Recent_Checkup": "CHECKUP",
    "COPD": "COPD",
    "Recent_Dentist": "DENTAL",
    "Depression": "DEPRESSION",
    "Diabetes_DX": "DIABETES",
    "Bad_Health": "GHLTH",
    "Physically_Inactive": "LPA",
    "Poor_Mental": "MHLTH",
    "Poor_Physical": "PHLTH",
    "Sleep_Debt": "SLEEP",
    "Had_Stroke": "STROKE",
    "No_Teeth": "TEETHLOST",
    "Hearing_Disability": "HEARING",
    "Vision_Disability": "VISION",
    "Cognitive_Disability": "COGNITION",
    "Mobility_Disability": "MOBILITY",
    "Selfcare_Disability": "SELFCARE",
    "Independent_Living_Disability": "INDEPLIVE",
    "Socially_Isolated": "ISOLATION",
    "Food_Insecure": "FOODINSECU",
    "Housing_Insecure": "HOUSINSECU",
    "Lacked_Reliable_Transportation": "LACKTRPT",
    "Lacked_Social_Emotional_Support": "EMOTIONSPT",
}

# CIF SVI theme measure -> lake RPL theme number (2010-2020 SVI theme order;
# 2022 CDC/ATSDR relabeled the theme *names* but kept the same 1-4 order).
SVI_MAP = {
    "SVI_SES": "THEME1",
    "SVI_Household": "THEME2",
    "SVI_Minority": "THEME3",
    "SVI_Housing": "THEME4",
    "SVI_Overall": "THEMES",
}

# CIF urban/rural measure -> lake RUCA key (tract level). Same long-format
# convention (FIPS, measure, value) as CIF's other three files diffed below;
# not verified against a real archive (none was available in this session).
# If the real column/file layout differs, compare_ruca raises and main()
# reports it as an "error" field like any other failed comparison, never
# silently wrong.
RUCA_MAP = {
    "PrimaryRUCA": "primary",
    "SecondaryRUCA": "secondary",
}


def connect():
    con = duckdb.connect()
    con.execute(f"ATTACH '{BUNDLE_URL}' AS cbm (READ_ONLY)")
    con.execute(GEO_FIPS_VIEW_SQL)
    return con


def find(cif_dir, pattern):
    hits = glob.glob(os.path.join(cif_dir, pattern))
    if not hits:
        raise FileNotFoundError(f"no file matching {pattern} in {cif_dir}")
    return hits[0]


def summarize(con, cif_rows_sql, lake_rows_sql, round_ndp=1, label=""):
    """cif_rows_sql / lake_rows_sql must each yield (fips, key, value). key is
    whatever ties a CIF row to a lake row (measure code, facility grouping,
    etc). Returns a dict of aggregate counts -- no raw values."""
    con.execute(f"CREATE OR REPLACE TEMP TABLE _cif AS {cif_rows_sql}")
    con.execute(f"CREATE OR REPLACE TEMP TABLE _lake AS {lake_rows_sql}")
    n_cif = con.execute("SELECT count(*) FROM _cif").fetchone()[0]
    n_lake = con.execute("SELECT count(*) FROM _lake").fetchone()[0]
    joined = con.execute(
        """
        SELECT c.fips, c.key, c.value AS cif_value, l.value AS lake_value
        FROM _cif c FULL OUTER JOIN _lake l USING (fips, key)
        """
    ).fetchall()
    n_both = n_exact = n_round = n_diff = n_cif_only = n_lake_only = 0
    max_abs_diff = 0.0
    for fips, key, cv, lv in joined:
        if cv is None:
            n_lake_only += 1
            continue
        if lv is None:
            n_cif_only += 1
            continue
        n_both += 1
        d = abs(cv - lv)
        if d == 0:
            n_exact += 1
        elif d <= 0.5 * (10 ** -round_ndp):
            n_round += 1
        else:
            n_diff += 1
            max_abs_diff = max(max_abs_diff, d)
    return {
        "label": label,
        "n_cif_cells": n_cif,
        "n_lake_cells": n_lake,
        "n_compared": n_both,
        "n_exact": n_exact,
        "n_within_rounding": n_round,
        "n_different": n_diff,
        "max_abs_diff": round(max_abs_diff, 4),
        "n_cif_only": n_cif_only,
        "n_lake_only": n_lake_only,
    }


def compare_places(con, cif_dir, states):
    f = find(cif_dir, "us_rf_and_screening_county_long_*.csv")
    state_list = ",".join(f"'{s}'" for s in states)
    case = " ".join(f"WHEN '{k}' THEN '{v}'" for k, v in PLACES_MAP.items())
    cif_sql = f"""
        SELECT FIPS AS fips,
               CASE measure {case} END AS key,
               value * 100 AS value
        FROM read_csv_auto('{f}')
        WHERE substr(FIPS,1,2) IN ({state_list})
          AND CASE measure {case} END IS NOT NULL
    """
    # CIF stores PLACES prevalence as a 0-1 fraction; the lake stores 0-100
    # percent -- hence the *100 above.
    lake_sql = f"""
        SELECT fips, replace(measure_id,'PLACES:','') AS key0, value
        FROM cbm.measure.observation o
        JOIN geo_fips g ON o.geo_id = g.geo_id
        WHERE o.source='PLACES' AND o.source_release='2024'
          AND g.level='county' AND substr(g.fips,1,2) IN ({state_list})
          AND o.measure_id LIKE '%:crude'
    """
    # strip the trailing ':crude' to get the bare topic code as `key`
    lake_sql = f"SELECT fips, replace(key0, ':crude','') AS key, value FROM ({lake_sql})"
    return summarize(con, cif_sql, lake_sql, round_ndp=1,
                      label="PLACES risk factors & screening (county, crude, CIF 2024 vintage vs lake source_release=2024)")


def compare_svi(con, cif_dir, states):
    f = find(cif_dir, "us_svi_county_long_*.csv")
    state_list = ",".join(f"'{s}'" for s in states)
    case = " ".join(f"WHEN '{k}' THEN '{v}'" for k, v in SVI_MAP.items())
    cif_sql = f"""
        SELECT FIPS AS fips, CASE measure {case} END AS key, value
        FROM read_csv_auto('{f}')
        WHERE substr(FIPS,1,2) IN ({state_list}) AND CASE measure {case} END IS NOT NULL
    """
    # lake's newest SVI *composite theme* vintage is 2020 (RPL_THEME*:2020);
    # CIF's dictionary says "CDC/ATSDR, 2024" -- no lake vintage matches that
    # label, so we compare against the newest lake has and flag the gap in
    # the report rather than silently forcing a match.
    lake_sql = f"""
        SELECT g.fips, replace(replace(o.measure_id,'SVI:RPL_',''),':2020','') AS key, o.value
        FROM cbm.measure.observation o
        JOIN geo_fips g ON o.geo_id = g.geo_id
        WHERE o.source='SVI' AND o.source_release='2022'
          AND g.level='county' AND substr(g.fips,1,2) IN ({state_list})
          AND o.measure_id LIKE 'SVI:RPL_%:2020'
    """
    return summarize(con, cif_sql, lake_sql, round_ndp=4,
                      label="SVI theme percentiles (county, CIF 'CDC/ATSDR 2024' vs lake newest carried vintage: source_release=2022 rows of the 2020 theme scores -- vintages do not line up, see report)")


def compare_fara(con, cif_dir, states):
    f = find(cif_dir, "us_food_desert_tract_long_*.csv")
    state_list = ",".join(f"'{s}'" for s in states)
    cif_sql = f"""
        SELECT FIPS AS fips, 'LILATracts_Vehicle' AS key, value
        FROM read_csv_auto('{f}')
        WHERE substr(FIPS,1,2) IN ({state_list}) AND measure = 'LILATracts_Vehicle'
    """
    lake_sql = f"""
        SELECT g.fips, 'LILATracts_Vehicle' AS key, o.value
        FROM cbm.measure.observation o
        JOIN geo_fips g ON o.geo_id = g.geo_id
        WHERE o.source='FARA' AND o.source_release='2019'
          AND g.level='tract' AND substr(g.fips,1,2) IN ({state_list})
          AND o.measure_id = 'FARA:LILATracts_Vehicle'
    """
    return summarize(con, cif_sql, lake_sql, round_ndp=0,
                      label="USDA FARA LILATracts_Vehicle (tract, CIF 'USDA ERS 2025' vs lake source_release=2019 -- CIF's cited vintage is newer than anything the lake carries, see report)")


def compare_rucc(con, cif_dir, states):
    f = find(cif_dir, "us_urb_county_long_*.csv")
    state_list = ",".join(f"'{s}'" for s in states)
    cif_sql = f"""
        SELECT FIPS AS fips, 'code' AS key, value
        FROM read_csv_auto('{f}')
        WHERE substr(FIPS,1,2) IN ({state_list}) AND measure = 'RUCC'
    """
    lake_sql = f"""
        SELECT g.fips, 'code' AS key, o.value
        FROM cbm.measure.observation o
        JOIN geo_fips g ON o.geo_id = g.geo_id
        WHERE o.source='RUCC' AND o.source_release='2023'
          AND g.level='county' AND substr(g.fips,1,2) IN ({state_list})
          AND o.measure_id = 'RUCC:code'
    """
    return summarize(con, cif_sql, lake_sql, round_ndp=0,
                      label="USDA RUCC rural-urban continuum code (county, lake source_release=2023; CIF file layout assumed, not verified against a real archive)")


def compare_ruca(con, cif_dir, states):
    f = find(cif_dir, "us_urb_tract_long_*.csv")
    state_list = ",".join(f"'{s}'" for s in states)
    case = " ".join(f"WHEN '{k}' THEN '{v}'" for k, v in RUCA_MAP.items())
    cif_sql = f"""
        SELECT FIPS AS fips, CASE measure {case} END AS key, value
        FROM read_csv_auto('{f}')
        WHERE substr(FIPS,1,2) IN ({state_list}) AND CASE measure {case} END IS NOT NULL
    """
    # CIF's tract file carries no separate edition label; matched against the
    # lake's newest RUCA edition (2020), same "newest carried vintage"
    # convention as compare_svi.
    lake_sql = f"""
        SELECT g.fips, replace(o.measure_id,'RUCA:','') AS key, o.value
        FROM cbm.measure.observation o
        JOIN geo_fips g ON o.geo_id = g.geo_id
        WHERE o.source='RUCA' AND o.source_release='2020'
          AND g.level='tract' AND substr(g.fips,1,2) IN ({state_list})
          AND o.measure_id IN ('RUCA:primary','RUCA:secondary')
    """
    return summarize(con, cif_sql, lake_sql, round_ndp=0,
                      label="USDA RUCA rural-urban commuting area code (tract, primary+secondary, lake source_release=2020; CIF file layout assumed, not verified against a real archive)")


def compare_facilities(con, cif_dir, states, cif_type, lake_kind, label):
    f = find(cif_dir, "us_facilities_and_providers_*.csv")
    state_abbrev = {"08": "CO", "21": "KY"}
    abbrevs = ",".join(f"'{state_abbrev[s]}'" for s in states if s in state_abbrev)
    cif_counts = con.execute(f"""
        SELECT State, count(*) FROM read_csv_auto('{f}')
        WHERE Type = '{cif_type}' AND State IN ({abbrevs})
        GROUP BY 1 ORDER BY 1
    """).fetchall()
    # Lake facility.site geo_id is populated for HRSA-sourced kinds (fqhc)
    # but NULL for the FDA MQSA mammography extract -- that extract hasn't
    # been geo-joined to a county/tract yet (a real gap, noted in the
    # report). Fall back to the state carried in attributes_json for that
    # case so the comparison still runs.
    state_case = " ".join(f"WHEN '{k}' THEN '{v}'" for k, v in state_abbrev.items())
    lake_counts = con.execute(f"""
        SELECT
            COALESCE(CASE substr(g.fips,1,2) {state_case} END,
                     json_extract_string(s.attributes_json, '$.state')) AS st,
            count(*)
        FROM cbm.facility.site s LEFT JOIN geo_fips g ON s.geo_id = g.geo_id
        WHERE s.kind = '{lake_kind}'
        GROUP BY 1 HAVING st IN ({abbrevs}) ORDER BY 1
    """).fetchall()
    return {"label": label, "cif_counts_by_state": cif_counts, "lake_counts_by_state": lake_counts}


def run(con, cif_dir, states):
    """All comparisons against an already-attached `con` (real ATTACH in
    main(), or a stubbed `cbm` schema in the offline test). Returns the list
    of result dicts main() prints -- factored out so the test can assert on
    it directly instead of scraping stdout."""
    results = []
    for fn in (compare_places, compare_svi, compare_fara, compare_rucc, compare_ruca):
        try:
            results.append(fn(con, cif_dir, states))
        except Exception as e:
            results.append({"label": fn.__name__, "error": str(e)})

    for label, cif_type, lake_kind in [
        ("FQHC sites", "FQHC", "fqhc"),
        ("Mammography facilities", "Mammography", "mammography"),
    ]:
        results.append(compare_facilities(con, cif_dir, states, cif_type, lake_kind, label))
    return results


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cif-dir", required=True, help="directory holding the extracted CIF us.zip CSVs")
    ap.add_argument("--states", required=True, help="comma-separated 2-digit state FIPS to compare, e.g. 08,21")
    args = ap.parse_args()
    states = args.states.split(",")

    con = connect()
    for r in run(con, args.cif_dir, states):
        print("=" * 70)
        for k, v in r.items():
            print(f"{k}: {v}")


if __name__ == "__main__":
    sys.exit(main())
