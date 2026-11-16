#!/usr/bin/env python3
"""
position_tracker.py — Exit-Überwachung für TJL-Trades (Scanner B).

Logik:
  - Jeder PASS aus der heutigen TJL-Watchlist öffnet AUTOMATISCH eine beobachtete Position
    (Einstiegskurs = curr_price beim PASS).
  - Pro Lauf werden alle offenen Positionen überwacht:
      1. Teilgewinn  : Kurs erreicht Einstieg + 1 ATR  → Alert "Teilgewinn (50%), Stop auf Einstieg"
      2. Stop: fest Einstieg - INIT_STOP_ATR*ATR; nach Teilgewinn Trailing TRAIL_ATR*ATR unter Hoch (≥ Einstieg)
      3. EOD-Schluss : ab 15:45 ET → Alert "vor Börsenschluss schließen"
  - Genauigkeit: zwischen zwei Läufen werden ALLE 1-Min-Bars seit Einstieg nachgespielt,
    damit auch ein Trailing-Stop ZWISCHEN den Läufen erkannt wird.
  - Datenquelle: TradingView (via MCP) wenn verfügbar, sonst Yahoo Finance als Fallback.
  - Rein informativ: das System handelt NICHT. Alerts sagen "die Strategie würde jetzt aussteigen".

Zustand:  positions_YYYY-MM-DD.json  (offene/geschlossene Positionen des Tages)
Aufruf:   python3 position_tracker.py            (normaler Lauf)
          python3 position_tracker.py --force    (Zeit-Gate ignorieren, zum Testen)
"""

import sys, os, json, glob, subprocess, time, select, shutil
from datetime import datetime
from zoneinfo import ZoneInfo

import yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tjl_rules as R  # gemeinsame Regeln (Live = Backtest)

# --- Parameter (Backtest-Standard, anpassbar) ---
# Stop-/Ziel-Parameter: siehe tjl_rules.PARAMS (gemeinsam mit Backtest)
ATR_PERIOD    = 14      # ATR-Periode (Tagesbasis)
EOD_HOUR_ET   = 15      # Zwangsschluss-Zeit (ET)
EOD_MIN_ET    = 45

ET     = ZoneInfo("America/New_York")
BERLIN = ZoneInfo("Europe/Berlin")
HERE   = os.path.dirname(os.path.abspath(__file__))
MCP_SERVER = "/Users/ivan/tradingview-mcp/src/server.js"


# ---------------------------------------------------------------------------
# Minimaler MCP-stdio-Client (identisch mit mcp_scanner_b.py)
# ---------------------------------------------------------------------------
def _find_node():
    cand = os.environ.get("MCP_NODE")
    if cand and os.path.exists(cand):
        return cand
    for p in ("/opt/homebrew/bin/node", "/usr/local/bin/node", "/usr/bin/node"):
        if os.path.exists(p):
            return p
    return shutil.which("node") or "node"


class MCPClient:
    def __init__(self, server_path):
        self.proc = subprocess.Popen(
            [_find_node(), server_path],
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
                                 "clientInfo": {"name": "position-tracker", "version": "1.0"}})
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


def try_connect_mcp():
    """MCP-Server starten + Health-Check. Gibt MCPClient zurück oder None."""
    if not os.path.exists(MCP_SERVER):
        return None
    try:
        mcp = MCPClient(MCP_SERVER)
        mcp.handshake()
        health = mcp.tool("tv_health_check")
        if health and health.get("cdp_connected"):
            return mcp
        mcp.close()
    except Exception:
        pass
    return None


def parse_de_number(s):
    if not s:
        return None
    try:
        return float(str(s).replace(".", "").replace(",", "."))
    except (ValueError, AttributeError):
        return None


# ---------------------------------------------------------------------------
def load_env():
    env = {}
    path = os.path.join(HERE, ".env")
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip()
    return env

ENV = load_env()

def send_telegram(msg):
    token = ENV.get("TELEGRAM_BOT_TOKEN")
    chat  = ENV.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("  ! Telegram credentials missing", file=sys.stderr)
        return
    payload = json.dumps({"chat_id": int(chat), "text": msg, "parse_mode": "HTML"})
    subprocess.run(
        ["curl", "-s", "-X", "POST",
         f"https://api.telegram.org/bot{token}/sendMessage",
         "-H", "Content-Type: application/json", "-d", payload],
        capture_output=True
    )


