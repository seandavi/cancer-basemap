# Site Worker

One Cloudflare Worker, `data-cancerbasemap`, ported from bioc-on-ice `site/`
(#175, ADR-0001 § Infrastructure of its own):

| URL | Serves |
|---|---|
| `https://basemap.cancerdatasci.org/` | the Quarto site in `../site`, rendered to `../site/_site/` (Workers static assets) |
| `https://basemap.cancerdatasci.org/data/*` | the `data-cancerbasemap` R2 bucket, `/data` stripped from the key |

Two rules hold for good, and `test/route.test.ts` and `test/data.test.ts` assert
them: no page is routed under `/data/`, and `/data/` serves bytes and never
redirects (release views and every Hugging Face copy hard-code its URLs).
Routing is in `src/route.ts`.

The bucket is the anonymous, credential-free read surface for the releases:
range and conditional requests (DuckDB-Wasm `If-Match`), CORS, directory
listing (HTML or JSON by `Accept`), and one Analytics Engine data point per
bucket request (`src/analytics.ts`) in `data_cancerbasemap_usage`:
`blob1` object key, `blob2` user agent, `blob3` hashed IP, `blob4` method,
`double1` status, `double2` body bytes (0 for HEAD). Rows are sampled: count
with `sum(_sample_interval)`. `logpush = true` ships the Worker's logs beside
the account's `http_requests` Logpush (the access record itself is #177).

```bash
cd worker
npm ci
npm test               # route, data path, range, conditional and analytics tests
npm run typecheck
quarto render ../site  # the pages the Worker serves
npx wrangler dev       # local Worker, real bucket (remote R2 binding)
npm run deploy         # quarto render ../site && wrangler deploy
```
