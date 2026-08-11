"""One-shot patcher: point the 30s price poll at /api/price instead of /api/ticker.

Follows the project's mandated flow: decode the __bundler/template JSON ->
exact string replacement -> re-encode with <\\/ escaping -> write back. The
replacement asserts exactly one match.

ONE replacement, one line of behaviour changed. startPricePoll() reads exactly
three fields off its response — price, change, change_pct (verified by grepping
`d.<field>` across the whole function) — but was polling /api/ticker, which runs
the FULL Code 33 pipeline behind the adapter's global lock and caches for 300s.
At a 30s poll interval that meant roughly every tenth tick paid an unrequested
15-30s pipeline run, blocking the event loop for every other connected client.
/api/price returns those same three fields off one yfinance fast_info call and
never reaches the pipeline.

DELIBERATELY NOT TOUCHED:
  - loadAnalysis()'s Promise.all fetch of /api/ticker — the initial page load
    genuinely needs the pipeline payload (status, rev_yoy, npm, ...). Asserted
    still byte-present after patching.
  - the world grid CSS, #world's box, PAGES, nav() and the journal redirect.
    Asserted byte-present after patching, same guard list as the news patcher.
  - the poll interval itself (30000ms) and every DOM line in the callback.
"""
import json
import re
import sys
from pathlib import Path

INDEX = Path(__file__).resolve().parent.parent / "frontend" / "index.html"

# --- the poll's fetch target ---------------------------------------------
# Anchored on the two lines above it so the match cannot drift onto
# loadAnalysis()'s /api/ticker call, which uses a different call style
# (arrow fn + r.ok guard) and must stay exactly as it is.
OLD_POLL = """    if (S.page !== 'analysis' || !S.ticker) return;
    try {
      var d = await fetch('/api/ticker/' + S.ticker).then(function(r){ return r.json(); });"""

NEW_POLL = """    if (S.page !== 'analysis' || !S.ticker) return;
    try {
      // /api/price, NOT /api/ticker. This poll reads only price/change/change_pct,
      // while /api/ticker runs the full Code 33 pipeline behind the adapter's global
      // lock with a 300s cache — so every ~10th tick fired an unrequested 15-30s
      // pipeline run that stalled the server for every connected client, on a page
      // nobody was touching. /api/price returns the same three fields from a single
      // yfinance fast_info call and never reaches the pipeline.
      // loadAnalysis()'s initial Promise.all still uses /api/ticker — it needs it.
      var d = await fetch('/api/price/' + S.ticker).then(function(r){ return r.json(); });"""

REPLACEMENTS = [
    ("price poll -> /api/price", OLD_POLL, NEW_POLL),
]

# Must still be byte-present after the patch: the initial page load's own
# /api/ticker fetch, and the three fields the poll consumes.
UNTOUCHED = [
    "fetch('/api/ticker/'    + tk).then(r => r.ok ? r.json() : {}),",
    "if (priceEl) priceEl.textContent = '$' + (d.price || 0).toFixed(2);",
    "var pct  = (d.change_pct || 0).toFixed(2);",
    "var sign = (d.change || 0) >= 0 ? '+' : '';",
    "  }, 30000);",
]

# Same protected list the news patcher guards on.
WORLD_GRID_GUARDS = [
    "#page-home     { position: absolute; left: 100vw; top: 0;",
    "#page-analysis { position: absolute; left: 100vw; top: 100vh;",
    "#page-screener { position: absolute; left: 0;     top: 0;",
    "#page-journal  { position: absolute; left: 200vw; top: 0;",
    "#world { position: absolute; width: 300vw; height: 300vh; top: 0; left: -100vw;",
    "if (page === 'journal') { window.location.href = '/journal'; return; }",
]


def main() -> int:
    html = INDEX.read_text(encoding="utf-8")
    m = re.search(r'(<script type="__bundler/template">)(.*?)(</script>)', html, re.DOTALL)
    if not m:
        print("bundler template not found")
        return 1
    decoded = json.loads(m.group(2))

    # The poll must be the ONLY thing repointed. Record how many /api/ticker
    # call sites exist before, so the after-count can be checked exactly.
    before_ticker_calls = decoded.count("/api/ticker/")
    before_price_calls = decoded.count("/api/price/")
    print(f"before: {before_ticker_calls} x /api/ticker/, {before_price_calls} x /api/price/")

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

    # verify: re-decode round-trip and confirm the patch survived
    html2 = INDEX.read_text(encoding="utf-8")
    m2 = re.search(r'<script type="__bundler/template">(.*?)</script>', html2, re.DOTALL)
    decoded2 = json.loads(m2.group(1))
    for name, _old, new in REPLACEMENTS:
        assert new in decoded2, f"verify failed: {name}"

    after_ticker_calls = decoded2.count("/api/ticker/")
    after_price_calls = decoded2.count("/api/price/")
    assert after_ticker_calls == before_ticker_calls - 1, (
        f"/api/ticker/ call sites went {before_ticker_calls} -> {after_ticker_calls}, "
        "expected exactly one to move")
    assert after_price_calls == before_price_calls + 1, (
        f"/api/price/ call sites went {before_price_calls} -> {after_price_calls}, "
        "expected exactly one to appear")
    print(f"after:  {after_ticker_calls} x /api/ticker/, {after_price_calls} x /api/price/")

    for s in UNTOUCHED:
        assert s in decoded2, f"untouched line went missing: {s}"
    for guard in WORLD_GRID_GUARDS:
        assert guard in decoded2, f"world-grid guard missing: {guard}"

    print("verify OK: poll repointed, initial /api/ticker load intact, "
          "world-grid intact, JSON round-trips")
    return 0


if __name__ == "__main__":
    sys.exit(main())
