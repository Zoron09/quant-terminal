import os
import json
import sys
import importlib

sys.path.insert(0, os.path.abspath('.'))
stock_detail = importlib.import_module("pages.15_stock_detail")
get_code33_data = stock_detail.get_code33_data

tickers = ["JAKK", "ASYS", "QUIK", "INTT", "ESOA", "UTGN", "WSR", "SODI"]
snapshot = {}

for ticker in tickers:
    try:
        data = get_code33_data(ticker)
        # Store a snapshot. We might need to handle datetimes or complex objects if any.
        # get_code33_data returns standard dicts, let's serialize them.
        snapshot[ticker] = data
    except Exception as e:
        snapshot[ticker] = {"error": str(e)}

with open('tests/fixtures/pre_unification_snapshot.json', 'w') as f:
    json.dump(snapshot, f, indent=4)
print("Snapshot created successfully.")
