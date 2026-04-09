import streamlit as st
import sys, os
import pandas as pd
import plotly.graph_objects as go

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.sidebar import render_sidebar
from utils.data_fetcher import get_ticker_info, get_ownership_data
from utils.formatters import fmt_large_number, fmt_pct, safe_get

st.set_page_config(page_title="Ownership · Quant Terminal", page_icon="🏦", layout="wide")

_css = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'styles', 'custom.css')
if os.path.exists(_css):
    with open(_css) as _f:
        st.markdown(f'<style>{_f.read()}</style>', unsafe_allow_html=True)

ticker = render_sidebar()
st.markdown("## 🏦 Ownership")

if not ticker:
    st.info("Enter a ticker in the sidebar.")
    st.stop()

DARK = dict(
    plot_bgcolor='#0E1117', paper_bgcolor='#0E1117',
    font=dict(color='#CCCCCC', family='Courier New'),
)

with st.spinner(f"Loading ownership data for {ticker} …"):
    info  = get_ticker_info(ticker)
    own   = get_ownership_data(ticker)

# ── OWNERSHIP SUMMARY ─────────────────────────────────────────────────────────
st.markdown('<div class="section-title">Ownership Summary</div>', unsafe_allow_html=True)

insider_pct = safe_get(info, 'heldPercentInsiders')
inst_pct    = safe_get(info, 'heldPercentInstitutions')

ow_c1, ow_c2 = st.columns([1, 1])
with ow_c1:
    for label, val, color in [
        ("Insider Ownership",      insider_pct, '#00FF41'),
        ("Institutional Ownership", inst_pct,   '#00BFFF'),
    ]:
        pct_str = fmt_pct(val) if val else 'N/A'
        st.markdown(f"""
        <div class="stat-card" style="border-left-color:{color};">
          <div class="stat-label">{label}</div>
          <div class="stat-value" style="color:{color}">{pct_str}</div>
        </div>""", unsafe_allow_html=True)

with ow_c2:
    if insider_pct and inst_pct:
        retail = max(0, 1 - insider_pct - inst_pct)
        fig = go.Figure(go.Pie(
            labels=['Insiders', 'Institutions', 'Retail/Other'],
            values=[insider_pct, inst_pct, retail],
            marker_colors=['#00FF41', '#00BFFF', '#FFD700'],
            hole=0.5,
            textinfo='label+percent',
        ))
        fig.update_layout(**DARK, height=240, margin=dict(l=0, r=0, t=10, b=0), showlegend=False)
        st.plotly_chart(fig, use_container_width=True)

st.markdown("---")

# ── INSIDER TRANSACTIONS ──────────────────────────────────────────────────────
st.markdown('<div class="section-title">Insider Transactions</div>', unsafe_allow_html=True)

# SEC Form 4 transaction code → (label, direction)
# direction: 'buy' | 'sell' | 'neutral'
_TX_CODE = {
    'P': ('Purchase',          'buy'),
    'S': ('Sale',              'sell'),
    'A': ('Award / Grant',     'buy'),
    'D': ('Disposition',       'sell'),
    'F': ('Tax Withholding',   'sell'),
    'G': ('Gift',              'neutral'),
    'M': ('Option Exercise',   'buy'),
    'X': ('Option Exercise',   'buy'),
    'W': ('Warrant Exercise',  'buy'),
    'C': ('Conversion',        'neutral'),
    'U': ('Expiration',        'sell'),
    'J': ('Other Acquisition', 'buy'),
    'K': ('Other Disposition', 'sell'),
    'L': ('Small Acquisition', 'buy'),
    'Z': ('Deposit/Withdrawal','neutral'),
}
_DIR_COLOR = {'buy': '#00FF41', 'sell': '#FF4444', 'neutral': '#888888'}
_DIR_BG    = {'buy': '#00FF4110', 'sell': '#FF444410', 'neutral': '#00000000'}


def _tx_label_and_color(code: str, text_hint: str = ''):
    """Return (label, color, bg_color) from a transaction code or free-text hint."""
    code = (code or '').strip().upper()
    if code in _TX_CODE:
        label, direction = _TX_CODE[code]
        return label, _DIR_COLOR[direction], _DIR_BG[direction]

    # Fall back to keyword scan on free text (yfinance 'Text' field)
    hint = (text_hint or '').lower()
    if any(w in hint for w in ('purchase', 'bought', 'buy', 'open market purchase')):
        return 'Purchase', _DIR_COLOR['buy'], _DIR_BG['buy']
    if any(w in hint for w in ('sale', 'sold', 'sell', 'open market sale')):
        return 'Sale', _DIR_COLOR['sell'], _DIR_BG['sell']
    if any(w in hint for w in ('award', 'grant', 'restrict')):
        return 'Award / Grant', _DIR_COLOR['buy'], _DIR_BG['buy']
    if 'gift' in hint:
        return 'Gift', _DIR_COLOR['neutral'], _DIR_BG['neutral']
    if any(w in hint for w in ('exercise', 'option')):
        return 'Option Exercise', _DIR_COLOR['buy'], _DIR_BG['buy']
    if any(w in hint for w in ('tax', 'withheld', 'withholding')):
        return 'Tax Withholding', _DIR_COLOR['sell'], _DIR_BG['sell']

    return code if code else '—', '#888888', '#00000000'


