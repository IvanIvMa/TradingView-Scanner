#!/usr/bin/env bash
# =============================================================================
# Daily Scanner v2 — Yahoo Top 100 Gainers + echte Premarket-Daten + Telegram
# =============================================================================
# Läuft täglich Mo-Fr um 15:00 Berlin (= 9:00 ET, 30 Min vor US-Öffnung).
#
# Ablauf:
#   1. Yahoo Screener API → Top 100 Tagesgewinner (Symbol-Vorauswahl)
#   2. yfinance Batch-Download 1-Min-Bars mit Premarket-Daten
#   3. Eigene Premarket-Berechnung mit ET-Zeitstempel-Filter
#      - Vortag-Close: letzte Bar vor 16:00 ET
#      - Premarket: Bars zwischen 4:00 und 9:30 ET heute
#   4. Filter: Gap>5%, Preis>$3, Premarket-Volumen>50K
#   5. News-Katalysator via Google News RSS
#   6. Telegram-Bericht mit Vergleich Premarket-Gap vs. Yahoo-Anzeige
# =============================================================================

set -euo pipefail
cd "$(dirname "$0")"
ulimit -n 4096 2>/dev/null || true

if [ ! -f .env ]; then
    echo "FEHLER: .env Datei nicht gefunden" >&2
    exit 1
fi
export $(grep -v '^#' .env | xargs)

if [ -z "${TELEGRAM_BOT_TOKEN:-}" ] || [ -z "${TELEGRAM_CHAT_ID:-}" ]; then
    echo "FEHLER: TELEGRAM_BOT_TOKEN und TELEGRAM_CHAT_ID müssen in .env gesetzt sein" >&2
    exit 1
fi

DATE=$(date +%Y-%m-%d)
TIME=$(date +%H:%M)
OUTFILE="premarket_gappers_${DATE}.json"
LOG="daily_scanner_${DATE}.log"

echo "=== Daily Scanner v2 — $DATE $TIME ===" | tee "$LOG"

send_telegram() {
    local msg="$1"
    local payload
    payload=$(python3 -c "import json,sys; print(json.dumps({'chat_id': ${TELEGRAM_CHAT_ID}, 'text': sys.argv[1], 'parse_mode': 'HTML'}))" "$msg")
    curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
        -H "Content-Type: application/json" -d "$payload" > /dev/null 2>&1
}

fetch_catalyst() {
    local symbol="$1"
    local headline
    headline=$(curl -s --max-time 10 \
        "https://news.google.com/rss/search?q=${symbol}+stock&hl=en-US&gl=US&ceid=US:en" \
        | grep -o '<title>[^<]*</title>' | sed 's/<[^>]*>//g' \
        | grep -vi "Google News" | head -1)
    echo "${headline:-}"
}

# =============================================================================
# SCHRITT 1: Top 100 Gainers von Yahoo Screener + echte Premarket-Berechnung
# =============================================================================
echo "" | tee -a "$LOG"
echo "--- Schritt 1: Top 100 Gainers + Premarket-Daten ---" | tee -a "$LOG"

# 1a. Yahoo Screener via curl (umgeht SSL-Probleme in Python 3.14)
SCREENER_JSON=$(curl -s --max-time 15 \
    "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved?scrIds=day_gainers&count=100" \
    -H "User-Agent: Mozilla/5.0")

python3 - "$OUTFILE" "$SCREENER_JSON" << 'PYEOF'
import sys, json, subprocess
from datetime import datetime
from zoneinfo import ZoneInfo

import yfinance as yf

BERLIN = ZoneInfo("Europe/Berlin")
ET = ZoneInfo("America/New_York")
outfile = sys.argv[1]

MIN_GAP = 5.0
MIN_PRICE = 3.0
MIN_VOLUME = 50_000
TOP_N = 10

# Yahoo Screener Daten vom Shell-Script
yahoo_data = json.loads(sys.argv[2])

yahoo_quotes = yahoo_data.get("finance", {}).get("result", [{}])[0].get("quotes", [])
print(f"  Yahoo Screener: {len(yahoo_quotes)} Top-Gainer geladen")

