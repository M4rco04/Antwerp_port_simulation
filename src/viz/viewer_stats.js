// The statistics window of the viewer (build_viewer.py inlines this file into the page; the map window
// writes it into a window of its own). It runs in that window with its own Chart.js and reads the run's
// data and the playhead from the map window (opener.VIEWER), which calls statsTick() when time moves.
"use strict";
const H = opener.VIEWER;
const D = H.D, M = D.meta, S = D.ships, TS = D.ts, PORT = D.port;
const START = Date.parse(M.start), NS = S.id.length, END = M.end_min;
const $ = id => document.getElementById(id);
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const C = { s: [css("--s1"), css("--s2"), css("--s3"), css("--s4"), css("--s5")], ink: css("--text-primary"),
            ink2: css("--text-secondary"), muted: css("--muted"), grid: css("--grid"), axis: css("--axis"), surface: css("--surface-1") };
const MON = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
const DAY = ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"];
const pad = n => String(n).padStart(2, "0");
function when(min) { const d = new Date(START + min * 60000); return `${DAY[d.getUTCDay()]} ${d.getUTCDate()} ${MON[d.getUTCMonth()]} ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`; }
function dayLabel(min) { const d = new Date(START + min * 60000); return `${d.getUTCDate()} ${MON[d.getUTCMonth()]}`; }
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const fmt = (v, d = 1) => v == null || Number.isNaN(v) ? "–" : Number(v).toFixed(d);
const label = s => String(s || "").replaceAll("_", " ");
const cap = s => s ? s[0].toUpperCase() + s.slice(1) : s;
function dur(m) { m = Math.max(0, Math.round(m)); const h = Math.floor(m / 60), r = m % 60; return h ? `${h} h ${pad(r)} min` : `${r} min`; }
const ships_ = n => `${n} ship${n === 1 ? "" : "s"}`;
function tNow() { try { return H.getT(); } catch (e) { return 0; } }

// ------------------------------------------------------------------ tabs, player, keys, ship links
let view = "now", chartsBuilt = false, analysisBuilt = false;
document.querySelectorAll(".tabs button").forEach(b => b.addEventListener("click", () => show(b.dataset.view)));
function show(v) {
  view = v;
  document.querySelectorAll(".tabs button").forEach(x => x.setAttribute("aria-selected", x.dataset.view === v));
  document.querySelectorAll(".spage").forEach(p => p.classList.toggle("on", p.id === v));
  if (v === "charts" && !chartsBuilt) { buildCharts(); chartsBuilt = true; }
  if (v === "analysis" && !analysisBuilt) { buildAnalysis(); analysisBuilt = true; }
  statsTick(tNow(), true);
}
const slider = $("slider");
slider.max = Math.round(END);
slider.addEventListener("input", () => H.seek(+slider.value));
$("play").onclick = () => H.togglePlay();
document.addEventListener("keydown", e => { if (e.target.tagName === "INPUT" && e.target.type !== "range" || e.target.tagName === "SELECT") return;
  if (e.code === "Space") { e.preventDefault(); H.togglePlay(); }
  if (e.code === "ArrowRight") H.seek(tNow() + 60); if (e.code === "ArrowLeft") H.seek(tNow() - 60); });
document.addEventListener("click", e => { const a = e.target.closest("[data-ship]"); if (!a) return; e.preventDefault();
  const i = +a.dataset.ship; if (i >= 0) { H.select(i); try { opener.focus(); } catch (err) { /* the browser may refuse */ } } });

// ------------------------------------------------------------------ time from the map window
let lastWall = 0, lastKey = null, pending = null;
window.statsTick = function (t, force) {
  slider.value = t;
  $("clock").textContent = `${when(t)} UTC · day ${fmt(t / 1440, 1)}`;
  const pl = H.isPlaying(); $("play").textContent = pl ? "❚❚ Pause" : "▶ Play"; $("play").setAttribute("aria-label", pl ? "Pause" : "Play");
  const now = performance.now();
  clearTimeout(pending);
  if (!force && now - lastWall < 250) { pending = setTimeout(() => statsTick(tNow(), false), 260); return; }
  lastWall = now;
  if (view === "now") renderNow(t, force);
  else if (view === "charts") charts.forEach(c => c.draw());
};
setInterval(() => { let gone = true; try { gone = !opener || opener.closed || opener.VIEWER !== H; } catch (e) { /* gone */ }
  $("gone").hidden = !gone; }, 1000);

