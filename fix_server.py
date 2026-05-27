import re

with open('api/server.py', 'r', encoding='utf-8') as f:
    code = f.read()

# 1. Add evict_cache function
evict_func = '''TICKER_CACHE = {}
CACHE_TTL = 300  # 5 minutes

def evict_cache():
    import time
    now = time.time()
    expired = [k for k, v in list(TICKER_CACHE.items()) if now - v[1] > 600]
    for k in expired: TICKER_CACHE.pop(k, None)
'''
code = code.replace('TICKER_CACHE = {}\nCACHE_TTL = 300  # 5 minutes', evict_func)

# Insert evict_cache() call at the start of endpoints
code = re.sub(r'(async def \w+\(.*?\):\n(?:    .*?\n)*?    now = time\.time\(\)\n)', r'\g<1>    evict_cache()\n', code)

# 2. Fix duplicate .info calls in ticker
ticker_replace = '''
        tk = yf.Ticker(t)
        info = tk.fast_info
        full_info = tk.info or {}
        data['price'] = getattr(info, 'last_price', 0)
        data['company_name'] = full_info.get(
            'shortName', t)
            
        data['change'] = getattr(info, 'last_price', 0) - \\
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
'''

old_ticker = '''        info = yf.Ticker(t).fast_info
        data['price'] = getattr(info, 'last_price', 0)
        data['company_name'] = yf.Ticker(t).info.get(
            'shortName', t)
            
        data['change'] = getattr(info, 'last_price', 0) - \\
          getattr(info, 'regular_market_previous_close', 
          getattr(info, 'previous_close', 0))
          
        data['change_pct'] = (data['change'] / 
          getattr(info, 'regular_market_previous_close',
          getattr(info, 'previous_close', 1))) * 100
        
        mc = getattr(info, 'market_cap', None)
        if mc is None:
            mc = yf.Ticker(t).info.get('marketCap', 0)
        def fmt_mcap(v):
            try:
                v = float(v)
                if v >= 1e12: return f"{v/1e12:.1f}T"
                if v >= 1e9:  return f"{v/1e9:.1f}B"
                if v >= 1e6:  return f"{v/1e6:.1f}M"
                return f"{v:,.0f}"
            except: return "N/A"
        data['market_cap_fmt'] = fmt_mcap(mc)
        
        data['pe_ratio'] = yf.Ticker(t).info.get(
            'trailingPE', 'N/A')'''

code = code.replace(old_ticker, ticker_replace)

# 3. Parallelize financials
old_fin = '''        inc = tk.quarterly_income_stmt
        bal = tk.quarterly_balance_sheet
        cf  = tk.quarterly_cashflow
        info = tk.info or {}'''

new_fin = '''        import concurrent.futures
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
            cal_data = f_cal.result()'''

code = code.replace(old_fin, new_fin)
code = code.replace('cal = tk.calendar', 'cal = cal_data')

# 4. Fix EPS fallback
code = code.replace("['NetIncome', 'Net Income', 'NetIncomeCommonStockholders']", "['NetIncomeCommonStockholders']")

# 5. Fix silent failures
code = re.sub(r'(\@app\.get\(\"/api/ownership/[^:]+:\n(?:(?:(?!\@app).)*?)except Exception) as e:', r'\1 as e:\n        print(f"[ERROR] /api/ownership/{ticker}: {e}")', code, flags=re.DOTALL)
code = re.sub(r'(\@app\.get\(\"/api/peers/[^:]+:\n(?:(?:(?!\@app).)*?)except Exception) as e:', r'\1 as e:\n        print(f"[ERROR] /api/peers/{ticker}: {e}")', code, flags=re.DOTALL)

# 6. Remove dead endpoint
code = re.sub(r'\@app\.get\(\"/api/debug/.*?$', '', code, flags=re.DOTALL)

with open('api/server.py', 'w', encoding='utf-8') as f:
    f.write(code)
