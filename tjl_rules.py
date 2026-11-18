#!/usr/bin/env python3
"""
tjl_rules.py — EINE Quelle für die TJL-Regeln (Einstieg + Ausstieg).

Benutzt von: tjl_scanner.sh (Scanner B, Yahoo-Pfad), mcp_scanner_b.py (TV-Pfad),
position_tracker.py (Live-Exits), backtest_exits.py (Backtest), Dashboard.
Ziel: Live und Backtest prüfen exakt dieselbe Logik.

Bars sind Dicts: {"t": unix_ts (Kerzenbeginn), "open","high","low","close","volume"}.

Neue Bausteine (Stand 2026-11-16) laufen per Default im Beobachtungsmodus:
sie werden berechnet und gespeichert, verändern aber kein Signal, bis der Backtest
sie bestätigt.  Scharf schalten: FILTER_MODE / VWAP_EXIT_MODE = "enforce".
"""
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

PARAMS = {
    # --- Einstieg: neue Filter ---
    "FILTER_MODE":    "observe",  # "observe" = nur protokollieren | "enforce" = blockieren
    "MAX_EXT_ATR":    1.0,        # Kurs max. 1 ATR über VWAP (nicht überdehnt)
    "MIN_RVOL":       2.0,        # relatives Volumen bis jetzt >= 2x
    # --- Ausstieg ---
    "INIT_STOP_ATR":  0.75,       # fester Anfangs-Stop
    "PARTIAL_ATR":    1.0,        # Teilgewinn-Ziel
    "PARTIAL_PCT":    50,         # Teilgewinn-Größe %
    "TRAIL_ATR":      0.75,       # Trailing nach Teilgewinn (Boden = Einstieg)
    "VWAP_EXIT_MODE": "observe",  # 5-Min-Schluss unter VWAP -> raus ("enforce") / nur melden
    "EOD_ET":         "15:45",
    "ATR_PERIOD":     14,
}

# Werte aus dem Cockpit (scanner_params.json) überschreiben die Defaults oben.
try:
    import os as _os, sys as _sys
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
    import params_store as _ps
    PARAMS.update({k: v for k, v in _ps.load().items() if k in PARAMS})
except Exception:
    pass


def reload_params():
    """Für langlebige Prozesse (Cockpit): Werte neu einlesen, PARAMS in place aktualisieren."""
    import params_store as ps
    PARAMS.update({k: v for k, v in ps.load().items() if k in PARAMS})
    return PARAMS


RTH_OPEN = dtime(9, 30)


# ---------------------------------------------------------------------------
# Daten (Yahoo) — gemeinsame Loader
# ---------------------------------------------------------------------------
def df_to_bars(df):
    if df is None or df.empty:
        return []
    out = []
    for ts, r in df.iterrows():
        out.append({"t": ts.timestamp(), "open": float(r["Open"]), "high": float(r["High"]),
                    "low": float(r["Low"]), "close": float(r["Close"]),
                    "volume": float(r.get("Volume", 0) or 0)})
    return out


def load_daily(symbol, period="2y"):
    import yfinance as yf
    df = yf.Ticker(symbol).history(period=period, interval="1d")
    if not df.empty:
        df.index = df.index.tz_convert(ET)
    return df


def load_intraday(symbol, period="1d", interval="1m", start=None):
    import yfinance as yf
    t = yf.Ticker(symbol)
    df = (t.history(start=start, interval=interval, prepost=True) if start
          else t.history(period=period, interval=interval, prepost=True))
    if not df.empty:
        df.index = df.index.tz_convert(ET)
    return df


# ---------------------------------------------------------------------------
# Kontext
# ---------------------------------------------------------------------------
def daily_context(daily_df, day):
    """Kennzahlen nur aus Tagen VOR `day` (kein Look-ahead)."""
    past = daily_df[daily_df.index.date < day]
    if len(past) < 50:
        return None
    closes = past["Close"].tolist()
    h, l, c = past["High"].tolist(), past["Low"].tolist(), closes
    tr = [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) for i in range(1, len(c))]
    n = PARAMS["ATR_PERIOD"]
    return {
        "prev_high": float(h[-1]), "prev_close": float(c[-1]),
        "sma200": sum(closes[-200:]) / len(closes[-200:]),
        "atr": sum(tr[-n:]) / n,
        "avg_vol20": float(past["Volume"].tail(20).mean()),
    }


def _et_time(ts):
    return datetime.fromtimestamp(ts, ET).time()


def vwap_series(rth_bars):
    """VWAP je RTH-Kerze (kumulativ ab 9:30)."""
    out, pv, vol = [], 0.0, 0.0
    for b in rth_bars:
        tp = (b["high"] + b["low"] + b["close"]) / 3
        pv += tp * b["volume"]; vol += b["volume"]
        out.append(pv / vol if vol else b["close"])
    return out


def intraday_context(day_bars, now_ts, bar_seconds=60):
    """Nur Kerzen, die vor now_ts FERTIG sind. HOD ohne die letzte Kerze (= aktueller Ausbruch)."""
    done = [b for b in day_bars if b["t"] + bar_seconds <= now_ts]
    pm = [b for b in done if dtime(4) <= _et_time(b["t"]) < RTH_OPEN]
    rth = [b for b in done if RTH_OPEN <= _et_time(b["t"]) < dtime(16)]
    if not rth:
        return None
    vw = vwap_series(rth)
    open_ts = datetime.fromtimestamp(rth[0]["t"], ET).replace(hour=9, minute=30, second=0).timestamp()
    return {
        "pmh": max(b["high"] for b in pm) if pm else None,
        "hod": max(b["high"] for b in rth[:-1]) if len(rth) > 1 else rth[0]["high"],
        "curr": rth[-1]["close"],
        "vwap": vw[-1],
        "cum_vol": sum(b["volume"] for b in rth),
        "minutes": max(1.0, (now_ts - open_ts) / 60),
    }


