#!/usr/bin/env python3
"""
scanner.py — Serverfähiger Nachbau des TradingView-Scanner-Tools, OHNE TradingView/MCP.

Zwei Scanner:
  A) Premarket Gappers  — größte Vorbörsen-Gainer, gefiltert nach Gap%, Preis, Volumen
  B) Trend Join Long    — prüft Ticker gegen Day-Trading-Entry-Kriterien (SMA200, PMH, HOD)

Datenquelle: Yahoo Finance (kostenlos, via yfinance). KEINE TradingView-App nötig.
Dieses Tool LIEST und ANALYSIERT nur — es platziert KEINE Orders.

Nutzung:
    python3 scanner.py selftest          # Logik mit Demo-Daten prüfen (keine Internetverbindung nötig)
    python3 scanner.py gappers           # Scanner A gegen echte Yahoo-Daten
    python3 scanner.py tjl AMD NVDA MU   # Scanner B für genannte Ticker
"""

import sys
import json
import math
from datetime import datetime, timezone, time as dtime
from zoneinfo import ZoneInfo

BERLIN = ZoneInfo("Europe/Berlin")

# ---------------------------------------------------------------------------
# Konfiguration — hier deine Filter anpassen
# ---------------------------------------------------------------------------
GAPPER_FILTERS = {
    "min_gap_pct": 5.0,        # nur Gaps > 5 %
    "min_price": 3.0,          # nur Aktien über $3
    "min_premarket_volume": 50_000,
    "top_n": 10,               # Top 10 nach Gap% absteigend
}

# Universe für den Gapper-Scan, wenn keine Live-"Gainers"-Liste vorliegt.
# Auf deinem Server kannst du das durch eine echte Gainers-Quelle ersetzen.
GAPPER_UNIVERSE = [
    "AAPL", "NVDA", "AMD", "TSLA", "MU", "INTC", "PLTR", "SOFI",
    "AMC", "GME", "RIVN", "LCID", "NIO", "F", "BAC",
]

NY_TZ_OFFSET_HOURS = -4  # grobe ET-Näherung (EDT). Für Produktion: zoneinfo nutzen.


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------
def now_iso():
    return datetime.now(BERLIN).isoformat()


def _lazy_yf():
    """yfinance erst bei Bedarf importieren, damit selftest ohne Netz läuft."""
    import yfinance as yf
    return yf


# ---------------------------------------------------------------------------
# Scanner A — Premarket Gappers
# ---------------------------------------------------------------------------
def compute_gap_pct(prev_close, premarket_price):
    if prev_close is None or prev_close == 0:
        return None
    return round((premarket_price - prev_close) / prev_close * 100, 2)


def filter_gappers(rows, f=GAPPER_FILTERS):
    """rows: Liste von dicts mit symbol, price, gap_pct, premarket_volume.
    Gibt gefilterte + sortierte Top-N-Liste zurück."""
    kept = [
        r for r in rows
        if r.get("gap_pct") is not None
        and r["gap_pct"] > f["min_gap_pct"]
        and r["price"] > f["min_price"]
        and r["premarket_volume"] > f["min_premarket_volume"]
    ]
    kept.sort(key=lambda r: r["gap_pct"], reverse=True)
    for i, r in enumerate(kept[: f["top_n"]], start=1):
        r["rank"] = i
    return kept[: f["top_n"]]


def scan_gappers_live(universe=GAPPER_UNIVERSE):
    """Holt echte Daten von Yahoo. Läuft auf deinem Server, NICHT in dieser Sandbox."""
    yf = _lazy_yf()
    rows = []
    for sym in universe:
        try:
            t = yf.Ticker(sym)
            info = t.fast_info
            prev_close = float(info.get("previous_close") or info.get("previousClose"))
            last = float(info.get("last_price") or info.get("lastPrice"))
            vol = int(info.get("last_volume") or info.get("lastVolume") or 0)
            gap = compute_gap_pct(prev_close, last)
            rows.append({
                "symbol": sym,
                "price": round(last, 2),
                "gap_pct": gap,
                "premarket_volume": vol,
            })
        except Exception as e:
            print(f"  ! {sym}: konnte nicht geladen werden ({e})", file=sys.stderr)
    hits = filter_gappers(rows)
    return {"scanned_at": now_iso(), "filters": GAPPER_FILTERS, "gappers": hits}


# ---------------------------------------------------------------------------
# Scanner B — Trend Join Long
# ---------------------------------------------------------------------------
def sma(values, period):
    if len(values) < period:
        return None
    return round(sum(values[-period:]) / period, 4)


def evaluate_tjl(curr_px, prev_daily_high, prev_daily_close, sma200, pmh, today_hod):
    """Bewertungslogik aus dem Artikel — PASS nur wenn beide Breakouts erfüllt sind."""
    daily_breakout = (curr_px > prev_daily_high) and (prev_daily_close > sma200)
    intraday_breakout = (curr_px > pmh) and (curr_px > today_hod)
    if daily_breakout and intraday_breakout:
        return "PASS"
    if not daily_breakout:
        return "fail_daily"
    return "fail_intraday"


def _et_window_filter(timestamps, highs, start_h, start_m, end_h, end_m):
    """max High für Bars im ET-Zeitfenster [start, end) des heutigen Tages (Näherung)."""
    vals = []
    for ts, hi in zip(timestamps, highs):
        et = ts + (NY_TZ_OFFSET_HOURS * 3600)
        d = datetime.fromtimestamp(et, tz=timezone.utc)
        bar_t = dtime(d.hour, d.minute)
        if dtime(start_h, start_m) <= bar_t < dtime(end_h, end_m):
            vals.append(hi)
    return max(vals) if vals else None


