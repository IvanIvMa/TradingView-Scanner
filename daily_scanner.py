#!/usr/bin/env python3
"""
Daily Scanner v4 — Python rewrite of daily_scanner.sh

Data source priority:
  1. TradingView MCP (live via Chrome DevTools Protocol) — primary
  2. Yahoo Finance yfinance — fallback

Flow:
  1. Yahoo Screener API → Top 100 day gainers (universe, can't be replaced by MCP)
  2. For each ticker: get price/volume data (TV MCP first, yfinance fallback)
  3. Premarket calculation: prev_close, PM window 4:00-9:30 ET, regular 9:30-16:00 ET
  4. Filters: gap>5%, price>$3, premarket_volume>50K, TOP_N=10
  5. ISIN mapping, float shares, news catalyst
  6. Telegram report

Usage:
  python3 daily_scanner.py              # normal premarket run
  python3 daily_scanner.py --merge      # append new tickers after market open
  python3 daily_scanner.py --force      # bypass DST time gate
"""

import sys, os, json, time, select, subprocess, shutil, urllib.request, urllib.parse
from datetime import datetime
from zoneinfo import ZoneInfo
from xml.etree import ElementTree

import yfinance as yf
import pandas as pd

ET = ZoneInfo("America/New_York")
BERLIN = ZoneInfo("Europe/Berlin")
HERE = os.path.dirname(os.path.abspath(__file__))
MCP_SERVER = "/Users/ivan/tradingview-mcp/src/server.js"

MIN_GAP = 5.0
MIN_PRICE = 3.0
MIN_VOLUME = 50_000
TOP_N = 10
CHUNK = 25


# =============================================================================
# MCP Client (same pattern as position_tracker.py / mcp_scanner_b.py)
# =============================================================================
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
                                 "clientInfo": {"name": "daily-scanner", "version": "4.0"}})
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
    if not os.path.exists(MCP_SERVER):
        return None
    try:
        mcp = MCPClient(MCP_SERVER)
        mcp.handshake()
        health = mcp.tool("tv_health_check")
        if health and health.get("cdp_connected"):
            log(f"TradingView connected (chart: {health.get('chart_symbol', '?')})")
            return mcp
        mcp.close()
    except Exception as e:
        log(f"MCP connection failed: {str(e)[:60]}")
    return None


def parse_de_number(s):
    if not s:
        return None
    try:
        return float(str(s).replace(".", "").replace(",", "."))
    except (ValueError, AttributeError):
        return None


# =============================================================================
# Helpers
# =============================================================================
def log(msg):
    ts = datetime.now(ET).strftime("%H:%M:%S ET")
    print(f"[daily_scanner {ts}] {msg}", flush=True)


def load_env():
    env_path = os.path.join(HERE, ".env")
    if not os.path.exists(env_path):
        print("ERROR: .env file not found", file=sys.stderr)
        sys.exit(1)
    env = {}
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    if not env.get("TELEGRAM_BOT_TOKEN") or not env.get("TELEGRAM_CHAT_ID"):
        print("ERROR: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set in .env", file=sys.stderr)
        sys.exit(1)
    return env


def send_telegram(env, msg):
    if not msg:
        return
    payload = json.dumps({
        "chat_id": int(env["TELEGRAM_CHAT_ID"]),
        "text": msg,
        "parse_mode": "HTML",
    }).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{env['TELEGRAM_BOT_TOKEN']}/sendMessage",
        data=payload,
        headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        log(f"Telegram send failed: {e}")


def fetch_catalyst(symbol):
    url = f"https://news.google.com/rss/search?q={urllib.parse.quote(symbol)}+stock&hl=en-US&gl=US&ceid=US:en"
    try:
        data = urllib.request.urlopen(url, timeout=10).read()
        root = ElementTree.fromstring(data)
        for item in root.iter("item"):
            title = item.findtext("title", "")
            if title and "Google News" not in title:
                return title
    except Exception:
        pass
    return ""


