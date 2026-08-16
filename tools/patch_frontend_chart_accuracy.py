"""One-shot patcher: un-smooth the price chart and make its numbers exact.

Mandated flow: decode the __bundler/template JSON -> exact string replacements
-> re-encode with <\\/ escaping -> write back. Every replacement asserts exactly
one match.

PART 1 — the line was never the data. makeSVG() emitted cubic beziers with BOTH
control points on the x-midpoint of each segment, which rounds every corner and
pins a horizontal tangent through each actual price. Replaced with straight
segments between the real points, the way Yahoo/TradingView draw them.

PART 2 — number accuracy:
  * periodPerf() becomes the ONE definition of the above-chart number.
    renderAnalysis() and renderChart() each carried their own copy of the
    arithmetic, which is precisely how two readouts drift apart.
  * 1D reuses the top badge's OWN values (live price vs previous close) instead
    of recomputing off the intraday series, whose first bar is NOT the previous
    close — measured on NVDA: badge +$1.68, label -$1.62, opposite signs, both
    'correct'. Reusing the values makes them identical by construction.
  * Every other tab measures its own plotted series' first and last points
    instead of ending at a separately-fetched live price (the ~1c mismatch).
  * The badge is seeded from the live /api/price quote at first paint, so it no
    longer renders a up-to-5-minute-old /api/ticker value and then jumps.
  * fmtChange() is one formatter for the badge string. The poll built its own
    and DROPPED THE MINUS SIGN on the dollar figure (-$1.65 rendered as
    "$1.65"); renderAnalysis() put it inside the dollar sign ("$-1.65").
  * Y-axis ticks go to 2dp — at toFixed(0) every tick on a $2.35 stock read "$2".

NOT TOUCHED: world-grid CSS, #world's box, PAGES, nav(), the journal redirect,
the 30000ms poll interval, and the /api/ticker fetch in loadAnalysis (the page
still needs the pipeline payload). All asserted below.
"""
import json
import re
import sys
from pathlib import Path

INDEX = Path(__file__).resolve().parent.parent / "frontend" / "index.html"

# --- 1. straight lines instead of beziers ---------------------------------
OLD_PATH = """  let lp = `M${px(0).toFixed(1)},${py(prices[0]).toFixed(1)}`;
  for (let i = 1; i < n; i++) {
    const cx = (px(i-1)+px(i))/2;
    lp += ` C${cx.toFixed(1)},${py(prices[i-1]).toFixed(1)} ${cx.toFixed(1)},${py(prices[i]).toFixed(1)} ${px(i).toFixed(1)},${py(prices[i]).toFixed(1)}`;
  }"""

NEW_PATH = """  // Straight segments between the REAL data points — no smoothing. This used to
  // emit a cubic bezier per segment with both control points at the x-midpoint,
  // which rounds every corner and forces a horizontal tangent through each
  // actual price, so the drawn line was a decorative approximation of the data
  // rather than the data. Yahoo/TradingView draw polylines; so do we.
  let lp = `M${px(0).toFixed(1)},${py(prices[0]).toFixed(1)}`;
  for (let i = 1; i < n; i++) {
    lp += ` L${px(i).toFixed(1)},${py(prices[i]).toFixed(1)}`;
  }"""

# --- 2. y-axis ticks to the cent ------------------------------------------
OLD_TICK = """fill="#3F3F46">$${v.toFixed(0)}</text>`"""
NEW_TICK = """fill="#3F3F46">$${v.toFixed(2)}</text>`"""

# --- 3. one perf definition + rewritten renderChart -----------------------
OLD_RENDERCHART = """function renderChart() {
  var prices     = PRICES[S.tf] || [];
  var firstClose = prices.length >= 1 ? prices[0] : 0;
  var lastClose  = (D.price && D.price > 0) ? D.price : (prices.length >= 1 ? prices[prices.length - 1] : 0);
  var isGain     = lastClose >= firstClose;
  var wrap = document.getElementById('chart-wrap');
  if (wrap) wrap.innerHTML = makeSVG(prices, isGain);
  document.querySelectorAll('.tf').forEach(function(x){ x.classList.toggle('on', x.dataset.tf === S.tf); });
  var perfEl = document.getElementById('period-perf');
  if (perfEl && prices.length >= 2 && firstClose > 0) {
    var dollarDiff = lastClose - firstClose;
    var absDollar  = Math.abs(dollarDiff).toFixed(2);
    var absPct     = Math.abs(dollarDiff / firstClose * 100).toFixed(2);
    var arrow      = isGain ? '▲' : '▼';
    perfEl.textContent = arrow + ' $' + absDollar + '   ' + absPct + '%';
    perfEl.style.color = isGain ? '#34D399' : '#F87171';
  }
}"""

