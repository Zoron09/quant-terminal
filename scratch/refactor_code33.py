import ast
import os
import sys

source_file = r'C:\Users\Meet Singh\quant-terminal\pages\15_stock_detail.py'
target_file = r'C:\Users\Meet Singh\quant-terminal\utils\code33_engine.py'

with open(source_file, 'r', encoding='utf-8') as f:
    source = f.read()

tree = ast.parse(source)

funcs_to_move = [
    '_get_fq_fy',
    '_build_margin_pool',
    '_date_first_yoy',
    'get_code33_data',
    '_c33_status'
]

# Find bounds of functions
lines = source.split('\n')
extracted_blocks = []
remove_ranges = []

# We need to preserve the decorator for get_code33_data: @st.cache_data(ttl=86400, show_spinner=False)
for node in tree.body:
    if isinstance(node, ast.FunctionDef) and node.name in funcs_to_move:
        # Find decorator line
        start_line = node.lineno
        if node.decorator_list:
            start_line = node.decorator_list[0].lineno
            
        end_line = node.end_lineno
        
        # We need to grab exactly from start_line - 1 to end_line
        block = '\n'.join(lines[start_line-1:end_line])
        extracted_blocks.append((start_line, end_line, block, node.name))
        remove_ranges.append((start_line, end_line))

# Sort ranges descending so removing them doesn't shift earlier lines
remove_ranges.sort(key=lambda x: x[0], reverse=True)

for start, end in remove_ranges:
    del lines[start-1:end]

# Add imports
new_source = "\n".join(lines)
import_statement = "from utils.code33_engine import _get_fq_fy, _build_margin_pool, _date_first_yoy, get_code33_data, _c33_status\n"

# Insert import after the last import in the file
import_inserted = False
for i, line in enumerate(lines):
    if 'from utils.formatters import' in line:
        # find end of this import
        for j in range(i, len(lines)):
            if ')' in lines[j] or 'fmt_date' in lines[j]:
                lines.insert(j + 2, import_statement)
                import_inserted = True
                break
    if import_inserted:
        break

if not import_inserted:
    lines.insert(30, import_statement)

new_source = "\n".join(lines)

with open(source_file, 'w', encoding='utf-8') as f:
    f.write(new_source)

# Construct code33_engine.py
engine_header = """import os
import requests
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
import streamlit as st

# We need SEC_HEADERS and other constants
from utils.data_fetcher import get_ticker_info, get_financials
from utils.sec_edgar import get_cik

FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY")
FMP_API_KEY = os.environ.get("FMP_API_KEY")

CACHE_VERSION = 'v2'

"""

blocks_sorted_by_original_order = sorted(extracted_blocks, key=lambda x: x[0])
engine_code = engine_header + "\n\n".join(b[2] for b in blocks_sorted_by_original_order)

with open(target_file, 'w', encoding='utf-8') as f:
    f.write(engine_code)

print("Refactoring complete.")
