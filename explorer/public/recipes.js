// Fixed recipe list for Cancer Basemap — worked queries against tables that
// are live today (anonymous read): geography.unit, measure.observation,
// measure.definition, measure.stratum, provenance.release. Every SQL string
// here is self-contained (INSTALL/LOAD/ATTACH included) so pasting one
// verbatim into desktop DuckDB works with no setup.
//
// Verified live against the catalog on 2026-09-18 (`duckdb` Python CLI, no
// browser) — the `verified` field is the row/value DuckDB actually returned
// that day, not a guess. Re-run them yourself to check currency.

const ATTACH = `INSTALL iceberg; LOAD iceberg;
ATTACH 'canceronice' AS coi (
    TYPE ICEBERG,
    ENDPOINT 'https://icegate-canceronice.seandavi.workers.dev',
    AUTHORIZATION_TYPE 'none'
);`;

export const RECIPES = [
  {
    id: "state-screening-rurality",
    title: "Screening in a state's counties, with interval and rurality",
    description:
      "Mammography screening (swap measure_id for any PLACES measure) across a state's counties (swap 'state:08' " +
      "for any state FIPS), lowest first, with the confidence interval, the release that said so, and the " +
      "county's RUCC rurality code. PLACES and RUCC rows carry geo_vintage=2020 but their geo_ids are actually the " +
      "2026 Gazetteer vintage's (issue #21, undecided) — so the geography join names vintage 2026 explicitly " +
      "rather than trusting geo_vintage.",
    sql: `${ATTACH}

SELECT u.name, o.source_release, o.value AS pct, o.lower, o.upper, o.value_status,
       r.value AS rucc_code
FROM coi.measure.observation o
JOIN coi.geography.unit u
  ON u.geo_id = o.geo_id AND u.vintage = 2026 AND u.valid_to IS NULL  -- see description: not geo_vintage
LEFT JOIN coi.measure.observation r
  ON r.geo_id = o.geo_id AND r.source = 'RUCC' AND r.valid_to IS NULL
WHERE o.source = 'PLACES' AND o.measure_id = 'PLACES:MAMMOUSE:age_adjusted'
  AND o.source_release = '2025' AND u.parent_geo_id = 'state:08'
  AND o.valid_to IS NULL
ORDER BY pct LIMIT 10;`,
    verified: "Colorado, mammography screening, 2025 release — lowest is Kiowa County at 62.3% (57.4–66.8, RUCC 9)",
  },
  {
    id: "places-release-diff",
    title: "What changed between PLACES releases 2024 and 2025",
    description:
      "Per-measure diff for one county between two PLACES releases, largest absolute change first. The geo_id " +
      "here ('county:09170', South Central Connecticut Planning Region) is a 2026-vintage id even though PLACES " +
      "tags its rows geo_vintage=2020 — the same issue #21 mismatch as the screening recipe, just not needing a " +
      "geography join to see it.",
    sql: `${ATTACH}

SELECT o25.measure_id,
       o24.value AS v2024, o25.value AS v2025,
       round(o25.value - o24.value, 2) AS delta
FROM coi.measure.observation o24
JOIN coi.measure.observation o25
  ON o24.measure_id = o25.measure_id AND o24.geo_id = o25.geo_id
  AND o24.stratum_id = o25.stratum_id
WHERE o24.source = 'PLACES' AND o24.source_release = '2024'
  AND o25.source = 'PLACES' AND o25.source_release = '2025'
  AND o24.geo_id = 'county:09170'
  AND o24.valid_to IS NULL AND o25.valid_to IS NULL
  AND o24.value IS NOT NULL AND o25.value IS NOT NULL
ORDER BY abs(delta) DESC
LIMIT 15;`,
    verified: "largest mover is PLACES:HIGHCHOL:crude, 33.7% -> 38.2% (+4.5 points)",
  },
  {
    id: "suppressed-cells",
    title: "Suppressed and unavailable cells",
    description:
      "Every row whose value_status is not 'reported' — proving value reads as NULL for every one of them, never " +
      "a number (AGENTS.md's suppression gate, SPEC.md acceptance C).",
    sql: `${ATTACH}

SELECT source, source_release, measure_id, geo_id, value_status, value
FROM coi.measure.observation
WHERE value_status != 'reported' AND valid_to IS NULL;`,
    verified: "68 rows (2 not_available, 66 suppressed_small_count); value IS NULL in all 68",
  },
  {
    id: "ct-boundary-history",
    title: "A county's boundary history across Gazetteer vintages",
    description:
      "Connecticut's county-level geography by vintage: eight traditional counties in 2010 and 2020, replaced by " +
      "nine planning regions in 2026 — a real redistricting, not a data error, and the reason recipes above pin " +
      "an explicit vintage instead of trusting geo_vintage.",
    sql: `${ATTACH}

SELECT vintage, geo_id, name, round(aland_m2 / 1e6, 1) AS land_km2
FROM coi.geography.unit
WHERE level = 'county' AND parent_geo_id = 'state:09' AND valid_to IS NULL
ORDER BY vintage, geo_id;`,
    verified: "8 counties at vintage 2010 and 2020 each, 9 planning regions at vintage 2026 (25 rows total)",
  },
  {
    id: "provenance",
    title: "Provenance — what each catalog release was built from",
    description:
      "One row per (release, source): the upstream version, how it was resolved, and when it was retrieved — " +
      "what makes a Cancer Basemap release reproducible.",
    sql: `${ATTACH}

SELECT release, source, source_version, version_method, retrieved_at, row_count
FROM coi.provenance.release
ORDER BY release, source;`,
    verified:
      "release 2026.09: census_gazetteer@2026 (3,222 rows), ers_rucc@2023 (9,703 rows), places@2025 (229,298 rows)",
  },
];

export const PROVENANCE_MATRIX_SQL = `${ATTACH}

PIVOT coi.provenance.release
ON source
USING first(source_version)
GROUP BY release
ORDER BY release;`;
