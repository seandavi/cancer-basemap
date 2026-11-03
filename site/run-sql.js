// "Run" under every ```{.sql .runnable} block. Nothing starts on page load: the
// first click loads ONE DuckDB-Wasm instance (the playground's setup), attaches
// latest/ as `basemap` and selects it, so blocks use plain `measure.observation`.
// Loaded after shell-links.js, whose "Open in DuckDB Shell" paragraph it extends.
let connPromise = null;
let queue = Promise.resolve(); // one query at a time on the shared connection

function connect() {
  connPromise ??= (async () => {
    const duckdb = await import("https://cdn.jsdelivr.net/npm/@duckdb/duckdb-wasm@1.33.1-dev57.0/+esm");
    const bundle = await duckdb.selectBundle(duckdb.getJsDelivrBundles());
    const workerUrl = URL.createObjectURL(
      new Blob([`importScripts("${bundle.mainWorker}");`], { type: "text/javascript" })
    );
    const db = new duckdb.AsyncDuckDB(new duckdb.VoidLogger(), new Worker(workerUrl));
    await db.instantiate(bundle.mainModule, bundle.pthreadWorker);
    // Byte-range reads only; all three flags are needed (see playground.qmd).
    await db.open({
      filesystem: { reliableHeadRequests: true, allowFullHTTPReads: false, forceFullHTTPReads: false }
    });
    const c = await db.connect();
    await c.query("ATTACH 'https://basemap.cancerdatasci.org/data/latest/cancerbasemap.duckdb' AS basemap (READ_ONLY)");
    await c.query("USE basemap");
    return c;
  })();
  connPromise.catch(() => { connPromise = null; }); // a failed start can be retried
  return connPromise;
}

const MAX_ROWS = 200;

function cell(v) {
  const td = document.createElement("td");
  if (v === null || v === undefined) {
    td.className = "text-muted fst-italic";
    td.textContent = "NULL"; // a suppressed cell must never look like a number or a blank
  } else {
    td.textContent = typeof v === "bigint" ? String(v) : v instanceof Date ? v.toISOString() : String(v);
  }
  return td;
}

function renderTable(table) {
  const names = table.schema.fields.map((f) => f.name);
  const wrap = document.createElement("div");
  wrap.style.cssText = "overflow:auto;max-height:24rem";
  const t = document.createElement("table");
  t.className = "table table-sm table-striped small";
  t.createTHead().insertRow().append(...names.map((n) => Object.assign(document.createElement("th"), { textContent: n })));
  const body = t.createTBody();
  for (const r of table.toArray().slice(0, MAX_ROWS)) {
    const o = r.toJSON();
    body.insertRow().append(...names.map((n) => cell(o[n])));
  }
  wrap.append(t);
  return wrap;
}

function run(sql, out, button) {
  button.disabled = true;
  out.replaceChildren(Object.assign(document.createElement("p"), {
    className: "small mb-1", textContent: connPromise ? "Running…" : "Starting DuckDB-Wasm…",
  }));
  queue = queue.then(async () => {
    const tStart = performance.now();
    try {
      const c = await connect();
      const t0 = performance.now();
      const table = await c.query(sql);
      const seconds = (performance.now() - t0) / 1000;
      const startup = (t0 - tStart) / 1000;
      const status = document.createElement("p");
      status.className = "small mb-1";
      status.dataset.rows = table.numRows;
      status.dataset.seconds = seconds.toFixed(1);
      status.textContent = `${table.numRows} rows in ${seconds.toFixed(1)} s` +
        (table.numRows > MAX_ROWS ? ` (first ${MAX_ROWS} shown)` : "") +
        (startup > 0.5 ? ` · plus ${startup.toFixed(1)} s to start DuckDB-Wasm` : "");
      out.replaceChildren(status, renderTable(table));
    } catch (e) {
      const alert = document.createElement("div");
      alert.className = "alert alert-danger";
      alert.setAttribute("role", "alert");
      const pre = document.createElement("pre");
      pre.className = "mb-0";
      pre.textContent = e.message ?? String(e);
      alert.append(pre);
      out.replaceChildren(alert);
    } finally {
      button.disabled = false;
    }
  });
}

document.querySelectorAll("pre.sourceCode.sql.runnable").forEach((pre) => {
  const bar = pre.closest("div.sourceCode").nextElementSibling; // the shell-link paragraph
  const out = document.createElement("div");
  out.setAttribute("aria-live", "polite");
  bar.after(out);
  const button = document.createElement("button");
  button.type = "button";
  button.className = "btn btn-sm btn-primary me-2 run-sql";
  button.textContent = "Run";
  button.onclick = () => run(pre.textContent, out, button);
  bar.prepend(button);
});
