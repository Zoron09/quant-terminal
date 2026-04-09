import streamlit as st
import sys, os
import json
import time
import requests
import pandas as pd
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.sidebar import render_sidebar
from utils.sec_edgar import get_key_filings
from utils.finnhub_client import FINNHUB_KEY

st.set_page_config(page_title="News & Sentiment · Quant Terminal", page_icon="📰", layout="wide")

_css = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'styles', 'custom.css')
if os.path.exists(_css):
    with open(_css) as _f:
        st.markdown(f'<style>{_f.read()}</style>', unsafe_allow_html=True)

ALERTS_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'price_alerts.json')

DARK = dict(
    plot_bgcolor='#0E1117', paper_bgcolor='#0E1117',
    font=dict(color='#CCCCCC', family='Courier New'),
)


# ── Alert helpers ─────────────────────────────────────────────────────────────

def load_alerts() -> list:
    try:
        with open(ALERTS_FILE) as f:
            return json.load(f)
    except Exception:
        return []


def save_alerts(alerts: list):
    with open(ALERTS_FILE, 'w') as f:
        json.dump(alerts, f, indent=2)


def check_alerts(alerts: list, current_prices: dict) -> list:
    """Return list of triggered alert dicts."""
    triggered = []
    for a in alerts:
        if not a.get('active', True):
            continue
        ticker = a.get('ticker', '').upper()
        price  = current_prices.get(ticker)
        if price is None:
            continue
        cond  = a.get('condition', 'above')
        level = float(a.get('price', 0))
        if cond == 'above' and price >= level:
            triggered.append(a)
        elif cond == 'below' and price <= level:
            triggered.append(a)
    return triggered


# ── News fetchers ─────────────────────────────────────────────────────────────

def _time_ago(ts) -> str:
    """Convert a unix timestamp or datetime to a human-readable 'X ago' string."""
    try:
        if isinstance(ts, (int, float)):
            dt = datetime.utcfromtimestamp(ts)
        elif isinstance(ts, str):
            dt = datetime.fromisoformat(ts.replace('Z', ''))
        else:
            dt = ts
        diff = datetime.utcnow() - dt
        if diff.days >= 1:
            return f"{diff.days}d ago"
        h = diff.seconds // 3600
        if h >= 1:
            return f"{h}h ago"
        m = diff.seconds // 60
        return f"{m}m ago"
    except Exception:
        return ''


@st.cache_data(ttl=60, show_spinner=False)
def fetch_finnhub_news(ticker: str) -> list[dict]:
    """
    Finnhub /company-news — real-time, published within minutes.
    Returns last 7 days. Free tier: ~60 calls/min.
    """
    if not FINNHUB_KEY:
        return []
    clean  = ticker.upper().split('.')[0]
    today  = datetime.utcnow().strftime('%Y-%m-%d')
    week   = (datetime.utcnow() - timedelta(days=7)).strftime('%Y-%m-%d')
    try:
        r = requests.get(
            'https://finnhub.io/api/v1/company-news',
            params={'symbol': clean, 'from': week, 'to': today, 'token': FINNHUB_KEY},
            timeout=8,
        )
        r.raise_for_status()
        data = r.json()
    except Exception:
        return []

    items = []
    seen  = set()
    for art in data:
        headline = (art.get('headline') or '').strip()
        if not headline or headline in seen:
            continue
        seen.add(headline)
        items.append({
            'title':     headline,
            'summary':   (art.get('summary') or '').strip(),
            'source':    art.get('source', '') or '',
            'link':      art.get('url', '') or '',
            'published': _time_ago(art.get('datetime')),
            'image':     art.get('image', '') or '',
        })

    return items[:40]


