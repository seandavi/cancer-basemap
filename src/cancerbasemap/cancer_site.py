"""SEER Site Recode ICD-O-3/WHO 2008 <-> SEER Cause of Death Recode 1969+
(ICD-10 mortality) -> measure.cancer_site, plus a small curated NCIt/MONDO
bridge for the cancer sites State Cancer Profiles (SCP) publishes (SPEC.md §
measure.cancer_site; issue #31).

**Licence.** Both tables are National Cancer Institute (SEER) publications.
NCI's own reuse policy: "Unless otherwise indicated, all text within National
Cancer Institute (NCI) products is free of copyright and may be reused
without our permission. Credit the National Cancer Institute as the source."
(https://www.cancer.gov/policies/copyright-reuse, checked 2026-09-18). SEER
content is additionally a U.S. Government work, public domain under 17
U.S.C. Sec 105 (resources.data.gov/open-licenses/, the same basis the other
federal sources in this repo cite).

**Which recode, and why.** SCP's own FAQ names exactly the two upstream
tables behind its statistics: "How do you determine what is included in a
cancer site? Incidence Data - We use the Site Recode ICD-O-3/WHO 2008
Definition, which can be found at
https://seer.cancer.gov/siterecode/icdo3_dwhoheme/index.html . Mortality
Data - We use a combination of ICD-8, ICD-9, ICD-10. Definitions of the
codes can be found at https://seer.cancer.gov/codrecode/1969_d03012018/ ."
(https://statecancerprofiles.cancer.gov/faq.html, checked 2026-09-18). Those
are exactly the two editions this module lands -- not the 2023 revision SEER
also publishes (a different, incompatible 2-digit code space); SCP's FAQ
doesn't point to it, so landing it would be enumerating an edition SCP
doesn't use, against the issue's "start with the sites SCP actually
publishes."

**Format: the plain-text form, not the HTML table.** Both pages publish the
same table as HTML and as a `;`-delimited ASCII file ("The information
provided in this table is also available in an ASCII text file", both
pages, checked 2026-09-18). The HTML renders site groups nested up to four
levels deep via `rowspan`/`colspan`; the text form needs none of that --
hierarchy is plain leading-space indentation (4 spaces/level) and every
record is one line, so it's the simpler of the two real layouts and is used
here (stdlib string splitting; no HTML parser, no new dependency).

**raw.seer__site_recode** lands the site-recode text file verbatim:
`site_group` keeps the source's own leading-space indentation (its
hierarchy marker) rather than trimming it, `icdo3_site`/`icdo3_histology`
are the published range expressions unparsed (that column holds both
exclusion ranges, e.g. "excluding 9050-9055, 9140, 9590-9993", and, for a
few codes, an inclusion range instead, e.g. Melanoma's "8720-8790" or
Myeloma's "9731-9732, 9734" -- landed as published either way), and
`recode` is the numeric code where the source gives one, blank for every
row that is a group heading rather than a site (e.g. "Colon and Rectum",
"Digestive System") -- never invented. A handful of codes are defined by
more than one physical row (e.g. 31040 "Cranial Nerves Other Nervous
System" has one row for site C710-C719/histology 9530-9539 and a second for
site C700-C709,C720-C729/histology "excluding ..."); both land as separate
raw rows exactly as published -- `transform` concatenates a code's distinct
clause texts into one measure.cancer_site row.

**raw.seer__cod_recode** lands only the text file's first table ("Neoplasm
Causes of Death"); the "Non-Neoplasm Causes of Death" and "Codes Not
Indicating Causes of Death" tables that follow it in the same file are
administrative/non-cancer causes, out of scope for a cancer-site bridge.
`recode` is blank, or the literal sentinel "--" ("All Malignant Cancers"),
for rows with no site-recode equivalent.

**measure.cancer_site** derives one row per *numeric* recode in
raw.seer__site_recode (`cancer_site_code`), never per group heading -- SEER's
table assigns no code to any heading at any depth, so `parent_code` is NULL
throughout this edition (declared per SPEC.md/the issue, ready for an
edition that does publish one -- see ponytail below). `icd10_mortality` is
filled by joining raw.seer__cod_recode on an EXACT label match ("where the
site names align exactly", per the issue) -- deliberately not fuzzy or
case-folded, so a near-miss caused by COD's own footnote markers baked into
a label (e.g. "Soft Tissue including Heart$") or a real wording difference
(COD's mortality-only "Mesothelioma (ICD-10 only)+" vs incidence's plain
"Mesothelioma") is left NULL rather than guessed. 56 of 81 site-recode codes
align this way; the other 25 are individually finer-grained than COD's own
grouping (the 9 colon subsites 21041-21049 all roll up to COD's single
"Colon excluding Rectum" = a *different* code, 21040) and get no ICD-10
range here.

**"All Sites"/"All Cancer Sites" has no cancer_site_code.** SCP's FAQ: "All
Cancers refers to all invasive cancers combined. This includes the cancer
sites that we list on our Web site ... as well as all other invasive
cancers." (statecancerprofiles.cancer.gov/faq.html, checked 2026-09-18) -- it
is the absence of a site filter, not a discrete SEER recode value; the COD
table's own "All Malignant Cancers" row carries the literal sentinel "--"
instead of a code, confirming the same on the mortality side. Left out of
the curated CSV; the issue's "every cancer_site_code used by #27 resolves"
is unaffected since there is no code to resolve for it.

**Curated NCIt/MONDO bridge
(`src/cancerbasemap/data/cancer_site_ontology.csv`).** Researched first, per
the issue: neither SEER, NCIt nor MONDO publishes a site-recode-to-ontology
crosswalk (checked NCI EVS/OLS4 and MONDO's own mapping docs, 2026-09-18) --
this file is this project's own curation, `mapping_basis = 'curated'`
wherever it applies. One row per constituent `cancer_site_code`, so a
reviewer can check every id against the exact SEER code it covers. Every id
was looked up and confirmed live against the EBI OLS4 API
(`https://www.ebi.ac.uk/ols4/api/ontologies/{ncit,mondo}/terms?obo_id=...`)
on 2026-09-18: not obsolete, label matches the CSV's own `ncit_label`/
`mondo_label`. Gaps, reported honestly rather than guessed:
  - **All Sites** -- no cancer_site_code exists to attach it to (see above).
  - **Oral Cavity and Pharynx** -- no NCIt term combining exactly this SEER
    group (C000-C149) was found with confidence; candidates were either
    narrower (a single subsite) or broader (all of head and neck). Left
    unmapped.
  - **Liver and Intrahepatic Bile Duct** -- MONDO has an exact-label match
    (MONDO:0024477); NCIt does not (its nearest term, "Malignant
    Hepatobiliary Neoplasm" C8609, also covers gallbladder and other biliary
    sites SEER keeps separate) -- `ncit_id` NULL, `mapping_basis` still
    'curated' since `mondo_id` is filled.
  - **Kidney and Renal Pelvis** -- mapped to the general "Malignant Kidney
    Neoplasm"/"kidney cancer" terms (a broader match: NCIt separately
    defines a narrower "... Except Renal Pelvis" sibling term, implying the
    plain term includes it, but this was not independently confirmed) --
    noted in the CSV's own `note` column.
For every SCP category that is not a single SEER leaf code (Colon & Rectum,
NHL, Leukemia, Liver & Bile Duct, Uterus/Corpus, Brain & ONS), the CSV lists
each constituent `cancer_site_code`. SCP's FAQ spells out Brain & ONS's two
constituents explicitly: "We combine brain and other nervous system
together as one cancer site grouping - Brain and ONS. This includes two
groupings: Brain, Cranial Nerves Other Nervous System." The FAQ names no
others, so the rest are this project's own reading of the SEER Site Recode
table's matching SECTION HEADERS (its "Colon and Rectum", "Non-Hodgkin
Lymphoma", "Leukemia", "Corpus and Uterus, NOS", "Liver and Intrahepatic
Bile Duct" groupings use the identical wording SCP's site list uses) -- a
`note` on each such row says so.

**`mapping_relation` (#90).** The CSV's free-text `note` said whether a
mapping was exact or broader only in prose; #90 asks for that as its own
column so a cross-lake join to biocOnIce's `ontology` namespace (#60, #61)
can filter to exact matches only, the same way a stratum pooling is made
visible via `measure.stratum_map.relation` (SPEC.md) -- the same four-value
vocabulary (`exact` | `broader` | `narrower` | `overlap`) that column
declares, not a cancer_site-only pair.

Most of the 40 curated rows already documented above as a "SCP combined
category" (Colon & Rectum's 11 subsites, NHL's 2, Leukemia's 9, Liver & Bile
Duct's 2, Brain & ONS's 2 -- 26 rows) are `broader`: the ontology term names
the combined disease, and the row's own `cancer_site_code` is one narrower
constituent of it. Kidney and Renal Pelvis (29020) is also `broader`, for
the different reason already in its `note` (no NCIt/MONDO term splits
kidney parenchyma from renal pelvis at SEER's granularity) -- 27 `broader`
rows in total. The Corpus/Uterus pair splits instead of matching that
pattern: Corpus Uteri (27020, C540-C549) is exactly the anatomic site
"Malignant Uterine Corpus Neoplasm"/"uterine corpus cancer" names, so it is
`exact`; Uterus, NOS (27030, C559) is unclassified by subsite -- some cases
are corpus, some are not -- so it is neither a subset nor a superset of the
ontology term and is `overlap` rather than `broader` (which would wrongly
claim every NOS case is a corpus case). The remaining 11 single-site rows
(Breast, Cervix, Lung, Prostate, Melanoma, Bladder, Pancreas, Thyroid,
Ovary, Stomach, Esophagus) are `exact` -- a 1:1 match between the SEER code
and the ontology term, for 12 `exact` rows total with Corpus Uteri. Final
split: 12 `exact`, 27 `broader`, 1 `overlap`. `mapping_relation` is NULL
exactly where `mapping_basis` is NULL (no ontology id at all).

ponytail: `parent_code` is declared but always NULL for this edition (see
above) -- add real values if a future SEER edition (e.g. the 2023 revision,
which does assign single codes to some of these same combined groups) turns
out to be what a downstream consumer needs, rather than inventing a
cross-edition mapping here.

ponytail: only the "Neoplasm Causes of Death" section of the COD recode text
file is landed; "Non-Neoplasm Causes of Death" and "Codes Not Indicating
Causes of Death" are unrelated to cancer sites.

ponytail: the SEER 2023 revision definitions (icdo3_2023, icdo3_d2023) are
not landed -- SCP's FAQ does not name them as what SCP uses; add them
alongside these two if SCP (or another consumer) migrates.
"""

