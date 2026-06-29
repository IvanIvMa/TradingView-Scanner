#!/usr/bin/env python3
# =============================================================================
# performance_log.py — Live-Track-Record der echten TJL-Signale
# =============================================================================
# Aggregiert die täglichen positions_YYYY-MM-DD.json (vom Position-Tracker) zu
# einer ehrlichen Bilanz der TATSÄCHLICH gewählten Kandidaten — jeden Tag andere.
# Kein Backtest: das sind die realen Signale, die das System ausgegeben hat.
#
# Liefert eine Equity-Kurve (PNG) + Statistik per Telegram.
#
# Nutzung:
#   python3 performance_log.py            # Report bauen + per Telegram senden
#   python3 performance_log.py --dry      # nur erzeugen + Stats drucken (kein Telegram)
#   python3 performance_log.py --week     # nur die laufende Kalenderwoche
# =============================================================================

import os, sys, json, glob
from datetime import datetime, date
from zoneinfo import ZoneInfo

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

BERLIN = ZoneInfo("Europe/Berlin")
HERE = os.path.dirname(os.path.abspath(__file__))

# muss zu position_tracker.py passen
PARTIAL_ATR = 1.0
PARTIAL_PCT = 50      # % der Position, der beim Teilgewinn verkauft wird

DRY = "--dry" in sys.argv
WEEK_ONLY = "--week" in sys.argv


def load_env():
    env = {}
    p = os.path.join(HERE, ".env")
    if os.path.exists(p):
        for line in open(p):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def realized_return_pct(pos):
    """Realisierte Rendite % einer geschlossenen Position (inkl. Teilgewinn-Blend)."""
    entry = pos.get("entry_price")
    exit_px = pos.get("exit_price")
    if not entry or exit_px is None:
        return None
    final_ret = (exit_px - entry) / entry
    if pos.get("partial_alerted"):
        atr = pos.get("atr") or 0
        partial_px = entry + atr * PARTIAL_ATR
        partial_ret = (partial_px - entry) / entry
        w = PARTIAL_PCT / 100.0
        blended = w * partial_ret + (1 - w) * final_ret
        return round(blended * 100, 2)
    return round(final_ret * 100, 2)


def collect_trades(week_only=False):
    """Alle geschlossenen Trades aus positions_*.json, chronologisch."""
    today = datetime.now(BERLIN).date()
    iso_week = today.isocalendar()[:2]
    trades = []
    open_count = 0
    for path in sorted(glob.glob(os.path.join(HERE, "positions_*.json"))):
        d = os.path.basename(path)[len("positions_"):-len(".json")]
        try:
            day = date.fromisoformat(d)
        except ValueError:
            continue
        if week_only and day.isocalendar()[:2] != iso_week:
            continue
        try:
            positions = json.load(open(path))
        except Exception:
            continue
        for sym, pos in positions.items():
            if pos.get("status") == "open":
                open_count += 1
                continue
            r = realized_return_pct(pos)
            if r is None:
                continue
            trades.append({
                "date": day, "symbol": sym, "ret": r,
                "reason": pos.get("exit_reason", "?"),
                "ts": pos.get("entry_ts", 0),
            })
    trades.sort(key=lambda t: (t["date"], t["ts"]))
    return trades, open_count


def compute_stats(trades):
    n = len(trades)
    if n == 0:
        return None
    wins = [t for t in trades if t["ret"] > 0]
    rets = [t["ret"] for t in trades]
    equity = [100.0]
    for r in rets:
        equity.append(equity[-1] * (1 + r / 100))
    best = max(trades, key=lambda t: t["ret"])
    worst = min(trades, key=lambda t: t["ret"])
    return {
        "n": n, "wins": len(wins),
        "win_rate": round(len(wins) / n * 100, 1),
        "avg": round(sum(rets) / n, 2),
        "best": best, "worst": worst,
        "cum_pct": round(equity[-1] - 100, 2),
        "equity": equity,
        "first": trades[0]["date"], "last": trades[-1]["date"],
    }