@st.cache_data(ttl=60, show_spinner=False)
def fetch_alpaca_news(ticker: str) -> list[dict]:
    """
    Alpaca News API — real-time, requires Alpaca credentials.
    Endpoint: https://data.alpaca.markets/v1beta1/news
    """
    try:
        from utils.alpaca_client import ALPACA_KEY, ALPACA_SECRET, _HAS_ALPACA
        if not _HAS_ALPACA:
            return []
    except Exception:
        return []

    clean = ticker.upper().split('.')[0]
    try:
        r = requests.get(
            'https://data.alpaca.markets/v1beta1/news',
            params={
                'symbols':    clean,
                'limit':      40,
                'sort':       'desc',
                'include_content': 'false',
            },
            auth=(ALPACA_KEY, ALPACA_SECRET),
            timeout=8,
        )
        r.raise_for_status()
        data = r.json()
    except Exception:
        return []

    items = []
    seen  = set()
    for art in data.get('news', []):
        headline = (art.get('headline') or '').strip()
        if not headline or headline in seen:
            continue
        seen.add(headline)
        items.append({
            'title':     headline,
            'summary':   (art.get('summary') or '').strip(),
            'source':    art.get('source', '') or '',
            'link':      art.get('url', '') or '',
            'published': _time_ago(art.get('created_at') or art.get('updated_at')),
            'image':     '',
        })

    return items[:40]


def fetch_news(ticker: str) -> tuple[list[dict], str]:
    """
    Try Finnhub first (US and international), fall back to Alpaca.
    Returns (items, source_label).
    """
    items = fetch_finnhub_news(ticker)
    if items:
        return items, 'Finnhub'
    items = fetch_alpaca_news(ticker)
    if items:
        return items, 'Alpaca'
    return [], ''


# ── Render ────────────────────────────────────────────────────────────────────

ticker = render_sidebar()
st.markdown("## 📰 News & Sentiment")

if not ticker:
    st.info("Enter a ticker in the sidebar.")
    st.stop()

is_us = '.' not in ticker and not ticker.startswith('^')

# ── Price alert banner ────────────────────────────────────────────────────────
alerts = load_alerts()
ticker_alerts = [a for a in alerts if a.get('ticker', '').upper() == ticker.upper() and a.get('active', True)]
if ticker_alerts:
    # Try to get current price quickly
    try:
        import yfinance as yf
        fast_price = yf.Ticker(ticker).fast_info.get('lastPrice')
        if fast_price:
            triggered = check_alerts(ticker_alerts, {ticker.upper(): fast_price})
            for ta in triggered:
                cond  = 'above' if ta['condition'] == 'above' else 'below'
                level = ta['price']
                st.warning(
                    f"ALERT: {ticker} is now {'above' if cond == 'above' else 'below'} "
                    f"${level:.2f} — current price ${fast_price:.2f}",
                    icon="🔔"
                )
    except Exception:
        pass

# ── Sentiment fetchers ────────────────────────────────────────────────────────

@st.cache_data(ttl=1800, show_spinner=False)
def fetch_finnhub_sentiment(ticker: str) -> dict:
    """Finnhub social sentiment — bullish/bearish counts."""
    if not FINNHUB_KEY:
        return {}
    clean = ticker.upper().split('.')[0]
    today = datetime.utcnow().strftime('%Y-%m-%d')
    week  = (datetime.utcnow() - timedelta(days=7)).strftime('%Y-%m-%d')
    try:
        r = requests.get(
            'https://finnhub.io/api/v1/stock/social-sentiment',
            params={'symbol': clean, 'from': week, 'to': today, 'token': FINNHUB_KEY},
            timeout=8,
        )
        r.raise_for_status()
        data = r.json()
        reddit  = data.get('reddit',  [])
        twitter = data.get('twitter', [])
        def _agg(items):
            total = sum(i.get('mention', 0) for i in items)
            pos   = sum(i.get('positiveScore', 0) * i.get('mention', 0) for i in items)
            neg   = sum(i.get('negativeScore',  0) * i.get('mention', 0) for i in items)
            if total == 0:
                return None
            return {'mentions': total, 'bullish_pct': round(pos / total * 100, 1), 'bearish_pct': round(neg / total * 100, 1)}
        return {'reddit': _agg(reddit), 'twitter': _agg(twitter)}
    except Exception:
        return {}


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_stocktwits_sentiment(ticker: str) -> dict:
    """Stocktwits public API — message count, bullish %, bearish %."""
    clean = ticker.upper().split('.')[0]
    try:
        r = requests.get(
            f'https://api.stocktwits.com/api/2/streams/symbol/{clean}.json',
            timeout=8,
            headers={'User-Agent': 'QuantTerminal/1.0'},
        )
        r.raise_for_status()
        data = r.json()
        messages = data.get('messages', [])
        total    = len(messages)
        bullish  = sum(1 for m in messages if m.get('entities', {}).get('sentiment', {}).get('basic') == 'Bullish')
        bearish  = sum(1 for m in messages if m.get('entities', {}).get('sentiment', {}).get('basic') == 'Bearish')
        neutral  = total - bullish - bearish
        bull_pct = round(bullish / total * 100, 1) if total > 0 else 0
        bear_pct = round(bearish / total * 100, 1) if total > 0 else 0
        return {
            'total':      total,
            'bullish':    bullish,
            'bearish':    bearish,
            'neutral':    neutral,
            'bull_pct':   bull_pct,
            'bear_pct':   bear_pct,
        }
    except Exception:
        return {}


