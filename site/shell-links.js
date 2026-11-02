// "Open in DuckDB Shell" under each SQL example, from omicidx docs/shell-links.html.
// shell.duckdb.org runs the queries in its URL hash, #queries=v0,<q1>,<q2>,...,
// each one with space<->hyphen and semicolon<->tilde swapped, then URI-encoded
// (the symmetric `extraswaps` of duckdb/duckdb-wasm#1529). Examples that don't
// ATTACH get the latest release attached first. Opt out with `.no-shell`.
window.basemapShellUrl = function (sql) {
  const swap = (s) => s.replace(/[ \-;~]/g, (c) => ({ " ": "-", "-": " ", ";": "~", "~": ";" })[c]);
  // Statements go through as written: comments and whitespace may sit inside string literals.
  const stmts = sql.split(/;\s*(?:\n|$)/).map((s) => s.trim()).filter(Boolean);
  if (!/\bATTACH\b/i.test(sql)) {
    stmts.unshift(
      "ATTACH 'https://basemap.cancerdatasci.org/data/latest/cancerbasemap.duckdb' AS basemap (READ_ONLY)",
      "USE basemap",
    );
  }
  return "https://shell.duckdb.org/#queries=v0," +
    stmts.map((s) => encodeURIComponent(swap(s + ";"))).join(",");
};
document.querySelectorAll("pre.sourceCode.sql").forEach((pre) => {
  if (pre.matches(".no-shell, .no-shell *")) return;
  const a = document.createElement("a");
  a.href = window.basemapShellUrl(pre.textContent);
  a.target = "_blank";
  a.rel = "noopener";
  a.className = "shell-link";
  a.textContent = "Open in DuckDB Shell ↗";
  const p = document.createElement("p");
  p.className = "small text-end";
  p.append(a);
  pre.closest("div.sourceCode").after(p);
});