def fetch_yahoo_screener():
    url = "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved?scrIds=day_gainers&count=100"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        data = urllib.request.urlopen(req, timeout=15).read()
        return json.loads(data)
    except Exception as e:
        log(f"Yahoo Screener fetch failed: {e}")
        return {}


# =============================================================================
# DST-robust ET time gate
# =============================================================================
def check_time_gate(merge, force):
    if force:
        return True
    now = datetime.now(ET)
    mins = now.hour * 60 + now.minute
    if merge:
        ok = (9 * 60 + 30) <= mins <= (10 * 60 + 29)
    else:
        ok = (8 * 60 + 30) <= mins <= (9 * 60 + 29)
    if not ok:
        log(f"DST gate: {now.strftime('%H:%M')} ET outside target window — skipping (use --force to override)")
    return ok


# =============================================================================
# Data fetching: TradingView MCP (primary) or yfinance (fallback)
# =============================================================================
def fetch_data_mcp(mcp, tickers, today_et):
    """Fetch 1-min bars per ticker via TradingView MCP. Returns dict {sym: DataFrame}."""
    frames = {}
    for sym in tickers:
        try:
            mcp.tool("chart_set_symbol", {"symbol": sym})
            mcp.tool("chart_set_timeframe", {"timeframe": "1"})
            time.sleep(0.3)
            ohlcv = mcp.tool("data_get_ohlcv", {"count": 500, "summary": False}, timeout=30)
            bars = (ohlcv or {}).get("bars", [])
            if not bars:
                continue
            rows = []
            for b in bars:
                t = b.get("t") or b.get("time")
                if t is None:
                    continue
                o = parse_de_number(b.get("open")) or b.get("open")
                h = parse_de_number(b.get("high")) or b.get("high")
                lo = parse_de_number(b.get("low")) or b.get("low")
                c = parse_de_number(b.get("close")) or b.get("close")
                v = b.get("volume", 0)
                if isinstance(v, str):
                    v = parse_de_number(v) or 0
                rows.append({"time": t, "Open": float(o), "High": float(h),
                             "Low": float(lo), "Close": float(c), "Volume": int(v)})
            if rows:
                df = pd.DataFrame(rows)
                df.index = pd.to_datetime(df["time"], unit="s", utc=True).dt.tz_convert(ET)
                df = df.drop(columns=["time"])
                frames[sym] = df
        except Exception as e:
            log(f"  MCP {sym}: {str(e)[:50]}")
    return frames


def fetch_data_yfinance(tickers):
    """Batch download 1-min bars via yfinance (chunks of 25). Returns dict {sym: DataFrame}."""
    chunks = [tickers[i:i + CHUNK] for i in range(0, len(tickers), CHUNK)]
    frames = {}
    for chunk in chunks:
        d = yf.download(chunk, period="2d", interval="1m", prepost=True,
                        progress=False, group_by="ticker", threads=True, auto_adjust=False)
        if len(chunk) == 1:
            frames[chunk[0]] = d
        else:
            for sym in chunk:
                if sym in d.columns.get_level_values(0):
                    frames[sym] = d[sym]
    return frames


