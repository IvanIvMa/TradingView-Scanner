import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import * as tv from "./cdp.js";

const server = new McpServer({
  name: "tradingview",
  version: "1.0.0",
});

// ---- 1. Health Check -------------------------------------------------------
server.tool(
  "tv_health_check",
  "Prüft ob TradingView Desktop via CDP verbunden ist.",
  {},
  async () => {
    const result = await tv.healthCheck();
    return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
  }
);

// ---- 2. Chart-Daten --------------------------------------------------------
server.tool(
  "tv_get_chart_info",
  "Liest Symbol, Timeframe und aktuelle Chart-Informationen aus TradingView.",
  {},
  async () => {
    const result = await tv.getChartInfo();
    return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
  }
);

server.tool(
  "tv_screenshot",
  "Erstellt einen Screenshot des aktuellen TradingView Charts.",
  {},
  async () => {
    const b64 = await tv.screenshot();
    return {
      content: [{ type: "image", data: b64, mimeType: "image/png" }],
    };
  }
);

// ---- 3. Scanner ------------------------------------------------------------
server.tool(
  "tv_get_scanner_results",
  "Liest die Ergebnisse des TradingView Scanners aus. Der Scanner muss in TradingView geöffnet sein.",
  {},
  async () => {
    const result = await tv.getScannerResults();
    return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
  }
);

// ---- 4. Alerts -------------------------------------------------------------
server.tool(
  "tv_get_alerts",
  "Listet alle aktiven TradingView Alerts auf. Die Alert-Liste muss in TradingView geöffnet sein.",
  {},
  async () => {
    const result = await tv.getAlerts();
    return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
  }
);

server.tool(
  "tv_create_alert",
  "Öffnet den Alert-Dialog in TradingView (Alt+A). Vollautomatisches Erstellen ist aus Sicherheitsgründen nicht möglich.",
  {
    symbol: z.string().describe("Ticker-Symbol, z.B. AAPL"),
    condition: z.string().describe("Bedingung, z.B. 'price crosses above'"),
    price: z.number().describe("Preislevel für den Alert"),
  },
  async ({ symbol, condition, price }) => {
    const result = await tv.createAlert(symbol, condition, price);
    return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
  }
);

server.tool(
  "tv_delete_alert",
  "Löscht einen Alert in TradingView anhand eines Suchtexts (Symbol oder Beschreibung).",
  {
    alert_text: z.string().describe("Text des Alerts, der gelöscht werden soll"),
  },
  async ({ alert_text }) => {
    const result = await tv.deleteAlert(alert_text);
    return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
  }
);

// ---- Start -----------------------------------------------------------------
const transport = new StdioServerTransport();
await server.connect(transport);
