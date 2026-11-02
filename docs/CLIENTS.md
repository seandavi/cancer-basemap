# Clients: reading Cancer Basemap from R, SAS, and SEER*Stat

The README's `ATTACH` of a release bundle is DuckDB SQL. Most catchment-office analysts work in
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
| SEER\*Stat | Not a client of Cancer Basemap at all — export a results matrix, then join it in DuckDB/R | your machine, offline join |
| Python | `duckdb` (two lines) | your own machine, live |

## Pin a release

Every route below reads `latest/` unless told otherwise. For anything you will
rerun or report, use a dated folder
(`https://basemap.cancerdatasci.org/data/v2026-11-02/`) and record the date, or
download the Hugging Face tag (`seandavis/cancerbasemap@2026-11-02`) and cite
that. See [Versions and citation](https://basemap.cancerdatasci.org/guides/versions-and-citation.html).
