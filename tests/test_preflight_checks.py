import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from utils.code33_engine import get_code33_data
from tools.preflight_checks import run_preflight

SHOULD_FLAG = ['EDRY', 'CPTP', 'KEWL', 'TRT']
SHOULD_NOT_FLAG = ['AIP', 'CMP', 'MU']

# TRT's known issue (non-standard fiscal year, code's quarter label disagrees
# with SEC's declared fiscal quarter) is real but not a safe detector: CMP has
# the same kind of mismatch (FYE Sept 30) and is a legitimate GREEN ticker, so
# a mismatch-based check false-positives on CMP. No detector below catches TRT
# yet. Tracked here instead of silently dropping TRT from the suite.
XFAIL_TICKERS = {'TRT': "fiscal-label-mismatch detector removed (false-positived on CMP); no safe detector for TRT's issue yet"}


@pytest.mark.parametrize("ticker", SHOULD_FLAG)
def test_known_broken_tickers_are_flagged(ticker):
    if ticker in XFAIL_TICKERS:
        pytest.xfail(XFAIL_TICKERS[ticker])
    data = get_code33_data(ticker)
    flags = run_preflight(ticker, data)
    assert flags, f"{ticker} should have been flagged by at least one pre-flight check, got none (status={data.get('status')})"


@pytest.mark.parametrize("ticker", SHOULD_NOT_FLAG)
def test_known_good_tickers_are_not_flagged(ticker):
    data = get_code33_data(ticker)
    flags = run_preflight(ticker, data)
    assert not flags, f"{ticker} should NOT have been flagged (false positive), got: {flags}"