import csv
import urllib.request
from pathlib import Path

import pyarrow as pa
from pyiceberg.expressions import And, EqualTo

from . import merge

USER_AGENT = "cancerbasemap/1.0 (+https://github.com/seandavi/cancer-basemap)"

SITE_RECODE_URL = "https://seer.cancer.gov/siterecode/icdo3_dwhoheme/index.txt"
SITE_RECODE_EDITION = "icdo3_dwhoheme"
SITE_RECODE_HEADER = ("Site Group", "ICD-O-3 Site", "ICD-O-3 Histology (Type)", "Recode")
SITE_RECODE_COLUMNS = ("site_group", "icdo3_site", "icdo3_histology", "recode")

COD_RECODE_URL = "https://seer.cancer.gov/codrecode/1969_d03012018/index.txt"
COD_RECODE_EDITION = "1969_d03012018"
COD_RECODE_HEADER = ("Neoplasm Causes of Death", "ICD-8", "ICD-9 (1979-1998) #",
                     "ICD-10 (1999+) #", "Recode")
COD_RECODE_COLUMNS = ("cod_group", "icd8", "icd9", "icd10", "recode")

CURATED_CSV = Path(__file__).parent / "data" / "cancer_site_ontology.csv"


def _fetch_text(url):
    """The file's text. A local path (tests) is read directly; a remote URL
    goes through urllib with a descriptive User-Agent."""
    if not url.startswith("http"):
        return Path(url).read_text()
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req) as r:
        return r.read().decode("utf-8")


