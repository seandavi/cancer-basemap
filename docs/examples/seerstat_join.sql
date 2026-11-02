-- Join a SEER*Stat rate-session export to Cancer Basemap by county FIPS.
--
-- docs/examples/seerstat_synthetic_export.csv is SYNTHETIC: five Colorado
-- counties, invented breast cancer counts/rates for illustration only. It is
-- NOT SEER data. Real SEER*Stat exports are governed by SEER's data-use
-- agreement and must stay on the analyst's own machine -- never uploaded
-- here or to any public repo.
--
-- Run from the repo root:
--   duckdb -c ".read docs/examples/seerstat_join.sql"

ATTACH 'https://basemap.cancerdatasci.org/data/latest/cancerbasemap.duckdb' AS cbm (READ_ONLY);

-- 1. Read the export and normalize its county label to Cancer Basemap's geo_id.
-- SEER*Stat's own "County" attribute text varies by which county variable
-- your session used (County / County recode / State-county recode); this
-- assumes a trailing 5-digit FIPS in parentheses, as this synthetic file
-- has -- adjust the regexp to match whatever your real export shows.
--
-- Suppression: SEER*Stat flags a cell that fails its count/population
-- threshold in the matrix, and the Export dialog can keep or strip that
-- flag character. This script does NOT assume a specific symbol (its docs
-- read for this project did not pin one down -- see docs/CLIENTS.md) --
-- any Count/Rate field that isn't a plain number is treated as suppressed,
-- the same "status, never a number" contract Cancer Basemap itself uses.
CREATE OR REPLACE TEMP TABLE seerstat_export AS
SELECT
    'county:' || regexp_extract("County", '\((\d{5})\)', 1) AS geo_id,
    "Year of Diagnosis"::INTEGER               AS year,
    "Site"                                     AS site,
    TRY_CAST(NULLIF(trim(Count), '') AS BIGINT) AS count,
    Population::BIGINT                          AS population,
    TRY_CAST(NULLIF(trim("Age-Adjusted Rate"), '') AS DOUBLE) AS rate,
    CASE WHEN TRY_CAST(NULLIF(trim("Age-Adjusted Rate"), '') AS DOUBLE) IS NULL
         THEN 'suppressed' ELSE 'reported' END  AS seer_status
FROM read_csv('docs/examples/seerstat_synthetic_export.csv', header = true, all_varchar = true);

-- 2. Join to Cancer Basemap context: SVI overall percentile (2020 vintage, 2022
-- release, the latest), RUCC rurality code, PLACES mammography screening
-- (2025 release), and a count of FQHC sites as a facility-access proxy --
-- facility.site rows of kind 'mammography' carry no geo_id yet, so they
-- can't be joined by county (see docs/CLIENTS.md).
SELECT
    u.name,
    s.geo_id,
    s.year,
    s.site,
    s.count          AS seer_count,
    s.rate           AS seer_age_adj_rate,
    s.seer_status,
    svi.value        AS svi_pctile,
    rucc.value       AS rucc_code,
    places.value     AS mammo_screening_pct,
    places.value_status AS mammo_status,
    fqhc.n_fqhc
FROM seerstat_export s
JOIN cbm.geography.unit u
  ON u.geo_id = s.geo_id AND u.level = 'county' AND u.vintage = 2020
LEFT JOIN cbm.measure.observation svi
  ON svi.geo_id = s.geo_id AND svi.source = 'SVI'
 AND svi.measure_id = 'SVI:RPL_THEMES:2020' AND svi.source_release = '2022'
LEFT JOIN cbm.measure.observation rucc
  ON rucc.geo_id = s.geo_id AND rucc.source = 'RUCC'
LEFT JOIN cbm.measure.observation places
  ON places.geo_id = s.geo_id AND places.source = 'PLACES'
 AND places.measure_id = 'PLACES:MAMMOUSE:age_adjusted' AND places.source_release = '2025'
LEFT JOIN (
    SELECT geo_id, count(*) AS n_fqhc
    FROM cbm.facility.site
    WHERE kind = 'fqhc'
    GROUP BY geo_id
) fqhc ON fqhc.geo_id = s.geo_id
ORDER BY s.geo_id;
