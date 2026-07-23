"""Frontend patch: surface a tripped scan circuit breaker in the UI.

Without this the polling loop only console.warn()s on st.error, so a job that
stopped early looks identical to one that finished — the exact ambiguity the
breaker exists to remove. Adds a visible banner distinguishing "stopped early
due to a pattern" from a generic failure.

Same mandated flow as tools/patch_frontend_scan.py: decode __bundler/template
JSON -> exact replacements (each asserted unique) -> re-encode with <\\/ ->
write back -> verify by round-trip.
"""
import json
import re
import sys
from pathlib import Path

INDEX = Path(__file__).resolve().parent.parent / "frontend" / "index.html"

OLD_BREAK = "        if (st.done || st.error) { if (st.error) console.warn('[runScan] job error:', st.error); break; }"
NEW_BREAK = """        if (st.done || st.error) {
          S.scanStopped = st.stopped_early ? (st.stop_reason || 'stopped early') : null;
          S.scanFailReasons = st.failure_reasons || null;
          if (st.error) console.warn('[runScan] job error:', st.error);
          break;
        }"""

# Clear any stale banner when a new scan starts.
OLD_START = "  try {\n    const fd = new FormData();\n    fd.append('file', S.file);\n    const resp = await fetch('/api/scan', { method: 'POST', body: fd });"
NEW_START = "  S.scanStopped = null; S.scanFailReasons = null;\n  try {\n    const fd = new FormData();\n    fd.append('file', S.file);\n    const resp = await fetch('/api/scan', { method: 'POST', body: fd });"

# Banner sits directly above the summary pills, inside the scanRan block.
OLD_PILLS_OPEN = """        ${S.scanRan ? `
        <div class="sum-pills">"""
NEW_PILLS_OPEN = """        ${S.scanRan ? `
        ${S.scanStopped ? `<div style="border:1px solid #FBBF24;background:rgba(251,191,36,.08);border-radius:6px;padding:12px 14px;margin-bottom:16px">
          <div style="font-size:11px;letter-spacing:.1em;text-transform:uppercase;color:#FBBF24;font-weight:600;margin-bottom:6px">Scan stopped early \\u2014 circuit breaker</div>
          <div style="font-size:12px;color:#FAFAFA;line-height:1.55">${S.scanStopped}</div>
          ${S.scanFailReasons ? `<div style="font-size:11px;color:#52525B;margin-top:8px">${Object.entries(S.scanFailReasons).map(([k,v]) => v + ' \\u00d7 ' + k).join(' \\u00b7 ')}</div>` : ''}
        </div>` : ''}
        <div class="sum-pills">"""

REPLACEMENTS = [
    ("polling loop captures stop state", OLD_BREAK, NEW_BREAK),
    ("clear banner on new scan", OLD_START, NEW_START),
    ("breaker banner above pills", OLD_PILLS_OPEN, NEW_PILLS_OPEN),
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

    html2 = INDEX.read_text(encoding="utf-8")
    m2 = re.search(r'<script type="__bundler/template">(.*?)</script>', html2, re.DOTALL)
    decoded2 = json.loads(m2.group(1))
    for name, _old, new in REPLACEMENTS:
        assert new in decoded2, f"verify failed: {name}"
    assert "circuit breaker" in decoded2.lower()
    print("verify OK: all patches present, JSON round-trips")
    return 0


if __name__ == "__main__":
    sys.exit(main())