def make_png(trades, stats, out_path):
    equity = stats["equity"]
    x = list(range(len(equity)))
    fig, ax = plt.subplots(figsize=(7, 3.6), dpi=150)
    up = stats["cum_pct"] >= 0
    line_c = "#16a34a" if up else "#dc2626"
    ax.plot(x, equity, color=line_c, linewidth=2.2)
    ax.fill_between(x, 100, equity, color=line_c, alpha=0.10)
    ax.axhline(100, color="#9ca3af", linewidth=1, linestyle="--")
    # Marker je Trade (grün Gewinn / rot Verlust)
    for i, t in enumerate(trades, start=1):
        ax.scatter(i, equity[i], s=18, zorder=3,
                   color="#16a34a" if t["ret"] > 0 else "#dc2626")
    ax.set_title(f"TJL Live-Track-Record — {stats['n']} Trades  "
                 f"({stats['first'].strftime('%d.%m.')}–{stats['last'].strftime('%d.%m.%Y')})",
                 fontsize=11, fontweight="bold")
    ax.set_ylabel("Equity (Start = 100)", fontsize=9)
    ax.set_xlabel("Trade #", fontsize=9)
    ax.grid(True, alpha=0.2)
    ax.margins(x=0.01)
    fig.tight_layout()
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)


def build_caption(stats, open_count):
    b, w = stats["best"], stats["worst"]
    sign = "+" if stats["cum_pct"] >= 0 else ""
    return (
        f"📊 <b>TJL Performance Log</b>\n"
        f"<i>{stats['first'].strftime('%m/%d')}–{stats['last'].strftime('%m/%d/%Y')} · live signals</i>\n\n"
        f"Trades: <b>{stats['n']}</b>  ({stats['wins']} winners)\n"
        f"Win rate: <b>{stats['win_rate']}%</b>\n"
        f"Avg per trade: <b>{'+' if stats['avg']>=0 else ''}{stats['avg']}%</b>\n"
        f"Cumulative (compounded): <b>{sign}{stats['cum_pct']}%</b>\n\n"
        f"🟢 Best: {b['symbol']} +{b['ret']}%\n"
        f"🔴 Worst: {w['symbol']} {w['ret']}%\n"
        f"👁 Currently open: {open_count}"
    )


def send_photo(env, png_path, caption):
    import requests
    token = env.get("TELEGRAM_BOT_TOKEN")
    chat = env.get("TELEGRAM_CHAT_ID")
    with open(png_path, "rb") as f:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendPhoto",
            data={"chat_id": int(chat), "caption": caption, "parse_mode": "HTML"},
            files={"photo": f}, timeout=30)
    return r.json().get("ok", False)


def send_text(env, msg):
    import requests
    token = env.get("TELEGRAM_BOT_TOKEN")
    chat = env.get("TELEGRAM_CHAT_ID")
    r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      json={"chat_id": int(chat), "text": msg, "parse_mode": "HTML"},
                      timeout=15)
    return r.json().get("ok", False)


def main():
    env = load_env()
    trades, open_count = collect_trades(week_only=WEEK_ONLY)
    stats = compute_stats(trades)

    if stats is None:
        msg = (f"📊 <b>TJL Performance Log</b>\n"
               f"<i>No closed trades yet.</i>\n"
               f"👁 Currently open: {open_count}\n\n"
               f"Once Scanner B produces PASS signals and the tracker closes them, "
               f"the equity curve will appear here.")
        print(msg.replace("<b>","").replace("</b>","").replace("<i>","").replace("</i>",""))
        if not DRY:
            send_text(env, msg)
        return

    png = os.path.join(HERE, "performance_equity.png")
    make_png(trades, stats, png)
    caption = build_caption(stats, open_count)

    print(caption.replace("<b>","").replace("</b>","").replace("<i>","").replace("</i>",""))
    print(f"\nPNG: {png}")
    if not DRY:
        ok = send_photo(env, png, caption)
        print("Telegram sent." if ok else "Telegram error.")


if __name__ == "__main__":
    main()