# Yahoo's Gap-Anzeige für Vergleich merken
yahoo_pct_map = {}
tickers = []
for q in yahoo_quotes:
    sym = q.get("symbol")
    if not sym:
        continue
    # Forex-Paare, Krypto, Indices ausschließen
    if any(c in sym for c in ["=", "^", "-"]):
        continue
    tickers.append(sym)
    yahoo_pct_map[sym] = float(q.get("regularMarketChangePercent") or 0)

print(f"  {len(tickers)} Aktien-Ticker (ohne FX/Krypto/Indices)")

# --- 1b. Batch-Download 1-Min-Bars MIT Premarket (in Chunks) ---
import pandas as pd
CHUNK = 25
print(f"  Lade 1-Min-Bars mit Premarket-Daten (~30 Sek)...")
chunks = [tickers[i:i+CHUNK] for i in range(0, len(tickers), CHUNK)]
frames = {}
for chunk in chunks:
    d = yf.download(chunk, period="2d", interval="1m", prepost=True,
                    progress=False, group_by="ticker", threads=True, auto_adjust=False)
    if len(chunk) == 1:
        frames[chunk[0]] = d
    else:
        for sym in chunk:
            if sym in d.columns.get_level_values(0):
                frames[sym] = d[sym]
data = frames

# --- 1c. Eigene Premarket-Berechnung ---
today_et = datetime.now(ET).date()

# ISIN-Mapping laden (nur für Endreport)
import os
isin_path = os.path.join(os.path.dirname(outfile) or ".", "ticker_isin.json")
try:
    with open(isin_path) as f:
        isin_map = json.load(f)
except FileNotFoundError:
    isin_map = {}

# Fehlende ISINs für die heutigen Top-Gainer automatisch nachladen
new_isins = 0
for sym in tickers:
    if sym not in isin_map or not isin_map.get(sym):
        try:
            isin = yf.Ticker(sym).isin
            if isin and isin not in ("-", "N/A"):
                isin_map[sym] = isin
                new_isins += 1
            else:
                isin_map[sym] = None
        except Exception:
            isin_map[sym] = None
if new_isins:
    with open(isin_path, "w") as f:
        json.dump(isin_map, f, indent=2)
    print(f"  {new_isins} neue ISINs nachgeladen")

results = []
for sym in tickers:
    try:
        df = data.get(sym)
        if df is None:
            continue
        df = df.dropna()
        if df.empty:
            continue
        df.index = df.index.tz_convert(ET)

        # Vortag-Close: letzte Bar VOR 16:00 ET (regulärer Schluss, KEIN After-Hours)
        yesterday = df[df.index.date < today_et]
        reg_yesterday = yesterday[yesterday.index.hour < 16]
        if reg_yesterday.empty:
            continue
        prev_close = float(reg_yesterday["Close"].iloc[-1])

        # Heute: Premarket-Fenster 4:00-9:30 ET
        today = df[df.index.date == today_et]
        premarket = today[
            (today.index.hour >= 4) &
            ((today.index.hour < 9) | ((today.index.hour == 9) & (today.index.minute < 30)))
        ]
        # Heute: Regular Session ab 9:30 ET
        regular = today[
            ((today.index.hour > 9) | ((today.index.hour == 9) & (today.index.minute >= 30))) &
            (today.index.hour < 16)
        ]

        pm_price = pm_volume = pm_time = None
        if not premarket.empty:
            pm_price = float(premarket["Close"].iloc[-1])
            pm_volume = int(premarket["Volume"].sum())
            pm_time = premarket.index[-1].strftime("%H:%M ET")

        intraday_price = intraday_time = None
        if not regular.empty:
            intraday_price = float(regular["Close"].iloc[-1])
            intraday_time = regular.index[-1].strftime("%H:%M ET")

        # Premarket-Gap (echte Definition)
        if pm_price:
            pm_gap = round((pm_price - prev_close) / prev_close * 100, 2)
        else:
            pm_gap = None

        # Intraday-Performance (für Vergleich)
        if intraday_price:
            intraday_gap = round((intraday_price - prev_close) / prev_close * 100, 2)
        else:
            intraday_gap = None

        # Yahoo's eigene Anzeige
        yahoo_gap = round(yahoo_pct_map.get(sym, 0), 2)

        results.append({
            "symbol": sym,
            "isin": isin_map.get(sym),
            "prev_close": round(prev_close, 2),
            "premarket_price": round(pm_price, 2) if pm_price else None,
            "premarket_volume": pm_volume,
            "premarket_time": pm_time,
            "premarket_gap_pct": pm_gap,
            "intraday_price": round(intraday_price, 2) if intraday_price else None,
            "intraday_time": intraday_time,
            "intraday_gap_pct": intraday_gap,
            "yahoo_displayed_gap_pct": yahoo_gap,
        })
    except Exception as e:
        print(f"  ! {sym}: {e}", file=sys.stderr)

