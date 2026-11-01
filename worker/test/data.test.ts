import { test } from "node:test";
import assert from "node:assert/strict";
import worker from "../src/index.ts";

// ADR-0001 rule 2: /data/ serves bytes and never redirects. The whole Worker
// runs against a one-object bucket; ASSETS answers every page with a 307 so a
// leak into the pages path would show as a redirect.
const BODY = new TextEncoder().encode("0123456789");
const ETAG = '"abc"';
const object = { key: "latest/a.parquet", size: BODY.length, httpEtag: ETAG, uploaded: new Date("2026-11-01T00:00:00Z") };

const bucket = {
  head: async (key: string) => (key === object.key ? object : null),
  get: async (key: string, o: { onlyIf: Headers; range?: { offset: number; length: number } }) => {
    if (key !== object.key) return null;
    const ifMatch = o.onlyIf.get("if-match");
    if (ifMatch !== null && ifMatch !== ETAG) return object; // precondition failed: no body
    const r = o.range;
    const slice = r ? BODY.slice(r.offset, r.offset + r.length) : BODY;
    return { ...object, body: slice, range: r };
  },
  list: async () => ({ objects: [object], delimitedPrefixes: [], truncated: false }),
};

let assetCalls = 0;
const env = {
  ASSETS: { fetch: async () => { assetCalls++; return new Response(null, { status: 307, headers: { location: "/elsewhere" } }); } },
  DATA_BUCKET: bucket,
  USAGE: { writeDataPoint: () => {} },
};
const ctx = { waitUntil: () => {} };

const get = (path: string, headers: Record<string, string> = {}, method = "GET") =>
  worker.fetch(new Request(`https://basemap.cancerdatasci.org${path}`, { method, headers }), env as any, ctx as any);

test("/data/ object: 200 bytes, CORS, no redirect", async () => {
  const res = await get("/data/latest/a.parquet");
  assert.equal(res.status, 200);
  assert.equal(res.headers.get("access-control-allow-origin"), "*");
  assert.equal(await res.text(), "0123456789");
});

test("/data/ range request: 206 with content-range", async () => {
  const res = await get("/data/latest/a.parquet", { range: "bytes=2-4" });
  assert.equal(res.status, 206);
  assert.equal(res.headers.get("content-range"), "bytes 2-4/10");
  assert.equal(await res.text(), "234");
});

test("/data/ stale If-Match: 412, not a redirect", async () => {
  const res = await get("/data/latest/a.parquet", { "if-match": '"stale"' });
  assert.equal(res.status, 412);
});

test("/data/ missing key: 404; directory forms list, never redirect", async () => {
  assert.equal((await get("/data/latest/nope.parquet")).status, 404);
  for (const p of ["/data", "/data/", "/data/latest/"]) {
    const res = await get(p, { accept: "application/json" });
    assert.equal(res.status, 200, p);
    assert.equal(res.headers.get("location"), null, p);
  }
  assert.equal((await get("/data/latest/a.parquet", {}, "HEAD")).status, 200);
});

test("/data/ never reaches the pages", async () => {
  for (const p of ["/data/", "/data/index.html", "/data/home_map.json", "/data/latest/"]) await get(p);
  assert.equal(assetCalls, 0);
});

test("pages go to ASSETS, with the 307 made a 301", async () => {
  const res = await get("/start/python/");
  assert.equal(assetCalls, 1);
  assert.equal(res.status, 301);
});

test("HEAD has no body: directory listing and object", async () => {
  const dir = await get("/data/", {}, "HEAD");
  assert.equal(dir.status, 200);
  assert.equal(dir.body, null);
  const obj = await get("/data/latest/a.parquet", {}, "HEAD");
  assert.equal(obj.status, 200);
  assert.equal(obj.body, null);
  assert.equal(obj.headers.get("content-length"), "10");
});

test("HEAD ignores Range: 200 for the whole object", async () => {
  const res = await get("/data/latest/a.parquet", { range: "bytes=2-4" }, "HEAD");
  assert.equal(res.status, 200);
  assert.equal(res.headers.get("content-length"), "10");
  assert.equal(res.headers.get("content-range"), null);
});
