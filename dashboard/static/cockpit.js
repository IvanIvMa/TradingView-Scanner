// TJL Cockpit — liest nur /api/*, schreibt nichts.
const $ = (s, r = document) => r.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const fmt = (n, d = 2) => (n == null || isNaN(n) ? "—" : Number(n).toFixed(d));
const pct = (n) => (n == null ? "—" : `<span class="${n >= 0 ? "pos" : "neg"}">${n >= 0 ? "+" : ""}${fmt(n)} %</span>`);
const get = async (u) => { try { const r = await fetch(u); return await r.json(); } catch { return null; } };
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();

// Zeitzone: Unix-Sekunden -> "ET-Wandzeit" für Lightweight Charts (zeigt sonst UTC)
function etShift(t) {
  const d = new Date(t * 1000);
  const et = new Date(d.toLocaleString("en-US", { timeZone: "America/New_York" }));
  const utc = new Date(d.toLocaleString("en-US", { timeZone: "UTC" }));
  return t + (et - utc) / 1000;
}

// ---------- Tabs ----------
document.querySelectorAll(".tabs button").forEach((b) =>
  b.addEventListener("click", () => showTab(b.dataset.tab)));
function showTab(name) {
  document.querySelectorAll(".tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  document.querySelectorAll(".tab").forEach((s) => s.classList.toggle("hidden", s.id !== `tab-${name}`));
  try { localStorage.setItem("tjl-tab", name); } catch {}
  if (name === "perf") loadPerf();
  if (name === "bt") loadBacktest();
  if (name === "log") loadLog();
  if (name === "chart" && !chart) loadChart();
}

// ---------- Health ----------
function setCard(id, state, val, sub) {
  const el = $(id);
  el.className = `hcard ${state}`;
  $(".hval", el).textContent = val;
  if (sub !== undefined) $(".hsub", el).textContent = sub;
}
let lastHealth = null;
async function loadHealth() {
  const h = await get("/api/health");
  if (!h) return;
  lastHealth = h;
  $("#clock-et").textContent = h.time_et.slice(0, 5);
  $("#clock-de").textContent = h.time_berlin.slice(0, 5);
  const m = $("#market");
  m.textContent = h.market_open ? "Markt offen" : "Markt zu";
  m.className = `pill ${h.market_open ? "open" : ""}`;
  const a = h.scanner_a;
  setCard("#h-a", a.ok ? "ok" : "warn", a.ok ? `${a.count} Gapper` : "noch keine Liste", a.time ? `Scan ${a.time}` : "läuft 15:00 / 15:45");
  const b = h.scanner_b;
  const bsub = b.error ? `Fehler: ${b.error}` :
    b.last_run ? `letzter Lauf ${b.last_run}${b.age_min != null ? ` (vor ${b.age_min} min)` : ""}` :
    (b.in_window ? "heute noch kein Lauf" : "außerhalb 10:00–15:45 ET");
  setCard("#h-b", b.ok ? "ok" : "bad", b.ok ? "läuft" : "PRÜFEN", bsub);
  setCard("#h-tv", h.tradingview_cdp ? "ok" : "", h.tradingview_cdp ? "verbunden" : "nicht verbunden");
}

// ---------- Heute ----------
const tag = (r) => {
  if (r === "PASS") return `<span class="tag pass">PASS</span>`;
  if (r === "error" || r === "fail_no_data") return `<span class="tag err">${esc(r)}</span>`;
  return `<span class="tag fail">${esc((r || "—").replace("fail_", ""))}</span>`;
};
const flag = (ok) => (ok == null ? "—" : ok ? "✅" : "⚠️");
async function loadToday() {
  const [t, p] = await Promise.all([get("/api/today"), get("/api/positions")]);
  if (t) {
    $("#scan-time").textContent = t.scan_time ? `· Stand ${t.scan_time}` : "· Scanner B noch nicht gelaufen";
    const tb = $("#gappers tbody");
    tb.innerHTML = t.rows.length ? t.rows.map((r) => {
      const f = r.filters || {};
      return `<tr class="click" data-sym="${esc(r.symbol)}">
        <td><b>${esc(r.symbol)}</b></td><td>${pct(r.gap)}</td><td>${tag(r.result)}</td>
        <td>${flag(f.above_vwap)}</td><td>${fmt(f.rvol, 1)} ${flag(f.rvol_ok)}</td>
        <td>${fmt(f.ext_atr)} ${flag(f.ext_ok)}</td><td class="cat">${esc(r.catalyst || "")}</td></tr>`;
    }).join("") : `<tr><td colspan="7" class="muted">Heute noch keine Gapper.</td></tr>`;
    tb.querySelectorAll("tr.click").forEach((tr) => tr.addEventListener("click", () => openChart(tr.dataset.sym)));
  }
  const pos = (p && p.positions) || [];
  const open = pos.filter((x) => x.status === "open").length;
  setCard("#h-pos", open ? "warn" : "", `${open} offen · ${pos.length - open} zu`, pos.length ? "" : "noch kein PASS heute");
  $("#positions").innerHTML = pos.length ? pos.map((x) => `
    <div class="card">
      <div class="row"><span class="sym" data-sym="${esc(x.symbol)}">${esc(x.symbol)}</span>
        <span class="tag ${x.status === "open" ? "open" : "fail"}">${x.status === "open" ? "offen" : esc(x.exit_reason || "zu")}</span></div>
      <div class="row"><span>Einstieg</span><span>$${fmt(x.entry_price)} · ${esc(x.entry_et)}</span></div>
      <div class="row"><span>Aktuell / Hoch</span><span>$${fmt(x.last_price ?? x.exit_price)} / $${fmt(x.high_water)}</span></div>
      <div class="row"><span>Stop</span><span>$${fmt(x.current_stop)}</span></div>
      <div class="row"><span>Teilgewinn</span><span>${x.partial_alerted ? "✅ erreicht" : "—"}</span></div>
      <div class="row"><span>VWAP-Bruch</span><span>${x.vwap_break_ts ? "⚠️ ja" : "—"}</span></div>
      <div class="row"><span>P&amp;L inkl. Teilgewinn</span><span>${pct(x.pnl_pct)}</span></div>
    </div>`).join("") : `<div class="empty">Keine Positionen heute.</div>`;
  document.querySelectorAll("#positions .sym").forEach((s) => s.addEventListener("click", () => openChart(s.dataset.sym)));
}

// ---------- Chart ----------
let chart, candles, vwapS, priceLines = [];
function ensureChart() {
  if (chart) return;
  const el = $("#chart");
  chart = LightweightCharts.createChart(el, {
    autoSize: true,
    layout: { background: { color: css("--panel") }, textColor: css("--muted") },
    grid: { vertLines: { color: css("--line") }, horzLines: { color: css("--line") } },
    timeScale: { timeVisible: true, secondsVisible: false }, rightPriceScale: { borderColor: css("--line") },
  });
  candles = chart.addCandlestickSeries({ upColor: css("--green"), downColor: css("--red"),
    wickUpColor: css("--green"), wickDownColor: css("--red"), borderVisible: false });
  vwapS = chart.addLineSeries({ color: css("--purple"), lineWidth: 2, priceLineVisible: false, lastValueVisible: false });
}
function openChart(sym) { $("#sym").value = sym; showTab("chart"); loadChart(); }
async function loadChart() {
  const sym = $("#sym").value.trim().toUpperCase();
  if (!sym) { $("#chart-note").textContent = "Symbol eingeben oder in „Heute“ auf eine Zeile klicken."; return; }
  ensureChart();
  $("#chart-note").textContent = "Lade …";
  const iv = $("#iv").value, step = iv === "5m" ? 300 : 60;
  const d = await get(`/api/chart/${encodeURIComponent(sym)}?interval=${iv}`);
  if (!d || !d.bars || !d.bars.length) { $("#chart-note").textContent = "Keine Daten von Yahoo."; return; }
  candles.setData(d.bars.map((b) => ({ ...b, time: etShift(b.time) })));
  vwapS.setData(d.vwap.map((v) => ({ time: etShift(v.time), value: v.value })));
  priceLines.forEach((l) => candles.removePriceLine(l));
  const col = { Einstieg: css("--blue"), Stop: css("--red"), Ziel: css("--green") };
  priceLines = d.lines.map((l) => candles.createPriceLine({ price: l.price, color: col[l.label], lineWidth: 1,
    lineStyle: 2, axisLabelVisible: true, title: l.label }));
  const mk = d.markers.map((m) => {
    const t = etShift(Math.floor(m.t / step) * step);
    if (m.kind === "entry") return { time: t, position: "belowBar", color: css("--blue"), shape: "arrowUp", text: "Kauf" };
    if (m.kind === "exit") return { time: t, position: "aboveBar", color: css("--red"), shape: "arrowDown", text: m.reason || "Exit" };
    return { time: t, position: "aboveBar", color: css("--purple"), shape: "circle", text: "VWAP-Bruch" };
  }).sort((a, b) => a.time - b.time);
  candles.setMarkers(mk);
  chart.timeScale().fitContent();
  $("#chart-note").textContent = d.lines.length
    ? `${sym}: Position heute — Linien zeigen Einstieg, aktuellen Stop und Teilgewinn-Ziel.`
    : `${sym}: heute keine Position — nur Kurs und VWAP.`;
}
$("#load").addEventListener("click", loadChart);
$("#sym").addEventListener("keydown", (e) => e.key === "Enter" && loadChart());
$("#iv").addEventListener("change", loadChart);

// ---------- Performance ----------
let eqChart;
async function loadPerf() {
  const p = await get("/api/performance");
  if (!p) return;
  const box = (title, s) => `<div class="card"><div class="hlabel">${title}</div>
    <div class="hval">${s.n ? `${s.n} Trades` : "noch keine"}</div>
    <div class="row"><span>Trefferquote</span><span>${s.n ? fmt(s.win_pct, 1) + " %" : "—"}</span></div>
    <div class="row"><span>Ø pro Trade</span><span>${s.n ? pct(s.avg_pct) : "—"}</span></div></div>`;
  $("#perf-sum").innerHTML = box("Alte Regeln (2 %-Trailing)", p.old) + box("Neue Regeln (ATR, ab 16.11.)", p.new);
  $("#trades tbody").innerHTML = p.trades.map((t) => `<tr class="click" data-sym="${esc(t.symbol)}">
    <td>${esc(t.date)}</td><td><b>${esc(t.symbol)}</b></td><td>$${fmt(t.entry)} · ${esc(t.entry_et || "")}</td>
    <td>$${fmt(t.exit)}</td><td>${esc(t.reason || "")}</td><td>${pct(t.pnl_pct)}</td><td>${esc(t.rules)}</td></tr>`).join("")
    || `<tr><td colspan="7" class="muted">Keine abgeschlossenen Trades.</td></tr>`;
  if (!eqChart) {
    eqChart = LightweightCharts.createChart($("#equity"), { autoSize: true,
      layout: { background: { color: css("--panel") }, textColor: css("--muted") },
      grid: { vertLines: { visible: false }, horzLines: { color: css("--line") } },
      timeScale: { visible: false }, handleScroll: false, handleScale: false });
    eqChart.eq = eqChart.addLineSeries({ color: css("--blue"), lineWidth: 2 });
  }
  eqChart.eq.setData(p.curve.map((c, i) => ({ time: i + 1, value: c.equity })));
  eqChart.timeScale().fitContent();
}

// ---------- Backtest ----------
async function loadBacktest() {
  const b = await get("/api/backtest");
  if (!b || !b.table.length) { $("#bt-note").textContent = "Noch kein Backtest. Ausführen: python3 backtest_exits.py"; return; }
  $("#bt-note").innerHTML = `${b.n_entries} Einstiege seit ${esc(b.window_from)} (Yahoo 5-Min), erstellt ${esc(b.generated.slice(0, 16).replace("T", " "))}.
    <b>Kleine Stichprobe</b> — Richtung, kein Beweis. Gleiche Regeln wie live (tjl_rules.py).`;
  let prev = null;
  $("#bt tbody").innerHTML = b.table.map((r) => {
    const first = r.entries !== prev; prev = r.entries;
    return `<tr><td>${first ? `<b>${esc(r.entries)}</b>` : ""}</td><td>${esc(r.exits)}</td><td>${r.n}</td>
      <td>${r.n ? fmt(r.win_pct, 1) + " %" : "—"}</td><td>${r.n ? pct(r.avg_pct) : "—"}</td>
      <td>${r.n ? pct(r.sum_pct) : "—"}</td><td>${fmt(r.pf)}</td></tr>`;
  }).join("");
}

// ---------- Log & Regeln ----------
async function loadLog() {
  const [r] = await Promise.all([get("/api/rules"), loadHealth()]);
  if (r) $("#rules tbody").innerHTML = Object.entries(r).map(([k, v]) => `<tr><td><code>${esc(k)}</code></td><td>${esc(v)}</td></tr>`).join("");
  $("#log").textContent = (lastHealth?.log_tail || []).join("\n") || "Heute noch kein Scanner-B-Lauf.";
}

// ---------- Start ----------
async function refresh() { await loadHealth(); await loadToday(); }
refresh();
setInterval(refresh, 60_000);
try { const t = localStorage.getItem("tjl-tab"); if (t && t !== "today") showTab(t); } catch {}