def _table_rows(text, header, out_columns):
    """Rows of the first `;`-delimited table in `text` whose header line
    equals `header` exactly. Only lines containing ';' are table lines --
    every title/caption/footnote line in these two files has none, so this
    also naturally skips the file's opening prose and trailing footnotes.
    Stops at the first blank line, which is what separates this table from
    whatever table (if any) follows it in the same file. A ragged row (a
    group heading with fewer real fields than a leaf row) is padded with ''
    so every returned row has len(header) fields; a line's own trailing ';'
    produces one spurious trailing empty field, dropped first.
    """
    lines = text.splitlines()
    try:
        i = lines.index(";".join(header))
    except ValueError:
        raise SystemExit(f"cancer_site: header {header!r} not found in the fetched file; "
                         f"upstream layout may have changed")
    rows = []
    for line in lines[i + 1:]:
        if line.strip() == "":
            break
        if ";" not in line:
            continue
        fields = line.split(";")
        if fields and fields[-1] == "":
            fields = fields[:-1]
        fields = (fields + [""] * len(header))[:len(header)]
        rows.append(dict(zip(out_columns, fields)))
    if not rows:
        raise SystemExit(f"cancer_site: no data rows found under header {header!r}")
    return rows


def land_raw(cat, release, site_url=None, cod_url=None):
    """Phase 1: both SEER recode tables, verbatim and whole, each replaced
    wholesale per its own edition."""
    site_url = site_url or SITE_RECODE_URL
    site_rows = _table_rows(_fetch_text(site_url), SITE_RECODE_HEADER, SITE_RECODE_COLUMNS)
    for i, r in enumerate(site_rows):
        r["row_order"] = i
        r["site_recode_edition"] = SITE_RECODE_EDITION
        r["landed_in"] = release
    n_site = merge.write(cat, "raw.seer__site_recode", pa.Table.from_pylist(site_rows),
                         EqualTo("site_recode_edition", SITE_RECODE_EDITION))
    merge.manifest(cat, release, "seer_site_recode", site_url, n_site,
                   version=SITE_RECODE_EDITION, method="release_number")

    cod_url = cod_url or COD_RECODE_URL
    cod_rows = _table_rows(_fetch_text(cod_url), COD_RECODE_HEADER, COD_RECODE_COLUMNS)
    for i, r in enumerate(cod_rows):
        r["row_order"] = i
        r["cod_recode_edition"] = COD_RECODE_EDITION
        r["landed_in"] = release
    n_cod = merge.write(cat, "raw.seer__cod_recode", pa.Table.from_pylist(cod_rows),
                        EqualTo("cod_recode_edition", COD_RECODE_EDITION))
    merge.manifest(cat, release, "seer_cod_recode", cod_url, n_cod,
                   version=COD_RECODE_EDITION, method="release_number")

    return {"raw.seer__site_recode": n_site, "raw.seer__cod_recode": n_cod}


