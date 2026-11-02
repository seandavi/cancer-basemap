# Cancer Basemap

Population cancer data — incidence, mortality, screening, risk factors, social
and environmental context, and the places people get care — published as
monthly releases of Parquet files plus DuckDB views, keyed on geography and
time, where every release every source published stays queryable
(`source_release` is a column). Every Cancer Basemap release stays on
[Hugging Face](https://huggingface.co/datasets/seandavis/cancerbasemap).

Sibling of [biocOnIce](https://github.com/seandavi/bioc-on-ice). Public
aggregates only. Site: <https://basemap.cancerdatasci.org/>.

- **[SPEC.md](SPEC.md)** — what the system must do (design source of truth)
- **[AGENTS.md](AGENTS.md)** — working rules for agents and humans
- **[docs/adr/](docs/adr/)** — why decisions went the way they did
- **[docs/DEPLOY.md](docs/DEPLOY.md)** — bucket, catalog, gateway and secrets runbook
- **[CONTRIBUTING.md](CONTRIBUTING.md)** — how to propose a source or a catchment

## Query it

No account, no token. A release is a folder of Parquet files plus a DuckDB
database of views over them, served over HTTPS:

- `https://basemap.cancerdatasci.org/data/latest/` — the newest release
- `https://basemap.cancerdatasci.org/data/v2026-11-02/` — a dated release that never
  changes. R2 keeps the newest release of each of the last 12 months.
- Hugging Face `seandavis/cancerbasemap`, tag `2026-11-02` — every release,
  permanently. Cite the tag, e.g. `seandavis/cancerbasemap@2026-11-02`.

From DuckDB, attach the release database (read-only), or read `views.sql`
into a session. Pin a dated folder for anything you will rerun:

```sql
ATTACH 'https://basemap.cancerdatasci.org/data/latest/cancerbasemap.duckdb' AS cbm (READ_ONLY);
USE cbm;
-- or: .read https://basemap.cancerdatasci.org/data/latest/views.sql
-- pinned: .../data/v2026-11-02/cancerbasemap.duckdb
```

Mammography screening in Colorado counties, lowest first, with the interval,
the release that said so, and the county's rurality code:

```sql bundle
SELECT u.name, o.source_release, o.value AS pct, o.lower, o.upper, o.value_status,
       r.value AS rucc_code
FROM measure.observation o
JOIN geography.unit u
  ON u.geo_id = o.geo_id AND u.vintage = 2026
LEFT JOIN measure.observation r
  ON r.geo_id = o.geo_id AND r.source = 'RUCC'
WHERE o.source = 'PLACES' AND o.measure_id = 'PLACES:MAMMOUSE:age_adjusted'
  AND o.source_release = '2025' AND u.parent_geo_id = 'state:08'
ORDER BY pct LIMIT 10;
```

`value` is NULL whenever `value_status` is not `reported` — a suppressed cell
never reads as a number. The geography join names a vintage explicitly because
`geo_vintage` assignment is still being settled (#21). A bundle holds the
current rows only: it has no validity columns, so there is no `valid_to` to
filter on.

From Python, fetch with `duckdb`, `requests` or `polars`: Python's default
`urllib` user agent is blocked by the zone (HTTP 403, Cloudflare error 1010).

Working from R, SAS or SEER\*Stat instead of raw SQL? See
[docs/CLIENTS.md](docs/CLIENTS.md). Why releases look like this:
[ADR-0001](docs/adr/0001-public-releases-monthly-parquet-bundles.md).

## Status

First release `2026-11-02`: 59 tables, 78,550,648 rows (counted from its
`manifest.json`), including `measure.observation` (29,557,502 rows) and
`geography.unit` (582,392). Work is sequenced by milestone tracking issues —
see the [milestones](../../milestones).

## Develop

```sh
uv run pytest          # no live services; uses a local sqlite warehouse. The release tests need
                       # DuckDB's ducklake extension (INSTALL ducklake on first run, then cached)
```

## Licence

Code: [MIT](LICENSE). Data: each source keeps its own terms, recorded per
source in `provenance`; only third-party-redistributable public aggregates are
admitted (SPEC.md § Licence gate).
