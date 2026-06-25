#!/usr/bin/env bash
# =============================================================================
# Benzinga Premium-Update — manuelle Anreicherung des täglichen Cronjob-Berichts
# =============================================================================
# Dieses Script wird NICHT vom Cronjob ausgeführt. Es wird ausgeführt, wenn
# Claude aktiv ist UND der User bei Benzinga.com eingeloggt ist.
#
# Ablauf:
#   1. Lese den heutigen premarket_gappers_YYYY-MM-DD.json
#   2. Drucke die Top 5 Ticker zur weiteren Verarbeitung
#   3. Claude scrapt dann Benzinga via Chrome-MCP und sendet Update-Telegram
#
# Nutzung im Claude-Chat:
#   "Hole Benzinga-Update für die heutigen Gappers"
#   → Claude führt dieses Script + die Chrome-Schritte aus
#
# Nutzung direkt im Terminal:
#   bash enrich_with_benzinga.sh   # zeigt die Top-Ticker zum Scrapen
# =============================================================================

set -euo pipefail
cd "$(dirname "$0")"

DATE=$(date +%Y-%m-%d)
INFILE="premarket_gappers_${DATE}.json"

if [ ! -f "$INFILE" ]; then
    echo "FEHLER: Kein Scanner-Bericht für heute ($DATE) gefunden." >&2
    echo "Erst daily_scanner.sh ausführen, dann anreichern." >&2
    exit 1
fi

# Alter des Berichts prüfen (Warnung wenn > 4h alt)
if [ -f "$INFILE" ]; then
    AGE_MIN=$(( ($(date +%s) - $(stat -f %m "$INFILE")) / 60 ))
    if [ $AGE_MIN -gt 240 ]; then
        echo "⚠️  Warnung: Letzter Scanner-Lauf ist $AGE_MIN Minuten alt." >&2
        echo "   Daten könnten veraltet sein. Trotzdem fortfahren? (Ja per Default)" >&2
    fi
fi

# .env laden
if [ ! -f .env ]; then
    echo "FEHLER: .env Datei nicht gefunden" >&2
    exit 1
fi
export $(grep -v '^#' .env | xargs)

# Top 5 Ticker und URLs ausgeben
echo "=== Benzinga-Anreicherung für $DATE ==="
echo ""
echo "Top Gappers zum Scrapen (Benzinga.com via Chrome-MCP):"
echo ""

python3 - "$INFILE" << 'PYEOF'
import sys, json

with open(sys.argv[1]) as f:
    data = json.load(f)

gappers = data.get("gappers", [])[:5]  # Top 5

if not gappers:
    print("Keine Gappers im aktuellen Bericht.")
    sys.exit(0)

print(f"{'#':<3} {'Ticker':<8} {'Preis':<10} {'Gap':<10} {'Benzinga-URL'}")
print("-" * 80)
for g in gappers:
    sym = g["symbol"]
    price = g.get("premarket_price") or g.get("intraday_price") or 0
    gap = g.get("premarket_gap_pct") or g.get("intraday_gap_pct") or 0
    url = f"https://www.benzinga.com/quote/{sym}"
    print(f"{g.get('rank', '-'):<3} {sym:<8} ${price:<9.2f} {gap:+.2f}%    {url}")

print()
print("=== Nächste Schritte (für Claude) ===")
print("1. Für jeden Ticker oben: Chrome → benzinga.com/quote/<TICKER>")
print("2. find-Query 'news headlines about <TICKER>' → Top-Headline extrahieren")
print("3. Telegram-Nachricht zusammenbauen (Format unten)")
print("4. Senden via curl an Telegram Bot API")
print()
print("=== Telegram-Nachrichten-Vorlage ===")
print()
print("🔥 <b>Benzinga UPDATE — Top 5 Premium Headlines</b>")
print()
for g in gappers:
    sym = g["symbol"]
    price = g.get("premarket_price") or g.get("intraday_price") or 0
    gap = g.get("premarket_gap_pct") or g.get("intraday_gap_pct") or 0
    print(f"<b>{g.get('rank', '-')}. {sym}</b>  {gap:+.2f}%  ${price:.2f}")
    print(f"   📰 <i>{{HEADLINE_FROM_BENZINGA}}</i>")
    print()
print("<i>Quelle: Benzinga.com (eingeloggte Session via Chrome)</i>")
PYEOF
