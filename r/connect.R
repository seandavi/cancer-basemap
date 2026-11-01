# Anonymous connection to Cancer Basemap's Iceberg catalog via icegate.
#
# No token, no account: icegate serves public aggregates read-only. Ported
# from bioc-on-ice's r/connect.R (same pattern, different catalog/endpoint).
#
# Usage:
#   source("r/connect.R")
#   con <- cancerbasemap_connect()
#   DBI::dbGetQuery(con, "SELECT * FROM coi.geography.unit LIMIT 5")

cancerbasemap_connect <- function(endpoint = "https://icegate-canceronice.seandavi.workers.dev",
                                   catalog = "canceronice",
                                   alias = "coi") {
  con <- DBI::dbConnect(duckdb::duckdb())
  DBI::dbExecute(con, "INSTALL iceberg; LOAD iceberg;")
  # DuckDB renamed this attach option from ENDPOINT to URI. CRAN's duckdb
  # package (1.5.5 as of this writing) still wants ENDPOINT; a newer DuckDB
  # wants URI and warns on ENDPOINT. Try the current name, fall back to the
  # old one -- ponytail: two-attempt fallback, not a version check, because
  # that's what actually varies across installs.
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

if (sys.nframe() == 0) {
  con <- cancerbasemap_connect()
  print(DBI::dbGetQuery(con, "SHOW ALL TABLES"))
  DBI::dbDisconnect(con, shutdown = TRUE)
}
