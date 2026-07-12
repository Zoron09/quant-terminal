# Bug Report — Quant Terminal Engine

Authoritative bug-status reference for the current engine version. Scope: bugs found
during the manual ticker-testing initiative, 2026-07-09 to 2026-07-12, tied to the
current engine only. Older/historical bugs (ESOA, EDRY, PED, KEWL, WSR, sector-exclusion
gaps, etc.) are out of scope here — tracked elsewhere. The financial-sector/bank
net-margin bug (JPM-type) is known, deliberately deferred, and also out of scope.

---

## Resolved

### CELH net income bug — wrong NI tag for preferred-stock companies
- **Commit:** `5f680ae` (2026-07-09)
- **What it was:** Net margin (and EPS convention) used plain `NetIncomeLoss` instead of
  `NetIncomeLossAvailableToCommonStockholdersBasic` for companies with preferred stock —
  wrong numerator whenever preferred dividends materially change the common-stockholders
  figure.
- **Root cause:** `_NI_TAGS` priority order in `secfs_revenue.py` and the Tier 1/Tier 2
  order in `edgar_net_margin.py::_ni_row()` put `NetIncomeLossAvailableToCommonStockholdersBasic`
  *last* instead of *first*, so plain `NetIncomeLoss` matched first and the preferred-dividend
  deduction was silently skipped.
- **How found:** Direct SEC EDGAR check (not through the secfsdstools/edgartools abstraction)
  on CELH's real Q3 2024 10-Q: `NetIncomeLoss` = $6,356,000 (positive) vs actual
  attributable-to-common = $(557,000) (negative) after $6,913,000 in Series A preferred
  dividends. Macrotrends independently reports the common-stockholders figure — confirmed
  the engine's number didn't match a real external source.
- **How fixed:** Reordered `_NI_TAGS` in `secfs_revenue.py`; swapped Tier 1/Tier 2 in
  `edgar_net_margin.py::_ni_row()`. Pure tag-priority reorder, no other logic touched.
- **Verification:** Checked all other tracked tickers (GOOGL, MU, CMP, PED, CPTP, TEAM, LIN,
  JNJ, CB, AME, BLK, NVDA, AMD, MSFT, AIP) directly against the local secfsdstools parquet DB
  — confirmed none of them ever file the `...CommonStockholdersBasic` tag at all, so the
  reorder is a no-op for them (byte-identical output before/after, 15/15). CELH itself:
  net income now exact-matches the filing ($-557,000); margin flipped +2.41% → -0.23%, correct
  sign vs Macrotrends.

### _to_m() unit-conversion bug — sub-$1M values corrupted or silently zeroed
- **Commit:** `8f620c4` (2026-07-12)
- **What it was:** Two separate defects in the same helper function, existing as four
  independent copies across `edgar_revenue.py`, `edgar_net_margin.py`, `secfs_revenue.py`,
  `secfs_net_margin.py`:
  1. `edgar_revenue.py`/`edgar_net_margin.py`'s `_to_m()` skipped the division for any raw
     value under $1,000,000 (`return val if abs(val) < 1_000_000 else val/1_000_000`),
     assuming "small raw value means it's already in millions." Wrong: XBRL values are
     always raw USD regardless of company size. A real -$38,000 net income was left as
     `-38000.0` and then treated downstream as *-38000.0 million dollars* — a
     unit-magnitude error of exactly 10^6.
  2. `secfs_revenue.py`/`secfs_net_margin.py`'s `_to_m()` already divided unconditionally
     (this exact skip bug was fixed here once before — see the ASYS case below) but rounded
     to 1 decimal place, which has the same erasure effect for sub-$1M values: -$38,000 in
     millions is -0.038, and `round(-0.038, 1)` is `-0.0` — silently losing sign and
     magnitude, displaying as a healthy 0% margin instead of a real small loss.
