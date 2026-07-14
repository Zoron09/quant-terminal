from fastapi import FastAPI, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
import json
import io
import sys
import os
import yfinance as yf
from functools import lru_cache
from datetime import datetime
from pathlib import Path
import time

# tools/ — not served by StaticFiles, unlike frontend/ (mounted at /static below)
TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from utils.code33_engine import get_code33_data, CACHE_VERSION

TICKER_CACHE = {}
CACHE_TTL = 300  # 5 minutes

def evict_cache():
    now = time.time()
    expired = [k for k, v in list(TICKER_CACHE.items()) if now - v[1] > CACHE_TTL]
    for k in expired: TICKER_CACHE.pop(k, None)


app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve HTML files
app.mount("/static", StaticFiles(directory="frontend"), name="static")

@app.get("/")
async def root():
    return FileResponse("frontend/index.html")

@app.get("/screener")
async def screener():
    return FileResponse("frontend/index.html")

@app.get("/analysis")
async def analysis():
    return FileResponse("frontend/index.html")

@app.get("/journal")
async def journal():
    return FileResponse("frontend/index.html")

@app.get("/api/journal/wealthsimple-latest")
async def wealthsimple_latest():
    """Read-only. Serves whatever tools/wealthsimple_export.py has already written
    to disk. Does NOT trigger the script and never touches Wealthsimple credentials
    or session.json — login/2FA stays a manual terminal run of that script."""
    trades_file = TOOLS_DIR / "ws_import_latest.json"
    review_file = TOOLS_DIR / "needs_review.json"

    trades = None
    if trades_file.exists():
        try:
            trades = json.loads(trades_file.read_text())
        except Exception:
            trades = None

    needs_review = None
    if review_file.exists():
        try:
            needs_review = json.loads(review_file.read_text())
        except Exception:
            needs_review = None

    if trades is None and needs_review is None:
        return JSONResponse(
            {'error': 'No Wealthsimple export found. Run tools/wealthsimple_export.py first.'},
            status_code=404,
        )

    return JSONResponse({'trades': trades, 'needs_review': needs_review})

@app.post("/api/scan")
async def scan(file: UploadFile = File(...)):
    contents = await file.read()
    df = pd.read_csv(io.BytesIO(contents))
    
    sector_map = {}
    mcap_map = {}
    
    if 'Symbol' in df.columns and 'Sector' in df.columns:
        sector_map = dict(zip(
            df['Symbol'].str.upper(),
            df['Sector'].fillna('Unknown')
        ))
    
    company_map = {}
    if 'Symbol' in df.columns and 'Description' in df.columns:
        company_map = dict(zip(
            df['Symbol'].str.upper(),
            df['Description'].fillna('')
        ))

    if 'Symbol' in df.columns and 'Market capitalization' in df.columns:
        def fmt_mcap(v):
            try:
                v = float(v)
                if v >= 1e12: return f"${v/1e12:.1f}T"
                if v >= 1e9:  return f"${v/1e9:.1f}B"
                if v >= 1e6:  return f"${v/1e6:.1f}M"
                return f"${v:,.0f}"
            except: return "N/A"
        mcap_map = {
            str(row['Symbol']).upper(): fmt_mcap(row['Market capitalization'])
            for _, row in df.iterrows()
        }

    import time
    start = time.time()
    
    tickers = df['Symbol'].str.upper().tolist() \
        if 'Symbol' in df.columns else []

    print(f"[SCAN] START - file received: {file.filename}")
    print(f"[SCAN] tickers count: {len(tickers)}")
    print(f"[SCAN] first 5 tickers: {tickers[:5]}")

    import concurrent.futures

    winners = []
    insufficient = 0
    crashes = 0
    count_green = 0
    count_yellow = 0
    count_red = 0
    total = len(tickers)

    def safe3(lst):
        if not lst: return [0, 0, 0]
        lst = [x for x in lst if x is not None]
        if len(lst) < 3:
            lst = ([0] * (3 - len(lst))) + lst
        return [round(x, 1) for x in lst[-3:]]

    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        future_to_ticker = {executor.submit(get_code33_data, t, CACHE_VERSION): t for t in tickers}
        for future in concurrent.futures.as_completed(future_to_ticker):
            ticker = future_to_ticker[future]
            try:
                data = future.result(timeout=15)
                if not data:
                    insufficient += 1
                    continue
                
                status = data.get('status', 'insufficient')
                if status == 'green': count_green += 1
                elif status == 'yellow': count_yellow += 1
                elif status == 'red': count_red += 1
                elif status == 'insufficient': insufficient += 1

                if status not in ('green', 'yellow'):
                    continue

                winners.append({
                    'ticker':  ticker,
                    'company': company_map.get(ticker, '') or data.get('company_name', ticker),
                    'sector':  sector_map.get(ticker, 'Unknown'),
                    'mcap':    mcap_map.get(ticker, 'N/A'),
                    'eps':     safe3(data.get('eps_yoy', [])),
                    'rev':     safe3(data.get('rev_yoy', [])),
                    'margin':  safe3(data.get('npm', [])),
                    'status':  status,
                })
            except concurrent.futures.TimeoutError:
                print(f"[SCAN ERROR] {ticker}: Timeout")
                insufficient += 1
                crashes += 1
            except Exception as e:
                print(f"[SCAN ERROR] {ticker}: {e}")
                insufficient += 1
                crashes += 1

    print(f"[SCAN] COMPLETE - green: {count_green}, yellow: {count_yellow}, red: {count_red}, insufficient: {insufficient}, crashes: {crashes}")
    print(f"[SCAN] first winner: {winners[0] if winners else 'none'}")
    print(f"[SCAN] duration: {time.time()-start:.1f}s")
    return JSONResponse({
        'winners': winners,
        'meta': {
            'total': total,
            'passed': len(winners),
            'insufficient': insufficient,
        }
    })

