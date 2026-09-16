/* MarketSync web terminal.
 *
 * This file only DRAWS. Every number it renders comes from the project's real
 * Python running in Pyodide: MockProvider generates the markets, ArbitrageEngine
 * derives the opportunities, calculations.py does the depth-aware hedge maths.
 * See web/webapp.py for the glue and web/build.py for how app/ gets here.
 */
"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const state = {
  term: null,        // PyProxy for webapp.TERMINAL
  rows: [],
  selected: null,
  sort: { key: "net_edge", dir: -1 },
  search: "",
  showAll: false,
  paused: false,
  interval: 1500,
  timer: null,
};

/* ---------- formatting (mirrors app/utils/formatting.py) ---------- */
const pct = (v, dp = 2) => `${v.toFixed(dp)}%`;
const signedPct = (v, dp = 2) => `${v >= 0 ? "+" : ""}${v.toFixed(dp)}%`;
const money = (v) => `£${v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const moneyShort = (v) => (Math.abs(v) >= 1000 ? `£${(v / 1000).toFixed(1)}k` : `£${v.toFixed(0)}`);
const edgeClass = (v) => (v > 1 ? "pos" : v > 0 ? "warn" : "neg");

/* ---------- boot ---------- */
const bootLog = (msg) => {
  $("#boot-log").textContent += msg + "\n";
};
const bootProgress = (p) => {
  $("#boot-fill").style.width = `${p}%`;
};

async function boot() {
  try {
    bootLog("› loading CPython (WebAssembly)…");
    bootProgress(12);
    const pyodide = await loadPyodide();
    const py = pyodide.runPython("import sys; '.'.join(map(str, sys.version_info[:3]))");
    bootLog(`  CPython ${py} via Pyodide ${pyodide.version}`);
    bootProgress(55);

    bootLog("› mounting app/ modules…");
    const manifest = await (await fetch("py/manifest.json")).json();
    const files = manifest.files;

    // Fetch every module and write it into Pyodide's virtual filesystem at the
    // same path it has in the repo, so `import app.services...` resolves.
    const sources = await Promise.all(
      files.map(async (path) => [path, await (await fetch(`py/${path}`)).text()])
    );
    for (const [path, text] of sources) {
      const parts = path.split("/");
      for (let i = 1; i < parts.length; i++) {
        const dir = parts.slice(0, i).join("/");
        try { pyodide.FS.mkdir(dir); } catch { /* already exists */ }
      }
      pyodide.FS.writeFile(path, text, { encoding: "utf8" });
    }
    bootLog(`  ${files.length} modules mounted (${(sources.reduce((n, [, t]) => n + t.length, 0) / 1024).toFixed(0)} KB)`);
    bootProgress(80);

    bootLog("› starting detection engine…");
    await pyodide.runPythonAsync("import webapp");
    state.term = pyodide.runPython("webapp.TERMINAL");
    bootProgress(100);
    bootLog("  MockProvider + ArbitrageEngine live");

    tick();
    setSpeed(state.interval);
    setTimeout(() => $("#boot").classList.add("done"), 380);
  } catch (err) {
    bootLog("\n✗ FAILED: " + err.message);
    bootLog("\nThe engine could not start. This preview needs WebAssembly and");
    bootLog("must be served over http(s) — opening the file directly will not work.");
    console.error(err);
  }
}

/* ---------- tick ---------- */
function tick() {
  if (!state.term) return;
  const snap = JSON.parse(state.term.tick());
  state.rows = snap.rows;
  renderGrid();
  renderFooter(snap);
  if (state.selected) renderDetail(state.selected);
}

function setSpeed(ms) {
  state.interval = ms;
  clearInterval(state.timer);
  if (!state.paused) state.timer = setInterval(tick, ms);
}

/* ---------- screener ---------- */
function visibleRows() {
  const q = state.search.toLowerCase();
  let rows = state.rows.filter((r) => state.showAll || r.passes);
  if (q) {
    rows = rows.filter(
      (r) => r.event.toLowerCase().includes(q) || r.selection.toLowerCase().includes(q)
    );
  }
  const { key, dir } = state.sort;
  return rows.sort((a, b) => {
    const x = a[key], y = b[key];
    return (typeof x === "string" ? x.localeCompare(y) : x - y) * dir;
  });
}

function renderGrid() {
  const rows = visibleRows();
  const body = $("#rows");
  body.innerHTML = rows
    .map(
      (r) => `
      <tr data-id="${r.id}" class="${r.id === state.selected ? "sel" : ""}${r.passes ? "" : " dim"}">
        <td title="${r.event}">${r.event}</td>
        <td title="${r.selection}">${r.selection}${r.in_play ? ' <span class="warn">•</span>' : ""}</td>
        <td class="num"><span class="venue-tag">${r.back_venue.slice(0, 2).toUpperCase()}</span>${r.back_odds.toFixed(2)}</td>
        <td class="num"><span class="venue-tag">${r.lay_venue.slice(0, 2).toUpperCase()}</span>${r.lay_odds.toFixed(2)}</td>
        <td class="num ${edgeClass(r.net_edge)}">${signedPct(r.net_edge)}</td>
        <td class="num">${moneyShort(r.liquidity)}</td>
        <td class="num">${r.quality.toFixed(0)}</td>
        <td><span class="pill ${r.risk}">${r.risk}</span></td>
      </tr>`
    )
    .join("");

  $("#empty").hidden = rows.length > 0;
  $("#screener-count").textContent = `${rows.length} shown / ${state.rows.length} priced`;
}

/* ---------- inspector ---------- */
function renderDetail(id) {
  const row = state.rows.find((r) => r.id === id);
  if (!row) return;
  const d = JSON.parse(state.term.detail(id));
  if (!d.found) return;

  $("#insp-empty").hidden = true;
  $("#insp").hidden = false;

  $(".insp-event").textContent = d.event;
  $(".insp-sel").textContent = `${d.selection} — ${d.market_name}`;
  $(".insp-dir").textContent =
    `BACK ${row.back_venue} @ ${row.back_odds.toFixed(2)}  /  LAY ${row.lay_venue} @ ${row.lay_odds.toFixed(2)}`;

  const net = $(".net");
  net.textContent = signedPct(row.net_edge);
  net.className = "net " + edgeClass(row.net_edge);
  $(".gross").textContent = signedPct(row.gross_edge);
  const buffered = $(".buffered");
  buffered.textContent = signedPct(row.buffered_edge);
  buffered.className = "buffered " + (row.buffered_edge >= 0 ? "pos" : "neg");
  $(".qual").textContent = row.quality.toFixed(0);

  $(".peak").textContent = pct(row.peak);
  $(".avg").textContent = pct(row.avg);
  $(".low").textContent = pct(row.low);
  $(".changes").textContent = row.changes;

  renderSpark(row.history);
  renderQuality(d.quality);

  $("#max-exec").textContent = `max executable ${moneyShort(d.max_executable)}`;
  const stake = $("#stake");
  stake.max = Math.max(100, Math.round(d.max_executable * 1.2));
  renderSim(JSON.parse(state.term.simulate(id, Number(stake.value))));

  renderLadders(d.ladders);
  $("#ladder-sel").textContent = `${d.event} — ${d.selection}`;
}

function renderSpark(history) {
  const svg = $("#spark");
  if (!history.length) { svg.innerHTML = ""; return; }
  const w = 320, h = 54, pad = 3;
  const lo = Math.min(0, ...history), hi = Math.max(...history, 0.5);
  const span = hi - lo || 1;
  const x = (i) => (history.length === 1 ? w : (i / (history.length - 1)) * w);
  const y = (v) => h - pad - ((v - lo) / span) * (h - pad * 2);

  const line = history.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("");
  const area = `${line}L${w},${h}L0,${h}Z`;
  const zero = lo < 0 && hi > 0 ? `<line x1="0" y1="${y(0)}" x2="${w}" y2="${y(0)}" stroke="#30363d" stroke-dasharray="2 3"/>` : "";
  const last = history[history.length - 1];
  const colour = last > 1 ? "#3fb950" : last > 0 ? "#d29922" : "#f85149";

  svg.innerHTML = `
    ${zero}
    <path d="${area}" fill="${colour}" opacity=".13"/>
    <path d="${line}" fill="none" stroke="${colour}" stroke-width="1.4"/>
    <circle cx="${x(history.length - 1)}" cy="${y(last)}" r="2" fill="${colour}"/>`;
}

function renderQuality(quality) {
  $("#quality-bars").innerHTML = Object.entries(quality)
    .map(([label, [score, max]]) => {
      const share = max ? (score / max) * 100 : 0;
      return `
        <div class="qbar">
          <div class="qbar-top"><span class="muted">${label}</span><span>${score} / ${max}</span></div>
          <div class="qbar-track"><div class="qbar-fill" style="width:${share.toFixed(0)}%"></div></div>
        </div>`;
    })
    .join("");
}

function renderSim(sim) {
  if (!sim || sim.found === false) return;
  const cells = [
    ["capital", money(sim.capital)],
    ["back stake", money(sim.back_stake)],
    ["lay stake", money(sim.lay_stake)],
    ["liability", money(sim.liability)],
    ["avg back", sim.avg_back.toFixed(3)],
    ["avg lay", sim.avg_lay.toFixed(3)],
    ["profit", `<b class="${sim.net_profit >= 0 ? "pos" : "neg"}">${money(sim.net_profit)}</b>`],
    ["roi", `<b class="${sim.roi >= 0 ? "pos" : "neg"}">${signedPct(sim.roi, 3)}</b>`],
  ];
  $("#sim").innerHTML =
    cells.map(([k, v]) => `<div class="sim-cell"><span>${k}</span>${v}</div>`).join("") +
    (sim.executable
      ? ""
      : `<div class="sim-cell" style="grid-column:1/-1"><span class="neg">book too thin for this stake</span></div>`);
}

function renderLadders(ladders) {
  for (const el of $$(".venue")) {
    const data = ladders[el.dataset.venue];
    const book = $(".book", el);
    if (!data) { book.innerHTML = `<div class="book-empty">no prices</div>`; continue; }
    const peak = Math.max(1, ...[...data.back, ...data.lay].map((l) => l.size));
    const side = (levels, cls) =>
      `<div class="${cls}"><div class="side-hd">${cls === "back-side" ? "BACK" : "LAY"}</div>` +
      levels
        .map(
          (l) => `<div class="rung">
            <div class="depth" style="width:${((l.size / peak) * 100).toFixed(0)}%"></div>
            <span>${l.odds.toFixed(2)}</span><span class="sz">${moneyShort(l.size)}</span>
          </div>`
        )
        .join("") +
      `</div>`;
    book.innerHTML = side(data.back, "back-side") + side(data.lay, "lay-side");
  }
}

/* ---------- footer ---------- */
function renderFooter(snap) {
  const s = snap.stats;
  $("#foot-left").textContent =
    `tick ${snap.ticks} · ${snap.ts} · ${s.markets} markets · ${s.surfaced} surfaced (${s.safe} SAFE / ${s.thin} THIN)`;
  $("#foot-right").textContent =
    `profile ${s.profile} · buffer ${pct(s.buffer, 1)} · min net ${pct(s.min_net, 2)} · best ${signedPct(s.best)}`;
}

/* ---------- events ---------- */
$("#rows").addEventListener("click", (e) => {
  const tr = e.target.closest("tr");
  if (!tr) return;
  state.selected = tr.dataset.id;
  renderGrid();
  renderDetail(state.selected);
});

$$("thead th").forEach((th) =>
  th.addEventListener("click", () => {
    const key = th.dataset.sort;
    state.sort = { key, dir: state.sort.key === key ? -state.sort.dir : -1 };
    $$("thead th").forEach((h) => h.classList.remove("sorted-asc", "sorted-desc"));
    th.classList.add(state.sort.dir === 1 ? "sorted-asc" : "sorted-desc");
    renderGrid();
  })
);

$$(".preset[data-profile]").forEach((btn) =>
  btn.addEventListener("click", () => {
    btn.classList.toggle("on");
    let names = $$(".preset[data-profile].on").map((b) => b.dataset.profile);
    if (!names.length) { btn.classList.add("on"); names = [btn.dataset.profile]; }
    state.term.set_enabled(names);
    tick();
  })
);

$("#search").addEventListener("input", (e) => {
  state.search = e.target.value.trim();
  renderGrid();
});

$("#toggle-all").addEventListener("click", (e) => {
  state.showAll = !state.showAll;
  e.target.classList.toggle("on", state.showAll);
  e.target.textContent = state.showAll ? "ALL MARKETS" : "QUALIFYING ONLY";
  renderGrid();
});

$("#pause").addEventListener("click", (e) => {
  state.paused = !state.paused;
  e.target.classList.toggle("on", state.paused);
  e.target.innerHTML = state.paused ? "&#9654; RESUME" : "&#10073;&#10073; PAUSE";
  setSpeed(state.interval);
});

$("#speed").addEventListener("change", (e) => setSpeed(Number(e.target.value)));

$("#stake").addEventListener("input", (e) => {
  if (!state.selected) return;
  renderSim(JSON.parse(state.term.simulate(state.selected, Number(e.target.value))));
});

boot();
