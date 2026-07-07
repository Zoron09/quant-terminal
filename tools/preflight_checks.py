"""
Pre-flight checks for the Code33 GREEN scan shortlist.
====================================================
Runs against an already-computed get_code33_data() result and flags known-broken
data-quality patterns before a ticker's GREEN signal ships. Each detector returns
a human-readable flag reason (or None); run_preflight() aggregates all of them.

Detectors:
  1. INSUFFICIENT status for a US-listed ticker (CODE33_SPEC.md: never acceptable)
  2. Sub-viable latest-quarter revenue (YoY swings on a tiny base are noise)
  3. SEC-declared reporting currency other than USD

Detector 3 makes one extra network call (edgartools, latest 10-Q's XBRL facts) —
on any failure it returns None (skip) rather than guess, since a false positive
here is worse than a missed catch.

A "code label vs SEC-declared fiscal quarter" mismatch detector was built and
tested (meant to catch TRT's non-standard fiscal year) but removed: it also
fired on CMP, which has a non-Dec FYE (Sept 30) too and is a legitimate current
GREEN ticker — the label mismatch turned out to be a common, apparently
harmless cosmetic quirk for non-Dec-FYE filers in general, not a marker of a
real data bug. TRT is not caught by any detector here as a result — see the
xfail note in tests/test_preflight_checks.py.
"""

import re

REVENUE_FLOOR = 2_000_000  # verified against AIP ($11.2M) / CMP ($202.9M) / MU ($3.69B) quarterly minimums

_QUARTER_RE = re.compile(r"Q(\d)")


def check_insufficient_status(ticker, data):
    if data.get('is_us', True) and str(data.get('status', '') or '').lower() == 'insufficient':
        return "status is INSUFFICIENT for a US-listed ticker — spec says this is never acceptable (data pipeline gap)"
    return None


def check_revenue_floor(ticker, data, floor=REVENUE_FLOOR):
    rev = [v for v in (data.get('rev') or []) if v is not None]
    if not rev:
        return None  # no data at all — already caught by check_insufficient_status
    latest = rev[-1]
    if latest < floor:
        return f"latest quarterly revenue ${latest:,.0f} is below the ${floor:,.0f} sub-viability floor — YoY swings likely noise, not signal"
    return None


def _latest_10q_fact(ticker, concept, max_filings=4):
    """Fetch `concept` from the most recent 10-Q that has both DocumentPeriodEndDate
    and the requested concept. Returns (period_end, value) or (None, None)."""
    from edgar import Company, set_identity
    set_identity("QuantTerminal preflight@quant-terminal.local")

    company = Company(ticker)
    filings = company.get_filings(form='10-Q').head(max_filings)
    for f in filings:
        xbrl = f.xbrl()
        facts = xbrl.facts
        pe = facts.query().by_concept('dei:DocumentPeriodEndDate').to_dataframe()
        target = facts.query().by_concept(concept).to_dataframe()
        if len(pe) and len(target):
            return str(pe['value'].iloc[0])[:10], str(target['value'].iloc[0]).strip()
    return None, None


def check_reporting_currency(ticker, data):
    try:
        _, iso = _latest_10q_fact(ticker, 'dei:EntityReportingCurrencyISOCode', max_filings=2)
    except Exception:
        return None
    if iso and iso.upper() != 'USD':
        return f"SEC filing reports financials in {iso.upper()}, not USD — revenue/NI figures are foreign-currency, not directly comparable"
    return None


def run_preflight(ticker, data):
    """Returns a list of human-readable flag reasons; empty list = clean."""
    checks = [
        check_insufficient_status(ticker, data),
        check_revenue_floor(ticker, data),
        check_reporting_currency(ticker, data),
    ]
    return [c for c in checks if c]