- **Root cause / how found:** Confirmed live on TRT: `get_code33_data('TRT')` produced
  `npm = -230303.03` for its newest quarter (2026-03-31) — implying a ~$38 billion net loss
  on $16.5M revenue. Pulled TRT's actual 10-Q directly from SEC EDGAR (accession
  `0001437749-26-016914`, filed 2026-05-14): real reported net income is **-$38,000**.
  `-38000 / 1_000_000 × 100 / 16.5 = -230303.03` — exact match, confirming defect #1 above
  as the live mechanism. Checked the sibling `secfs_*` modules for the same class of problem
  even though they don't have the skip bug — found defect #2 (1-decimal rounding) live with
  the identical TRT numbers, confirming both needed the same fix.
  This is the same bug class documented once before and only half-fixed: `secfs_revenue.py`'s
  own `_to_m()` docstring already recorded the ASYS case (real NI $312,000 left unconverted,
  producing a >500,000% margin) and was fixed in the `secfs_*` pair — but that fix never got
  ported to the `edgar_*` pair, which is why the same bug class recurred, now confirmed on TRT.
- **How fixed:** All four `_to_m()` implementations now divide unconditionally and round to
  4 decimal places (not 1) — sub-$1M values keep correct sign and magnitude down to roughly
  $100 raw. Downstream margin-percentage rounding (2dp) was checked and is fine now that its
  input is correct.
- **Verification:** TRT's newest quarter now shows `npm = -0.23` — exact match to the real
  filed number (-$38,000 / $16.5M × 100 = -0.230303...%), correct sign and magnitude, not
  -230,303% and not 0.0%. Spot-checked AIP, CELH, TEAM, PED, CMP (other small-caps flagged as
  exposed to this bug class) — no absurd (>1000%) or suspiciously-exact-zero margins on any
  quarter. Regression: NVDA, MSFT, GOOGL byte-identical to their pre-fix baseline (their NI is
  always well over $1M, so they never hit the broken branch either way).
- **Call-site audit:** confirmed every call site of `_to_m()` in both `edgar_revenue.py` and
  `edgar_net_margin.py` feeds only dollar-denominated Revenue/Net-Income rows — nothing
  per-share or already-ratio-valued flows through it, so the unconditional-divide fix is safe
  everywhere it's used.
- **Follow-up / tech debt (not done in this commit):** four independent copies of `_to_m()`
  exist across these two module pairs. This exact bug class recurred specifically *because* a
  fix landed in one pair (`secfs_*`, for the ASYS case) and never propagated to the other
  (`edgar_*`). Recommend consolidating into a single shared utility function so a future fix
  can't diverge again the same way.

### /api/financials/{ticker} endpoint — newest-quarter margin null, wrong dates
- **Commit:** `<fill in after commit>` (2026-07-12)
- **What it was:** `/api/financials/{ticker}` called `secfs_revenue.py`/`secfs_net_margin.py`
  directly instead of going through `code33_engine.py`'s date-aware gap detection. Confirmed
  live on 16 of 20 tracked tickers: newest-quarter `net_margin` was `null` (no fallback for
  margin at all), and revenue — where present — came only from a yfinance fallback that uses
  yfinance's own calendar-normalized quarter-end date, not the real SEC-filed date (e.g. NVDA
  showed `2026-04-30` instead of the real `2026-04-26`; FN showed `2026-03-31` instead of the
  real `2026-03-27`).
- **Root cause:** this endpoint was a second, independent caller of
  `secfs_revenue.py`/`secfs_net_margin.py` with no compensating layer — unlike
  `code33_engine.py`'s callers, which are protected by its own `_target_quarter_ends`/
  `_fill_target_quarters` date-aware gap-fill. See the "Count-gate double-merge redundancy"
  entry above for the underlying mechanism this endpoint had no protection against.
- **How fixed:** routed the endpoint through `get_code33_data(t, n_quarters=12)` instead —
  added an optional `n_quarters` parameter to `get_code33_data()`/`_get_code33_data_inner()`
  (default 8, so every existing caller is unaffected) so this endpoint can request its own
  12-quarter buffer (8 display quarters + 4 for its own index-based YoY calc) through the
  same date-aware path everything else already trusts. Added a `_closest_date()` proximity
  matcher (10-day tolerance) so `get_code33_data`'s real filed dates correctly merge with
  yfinance's own EPS-only date series instead of splitting the same quarter into two
  incomplete rows. Dropped the old yfinance-revenue-fallback block — no longer needed.
- **Verification method — note for future sessions:** verified via a **fresh Python
  interpreter per ticker calling `api.server.financials()` directly**, not real HTTP against
  a running `uvicorn --reload` server. Real-HTTP verification produced false "still broken"
  results earlier in this same work session: the `--reload` worker process did not reliably
  restart on file changes, so requests kept hitting pre-fix code (TRT briefly appeared to
  still show its Commit-1-fixed garbage margin, purely because the live worker was stale) —
  wasted significant time chasing a phantom regression that didn't exist in the actual code.
  If verifying this endpoint again via real HTTP, explicitly confirm the worker PID is fresh
  (check `Started server process [PID]` in the boot log against `Get-Process`) before trusting
  any response — don't assume `--reload` picked up an edit.