# ---------------------------------------------------------------------------
def compute_atr(symbol, period=ATR_PERIOD):
    """ATR aus abgeschlossenen Tagesbalken."""
    try:
        daily = yf.Ticker(symbol).history(period="3mo", interval="1d")
        if len(daily) < period + 1:
            return None
        highs  = daily["High"].tolist()
        lows   = daily["Low"].tolist()
        closes = daily["Close"].tolist()
        trs = []
        for i in range(1, len(daily)):
            tr = max(highs[i] - lows[i],
                     abs(highs[i] - closes[i-1]),
                     abs(lows[i] - closes[i-1]))
            trs.append(tr)
        return round(sum(trs[-period:]) / period, 2)
    except Exception:
        return None


def today_intraday_since_yf(symbol, entry_ts, now_et):
    """1-Min-Bars von heute ab Einstiegszeit via Yahoo Finance."""
    try:
        intra = yf.Ticker(symbol).history(period="1d", interval="1m", prepost=True)
        if intra.empty:
            return []
        intra.index = intra.index.tz_convert(ET)
        today = intra[intra.index.date == now_et.date()]
        bars = []
        for ts, row in today.iterrows():
            t = ts.timestamp()
            if t >= entry_ts:
                bars.append({"t": t, "high": float(row["High"]),
                             "low": float(row["Low"]), "close": float(row["Close"])})
        return bars
    except Exception:
        return []


def today_intraday_since_tv(mcp, symbol, entry_ts, now_et):
    """1-Min-Bars von heute ab Einstiegszeit via TradingView MCP."""
    try:
        mcp.tool("chart_set_symbol", {"symbol": symbol})
        mcp.tool("chart_set_timeframe", {"timeframe": "1"})
        time.sleep(0.3)
        minutes_since_open = int((now_et.timestamp() - entry_ts) / 60) + 5
        count = max(minutes_since_open, 30)
        ohlcv = mcp.tool("data_get_ohlcv", {"count": count, "summary": False}, timeout=30)
        if not ohlcv or "bars" not in ohlcv:
            return None
        bars = []
        for b in ohlcv["bars"]:
            t = b.get("time")
            if t is None:
                continue
            if isinstance(t, str):
                continue
            if t >= entry_ts:
                high = parse_de_number(b.get("high")) if isinstance(b.get("high"), str) else b.get("high")
                low = parse_de_number(b.get("low")) if isinstance(b.get("low"), str) else b.get("low")
                close = parse_de_number(b.get("close")) if isinstance(b.get("close"), str) else b.get("close")
                if high is not None and low is not None and close is not None:
                    bars.append({"t": t, "high": float(high),
                                 "low": float(low), "close": float(close)})
        return bars if bars else None
    except Exception:
        return None


def today_intraday_since(symbol, entry_ts, now_et, mcp=None):
    """1-Min-Bars: TradingView wenn MCP verfügbar, sonst Yahoo Finance."""
    if mcp:
        bars = today_intraday_since_tv(mcp, symbol, entry_ts, now_et)
        if bars is not None:
            return bars
    return today_intraday_since_yf(symbol, entry_ts, now_et)


# ---------------------------------------------------------------------------
def get_today_passes():
    """Neueste TJL-Watchlist von heute lesen → {symbol: curr_price}."""
    today = datetime.now(BERLIN).strftime("%Y-%m-%d")
    files = sorted(glob.glob(os.path.join(HERE, f"tjl_watchlist_{today}_*.json")), reverse=True)
    passes = {}
    if files:
        try:
            with open(files[0]) as f:
                data = json.load(f)
            for h in data.get("hits", []):
                passes[h["symbol"]] = h
        except Exception:
            pass
    return passes


def fmt_et(ts):
    return datetime.fromtimestamp(ts, ET).strftime("%H:%M ET")


