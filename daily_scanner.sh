#!/usr/bin/env bash
# =============================================================================
# Daily Scanner v3 — Yahoo Top 100 Gainers + echte Premarket-Daten + Telegram
# =============================================================================
# Läuft täglich Mo-Fr:
#   - 15:00 Berlin (= 9:00 ET) → Premarket-Scan (30 Min vor US-Öffnung)
#   - 15:45 Berlin (= 9:45 ET) → Merge-Scan (nach Marktöffnung, neue Ticker ergänzen)
#
# Ablauf:
#   1. Yahoo Screener API → Top 100 Tagesgewinner (Symbol-Vorauswahl)
#   2. yfinance Batch-Download 1-Min-Bars mit Premarket-Daten
#   3. Eigene Premarket-Berechnung mit ET-Zeitstempel-Filter
#   4. Filter: Gap>5%, Preis>$3, Premarket-Volumen>50K
#   5. News-Katalysator via Google News RSS
#   6. Telegram-Bericht mit Vergleich Premarket-Gap vs. Yahoo-Anzeige
#
# Nutzung:
#   bash daily_scanner.sh            # normaler Lauf (überschreibt)
#   bash daily_scanner.sh --merge    # ergänzt nur neue Ticker zur bestehenden Liste
# =============================================================================

set -euo pipefail
cd "$(dirname "$0")"
ulimit -n 4096 2>/dev/null || true

MERGE=0
FORCE=0
while [ $# -gt 0 ]; do
    case "$1" in
        --merge) MERGE=1 ;;
        --force) FORCE=1 ;;
    esac
    shift
done

if [ ! -f .env ]; then
    echo "FEHLER: .env Datei nicht gefunden" >&2
    exit 1
fi
export $(grep -v '^#' .env | xargs)

if [ -z "${TELEGRAM_BOT_TOKEN:-}" ] || [ -z "${TELEGRAM_CHAT_ID:-}" ]; then
    echo "FEHLER: TELEGRAM_BOT_TOKEN und TELEGRAM_CHAT_ID müssen in .env gesetzt sein" >&2
    exit 1
fi

# =============================================================================
# DST-robustes ET-Gate
# =============================================================================
# launchd plant in Berlin-Zeit. Weil EU/US die Sommerzeit an verschiedenen
# Tagen umschalten (8.-29. März, 25. Okt-1. Nov), driftet die Berlin->ET-
# Umrechnung in diesen Wochen um +1h. Deshalb feuern die launchd-Jobs zu ZWEI
# Berlin-Zeiten (Normal- + Gap-Woche); dieses Gate lässt nur den Lauf durch,
# der wirklich die Ziel-ET-Zeit trifft. --force umgeht das (manuelle Läufe).
#   Premarket-Lauf (kein --merge): Soll 9:00 ET  -> Fenster 8:30-9:29 ET
#   Merge-Lauf     (--merge):      Soll 9:45 ET  -> Fenster 9:30-10:29 ET
if [ "$FORCE" != "1" ]; then
    GATE=$(MERGE=$MERGE python3 - << 'PYEOF'
import os
from datetime import datetime
from zoneinfo import ZoneInfo
now = datetime.now(ZoneInfo("America/New_York"))
mins = now.hour * 60 + now.minute
if os.environ.get("MERGE") == "1":
    ok = (9*60+30) <= mins <= (10*60+29)
else:
    ok = (8*60+30) <= mins <= (9*60+29)
print(f"{'OK' if ok else 'SKIP'}|{now.strftime('%H:%M')}")
PYEOF
)
    if [ "${GATE%%|*}" = "SKIP" ]; then
        echo "DST-Gate: ${GATE##*|} ET außerhalb Soll-Fenster — Lauf übersprungen (--force erzwingt)."
        exit 0
    fi
fi

DATE=$(date +%Y-%m-%d)
TIME=$(date +%H:%M)
OUTFILE="premarket_gappers_${DATE}.json"
LOG="daily_scanner_${DATE}.log"

if [ "$MERGE" = "1" ]; then
    echo "=== Daily Scanner v3 (MERGE) — $DATE $TIME ===" | tee -a "$LOG"
else
    echo "=== Daily Scanner v3 — $DATE $TIME ===" | tee "$LOG"
fi

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

MERGE_FLAG=$MERGE python3 - "$OUTFILE" "$SCREENER_JSON" << 'PYEOF'
import sys, json, subprocess, os
from datetime import datetime
from zoneinfo import ZoneInfo

import yfinance as yf

BERLIN = ZoneInfo("Europe/Berlin")
ET = ZoneInfo("America/New_York")
outfile = sys.argv[1]
merge_mode = os.environ.get("MERGE_FLAG") == "1"

MIN_GAP = 5.0
MIN_PRICE = 3.0
MIN_VOLUME = 50_000
TOP_N = 10

