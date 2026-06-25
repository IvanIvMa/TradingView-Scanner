#!/usr/bin/env python3
"""
position_tracker.py — Exit-Überwachung für TJL-Trades (Scanner B).

Logik:
  - Jeder PASS aus der heutigen TJL-Watchlist öffnet AUTOMATISCH eine beobachtete Position
    (Einstiegskurs = curr_price beim PASS).
  - Pro Lauf werden alle offenen Positionen überwacht:
      1. Teilgewinn  : Kurs erreicht Einstieg + 1 ATR  → Alert "Teilgewinn (50%), Stop auf Einstieg"
      2. Trailing Stop: Kurs fällt > TRAIL_PCT unter das Hoch seit Einstieg → Alert "schließen"
      3. EOD-Schluss : ab 15:45 ET → Alert "vor Börsenschluss schließen"
  - Genauigkeit: zwischen zwei Läufen werden ALLE 1-Min-Bars seit Einstieg nachgespielt,
    damit auch ein Trailing-Stop ZWISCHEN den Läufen erkannt wird.
  - Rein informativ: das System handelt NICHT. Alerts sagen "die Strategie würde jetzt aussteigen".

Zustand:  positions_YYYY-MM-DD.json  (offene/geschlossene Positionen des Tages)
Aufruf:   python3 position_tracker.py            (normaler Lauf)
          python3 position_tracker.py --force    (Zeit-Gate ignorieren, zum Testen)
"""

import sys, os, json, glob, subprocess
from datetime import datetime
from zoneinfo import ZoneInfo

import yfinance as yf

# --- Parameter (Backtest-Standard, anpassbar) ---
PARTIAL_ATR   = 1.0     # Teilgewinn-Ziel: Einstieg + 1 ATR
PARTIAL_PCT   = 50      # Teilgewinn-Größe in %
TRAIL_PCT     = 2.0     # Trailing Stop: % unter dem Hoch seit Einstieg
ATR_PERIOD    = 14      # ATR-Periode (Tagesbasis)
EOD_HOUR_ET   = 15      # Zwangsschluss-Zeit (ET)
EOD_MIN_ET    = 45

ET     = ZoneInfo("America/New_York")
BERLIN = ZoneInfo("Europe/Berlin")
HERE   = os.path.dirname(os.path.abspath(__file__))


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
        print("  ! Telegram-Credentials fehlen", file=sys.stderr)
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


def today_intraday_since(symbol, entry_ts, now_et):
    """1-Min-Bars von heute ab Einstiegszeit (inkl. Premarket), sortiert."""
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
                passes[h["symbol"]] = h.get("curr_price")
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
        print(f"  Außerhalb Überwachungsfenster ({now_et.strftime('%H:%M ET')}) — kein Lauf.")
        return

    is_eod = (now_et.hour, now_et.minute) >= (EOD_HOUR_ET, EOD_MIN_ET)

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
    for sym, price in passes.items():
        if sym in positions:
            continue  # schon beobachtet
        if price is None:
            continue
        atr = compute_atr(sym) or round(price * 0.02, 2)  # Fallback: 2% des Kurses
        positions[sym] = {
            "symbol": sym,
            "entry_price": price,
            "entry_ts": now_et.timestamp(),
            "entry_et": now_et.strftime("%H:%M ET"),
            "atr": atr,
            "high_water": price,
            "partial_alerted": False,
            "status": "open",
        }
        target = round(price + atr, 2)
        init_stop = round(price * (1 - TRAIL_PCT / 100), 2)
        alerts.append(
            f"👁 <b>{sym} — Beobachtung gestartet</b>\n"
            f"   Einstieg ${price}  |  ATR ${atr}\n"
            f"   Teilgewinn-Ziel: ${target} (+1 ATR)\n"
            f"   Start Trailing Stop: ${init_stop} (-{TRAIL_PCT}%)"
        )

    # --- 2. Offene Positionen überwachen ---
    for sym, pos in positions.items():
        if pos["status"] != "open":
            continue

        entry = pos["entry_price"]
        atr   = pos["atr"]
        bars  = today_intraday_since(sym, pos["entry_ts"], now_et)

        running_high = max(pos["high_water"], entry)
        partial_price = entry + atr * PARTIAL_ATR
        exit_event = None  # (typ, preis, zeit)

        # Bars seit Einstieg nachspielen (erkennt auch Stop ZWISCHEN den Läufen)
        for b in bars:
            running_high = max(running_high, b["high"])

            # Teilgewinn erreicht?
            if not pos["partial_alerted"] and running_high >= partial_price:
                pos["partial_alerted"] = True
                alerts.append(
                    f"🟡 <b>{sym} — Teilgewinn-Ziel erreicht</b> @ ${round(partial_price,2)}\n"
                    f"   Strategie: {PARTIAL_PCT}% verkaufen, Stop auf Einstieg ${entry} nachziehen\n"
                    f"   <i>(+1 ATR seit Einstieg)</i>"
                )

            # Trailing Stop: nach Teilgewinn Boden = Einstieg (Breakeven)
            trail_stop = running_high * (1 - TRAIL_PCT / 100)
            if pos["partial_alerted"]:
                trail_stop = max(trail_stop, entry)
            if b["low"] <= trail_stop:
                exit_event = ("trailing", round(trail_stop, 2), b["t"])
                break

        pos["high_water"] = round(running_high, 2)

        # Exit durch Trailing Stop?
        if exit_event:
            _, stop_px, t = exit_event
            pnl_pct = round((stop_px - entry) / entry * 100, 2)
            sign = "+" if pnl_pct >= 0 else ""
            pos["status"] = "closed"
            pos["exit_price"] = stop_px
            pos["exit_reason"] = "trailing_stop"
            alerts.append(
                f"🔴 <b>{sym} — Trailing Stop ausgelöst</b> @ ${stop_px} ({fmt_et(t)})\n"
                f"   Strategie: Restposition schließen\n"
                f"   Ergebnis ab Einstieg: <b>{sign}{pnl_pct}%</b> (Hoch war ${pos['high_water']})"
            )
            continue

        # Exit durch EOD?
        if is_eod:
            curr = bars[-1]["close"] if bars else entry
            pnl_pct = round((curr - entry) / entry * 100, 2)
            sign = "+" if pnl_pct >= 0 else ""
            pos["status"] = "closed"
            pos["exit_price"] = round(curr, 2)
            pos["exit_reason"] = "eod"
            alerts.append(
                f"🟠 <b>{sym} — Börsenschluss naht</b>\n"
                f"   Strategie: Position schließen (kein Overnight)\n"
                f"   Aktueller Kurs ${round(curr,2)}  |  ab Einstieg: <b>{sign}{pnl_pct}%</b>"
            )

    # Zustand speichern
    with open(state_path, "w") as f:
        json.dump(positions, f, indent=2)

    # Alerts senden
    open_count = sum(1 for p in positions.values() if p["status"] == "open")
    print(f"  Positionen: {len(positions)} gesamt, {open_count} offen, {len(alerts)} Alert(s)")
    for a in alerts:
        print("  ---")
        print("  " + a.replace("\n", "\n  "))
        send_telegram(a)


if __name__ == "__main__":
    main()
