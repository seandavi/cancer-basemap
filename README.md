# Cancer Basemap

Population cancer data — incidence, mortality, screening, risk factors, social
and environmental context, and the places people get care — published as
Apache Iceberg tables keyed on geography and time, where **every release every
source ever published stays queryable**.

Sibling of [biocOnIce](https://github.com/seandavi/bioc-on-ice), served through
[icegate](https://github.com/seandavi/icegate). Public aggregates only.

- **[SPEC.md](SPEC.md)** — what the system must do (design source of truth)
- **[AGENTS.md](AGENTS.md)** — working rules for agents and humans
- **[docs/adr/](docs/adr/)** — why decisions went the way they did
- **[docs/DEPLOY.md](docs/DEPLOY.md)** — bucket, catalog, gateway and secrets runbook
- **[CONTRIBUTING.md](CONTRIBUTING.md)** — how to propose a source or a catchment

## Query it

No account, no token. From DuckDB:

```sql
INSTALL iceberg; LOAD iceberg;
ATTACH 'canceronice' AS coi (
    TYPE ICEBERG,
    URI 'https://icegate-canceronice.seandavi.workers.dev',  -- DuckDB <= 1.5: ENDPOINT instead of URI
    AUTHORIZATION_TYPE 'none'
);
```

Mammography screening in Colorado counties, lowest first, with the interval,
the release that said so, and the county's rurality code:

```sql
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
ORDER BY pct LIMIT 10;
```

`value` is NULL whenever `value_status` is not `reported` — a suppressed cell
never reads as a number. The geography join names a vintage explicitly because
`geo_vintage` assignment is still being settled (#21).

Working from R, SAS or SEER\*Stat instead of raw SQL? See
[docs/CLIENTS.md](docs/CLIENTS.md).

## Status

Bootstrap catalog live since 2026-09-18, first loaded as catalog release
`2026.09`: `geography.unit` (Census Gazetteer vintages 2010, 2020, 2026 —
254,616 rows), and `measure.observation` from CDC PLACES county releases 2024
and 2025 (470,184 rows) and USDA ERS Rural-Urban Continuum Codes 2023 (3,235
rows). The versioning model is not settled; expect these tables to be rebuilt.
Work is sequenced by milestone tracking issues — see the
[milestones](../../milestones).

## Develop

```sh
uv run pytest          # no live services; uses a local sqlite warehouse. The release tests need
                       # DuckDB's ducklake extension (INSTALL ducklake on first run, then cached)
```

## Licence

Code: [MIT](LICENSE). Data: each source keeps its own terms, recorded per
source in `provenance`; only third-party-redistributable public aggregates are
admitted (SPEC.md § Licence gate).
