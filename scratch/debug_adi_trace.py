import sys
sys.path.insert(0, '.')
import os
os.environ['DEBUG_C33'] = '1'
from utils.code33_engine import get_code33_data

result = get_code33_data("ADI")

print("\nEPS YOY PAIRS:")
for item in result.get('eps_yoy_detail', result.get('eps_yoy', [])):
    print(item)

print("\nRAW EPS POINTS:")
for item in result.get('eps_points', result.get('eps_data', result.get('eps', []))):
    print(item)
