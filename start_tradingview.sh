#!/usr/bin/env bash
# =============================================================================
# start_tradingview.sh — TradingView mit Debug-Port (CDP) sicherstellen
# =============================================================================
# Der TradingView-MCP braucht TradingView Desktop MIT --remote-debugging-port=9222.
# Startet TradingView normal (App-Icon, nach Reboot/Update), fehlt das Flag und
# der ganze MCP-Pfad fällt still auf yfinance zurück. Dieses Script stellt den
# korrekten Zustand her.
#
# Nutzung:   bash start_tradingview.sh
# Tipp:      als Login-Objekt einrichten, damit TradingView IMMER korrekt startet.
# =============================================================================

PORT=9222
APP="/Applications/TradingView.app/Contents/MacOS/TradingView"

# 1-4. Debug-Port sicherstellen (nur wenn nicht schon erreichbar)
if curl -s --max-time 2 "http://localhost:${PORT}/json/version" >/dev/null 2>&1; then
    echo "✅ TradingView läuft bereits mit Debug-Port ${PORT}."
else
    if pgrep -f "TradingView.app/Contents/MacOS/TradingView" >/dev/null 2>&1; then
        echo "TradingView läuft ohne Debug-Port — Neustart…"
        pkill -9 -f "TradingView.app/Contents/MacOS/TradingView" 2>/dev/null
    fi
    echo "Starte TradingView mit --remote-debugging-port=${PORT}…"
    ( "$APP" --remote-debugging-port=${PORT} >/dev/null 2>&1 & )
    if curl -s --retry 45 --retry-delay 1 --retry-connrefused --max-time 90 \
            "http://localhost:${PORT}/json/version" >/dev/null 2>&1; then
        echo "✅ TradingView bereit (CDP ${PORT})."
    else
        echo "❌ CDP ${PORT} nach Timeout nicht erreichbar." >&2
        exit 1
    fi
fi

# 5. Chart-Check: ist ein Chart offen und liefert Daten? Sonst Telegram-Warnung.
#    (Ohne offenen Chart fällt Scanner B still auf Yahoo-Daten zurück.)
cd "$(dirname "$0")"
python3 - << 'PYEOF'
import sys, time, subprocess
sys.path.insert(0, ".")
from position_tracker import try_connect_mcp, send_telegram, _find_node

def chart_ok():
    m = try_connect_mcp()
    if not m:
        return None
    q = m.tool("quote_get") or {}
    m.close()
    if isinstance(q, dict) and q.get("success") is not False and q.get("symbol"):
        return q.get("symbol")
    return None

ok = False
for attempt in range(4):
    sym = chart_ok()
    if sym:
        ok = True
        print(f"✅ Chart offen ({sym}) — MCP liefert Live-Daten.")
        break
    if attempt == 1:                    # nach ~20 s ohne Chart: selbst öffnen
        print("Kein Chart offen — öffne automatisch NASDAQ:AAPL…")
        r = subprocess.run([_find_node(), "open_chart.mjs"], capture_output=True, text=True, timeout=90)
        print("  " + (r.stdout.strip() or r.stderr.strip()[:200]))
    time.sleep(10)
if not ok:
    print("⚠️ Kein Chart offen — Telegram-Warnung gesendet.")
    send_telegram("⚠️ <b>TradingView: kein Chart offen</b>\n"
                  "Scanner B nutzt nur Yahoo-Daten, bis ein Chart geöffnet ist.\n"
                  "Bitte in TradingView ein Layout/Chart öffnen.")
    sys.exit(2)
PYEOF
