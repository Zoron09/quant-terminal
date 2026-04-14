import os
from dotenv import load_dotenv
import importlib
import sys

load_dotenv()
sys.path.insert(0, os.path.dirname(__file__))

mod = importlib.import_module("pages.15_stock_detail")
print("Has FMP:", mod._HAS_FMP)
mod.get_code33_data('NVDA')
