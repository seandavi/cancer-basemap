// Run: node --test tests/shell-links.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const window = {};
vm.runInNewContext(readFileSync(new URL("../site/shell-links.js", import.meta.url), "utf8"), {
  window,
  document: { querySelectorAll: () => [] },
});

const swap = (s) => s.replace(/[ \-;~]/g, (c) => ({ " ": "-", "-": " ", ";": "~", "~": ";" })[c]);
// The statements the Shell would run, after the ATTACH/USE prefix.
const decoded = (sql) =>
  window.basemapShellUrl(sql).split("#queries=v0,")[1].split(",").map((q) => swap(decodeURIComponent(q)));

for (const sql of ["SELECT 'a--b';", "SELECT 'a  b';"]) {
  test(`round-trips ${JSON.stringify(sql)}`, () => {
    assert.equal(decoded(sql).at(-1), sql);
  });
}