# ---------------------------------------------------------------------------
def main():
    force = "--force" in sys.argv
    now_et = datetime.now(ET)
    today = datetime.now(BERLIN).strftime("%Y-%m-%d")
    state_path = os.path.join(HERE, f"positions_{today}.json")

    # Zeit-Gate: Überwachung nur während/nach Handelszeit (10:00-16:00 ET)
    market_open  = now_et.replace(hour=10, minute=0, second=0, microsecond=0)
    market_close = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
    in_window = market_open <= now_et <= market_close
    if not in_window and not force:
        print(f"  Outside monitoring window ({now_et.strftime('%H:%M ET')}) — skipping.")
        return

    is_eod = (now_et.hour, now_et.minute) >= (EOD_HOUR_ET, EOD_MIN_ET)

    # TradingView MCP verbinden (Fallback: Yahoo Finance)
    mcp = None  # Kerzen kommen seit 2026-11-16 immer von Yahoo (gleiche Quelle wie Backtest)
    print("  Data source: Yahoo Finance 1-min (tjl_rules.py)")

    # Zustand laden
    positions = {}
    if os.path.exists(state_path):
        try:
            with open(state_path) as f:
                positions = json.load(f)
        except Exception:
            positions = {}

    alerts = []

    # --- 1. Neue Positionen aus PASS-Signalen eröffnen ---
    passes = get_today_passes()
    for sym, hit in passes.items():
        price = hit.get("curr_price")
        if sym in positions or price is None:
            continue
        atr = hit.get("atr") or compute_atr(sym) or round(price * 0.02, 2)
        positions[sym] = {
            "symbol": sym, "entry_price": price,
            "entry_ts": now_et.timestamp(), "entry_et": now_et.strftime("%H:%M ET"),
            "atr": atr, "high_water": price, "partial_alerted": False,
            "vwap_break_alerted": False, "status": "open",
            "entry_filters": hit.get("filters"), "entry_vwap": hit.get("vwap"),
        }
        P = R.PARAMS
        alerts.append(
            f"👁 <b>{sym} — Tracking started</b>\n"
            f"   Entry ${price}  |  ATR ${atr}\n"
            f"   Partial profit target: ${round(price + atr * P['PARTIAL_ATR'], 2)} (+{P['PARTIAL_ATR']} ATR)\n"
            f"   Initial stop: ${round(price - atr * P['INIT_STOP_ATR'], 2)} (-{P['INIT_STOP_ATR']} ATR, fixed until partial)"
        )

    # --- 2. Offene Positionen überwachen (Regeln aus tjl_rules.py, Yahoo 1-Min) ---
    for sym, pos in positions.items():
        if pos["status"] != "open":
            continue
        entry, atr = pos["entry_price"], pos["atr"]
        try:
            day = [b for b in R.df_to_bars(R.load_intraday(sym, period="1d", interval="1m"))
                   if datetime.fromtimestamp(b["t"], ET).date() == now_et.date()]
        except Exception:
            day = []
        rth = [b for b in day if R.RTH_OPEN <= datetime.fromtimestamp(b["t"], ET).time()]
        tr = R.replay_exits(entry, atr, rth, pos["entry_ts"])
        pos["high_water"] = round(tr.high, 2)
        pos["current_stop"] = round(tr.stop, 2)
        last_px = rth[-1]["close"] if rth else entry
        pos["last_price"] = round(last_px, 2)

        if tr.partial_done and not pos["partial_alerted"]:
            pos["partial_alerted"] = True
            alerts.append(
                f"🟡 <b>{sym} — Partial profit target hit</b> @ ${round(tr.target,2)}\n"
                f"   Strategy: sell {R.PARAMS['PARTIAL_PCT']}%, stop now trails {R.PARAMS['TRAIL_ATR']} ATR (min. entry ${entry})"
            )
        if tr.vwap_break_ts and not pos.get("vwap_break_alerted"):
            pos["vwap_break_alerted"] = True
            pos["vwap_break_ts"] = tr.vwap_break_ts
            if not tr.closed:
                alerts.append(
                    f"🟣 <b>{sym} — 5-min close below VWAP</b> ({fmt_et(tr.vwap_break_ts)})\n"
                    f"   <i>Beobachtung — kein automatischer Exit (VWAP_EXIT_MODE=observe)</i>"
                )

        if tr.closed or is_eod:
            if not tr.closed:
                tr.close_eod(last_px, now_et.timestamp())
            pnl = round(tr.pnl_pct(), 2)
            pos.update(status="closed", exit_price=round(tr.exit_price, 2),
                       exit_reason=tr.exit_reason, exit_ts=tr.exit_ts, pnl_pct=pnl)
            icon = {"eod": "🟠"}.get(tr.exit_reason, "🔴")
            alerts.append(
                f"{icon} <b>{sym} — Exit: {tr.exit_reason}</b> @ ${pos['exit_price']} ({fmt_et(tr.exit_ts)})\n"
                f"   Strategy: close remaining position\n"
                f"   P&L incl. partial: <b>{'+' if pnl >= 0 else ''}{pnl}%</b> (high was ${pos['high_water']})"
            )
        else:
            pos["pnl_pct"] = round(tr.pnl_pct(last_px), 2)

    # MCP-Verbindung schließen
    if mcp:
        mcp.close()

    # Zustand speichern
    with open(state_path, "w") as f:
        json.dump(positions, f, indent=2)

    # Alerts senden
    open_count = sum(1 for p in positions.values() if p["status"] == "open")
    print(f"  Positions: {len(positions)} total, {open_count} open, {len(alerts)} alert(s)")
    for a in alerts:
        print("  ---")
        print("  " + a.replace("\n", "\n  "))
        send_telegram(a)


if __name__ == "__main__":
    main()
