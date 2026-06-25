#!/usr/bin/env python3
# =============================================================================
# mark_trades_tv.py — zeichnet abgeschlossene TJL-Trades auf die TV-Charts
# =============================================================================
# Bonus-Visualisierung (Ebene A): für jeden geschlossenen Trade eines Tages
# werden auf dem Chart des Tickers Entry-/Exit-Linien, die Trade-Strecke und ein
# Label eingezeichnet — direkt über den MCP-Server (kein Claude nötig).
#
# Robust: ist TradingView Desktop nicht erreichbar, wird still übersprungen.
# Idempotent: gezeichnete entity-IDs werden in tv_marked_*.json gespeichert,
# sodass Redraw/Clear gezielt nur die eigenen Markierungen anfassen.
#
# Nutzung:
#   python3 mark_trades_tv.py                 # heutige Trades markieren
#   python3 mark_trades_tv.py --date 2026-06-25
#   python3 mark_trades_tv.py --dry           # nur Plan zeigen
#   python3 mark_trades_tv.py --force-redraw  # alte Markierungen entfernen + neu
#   python3 mark_trades_tv.py --clear         # alle Markierungen des Tages entfernen
# =============================================================================

import os, sys, json, time
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
CLEAR = "--clear" in sys.argv

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


def load_marked(path):
    if not os.path.exists(path):
        return {}
    try:
        raw = json.load(open(path))
    except Exception:
        return {}
    if isinstance(raw, list):            # altes Format: nur Symbole
        return {s: [] for s in raw}
    return raw                           # {symbol: [entity_ids]}


def health_ok(mcp):
    h = mcp.tool("tv_health_check")
    return bool(h and h.get("cdp_connected"))


def draw_trade(mcp, symbol, p):
    """zeichnet einen Trade; gibt (entity_ids, realized_pct) zurück."""
    ret = realized_pct(p)
    entry, ex = p["entry_price"], p.get("exit_price")
    ets, xts = int(p.get("entry_ts") or 0), int(p.get("exit_ts") or 0)
    anchor = ets or xts
    exit_c = WIN_C if (ret or 0) >= 0 else LOSS_C
    ids = []

    def shape(args):
        r = mcp.tool("draw_shape", args)
        if isinstance(r, dict) and r.get("entity_id"):
            ids.append(r["entity_id"])

    shape({"shape": "horizontal_line", "point": {"time": anchor, "price": entry},
           "overrides": json.dumps({"linecolor": ENTRY_C, "linewidth": 2, "linestyle": 2})})
    shape({"shape": "horizontal_line", "point": {"time": xts or anchor, "price": ex},
           "overrides": json.dumps({"linecolor": exit_c, "linewidth": 2})})
    if ets and xts:
        shape({"shape": "trend_line",
               "point": {"time": ets, "price": entry},
               "point2": {"time": xts, "price": ex},
               "overrides": json.dumps({"linecolor": exit_c, "linewidth": 2})})
    sign = "+" if (ret or 0) >= 0 else ""
    shape({"shape": "text", "point": {"time": anchor, "price": max(entry, ex)},
           "text": f"TJL {symbol} {sign}{ret}% · {p.get('exit_reason', '')}",
           "overrides": json.dumps({"color": exit_c, "fontsize": 12, "bold": True})})
    return ids, ret


def remove_ids(mcp, symbol, ids):
    mcp.tool("chart_set_symbol", {"symbol": symbol})
    time.sleep(0.3)
    for i in ids:
        mcp.tool("draw_remove_one", {"entity_id": i})


def main():
    d = arg_date()
    marked_file = os.path.join(HERE, f"tv_marked_{d}.json")

    # --- CLEAR: alle Markierungen des Tages entfernen ---
    if CLEAR:
        marked = load_marked(marked_file)
        if not marked:
            log("nichts zu löschen."); return
        mcp = MCPClient(MCP_SERVER)
        try:
            mcp.handshake()
            if not health_ok(mcp):
                log("TradingView nicht erreichbar."); return
            for s, ids in marked.items():
                remove_ids(mcp, s, ids)
                log(f"  ✗ {s}: {len(ids)} Markierung(en) entfernt")
        finally:
            mcp.close()
        os.remove(marked_file)
        log("Markierungen gelöscht."); return

    # --- normaler Lauf: Trades markieren ---
    pfile = os.path.join(HERE, f"positions_{d}.json")
    if not os.path.exists(pfile):
        log(f"keine positions-Datei für {d} — nichts zu tun."); return
    closed = {s: p for s, p in json.load(open(pfile)).items() if p.get("status") == "closed"}
    if not closed:
        log(f"keine geschlossenen Trades für {d}."); return

    marked = load_marked(marked_file)
    todo = closed if FORCE else {s: p for s, p in closed.items() if s not in marked}
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
        if not health_ok(mcp):
            log("TradingView nicht erreichbar — übersprungen (Bonus, kein Fehler).")
            return
        for s, p in todo.items():
            mcp.tool("chart_set_symbol", {"symbol": s})
            time.sleep(0.3)
            if FORCE and marked.get(s):          # alte Markierungen erst weg
                for i in marked[s]:
                    mcp.tool("draw_remove_one", {"entity_id": i})
            ids, ret = draw_trade(mcp, s, p)
            marked[s] = ids
            sign = "+" if (ret or 0) >= 0 else ""
            log(f"  ✓ {s} markiert ({sign}{ret}%, {len(ids)} Objekte)")
    finally:
        mcp.close()

    json.dump(marked, open(marked_file, "w"), indent=2)
    log("fertig.")


if __name__ == "__main__":
    main()