# ---------------------------------------------------------------------------
# Einstieg
# ---------------------------------------------------------------------------
def evaluate_entry(d, i, params=PARAMS):
    """d = daily_context, i = intraday_context. Gibt Ergebnis + alle Filterwerte zurück."""
    if not d or not i:
        return {"result": "fail_no_data"}
    curr = i["curr"]
    daily_ok = curr > d["prev_high"] and d["prev_close"] > d["sma200"]
    pmh, hod = i.get("pmh"), i.get("hod")
    intra_ok = (pmh is None or curr > pmh) and (hod is None or curr > hod) and (pmh is not None or hod is not None)
    base = "PASS" if (daily_ok and intra_ok) else ("fail_daily" if not daily_ok else "fail_intraday")

    vwap, atr = i.get("vwap"), d.get("atr")
    expected = (d.get("avg_vol20") or 0) * min(i.get("minutes") or 0, 390) / 390
    rvol = i["cum_vol"] / expected if expected and i.get("cum_vol") is not None else None
    ext_atr = (curr - vwap) / atr if (atr and vwap is not None) else None
    filters = {
        "above_vwap": vwap is not None and curr > vwap,
        "rvol": round(rvol, 2) if rvol is not None else None,
        "rvol_ok": rvol is not None and rvol >= params["MIN_RVOL"],
        "ext_atr": round(ext_atr, 2) if ext_atr is not None else None,
        "ext_ok": ext_atr is not None and ext_atr <= params["MAX_EXT_ATR"],
    }
    filters["all_ok"] = filters["above_vwap"] and filters["rvol_ok"] and filters["ext_ok"]

    result = base
    if base == "PASS" and params["FILTER_MODE"] == "enforce" and not filters["all_ok"]:
        result = "fail_filter"
    return {
        "result": result, "base_result": base, "filters": filters,
        "curr_price": round(curr, 2), "prev_daily_high": round(d["prev_high"], 2),
        "sma200": round(d["sma200"], 2), "pmh": i.get("pmh") and round(i["pmh"], 2),
        "today_hod": i.get("hod") and round(i["hod"], 2),
        "vwap": vwap and round(vwap, 2), "atr": atr and round(atr, 2),
    }


# ---------------------------------------------------------------------------
# Ausstieg
# ---------------------------------------------------------------------------
class ExitTracker:
    """Spielt Kerzen ab Einstieg ab. Konservativ: Stop wird vor Ziel geprüft."""

    def __init__(self, entry, atr, params=PARAMS):
        self.p, self.entry, self.atr = params, entry, atr
        self.stop = entry - atr * params["INIT_STOP_ATR"]
        self.target = entry + atr * params["PARTIAL_ATR"]
        self.high = entry
        self.partial_done = False
        self.closed = False
        self.exit_price = self.exit_reason = self.exit_ts = None
        self.vwap_break_ts = None
        self.events = []

    def _close(self, px, reason, ts):
        self.closed, self.exit_price, self.exit_reason, self.exit_ts = True, px, reason, ts
        self.events.append(("exit", reason, px, ts))

    def update(self, bar, vwap=None, check_vwap=True):
        if self.closed:
            return
        if bar["low"] <= self.stop:
            reason = ("trailing_stop" if self.stop > self.entry else
                      "breakeven_stop" if self.partial_done else "initial_stop")
            return self._close(self.stop, reason, bar["t"])
        if not self.partial_done and bar["high"] >= self.target:
            self.partial_done = True
            self.events.append(("partial", "target", self.target, bar["t"]))
        self.high = max(self.high, bar["high"])
        if self.partial_done:
            self.stop = max(self.stop, self.high - self.atr * self.p["TRAIL_ATR"], self.entry)
        if check_vwap and vwap is not None and bar["close"] < vwap and self.vwap_break_ts is None:
            self.vwap_break_ts = bar["t"]
            self.events.append(("vwap_break", self.p["VWAP_EXIT_MODE"], bar["close"], bar["t"]))
            if self.p["VWAP_EXIT_MODE"] == "enforce":
                return self._close(bar["close"], "vwap_break", bar["t"])

    def close_eod(self, px, ts):
        if not self.closed:
            self._close(px, "eod", ts)

    def pnl_pct(self, last_px=None):
        """Gemischter P&L inkl. Teilgewinn (der alte Log ignorierte den Teilgewinn)."""
        exit_px = self.exit_price if self.closed else (last_px or self.entry)
        part = self.p["PARTIAL_PCT"] / 100 if self.partial_done else 0
        return ((part * (self.target - self.entry) + (1 - part) * (exit_px - self.entry))
                / self.entry * 100)


def replay_exits(entry, atr, rth_bars, entry_ts, params=PARAMS, bar_seconds=60):
    """Hilfsfunktion: ExitTracker über alle RTH-Kerzen nach entry_ts laufen lassen (VWAP ab 9:30)."""
    vw = vwap_series(rth_bars)
    tr = ExitTracker(entry, atr, params)
    eh, em = map(int, params["EOD_ET"].split(":"))
    for b, v in zip(rth_bars, vw):
        if b["t"] < entry_ts:
            continue
        if _et_time(b["t"]) >= dtime(eh, em):
            tr.close_eod(b["open"], b["t"])
            break
        # VWAP-Bruch nur auf 5-Min-Schlusskursen prüfen (1-Min wäre zu nervös)
        tr.update(b, v, check_vwap=int(b["t"] + bar_seconds) % 300 == 0)
    return tr
