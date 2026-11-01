"""measure.cancer_site_group -- prevention-lens groupings over
measure.cancer_site: screenable, vaccine-preventable, and tobacco-, HPV-,
obesity-, alcohol- and UV-associated cancers (SPEC.md § measure.cancer_site_group;
issue #126).

**Why.** A catchment researcher's caution, quoted in the issue: no single
burden metric should drive decisions, and *preventability* changes the
ranking -- it raises melanoma and cervical cancer above where mortality
alone puts them. Preventability is not a measured value; it is an attribute
of the cancer site, so it is carried here as a small, cited lookup rather
than folded into measure.cancer_site itself.

**Licence.** This module's only artifact is `data/cancer_site_groups.csv`,
this project's own curated compilation -- not a redistribution of any single
upstream table. Every row cites a U.S. federal public-domain source (CDC,
NCI, the US Surgeon General) or USPSTF, whose recommendations are likewise a
work of the U.S. government (AHRQ-convened, HHS): "Data and content created
by government employees within the scope of their employment are not
subject to domestic copyright protection under 17 U.S.C. Sec 105."
(https://resources.data.gov/open-licenses/, the same authority the other
federal sources in this package cite). Quoting a short sentence from each
page for attribution is fair use regardless.

**One citation per (group, site) row, stored in the data, never from
memory** (per the issue). `data/cancer_site_groups.csv` columns: group_id,
group_label, cancer_site_code, mapping_relation, basis (citation: publisher,
page, date, verbatim quote), source_url, note. Every URL was fetched live
and the quote checked against the fetched page on 2026-09-19.

**Groups landed:**
  - **tobacco_associated** -- CDC, "Tobacco and Cancer". 12 named sites; the
    9 oral-cavity/pharynx SEER leaves stand in for CDC's undifferentiated
    "Mouth and throat" (mapping_relation='broader'); "Lungs, bronchi, and
    trachea" is landed as Lung and Bronchus (22030) only -- trachea has no
    clean matching SEER leaf of its own (see per-row note) and is not
    guessed at.
  - **hpv_associated** -- CDC, "Basic Information about HPV and Cancer".
    Cervix, vulva, vagina, penis, anus are exact; CDC's own definition of
    "oropharynx" spans SEER's separate Oropharynx and Tonsil leaves, so both
    are landed as 'broader' with a note -- the issue's own named example.
  - **obesity_associated** -- CDC, "Obesity and Cancer" (13 sites, matching
    IARC's 2016 Working Group sufficient-evidence list). Three of its named
    sites are histology/subsite-specific claims SEER's site recode cannot
    express as a matching single code (adenocarcinoma of the esophagus,
    gastric cardia/"upper stomach", meningioma) -- each landed against the
    closest containing SEER code, marked 'broader', with a note naming the
    mismatch, the same discipline #90 uses for the NCIt/MONDO bridge.
  - **alcohol_associated** -- CDC, "Alcohol and Cancer", core causal list (7
    sites, matching IARC's Group 1 alcohol sites). The same page separately
    hedges stomach, pancreatic and prostate cancer with "some studies show"
    / "may also increase" language -- landed as a **separate**
    `alcohol_associated_limited_evidence` group rather than flattened into
    `alcohol_associated`, per the issue's instruction to record where
    evidence is limited rather than sufficient.
  - **uspstf_screenable** -- current USPSTF Grade A/B recommendations:
    breast (Grade B, 40-74), cervical (Grade A), colorectal (Grade A 50-75 /
    Grade B 45-49), lung (Grade B). Weaker/narrower grades for other ages
    (breast 75+ Grade I, colorectal 76-85 Grade C) are recorded in `note`,
    not landed as separate members.
  - **vaccine_preventable** -- HPV vaccine, same site membership and
    oropharynx caveat as hpv_associated, cited separately (CDC's HPV Vaccine
    Information Statement) since it is a distinct assertion (prevention, not
    association); and hepatitis B vaccine -> liver cancer, cited from NCI's
    PDQ Liver Cancer Prevention summary (the CDC/WHO hepatitis pages found
    while researching this state the vaccine prevents HBV infection and name
    liver cancer as a consequence of chronic infection, but neither states
    the vaccine-prevents-cancer link in one sentence the way NCI's PDQ
    literature review does) -- mapped to Liver (21071) only, not
    Intrahepatic Bile Duct (21072), since HBV/HCC etiology is liver-specific.
  - **uv_associated** -- melanoma only, from the US Surgeon General's 2014
    "Call to Action to Prevent Skin Cancer": "As many as 90% of melanomas
    are estimated to be caused by UV exposure."

ponytail: mapping_relation only distinguishes 'exact' | 'broader' (#90's
vocabulary), not finer relations (narrower/overlap) -- the groupings named in
the issue never need those; add one if a future grouping does.
"""