// ------------------------------------------------------------------ port now: helpers
function at(recs, t) {                              // the record in force at t: the last one with time <= t
  if (!recs || !recs.length || recs[0][0] > t) return null;
  let lo = 0, hi = recs.length - 1;
  while (lo < hi) { const m = (lo + hi + 1) >> 1; if (recs[m][0] <= t) lo = m; else hi = m - 1; }
  return recs[lo];
}
const CLS = { container: "container", bulk_general: "bulk / general", tanker: "tanker", inland_cargo: "inland cargo",
              inland_tanker: "inland tanker", passenger: "passenger" };
function ship(i, extra = "") {
  if (i == null || i < 0) return `<span class="mut">a ship not in the ship table</span>`;
  return `<a href="#" class="ship" data-ship="${i}">${esc(S.name[i] || S.id[i])}</a> <span class="mut">${esc(CLS[S.cls[i]] || S.cls[i])}, ${fmt(S.loa[i], 0)} m, T ${fmt(S.draught[i], 1)} m${extra}</span>`;
}
function shipList(list, numbered) {
  return list.length ? list.map((i, k) => `<div>${numbered ? `<span class="mut">${k + 1}.</span> ` : ""}${ship(i)}</div>`).join("") : `<span class="mut">–</span>`;
}
const dot = k => `<span class="sw" style="background:${C.s[k]}"></span>`;
// where a ship with a berth is: coming, mooring, at the berth, leaving
const AT_BERTH = { mooring: ["Mooring", 2, "here"], at_berth: ["At the berth", 2, "here"], dwell_port: ["In port", 2, "here"],
                   wait_clearance: ["Ready to leave, waiting for VTS clearance", 3, "here"], unmooring: ["Unmooring", 3, "here"] };
function berthStatus(st) {
  if (st == null) return ["–", "", "free"];
  const a = AT_BERTH[st];
  if (a) return [`<span class="st">${dot(a[1])}${a[0]}</span>`, a[0], a[2]];
  const txt = `Coming: ${label(st)}`;
  return [`<span class="st">${dot(0)}${esc(txt)}</span>`, txt, "coming"];
}

// ------------------------------------------------------------------ port now
function tsIndex(t) { let lo = 0, hi = TS.t.length - 1; while (lo < hi) { const m = (lo + hi + 1) >> 1; if (TS.t[m] <= t) lo = m; else hi = m - 1; } return lo; }
function kpis(t) { const k = tsIndex(t);
  const v = [["In the area", TS.under_way[k] + TS.waiting[k] + TS.berth[k]], ["Under way", TS.under_way[k]], ["Waiting", TS.waiting[k]],
             ["At anchor", TS.anchored[k]], ["At berth / lock", TS.berth[k]], ["VTS queue", TS.vts_requests?.[k] ?? "–"],
             ["At the locks", TS.lock_queue?.[k] ?? "–"],
             ["Wind", `${TS.wind_bft?.[k] ?? "–"} Bft`], ["Visibility", TS.visibility_m?.[k] != null ? `${fmt(TS.visibility_m[k] / 1000, 1)} km` : "–"]];
  $("kpis").innerHTML = v.map(([l, x]) => `<div class="kpi"><div class="v">${x}</div><div class="l">${l}</div></div>`).join(""); }

function renderNow(t, force) {
  const key = Math.floor(t / M.step_min);
  if (!force && key === lastKey) return;
  lastKey = key;
  kpis(t);
  if (!PORT) { $("noport").hidden = false; $("portgrid").hidden = true; return; }
  renderVts(t); renderLocks(t); renderTerminals(t); renderBerths(t); renderPorts(t);
}

const REASON = { tide: "Tide: not deep enough on the way, leaving now and an hour later", pilot: "A pilot (or a pilot boat)",
                 destination: "Room at its berth or quay", weather: "The weather (wind, visibility)", no_route: "A route (water depth, locks)" };
