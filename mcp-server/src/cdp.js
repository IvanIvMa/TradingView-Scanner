/**
 * CDP (Chrome DevTools Protocol) connection manager for TradingView Desktop.
 *
 * TradingView Desktop must be started with:
 *   open -a TradingView --args --remote-debugging-port=9222
 */

import CDP from "chrome-remote-interface";

const PORT = 9222;
let _client = null;

async function connect() {
  let targets;
  try {
    targets = await CDP.List({ port: PORT });
  } catch {
    throw new Error(
      `TradingView ist nicht erreichbar (Port ${PORT}). ` +
        'Starte TradingView mit: open -a TradingView --args --remote-debugging-port=9222'
    );
  }

  // Hauptseite finden (kein Service Worker, keine Extensions)
  const page =
    targets.find(
      (t) =>
        t.type === "page" &&
        (t.url.includes("tradingview") || t.title.includes("TradingView"))
    ) || targets.find((t) => t.type === "page");

  if (!page) throw new Error("Keine TradingView-Seite unter den CDP-Targets gefunden.");

  return CDP({ target: page.id, port: PORT });
}

async function getClient() {
  if (_client) {
    try {
      await _client.Runtime.evaluate({ expression: "1", returnByValue: true });
      return _client;
    } catch {
      _client = null;
    }
  }
  _client = await connect();
  return _client;
}

async function evaluate(expression) {
  const client = await getClient();
  const result = await client.Runtime.evaluate({
    expression,
    returnByValue: true,
    awaitPromise: true,
  });
  if (result.exceptionDetails) {
    throw new Error(result.exceptionDetails.exception?.description || "JS-Fehler");
  }
  return result.result.value;
}

// ---------------------------------------------------------------------------
// Öffentliche Funktionen
// ---------------------------------------------------------------------------

export async function healthCheck() {
  try {
    const client = await getClient();
    const targets = await CDP.List({ port: PORT });

    const title = await evaluate("document.title");
    const url = await evaluate("window.location.href");
    const apiAvailable = await evaluate(
      'typeof window.TradingView !== "undefined" || typeof window.tvWidget !== "undefined"'
    );

    return {
      cdp_connected: true,
      page_title: title,
      page_url: url,
      api_available: apiAvailable,
      targets_found: targets.length,
    };
  } catch (err) {
    return { cdp_connected: false, error: err.message };
  }
}

export async function getChartInfo() {
  const js = `
    (function() {
      const info = { method: null };
      try {
        // Methode 1: tvWidget API
        if (window.tvWidget && typeof window.tvWidget.chart === 'function') {
          const c = window.tvWidget.chart();
          info.symbol   = c.symbol();
          info.interval = c.resolution();
          info.method   = 'tvWidget';
          return info;
        }
        // Methode 2: URL-Parameter
        const url = window.location.href;
        const symMatch = url.match(/symbol=([^&]+)/);
        if (symMatch) { info.symbol = decodeURIComponent(symMatch[1]); info.method = 'url'; }
        // Methode 3: DOM – Legende des Charts
        const legendEl = document.querySelector(
          '[data-name="legend-series-item"] span, .chart-markup-table .pane-legend-title'
        );
        if (legendEl) { info.symbol_dom = legendEl.textContent.trim(); info.method = info.method || 'dom'; }
        return info;
      } catch(e) { return { error: e.message }; }
    })()
  `;
  return await evaluate(js);
}

export async function getScannerResults() {
  const js = `
    (function() {
      try {
        // Scanner-Tabelle im DOM suchen
        const rows = Array.from(document.querySelectorAll(
          'tr[data-rowindex], .screener-table-row, [class*="row-"][class*="screener"]'
        ));
        if (rows.length === 0) return { error: 'Kein Scanner-Widget gefunden oder Scanner nicht geöffnet.' };
        return rows.slice(0, 20).map(row => {
          const cells = Array.from(row.querySelectorAll('td, [class*="cell"]'));
          return cells.map(c => c.textContent.trim()).filter(Boolean);
        });
      } catch(e) { return { error: e.message }; }
    })()
  `;
  const raw = await evaluate(js);
  if (raw && raw.error) return raw;
  return { rows: raw, note: 'Rohdaten aus Scanner-DOM. Scanner muss in TradingView geöffnet sein.' };
}

export async function getAlerts() {
  const js = `
    (function() {
      try {
        // Alerts aus dem DOM lesen (Alert-Liste muss geöffnet sein)
        const alertEls = Array.from(document.querySelectorAll(
          '[data-name="alert-item"], .alarm-item, [class*="alertItem"]'
        ));
        if (alertEls.length === 0) return { note: 'Keine Alerts im DOM. Öffne die Alert-Liste in TradingView.' };
        return alertEls.map(el => ({
          text: el.querySelector('[class*="title"], [class*="name"]')?.textContent?.trim(),
          status: el.querySelector('[class*="status"]')?.textContent?.trim(),
          raw: el.textContent.trim().slice(0, 120),
        }));
      } catch(e) { return { error: e.message }; }
    })()
  `;
  return await evaluate(js);
}

export async function createAlert(symbol, condition, price) {
  // TradingView Alerts können nur über die UI erstellt werden.
  // Diese Funktion öffnet den Alert-Dialog mit vorausgefüllten Werten via Keyboard-Shortcut.
  const js = `
    (function() {
      try {
        // Alt+A öffnet "Create Alert"-Dialog in TradingView
        document.dispatchEvent(new KeyboardEvent('keydown', {
          key: 'a', altKey: true, bubbles: true
        }));
        return { triggered: true, note: 'Alert-Dialog-Shortcut (Alt+A) wurde ausgelöst. Fülle die Felder manuell aus.' };
      } catch(e) { return { error: e.message }; }
    })()
  `;
  const result = await evaluate(js);
  return {
    ...result,
    symbol,
    requested_condition: condition,
    requested_price: price,
  };
}

export async function deleteAlert(alertText) {
  const js = `
    (function(searchText) {
      try {
        const items = Array.from(document.querySelectorAll(
          '[data-name="alert-item"], .alarm-item, [class*="alertItem"]'
        ));
        const match = items.find(el => el.textContent.includes(searchText));
        if (!match) return { deleted: false, error: 'Alert nicht gefunden: ' + searchText };
        const deleteBtn = match.querySelector('[data-name="remove"], [class*="remove"], [class*="delete"]');
        if (deleteBtn) { deleteBtn.click(); return { deleted: true }; }
        return { deleted: false, error: 'Löschen-Button nicht gefunden.' };
      } catch(e) { return { error: e.message }; }
    })("${alertText.replace(/"/g, '\\"')}")
  `;
  return await evaluate(js);
}

export async function screenshot() {
  const client = await getClient();
  const { data } = await client.Page.captureScreenshot({ format: "png" });
  return data; // base64
}