@app.get("/api/ticker/{ticker}")
async def ticker_data(ticker: str):
    t = ticker.upper()
    now = time.time()
    evict_cache()
    
    if t in TICKER_CACHE:
        cached, ts = TICKER_CACHE[t]
        if now - ts < CACHE_TTL:
            return JSONResponse(cached)
    
    try:
        data = get_code33_data(t, CACHE_VERSION)
        if not data:
            return JSONResponse({'error': 'No data'}, 
                                status_code=404)
        
        data['status'] = data.get('status', 'insufficient')
        

        tk = yf.Ticker(t)
        info = tk.fast_info
        full_info = tk.info or {}
        data['price'] = getattr(info, 'last_price', 0)
        data['company_name'] = full_info.get(
            'shortName', t)
            
        data['change'] = getattr(info, 'last_price', 0) - \
          getattr(info, 'regular_market_previous_close', 
          getattr(info, 'previous_close', 0))
          
        data['change_pct'] = (data['change'] / 
          getattr(info, 'regular_market_previous_close',
          getattr(info, 'previous_close', 1))) * 100
        
        mc = getattr(info, 'market_cap', None)
        if mc is None:
            mc = full_info.get('marketCap', 0)
        def fmt_mcap(v):
            try:
                v = float(v)
                if v >= 1e12: return f"{v/1e12:.1f}T"
                if v >= 1e9:  return f"{v/1e9:.1f}B"
                if v >= 1e6:  return f"{v/1e6:.1f}M"
                return f"{v:,.0f}"
            except: return "N/A"
        data['market_cap_fmt'] = fmt_mcap(mc)
        
        data['pe_ratio'] = full_info.get(
            'trailingPE', 'N/A')

        data['week52_high'] = getattr(
            info, 'year_high', 0)
        data['week52_low'] = getattr(
            info, 'year_low', 0)
        data['avg_volume'] = getattr(
            info, 'three_month_average_volume', 0)
        
        import logging
        logging.warning(f"DATA KEYS: {list(data.keys())}")
        
        TICKER_CACHE[t] = (data, now)
        return JSONResponse(data)
    except Exception as e:
        return JSONResponse({'error': str(e)}, 
                            status_code=500)

@app.get("/api/chart/{ticker}")
async def chart_data(ticker: str, period: str = "3mo", interval: str = "1d"):
    t = ticker.upper()
    cache_key = f"chart_{t}_{period}_{interval}"
    now = time.time()
    evict_cache()
    
    if cache_key in TICKER_CACHE:
        cached, ts = TICKER_CACHE[cache_key]
        if now - ts < 300:
            return JSONResponse(cached)
    
    try:
        hist = yf.Ticker(t).history(period=period, interval=interval)
        if hist.empty:
            return JSONResponse({'error': 'No data'}, 
                                status_code=404)
        
        prices = [
            {
                'date': str(idx.date()),
                'close': round(float(row['Close']), 2)
            }
            for idx, row in hist.iterrows()
        ]
        
        result = {'ticker': t, 'period': period, 
                  'prices': prices}
        TICKER_CACHE[cache_key] = (result, now)
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({'error': str(e)}, 
                            status_code=500)

