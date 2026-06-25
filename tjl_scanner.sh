#!/usr/bin/env bash
# =============================================================================
# TJL Scanner (Scanner B) — Trend Join Long, live auf den heutigen Gappers
# =============================================================================
# Läuft alle 30 Min während US-Handelszeit (16:00-20:00 Berlin = 10:00-14:00 ET).
#
# Ablauf:
#   1. Liest die heutige Gappers-Liste (Output von Scanner A / daily_scanner.sh)
#   2. Für jeden Ticker: TJL-Kriterien via yfinance prüfen
#      - Daily:    prev_daily_high, prev_daily_close, SMA200
#      - Intraday: PMH (4:00-9:30 ET), HOD (9:30-jetzt), aktueller Kurs
#   3. Urteil: PASS / fail_daily / fail_intraday
#   4. Telegram NUR bei: erstem Lauf des Tages ODER neuem PASS (kein Spam)
#
# Nutzung:
#   bash tjl_scanner.sh                    # normaler Lauf (yfinance, mit Zeit-Gate)
#   bash tjl_scanner.sh --force            # Zeit-Gate ignorieren (zum Testen)
#   bash tjl_scanner.sh --mcp-data '<JSON>'  # TradingView MCP-Daten (von Claude)
# =============================================================================

set -euo pipefail
cd "$(dirname "$0")"

FORCE=0
MCP_DATA=""
while [ $# -gt 0 ]; do
    case "$1" in
        --force) FORCE=1 ;;
        --mcp-data) MCP_DATA="$2"; shift ;;
    esac
    shift
done

# .env laden
if [ ! -f .env ]; then
    echo "FEHLER: .env Datei nicht gefunden" >&2
    exit 1
fi
export $(grep -v '^#' .env | xargs)

DATE=$(date +%Y-%m-%d)
GAPPERS_FILE="premarket_gappers_${DATE}.json"
STATE_FILE="tjl_state_${DATE}.json"
LOG="tjl_scanner_${DATE}.log"

TIME_ET=$(TZ='America/New_York' date '+%H:%M')
echo "=== TJL Scanner — $DATE $TIME_ET ET ===" | tee -a "$LOG"

send_telegram() {
    local msg="$1"
    local payload
    payload=$(python3 -c "import json,sys; print(json.dumps({'chat_id': ${TELEGRAM_CHAT_ID}, 'text': sys.argv[1], 'parse_mode': 'HTML'}))" "$msg")
    curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
        -H "Content-Type: application/json" -d "$payload" > /dev/null 2>&1
}

