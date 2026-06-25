# AI-Powered TradingView Day-Trading Scanner

## Projektdokumentation und Präsentationsgrundlage

---

## Inhaltsverzeichnis

1. [Was haben wir gebaut?](#was-haben-wir-gebaut)
2. [Die Trading-Strategie im Detail](#die-trading-strategie-im-detail)
3. [Wie wir das Tool gebaut haben — Schritt für Schritt](#wie-wir-das-tool-gebaut-haben)
4. [Verbesserungen über das Tutorial hinaus](#verbesserungen-über-das-tutorial-hinaus)
5. [Ergebnisse und Interpretation](#ergebnisse-und-interpretation)
6. [Tägliche Automatisierung](#tägliche-automatisierung)
7. [Sicherheit und Risiken](#sicherheit-und-risiken)
8. [Technologie-Stack](#technologie-stack)

---

## Was haben wir gebaut?

Ein vollautomatisches **Day-Trading-Analyse-System**, das jeden Morgen vor US-Börseneröffnung die interessantesten Aktien des Tages identifiziert und uns per Telegram aufs Handy schickt.


### Was das System macht

- **Findet** vorbörsliche Kursgewinner aus über 5.700 US-Aktien
- **Filtert** nach Kriterien wie Kursbewegung, Volumen, Liquidität
- **Begründet** jeden Treffer mit der News-Schlagzeile, die ihn antreibt
- **Bewertet** zusätzlich, ob bestimmte technische Entry-Bedingungen erfüllt sind (Einstiegssignal)
- **Überwacht** nach einem Signal automatisch den besten Ausstieg (Exit-Alerts)
- **Sendet** alle Berichte und Signale automatisch per Telegram aufs Handy

### Was das System NICHT macht

- Es **kauft und verkauft keine Aktien**. Es analysiert und benachrichtigt nur.
- Es ist **kein Investment-Tool**. Die gefundenen Aktien sind Tageskandidaten, keine Portfolio-Empfehlungen.
- Es **garantiert keine Gewinne**. Es ist ein Werkzeug zur schnellen Vorauswahl — die Entscheidung trifft der Trader.

---

## Die Trading-Strategie im Detail

### Day-Trading vs. langfristige Investition

Das System ist **explizit für Day-Trading** entwickelt — also für Trades, die innerhalb desselben Handelstages eröffnet UND geschlossen werden. Das ist ein fundamentaler Unterschied zu langfristigen Investitionen:

| | Day-Trading (unser System) | Langfristige Investition |
|---|---|---|
| Haltezeit | Minuten bis Stunden | Monate bis Jahre |
| Entscheidungsbasis | Tagesnews + technische Signale | Unternehmensbewertung, Branche, Strategie |
| Risiko | Hoch (schnelle Bewegungen) | Gestreut über Zeit |
| Übernacht-Position | Wird vor Schluss geschlossen | Wird gehalten |
| Beispiel-Aktien | Momentum-Werte, News-Mover | Dividenden-Titel, Marktführer |

Das System sucht also bewusst nach Aktien, die **heute** stark schwanken, nicht nach stabilen Langfristkandidaten.

### Zwei Scanner arbeiten zusammen

Das System besteht aus zwei aufeinander aufbauenden Scannern:

#### Scanner A — Premarket Gappers (die Vorauswahl)

**Ziel:** Aktien finden, die **vorbörslich** (vor 9:30 Uhr New Yorker Zeit, das entspricht 15:30 Uhr in Berlin) stark steigen.

**Warum vorbörslich?** Eine Aktie, die schon um 8:00 ET (14:00 Berlin) 15% über dem gestrigen Schlusskurs handelt, hat einen ernsten Grund — meistens eine über Nacht erschienene Nachricht. Das sind die Aktien, die am ersten Handelstag besonders bewegt werden.

**Was wird gemessen?**
- **Gap in Prozent**: Wie weit ist die Aktie vorbörslich gegenüber dem gestrigen Schlusskurs gestiegen?
- **Aktueller Kurs**: Mindestens 3 Dollar (keine Penny-Stocks, weil dort die Bewegungen unkontrolliert sind)
- **Vorbörsliches Volumen**: Mindestens 50.000 Stück (genug Liquidität, damit man tatsächlich kaufen und wieder verkaufen kann)

**Was wird gefiltert?**
Nur Aktien, die **alle drei** Bedingungen erfüllen, gelten als Kandidaten:
- Gap größer als **5 %**
- Kurs über **3 Dollar**
- Volumen über **50.000 Stück**

Danach werden die Top 10 nach Gap-Größe sortiert.

**Der Katalysator (das Wichtigste):**
Für jede gefilterte Aktie wird die aktuelle **Schlagzeile** geladen — die Nachricht, die den Anstieg auslöst. Das ist entscheidend:
- Eine Aktie, die +20% steigt **wegen einer FDA-Zulassung**, verhält sich völlig anders als eine, die +20% steigt **ohne erkennbaren Grund**.
- Mit dem Katalysator kann der Trader in 30 Sekunden entscheiden, ob die Aktie das Risiko wert ist.

#### Scanner B — Trend Join Long (TJL, die Entry-Logik)

**Ziel:** Aus den Gappers diejenigen identifizieren, die **gerade jetzt** einen technischen Einstieg ermöglichen.

**Das Konzept:** Wir kaufen nur dann eine Aktie, wenn **zwei Breakouts gleichzeitig** stattfinden — einer auf Tagesebene, einer intraday.

**Breakout 1 — Auf Tagesebene (Daily):**
- Der aktuelle Kurs liegt **über dem gestrigen Tageshoch**
- Der gestrige Schlusskurs lag **über dem 200-Tage-Durchschnitt** (SMA200)
- Das zeigt: Die Aktie ist im **langfristigen Aufwärtstrend** UND bricht gerade auf ein **neues Hoch** aus

**Breakout 2 — Intraday (im Tagesverlauf):**
- Der aktuelle Kurs liegt **über dem vorbörslichen Hoch** (PMH = Premarket High)
- Der aktuelle Kurs liegt **über dem bisherigen Tageshoch** (HOD = High of Day)
- Das zeigt: Die **Käufer dominieren heute** und treiben den Kurs auf neue Höchststände

**Nur wenn BEIDE Bedingungen erfüllt sind → PASS-Signal**

Das ist der Moment, in dem die Strategie sagt: "Jetzt einsteigen." Ohne dieses doppelte Signal bleibt der Trader an der Seitenlinie.

**Warum diese strenge Logik?**
Day-Trading lebt davon, **mit dem Trend** zu handeln. Eine Aktie, die "nur" vorbörslich steigt, aber nach Eröffnung wieder fällt, ist ein typischer **Fakeout** — viele Trader verlieren genau dort Geld. Indem wir verlangen, dass die Stärke auch **nach Marktöffnung anhält**, filtern wir Fakeouts aus.

### Was passiert nach dem Einstieg? (Exit-Überwachung)

Sobald Scanner B ein PASS-Signal sendet, startet **automatisch** der **Position-Tracker** — er überwacht die Aktie und meldet per Telegram, wann die Strategie aussteigen würde. Drei Exit-Regeln (auch im PineScript-Backtest abgebildet):

- **Teilgewinn bei 1 ATR**: Erreicht der Kurs den Einstieg + 1 ATR (Average True Range = durchschnittliche Tagesschwankung) → Alert *"50% verkaufen, Stop auf Einstieg nachziehen"*. Sichert einen Teil des Gewinns und macht die Position risikofrei.
- **Trailing Stop**: Der Tracker merkt sich das höchste Kurshoch seit Einstieg. Fällt der Kurs mehr als 2% darunter → Alert *"Restposition schließen"*. Solange die Aktie steigt, bleibt man drin; dreht sie, steigt man mit gesichertem Gewinn aus.
- **Zwangsschluss vor Marktschluss** (15:45 ET): Alert *"Position schließen, kein Overnight"*. Übernacht-Risiken werden kategorisch vermieden — eine Nachricht nach Börsenschluss könnte die Position am nächsten Morgen massiv im Minus eröffnen.

**Wichtige Eigenschaften:**
- **Genauigkeit**: Zwischen zwei Überwachungsläufen spielt der Tracker alle 1-Minuten-Kursbalken seit Einstieg nach — so erkennt er auch einen Trailing-Stop, der *zwischen* den Läufen ausgelöst wurde.
- **Rein informativ**: Das System handelt nicht. Die Alerts sagen *"die Strategie würde jetzt aussteigen"* — die tatsächliche Order legt der Trader selbst im Broker an.
- **Frühwarnung, kein Millisekunden-Trigger**: Wegen 30-Minuten-Takt und ~15 Min verzögerter Daten sind die Alerts eine Orientierung. Für präzise Exits nutzt man die nativen Stop-Orders des Brokers.

Damit deckt das System den **vollen Day-Trading-Zyklus** ab: Kandidaten finden (Scanner A) → Einstieg signalisieren (Scanner B) → Ausstieg überwachen (Position-Tracker) — alles aufs Handy.

---

## Wie wir das Tool gebaut haben

In 12 Schritten . Hier eine Beschreibung in einfacher Sprache:

### Schritt 1 — Claude Code installieren

**Was ist Claude Code?** Eine spezielle Version von Claude AI, die im Terminal läuft (also über Befehlszeile, nicht über die Website). Der Unterschied: Diese Version kann **Programme auf dem Computer steuern**, Dateien schreiben, andere Programme öffnen — also alles, was für ein Trading-Tool nötig ist.

**Was wurde installiert?** Eine kleine Software, die per Befehl `claude` im Terminal aufgerufen wird. Sie verbindet sich über das Internet mit Anthropics Claude-Modell.

**Aufwand:** Wenige Minuten, ein einziger Befehl.

### Schritt 2 — TradingView Desktop installieren

**Warum die Desktop-App und nicht die Webseite?** Die Desktop-Version ist eine spezielle Anwendung, die einen versteckten "Debug-Modus" zulässt — nur über diesen Modus kann Claude auf die Charts zugreifen. Die Browser-Version hat das nicht.

**Was wurde gemacht?**
- TradingView Desktop von der offiziellen Seite heruntergeladen und installiert
- In TradingView eingeloggt
- Einen Test-Chart geöffnet (irgendeine Aktie)

### Schritt 3 — Die Brücke installieren (MCP)

**Was ist MCP?** Das **Model Context Protocol** ist eine moderne Schnittstelle, über die Claude direkt mit anderen Programmen kommunizieren kann. Stell dir vor, du gibst Claude ein "Telefon", mit dem es TradingView anrufen kann.

**Was haben wir installiert?**
Einen Open-Source-MCP-Server vom Entwickler *tradesdontlie* (von GitHub). Dieser Server ist die eigentliche Übersetzungsschicht:
- Claude sagt: "Wechsle den Chart auf AMD"
- Der MCP-Server übersetzt das in Befehle, die TradingView versteht
- TradingView wechselt den Chart, der Server meldet "fertig" zurück an Claude

**Wie viele Funktionen hat dieser Server?**
**78 spezialisierte Werkzeuge** — von "Symbol wechseln" über "Indikator hinzufügen" bis "PineScript-Strategie kompilieren". Wir nutzen davon etwa 15-20 für unsere Scanner.

**Aufwand:** Ein einziger Prompt an Claude — Claude erledigt die Installation selbst.

### Schritt 4 — TradingView mit Debug-Port starten

**Was ist der Debug-Port?** TradingView läuft normalerweise abgeschottet — kein Programm außerhalb der App kann hineingucken. Mit dem Debug-Port öffnet TradingView eine spezielle "Tür" (technisch: Port 9222), durch die unser MCP-Server reinschauen darf.

**Sicherheit:** Diese Tür ist nur lokal auf dem eigenen Mac offen — kein Programm aus dem Internet kann hier reinkommen.

**Aufwand:** Ein Befehl, der TradingView mit dem Debug-Modus startet.

### Schritt 5 — Verbindung testen

Wir geben Claude den Prompt: *"Prüfe, ob TradingView verbunden ist."* Claude führt den `tv_health_check` aus und meldet `cdp_connected: true`. **Damit ist die Brücke gebaut.**

### Schritt 6 — Erste Test-Befehle

Bevor wir die Scanner bauen, testen wir die Verbindung mit einfachen Prompts:
- *"Wechsle den Chart auf NVDA, 5-Minuten-Ansicht, füge SMA200 und RSI hinzu."*
- *"Lies meine Watchlist aus und sage mir, welche Aktien heute am stärksten gestiegen sind."*
- *"Analysiere AMD und zeige mir die wichtigsten Unterstützungs- und Widerstandslinien."*

Das alles geschieht jetzt automatisch — Claude steuert TradingView wie ein menschlicher Nutzer.

### Schritt 7 — Scanner A bauen (Premarket Gappers)

Wir geben Claude einen ausführlichen Prompt mit allen Filterkriterien. Claude schreibt selbstständig ein Shell-Script, das:
1. Aktuelle Kursdaten von Yahoo Finance holt
2. Den Premarket-Gap berechnet
3. Nach unseren Kriterien filtert (Gap >5%, Preis >$3, Volumen >50K)
4. Die Top 10 sortiert
5. Für jede Aktie die News-Schlagzeile lädt
6. Das Ergebnis als JSON-Datei speichert

**Aufwand:** Ein Prompt, etwa 90 Sekunden Laufzeit pro Durchlauf.

### Schritt 8 — Automatisierung (launchd)

**Was ist launchd?** Der "Aufgabenplaner" von macOS — er kann Programme zu festgelegten Zeiten automatisch starten.

Wir konfigurieren launchd so, dass unser Scanner **täglich Montag bis Freitag um 15:00 Uhr deutscher Zeit** (= 9:00 ET, 30 Minuten vor US-Marktöffnung) automatisch läuft.

**Schlauer Bonus:** Wenn der Mac um 15:00 schläft, holt das System den Lauf automatisch nach, sobald der Mac aufwacht — natürlich nur an Werktagen und nur einmal pro Tag.

### Schritt 9 — Scanner B bauen (TJL Strategy)

Scanner B prüft pro Aktie die TJL-Kriterien:
1. Für jede Aktie aus Scanner A: Tages-Daten holen, SMA200 + Vortageshoch + Vortagesschluss berechnen
2. 1-Minuten-Daten holen: PMH (Premarket High, 4:00–9:30 ET) und HOD (High of Day, ab 9:30 ET) berechnen
3. Aktuellen Kurs holen
4. Die zwei Breakout-Bedingungen prüfen
5. Ergebnis als PASS / fail_daily / fail_intraday markieren

**Zwei Betriebsarten:**
- **Interaktiv (live, höchste Qualität):** Wenn Claude aktiv ist und TradingView Desktop läuft, liest Claude die Daten direkt über den TradingView-MCP (Echtzeit, börsengenaues Volumen). Pro Aktie ~3–5 Minuten, weil der Chart umgeschaltet werden muss.
- **Automatisch (Cronjob):** Da ein Cronjob die MCP-Werkzeuge nicht aufrufen kann (die brauchen eine aktive Claude-Session), nutzt der automatische Lauf **yfinance**. Damit läuft Scanner B vollautomatisch ohne Claude — die Rechenlogik (SMA200, PMH, HOD) ist identisch.

### Schritt 10 — Strategie alle 30 Minuten ausführen

TJL-Setups treten oft erst um 10:45, 11:30 oder nach dem Mittag auf. Deshalb läuft Scanner B (`tjl_scanner.sh`) automatisch **alle 30 Minuten von 16:00 bis 20:00 Berlin** (= 10:00–14:00 ET, Markt offen) über einen eigenen launchd-Job. Das Universum sind die **heutigen Gappers aus Scanner A** (nicht mehr eine feste Liste).

Anti-Spam: Eine Telegram-Nachricht kommt nur, wenn
- es der erste Lauf des Tages ist, ODER
- ein **neuer** PASS-Treffer dazukommt.

Sonst bleibt das System still.

### Schritt 11 — Backtest mit PineScript

**Was ist PineScript?** Die Programmiersprache von TradingView, mit der man Handelsstrategien programmieren und historisch testen kann.

**Was haben wir gemacht?**
- Claude hat die TJL-Strategie als PineScript geschrieben (45 Zeilen Code)
- Den Code direkt in den TradingView Pine Editor injiziert
- Auf den AMD-Chart angewendet
- TradingView testet die Strategie automatisch über den gesamten verfügbaren Kursverlauf
- Wir lesen die Ergebnisse aus dem Strategy Tester (Win Rate, Profitfaktor, Drawdown)

### Schritt 12 — Telegram-Anbindung

**Warum Telegram?** Push-Nachrichten direkt aufs Handy, ohne dass man am Laptop sitzen muss.

**Aufbau:**
1. Über @BotFather (offizieller Telegram-Bot) einen neuen Bot erstellt — bekommt einen geheimen Token
2. Bot eine Nachricht geschickt, um die persönliche Chat-ID zu bekommen
3. Token und Chat-ID in einer **`.env`-Datei** auf dem Mac gespeichert (nie im Code!)
4. Beide Scanner so erweitert, dass sie nach jedem Lauf eine Nachricht per Telegram senden

**Telegram-Format:**
```
📊 Daily Premarket Report — 22.06.2026 15:00 CEST

7 Gappers gefunden:

1. UMC (US9108734057)
   Premarket: +12.67% $27.13 @ 09:14 ET
   📰 Hits 52-Week High / New Display Chip Technology Launch

2. APGE (US03770N1019)
   Premarket: +46.71% $132.58 @ 09:29 ET
   📰 AbbVie Expands Immunology With $11B Acquisition
   
...
```

### Schritt 13 — Exit-Überwachung (Position-Tracker)

**Über das Tutorial hinaus.** Das Humbled-Trader-Tutorial baut keine Live-Exit-Alerts (Ausstiege kommen dort erst in Teil 2 mit der Broker-Anbindung). Wir haben den Zyklus selbst vervollständigt.

**Was wurde gebaut?**
Ein eigenständiges Programm (`position_tracker.py`), das nach jedem PASS-Signal **automatisch** die Aktie überwacht und den Ausstieg meldet:

1. **Position eröffnen**: Sobald Scanner B ein PASS sendet, merkt sich der Tracker den Einstiegskurs, berechnet die ATR (durchschnittliche Tagesschwankung) und die Zielmarken.
2. **Überwachen**: Bei jedem 30-Minuten-Lauf prüft er drei Ausstiegsregeln und spielt dabei alle 1-Minuten-Kursbalken seit Einstieg nach (erkennt auch Auslöser *zwischen* den Läufen).
3. **Melden**: Bei einem Treffer kommt ein Telegram-Alert mit konkretem Kurs und Ergebnis.

**Die drei Exit-Regeln:**
- 🟡 **Teilgewinn bei +1 ATR** — "50% verkaufen, Stop auf Einstieg nachziehen"
- 🔴 **Trailing Stop bei -2% vom Hoch** — "Restposition schließen"
- 🟠 **Zwangsschluss um 15:45 ET** — "vor Börsenschluss schließen, kein Overnight"

**Automatisierung:** Ein zweiter launchd-Job (`com.tradingview.positiontracker`) führt die Überwachung bis Börsenschluss fort (20:30–22:00 Berlin), auch nachdem Scanner B um 20:00 endet — damit der EOD-Ausstieg um 21:45 Berlin (15:45 ET) sicher feuert.

Details zur Logik: siehe Abschnitt [Was passiert nach dem Einstieg?](#was-passiert-nach-dem-einstieg-exit-überwachung).

---

## Verbesserungen über das Tutorial hinaus

Beim Bauen sind uns drei methodische Schwächen aufgefallen, die wir behoben haben:

### Verbesserung 1 — Universum statt Watchlist

**Problem:** Im ersten Anlauf hatte ich (Claude) eine handverlesene Watchlist mit 58 Tickern hartcodiert. Damit war jeder Tagesgewinner, der nicht auf der Liste war, unsichtbar.

**Lösung:** Wir nutzen jetzt die **Yahoo Screener API** und holen täglich die **Top 100 Tagesgewinner aus über 5.700 US-Aktien**. Diese werden dann mit unseren Filtern weiter verarbeitet.

**Effekt:** Heute haben wir Aktien wie **DFTX** (+57%), **APGE** (+47%), **ORKA** (+11%) gefunden — alles Werte, die in der alten 58er-Liste nie vorgekommen wären.

### Verbesserung 2 — Echte Premarket-Berechnung

**Problem:** Die ursprüngliche yfinance-Bibliothek liefert für Premarket-Daten oft unklare Werte. Was wir als "Gap" gemeldet haben, war manchmal in Wirklichkeit die **Tagesperformance**, nicht der echte Premarket-Gap.

**Lösung:** Wir laden 1-Minuten-Bars **mit explizitem Premarket-Flag** und filtern selbst nach Zeitstempel:
- **Vortag-Schluss** = letzte Bar VOR 16:00 ET am Vortag (regulärer Schluss, kein After-Hours)
- **Premarket-Kurs** = letzte Bar zwischen 4:00 und 9:30 ET heute
- **Echter Gap** = Premarket-Kurs ÷ Vortag-Schluss − 1

**Effekt:** Im Bericht steht jetzt zusätzlich **Yahoo's eigene Anzeige zum Vergleich**, mit einer Differenz-Spalte (Δ). Bei UMC sehen wir z.B.:
- Unser Premarket-Gap: +12,67% (9:14 ET)
- Yahoo zeigt: +15,14% (Live Intraday)
- Differenz: -2,47 Prozentpunkte = die Bewegung NACH Marktöffnung

So wissen wir genau, was wir messen.

### Verbesserung 3 — Benzinga als Premium-Nachrichtenquelle

**Problem:** Google News RSS liefert manchmal generische oder irrelevante Headlines ("UMC Stock Up 10.7%").

**Lösung:** Über die Chrome-Browser-Anbindung greifen wir auf eine **eingeloggte Benzinga-Session** zu. Benzinga ist die Profi-Quelle für Day-Trading-News und liefert deutlich präzisere Katalysatoren.

**Effekt — direkter Vergleich bei APGE:**
- Google News: *"biggest moves premarket: Apogee Therapeutics, SpaceX, Arcosa & more"*
- Benzinga: *"AbbVie Expands Immunology Footprint With Apogee $11 Billion Acquisition"*

Bei Benzinga sehen wir den **eigentlichen Grund** für die Kursbewegung ($11 Mrd. Übernahme!) — das ist genau die Information, die ein Day-Trader für seine Entscheidung braucht.

### Verbesserung 4 — ISIN-Mapping für den Endreport

Damit der Bericht professioneller wird, haben wir für jeden Treffer die **ISIN** (International Securities Identification Number) hinzugefügt. Diese 12-stellige Kennnummer identifiziert eine Aktie eindeutig international — wichtig für die Dokumentation und für den Handel über deutsche Broker.

Beispiel: AMD = US0079031078

Das ISIN-Mapping wird automatisch aktualisiert, wenn neue Ticker auftauchen.

### Verbesserung 5 — Chunked Downloads (Stabilität)

**Problem:** Scanner A stürzte ab mit `OSError: Too many open files`. yfinance lud alle ~100 Ticker gleichzeitig herunter (`threads=True`), was das macOS-Dateideskriptor-Limit (256) überschritt. Folge: DNS-Fehler, SQLite-Fehler, kein Telegram.

**Lösung:** Zwei Maßnahmen:
1. `ulimit -n 4096` — erhöht das Limit offener Dateien auf 4.096
2. **Chunked Download** — die ~100 Ticker werden in Gruppen von 25 heruntergeladen statt alle gleichzeitig

**Effekt:** Scanner A läuft seit dem Fix zuverlässig, auch bei 100 Tickern.

### Verbesserung 6 — TradingView-Live-Daten via CronCreate

**Problem:** Scanner B nutzte im Cronjob nur yfinance-Daten (leicht verzögert, kein Echtzeit-Volumen). Die ursprüngliche Anleitung von Shay sah TradingView-Echtzeitdaten vor, aber der MCP braucht eine aktive Claude-Session.

**Lösung:** Auf dem Mac Mini läuft Claude permanent. Über **CronCreate** (Claude-interner Scheduler) wird Scanner B automatisch alle 30 Minuten während der Handelszeit getriggert. Claude:
1. Liest die heutigen Gappers aus Scanner A
2. Lädt jeden Ticker in TradingView Desktop
3. Holt Daily-OHLCV (SMA200), 1-Min-Bars (PMH/HOD) und Live-Quote über den MCP
4. Übergibt die Daten an `tjl_scanner.sh --mcp-data '<JSON>'`

**Dual-Mode-Fallback:** Wenn Claude nicht offen ist, springt der launchd-Cronjob mit yfinance-Daten ein. Die Rechenlogik ist identisch — nur die Datenquelle wechselt.

**Einschränkung:** CronCreate-Jobs sind session-only (max. 7 Tage). Sie laufen nur solange die Claude-Session aktiv ist.

---

## Ergebnisse und Interpretation

### Live-Test am 22. Juni 2026

Wir haben das System an einem regulären Börsentag laufen lassen. Hier die Top 5 mit Benzinga-Katalysatoren:

| # | Ticker | Premarket | Katalysator (Benzinga) |
|---|---|---|---|
| 1 | **DFTX** | +57,17% | Soar After Reporting Positive Phase 3 Results For Single-Dose Depression Treatment |
| 2 | **APGE** | +46,71% | AbbVie Expands Immunology Footprint With Apogee $11 Billion Acquisition |
| 3 | **BWIN** | +18,49% | Stock Lower Before Earnings Report |
| 4 | **PENG** | +14,36% | Gains Momentum As AI Infrastructure Demand Remains Strong |
| 5 | **UMC** | +12,67% | Hits 52-Week High / New Display Chip Technology Launch |

**Was das in der Praxis bedeutet:**
- **DFTX**: Biotech mit Phase-3-Erfolg → typischer Day-Trading-Kandidat mit klarer News-Story
- **APGE**: $11 Mrd. Übernahme → wahrscheinlich begrenztes Upside (Kurs steigt zum Übernahmepreis), aber liquide
- **BWIN**: Earnings-Sorge → vorsichtig handeln, könnte volatil sein
- **PENG**: AI-Story → folgt dem allgemeinen Markt-Hype, gut für Day-Trading
- **UMC**: 52-Wochen-Hoch → klassischer Breakout-Kandidat für TJL-Strategie

### Backtest-Ergebnisse (TJL Strategy auf AMD, Daily)

Wir haben die TJL-Strategie über den gesamten verfügbaren Kursverlauf von AMD getestet (1972–2026):

| Kennzahl | Wert |
|---|---|
| Nettogewinn | +$337.908 (+3.379%) |
| Max. Drawdown | $42.358 (61%) |
| Gewinnquote | 46,12% (380 von 824 Trades) |
| Profitfaktor | 1,622 |
| 1-Jahres-Rendite | +319,79% |

**Wie liest man diese Zahlen?**

**Profitfaktor 1,622** ist der wichtigste Wert:
- Bedeutet: Für jeden verlorenen Dollar hat die Strategie $1,62 gewonnen
- **Über 1,5 gilt als solide Strategie**
- Das ist ein echter statistischer Vorteil ("Edge")

**Gewinnquote 46% klingt niedrig — ist aber normal:**
- Trendfolge-Strategien gewinnen typischerweise weniger als die Hälfte der Trades
- Das Prinzip: **"Verliere klein, gewinne groß"**
- Wenige große Gewinner gleichen viele kleine Verluste mehr als aus

**Max Drawdown 61% ist der kritische Wert:**
- Zeigt: Zu irgendeinem Zeitpunkt war das Konto 61% unter seinem Höchststand
- In der Praxis vermeidet man das durch **Positionsgrößen-Management** — nie 100% des Kapitals in einen Trade
- Bei realistischer Positionsgröße (z.B. 5% pro Trade) sinkt der Drawdown drastisch

### Backtest-Ergebnisse (zum Vergleich)

Aus dem Tutorial:

**Einzeltest MU (Micron, 60 Tage, 5-Min-Chart):**
- 21 Trades, **66,67% Win Rate**, +$49,24 P&L, **Profitfaktor 1,57**, Drawdown 0,74%

**Multi-Symbol-Sweep (32 Momentum-Aktien, 30 Tage):**
- 280 Trades, 54,6% Win Rate, +$1.167 P&L, Profitfaktor 1,59

### Was der Backtest NICHT sagt

- **Keine Garantie für die Zukunft** — Vergangenheits-Performance sagt nichts über zukünftige Ergebnisse
- **Survivorship Bias** — Wir testen AMD, eine extrem erfolgreiche Aktie. Auf einer Pleite-Aktie würden die Zahlen anders aussehen
- **Slippage und Spread fehlen** — In der echten Welt bekommt man nicht immer den gewünschten Preis
- **Funktioniert nur für Momentum-Aktien** — auf Utilities/Staples getestet → Verluste

---

## Tägliche Automatisierung

Das System läuft jetzt täglich automatisch:

### Zeitplan (alle Zeiten Berlin)

| Uhrzeit | Was passiert |
|---|---|
| **15:00** | Scanner A startet automatisch (= 9:00 ET, 30 Min vor US-Öffnung) |
| **15:00–15:30** | Premarket Gappers werden gescannt + News + Telegram |
| **16:00–20:00** | Scanner B läuft alle 30 Min — **zwei parallele Pfade:** |
| | → **CronCreate (MCP):** Claude holt TradingView-Echtzeitdaten (wenn Session aktiv) |
| | → **launchd (yfinance):** Automatischer Fallback (immer aktiv, auch ohne Claude) |
| **16:00–22:00** | Position-Tracker überwacht offene Positionen (Exit-Alerts) |
| **~21:45** | Zwangsschluss-Alert (15:45 ET) für noch offene Positionen |
| **22:00** | US-Markt schließt, System ruht, Positionen werden zurückgesetzt |

### Was du auf deinem Handy bekommst

**Einmal morgens (Scanner A):**
- Liste der Top-Gappers des Tages
- Pro Aktie: Ticker, ISIN, Premarket-Gap, Aktueller Preis, Volumen, News-Katalysator
- Vergleich zu Yahoo-Anzeige (Qualitätscheck)

**Im Tagesverlauf (Scanner B):**
- Ein **Einstiegssignal** (PASS), wenn eine Aktie die TJL-Kriterien erfüllt
- Nur bei neuem Treffer — sonst keine Nachrichten (kein Spam)

**Nach einem PASS (Position-Tracker):**
- 👁 *"Beobachtung gestartet"* mit Einstiegskurs und Zielmarken
- 🟡 *Teilgewinn* bei +1 ATR
- 🔴 *Trailing Stop* beim Drehen des Kurses (mit Ergebnis in %)
- 🟠 *Zwangsschluss* vor Börsenschluss

### Steuerung

Drei getrennte launchd-Jobs:
- Scanner A: `com.tradingview.scanner` (Mo–Fr 15:00)
- Scanner B: `com.tradingview.tjlscanner` (Mo–Fr alle 30 Min, 16:00–20:00)
- Exit-Tracker: `com.tradingview.positiontracker` (Mo–Fr 20:30–22:00, Spätfenster für EOD)

- **Manuell starten**: `bash daily_scanner.sh` · `bash tjl_scanner.sh --force` · `bash tjl_scanner.sh --force --mcp-data '<JSON>'` · `python3 position_tracker.py --force`
- **Pausieren**: launchd-Job mit `launchctl unload` deaktivieren
- **Exit-Parameter anpassen**: Werte (Trailing %, ATR-Ziel) oben in `position_tracker.py` ändern
- **Filter anpassen**: Werte (Gap, Preis) in den Scripts ändern
- **Universe ändern**: Anderen Yahoo-Screener nutzen (z.B. "Top Losers", "Most Active")

### Wichtiger Lerneffekt: Speicherort außerhalb von ~/Documents

Anfangs lag das Projekt unter `~/Documents`. Die automatischen Läufe schlugen **stillschweigend fehl** ("Operation not permitted"), weil macOS die Ordner Dokumente, Schreibtisch und Downloads mit einer Datenschutz-Sperre (TCC) schützt — Hintergrundprozesse wie launchd dürfen dort nicht zugreifen. Manuelle Läufe funktionierten, automatische nicht.

**Lösung:** Das Projekt liegt jetzt unter `~/TradingViewScanner/` (außerhalb der Sperre). Lehre: zeitgesteuerte Scripts gehören nicht in die geschützten macOS-Benutzerordner.

---

## Sicherheit und Risiken

### Sicherheit der Daten

- **Telegram Bot Token**: Nur lokal in `.env` Datei gespeichert, niemals im Code
- **`.gitignore`**: Verhindert versehentliches Hochladen sensibler Daten zu GitHub
- **TradingView Login**: Bleibt komplett lokal — Claude bekommt nie deine Zugangsdaten
- **Bot kann nur senden**: Der Telegram-Bot kann Nachrichten an dich schicken, aber nicht handeln oder Aufträge auslösen
- **Keine Trades**: Das System analysiert nur, es führt keine Käufe oder Verkäufe aus

### Trading-Risiken

**Day-Trading ist hochriskant.** Folgendes muss klar sein:

1. **Hoher Drawdown möglich**: Der Backtest zeigt 61% Drawdown — also temporäre Verluste über die Hälfte des Kapitals
2. **Schnelle Bewegungen**: Eine Aktie kann innerhalb von Minuten 10% fallen
3. **Emotionaler Stress**: Day-Trading erfordert Disziplin — Computer-Signale sind nur die halbe Miete
4. **Steuern**: In Deutschland gelten Day-Trading-Gewinne als private Veräußerungsgeschäfte oder Kapitaleinkünfte (Steuerberater fragen!)
5. **Paper-Trading zuerst**: Empfehlung: Mindestens 1 Monat im Demokonto testen, BEVOR echtes Geld eingesetzt wird

---

## Technologie-Stack

| Komponente | Technologie | Zweck |
|---|---|---|
| AI-Assistent | Claude Code (Opus) | Steuerung, Analyse, Code-Generierung |
| Chart-Plattform | TradingView Desktop | Charts, Kursdaten, Backtesting |
| Verbindungsprotokoll | MCP (Model Context Protocol) | Brücke zwischen Claude und Programmen |
| Transportschicht | Chrome DevTools Protocol | Zugriff auf TradingView Electron-App |
| MCP 1 — TradingView | Node.js (tradesdontlie/tradingview-mcp) | 78 Tools: Chart steuern, Daten lesen, PineScript, Backtest |
| MCP 2 — Claude-in-Chrome | Browser-Automatisierung | Benzinga-Premium-News in eingeloggter Session lesen |
| Kursdaten-Quelle | Yahoo Finance via Screener API | Aktuelle Kurse aller US-Aktien |
| News (automatisch) | Google News RSS Feed | News-Katalysator pro Ticker |
| News (premium) | Benzinga.com via Chrome | Day-Trading-Qualitäts-Headlines |
| Backtesting | PineScript v6 (TradingView) | Historischer Strategie-Test |
| Benachrichtigung | Telegram Bot API | Push-Alerts aufs Handy |
| Automatisierung | macOS launchd (3 Jobs) + CronCreate | Scanner A (15:00) + Scanner B (16:00–20:00) + Exit-Tracker (20:30–22:00) |
| Zeitzone | Python ZoneInfo | Saubere ET/CEST-Umrechnung |

### Projektstruktur

Speicherort: **`~/TradingViewScanner/`** (bewusst NICHT unter `~/Documents`, siehe Lerneffekt unten).

```
~/TradingViewScanner/
├── .env                          ← Telegram-Credentials (nicht im Git)
├── .gitignore                    ← Schützt sensible Dateien
├── daily_scanner.sh              ← Scanner A: Premarket Gappers (automatisch)
├── tjl_scanner.sh                ← Scanner B: TJL-Signale live + ruft Tracker (automatisch)
├── position_tracker.py           ← Exit-Überwachung: Teilgewinn / Trailing Stop / EOD
├── enrich_with_benzinga.sh       ← Premium-News-Update via Benzinga (Chrome)
├── premarket_gappers.sh          ← Scanner A (frühe Standalone-Version)
├── telegram_alert.sh             ← Telegram-Anbindung
├── scanner.py                    ← Standalone-Version mit Selbsttests
├── fetch_news_chrome.sh          ← Dokumentation Chrome-Scraping
├── ticker_isin.json              ← ISIN-Mapping (wächst automatisch)
├── ANLEITUNG.md                  ← Diese Datei
└── Ergebnis-Dateien:
    ├── premarket_gappers_YYYY-MM-DD.json   ← Scanner-A-Treffer
    ├── tjl_watchlist_YYYY-MM-DD_HHMM_ET.json ← Scanner-B-Urteile
    ├── tjl_state_YYYY-MM-DD.json            ← Anti-Spam-Status (PASS pro Tag)
    ├── positions_YYYY-MM-DD.json           ← Offene/geschlossene Positionen des Tages
    ├── backtest_tjl_amd.json                ← Backtest-Kennzahlen
    └── *.log                                ← Lauf-Protokolle

Zeitgesteuert über drei macOS-launchd-Jobs (in ~/Library/LaunchAgents/):
├── com.tradingview.scanner.plist          ← Scanner A, Mo–Fr 15:00 Berlin
├── com.tradingview.tjlscanner.plist       ← Scanner B, Mo–Fr alle 30 Min 16:00–20:00
└── com.tradingview.positiontracker.plist  ← Exit-Tracker, Mo–Fr 20:30–22:00
```

---

## Lerneffekte und Erkenntnisse

1. **MCP ist die Zukunft der AI-Tool-Integration**
   Claude kann externe Programme steuern wie ein menschlicher Nutzer — aber schneller und konsistenter. Was 30 Minuten manuelles Chart-Klicken kosten würde, erledigt das System in Sekunden.

2. **Methodische Sauberkeit zahlt sich aus**
   Die ursprüngliche feste Watchlist hat den eigentlichen Day-Trading-Workflow verfälscht. Erst durch den Wechsel zum Yahoo-Screener und die saubere Premarket-Berechnung wurde das System wirklich nutzbar.

3. **Daten-Qualität schlägt Daten-Menge**
   Benzinga's wenige aber präzise Headlines schlagen Google News' viele aber generische Treffer. Bei APGE war der Unterschied zwischen "biggest movers" (Google) und "$11 Billion Acquisition" (Benzinga) der zwischen "kein Signal" und "klares Signal".

4. **Backtesting ist unverzichtbar — aber kein Versprechen**
   Profitfaktor 1,62 ist solide, aber das schützt nicht vor schlechten Tagen, falschen Märkten oder emotionalen Fehlern. Der Backtest validiert das Konzept, nicht die zukünftige Performance.

5. **Automatisierung spart jeden Tag 30-60 Minuten**
   Charts manuell durchklicken, News lesen, technische Levels prüfen — was vorher den ganzen Morgen kostete, kommt jetzt zwischen Frühstück und erstem Kaffee aufs Handy.

6. **Day-Trading bleibt Day-Trading**
   Das Tool ist ein Werkzeug zur Vorauswahl, nicht ein "Druck-mich-und-werde-reich"-Knopf. Wer ohne Disziplin und Risiko-Management handelt, verliert Geld — egal wie gut das Werkzeug ist.

---

## Nächste Schritte

**Bereits umgesetzt (über das Tutorial hinaus):** Exit-Alerts — nach einem PASS wird die Position automatisch beobachtet und das Ausstiegssignal (Teilgewinn bei 1 ATR, Trailing Stop, Zwangsschluss) per Telegram gesendet. Der volle Zyklus Einstieg → Überwachung → Ausstieg ist damit abgedeckt.

Was wir noch erweitern könnten:

- **Strategie-Analyse und Optimierung**: Die TJL-Watchlists speichern aktuell nur PASS/fail — nicht die Zahlenwerte (Kurs, PMH, HOD, SMA200, Gap%). Erweitert man die Speicherung um numerische Werte und Forward Returns (Kursverhalten 1h, 2h, EOD nach dem Signal), kann man nach einigen Wochen Daten analysieren: Bei welchem Gap% kommen die besten Signale? Wie oft führt fail_intraday doch noch zu einem Breakout?
- **Paper-Trading-Anbindung an Interactive Brokers**: tatsächliche (virtuelle) Order-Ausführung statt nur Benachrichtigung.
- **Weitere Strategien**: Short-Setups (Trend Join Short), Mean Reversion, Earnings Plays
- **Watchlist-Anpassung**: Statt Yahoo Top 100 eigene Sektor-Universen (Halbleiter, AI, Energie)
- **Alternative Datenquellen**: Yahoo's `day_gainers` Screener könnte langfristig instabil sein — Alternativen wie Finviz, Unusual Whales oder direkte Börsendaten-APIs wären robuster

---

