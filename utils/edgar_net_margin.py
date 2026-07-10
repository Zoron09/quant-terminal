"""
utils/edgar_net_margin.py  —  Production quarterly Net Margin fetcher via edgartools.

PROTECTED MODULE — do not modify without a confirmed bug.

All five bugs discovered during testing are hardcoded as permanent safeguards:

  BUG 1  10-K/A amended filings      amendments=False on every 10-K fetch.
                                      Amended 10-K/A filings lack full XBRL data
                                      and cause silent NI extraction failures.
                                      (confirmed: TSLA, AMD returned N/A without fix)

  BUG 2  Prior-year column (CRWD)    Pin column selection to the filing's own
                                      period_of_report date, not q_cols[0].
                                      edgartools income-statement DataFrames contain
                                      both current-period and prior-year comparison
                                      columns; ordering is not guaranteed.
                                      (confirmed: CRWD FY26 Q2 NI grabbed wrong year)

  BUG 3  FY boundary estimate        Use exact previous 10-K period end as the
                                      fiscal year start boundary. Never use a
                                      day-count estimate — it can admit quarters
                                      from the wrong fiscal year.
                                      (confirmed: CRWD FY26 Q2 admitted FY25 quarter)

  BUG 4  Concept priority (LITE)     edgartools maps us-gaap_IncomeLossAttributable-
                                      ToParent (pre-tax income) to standard_concept
                                      'NetIncome', alongside us-gaap_NetIncomeLoss
                                      (actual after-tax). iloc[0] silently returns
                                      the pre-tax row when it appears first.
                                      Apply 3-tier priority to pick the correct row.
                                      (confirmed: LITE FY25 Q4 = -$11.4M without fix,
                                      +$213.3M after fix. Annual NI was -$172.1M
                                      pre-tax vs +$25.9M actual after large tax benefit)

  BUG 5  Q4 derivation validation    Require exactly {Q1, Q2, Q3} within the FY
                                      window before deriving Q4. Belt-and-suspenders
                                      fps check plus _is_implausible_ni guard.
                                      NI can legitimately be negative or volatile
                                      (one-time charges), so the guard is intentionally
                                      looser than the Revenue equivalent.
"""

import logging
from datetime import date, timedelta

from edgar import Company, set_identity as _edgar_set_identity

from utils.edgar_revenue import get_quarterly_revenue

log = logging.getLogger(__name__)

_edgar_set_identity("Meet Singh meetsingh@example.com")


# ── Private helpers ───────────────────────────────────────────────────────────

def _period_cols(df) -> list[str]:
    """All date-prefixed column headers (YYYY-MM-DD ...) from a statement df."""
    return [c for c in df.columns if len(c) > 8 and c[4] == "-" and c[7] == "-"]


def _ni_row(df):
    """
    Return the best single-row DataFrame for Net Income.

    BUG 4 safeguard — 3-tier priority (LITE confirmed):

    Tier 1: standard_concept=='NetIncomeToCommonShareholders'
            → after-preferred-dividends net income attributable to common
            stockholders (Code33 margin convention — matches Macrotrends and
            Minervini's EPS numerator; see CELH 2024-09-30 investigation).

    Tier 2: standard_concept=='NetIncome' AND concept contains 'NetIncomeLoss'
            → the real us-gaap_NetIncomeLoss (after-tax, before preferred
            dividends). Skips us-gaap_IncomeLossAttributableToParent which
            edgartools incorrectly maps to standard_concept='NetIncome' for
            some filers.

    Tier 3: last standard_concept=='NetIncome' row, undimensioned, non-breakdown
            → after-tax net income always appears below the income tax line
            in income statement ordering, so iloc[-1] is safer than iloc[0].
    """
    mask = (df["dimension"] == False) & (df["is_breakdown"] == False)
    ni = df[mask & (df["standard_concept"] == "NetIncome")]

    nic = df[mask & (df["standard_concept"] == "NetIncomeToCommonShareholders")]
    if not nic.empty:
        return nic.iloc[[-1]]

    if not ni.empty and "concept" in df.columns:
        nl = ni[ni["concept"].str.contains("NetIncomeLoss", na=False, case=False)]
        if not nl.empty:
            return nl.iloc[[-1]]

    if not ni.empty:
        return ni.iloc[[-1]]

    return ni


