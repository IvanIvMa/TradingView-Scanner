# Optimized Steps — Humbled Trader Tutorial → Production Build

This maps Shay's 10-step tutorial
([Connect Claude to TradingView MCP](https://www.humbledtrader.com/blog/connect-claude-to-tradingview-mcp/))
to our production implementation, and lists the optimizations we added on top.

The tutorial got us a working prototype in an afternoon. The notes below are the
changes we made to run it **unattended, every trading day, without a Claude
session open** — and a few strategy/UX refinements. Shared here to discuss with Shay.

---

## Step-by-step: tutorial vs. our build

| # | Shay's step | Status | What we changed / added |
|---|---|---|---|
| 1 | Install Claude Code | ✅ as-is | — |
| 2 | Install TradingView Desktop | ✅ as-is | — |
| 3 | Install the TradingView MCP | ✅ as-is | Also reused outside Claude (see "Key optimization") |
| 4 | Basic prompts | ✅ as-is | — |
| 5 | Build Scanner A (gap scanner) | ✅ improved | Real premarket-gap math; live Top-100 universe |
| 6 | Automate Scanner A | ✅ improved | DST-robust scheduling + a second "merge" run |
| 7 | Build Scanner B (strategy) | ✅ as-is | TJL: daily + intraday breakout |
| 8 | Automate Scanner B every 30 min | ✅ improved | Runs **without Claude**; stops at the entry cutoff |
| 9 | Backtest with PineScript | ✅ as-is | Own backtest (AMD daily, profit factor 1.62) |
| 10 | Test an "obvious" filter (SPY/QQQ regime) | ✅ reframed | Added as an **advisory**, not a hard filter |

---

## Our optimizations (in detail)

### A. Scanner B runs without a Claude session — the big one
**Tutorial:** the MCP (live TradingView data) needs an active Claude session;
the automated cron falls back to delayed data.
**Our change:** the MCP server is a local Node stdio process. `mcp_scanner_b.py`
**starts it and speaks JSON-RPC directly**, so Scanner B gets real-time
TradingView data from a plain `launchd` job — no Claude, no API tokens, no
7-day session-expiry. yfinance remains an automatic fallback if TradingView is
closed.
**Why it matters:** the original setup dies when Claude is closed or expires
after 7 days; ours runs indefinitely.

### B. Real premarket-gap calculation (Step 5)
**Tutorial / first attempt:** yfinance's premarket numbers were ambiguous — what
we reported as "gap" was sometimes the day's performance, not the true premarket
gap.
**Our change:** compute the gap ourselves from 1-min bars with explicit ET
windows (previous close = last bar before 16:00 ET; premarket = 4:00–9:30 ET).
We also show Yahoo's displayed % next to ours so the difference is visible.

### C. DST-robust scheduling (Step 6/8)
**Tutorial:** cron in local time.
**Problem:** EU and US change daylight saving on different dates (~3 weeks/year
the Berlin↔ET offset drifts 1h), so a fixed local time hits the wrong US-market
moment.
**Our change:** each job fires at **two** local times; an ET self-gate in the
script lets only the run that hits the real US-market time proceed.

### D. Dual-run Scanner A (Step 5/6)
Yahoo's gainer screener at 9:00 ET doesn't yet reflect some overnight movers
(e.g. MU was missing). We added a second **merge** run at 9:45 ET that only adds
*new* gappers to the existing list — premarket first, then post-open completion.
Added company names + ISIN to every alert.

### E. Full exit lifecycle (beyond the tutorial)
The tutorial stops at entry signals (exits come in a later, broker-bound part).
We built `position_tracker.py`: on a PASS it opens a watched position and sends
exit alerts — partial profit at +1 ATR, 2% trailing stop, forced EOD close at
15:45 ET. Runs every 5 min for tight exit timing.

### F. Step 10 as an advisory, not a filter
**Tutorial's lesson:** the "obvious" SPY/QQQ regime filter *reduced* backtest
profit ($1,167 → $381) — a good filter on paper that hurt performance.
**Our take:** keep the **information**, drop the **over-filtering**. We show a
regime line (🟢/🟡/🔴, SPY & QQQ vs SMA200) on every entry signal, but it never
blocks a trade. The trader gets the context and decides.

### G. Anti-spam & stability
- Telegram only on the first run of the day or a genuinely new PASS.
- Chunked yfinance downloads + raised file-descriptor limit (fixed an
  `OSError: Too many open files` crash at ~100 tickers).

---

## Open questions for Shay

1. **Regime filter** — in your backtest it hurt. Have you tested it as a
   position-sizing input (smaller size in 🔴) rather than on/off? Curious whether
   that recovers the edge without the over-filtering.
2. **PMH/HOD source** — we pull these from yfinance even in MCP mode (they're
   cumulative maxima, so latency is harmless). Do you see value in taking them
   from TradingView too?
3. **Premarket volume** — yfinance returns 0 for premarket volume; TradingView
   has it. Worth wiring the MCP volume into Scanner A's filter?
4. **Exit logic** — does your Part-2 broker integration use the same
   ATR/trailing/EOD rules, or something else?

---

*Built on the Humbled Trader tutorial. Thanks, Shay — the foundation was solid;
these are just the production hardening on top.*
