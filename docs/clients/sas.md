## SAS

**NOT YET RUN IN SAS.** SAS has no Iceberg engine, so every route puts
DuckDB on one side of a boundary SAS never crosses. In order of how little
they assume about your SAS environment:

1. **DuckDB CLI &rarr; CSV/Parquet &rarr; `PROC IMPORT`** (or the Parquet
   LIBNAME engine on Viya). [`sas/cancerbasemap.sas`](../../sas/cancerbasemap.sas)
   implements this as a macro. Requires XCMD (SAS's setting that allows
   shelling out) enabled for the session — `FILENAME PIPE` shells out to
   run `duckdb`. **NOXCMD is the default on many managed SAS 9.4 servers and
   on SAS OnDemand for Academics / Viya.** If your site runs NOXCMD, this
   macro cannot execute at all; run the same DuckDB CLI command on your own
   machine instead, producing a CSV or Parquet file, and upload that file
   for `PROC IMPORT` (or, on Viya, the Parquet LIBNAME engine to read it
   directly, no PIPE needed).
2. **`PROC PYTHON` (Viya only).** Viya's Python integration can run the
   `duckdb` Python package directly inside a SAS Studio Viya session and
   hand a pandas DataFrame back to SAS. Not tested here — Viya is not
   available on this build host.
3. **SAS/ACCESS to ODBC + the DuckDB ODBC driver.** DuckDB ships an ODBC
   driver; SAS/ACCESS Interface to ODBC can then treat `coi.*` tables like
   any ODBC source. The caveat: an `ATTACH` is a live-session command, not
   something stored in a DuckDB database file, so it has to be issued on
   **every** ODBC connection SAS opens — there is no DuckDB database file
   to attach it into once and reuse. Checked DuckDB's own ODBC docs
   ([ODBC Configuration](https://duckdb.org/docs/lts/clients/odbc/configuration),
   [ODBC 101 guide](https://duckdb.org/docs/current/guides/odbc/general))
   for a documented way to run init SQL automatically per connection (an
   `odbc.ini` key, a connection-string option, an autoexec setting): **there
   isn't one.** The documented `odbc.ini` keys are `Driver`, `Database` and
   `access_mode` only. In practice that means either running the `ATTACH`
   explicitly as the first statement of every SAS/ACCESS session (e.g. a
   `PROC SQL` pass-through `CONNECT` block that issues it before any query),
   or pointing `Database` at a local DuckDB file that already has
   `ATTACH ... AS coi` baked in via a `.duckdbrc`-style init script your site
   controls — neither of which this project has built or tested.

See [`sas/cancerbasemap.sas`](../../sas/cancerbasemap.sas) for the macro
implementing route 1, with a "NOT YET RUN IN SAS" banner and a checklist for
whoever can run SAS. What **was** verified on the DuckDB side of the
boundary:

```
$ duckdb --version
v2.1.0-alpha40519 (Unknown Version) 154c2c8d5f

$ duckdb -csv -nullvalue '' -c "
INSTALL iceberg; LOAD iceberg;
ATTACH 'canceronice' AS coi (TYPE ICEBERG, URI 'https://icegate-canceronice.seandavi.workers.dev', AUTHORIZATION_TYPE 'none');
SELECT geo_id, source, source_release, measure_id, value, lower, upper, value_status
FROM coi.measure.observation
WHERE source = 'PLACES' AND measure_id = 'PLACES:MAMMOUSE:age_adjusted'
  AND source_release = '2025' AND valid_to IS NULL
  AND geo_id IN ('county:08031','county:08001','county:48301')
ORDER BY geo_id;
"
geo_id,source,source_release,measure_id,value,lower,upper,value_status
county:08001,PLACES,2025,PLACES:MAMMOUSE:age_adjusted,64.9,57.6,71.7,reported
county:08031,PLACES,2025,PLACES:MAMMOUSE:age_adjusted,73.1,66.3,78.9,reported
county:48301,PLACES,2025,PLACES:MAMMOUSE:age_adjusted,,,,suppressed_small_count
```

That's the exact CSV `%cancerbasemap()`'s `FILENAME PIPE` would hand SAS:
a header row, a FIPS code with a leading zero preserved (`county:08001`,
because `geo_id` is a string like `'county:08031'`, never a bare number —
see the caveat in `sas/cancerbasemap.sas` about a bare `fips` column
instead), and a suppressed cell (`county:48301`) as an **empty field**
(`-nullvalue ''`), which `PROC IMPORT`/a numeric `INPUT` reads as a genuine
SAS missing value, with `value_status` still telling you why.
