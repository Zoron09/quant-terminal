import pandas as pd
import numpy as np


def _get(df: pd.DataFrame, keys: list, col: int = 0):
    """Try multiple possible row names; return float or None."""
    if df is None or df.empty:
        return None
    for k in keys:
        if k in df.index:
            try:
                val = df.loc[k].iloc[col]
                if pd.notna(val):
                    return float(val)
            except Exception:
                pass
    return None


def calculate_piotroski(info: dict, financials: dict) -> dict:
    """
    Calculate all 9 Piotroski F-Score criteria.
    Returns dict with keys F1..F9, each {'name', 'pass', 'value'}, plus 'total'.
    """
    scores = {}

    bs = financials.get('balance_annual')
    cf = financials.get('cashflow_annual')
    inc = financials.get('income_annual')

    # ── Profitability ──────────────────────────────────────────────────────────

    # F1: Positive ROA
    roa = info.get('returnOnAssets')
    scores['F1'] = {
        'name': 'Positive ROA',
        'pass': roa is not None and not np.isnan(float(roa)) and float(roa) > 0,
        'value': f"{float(roa)*100:.2f}%" if roa is not None else 'N/A',
    }

    # F2: Positive operating cash flow
    ocf = _get(cf, ['Operating Cash Flow', 'Cash From Operations', 'Total Cash From Operating Activities'])
    scores['F2'] = {
        'name': 'Positive Operating Cash Flow',
        'pass': ocf is not None and ocf > 0,
        'value': f"${ocf/1e9:.2f}B" if ocf is not None else 'N/A',
    }

    # F3: Improving ROA YoY
    net_inc_curr = _get(inc, ['Net Income', 'Net Income Common Stockholders'], 0)
    net_inc_prev = _get(inc, ['Net Income', 'Net Income Common Stockholders'], 1)
    ta_curr = _get(bs, ['Total Assets'], 0)
    ta_prev = _get(bs, ['Total Assets'], 1)
    roa_curr = (net_inc_curr / ta_curr) if (net_inc_curr and ta_curr) else None
    roa_prev = (net_inc_prev / ta_prev) if (net_inc_prev and ta_prev) else None
    scores['F3'] = {
        'name': 'Improving ROA (YoY)',
        'pass': roa_curr is not None and roa_prev is not None and roa_curr > roa_prev,
        'value': (f"{roa_curr*100:.2f}% vs {roa_prev*100:.2f}%"
                  if roa_curr is not None and roa_prev is not None else 'N/A'),
    }

    # F4: Cash flow > net income (quality of earnings)
    scores['F4'] = {
        'name': 'Cash Flow > Net Income',
        'pass': ocf is not None and net_inc_curr is not None and ocf > net_inc_curr,
        'value': (f"OCF ${ocf/1e9:.2f}B vs NI ${net_inc_curr/1e9:.2f}B"
                  if ocf and net_inc_curr else 'N/A'),
    }

    # ── Leverage / Liquidity ───────────────────────────────────────────────────

    # F5: Lower long-term debt ratio
    debt_curr = _get(bs, ['Long Term Debt', 'Total Debt', 'Long Term Debt And Capital Lease Obligation'], 0)
    debt_prev = _get(bs, ['Long Term Debt', 'Total Debt', 'Long Term Debt And Capital Lease Obligation'], 1)
    ldr_curr = (debt_curr / ta_curr) if (debt_curr is not None and ta_curr) else None
    ldr_prev = (debt_prev / ta_prev) if (debt_prev is not None and ta_prev) else None
    scores['F5'] = {
        'name': 'Lower Long-Term Debt Ratio',
        'pass': ldr_curr is not None and ldr_prev is not None and ldr_curr < ldr_prev,
        'value': (f"{ldr_curr*100:.1f}% vs {ldr_prev*100:.1f}%"
                  if ldr_curr is not None and ldr_prev is not None else 'N/A'),
    }

    # F6: Higher current ratio (proxy: current ratio > 1)
    curr_ratio = info.get('currentRatio')
    scores['F6'] = {
        'name': 'Current Ratio > 1',
        'pass': curr_ratio is not None and float(curr_ratio) > 1.0,
        'value': f"{float(curr_ratio):.2f}" if curr_ratio else 'N/A',
    }

    # F7: No new shares issued
    shares_issued = _get(cf, ['Common Stock Issued', 'Issuance Of Capital Stock', 'Proceeds From Issuance Of Common Stock'], 0)
    scores['F7'] = {
        'name': 'No New Shares Issued',
        'pass': shares_issued is None or shares_issued <= 0,
        'value': (f"${shares_issued/1e6:.1f}M issued" if shares_issued and shares_issued > 0
                  else 'None issued'),
    }

    # ── Operating Efficiency ──────────────────────────────────────────────────

    # F8: Higher gross margin
    gp_curr = _get(inc, ['Gross Profit'], 0)
    gp_prev = _get(inc, ['Gross Profit'], 1)
    rev_curr = _get(inc, ['Total Revenue', 'Revenue'], 0)
    rev_prev = _get(inc, ['Total Revenue', 'Revenue'], 1)
    gm_curr = (gp_curr / rev_curr) if (gp_curr and rev_curr) else None
    gm_prev = (gp_prev / rev_prev) if (gp_prev and rev_prev) else None
    scores['F8'] = {
        'name': 'Improving Gross Margin',
        'pass': gm_curr is not None and gm_prev is not None and gm_curr > gm_prev,
        'value': (f"{gm_curr*100:.1f}% vs {gm_prev*100:.1f}%"
                  if gm_curr is not None and gm_prev is not None else 'N/A'),
    }

    # F9: Higher asset turnover
    at_curr = (rev_curr / ta_curr) if (rev_curr and ta_curr) else None
    at_prev = (rev_prev / ta_prev) if (rev_prev and ta_prev) else None
    scores['F9'] = {
        'name': 'Improving Asset Turnover',
        'pass': at_curr is not None and at_prev is not None and at_curr > at_prev,
        'value': (f"{at_curr:.2f}x vs {at_prev:.2f}x"
                  if at_curr is not None and at_prev is not None else 'N/A'),
    }

    scores['total'] = sum(1 for k, v in scores.items() if k != 'total' and v.get('pass'))
    return scores