# =============================================================================
# Main logic
# =============================================================================
def main():
    args = sys.argv[1:]
    merge = "--merge" in args
    force = "--force" in args

    env = load_env()

    if not check_time_gate(merge, force):
        return

    now_et = datetime.now(ET)
    today_et = now_et.date()
    date_str = datetime.now(BERLIN).strftime("%Y-%m-%d")
    outfile = os.path.join(HERE, f"premarket_gappers_{date_str}.json")
    log_file = os.path.join(HERE, f"daily_scanner_{date_str}.log")

    mode_str = "MERGE" if merge else "PREMARKET"
    log(f"=== Daily Scanner v4 ({mode_str}) — {date_str} ===")

    # Load existing gappers in merge mode
    existing_symbols = set()
    existing_gappers = []
    if merge and os.path.exists(outfile):
        with open(outfile) as f:
            prev = json.load(f)
        existing_gappers = prev.get("gappers", [])
        existing_symbols = {g["symbol"] for g in existing_gappers}
        log(f"MERGE mode: {len(existing_symbols)} existing gappers preserved")

    # Step 1: Yahoo Screener → universe
    log("--- Step 1: Yahoo Screener (Top 100 Gainers) ---")
    yahoo_data = fetch_yahoo_screener()
    yahoo_quotes = yahoo_data.get("finance", {}).get("result", [{}])[0].get("quotes", [])
    log(f"Yahoo Screener: {len(yahoo_quotes)} top gainers loaded")

    yahoo_pct_map = {}
    yahoo_name_map = {}
    tickers = []
    for q in yahoo_quotes:
        sym = q.get("symbol")
        if not sym or any(c in sym for c in ["=", "^", "-"]):
            continue
        tickers.append(sym)
        yahoo_pct_map[sym] = float(q.get("regularMarketChangePercent") or 0)
        yahoo_name_map[sym] = q.get("shortName") or q.get("longName") or ""

    # In merge mode: backfill names for existing gappers
    if merge and existing_gappers:
        missing = [g["symbol"] for g in existing_gappers
                   if not g.get("name") and g["symbol"] not in yahoo_name_map]
        for ms in missing:
            try:
                n = (yf.Ticker(ms).info or {}).get("shortName") or ""
                if n:
                    yahoo_name_map[ms] = n
            except Exception:
                pass
        for g in existing_gappers:
            if not g.get("name") and g["symbol"] in yahoo_name_map:
                g["name"] = yahoo_name_map[g["symbol"]]

    log(f"{len(tickers)} stock tickers (excluding FX/crypto/indices)")

    if merge:
        new_tickers = [t for t in tickers if t not in existing_symbols]
        log(f"New tickers (not in premarket run): {len(new_tickers)}")
        if not new_tickers:
            log("No new tickers — nothing to do.")
            return
        tickers = new_tickers

    # Step 2: Fetch price data (TradingView MCP primary, yfinance fallback)
    log("--- Step 2: Price data ---")
    mcp = try_connect_mcp()
    data_source = "yfinance"

    if mcp:
        log(f"Fetching 1-min bars from TradingView MCP for {len(tickers)} tickers...")
        data = fetch_data_mcp(mcp, tickers, today_et)
        mcp.close()
        if len(data) >= len(tickers) * 0.5:
            data_source = "TradingView MCP"
            log(f"TradingView: got data for {len(data)}/{len(tickers)} tickers")
        else:
            log(f"TradingView only got {len(data)}/{len(tickers)} — supplementing with yfinance")
            missing_tickers = [t for t in tickers if t not in data]
            if missing_tickers:
                yf_data = fetch_data_yfinance(missing_tickers)
                data.update(yf_data)
            data_source = "TradingView MCP + yfinance"
    else:
        log("TradingView not available — using yfinance batch download")
        log(f"Downloading 1-min bars for {len(tickers)} tickers (~30 sec)...")
        data = fetch_data_yfinance(tickers)

    # Step 3: Premarket calculation
    log("--- Step 3: Premarket calculation ---")

    # ISIN mapping
    isin_path = os.path.join(HERE, "ticker_isin.json")
    try:
        with open(isin_path) as f:
            isin_map = json.load(f)
    except FileNotFoundError:
        isin_map = {}

    new_isins = 0
    for sym in tickers:
        if sym not in isin_map or not isin_map.get(sym):
            try:
                isin = yf.Ticker(sym).isin
                if isin and isin not in ("-", "N/A"):
                    isin_map[sym] = isin
                    new_isins += 1
                else:
                    isin_map[sym] = None
            except Exception:
                isin_map[sym] = None
    if new_isins:
        with open(isin_path, "w") as f:
            json.dump(isin_map, f, indent=2)
        log(f"{new_isins} new ISINs loaded")

    is_premarket_window = (now_et.hour < 9) or (now_et.hour == 9 and now_et.minute < 30)

    results = []
    for sym in tickers:
        try:
            df = data.get(sym)
            if df is None:
                continue
            df = df.dropna()
            if df.empty:
                continue
            if df.index.tz is None:
                df.index = df.index.tz_localize("UTC").tz_convert(ET)
            elif str(df.index.tz) != str(ET):
                df.index = df.index.tz_convert(ET)

            yesterday = df[df.index.date < today_et]
            reg_yesterday = yesterday[yesterday.index.hour < 16]
            if reg_yesterday.empty:
                continue
            prev_close = float(reg_yesterday["Close"].iloc[-1])

            today_bars = df[df.index.date == today_et]
            premarket = today_bars[
                (today_bars.index.hour >= 4) &
                ((today_bars.index.hour < 9) | ((today_bars.index.hour == 9) & (today_bars.index.minute < 30)))
            ]
            regular = today_bars[
                ((today_bars.index.hour > 9) | ((today_bars.index.hour == 9) & (today_bars.index.minute >= 30))) &
                (today_bars.index.hour < 16)
            ]

            pm_price = pm_volume = pm_time = None
            if not premarket.empty:
                pm_price = float(premarket["Close"].iloc[-1])
                pm_volume = int(premarket["Volume"].sum())
                pm_time = premarket.index[-1].strftime("%H:%M ET")

            intraday_price = intraday_time = intraday_volume = None
            if not regular.empty:
                intraday_price = float(regular["Close"].iloc[-1])
                intraday_time = regular.index[-1].strftime("%H:%M ET")
                intraday_volume = int(regular["Volume"].sum())

            pm_gap = round((pm_price - prev_close) / prev_close * 100, 2) if pm_price else None
            intraday_gap = round((intraday_price - prev_close) / prev_close * 100, 2) if intraday_price else None
            yahoo_gap = round(yahoo_pct_map.get(sym, 0), 2)

            float_shares = None
            try:
                info = yf.Ticker(sym).info or {}
                float_shares = info.get("floatShares")
            except Exception:
                pass

            results.append({
                "symbol": sym,
                "name": yahoo_name_map.get(sym, ""),
                "isin": isin_map.get(sym),
                "prev_close": round(prev_close, 2),
                "premarket_price": round(pm_price, 2) if pm_price else None,
                "premarket_volume": pm_volume,
                "premarket_time": pm_time,
                "premarket_gap_pct": pm_gap,
                "intraday_price": round(intraday_price, 2) if intraday_price else None,
                "intraday_time": intraday_time,
                "intraday_gap_pct": intraday_gap,
                "intraday_volume": intraday_volume,
                "yahoo_displayed_gap_pct": yahoo_gap,
                "float_shares": float_shares,
            })
        except Exception as e:
            log(f"  ! {sym}: {e}")

    # Step 4: Filter
    log("--- Step 4: Filtering ---")

    def get_effective_gap(r):
        return r["premarket_gap_pct"] if r["premarket_gap_pct"] is not None else r["intraday_gap_pct"]

    def get_effective_price(r):
        return r["premarket_price"] or r["intraday_price"] or r["prev_close"]

    filtered = []
    for r in results:
        gap = get_effective_gap(r)
        price = get_effective_price(r)
        if gap is None or price is None:
            continue
        if gap <= MIN_GAP or price <= MIN_PRICE:
            continue
        pm_vol = r["premarket_volume"] or 0
        if r["premarket_gap_pct"] is not None and pm_vol > MIN_VOLUME:
            r["filter_mode"] = "premarket"
        elif r["premarket_gap_pct"] is not None:
            r["filter_mode"] = "premarket_lowvol"
        elif is_premarket_window:
            continue
        else:
            r["filter_mode"] = "intraday"
        filtered.append(r)

    filtered.sort(key=lambda r: get_effective_gap(r), reverse=True)
    filtered = filtered[:TOP_N]

    if merge and existing_gappers:
        merged = existing_gappers + filtered
        merged.sort(key=lambda r: get_effective_gap(r) or 0, reverse=True)
        merged = merged[:TOP_N]
        new_count = len(filtered)
    else:
        merged = filtered
        new_count = len(filtered)

    for i, r in enumerate(merged, 1):
        r["rank"] = i

    universe_src = f"Yahoo Screener day_gainers (Top 100) — data: {data_source}"
    if merge:
        universe_src += " — MERGE (post-open update)"

    result_obj = {
        "scanned_at": datetime.now(BERLIN).isoformat(),
        "scan_time_et": datetime.now(ET).strftime("%H:%M ET"),
        "universe_source": universe_src,
        "universe_size": len(tickers) + len(existing_symbols),
        "data_source": data_source,
        "filters": {
            "min_gap_pct": MIN_GAP,
            "min_price": MIN_PRICE,
            "min_premarket_volume": MIN_VOLUME,
            "top_n": TOP_N,
        },
        "gappers": merged,
    }
    if merge:
        result_obj["merge_new_gappers"] = new_count

    with open(outfile, "w") as f:
        json.dump(result_obj, f, indent=2)

    if merge:
        log(f"{new_count} NEW gappers found, {len(merged)} total after merge:")
    else:
        log(f"{len(merged)} gappers after filter:")
    for r in merged:
        pm = r.get("premarket_gap_pct")
        yh = r.get("yahoo_displayed_gap_pct", 0)
        mode = r.get("filter_mode", "?")
        is_new = merge and r["symbol"] not in existing_symbols
        marker = " NEW" if is_new else ""
        if pm is not None:
            log(f"  {r['rank']}. {r['symbol']:6s} PM: {pm:+.2f}%  Yahoo: {yh:+.2f}%  [{mode}]{marker}")
        else:
            intra = r.get("intraday_gap_pct", 0)
            log(f"  {r['rank']}. {r['symbol']:6s} Intraday: {intra:+.2f}% (no PM)  [{mode}]{marker}")

    # Step 5: News catalyst
    log("--- Step 5: News catalysts (Google News RSS) ---")
    for g in merged:
        if not g.get("catalyst"):
            cat = fetch_catalyst(g["symbol"])
            if cat:
                log(f"  {g['symbol']}: {cat[:60]}")
            else:
                log(f"  {g['symbol']}: (no catalyst found)")
            g["catalyst"] = cat if cat else None
            g["catalyst_source"] = "Google News RSS"

    with open(outfile, "w") as f:
        json.dump(result_obj, f, indent=2)

    # Step 6: Telegram report
    log("--- Step 6: Telegram report ---")
    msg = build_telegram_message(result_obj, merge, existing_symbols)
    if msg:
        send_telegram(env, msg)
        log("Telegram sent!")
    else:
        log("Merge: no new gappers — no Telegram.")

    # Write log
    with open(log_file, "a" if merge else "w") as f:
        f.write(f"=== Daily Scanner v4 ({mode_str}) — {date_str} ===\n")
        f.write(f"Data source: {data_source}\n")
        f.write(f"Tickers checked: {len(tickers)}\n")
        f.write(f"Gappers after filter: {len(merged)}\n")
        for r in merged:
            gap = get_effective_gap(r) or 0
            f.write(f"  {r['rank']}. {r['symbol']} {gap:+.2f}%\n")

    log(f"=== Daily Scanner v4 done ({data_source}) ===")


