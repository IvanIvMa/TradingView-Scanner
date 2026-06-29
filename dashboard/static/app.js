// TJL Scanner — Trading Cockpit Frontend

let mainChart = null;
let mainSeries = null;
let currentTab = 'positions';

// ─── Tab Switching ──────────────────────────────────────────────────
function switchTab(tab) {
  currentTab = tab;
  document.querySelectorAll('.tab-content').forEach(el => el.classList.add('hidden'));
  document.getElementById('content-' + tab).classList.remove('hidden');
  document.querySelectorAll('.tab').forEach(el => el.classList.remove('tab-active'));
  document.getElementById('tab-' + tab).classList.add('tab-active');
}

// ─── Settings Modal ─────────────────────────────────────────────────
function openSettings() {
  document.getElementById('settings-modal').classList.remove('hidden');
  fetch('/api/params').then(r => r.json()).then(p => {
    document.getElementById('param-partial-atr').value = p.PARTIAL_ATR;
    document.getElementById('param-partial-pct').value = p.PARTIAL_PCT;
    document.getElementById('param-trail-pct').value = p.TRAIL_PCT;
    document.getElementById('param-atr-period').value = p.ATR_PERIOD;
    document.getElementById('param-eod-hour').value = p.EOD_HOUR_ET;
    document.getElementById('param-eod-min').value = p.EOD_MIN_ET;
  });
}
function closeSettings() { document.getElementById('settings-modal').classList.add('hidden'); }
function saveSettings() { closeSettings(); }

// ─── Data Fetching ──────────────────────────────────────────────────
async function fetchJSON(url) {
  try { return await (await fetch(url)).json(); } catch { return null; }
}

async function refreshAll() {
  const [status, regime, gappers, signals, positions, history] = await Promise.all([
    fetchJSON('/api/status'),
    fetchJSON('/api/regime'),
    fetchJSON('/api/gappers'),
    fetchJSON('/api/signals'),
    fetchJSON('/api/positions'),
    fetchJSON('/api/history'),
  ]);
  if (status) renderStatus(status);
  if (regime) renderRegime(regime);
  if (gappers) renderGappers(gappers);
  if (signals) renderSignals(signals);
  if (positions) renderPositions(positions);
  if (history) renderHistory(history);
}

// ─── Status ─────────────────────────────────────────────────────────
function renderStatus(s) {
  document.getElementById('clock').textContent = s.time_et;
  var dot = document.getElementById('market-dot');
  var label = document.getElementById('market-status');
  if (s.market_open) {
    dot.className = 'dot dot-green';
    label.textContent = 'Market open';
    label.style.color = 'var(--green)';
  } else {
    dot.className = 'dot dot-gray';
    label.textContent = 'Market closed';
    label.style.color = 'var(--text-3)';
  }
}

// ─── Regime ─────────────────────────────────────────────────────────
function renderRegime(r) {
  var icon = document.getElementById('regime-icon');
  var label = document.getElementById('regime-label');
  var detail = document.getElementById('regime-detail');
  var card = document.getElementById('card-regime');
  var badge = document.getElementById('regime-badge');

  var spyClose = r.spy && r.spy.close != null ? r.spy.close : '?';
  var spySma = r.spy && r.spy.sma200 != null ? r.spy.sma200 : '?';
  var qqqClose = r.qqq && r.qqq.close != null ? r.qqq.close : '?';
  var qqqSma = r.qqq && r.qqq.sma200 != null ? r.qqq.sma200 : '?';
  var spyAbove = r.spy && r.spy.above;
  var qqqAbove = r.qqq && r.qqq.above;

  detail.textContent = 'SPY $' + spyClose + (spyAbove ? ' > ' : ' < ') + 'SMA200 $' + spySma +
    '  |  QQQ $' + qqqClose + (qqqAbove ? ' > ' : ' < ') + 'SMA200 $' + qqqSma;

  if (r.regime === 'tailwind') {
    icon.textContent = '🟢';
    label.textContent = 'Tailwind';
    label.style.color = 'var(--green)';
    card.className = 'card glow-green';
    badge.innerHTML = '<span class="dot dot-green"></span><span style="color:var(--green)">Tailwind</span>';
  } else if (r.regime === 'mixed') {
    icon.textContent = '🟡';
    label.textContent = 'Mixed';
    label.style.color = 'var(--yellow)';
    card.className = 'card';
    badge.innerHTML = '<span class="dot dot-yellow"></span><span style="color:var(--yellow)">Mixed</span>';
  } else if (r.regime === 'headwind') {
    icon.textContent = '🔴';
    label.textContent = 'Headwind';
    label.style.color = 'var(--red)';
    card.className = 'card glow-red';
    badge.innerHTML = '<span class="dot dot-red"></span><span style="color:var(--red)">Headwind</span>';
  } else {
    icon.textContent = '➖';
    label.textContent = 'Unknown';
    label.style.color = 'var(--text-3)';
  }
}