@app.get("/api/financials/{ticker}")
async def financials(ticker: str):
    import numpy as np
    t = ticker.upper()
    cache_key = f"fin_{t}"
    now = time.time()
    evict_cache()
    if cache_key in TICKER_CACHE:
        cached, ts = TICKER_CACHE[cache_key]
        if now - ts < 600:
            return JSONResponse(cached)
    try:
        tk = yf.Ticker(t)
        def df_to_dict(df):
            if df is None or df.empty:
                return {}
            df = df.copy()
            result = {}
            for idx in df.index:
                row = {}
                for col in df.columns:
                    val = df.loc[idx, col]
                    if hasattr(val, 'item'):
                        val = val.item()
                    if val is None or (
                        isinstance(val, float) and 
                        np.isnan(val)):
                        val = None
                    row[str(col.date() if hasattr(
                        col, 'date') else col)] = val
                result[str(idx)] = row
            return result
        
        def fmt_val(v):
            if v is None: return None
            try:
                v = float(v)
                if abs(v) >= 1e9:
                    return f"{v/1e9:.2f}B"
                if abs(v) >= 1e6:
                    return f"{v/1e6:.0f}M"
                return f"{v:.2f}"
            except: return None
        
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as executor:
            f_inc = executor.submit(lambda: tk.quarterly_income_stmt)
            f_bal = executor.submit(lambda: tk.quarterly_balance_sheet)
            f_cf  = executor.submit(lambda: tk.quarterly_cashflow)
            f_info = executor.submit(lambda: tk.info)
            f_cal = executor.submit(lambda: tk.calendar)

            inc = f_inc.result()
            bal = f_bal.result()
            cf  = f_cf.result()
            info = f_info.result() or {}
            cal_data = f_cal.result()
        
        # --- Build earnings list from secfsdstools + yfinance merge ---
        earnings_list = []

        try:
            yf_df = inc  # already fetched above

            # EPS from yfinance — up to 5 quarters
            yf_eps = {}
            if yf_df is not None and not yf_df.empty:
                for col in yf_df.columns:
                    eps_val = None
                    for field in ['Diluted EPS', 'DilutedEPS', 'Basic EPS', 'BasicEPS']:
                        if field in yf_df.index:
                            v = yf_df.loc[field, col]
                            if v is not None and str(v) != 'nan':
                                try:
                                    eps_val = float(v)
                                    break
                                except (TypeError, ValueError):
                                    pass
                    date_str = col.strftime('%Y-%m-%d') if hasattr(col, 'strftime') else str(col)[:10]
                    yf_eps[date_str] = eps_val

            # Revenue + net margin from get_code33_data() — date-aware gap
            # detection (real filed dates, correct edgartools coverage for
            # the newest quarter). n_quarters=12: 8 display quarters + 4
            # buffer for this endpoint's own index-based margin/EPS YoY below.
            c33_rev_by_date = {}
            c33_rev_yoy_by_date = {}
            c33_margin_by_date = {}
            try:
                c33 = get_code33_data(t, n_quarters=12)
                rev_dates = c33.get('rev_end_dates') or []
                rev_vals = c33.get('rev') or []
                rev_yoy_vals = c33.get('rev_yoy') or []
                for d, v in zip(rev_dates, rev_vals):
                    c33_rev_by_date[d] = v
                # rev_yoy is only positionally aligned with rev_end_dates when
                # every target quarter has a value — guard rather than assume.
                if len(rev_yoy_vals) == len(rev_dates):
                    for d, v in zip(rev_dates, rev_yoy_vals):
                        c33_rev_yoy_by_date[d] = v
                npm_dates = c33.get('npm_ends') or []
                npm_vals = c33.get('npm') or []
                for d, v in zip(npm_dates, npm_vals):
                    c33_margin_by_date[d] = v
            except Exception as e:
                print(f"[financials] get_code33_data failed: {e}")

            # get_code33_data's real filed dates and yfinance's own
            # calendar-normalized quarter dates rarely match exactly (e.g.
            # NVDA's real 2026-04-26 vs yfinance's 2026-04-30) — match by
            # proximity, not exact string equality, or the same quarter
            # splits into two incomplete rows instead of one complete one.
            def _closest_date(target_str, candidates, tolerance_days=10):
                try:
                    target = datetime.strptime(target_str, '%Y-%m-%d').date()
                except Exception:
                    return None
                best, best_diff = None, tolerance_days + 1
                for c in candidates:
                    try:
                        diff = abs((datetime.strptime(c, '%Y-%m-%d').date() - target).days)
                    except Exception:
                        continue
                    if diff <= tolerance_days and diff < best_diff:
                        best, best_diff = c, diff
                return best

            # Collect all unique dates: c33's real filed dates are
            # authoritative; only pull in a yfinance date if nothing in c33
            # is close to it (keeps any EPS-only history c33 doesn't cover).
            c33_dates = set(c33_rev_by_date.keys()) | set(c33_margin_by_date.keys())
            eps_keys = list(yf_eps.keys())
            unmatched_eps_dates = {
                ek for ek in eps_keys if _closest_date(ek, c33_dates) is None
            }
            all_dates = sorted(c33_dates | unmatched_eps_dates, reverse=True)[:12]

            # Build merged quarters
            raw_quarters = []
            for d in all_dates:
                rev = c33_rev_by_date.get(d)
                margin = c33_margin_by_date.get(d)
                eps_key = _closest_date(d, eps_keys)
                eps = yf_eps.get(eps_key) if eps_key else None
                raw_quarters.append({
                    'date': d,
                    'revenue': rev,
                    'rev_yoy': c33_rev_yoy_by_date.get(d),
                    'net_margin': margin,
                    'net_margin_yoy': None,
                    'eps': eps,
                    'eps_yoy': None,
                })

            # Calculate YoY fields (compare index i vs i+4) — margin/EPS only.
            # Revenue YoY comes pre-computed from get_code33_data above
            # (fiscal-period-matched, not this naive index lookback).
            for i, q in enumerate(raw_quarters):
                if i + 4 < len(raw_quarters):
                    prev_m = raw_quarters[i+4].get('net_margin')
                    curr_m = q.get('net_margin')
                    if curr_m is not None and prev_m is not None:
                        q['net_margin_yoy'] = curr_m - prev_m

                    prev_eps = raw_quarters[i+4].get('eps')
                    curr_eps = q.get('eps')
                    if curr_eps is not None and prev_eps is not None and prev_eps != 0:
                        q['eps_yoy'] = (curr_eps - prev_eps) / abs(prev_eps) * 100

            earnings_list = raw_quarters

        except Exception as e:
            print(f"[financials] earnings build failed: {e}")
            earnings_list = []

        # First 8 for display — rest only needed for YoY calculation
        earnings_list = earnings_list[:8]

        next_earnings = None
        try:
            cal = cal_data
            if isinstance(cal, dict) and 'Earnings Date' in cal:
                ed = cal['Earnings Date']
                if isinstance(ed, list) and len(ed) > 0:
                    next_earnings = str(ed[0])
            elif hasattr(cal, 'iloc') and 'Earnings Date' in cal.index:
                val = cal.loc['Earnings Date']
                if hasattr(val, 'iloc'): val = val.iloc[0]
                next_earnings = str(val.date() if hasattr(val, 'date') else val).split(' ')[0]
        except: pass
        
        result = {
            'balance_sheet': df_to_dict(bal),
            'cash_flow': df_to_dict(cf),
            'valuation': {
                'P/E ratio': info.get('trailingPE'),
                'Forward P/E': info.get('forwardPE'),
                'P/S ratio': info.get('priceToSalesTrailing12Months'),
                'P/B ratio': info.get('priceToBook'),
                'EV/EBITDA': info.get('enterpriseToEbitda'),
                'EV/Revenue': info.get('enterpriseToRevenue'),
                'Debt/Equity': info.get('debtToEquity'),
                'ROE': info.get('returnOnEquity'),
                'ROA': info.get('returnOnAssets'),
                'Profit margin': info.get('profitMargins'),
            },
            'earnings': earnings_list,
            'next_earnings': next_earnings
        }
        TICKER_CACHE[cache_key] = (result, now)
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({'error': str(e)})

