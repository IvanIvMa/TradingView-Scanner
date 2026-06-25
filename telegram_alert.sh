#!/usr/bin/env bash
# Telegram Alert Script — sendet Scanner-Ergebnisse als Telegram-Nachricht
# Nutzung:
#   bash telegram_alert.sh gappers   # Premarket Gappers scannen + Telegram senden
#   bash telegram_alert.sh tjl       # TJL Ergebnisse senden (letztes JSON)
#   bash telegram_alert.sh test      # Testnachricht senden

set -euo pipefail
cd "$(dirname "$0")"

# .env laden
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

if [ -z "${TELEGRAM_BOT_TOKEN:-}" ] || [ -z "${TELEGRAM_CHAT_ID:-}" ]; then
    echo "FEHLER: TELEGRAM_BOT_TOKEN und TELEGRAM_CHAT_ID müssen in .env gesetzt sein"
    exit 1
fi

send_telegram() {
    local msg="$1"
    curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
        -H "Content-Type: application/json" \
        -d "{\"chat_id\": ${TELEGRAM_CHAT_ID}, \"text\": $(python3 -c "import json,sys; print(json.dumps(sys.argv[1]))" "$msg"), \"parse_mode\": \"HTML\"}" > /dev/null
}

CMD="${1:-help}"
DATE=$(date +%Y-%m-%d)

case "$CMD" in
    gappers)
        echo "=== Scanner A: Premarket Gappers ==="
        bash premarket_gappers.sh

        OUTFILE="premarket_gappers_${DATE}.json"
        if [ ! -f "$OUTFILE" ]; then
            echo "Keine Ergebnisse-Datei gefunden."
            exit 1
        fi

        MSG=$(python3 - "$OUTFILE" << 'PYEOF'
import sys, json

with open(sys.argv[1]) as f:
    data = json.load(f)

gappers = data.get("gappers", [])
if not gappers:
    print("📊 <b>Premarket Gappers</b> — Keine Gappers gefunden (Markt geschlossen?)")
    sys.exit()

lines = [f"📊 <b>Premarket Gappers ({len(gappers)} Treffer)</b>\n"]
for g in gappers[:10]:
    catalyst = g.get("catalyst", "")
    cat_str = f"\n   📰 {catalyst[:50]}" if catalyst else ""
    lines.append(
        f"<b>{g.get('rank', '-')}. {g['symbol']}</b>  "
        f"+{g['gap_pct']}%  ${g['price']:.2f}  "
        f"Vol: {g['premarket_volume']:,}{cat_str}"
    )
print("\n".join(lines))
PYEOF
        )
        send_telegram "$MSG"
        echo "Telegram-Nachricht gesendet."
        ;;

    tjl)
        echo "=== Scanner B: TJL Watchlist ==="
        LATEST=$(ls -t tjl_watchlist_*.json 2>/dev/null | head -1)
        if [ -z "$LATEST" ]; then
            echo "Keine TJL-Ergebnisse gefunden. Erst 'scanner.py tjl' oder den MCP-Scanner laufen lassen."
            exit 1
        fi

        MSG=$(python3 - "$LATEST" << 'PYEOF'
import sys, json

with open(sys.argv[1]) as f:
    data = json.load(f)

hits = data.get("hits", [])
all_res = data.get("all_results", [])
checked = data.get("candidates_checked", 0)

if hits:
    lines = [f"🎯 <b>TJL Scanner ({len(hits)}/{checked} PASS)</b>\n"]
    for h in hits:
        lines.append(
            f"<b>{h['symbol']}</b>  ${h.get('curr_price', 'N/A')}  "
            f"PMH: ${h.get('pmh', 'N/A')}  HOD: ${h.get('today_hod', 'N/A')}"
        )
else:
    lines = [f"🔍 <b>TJL Scanner ({checked} geprüft, 0 PASS)</b>\n"]
    for r in all_res:
        lines.append(f"  {r['symbol']}: {r['result']}")

if data.get("note"):
    lines.append(f"\n<i>{data['note'][:100]}</i>")

print("\n".join(lines))
PYEOF
        )
        send_telegram "$MSG"
        echo "Telegram-Nachricht gesendet."
        ;;

    test)
        send_telegram "✅ TradingView Scanner — Telegram Alert funktioniert! ($(date '+%Y-%m-%d %H:%M'))"
        echo "Testnachricht gesendet."
        ;;

    *)
        echo "Nutzung: bash telegram_alert.sh [gappers|tjl|test]"
        ;;
esac