function renderVts(t) {
  const r = at(PORT.vts, t), rows = r ? r[1] : [];
  const n = {};
  rows.forEach(x => { const k = x[1] || "unchecked"; n[k] = (n[k] || 0) + 1; });
  $("vts_sub").textContent = rows.length
    ? `${ships_(rows.length)} wait${rows.length === 1 ? "s" : ""} for clearance, in the order the VTS looks at them (distress, then tide-dependent ships, then first come first served). Waiting for: `
      + Object.entries(n).sort((a, b) => b[1] - a[1]).map(([k, v]) => `${k === "unchecked" ? "not looked at yet" : label(k)} ${v}`).join(", ")
    : "No ship waits for VTS clearance now";
  $("vts").innerHTML = rows.length ? `<thead><tr><th class="n">#</th><th>Ship</th><th>Voyage</th><th>Where it waits</th><th>Held back by</th><th class="n">Waiting</th></tr></thead><tbody>`
    + rows.map(([i, reason, since, dep, st, anch], k) => {
        const voyage = i < 0 ? "–" : dep ? `Departure → ${esc(label(S.exit[i]) || "sea")}` : `Arrival → ${esc(label(S.terminal[i] || S.destination[i]))}`;
        const where = anch ? `At anchor, ${esc(label(anch))}` : st === "anchored" ? "At anchor" : st === "wait_clearance"
          ? (dep ? "At its berth / in port" : "At the pilot station or its port") : esc(cap(label(st)));
        const tide = i >= 0 && S.draught[i] > 13.1 ? ` <span class="mut">(tide-dependent)</span>` : "";
        return `<tr><td class="n">${k + 1}</td><td>${ship(i)}${tide}</td><td>${voyage}</td><td>${where}</td>
          <td>${reason ? esc(REASON[reason] || label(reason)) : `<span class="mut">not looked at yet</span>`}</td><td class="n">${dur(t - since)}</td></tr>`; }).join("")
    + "</tbody>" : "";
}

function sideName(L, s) {
  const d = L.sides[s], o = L.sides[s === "a" ? "b" : "a"];
  if (!d) return `side ${s}`;
  let n = cap(label(d.zone)) + (d.tidal ? " (tidal)" : "");
  if (o && o.zone === d.zone) n += `, side ${s.toUpperCase()}`;
  return n;
}
const GATE = { closing: "Closing the gates", levelling: "Levelling", opening: "Opening the gates" };
const TASK = { enter: "Going in", exit: "Coming out", pass: "Passing through" };
function renderLocks(t) {
  let html = `<thead><tr><th>Lock and chamber</th><th>Now</th><th>In the chamber</th><th>Waiting on side A</th><th>Waiting on side B</th></tr></thead><tbody>`;
  let waiting = 0, inside = 0;
  for (const [name, L] of Object.entries(PORT.static.locks)) {
    const held = at(PORT.held[name], t);
    L.chambers.forEach((c, k) => {
      const r = at(PORT.locks[`${name}|${c.name}`], t);
      const dims = `<span class="mut">${fmt(c.length_m, 0)} × ${fmt(c.width_m, 0)} m, sill ${fmt(c.sill_m, 1)} m</span>`;
      const title = `<b>${esc(name)}</b>${c.name !== name ? `<br>${esc(c.name)}` : ""}<br>${dims}`;
      if (!r) { html += `<tr class="${k ? "" : "lockfirst"}"><td>${title}</td><td colspan="4"><span class="mut">no record yet</span></td></tr>`; return; }
      const [, st, side, until, task, tship, ins, qa, qb, res, rfrom] = r;
      waiting += qa.length + qb.length; inside += ins.length;
      const left = until != null && until > t ? ` <span class="mut">· ${dur(until - t)} left</span>` : "";
      let now;
      if (st === "open") {
        now = `<span class="st">${dot(2)}<b>Open</b></span> to ${esc(sideName(L, side))}`;
        if (task) now += `<div>${TASK[task] || label(task)}: ${ship(tship)}${left}</div>`;
        else if (!ins.length && !qa.length && !qb.length) now += ` <span class="mut">· idle</span>`;
      } else {
        now = `<span class="st">${dot(1)}<b>${GATE[st] || esc(cap(label(st)))}</b></span>${left}<div class="mut">from ${esc(sideName(L, side))} to ${esc(sideName(L, side === "a" ? "b" : "a"))}</div>`;
      }
      if (res != null) now += `<div class="mut">Kept empty for ${res >= 0 ? ship(res) : "a ULCV"} from ${when(rfrom)}</div>`;
      if (k === 0 && held && held[1].length) now += `<div class="mut">Held in the lock while a ULCV passes:</div>${shipList(held[1])}`;
      html += `<tr class="${k ? "" : "lockfirst"}"><td>${title}</td><td>${now}</td><td>${shipList(ins)}</td>
        <td><div class="mut">from ${esc(sideName(L, "a"))}</div>${shipList(qa, true)}</td><td><div class="mut">from ${esc(sideName(L, "b"))}</div>${shipList(qb, true)}</td></tr>`;
    });
  }
  $("locks").innerHTML = html + "</tbody>";
  $("locks_sub").textContent = `${ships_(inside)} in a chamber, ${waiting} waiting. Each chamber: what it does now, the ships in it and the ships waiting on each side, in the order they go in. Click a ship to show it on the map.`;
}