# Im Merge-Modus: bestehende Ticker laden um Duplikate zu vermeiden
existing_symbols = set()
existing_gappers = []
if merge_mode and os.path.exists(outfile):
    with open(outfile) as f:
        prev = json.load(f)
    existing_gappers = prev.get("gappers", [])
    existing_symbols = {g["symbol"] for g in existing_gappers}
    print(f"  MERGE-Modus: {len(existing_symbols)} bestehende Gappers werden beibehalten")

# Yahoo Screener Daten vom Shell-Script
yahoo_data = json.loads(sys.argv[2])

yahoo_quotes = yahoo_data.get("finance", {}).get("result", [{}])[0].get("quotes", [])
print(f"  Yahoo Screener: {len(yahoo_quotes)} Top-Gainer geladen")

# Yahoo's Gap-Anzeige für Vergleich merken
yahoo_pct_map = {}
yahoo_name_map = {}
tickers = []
for q in yahoo_quotes:
    sym = q.get("symbol")
    if not sym:
        continue
    if any(c in sym for c in ["=", "^", "-"]):
        continue
    tickers.append(sym)
    yahoo_pct_map[sym] = float(q.get("regularMarketChangePercent") or 0)
    yahoo_name_map[sym] = q.get("shortName") or q.get("longName") or ""

# Im Merge-Modus: Firmennamen für alte Gappers nachpflegen
if merge_mode and existing_gappers:
    missing_name_syms = [g["symbol"] for g in existing_gappers
                         if not g.get("name") and g["symbol"] not in yahoo_name_map]
    if missing_name_syms:
        for ms in missing_name_syms:
            try:
                ti = yf.Ticker(ms)
                n = (ti.info or {}).get("shortName") or (ti.info or {}).get("longName") or ""
                if n:
                    yahoo_name_map[ms] = n
            except Exception:
                pass
    for g in existing_gappers:
        if not g.get("name") and g["symbol"] in yahoo_name_map:
            g["name"] = yahoo_name_map[g["symbol"]]

print(f"  {len(tickers)} Aktien-Ticker (ohne FX/Krypto/Indices)")

# Im Merge-Modus: nur neue Ticker downloaden
if merge_mode:
    new_tickers = [t for t in tickers if t not in existing_symbols]
    print(f"  Davon NEU (nicht im 15:00-Lauf): {len(new_tickers)}")
    if not new_tickers:
        print("  Keine neuen Ticker — nichts zu tun.")
        # Bestehende Datei unverändert lassen
        sys.exit(0)
    tickers = new_tickers

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
            "name": yahoo_name_map.get(sym, ""),
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

# Im Merge-Modus: neue Gappers an bestehende anhängen, nach Gap neu sortieren
if merge_mode and existing_gappers:
    merged = existing_gappers + filtered
    merged.sort(key=lambda r: get_effective_gap(r) or 0, reverse=True)
    merged = merged[:TOP_N]
    new_count = len(filtered)
else:
    merged = filtered
    new_count = len(filtered)

for i, r in enumerate(merged, 1):
    r["rank"] = i

universe_src = "Yahoo Screener day_gainers (Top 100)"
if merge_mode:
    universe_src += " — MERGE (15:45 Ergänzung)"

result_obj = {
    "scanned_at": datetime.now(BERLIN).isoformat(),
    "scan_time_et": datetime.now(ET).strftime("%H:%M ET"),
    "universe_source": universe_src,
    "universe_size": len(tickers) + len(existing_symbols),
    "filters": {
        "min_gap_pct": MIN_GAP,
        "min_price": MIN_PRICE,
        "min_premarket_volume": MIN_VOLUME,
        "top_n": TOP_N,
    },
    "gappers": merged,
}
if merge_mode:
    result_obj["merge_new_gappers"] = new_count

with open(outfile, "w") as f:
    json.dump(result_obj, f, indent=2)

if merge_mode:
    print(f"\n  {new_count} NEUE Gappers gefunden, {len(merged)} gesamt nach Merge:")
else:
    print(f"\n  {len(merged)} Gappers nach Filter:")
for r in merged:
    pm = r.get("premarket_gap_pct")
    yh = r.get("yahoo_displayed_gap_pct", 0)
    mode = r.get("filter_mode", "?")
    is_new = merge_mode and r["symbol"] not in existing_symbols
    marker = " 🆕" if is_new else ""
    if pm is not None:
        print(f"    {r['rank']}. {r['symbol']:6s} Premarket: {pm:+.2f}%  Yahoo zeigt: {yh:+.2f}%  [{mode}]{marker}")
    else:
        intra = r.get("intraday_gap_pct", 0)
        print(f"    {r['rank']}. {r['symbol']:6s} Intraday: {intra:+.2f}% (kein Premarket)  [{mode}]{marker}")
PYEOF

echo "" | tee -a "$LOG"

# =============================================================================
# SCHRITT 2: News-Katalysator für jeden Gapper holen
# =============================================================================
echo "--- Schritt 2: News-Katalysatoren (Google News RSS) ---" | tee -a "$LOG"

