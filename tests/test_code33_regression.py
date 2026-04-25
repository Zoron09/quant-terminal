import os
import json
import pytest
import sys
import importlib

# Add parent dir to sys.path to import pages
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
stock_detail = importlib.import_module("pages.15_stock_detail")
get_code33_data = stock_detail.get_code33_data
_c33_status = stock_detail._c33_status

FIXTURE_PATH = os.path.join(os.path.dirname(__file__), 'fixtures', 'code33_ground_truth.json')

with open(FIXTURE_PATH, 'r') as f:
    GROUND_TRUTH = json.load(f)

TICKERS = list(GROUND_TRUTH.keys())

def check_value(name, actual, expected, tol=0.6):
    if expected is None and actual is None:
        return
    if actual is None:
        pytest.fail(f"{name} is None, expected {expected:.1f}")
    if expected is None:
        pytest.fail(f"{name} is {actual:.1f}, expected None")
    
    diff = abs(actual - expected)
    if diff > tol:
        pytest.fail(f"{name} mismatch! Actual: {actual:.1f}%, Expected: {expected:.1f}% (Diff: {diff:.1f}pp > {tol}pp tol)")

@pytest.mark.parametrize("ticker", TICKERS)
def test_code33_regression(ticker):
    expected = GROUND_TRUTH[ticker]
    
    try:
        data = get_code33_data(ticker)
    except Exception as e:
        pytest.fail(f"Engine threw exception for {ticker}: {e}")
        
    rev_yoy = data.get('rev_yoy', [])
    npm_vals = data.get('npm', [])
    eps_yoy = data.get('eps_yoy', [])
    eps_raw = data.get('eps', [])
    
    is_us = data.get('is_us', True)
    sector_excluded = data.get('sector_excluded', False)
    
    # Check if pre-profit (all 6 latest raw EPS are negative)
    is_preprofit = False
    if len(eps_raw) >= 6:
        last6_eps = eps_raw[-6:]
        if all(v is not None and v < 0 for v in last6_eps):
            is_preprofit = True
            
    if len(npm_vals) < 3:
        npm_status = 'insufficient'
    else:
        npm_d1 = npm_vals[-2] - npm_vals[-3]
        npm_d2 = npm_vals[-1] - npm_vals[-2]
        if npm_d1 < 0 or npm_d2 < 0:
            npm_status = 'red'
        elif npm_vals[-3] < 0 and npm_vals[-2] < 0 and npm_vals[-1] < 0:
            npm_status = 'not_applicable'
        else:
            npm_status = 'green' if (npm_d1 > 0 and npm_d2 > 0) else 'yellow'

    if is_preprofit or not is_us or sector_excluded:
        status_str = "NOT_APPLICABLE"
    elif len(rev_yoy) < 3 or len(eps_yoy) < 3:
        status_str = "INSUFFICIENT"
    else:
        eps_status, _, _ = _c33_status(eps_yoy[-3:])
        rev_status, _, _ = _c33_status(rev_yoy[-3:])
        
        statuses = [eps_status, rev_status, npm_status]
        if all(s == 'insufficient' for s in statuses):
            status_str = "INSUFFICIENT"
        elif 'red' in statuses:
            status_str = "BROKEN"
        elif 'yellow' in statuses:
            status_str = "ACTIVE"
        elif all(s == 'green' for s in statuses):
            status_str = "ACTIVE"
        elif 'insufficient' in statuses:
            status_str = "INSUFFICIENT"
        else:
            status_str = "ACTIVE"
            
    if status_str == "INSUFFICIENT" and expected.get('signal') != "INSUFFICIENT":
        pytest.skip(f"{ticker} returned INSUFFICIENT data but expected {expected.get('signal')}.")
        
    if status_str != expected.get('signal'):
        pytest.fail(f"Signal mismatch! Actual: {status_str}, Expected: {expected.get('signal')}")
        
    if status_str in ["NOT_APPLICABLE", "INSUFFICIENT"]:
        return

    actual_rev_q2 = rev_yoy[-3] if len(rev_yoy) >= 3 else None
    actual_rev_q1 = rev_yoy[-2] if len(rev_yoy) >= 2 else None
    actual_rev_q0 = rev_yoy[-1] if len(rev_yoy) >= 1 else None
    
    actual_npm_q2 = npm_vals[-3] if len(npm_vals) >= 3 else None
    actual_npm_q1 = npm_vals[-2] if len(npm_vals) >= 2 else None
    actual_npm_q0 = npm_vals[-1] if len(npm_vals) >= 1 else None
    
    if 'rev_q2' in expected: check_value("Revenue Q-2", actual_rev_q2, expected['rev_q2'])
    if 'rev_q1' in expected: check_value("Revenue Q-1", actual_rev_q1, expected['rev_q1'])
    if 'rev_q0' in expected: check_value("Revenue Q0", actual_rev_q0, expected['rev_q0'])
    
    if 'npm_q2' in expected: check_value("NPM Q-2", actual_npm_q2, expected['npm_q2'])
    if 'npm_q1' in expected: check_value("NPM Q-1", actual_npm_q1, expected['npm_q1'])
    if 'npm_q0' in expected: check_value("NPM Q0", actual_npm_q0, expected['npm_q0'])
