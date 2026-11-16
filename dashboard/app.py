#!/usr/bin/env python3
"""
TJL Scanner — Cockpit (lokales Web-Dashboard)

Liest nur die Dateien, die Scanner A/B und der Position Tracker schreiben
(premarket_gappers_*, tjl_watchlist_*, positions_*, Logs, backtest_results.json)
und zeigt sie an. Löst selbst KEINE Signale und keine Telegram-Nachrichten aus.

Start:   cd dashboard && python3 app.py      -> http://localhost:8050
"""
import glob, json, os, sys, urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
import tjl_rules as R  # noqa: E402

ET = ZoneInfo("America/New_York")
BERLIN = ZoneInfo("Europe/Berlin")
STATIC = Path(__file__).parent / "static"

app = FastAPI(title="TJL Cockpit")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


def today():
    return datetime.now(BERLIN).strftime("%Y-%m-%d")


def load(path):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def tail(path, n=40):
    try:
        with open(path, errors="replace") as f:
            return f.read().splitlines()[-n:]
    except Exception:
        return []


def mtime_berlin(path):
    try:
        return datetime.fromtimestamp(os.path.getmtime(path), BERLIN)
    except Exception:
        return None


def latest_watchlist(day):
    files = sorted(glob.glob(str(BASE / f"tjl_watchlist_{day}_*.json")))
    return (files[-1], load(files[-1])) if files else (None, None)


@app.get("/")
async def root():
    return FileResponse(STATIC / "cockpit.html")


@app.get("/api/health")
async def health():
    """Läuft alles? Genau das, was beim Ausfall Aug–Nov gefehlt hat."""
    day, now_et = today(), datetime.now(ET)
    in_window = now_et.weekday() < 5 and (10, 0) <= (now_et.hour, now_et.minute) <= (15, 45)

    g = load(BASE / f"premarket_gappers_{day}.json")
    scanner_a = {"ok": g is not None, "time": g.get("scan_time_et") if g else None,
                 "count": len(g.get("gappers", [])) if g else 0}

    wfile, _ = latest_watchlist(day)
    wt = mtime_berlin(wfile) if wfile else None
    age_min = (datetime.now(BERLIN) - wt).total_seconds() / 60 if wt else None
    stderr = BASE / "launchd_tjl_stderr.log"
    err_lines = [l for l in tail(stderr, 30) if "Error" in l or "Traceback" in l]
    st = mtime_berlin(stderr)
    err_recent = bool(err_lines) and st is not None and st.date() == datetime.now(BERLIN).date() \
        and (wt is None or st > wt)
    if in_window and g and g.get("gappers"):
        b_ok = age_min is not None and age_min <= 40 and not err_recent
    else:
        b_ok = not err_recent
    scanner_b = {"ok": b_ok, "last_run": wt.strftime("%H:%M") if wt else None,
                 "age_min": round(age_min) if age_min is not None else None,
                 "error": err_lines[-1] if err_recent else None, "in_window": in_window}

    try:
        urllib.request.urlopen("http://localhost:9222/json/version", timeout=1)
        tv = True
    except Exception:
        tv = False

    return {"time_et": now_et.strftime("%H:%M:%S"), "time_berlin": datetime.now(BERLIN).strftime("%H:%M:%S"),
            "date": day, "market_open": now_et.weekday() < 5 and (9, 30) <= (now_et.hour, now_et.minute) < (16, 0),
            "scanner_a": scanner_a, "scanner_b": scanner_b, "tradingview_cdp": tv,
            "log_tail": tail(BASE / f"tjl_scanner_{day}.log", 25)}


@app.get("/api/today")
async def today_view():
    day = today()
    g = load(BASE / f"premarket_gappers_{day}.json") or {}
    _, w = latest_watchlist(day)
    results = {r["symbol"]: r for r in (w or {}).get("all_results", [])}
    hits = {h["symbol"]: h for h in (w or {}).get("hits", [])}
    rows = []
    for gp in g.get("gappers", []):
        s = gp["symbol"]
        r = results.get(s, {})
        rows.append({"symbol": s, "name": gp.get("name"),
                     "gap": gp.get("premarket_gap_pct") or gp.get("intraday_gap_pct"),
                     "price": gp.get("premarket_price") or gp.get("intraday_price"),
                     "catalyst": gp.get("catalyst"), "result": r.get("result", "—"),
                     "filters": r.get("filters"), "hit": hits.get(s)})
    return {"date": day, "scan_time": (w or {}).get("scan_time_et"), "rows": rows}


