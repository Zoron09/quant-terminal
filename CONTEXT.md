# CONTEXT.md — Quant Terminal Project State
> Generated after CACHE_VERSION v29 (secfsdstools wiring + EPS removed from Code33 signal).
> See CLAUDE.md for full spec/rules. This file tracks current state, not rules.

---

## 1. File Inventory

### utils/
| File | Status |
|---|---|
| `code33_engine.py` | **Production** — Code33 engine. Rev/NI: secfsdstools primary → edgartools fallback → FMP/EDGAR-raw last resort. EPS still fetched (Finnhub primary, EDGAR fallback) but no longer feeds the status signal (v29). |
| `secfs_revenue.py` | **Production (new, v29)** — `get_quarterly_revenue()` / `get_quarterly_revenue_yoy()`. Reads the local secfsdstools parquet DB directly (sqlite-backed `CompanyIndexReader` + a shared, process-wide tag-filtered quarter cache — avoids secfsdstools' own collector/ParallelExecutor classes, which benchmarked at 40-340s/call on this machine). 365-day staleness gate before falling back to edgartools. |
| `secfs_net_margin.py` | **Production (new, v29)** — `get_quarterly_net_margin()` / `get_quarterly_net_margin_pct()`. Same architecture as `secfs_revenue.py`, reuses its shared quarter cache. |
| `edgar_revenue.py` | **Production** — `get_quarterly_revenue()`. PROTECTED — do not modify without a confirmed bug. Now the fallback tier, not primary. |
| `edgar_net_margin.py` | **Production** — `get_quarterly_net_margin()`. PROTECTED — do not modify without a confirmed bug. Now the fallback tier, not primary. |
| `sec_edgar.py` | **Production** — CIK lookup, filings list. v29: fixed `get_cik()` re-downloading SEC's full ticker→CIK mapping JSON on every call (and one dead, unused network call); mapping is now cached once per process via `_get_ticker_mapping()`. |
| `data_fetcher.py` | **Production** — Alpaca primary / yfinance fallback routing for price + financials. |
| `sepa_engine.py` | **Production** — Trend template, Weinstein stage, VCP, RS rank (pages/9_SEPA_Analysis.py). |
| `alpaca_client.py` | **Production** — Alpaca data + WebSocket streaming. |
| `finnhub_client.py` | **Production** — News, analyst ratings, earnings surprises. |
| `formatters.py` | **Production** — number/pct/price formatting helpers. |
| `sidebar.py` | **Production** — shared sidebar nav render. |
| `dcf_model.py` | **Production** — DCF calc (4_Valuation.py). |
| `piotroski.py` | **Production** — F-Score calc. |
| `portfolio_engine.py` | **Production** — portfolio P&L, optimizer, risk, backtest. |
| `__init__.py` | package marker. |

### api/
| File | Status |
|---|---|
| `server.py` | **Production** — FastAPI app. Serves frontend/*.html, `/api/scan` (CSV → Code33 batch via code33_engine), `/api/ticker`. |

### frontend/
| File | Status |
|---|---|
| `overview.html` | **Production** — served by api/server.py `/` route. |
| `screener.html` | **Production** — served by api/server.py `/screener` route; also embedded via iframe in pages/10_Screener.py. |
| `portfolio.html` | **Production** — served by api/server.py `/portfolio` route. |
| `colors_and_type.css` | **Production** — shared Bloomberg dark theme styling. |

### pages/ (Streamlit multipage app)
All 13 files are **production**, each a reachable tab: `2_Financials.py`, `3_Growth_and_Margins.py`, `4_Valuation.py`, `5_Earnings.py`, `6_Analyst_Ratings.py`, `7_Ownership.py`, `8_Peer_Comparison.py`, `9_SEPA_Analysis.py`, `10_Screener.py` (CSV-upload Code33 screener, embeds frontend/screener.html), `11_News_Sentiment.py`, `12_Portfolio.py`, `13_Market_Dashboard.py`, `15_stock_detail.py`.

### tools/
| File | Status |
|---|---|
| `code33_screener.py` | **Production CLI tool** — `python tools/code33_screener.py <csv>`. Reads TradingView CSV export, runs Code33 via code33_engine, writes results CSV. |
| `run_c33_batch.py` | **Production CLI tool (new, v29)** — `python tools/run_c33_batch.py`. Reads `Symbol` column from a Minervini-builder CSV export, runs `get_code33_data()` per ticker via `ThreadPoolExecutor(max_workers=10)`, writes `Ticker, Status, Rev_YoY_Q1-3, NPM_Q1-3, Source` incrementally (one row per ticker as it completes, not buffered to the end). Last full run: 381 tickers in 65.6 min, 0 errors. |

### archive/ (moved during v28 cleanup — not deleted, not currently wired in)
| File | Status |
|---|---|
| `utils/screener_db.py` | SQLite cache for a full Alpaca-universe screener (CLAUDE.md §9 describes this architecture; current pages/10_Screener.py is CSV-upload only and doesn't use it). Orphaned, zero imports anywhere. Kept in case the Alpaca-universe screener gets rebuilt. |
| `tools/batch_c33_scan.py`, `tools/fast_batch_c33_scan.py` | Earlier/duplicate batch Code33 scanners, superseded by `tools/code33_screener.py` / `tools/run_c33_batch.py`. |
| `tools/accuracy_audit.py`, `tools/code33_full_audit.py`, `tools/diagnose_eps.py`, `tools/eps_source_audit.py`, `tools/margin_accuracy_audit.py`, `tools/revenue_accuracy_audit.py` | Validation suite that checks engine output against EDGAR ground truth — the tooling that originally proved out edgar_revenue.py/edgar_net_margin.py accuracy. Kept for future regression checks, not run automatically.

**Deleted in v28 cleanup (not archived):** ~105 one-off ticker-debugging scripts from root and scratch/ (audit_*, test_*, diagnostic_*, check_*, investigate_*, fix_*, temp_* — KO/XOM/AXON/META/ADI debugging sessions), plus regenerable .txt/.log output files and two corrupted file copies (`cb9d504.py`, `temp_cb9d504.py`). Full list in commit `b565b72`.

---

## 2. Data Sources (as of v29)

| Metric | Primary | Fallback 1 | Fallback 2 (last resort) |
|---|---|---|---|
| **Revenue** | `secfs_revenue.get_quarterly_revenue()` (local secfsdstools parquet DB) | `edgar_revenue.get_quarterly_revenue()` (edgartools, live HTTP) | FMP quarterly income statement → EDGAR raw XBRL concepts → yfinance |
| **Net Margin** | `secfs_net_margin.get_quarterly_net_margin()` (secfsdstools, NI/Revenue) | `edgar_net_margin.get_quarterly_net_margin()` (edgartools, live HTTP) | FMP-paired or EDGAR-raw-paired margin pool (`_build_margin_pool`, strict source-lock — never mixes FMP rev with EDGAR ni) |
| **EPS** | Finnhub `stock/earnings` (adjusted) | EDGAR normalized EPS (NI / split-adjusted diluted shares) → FMP → yfinance `earnings_dates` | — (still computed and returned in `get_code33_data()`, but **no longer feeds `_c33_status`** as of v29) |

Selection rule for Rev/Margin: secfsdstools result used only if it has ≥3 non-null quarters AND the most recent end-date is within 365 days (lazily short-circuits to skip the live edgartools call entirely when this succeeds — edgartools is the slowest tier and was previously always computed regardless). edgartools result used only if it has ≥3 non-null quarters AND the most recent end-date is within ~18 months (`_is_recent`). Otherwise falls through to the FMP/EDGAR-raw pipeline. This selection logic lives entirely in `code33_engine.py`; `edgar_revenue.py`/`edgar_net_margin.py` were not modified (protected modules).

secfsdstools lags live filings by up to ~1 quarter (SEC only publishes bulk datasets quarterly; the most recent quarter for any given company isn't extractable until the *next* quarter's annual/10-K closes the window — same structural limitation as `edgar_revenue.py`, confirmed by direct comparison). The 365-day threshold was chosen empirically (started at 90, then 180) to balance freshness against secfsdstools actually being used as the fast path for most tickers.

---

## 3. What's Done (v29)

- **`utils/secfs_revenue.py` + `utils/secfs_net_margin.py` built.** Local-DB equivalents of `edgar_revenue.py`/`edgar_net_margin.py`, same own-period-pin + Q4-derivation architecture, but reading the local secfsdstools parquet DB instead of live HTTP. Each 10-Q's quarter is emitted directly and unconditionally (not gated on the fiscal year closing) — only Q4 still requires the annual 10-K, since it's never filed standalone.
- **Wired into `code33_engine.py` as the new primary tier**, ahead of edgartools, ahead of FMP/EDGAR-raw. Lazy short-circuit: the live edgartools call is skipped entirely whenever secfsdstools already resolves a ticker, cutting per-ticker latency substantially for the majority case.
- **`utils/sec_edgar.get_cik()` fixed** — was re-downloading the entire SEC ticker→CIK mapping JSON (~1-3s) on every single ticker call, plus making one entirely unused network request. Now caches the mapping once per process.
- **EPS removed from `_c33_status`.** Code33 status is now Revenue YoY acceleration + Net Margin expansion only, evaluated over the last 3 quarters. EPS is still fetched and returned in `get_code33_data()` for display, just no longer part of the gating signal. Rationale: a large fraction of tickers had complete Revenue+NPM data but were blocked from a real signal by a partial/missing EPS series (confirmed directly on LRCX, TWLO — both had full secfsdstools-sourced Revenue+NPM history but `eps_yoy` had only 1-2 of 4 quarters non-null).
- **`CACHE_VERSION` bumped to `v29`.**
- **`tools/run_c33_batch.py` rebuilt** to write each ticker's row to disk as soon as it completes (not buffered to the end) and to log the data source (`rev:<src>|ni:<src>`) per row.
- **Full batch run on `Minervini builder Managed copy_2026-06-23.csv` (381 tickers), post EPS-removal:** 65.6 min, 0 errors. GREEN: AIP, CMP, MU (4th GREEN ticker, EIX, is a Utilities-sector stock — see §4, Code33's sector exclusion is not currently applied to the `status` field, so EIX should be treated as a false positive, not a real signal). YELLOW: 13. RED: 314. INSUFFICIENT: 50 (down from 94 in the pre-fix run — confirms the EPS-removal fix's intended effect).
- Performance work: discovered secfsdstools' own collector classes that spin up its `ParallelExecutor` cost 40-340s/call regardless of how much is requested (ProcessPoolExecutor spin-up cost on Windows); avoided entirely in favor of the sqlite-backed `CompanyIndexReader` (~1s) plus a shared, tag-filtered, in-process parquet cache keyed by quarter folder (one disk read per quarter file, reused across every ticker and both metrics in a batch run).

---

## 4. What's Pending

- **Sector-exclusion gating gap (found during v29 batch run, not yet fixed).** `code33_engine.py` computes `sector_excluded` (True for Utilities + cyclical/airline industry keywords) and returns it in the data dict, but `status` is computed independently and does **not** check `sector_excluded` — so a Utilities-sector ticker can still come back GREEN/RED/YELLOW from `_c33_status` alone. This is why EIX showed up GREEN in the v29 batch run despite being a utility. `tools/run_c33_batch.py` and `tools/code33_screener.py` don't apply this filter either (only `tests/test_code33_regression.py`'s own replica logic does, as an external wrapper). Needs a decision next session: gate inside `_c33_status`/`get_code33_data`, or apply consistently in every caller.
- **Per-quarter merge logic between secfsdstools and edgartools is not implemented — pending next session.** The current selection is all-or-nothing per metric per ticker (whichever source's *entire* series passes the freshness+length check wins). A merged approach — secfsdstools for older/historical quarters it has covered, edgartools filling in just the newest quarter(s) it's missing — would likely raise the secfsdstools-resolved rate further and reduce reliance on the slow live-HTTP fallback, but requires quarter-level (not series-level) source selection and was out of scope for this session.
- **EPS module not built.** There is no `secfs_eps.py`/`edgar_eps.py`-parity local-DB module for EPS — it still runs the older Finnhub/EDGAR/FMP/yfinance fallback chain inside `code33_engine.py`. Lower priority now that EPS no longer gates the Code33 signal, but EPS is still displayed/returned and used elsewhere.
- **Screener filters missing.** Neither `pages/10_Screener.py` nor `tools/code33_screener.py` has: an ADV (average daily volume) floor, a sector dropdown/selector, or a revenue floor. The only exclusions currently applied (at fetch time, not status time — see gating gap above) are the hard sector list and the pre-profit check (6 consecutive negative EPS quarters).
- CLAUDE.md §9 describes a ~6000-11000 stock Alpaca-universe screener with SQLite caching — that architecture (`archive/utils/screener_db.py`) is not currently wired into any page; the real screener today is CSV-upload only.
- **secfsdstools local DB currency.** As of this session, the local parquet DB tops out at `2026q1.zip` (SEC hadn't published `2026q2.zip` yet — confirmed via direct HTTP check, 404). Re-running secfsdstools' update process once `2026q2` (or later) is published will extend the fast/fresh-via-secfsdstools coverage window without any code changes.

---

## 5. Key Decisions

- **EPS removed from the Code33 signal (v29).** Code33 now evaluates Revenue YoY acceleration + Net Margin expansion only, over the last 3 quarters. Decided after the v29 batch run showed the majority of INSUFFICIENT tickers had complete Revenue+NPM data and were blocked only by a partial EPS series — EPS coverage (Finnhub-adjusted + EDGAR-normalized fallback) is patchier than Revenue/NPM coverage across the full ticker universe, mainly due to fiscal-calendar misalignment between Finnhub and EDGAR comparison windows. EPS is still fetched and shown, just doesn't gate status.
- **secfsdstools is now ground truth for Revenue + Net Margin when fresh enough (within 365 days).** When stale/insufficient, falls through to edgartools (live, will always have newer quarters than the local bulk DB, which lags by ~1 quarter structurally), then FMP/EDGAR-raw as last resort.
- **365-day secfsdstools freshness threshold (started at 90, raised to 180, then to 365 this session).** SEC's bulk datasets are released quarterly with a lag, so the "freshest quarter" extractable via either secfsdstools OR edgartools is structurally anchored to the most recently *closed* fiscal year/quarter for a given company, not to "today." A 90-day window almost never passed for any ticker; 365 days lets secfsdstools resolve the large majority of tickers fast while still excluding genuinely-stale data.
- **edgar_revenue.py / edgar_net_margin.py remain protected, untouched.** Both still carry "do not modify without a confirmed bug" headers. All v29 integration was done by adding selection logic in `code33_engine.py` and building net-new `secfs_*.py` modules, never touching either protected module.
- **secfsdstools' built-in collector classes (`CompanyReportCollector`, multi-item `MultiReportCollector`) are avoided entirely** in favor of direct sqlite index lookups (`CompanyIndexReader`) + a hand-rolled, shared, tag-filtered parquet cache — empirically 40-340x faster for this batch-of-many-tickers use case (their `ParallelExecutor` has a large fixed per-call cost on Windows that doesn't amortize across multiple CIKs the way you'd expect).

---

## 6. Known Edge Cases

- **FN (Fabrinet) — June fiscal year end.** Non-calendar fiscal calendar; quarter labels are fiscal-quarter, not calendar-quarter. Status currently YELLOW under the v29 (secfsdstools-primary, EPS-removed) pipeline: Revenue YoY accelerating (+0.86pp → +14.28pp) but Net Margin deltas shrinking (+0.21pp → +0.14pp) — held back by margin, not by the FN-specific Q4-derivation quirk noted in v28.
- **AXON — lumpy NI from stock-based comp / legal settlements.** Net margin swings heavily quarter to quarter, which reads as margin contraction under Code33's rules even though it may just be one-time charge noise rather than a genuine fundamental deterioration. Worth a manual look before treating an AXON RED/GREEN flip as a real signal change.
- **Pre-revenue/early-stage biotechs show "no revenue match" from secfsdstools and "no revenue row" from edgartools across every quarter checked (e.g. DSGN, CMPS).** Confirmed both sources genuinely have no usable Revenue concept tag filed — this is a real data gap (company reports no/near-zero revenue under any of the standard XBRL revenue tags), not a code bug. These will stay INSUFFICIENT regardless of further fixes to the selection logic.
- **Tiny-revenue-base companies produce extreme YoY% swings.** E.g. AMLX showed rev_yoy values like +34133% and -100% from quarter-over-quarter swings off a near-zero base, plus mostly-null NPM. Genuinely insufficient/unreliable data, not a bug.