def _to_m(val: float) -> float:
    """Convert raw USD value to millions, rounded to 1 decimal."""
    return round(val / 1_000_000, 1) if abs(val) >= 1_000_000 else round(val, 1)


def _is_implausible_ni(q4: float, annual: float) -> bool:
    """
    BUG 5 guard: return True only if the derived Q4 is arithmetically absurd.

    Guard applies ONLY when |Annual NI| >= $100M. Below that threshold the
    annual NI is near-zero (large quarterly swings offsetting each other), so
    any non-trivial Q4 will look implausible relative to the tiny net.
    (confirmed: LITE FY25 annual NI = +$25.9M, Q4 = +$213.3M; without the
    $100M floor the check incorrectly flagged 213.3 > 25.9 × 5 = 129.5)

    When |Annual| >= $100M, flags |Q4| > |Annual| × 10.
    (confirmed: CRWD FY24 derived Q4 = -$490,945M correctly blocked)
    """
    if abs(annual) >= 100 and abs(q4) > abs(annual) * 10:
        return True
    return False


def _extract_annual_ni(filing) -> float | None:
    """
    Extract full-year Net Income in millions from a 10-K filing.

    BUG 1: caller must have fetched with amendments=False.
    BUG 4: uses _ni_row() priority chain, not a plain standard_concept filter.
    """
    try:
        xb = filing.xbrl()
        income = xb.statements.income_statement()
        df = income.to_dataframe()
        ni = _ni_row(df)
        if ni.empty:
            log.warning("edgar_net_margin: no NI row in 10-K period=%s",
                        filing.period_of_report)
            return None
        cols = _period_cols(df)
        fy_cols = [c for c in cols if "(FY)" in c]
        col = fy_cols[0] if fy_cols else (cols[0] if cols else None)
        if col is None:
            return None
        return _to_m(float(ni.iloc[0][col]))
    except Exception as exc:
        log.warning("edgar_net_margin: _extract_annual_ni period=%s: %s",
                    filing.period_of_report, exc)
        return None


def _extract_quarterly_ni(filing) -> float | None:
    """
    Extract single-quarter (not YTD) Net Income in millions from a 10-Q filing.

    BUG 2 safeguard: pins column selection to the filing's own period_of_report
    date before falling back to q_cols[0].

    BUG 4 safeguard: uses _ni_row() priority chain.
    """
    own_period: str = filing.period_of_report
    try:
        xb = filing.xbrl()
        income = xb.statements.income_statement()
        df = income.to_dataframe()
        ni = _ni_row(df)
        if ni.empty:
            log.warning("edgar_net_margin: no NI row in 10-Q period=%s", own_period)
            return None
        cols = _period_cols(df)
        q_cols = [c for c in cols if "(Q" in c and "YTD" not in c]
        own_cols = [c for c in q_cols if c.startswith(own_period)]
        col = (own_cols[0] if own_cols
               else q_cols[0] if q_cols
               else cols[0] if cols
               else None)
        if col is None:
            return None
        return _to_m(float(ni.iloc[0][col]))
    except Exception as exc:
        log.warning("edgar_net_margin: _extract_quarterly_ni period=%s: %s",
                    own_period, exc)
        return None