// ─── Gappers ────────────────────────────────────────────────────────
function renderGappers(g) {
  document.getElementById('stat-gappers').textContent = g.count;
  document.getElementById('stat-gappers-sub').textContent = g.date;
  var tbody = document.getElementById('gappers-tbody');
  if (!g.gappers.length) {
    tbody.innerHTML = '<tr><td colspan="6" style="padding:32px;text-align:center;color:var(--text-3)">No gappers today</td></tr>';
    return;
  }
  tbody.innerHTML = g.gappers.map(function(gp) {
    var gapVal = gp.premarket_gap_pct || gp.intraday_gap_pct || gp.gap_pct;
    var gap = gapVal ? '+' + gapVal.toFixed(1) + '%' : '--';
    var vol = gp.premarket_volume || gp.volume;
    vol = vol ? formatNumber(vol) : '--';
    var fl = gp.float_shares ? formatNumber(gp.float_shares) : '--';
    var priceVal = gp.premarket_price || gp.intraday_price || gp.price;
    var price = priceVal ? '$' + priceVal.toFixed(2) : '--';
    return '<tr>' +
      '<td class="text-left" style="font-weight:600;color:var(--blue)">' + gp.symbol + '</td>' +
      '<td class="text-right mono">' + price + '</td>' +
      '<td class="text-right mono color-green">' + gap + '</td>' +
      '<td class="text-right mono">' + vol + '</td>' +
      '<td class="text-right mono">' + fl + '</td>' +
      '<td class="text-center"><button class="btn-sm" onclick="loadChartForSymbol(\'' + gp.symbol + '\')">Chart</button></td>' +
      '</tr>';
  }).join('');
}

// ─── Signals ────────────────────────────────────────────────────────
function renderSignals(s) {
  document.getElementById('stat-passes').textContent = s.passes.length;
  document.getElementById('stat-passes-sub').textContent = s.scan_time ? 'Scan: ' + s.scan_time : '--';
  var container = document.getElementById('signals-container');
  if (!s.passes.length && !s.fails.length) {
    container.innerHTML = '<div class="card card-empty">No signals today</div>';
    return;
  }
  var html = '';
  s.passes.forEach(function(p) { html += signalCard(p, true); });
  s.fails.forEach(function(p) { html += signalCard(p, false); });
  container.innerHTML = html;
}

function signalCard(p, isPass) {
  var icon = isPass ? '✅' : '❌';
  var badgeClass = isPass ? 'badge-green' : 'badge-red';
  var badgeText = isPass ? 'PASS' : p.result || 'FAIL';
  var glowClass = isPass ? ' glow-green' : '';
  var details = '';
  if (p.curr_price) {
    details = '$' + p.curr_price.toFixed(2);
    if (p.prev_daily_high) details += ' | Prev high $' + p.prev_daily_high.toFixed(2);
    if (p.sma200) details += ' | SMA200 $' + p.sma200.toFixed(2);
  }

  return '<div class="card' + glowClass + '">' +
    '<div class="signal-card">' +
      '<div class="signal-left">' +
        '<span class="signal-icon">' + icon + '</span>' +
        '<div>' +
          '<div class="signal-sym">' + p.symbol + ' <span class="badge ' + badgeClass + '">' + badgeText + '</span></div>' +
          (details ? '<div class="signal-detail">' + details + '</div>' : '') +
        '</div>' +
      '</div>' +
      '<button class="btn-sm" onclick="loadChartForSymbol(\'' + p.symbol + '\')">Chart</button>' +
    '</div>' +
  '</div>';
}

