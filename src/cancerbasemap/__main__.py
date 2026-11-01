import argparse
from pathlib import Path

from . import catalog, census_gazetteer, merge, publish, schemas


def _print(counts):
    for name, c in counts.items():
        print(f"{name:40} {c['written']:>10,} written  {c['unchanged']:>10,} unchanged"
              if isinstance(c, dict) else f"{name:40} {c:>10,} rows")


def main():
    p = argparse.ArgumentParser(prog="cancerbasemap")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="create every declared namespace and table")
    sub.add_parser("tables", help="list catalog tables")

    # core: sort-on-write layout (#120)
    rw = sub.add_parser("rewrite", help="one-time PyIceberg-only rewrite of a live table onto "
                        "its current sort_by / row-group-limit properties (#120)")
    rw.add_argument("identifier", nargs="?", help="table to rewrite, e.g. measure.observation")
    rw.add_argument("--all", action="store_true", help="rewrite every declared table")

    # core: release bundle (ADR-0001, #171)
    pb = sub.add_parser("publish", help="build a release bundle (Parquet, views.sql, "
                        "manifest.json) from the live catalog; uploads nothing")
    pb.add_argument("out", help="directory to write the bundle into")
    pb.add_argument("--base-url", dest="base_url", default=publish.DEFAULT_BASE_URL,
                    help="where the bundle's views will read it from "
                         "(default: %(default)s; a dated folder passes its own /data/v{date})")
    pb.add_argument("--only", nargs="+", help="publish only these tables, e.g. measure.observation")

    # --- raw: census gazetteer ---
    gz = sub.add_parser("gazetteer", help="land one Census Gazetteer vintage's county + "
                        "tract files, then derive geography.unit")
    gz.add_argument("--release", required=True, help="Cancer Basemap release, e.g. 2026.09")
    gz.add_argument("--year", required=True, type=int, help="gazetteer vintage year, e.g. 2024")
    gz.add_argument("--county-url", help="an already-downloaded counties zip/txt; skips download")
    gz.add_argument("--tract-url", help="an already-downloaded tracts zip/txt; skips download")
    gz.add_argument("--state-url", help="an already-downloaded state.txt; skips download")

    # --- raw: census gazetteer districts ---
    # Congressional and state legislative districts (#104).
    gd = sub.add_parser("gazetteer-districts", help="land one gazetteer vintage's CD/SLDU/SLDL "
                        "files, then derive geography.unit (a year with no known Congress number "
                        "lands SLDU/SLDL only)")
    gd.add_argument("--release", required=True, help="Cancer Basemap release, e.g. 2026.09")
    gd.add_argument("--year", required=True, type=int, help="gazetteer vintage year, e.g. 2024")
    gd.add_argument("--cd-url", help="an already-downloaded CD zip/txt; skips download")
    gd.add_argument("--sldu-url", help="an already-downloaded SLDU zip/txt; skips download")
    gd.add_argument("--sldl-url", help="an already-downloaded SLDL zip/txt; skips download")

    # --- raw: cdc places ---
    from . import places
    pl = sub.add_parser("places", help="land a CDC PLACES county-data release, then derive")
    pl.add_argument("--release", required=True, help="Cancer Basemap release, e.g. 2026.09")
    pl.add_argument("--places-release", dest="places_release",
                    choices=sorted(set(places.RELEASES) | set(places.TRACT_RELEASES)),
                    help="PLACES release year (default: latest known for --level)")
    pl.add_argument("--level", choices=("county", "tract"), default="county",
                    help="geography level to land (default: county) (#30)")
    pl.add_argument("--url", help="an already-downloaded CSV file or alternate URL")

    # --- raw: usda ers rucc ---
    from . import ers_rucc
    rc = sub.add_parser("rucc", help="land the USDA ERS Rural-Urban Continuum Codes, then derive")
    rc.add_argument("--release", required=True, help="Cancer Basemap release, e.g. 2026.09")
    rc.add_argument("--url", help="an already-downloaded CSV file or alternate URL")

    # --- derived: geography alias ---
    # geography.alias — FIPS renames and recodes that are not boundary changes (#26).
    from . import geography_alias
    ga = sub.add_parser("geo-alias", help="land the curated county-recode CSV, then derive "
                        "geography.alias")
    ga.add_argument("--release", required=True, help="Cancer Basemap release, e.g. 2026.09")
    ga.add_argument("--path", help="an alternate curated CSV; defaults to the packaged one")

    # --- derived: measure cancer site ---
    from . import cancer_site
    cs = sub.add_parser("cancer-site", help="land the SEER site recode + cause-of-death recode, "
                        "then derive measure.cancer_site")
    cs.add_argument("--release", required=True, help="Cancer Basemap release, e.g. 2026.09")
    cs.add_argument("--site-url", help="an already-downloaded site-recode text file or alternate URL")
    cs.add_argument("--cod-url", help="an already-downloaded cause-of-death recode text file or alternate URL")

    # --- derived: measure cancer site group ---
    # Prevention-lens groupings over measure.cancer_site (#126).
    from . import cancer_site_group
    cg = sub.add_parser("cancer-site-group", help="land the curated cancer-site groupings CSV, "
                        "then derive measure.cancer_site_group (requires measure.cancer_site "
                        "already landed by `cancer-site`)")
    cg.add_argument("--release", required=True, help="Cancer Basemap release, e.g. 2026.09")
    cg.add_argument("--path", help="an alternate curated CSV; defaults to the packaged one")

    # --- raw: cdc atsdr svi ---
    from . import cdc_svi
    sv = sub.add_parser("svi", help="land one CDC/ATSDR SVI edition's county or tract "
                        "file, then derive")
    sv.add_argument("--release", required=True, help="Cancer Basemap release, e.g. 2026.09")
    sv.add_argument("--edition", choices=sorted(cdc_svi.EDITIONS, key=int),
                    help="SVI edition (default: latest known)")
    sv.add_argument("--level", choices=("county", "tract"), default="county",
                    help="geography level to land (default: county; tract is only "
                         f"landed for {cdc_svi.TRACT_EDITIONS})")
    sv.add_argument("--url", help="an already-downloaded CSV file or alternate URL")

    # --- raw: usda ers ruca ---
    from . import ers_ruca
    ru = sub.add_parser("ruca", help="land a USDA ERS RUCA tract edition, then derive")
    ru.add_argument("--release", required=True, help="Cancer Basemap release, e.g. 2026.09")
    ru.add_argument("--edition", choices=sorted(ers_ruca.EDITIONS),
                    help="RUCA edition (default: latest known)")
    ru.add_argument("--url", help="an already-downloaded file or alternate URL")

    # --- raw: usda ers food access ---
    from . import ers_food_access
    fa = sub.add_parser("food-access", help="land a USDA ERS Food Access Research Atlas "
                        "edition, then derive")
    fa.add_argument("--release", required=True, help="Cancer Basemap release, e.g. 2026.09")
    fa.add_argument("--edition", choices=sorted(ers_food_access.EDITIONS),
                    help="atlas edition (default: latest known)")
    fa.add_argument("--url", help="an already-downloaded zip/csv/xlsx file or alternate URL")

    # --- raw: hrsa ahrf ---
    # HRSA Area Health Resources Files, county (#39).
    from . import hrsa_ahrf
    ah = sub.add_parser("ahrf", help="land the HRSA Area Health Resources Files (county), then derive")
    ah.add_argument("--release", required=True, help="Cancer Basemap release, e.g. 2026.09")
    ah.add_argument("--ahrf-release", dest="ahrf_release", choices=sorted(hrsa_ahrf.RELEASES),
                    help="AHRF release, e.g. 2024-2025 (default: latest known)")
    ah.add_argument("--csv-url", help="an already-downloaded AHRF county CSV (or its zip); "
                    "skips download")
    ah.add_argument("--techdoc-url", help="an already-downloaded technical documentation "
                    "xlsx (or its zip); skips download")

    # --- raw: hrsa hpsa and health centers ---
    # HRSA HPSA designations and health-center sites; declares facility.site (#38).
    from . import hrsa_sites
    hs = sub.add_parser("hrsa-sites", help="land HRSA health-center sites + primary-care HPSA "
                        "designations, then derive facility.site and county HPSA measures")
    hs.add_argument("--release", required=True, help="Cancer Basemap release, e.g. 2026.09")
    hs.add_argument("--hc-url", dest="hc_url", help="an already-downloaded health-center sites CSV or alternate URL")
    hs.add_argument("--hpsa-url", dest="hpsa_url", help="an already-downloaded HPSA primary-care CSV or alternate URL")
    hs.add_argument("--retrieved-on", dest="retrieved_on",
                    help="ISO date to record as the version (default: today)")

    # --- raw: state cancer profiles ---
    # State Cancer Profiles, all vintages (#27).
    from . import scp
    sc = sub.add_parser("scp", help="land one State Cancer Profiles vintage (all its "
                        "topics), then derive incidence/mortality")
    sc.add_argument("--release", required=True, help="Cancer Basemap release, e.g. 2026.09")
    sc.add_argument("--vintage", choices=sorted(scp.VINTAGES), help="SCP vintage "
                    "(default: latest known)")

    # --- raw: census acs ---
    # ACS 5-year, the Cancer InFocus indicator subset (#29).
    # The local `from . import <module>` and the subparser goes directly under this comment block.
    # Leave this marker and the blank lines around it untouched so
    # independent branches merge cleanly.
    from . import census_acs
    acs = sub.add_parser("acs", help="land a Census ACS 5-year Summary File release's county "
                         "or tract detailed tables, then derive the CIF-parity indicator subset")
    acs.add_argument("--release", required=True, help="Cancer Basemap release, e.g. 2026.09")
    acs.add_argument("--year", required=True, type=int,
                     help="ACS 5-year release end year (e.g. 2023 for the 2019-2023 release)")
    acs.add_argument("--level", required=True, choices=("county", "tract"),
                     help="geography level to land")
    acs.add_argument("--dat-dir", dest="dat_dir",
                     help="a directory of already-downloaded acsdt5y<year>-<table>.dat files; "
                          "skips downloading")

    # --- raw: cdc places tract ---
    # CDC PLACES tract releases (#30).
    # The local `from . import <module>` and the subparser goes directly under this comment block.
    # Leave this marker and the blank lines around it untouched so
    # independent branches merge cleanly.

    # --- raw: fda mqsa ---
    # FDA MQSA certified mammography facilities (#36).
    from . import fda_mqsa
    mq = sub.add_parser("mqsa", help="land the weekly FDA MQSA certified facility list, "
                        "then derive facility.site")
    mq.add_argument("--release", required=True, help="Cancer Basemap release, e.g. 2026.09")
    mq.add_argument("--url", help="an already-downloaded zip/txt file or alternate URL")
    mq.add_argument("--retrieved-on", dest="retrieved_on",
                    help="ISO date to record as the version (default: today)")

    # --- raw: epa sdwis ---
    from . import epa_sdwis
    sd = sub.add_parser("sdwis", help="land one EPA SDWIS quarterly SDWA bulk download, "
                        "then derive county-year health-based violation counts")
    sd.add_argument("--release", required=True, help="Cancer Basemap release, e.g. 2026.09")
    sd.add_argument("--url", help="an already-downloaded SDWA zip file or alternate URL")
    sd.add_argument("--pws-url", dest="pws_url", help="an already-downloaded pub_water_systems CSV")
    sd.add_argument("--geo-url", dest="geo_url", help="an already-downloaded geographic_areas CSV")
    sd.add_argument("--viol-url", dest="viol_url", help="an already-downloaded violations_enforcement CSV")
    sd.add_argument("--ansi-url", dest="ansi_url", help="an already-downloaded ref_ansi_areas CSV")

    # --- raw: fcc broadband ---
    # FCC Broadband Data Collection (#54).
    # The local `from . import <module>` and the subparser goes directly under this comment block.
    # Leave this marker and the blank lines around it untouched so
    # independent branches merge cleanly.

    # --- raw: epa ejscreen ---
    # EPA EJScreen, every archived edition (#97).
    from . import ejscreen
    ej = sub.add_parser("ejscreen", help="land one EPA EJScreen edition's block group "
                        "or tract file, then derive (tract only)")
    ej.add_argument("--release", required=True, help="Cancer Basemap release, e.g. 2026.09")
    ej.add_argument("--edition", choices=sorted(ejscreen.EDITIONS, key=int),
                    help="EJScreen edition (default: latest known)")
    ej.add_argument("--level", choices=("blockgroup", "tract"), default="blockgroup",
                    help="geography level to land (default: blockgroup; tract is only "
                         f"landed for {ejscreen.TRACT_EDITIONS})")
    ej.add_argument("--url", help="an already-downloaded CSV/zip file or alternate URL")

    # --- raw: bls laus ---
    # BLS Local Area Unemployment Statistics, county (#94).
    from . import bls_laus
    bl = sub.add_parser("laus", help="land a BLS LAUS county retrieval vintage, then derive")
    bl.add_argument("--release", required=True, help="Cancer Basemap release, e.g. 2026.09")
    bl.add_argument("--county-url", dest="county_url",
                    help="an already-downloaded la.data.64.County file or alternate URL")
    bl.add_argument("--area-url", dest="area_url", help="an already-downloaded la.area file or alternate URL")
    bl.add_argument("--series-url", dest="series_url", help="an already-downloaded la.series file or alternate URL")
    bl.add_argument("--measure-url", dest="measure_url", help="an already-downloaded la.measure file or alternate URL")
    bl.add_argument("--footnote-url", dest="footnote_url", help="an already-downloaded la.footnote file or alternate URL")
    bl.add_argument("--vintage", help="ISO date to record as the version (default: today)")
    bl.add_argument("--since", type=int,
                    help="derive years >= this (default: this year minus 10)")

    # --- raw: cdc teenvaxview ---
    # CDC TeenVaxView / NIS-Teen HPV vaccination coverage (#105).
    from . import teenvaxview
    tv = sub.add_parser("teenvax", help="land the CDC TeenVaxView / NIS-Teen vaccination "
                        "coverage file, then derive HPV measures")
    tv.add_argument("--release", required=True, help="Cancer Basemap release, e.g. 2026.09")
    tv.add_argument("--vintage", help="ISO date to record as the version (default: today)")
    tv.add_argument("--url", help="an already-downloaded CSV file or alternate URL")

    # --- raw: epa airtoxscreen ---
    # EPA AirToxScreen tract-level modeled cancer risk (#98).
    from . import epa_airtoxscreen
    at = sub.add_parser("airtoxscreen", help="land one AirToxScreen assessment year's "
                        "source-group and pollutant files, then derive")
    at.add_argument("--release", required=True, help="Cancer Basemap release, e.g. 2026.09")
    at.add_argument("--year", choices=sorted(epa_airtoxscreen.YEARS, key=int),
                    help="assessment year (default: latest known)")
    at.add_argument("--srcgrp-url", dest="srcgrp_url",
                    help="an already-downloaded source-group xlsx file or alternate URL")
    at.add_argument("--pollutant-url", dest="pollutant_url",
                    help="an already-downloaded pollutant xlsx file or alternate URL")

    # --- raw: epa tri ---
    # EPA Toxics Release Inventory Basic Data Files (#100).
    from . import epa_tri
    tr = sub.add_parser("tri", help="land one EPA TRI Basic Data Files reporting year, then "
                        "derive facility.site (kind='tri') and county-year release totals")
    tr.add_argument("--release", required=True, help="Cancer Basemap release, e.g. 2026.09")
    tr.add_argument("--year", required=True, type=int, help="reporting year, e.g. 2023")
    tr.add_argument("--url", help="an already-downloaded CSV file or alternate URL")
    tr.add_argument("--retrieved-on", dest="retrieved_on",
                    help="ISO date to record as the version (default: today)")

    # --- raw: epa radon zones ---
    # EPA Map of Radon Zones, county (#101).
    from . import epa_radon
    rz = sub.add_parser("radon", help="land the EPA Map of Radon Zones (county), then derive")
    rz.add_argument("--release", required=True, help="Cancer Basemap release, e.g. 2026.09")
    rz.add_argument("--url", help="an already-downloaded .xls file or alternate URL")

    # --- raw: epa superfund npl ---
    # EPA Superfund National Priorities List sites (#99); extends facility.site with kind='superfund'.
    from . import epa_superfund
    sf = sub.add_parser("superfund", help="land EPA Superfund NPL site status + FRS FIPS "
                        "lookup, then derive facility.site")
    sf.add_argument("--release", required=True, help="Cancer Basemap release, e.g. 2026.09")
    sf.add_argument("--status-url", dest="status_url",
                    help="an already-downloaded NPL status JSON file or alternate URL")
    sf.add_argument("--frs-url", dest="frs_url",
                    help="an already-downloaded FRS SEMS_NPL JSON file or alternate URL")
    sf.add_argument("--retrieved-on", dest="retrieved_on",
                    help="ISO date to record as the version (default: today)")

    args = p.parse_args()

    if args.cmd == "publish":
        publish.publish(publish.connect(), Path(args.out), args.base_url, args.only)
        return

    cat = catalog()
    if args.cmd == "init":
        for identifier in schemas.TABLES:
            schemas.create(cat, identifier)
        print(f"created {len(schemas.TABLES)} tables across {len(schemas.NAMESPACES)} namespaces")

    # core: sort-on-write layout (#120)
    elif args.cmd == "rewrite":
        if not args.all and not args.identifier:
            p.error("rewrite needs an identifier, or --all")
        identifiers = list(schemas.TABLES) if args.all else [args.identifier]
        for identifier in identifiers:
            print(f"rewriting {identifier}...")
            merge.rewrite(cat, identifier)
        print(f"rewrote {len(identifiers)} table(s)")

    # --- raw: census gazetteer ---
    elif args.cmd == "gazetteer":
        _print(census_gazetteer.ingest(cat, args.release, args.year,
                                       args.county_url, args.tract_url, args.state_url))

    # --- raw: census gazetteer districts ---
    elif args.cmd == "gazetteer-districts":
        _print(census_gazetteer.ingest_districts(cat, args.release, args.year,
                                                  args.cd_url, args.sldu_url, args.sldl_url))

    # --- raw: cdc places ---
    elif args.cmd == "places":
        _print(places.ingest(cat, args.release, args.places_release, args.url, args.level))

    # --- raw: usda ers rucc ---
    elif args.cmd == "rucc":
        _print(ers_rucc.ingest(cat, args.release, args.url))

    # --- derived: geography alias ---
    elif args.cmd == "geo-alias":
        _print(geography_alias.ingest(cat, args.release, args.path))

    # --- derived: measure cancer site ---
    elif args.cmd == "cancer-site":
        _print(cancer_site.ingest(cat, args.release, args.site_url, args.cod_url))

    # --- derived: measure cancer site group ---
    # Prevention-lens groupings over measure.cancer_site (#126).
    elif args.cmd == "cancer-site-group":
        _print(cancer_site_group.ingest(cat, args.release, args.path))

    # --- raw: cdc atsdr svi ---
    elif args.cmd == "svi":
        _print(cdc_svi.ingest(cat, args.release, args.edition, args.level, args.url))

    # --- raw: usda ers ruca ---
    elif args.cmd == "ruca":
        _print(ers_ruca.ingest(cat, args.release, args.edition, args.url))

    # --- raw: usda ers food access ---
    elif args.cmd == "food-access":
        _print(ers_food_access.ingest(cat, args.release, args.edition, args.url))

    # --- raw: hrsa ahrf ---
    # HRSA Area Health Resources Files, county (#39).
    elif args.cmd == "ahrf":
        _print(hrsa_ahrf.ingest(cat, args.release, args.ahrf_release, args.csv_url,
                                args.techdoc_url))

    # --- raw: hrsa hpsa and health centers ---
    # HRSA HPSA designations and health-center sites; declares facility.site (#38).
    elif args.cmd == "hrsa-sites":
        _print(hrsa_sites.ingest(cat, args.release, args.hc_url, args.hpsa_url, args.retrieved_on))

    # --- raw: state cancer profiles ---
    # State Cancer Profiles, all vintages (#27).
    elif args.cmd == "scp":
        _print(scp.ingest(cat, args.release, args.vintage))

    # --- raw: census acs ---
    # ACS 5-year, the Cancer InFocus indicator subset (#29).
    # The `elif args.cmd == ...` dispatch branch goes directly under this comment block.
    # Leave this marker and the blank lines around it untouched so
    # independent branches merge cleanly.
    elif args.cmd == "acs":
        _print(census_acs.ingest(cat, args.release, args.year, args.level, args.dat_dir))

    # --- raw: cdc places tract ---
    # CDC PLACES tract releases (#30).
    # The `elif args.cmd == ...` dispatch branch goes directly under this comment block.
    # Leave this marker and the blank lines around it untouched so
    # independent branches merge cleanly.

    # --- raw: fda mqsa ---
    # FDA MQSA certified mammography facilities (#36).
    elif args.cmd == "mqsa":
        _print(fda_mqsa.ingest(cat, args.release, args.url, args.retrieved_on))

    # --- raw: epa sdwis ---
    elif args.cmd == "sdwis":
        _print(epa_sdwis.ingest(cat, args.release, args.url, args.pws_url, args.geo_url,
                                args.viol_url, args.ansi_url))

    # --- raw: fcc broadband ---
    # FCC Broadband Data Collection (#54).
    # The `elif args.cmd == ...` dispatch branch goes directly under this comment block.
    # Leave this marker and the blank lines around it untouched so
    # independent branches merge cleanly.

    # --- raw: epa ejscreen ---
    # EPA EJScreen, every archived edition (#97).
    elif args.cmd == "ejscreen":
        _print(ejscreen.ingest(cat, args.release, args.edition, args.level, args.url))

    # --- raw: bls laus ---
    # BLS Local Area Unemployment Statistics, county (#94).
    elif args.cmd == "laus":
        _print(bls_laus.ingest(cat, args.release, args.county_url, args.area_url, args.series_url,
                               args.measure_url, args.footnote_url, args.vintage, args.since))

    # --- raw: cdc teenvaxview ---
    # CDC TeenVaxView / NIS-Teen HPV vaccination coverage (#105).
    elif args.cmd == "teenvax":
        _print(teenvaxview.ingest(cat, args.release, args.vintage, args.url))

    # --- raw: epa airtoxscreen ---
    # EPA AirToxScreen tract-level modeled cancer risk (#98).
    elif args.cmd == "airtoxscreen":
        _print(epa_airtoxscreen.ingest(cat, args.release, args.year, args.srcgrp_url,
                                       args.pollutant_url))

    # --- raw: epa tri ---
    # EPA Toxics Release Inventory Basic Data Files (#100).
    elif args.cmd == "tri":
        _print(epa_tri.ingest(cat, args.release, args.year, args.url, args.retrieved_on))

    # --- raw: epa radon zones ---
    elif args.cmd == "radon":
        _print(epa_radon.ingest(cat, args.release, args.url))

    # --- raw: epa superfund npl ---
    # EPA Superfund National Priorities List sites (#99); extends facility.site with kind='superfund'.
    elif args.cmd == "superfund":
        _print(epa_superfund.ingest(cat, args.release, args.status_url, args.frs_url, args.retrieved_on))

    else:
        for ns in cat.list_namespaces():
            for t in cat.list_tables(ns):
                print(".".join(t))


if __name__ == "__main__":
    main()
