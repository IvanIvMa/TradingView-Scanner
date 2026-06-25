#!/usr/bin/env python3
# =============================================================================
# mark_trades_tv.py — zeichnet abgeschlossene TJL-Trades auf die TV-Charts
# =============================================================================
# Bonus-Visualisierung (Ebene A): für jeden geschlossenen Trade eines Tages
# werden auf dem Chart des Tickers Entry-/Exit-Linien, die Trade-Strecke und ein
# Label eingezeichnet — direkt über den MCP-Server (kein Claude nötig).
#
# Robust: ist TradingView Desktop nicht erreichbar, wird still übersprungen
# (es ist ein Bonus; der Telegram-Track-Record läuft unabhängig).
#
# Nutzung:
#   python3 mark_trades_tv.py                 # heutige Trades markieren
#   python3 mark_trades_tv.py --date 2026-06-25
#   python3 mark_trades_tv.py --dry           # nur Plan zeigen, nichts zeichnen
#   python3 mark_trades_tv.py --force-redraw  # bereits markierte erneut zeichnen
# =============================================================================

import os, sys, json, glob, time
from datetime import datetime
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from mcp_scanner_b import MCPClient, MCP_SERVER

BERLIN = ZoneInfo("Europe/Berlin")
PARTIAL_ATR = 1.0
PARTIAL_PCT = 50

DRY = "--dry" in sys.argv
FORCE = "--force-redraw" in sys.argv

ENTRY_C = "#2563eb"   # blau
WIN_C   = "#16a34a"   # grün
LOSS_C  = "#dc2626"   # rot


def log(m): print(f"[mark_trades_tv {datetime.now(BERLIN):%H:%M:%S}] {m}", flush=True)


def arg_date():
    if "--date" in sys.argv:
        i = sys.argv.index("--date")
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return datetime.now(BERLIN).strftime("%Y-%m-%d")


def realized_pct(pos):
    entry, ex = pos.get("entry_price"), pos.get("exit_price")
    if not entry or ex is None:
        return None
    fr = (ex - entry) / entry
    if pos.get("partial_alerted"):
        pp = entry + (pos.get("atr") or 0) * PARTIAL_ATR
        w = PARTIAL_PCT / 100.0
        fr = w * ((pp - entry) / entry) + (1 - w) * fr
    return round(fr * 100, 2)


def main():
    d = arg_date()
    pfile = os.path.join(HERE, f"positions_{d}.json")
    if not os.path.exists(pfile):
        log(f"keine positions-Datei für {d} — nichts zu tun."); return
    positions = json.load(open(pfile))
    closed = {s: p for s, p in positions.items() if p.get("status") == "closed"}
    if not closed:
        log(f"keine geschlossenen Trades für {d}."); return

    marked_file = os.path.join(HERE, f"tv_marked_{d}.json")
    marked = set()
    if os.path.exists(marked_file) and not FORCE:
        try:
            marked = set(json.load(open(marked_file)))
        except Exception:
            pass
    todo = {s: p for s, p in closed.items() if s not in marked}
    if not todo:
        log("alle Trades bereits markiert."); return
    log(f"{len(todo)} Trade(s) zu markieren: {', '.join(todo)}")

    if DRY:
        for s, p in todo.items():
            log(f"  DRY {s}: entry {p.get('entry_price')} → exit {p.get('exit_price')} "
                f"= {realized_pct(p)}%  ({p.get('exit_reason')})")
        return

    mcp = MCPClient(MCP_SERVER)
    try:
        mcp.handshake()
        h = mcp.tool("tv_health_check")
        if not h or not h.get("cdp_connected"):
            log("TradingView nicht erreichbar — übersprungen (Bonus, kein Fehler).")
            return
        for s, p in todo.items():
            ret = realized_pct(p)
            entry, ex = p["entry_price"], p.get("exit_price")
            ets, xts = int(p.get("entry_ts") or 0), int(p.get("exit_ts") or 0)
            anchor = ets or xts
            exit_c = WIN_C if (ret or 0) >= 0 else LOSS_C

            mcp.tool("chart_set_symbol", {"symbol": s})
            time.sleep(0.3)
            # Entry-Linie (blau, gestrichelt)
            mcp.tool("draw_shape", {"shape": "horizontal_line",
                                    "point": {"time": anchor, "price": entry},
                                    "overrides": json.dumps({"linecolor": ENTRY_C, "linewidth": 2, "linestyle": 2})})
            # Exit-Linie (grün/rot)
            mcp.tool("draw_shape", {"shape": "horizontal_line",
                                    "point": {"time": xts or anchor, "price": ex},
                                    "overrides": json.dumps({"linecolor": exit_c, "linewidth": 2})})
            # Trade-Strecke (wenn beide Zeitstempel da)
            if ets and xts:
                mcp.tool("draw_shape", {"shape": "trend_line",
                                        "point": {"time": ets, "price": entry},
                                        "point2": {"time": xts, "price": ex},
                                        "overrides": json.dumps({"linecolor": exit_c, "linewidth": 2})})
            # Label
            sign = "+" if (ret or 0) >= 0 else ""
            mcp.tool("draw_shape", {"shape": "text",
                                    "point": {"time": anchor, "price": max(entry, ex)},
                                    "text": f"TJL {s} {sign}{ret}% · {p.get('exit_reason', '')}",
                                    "overrides": json.dumps({"color": exit_c, "fontsize": 12, "bold": True})})
            marked.add(s)
            log(f"  ✓ {s} markiert ({sign}{ret}%)")
    finally:
        mcp.close()

    json.dump(sorted(marked), open(marked_file, "w"))
    log("fertig.")


if __name__ == "__main__":
    main()