# --- 1d. Filter ---
# Logik: nutze Premarket-Gap wenn verfügbar, sonst Intraday-Gap.
# Volumen-Filter: Premarket-Volumen ODER (wenn keine PM-Daten) Tagesvolumen.
def get_effective_gap(r):
    return r["premarket_gap_pct"] if r["premarket_gap_pct"] is not None else r["intraday_gap_pct"]

def get_effective_price(r):
    return r["premarket_price"] or r["intraday_price"] or r["prev_close"]

# Aktuelle ET-Zeit prüfen: Sind wir VOR 9:30 ET? Dann ist es echtes Premarket-Scanning
now_et = datetime.now(ET)
is_premarket_window = (now_et.hour < 9) or (now_et.hour == 9 and now_et.minute < 30)

filtered = []
for r in results:
    gap = get_effective_gap(r)
    price = get_effective_price(r)
    if gap is None or price is None:
        continue
    if gap <= MIN_GAP or price <= MIN_PRICE:
        continue

    pm_vol = r["premarket_volume"] or 0
    if r["premarket_gap_pct"] is not None and pm_vol > MIN_VOLUME:
        r["filter_mode"] = "premarket"
    elif r["premarket_gap_pct"] is not None:
        # Premarket-Gap da aber Volumen niedrig — markieren aber durchlassen
        r["filter_mode"] = "premarket_lowvol"
    elif is_premarket_window:
        # Wir sind im PM-Fenster aber Ticker hat keine PM-Bars (illiquide)
        continue
    else:
        # Markt offen, kein Premarket möglich → Intraday-Modus
        r["filter_mode"] = "intraday"
    filtered.append(r)

# Sortieren nach Premarket-Gap (oder Intraday wenn Premarket fehlt)
filtered.sort(key=lambda r: get_effective_gap(r), reverse=True)
filtered = filtered[:TOP_N]
for i, r in enumerate(filtered, 1):
    r["rank"] = i

result_obj = {
    "scanned_at": datetime.now(BERLIN).isoformat(),
    "scan_time_et": datetime.now(ET).strftime("%H:%M ET"),
    "universe_source": "Yahoo Screener day_gainers (Top 100)",
    "universe_size": len(tickers),
    "filters": {
        "min_gap_pct": MIN_GAP,
        "min_price": MIN_PRICE,
        "min_premarket_volume": MIN_VOLUME,
        "top_n": TOP_N,
    },
    "gappers": filtered,
}
with open(outfile, "w") as f:
    json.dump(result_obj, f, indent=2)

print(f"\n  {len(filtered)} Gappers nach Filter:")
for r in filtered:
    pm = r["premarket_gap_pct"]
    yh = r["yahoo_displayed_gap_pct"]
    mode = r["filter_mode"]
    if pm is not None:
        print(f"    {r['rank']}. {r['symbol']:6s} Premarket: {pm:+.2f}%  Yahoo zeigt: {yh:+.2f}%  Diff: {(pm-yh):+.2f}pp  [{mode}]")
    else:
        intra = r["intraday_gap_pct"]
        print(f"    {r['rank']}. {r['symbol']:6s} Intraday: {intra:+.2f}% (kein Premarket)  Yahoo: {yh:+.2f}%  [{mode}]")
PYEOF

echo "" | tee -a "$LOG"

# =============================================================================
# SCHRITT 2: News-Katalysator für jeden Gapper holen
# =============================================================================
echo "--- Schritt 2: News-Katalysatoren (Google News RSS) ---" | tee -a "$LOG"

