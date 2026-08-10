# QUANT TERMINAL — PROJECT BIBLE
**Location:** `C:\Users\Meet Singh\quant-terminal`
**GitHub:** Zoron09/quant-terminal (branch: main)
**Purpose:** Cinematic stock screening terminal based on Minervini SEPA/Code33 methodology.

---

## ABSOLUTE RULES — READ BEFORE TOUCHING ANYTHING
1. **The Code 33 engine now lives IN THIS REPO** at `code33/` (8 modules), with
   `utils/code33_adapter.py` as its adapter. Engine changes happen HERE, not elsewhere.
   The external `code33-screener` project is no longer a dependency — its editable pip
   install was removed 2026-08-01 (vendoring steps 5-6; the copy itself is commit
   `6107e77`). That repo still exists on disk and is still **read-only from
   quant-terminal sessions** — never modify it — but it is now a reference copy and the
   upstream of a one-time fork, not the running code.
   - **What changing `code33/` requires** (today's precedent, treat as the standard):
     a wide ticker regression — 20+ tickers spanning reported / derived-Q4 /
     edgartools-filled quarters, an excluded bank, an insufficient case, a restated
     ticker and a non-calendar fiscal year; a **byte-level comparison of the entire JSON
     payload** before and after, excluding only live market fields, with **zero
     tolerance** (one differing value = revert, don't patch); and **exactly one listener
     on port 8000 confirmed before any test** (stale workers have twice produced false
     results — see the 2026-08-01 entry).
   - **The dataset is still external.** `.secfsdstools.cfg` points at
     `code33-screener\data\` by absolute path. Vendoring moved the code, not the ~426K-report
     parquet dataset, so that directory must still exist. Fully removing the dependency is
     a separate, larger job.
   - `secfsdstools==2.4.3` / `edgartools==5.39.1` are PINNED in requirements.txt for this
     reason — the engine was validated against exactly these.
   - History: the old rule pointed engine work at the external repo and its
     `tools/regression_check.py` 19-ticker baseline; that suite still lives there and no
     longer covers the code that actually runs. Before that, the rule was "never touch
     `utils/code33_engine.py`" — retired 2026-07-22 when that file and its 5 helper
     modules were deleted in the code33-swap branch by explicit owner instruction.
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
13. NEVER ask Meet to run a live Wealthsimple login (`tools/wealthsimple_export.py` without a valid cached `tools/session.json`) as a routine verification step. Any change to that script or to `/api/journal/wealthsimple-latest` gets verified with `--dry-run` or the cached session first — real 2FA/credential entry is a rare, deliberate, Meet-initiated action only, never something asked for just to confirm a code change works.
14. ALWAYS reuse the SAME `--start-date` across repeated `tools/wealthsimple_export.py` runs (account inception, or a fixed date picked once) — never a rolling/shifting window. FIFO leg-matching has no state persisted between runs, so a wider or shifted range can pair the same closing leg with a different opener than a prior run did, producing a different `trade_id` for what's economically the same trade. Re-running the *same* range is always safe; this is a usage convention, not something the script validates or blocks.

---

## GSTACK POLICY

Applies to every session in this repo, including agent sessions. Recorded 2026-08-01 so
it never has to be re-explained. **Context that drives all of it:** the owner does not
write code and relies entirely on the agent to judge what is safe; this app reads and
stores **real brokerage data** (Wealthsimple session tokens in `tools/session.json`,
real account balances in `tools/account_balances.json`), and the server is deliberately
bound to `127.0.0.1` only. Anything that widens that blast radius is off the table.

### APPROVED — use when relevant
| Skill | Use for |
|---|---|
| `/office-hours` | **Before** writing code — clarify what is actually wanted first |
| `/investigate` | Root-cause debugging. No guessing at fixes |
| `/gstack-review` | Post-implementation bug hunt (renamed from gstack's `/review` — see collision note below) |
| `/guard` (or `/careful` + `/freeze`) | Safety rails — warn before destructive commands, restrict edits to one folder while debugging |
| `/document-release` | Keep CLAUDE.md and docs in sync with what actually shipped |
| `/qa` | Local browser testing of the running app |
| `/cso` | Read-only security scan |

`/office-hours` and `/guard` pair naturally with existing rules 10 (one change at a
time) and 11 (stop and revert on breakage). `/document-release` serves rules 9 and 12.

### NEVER USE — even if the owner forgets to say so
| Skill | Why |
|---|---|
| `/land-and-deploy`, `/setup-deploy`, `/canary` | No deploy pipeline exists, and none is wanted. Ever |
| `/ship` | No auto-push, no auto-PR. The owner reviews and pushes manually |
| `/scrape` | No web scraping — already decided against on legal grounds |
| `/open-gstack-browser`, `/setup-browser-cookies` | Never import the owner's real browser login/cookies into an automated session. Non-negotiable while the Wealthsimple integration exists — it would put live brokerage auth inside an agent-driven browser |
| `/design-*` (`design`, `design-consultation`, `design-html`, `design-review`, `design-shotgun`), `/plan-ceo-review`, `/autoplan` | No unprompted scope expansion |

**If a task seems to call for something in the NEVER USE list — STOP and ask.** Do not
decide it is fine this once. "It would be easier if I just deployed/pushed/scraped" is
exactly the reasoning this list exists to block. Same standard as rule 13: the fact
that a shortcut would work is not authorization to take it.

### Install state (2026-08-01) — manually registered, `./setup` deliberately NOT run
Cloned to `~/.claude/skills/gstack`. **`./setup` was never run and must not be run
without asking** — it requires `bun` (absent by design, see below). Instead the 8
approved skills were registered by hand: their directories were copied to
`~/.claude/skills/<name>/` (SKILL.md plus `sections/`, `checklist.md`, `specialists/`,
`bin/` as applicable). 28 files, verified file-count-identical to source.

**Not installed, by explicit decision:** bun, Playwright, Chromium, `@ngrok/ngrok`.
`~/.claude/settings.json` untouched — no gstack hooks. `~/.gstack/` does not exist.

**What this means in practice.** `/guard`, `/careful`, `/freeze` are 100% complete —
their only helpers are bash. `/cso` and `/document-release` are also complete.
`/office-hours`, `/investigate` and `/review` run their full method but silently skip
gstack's cross-session decision store (`bin/gstack-decision-log` / `-search` need bun;
the search call is already gated + `2>/dev/null`, so it no-ops cleanly). `/review` also
skips Step 3.4 (version queue) and Step 3.5 (slop scan) — both marked "advisory, never
blocks review" in the skill itself. `/office-hours` loses only its optional Visual
Sketch sub-flow. **`/qa` is deliberately NOT registered** — it genuinely needs the
browser stack; registering it is a separate decision, not an oversight.

**Name collision — RESOLVED by rename (2026-08-01).** gstack ships its review skill as
`review`, which collides with the Claude Code built-in `/review` (review a GitHub PR);
the built-in won and gstack's never surfaced. It was renamed on registration:
directory `~/.claude/skills/gstack-review/`, frontmatter `name: gstack-review`.
**Invoke it as `/gstack-review`.** Both built-ins are unaffected and still mean what
they always did — `/review` for a GitHub PR, `/code-review` for the working diff.
The rename is local to the registered copy only; the clone at
`~/.claude/skills/gstack/review/` keeps its original name, and the renamed skill still
reads its specialist files from there by absolute path, so re-cloning or updating
gstack does not undo the rename but also does not re-collide.

Two things to know before anyone reconsiders `./setup`:
- It wants to install **Playwright + Chromium** and **`@ngrok/ngrok`**. ngrok is a
  tunnelling library that can expose a localhost server to the public internet. That
  is a direct conflict with the deliberate `127.0.0.1` binding — installing the
  library does not open a tunnel by itself, but it is the capability sitting one
  command away on a machine holding live brokerage credentials.
- It offers to add `PreToolUse`/`PostToolUse` hooks to `~/.claude/settings.json`.
  Non-interactive runs skip this and print the commands instead; it backs up
  settings.json before any mutation. Do not opt in without asking.

---

## TECH STACK
- **Backend:** FastAPI — start with `.venv\Scripts\python.exe run.py`
- **Frontend:** Single file `frontend/index.html` (~810KB, Claude Design bundled)
- **Python for scripts:** `C:\Users\Meet Singh\AppData\Local\Programs\Python\Python314\python.exe`
- **Venv Python:** `C:\Users\Meet Singh\quant-terminal\.venv\Scripts\python.exe`
- **Server URL:** `http://localhost:8000` — bound to `127.0.0.1` only as of 2026-07-15 (was `0.0.0.0`).
  **If you've been reaching this app from another device on your LAN (phone, another PC via
  your machine's real IP), that access is now gone** — only this machine can reach it. Change
  `--host` back in `run.py` if that LAN access is actually wanted; this wasn't silently assumed
  to be fine, it's a deliberate tradeoff for the Wealthsimple auto-sync feature below.

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

#page-news     { left: 100vw; top: -100vh; } ← swipe DOWN from home (added 2026-08-04)

**On `#page-news` sitting outside `#world`'s 300vw x 300vh box:** deliberate, and it needs no
change to `#world`. The only clipping rule in the file is `#viewport { position: fixed; inset: 0;
overflow: hidden; }`, which clips to the SCREEN — that is the mechanism the whole grid relies
on. `#world` sets no `overflow` of its own, so a child above it renders normally once the world
translates down. **The journal cell at (200vw, 0) is dead but must NOT be repurposed** —
`nav('journal')` redirects to `/journal` before ever reading `PAGES.journal`, so taking the cell
would steal the left-from-home gesture.

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

POST /api/scan                     → starts background job: {job_id, total, resumed_from, running} (409 {error, job_id} if one is already running)

GET  /api/scan/status              → {running, done, error, total, completed, current_ticker, winners: [{ticker, company, sector, mcap, eps, rev, margin, status}], excluded_banks: [tickers], meta: {total, passed, insufficient, excluded_banks}}

**News Scanner (Stage 1)** — routes live in `api/news_scanner.py`, NOT server.py. Separate
universe from `/api/news` above: different prefix, different store, no shared code.

GET    /api/news-scanner/feed?mode=market|watchlist&q=&limit= → {mode, query, session_date, count, items: [{id, source, ticker, company, headline, url, published, first_seen, meta}]}

GET    /api/news-scanner/status    → {poller_running, primed, in_market_window, market_window_et, now_et, scan_running, session_date, items_in_memory, items_today, watchlist_size, sources: {edgar|finnhub_general|finnhub_company: {last_ok, last_error, last_attempt, items}}, intervals: {}}

GET    /api/news-scanner/watchlist → {tickers: []}

POST   /api/news-scanner/watchlist/{ticker}   → {tickers: []}   (400 on a malformed symbol)

DELETE /api/news-scanner/watchlist/{ticker}   → {tickers: []}

---

## CURRENT STATUS (update this after every session)

### ✅ WORKING
- Homepage: pure black, Bodoni Moda title, swipe hints, cube animation placeholder
- Navigation: home/analysis/screener still slide (touch + keyboard); journal direction now redirects to `/journal` (real page load) instead of sliding, since the working journal lives outside the `#world` grid — see Journal entry below
- Screener: CSV upload → Code33 scan → GREEN/YELLOW results cards → wired to `/api/scan`
- Journal: separate standalone page at `frontend/journal.html` (sin-list's original file, restyled to quant-terminal's monochrome/white accent + underline tabs, own everything else — not merged into the bundled SPA). `GET /journal` serves it directly; `nav('journal')` in the SPA's bundled `nav()` redirects there (`window.location.href = '/journal'`) instead of sliding the world grid.
- Wealthsimple auto-sync (2026-07-15): `/api/journal/wealthsimple-latest` now also triggers a debounced background refresh (5 min minimum between attempts, single-worker `ThreadPoolExecutor`, genuinely fire-and-forget — the handler never calls `.result()`/awaits it, proven via concurrent-request testing that other requests stay fast while a fetch is in flight) using `tools/wealthsimple_export.py`'s `get_cached_api_or_none()` / `run_export_with_cached_session()`. **Only ever uses the existing cached `tools/session.json`** — no password/2FA path exists in this code at all; missing/expired session degrades to serving last-known-good cached data with `live_sync: {last_attempt_ok: false}` in the response, never a crash or hang. Auto-refresh reuses whichever `--start-date` the most recent manual `ws_import_<start>_<end>.json` used (rule 14 — never a shifting window) and does nothing if no manual export has ever been run yet. `_atomic_write_json` (in `wealthsimple_export.py`) now qualifies its temp filename with the process PID so the server's auto-fetch and a manual CLI run can never collide on the same temp file.
- Current Capital stat card (2026-07-15): a real Wealthsimple NAV (`financials.currentCombined.netLiquidationValue`), not derived from trade P&L — this field is already returned by the same `get_accounts()` call `_build_account_labels()`/`_get_account_ids()` already make (no new API scope, no extra network call). New `_build_account_balances(api, account_labels)` writes `tools/account_balances.json` (gitignored — real balance data) as a sibling to `ws_import_latest.json`, keyed by the same resolved label used for `trade.acc`, **summed** (not overwritten) when two raw accounts resolve to the same label — confirmed against real data that this actually happens (two of Meet's cash sub-accounts both carry the nickname "Meet"); naively overwriting silently dropped one account's real dollar balance. Frontend's "Combined" sums only the accounts the switcher itself tracks (labels actually present in `TRADES`), not every Wealthsimple account on the profile — Meet's FHSA/RRSP/unrelated cash accounts don't inflate it.
- **News Scanner tab (2026-08-04, Stage 1 of 5)**: new page in the world grid's previously
  unused **down-from-home** direction (`#page-news` at `top:-100vh`, `PAGES.news = {x:0,
  y:+innerHeight}`). Headlines only — SEC EDGAR 8-K current-events feed + Finnhub general
  market news, whole-market/watchlist toggle, today-only session history with search.
  Backend is `api/news_scanner.py`: one daemon-thread poller (never an asyncio task — the
  event loop already blocks on `/api/financials`), its own store behind its own lock, its
  own SQLite at `data/news_session.db` (WAL, gitignored). Never calls `get_code33_data()`,
  so it never touches `_PIPELINE_LOCK`. **Stages 2-5 not built:** catalyst tagging +
  visual highlight (2), full article text via trafilatura (3), wire RSS + dedup (4).
- News: tradingview-scraper primary, yfinance fallback, 60s cache
- Chart: dynamic color (green/red), period % + $ gain label, YTD/1D/1W/1M/3M/1Y/5Y timeframes, 30s price poll

### ❌ BROKEN / PENDING
**⚠️ All FIX items below predate the 2026-07-22 engine swap and have NOT been re-checked
against the current engine.** Treat them as unverified reports, not confirmed open bugs —
FIX 2 in particular describes the `/api/financials` path that commit `64a5757` rerouted and
that the 2026-08-01 adapter change altered again.
- FIX 2: Financials — Income Statement YoY Growth shows dashes, Net Income $0.0B (secfsdstools integration in progress)
- FIX 3: loadAnalysis() — ticker search doesn't update the page (fetches but doesn't re-render)
- FIX 4: Chart doesn't update when ticker changes
- FIX 5: Balance Sheet + Cash Flow show raw unformatted numbers
- FIX 6: Stats pills may show mock values instead of live API values

### 🔄 IN PROGRESS
- **Dead code flagged, not removed:** `frontend/index.html`'s bundled `#page-journal` div and
  `renderJournal()` (+ its ~71 supporting functions, `.sin-journal` CSS block) are now
  unreachable — `nav('journal')` redirects to the real `/journal` page (`frontend/journal.html`)
  before ever touching `PAGES.journal`/`#page-journal`. Left in place deliberately (not deleted
  this session) so it doesn't quietly rot as confusing dead code without a record — cleanup
  candidate for a future session, not urgent.
- **⚠️ PRE-SWAP — needs re-confirmation before being treated as current.**
  **Count-gate double-merge redundancy** (found 2026-07-11 during META testing). Every file
  named below (`secfs_revenue.py`, `secfs_net_margin.py`, `code33_engine.py`) was DELETED in
  the 2026-07-22 engine swap, so this describes a pipeline that no longer exists. The same
  class of redundancy may or may not be present in code33-screener — the 2026-07-31 pass did
  observe the revenue series being built twice per call (logged in `bug_report.md`), which
  looks related but was not traced back to this mechanism. Kept for the diagnosis, not as a
  live to-do:
  `secfs_revenue.py`/`secfs_net_margin.py`'s inner secfsdstools→edgartools fallback gates on
  `len(merged) >= n_quarters` (a pure count, no recency check), so it wrongly skips edgartools
  whenever secfsdstools already has ≥16 *old* quarters but is missing the single newest one —
  the normal steady state, since the local secfsdstools bulk dataset lags live filings by ~1
  quarter by design. `code33_engine.py`'s own separate date-aware target-quarter check catches
  the gap and re-fetches via edgartools itself, so this is currently a **performance cost only,
  not a correctness bug** (confirmed: NVDA's 2026-04-26 quarter still reaches output, just after
  a redundant ~19-33s/metric live re-fetch). Hits 13 of 16 regression tickers. Plan (not
  implemented): give the inner check the same recency-awareness instead of a bare count, then
  delete code33_engine.py's now-redundant outer retry block. See `bug_report.md` for full
  writeup — "Solution prepared, not yet implemented".
- ~~**TRT margin output not re-verified under the new NI-tag order (2026-07-09).**~~
  **RESOLVED — this entry was stale.** `bug_report.md` closed it on 2026-07-12: TRT's NI tag
  selection was never wrong (the extracted value exact-matched its filed net income); the real
  defect was the unrelated `_to_m()` unit-conversion bug, fixed in `8f620c4`. CLAUDE.md was
  never updated to match. Kept as a struck-through line rather than deleted so the
  contradiction between the two files is visible rather than silently erased.

---

## ENGINE STATUS
- **CACHE_VERSION:** v32-code33-vendored (this line said `v31-code33-screener` until
  2026-08-06; the bump happened during vendoring and the doc was never updated —
  corrected against the constant in `utils/code33_adapter.py`, no code change)
- **Location:** external `code33-screener` project (`pip install -e`), adapted through
  `utils/code33_adapter.py` — the ONLY in-repo engine file. The old
  `utils/code33_engine.py` + 5 helper modules (`secfs_revenue`, `secfs_net_margin`,
  `edgar_revenue`, `edgar_net_margin`, `sec_edgar`) were deleted 2026-07-22
  (code33-swap branch).
- **Pipeline:** secfsdstools primary (VALIDATED dataset shared with code33-screener via
  project-root `.secfsdstools.cfg` — absolute paths, gitignored, example committed;
  deliberately NOT the ~/.secfsdstools.cfg dataset, which was built with the unsafe
  parallel-download settings), live-EDGAR gap fill for quarters the bulk mirror lacks.
  Validated against SEC filings, a 19-ticker regression baseline, and a 568-ticker
  universe run in the code33-screener project.
- **Concurrency:** pipeline is STRICTLY SEQUENTIAL — a global lock inside
  `utils/code33_adapter.py` serializes every pipeline call server-wide (all endpoints +
  the background scan job). Endpoints offload via `run_in_threadpool` so the event loop
  stays live. Never add a worker pool around the pipeline.
- **Scan:** `/api/scan` is now a background, checkpointed, resumable job
  (`data/scan_jobs/scan_<hash>.csv`, job identity = hash of sorted ticker list; frontend
  polls `GET /api/scan/status` every 3s). Real scans run hours at 15-40s/ticker.
- **Banks:** bank/depository tickers return `status='excluded_bank'` (pipeline refuses to
  score them — their revenue is silently wrong under standard XBRL tags, confirmed on
  FULT). Frontend shows an explicit "EXCLUDED — BANK, NOT YET SUPPORTED" badge and an
  "Excluded — Banks" scan pill, never a silent disappearance.
  - **Refined 2026-08-07 — `BANK_SIGNAL_TAGS` alone is only a tripwire, not the verdict.**
    It fired on 4 non-lenders (KMX, LOVE, SKWD, PLXS). `_is_really_a_bank()` in the adapter
    now confirms it: a ticker is excluded unless it files **no lending-income concept at all**
    (vestigial signal) or lending income is **< `_BANK_LENDING_SHARE` (50%)** of revenue —
    and in both cases only when a usable revenue series exists. Unmeasurable stays excluded.
    HASI (68.5%) is correctly excluded; near-threshold cases need a human tie-breaker, see
    the docstring. 96 excluded as of the 2026-08-07 scan, down from 100.
- **Status semantics:** `_c33_status` (green/yellow/red/insufficient badge) — **corrected
  2026-08-06, no longer the verbatim pre-swap port.** It now evaluates the spec's real
  window: **4 YoY rates / 3 acceleration jumps** (`_ACCEL_RATES = 4`), not the 3 rates /
  2 jumps it had been checking since the swap. The `d2 >= d1` second-derivative test for
  green is also gone — acceleration means each rate exceeds the prior one, nothing more.
  Frontend contract (the field and its four values) is unchanged.
  - **YELLOW is now effectively a dead tier** — it used to mean "positive but shrinking
    jumps", which *was* the second-derivative test. 0 yellow across all 606 tickers on the
    2026-08-06 scan. `_scan_state['passed']` counts green + yellow, so it is now just the
    green count. Reconciling these tiers with the spec's ACTIVE/BROKEN/NOT ACTIVE
    vocabulary is an open, deliberately deferred decision.
  - **`_MIN_RATES = 3` is deliberately NOT raised to 4.** It gates scoreability only;
    raising it would move short-history tickers red → insufficient, changing the failure
    taxonomy rather than the acceleration check. A 3-rate ticker still cannot go green.
- **Restatement basis — BOTH legs, as of 2026-08-09.** When a filer republishes a quarter,
  revenue YoY (`_yoy_value()` in the adapter, since 2026-08-02) **and** net margin
  (`_restated_basis()` in `code33/net_margin.py`, since 2026-08-09) both compute on the
  recast figure. Displayed `rev` / `ni` / `npm` inputs stay as-filed; only the comparison
  basis moves. The two helpers are deliberate mirrors — change one, change the other.
  **Known vocabulary caveat:** `restated` means "a later filing published a different
  figure for this `ddate`", which on MAGN is a different *entity's* figure after a reverse
  merger, not a correction. See the 2026-08-09 entry under LAST UPDATED.
  - **Which point sources get flagged (2026-08-09):** `_RESTATEMENT_ELIGIBLE_SOURCES` =
    `("reported", "derived_fy_minus_quarters")`. Derived Q4s were excluded until then on a
    justification that proved false. **`edgartools` is still excluded and that is a known
    open gap, not a decision** — `_fill_gaps` builds those points after the flagger has
    already run, so they are never offered to it. It affects the NEWEST quarters, i.e.
    inside the scoring window. Deferred, needs its own investigation.
  - **Candidate matching is exact on tag, and guarded against annual mis-tags.** Both are
    load-bearing and evidence-backed — see the 2026-08-09 (later) entry. Do not loosen the
    tag match; do not replace the guard with a magnitude threshold.
- **EPS:** still out of scope entirely. Raw `'ni'` is NO LONGER empty as of
  2026-08-01 — it carries real per-quarter net income, alongside new
  `rev_sources`/`ni_sources` and `ni_restated`/`ni_restated_value`. All EPS
  fields (`eps`, `eps_labels`) remain empty — that is EPS-specific and says
  nothing about the fiscal-quarter labels: as of 2026-08-01 `rev_labels`/
  `npm_labels` are populated and correct on **every** quarter, including
  edgartools-filled ones (previously blank) and Q4s (previously `FY FY24`).
  Neither array has a frontend consumer today. See the 2026-08-01 entry under
  LAST UPDATED and the two CLOSED label entries in `bug_report.md`.
- **Failure labelling:** every `status='insufficient'` path now sets a real
  `excluded_reason`. The success path used to hardcode `''` (11 of 540 tickets on the
  last full scan reported as `insufficient (unspecified)`); `_diagnose_insufficient()`
  in the adapter now names the cause and `_classify_failure()` in `api/server.py`
  buckets it using code33-screener's `universe_scan.py` taxonomy, plus one new bucket
  — **`no reported revenue (pre-revenue company)`**. Diagnosis is derived from the same
  data `_c33_status` sees, and `_yoy_miss_cause()` mirrors `yoy_for()`'s walk exactly so
  the two can never disagree.

---

## GIT WORKFLOW
git add <files>

git commit -m "type: description"

git push
Commit before any new change. Commit message must describe what was validated.

---

## LAST UPDATED
2026-08-09 (later) — **Restatement detection was skipping every derived Q4.** Engine fix,
**`code33/quarterly_engine.py` only**, stacked on the margin fix below. Full writeup,
scope table and the deferred items in `bug_report.md`.
  - **What was wrong.** `_attach_restatement_flags` gated on `source != "reported"`, so a
    derived Q4 could never be flagged even when the filer's own later filing published a
    different discrete figure for that period. The stated reason — "a derived value
    combines multiple filings, so there's no single figure to check" — **was tested and is
    false**: it describes the point's own provenance, which the query never reads. Derived
    points carry both fields it needs (`.adsh`, `.tag`).
  - **Scope, measured on the full 606 before implementing: 27 tickers, 37 quarters**, each
    triaged against `data.sec.gov`. **Not a reverse-merger niche** — the dominant class is
    the ordinary continuing-ops recast (JNJ/Kenvue, DD/Qnity, CALY/Topgolf, ADEA/Xperi,
    PBI/GEC), and **30 of 37 later figures come from a 10-K comparative**, not a
    fiscal-calendar change.
  - **The DINO guard is not optional.** HF Sinclair's FY2025 10-K tags $28,580,000,000 for
    2024-10-01..2024-12-31 as `qtrs=1` — bit-identical to the `qtrs=4` FY fact in the SAME
    filing, i.e. a filer XBRL error at SEC. Naively extending the flag would have replaced
    DINO's correct derived Q4 ($6.5B) with an annual figure and dragged a quarter **inside
    the 4-rate scoring window from -0.55% to -77.38%**. `_is_annual_mistagged_as_quarter()`
    rejects a candidate equal to a `qtrs=4` fact in the same accession — an **input check,
    deliberately not a size heuristic** (the ±1000% guard lesson), applied before the
    latest-filed sort so a genuine earlier restatement can still win.
  - **Two things deliberately NOT done, both evidence-backed:** exact-tag matching kept
    (relaxing it surfaces 7 cross-*concept* false positives — `NetIncomeLoss` vs
    `ProfitLoss`, `Revenues` vs `RevenueFromContractWithCustomer...`), and no
    magnitude/precision threshold added (the 5 sub-0.5% findings round away at 2dp with
    zero downstream effect).
  - **`utils/code33_adapter.py` untouched** — `_yoy_value()` and `_restated_basis()` both
    key off `restated`/`restated_value`, so this propagates automatically, same as the GE fix.
  - **Verified:** 75-ticker (27 affected + 48 controls, all five statuses) **byte-level
    whole-payload comparison, 2,100 keys — 12 changed, 63 byte-identical, ZERO control
    violations, ZERO status changes**; the 12 are exactly the 13 predicted minus DINO.
    **DINO byte-identical, guard proven**, including its three pre-existing reported-point
    flags left untouched. **MAGN corrected 119.11% → 35.26%**, matching prediction.
    **Containment universe-wide: 14,955 reported points across all 606, zero behaviour
    changes.** Single listener confirmed; fixed code confirmed live over HTTP.
  - **"Zero status changes" is coincidence, not protection.** Eight tickers have an
    affected value INSIDE the scoring window (DINO, CALY, DD, MCFT, MIDD, PAG, PAA, PAGP),
    moving 2.6–59pp; `_c33_status` reds on any negative transition, so that size of move
    flips a sign trivially. PAG — the one status change in the GE fix — moved +0.64 →
    -3.82 in-window without crossing. Expect a nonzero rate as quarters land.
  - **Fresh full 606-ticker scan** (checkpoint archived, `resumed_from: 0`), 606/606,
    breaker not tripped: green **9 → 9**, yellow **1 → 1**, red **419 → 419**,
    insufficient **81 → 81**, banks **96 → 96**. **Zero status changes universe-wide, every
    bucket identical.** 35 tickers moved a scored value, separating cleanly: **6 in-place,
    all in the affected set** (CALY, DD, MIDD, PAA, PAG, PAGP) — that is the fix — and
    **28 pure window shifts** (`old[1:] == new[:-1]`), which this fix cannot structurally
    cause since it changes a comparison basis and cannot append a quarter; those are 10-Qs
    filed since the 2026-08-07 baseline, arriving via the live edgartools leg (the local
    bulk dataset is unchanged, parquet mtimes all 2026-07-21). **One anomaly, PVLA,
    investigated and cleared** — in-place margin move, not in the affected set, proven
    **byte-identical** with the fix reverted in memory, so it is live-leg drift, not this
    change.
  - **TWO DEFERRED FOLLOW-UPS, neither fixed here.** (1) **`edgartools` fills are outside
    the restatement mechanism entirely, and it is bigger than the gap just closed** —
    `_fill_gaps` builds those points AFTER `get_quarterly_series` has already run the
    flagger, so they are never offered to it; fixing it means moving the flagger, not
    adding a source string, and it hits the NEWEST quarters, i.e. inside the window.
    (2) **A NaN `restated_value` breaks `/api/financials` for IDYA** — returns
    `{"error":"Out of range float values are not JSON compliant: nan"}`. **Pre-existing,
    dating to the GE fix (2026-08-02)**, proven by reconstructing `b53835d` behaviour in
    memory; exactly 1 point universe-wide out of 14,955.

2026-08-09 — **Net margin now computes on the filer's recast basis, same as revenue YoY.**
Engine fix, **`code33/net_margin.py` only**. Full writeup in `bug_report.md`.
  - **What was wrong.** `pair_margin_series()` computed the margin from as-first-filed
    figures on both legs, while `_yoy_value()` in the adapter had computed revenue YoY on
    the filer's own recast basis since the GE fix (2026-08-02). Two legs of one signal, two
    different bases. The ratio was never internally incoherent — numerator and denominator
    always came from the same filing — but the **acceleration test** one level up saw a
    since-corrected quarter sitting next to never-revised neighbours, making a transition
    that is partly artifact.
  - **Fix:** new `_restated_basis(point)`, mirroring `_yoy_value()` exactly, applied to
    **both** legs. Display values deliberately unchanged — `MarginPoint.net_income` /
    `.revenue` still carry the as-filed record, with the four `*_restated*` fields
    alongside. Calculation basis lives in separate locals so reusing the display ones
    could not silently rewrite the as-filed arrays.
  - **Scope, measured before implementing (full 606):** 25 tickers carry a restated NI in
    the displayed window, 20 margin series actually move, **ZERO statuses change**. A
    latent correctness gap closed, not an active scoring bug.
  - **MAGN's ~69% "restatement" is a reverse merger, not a data error.** Verified against
    raw `data.sec.gov` XBRL, bypassing secfsdstools/edgartools: as-filed $329,443,000
    (Glatfelter 10-Q, 2024-04-01→2024-06-30) vs $556,000,000 (Magnera 10-Q filed
    2025-08-06, 2024-03-31→2024-06-29). Engine `rev_restated_value` = **556,000,000
    exactly**. Treasure Holdco (Berry's health/hygiene/specialties nonwovens business) was
    the **accounting acquirer** in the 2024-11-04 Reverse Morris Trust; CIK 41719's
    `formerNames` shows Glatfelter → Magnera and `fiscalYearEnd` moved 12/31 → 09/26. So
    the two figures are **different reporting entities over near-identical windows —
    neither corrects the other.** They pair because DERA rounds `ddate` to month-end, so
    06-29 and 06-30 collide. Value accurate; only the word "restated" is imprecise.
  - **Verified:** full 606-ticker byte comparison passed, zero unexplained status changes,
    single listener confirmed before testing.

2026-08-07 (evening) — **The app could not boot from `requirements.txt`. Fixed.** Packaging
only, no engine change. Full detail in `bug_report.md`.
  - **Hard boot failure on any clean install:** `RuntimeError: Form data requires
    "python-multipart" to be installed`, raised from inside `@app.post("/api/scan")` at
    import time — before the socket opens, so nothing is reachable. `/api/scan` takes
    `UploadFile = File(...)` and FastAPI cannot build that route without it.
  - **Caused by `bdf1e71`.** `python-multipart` was only ever a **transitive dep of
    `streamlit`** (`Required-by: streamlit`). Removing streamlit was correct — zero imports,
    re-confirmed, and there are **no dynamic imports anywhere** in the codebase — but it took
    the only declaration of `python-multipart` with it. Invisible locally because the `.venv`
    still has streamlit: removing a line never uninstalls anything.
  - **Two more gaps found in the same pass:** `FinNews` and `tradingview-scraper` (both
    `/api/news` sources) were undeclared, so a clean install silently degraded the endpoint
    to its yfinance fallback while still returning HTTP 200. And declaring them was **not
    enough** — both do a bare `import pkg_resources`, which **setuptools deleted in 81.0.0**;
    a fresh install pulls 83.x while the `.venv` has 80.10.2. Needed a `setuptools<81`
    ceiling on top.
  - **Fix: 4 lines**, pinned to what the running env actually has —
    `python-multipart==0.0.32`, `FinNews==1.1.0`, `tradingview-scraper==0.4.20`,
    `setuptools<81`.
  - **STANDING RULE, now written at the top of `requirements.txt`: any dependency change must
    BOOT THE APP, not just import modules.** An import-only smoke test passed this file twice
    while the app could not start — every declared package imported fine; the problem was one
    that was never declared.
  - **Verified** in a throwaway venv (Python 3.12.8), with `python-multipart` deliberately
    uninstalled first so the file had to supply it: clean install exit 0, **no crash, exactly
    one listener** (PID 6180), AAPL → red, `/api/financials` 8 real quarters, `/api/scan`
    upload 1/1, and **`/api/news` 30 items with zero source failures** (15 Seeking Alpha via
    FinNews, plus Reuters/TradingView/Dow Jones via tradingview-scraper) — up from 10
    yfinance-only. **Real `.venv` and running server untouched throughout**, re-verified.

2026-08-07 (later) — **Bank exclusion no longer fires on non-banks; PLXS revenue scale bug
fixed.** Two fixes with a hard dependency between them. Full detail, distribution table and
the recorded wrong turns in `bug_report.md`.
  - **4 companies were excluded as banks and are not lenders:** KMX (CarMax — captive auto
    finance behind a used-car retailer), LOVE (Lovesac, furniture), SKWD (Skyward, insurance),
    PLXS (Plexus, electronics). KMX's revenue was being read **correctly all along** (priority-1
    `Revenues`, $6-8B/qtr, verified against SEC), so the exclusion's one stated justification —
    revenue silently wrong under standard tags, proven on FULT — never applied to it.
  - **Metric: lending income ÷ total revenue**, chosen semantically, never by tag-priority.
    A first attempt ratioing "whichever `BANK_SIGNAL_TAGS` entry fired first" was **unsound
    and would have released real lenders** (WRLD 12.9%→ actually 87.3%; ATLC 0.1% → 100.0%),
    because `NoninterestIncome` is by definition the NON-lending part. Recorded in
    `bug_report.md` so it isn't retried.
  - **Threshold 50%** = "majority of the business is banking/lending". Validated across all
    100 excluded tickers: KMX 5.8%, then **nothing until 68.5%**, lowest genuine lender
    70.2%. Chosen for what it means, not where it sits. **HASI (68.5%) stays excluded** —
    specialty finance, majority interest income, correctly a bank even though its own numbers
    are accurate. Standing guidance for a future near-threshold case is documented in-code as
    a **human** tie-breaker (read the company's own 10-K business description), deliberately
    not encoded.
  - **Two branches, both requiring a usable revenue series:** files no lending-income concept
    at all (vestigial signal — provably safe, 97/100 file one and every bank-SIC ticker does),
    or files one but lending is a minority of revenue. Unmeasurable stays excluded.
  - **A defect in my first implementation, caught by verification:** I omitted the
    "AND a usable revenue series exists" condition, and it **released NEWT (NewtekOne, a
    genuine National Commercial Bank)** whose ratio computed off a mismatched pair at 4.4%.
    Fixed against the pulled series; NEWT is excluded again.
  - **PLXS scale bug (separate, and a hard dependency):** SEC carries
    `...ExcludingAssessedTax` in **thousands** and `...IncludingAssessedTax` in dollars for
    the same period on 6 quarters, so the edgartools fill returned values **1000x too small**.
    Fixed with a scale guard in `fetch_discrete_quarter` that **skips** a candidate under
    1/100th of the series' established magnitude so priority falls through to the next tag,
    recovering the correct figure. Self-limiting — no established scale, no guard.
    Universe-wide the true signature (same mantissa, power-of-1000 apart) hits **3 of 606**
    (PLXS 2026, IRDM 2018, LUV 2011); only PLXS has live impact. **PLXS needed both fixes** —
    releasing it first would have scored it on broken data.
  - **Verified:** 100 excluded + 51 controls captured before any edit; **4,116-key byte
    comparison, all 96 non-released excluded tickers and every control byte-identical**; OSCR
    was the sole diff and is proven new-filing drift (its 10-Q landed the same day; every
    overlapping value bit-identical with the window advanced one quarter). One listener
    confirmed (PID 18640); HTTP verified. **Fresh full scan** (`resumed_from: 0`), 606/606:
    red 415 → **419**, excluded_bank 100 → **96**, insufficient **81 → 81**, green **9 → 9**,
    yellow **1 → 1** — exactly the 4 intended changes, nothing else moved.

2026-08-07 — **Revenue sign gate corrected: it rejected Minervini's own worked example.**
Second methodology fix confirmed directly against the source material. Full detail and the
scope table in `bug_report.md`.
  - **What was wrong.** `_c33_status` ran `if any(r < 0 for r in rev_w): return 'red'` —
    one negative rate anywhere in the 4-rate window was an instant reject, *before* the
    acceleration test. Minervini's own qualifying Code 33 revenue sequence
    (*Trade Like a Stock Market Wizard*, ch. 8) is **−22% → +3% → +16% → +38%**, and his
    EPS example starts at −34%. The gate threw both out on the first element.
  - **Never a data guard.** Entered `b565b72` (2026-06-23) citing a "CLAUDE.md §8" that no
    longer exists; no `bug_report.md` justification ever existed; and `CODE33_SPEC.md`
    never required it — §1 is a pure ordering condition and §5 explicitly **keeps**
    sign-flipped rates as `[NM]`. It also created an unexplained asymmetry: margin has no
    sign gate and correctly accepts `-6.42 → -4.49 → -2.57 → -2.32` (XMTR is GREEN on that).
  - **The rule shipped is a refinement, not a blanket removal:** only the **newest** rate
    must be positive (`if rev_w[-1] < 0`). The methodology wants real growth, not less
    shrinkage — for turnarounds it demands strongly positive current results — and his
    example *ends* at +38%. A sequence like `-50 → -40 → -30 → -20` accelerates while
    revenue still falls every quarter, and stays red. Revenue-only; **margin unchanged**;
    the transition test untouched.
  - **`utils/code33_adapter.py` only — `code33/` untouched.** `_c33_status` is badge
    logic; `code33/` is data extraction. Same boundary as the acceleration fix.
  - **Scope (measured before implementing, full 606):** the gate was short-circuiting
    **126** tickers whose newest rate is positive; 121 were red on transitions anyway, so
    it masked a correct answer, and **5 were genuinely wrong**. **59** tickers with a
    negative newest rate stay red — the population the refinement protects. Zero
    divergence from blanket removal today.
  - **Verified:** full 606-payload baseline captured before the edit; **1,596-key byte
    comparison across 57 tickers, zero violations** (52 controls byte-identical, including
    12 newest-rate-negative and 13 re-evaluated-still-red); proof the change **cannot**
    create a red (`newest<0` ⊂ `any<0`, measured 0 across the universe); one listener
    confirmed (PID 19956); HTTP verified.
  - **Fresh full scan** (checkpoint archived, `resumed_from: 0`), 606/606: green 6 → **9**,
    yellow 0 → **1**, red 418 → **415**, insufficient 82 → **81**, banks **100 → 100**.
    Changes: HELE/ST/INSW/VLO red→green, CSX red→yellow.
  - **2 further scan changes are NOT from this fix** — `DDOG` (green→red) and `GRDN`
    (insufficient→red) were already red in the pre-edit baseline; both are data drift from
    newly-landed quarters.

2026-08-06 (evening) — **Fixed a false diagnostic message; NBN recorded as a dead ticker.**
Diagnostic accuracy only — **no status and no scored value changed anywhere.** Full detail
in `bug_report.md`.
  - `quarterly_engine` reported `no filings of any kind under this CIK` and blamed a
    corporate reorg, but **PBT has 118 real 10-Q/10-K filings at SEC since 1995**. Root
    cause: `CompanyIndexReader` reads the **local secfsdstools mirror**, so empty means
    "absent from the local dataset", not "never filed". The reorg hint was a red herring
    for these filers.
  - Affects 5 tickers, all verdicts already correct: PBT (royalty trust) and BSTZ/RMT/HQH/
    HQL (closed-end funds) — all return **HTTP 404 on companyfacts**, i.e. they publish no
    XBRL financial data, and the bulk dataset is built from XBRL financial statements.
  - **Fix spans 3 files in `code33/`, placement forced by which layer knows what:**
    `quarterly_engine.py` reports only what it checked (it has a CIK, never the ticker);
    `edgar_fill.py` gains `has_xbrl_quarterly_facts()` mirroring `bank_signal_tags()` and
    sharing its cache (**no extra network call** — the adapter already populates it);
    `pipeline.py` appends the SEC-side half from `_fill_gaps`'s existing early return.
    Joined by a shared `_LOCAL_MISS_HINT` constant so matcher and message cannot drift.
  - **The `"no 10-Q/10-K filings found - "` prefix is preserved byte-identically** —
    `_classify_failure` buckets on it and is the only consumer.
  - Verified: 31 tickers (5 affected + NBN + **25 controls**, including 5 20-F filers on the
    other branch of the same `if/else`), **930-key byte comparison, zero violations**, all
    buckets identical, one listener confirmed (PID 23024), HTTP smoke passed. **No full scan
    run — deliberately**, since nothing but message text moved.
  - **NBN: dead ticker, no code changed.** Absent from SEC's `company_tickers.json`;
    already degrades gracefully to `insufficient` / `ticker/CIK resolution failed`. Drop it
    when the universe list is next curated.

2026-08-06 (later still) — **Insurance-sector revenue tag selection: investigated, NOT a
defect, no code written.** Documentation-only close-out; full reasoning and the ratio
table in `bug_report.md`. OSCR's revenue was verified **dollar-exact against SEC** (the
`Revenues` tag is the true total and includes investment income — the long-paused
LMND-style suspicion is closed), and OSCR is correctly NOT caught by the bank exclusion.
That raised a theoretical concern about the `REVENUE_TAGS` fallback picking an ancillary
tag for other insurers; a 606-ticker sweep found 23 insurers, 22 on `Revenues`, with SLDE
flagged. **Both the flag and the proposed fix were wrong** — the sweep measured concept
*presence* rather than the tag actually *resolved* per quarter (missing SPB entirely), and
a "files premium concepts" detector fires on conglomerates with incidental insurance arms
(SPB, DE, CVS, C), so building it as scoped would have regressed SPB from correctly-scored
`red` to `insufficient`. The decisive test — engine revenue vs `PremiumsEarnedNet` for the
same quarter — shows genuine insurers at ratio ~1.0-1.3 and conglomerates at 2.6-93+, with
**nothing below 1.0**, i.e. the hypothesised failure mode occurs nowhere. **All 23 insurers
resolve correctly; no fix warranted.** Process lesson recorded: concept presence is not
resolved value.

2026-08-06 (later) — **LQDA / `CODE33_SPEC.md` §5 ±999% N/A guard: investigated, NOT a
defect, no code written.** Documentation-only close-out; full reasoning in
`bug_report.md`. The guard is genuinely unimplemented, and a fix was scoped and
CRSP-reconciled (§5 governs YoY *rates*; CRSP's extreme value is a margin *level*, so the
earlier margin decision was never at risk) — then **abandoned on evidence**. Minervini's
own material treats explosive percentage growth off a small base as a sought-after signal,
not noise; his concern about extreme comparisons is about an *artificially depressed prior
quarter*, which no magnitude threshold can detect. LQDA is a real product launch and its
**GREEN is correct and intentional — unchanged**. `CODE33_SPEC.md` §5's ±999% row is now
flagged as likely not matching actual methodology and recommended for reconsideration or
removal in a future pass; **the spec document was deliberately not edited here**. One
unrelated design question was surfaced and left open (a nulled rate would let
`_c33_status` compact the `None` away and compare non-adjacent quarters — see
`bug_report.md`). Verified at close-out: `git status` empty, `utils/code33_adapter.py`,
`code33/` and `CODE33_SPEC.md` all untouched.

2026-08-06 — **Code 33's acceleration check corrected: it was testing 2 jumps, not the
spec's 3.** Engine-signal fix, `utils/code33_adapter.py` only — **`code33/` untouched**,
same as the GE fix. Full writeup in `bug_report.md`.
  - **What was wrong.** `_c33_status`'s `_last3()` took the newest 3 YoY rates and built 2
    deltas. `CODE33_SPEC.md` §2.1-2.2 requires **4 rates / 3 jumps** and names the shorter
    form as disqualifying outright. Found via DELL scoring GREEN off `10.8 → 39.5 → 87.5`
    while the transition *into* that window (`18.98 → 10.83`) was a deceleration nobody
    checked. Confirmed on IESC (margin leg) and RNG (revenue leg) too — not ticker-specific.
  - **Second defect fixed in the same edit:** green also required `d2 >= d1` (jump sizes
    must grow — a second-derivative test). Not part of Minervini's definition; confirmed
    against his source material via NotebookLM and removed. It made the filter too strict,
    the opposite direction from the window bug, so the two partly masked each other.
  - **No new data fetch.** The adapter already pulls `n_quarters + 4`, so `rev_yoy`/`npm`
    each carried **8** clean values while the check used 3. Same class of fix as GE — read
    what was already there.
  - **Two judgment calls, commented in-code:** `_MIN_RATES` stayed at 3 (raising it would
    change the failure taxonomy, not the acceleration check), and the negative-**rate** gate
    stayed revenue-only (a margin going `-6.4 → -4.5 → -2.6` is expansion; negative
    *transitions* are checked on both metrics).
  - **Verified:** baseline captured before any edit across 33 pass-list + **37 controls**;
    **byte-level whole-payload comparison, 1,960 keys, zero violations** — all 37 controls
    byte-identical, all 29 status changes on the pass-list. Offline replay against frozen
    baseline arrays reproduced the identical 29 changes, isolating the logic change from
    data drift. One listener on :8000 confirmed (PID 22308); fixed code confirmed live over
    HTTP; logs clean, no reload fired mid-scan.
  - **Fresh full 606-ticker scan** (606/606, breaker not tripped): green 8 → **6**, yellow
    25 → **0**, red 391 → **418**, insufficient **82 → 82**, banks **100 → 100**. The two
    unchanged counts are independent corroboration nothing outside the acceleration check
    moved. Survivors: **YOU, AVT, DDOG, XMTR, URGN, LQDA** — exactly what the 70-ticker
    sample predicted.
  - **YELLOW is now a dead tier** (see ENGINE STATUS). Flagged, not fixed — the tier
    vocabulary question was explicitly out of scope.
  - **Two operational findings recorded in `bug_report.md`, neither fixed:** (1) a scan
    checkpoint silently **resumes pre-fix rows across a code change**, because `job_id` is
    a hash of the ticker list with no notion of engine version — the old checkpoint had to
    be archived first, and `resumed_from: 0` is the check to confirm. (2) NOVT and IRM were
    already stale in the 2026-08-04 checkpoint before any code changed.
  - **One anomaly investigated and cleared:** SN's failure bucket changed. Proven
    code-independent by running it with the old `_c33_status` monkeypatched back in
    (identical result); actual cause is SN's revenue series now returning only 3 quarters,
    so it exits before `_c33_status` is ever called. Left open as a separate observation.

2026-08-04 — **News Scanner tab, Stage 1 of 5: core feed, headlines only.** New isolated
feature. Nothing pre-existing was modified: `code33/`, `code33_adapter.py`, `_PIPELINE_LOCK`,
`/api/news` and its FinNews/tradingview-scraper path are all untouched.
  - **New module `api/news_scanner.py`** (routes under `/api/news-scanner`, listed in BACKEND
    API ROUTES above). Sources: SEC EDGAR 8-K current-events atom feed via feedparser, and
    Finnhub free-tier general market news. Server.py's only changes are a `lifespan` handler,
    one import and one `include_router`.
  - **Architecture, per the pre-build investigation:** poller on a **daemon thread**, never an
    asyncio task — `/api/financials` calls `.result()` synchronously inside an `async def` and
    blocks the single event loop, which would stall an async poller. Own store behind its own
    lock; `TICKER_CACHE` is deliberately NOT shared (no lock, and a background writer would
    race `evict_cache()`'s iteration). SEC identity is **reused**, not redeclared —
    `code33/edgar_fill.py`'s `set_identity()` via `get_identity()`, because SEC's rate budget
    is per-identity and the Code 33 pipeline already spends it.
  - **Intervals:** EDGAR 120s, backing off to 300s automatically while `_scan_state['running']`;
    Finnhub general 60s (1.7% of the 60/min free cap); Finnhub company-news 300s/ticker,
    staggered, hard ceiling 30 calls/min. Polling is gated to **07:00-20:00 ET, weekdays** —
    wider than 09:30-16:00 because earnings and 8-Ks cluster pre-market and after the close.
    One priming fetch runs at startup regardless of the window, so the tab is never empty.
  - **Session history = calendar day in ET**, in `data/news_session.db` (WAL, gitignored),
    purged on the first request of a new day. Survives restarts, and the feed is rehydrated
    from it on boot. Rollover confirmed live: 426 stale rows purged on 2026-08-04.
  - **Frontend patched additively** via `tools/patch_frontend_news.py` (the mandated
    decode/replace/re-encode flow). Six replacements, each asserting exactly one match, and
    the patcher additionally asserts the four world-grid cell rules, the `#world` box and the
    journal redirect are still byte-present afterwards. **No existing line was modified.**
  - **Three defects found and fixed during the build, all in the new code** — full writeups in
    `bug_report.md`: the Finnhub **API key being logged in plaintext** (and served over HTTP in
    `status.last_error`), the watchlist filter running **after** the SQL `LIMIT`, and **two
    pollers** starting because `start_poller()` ran at import time under `--reload`.
  - **Operational hazard confirmed, NOT fixed:** `uvicorn --reload` logs "detected changes …
    Reloading" and then never completes — the old worker keeps serving, so an edit silently
    does not take effect, and `netstat` still shows exactly one listener so the single-listener
    check does not catch it. Observed twice. `watchfiles` is not installed. **Until this is
    fixed, kill the process tree and restart before trusting any test result.**
  - **Verified:** exactly one listener and one poller on a clean boot; live feed 198 items
    (98 real EDGAR 8-Ks with accession numbers, 100 Finnhub headlines, 95 carrying tickers);
    nav wiring proved by executing the real patched `PAGES`/`nav()`/gesture/keyboard code
    against a stub DOM — **16/16 checks**, including that the four existing directions still
    behave identically and that the news scroll-guard matches the analysis page's exactly;
    JS parses clean under `node --check`; source-failure isolation proved by pointing EDGAR at
    an unreachable host (feed held at 100 items, other source kept working, recovery to 197);
    **full API regression 4,814 keys across AAPL/UNP/MU on 6 endpoints, 0 non-live diffs.**
  - **Not verified:** the tab has not been opened in a real browser. The Chrome extension was
    not connected, and per GSTACK POLICY `/qa` is deliberately unregistered, so driving a
    browser was not attempted. The nav proof above is code-level, not visual.
  - **`requirements.txt`:** `finnhub-python` and `feedparser` re-added. Both were correctly
    removed on 2026-08-01 as unused; Stage 1 genuinely imports them. No other line touched.

2026-08-02 — **`/api/ownership` fixed, then both it and `/api/peers` cached.** Two commits,
neither of which updated this file when it shipped (rule 12); recorded retroactively as a
documentation-only change. Full detail for both lives in `bug_report.md` — deliberately not
duplicated here.
  - **`ac227c7` — `fix(api): recover from a stale yfinance crumb; drop mock ownership data`.**
    Closes the `/api/ownership` returns-empty-for-every-ticker bug logged 2026-08-01.
    Root cause: yfinance's process-wide cached auth crumb is never revalidated, so once
    Yahoo rejects it every crumb-authenticated call fails for the life of the process —
    silently, because `hide_exceptions` defaults `True` and the error is absorbed upstream
    into an empty result behind a 200. Fixed with `_yf_force_fresh_crumb()` + a retry on a
    **new** `yf.Ticker` (yfinance memoizes on the instance), wired into `/api/ownership`,
    `/api/ticker`, `/api/financials` and `/api/peers`. Two co-fixes shipped with it: `.info`
    raising instead of degrading, and a NaN insider `Value` breaking `JSONResponse`. Frontend:
    the hardcoded mock holder list is gone, replaced by an explicit "Ownership data
    unavailable" state. Verified against a deliberately poisoned crumb.
  - **`8d2af72` — `perf(api): cache /api/peers and /api/ownership`.** Both endpoints
    bypassed `TICKER_CACHE` entirely and recomputed on every search; `/api/peers` is the
    most expensive endpoint in the app (one pipeline run **per peer**, four peers, serialized
    behind the adapter's global lock). Both now use the per-prefix TTL mechanism at 600s.
    Empty payloads handled asymmetrically on purpose: ownership caches only a non-empty
    result (an empty one is indistinguishable from a transient Yahoo failure — precisely the
    `ac227c7` bug class), while peers gates on a resolved `.info`, so a sector that
    legitimately has no peers is cached but an `.info` failure is not. Repeat search
    4.28s → 0.01s; cold searches unchanged.
  - **Caching-layer only — `8d2af72` fixes nothing in the ownership bug.** Recorded because
    the two commits are adjacent and easy to conflate; the fix is `ac227c7`.

2026-08-01 (later) — **Vendoring COMPLETE — steps 5-6 done.** Continues the vendoring
recorded in commit `6107e77` (steps 1-4: copy, hash-verify, one path fix, 20-ticker
regression); see that commit and the entry below rather than duplicating them here.
  - **External dependency removed.** `pip uninstall code33-screener` — the editable
    `.pth` and dist-info are gone. Proven, not assumed: `import code33` from outside the
    repo now raises `ModuleNotFoundError`, while from the repo root it resolves to
    `quant-terminal\code33\`. Nothing was depending on the pip install itself.
    code33-screener's own source is untouched (all 9 files intact) and remains available
    as a reference and rollback path.
  - **Dependencies pinned:** `secfsdstools==2.4.3`, `edgartools==5.39.1` added to
    requirements.txt. They were previously declared only by code33-screener's
    `pyproject.toml`; after vendoring, nothing declared them at all.
  - **`CACHE_VERSION` bumped** `v31-code33-screener` → `v32-code33-vendored`. Traceability
    only — verified it changes no reported data.
  - **Rule 1 rewritten** for the new reality: the engine lives in `code33/`, changes happen
    locally, and the testing standard is now written down (20+ mixed tickers, byte-level
    whole-payload comparison, zero tolerance, single-listener check). Prior versions of the
    rule are kept inline as history.
  - **Still external:** the secfsdstools parquet dataset. `.secfsdstools.cfg` points at
    `code33-screener\data\` absolutely, so that folder is still required at runtime.
    Vendoring moved the code only.
  - Verified: UNP, MU, AES, ORA, BRK.B, SOFI re-pulled after the uninstall — 156 key
    comparisons against the last verified state, **0 differences**; logs clean; single
    listener confirmed before testing.

2026-08-01 — **Adapter now exposes what it was discarding; watchlist file deleted;
sector gate added and removed the same day.** (Session ran 2026-07-31 into 2026-08-01;
the data-accuracy investigations behind these changes are dated 2026-07-31 in
`bug_report.md`.) **Nothing in this entry is committed or pushed yet** — `main` is still
2 commits ahead of `origin/main` and `git push` is blocked: `gh auth status` reports the
active account as `monikaarya-work`, which lacks write access to Zoron09/quant-terminal.

  - **Adapter discard fix (`utils/code33_adapter.py`).** `margin_for()` read only
    `net_margin_pct` off each `MarginPoint` and dropped the rest. It is now
    `margin_point_for()`, returning the whole point, and three things it was throwing
    away reach the API:
      1. **Real net income** — `'ni'`/`'ni_end_dates'` are populated instead of hardcoded
         `[]`. (Supersedes the ENGINE STATUS note that called raw `'ni'` intentionally
         empty.) Verified nothing consumed the empty contract first: `api/server.py`
         reads only `npm_ends`, and the one `ni:` hit in `frontend/index.html` is
         hardcoded demo data, not an API read.
      2. **Per-quarter provenance** — new `'rev_sources'`/`'ni_sources'`, the un-flattened
         form of the `'sources'` summary (which is still emitted unchanged). Upstream
         vocabulary verbatim: `reported` = secfsdstools, `edgartools` = live gap fill,
         `derived_fy_minus_quarters` = Q4 back-solved from the 10-K.
      3. **Restatement flags** — new `'ni_restated'`/`'ni_restated_value'`. The pipeline
         already detected restatements and the adapter discarded the finding. AES proves
         the cost: its 2024-06-30 quarter is served as $185.0M when AES itself later
         restated it to $276.0M — a 3.1pp margin error feeding the margin-expansion leg.
         The engine still reports the as-first-filed value; this only surfaces that a
         revision exists. Which value *should* win is an open policy question.
    `ni_plausible`/`revenue_plausible` deliberately left unexposed. Purely additive — no
    field removed or renamed, no revenue or margin value changed. Regression: AES, UNP,
    MU, INTC, JBLU, IQV byte-identical on rev/npm/status/sources against a baseline
    captured from the live API before the edit.

  - **`data/sp500_tickers.json` deleted.** Four stale tickers were fixed first (ABC→COR,
    SQ→XYZ, WBA and K removed — all four confirmed against SEC's live ticker map as
    resolving to nothing; BRK.B left alone, it is a dot-vs-hyphen false positive that
    `normalize_ticker()` already handles). Then the file was removed outright: grep of
    the whole repo including both frontend bundles found **zero code consumers** — its
    only reader, `tools/watchlist_ticker_audit.py`, was deleted in the 2026-07-22 swap.
    Deletion is staged. Note the force-delete discarded the ticker fix before it was
    committed, so that edit leaves no trace in git history.
    **Stale prose:** the 2026-07-09 entry below still describes this file, plus
    `tools/watchlist_ticker_audit.py` and `tools/preflight_checks.py` — all three now
    gone. Left as-is deliberately: it is a dated historical record, accurate when
    written. Only its "watchlist cleanup not yet done — pending go-ahead" status line is
    superseded, by this entry.

  - **Sector exclusion: gate added, then removed same day — final state is
    informational-only.** The reported symptom was EIX (Utilities) scoring GREEN on the
    last full scan. Root cause was not the documented "gating gap": the swap deleted the
    sector logic entirely, leaving `sector_excluded` a hardcoded `False` literal with
    nothing computing it (code33-screener has no sector concept — its bank check is
    explicitly "deliberately NOT sector labels"). The `EXCL_SECTORS`/
    `EXCL_INDUSTRY_KEYWORDS`/`REIT_KEYWORDS` lists were recovered verbatim from
    `dc77f59^` and a hard gate wired in, returning `status='excluded_sector'` before the
    pipeline ran.
    **Reversed the same day on review of Minervini's actual methodology:** these are
    defensive/late-cycle sectors that Code 33's own growth and margin criteria are meant
    to filter out on the numbers. A pre-scoring gate pre-empts that judgement and hides
    the evidence for it. The gate is gone; `_sector_flags()` and both lists stay, and
    `sector_excluded`/`excluded_sector_name`/`is_reit` are returned as metadata on every
    path including the no-data exits. EIX and AES now score normally and still report
    `sector: Utilities`.
    **The bank exclusion was deliberately NOT touched** — banks are refused for a proven
    data-correctness fault (revenue silently wrong under standard tags, confirmed on
    FULT), which is a different category from a sector-fit judgement.
    **Cost, flagged not fixed:** `_sector_flags()` makes a yfinance `.info` call per
    ticker inside the globally-serialized pipeline. With the gate it paid for itself by
    skipping the pull; now every ticker pays it for metadata only.
    **Worth revisiting:** the keyword list matches substrings against a yfinance
    free-text field — `'chemical'` catches both "Specialty Chemicals" and "Agricultural
    Chemicals", and a vendor relabelling silently changes behaviour.
    **Removed entirely hours later, same session.** With no gating behaviour left, the flags
    were one extra yfinance `.info` call per ticker — multiplied across a 500+ ticker scan —
    for a label nothing consumed. `_sector_flags()`, both keyword lists, `REIT_KEYWORDS` and
    the yfinance import are gone; `sector_excluded`/`excluded_sector_name`/`is_reit` are back
    to their original hardcoded `False`/`''`/`False` on every return path. Net effect of the
    day's sector work on the adapter: zero, minus a comment explaining why there is no gate.

  - **Verification lesson — confirm ONE listener on port 8000 before trusting any
    result.** A post-fix pull showed the sector gate doing nothing; it was working. Three
    processes were listening on 8000 simultaneously (two stale servers plus orphaned
    `multiprocessing` children holding inherited socket handles), and requests were
    landing on pre-fix code. `Stop-Process` on the reloader PID is not sufficient — check
    `netstat -ano | Select-String ":8000.*LISTENING"` returns exactly one row, and kill
    orphaned `python.exe` children whose command line contains `multiprocessing`. This is
    the same trap recorded in `bug_report.md` under commit `64a5757`.

  - **`bug_report.md` — new 2026-07-31 sections** from two 10-ticker data-accuracy passes
    (20 tickers, all verified against `data.sec.gov` directly). **Every defect this list
    originally carried is now fixed or reclassified — see the notes below and the CLOSED
    entries in `bug_report.md`. Nothing from this pass remains open.** Cleared
    after investigation: ORA, LMND, ESRT, ICE, NUE, COR — all matched SEC exactly;
    the LMND/ICE/ESRT/AES gaps against TradingView are vendor definitional differences,
    now documented per ticker.
    **Reclassified 2026-08-01 — the missing ±1000% margin plausibility guard is NOT a
    defect and has been removed from the confirmed list above.** Half of the original
    claim still holds: commit `990bcba`'s TRT tripwire was never ported into the adapter,
    so no plausibility guard exists and values past ±1000% do reach output. That absence
    is not itself a fault. The other half does not hold: CRSP's -24450%, cited as proof
    values were escaping, is **real filed data** — verified dollar-exact against SEC on
    all 8 quarters. The `bug_report.md` entry is now CLOSED and carries the full evidence
    plus why a bare magnitude threshold cannot be the fix if the guard is ever revisited.
    **Fixed 2026-08-01 — both fiscal-label bugs, and removed from the confirmed list
    above:** blank labels on edgartools-filled quarters, and calendar-Q4 rendering as
    `FY FY24`. Fixed as ONE change on purpose — repairing the blank label alone would have
    widened the FY-doubling bug, since a fill sourced from a 10-K row carries `fp='FY'`.
    `edgar_fill.py`'s `fetch_discrete_quarter()` now returns fy/fp (they were always on the
    row it had already selected — a dropped field at a return boundary, not the upstream
    gap the original note guessed), `pipeline.py` wires them through, and `_fq_label()`
    maps `FY`→`Q4`. Verified: 14 blank + 25 doubled labels before, 0 and 0 after; 101
    labels checked against real SEC fiscal calendars, all correct; 364-key byte-level
    payload comparison across 14 tickers with zero unintended changes; confirmed over HTTP.
    Full evidence in `bug_report.md`. Note `rev_labels`/`npm_labels` have no frontend
    consumers, so this is payload correctness with no visible UI change yet.
    **Fixed 2026-08-01 — the pre-revenue bucketing gap, also removed from the confirmed
    list above.** Reported as SLXN-only; it was **16 tickers**. A company filing NO revenue
    concept gets `value=None`, which the `<5 quarters` guard's own filter strips, so it
    returned early and never reached `_diagnose_insufficient()` — while `$0.00` filers keep
    `value=0.0`, survive, and bucket correctly. Same condition, two XBRL tagging choices.
    Fixed in `utils/code33_adapter.py` only (three shared helpers so the guard and the
    diagnosis can't drift, plus one conditional on the UNFILTERED series); `api/server.py`
    needed no change — the new message self-routes to the pre-revenue bucket. Verified: all
    16 flipped bucket, 702-key before/after comparison with 0 violations, 10 control tickers
    byte-identical, confirmed over HTTP. Full evidence in `bug_report.md`.

  - **Ticker normalization completed across every yfinance call site (2026-08-01).** The
    BRK.B fix had covered `/api/ticker` only; the remaining 6 call sites in `api/server.py`
    (`/api/chart`, `/api/financials`, `/api/news`, `/api/ownership`, `/api/peers` ×2) now all
    route through `normalize_ticker()`. A grep for an un-normalized `yf.Ticker(` returns
    nothing. **The failure modes were NOT uniform** — chart 404'd, financials returned an
    empty balance sheet/cash flow behind a 200, peers returned an empty list, news was never
    actually broken (tradingview is primary, the yfinance path is an unexercised fallback).
    Each was confirmed against BRK.B on the un-fixed code before editing. AAPL is
    byte-identical through all 5 endpoints before/after, with the server restarted between
    captures so `TICKER_CACHE` could not mask a difference. Detail in `bug_report.md`.
    **New bug found while doing this — since CLOSED (FIXED 2026-08-02, commit `ac227c7`).**
    `/api/ownership` returned empty for **every** ticker, not just dot-tickers. Root cause
    was yfinance's process-wide cached auth crumb going stale and never revalidating, with
    the resulting error swallowed upstream by `hide_exceptions` — which is why the handler's
    own logic worked in a fresh process. Fixed with a forced crumb refresh plus retry, and
    two co-fixes. Full writeup in `bug_report.md`; re-confirmed live 2026-08-02.

  - **`requirements.txt` corrected (2026-08-01).** It was **broken for clean installs** —
    `pypfopt>=1.5.5` names an import, not a PyPI distribution, and pip aborted the whole
    file on it (`No matching distribution found`). Proven by installing into a throwaway
    venv, not by inspection. Now: `fastapi==0.138.0` and `uvicorn==0.49.0` **added** (the
    two hard runtime deps were previously undeclared and only present transitively);
    `pypfopt` **renamed** to `PyPortfolioOpt>=1.5.5` (same package, correct distribution
    name, version floor unchanged); `finnhub-python`, `streamlit`, `feedparser` **removed**
    after re-verifying zero imports anywhere outside `.venv`. `alpaca-py` and
    `PyPortfolioOpt` **kept deliberately despite zero code usage** — `.env` carries
    `ALPACA_API_KEY`/`ALPACA_API_SECRET`, so that integration is wired-but-unimplemented
    rather than dead, and removing a trading dependency on grep evidence alone is the wrong
    risk trade. Verified: clean install into a throwaway venv succeeds and every declared
    package imports. Note `.env` still carries a vestigial `FINNHUB_API_KEY` that no code
    reads.

  - **Two stale labels corrected 2026-08-01 (no code change) — both were fixed by `b7d6b6a`,
    which predates this session and is already on origin/main; the docs just never caught up.**
    (1) **The restatement discard is NOT open.** The adapter stopped throwing
    `ni_restated`/`ni_restated_value` away; verified live on AES, which now reports
    `ni_restated=[True,True,...]` with `ni_restated_value=[276000000, 504000000, ...]` on the
    two recast quarters. What remains is the *policy* question of whether to serve the
    as-filed or the restated figure — the owner's call, explicitly not treated as a defect by
    the entry itself. (2) **The duplicate revenue build is NOT open** — the adapter reuses
    `rev_series`; confirmed by counting `(quarter, tag)` fill pairs on MU and IQV, zero
    duplicates. Both `bug_report.md` entries are now marked accordingly.

  - **YoY now uses the filer's recast basis when a quarter was restated (2026-08-02).**
    GE reported **-43.26% YoY** for 2024-09-30 purely because its year-ago base still
    contained GE Vernova, divested 2024-04-02. Every VALUE was correct; only the
    comparison was meaningless. **No boundary detection was needed** — GE recast its own
    history and `_attach_restatement_flags` already flagged it on the revenue leg,
    marking exactly the five pre-spinoff quarters. Both signals considered in planning
    were rejected: discontinued-ops concepts appear on nearly every GE quarter since
    2017, and a revenue step-change heuristic repeats the ±1000%-margin-guard mistake.
    Fix is `utils/code33_adapter.py` only (**`code33/` untouched**): a `_yoy_value()`
    helper applied to BOTH ends of every comparison, mirrored into `_yoy_miss_cause()`
    so the diagnosis cannot disagree with the emitted number, plus `rev_restated` /
    `rev_restated_value` exposed. Those two arrays deliberately cover all 12 pulled
    quarters, not the 8 displayed — a restatement on a base-only quarter still moves
    `rev_yoy`, found on PFE. Displayed `rev` stays as-filed. Scope: 23 of 543 tickers
    restate ≥10%; GE is 6th, and JNJ and NVRI are affected. Verified: 57 restated
    quarters EXACT vs SEC; universe audit of 430 scored tickers → 36 YoY changed,
    **1 status changed (PAG yellow→red, accepted)**, zero tickers without a restatement
    changed at all. Full evidence in `bug_report.md`.

  - **Ticker→CIK resolution after a holdco reorganization (2026-08-01).** `XOM` returned no
    data. **Not an engine defect** — ExxonMobil completed a holding-company reorganization in
    July 2026 and SEC's `company_tickers.json` now maps XOM to the new parent, CIK 2115436,
    which has 27 filings and **zero** 10-K/10-Q. The operating history is on CIK 34088. The
    lookup code, its source and its cache were all verified correct; the mapping changed
    underneath it. Same shape as NVRI (Enviri, history on Harsco CIK 45876).
    **Blast radius 2 of 541, not the 39 initially flagged** — a universe scan found 39
    zero-filing tickers, but testing the form signature (`8-K12B`/`10-12B` vs `20-F`/`6-K`)
    showed ~33 are foreign private issuers and 3 funds/local gaps, all correctly out of scope.
    Fix: an explicit `PREDECESSOR_CIK` map in `code33/ticker_lookup.py` (deliberately a map,
    not a heuristic, so the 36 out-of-scope tickers cannot be caught by it), plus a
    `quarterly_engine.py` change that distinguishes "no filings of any kind" from "files
    20-F/6-K but no 10-Q" — **restoring the signal `check_cik_discontinuity` gave before
    `dc77f59` deleted it**. **The map is a BRIDGE, not permanent:** re-check when ExxonMobil
    Holdings files its first 10-Q, expected ~November 2026, since the correct series may then
    span both CIKs. Verified: XOM and NVRI both 0 → 8 quarters, newest quarter dollar-exact
    vs SEC; 36 zero-filing controls gained no data and kept their CIK; AAPL/DELL/WMT
    byte-identical. Full evidence in `bug_report.md`.

  - **Filing-lag blind window closed (2026-08-01) — reported as an ICE bug, was ~99% of the
    universe.** `FILING_LAG_DAYS = 45` gated `expected_quarter_ends()`'s forward-projection
    loop. 45 is the SEC 10-Q statutory *deadline* (the LATEST a quarter may legally appear),
    which is the wrong number for deciding when to START looking: measured across **17,635
    10-Q filings**, 96.6% are filed before day 45 (median 36d, fastest 9d), and **494 of 499
    companies** had their newest 10-Q filed inside the old gate. Every one of them carried a
    blind window each quarter — ICE 15 days, DAL 36. Renamed to `SEC_10Q_DEADLINE_DAYS`
    (reference only, gates nothing) and added `PROJECTION_MIN_AGE_DAYS = 10` as the real
    gate. **A second bug was found and fixed with it:** projections were evicting the OLDEST
    known end from the fill window, which silently stopped back-filling older gaps that serve
    as YoY bases; the return is now additive. Safe because the cutoff gates only projections
    and a projection that finds nothing adds no point — and because **nothing in the codebase
    ever marks a quarter overdue**, so there was no late-filer protection to weaken. Verified:
    7 tickers gained their true newest quarter, all dollar-exact vs SEC; 11 unchanged
    including every late filer that reaches the pipeline; 0 violations; cost +1.3s across 18
    tickers. Full evidence in `bug_report.md`.

2026-07-31 — **Unlabelled-failure reporting gap closed (branch
`insufficient-reason-labels`, NOT merged — held for review)**. `_c33_status` can return
'insufficient' from the adapter's SUCCESS path (both series pulled fine, but a leg had
fewer than the 3 clean values the 3-quarter window needs); that path hardcoded
`excluded_reason=''`, so 11 of 540 tickers on the last full scan collapsed into one
anonymous `insufficient (unspecified)` bucket that told the operator nothing and gave
the circuit breaker no cause to group on.
  - Traced all 11 to real root causes before writing any fix (live pipeline + live
    EDGAR, not inference). Two genuine clusters: **5 pre-revenue companies** (RVMD,
    XENE, SYRE, DNLI, PLSE — 9-11 of 12 quarters report $0 or no revenue line;
    confirmed against live EDGAR that RVMD/DNLI/SYRE file a revenue concept valued
    exactly 0.00 for 2025+, so this is a company property, not a data gap) and
    **6 short-history companies** (SDRL, VG, INDV, ALMS, BIOA, SEPN — 5-6 quarters,
    fewer than the 7 needed to form 3 YoY pairs).
  - New bucket: `no reported revenue (pre-revenue company)`. Zero revenue breaks BOTH
    legs simultaneously — net margin is undefined against a zero denominator
    (`net_margin.py` guards `revenue != 0`) and YoY is undefined against a zero base —
    so none of the existing categories described it. The other 6 map onto the existing
    `insufficient revenue history`.
  - **Finding worth acting on separately:** within the short-history six, SDRL and INDV
    are NOT young companies. Both are former foreign private issuers that converted to
    domestic filing in 2025 (SDRL: 6× 20-F 2019-2024, first 10-Q 2025-02-27; INDV: 20-F
    2024-03-06, first 10-Q 2025-03-03). Their pre-conversion history is annual-only
    20-F, which this pipeline correctly excludes. Mechanically identical outcome, very
    different meaning. Not separately bucketed — distinguishing it needs a per-ticker
    filing-history lookup, a real cost across a 540-ticker scan. Flagged, not actioned.
  - Verified: all 11 now carry a specific reason and a named bucket, zero left
    unspecified; 14 spot-check tickers (3 green, 2 yellow, 5 red incl. AAPL/CHEF/TGT
    from the regression baseline, 2 excluded_bank) byte-identical to the pre-fix scan on
    status, rev_yoy and margin. Metadata only — the diff's sole deletion is the
    hardcoded `''`; frontend has zero references to `excluded_reason`.

2026-07-22 — **Code 33 engine swap (branch `code33-swap`, NOT merged to main)**: old
in-repo engine fully removed (`utils/code33_engine.py` + secfs_revenue/secfs_net_margin/
edgar_revenue/edgar_net_margin/sec_edgar, plus their orphaned consumers
tools/preflight_checks.py, tools/watchlist_ticker_audit.py, tools/engine_accuracy_check.py,
tools/run_c33_batch.py, tests/test_preflight_checks.py) and replaced by the externally
validated code33-screener pipeline via `utils/code33_adapter.py` (global pipeline lock,
verbatim `_c33_status` port, ascending-array contract preserved). `/api/scan` rebuilt as a
background checkpointed resumable job with `GET /api/scan/status` polling; frontend
patched (tools/patch_frontend_scan.py — runScan polling loop, scan progress line,
excluded-banks pill, EXCLUDED — BANK badge) within the bundled-SPA patch rules; world
grid/nav untouched. Wealthsimple/journal/analytics/portfolio paths confirmed untouched
by grep before AND after deletion. Partial validation passed (bank exclusion end-to-end +
regression-baseline spot checks); full 300-500-ticker scan deliberately NOT yet run —
awaiting final ticker list. See ENGINE STATUS above for the new architecture.

2026-07-13 — **4-commit sequence complete**: TRT's `-230,303%` margin corruption led to a
full chain — `8f620c4` fixed the root-cause `_to_m()` unit-conversion bug (4 duplicate
copies across secfs_*/edgar_* modules), `64a5757` routed `/api/financials/{ticker}` through
`code33_engine.py`'s own date-aware gap detection instead of calling secfsdstools/edgartools
directly, `9753f34` added a yfinance third-leg revenue fallback (fill-only, revenue-only,
provenance-tagged) for gaps neither SEC-sourced tool can fill, and `990bcba` adds a
`±1000%` plausibility guard on margin values as a last line of defense against the same bug
class recurring silently. Full detail, including honest verification notes (BLK/MU/CMP
weren't actually exercised by the yfinance leg on verification day, for three separate
reasons; CPTP unexpectedly was), in `bug_report.md`.

2026-07-11 — Corrected a stale IN PROGRESS note. The "newest quarter invisible" bug in
`edgar_revenue.py`/`edgar_net_margin.py` (originally confirmed 2026-07-07) was actually fixed
two days later in commit `9c421c5` (2026-07-09) — CLAUDE.md was never updated to reflect that,
so it sat listed as "pending explicit go-ahead, not yet implemented" for two days after
shipping. Re-verified live again today during NVDA reproduction testing: newest quarter
2026-04-26 confirmed present in `get_code33_data("NVDA")`'s output. RESOLVED, not open — see
`bug_report.md` for the full writeup. (Separately, a *different*, still-open bug in
`secfs_revenue.py`/`secfs_net_margin.py` was found today and now occupies the IN PROGRESS slot
below — confirmed via commit diff and live testing to be an unrelated mechanism, not a
resurfacing of the 07-07 bug.)

2026-07-10 — Full cleanup pass (stale artifacts + dead caching decorator), user-confirmed
before deletion. Pre-checks first: grepped all live code for imports reaching into archive/
(none found), grepped for "streamlit" case-insensitive (found it wasn't just code33_engine.py
— utils/sec_edgar.py also imports it, with 4 more `@st.cache_data` decorators; requirements.txt
still declares streamlit>=1.28.0, correctly left alone), checked tests/ for cache-behavior
tests (none exist, so removal couldn't break a real assertion).
  - Deleted (git rm, tracked files): `quick_scan.py`, `run_batch.py` (root scratch scripts),
    `Minervini builder Managed copy_2026-06-23.csv`, `Minervini_builder_Managed_2026-04-28.csv`
    (superseded ticker-list inputs), `Code33_Results_2026-06-23.csv`,
    `Code33_Results_2026-05-25.csv` (stale scan outputs sitting in repo root, risked being
    mistaken for current data), `archive/tools/*.py` (6 old audit scripts, superseded by
    `tools/engine_accuracy_check.py`/`preflight_checks.py`/`watchlist_ticker_audit.py`),
    `archive/utils/screener_db.py` (unused SQLite cache module, no db file existed on disk).
    `archive/` is now gone entirely (both subdirs were emptied).
  - Deleted all `__pycache__/`/`*.pyc` repo-wide (already gitignored, untracked) — included two
    orphaned bytecode files whose source `.py` no longer exists (`edgar_net_income.pyc`,
    `test_code33_regression.pyc` x2), leftover from earlier code removals.
  - Removed dead `import streamlit as st` + `@st.cache_data` from `code33_engine.py`
    (`get_code33_data`'s 24h result cache) — the app is FastAPI-only now, no Streamlit runtime
    ever exists, so this was silently caching in-memory per server process with no way to bust
    it short of a restart. Real risk confirmed: `CACHE_VERSION` (still 'v30') was NOT bumped
    across the last 4 NI/revenue logic fix commits (5f680ae, 9c421c5, 186d24d, 8d455cf) — none
    of them touch `code33_engine.py` — so a long-running server could've served pre-fix cached
    numbers for up to 24h post-deploy. Pure removal here, no replacement, per plan.
  - Expanded scope (user-approved) to `utils/sec_edgar.py`'s matching 4 decorators. Removing
    `_get_ticker_mapping()`'s decorator outright caused a **real regression**, caught by
    verification, not shipped: that function is zero-arg and fetches SEC's full multi-MB
    ticker→CIK map; `get_cik()` (called on every single ticker by
    `secfs_net_margin.py`/`secfs_revenue.py`/`preflight_checks.py`/`watchlist_ticker_audit.py`)
    calls it every time. With the decorator, one process-lifetime fetch was reused for every
    ticker in a batch; without it, a 16-ticker verification run refetched that file 16x back to
    back, and mid-run degraded into rate-limit/timeout failures that cascaded into 11 of 16
    tickers (LIN, JNJ, CB, AME, BLK, NVDA, AMD, MSFT, AIP, CELH, +partial CMP) coming back fully
    `insufficient`. Fixed by replacing that one decorator with `functools.lru_cache(maxsize=1)`
    (explicit stdlib, no streamlit dependency, same one-fetch-per-process effect — this
    function has no meaningful staleness risk, SEC's ticker map doesn't change within a
    process's lifetime, so a replacement was correct here unlike code33_engine.py's case). The
    other 3 decorators (`get_recent_filings`, `get_insider_filings`, `get_key_filings`) had zero
    callers anywhere in the live codebase — removed clean, no behavior change possible.
  - Re-verified after the lru_cache fix: all 10 previously-collapsed tickers back to matching
    baseline exactly (LIN, BLK, NVDA, AMD, MSFT, AIP, CELH byte-identical). Residual diffs on
    GOOGL/MU/CMP/PED/CPTP/TEAM/JNJ/CB/AME are the pre-existing newest-quarter edgartools bug
    above, not new — confirmed same shape (one quarter at the edge, filled/missing toggling)
    across two runs 45min apart, unrelated to any file this cleanup touched.
  - Server boot-tested: `run.py` starts clean, no import errors; `GET /api/ticker/MU` over real
    HTTP returned 200 with full data; server stopped cleanly after.
  - `tests/test_preflight_checks.py`: 6 passed, 1 xfailed (TRT, pre-existing) — unchanged from
    documented baseline.
  - `requirements.txt` untouched (out of scope for this cleanup) — worth noting though: after
    both files' edits, `streamlit` is no longer imported anywhere in the live codebase at all
    (checked: zero hits repo-wide outside `.venv`), so the `streamlit>=1.28.0` line is now a
    genuinely unused dependency, not just an unused import. Flagging, not removing — a
    dependency-list change is a separate decision from this cleanup.

2026-07-09 — Fixed net-margin numerator: engine was using plain "Net Income" (NetIncomeLoss)
instead of "Net Income Attributable to Common Stockholders" (post-preferred-dividend) for
companies with preferred stock. Confirmed via CELH's real Q3 2024 10-Q filing (SEC EDGAR,
not through edgartools/secfsdstools abstraction): NetIncomeLoss = $6,356,000 vs actual
attributable-to-common = $(557,000) after $6,913,000 in Series A preferred dividends —
Macrotrends independently reports the common-stockholders figure, and Minervini's own EPS
convention always uses it, so margin and EPS now share the same numerator convention.
  - utils/secfs_revenue.py: reordered `_NI_TAGS` — `NetIncomeLossAvailableToCommonStockholdersBasic`
    moved from last to first priority.
  - utils/edgar_net_margin.py (protected file — this counts as the confirmed-bug sign-off
    under rule 1): swapped Tier 1/Tier 2 in `_ni_row()`, same reorder.
  - Verified safe as a pure reorder: companies with no preferred stock (checked directly
    against the local secfsdstools parquet DB, not assumed) never file this tag at all —
    confirmed absent across 8 quarters each for GOOGL, MU, CMP, PED, CPTP, TEAM, LIN, JNJ,
    CB, AME, BLK, NVDA, AMD, MSFT, AIP — so lookup falls through to NetIncomeLoss unchanged
    for them. Regression-tested: all 15 byte-identical before/after.
  - CELH validated: all 8 quarters' margins shifted as expected; Q3 2024 net income now
    exact-matches the filing ($-557,000), margin flipped +2.41% → -0.23% (negative, correct
    direction vs Macrotrends).
  - TRT investigated as a possible edge case (initially looked like duplicate/ambiguous
    NetIncomeLossAvailableToCommonStockholdersBasic rows for the same period) but cleared —
    the duplication was a bug in a throwaway diagnostic script that omitted an XBRL `ddate`
    filter (conflated the current quarter with the filing's own prior-year comparative
    column); production code (`_own_period_value`) already pins on `ddate` correctly and was
    never affected. Real finding: TRT's tag nets out non-controlling interest, not preferred
    dividends (TRT has no preferred stock) — same tag, different economic adjustment. TRT
    was deliberately excluded from this fix's regression set and has not been explicitly
    re-verified under the new tag order (see IN PROGRESS above).

2026-07-09 — Added 4 new preflight detectors to tools/preflight_checks.py, closing gaps
found across 3 rounds of independent quarter-identification verification against raw SEC
EDGAR data (data.sec.gov, direct HTTP, no secfsdstools/edgartools). _target_quarter_ends's
date math itself was confirmed correct throughout (52-ticker systematic sample from
data/sp500_tickers.json: 96% clean match, zero date-math bugs) — all 4 fixes are
identity-resolution problems upstream of it:
  - check_foreign_annual_only: 20-F/40-F annual-only filers (BIDU, BABA) — no 10-Q ever
    exists, Code33's quarterly methodology structurally doesn't apply.
  - check_cik_discontinuity: tracked-universe tickers whose *current* CIK has <3 years of
    real SEC history — catches BlackRock/BLK-type holdco reorgs (confirmed: BLK's current
    CIK 2012383 only goes back to Feb 2024; the real 2006-2024 history sits under CIK
    1364742, renamed by SEC itself to "BlackRock Finance, Inc." 2024-09-26). Flags for
    manual review only — does not attempt to recover pre-reorg history.
  - check_ticker_resolution: ticker doesn't resolve via SEC's current company_tickers.json
    at all (renamed or taken private) — reported as a distinct watchlist-maintenance
    category, not a generic data failure.
  - check_deregistered: Form 15 in history AND no *operating* filings (10-Q/10-K/8-K/
    20-F/40-F — excludes third-party SC 13G/13D ownership disclosures, which keep
    appearing under a dead CIK indefinitely) for 200+ days afterward. A bare Form 15 alone
    is NOT sufficient signal — 5 tickers (AME, CB, JNJ, LIN, TEAM) have one in their
    history but still file normally; only CPTP (Form 15 filed 2025-02-11, zero operating
    filings since) genuinely qualifies.

New standalone tool: tools/watchlist_ticker_audit.py — cross-checks data/sp500_tickers.json
against SEC's current ticker map. Run once: found 5 stale tickers in the 208-ticker
watchlist — ABC (renamed COR/Cencora), WBA (taken private), K (Kellanova, acquired by
Mars), SQ (renamed XYZ/Block), and BRK.B (a false positive — SEC lists it as "BRK-B" with
a hyphen; utils/sec_edgar.py's get_cik() ticker normalization doesn't handle the dot/hyphen
convention difference, not a real corporate event). Watchlist cleanup (removing/renaming
the 4 genuine stale tickers) not yet done — flagged, not actioned, pending go-ahead.
All 7 preflight detectors verified with real tickers; existing test_preflight_checks.py
suite still passes unchanged (6 passed, 1 xfailed — TRT, pre-existing).

Prior (2026-07-07): Removed Finnhub/FMP/raw-XBRL-tier/yfinance-fallback from
code33_engine.py; redesigned revenue+margin fetch to quarters-first targeted gap-fill;
fixed real-filed-date and fiscal quarter-label mismatches (CMP, NVDA); deleted 5
confirmed-dead files from the Finnhub/FMP era. Confirmed but not yet fixed:
edgar_revenue.py/edgar_net_margin.py structural bug hiding each ticker's newest quarter
until its fiscal year closes — [fixed 2026-07-09, commit 9c421c5; see 2026-07-11 entry above].