# ── Tabs ──────────────────────────────────────────────────────────────────────
tab_news, tab_filings, tab_alerts = st.tabs(["News Feed", "SEC Filings", "Price Alerts"])


# ════════════════════════════════════════════════════════════════════════════
# TAB 1: NEWS FEED
# ════════════════════════════════════════════════════════════════════════════
with tab_news:
    st.markdown('<div class="section-title">Latest News</div>', unsafe_allow_html=True)

    # ── Social Sentiment gauges ───────────────────────────────────────────
    if is_us:
        scol1, scol2 = st.columns(2)

        with scol1:
            fh_sent = fetch_finnhub_sentiment(ticker)
            parts   = []
            for src, label in [('reddit', 'Reddit'), ('twitter', 'Twitter/X')]:
                d = fh_sent.get(src)
                if d:
                    bull = d['bullish_pct']
                    bear = d['bearish_pct']
                    bull_w = max(1, int(bull * 1.2))
                    bear_w = max(1, int(bear * 1.2))
                    parts.append(f"""
<div style="margin-bottom:8px;">
  <div style="color:#888;font-size:11px;font-family:monospace;">{label} · {d['mentions']:,} mentions</div>
  <div style="display:flex;align-items:center;gap:6px;margin-top:3px;">
    <div style="background:#00FF41;height:10px;width:{bull_w}px;border-radius:3px;"></div>
    <span style="color:#00FF41;font-size:12px;font-family:monospace;">{bull:.0f}%</span>
    <div style="background:#FF4444;height:10px;width:{bear_w}px;border-radius:3px;"></div>
    <span style="color:#FF4444;font-size:12px;font-family:monospace;">{bear:.0f}%</span>
  </div>
</div>""")
            if parts:
                scol1.markdown(f"""
<div style="background:#161B22;border:1px solid #333;border-radius:6px;padding:12px 16px;">
  <div style="color:#888;font-size:10px;font-family:monospace;letter-spacing:1px;margin-bottom:8px;">
    FINNHUB SENTIMENT (7D) &nbsp;·&nbsp; 🟢 BULL &nbsp; 🔴 BEAR
  </div>
  {''.join(parts)}
</div>""", unsafe_allow_html=True)
            elif FINNHUB_KEY:
                scol1.caption("Finnhub: no sentiment data for this symbol.")
            else:
                scol1.caption("Finnhub API key not set — sentiment unavailable.")

        with scol2:
            st_sent = fetch_stocktwits_sentiment(ticker)
            if st_sent and st_sent.get('total', 0) > 0:
                bull_p = st_sent['bull_pct']
                bear_p = st_sent['bear_pct']
                neut_p = round(100 - bull_p - bear_p, 1)
                overall_color = '#00FF41' if bull_p > bear_p else ('#FF4444' if bear_p > bull_p else '#888888')
                overall_label = 'BULLISH' if bull_p > bear_p else ('BEARISH' if bear_p > bull_p else 'NEUTRAL')
                bull_w = max(1, int(bull_p * 1.2))
                bear_w = max(1, int(bear_p * 1.2))
                scol2.markdown(f"""
<div style="background:#161B22;border:1px solid #333;border-radius:6px;padding:12px 16px;">
  <div style="color:#888;font-size:10px;font-family:monospace;letter-spacing:1px;margin-bottom:8px;">
    STOCKTWITS SENTIMENT (LATEST 30 MSG)
  </div>
  <div style="color:{overall_color};font-size:18px;font-weight:bold;font-family:monospace;">
    {overall_label}
  </div>
  <div style="display:flex;align-items:center;gap:6px;margin-top:6px;">
    <div style="background:#00FF41;height:10px;width:{bull_w}px;border-radius:3px;"></div>
    <span style="color:#00FF41;font-size:12px;font-family:monospace;">🐂 {bull_p:.0f}%</span>
    &nbsp;
    <div style="background:#FF4444;height:10px;width:{bear_w}px;border-radius:3px;"></div>
    <span style="color:#FF4444;font-size:12px;font-family:monospace;">🐻 {bear_p:.0f}%</span>
  </div>
  <div style="color:#888;font-size:11px;font-family:monospace;margin-top:4px;">
    {st_sent['total']} msgs · {st_sent['bullish']} bull · {st_sent['bearish']} bear · {st_sent['neutral']} neutral
  </div>
</div>""", unsafe_allow_html=True)
            elif st_sent is not None:
                scol2.caption("Stocktwits: no sentiment data for this symbol.")
            else:
                scol2.caption("Stocktwits: unavailable.")

        st.markdown("---")

    # Auto-refresh every 60 s
    AUTO_REFRESH_S = 60
    now_ts = time.time()
    if 'news_last_refresh' not in st.session_state or \
       st.session_state.get('news_ticker') != ticker:
        st.session_state['news_last_refresh'] = now_ts
        st.session_state['news_ticker']        = ticker

    col_refresh, col_ts = st.columns([1, 4])
    with col_refresh:
        if st.button("Refresh Now", key="btn_refresh_news"):
            fetch_finnhub_news.clear()
            fetch_alpaca_news.clear()
            st.session_state['news_last_refresh'] = time.time()
            st.rerun()

    with st.spinner(f"Loading news for {ticker}…"):
        news_items, news_source = fetch_news(ticker)

    elapsed   = time.time() - st.session_state['news_last_refresh']
    remaining = max(0, AUTO_REFRESH_S - int(elapsed))

    if not news_items:
        st.info(
            "No news returned. Finnhub company news requires a US common stock ticker "
            "(e.g. AAPL, MSFT). Indian stocks and indices may return no results."
        )
    else:
        col_ts.caption(
            f"Source: {news_source} · {len(news_items)} articles · "
            f"Updated: {datetime.now().strftime('%H:%M:%S')} · "
            f"Refresh in {remaining}s"
        )

        for item in news_items:
            title     = item.get('title', '')
            summary   = item.get('summary', '')
            source    = item.get('source', '')
            published = item.get('published', '')
            link      = item.get('link', '')

            # Truncate long summaries
            if len(summary) > 280:
                summary = summary[:277] + '…'

            summary_html = (
                f'<div style="color:#AAAAAA;font-size:12px;margin-top:5px;'
                f'line-height:1.5;">{summary}</div>'
                if summary else ''
            )

            st.markdown(f"""
<div style="border:1px solid #1e2530;border-radius:6px;padding:12px 16px;
            margin-bottom:10px;background:#0d1117;">
  <div style="margin-bottom:3px;">
    <a href="{link}" target="_blank"
       style="color:#E0E0E0;font-size:14px;font-weight:500;text-decoration:none;
              line-height:1.4;">
      {title}
    </a>
  </div>
  {summary_html}
  <div style="color:#555;font-size:11px;font-family:monospace;margin-top:6px;">
    <span style="color:#00BFFF;">{source}</span>
    &nbsp;·&nbsp; {published}
  </div>
</div>""", unsafe_allow_html=True)

    # Trigger rerun after AUTO_REFRESH_S seconds have elapsed
    if remaining == 0:
        st.session_state['news_last_refresh'] = time.time()
        fetch_finnhub_news.clear()
        fetch_alpaca_news.clear()
        st.rerun()

    st.caption(f"Auto-refreshes every {AUTO_REFRESH_S}s · Finnhub primary · Alpaca fallback")