def _is_code(value):
    return value.strip().isdigit()


def _consolidate_site_recode(cat):
    """One dict per numeric recode: label plus the distinct, in-order union of
    that code's ICD-O-3 site/histology clause texts (see module docstring --
    a handful of codes are defined by more than one physical row)."""
    rows = cat.load_table("raw.seer__site_recode").scan(
        row_filter=EqualTo("site_recode_edition", SITE_RECODE_EDITION)).to_arrow().to_pylist()
    rows.sort(key=lambda r: r["row_order"])

    by_code = {}
    for r in rows:
        code = r["recode"].strip()
        if not _is_code(code):
            continue
        label = r["site_group"].strip()
        entry = by_code.setdefault(code, {"label": label, "site": [], "histology": []})
        if entry["label"] != label:
            raise SystemExit(f"cancer_site: recode {code} has inconsistent labels "
                             f"{entry['label']!r} and {label!r}")
        site = r["icdo3_site"].strip()
        if site and site not in entry["site"]:
            entry["site"].append(site)
        hist = r["icdo3_histology"].strip()
        if hist and hist not in entry["histology"]:
            entry["histology"].append(hist)
    return by_code


def _cod_icd10_by_label(cat):
    """Exact-label lookup: leaf (numeric-recode) label -> its published ICD-10
    range, from the Neoplasm Causes of Death table."""
    rows = cat.load_table("raw.seer__cod_recode").scan(
        row_filter=EqualTo("cod_recode_edition", COD_RECODE_EDITION)).to_arrow().to_pylist()
    return {r["cod_group"].strip(): r["icd10"].strip()
           for r in rows if _is_code(r["recode"])}