@app.get("/api/news/{ticker}")
async def news(ticker: str):
    t = ticker.upper()
    cache_key = f"news_{t}"
    now = time.time()
    evict_cache()
    if cache_key in TICKER_CACHE:
        cached, ts = TICKER_CACHE[cache_key]
        if now - ts < 120:
            return JSONResponse(cached)

    items = []
    seen_titles = set()

    # Source 1: SeekingAlpha via FinNews — fastest (0.42s), ticker-specific, analyst quality
    try:
        import FinNews as fn
        sa = fn.SeekingAlpha(topics=[f'${t}'])
        sa_news = sa.get_news() or []
        for a in sa_news[:15]:
            title = a.get('title', '').strip()
            if not title or title in seen_titles:
                continue
            seen_titles.add(title)
            pub = a.get('published', '')
            items.append({
                'title': title,
                'source': 'Seeking Alpha',
                'url': a.get('link', '') or a.get('url', ''),
                'time': _parse_rfc2822(pub) if isinstance(pub, str) else (int(pub) if isinstance(pub, (int, float)) and pub > 0 else 0),
                'ts': _parse_rfc2822(pub),
            })
    except Exception as e:
        print(f"[news] SeekingAlpha failed: {e}")

    # Source 2: tradingview-scraper — ticker-specific, Dow Jones/Barron's/MarketWatch
    try:
        from tradingview_scraper.symbols.news import NewsScraper
        ns = NewsScraper()
        articles = ns.scrape_headlines(symbol=t, exchange='NASDAQ', sort='latest')
        if not isinstance(articles, list):
            articles = articles.get('data', [])
        for a in articles[:15]:
            title = a.get('title', '').strip()
            if not title or title in seen_titles:
                continue
            seen_titles.add(title)
            url = a.get('link', '')
            if not url and a.get('storyPath'):
                url = 'https://www.tradingview.com' + a['storyPath']
            pub = a.get('published', 0)
            items.append({
                'title': title,
                'source': a.get('source', a.get('provider', '')),
                'url': url,
                'time': _parse_rfc2822(pub) if isinstance(pub, str) else (int(pub) if isinstance(pub, (int, float)) and pub > 0 else 0),
                'ts': pub if isinstance(pub, (int, float)) else 0,
            })
    except Exception as e:
        print(f"[news] tradingview-scraper failed: {e}")

    # Source 3: yfinance fallback — only if both above return nothing
    if not items:
        try:
            tk = yf.Ticker(t)
            for n in (tk.news or [])[:12]:
                c = n.get('content', {})
                title = (c.get('title', '') or n.get('title', '')).strip()
                if not title or title in seen_titles:
                    continue
                seen_titles.add(title)
                pub = c.get('pubDate', '') or n.get('providerPublishTime', 0)
                items.append({
                    'title': title,
                    'source': c.get('provider', {}).get('displayName', '') or n.get('publisher', ''),
                    'url': c.get('canonicalUrl', {}).get('url', '') or n.get('link', ''),
                    'time': _parse_rfc2822(pub) if isinstance(pub, str) else (int(pub) if isinstance(pub, (int, float)) and pub > 0 else 0),
                    'ts': pub if isinstance(pub, (int, float)) else 0,
                })
        except Exception as e:
            print(f"[news] yfinance fallback failed: {e}")

    # Sort all items newest first
    items.sort(key=lambda x: x.get('ts', 0), reverse=True)

    # Strip internal ts field before returning
    result = {
        'news': [
            {'title': i['title'], 'source': i['source'], 'url': i['url'], 'time': i['ts']}
            for i in items
        ]
    }
    TICKER_CACHE[cache_key] = (result, now)
    return JSONResponse(result)