- **Verified (fresh-interpreter method):** NVDA (margin 71.46, date corrected to 2026-04-26),
  META (margin 47.54), FN (margin 10.31, date corrected to 2026-03-27), TRT (margin -0.23,
  confirms Commit 1's fix holds through this path), GOOGL (56.94) and CELH (10.87) both fully
  complete, nothing lost. Test suite unchanged (6 passed, 1 xfailed). Server boots clean.
- **Known, bounded gap — not fixed here, closed by Commit 3:** BLK, MU, and CMP lose their
  newest-quarter revenue and/or margin under this routing (BLK: revenue null, margin fine;
  MU: both null — its true newest quarter isn't inside `get_code33_data`'s expected window
  yet, a timing edge case, not a bug; CMP: showed margin null with revenue present on this
  verification run, but CMP's exact missing field varies run to run — it's the ticker most
  exposed to the pre-existing, separately-tracked count-gate flakiness above, unrelated to
  this fix). These three are a known interim state, to be closed by Commit 3.

### Newest-quarter-missing bug — edgar_revenue.py / edgar_net_margin.py open-fiscal-year gap
- **Commit:** `9c421c5` (2026-07-09)
- **What it was:** A ticker's newest already-filed quarter silently never reached output
  whenever that quarter belonged to a still-open fiscal year (no closing 10-K filed yet).
- **Root cause:** The quarter-assembly loop's only iteration driver was the list of
  already-filed 10-Ks — for each one, it scanned already-fetched 10-Qs for quarters strictly
  between that 10-K's period-end and the previous 10-K's (`prev_fye < period < fye`). A
  quarter filed *after* the latest 10-K had no window in that loop to land in at all. The
  quarter was extracted successfully from its own 10-Q — the bug was purely in assembly, not
  extraction.
- **How found:** Confirmed live on NVDA, AMD, and MSFT — each missing its newest
  already-filed quarter for exactly this reason.
- **How fixed:** Added an additive second pass — the strict complement (`period > latest_fye`)
  — that surfaces up to 3 such quarters directly from the already-fetched quarter pool. Never
  attempts Q4 derivation in the open year (no annual filing exists yet to derive from). Purely
  additive: 61 insertions, 0 deletions across both files; none of the 9 pre-existing hardcoded
  bug-fixes in either file were touched.
- **Verification:** NVDA/AMD (1 quarter open) and MSFT (3 quarters open, the real
  multi-quarter case) all correctly surfaced; AMD/MSFT cross-checked against Macrotrends
  independently (exact match); ORCL (fiscal year just closed, 0 quarters open) correctly
  returns nothing, no phantom entries; MU's dramatic Q2/Q3 FY2026 jump ($23.8B → $41.5B)
  verified real against Micron's own press release, not a bug. Regression-tested clean
  against 11 already-working tickers. **Re-verified live again 2026-07-11** during an
  unrelated investigation (NVDA reproduction for the double-merge bug below): newest quarter
  2026-04-26 confirmed present in `get_code33_data("NVDA")`'s output.
- **Note:** CLAUDE.md's IN PROGRESS section listed this as "pending explicit go-ahead, not
  yet implemented" for two days after it actually shipped — corrected 2026-07-11.

### sec_edgar.py cache-removal regression — SEC rate-limit cascade
- **Commit:** `f3faf5a` (2026-07-10) — caught before shipping, not a released regression
- **What it was:** During a cleanup pass, removing `@st.cache_data` from
  `sec_edgar.py::_get_ticker_mapping()` (a zero-arg function fetching SEC's full multi-MB
  ticker→CIK map) turned a one-fetch-per-process call into a one-fetch-per-ticker call.
- **Root cause:** `get_cik()` — called on every single ticker lookup by
  `secfs_net_margin.py`, `secfs_revenue.py`, `preflight_checks.py`, and
  `watchlist_ticker_audit.py` — calls `_get_ticker_mapping()` every time. With the decorator,
  one process-lifetime fetch was reused across an entire batch; without it, a 16-ticker
  verification run refetched the file 16x back-to-back and mid-run degraded into
  rate-limit/timeout failures.
- **How found:** Post-change regression verification (re-ran the same 16-ticker baseline
  capture used throughout this period) — 11 of 16 tickers (LIN, JNJ, CB, AME, BLK, NVDA, AMD,
  MSFT, AIP, CELH, plus a partial hit on CMP) collapsed to fully `insufficient` results.
  Caught during the verification step of the same session that introduced it — never
  committed or shipped in the broken state.
- **How fixed:** Replaced the removed decorator with `functools.lru_cache(maxsize=1)` —
  same one-fetch-per-process effect, no streamlit dependency. Judged appropriate specifically
  for this function: SEC's ticker→CIK map has no meaningful staleness risk within a process
  lifetime, unlike `code33_engine.py`'s 24h result cache (see next entry) where a bare
  removal was correct instead.
- **Verification:** Re-ran the identical 16-ticker capture post-fix — all previously-collapsed
  tickers matched the original baseline exactly (LIN, BLK, NVDA, AMD, MSFT, AIP, CELH
  byte-identical). Also boot-tested the FastAPI server end-to-end (`GET /api/ticker/MU` over
  real HTTP, 200 OK, server stopped cleanly) and ran the test suite (6 passed, 1 xfailed,
  unchanged from documented baseline).

### Dead st.cache_data decorators / stale CACHE_VERSION staleness risk
- **Commit:** `f3faf5a` (2026-07-10)
- **What it was:** `code33_engine.py::get_code33_data()` carried `@st.cache_data(ttl=86400)`;
  `sec_edgar.py` carried 4 more `@st.cache_data` decorators. Both leftover from a
  pre-FastAPI Streamlit architecture — no Streamlit runtime exists anymore (confirmed: every
  call triggers a "No runtime found, using MemoryCacheStorageManager" warning), so these were
  silently caching in-memory per long-running FastAPI server process, with no way to bust the
  cache short of a full restart.
- **Root cause / confirmed real risk:** `CACHE_VERSION` (the cache key's version component)
  was **not bumped** across the 4 most recent NI/revenue logic fix commits (`5f680ae`,
  `9c421c5`, `186d24d`, `8d455cf`) — none of them touch `code33_engine.py`. A long-running
  server left running across any of those deploys could have kept serving pre-fix cached
  numbers for up to 24h post-deploy.
- **How found:** Pre-check grep for `"streamlit"` (case-insensitive) across the live
  codebase, run ahead of a user-confirmed cleanup pass — found it wasn't just
  `code33_engine.py`; `sec_edgar.py` had 4 more instances. Cross-referenced `CACHE_VERSION`'s
  bump history via `git log` to confirm the staleness-window claim.
- **How fixed:** Removed `import streamlit as st` and the decorator from
  `code33_engine.py` (pure removal, no replacement — FastAPI doesn't need it). Removed 3 of
  `sec_edgar.py`'s 4 decorators the same way (`get_recent_filings`, `get_insider_filings`,
  `get_key_filings` — confirmed zero callers anywhere in the live codebase). The 4th
  (`_get_ticker_mapping`) needed a real replacement, not a bare removal — see the regression
  entry above.
- **Verification:** Server boot test (clean start, no import errors), live HTTP endpoint test
  (200 OK, full data returned), test suite (6 passed, 1 xfailed), full 16-ticker regression
  re-verification.

---

## Solution prepared, not yet implemented

### Count-gate double-merge redundancy
- **Found:** 2026-07-11, during META manual testing (`get_code33_data("META")` took 70.1s —
  over the expected budget).
- **What it is:** `secfs_revenue.py`/`secfs_net_margin.py`'s inner secfsdstools→edgartools
  fallback gates on `len(merged) >= n_quarters` — a pure count, with **zero recency check**.
  So it wrongly skips calling edgartools whenever secfsdstools already has ≥16 *old* quarters,
  even when the single newest expected quarter specifically is missing — which is the normal
  steady state, since the local secfsdstools bulk dataset lags live filings by ~1 quarter by
  design (documented in the module's own docstring).
- **Why it's not (currently) a correctness bug:** `code33_engine.py` runs its own, separate,
  date-aware target-quarter check (`_target_quarter_ends`/`_fill_target_quarters`) and
  re-fetches via edgartools itself whenever it finds the gap the inner layer missed — and that
  outer call succeeds, because it runs through the already-fixed `edgar_revenue.py`/
  `edgar_net_margin.py` (see "Newest-quarter-missing bug" above). Confirmed live on NVDA,
  right now: inner layer logs "16/16 secfsdstools quarters — skipping edgartools" (wrong,
  missing 2026-04-26); outer layer catches it and logs "rev source =
  secfsdstools+EDGAR-edgartools, missing = []" (correct); final output includes 2026-04-26.
  Verified this is a **separate, unrelated mechanism** from the already-fixed 07-07/`9c421c5`
  bug — different files, different pipeline layer (`git show 9c421c5 --stat` confirms
  `secfs_revenue.py`/`secfs_net_margin.py` were untouched by that commit, then or since).
- **Real cost:** ~19-33s of live edgartools latency per metric, per affected ticker, on every
  uncached call — purely from redundant work, not from any single call being duplicated
  (the inner layer never actually calls edgartools in the failing case; it just wrongly thinks
  it doesn't need to, and the outer layer ends up doing 100% of the real work anyway).
- **Blast radius:** Hits 13 of 16 tracked regression tickers — GOOGL, CMP, LIN, JNJ, CB, AME,
  NVDA, AMD, MSFT, AIP, CELH, PED, TEAM. Only MU, CPTP, and BLK's NI leg escape it (their local
  secfsdstools coverage happens to already include the newest quarter, or never accumulates
  ≥16 quarters in the first place so the inner layer's count-gate correctly falls through to
  edgartools on its own). This is the common case for mature, long-filing tickers, not an edge
  case.
- **Proposed plan (not implemented):** Give the inner fallback's skip decision the same
  recency-awareness `code33_engine.py` already has — e.g. check whether the newest entry
  already in `merged` is within the same ~45-day filing-lag tolerance of today, instead of
  just counting quarters. Once the inner layer reliably closes this gap itself, delete
  `code33_engine.py`'s now-redundant outer retry blocks (the `_rev_missing_precheck`/
  `_npm_missing_precheck` → second edgartools call pattern), keeping
  `_fill_target_quarters` only for its other job (final windowing/alignment against the
  target dates).
- **Status:** Investigated and planned across three separate sessions (2026-07-11); no code
  changed. Pending a decision to implement.

---

## No solution yet / open

*(None currently — the one item that was here is closed out below.)*

### TRT margin output not re-verified under the new NI-tag priority order — RESOLVED
**Closed out 2026-07-12** — the "next step" this item asked for (run TRT through the engine,
cross-check against its own filings) was done as part of investigating a different, more
urgent TRT symptom (a -230,303% margin). Result: TRT's NI *tag selection* was never the
problem — the extracted value exact-matched TRT's real filed net income ($-38,000). The
actual defect was the unrelated `_to_m()` unit-conversion bug (see Resolved section above).
Background/status kept for the record:
- TRT carries a `NetIncomeLossAvailableToCommonStockholdersBasic` tag, same as CELH — but for
  TRT that tag nets out non-controlling interest, not preferred dividends (TRT has no
  preferred stock, confirmed directly against its balance sheet). Same XBRL tag, different
  economic adjustment underneath it. This is fine — the tag choice was never wrong.
- An earlier, separate concern (duplicate/ambiguous rows under this tag) was investigated and
  cleared previously: a throwaway diagnostic script bug (missing XBRL `ddate` filter), not a
  production issue — `_own_period_value` already pins on `ddate` correctly.

---

## Verified clean, no issues found

Tickers manually tested and confirmed correct during this period, for context:

- **MU** — Q4 FY2024 net income derivation cross-checked directly against real SEC EDGAR
  10-K/10-Q filings (bypassing the secfsdstools/edgartools abstraction entirely). Engine's
  Q1+Q2+Q3+derived-Q4 arithmetic confirmed correct: $887M, matching the Macrotrends-implied
  figure ($888M) within rounding. Investigated 2026-07-10.
- **META** — Engine-side output (last 8 quarters revenue/NI/margin, sources, raw XBRL tag
  trace) and Macrotrends-side TTM data both pulled and manually cross-checked line by line;
  no discrepancies found (aside from the separate, already-documented count-gate performance
  issue above, which affects latency, not correctness, for META). Investigated 2026-07-11.
- **XOM** — Verified clean during this period.
