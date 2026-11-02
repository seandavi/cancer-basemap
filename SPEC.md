# Cancer Basemap — Specification (draft)

> Sibling of [biocOnIce](https://github.com/seandavi/bioc-on-ice), served
> through [icegate](https://github.com/seandavi/icegate), sourced through
> cdsci-lake where a DuckLake already curates the domain (biocOnIce ADR-0012).

## Names

**Cancer Basemap** is the product name — repository, papers, CARDS talks, grant
narratives. A basemap is the common reference layer a map
is drawn on, which is what this is under catchment dashboards such as Cancer
InFocus. The Python package and CLI are `cancerbasemap` (`basemap` on PyPI is
matplotlib's toolkit). The earlier names, "cancerOnIce" and "Catchment Lake",
are retired (ADR-0001 § Infrastructure of its own).

The Iceberg side keeps the old name until it is retired: the `canceronice`
bucket and catalog, the `icegate-canceronice` hostname, `canceronice-*` secrets,
and the literal `source = 'CANCERONICE'` on curated rows.

Terminology discipline: platform docs already call cdsci-lake a lake, and
biocOnIce ADR-0012 separates DuckLakes (ETL) from icegate catalogs
(publication). Write "cdsci-lake (ETL)" versus "Cancer Basemap (published)"
wherever both appear, and never call cdsci-lake the catalog or Cancer Basemap
the ETL layer.

## Vision

Population cancer data — incidence, mortality, screening, risk factors, the
social and environmental context around them, and the places people get care —
published as Apache Iceberg tables keyed on geography and time, where **every
release every source ever published stays queryable**.

The unit of value is the sentence a cancer center has to be able to write and
defend: *"In our catchment, as reported by source S in release R, the measure
was X."* Today that sentence rests on a screenshot, a downloaded CSV of unknown
vintage, or a dashboard that has since silently changed.

## Why

- **Surveillance sources overwrite themselves.** State Cancer Profiles has no
  API, bulk download, or archive of prior estimates; each data refresh
  replaces the last. The facility lists (FDA MQSA, HPSA designations, provider
  files) behave the same way: only today's list is served. biocOnIce's
  rows-carry-history model (`first_seen` / `retired_in`) is exactly what this
  domain lacks. PLACES, SVI and AHRF do keep their prior releases; the case
  for landing them is the next bullet, plus having every release in one
  joinable model rather than one file layout per year.
- **Sources get revised, restructured and retired.** Methods change, geography
  vintages roll, and data products are periodically reorganized or
  discontinued. Analyses and grant narratives written against an earlier
  release need that release to stay reachable; "every release stays
  queryable" is a reproducibility guarantee, not just a convenience.
- **Every NCI-designated center re-does the same ETL.** Each must describe a
  geographically defined catchment and its cancer burden for the CCSG, and most
  do it with small, under-resourced teams. The shared, public part of that work
  should be done once.
- **Dashboards are not data.** The existing tools (see *Landscape*) are built
  to be looked at. None is built to be queried across sources, across time, and
  across centers from R, Python, SQL, a browser, and an assistant.

## Non-goals

Cancer Basemap will not:

- host record-level, DUA-gated, or restricted data of any kind — public
  aggregates only (see *Licence gate*);
- compute cancer statistics from registry microdata (it republishes the rates
  sources publish; it does not become a registry);
- build a dashboard product (ECCO and others are consumers; see *Landscape*);
- harmonize race/ethnicity or cancer-site categories destructively — sources
  keep their own categories, mappings live beside them;
- store geometry as the primary artifact (geometry is referenced; see
  *Geography*).

---

# Landscape

What exists, what it does well, and where Cancer Basemap sits. Surveyed September
2026.

| Resource | What it is | Strength | Gap Cancer Basemap fills |
| --- | --- | --- | --- |
| **Cancer InFocus / CIFTools** (UK Markey) | Data gatherer (county list in → standardized files out) + Shiny app; code under a no-cost licence; downloads at CancerInFocus.org | The de facto standard: all NCI-designated centers covered, 35 licensed adopters by Oct 2024; community around the CARDS group and the Catchment Area Data Conference | Snapshot files, no history; not queryable across centers; its county incidence comes from the USCS Incidence Analytic Dataset through special access, which a public lake cannot republish |
| **NCI GIS Portal** (Cancer Atlas, catchment-area viewer, data-source index) | NCI's geospatial hub | Authoritative; its data-source index is a good candidate list | Visualization-first; catchment viewer is not downloadable |
| **State Cancer Profiles** | NCI/CDC county/state incidence, mortality, screening, risk, demographics | The canonical public county cancer burden source | No API, no bulk, no archive — already filled by `state-cancer-profile-scraper` and its Zenodo vintages |
| **County Health Rankings & Roadmaps** | Annual county health measures; now on Zenodo 2010–2025 with an R client | Versioned releases, programmatic access | Single source; not joined to cancer or catchments |
| **NaNDA** (U Michigan / ICPSR) | Tract/ZCTA/county contextual measures, 1981– | Broad, theory-derived, long time series | ICPSR distribution terms — a pointer target, not a copy |
| Harvard LIL data.gov archive, ICPSR DataLumos | General archives of federal data files | Broad coverage | Files, not a joinable model; no geography/time semantics |
| PolicyMap, Social Explorer | Commercial | Polished | Closed, paid |

**Positioning.** Cancer Basemap should not compete with Cancer InFocus; it should
be the thing CIF (and ECCO, and any center's own tool) reads from. Concretely:
an export recipe that writes CIFTools-shaped files for any catchment from the
lake is a better adoption path than a rival dashboard, and the CARDS group is
the audience to bring it to.

---

# Architecture

Identical in shape to biocOnIce:

```text
 upstream sources ──► cdsci-lake (EL + curation, where it already curates)
                          │
                          ▼  (ADR-0012 read → PyIceberg write)
                   raw.*   (landed verbatim, whole)
                          │
                          ▼  (derive)
    geography.* measure.* facility.* catchment.* resource.* provenance.*
                          │
                     R2 Data Catalog
                          │
                  icegate  (anonymous public read)
                          │
        DuckDB / DuckDB-WASM / PyIceberg / R / MCP / ECCO
```

**Changing (ADR-0001).** The public surface becomes monthly Parquet + DuckDB
view bundles on R2, kept a year, every release archived on Hugging Face; product
tables become release SELECTs, and writers move to cdsci-lake. This section
describes the writers and gateway that still exist until the retirement step.

- Separate R2 bucket and catalog from biocOnIce; bucket-scoped read-only
  vending token (biocOnIce ADR-0011). Same Cloudflare account is acceptable
  **only because** nothing restricted ever lands (ADR-0005: the account is the
  trust domain; restricted data would need its own).
- Listed in the federation registry (biocOnIce #59) as its own entry.
- PyIceberg is the only writer (biocOnIce AGENTS.md).
- Land raw whole, derive from raw (ADR-0002); declared schemas with column docs
  (ADR-0003); writer-scoped merges (ADR-0004); release manifest (ADR-0007).
  These are adopted by reference, not re-litigated.

---

# Versioning model

**Changing (ADR-0001):** the public product becomes one whole-product bundle
a month, kept a year on R2 and permanently on Hugging Face; the per-dataset
model below, and its "never pruned" promise, is replaced. Until then:
Cancer Basemap publishes **dataset releases** (biocOnIce ADR-0013, cdsci-lake
ADR-0025): each dataset is an immutable full snapshot with a release id
(`YYYY-MM-DD`, or `YYYY-MM-DD.N` for a second release the same day) and a
release date, on the dataset's own cadence and retention (`keep_last`, default
keep every release; pinned releases are never pruned). Rows carry no validity
interval. The row history already in the Iceberg tables is a frozen archive
and receives no further writes once its source moves to dataset releases.

One addition matters more here than in biocOnIce. Every measure has **three
time axes**, and conflating them is the characteristic error in this domain:

| Axis | Meaning | Example |
| --- | --- | --- |
| `period_start` / `period_end` | the time the estimate describes | 2018–2022 (a five-year pooled rate) |
| `source_release` | the upstream edition that published it | SCP vintage V3; PLACES 2025 release; ACS 2019–2023 |
| release id (`YYYY-MM-DD[.N]`) | the dataset release that served it | 2026-10-02 |

`source_release` for sources that publish no version label follows the
**vintage** definition already used for the SCP Zenodo deposits: a vintage is
one edition of the values the source served, bounded by the moment the source
silently replaced them; several scrapes that captured identical values are one
vintage.

---

# Catalog organization

```
raw          sources as landed, verbatim, per source release
geography    units, vintages, crosswalks, aliases (the spine)
population   denominators (SEER county/tract population, ACS universes)
measure      every published number, in one stacked long table + definitions
facility     places care happens (mammography, FQHC, providers, screening)
catchment    cancer centers and the geographies they claim
resource     pointers to large or non-redistributable data (NaNDA, geometries)
provenance   release manifest, source, transformation (as biocOnIce)
```

---

# Core data model

## Geography — the spine

Geography plays the role `reference.genome` plays in biocOnIce: every fact
joins through it, and it has versions. County and tract boundaries change
(Connecticut's move from counties to planning regions in 2022, Alaska
reorganizations, tract redraws each decennial census). A FIPS code without a
vintage is an assembly name without a patch level.

### geography.unit

```
geo_id          -- canonical: '<level>:<fips>', e.g. 'county:08031'
level           -- nation | state | county | tract | block_group | zcta | place | cd | sldu | sldl | custom
fips            -- the bare code
vintage         -- boundary vintage year, e.g. 2020
name
parent_geo_id   -- containing unit in the same vintage
aland_m2, awater_m2
centroid_lat, centroid_lon
geometry_uri    -- pointer (GeoParquet / PMTiles on R2), not the geometry itself
first_seen, retired_in
```

### geography.crosswalk

```
from_geo_id, from_vintage
to_geo_id,   to_vintage
weight          -- share of the from-unit assigned to the to-unit
weight_basis    -- population | housing_units | land_area
source          -- e.g. 'CENSUS_RELATIONSHIP_FILE'
```

Source: Census relationship files (public domain). NHGIS crosswalks are better
in places but IPUMS terms must be checked before redistribution — pointer until
then.

### geography.alias

FIPS changes that are renames or re-codings rather than boundary changes
(e.g. 46113 → 46102), so a join on an old code resolves rather than drops.

## Measures — one stacked long table

Surveillance sources publish the same *shape* of fact — a value for a place,
a period, and a stratum, with an interval and a status — under wildly
different layouts. They land raw as-is and derive into one stacked,
multi-writer table (the `source` column pattern from biocOnIce's genome-feature
tables).

### measure.observation

```
source              -- asserting provider: 'SCP' | 'PLACES' | 'ACS' | 'SVI' | ...
source_release      -- vintage / release label (see Versioning)
measure_id          -- FK measure.definition
geo_id, geo_vintage
period_start, period_end
stratum_id          -- FK measure.stratum
value               -- NULL whenever value_status != 'reported'
lower, upper        -- interval bounds
interval_level      -- 0.90 (ACS MOE) | 0.95 (SCP CI) | NULL
numerator, denominator   -- when published
value_status        -- see below; never NULL
reliability_flag    -- published separately from suppression (e.g. unstable RSE)
trend               -- source-published trend call, if any
first_seen, retired_in
```

Partitioned by `source`. Merge scope is `(source, source_release)` — a new SCP
vintage never retires a PLACES row. Physically sorted (issue #120) by
`(source_release, measure_id, geo_id, period_start, stratum_id)` on every
write — measure_id, not geo_id, is the dominant clustering key, since a query
naming one measure is the common case and Parquet row-group statistics can
only discriminate well on whichever column is highest in the sort order; a
geo_id-only query still benefits only modestly (SPEC.md's earlier "clustered
by geo_id" wording overstated this — see the #120 PR for the measured
tradeoff).

### Suppression is a value, not a NULL

`value_status` is a closed enum, documented in the column doc and enforced
before write:

| value_status | Meaning |
| --- | --- |
| `reported` | value published |
| `suppressed_small_count` | below the source's count threshold |
| `suppressed_complementary` | suppressed to prevent back-calculation |
| `suppressed_reliability` | suppressed because the estimate is unreliable |
| `not_available` | source publishes no value for this unit (e.g. state data not submitted or not meeting criteria) |
| `not_applicable` | combination is meaningless (cervix × male) |

The invariant is **no suppressed cell ever reads as a number**, and no reader
has to parse a sentinel (`"*"`, `"3 or fewer"`, `-1`) to find out.

Suppression itself is the source's. Every source publishes aggregates it has
already suppressed; Cancer Basemap never re-suppresses or clears what a source
chose to publish. The invariant is about `value`: when `value_status !=
'reported'` it is NULL. Companion columns (`lower`, `upper`, `numerator`,
`denominator`) carry whatever the source published for that cell (ADR-0001).

### measure.definition

```
measure_id, source, label, units
universe            -- population the rate is over
rate_basis          -- per 100,000 | per 1,000,000 | percent | count | index | sum
age_adjustment      -- standard population (e.g. 2000 US standard) or NULL
method              -- direct | model_based | survey_direct | derived
cancer_site_code    -- FK measure.cancer_site when applicable
doc                 -- prose
```

### measure.stratum

Source-native strata, never harmonized in place:

```
stratum_id, source
sex, age_group, race_ethnicity, stage, other
scheme              -- e.g. 'SCP_RACE_2024', 'OMB_1997', 'OMB_SPD15_2024'
```

Mappings between schemes live in `measure.stratum_map` with an explicit
`relation` (`exact` | `broader` | `narrower` | `overlap`), so a user choosing
to pool categories does it visibly. The 2024 revision of OMB SPD 15 means
schemes will diverge across releases of the same source; this is expected.

### measure.cancer_site

SEER site recode ↔ ICD-O-3 topography/histology ↔ ICD-10 (mortality) ↔ NCIt /
MONDO. The NCIt/MONDO columns are the **bridge to biocOnIce's `ontology`
namespace** — the one natural cross-lake join key besides publications.
`mapping_relation` (`exact` | `broader` | `narrower` | `overlap`, #90) says
how the NCIt/MONDO id relates to this site: exactly (a SEER subsite folded
into an SCP combined category is `broader` there, e.g. Cecum → "colorectal
cancer"; a code whose anatomic scope only partly matches the term, neither a
subset nor a superset, is `overlap`, e.g. Uterus, NOS against "uterine
corpus cancer" — some NOS cases are corpus, some are not) — the same
vocabulary and purpose as `measure.stratum_map`'s `relation` column above —
a consumer choosing to join on exact ontology matches only does it visibly,
rather than silently inheriting a broader or partial term's burden.

### measure.cancer_site_group

A small, cited lookup beside `measure.cancer_site` for reading burden through
a prevention lens (#126): a catchment researcher's caution is that no single
burden metric should drive decisions, and preventability changes which sites
matter most (e.g. it raises melanoma and cervical cancer above where
mortality alone ranks them).

```
group_id            -- 'tobacco_associated' | 'hpv_associated' |
                        'obesity_associated' | 'alcohol_associated' |
                        'alcohol_associated_limited_evidence' |
                        'uspstf_screenable' | 'vaccine_preventable' |
                        'uv_associated'
group_label
cancer_site_code     -- FK measure.cancer_site
mapping_relation     -- 'exact' | 'broader' -- same vocabulary as
                        measure.cancer_site's column of the same name (#90)
basis                -- the citation: publisher, page, date, verbatim quote
source_url
note                 -- caveats: why 'broader', evidence-strength language
                        the citation itself uses, disagreement between
                        authorities
source               -- always 'CANCERONICE' (this project's own curated
                        grouping; see Derived indices)
```

Every row cites one authoritative primary source (CDC, USPSTF, NCI, or a US
Surgeon General's report) with a URL and a quoted sentence — no memberships
from memory. Where CDC states weaker evidence for a site than its core causal
list (alcohol's "some studies indicate" language for stomach, pancreatic and
prostate cancer), that is its own `alcohol_associated_limited_evidence`
group rather than being flattened into `alcohol_associated` alongside the
sites CDC states plainly. Where a citation's definition is by histology or
subsite finer than SEER site recode can express (HPV-associated oropharynx
spans SEER's separate Oropharynx and Tonsil leaves; obesity's citation names
adenocarcinoma of the esophagus specifically, not all esophageal histologies;
obesity's citation names meningioma, which has no SEER leaf of its own, only
the combined Brain and Other Nervous System code), the row is marked
`broader` with a `note` explaining
the mismatch, the same discipline #90 applies to the NCIt/MONDO bridge.

## Facilities

### facility.site

```
facility_id, source, source_release
kind                -- mammography | fqhc | rhc | lung_screening | provider | hospital | tri | superfund
name, address, lat, lon
geo_id (tract), geo_vintage
attributes_json     -- JSON string, keys documented per source
first_seen, retired_in
```

`attributes` was originally specified as `map<string,string>`; implementing
the first writer (HRSA health-center sites, #38) found that a DuckDB MAP
value cast through Arrow into that Iceberg column type aborts the process —
Arrow's C++ validator fails a check ("Map array keys array should have no
nulls") that is not a catchable Python exception, reproduced with a minimal
example. `attributes_json` (a JSON string column) replaces it.

`source_release` is NULL for a continuously-refreshed snapshot source (its
retrieval date is recorded in `provenance.release` and the source's own raw
version column instead): repeating it here would make an unchanged row look
changed on every ingest, which is a stopgap under issue #19, not that issue's
resolution.

Facility lists are the clearest case for history: "which certified mammography
facilities existed in this county in 2023" is unanswerable from any live
source.

## Catchment

### catchment.center

NCI-designated centers (and others that opt in): id, name, designation type,
designation dates.

### catchment.member

```
center_id, geo_id, geo_vintage
declared_by          -- 'NCI_OCC' | 'CENTER_PR' | 'PUBLISHED_PAPER'
valid_from, valid_to
```

Catchment definitions are self-declared by centers and change. Proposed
mechanism, mirroring the federation registry: a `catchments.yaml` in the repo,
one entry per center, updated by pull request, with CI validating geo_ids
against `geography.unit`. Seed from published national catchment maps where
their licence allows; otherwise each center contributes its own.

## Resource (pointers)

For large or non-redistributable data (NaNDA tables, boundary geometries,
CIF downloads): what exists, its licence, its
geography/time coverage, and where to fetch it. Same shape as biocOnIce's
`resource` namespace; inherits whatever biocOnIce decides in its #30.

## Provenance

### provenance.lineage

Table- and column-level lineage DAG, captured at ingest with sqlglot (#140):
what fed each derived column's values, down to the raw table and — where the
module's own SQL states it directly — the raw column and the expression that
produced it. One row per edge; `to_column` NULL is a table-level-only edge
(the source is known, the column isn't), `from_kind='url'` roots a raw table
at the upstream URL it was landed from. Captured from the SQL a module
already writes, never inferred from read/write order. Rebuildable, so
`merge.write` scopes it on `(release, job, to_table)` — no Type 2 history, same as
`provenance.release`. Full column contract in `schemas.py`; capture API in
`cancerbasemap.lineage`. Wired module by module — see AGENTS.md / the module's
own docstring for whether a given source calls it yet.

---

# Licence gate

A source qualifies only if it is (a) redistributable by a third party,
(b) published as a complete dump per release (or scrapeable completely, with
the vintage rule), and (c) aggregate-only. Licence is assessed **before**
ingest, as in biocOnIce.

## Ruled out, and why

- **USCS Public Use Database** — only analyzable inside SEER\*Stat after a
  per-release agreement, carries no county-level data, and forbids linking to
  other databases without CDC approval. Doubly disqualified.
- **USCS Restricted Access Database / county incidence via special access** —
  RDC-only or bilateral access; the reason CIF has county incidence and a
  public lake cannot republish it. SCP's published county rates are the
  public route.
- **SEER Research / Research Plus data** — DUA per user.
- **Registry microdata of any kind**, including the Colorado Central Cancer
  Registry, even in aggregated form, unless the registry publishes the
  aggregate itself.

## Needs review before ingest

- **Area Deprivation Index** (Neighborhood Atlas) — registration-gated;
  redistribution terms not established. Its methodology is also disputed
  (unstandardized inputs let home value and income dominate). Consider
  publishing a transparent, standardized deprivation index derived in-lake
  from ACS instead, with code — see *Derived indices*.
- **County Health Rankings** — now on Zenodo; confirm the record's licence.
- **NaNDA** — ICPSR terms; pointer until cleared.
- **NHGIS crosswalks** — IPUMS terms; use Census relationship files meanwhile.
- **CDC WONDER** — data-use restrictions on small cells and no bulk dump;
  likely pointer-only.
- **ACR Lung Cancer Screening Registry locator** — likely proprietary.

---

# Sources — first tranche

| Source | Why | Version axis | Notes |
| --- | --- | --- | --- |
| **Census TIGER/Line + relationship files** | the spine | boundary vintage | public domain; geometry → GeoParquet/PMTiles pointer |
| **State Cancer Profiles** | county incidence, mortality, screening, risk, demographics | vintage | land from scraper releases / cdsci-lake (ADR-0012); existing Zenodo vintages backfill history |
| **SEER county & tract population** | denominators matching the rates | release | freely downloadable, no DUA |
| **ACS 5-year** (curated table subset) | demographics, poverty, vehicle access, insurance/Medicaid | release year | public domain; MOE → `interval_level = 0.90`; releases before 2017–2021 not landed (#125 — the keyless bulk Summary File only ships the sequence-based format before "2021", a different enough parser to be out of scope; CIF parity does not need it) |
| **CDC PLACES** | model-based tract/county screening & behaviors | annual release | public domain; `method = model_based` |
| **CDC/ATSDR SVI** | area-level context index | edition (2000–2022) | land every published edition |
| **USDA ERS RUCC / RUCA; Food Access Atlas** | rurality, food access | edition | public domain |
| **HRSA AHRF, HPSA, health-center sites** | workforce, shortage areas, FQHC/RHC | release | public domain |
| **FDA MQSA certified facilities** | mammography access | weekly snapshot | history is the value |
| **CMS NPPES** | provider locations by taxonomy (GI, colorectal surgery, oncology) | monthly full file | large but complete dumps |

## Second tranche

EPA SDWIS violations; FCC Broadband Data Collection (Form 477 is retired);
County Health Rankings (after licence check); NCI Tobacco Policy Viewer;
state open-data portals (e.g. Colorado's) as a pattern for state-level
additions.

---

# Derived indices

Composite indices are derived in-lake from landed tables, with the code in
this repository and a `method` doc per index — never landed as opaque scores
when an open computation is possible. Candidates: the Yost index (used in SEER
work), a standardized deprivation index as an open ADI alternative, rurality
composites. Derived indices are writers like any other (`source = 'CANCERONICE'`).

---

# Recipes

Shipped as site recipe pages and in the MCP server, as in biocOnIce:

1. **Catchment burden table** — for a center, every cancer measure over its
   catchment geographies, with source, release and interval, as of a named
   catalog release. The CCSG hook.
2. **What changed** — diff two SCP vintages for one county.
3. **Access gaps** — tracts in a catchment with low PLACES screening
   prevalence and no certified mammography facility within N km, at a date.
4. **CIFTools export** — write CIF-shaped files for any catchment.
5. **Cross-lake** — publications from biocOnIce's iCite tables whose MeSH or
   gene annotations match a catchment's top-burden cancer sites.

---

# Acceptance criteria

Verified against a real deployment, as in biocOnIce.

**A. Point in time.** In one release bundle, the raw SCP tables filtered on
`scp_vintage = 'V3'` reproduce the landed topics of the V3 Zenodo deposit
exactly, and `measure.observation` filtered on `source_release = 'V3'` is their
documented derivation (ADR-0001).

**B. Geography.** A 2019 Connecticut county-level measure crosswalks to 2022
planning regions with stated weights; an old FIPS code resolves through
`geography.alias`.

**C. Suppression.** No row with `value_status != 'reported'` has a non-NULL
`value`; every source's suppression sentinels are covered by a fixture test.

**D. Catchment report.** The catchment burden recipe reproduces the University
of Colorado Cancer Center's catchment table with a provenance manifest naming
every source release used.

**E. Access.** A release bundle reads without credentials from DuckDB and
DuckDB-WASM (`.read views.sql`, or `ATTACH` of `cancerbasemap.duckdb` over HTTPS);
ECCO reads its data from the bundle instead of its own Parquet (ADR-0001).

---

# Milestones

**M1 — spine and the flagship.** Geography (county + tract, 2010 and 2020
vintages), SCP with all vintages, SEER population, ACS subset, PLACES.
Acceptance A, B, C, E.

**M2 — access and context.** Facilities, SVI, RUCA/RUCC, AHRF; catchment
namespace and `catchments.yaml`; recipes 1–4; MCP server. Acceptance D.

**M3 — environment, indices, federation.** Second tranche; derived indices;
cancer-site ↔ MONDO bridge exercised from biocOnIce; federation registry entry.

---

# Open questions

- **Catchment definitions.** Is there a redistributable national source, or is
  PR-by-center the only honest route?
- **Geometry.** Iceberg v3 has native geometry types; is client support
  (DuckDB spatial over Iceberg) good enough to store geometry in-table, or do
  GeoParquet/PMTiles pointers stay the default?
- **ZCTA and ZIP.** Include ZCTA as a level; ZIP-to-ZCTA crosswalks are the
  usual licence trap.
- **Scraped provenance.** SCP is public-domain US government content, but the
  lake republishes a scrape; the provenance record should say so explicitly.
- **Partnership.** Approach the CIF team and the CARDS group before M2, so the
  export recipe targets what adopters actually load.