# =============================================================================
# Hauptlogik in Python (yfinance + TJL-Evaluation + State-Management)
# =============================================================================
RESULT=$(FORCE=$FORCE MCP_DATA="$MCP_DATA" python3 - "$GAPPERS_FILE" "$STATE_FILE" << 'PYEOF'
import sys, json, os, glob
from datetime import datetime
from zoneinfo import ZoneInfo

import yfinance as yf

ET = ZoneInfo("America/New_York")
BERLIN = ZoneInfo("Europe/Berlin")
gappers_file = sys.argv[1]
state_file = sys.argv[2]
force = os.environ.get("FORCE") == "1"

now_et = datetime.now(ET)

# --- Zeit-Gate: nur 10:00-15:30 ET (Markt offen, TJL sinnvoll) ---
market_open = now_et.replace(hour=10, minute=0, second=0, microsecond=0)
market_cut  = now_et.replace(hour=15, minute=30, second=0, microsecond=0)
in_window = market_open <= now_et <= market_cut
if not in_window and not force:
    print(json.dumps({"status": "outside_window", "time_et": now_et.strftime("%H:%M ET")}))
    sys.exit(0)

# --- Datenquelle: MCP (TradingView live) oder yfinance (Cronjob) ---
mcp_data_raw = os.environ.get("MCP_DATA", "")
mcp_data = json.loads(mcp_data_raw) if mcp_data_raw else None

if mcp_data:
    tickers = [d["symbol"] for d in mcp_data]
    universe_note = f"{len(tickers)} Gappers (TradingView MCP live)"
else:
    tickers = []
    try:
        with open(gappers_file) as f:
            gdata = json.load(f)
        tickers = [g["symbol"] for g in gdata.get("gappers", [])]
    except FileNotFoundError:
        pass
    if not tickers:
        tickers = ["AMD", "NVDA", "MU"]
        universe_note = "Fallback (keine Gappers heute)"
    else:
        universe_note = f"{len(tickers)} Gappers von Scanner A"

# --- TJL-Evaluation ---
def sma(values, period):
    if len(values) < period:
        return None
    return round(sum(values[-period:]) / period, 4)

def evaluate(curr_px, prev_high, prev_close, sma200, pmh, hod):
    if None in (curr_px, prev_high, prev_close, sma200):
        return "fail_no_data"
    daily_breakout = (curr_px > prev_high) and (prev_close > sma200)
    pmh_ok = (pmh is None) or (curr_px > pmh)
    hod_ok = (hod is None) or (curr_px > hod)
    intraday_breakout = pmh_ok and hod_ok and (pmh is not None or hod is not None)
    if daily_breakout and intraday_breakout:
        return "PASS"
    if not daily_breakout:
        return "fail_daily"
    return "fail_intraday"

results = []
hits = []

if mcp_data:
    # --- MCP-Modus: TradingView live-Daten von Claude ---
    for d in mcp_data:
        sym = d["symbol"]
        res = evaluate(d["curr_price"], d["prev_daily_high"], d["prev_daily_close"],
                       d["sma200"], d.get("pmh"), d.get("hod"))
        results.append({"symbol": sym, "result": res})
        if res == "PASS":
            hits.append({
                "symbol": sym, "curr_price": d["curr_price"],
                "prev_daily_high": round(d["prev_daily_high"], 2),
                "sma200": d["sma200"], "pmh": d.get("pmh"), "today_hod": d.get("hod"),
            })
else:
    # --- yfinance-Modus (Cronjob-Fallback) ---
    for sym in tickers:
        try:
            t = yf.Ticker(sym)

            daily = t.history(period="2y", interval="1d")
            if daily.empty or len(daily) < 50:
                results.append({"symbol": sym, "result": "fail_no_data"})
                continue
            daily_idx_et = daily.index.tz_convert(ET) if daily.index.tz else daily.index
            completed = daily[daily_idx_et.date < now_et.date()]
            if len(completed) < 50:
                completed = daily.iloc[:-1] if len(daily) > 1 else daily
            closes = completed["Close"].tolist()
            prev_high = float(completed["High"].iloc[-1])
            prev_close = float(completed["Close"].iloc[-1])
            sma200 = sma(closes, 200) or sma(closes, min(200, len(closes)))

            intra = t.history(period="2d", interval="1m", prepost=True)
            pmh = hod = curr_px = None
            if not intra.empty:
                intra.index = intra.index.tz_convert(ET)
                today = intra[intra.index.date == now_et.date()]
                if not today.empty:
                    pm = today[(today.index.hour >= 4) &
                               ((today.index.hour < 9) | ((today.index.hour == 9) & (today.index.minute < 30)))]
                    rs = today[((today.index.hour > 9) | ((today.index.hour == 9) & (today.index.minute >= 30))) &
                               (today.index.hour < 16)]
                    if not pm.empty:
                        pmh = round(float(pm["High"].max()), 2)
                    if not rs.empty:
                        hod = round(float(rs["High"].iloc[:-1].max()), 2) if len(rs) > 1 else round(float(rs["High"].max()), 2)
                    curr_px = round(float(today["Close"].iloc[-1]), 2)
            if curr_px is None:
                fi = t.fast_info
                curr_px = round(float(fi.get("last_price") or prev_close), 2)

            res = evaluate(curr_px, prev_high, prev_close, sma200, pmh, hod)
            results.append({"symbol": sym, "result": res})
            if res == "PASS":
                hits.append({
                    "symbol": sym, "curr_price": curr_px,
                    "prev_daily_high": round(prev_high, 2),
                    "sma200": sma200, "pmh": pmh, "today_hod": hod,
                })
        except Exception as e:
            results.append({"symbol": sym, "result": "error", "error": str(e)[:60]})

# --- Output-JSON speichern ---
out = {
    "scanned_at": datetime.now(BERLIN).isoformat(),
    "scan_time_et": now_et.strftime("%H:%M ET"),
    "universe": universe_note,
    "candidates_checked": len(tickers),
    "hits": hits,
    "all_results": results,
}
fname = f"tjl_watchlist_{datetime.now(BERLIN).strftime('%Y-%m-%d_%H%M')}_ET.json"
with open(fname, "w") as f:
    json.dump(out, f, indent=2)

# --- State: erster Lauf? neue PASS? ---
prev_passes = set()
first_run = True
if os.path.exists(state_file):
    first_run = False
    try:
        with open(state_file) as f:
            prev_passes = set(json.load(f).get("passed_symbols", []))
    except Exception:
        pass

current_passes = {h["symbol"] for h in hits}
new_passes = current_passes - prev_passes

# State aktualisieren (kumulativ über den Tag)
with open(state_file, "w") as f:
    json.dump({"passed_symbols": sorted(prev_passes | current_passes),
               "last_run_et": now_et.strftime("%H:%M ET")}, f)

# --- Entscheidung: Telegram senden? ---
send = first_run or bool(new_passes)

# --- Markt-Regime als HINWEIS (Step 10) — filtert NICHT, nur Empfehlung ---
# SPY & QQQ vs. SMA200: gibt dem Trader Kontext, blockiert aber keinen Einstieg.
def market_regime_line():
    parts = {}
    for idx in ("SPY", "QQQ"):
        try:
            c = yf.Ticker(idx).history(period="1y", interval="1d")["Close"].dropna().tolist()
            parts[idx] = (c[-1] > sum(c[-200:]) / 200) if len(c) >= 200 else None
        except Exception:
            parts[idx] = None
    spy, qqq = parts.get("SPY"), parts.get("QQQ")
    if spy is None and qqq is None:
        return ""
    if spy and qqq:
        tag = "🟢 Rückenwind — SPY &amp; QQQ über SMA200"
    elif spy is False and qqq is False:
        tag = "🔴 Gegenwind — SPY &amp; QQQ unter SMA200 (Vorsicht bei Longs)"
    else:
        s = "über" if spy else ("unter" if spy is False else "?")
        q = "über" if qqq else ("unter" if qqq is False else "?")
        tag = f"🟡 Gemischt — SPY {s}, QQQ {q} SMA200"
    return f"📈 Markt-Regime: {tag}"

regime_line = market_regime_line() if send else ""

decision = {
    "status": "ok",
    "time_et": now_et.strftime("%H:%M ET"),
    "universe_note": universe_note,
    "checked": len(tickers),
    "hits": hits,
    "all_results": results,
    "new_passes": sorted(new_passes),
    "first_run": first_run,
    "send": send,
    "regime_line": regime_line,
    "outfile": fname,
}
print(json.dumps(decision))
PYEOF
)

