"""One-shot patcher for the code33-swap frontend changes (scan polling UI +
bank-exclusion badge/pill). Follows the project's mandated flow: decode the
__bundler/template JSON -> exact string replacements -> re-encode with <\\/
escaping -> write back. Each replacement asserts exactly one match.
"""
import json
import re
import sys
from pathlib import Path

INDEX = Path(__file__).resolve().parent.parent / "frontend" / "index.html"

OLD_RUNSCAN = """async function runScan() {
  if (!S.file) { S.scanning = false; renderScreener(); return; }
  try {
    const fd = new FormData();
    fd.append('file', S.file);
    const resp = await fetch('/api/scan', { method: 'POST', body: fd });
    const data = await resp.json();
    if (data.winners && Array.isArray(data.winners)) {
      SC.length = 0;
      data.winners.forEach(w => SC.push({
        t:   w.ticker,
        n:   w.company  || w.ticker,
        sec: w.sector   || 'Unknown',
        st:  w.status,
        cap: w.mcap     || 'N/A',
        rq:  (w.rev    || [0,0,0]).map(v => (Number(v) >= 0 ? '+' : '') + Number(v).toFixed(0) + '%'),
        mq:  (w.margin || [0,0,0]).map(v => (Number(v) >= 0 ? '+' : '') + Number(v).toFixed(1) + '%'),
      }));
    }
    if (data.meta) S.scanMeta = data.meta;
  } catch (err) {
    console.warn('[runScan] error:', err);
  }
  S.scanning = false; S.scanRan = true; renderScreener();
}"""

NEW_RUNSCAN = """async function runScan() {
  if (!S.file) { S.scanning = false; renderScreener(); return; }
  const applyStatus = (st) => {
    if (st.meta) S.scanMeta = st.meta;
    S.scanProgress = { completed: st.completed || 0, total: st.total || 0, current: st.current_ticker || '' };
    if (st.winners && Array.isArray(st.winners)) {
      SC.length = 0;
      st.winners.forEach(w => SC.push({
        t:   w.ticker,
        n:   w.company  || w.ticker,
        sec: w.sector   || 'Unknown',
        st:  w.status,
        cap: w.mcap     || 'N/A',
        rq:  (w.rev    || [0,0,0]).map(v => (Number(v) >= 0 ? '+' : '') + Number(v).toFixed(0) + '%'),
        mq:  (w.margin || [0,0,0]).map(v => (Number(v) >= 0 ? '+' : '') + Number(v).toFixed(1) + '%'),
      }));
    }
  };
  try {
    const fd = new FormData();
    fd.append('file', S.file);
    const resp = await fetch('/api/scan', { method: 'POST', body: fd });
    const start = await resp.json();
    if (start.error && !start.job_id) {
      console.warn('[runScan] start error:', start.error);
    } else {
      while (true) {
        const st = await fetch('/api/scan/status').then(r => r.json());
        applyStatus(st);
        if (st.done || st.error) { if (st.error) console.warn('[runScan] job error:', st.error); break; }
        renderScreener();
        await new Promise(res => setTimeout(res, 3000));
      }
    }
  } catch (err) {
    console.warn('[runScan] error:', err);
  }
  S.scanning = false; S.scanRan = true; renderScreener();
}"""

OLD_BMAP = "const bmap = { green:{text:'CODE 33 GREEN',color:'#34D399'}, yellow:{text:'CODE 33 YELLOW',color:'#FBBF24'}, red:{text:'CODE 33 RED',color:'#F87171'} };"
NEW_BMAP = "const bmap = { green:{text:'CODE 33 GREEN',color:'#34D399'}, yellow:{text:'CODE 33 YELLOW',color:'#FBBF24'}, red:{text:'CODE 33 RED',color:'#F87171'}, excluded_bank:{text:'EXCLUDED \\u2014 BANK, NOT YET SUPPORTED',color:'#52525B'} };"

OLD_PROG = "${S.scanning ? `<div class=\"prog-wrap\"><div class=\"prog-bar go\"></div></div>` : ''}"
NEW_PROG = "${S.scanning ? `<div class=\"prog-wrap\"><div class=\"prog-bar go\"></div></div><div class=\"pg-sub\">${(S.scanProgress && S.scanProgress.total) ? (S.scanProgress.completed + ' / ' + S.scanProgress.total + (S.scanProgress.current ? ' \\u2014 ' + S.scanProgress.current : '') + ((S.scanMeta && S.scanMeta.passed) ? ' \\u00b7 ' + S.scanMeta.passed + ' passed' : '')) : 'starting\\u2026'}</div>` : ''}"

OLD_PILLS = "<div class=\"s-pill\"><div class=\"s-lbl\">Insufficient Data</div><div class=\"s-val m\">${S.scanMeta.insufficient||0}</div></div>"
NEW_PILLS = "<div class=\"s-pill\"><div class=\"s-lbl\">Insufficient Data</div><div class=\"s-val m\">${S.scanMeta.insufficient||0}</div></div>\n          ${(S.scanMeta.excluded_banks||0) > 0 ? `<div class=\"s-pill\"><div class=\"s-lbl\">Excluded \\u2014 Banks</div><div class=\"s-val m\">${S.scanMeta.excluded_banks}</div></div>` : ''}"

REPLACEMENTS = [
    ("runScan polling", OLD_RUNSCAN, NEW_RUNSCAN),
    ("bmap excluded_bank badge", OLD_BMAP, NEW_BMAP),
    ("scan progress line", OLD_PROG, NEW_PROG),
    ("excluded-banks pill", OLD_PILLS, NEW_PILLS),
]


def main() -> int:
    html = INDEX.read_text(encoding="utf-8")
    m = re.search(r'(<script type="__bundler/template">)(.*?)(</script>)', html, re.DOTALL)
    if not m:
        print("bundler template not found")
        return 1
    decoded = json.loads(m.group(2))

    for name, old, new in REPLACEMENTS:
        count = decoded.count(old)
        if count != 1:
            print(f"FAIL: '{name}' matched {count} times (need exactly 1)")
            return 1
        decoded = decoded.replace(old, new)
        print(f"patched: {name}")

    encoded = json.dumps(decoded).replace("</", "<\\/")
    html = html[: m.start(2)] + encoded + html[m.end(2):]
    INDEX.write_text(html, encoding="utf-8")

    # verify: re-decode round-trip and confirm patches present
    html2 = INDEX.read_text(encoding="utf-8")
    m2 = re.search(r'<script type="__bundler/template">(.*?)</script>', html2, re.DOTALL)
    decoded2 = json.loads(m2.group(1))
    for name, _old, new in REPLACEMENTS:
        assert new in decoded2, f"verify failed: {name}"
    assert "api/scan/status" in decoded2
    print("verify OK: all patches present, JSON round-trips")
    return 0


if __name__ == "__main__":
    sys.exit(main())