# ════════════════════════════════════════════════════════════════════════════
# TAB 2: SEC FILINGS (US only)
# ════════════════════════════════════════════════════════════════════════════
with tab_filings:
    st.markdown('<div class="section-title">SEC Filings</div>', unsafe_allow_html=True)

    if not is_us:
        st.info("SEC EDGAR filings are only available for US-listed stocks.")
    else:
        with st.spinner("Loading SEC filings…"):
            filings_df = get_key_filings(ticker)

        if filings_df is None or filings_df.empty:
            st.info("No SEC filings found. The ticker may not be registered with EDGAR, or it's a very new listing.")
        else:
            # Form-type filter
            available_forms = sorted(filings_df['form'].unique().tolist())
            selected_forms  = st.multiselect(
                "Filter by form type",
                options=available_forms,
                default=available_forms,
                key="filings_filter",
            )
            filtered = filings_df[filings_df['form'].isin(selected_forms)] if selected_forms else filings_df

            FORM_COLORS = {
                '10-K':  '#00FF41',
                '10-Q':  '#00BFFF',
                '8-K':   '#FFD700',
                '4':     '#FF9944',
                '4/A':   '#FF9944',
                'DEF 14A': '#AA88FF',
            }
            FORM_DESC = {
                '10-K':  'Annual Report',
                '10-Q':  'Quarterly Report',
                '8-K':   'Current Report',
                '4':     'Insider Transaction',
                '4/A':   'Insider Transaction (Amended)',
                'DEF 14A': 'Proxy Statement',
            }

            for _, row in filtered.head(40).iterrows():
                form      = str(row.get('form', ''))
                date      = str(row.get('filingDate', ''))[:10]
                report_dt = str(row.get('reportDate', ''))[:10]
                url       = row.get('url', '')
                desc      = FORM_DESC.get(form, form)
                color     = FORM_COLORS.get(form, '#888888')

                st.markdown(f"""
<div style="border-left:3px solid {color};padding:8px 14px;margin-bottom:6px;
            background:#0d1117;border-radius:0 6px 6px 0;">
  <span style="color:{color};font-weight:bold;font-family:monospace;
               font-size:12px;min-width:60px;display:inline-block;">{form}</span>
  <span style="color:#CCCCCC;font-size:13px;margin-left:10px;">{desc}</span>
  <span style="color:#888;font-size:11px;margin-left:10px;font-family:monospace;">{date}</span>
  {'<span style="color:#888;font-size:11px;margin-left:6px;font-family:monospace;">· Report: ' + report_dt + '</span>' if report_dt and report_dt != 'NaT' else ''}
  {'<a href="' + url + '" target="_blank" style="color:#00BFFF;font-size:11px;margin-left:10px;">View →</a>' if url else ''}
</div>""", unsafe_allow_html=True)

        st.caption("Source: SEC EDGAR · 1h cache")