def scan_tjl_live(tickers):
    """Echter TJL-Scan über Yahoo-Daten. Läuft auf deinem Server."""
    yf = _lazy_yf()
    results, hits = [], []
    for sym in tickers:
        try:
            t = yf.Ticker(sym)
            daily = t.history(period="300d", interval="1d")
            if len(daily) < 201:
                results.append({"symbol": sym, "result": "fail_no_data"})
                continue
            closes = daily["Close"].tolist()
            prev_daily_high = float(daily["High"].iloc[-1])
            prev_daily_close = float(daily["Close"].iloc[-1])
            sma200 = sma(closes[:-1], 200)  # ohne aktuelle Bar
            curr_px = float(t.fast_info.get("last_price") or closes[-1])

            intraday = t.history(period="1d", interval="1m")
            ts = [int(x.timestamp()) for x in intraday.index]
            highs = intraday["High"].tolist()
            pmh = _et_window_filter(ts, highs, 4, 0, 9, 30)
            hod = _et_window_filter(ts, highs, 9, 30, 23, 59)
            pmh = pmh if pmh is not None else curr_px
            hod = hod if hod is not None else curr_px

            res = evaluate_tjl(curr_px, prev_daily_high, prev_daily_close, sma200, pmh, hod)
            results.append({"symbol": sym, "result": res})
            if res == "PASS":
                hits.append({
                    "symbol": sym, "curr_price": round(curr_px, 2),
                    "prev_daily_high": round(prev_daily_high, 2),
                    "sma200": sma200, "pmh": round(pmh, 2),
                    "today_hod": round(hod, 2),
                })
        except Exception as e:
            print(f"  ! {sym}: {e}", file=sys.stderr)
            results.append({"symbol": sym, "result": "error"})
    return {
        "scanned_at": now_iso(),
        "candidates_checked": len(tickers),
        "hits": hits,
        "all_results": results,
    }


# ---------------------------------------------------------------------------
# Selbsttest — prüft die Logik mit Demo-Daten (keine Internetverbindung nötig)
# ---------------------------------------------------------------------------
def selftest():
    print("=== SELBSTTEST: Filter- und Bewertungslogik ===\n")
    ok = True

    # Scanner A: Filterlogik
    demo_rows = [
        {"symbol": "POET", "price": 20.75, "gap_pct": 44.34, "premarket_volume": 800_000},
        {"symbol": "PENNY", "price": 1.20, "gap_pct": 60.0, "premarket_volume": 900_000},  # Preis zu niedrig
        {"symbol": "THIN", "price": 50.0, "gap_pct": 12.0, "premarket_volume": 10_000},     # Volumen zu niedrig
        {"symbol": "FLAT", "price": 30.0, "gap_pct": 2.0, "premarket_volume": 500_000},     # Gap zu klein
        {"symbol": "ONDS", "price": 11.21, "gap_pct": 26.52, "premarket_volume": 600_000},
    ]
    hits = filter_gappers(demo_rows)
    symbols = [h["symbol"] for h in hits]
    expected = ["POET", "ONDS"]
    print(f"Scanner A — erwartet {expected}, bekommen {symbols}")
    if symbols != expected:
        ok = False
        print("  FEHLER: Filterlogik stimmt nicht!")
    else:
        print("  OK: Junk gefiltert, korrekt nach Gap% sortiert.")

    # Scanner B: Bewertungslogik
    print()
    cases = [
        # (curr, prevHigh, prevClose, sma200, pmh, hod, erwartet)
        (415.20, 412.55, 410.0, 285.50, 414.10, 415.0, "PASS"),
        (400.0, 412.55, 410.0, 285.50, 414.10, 415.0, "fail_daily"),    # unter prev high
        (413.0, 412.55, 410.0, 285.50, 414.10, 415.0, "fail_intraday"), # über prev high, aber unter PMH
        (300.0, 412.55, 410.0, 285.50, 414.10, 415.0, "fail_daily"),
    ]
    for i, (curr, ph, pc, s200, pmh, hod, exp) in enumerate(cases, 1):
        got = evaluate_tjl(curr, ph, pc, s200, pmh, hod)
        mark = "OK" if got == exp else "FEHLER"
        if got != exp:
            ok = False
        print(f"Scanner B Fall {i} — erwartet {exp:14s} bekommen {got:14s} [{mark}]")

    # SMA-Test
    print()
    vals = list(range(1, 201))  # 1..200, Mittel = 100.5
    s = sma(vals, 200)
    print(f"SMA200 von 1..200 — erwartet 100.5, bekommen {s} [{'OK' if s == 100.5 else 'FEHLER'}]")
    if s != 100.5:
        ok = False

    print("\n" + ("ALLE TESTS BESTANDEN ✓" if ok else "TESTS FEHLGESCHLAGEN ✗"))
    return ok


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    cmd = sys.argv[1].lower()
    if cmd == "selftest":
        selftest()
    elif cmd == "gappers":
        out = scan_gappers_live()
        print(json.dumps(out, indent=2))
        fname = f"premarket_gappers_{datetime.now(BERLIN).strftime('%Y-%m-%d')}.json"
        with open(fname, "w") as fp:
            json.dump(out, fp, indent=2)
        print(f"\nGespeichert: {fname}")
    elif cmd == "tjl":
        tickers = sys.argv[2:] or ["AMD", "NVDA", "MU"]
        out = scan_tjl_live(tickers)
        print(json.dumps(out, indent=2))
    else:
        print(f"Unbekannter Befehl: {cmd}")
        print(__doc__)


if __name__ == "__main__":
    main()