def build_telegram_message(data, merge, existing_symbols):
    now_str = datetime.now(BERLIN).strftime("%d.%m.%Y %H:%M")
    gappers = data.get("gappers", [])
    new_count = data.get("merge_new_gappers", 0)

    if merge and new_count == 0:
        return ""

    lines = []
    if merge:
        lines.append(f"\U0001f504 <b>Scanner A UPDATE — {now_str} CEST</b>")
        lines.append(f"<i>{new_count} new gappers discovered after market open!</i>\n")
    else:
        lines.append(f"\U0001f4ca <b>Daily Premarket Report — {now_str} CEST</b>")
        src = data.get("data_source", "yfinance")
        lines.append(f"<i>Universe: {data.get('universe_size', '?')} stocks (Yahoo Top Gainers) | Data: {src}</i>\n")

    if gappers:
        has_pm = any(g.get("premarket_gap_pct") is not None for g in gappers)
        if not merge:
            if has_pm:
                lines.append(f"<b>{len(gappers)} gappers found:</b>")
            else:
                lines.append(f"<b>{len(gappers)} gappers (market open — intraday data):</b>")
        else:
            lines.append(f"<b>Updated list ({len(gappers)} gappers):</b>")
        lines.append("")

        for g in gappers:
            sym = g["symbol"]
            name = g.get("name") or ""
            isin = g.get("isin") or "—"
            isin_part = f" ({isin})" if isin != "—" else ""
            name_part = f" — {name}" if name else ""
            pm = g.get("premarket_gap_pct")
            yh = g.get("yahoo_displayed_gap_pct", 0)
            intra = g.get("intraday_gap_pct")
            pm_time = g.get("premarket_time")
            pm_vol = g.get("premarket_volume") or 0
            price = g.get("premarket_price") or g.get("intraday_price") or g.get("prev_close")

            float_s = g.get("float_shares")
            if float_s:
                if float_s >= 1_000_000_000:
                    float_str = f"{float_s / 1_000_000_000:.1f}B"
                elif float_s >= 1_000_000:
                    float_str = f"{float_s / 1_000_000:.1f}M"
                else:
                    float_str = f"{float_s / 1000:.0f}K"
            else:
                float_str = ""

            if pm_vol > 1_000_000:
                vol_str = f"{pm_vol / 1_000_000:.1f}M"
            elif pm_vol > 1000:
                vol_str = f"{pm_vol / 1000:.0f}K"
            else:
                vol_str = str(pm_vol) if pm_vol > 0 else ""

            new_marker = " \U0001f195" if (merge and sym not in existing_symbols) else ""

            if pm is not None:
                diff = pm - yh
                diff_str = f" (Yahoo: {yh:+.2f}%, Δ {diff:+.2f}pp)" if abs(diff) > 0.5 else ""
                lines.append(f"<b>{g['rank']}. {sym}</b>{name_part}{isin_part}{new_marker}")
                extras = []
                if vol_str:
                    extras.append(f"Vol: {vol_str}")
                if float_str:
                    extras.append(f"Float: {float_str}")
                extra_line = f"   {' | '.join(extras)}" if extras else ""
                lines.append(f"   Premarket: <b>{pm:+.2f}%</b> ${price:.2f} @ {pm_time}{diff_str}")
                if extra_line:
                    lines.append(extra_line)
            else:
                lines.append(f"<b>{g['rank']}. {sym}</b>{name_part}{isin_part}{new_marker}")
                extras = []
                if float_str:
                    extras.append(f"Float: {float_str}")
                intra_vol = g.get("intraday_volume") or 0
                if intra_vol > 1_000_000:
                    extras.append(f"Vol: {intra_vol / 1_000_000:.1f}M")
                elif intra_vol > 1000:
                    extras.append(f"Vol: {intra_vol / 1000:.0f}K")
                extra_line = f"   {' | '.join(extras)}" if extras else ""
                lines.append(f"   Intraday: <b>{intra:+.2f}%</b> ${price:.2f}")
                if extra_line:
                    lines.append(extra_line)

            cat = g.get("catalyst")
            benz = g.get("catalyst_benzinga")
            if benz:
                lines.append(f"   \U0001f4f0 <i>{benz[:75]}</i> <b>[Benzinga]</b>")
            elif cat:
                lines.append(f"   \U0001f4f0 <i>{cat[:75]}</i>")
            lines.append("")
    else:
        lines.append("No gappers after filter (gap>5%, price>$3)")

    if merge:
        lines.append(f"\n<i>Post-open update: Yahoo screener refreshed after market open</i>")
    else:
        lines.append(f"\n<i>Premarket calculated (4:00-9:30 ET) | Universe: Yahoo Top 100</i>")
        lines.append(f"<i>TJL signals follow at 10:00 ET (Scanner B, at market open)</i>")

    return "\n".join(lines)


if __name__ == "__main__":
    main()
