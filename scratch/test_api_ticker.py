import subprocess, sys, os, time, requests

cwd = r"C:\Users\Meet Singh\quant-terminal"
log_path = os.path.join(cwd, "scratch", "server_api_ticker.log")

with open(log_path, "w") as log_file:
    proc = subprocess.Popen([sys.executable, "run.py"], stdout=log_file, stderr=subprocess.STDOUT, cwd=cwd)

time.sleep(6)

for t in ['META', 'NVDA']:
    try:
        r = requests.get(f"http://localhost:8000/api/ticker/{t}", timeout=30)
        d = r.json()
        print(f"{t}: api_status={d.get('status')}")
    except Exception as e:
        print(f"{t}: FAILED — {e}")

proc.terminate()
proc.wait()
