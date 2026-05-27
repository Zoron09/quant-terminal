import sys
sys.path.append(r"C:\Users\Meet Singh\quant-terminal")
from utils.code33_engine import get_code33_data

print("Fetching AXON")
data = get_code33_data('AXON')
print("\nEPS values:")
print(data.get('eps'))
print("\nEPS end dates:")
print(data.get('eps_end_dates'))
print("\nEPS YoY:")
print(data.get('eps_yoy'))
