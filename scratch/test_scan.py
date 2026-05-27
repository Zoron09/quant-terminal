import subprocess
import requests
import time
import sys
import os

cwd = r"C:\Users\Meet Singh\quant-terminal"
log_path = os.path.join(cwd, "scratch", "server_out.log")

with open(log_path, "w") as log_file:
    proc = subprocess.Popen([sys.executable, "run.py"], stdout=log_file, stderr=subprocess.STDOUT, cwd=cwd)

time.sleep(5)

csv_path = os.path.join(cwd, "Minervini_builder_Managed_2026-04-28.csv")
try:
    with open(csv_path, "rb") as f:
        r = requests.post("http://localhost:8000/api/scan", files={"file": f})
        print(f"Status Code: {r.status_code}")
except Exception as e:
    print(f"Request failed: {e}")

proc.terminate()
proc.wait()

with open(log_path, "r") as log_file:
    print("--- TERMINAL OUTPUT ---")
    print(log_file.read())