from pathlib import Path

import duckdb
from pyiceberg.expressions import AlwaysTrue, EqualTo

from . import merge

SOURCE = "CANCERONICE"
CHECKED = "2026-09-19"
DATA_FILE = Path(__file__).parent / "data" / "cancer_site_groups.csv"

COLUMNS = ("group_id", "group_label", "cancer_site_code", "mapping_relation",
          "basis", "source_url", "note")
RELATIONS = ("exact", "broader")


def land_raw(cat, release, path=None):
    """Phase 1: the curated CSV, verbatim and whole. Replaced wholesale each
    time (like raw.geography__county_recodes) -- there is no upstream
    edition axis, only our own re-curation.
    """
    path = Path(path) if path else DATA_FILE
    header = tuple(path.read_text(encoding="utf-8").splitlines()[0].split(","))
    if header != COLUMNS:
        raise SystemExit(f"cancer_site_group: {path} header is not the declared one; "
                         f"differs in {sorted(set(header) ^ set(COLUMNS))}")

    con = duckdb.connect()
    arrow = con.sql(f"""
        SELECT {", ".join(COLUMNS)}, '{release}' AS landed_in
        FROM read_csv('{path}', header=true, all_varchar=true, delim=',',
                      quote='"', escape='"', nullstr='')
    """).to_arrow_table()
    if not arrow.num_rows:
        raise SystemExit(f"cancer_site_group: {path} yielded no rows")

    n = merge.write(cat, "raw.canceronice__cancer_site_group", arrow, AlwaysTrue())
    merge.manifest(cat, release, "cancer_site_group", str(path), n,
                   version=CHECKED, method="retrieval_date")
    return n


def transform(cat, release):
    """Phase 2: one measure.cancer_site_group row per curated membership,
    checked against measure.cancer_site so a typo'd cancer_site_code fails
    loudly rather than landing an orphan FK."""
    con = duckdb.connect()
    con.register("raw", cat.load_table("raw.canceronice__cancer_site_group").scan().to_arrow())

    bad = con.sql(f"""
        SELECT DISTINCT mapping_relation FROM raw
        WHERE mapping_relation NOT IN ({", ".join(f"'{r}'" for r in RELATIONS)})
    """).fetchall()
    if bad:
        raise SystemExit(f"cancer_site_group: unknown mapping_relation(s) "
                         f"{[b[0] for b in bad]}; expected one of {RELATIONS}")

    known_codes = {r["cancer_site_code"]
                  for r in cat.load_table("measure.cancer_site").scan(
                      selected_fields=("cancer_site_code",)).to_arrow().to_pylist()}
    curated_codes = {r[0] for r in con.sql("SELECT DISTINCT cancer_site_code FROM raw").fetchall()}
    if unknown := curated_codes - known_codes:
        raise SystemExit(f"cancer_site_group: curated CSV references unknown "
                         f"cancer_site_code(s): {sorted(unknown)}")

    group = con.sql(f"""
        SELECT group_id, group_label, cancer_site_code, mapping_relation, basis,
               source_url, note, '{SOURCE}' AS source
        FROM raw
    """).to_arrow_table()

    scope = EqualTo("source", SOURCE)
    return {"measure.cancer_site_group": merge.merge(cat, "measure.cancer_site_group",
                                                      group, release, scope)}


def ingest(cat, release, path=None):
    n = land_raw(cat, release, path)
    return {"raw.canceronice__cancer_site_group": n, **transform(cat, release)}