NEW_RENDERCHART = """// The one definition of the above-chart performance number. renderAnalysis()
// (first paint) and renderChart() (tab switch) both call it; they used to carry
// duplicate copies of this arithmetic, which is exactly how two readouts drift
// apart from each other.
//
// 1D is deliberately special-cased. "1D" and "today" are the same thing, so it
// reuses the top badge's OWN numbers — live price against the previous close —
// rather than recomputing from the intraday series, whose first bar is not the
// previous close. Measured on NVDA: badge +$1.68 (vs prev close 217.55) against
// -$1.62 (vs the 09:30 bar at 220.86) — opposite signs, both arithmetically
// right, one baseline wrong for the label. Reusing the VALUES rather than just
// the baseline makes the two identical by construction, not by rounding luck.
//
// Every other tab measures the plotted series' own first and last points, so
// the label can never disagree with the line drawn directly beneath it. It used
// to end at the separately-fetched live quote, a different number from the
// chart's own last close.
function periodPerf(tf) {
  if (tf === '1D') {
    if (D.change == null || D.changePct == null) return null;
    return { dollar: Number(D.change), pct: Number(D.changePct) };
  }
  var prices = PRICES[tf] || [];
  if (prices.length < 2) return null;
  var first = prices[0], last = prices[prices.length - 1];
  if (!(first > 0)) return null;
  var dollar = last - first;
  return { dollar: dollar, pct: dollar / first * 100 };
}

// One formatter for the badge's "$change (pct%)". The 30s poll used to build
// this string itself and DROPPED THE MINUS SIGN on the dollar figure entirely
// (a -$1.65 move rendered as "$1.65"), while renderAnalysis() put the sign
// inside the dollar sign ("$-1.65"). Both now read "-$1.65".
function fmtChange(dollar, pct) {
  var d = Number(dollar) || 0, p = Number(pct) || 0;
  var s = d >= 0 ? '+' : '-';
  return s + '$' + Math.abs(d).toFixed(2) + ' (' + s + Math.abs(p).toFixed(2) + '%)';
}

function renderChart() {
  var prices = PRICES[S.tf] || [];
  var pp     = periodPerf(S.tf);
  var isGain = pp ? pp.dollar >= 0
                  : (prices.length >= 2 ? prices[prices.length - 1] >= prices[0] : true);
  var wrap = document.getElementById('chart-wrap');
  if (wrap) wrap.innerHTML = makeSVG(prices, isGain);
  document.querySelectorAll('.tf').forEach(function(x){ x.classList.toggle('on', x.dataset.tf === S.tf); });
  var perfEl = document.getElementById('period-perf');
  if (perfEl && pp) {
    perfEl.textContent = (isGain ? '▲' : '▼') + ' $' + Math.abs(pp.dollar).toFixed(2)
                       + '   ' + Math.abs(pp.pct).toFixed(2) + '%';
    perfEl.style.color = isGain ? '#34D399' : '#F87171';
  }
}"""

# --- 4. renderAnalysis uses the same helper -------------------------------
OLD_RA = """  const isPos = D.changePct >= 0;
  const chartPrices = PRICES[S.tf] || [];
  const firstCloseRA  = chartPrices.length >= 1 ? chartPrices[0] : 0;
  const lastCloseRA   = (D.price && D.price > 0) ? D.price : (chartPrices.length >= 1 ? chartPrices[chartPrices.length-1] : 0);
  const isGain     = lastCloseRA >= firstCloseRA;
  const dollarDiffRA = lastCloseRA - firstCloseRA;
  const absDollarRA  = Math.abs(dollarDiffRA).toFixed(2);
  const absPctRA     = (firstCloseRA > 0 ? Math.abs(dollarDiffRA / firstCloseRA * 100) : 0).toFixed(2);
  const perfArrow  = isGain ? '▲' : '▼';
  const perfColor  = isGain ? '#34D399' : '#F87171';
  const perfDisplay = chartPrices.length >= 2 && firstCloseRA > 0 ? perfArrow + ' $' + absDollarRA + '   ' + absPctRA + '%' : '';"""

