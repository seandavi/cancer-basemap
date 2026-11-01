import { test } from "node:test";
import assert from "node:assert/strict";
import { permanentRedirect, route } from "../src/route.ts";

const at = (u: string) => route(new URL(u));
const host = "https://basemap.cancerdatasci.org";

test("pages everywhere but /data", () => {
  assert.deepEqual(at(`${host}/`), { kind: "docs" });
  assert.deepEqual(at(`${host}/start/python.html`), { kind: "docs" });
  assert.deepEqual(at(`${host}/releases`), { kind: "docs" });
  // a sibling that merely starts with "data" is a page, not the bucket
  assert.deepEqual(at(`${host}/dataset`), { kind: "docs" });
  assert.deepEqual(at(`${host}/data-dictionary/`), { kind: "docs" });
});

test("ADR-0001 rule 1: no page route under /data/", () => {
  for (const p of ["/data", "/data/", "/data/index.html", "/data/home_map.json", "/data/latest/", "/data/x/y.html"]) {
    assert.equal(at(`${host}${p}`).kind, "data", p);
  }
});

test("/data/* strips the prefix", () => {
  const data = (key: string) => ({ kind: "data", key, base: "/data" });
  assert.deepEqual(at(`${host}/data`), data(""));
  assert.deepEqual(at(`${host}/data/`), data(""));
  assert.deepEqual(at(`${host}/data/latest/a%20b.parquet`), data("latest/a b.parquet"));
  assert.deepEqual(at(`${host}/data/data/x`), data("data/x"));
});

test("malformed percent-escape is a bad request, not a throw", () => {
  assert.deepEqual(at(`${host}/data/%E0%A4%A`), { kind: "bad" });
});

test("permanentRedirect: assets' trailing-slash 307 becomes a 301 (omicidx#233)", () => {
  const r = permanentRedirect(new Response(null, { status: 307, headers: { location: "/guides/x" } }));
  assert.equal(r.status, 301);
  assert.equal(r.headers.get("location"), "/guides/x");
  const ok = new Response("hi");
  assert.equal(permanentRedirect(ok), ok);
});