function renderTerminals(t) {
  const k = tsIndex(t);
  let html = "";
  for (const [name, info] of Object.entries(PORT.static.terminals)) {
    const r = at(PORT.berths[`T:${name}`], t), rows = r ? r[1] : [];
    const q = at(PORT.quay_queue[name], t), queue = q ? q[1] : [];
    const free = TS.free_quay[name]?.[k];
    html += `<h3>${esc(name)} <span class="mut" style="font-weight:400">· quay ${info.quay_m} m, ${free != null ? `${free} m free` : ""} · ${info.sts} STS cranes · ${ships_(rows.length)}</span></h3>`;
    if (rows.length) {
      html += `<div class="tablewrap" style="max-height:none"><table class="ptable"><thead><tr><th>Ship</th><th>Berth slots</th><th class="n">Quay (m)</th><th>Status</th><th class="n">Cranes</th></tr></thead><tbody>`
        + rows.map(([i, s0, s1, st, cranes]) => {
            const slots = Object.entries(info.slots).filter(([, [a, b]]) => a < s1 && b > s0).map(([b]) => b.replace(/^ANTW_/, "")).join(", ");
            return `<tr><td>${ship(i)}</td><td>${esc(slots) || "–"}</td><td class="n">${fmt(s0, 0)}–${fmt(s1, 0)}</td><td>${berthStatus(st)[0]}</td><td class="n">${cranes || "–"}</td></tr>`; }).join("")
        + "</tbody></table></div>";
    } else html += `<p class="empty">No ship at or coming to this terminal</p>`;
    if (queue.length) html += `<div style="margin-top:6px"><span class="mut">Waiting for room at the quay:</span> ${queue.map(([i, since]) => ship(i, `, ${dur(t - since)}`)).join(" · ")}</div>`;
  }
  $("terms").innerHTML = html;
}

const BERTH_IDS = PORT ? Object.keys(PORT.static.berths) : [];
function renderBerths(t) {
  const q = $("bq").value.trim().toLowerCase(), want = $("bstatus").value;
  const rows = [];
  let coming = 0, here = 0;
  for (const b of BERTH_IDS) {
    const info = PORT.static.berths[b], r = at(PORT.berths[`B:${b}`], t);
    const i = r ? r[1] : null, st = r ? r[2] : null;
    const [html, txt, kind] = berthStatus(i == null ? null : st);
    if (kind === "coming") coming++; else if (kind === "here") here++;
    if (want && kind !== want) continue;
    if (q && !`${b} ${info.lpl} ${info.zone} ${info.type} ${i != null && i >= 0 ? `${S.id[i]} ${S.name[i]}` : ""} ${txt}`.toLowerCase().includes(q)) continue;
    rows.push([b, info, i, html, kind]);
  }
  rows.sort((a, b) => (a[4] === "free") - (b[4] === "free") || String(a[1].zone).localeCompare(String(b[1].zone)) || a[0].localeCompare(b[0], undefined, { numeric: true }));
  $("berths_sub").textContent = `Berths outside the container terminals that ships used in this run: ${coming} with a ship coming, ${here} with a ship alongside, ${BERTH_IDS.length - coming - here} free now`;
  const shown = rows.slice(0, 400);
  $("berths").innerHTML = `<thead><tr><th>Berth</th><th>Zone</th><th>Kind</th><th class="n">Length (m)</th><th class="n">Max draught (m)</th><th>Ship</th><th>Status</th></tr></thead><tbody>`
    + shown.map(([b, info, i, html]) => `<tr><td><b>${esc(b.replace(/^ANTW_/, ""))}</b>${info.tanker ? ` <span class="mut">tanker</span>` : ""}</td>
        <td>${esc(cap(label(info.zone)))}${info.tidal === false ? ` <span class="mut">behind the locks</span>` : ""}</td><td>${esc(info.type || "–")}</td>
        <td class="n">${fmt(info.length_m, 0)}</td><td class="n">${fmt(info.max_draught_m, 1)}</td><td>${i == null ? "–" : ship(i)}</td><td>${html}</td></tr>`).join("")
    + (rows.length > shown.length ? `<tr><td colspan="7" class="mut">${rows.length - shown.length} more: narrow the search</td></tr>` : "") + "</tbody>";
}
["bq", "bstatus"].forEach(id => $(id).addEventListener("input", () => { if (PORT) renderBerths(tNow()); }));

