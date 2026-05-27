import subprocess, sys, os, time, requests, json

cwd = r"C:\Users\Meet Singh\quant-terminal"
log_path = os.path.join(cwd, "scratch", "server_scan2.log")

with open(log_path, "w") as log_file:
    proc = subprocess.Popen([sys.executable, "run.py"], stdout=log_file, stderr=subprocess.STDOUT, cwd=cwd)

time.sleep(6)

csv_path = os.path.join(cwd, "scratch", "test_mini.csv")
try:
    with open(csv_path, "rb") as f:
        r = requests.post("http://localhost:8000/api/scan", files={"file": ("test_mini.csv", f, "text/csv")})
        data = r.json()
        print("=== API /api/scan results ===")
        for w in data.get("winners", []):
            print(f"{w['ticker']}: api_status={w['status']}")
        meta = data.get("meta", {})
        print(f"meta: total={meta.get('total')} passed={meta.get('passed')} insufficient={meta.get('insufficient')}")
except Exception as e:
    print(f"Request failed: {e}")

proc.terminate()
proc.wait()