def _curated_ontology(ontology_csv):
    """cancer_site_code -> (ncit_id, mondo_id, mapping_relation), from the
    reviewed CSV (module docstring). A blank cell is NULL, never an empty
    string."""
    with open(ontology_csv, newline="") as f:
        return {row["cancer_site_code"]: (row["ncit_id"] or None, row["mondo_id"] or None,
                                          row["mapping_relation"] or None)
               for row in csv.DictReader(f)}


def transform(cat, release, ontology_csv=None):
    """Phase 2: measure.cancer_site, one row per numeric SEER site-recode
    code, bridged to ICD-10 mortality and (for the curated sites) NCIt/MONDO.

    `ontology_csv` overrides the curated bridge file -- a tiny fixture in
    tests, so a small offline site-recode fixture doesn't have to define
    every code the real, full curated CSV covers.
    """
    site_by_code = _consolidate_site_recode(cat)
    icd10_by_label = _cod_icd10_by_label(cat)
    ontology = _curated_ontology(ontology_csv or CURATED_CSV)
    if unknown := set(ontology) - set(site_by_code):
        raise SystemExit(f"cancer_site: curated CSV references unknown cancer_site_code(s): "
                         f"{sorted(unknown)}")

    out = []
    for code, entry in site_by_code.items():
        ncit_id, mondo_id, mapping_relation = ontology.get(code, (None, None, None))
        out.append(dict(
            cancer_site_code=code,
            label=entry["label"],
            parent_code=None,  # see module docstring
            icdo3_topography="; ".join(entry["site"]) or None,
            icdo3_histology_exclusions="; ".join(entry["histology"]) or None,
            icd10_mortality=icd10_by_label.get(entry["label"]),
            ncit_id=ncit_id,
            mondo_id=mondo_id,
            mapping_basis="curated" if (ncit_id or mondo_id) else None,
            source="SEER",
            source_release=SITE_RECODE_EDITION,
            mapping_relation=mapping_relation if (ncit_id or mondo_id) else None,
        ))

    cancer_site = pa.Table.from_pylist(out)
    scope = And(EqualTo("source", "SEER"), EqualTo("source_release", SITE_RECODE_EDITION))
    return {"measure.cancer_site": merge.merge(cat, "measure.cancer_site", cancer_site, release, scope)}


def ingest(cat, release, site_url=None, cod_url=None, ontology_csv=None):
    counts = land_raw(cat, release, site_url, cod_url)
    return {**counts, **transform(cat, release, ontology_csv)}