function renderPorts(t) {
  const keys = Object.keys(PORT.berths).filter(k => k.startsWith("P:")).sort();
  $("ports").innerHTML = keys.length ? keys.map(k => { const r = at(PORT.berths[k], t), rows = r ? r[1] : [];
    return `<h3>${esc(cap(label(k.slice(2))))} <span class="mut" style="font-weight:400">· ${ships_(rows.length)}</span></h3>`
      + (rows.length ? rows.map(([i, st]) => `<div>${ship(i)} ${berthStatus(st)[0]}</div>`).join("") : `<p class="empty">None</p>`); }).join("")
    : `<p class="empty">No ship went to these ports in this run</p>`;
}

// ------------------------------------------------------------------ charts
Chart.defaults.font.family = 'system-ui, -apple-system, "Segoe UI", sans-serif';
Chart.defaults.font.size = 12;
Chart.defaults.color = C.ink2;
Chart.defaults.borderColor = C.grid;
Chart.register({ id: "cursor", afterDatasetsDraw(ch) { if (!ch.options.plugins.cursor) return;
  const x = ch.scales.x.getPixelForValue(tNow()), a = ch.chartArea; if (x < a.left || x > a.right) return;
  const g = ch.ctx; g.save(); g.strokeStyle = C.ink; g.lineWidth = 1; g.setLineDash([4, 3]);
  g.beginPath(); g.moveTo(x, a.top); g.lineTo(x, a.bottom); g.stroke(); g.restore(); } });
function timeAxis() { return { type: "linear", min: 0, max: END, grid: { color: C.grid }, border: { color: C.axis },
  ticks: { stepSize: 1440, callback: v => dayLabel(v), maxRotation: 0, autoSkipPadding: 12, color: C.muted } }; }
function valueAxis(title, extra = {}) { return { beginAtZero: true, grid: { color: C.grid }, border: { display: false },
  ticks: { color: C.muted, precision: 0, maxTicksLimit: 5 }, title: { display: !!title, text: title, color: C.ink2 }, ...extra }; }
