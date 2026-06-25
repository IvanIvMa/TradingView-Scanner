#!/usr/bin/env bash
# Premarket Gappers Scanner (Step 5) — nach Humbled Trader Anleitung
# Holt Yahoo Finance Gainers, filtert, holt Benzinga-Catalyst pro Ticker.
# Nutzung: bash premarket_gappers.sh

set -euo pipefail
cd "$(dirname "$0")"

DATE=$(date +%Y-%m-%d)
OUTFILE="premarket_gappers_${DATE}.json"

echo "=== Premarket Gappers Scanner — $DATE ==="
echo ""

python3 - "$OUTFILE" << 'PYEOF'
import sys, json, re, urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

BERLIN = ZoneInfo("Europe/Berlin")

outfile = sys.argv[1]

MIN_GAP = 5.0
MIN_PRICE = 3.0
MIN_VOLUME = 50000
TOP_N = 10

def fetch_url(url):
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
        })
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.read().decode("utf-8", errors="replace")
    except Exception:
        return None

def fetch_catalyst(symbol):
    url = f"https://www.benzinga.com/quote/{symbol}"
    try:
        html = fetch_url(url)
        if not html:
            return None, []
        # Verschiedene Patterns für Benzinga Headlines
        patterns = [
            r'class="[^"]*news-title[^"]*"[^>]*>(.*?)</a>',
            r'<h3[^>]*class="[^"]*headline[^"]*"[^>]*>(.*?)</h3>',
            r'"headline":"([^"]+)"',
        ]
        headlines = []
        for pat in patterns:
            found = re.findall(pat, html, re.DOTALL)
            if found:
                headlines = [re.sub(r'<[^>]+>', '', h).strip() for h in found[:2]]
                break
        catalyst = headlines[0] if headlines else None
        return catalyst, headlines
    except Exception:
        return None, []

# --- Hauptprogramm ---
import yfinance as yf

print(f"Filter: gap>{MIN_GAP}%, price>${MIN_PRICE}, volume>{MIN_VOLUME}")
print("Hole Gainers-Daten via yfinance...\n")

# Screener: Top US Gainers
# yfinance hat keinen eingebauten Screener, daher nutzen wir eine breite Liste
# und berechnen den Gap selbst
universe = [
    "BFLY","WOLF","QS","BE","OUST","ACMR","ENTG","SMR","CHRN","KMX",
    "EQPT","PENG","LEU","ALAB","SEZL","HIMS","GLW","CIFR","JBLU","UMC",
    "INTC","AAPL","NVDA","AMD","TSLA","MU","PLTR","SOFI","AMC","GME",
    "RIVN","LCID","NIO","F","BAC","MARA","RIOT","COIN","HOOD","SQ",
    "SNAP","UBER","LYFT","DIS","NFLX","META","GOOG","AMZN","MSFT",
    "ORCL","CRM","SHOP","SNOW","DDOG","NET","ZS","CRWD","PANW",
]

rows = []
for sym in universe:
    try:
        t = yf.Ticker(sym)
        fi = t.fast_info
        prev = float(fi.get("previous_close", 0) or fi.get("previousClose", 0) or 0)
        last = float(fi.get("last_price", 0) or fi.get("lastPrice", 0) or 0)
        vol = int(fi.get("last_volume", 0) or fi.get("lastVolume", 0) or 0)
        if prev > 0 and last > 0:
            gap = round((last - prev) / prev * 100, 2)
            if gap > 0:
                rows.append({
                    "symbol": sym,
                    "price": round(last, 2),
                    "gap_pct": gap,
                    "premarket_volume": vol,
                })
    except Exception as e:
        print(f"  ! {sym}: {e}", file=sys.stderr)

print(f"  {len(rows)} Ticker mit positivem Gap gefunden")

# Filter
filtered = [
    r for r in rows
    if r["gap_pct"] > MIN_GAP
    and r["price"] > MIN_PRICE
    and r["premarket_volume"] > MIN_VOLUME
]
filtered.sort(key=lambda r: r["gap_pct"], reverse=True)
filtered = filtered[:TOP_N]

print(f"  {len(filtered)} Gappers nach Filter\n")

# News-Catalyst
if filtered:
    print("Hole News-Catalyst von Benzinga...")
    for i, r in enumerate(filtered, 1):
        r["rank"] = i
        sym = r["symbol"]
        print(f"  [{i}/{len(filtered)}] {sym}...", end=" ", flush=True)
        catalyst, headlines = fetch_catalyst(sym)
        r["catalyst"] = catalyst
        r["headlines"] = headlines
        print(catalyst[:60] if catalyst else "kein Catalyst")

# Speichern
result = {
    "scanned_at": datetime.now(BERLIN).isoformat(),
    "filters": {
        "min_gap_pct": MIN_GAP,
        "min_price": MIN_PRICE,
        "min_premarket_volume": MIN_VOLUME,
        "top_n": TOP_N,
    },
    "gappers": filtered,
}
with open(outfile, "w") as f:
    json.dump(result, f, indent=2)

# Summary
print(f"\nGespeichert: {outfile}")
if filtered:
    top3 = ", ".join(
        f"{r['symbol']} ({r['gap_pct']}%)"
        + (f" — {r['catalyst'][:40]}" if r.get("catalyst") else "")
        for r in filtered[:3]
    )
    print(f"Premarket Gappers: {len(filtered)} names. Top: {top3}")
else:
    print("Keine Gappers gefunden (Markt evtl. geschlossen / Wochenende).")
PYEOF

echo ""
echo "=== Scanner A fertig ==="