def _fmt_news_time(val):
    try:
        from datetime import datetime
        if isinstance(val, (int, float)) and val > 0:
            dt = datetime.utcfromtimestamp(val)
        elif isinstance(val, str) and val:
            import email.utils
            parsed = email.utils.parsedate_to_datetime(val)
            dt = parsed.replace(tzinfo=None)
        else:
            return ''
        diff = datetime.utcnow() - dt
        mins = int(diff.total_seconds() / 60)
        if mins < 0: return 'just now'
        if mins < 60: return f"{mins}m ago"
        if mins < 1440: return f"{mins//60}h ago"
        return f"{mins//1440}d ago"
    except:
        return ''


def _parse_rfc2822(val):
    try:
        import email.utils
        parsed = email.utils.parsedate_to_datetime(val)
        return int(parsed.timestamp())
    except:
        return 0


@app.get("/api/ownership/{ticker}")
async def ownership(ticker: str):
    from datetime import datetime
    def fmt_date(d):
        try:
            if isinstance(d, str):
                dt = datetime.strptime(d.split(' ')[0], '%Y-%m-%d')
            else:
                dt = pd.Timestamp(d).to_pydatetime()
            return dt.strftime('%b %d')
        except:
            return str(d)

    try:
        t = yf.Ticker(ticker.upper())
        holders = t.institutional_holders
        insiders = t.insider_transactions
        
        inst_list = []
        if holders is not None and not holders.empty:
            for _, row in holders.head(5).iterrows():
                pct = float(row.get('pctHeld', 
                      row.get('% Out', 0))) * 100
                inst_list.append({
                    'name': str(row.get('Holder', 
                            row.get('Name', ''))),
                    'pct': round(pct, 1)
                })
        
        insider_list = []
        if insiders is not None and not insiders.empty:
            for _, row in insiders.head(3).iterrows():
                val = float(row.get('Value', 0))
                insider_list.append({
                    'name': str(row.get('Insider', '')),
                    'role': str(row.get('Relationship', '')),
                    'date': fmt_date(row.get('Start Date', '')),
                    'value': val,
                    'type': 'BUY' if val > 0 else 'SELL'
                })
        
        return JSONResponse({
            'institutional': inst_list,
            'insiders': insider_list
        })
    except Exception as e:
        return JSONResponse({
            'institutional': [],
            'insiders': []
        })

