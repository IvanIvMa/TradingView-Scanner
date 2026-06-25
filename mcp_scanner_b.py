#!/usr/bin/env python3
# =============================================================================
# mcp_scanner_b.py — Scanner B mit TradingView-Echtzeitdaten, OHNE Claude-Session
# =============================================================================
# Treibt den TradingView-MCP-Server (lokaler stdio-Node-Prozess) direkt per
# JSON-RPC an — dieselben Daten wie im Claude-MCP-Modus, aber als eigenständiges
# Script, das von launchd gestartet werden kann (persistent, kein 7-Tage-Ablauf,
# keine Token-Kosten, keine Session-Abhängigkeit).
#
# Ablauf:
#   1. Heutige Gappers aus premarket_gappers_YYYY-MM-DD.json laden
#   2. MCP-Server starten + Handshake; tv_health_check
#      -> TradingView nicht erreichbar? Fallback: tjl_scanner.sh (yfinance)
#   3. PMH/HOD via yfinance (kumulative Maxima, Verzögerung egal)
#   4. Pro Ticker via MCP: Daily-OHLCV (prev_high/close), SMA200, Live-Quote
#   5. tjl_scanner.sh --force --mcp-data '<JSON>' aufrufen
#
# Nutzung:
#   python3 mcp_scanner_b.py            # normal (von launchd)
#   python3 mcp_scanner_b.py --force    # Zeit-Gate in tjl_scanner.sh umgehen
# =============================================================================

import subprocess, json, sys, time, select, os
from datetime import datetime
from zoneinfo import ZoneInfo

import yfinance as yf

ET = ZoneInfo("America/New_York")
BASE = os.path.dirname(os.path.abspath(__file__))
MCP_SERVER = "/Users/ivan/tradingview-mcp/src/server.js"
FORCE = "--force" in sys.argv


def find_node():
    """node-Binary robust finden (launchd hat /opt/homebrew/bin NICHT im PATH)."""
    import shutil
    cand = os.environ.get("MCP_NODE")
    if cand and os.path.exists(cand):
        return cand
    for p in ("/opt/homebrew/bin/node", "/usr/local/bin/node", "/usr/bin/node"):
        if os.path.exists(p):
            return p
    return shutil.which("node") or "node"


NODE_BIN = find_node()


def log(msg):
    ts = datetime.now(ET).strftime("%H:%M:%S ET")
    print(f"[mcp_scanner_b {ts}] {msg}", flush=True)


# -----------------------------------------------------------------------------
# Minimaler MCP-stdio-Client (JSON-RPC 2.0, zeilenbasiert)
# -----------------------------------------------------------------------------
class MCPClient:
    def __init__(self, server_path):
        self.proc = subprocess.Popen(
            [NODE_BIN, server_path],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1)
        self._id = 0

    def _send(self, obj):
        self.proc.stdin.write(json.dumps(obj) + "\n")
        self.proc.stdin.flush()

    def _read(self, mid, timeout=20):
        end = time.time() + timeout
        while time.time() < end:
            r, _, _ = select.select([self.proc.stdout], [], [], end - time.time())
            if not r:
                continue
            line = self.proc.stdout.readline()
            if not line:
                break
            line = line.strip()
            if not line:
                continue
            try:
                m = json.loads(line)
            except json.JSONDecodeError:
                continue
            if m.get("id") == mid:
                return m
        return None

    def call(self, method, params=None, timeout=20):
        self._id += 1
        mid = self._id
        self._send({"jsonrpc": "2.0", "id": mid, "method": method,
                    "params": params or {}})
        return self._read(mid, timeout)

    def notify(self, method, params=None):
        self._send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def handshake(self):
        self.call("initialize", {"protocolVersion": "2024-11-05",
                                 "capabilities": {},
                                 "clientInfo": {"name": "launchd-scanner-b", "version": "1.0"}})
        self.notify("notifications/initialized")

    def tool(self, name, args=None, timeout=20):
        resp = self.call("tools/call", {"name": name, "arguments": args or {}}, timeout)
        if not resp or "result" not in resp:
            return None
        for c in resp["result"].get("content", []):
            if c.get("type") == "text":
                try:
                    return json.loads(c["text"])
                except json.JSONDecodeError:
                    return c["text"]
        return None

    def close(self):
        try:
            self.proc.terminate()
            self.proc.wait(timeout=3)
        except Exception:
            self.proc.kill()


def parse_de_number(s):
    """'1.125,00' -> 1125.0 ; '57,38' -> 57.38 ; None bei Fehler."""
    if not s:
        return None
    try:
        return float(str(s).replace(".", "").replace(",", "."))
    except (ValueError, AttributeError):
        return None


