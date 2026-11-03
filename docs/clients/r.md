## R

Run on this build host with R 4.6.1, `duckdb` 1.5.6, DBI 1.3.0 and dplyr
1.2.1, against the `latest` release as of 2026-11-02: `connect.R`, the DBI
query and the dplyr analysis below returned the results described.

[`r/connect.R`](../../r/connect.R) ports bioc-on-ice's `r/connect.R` (same
pattern, Cancer Basemap's bundle). It attaches a release's
`cancerbasemap.duckdb` read-only over HTTPS, as `cbm`. No token, no extension
to install by hand:

```r
cancerbasemap_connect <- function(release = "latest",
                                   base = "https://basemap.cancerdatasci.org/data",
                                   alias = "cbm") {
  con <- DBI::dbConnect(duckdb::duckdb())
  DBI::dbExecute(con, sprintf(
    "ATTACH '%s/%s/cancerbasemap.duckdb' AS %s (READ_ONLY);", base, release, alias
  ))
  con
}
```

Pin a dated release for anything you will rerun:
`cancerbasemap_connect("v2026-11-02")`. A bundle holds current rows only, so
there is no `valid_to` column to filter on.

### DBI: the README's worked query

```r
source("r/connect.R")
con <- cancerbasemap_connect()

DBI::dbGetQuery(con, "
  SELECT u.name, o.source_release, o.value AS pct, o.lower, o.upper, o.value_status,
         r.value AS rucc_code
  FROM cbm.measure.observation o
  JOIN cbm.geography.unit u
    ON u.geo_id = o.geo_id AND u.vintage = 2026
  LEFT JOIN cbm.measure.observation r
    ON r.geo_id = o.geo_id AND r.source = 'RUCC'
  WHERE o.source = 'PLACES' AND o.measure_id = 'PLACES:MAMMOUSE:age_adjusted'
    AND o.source_release = '2025' AND u.parent_geo_id = 'state:08'
  ORDER BY pct LIMIT 5;
")
```

### dplyr/dbplyr

An attached table is three-part (`database.schema.table`), which
`dplyr::tbl()` doesn't parse from a bare string. Hand it a qualified name with
`I()`, which marks the string as already-quoted SQL:

```r
library(dplyr)

mammo <- tbl(con, I("cbm.measure.observation")) |>
  filter(source == "PLACES", measure_id == "PLACES:MAMMOUSE:age_adjusted",
         source_release == "2025")

rucc <- tbl(con, I("cbm.measure.observation")) |>
  filter(source == "RUCC") |>
  select(geo_id, rucc_code = value)

geo <- tbl(con, I("cbm.geography.unit")) |>
  filter(level == "county", vintage == 2026, parent_geo_id == "state:08") |>
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

`result` is a standard `tibble`/`data.frame` at this point. Its lowest rows
are Kiowa, Otero and Bent counties in the low 60s (percent), each with a
`reported` `value_status` and a non-NA CI. A suppressed county elsewhere would
show `value` and the CI columns as `NA` with `value_status` still telling you
why (`suppressed_small_count`, etc.). That is the same contract shown running end to
end in [duckdb-cli.md](duckdb-cli.md) and [seerstat.md](seerstat.md).