const pts = arr => Array.from(TS.t, (t, k) => ({ x: t, y: arr ? arr[k] : null }));
function lineSet(lbl, arr, k, extra = {}) { return { label: lbl, data: pts(arr), borderColor: C.s[k], backgroundColor: C.s[k], borderWidth: 2, pointRadius: 0, pointHoverRadius: 4, tension: 0, ...extra }; }
function seekFromChart(ch, ev) { H.seek(ch.scales.x.getValueForPixel(Chart.helpers.getRelativePosition(ev, ch).x)); }
function timeChart(id, datasets, opts = {}) {
  return new Chart($(id), { type: "line", data: { datasets },
    options: { animation: false, maintainAspectRatio: false, parsing: false, normalized: true, spanGaps: true,
      interaction: { mode: "index", intersect: false },
      scales: { x: timeAxis(), y: valueAxis(opts.y, opts.yExtra) },
      plugins: { cursor: true,
        legend: { display: datasets.length > 1, position: "top", align: "start", labels: { boxWidth: 10, boxHeight: 10, usePointStyle: true, pointStyle: "circle", color: C.ink } },
        tooltip: { callbacks: { title: it => when(it[0].parsed.x) } } },
      onClick: (ev, _e, chart) => seekFromChart(chart, ev.native ?? ev) } });
}
const charts = [];
function buildCharts() {
  charts.push(timeChart("c_activity", [
    lineSet("Under way", TS.under_way, 0, { fill: "origin", borderColor: C.surface, borderWidth: 1.5, backgroundColor: C.s[0], stack: "a" }),
    lineSet("Waiting", TS.waiting, 1, { fill: "-1", borderColor: C.surface, borderWidth: 1.5, backgroundColor: C.s[1], stack: "a" }),
    lineSet("At berth, in port or in a lock", TS.berth, 2, { fill: "-1", borderColor: C.surface, borderWidth: 1.5, backgroundColor: C.s[2], stack: "a" }),
  ], { yExtra: { stacked: true } }));
  charts.push(timeChart("c_queues", [lineSet("VTS queue", TS.vts_requests, 0), lineSet("At the locks", TS.lock_queue, 1)]));
  { const DL = D.depth.levels, G = D.depth.cells.gauges, pick = [["vlissingen", "Vlissingen"], ["antwerpen.loodsgebouw", "Antwerp"]].filter(([g]) => G.includes(g));
    $("level_sub").textContent = DL.source;
    charts.push(timeChart("c_level", pick.map(([g, n], k) => ({ label: n, data: Array.from(DL.t, (t, j) => ({ x: t, y: DL.cm[G.indexOf(g)][j] / 100 })),
      borderColor: C.s[k], backgroundColor: C.s[k], borderWidth: 2, pointRadius: 0, pointHoverRadius: 4, tension: 0 })))); }
  charts.push(timeChart("c_pilots", [lineSet("Sea", TS.pilots_busy_sea, 0), lineSet("River", TS.pilots_busy_river, 1), lineSet("Docks", TS.pilots_busy_dock, 2)]));
  charts.push(timeChart("c_services", [lineSet("Tugs", TS.tugs_busy, 0), lineSet("Pilot boats", TS.pilot_boats_busy, 1), lineSet("Boatmen crews", TS.boatmen_busy, 2)]));
  charts.push(timeChart("c_wind", [lineSet("Wind force", TS.wind_bft, 0, { stepped: true })], { yExtra: { suggestedMax: 8 } }));
  charts.push(timeChart("c_vis", [lineSet("Visibility", TS.visibility_m && Array.from(TS.visibility_m, v => v == null ? null : v / 1000), 0, { stepped: true })]));
}

