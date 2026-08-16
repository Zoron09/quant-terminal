"""One-shot patcher: remove the SECTOR PEERS feature from the analysis page.

Follows the project's mandated flow: decode the __bundler/template JSON ->
exact string replacements -> re-encode with <\\/ escaping -> write back. Every
replacement asserts exactly one match before it is applied.

WHY: /api/peers ran the full Code 33 pipeline once per peer, four peers, all
serialized behind the adapter's global lock. On a cold AAPL load it was 57.69s
of a 57.70s page wall — the entire load. The backend endpoint and its cache are
deleted in api/server.py; this removes the frontend half so nothing fetches or
renders it.

NINE replacements, in DOM/definition order:
  1. .peer-tbl CSS block (5 rules, only consumer was the peers table)
  2. .bot-cols becomes a single column, so INSTITUTIONAL OWNERSHIP spans the
     full width instead of sitting in the left half of a 2-column grid with a
     hole where the peers card was. The 680px media query that also set 1fr
     goes with it — it now restates the base rule exactly.
  3. the mock D.peers seed array
  4. _applyToD()'s a.peers -> D.peers mapping
  5. the idle/loading message, which advertised "and peers"
  6. renderAnalysis()'s `const peers = D.peers.map(...)` row builder
  7. the SECTOR PEERS card markup
  8. loadAnalysis()'s Promise.all: the /api/peers fetch and its `pe` binding
  9. S.analysis's `peers:` field

DELIBERATELY NOT TOUCHED: the chart, financials, news, ownership and price-badge
paths; the remaining six fetches in the fan-out; the world grid CSS, #world's
box, PAGES, nav() and the journal redirect. All asserted byte-present after.
"""
import json
import re
import sys
from pathlib import Path

INDEX = Path(__file__).resolve().parent.parent / "frontend" / "index.html"

# --- 1. peers table CSS ---------------------------------------------------
OLD_CSS = """    .peer-tbl { width: 100%; border-collapse: collapse; }
    .peer-tbl th { font-size: 10px; color: var(--fg3); text-transform: uppercase; letter-spacing: .08em; padding: 5px 8px; border-bottom: 1px solid var(--bs); text-align: left; }
    .peer-tbl td { padding: 8px 8px; font-family: 'IBM Plex Mono', monospace; font-size: 12px; border-bottom: 1px solid var(--bs); }
    .peer-tbl tr:last-child td { border-bottom: none; }
    .peer-tbl tr.hl td { color: var(--gold); }
"""
NEW_CSS = ""

# --- 2. bottom row goes single-column -------------------------------------
OLD_COLS = """    .bot-cols { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
    @media (max-width: 680px) { .bot-cols { grid-template-columns: 1fr; } }
"""
NEW_COLS = """    /* Single column since SECTOR PEERS was removed — INSTITUTIONAL OWNERSHIP is
       the only card left in this row, and a 1fr 1fr grid would have parked it in
       the left half with an empty right half. The 680px media query that also
       set 1fr went with it: it now restated the base rule exactly. */
    .bot-cols { display: grid; grid-template-columns: 1fr; gap: 14px; }
"""

# --- 3. mock seed data ----------------------------------------------------
OLD_MOCK = """  peers: [
    { t: 'NVDA', r: '+197.3%', m: '61.2%',  me: true },
    { t: 'AMD',  r: '+17.6%',  m: '5.8%',   me: false },
    { t: 'INTC', r: '-8.2%',   m: '-14.3%', me: false },
    { t: 'QCOM', r: '+9.1%',   m: '26.4%',  me: false },
    { t: 'AVGO', r: '+51.2%',  m: '38.9%',  me: false }
  ],
"""
NEW_MOCK = ""

# --- 4. API -> D mapping --------------------------------------------------
OLD_APPLY = """  if (a.peers && a.peers.length)
    D.peers = [{ t: S.ticker, r: D.revYoY, m: D.netMargin, me: true },
               ...a.peers.map(p => ({
                 t: p.ticker,
                 r: p.rev_yoy != null ? (p.rev_yoy >= 0 ? '+' : '') + Number(p.rev_yoy).toFixed(1) + '%' : 'N/A',
                 m: p.npm     != null ? (p.npm     >= 0 ? '+' : '') + Number(p.npm).toFixed(1)     + '%' : 'N/A',
                 me: false,
               }))];
"""
NEW_APPLY = ""

# --- 5. loading copy ------------------------------------------------------
OLD_IDLE = ">Pulling filings, price, news and peers.</div>`"
NEW_IDLE = ">Pulling filings, price, news and ownership.</div>`"

# --- 6. row builder -------------------------------------------------------
OLD_ROWS = """  const peers = D.peers.map(p => `
    <tr class="${p.me?'hl':''}">
      <td>${p.t}</td>
      <td class="${parseFloat(p.r)>0?'pos':'neg'}" style="text-align:right">${p.r}</td>
      <td class="${parseFloat(p.m)>0?'pos':'neg'}" style="text-align:right">${p.m}</td>
    </tr>`).join('');

"""
NEW_ROWS = ""

