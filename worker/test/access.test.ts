import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import Ajv2020 from "ajv/dist/2020.js";
import worker from "../src/index.ts";

// monode #67: one access record per request, pages and /data/, every method and
// status, as one JSON console.log line. The Worker runs against a one-object
// bucket; ASSETS answers pages with a 307 (as data.test.ts does).
const BODY = new TextEncoder().encode("0123456789");
const object = { key: "latest/a.parquet", size: BODY.length, httpEtag: '"abc"', uploaded: new Date("2026-11-01T00:00:00Z") };
const bucket = {
  head: async (key: string) => (key === object.key ? object : null),
  get: async (key: string, o: { range?: { offset: number; length: number } }) =>
    key === object.key
      ? { ...object, body: o.range ? BODY.slice(o.range.offset, o.range.offset + o.range.length) : BODY, range: o.range }
      : null,
  list: async () => ({ objects: [object], delimitedPrefixes: [], truncated: false }),
};
const env = {
  ASSETS: { fetch: async () => new Response(null, { status: 307, headers: { location: "/elsewhere" } }) },
  DATA_BUCKET: bucket,
  USAGE: { writeDataPoint: () => {} },
};
const ctx = { waitUntil: () => {} };

// "DERIVED" schema, see its $comment: monode holds none yet.
const validate = new Ajv2020({ strict: false }).compile(
  JSON.parse(readFileSync(new URL("./access-record.schema.json", import.meta.url), "utf8")),
);

/** Run one request and return the access records it logged. */
async function records(path: string, headers: Record<string, string> = {}, method = "GET") {
  const lines: string[] = [];
  const log = console.log;
  console.log = (line: string) => lines.push(line);
  try {
    const res = await worker.fetch(
      new Request(`https://basemap.cancerdatasci.org${path}`, { method, headers }),
      env as any,
      ctx as any,
    );
    await res.arrayBuffer();
  } finally {
    console.log = log;
  }
  return lines.map((l) => JSON.parse(l));
}

test("one schema-valid record per request: data, page, directory, other methods", async () => {
  const cases: [string, Record<string, string>, string, number][] = [
    ["/data/latest/a.parquet", {}, "GET", 200],
    ["/data/latest/a.parquet", {}, "HEAD", 200],
    ["/data/latest/", { accept: "application/json" }, "GET", 200],
    ["/data/latest/a.parquet", {}, "OPTIONS", 204],
    ["/data/latest/a.parquet", {}, "POST", 405],
    ["/", {}, "GET", 301],
  ];
  for (const [path, headers, method, status] of cases) {
    const recs = await records(path, headers, method);
    assert.equal(recs.length, 1, `${method} ${path}`);
    assert.ok(validate(recs[0]), `${method} ${path}: ${JSON.stringify(validate.errors)}`);
    assert.equal(recs[0].sc_status, status, `${method} ${path}`);
    assert.equal(recs[0].cs_method, method);
  }
});

test("/data/ range request record", async () => {
  const [r] = await records("/data/latest/a.parquet?x=1", {
    range: "bytes=2-4",
    "cf-connecting-ip": "203.0.113.7",
    "user-agent": "duckdb",
    referer: "https://example.org/",
  });
  assert.equal(r.type, "access");
  assert.equal(r.v, 1);
  assert.equal(r.sc_status, 206);
  assert.equal(r.cs_host, "basemap.cancerdatasci.org");
  assert.equal(r.cs_uri_stem, "/data/latest/a.parquet");
  assert.equal(r.cs_uri_query, "?x=1");
  assert.equal(r.c_ip, "203.0.113.7");
  assert.equal(r.cs_user_agent, "duckdb");
  assert.equal(r.cs_referer, "https://example.org/");
  assert.equal(r.sc_bytes, 3);
  assert.equal(r.sc_content_len, "3");
  assert.equal(r.sc_range_start, 2);
  assert.equal(r.sc_range_end, 4);
  assert.equal(r.x_edge_result_type, "MISS");
  assert.equal(r.cs_cookie, null);
});

test("HEAD sends no bytes; ranged GET counts the range", async () => {
  const [head] = await records("/data/latest/a.parquet", {}, "HEAD");
  assert.equal(head.sc_bytes, 0);
  assert.equal(head.sc_content_len, "10");
  const [ranged] = await records("/data/latest/a.parquet", { range: "bytes=2-5" });
  assert.equal(ranged.sc_bytes, 4);
});

test("cookie and authorization values never reach the record", async () => {
  const [r] = await records("/data/latest/a.parquet", {
    cookie: "session=s3cret-cookie",
    authorization: "Bearer s3cret-token",
  });
  const json = JSON.stringify(r);
  assert.ok(!json.includes("s3cret-cookie"));
  assert.ok(!json.includes("s3cret-token"));
});

test("/data/ 404 record", async () => {
  const [r] = await records("/data/latest/nope.parquet");
  assert.equal(r.sc_status, 404);
  assert.equal(r.cs_uri_stem, "/data/latest/nope.parquet");
  assert.equal(r.sc_range_start, null);
  assert.ok(validate(r), JSON.stringify(validate.errors));
});

test("a thrown handler still logs one 500 record and rethrows", async () => {
  const broken = { ...env, DATA_BUCKET: { ...bucket, get: async () => { throw new Error("r2 down"); } } };
  const lines: string[] = [];
  const log = console.log;
  console.log = (line: string) => lines.push(line);
  try {
    await assert.rejects(
      worker.fetch(new Request("https://basemap.cancerdatasci.org/data/latest/a.parquet"), broken as any, ctx as any),
    );
  } finally {
    console.log = log;
  }
  assert.equal(lines.length, 1);
  const r = JSON.parse(lines[0]);
  assert.equal(r.sc_status, 500);
  assert.ok(validate(r), JSON.stringify(validate.errors));
});
