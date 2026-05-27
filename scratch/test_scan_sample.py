import requests, os

cwd = r"C:\Users\Meet Singh\quant-terminal"
csv_path = os.path.join(cwd, "Minervini_builder_Managed_2026-04-28.csv")

with open(csv_path, "rb") as f:
    r = requests.post("http://localhost:8000/api/scan", files={"file": ("Minervini_builder_Managed_2026-04-28.csv", f, "text/csv")})
    data = r.json()
    winners = data.get("winners", [])
    print(f"[SCAN] winners found: {len(winners)}")
    if winners:
        print(f"[SCAN] first winner sample: {winners[0]}")
    meta = data.get("meta", {})
    print(f"meta: total={meta.get('total')} passed={meta.get('passed')} insufficient={meta.get('insufficient')}")