TICKERS=$(python3 -c "
import json
with open('$OUTFILE') as f:
    data = json.load(f)
for g in data.get('gappers', []):
    print(g['symbol'])
")

if [ -n "$TICKERS" ]; then
    for SYM in $TICKERS; do
        CATALYST=$(fetch_catalyst "$SYM")
        if [ -n "$CATALYST" ]; then
            echo "  $SYM: $CATALYST" | tee -a "$LOG"
        else
            echo "  $SYM: (kein Katalysator gefunden)" | tee -a "$LOG"
            CATALYST=""
        fi
        python3 -c "
import json, sys
sym, cat = sys.argv[1], sys.argv[2]
with open('$OUTFILE') as f:
    data = json.load(f)
for g in data.get('gappers', []):
    if g['symbol'] == sym:
        g['catalyst'] = cat if cat else None
        g['catalyst_source'] = 'Google News RSS'
with open('$OUTFILE', 'w') as f:
    json.dump(data, f, indent=2)
" "$SYM" "$CATALYST"
    done
fi

echo "" | tee -a "$LOG"

# =============================================================================
# SCHRITT 3: Telegram-Bericht mit ISIN + Vergleich Premarket vs. Yahoo
# =============================================================================
echo "--- Schritt 3: Telegram senden ---" | tee -a "$LOG"

MSG=$(python3 - "$OUTFILE" << 'PYEOF'
import json, sys
from datetime import datetime
from zoneinfo import ZoneInfo

BERLIN = ZoneInfo("Europe/Berlin")
now = datetime.now(BERLIN).strftime("%d.%m.%Y %H:%M")

with open(sys.argv[1]) as f:
    data = json.load(f)

gappers = data.get("gappers", [])

lines = [f"📊 <b>Daily Premarket Report — {now} CEST</b>"]
lines.append(f"<i>Universe: {data.get('universe_size', '?')} Aktien (Yahoo Top Gainers)</i>\n")

if gappers:
    has_premarket = any(g.get("premarket_gap_pct") is not None for g in gappers)
    if has_premarket:
        lines.append(f"<b>{len(gappers)} Gappers gefunden:</b>")
    else:
        lines.append(f"<b>{len(gappers)} Gappers (Markt offen — Intraday-Daten):</b>")
    lines.append("")

    for g in gappers:
        sym = g["symbol"]
        isin = g.get("isin") or "—"
        pm = g.get("premarket_gap_pct")
        yh = g.get("yahoo_displayed_gap_pct")
        intra = g.get("intraday_gap_pct")
        pm_time = g.get("premarket_time")
        pm_vol = g.get("premarket_volume") or 0
        price = g.get("premarket_price") or g.get("intraday_price") or g.get("prev_close")

        # Volumen formatieren
        if pm_vol > 1_000_000:
            vol_str = f"{pm_vol/1_000_000:.1f}M"
        elif pm_vol > 1000:
            vol_str = f"{pm_vol/1000:.0f}K"
        else:
            vol_str = f"{pm_vol}"

        # Hauptzeile
        if pm is not None:
            diff = pm - yh
            diff_str = f" (Yahoo: {yh:+.2f}%, Δ {diff:+.2f}pp)" if abs(diff) > 0.5 else ""
            lines.append(f"<b>{g['rank']}. {sym}</b> ({isin})")
            lines.append(f"   Premarket: <b>{pm:+.2f}%</b> ${price:.2f} @ {pm_time}{diff_str}")
            lines.append(f"   PM-Volumen: {vol_str}")
        else:
            lines.append(f"<b>{g['rank']}. {sym}</b> ({isin})")
            lines.append(f"   Intraday: <b>{intra:+.2f}%</b> ${price:.2f}  (kein Premarket-Volumen)")

        # Katalysator
        cat = g.get("catalyst")
        if cat:
            lines.append(f"   📰 <i>{cat[:75]}</i>")
        lines.append("")
else:
    lines.append("Keine Gappers nach Filter (Gap>5%, Preis>$3)")

# Hinweis: TJL (Scanner B) läuft separat während der Handelszeit (tjl_scanner.sh),
# nicht hier. Scanner A liefert nur die Premarket-Kandidaten.
lines.append(f"\n<i>Premarket selbst berechnet (4:00-9:30 ET) | Universe: Yahoo Top 100</i>")
lines.append(f"<i>TJL-Signale folgen ab 16:00 Berlin (Scanner B, bei Markteröffnung)</i>")
print("\n".join(lines))
PYEOF
)

send_telegram "$MSG"
echo "  Telegram gesendet!" | tee -a "$LOG"
echo "" | tee -a "$LOG"
echo "=== Daily Scanner v2 fertig ===" | tee -a "$LOG"
