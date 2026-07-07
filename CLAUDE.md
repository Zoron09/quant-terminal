# QUANT TERMINAL — PROJECT BIBLE
**Location:** `C:\Users\Meet Singh\quant-terminal`
**GitHub:** Zoron09/quant-terminal (branch: main)
**Purpose:** Cinematic stock screening terminal based on Minervini SEPA/Code33 methodology.

---

## ABSOLUTE RULES — READ BEFORE TOUCHING ANYTHING
1. NEVER touch `utils/code33_engine.py` or anything in `utils/` except `secfs_revenue.py` and `secfs_net_margin.py`
2. NEVER touch world grid CSS or navigation JS in `frontend/index.html`
3. NEVER use `&&` in PowerShell — use `;` instead
4. ALWAYS use Python patch approach for frontend changes (decode `__bundler/template` JSON → patch → re-encode with `<\/` escaping → write back)
5. ALWAYS inspect exact strings before replacing — never guess
6. ALWAYS run verify script after patching frontend
7. ALWAYS restart server and confirm at localhost:8000 after changes
8. ALWAYS commit and push after any confirmed working change
9. ALWAYS update this CLAUDE.md after any significant change
10. ONE change at a time — test after each
11. If something breaks — STOP, revert to last working git commit, document what happened
12. AFTER EVERY CHANGE — update the CURRENT STATUS section in CLAUDE.md to reflect what was done, then commit CLAUDE.md alongside the changed files in the same commit. No commit is complete without an updated CLAUDE.md.

---

## TECH STACK
- **Backend:** FastAPI — start with `.venv\Scripts\python.exe run.py`
- **Frontend:** Single file `frontend/index.html` (~810KB, Claude Design bundled)
- **Python for scripts:** `C:\Users\Meet Singh\AppData\Local\Programs\Python\Python314\python.exe`
- **Venv Python:** `C:\Users\Meet Singh\quant-terminal\.venv\Scripts\python.exe`
- **Server URL:** `http://localhost:8000`

---

## DATA SOURCES
| Source | Used For | Location |
|--------|----------|----------|
| secfsdstools | Revenue + Net Margin (primary) | `C:\Users\Meet Singh\secfsdstools\data\` — 426K reports, 69 quarters |
| edgartools | Revenue + Net Margin (targeted gap-fill only) | pip installed |
| yfinance | Chart, price, ownership, peers | pip installed |
| tradingview-scraper | News (primary) | pip installed |
| yfinance | News fallback | pip installed |

---

## FRONTEND ARCHITECTURE
Single file: `frontend/index.html`
The app code lives inside `<script type="__bundler/template">` as JSON-encoded string.
All edits: decode JSON → string replace → re-encode with `<\/` escaping → write back.

**World Grid Layout (DO NOT CHANGE):**
#world { position: absolute; width: 300vw; height: 300vh; top: 0; left: -100vw; }

#page-home     { left: 100vw; top: 0;     } ← center hub

#page-analysis { left: 100vw; top: 100vh; } ← swipe UP from home

#page-screener { left: 0;     top: 0;     } ← swipe LEFT from home

#page-journal  { left: 200vw; top: 0;     } ← swipe RIGHT from home

**Navigation:** `goTo(page)` translates `#world` div. Touch drag `passive: false`. Arrow keys work. DO NOT TOUCH.

---

## DESIGN SYSTEM (locked)
Background:     #000000 (all pages)

Cards:          #141416

Borders:        #2A2A2E

Accent gold:    #D4A843

Positive:       #34D399

Negative:       #F87171

Warning:        #FBBF24

Text primary:   #FAFAFA

Text muted:     #52525B
Fonts: DM Serif Display (headings), Inter (UI), IBM Plex Mono (numbers)

Homepage title: Bodoni Moda 900

---

## BACKEND API ROUTES
All routes in `api/server.py`. DO NOT touch engine files.
GET  /api/ticker/{ticker}          → {price, company_name, change, change_pct, status, market_cap_fmt, pe_ratio, week52_high, week52_low, avg_volume, eps_yoy}

GET  /api/chart/{ticker}?period=1y&interval=1d → {ticker, period, prices: [{date, close}]}

GET  /api/financials/{ticker}      → {earnings: [{date, revenue, rev_yoy, net_margin, net_margin_yoy, eps, eps_yoy}], balance_sheet: {}, cash_flow: {}, valuation: {}}

GET  /api/news/{ticker}            → {news: [{title, source, url, time}]}

