import sys
from datetime import datetime, timedelta
sys.path.append(r"C:\Users\Meet Singh\quant-terminal")
from utils.code33_engine import get_edgar_facts
import itertools

facts = get_edgar_facts('XOM')
usgaap = facts.get('facts', {}).get('us-gaap', {})

TARGET_DATE = '2026-03-31'
TARGET_DT = datetime.strptime(TARGET_DATE, '%Y-%m-%d')
BASE_REVENUE = 85_138_000_000
IMPLIED_REVENUE = 89_206_000_000
GAP = IMPLIED_REVENUE - BASE_REVENUE # ~4.068B

def get_q_val(concept):
    units = usgaap.get(concept, {}).get('units', {}).get('USD', [])
    for e in units:
        form = str(e.get('form', '')).upper()
        if form not in ('10-Q', '10-K', '20-F', '6-K'): continue
        end_s = str(e.get('end', '')).strip()
        start_s = str(e.get('start', '')).strip()
        val = e.get('val')
        if not end_s or not start_s or val is None: continue
        try:
            end_dt = datetime.strptime(end_s, '%Y-%m-%d')
            start_dt = datetime.strptime(start_s, '%Y-%m-%d')
        except: continue
        dur = (end_dt - start_dt).days
        if not (75 <= dur <= 105): continue
        if abs((end_dt - TARGET_DT).days) <= 15:
            return float(val)
    return None

print("1. Fetch ALL EDGAR XBRL concepts with values between $500M and $10B for Q1 2026:")
candidates = {}
for concept in usgaap.keys():
    val = get_q_val(concept)
    if val is not None and 500_000_000 <= val <= 10_000_000_000:
        candidates[concept] = val
        print(f"  {concept}: ${val:,.0f}")

print("\n2. Find combination of concepts that sums to ~$89,206,000,000 (Target Gap = ~$4,068M):")
# Try single
found_single = False
for c, v in candidates.items():
    if abs(v - GAP) < GAP * 0.05: # within 5%
        print(f"  Single Concept matches Gap: {c} (${v:,.0f}) => Total Revenue = ${(BASE_REVENUE + v):,.0f}")
        found_single = True

# Try pairs
found_pair = False
keys = list(candidates.keys())
for i in range(len(keys)):
    for j in range(i+1, len(keys)):
        c1, c2 = keys[i], keys[j]
        v1, v2 = candidates[c1], candidates[c2]
        if abs((v1 + v2) - GAP) < GAP * 0.05:
            print(f"  Pair Concept matches Gap: {c1} + {c2} (${(v1+v2):,.0f}) => Total Revenue = ${(BASE_REVENUE + v1 + v2):,.0f}")
            found_pair = True

if not found_single and not found_pair:
    print("  No single or pair combination found within 5% of the gap.")

print("\n3. Specifically check these concepts:")
specific_concepts = [
    'IncomeFromEquityMethodInvestments',
    'IncomeLossFromEquityMethodInvestments',
    'OtherNonoperatingIncome',
    'OtherIncome',
    'GainLossOnSaleOfProperties',
    'NonoperatingIncomeExpense'
]
for c in specific_concepts:
    val = get_q_val(c)
    if val is not None:
        print(f"  {c}: ${val:,.0f}")
    else:
        print(f"  {c}: Not Found or No valid Q1 2026 data")
