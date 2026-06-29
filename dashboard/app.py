#!/usr/bin/env python3
"""
TJL Scanner — Trading Cockpit (Web Dashboard)

FastAPI backend serving the dashboard UI and JSON APIs.
Reads scanner output files (premarket_gappers, tjl_watchlist, positions)
and exposes them as live endpoints.

Start:  cd dashboard && uvicorn app:app --reload --port 8050
"""

import os, json, glob
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
import yfinance as yf

ET = ZoneInfo("America/New_York")
BERLIN = ZoneInfo("Europe/Berlin")
BASE = Path(__file__).resolve().parent.parent

app = FastAPI(title="TJL Scanner Cockpit")
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")

DEFAULTS = {
    "PARTIAL_ATR": 1.0,
    "PARTIAL_PCT": 50,
    "TRAIL_PCT": 2.0,
    "ATR_PERIOD": 14,
    "EOD_HOUR_ET": 15,
    "EOD_MIN_ET": 45,
}


def today_str():
    return datetime.now(BERLIN).strftime("%Y-%m-%d")


def load_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


@app.get("/", response_class=HTMLResponse)
async def root():
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@app.get("/api/status")
async def api_status():
    now_et = datetime.now(ET)
    market_open = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
    is_open = market_open <= now_et <= market_close and now_et.weekday() < 5
    return {
        "time_et": now_et.strftime("%H:%M:%S ET"),
        "time_berlin": datetime.now(BERLIN).strftime("%H:%M:%S"),
        "date": today_str(),
        "market_open": is_open,
        "weekday": now_et.strftime("%A"),
    }


@app.get("/api/gappers")
async def api_gappers():
    today = today_str()
    path = BASE / f"premarket_gappers_{today}.json"
    data = load_json(path)
    if not data:
        return {"date": today, "gappers": [], "count": 0}
    gappers = data.get("gappers", [])
    return {"date": today, "gappers": gappers, "count": len(gappers)}


@app.get("/api/signals")
async def api_signals():
    today = today_str()
    files = sorted(glob.glob(str(BASE / f"tjl_watchlist_{today}_*.json")), reverse=True)
    if not files:
        return {"date": today, "passes": [], "fails": [], "scan_time": None}
    data = load_json(files[0])
    if not data:
        return {"date": today, "passes": [], "fails": [], "scan_time": None}
    passes = [h for h in data.get("hits", []) if h.get("result") == "PASS"]
    fails = [h for h in data.get("hits", []) if h.get("result") != "PASS"]
    scan_time = data.get("scan_time") or os.path.basename(files[0]).replace(f"tjl_watchlist_{today}_", "").replace(".json", "")
    return {"date": today, "passes": passes, "fails": fails, "scan_time": scan_time}


@app.get("/api/positions")
async def api_positions():
    today = today_str()
    path = BASE / f"positions_{today}.json"
    data = load_json(path)
    if not data:
        return {"date": today, "positions": [], "open_count": 0, "closed_count": 0}
    positions = list(data.values()) if isinstance(data, dict) else data
    open_pos = [p for p in positions if p.get("status") == "open"]
    closed_pos = [p for p in positions if p.get("status") == "closed"]
    return {
        "date": today,
        "positions": positions,
        "open_count": len(open_pos),
        "closed_count": len(closed_pos),
    }


@app.get("/api/regime")
async def api_regime():
    try:
        spy_hist = yf.Ticker("SPY").history(period="1y", interval="1d")
        qqq_hist = yf.Ticker("QQQ").history(period="1y", interval="1d")
        if spy_hist.empty or qqq_hist.empty:
            return {"regime": "unknown", "error": "Keine Daten von Yahoo Finance",
                    "spy": {"close": 0, "sma200": 0, "above": False},
                    "qqq": {"close": 0, "sma200": 0, "above": False}}
        spy_close = round(float(spy_hist["Close"].iloc[-1]), 2)
        qqq_close = round(float(qqq_hist["Close"].iloc[-1]), 2)
        spy_sma200 = round(float(spy_hist["Close"].tail(200).mean()), 2)
        qqq_sma200 = round(float(qqq_hist["Close"].tail(200).mean()), 2)
        spy_above = spy_close > spy_sma200
        qqq_above = qqq_close > qqq_sma200
        if spy_above and qqq_above:
            regime = "tailwind"
        elif spy_above or qqq_above:
            regime = "mixed"
        else:
            regime = "headwind"
        return {
            "regime": regime,
            "spy": {"close": spy_close, "sma200": spy_sma200, "above": spy_above},
            "qqq": {"close": qqq_close, "sma200": qqq_sma200, "above": qqq_above},
        }
    except Exception as e:
        return {"regime": "unknown", "error": str(e),
                "spy": {"close": 0, "sma200": 0, "above": False},
                "qqq": {"close": 0, "sma200": 0, "above": False}}


@app.get("/api/history")
async def api_history():
    """Recent position files for historical view."""
    files = sorted(glob.glob(str(BASE / "positions_*.json")), reverse=True)[:10]
    history = []
    for f in files:
        date = os.path.basename(f).replace("positions_", "").replace(".json", "")
        data = load_json(f)
        if not data:
            continue
        positions = list(data.values()) if isinstance(data, dict) else data
        wins = sum(1 for p in positions if p.get("status") == "closed" and p.get("exit_price", 0) > p.get("entry_price", 0))
        losses = sum(1 for p in positions if p.get("status") == "closed" and p.get("exit_price", 0) <= p.get("entry_price", 0))
        history.append({"date": date, "total": len(positions), "wins": wins, "losses": losses, "positions": positions})
    return {"days": history}


@app.get("/api/params")
async def api_params():
    return DEFAULTS.copy()


@app.get("/api/chart/{symbol}")
async def api_chart(symbol: str, period: str = "1d", interval: str = "1m"):
    try:
        data = yf.Ticker(symbol).history(period=period, interval=interval, prepost=True)
        if data.empty:
            return {"symbol": symbol, "bars": []}
        data.index = data.index.tz_convert(ET)
        bars = []
        for ts, row in data.iterrows():
            bars.append({
                "time": int(ts.timestamp()),
                "open": round(float(row["Open"]), 2),
                "high": round(float(row["High"]), 2),
                "low": round(float(row["Low"]), 2),
                "close": round(float(row["Close"]), 2),
                "volume": int(row["Volume"]),
            })
        return {"symbol": symbol, "bars": bars}
    except Exception as e:
        return {"symbol": symbol, "bars": [], "error": str(e)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8050)