GET  /api/ownership/{ticker}       → {institutional: [{name, pct}], insiders: [{name, role, date, value, type}]}

GET  /api/peers/{ticker}           → {ticker, peers: [{ticker, rev_yoy, npm, status}]}

POST /api/scan                     → {winners: [{ticker, company, sector, mcap, eps, rev, margin, status}], meta: {total, passed, insufficient}}

---

## CURRENT STATUS (update this after every session)

### ✅ WORKING
- Homepage: pure black, Bodoni Moda title, swipe hints, cube animation placeholder
- Navigation: all 4 directions, smooth physical slide, touch + keyboard
- Screener: CSV upload → Code33 scan → GREEN/YELLOW results cards → wired to `/api/scan`
- Journal: full sin-list trading journal (Analytics, Review, Trades DB, Missed Trades, Milestones) with IndexedDB persistence
- News: tradingview-scraper primary, yfinance fallback, 60s cache
- Chart: dynamic color (green/red), period % + $ gain label, YTD/1D/1W/1M/3M/1Y/5Y timeframes, 30s price poll

### ❌ BROKEN / PENDING
- FIX 2: Financials — Income Statement YoY Growth shows dashes, Net Income $0.0B (secfsdstools integration in progress)
- FIX 3: loadAnalysis() — ticker search doesn't update the page (fetches but doesn't re-render)
- FIX 4: Chart doesn't update when ticker changes
- FIX 5: Balance Sheet + Cash Flow show raw unformatted numbers
- FIX 6: Stats pills may show mock values instead of live API values

### 🔄 IN PROGRESS
- Batch Code 33 scan on 381-ticker Minervini CSV (running via direct engine call)
- `utils/edgar_revenue.py` / `utils/edgar_net_margin.py` confirmed bug (2026-07-07): quarter
  assembly only considers quarters strictly between two 10-K filings, so a ticker's newest
  quarter is invisible whenever it's the first quarter of a still-open fiscal year (confirmed
  live on NVDA — real 10-Q filed 2026-05-20 for period 2026-04-26, extraction succeeds, but
  never reaches the output). Fix scoped and pending explicit go-ahead, not yet implemented.

---

## ENGINE STATUS
- **CACHE_VERSION:** v30
- **Location:** `utils/code33_engine.py`
- **Signals:** ACTIVE / BROKEN / NOT ACTIVE / INSUFFICIENT / NOT APPLICABLE
- **Sources:** secfsdstools primary, edgartools targeted per-quarter gap-fill only (Finnhub
  and FMP fully removed 2026-07-06; raw hand-rolled SEC-XBRL tier and yfinance rev/NI
  fallback also removed same day — only two sources remain)
- **EPS:** Removed from Code33 signal AND no longer fetched at all (was Finnhub/EDGAR;
  out of scope entirely as of 2026-07-06) — manual verification via StockAnalysis.com
- **Quarter selection:** quarters-first target-date approach (2026-07-06/07) — computes the
  8 fiscal quarter-end dates that should exist as of today from each ticker's real
  `fy_end_month`, checks secfsdstools against that named list, targeted-fills only the named
  gaps from edgartools, reports genuinely-missing quarters by date via
  `sources['rev_missing']`/`sources['ni_missing']` instead of a generic INSUFFICIENT.
  Displayed dates are the real filed period-end, not the synthetic target. Fiscal
  quarter/year labels (`_get_fq_fy`) computed directly from `fy_end_month` — fixed
  mislabeling on non-Dec fiscal years (confirmed wrong before fix: CMP/Sept FYE, NVDA/Jan
  52-53-week FYE; TRT's pre-existing xfail in `tests/test_preflight_checks.py` references
  this same class of bug).
- Raw `'ni'` (absolute net income $) is intentionally always empty — neither remaining
  source exposes it, only the margin ratio.

---

## GIT WORKFLOW
git add <files>

git commit -m "type: description"

git push
Commit before any new change. Commit message must describe what was validated.

---

## LAST UPDATED
2026-07-07 — Removed Finnhub/FMP/raw-XBRL-tier/yfinance-fallback from code33_engine.py;
redesigned revenue+margin fetch to quarters-first targeted gap-fill; fixed real-filed-date
and fiscal quarter-label mismatches (CMP, NVDA); deleted 5 confirmed-dead files from the
Finnhub/FMP era. Confirmed but not yet fixed: edgar_revenue.py/edgar_net_margin.py structural
bug hiding each ticker's newest quarter until its fiscal year closes (see IN PROGRESS above).
