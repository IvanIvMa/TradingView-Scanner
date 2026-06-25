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

# 1. Schon mit Debug-Port erreichbar? -> nichts zu tun
if curl -s --max-time 2 "http://localhost:${PORT}/json/version" >/dev/null 2>&1; then
    echo "✅ TradingView läuft bereits mit Debug-Port ${PORT}."
    exit 0
fi

# 2. Läuft, aber ohne Debug-Port? -> beenden
if pgrep -f "TradingView.app/Contents/MacOS/TradingView" >/dev/null 2>&1; then
    echo "TradingView läuft ohne Debug-Port — Neustart…"
    pkill -9 -f "TradingView.app/Contents/MacOS/TradingView" 2>/dev/null
fi

# 3. Mit Debug-Port (neu) starten (detached)
echo "Starte TradingView mit --remote-debugging-port=${PORT}…"
( "$APP" --remote-debugging-port=${PORT} >/dev/null 2>&1 & )

# 4. Auf CDP warten (curl-Retry statt sleep)
if curl -s --retry 45 --retry-delay 1 --retry-connrefused --max-time 90 \
        "http://localhost:${PORT}/json/version" >/dev/null 2>&1; then
    echo "✅ TradingView bereit (CDP ${PORT})."
else
    echo "❌ CDP ${PORT} nach Timeout nicht erreichbar." >&2
    exit 1
fi