@app.get("/api/positions")
async def positions():
    data = load(BASE / f"positions_{today()}.json") or {}
    return {"positions": list(data.values())}


@app.get("/api/performance")
async def performance():
    trades = []
    for f in sorted(glob.glob(str(BASE / "positions_*.json"))):
        day = os.path.basename(f)[10:20]
        for p in (load(f) or {}).values():
            if p.get("status") != "closed" or not p.get("exit_price"):
                continue
            pnl = p.get("pnl_pct")
            new_rules = pnl is not None
            if pnl is None:
                pnl = (p["exit_price"] - p["entry_price"]) / p["entry_price"] * 100
            trades.append({"date": day, "symbol": p["symbol"], "entry_et": p.get("entry_et"),
                           "entry": p["entry_price"], "exit": p["exit_price"],
                           "reason": p.get("exit_reason"), "pnl_pct": round(pnl, 2),
                           "rules": "neu (ATR)" if new_rules else "alt (2 %)"})
    eq, curve = 100.0, []
    for t in trades:
        eq *= 1 + t["pnl_pct"] / 100
        curve.append({"date": t["date"], "symbol": t["symbol"], "equity": round(eq, 2)})

    def summary(ts):
        if not ts:
            return {"n": 0}
        w = [t for t in ts if t["pnl_pct"] > 0]
        return {"n": len(ts), "win_pct": round(len(w) / len(ts) * 100, 1),
                "avg_pct": round(sum(t["pnl_pct"] for t in ts) / len(ts), 2)}
    return {"trades": trades[::-1], "curve": curve,
            "old": summary([t for t in trades if t["rules"].startswith("alt")]),
            "new": summary([t for t in trades if t["rules"].startswith("neu")])}


@app.get("/api/backtest")
async def backtest():
    return load(BASE / "backtest_results.json") or {"table": [], "trades": []}


@app.get("/api/rules")
async def rules():
    return R.PARAMS


@app.get("/api/chart/{symbol}")
async def chart(symbol: str, interval: str = "1m"):
    """Kerzen des letzten Handelstags + VWAP + Marker aus positions_<heute>.json."""
    sym = symbol.upper()
    try:
        bars = R.df_to_bars(R.load_intraday(sym, period="1d" if interval == "1m" else "5d", interval=interval))
    except Exception as e:
        return {"symbol": sym, "bars": [], "error": str(e)}
    if not bars:
        return {"symbol": sym, "bars": []}
    last_day = datetime.fromtimestamp(bars[-1]["t"], ET).date()
    bars = [b for b in bars if datetime.fromtimestamp(b["t"], ET).date() == last_day]
    rth = [b for b in bars if R.RTH_OPEN <= datetime.fromtimestamp(b["t"], ET).time() < R.dtime(16)]
    vw = R.vwap_series(rth)
    pos = (load(BASE / f"positions_{today()}.json") or {}).get(sym)
    markers, lines = [], []
    if pos:
        markers.append({"t": pos["entry_ts"], "kind": "entry", "price": pos["entry_price"]})
        if pos.get("vwap_break_ts"):
            markers.append({"t": pos["vwap_break_ts"], "kind": "vwap_break"})
        if pos.get("exit_ts"):
            markers.append({"t": pos["exit_ts"], "kind": "exit", "price": pos.get("exit_price"),
                            "reason": pos.get("exit_reason")})
        P = R.PARAMS
        lines = [{"label": "Einstieg", "price": pos["entry_price"]},
                 {"label": "Ziel", "price": round(pos["entry_price"] + pos["atr"] * P["PARTIAL_ATR"], 2)},
                 {"label": "Stop", "price": pos.get("current_stop",
                                                    round(pos["entry_price"] - pos["atr"] * P["INIT_STOP_ATR"], 2))}]
    return {"symbol": sym,
            "bars": [{"time": int(b["t"]), "open": b["open"], "high": b["high"], "low": b["low"],
                      "close": b["close"], "volume": b["volume"]} for b in bars],
            "vwap": [{"time": int(b["t"]), "value": round(v, 3)} for b, v in zip(rth, vw)],
            "markers": markers, "lines": lines}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8050)
