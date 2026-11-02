## Python

No new dependency: `duckdb` (already this project's own dependency,
`duckdb>=1.4` in `pyproject.toml`) is all it takes.

```python
import duckdb
con = duckdb.connect()
con.execute("ATTACH 'https://basemap.cancerdatasci.org/data/latest/cancerbasemap.duckdb' AS cbm (READ_ONLY)")
con.sql("SELECT count(*) FROM cbm.geography.unit").fetchall()
```

Fetch with `duckdb`, `requests` or `polars` (`pl.scan_parquet(url)` works on
any file in a release). Python's default `urllib` user agent is blocked by the
zone: HTTP 403, Cloudflare error 1010.

Pin a dated folder (`.../data/v2026-11-02/cancerbasemap.duckdb`) for anything
you will rerun, and cite the Hugging Face tag (`seandavis/cancerbasemap@2026-11-02`).
Run here with this project's own pinned `duckdb` (`1.5.5`, from `uv run
python`) against the `2026-11-02` release. See [duckdb-cli.md](duckdb-cli.md)
for the CLI form and the `views.sql` route.