# Nur Gappers ohne Katalysator (im Merge: nur die neuen)
TICKERS=$(python3 -c "
import json
with open('$OUTFILE') as f:
    data = json.load(f)
for g in data.get('gappers', []):
    if not g.get('catalyst'):
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

MSG=$(MERGE_FLAG=$MERGE python3 - "$OUTFILE" << 'PYEOF'
import json, sys, os
from datetime import datetime
from zoneinfo import ZoneInfo

BERLIN = ZoneInfo("Europe/Berlin")
now = datetime.now(BERLIN).strftime("%d.%m.%Y %H:%M")
is_merge = os.environ.get("MERGE_FLAG") == "1"

with open(sys.argv[1]) as f:
    data = json.load(f)

gappers = data.get("gappers", [])
new_count = data.get("merge_new_gappers", 0)

if is_merge and new_count == 0:
    print("")
    sys.exit(0)

if is_merge:
    lines = [f"🔄 <b>Scanner A UPDATE — {now} CEST</b>"]
    lines.append(f"<i>{new_count} neue Gappers nach Marktöffnung entdeckt!</i>\n")
else:
    lines = [f"📊 <b>Daily Premarket Report — {now} CEST</b>"]
    lines.append(f"<i>Universe: {data.get('universe_size', '?')} Aktien (Yahoo Top Gainers)</i>\n")

if gappers:
    if not is_merge:
        has_premarket = any(g.get("premarket_gap_pct") is not None for g in gappers)
        if has_premarket:
            lines.append(f"<b>{len(gappers)} Gappers gefunden:</b>")
        else:
            lines.append(f"<b>{len(gappers)} Gappers (Markt offen — Intraday-Daten):</b>")
    else:
        lines.append(f"<b>Aktualisierte Liste ({len(gappers)} Gappers):</b>")
    lines.append("")

    for g in gappers:
        sym = g["symbol"]
        name = g.get("name") or ""
        isin = g.get("isin") or "—"
        isin_part = f" ({isin})" if isin != "—" else ""
        name_part = f" — {name}" if name else ""
        pm = g.get("premarket_gap_pct")
        yh = g.get("yahoo_displayed_gap_pct", 0)
        intra = g.get("intraday_gap_pct")
        pm_time = g.get("premarket_time")
        pm_vol = g.get("premarket_volume") or 0
        price = g.get("premarket_price") or g.get("intraday_price") or g.get("prev_close")

        if pm_vol > 1_000_000:
            vol_str = f"{pm_vol/1_000_000:.1f}M"
        elif pm_vol > 1000:
            vol_str = f"{pm_vol/1000:.0f}K"
        else:
            vol_str = str(pm_vol) if pm_vol > 0 else ""

        new_marker = " 🆕" if (is_merge and not g.get("catalyst_source")) else ""

        if pm is not None:
            diff = pm - yh
            diff_str = f" (Yahoo: {yh:+.2f}%, Δ {diff:+.2f}pp)" if abs(diff) > 0.5 else ""
            lines.append(f"<b>{g['rank']}. {sym}</b>{name_part}{isin_part}{new_marker}")
            vol_line = f"   PM-Vol: {vol_str}" if vol_str else ""
            lines.append(f"   Premarket: <b>{pm:+.2f}%</b> ${price:.2f} @ {pm_time}{diff_str}{vol_line}")
        else:
            lines.append(f"<b>{g['rank']}. {sym}</b>{name_part}{isin_part}{new_marker}")
            lines.append(f"   Intraday: <b>{intra:+.2f}%</b> ${price:.2f}")

        cat = g.get("catalyst")
        benz = g.get("catalyst_benzinga")
        if benz:
            lines.append(f"   📰 <i>{benz[:75]}</i> <b>[Benzinga]</b>")
        elif cat:
            lines.append(f"   📰 <i>{cat[:75]}</i>")
        lines.append("")
else:
    lines.append("Keine Gappers nach Filter (Gap>5%, Preis>$3)")

if is_merge:
    lines.append(f"\n<i>15:45-Ergänzung: Yahoo-Screener nach Marktöffnung aktualisiert</i>")
else:
    lines.append(f"\n<i>Premarket selbst berechnet (4:00-9:30 ET) | Universe: Yahoo Top 100</i>")
    lines.append(f"<i>TJL-Signale folgen ab 16:00 Berlin (Scanner B, bei Markteröffnung)</i>")
print("\n".join(lines))
PYEOF
)

if [ -n "$MSG" ]; then
    send_telegram "$MSG"
    echo "  Telegram gesendet!" | tee -a "$LOG"
else
    echo "  Merge: keine neuen Gappers — kein Telegram." | tee -a "$LOG"
fi
echo "" | tee -a "$LOG"
echo "=== Daily Scanner v3 fertig ===" | tee -a "$LOG"
