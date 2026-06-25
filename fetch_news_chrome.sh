#!/usr/bin/env bash
# Chrome-basierter News-Scraper für Stock-Katalysatoren
# Nutzt Claude's Chrome-Extension um Yahoo Finance News auszulesen.
#
# Dieses Script wird NICHT direkt ausgeführt — es dokumentiert den Ablauf,
# den Claude im Chat durchführt. Der eigentliche Scraper läuft über die
# Claude-in-Chrome MCP Tools.
#
# Ablauf:
#   1. Claude öffnet einen Chrome-Tab
#   2. Navigiert zu finance.yahoo.com/quote/{SYMBOL}/news/
#   3. Liest die Seite aus (get_page_text)
#   4. Extrahiert die Top-Headlines als Katalysator
#   5. Wiederholt für jeden Gapper-Ticker
#
# Alternative Quellen (Priorität):
#   1. Yahoo Finance News  — finance.yahoo.com/quote/{SYM}/news/
#      + Kostenlos, keine API nötig, aggregiert viele Quellen
#      + Chrome-Extension umgeht Anti-Bot-Schutz
#
#   2. Google News Search  — news.google.com/search?q={SYM}+stock
#      + Breiteste Abdeckung, alle Quellen
#      - Nicht aktienspezifisch, braucht Filterung
#
#   3. MarketWatch          — marketwatch.com/investing/stock/{sym}
#      + Gute Zusammenfassung, Analystenmeinungen
#      - Manchmal Paywall
#
#   4. Seeking Alpha        — seekingalpha.com/symbol/{SYM}/news
#      + Detaillierte Analysen
#      - Paywall nach wenigen Artikeln
#
# Warum Chrome statt direktem HTTP-Request?
#   - Websites blockieren automatisierte Anfragen (SSL-Fehler, CAPTCHAs, 403)
#   - Chrome hat alle Cookies, Sessions, und JavaScript-Rendering
#   - Claude's Chrome-Extension kann die gerenderte Seite direkt auslesen
#   - Kein API-Key nötig, keine Rate-Limits

echo "Dieser Script dokumentiert den Chrome-News-Scraper-Ablauf."
echo "Der eigentliche Scraper wird von Claude im Chat ausgeführt."
echo ""
echo "Nutzung im Claude-Chat:"
echo '  "Hole News-Katalysatoren für meine Gappers über Chrome"'
echo '  "Starte den Scanner mit Chrome-News"'
