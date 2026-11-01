# Clients: reading Cancer Basemap from R, SAS, and SEER*Stat

The README's `ATTACH` is DuckDB SQL. Most catchment-office analysts work in
R, SAS or SEER*Stat and touch SQL rarely, if at all. Start with the DuckDB
CLI page — everything else builds on it — then pick your tool. Each is its
own page, honestly marked where it was and wasn't run:

- [DuckDB CLI](clients/duckdb-cli.md)
- [R](clients/r.md)
- [SAS](clients/sas.md)
- [SEER\*Stat](clients/seerstat.md)
- [Python](clients/python.md)

## Which route should I use

| You use | Route | Runs where |
| --- | --- | --- |
| R | [`r/connect.R`](../r/connect.R) + DBI/dplyr | your own machine, live |
| SAS with XCMD allowed | [`sas/cancerbasemap.sas`](../sas/cancerbasemap.sas) macro (DuckDB CLI via `FILENAME PIPE`) | SAS server shells out to `duckdb` |
| SAS with XCMD blocked (NOXCMD) | Run the DuckDB CLI on another machine, `PROC IMPORT` the CSV/Parquet it writes | your machine, then upload |
| SAS Viya | `PROC PYTHON`, or the Parquet LIBNAME engine over a DuckDB-written extract | Viya |
| SEER\*Stat | Not a client of the lake at all — export a results matrix, then join it in DuckDB/R | your machine, offline join |
| Python | `duckdb` (three lines) | your own machine, live |