def get_sma200(study_values):
    """SMA200 aus 'Demo TJL Strategy' (Fallback 'SMA200 & RSI Alert')."""
    studies = (study_values or {}).get("studies", [])
    for name in ("Demo TJL Strategy", "SMA200 & RSI Alert"):
        for st in studies:
            if st.get("name") == name:
                v = st.get("values", {}).get("SMA200")
                n = parse_de_number(v)
                if n is not None:
                    return n
    return None


def compute_pmh_hod(tickers):
    """PMH (4:00-9:30 ET) + HOD (9:30-jetzt ET) je Ticker via yfinance."""
    today = datetime.now(ET).date()
    out = {}
    for sym in tickers:
        try:
            intra = yf.Ticker(sym).history(period="2d", interval="1m", prepost=True)
            if intra.empty:
                out[sym] = (None, None)
                continue
            intra.index = intra.index.tz_convert(ET)
            tb = intra[intra.index.date == today]
            if tb.empty:
                out[sym] = (None, None)
                continue
            pm = tb[(tb.index.hour >= 4) &
                    ((tb.index.hour < 9) | ((tb.index.hour == 9) & (tb.index.minute < 30)))]
            rs = tb[((tb.index.hour > 9) | ((tb.index.hour == 9) & (tb.index.minute >= 30))) &
                    (tb.index.hour < 16)]
            pmh = round(float(pm["High"].max()), 2) if not pm.empty else None
            hod = round(float(rs["High"].max()), 2) if not rs.empty else None
            out[sym] = (pmh, hod)
        except Exception as e:
            log(f"  PMH/HOD {sym}: Fehler {str(e)[:50]}")
            out[sym] = (None, None)
    return out


def run_yfinance_fallback():
    cmd = ["bash", os.path.join(BASE, "tjl_scanner.sh")]
    if FORCE:
        cmd.append("--force")
    log("TradingView nicht erreichbar — Fallback auf yfinance (tjl_scanner.sh).")
    subprocess.run(cmd, cwd=BASE)


def main():
    # 1. Gappers laden
    date = datetime.now(ET).strftime("%Y-%m-%d")
    gfile = os.path.join(BASE, f"premarket_gappers_{date}.json")
    if not os.path.exists(gfile):
        log(f"Keine Gappers-Datei ({gfile}) — nichts zu tun.")
        return
    with open(gfile) as f:
        gappers = json.load(f).get("gappers", [])
    tickers = [g["symbol"] for g in gappers]
    if not tickers:
        log("Gappers-Liste leer — nichts zu tun.")
        return
    log(f"{len(tickers)} Gappers: {', '.join(tickers)}")

    # 2. MCP starten + Health-Check
    mcp = MCPClient(MCP_SERVER)
    try:
        mcp.handshake()
        health = mcp.tool("tv_health_check")
        if not health or not health.get("cdp_connected"):
            mcp.close()
            run_yfinance_fallback()
            return
        log(f"TradingView verbunden (Chart: {health.get('chart_symbol')}).")

        # 3. PMH/HOD via yfinance
        pmh_hod = compute_pmh_hod(tickers)

        # 4. Pro Ticker: Daily-OHLCV + SMA200 + Quote via MCP
        mcp_data = []
        for sym in tickers:
            mcp.tool("chart_set_symbol", {"symbol": sym})
            mcp.tool("chart_set_timeframe", {"timeframe": "D"})
            time.sleep(0.3)  # Chart settlen lassen
            ohlcv = mcp.tool("data_get_ohlcv", {"count": 3, "summary": False})
            studies = mcp.tool("data_get_study_values")
            quote = mcp.tool("quote_get", {"symbol": sym})

            bars = (ohlcv or {}).get("bars", [])
            if len(bars) < 2 or not quote:
                log(f"  {sym}: unvollständige Daten — übersprungen.")
                continue
            prev = bars[-2]  # vorletzte Bar = letzter abgeschlossener Handelstag
            curr_price = quote.get("last")
            pmh, hod = pmh_hod.get(sym, (None, None))
            mcp_data.append({
                "symbol": sym,
                "curr_price": curr_price,
                "prev_daily_high": prev.get("high"),
                "prev_daily_close": prev.get("close"),
                "sma200": get_sma200(studies),
                "pmh": pmh,
                "hod": hod,
            })
        log(f"Daten für {len(mcp_data)}/{len(tickers)} Ticker gesammelt.")
    finally:
        mcp.close()

    if not mcp_data:
        log("Keine verwertbaren MCP-Daten — Fallback auf yfinance.")
        run_yfinance_fallback()
        return

    # 5. tjl_scanner.sh mit MCP-Daten füttern
    cmd = ["bash", os.path.join(BASE, "tjl_scanner.sh"), "--force",
           "--mcp-data", json.dumps(mcp_data)]
    subprocess.run(cmd, cwd=BASE)


if __name__ == "__main__":
    main()
