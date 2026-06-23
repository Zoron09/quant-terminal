# CONTEXT.md — Quant Terminal Project State
> Generated after CACHE_VERSION v28 (edgartools wiring + repo cleanup).
> See CLAUDE.md for full spec/rules. This file tracks current state, not rules.

---

## 1. File Inventory

### utils/
| File | Status |
|---|---|
| `code33_engine.py` | **Production** — Code33 engine. Rev/NI: edgartools primary, FMP/EDGAR-raw fallback. EPS: Finnhub primary, EDGAR fallback. Unchanged since v28. |
| `edgar_revenue.py` | **Production** — `get_quarterly_revenue()`. PROTECTED — do not modify without a confirmed bug. |
| `edgar_net_margin.py` | **Production** — `get_quarterly_net_margin()`. PROTECTED — do not modify without a confirmed bug. |
| `sec_edgar.py` | **Production** — CIK lookup, filings list. |
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
| `code33_screener.py` | **Production CLI tool** — `python tools/code33_screener.py <csv>`. Reads TradingView CSV export, runs Code33 via code33_engine, writes results CSV. The only file left in tools/ after cleanup. |

### archive/ (moved during v28 cleanup — not deleted, not currently wired in)
| File | Status |
|---|---|
| `utils/screener_db.py` | SQLite cache for a full Alpaca-universe screener (CLAUDE.md §9 describes this architecture; current pages/10_Screener.py is CSV-upload only and doesn't use it). Orphaned, zero imports anywhere. Kept in case the Alpaca-universe screener gets rebuilt. |
| `tools/batch_c33_scan.py`, `tools/fast_batch_c33_scan.py` | Earlier/duplicate batch Code33 scanners, superseded by `tools/code33_screener.py`. |
| `tools/accuracy_audit.py`, `tools/code33_full_audit.py`, `tools/diagnose_eps.py`, `tools/eps_source_audit.py`, `tools/margin_accuracy_audit.py`, `tools/revenue_accuracy_audit.py` | Validation suite that checks engine output against EDGAR ground truth — the tooling that originally proved out edgar_revenue.py/edgar_net_margin.py accuracy. Kept for future regression checks, not run automatically.

**Deleted in v28 cleanup (not archived):** ~105 one-off ticker-debugging scripts from root and scratch/ (audit_*, test_*, diagnostic_*, check_*, investigate_*, fix_*, temp_* — KO/XOM/AXON/META/ADI debugging sessions), plus regenerable .txt/.log output files and two corrupted file copies (`cb9d504.py`, `temp_cb9d504.py`). Full list in commit `b565b72`.

---

## 2. Data Sources (as of v28)

| Metric | Primary | Fallback |
|---|---|---|
| **Revenue** | `edgar_revenue.get_quarterly_revenue()` (edgartools) | FMP quarterly income statement → EDGAR raw XBRL concepts → yfinance |
| **Net Margin** | `edgar_net_margin.get_quarterly_net_margin()` (edgartools, NI/Revenue) | FMP-paired or EDGAR-raw-paired margin pool (`_build_margin_pool`, strict source-lock — never mixes FMP rev with EDGAR ni) |
| **EPS** | Finnhub `stock/earnings` (adjusted) | EDGAR normalized EPS (NI / split-adjusted diluted shares) → FMP → yfinance `earnings_dates` |

Selection rule for Rev/Margin: edgartools result used only if it has ≥3 non-null quarters AND the most recent end-date is within ~18 months (`_is_recent`). Otherwise falls through to the existing FMP/EDGAR-raw pipeline untouched. This logic lives entirely in `code33_engine.py`; `edgar_revenue.py`/`edgar_net_margin.py` were not modified (protected modules).

---

## 3. What's Done

- edgartools (`edgar_revenue.py`, `edgar_net_margin.py`) wired into `code33_engine.py` as primary source for Revenue + Net Margin, with the prior pipeline retained as automatic fallback.
- Repo cleaned: 9 files archived, ~105 junk/debug files deleted (see §1).
- `CACHE_VERSION` bumped to `v28`.
- EPS logic and `_c33_status` untouched per instruction.
- Verified live on FN and AXON post-change — both resolve `sources.rev`/`sources.ni` to `EDGAR-edgartools`. Engine compiles clean (`py_compile` pass).
- Committed and pushed to `origin/main` (`b565b72`).

---

## 4. What's Pending

- **EPS module not built.** There is no `edgar_eps.py` equivalent to `edgar_revenue.py`/`edgar_net_margin.py` — EPS still runs the older Finnhub/EDGAR/FMP/yfinance fallback chain inside `code33_engine.py`, untouched by the v28 work.
- **Screener filters missing.** Neither `pages/10_Screener.py` nor `tools/code33_screener.py` has: an ADV (average daily volume) floor, a sector dropdown/selector, or a revenue floor. The only exclusions currently applied are the hard sector list (Utilities + cyclical/airline industry keywords, baked into `code33_engine.py`) and the pre-profit check (6 consecutive negative EPS quarters).
- CLAUDE.md §9 describes a ~6000-11000 stock Alpaca-universe screener with SQLite caching — that architecture (`archive/utils/screener_db.py`) is not currently wired into any page; the real screener today is CSV-upload only.

---

## 5. Key Decisions

- **GAAP EPS for bulk screening, manual 10-Q review on shortlist.** The engine's EPS figures (Finnhub-adjusted primary, EDGAR GAAP-normalized fallback) are treated as good enough to rank/filter a large universe, but not as the final word — anything that screens as a Code33 candidate should get its actual 10-Q EPS checked by hand before acting on it.
- **edgartools is ground truth for Revenue + Net Margin.** When `edgar_revenue.py`/`edgar_net_margin.py` return sufficient recent data, their numbers override FMP — FMP/EDGAR-raw is fallback-only, not a cross-check average.
- **edgar_revenue.py / edgar_net_margin.py are protected.** Both carry a "do not modify without a confirmed bug" header. The v28 integration was done by adding selection logic in `code33_engine.py` rather than touching either protected module.

---

## 6. Known Edge Cases

- **FN (Fabrinet) — June fiscal year end.** Non-calendar fiscal calendar; quarter labels are fiscal-quarter, not calendar-quarter. Under the new edgartools-primary path, FN's Code33 status flipped from YELLOW (old FMP-based numbers) to RED (edgartools-derived numbers) — the two pipelines derive Q4 differently (edgartools subtracts Q1+Q2+Q3 from the 10-K annual; FMP reports each quarter directly), and for FN this changes the qualifying signal. Flagged, not yet independently verified against the raw 10-Q.
- **AXON — lumpy NI from stock-based comp / legal settlements.** Net margin swings heavily quarter to quarter (e.g. 23.72% → 14.58% → 5.4% → ‑0.31% → 0.35%), which reads as margin contraction under Code33's rules even though it may just be one-time charge noise rather than a genuine fundamental deterioration. Worth a manual look before treating an AXON RED/GREEN flip as a real signal change.