# --- 7. card markup -------------------------------------------------------
# Anchored on the ownership card's closing </div> above it and .bot-cols'
# closing </div> below it, so the match cannot drift onto another card.
OLD_CARD = """          </div>
          <div class="card">
            <div class="card-hd">SECTOR PEERS</div>
            <div style="padding:14px">
              <table class="peer-tbl">
                <thead><tr><th>Ticker</th><th style="text-align:right">Rev YoY</th><th style="text-align:right">Net Margin</th></tr></thead>
                <tbody>${peers}</tbody>
              </table>
            </div>
          </div>
        </div>
"""
NEW_CARD = """          </div>
        </div>
"""

# --- 8. the fan-out -------------------------------------------------------
OLD_DESTRUCTURE = "    const [ti, ch, fi, nw, ow, pe, qt] = await Promise.all(["
NEW_DESTRUCTURE = "    const [ti, ch, fi, nw, ow, qt] = await Promise.all(["

OLD_FETCH = """      fetch('/api/peers/'     + tk).then(r => r.ok ? r.json() : {}),
"""
NEW_FETCH = ""

# --- 9. state field -------------------------------------------------------
OLD_STATE = """      peers:     pe.peers || [],
"""
NEW_STATE = ""

REPLACEMENTS = [
    ("peer-tbl CSS",            OLD_CSS,         NEW_CSS),
    ("bot-cols single column",  OLD_COLS,        NEW_COLS),
    ("mock D.peers seed",       OLD_MOCK,        NEW_MOCK),
    ("_applyToD peers mapping", OLD_APPLY,       NEW_APPLY),
    ("idle loading copy",       OLD_IDLE,        NEW_IDLE),
    ("peers row builder",       OLD_ROWS,        NEW_ROWS),
    ("SECTOR PEERS card",       OLD_CARD,        NEW_CARD),
    ("Promise.all destructure", OLD_DESTRUCTURE, NEW_DESTRUCTURE),
    ("/api/peers fetch",        OLD_FETCH,       NEW_FETCH),
    ("S.analysis peers field",  OLD_STATE,       NEW_STATE),
]

# Everything the analysis page still depends on. If any of these moved, the
# patch hit more than it was supposed to.
UNTOUCHED = [
    "fetch('/api/ticker/'    + tk).then(r => r.ok ? r.json() : {}),",
    "fetch('/api/chart/'     + tk + '?period=1y&interval=1d').then(r => r.ok ? r.json() : {}),",
    "fetch('/api/financials/'+ tk).then(r => r.ok ? r.json() : {}),",
    "fetch('/api/news/'      + tk).then(r => r.ok ? r.json() : {}),",
    "fetch('/api/ownership/' + tk).then(r => r.ok ? r.json() : {}),",
    "fetch('/api/price/'     + tk).then(r => r.ok ? r.json() : {}),",
    'var d = await fetch(\'/api/price/\' + S.ticker).then(function(r){ return r.json(); });',
    '<div class="card-hd">INSTITUTIONAL OWNERSHIP</div>',
    '<div class="card-hd">LIVE NEWS<span class="live-pill"><span class="live-dot"></span>LIVE</span></div>',
    "D.owners = (a.ownership || []).map(h => ({ name: h.name, pct: Number(h.pct) }));",
    "ownership: ow.institutional || [],",
    "quote:     qt,",
    "  }, 30000);",
]

# Same protected list every other patcher in this directory guards on.
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

    before_peers = len(re.findall(r'peers|peer-tbl|SECTOR PEERS', decoded))
    before_fetches = decoded.count("fetch('/api/")
    print(f"before: {before_peers} peers-ish tokens, {before_fetches} fetch('/api/ call sites")

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

    for name, old, _new in REPLACEMENTS:
        assert old not in decoded2, f"verify failed, still present: {name}"

    # No peers CODE may survive anywhere in the bundle. The two CSS comment
    # lines this patch introduces name the removed feature on purpose — they are
    # the record of why .bot-cols is single-column — so they are excluded by
    # matching the comment marker, not by matching their text.
    survivors = [l.strip() for l in decoded2.splitlines()
                 if re.search(r'peers|peer-tbl|SECTOR PEERS|/api/peers', l)
                 and not l.lstrip().startswith(('/*', '*', 'the left half'))]
    assert not survivors, f"peers references survived: {survivors[:5]}"

    after_fetches = decoded2.count("fetch('/api/")
    assert after_fetches == before_fetches - 1, (
        f"fetch('/api/ call sites went {before_fetches} -> {after_fetches}, "
        "expected exactly one to disappear")
    print(f"after:  0 peers-ish tokens, {after_fetches} fetch('/api/ call sites")

    for s in UNTOUCHED:
        assert s in decoded2, f"untouched line went missing: {s}"
    for guard in WORLD_GRID_GUARDS:
        assert guard in decoded2, f"world-grid guard missing: {guard}"

    print("verify OK: peers gone, other five fetches + price poll intact, "
          "ownership/news cards intact, world-grid intact, JSON round-trips")
    return 0


if __name__ == "__main__":
    sys.exit(main())
