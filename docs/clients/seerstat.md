## SEER*Stat

SEER\*Stat cannot connect to Cancer Basemap, or to anything external. It reads
only its own SEER\*Stat-format databases (`.dic`/state-county-level session
files it manages itself). There is no route where SEER\*Stat is the client
and Cancer Basemap is the server. The workflow instead runs the other
direction:

1. In SEER\*Stat, run a rate session (county &times; year &times; site) as
   you normally would.
2. Export the results matrix as delimited text. From NCI's own SEER\*Stat
   help pages (`Matrix Options`, `Rate Statistic Tab`, `Rate Output Tab`;
   see citations below): the export writes a delimited **data** file plus a
   paired **dictionary** file describing it, with format choices (field
   delimiter, whether to include a header) and a "Remove Flags (Footnote),
   Prefix and Suffix Characters" option on the Export dialog. Suppressed or
   footnoted cells (below your session's case-count or population
   threshold) are flagged in the on-screen matrix; **the exact default flag
   character is not stated on the pages this project could reach**
   ([Matrix Options](https://seer.cancer.gov/help/seerstat/seer-stat-basics/results-matrix/features-of-a-results-matrix/matrix-options),
   [Rate Statistic Tab](https://seer.cancer.gov/help/seerstat/rate-session/rate-statistic-tab),
   [Rate Output Tab](https://seer.cancer.gov/help/seerstat/rate-session/rate-output-tab),
   [SEER\*Stat FAQ](https://seer.cancer.gov/seerstat/faq.html)). Confirm it
   against your own export before writing a parser that depends on it.
3. Join the export to a Cancer Basemap release in DuckDB or R, by 5-digit county FIPS and
   year. This is the same "status, never a number" contract Cancer Basemap itself uses,
   applied to whatever suppression marker your export shows.

[`docs/examples/seerstat_synthetic_export.csv`](../examples/seerstat_synthetic_export.csv)
is a **SYNTHETIC** stand-in for step 2: five Colorado counties, invented
breast cancer counts and rates, two of them suppressed. It is not SEER
data. Because the exact suppression symbol isn't confirmed,
[`docs/examples/seerstat_join.sql`](../examples/seerstat_join.sql) doesn't
hardcode one: it treats any Count/Rate field that fails a numeric cast as
suppressed, whatever character your version uses.

Run against the live `latest/` release (`2026-11-02`):

```
$ duckdb -csv -c ".read docs/examples/seerstat_join.sql"
name,geo_id,year,site,seer_count,seer_age_adj_rate,seer_status,svi_pctile,rucc_code,mammo_screening_pct,mammo_status,n_fqhc
Adams County,county:08001,2022,Female Breast,142,127.4,reported,0.7264,1.0,64.9,reported,13
Alamosa County,county:08003,2022,Female Breast,NULL,NULL,suppressed,0.8253,7.0,68.1,reported,6
Boulder County,county:08013,2022,Female Breast,238,131.2,reported,0.209,2.0,72.1,reported,17
Denver County,county:08031,2022,Female Breast,412,129.8,reported,0.5603,1.0,73.1,reported,72
Kiowa County,county:08061,2022,Female Breast,NULL,NULL,suppressed,0.3312,9.0,62.3,reported,1
```

(Re-run 2026-11-02 against the release bundle. Only Denver's FQHC count moved,
71 to 72, because the bundle holds the newest HRSA snapshot. `-csv` prints
SQL NULL as `NULL`; add `-nullvalue ''` for empty fields.)

Notes:

- No county-level mammography facility count. `facility.site` rows of
  kind `mammography` all currently carry `geo_id IS NULL` (not yet
  geocoded to a county), checked directly against the release
  (`SELECT kind, count(*), count(geo_id) FROM cbm.facility.site GROUP BY 1`
  returns 0 non-null `geo_id` for 9,137 `mammography` rows, vs. 19,471 of
  19,471 for `fqhc`). The join above uses the FQHC count per county as an
  access proxy instead.
- County definitions can drift between SEER\*Stat and Cancer Basemap. SEER's
  own county recodes and Cancer Basemap's Census boundary vintages
  (`geography.unit.vintage`) aren't guaranteed to agree for every county in
  every year; a code that changed (e.g. a rename/recode) resolves through
  `geography.alias` (see [SPEC.md](../../SPEC.md)) rather than silently
  failing the join. Check there if a county from your export doesn't
  match.
- SEER Research/Research Plus data carries a per-user data-use
  agreement. Any real export stays on your own machine. Never upload a
  real SEER\*Stat export here, to a Cancer Basemap release, or to any public repository.
  Only synthetic or already-public aggregate data belongs in this project.

The heavier reverse route is not built: Cancer Basemap extract &rarr; fixed-width file +
SEER\*Prep data dictionary &rarr; a custom SEER\*Stat database you could
open like a native SEER\*Stat session. It would let an
analyst browse Cancer Basemap data inside SEER\*Stat itself rather than joining
outside it, at the cost of maintaining a SEER\*Prep dictionary alongside
every table's schema; the DuckDB/R join above answers the same question
with far less to maintain.
