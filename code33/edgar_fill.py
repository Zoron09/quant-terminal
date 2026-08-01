"""Live-EDGAR gap filler (edgartools) — fallback/supporting source only, never primary.

Pulls a company's XBRL facts once per process (cached) and answers targeted
"give me the discrete quarter ending near this date" requests for whatever
quarters secfsdstools doesn't have yet — structurally, the bulk mirror lags
real filings, so the gap is usually (not always) the single newest quarter.

SEC requires a compliant identifying User-Agent on all API calls; set_identity
handles that here.
"""
import logging
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

import pandas as pd

from edgar import Company, set_identity

log = logging.getLogger(__name__)

set_identity("Meet Singh monikaarya.work@gmail.com")

# Discrete ("three months ended") duration window, days. Fiscal quarters run
# 13 weeks (91d) but 52/53-week calendars and month-length wobble spread this.
_QUARTER_MIN_DAYS = 75
_QUARTER_MAX_DAYS = 100

# A fact's period_end must land within this many days of the requested target
# to count as that quarter. Needs to absorb two effects stacking: secfsdstools
# rounds ddates to the nearest month end (up to ~15d off the true period end,
# which EDGAR facts carry exactly), plus 52/53-week calendar drift. Quarters
# sit ~91 days apart, so 25d can never grab an adjacent quarter.
MATCH_TOLERANCE_DAYS = 25

_FACTS_CACHE: Dict[str, Optional[pd.DataFrame]] = {}


def _load_facts_df(ticker: str) -> Optional[pd.DataFrame]:
    """All duration-type facts for ticker as one dataframe, cached per process."""
    if ticker in _FACTS_CACHE:
        return _FACTS_CACHE[ticker]
    try:
        company = Company(ticker)
        facts = company.get_facts()
        # Deliberately no by_period_type("quarterly") here: edgartools' period
        # classifier silently drops some genuinely-quarterly rows (seen live:
        # DELL's newest 10-Q). The explicit 75-100 day duration filter below
        # is the real discrete-quarter test.
        df = facts.query().to_dataframe()
    except Exception as exc:
        log.warning("edgar_fill: facts pull failed for %s: %s", ticker, exc)
        _FACTS_CACHE[ticker] = None
        return None

    if df is None or df.empty:
        _FACTS_CACHE[ticker] = None
        return None

    df = df.copy()
    df["period_start"] = pd.to_datetime(df["period_start"], errors="coerce")
    df["period_end"] = pd.to_datetime(df["period_end"], errors="coerce")
    df["filing_date"] = pd.to_datetime(df["filing_date"], errors="coerce")
    df = df.dropna(subset=["period_start", "period_end", "numeric_value"])
    df["_days"] = (df["period_end"] - df["period_start"]).dt.days
    df = df[(df["_days"] >= _QUARTER_MIN_DAYS) & (df["_days"] <= _QUARTER_MAX_DAYS)]
    df = df[df["form_type"].isin(["10-Q", "10-K"])]
    _FACTS_CACHE[ticker] = df
    return df


# Bank/depository-institution signal tags — STRONG signals only. Confirmed
# live (568-ticker scan): bare InterestIncomeExpenseNet/InterestRevenueExpenseNet
# are useless as bank signals — Delta, CVS, CSX, JB Hunt and ~65 other plain
# non-banks file them for nonoperating net interest. Genuine banks all carry
# at least one of these three: NoninterestIncome (bank-only vocabulary, and
# definitionally where the fee income that caused the FULT wrong-revenue bug
# lives), the bank top-line RevenuesNetOfInterestExpense, or a loan-loss
# provision line only lenders file. Deliberately NOT sector labels or ticker
# lists. REITs, insurers, and asset managers file none of these.
BANK_SIGNAL_TAGS = {
    "us-gaap:InterestIncomeExpenseAfterProvisionForLoanLoss",
    "us-gaap:NoninterestIncome",
    "us-gaap:RevenuesNetOfInterestExpense",
}


def bank_signal_tags(ticker: str) -> list:
    """The bank-signal tags this company actually files (empty list = not a
    bank, or facts unavailable — caller decides how to treat the latter)."""
    df = _load_facts_df(ticker)
    if df is None or df.empty:
        return []
    present = set(df["concept"].unique()) & BANK_SIGNAL_TAGS
    return sorted(t.split(":", 1)[1] for t in present)


def fetch_discrete_quarter(
    ticker: str, target_end: date, tag_priority: List[str]
) -> Optional[Tuple[date, float, str, str, date, Optional[int], Optional[str]]]:
    """The discrete-quarter value ending nearest target_end (within tolerance).

    Returns (period_end, value, tag, accession, filing_date, fy, fp) or None.
    Tag priority mirrors the secfsdstools pull. Within a tag, the ORIGINAL
    as-filed figure wins (earliest filing_date) — same restatement principle as
    the primary source: later filings' comparative-column revisions never replace
    what the original filing reported for its own period.

    fy/fp come from the same selected row and are what let a gap-filled quarter
    carry a fiscal label instead of a blank one. They are only trustworthy
    BECAUSE of the earliest-filing_date rule above: edgartools stamps every fact
    with its FILING's fiscal year/period, so a quarter's own original 10-Q
    labels it correctly, while the comparative columns republished in later
    filings carry the later filing's fy/fp. Selecting the original filing avoids
    that mislabel by construction. Both degrade to None when absent or NaN — a
    blank label is the honest output, never a guessed one.
    """
    df = _load_facts_df(ticker)
    if df is None or df.empty:
        return None

    lo = pd.Timestamp(target_end - timedelta(days=MATCH_TOLERANCE_DAYS))
    hi = pd.Timestamp(target_end + timedelta(days=MATCH_TOLERANCE_DAYS))
    window = df[(df["period_end"] >= lo) & (df["period_end"] <= hi)]
    if window.empty:
        return None

    for tag in tag_priority:
        tag_rows = window[window["concept"] == f"us-gaap:{tag}"]
        if tag_rows.empty:
            continue
        row = tag_rows.sort_values("filing_date").iloc[0]
        fy_raw, fp_raw = row.get("fiscal_year"), row.get("fiscal_period")
        return (
            row["period_end"].date(),
            float(row["numeric_value"]),
            tag,
            str(row.get("accession") or ""),
            row["filing_date"].date() if pd.notna(row["filing_date"]) else target_end,
            int(fy_raw) if pd.notna(fy_raw) else None,
            str(fp_raw) if pd.notna(fp_raw) else None,
        )
    return None
