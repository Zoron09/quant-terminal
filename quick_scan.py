import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, r'C:\Users\Meet Singh\quant-terminal')
from utils.code33_engine import get_code33_data

for t in ['NTCT','PLGO','WASH','NVRI','EBC','FRST','CLBK','MSBI','AMTB']:
    data = get_code33_data(t)
    print(t, data.get('status'), flush=True)