// ------------------------------------------------------------------ analysis (the whole run)
function barChart(id, labels, values, opts = {}) {
  return new Chart($(id), { type: "bar",
    data: { labels: Array.from(labels), datasets: [{ data: Array.from(values), backgroundColor: C.s[0], borderRadius: 4, borderSkipped: "start", maxBarThickness: 22 }] },
    options: { indexAxis: opts.horizontal ? "y" : "x", animation: false, maintainAspectRatio: false,
      scales: { x: opts.horizontal ? valueAxis(opts.vtitle) : { grid: { display: false }, ticks: { color: C.muted, maxRotation: 0, autoSkipPadding: 8 }, title: { display: !!opts.xtitle, text: opts.xtitle, color: C.ink2 } },
                y: opts.horizontal ? { grid: { display: false }, ticks: { color: C.ink } } : valueAxis(opts.vtitle) },
      plugins: { cursor: false, legend: { display: false }, tooltip: { callbacks: opts.tip ? { label: opts.tip } : {} } } } });
}
function buildAnalysis() {
  const sm = M.summary;
  const ak = [["Days simulated", fmt(sm.days, 1)], ["Ships generated", sm.ships_generated], ["Finished after warm-up", sm.ships_finished_after_warmup],
              ["Still in the area", sm.still_in_area], ["Removed (voyage impossible)", sm.removed_infeasible], ["Mean ships at anchor", fmt(sm.anchored_mean, 1)]];
  $("akpis").innerHTML = ak.map(([l, v]) => `<div class="kpi"><div class="v">${v}</div><div class="l">${l}</div></div>`).join("");

  // time in the area by phase, per class: ships that entered after the warm-up and finished
  const phases = Array.from(M.phases);
  const classes = Object.keys(M.class_label).filter(c => S.cls.some((x, i) => x === c && S.after_warmup[i] && S.status[i] === "finished"));
  const sel = c => { const out = []; for (let i = 0; i < NS; i++) if (S.cls[i] === c && S.after_warmup[i] && S.status[i] === "finished") out.push(i); return out; };
  const mean = a => a.length ? a.reduce((p, q) => p + q, 0) / a.length : 0;
  const median = a => { if (!a.length) return null; const s = [...a].sort((p, q) => p - q), m = s.length >> 1; return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; };
  const groups = classes.map(sel);
  $("phase_sub").textContent = `Mean hours per ship, ships that entered after the ${fmt(M.warmup_min / 1440, 1)}-day warm-up and left within the run`;
  new Chart($("c_phase"), { type: "bar",
    data: { labels: classes.map(c => M.class_label[c]), datasets: phases.map((p, k) => ({ label: p, data: groups.map(g => mean(g.map(i => S.phase[p][i]))),
      backgroundColor: C.s[k], borderColor: C.surface, borderWidth: { right: 2 }, borderSkipped: false, maxBarThickness: 26 })) },
    options: { indexAxis: "y", animation: false, maintainAspectRatio: false,
      scales: { x: { ...valueAxis("hours"), stacked: true }, y: { stacked: true, grid: { display: false }, ticks: { color: C.ink } } },
      plugins: { cursor: false, legend: { position: "top", align: "start", labels: { boxWidth: 10, boxHeight: 10, color: C.ink } },
        tooltip: { callbacks: { label: it => `${it.dataset.label}: ${fmt(it.parsed.x, 1)} h` } } } } });
  $("phase_table").innerHTML = `<thead><tr><th>Class</th><th class="n">Ships</th><th class="n">Mean h in area</th><th class="n">Median h</th>${phases.map(p => `<th class="n">${p} (h)</th>`).join("")}</tr></thead><tbody>`
    + classes.map((c, k) => { const g = groups[k]; return `<tr><td>${M.class_label[c]}</td><td class="n">${g.length}</td><td class="n">${fmt(mean(g.map(i => S.hours[i])), 1)}</td><td class="n">${fmt(median(g.map(i => S.hours[i])), 1)}</td>${phases.map(p => `<td class="n">${fmt(mean(g.map(i => S.phase[p][i])), 1)}</td>`).join("")}</tr>`; }).join("") + "</tbody>";

  // container delay against the schedule
  const del = []; for (let i = 0; i < NS; i++) if (S.delay[i] != null && S.cls[i] === "container") del.push(S.delay[i]);
  if (del.length) {
    const w = 6, lo = Math.floor(Math.min(...del) / w) * w, hi = Math.ceil(Math.max(...del) / w) * w + w;
    const bins = []; for (let b = lo; b < hi; b += w) bins.push(b);
    const counts = bins.map(b => del.filter(d => d >= b && d < b + w).length);
    $("delay_sub").textContent = `${del.length} moored container ships · median ${fmt(median(del), 1)} h after the scheduled berth time`;
    barChart("c_delay", bins.map(b => `${b > 0 ? "+" : ""}${b}`), counts, { xtitle: "hours late against the schedule (6 h bins)", vtitle: "ships",
      tip: it => `${it.parsed.y} ships, ${bins[it.dataIndex]} to ${bins[it.dataIndex] + w} h` });
  } else $("delay_sub").textContent = "No container ship moored in this run";

  const A = D.analysis;
  const hold = Object.entries(A.vts_hold).sort((a, b) => b[1] - a[1]);
  barChart("c_hold", hold.map(h => label(h[0])), hold.map(h => h[1]), { horizontal: true, vtitle: "holds" });
  const locks = Object.entries(A.lock_entries).sort((a, b) => b[1] - a[1]);
  barChart("c_locks", locks.map(l => l[0]), locks.map(l => l[1]), { horizontal: true, vtitle: "ships" });
  const rules = Object.entries(A.rules).filter(r => r[1] > 0).sort((a, b) => b[1] - a[1]);
  const RL = { overtake_denied: "Overtaking refused", reroute: "Detour taken", squeeze_past: "Deadlock let through", hold_encounter_rule: "Held by an encounter rule",
    held_for_ulcv: "Held in a lock for a ULCV", weather_hold: "Held by the weather", fallback_berth: "ULCV fallback berth", draught_capped: "Container draught capped",
    no_anchorage: "No anchorage with room", anchorage_full: "Anchorage full on arrival", infeasible: "Voyage impossible (removed)" };
  barChart("c_rules", rules.map(r => RL[r[0]] || label(r[0])), rules.map(r => r[1]), { horizontal: true, vtitle: "events" });
  const q = Object.entries(TS.free_quay);
  new Chart($("c_quay"), { type: "line",
    data: { datasets: q.map(([n, arr], k) => lineSet(n, arr, k)) },
    options: { animation: false, maintainAspectRatio: false, parsing: false, interaction: { mode: "index", intersect: false },
      scales: { x: timeAxis(), y: valueAxis("metres") },
      plugins: { cursor: false, legend: { position: "top", align: "start", labels: { boxWidth: 10, boxHeight: 10, usePointStyle: true, pointStyle: "circle", color: C.ink } },
        tooltip: { callbacks: { title: it => when(it[0].parsed.x) } } } } });

  // the ship table: a click shows the ship on the map at its arrival
  const fc = $("fclass");
  Object.entries(M.class_label).forEach(([k, v]) => fc.insertAdjacentHTML("beforeend", `<option value="${k}">${v}</option>`));
  const waitP = phases[1];
  const cols = [["id", "Ship", i => S.name[i] ? `${esc(S.name[i])} <span style="color:${C.ink2}">${esc(S.id[i])}</span>` : esc(S.id[i]), i => S.name[i] || S.id[i]],
    ["cls", "Class", i => esc(M.class_label[S.cls[i]] || S.cls[i]), i => S.cls[i]],
    ["loa", "LOA (m)", i => fmt(S.loa[i], 0), i => S.loa[i], 1], ["beam", "Beam (m)", i => fmt(S.beam[i], 1), i => S.beam[i], 1],
    ["draught", "Draught (m)", i => fmt(S.draught[i], 2), i => S.draught[i], 1],
    ["from", "From", i => esc(label(S.source[i])), i => S.source[i]], ["to", "To", i => esc(label(S.terminal[i] || S.destination[i])), i => S.terminal[i] || S.destination[i]],
    ["hours", "Hours in area", i => fmt(S.hours[i], 1), i => S.hours[i], 1], ["wait", "Hours waiting", i => fmt(S.phase[waitP][i], 1), i => S.phase[waitP][i], 1],
    ["delay", "Berth delay (h)", i => fmt(S.delay[i], 1), i => S.delay[i] ?? -1e9, 1], ["status", "Status", i => esc(S.status[i]), i => S.status[i]]];
  let sortCol = 7, sortDir = -1;
  function drawTable() {
    const q = $("q").value.trim().toLowerCase(), c = fc.value, st = $("fstatus").value, warm = $("fwarm").checked;
    const rows = [];
    for (let i = 0; i < NS; i++) {
      if (c && S.cls[i] !== c) continue; if (st && S.status[i] !== st) continue; if (warm && !S.after_warmup[i]) continue;
      if (q && !`${S.id[i]} ${S.name[i]} ${S.source[i]} ${S.destination[i]} ${S.terminal[i]}`.toLowerCase().includes(q)) continue;
      rows.push(i);
    }
    const key = cols[sortCol][3];
    rows.sort((a, b) => { const x = key(a), y = key(b); return (x < y ? -1 : x > y ? 1 : 0) * sortDir; });
    const shown = rows.slice(0, 600);
    $("tcount").textContent = `${rows.length} ships${rows.length > shown.length ? `, first ${shown.length} shown` : ""}`;
    $("shiptable").innerHTML = `<thead><tr>${cols.map((cl, k) => `<th class="${cl[4] ? "n" : ""}" data-k="${k}">${cl[1]}${k === sortCol ? (sortDir < 0 ? " ↓" : " ↑") : ""}</th>`).join("")}</tr></thead><tbody>`
      + shown.map(i => `<tr data-i="${i}">${cols.map(cl => `<td class="${cl[4] ? "n" : ""}">${cl[2](i)}</td>`).join("")}</tr>`).join("") + "</tbody>";
    document.querySelectorAll("#shiptable th").forEach(th => th.onclick = () => { const k = +th.dataset.k; sortDir = k === sortCol ? -sortDir : -1; sortCol = k; drawTable(); });
    document.querySelectorAll("#shiptable tbody tr").forEach(tr => tr.onclick = () => { H.showShip(+tr.dataset.i); try { opener.focus(); } catch (e) { /* refused */ } });
  }
  ["q", "fclass", "fstatus", "fwarm"].forEach(id => $(id).addEventListener("input", drawTable));
  drawTable();
}

statsTick(tNow(), true);