@app.get("/api/peers/{ticker}")
async def peers(ticker: str):
    from utils.code33_engine import get_code33_data, CACHE_VERSION
    try:
        info = yf.Ticker(ticker.upper()).info
        # Get peers from recommendationKey or sector peers
        # Use analyst recommendations to find peer tickers
        recs = yf.Ticker(ticker.upper()).recommendations
        # Get sector and find similar companies
        sector = info.get('sector', '')
        
        # Hardcode peers per sector as fallback
        SECTOR_PEERS = {
            'Technology': ['NVDA','MSFT','AAPL','GOOGL','META'],
            'Health Technology': ['LLY','NVO','ABBV','MRK','AMGN'],
            'Healthcare': ['LLY','NVO','ABBV','MRK','AMGN'],
            'Consumer Cyclical': ['AMZN','TSLA','HD','MCD','NKE'],
            'Financial Services': ['JPM','BAC','GS','MS','V'],
            'Energy': ['XOM','CVX','COP','SLB','EOG'],
            'Industrials': ['CAT','DE','HON','UPS','LMT'],
            'Communication Services': ['META','GOOGL','NFLX','DIS','CMCSA'],
        }
        
        peer_tickers = SECTOR_PEERS.get(sector, [])
        # Remove self
        peer_tickers = [p for p in peer_tickers 
                       if p != ticker.upper()][:4]
        
        peers_data = []
        for p in peer_tickers:
            try:
                d = get_code33_data(p, CACHE_VERSION)
                if not d:
                    continue
                last_eps = next((x for x in reversed(
                    d.get('eps_yoy', []) or []) 
                    if x is not None), None)
                last_rev = next((x for x in reversed(
                    d.get('rev_yoy', []) or []) 
                    if x is not None), None)
                last_npm = next((x for x in reversed(
                    d.get('npm', []) or []) 
                    if x is not None), None)
                peers_data.append({
                    'ticker': p,
                    'eps_yoy': round(last_eps, 1) 
                               if last_eps is not None else None,
                    'rev_yoy': round(last_rev, 1) 
                               if last_rev is not None else None,
                    'npm': round(last_npm, 1) 
                           if last_npm is not None else None,
                    'status': d.get('status', '')
                })
            except:
                continue
        
        return JSONResponse({
            'ticker': ticker.upper(),
            'peers': peers_data
        })
    except Exception as e:
        return JSONResponse({
            'ticker': ticker.upper(),
            'peers': [],
            'error': str(e)
        })