// ─── Positions ──────────────────────────────────────────────────────
function renderPositions(data) {
  var grid = document.getElementById('positions-grid');
  document.getElementById('tab-pos-count').textContent = data.open_count;

  if (!data.positions.length) {
    grid.innerHTML = '<div class="card card-empty" style="grid-column:span 2">' +
      '<div class="empty-icon">💭</div>' +
      '<div>No positions today</div>' +
      '<div style="font-size:12px;margin-top:4px;color:var(--text-3)">PASS signals are tracked automatically</div>' +
    '</div>';
    return;
  }

  grid.innerHTML = data.positions.map(function(pos) {
    var isOpen = pos.status === 'open';
    var entry = pos.entry_price;
    var current = pos.exit_price || pos.high_water || entry;
    var pnl = ((current - entry) / entry * 100).toFixed(2);
    var pnlColor = pnl >= 0 ? 'color-green' : 'color-red';
    var pnlSign = pnl >= 0 ? '+' : '';
    var target = (entry + pos.atr).toFixed(2);
    var trailStop = (pos.high_water * (1 - 2.0 / 100)).toFixed(2);
    var progressPct = Math.min(((current - entry) / pos.atr) * 100, 100);
    var progressClass = progressPct >= 100 ? 'progress-fill-green' : 'progress-fill-blue';

    var statusBadge = isOpen ? '<span class="badge badge-blue">OPEN</span>'
      : pos.exit_reason === 'trailing_stop' ? '<span class="badge badge-red">TRAILING STOP</span>'
      : '<span class="badge badge-yellow">EOD EXIT</span>';
    var partialBadge = pos.partial_alerted ? '<span class="badge badge-green">PARTIAL</span>' : '';

    var html = '<div class="card' + (isOpen ? ' glow-blue' : '') + '">' +
      '<div class="pos-header">' +
        '<div><span class="pos-symbol">' + pos.symbol + '</span>' + statusBadge + partialBadge + '</div>' +
        '<span class="pos-pnl ' + pnlColor + '">' + pnlSign + pnl + '%</span>' +
      '</div>' +
      '<div class="pos-stats">' +
        '<div><div class="pos-stat-label">Entry</div><div class="pos-stat-value mono">$' + entry.toFixed(2) + '</div></div>' +
        '<div><div class="pos-stat-label">' + (isOpen ? 'High' : 'Exit') + '</div><div class="pos-stat-value mono">$' + current.toFixed(2) + '</div></div>' +
        '<div><div class="pos-stat-label">ATR</div><div class="pos-stat-value mono">$' + pos.atr.toFixed(2) + '</div></div>' +
      '</div>';

    if (isOpen) {
      html += '<div class="progress-bar"><div class="progress-fill ' + progressClass + '" style="width:' + Math.max(0, Math.min(progressPct, 100)) + '%"></div></div>' +
        '<div class="progress-labels">' +
          '<span class="color-red">Stop $' + trailStop + '</span>' +
          '<span class="color-muted">Target $' + target + '</span>' +
        '</div>';
    } else {
      html += '<div style="margin-top:12px;font-size:12px;color:var(--text-3)">' +
        'Exit: ' + (pos.exit_reason === 'trailing_stop' ? 'Trailing Stop' : 'End of Day') +
        (pos.exit_price ? ' @ $' + pos.exit_price.toFixed(2) : '') +
      '</div>';
    }

    html += '<div style="margin-top:12px;text-align:right">' +
      '<button class="btn-sm" onclick="loadChartForSymbol(\'' + pos.symbol + '\')">View chart</button></div></div>';
    return html;
  }).join('');
}

