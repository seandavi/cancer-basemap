# Anonymous, read-only connection to a Cancer Basemap release bundle.
#
# No token, no account: a release is public Parquet plus a DuckDB database of
# views over it, served over HTTPS. Ported from bioc-on-ice's r/connect.R
# (same pattern, different bundle).
#
# Usage:
#   source("r/connect.R")
#   con <- cancerbasemap_connect()                     # latest/
#   con <- cancerbasemap_connect("v2026-11-02")        # a pinned release
#   DBI::dbGetQuery(con, "SELECT * FROM cbm.geography.unit LIMIT 5")

cancerbasemap_connect <- function(release = "latest",
                                   base = "https://basemap.cancerdatasci.org/data",
                                   alias = "cbm") {
  con <- DBI::dbConnect(duckdb::duckdb())
  DBI::dbExecute(con, sprintf(
    "ATTACH '%s/%s/cancerbasemap.duckdb' AS %s (READ_ONLY);", base, release, alias
  ))
  con
}

if (sys.nframe() == 0) {
  con <- cancerbasemap_connect()
  print(DBI::dbGetQuery(con, "SELECT schema_name, view_name FROM duckdb_views() WHERE database_name = 'cbm' AND NOT internal"))
  DBI::dbDisconnect(con, shutdown = TRUE)
}