# =============================================================================
# Telegram-Nachricht bauen + senden (nur wenn send=true)
# =============================================================================
STATUS=$(echo "$RESULT" | python3 -c "import json,sys; print(json.load(sys.stdin).get('status',''))")

if [ "$STATUS" = "outside_window" ]; then
    TET=$(echo "$RESULT" | python3 -c "import json,sys; print(json.load(sys.stdin).get('time_et',''))")
    echo "Außerhalb Handelsfenster ($TET) — kein Lauf. (--force zum Erzwingen)" | tee -a "$LOG"
    exit 0
fi

echo "$RESULT" | python3 -c "
import json, sys
d = json.load(sys.stdin)
print(f\"  Geprüft: {d['checked']} ({d['universe_note']})\")
print(f\"  PASS: {len(d['hits'])}  |  Neue PASS: {len(d['new_passes'])}  |  Erster Lauf: {d['first_run']}\")
for r in d['all_results']:
    print(f\"    {r['symbol']}: {r['result']}\")
" | tee -a "$LOG"

SEND=$(echo "$RESULT" | python3 -c "import json,sys; print('1' if json.load(sys.stdin).get('send') else '0')")

if [ "$SEND" = "1" ]; then
    MSG=$(echo "$RESULT" | python3 -c "
import json, sys
d = json.load(sys.stdin)
lines = [f\"🎯 <b>TJL Scanner — {d['time_et']}</b>\"]
lines.append(f\"<i>{d['universe_note']}</i>\")
if d.get('regime_line'):
    lines.append(d['regime_line'])
lines.append('')
hits = d['hits']
if hits:
    lines.append(f\"<b>{len(hits)} PASS-Signal(e):</b>\")
    for h in hits:
        new = ' 🆕' if h['symbol'] in d['new_passes'] else ''
        lines.append(f\"✅ <b>{h['symbol']}</b>{new}  \${h['curr_price']}\")
        lines.append(f\"   Vortageshoch \${h['prev_daily_high']} | PMH \${h.get('pmh','—')} | HOD \${h.get('today_hod','—')} | SMA200 \${h['sma200']}\")
else:
    lines.append('Keine PASS-Signale in diesem Lauf.')
    fails = {}
    for r in d['all_results']:
        fails[r['result']] = fails.get(r['result'], 0) + 1
    summary = ', '.join(f'{k}: {v}' for k,v in fails.items())
    lines.append(f'<i>{summary}</i>')
print('\n'.join(lines))
")
    send_telegram "$MSG"
    echo "  Telegram gesendet." | tee -a "$LOG"
else
    echo "  Kein neues Signal — keine Telegram-Nachricht (Anti-Spam)." | tee -a "$LOG"
fi

# =============================================================================
# SCHRITT 4: Exit-Überwachung (Position-Tracker)
# Öffnet bei neuem PASS eine beobachtete Position, überwacht Teilgewinn /
# Trailing Stop / EOD und sendet Exit-Alerts.
# =============================================================================
echo "--- Schritt 4: Exit-Überwachung ---" | tee -a "$LOG"
FORCE_FLAG=""
[ "$FORCE" = "1" ] && FORCE_FLAG="--force"
python3 "$(dirname "$0")/position_tracker.py" $FORCE_FLAG 2>&1 | tee -a "$LOG"

echo "=== TJL Scanner fertig ===" | tee -a "$LOG"
