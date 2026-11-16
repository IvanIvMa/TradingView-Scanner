#!/usr/bin/env python3
"""
backtest_exits.py — Scanner-B-Einstiege der letzten ~57 Tage nachspielen.
Nutzt EXAKT die Live-Regeln aus tjl_rules.py (Einstieg + Ausstieg).

Datenbasis: premarket_gappers_<datum>.json (Scanner A) + Yahoo 5-Min-Kerzen
(Yahoo liefert 5-Min nur ~60 Tage). Einstieg = erster Basis-PASS an einem
30-Min-Prüfpunkt (10:00–15:30 ET) zum Schluss der letzten fertigen Kerze.
Konservativ: trifft eine Kerze Stop UND Ziel, zählt der Stop.

Ergebnis: Konsole + backtest_results.json (fürs Dashboard).
Hinweis: kleine Stichprobe -> Richtung, kein Beweis. Endgültiger Test im
IBKR-Projekt (Alpaca-1-Min, Holdout-Registry).
"""
import glob, json, os
from copy import deepcopy
from datetime import datetime, timedelta, time as dtime
import tjl_rules as R

ET = R.ET
HERE = os.path.dirname(os.path.abspath(__file__))
CUTOFF = (datetime.now(ET) - timedelta(days=57)).date()
CHECKPOINTS = [dtime(h, m) for h in range(10, 16) for m in (0, 30)][:-1]  # 10:00..15:30
BAR = 300


def load_days():
    days = {}
    for f in sorted(glob.glob(os.path.join(HERE, "premarket_gappers_*.json"))):
        d = datetime.strptime(os.path.basename(f)[18:28], "%Y-%m-%d").date()
        if CUTOFF <= d < datetime.now(ET).date():
            try:
                syms = [g["symbol"] for g in json.load(open(f)).get("gappers", [])]
            except Exception:
                continue
            if syms:
                days[d] = syms
    return days


def find_entries(days):
    entries, cache = [], {}
    for d, syms in days.items():
        for sym in syms:
            if sym not in cache:
                try:
                    cache[sym] = (R.load_daily(sym), R.df_to_bars(R.load_intraday(sym, interval="5m", start=CUTOFF)))
                except Exception:
                    cache[sym] = (None, [])
            daily, bars = cache[sym]
            if daily is None or daily.empty or not bars:
                continue
            dctx = R.daily_context(daily, d)
            day = [b for b in bars if datetime.fromtimestamp(b["t"], ET).date() == d]
            if not dctx or not day:
                continue
            for cp in CHECKPOINTS:
                now_ts = datetime.combine(d, cp, ET).timestamp()
                ev = R.evaluate_entry(dctx, R.intraday_context(day, now_ts, bar_seconds=BAR))
                if ev.get("base_result") == "PASS":
                    rth = [b for b in day if dtime(9, 30) <= datetime.fromtimestamp(b["t"], ET).time() < dtime(16)]
                    entries.append({"date": str(d), "sym": sym, "cp": cp.strftime("%H:%M"),
                                    "entry": ev["curr_price"], "atr": ev["atr"], "entry_ts": now_ts,
                                    "filters": ev["filters"], "rth": rth})
                    break
    return entries


def run(entries, params):
    out = []
    for e in entries:
        tr = R.replay_exits(e["entry"], e["atr"], e["rth"], e["entry_ts"], params, bar_seconds=BAR)
        if not tr.closed:
            tr.close_eod(e["rth"][-1]["close"], e["rth"][-1]["t"])
        out.append(round(tr.pnl_pct(), 3))
    return out


def stats(p):
    n = len(p)
    if not n:
        return {"n": 0}
    gw = sum(x for x in p if x > 0); gl = -sum(x for x in p if x < 0)
    return {"n": n, "win_pct": round(sum(x > 0 for x in p) / n * 100, 1),
            "avg_pct": round(sum(p) / n, 2), "sum_pct": round(sum(p), 1),
            "pf": round(gw / gl, 2) if gl else None}


def P(**kw):
    p = deepcopy(R.PARAMS); p.update(kw); return p


EXIT_VARIANTS = {
    "Aktuell: Stop 0.75 / Ziel 1.0 / Trail 0.75":      P(),
    "+ VWAP-Bruch-Exit scharf":                          P(VWAP_EXIT_MODE="enforce"),
    "Enger: Stop 0.5 / Ziel 1.0 / Trail 0.5":           P(INIT_STOP_ATR=0.5, TRAIL_ATR=0.5),
    "Alt-ähnlich: Stop 0.25 / Ziel 0.5 / Trail 0.5":    P(INIT_STOP_ATR=0.25, PARTIAL_ATR=0.5, TRAIL_ATR=0.5),
}
ENTRY_SUBSETS = {
    "Alle Basis-PASS":                lambda e: True,
    "Filter: über VWAP":              lambda e: e["filters"]["above_vwap"],
    "Filter: RVOL >= 2":              lambda e: e["filters"]["rvol_ok"],
    "Filter: nicht überdehnt":        lambda e: e["filters"]["ext_ok"],
    "Alle 3 Filter":                  lambda e: e["filters"]["all_ok"],
    "Nur bis 11:30 ET":               lambda e: e["cp"] <= "11:30",
}

if __name__ == "__main__":
    entries = find_entries(load_days())
    res = {"generated": datetime.now(ET).isoformat(), "window_from": str(CUTOFF),
           "bar": "5m", "n_entries": len(entries), "table": [], "trades": []}
    print(f"Einstiege seit {CUTOFF}: {len(entries)}")
    for sname, filt in ENTRY_SUBSETS.items():
        sel = [e for e in entries if filt(e)]
        print(f"\n== {sname} ==")
        for vname, params in EXIT_VARIANTS.items():
            st = stats(run(sel, params))
            res["table"].append({"entries": sname, "exits": vname, **st})
            print(f"  {vname:46s} {st}")
    base = run(entries, R.PARAMS)
    for e, p in zip(entries, base):
        res["trades"].append({k: e[k] for k in ("date", "sym", "cp", "entry", "atr", "filters")} | {"pnl_pct": p})
    json.dump(res, open(os.path.join(HERE, "backtest_results.json"), "w"), indent=1)
    print("\n-> backtest_results.json geschrieben")