def _fmt_val(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return 'N/A'
    try:
        v = float(v)
        if v >= 1e9:  return f'${v/1e9:.2f}B'
        if v >= 1e6:  return f'${v/1e6:.2f}M'
        if v >= 1e3:  return f'${v/1e3:.0f}K'
        return f'${v:,.0f}'
    except Exception:
        return 'N/A'


def _build_tx_rows(rows: list[dict]) -> str:
    """Render a list of normalised transaction dicts to HTML table rows."""
    html = ''
    for r in rows[:30]:
        label, color, bg = _tx_label_and_color(r.get('code', ''), r.get('text', ''))
        direction_arrow  = '▲' if color == '#00FF41' else ('▼' if color == '#FF4444' else '●')
        shares_str = f"{abs(int(r['shares'])):,}" if r.get('shares') is not None else 'N/A'
        html += f"""<tr style="background:{bg};">
  <td style="text-align:left;font-family:monospace;color:#AAAAAA">{r.get('date','N/A')}</td>
  <td style="text-align:left;color:#CCCCCC">{str(r.get('name','N/A'))[:32]}</td>
  <td style="text-align:left;color:#888888;font-size:11px">{str(r.get('title',''))[:24]}</td>
  <td style="text-align:left;color:{color};font-weight:bold">{direction_arrow} {label}</td>
  <td style="text-align:right;font-family:monospace">{shares_str}</td>
  <td style="text-align:right;font-family:monospace;color:{color}">{r.get('value_str','N/A')}</td>
</tr>"""
    return html


# ── Try Finnhub first (US stocks — has proper transactionCode and price) ──────
fh_it = own.get('fh_insider_transactions')
rows_normalised = []

if fh_it is not None and not fh_it.empty:
    for _, row in fh_it.iterrows():
        change = row.get('change')          # negative = sold, positive = bought
        shares = row.get('share')           # total shares held after tx
        price  = row.get('transactionPrice')
        code   = str(row.get('transactionCode', '') or '').strip().upper()

        # Use abs(change) as the number of shares transacted
        tx_shares = abs(int(change)) if pd.notna(change) and change != 0 else (
                    abs(int(shares)) if pd.notna(shares) else None)

        # Calculate value: shares transacted × price
        val = None
        if tx_shares and pd.notna(price) and price and price > 0:
            val = tx_shares * float(price)

        rows_normalised.append({
            'date':      str(row.get('transactionDate', row.get('filingDate', '')))[:10],
            'name':      str(row.get('name', 'N/A')),
            'title':     '',
            'code':      code,
            'text':      '',
            'shares':    tx_shares,
            'value_str': _fmt_val(val),
        })

# ── Fall back to yfinance insider_transactions ────────────────────────────────
elif own.get('insider_transactions') is not None and not own['insider_transactions'].empty:
    it = own['insider_transactions']
    for _, row in it.iterrows():
        # yfinance Transaction column is broken (empty strings) — use Text field
        # and infer from Shares sign (always positive in yf, so we rely on Text)
        yf_tx    = str(row.get('Transaction', '') or '').strip()
        yf_text  = str(row.get('Text', '') or '').strip()
        shares   = row.get('Shares')
        val      = row.get('Value')
        date_raw = row.get('Start Date', '')
        name     = str(row.get('Insider', 'N/A'))
        title    = str(row.get('Position', ''))

        # yfinance Ownership column: 'D'=direct, 'I'=indirect — NOT transaction type
        # The Transaction column is always empty in current yfinance builds.
        # Derive type from Text field; if no text, mark as unknown.

        # Value: use provided or skip (no price available to calculate)
        val_computed = None
        if pd.notna(val) and val and float(val) > 0:
            val_computed = float(val)

        rows_normalised.append({
            'date':      str(date_raw)[:10] if date_raw else 'N/A',
            'name':      name,
            'title':     title,
            'code':      '',          # always empty in current yfinance
            'text':      yf_text,     # Text hint used by _tx_label_and_color
            'shares':    abs(int(shares)) if pd.notna(shares) and shares else None,
            'value_str': _fmt_val(val_computed),
        })

if rows_normalised:
    source_label = 'Finnhub' if fh_it is not None and not fh_it.empty else 'yfinance'
    st.caption(f"Source: {source_label} · Codes: P=Purchase, S=Sale, A=Award, D=Disposition, F=Tax withholding, M=Option exercise")

    table_html = f"""
<div style="overflow-x:auto;">
<table style="width:100%;border-collapse:collapse;font-size:13px;">
<thead>
<tr style="background:#161B22;color:#888;text-transform:uppercase;font-size:10px;
           border-bottom:1px solid #333;letter-spacing:1px;font-family:monospace;">
  <th style="padding:7px 8px;text-align:left;">Date</th>
  <th style="padding:7px 8px;text-align:left;">Insider</th>
  <th style="padding:7px 8px;text-align:left;">Title</th>
  <th style="padding:7px 8px;text-align:left;">Transaction</th>
  <th style="padding:7px 8px;text-align:right;">Shares</th>
  <th style="padding:7px 8px;text-align:right;">Value</th>
</tr></thead>
<tbody>
{_build_tx_rows(rows_normalised)}
</tbody>
</table>
</div>"""
    st.markdown(table_html, unsafe_allow_html=True)

    # ── Net buying summary ────────────────────────────────────────────────────
    if fh_it is not None and not fh_it.empty:
        st.markdown("<br>", unsafe_allow_html=True)
        sc1, sc2, sc3 = st.columns(3)
        for period_days, col, label in [(90, sc1, '3 Months'), (180, sc2, '6 Months'), (365, sc3, '12 Months')]:
            cutoff = pd.Timestamp.now() - pd.Timedelta(days=period_days)
            buys = sells = 0
            for r in rows_normalised:
                try:
                    if pd.Timestamp(r['date']) < cutoff:
                        continue
                    code = r.get('code', '')
                    if code in ('P', 'A', 'M', 'X', 'W', 'J', 'L'):
                        buys += r['shares'] or 0
                    elif code in ('S', 'D', 'F', 'U', 'K'):
                        sells += r['shares'] or 0
                except Exception:
                    pass
            net = buys - sells
            net_c = '#00FF41' if net > 0 else ('#FF4444' if net < 0 else '#888888')
            col.markdown(f"""
<div style="background:#161B22;border:1px solid #333;border-radius:6px;
            padding:10px 14px;text-align:center;">
  <div style="color:#888;font-size:11px;font-family:monospace;">{label}</div>
  <div style="color:#00FF41;font-size:13px;font-family:monospace;">
    ▲ {buys:,} bought</div>
  <div style="color:#FF4444;font-size:13px;font-family:monospace;">
    ▼ {sells:,} sold</div>
  <div style="color:{net_c};font-weight:bold;font-family:monospace;margin-top:4px;">
    Net: {net:+,}</div>
</div>""", unsafe_allow_html=True)
else:
    st.info("Insider transaction data not available.")

st.markdown("---")

# ── INSTITUTIONAL HOLDERS ─────────────────────────────────────────────────────
st.markdown('<div class="section-title">Top Institutional Holders</div>', unsafe_allow_html=True)

ih = own.get('institutional_holders')
if ih is not None and not ih.empty:
    try:
        ih_display = ih.head(15).copy()
        # Format numeric columns
        for col in ih_display.columns:
            cl = col.lower()
            if 'shares' in cl or 'value' in cl:
                ih_display[col] = ih_display[col].apply(
                    lambda x: fmt_large_number(x) if pd.notna(x) else 'N/A'
                )
            elif 'pct' in cl or 'percent' in cl or '%' in cl:
                ih_display[col] = ih_display[col].apply(
                    lambda x: fmt_pct(x) if pd.notna(x) else 'N/A'
                )
        st.dataframe(ih_display, hide_index=True, use_container_width=True)
    except Exception:
        st.dataframe(ih.head(15), use_container_width=True)
else:
    st.info("Institutional holder data not available.")

st.markdown("---")

# ── MUTUAL FUND HOLDERS ───────────────────────────────────────────────────────
st.markdown('<div class="section-title">Top Mutual Fund Holders</div>', unsafe_allow_html=True)

mf = own.get('mutualfund_holders')
if mf is not None and not mf.empty:
    try:
        mf_display = mf.head(15).copy()
        for col in mf_display.columns:
            cl = col.lower()
            if 'shares' in cl or 'value' in cl:
                mf_display[col] = mf_display[col].apply(
                    lambda x: fmt_large_number(x) if pd.notna(x) else 'N/A'
                )
        st.dataframe(mf_display, hide_index=True, use_container_width=True)
    except Exception:
        st.dataframe(mf.head(15), use_container_width=True)
else:
    st.info("Mutual fund holder data not available.")

st.caption("Source: yfinance · 24h cache")