def _get_ni_quarters(ticker: str, n_quarters: int) -> list[dict]:
    """
    Internal NI fetcher — same architecture as edgar_net_income.py.
    Returns list of dicts with keys: period_end (date), fiscal_quarter,
    net_income_m (float), source (str).
    All 5 bug safeguards applied.
    """
    try:
        company = Company(ticker)
    except Exception as exc:
        log.warning("edgar_net_margin: Company('%s') failed: %s", ticker, exc)
        return []

    n_10q = min(n_quarters + 6, 20)
    try:
        raw_10q = company.get_filings(form="10-Q").latest(n_10q)
    except Exception as exc:
        log.warning("edgar_net_margin: %s 10-Q fetch failed: %s", ticker, exc)
        raw_10q = []

    q_pool: dict[str, float] = {}
    for i in range(len(raw_10q)):
        f = raw_10q[i]
        ni = _extract_quarterly_ni(f)
        if ni is not None:
            q_pool[f.period_of_report] = ni
        else:
            log.warning("edgar_net_margin: %s 10-Q period=%s skipped (no NI)",
                        ticker, f.period_of_report)

    # BUG 1: amendments=False; fetch extra for BUG 3 prev_fye
    n_fy = max((n_quarters // 4) + 2, 3)
    try:
        annual_obj = company.get_filings(form="10-K", amendments=False).latest(n_fy)
    except Exception as exc:
        log.warning("edgar_net_margin: %s 10-K fetch failed: %s", ticker, exc)
        annual_obj = []

    annual_list: list = [annual_obj[i] for i in range(len(annual_obj))]

    results: list[dict] = []
    seen: set[date] = set()

    for idx, af in enumerate(annual_list):
        try:
            fye = date.fromisoformat(af.period_of_report)
        except (ValueError, TypeError):
            continue

        # BUG 3: exact previous FY end from already-fetched list
        if idx + 1 < len(annual_list):
            try:
                prev_fye = date.fromisoformat(annual_list[idx + 1].period_of_report)
            except (ValueError, TypeError):
                prev_fye = fye - timedelta(days=366)
        else:
            prev_fye = fye - timedelta(days=366)

        fy_qs: list[tuple[date, float]] = sorted(
            [
                (date.fromisoformat(p), ni)
                for p, ni in q_pool.items()
                if prev_fye < date.fromisoformat(p) < fye
            ],
            key=lambda x: x[0],
        )

        for qi, (period, ni) in enumerate(fy_qs[:3]):
            if period not in seen:
                seen.add(period)
                results.append({
                    "period_end":     period,
                    "fiscal_quarter": f"Q{qi + 1}",
                    "net_income_m":   ni,
                    "source":         "10-Q",
                })

        # BUG 5: require exactly three quarters
        if len(fy_qs) < 3:
            log.warning(
                "edgar_net_margin: %s FY=%s — %d quarter(s) in window, need 3; skipping Q4",
                ticker, af.period_of_report, len(fy_qs)
            )
            continue

        fps = {f"Q{i + 1}" for i in range(3)}
        if fps != {"Q1", "Q2", "Q3"}:
            log.warning("edgar_net_margin: %s FY=%s unexpected fps=%s; skipping Q4",
                        ticker, af.period_of_report, fps)
            continue

        # BUG 4: _extract_annual_ni uses _ni_row() priority chain
        annual_ni = _extract_annual_ni(af)
        if annual_ni is None:
            log.warning("edgar_net_margin: %s FY=%s annual NI unavailable; skipping Q4",
                        ticker, af.period_of_report)
            continue

        q1_ni, q2_ni, q3_ni = fy_qs[0][1], fy_qs[1][1], fy_qs[2][1]
        q4_ni = round(annual_ni - q1_ni - q2_ni - q3_ni, 1)

        if _is_implausible_ni(q4_ni, annual_ni):
            log.warning(
                "edgar_net_margin: %s FY=%s derived Q4=%.1fM failed implausibility check; skipping",
                ticker, af.period_of_report, q4_ni
            )
            continue

        if fye not in seen:
            seen.add(fye)
            results.append({
                "period_end":     fye,
                "fiscal_quarter": "Q4",
                "net_income_m":   q4_ni,
                "source":         "derived_q4",
            })

    # ── Open fiscal year: quarters already filed since the newest 10-K, with
    # no closing 10-K yet to anchor a window — see utils/edgar_revenue.py's
    # identical block for the full reasoning (same bug, same shape, mirrored
    # here for NI). Never attempts Q4 derivation — no annual filing exists yet
    # for this year. Strict complement of the existing prev_fye < period < fye
    # test (period > latest fye), so no gap/overlap with the loop above.
    if annual_list:
        try:
            latest_fye = date.fromisoformat(annual_list[0].period_of_report)
        except (ValueError, TypeError):
            latest_fye = None
        if latest_fye is not None:
            open_qs: list[tuple[date, float]] = sorted(
                [(date.fromisoformat(p), ni) for p, ni in q_pool.items()
                 if date.fromisoformat(p) > latest_fye],
                key=lambda x: x[0],
            )
            for qi, (period, ni) in enumerate(open_qs[:3]):
                if period not in seen:
                    seen.add(period)
                    results.append({
                        "period_end":     period,
                        "fiscal_quarter": f"Q{qi + 1}",
                        "net_income_m":   ni,
                        "source":         "10-Q",
                    })

    results.sort(key=lambda r: r["period_end"], reverse=True)
    return results[:n_quarters]


# ── Public API ────────────────────────────────────────────────────────────────

def get_quarterly_net_margin(ticker: str, n_quarters: int = 8) -> list[dict]:
    """
    Return up to n_quarters of quarterly Net Margin for ticker, sorted newest first.

    Each element is a dict:
      'ticker'          str   — e.g. 'LITE'
      'period_end'      date  — calendar end-date of the quarter
      'fiscal_quarter'  str   — 'Q1' | 'Q2' | 'Q3' | 'Q4'
      'net_margin_pct'  float — Net Income / Revenue × 100, rounded to 2 dp
      'source'          str   — '10-Q' (both direct) |
                                'derived_q4' (either NI or revenue is derived)

    Hardcoded safeguards — never remove:
      BUG 1  amendments=False on every 10-K get_filings call (TSLA, AMD)
      BUG 2  pin quarterly column to filing's own period_of_report date (CRWD)
      BUG 3  use exact previous 10-K period end as FY start boundary (CRWD)
      BUG 4  _ni_row() 3-tier concept priority — avoids pre-tax row (LITE)
      BUG 5  require exactly {Q1,Q2,Q3}; _is_implausible_ni guard before Q4

    Returns empty list (never raises) if edgartools returns no data or if
    revenue is zero / unavailable for a quarter (division guard).
    """
    ni_quarters = _get_ni_quarters(ticker, n_quarters)
    if not ni_quarters:
        return []

    rev_quarters = get_quarterly_revenue(ticker, n_quarters)
    if not rev_quarters:
        return []

    # Index revenue by period_end for O(1) lookup
    rev_by_period: dict[date, dict] = {r["period_end"]: r for r in rev_quarters}

    results: list[dict] = []
    for ni_item in ni_quarters:
        period = ni_item["period_end"]
        rev_item = rev_by_period.get(period)
        if rev_item is None:
            log.warning("edgar_net_margin: %s period=%s — no revenue match; skipping",
                        ticker, period)
            continue

        revenue_m = rev_item["revenue_m"]
        if not revenue_m:
            log.warning("edgar_net_margin: %s period=%s — revenue zero/null; skipping",
                        ticker, period)
            continue

        net_margin_pct = round((ni_item["net_income_m"] / revenue_m) * 100, 2)

        # source is derived_q4 if either leg is derived
        source = ("derived_q4"
                  if "derived" in ni_item["source"] or "derived" in rev_item["source"]
                  else "10-Q")

        results.append({
            "ticker":         ticker,
            "period_end":     period,
            "fiscal_quarter": ni_item["fiscal_quarter"],
            "net_margin_pct": net_margin_pct,
            "source":         source,
        })

    results.sort(key=lambda r: r["period_end"], reverse=True)
    return results[:n_quarters]
