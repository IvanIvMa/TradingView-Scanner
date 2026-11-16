// open_chart.mjs — öffnet in TradingView Desktop einen Chart (via CDP Port 9222),
// falls die App nur auf der Start-/Layout-Auswahlseite steht.
// Nutzung: node open_chart.mjs [SYMBOL]   (Default: NASDAQ:AAPL)
import CDP from '/Users/ivan/tradingview-mcp/node_modules/chrome-remote-interface/index.js';

const symbol = process.argv[2] || 'NASDAQ:AAPL';
const targets = await CDP.List({ port: 9222 });
const pages = targets.filter(t => t.type === 'page');
const target =
  pages.find(t => t.url.includes('new-tab')) ||
  pages.find(t => t.url.startsWith('https://www.tradingview.com')) ||
  undefined; // undefined = CDP-Default (hat in Tests funktioniert)

const c = await CDP({ port: 9222, target });
try {
  await c.Page.navigate({ url: `https://www.tradingview.com/chart/?symbol=${encodeURIComponent(symbol)}` });
  let ok = false;
  for (let i = 0; i < 20 && !ok; i++) {          // bis ~40 s auf Chart-API warten
    await new Promise(r => setTimeout(r, 2000));
    const r = await c.Runtime.evaluate({ expression: '!!window.TradingViewApi' });
    ok = r.result.value === true;
  }
  console.log(ok ? `chart_opened ${symbol}` : 'chart_not_ready');
  process.exitCode = ok ? 0 : 1;
} finally {
  await c.close();
}