NEW_RA = """  const isPos = D.changePct >= 0;
  const chartPrices = PRICES[S.tf] || [];
  // Same helper renderChart() uses — see periodPerf() for why 1D differs.
  const ppRA       = periodPerf(S.tf);
  const isGain     = ppRA ? ppRA.dollar >= 0
                          : (chartPrices.length >= 2 ? chartPrices[chartPrices.length-1] >= chartPrices[0] : true);
  const perfArrow  = isGain ? '▲' : '▼';
  const perfColor  = isGain ? '#34D399' : '#F87171';
  const perfDisplay = ppRA ? perfArrow + ' $' + Math.abs(ppRA.dollar).toFixed(2)
                             + '   ' + Math.abs(ppRA.pct).toFixed(2) + '%' : '';"""

# --- 5. badge string goes through the shared formatter --------------------
OLD_BADGE = """            <span class="id-chg price-change ${isPos?'pos':'neg'}"> ${isPos?'+':''}$${D.change.toFixed(2)} (${isPos?'+':''}${D.changePct.toFixed(2)}%)</span>"""
NEW_BADGE = """            <span class="id-chg price-change ${isPos?'pos':'neg'}"> ${fmtChange(D.change, D.changePct)}</span>"""

# --- 6. seed the badge from the live quote at first paint -----------------
OLD_FETCH = """    const [ti, ch, fi, nw, ow, pe] = await Promise.all([
      fetch('/api/ticker/'    + tk).then(r => r.ok ? r.json() : {}),
      fetch('/api/chart/'     + tk + '?period=1y&interval=1d').then(r => r.ok ? r.json() : {}),
      fetch('/api/financials/'+ tk).then(r => r.ok ? r.json() : {}),
      fetch('/api/news/'      + tk).then(r => r.ok ? r.json() : {}),
      fetch('/api/ownership/' + tk).then(r => r.ok ? r.json() : {}),
      fetch('/api/peers/'     + tk).then(r => r.ok ? r.json() : {}),
    ]);
    S.analysis = {
      ticker:    tk,
      info:      ti,
      chart:     ch.prices || [],
      financials:fi,
      news:      nw.news || [],
      ownership: ow.institutional || [],
      peers:     pe.peers || [],
    };"""

NEW_FETCH = """    const [ti, ch, fi, nw, ow, pe, qt] = await Promise.all([
      fetch('/api/ticker/'    + tk).then(r => r.ok ? r.json() : {}),
      fetch('/api/chart/'     + tk + '?period=1y&interval=1d').then(r => r.ok ? r.json() : {}),
      fetch('/api/financials/'+ tk).then(r => r.ok ? r.json() : {}),
      fetch('/api/news/'      + tk).then(r => r.ok ? r.json() : {}),
      fetch('/api/ownership/' + tk).then(r => r.ok ? r.json() : {}),
      fetch('/api/peers/'     + tk).then(r => r.ok ? r.json() : {}),
      // Live quote for the badge. /api/ticker carries the same three fields but
      // is cached 300s, so at first paint it can be five minutes stale and then
      // visibly jump when the 30s poll lands. This costs ~0.4s, runs in the same
      // fan-out, and never touches the pipeline.
      fetch('/api/price/'     + tk).then(r => r.ok ? r.json() : {}),
    ]);
    S.analysis = {
      ticker:    tk,
      info:      ti,
      chart:     ch.prices || [],
      financials:fi,
      news:      nw.news || [],
      ownership: ow.institutional || [],
      peers:     pe.peers || [],
      quote:     qt,
    };"""

# --- 7. the live quote overrides the cached one ---------------------------
OLD_APPLY = """  if (inf.change_pct != null) D.changePct = Number(inf.change_pct);"""

NEW_APPLY = """  if (inf.change_pct != null) D.changePct = Number(inf.change_pct);
  // The live quote wins over /api/ticker's cached copy. Applied AFTER the inf
  // block on purpose. Same three fields, same yfinance fast_info source — this
  // is purely about freshness, not a different number.
  const q = a.quote || {};
  if (q.price      != null) D.price     = Number(q.price);
  if (q.change     != null) D.change    = Number(q.change);
  if (q.change_pct != null) D.changePct = Number(q.change_pct);"""

