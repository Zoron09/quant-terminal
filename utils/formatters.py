import numpy as np
from datetime import datetime


def _is_na(val):
    if val is None:
        return True
    try:
        if isinstance(val, float) and np.isnan(val):
            return True
    except Exception:
        pass
    return False


def fmt_number(val, decimals=2, prefix='', suffix=''):
    if _is_na(val):
        return 'N/A'
    try:
        return f"{prefix}{float(val):,.{decimals}f}{suffix}"
    except Exception:
        return 'N/A'


def fmt_large_number(val, symbol='$'):
    if _is_na(val):
        return 'N/A'
    try:
        v = float(val)
        sign = '-' if v < 0 else ''
        v = abs(v)
        if v >= 1e12:
            return f"{sign}{symbol}{v/1e12:.2f}T"
        elif v >= 1e9:
            return f"{sign}{symbol}{v/1e9:.2f}B"
        elif v >= 1e6:
            return f"{sign}{symbol}{v/1e6:.2f}M"
        elif v >= 1e3:
            return f"{sign}{symbol}{v/1e3:.2f}K"
        else:
            return f"{sign}{symbol}{v:.2f}"
    except Exception:
        return 'N/A'


def fmt_pct(val, decimals=2, already_pct=False):
    if _is_na(val):
        return 'N/A'
    try:
        v = float(val)
        if not already_pct:
            v = v * 100
        return f"{v:.{decimals}f}%"
    except Exception:
        return 'N/A'


def fmt_price(val):
    if _is_na(val):
        return 'N/A'
    try:
        v = float(val)
        return f"${v:,.2f}"
    except Exception:
        return 'N/A'


def fmt_volume(val):
    if _is_na(val):
        return 'N/A'
    try:
        v = int(float(val))
        if v >= 1_000_000:
            return f"{v/1_000_000:.2f}M"
        elif v >= 1_000:
            return f"{v/1_000:.1f}K"
        return f"{v:,}"
    except Exception:
        return 'N/A'


def fmt_fin(val):
    """Format financial statement numbers (M/B, parentheses for negatives)."""
    if _is_na(val):
        return 'N/A'
    try:
        v = float(val)
        negative = v < 0
        v = abs(v)
        if v >= 1e9:
            s = f"{v/1e9:.2f}B"
        elif v >= 1e6:
            s = f"{v/1e6:.1f}M"
        else:
            s = f"{v:,.0f}"
        return f"({s})" if negative else s
    except Exception:
        return 'N/A'


def fmt_date(val):
    if _is_na(val):
        return 'N/A'
    try:
        if isinstance(val, (int, float)):
            return datetime.fromtimestamp(val).strftime('%Y-%m-%d')
        return str(val)[:10]
    except Exception:
        return 'N/A'


def color_val(val, good='high'):
    """Return neon green / red / white based on sign."""
    if _is_na(val):
        return '#888888'
    try:
        v = float(val)
        if v > 0:
            return '#00FF41' if good == 'high' else '#FF4444'
        elif v < 0:
            return '#FF4444' if good == 'high' else '#00FF41'
        return '#FFFFFF'
    except Exception:
        return '#888888'


def pe_color(pe_val):
    if _is_na(pe_val):
        return '#888888'
    try:
        pe = float(pe_val)
        if pe < 0:
            return '#FF4444'
        elif pe < 15:
            return '#00FF41'
        elif pe < 30:
            return '#FFD700'
        else:
            return '#FF4444'
    except Exception:
        return '#888888'


def safe_get(d, key, default=None):
    if not isinstance(d, dict):
        return default
    val = d.get(key, default)
    if _is_na(val):
        return default
    return val