# ════════════════════════════════════════════════════════════════════════════
# TAB 3: PRICE ALERTS
# ════════════════════════════════════════════════════════════════════════════
with tab_alerts:
    st.markdown('<div class="section-title">Price Alerts</div>', unsafe_allow_html=True)

    alerts = load_alerts()

    # ── Add new alert ─────────────────────────────────────────────────────
    with st.expander("Add New Alert", expanded=True):
        ac1, ac2, ac3, ac4 = st.columns([2, 2, 2, 1])
        with ac1:
            alert_ticker = st.text_input("Ticker", value=ticker.upper(), key="alert_ticker").upper()
        with ac2:
            alert_cond = st.selectbox("Condition", ["above", "below"], key="alert_cond")
        with ac3:
            alert_price = st.number_input("Price ($)", min_value=0.01, value=100.0,
                                          step=0.5, format="%.2f", key="alert_price")
        with ac4:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("Add Alert", key="btn_add_alert"):
                new_alert = {
                    'ticker':    alert_ticker,
                    'condition': alert_cond,
                    'price':     alert_price,
                    'created':   datetime.now().strftime('%Y-%m-%d %H:%M'),
                    'active':    True,
                }
                alerts.append(new_alert)
                save_alerts(alerts)
                st.success(f"Alert added: {alert_ticker} {alert_cond} ${alert_price:.2f}")
                st.rerun()

    # ── Active alerts table ───────────────────────────────────────────────
    active_alerts = [a for a in alerts if a.get('active', True)]

    if not active_alerts:
        st.info("No active alerts. Add one above.")
    else:
        st.markdown(f"**{len(active_alerts)} active alert(s)**")

        # Get current prices for all alert tickers
        alert_tickers = list({a['ticker'].upper() for a in active_alerts})
        current_prices = {}
        try:
            import yfinance as yf
            for at in alert_tickers:
                try:
                    fi = yf.Ticker(at).fast_info
                    p  = fi.get('lastPrice') or fi.get('regularMarketPrice')
                    if p:
                        current_prices[at] = float(p)
                except Exception:
                    pass
        except Exception:
            pass

        for i, a in enumerate(alerts):
            if not a.get('active', True):
                continue
            at    = a.get('ticker', '').upper()
            cond  = a.get('condition', 'above')
            level = float(a.get('price', 0))
            cur   = current_prices.get(at)
            cur_str = f"${cur:.2f}" if cur else 'N/A'
            created = a.get('created', '')

            # Check if triggered
            triggered_flag = False
            if cur:
                if cond == 'above' and cur >= level:
                    triggered_flag = True
                elif cond == 'below' and cur <= level:
                    triggered_flag = True

            cond_color = '#00FF41' if cond == 'above' else '#FF4444'
            border_color = '#FFD700' if triggered_flag else '#333333'
            bg_color     = '#1a1500' if triggered_flag else '#0d1117'

            row_c1, row_c2 = st.columns([5, 1])
            with row_c1:
                st.markdown(f"""
<div style="border:1px solid {border_color};border-radius:6px;padding:8px 14px;
            background:{bg_color};">
  <span style="font-family:monospace;color:#00BFFF;font-weight:bold;">{at}</span>
  <span style="color:#888;margin:0 8px;">→</span>
  <span style="color:{cond_color};font-family:monospace;">{cond.upper()} ${level:.2f}</span>
  <span style="color:#888;margin:0 10px;font-size:11px;">Current: {cur_str}</span>
  {'<span style="color:#FFD700;font-size:12px;font-weight:bold;">🔔 TRIGGERED</span>' if triggered_flag else ''}
  <span style="color:#555;font-size:10px;float:right;font-family:monospace;">Added: {created}</span>
</div>""", unsafe_allow_html=True)

            with row_c2:
                if st.button("Delete", key=f"del_alert_{i}"):
                    alerts[i]['active'] = False
                    save_alerts(alerts)
                    st.rerun()

    # ── Triggered history / inactive ─────────────────────────────────────
    inactive = [a for a in alerts if not a.get('active', True)]
    if inactive:
        with st.expander(f"Dismissed alerts ({len(inactive)})"):
            for a in inactive[-20:]:
                st.caption(
                    f"{a.get('ticker','')} {a.get('condition','')} "
                    f"${a.get('price',0):.2f} — added {a.get('created','')}"
                )
            if st.button("Clear all dismissed", key="btn_clear_inactive"):
                alerts = [a for a in alerts if a.get('active', True)]
                save_alerts(alerts)
                st.rerun()

    st.caption("Alerts are checked on each page load. No server-side push notifications.")
