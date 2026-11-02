## DuckDB CLI

Everything else on this page is a wrapper around this. No account, no
token, nothing to install beyond `duckdb` itself. A release is a
`cancerbasemap.duckdb` file of views over Parquet files, read over HTTPS:

```sh
duckdb -csv -c "
ATTACH 'https://basemap.cancerdatasci.org/data/latest/cancerbasemap.duckdb' AS cbm (READ_ONLY);
SELECT * FROM cbm.geography.unit LIMIT 5;
"
```

`-csv` is one of several output modes (`-json`, `-table`; `COPY ... TO
'x.parquet'` for Parquet); drop it for a formatted table on a terminal. To
save a query's result to a file instead of printing it:

```sh
duckdb -c "
ATTACH 'https://basemap.cancerdatasci.org/data/latest/cancerbasemap.duckdb' AS cbm (READ_ONLY);
COPY (SELECT * FROM cbm.measure.observation WHERE source = 'PLACES') TO 'places.parquet';
"
```

**`views.sql` instead of `ATTACH`.** Every release also holds a `views.sql`
that creates the same views in your own session (`measure.observation`
instead of `cbm.measure.observation`). `.read` cannot open a URL, so fetch it
first:

```sh
curl -sO https://basemap.cancerdatasci.org/data/latest/views.sql
duckdb -c ".read views.sql" -c "SELECT count(*) FROM geography.unit"
```

**Pin a release.** Replace `latest` with a dated folder, e.g.
`.../data/v2026-11-02/cancerbasemap.duckdb`. Each dated folder's views read
that folder's own Parquet files. R2 keeps the newest release of each of the
last 12 months; a release you will cite is on Hugging Face as
`seandavis/cancerbasemap@2026-11-02` (download it, then query the local
files). A bundle holds current rows only, so there is no `valid_to` column to
filter on.

Run with `duckdb` `v2.0.0-alpha43763` and with the Python `duckdb` package
`1.5.5` (this repo's pinned version): both attach the release over HTTPS with
no extension to install by hand (`httpfs` loads itself).