// ─── History ────────────────────────────────────────────────────────
function renderHistory(data) {
  var container = document.getElementById('history-container');
  if (!data.days.length) {
    container.innerHTML = '<div class="card card-empty">No history available</div>';
    return;
  }
  container.innerHTML = data.days.map(function(day) {
    var total = day.wins + day.losses;
    var winRate = total > 0 ? ((day.wins / total) * 100).toFixed(0) : '--';
    var trades = day.positions.filter(function(p) { return p.status === 'closed'; }).map(function(p) {
      var pnl = p.exit_price && p.entry_price ? ((p.exit_price - p.entry_price) / p.entry_price * 100) : 0;
      var cls = pnl >= 0 ? 'trade-win' : 'trade-loss';
      return '<span class="trade-chip ' + cls + '">' + p.symbol + '</span>';
    }).join('');

    return '<div class="card">' +
      '<div class="history-header">' +
        '<div><span style="font-weight:600">' + day.date + '</span> <span class="color-muted" style="margin-left:8px">' + day.total + ' Trades</span></div>' +
        '<div class="history-stats">' +
          '<span class="color-green">' + day.wins + 'W</span>' +
          '<span class="color-red">' + day.losses + 'L</span>' +
          '<span>' + winRate + '%</span>' +
        '</div>' +
      '</div>' +
      '<div class="history-trades">' + trades + '</div>' +
    '</div>';
  }).join('');
}

// ─── Chart ──────────────────────────────────────────────────────────
function loadChartForSymbol(symbol) {
  document.getElementById('chart-symbol-input').value = symbol;
  switchTab('chart');
  loadChart();
}

async function loadChart() {
  var symbol = document.getElementById('chart-symbol-input').value.trim().toUpperCase();
  if (!symbol) return;
  var period = document.getElementById('chart-period').value;
  var interval = document.getElementById('chart-interval').value;

  var data = await fetchJSON('/api/chart/' + symbol + '?period=' + period + '&interval=' + interval);
  if (!data || !data.bars || !data.bars.length) return;

  var container = document.getElementById('main-chart');
  container.innerHTML = '';

  mainChart = LightweightCharts.createChart(container, {
    width: container.clientWidth,
    height: 500,
    layout: {
      background: { type: 'solid', color: '#161923' },
      textColor: '#94a3b8',
      fontSize: 12,
    },
    grid: {
      vertLines: { color: '#1c2030' },
      horzLines: { color: '#1c2030' },
    },
    crosshair: {
      mode: LightweightCharts.CrosshairMode.Normal,
      vertLine: { color: '#3b82f6', width: 1, style: 2, labelBackgroundColor: '#3b82f6' },
      horzLine: { color: '#3b82f6', width: 1, style: 2, labelBackgroundColor: '#3b82f6' },
    },
    timeScale: { borderColor: '#242838', timeVisible: true, secondsVisible: false },
    rightPriceScale: { borderColor: '#242838' },
  });

  mainSeries = mainChart.addCandlestickSeries({
    upColor: '#22c55e', downColor: '#ef4444',
    borderDownColor: '#ef4444', borderUpColor: '#22c55e',
    wickDownColor: '#ef4444', wickUpColor: '#22c55e',
  });
  mainSeries.setData(data.bars);

  var volumeSeries = mainChart.addHistogramSeries({
    color: '#3b82f6', priceFormat: { type: 'volume' }, priceScaleId: 'volume',
  });
  mainChart.priceScale('volume').applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
  volumeSeries.setData(data.bars.map(function(b) {
    return { time: b.time, value: b.volume, color: b.close >= b.open ? 'rgba(34,197,94,0.3)' : 'rgba(239,68,68,0.3)' };
  }));

  mainChart.timeScale().fitContent();
  new ResizeObserver(function() { mainChart.applyOptions({ width: container.clientWidth }); }).observe(container);
}

// ─── Helpers ────────────────────────────────────────────────────────
function formatNumber(n) {
  if (n >= 1e9) return (n / 1e9).toFixed(1) + 'B';
  if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M';
  if (n >= 1e3) return (n / 1e3).toFixed(1) + 'K';
  return String(n);
}

// ─── Init ───────────────────────────────────────────────────────────
refreshAll();
setInterval(refreshAll, 30000);
document.getElementById('chart-symbol-input').addEventListener('keydown', function(e) {
  if (e.key === 'Enter') loadChart();
});