# --- 8. the poll keeps D in sync so 1D's two numbers stay identical -------
OLD_POLL = """      var priceEl  = document.querySelector('.price-val');
      var changeEl = document.querySelector('.price-change');
      if (priceEl) priceEl.textContent = '$' + (d.price || 0).toFixed(2);
      if (changeEl) {
        var chg  = (d.change || 0).toFixed(2);
        var pct  = (d.change_pct || 0).toFixed(2);
        var sign = (d.change || 0) >= 0 ? '+' : '';
        changeEl.textContent = sign + '$' + Math.abs(d.change || 0).toFixed(2) + ' (' + sign + pct + '%)';
        changeEl.style.color = (d.change || 0) >= 0 ? '#34D399' : '#F87171';
      }"""

NEW_POLL = """      // Keep D in step with what was just painted. The 1D performance label is
      // derived from D.change/D.changePct, so updating only the DOM would let
      // the badge move while the label below the chart kept the load-time
      // numbers — the two would silently stop matching between polls.
      if (d.price      != null) D.price     = Number(d.price);
      if (d.change     != null) D.change    = Number(d.change);
      if (d.change_pct != null) D.changePct = Number(d.change_pct);
      var priceEl  = document.querySelector('.price-val');
      var changeEl = document.querySelector('.price-change');
      if (priceEl) priceEl.textContent = '$' + (d.price || 0).toFixed(2);
      if (changeEl) {
        changeEl.textContent = fmtChange(d.change, d.change_pct);
        changeEl.style.color = (d.change || 0) >= 0 ? '#34D399' : '#F87171';
      }
      // Only 1D's label depends on the quote; every other tab is chart-derived
      // and unaffected, so this repaints nothing it does not have to.
      if (S.tf === '1D') renderChart();"""

REPLACEMENTS = [
    ("chart line: bezier -> straight segments", OLD_PATH, NEW_PATH),
    ("y-axis ticks to 2dp", OLD_TICK, NEW_TICK),
    ("periodPerf/fmtChange helpers + renderChart", OLD_RENDERCHART, NEW_RENDERCHART),
    ("renderAnalysis uses periodPerf", OLD_RA, NEW_RA),
    ("badge uses fmtChange", OLD_BADGE, NEW_BADGE),
    ("loadAnalysis fetches the live quote", OLD_FETCH, NEW_FETCH),
    ("_applyToD prefers the live quote", OLD_APPLY, NEW_APPLY),
    ("price poll updates D + repaints 1D label", OLD_POLL, NEW_POLL),
]

# Must survive untouched.
UNTOUCHED = [
    "fetch('/api/ticker/'    + tk).then(r => r.ok ? r.json() : {}),",
    "  }, 30000);",
    "var d = await fetch('/api/price/' + S.ticker).then(function(r){ return r.json(); });",
    "<span class=\"id-price price-val\">$${D.price.toFixed(2)}</span>",
]

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

    before_bezier = len(re.findall(r"lp \+= ` C", decoded))
    print(f"before: {before_bezier} bezier-emitting line(s)")

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

    assert len(re.findall(r"lp \+= ` C", decoded2)) == 0, "a bezier segment survived"
    # Count the definition and the real call sites separately — matching a bare
    # "periodPerf(" also catches the prose references in the comments.
    assert decoded2.count("function periodPerf(") == 1, "periodPerf must be defined exactly once"
    assert decoded2.count("periodPerf(S.tf)") == 2, "periodPerf must be called by both renderers"
    assert decoded2.count("function fmtChange(") == 1, "fmtChange must be defined once"
    # Scoped to this page's chart deliberately. Two other toFixed(0) calls exist
    # in the bundle and are NOT touched: runScan()'s screener revenue pills and
    # buildSvgRadar()'s labels. Neither is a price/change figure on the analysis
    # page, so widening this would be scope creep, not an audit.
    assert OLD_TICK not in decoded2, "the 0dp y-axis tick survived"
    assert decoded2.count("/api/price/") == 2, "expected the poll's and loadAnalysis's quote fetch"
    assert decoded2.count("/api/ticker/") == 1, "loadAnalysis's /api/ticker fetch must remain"

    for s in UNTOUCHED:
        assert s in decoded2, f"untouched line went missing: {s}"
    for guard in WORLD_GRID_GUARDS:
        assert guard in decoded2, f"world-grid guard missing: {guard}"

    print("verify OK: no beziers left, one perf definition, one formatter, "
          "world-grid intact, JSON round-trips")
    return 0


if __name__ == "__main__":
    sys.exit(main())
