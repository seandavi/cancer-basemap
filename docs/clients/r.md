## R

**Not executed on this build host.** R 4.6.1 is installed here with DBI,
dplyr and dbplyr, but not the `duckdb` package. A source build of `duckdb`
1.5.5 into a throwaway library was started (no rhel9 binary exists yet for
R 4.6 on Posit's package manager, so it fell back to compiling from
source), and *did* finish successfully — but the throwaway library lived
under a session-scratch directory that was reclaimed hours later, before
the R snippets below were run against it. Re-running a from-scratch DuckDB
compile (previously ~15-20 minutes even in parallel) wasn't repeated for
this pass. Everything R-shaped below is written against the DBI/dplyr/
dbplyr API and this project's own SQL (verified separately via the DuckDB
CLI and Python, both against the live catalog — see
[duckdb-cli.md](duckdb-cli.md)), but not run as R code. If you can run R,
please report back on [issue #115](https://github.com/seandavi/cancer-basemap/issues/115).

[`r/connect.R`](../../r/connect.R) ports bioc-on-ice's `r/connect.R` (same
pattern, Cancer Basemap's catalog/endpoint). It tries the current attach
option name (`URI`) and falls back to the old one (`ENDPOINT`) on error,
because CRAN's `duckdb` package is 1.5.5 as of this writing — confirmed
via the Python `duckdb` package at the same version (see
[duckdb-cli.md](duckdb-cli.md)) that `URI` fails there with
`Unhandled options found: uri` and `ENDPOINT` is required. **The fallback
logic itself was not run in R** (no working `duckdb` package on this build
host, see above) — only the underlying DuckDB behavior it depends on:

```r
cancerbasemap_connect <- function(endpoint = "https://icegate-canceronice.seandavi.workers.dev",
                                   catalog = "canceronice",
                                   alias = "coi") {
  con <- DBI::dbConnect(duckdb::duckdb())
  DBI::dbExecute(con, "INSTALL iceberg; LOAD iceberg;")
  tryCatch(
    DBI::dbExecute(con, sprintf(
      "ATTACH '%s' AS %s (TYPE ICEBERG, URI '%s', AUTHORIZATION_TYPE 'none');",
      catalog, alias, endpoint
    )),
    error = function(e) DBI::dbExecute(con, sprintf(
      "ATTACH '%s' AS %s (TYPE ICEBERG, ENDPOINT '%s', AUTHORIZATION_TYPE 'none');",
      catalog, alias, endpoint
    ))
  )
  con
}
```

### DBI: the README's worked query

```r
source("r/connect.R")
con <- cancerbasemap_connect()

DBI::dbGetQuery(con, "
  SELECT u.name, o.source_release, o.value AS pct, o.lower, o.upper, o.value_status,
         r.value AS rucc_code
  FROM coi.measure.observation o
  JOIN coi.geography.unit u
    ON u.geo_id = o.geo_id AND u.vintage = 2026 AND u.valid_to IS NULL
  LEFT JOIN coi.measure.observation r
    ON r.geo_id = o.geo_id AND r.source = 'RUCC' AND r.valid_to IS NULL
  WHERE o.source = 'PLACES' AND o.measure_id = 'PLACES:MAMMOUSE:age_adjusted'
    AND o.source_release = '2025' AND u.parent_geo_id = 'state:08'
    AND o.valid_to IS NULL
  ORDER BY pct LIMIT 5;
")
```

### dplyr/dbplyr

An attached catalog table is three-part (`catalog.schema.table`), which
`dplyr::tbl()` doesn't parse from a bare string. Two documented ways to hand
it a qualified name: `dplyr::tbl(con, I("coi.measure.observation"))` (`I()`
marks the string as already-quoted SQL, so dbplyr won't try to treat it as
a single identifier) or `dplyr::tbl(con, dbplyr::in_catalog("coi",
"measure", "observation"))` (dbplyr's own three-level-identifier
constructor, added for catalog.schema.table backends). Both are written
here; **which one this project's exact dbplyr version accepts was not
confirmed by execution** — try `I(...)` first, it's the smaller
dependency footprint (base dplyr, not a dbplyr-version-specific export).

```r
library(dplyr)

mammo <- tbl(con, I("coi.measure.observation")) |>
  filter(source == "PLACES", measure_id == "PLACES:MAMMOUSE:age_adjusted",
         source_release == "2025", is.na(valid_to))

rucc <- tbl(con, I("coi.measure.observation")) |>
  filter(source == "RUCC", is.na(valid_to)) |>
  select(geo_id, rucc_code = value)

geo <- tbl(con, I("coi.geography.unit")) |>
  filter(level == "county", vintage == 2026, parent_geo_id == "state:08", is.na(valid_to)) |>
  select(geo_id, name)
```

### Worked analysis: mammography screening by rurality, Colorado counties

PLACES mammography screening (`PLACES:MAMMOUSE:age_adjusted`, 2025 release)
for every Colorado county, with its 95% CI and its RUCC rurality code,
collected into a plain data frame:

```r
result <- geo |>
  inner_join(mammo, by = "geo_id") |>
  left_join(rucc, by = "geo_id") |>
  select(name, value, lower, upper, value_status, rucc_code) |>
  arrange(value) |>
  collect()

DBI::dbDisconnect(con, shutdown = TRUE)
```

`result` is a standard `tibble`/`data.frame` at this point — the DuckDB CLI
run of the same shape of query (see [duckdb-cli.md](duckdb-cli.md) and the
README) returns e.g. Kiowa, Bent and Otero counties as the lowest-screening
counties in the 60s (percent), each with a `reported` `value_status` and a
non-NULL CI; a suppressed county elsewhere in the state would show `value`
and the CI columns as `NA` with `value_status` still telling you why
(`suppressed_small_count`, etc.) — the same contract shown running end to
end in [duckdb-cli.md](duckdb-cli.md) and [seerstat.md](seerstat.md).
