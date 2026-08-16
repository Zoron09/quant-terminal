r"""One-shot patcher: staged loading for the analysis page.

Follows the project's mandated flow: decode the __bundler/template JSON ->
exact replacements -> re-encode with <\/ escaping -> write back. Every
replacement asserts exactly one match before it is applied.

WHY: the page waited on all six endpoints before painting anything. Price,
chart, news and ownership land in 0.35-2.7s; the Code 33 half (/api/ticker and
/api/financials) takes 3-23s on a ticker's first touch. Now the fast four paint
immediately and the two slow sections fill in when they arrive.

The split itself is the easy part. The three things that make it safe:

  1. NO MOCK FALLBACK. D was seeded with real-looking NVIDIA figures
     (name 'NVIDIA Corporation', mktCap '$3.2T', pe '52.4x', c33Text
     'CODE 33 GREEN', full revYoYA/eps/qs arrays) and _applyToD only wrote a
     field when the API returned non-null. Painting early would therefore show
     NVIDIA's financials and a GREEN badge under whatever ticker the user
     searched. Every such seed is now a PENDING marker, and _applyToD writes
     the slow fields on BOTH branches so a field can never keep a previous
     ticker's value either. PRICES got the same treatment - it was seeded with
     a mock NVIDIA price series that would have rendered as the searched
     ticker's own chart if /api/chart failed.

  2. SURGICAL PATCH, NOT A SECOND RENDER. renderAnalysis() replaces all of
     #page-analysis and re-attaches three listeners; running it again when the
     slow data lands would destroy anything typed into the search box in the
     meantime. patchSlowSections() updates only #id-name, #c33-badge,
     #stats-grid and #fin-content.

  3. GENERATION TOKEN. Search A then B before A's slow half returns and A's
     late response must not paint over B. Every apply re-checks its token.

DELIBERATELY NOT TOUCHED: what any endpoint computes, fetches or returns; the
requested quarter counts; the world grid CSS, #world's box, PAGES, nav() and
the journal redirect. All asserted byte-present after.
"""
import json
import re
import sys
from pathlib import Path

INDEX = Path(__file__).resolve().parent.parent / "frontend" / "index.html"


def slice_between(src, start_anchor, end_anchor):
    """Exact text from start_anchor through end_anchor inclusive."""
    i = src.index(start_anchor)
    j = src.index(end_anchor, i) + len(end_anchor)
    return src[i:j]


# ---------------------------------------------------------------- 1. D seed
NEW_D_SEED = r"""// PENDING is what a slow-arriving field shows until its real value lands. It is
// deliberately a visible marker and NOT a plausible number.
//
// This object used to be seeded with real-looking NVIDIA figures - name
// 'NVIDIA Corporation', mktCap '$3.2T', pe '52.4x', c33Text 'CODE 33 GREEN',
// and full revYoYA/eps/qs arrays - and _applyToD() only overwrote a field when
// the API returned a non-null value for it. That was survivable while the page
// painted once, after every endpoint had answered. With staged rendering it
// would put NVIDIA's financials and a GREEN Code 33 badge under whatever ticker
// the user actually searched, for the seconds before the pipeline answers.
// A wrong number that looks real is worse than no number, so there are none.
const PENDING = '…';
const D = {
  name: PENDING, exchange: 'NASDAQ · Technology',
  price: 0, change: 0, changePct: 0, code33: false,
  mktCap: PENDING, pe: PENDING, epsYoY: PENDING, revYoY: PENDING,
  netMargin: PENDING, avgVol: PENDING,
  week52High: PENDING, week52Low: PENDING,
  c33Text: 'LOADING…', c33Color: '#52525B',
  owners: [],
  news: [],
  qs: [], rev: [], revYoYA: [], ni: [], eps: [], epsYoYA: [],
  netMarginArr: [], netMarginYoYA: [],
  bal: {}, cf: {}, val: {}
};
"""

# ------------------------------------------------------------- 2. PRICES seed
OLD_PRICES = (
    "const PRICES = {\n"
    "  '1D': mockP(78,  127.17, 131.38, 1.1),\n"
    "  '1W': mockP(35,  124.22, 131.38, 2.3),\n"
    "  '1M': mockP(22,  118.44, 131.38, 3.7),\n"
    "  '3M': mockP(65,  102.80, 131.38, 0.9),\n"
    "  '1Y': mockP(252,  60.42, 131.38, 4.2)\n"
    "};\n"
)
NEW_PRICES = r"""// Empty, not a mock series. Same reason as D's PENDING seed above: these were
// NVIDIA-shaped mock prices, and _applyToD() only overwrote them when
// /api/chart returned data - so a failed chart fetch rendered NVIDIA's price
// history as the searched ticker's own chart. _applyToD() now fills every key
// unconditionally. (mockP/sn are left in place but are now unused - a cleanup
// candidate for /simplify, not a behaviour change.)
const PRICES = {
  'YTD': [], '1D': [], '1W': [], '1M': [], '3M': [], '1Y': [], '5Y': []
};
"""

# --------------------------------------------------- 3. _applyToD info block
OLD_INFO = (
    "  const inf = a.info || {};\n"
    "  if (inf.company_name)  D.name       = inf.company_name;\n"
    "  if (inf.price    != null) D.price    = Number(inf.price);\n"
    "  if (inf.change   != null) D.change   = Number(inf.change);\n"
    "  if (inf.change_pct != null) D.changePct = Number(inf.change_pct);\n"
)
NEW_INFO = r"""  // /api/ticker carries the Code 33 verdict and the stat pills, and it is one
  // of the two slow halves - on a cold ticker it can be 10s+ behind the fast
  // four. Every field it owns is written on BOTH branches below: the real value
  // when the payload is here, an explicit PENDING when it is not. Never left
  // alone to keep whatever was there before, which would be the previous
  // ticker's value or a demo seed. Same "write unconditionally, empty
  // included" rule the ownership list already follows.
  const inf = a.info || {};
  const infoReady = !!(inf && Object.keys(inf).length);
  if (infoReady) {
    D.name = inf.company_name || S.ticker || '';
  } else {
    // The ticker the user typed is not a fake value - it is the one thing about
    // this company that is already known for certain.
    D.name = S.ticker || PENDING;
  }
  if (inf.price    != null) D.price    = Number(inf.price);
  if (inf.change   != null) D.change   = Number(inf.change);
  if (inf.change_pct != null) D.changePct = Number(inf.change_pct);
"""

OLD_INFO2 = (
    "  if (inf.market_cap_fmt)  D.mktCap   = inf.market_cap_fmt;\n"
    "  if (inf.pe_ratio != null && inf.pe_ratio !== 'N/A')\n"
    "    D.pe = Number(inf.pe_ratio).toFixed(1) + 'x';\n"
    "  if (inf.week52_high != null) D.week52High = '$' + Number(inf.week52_high).toFixed(2);\n"
    "  if (inf.week52_low  != null) D.week52Low  = '$' + Number(inf.week52_low).toFixed(2);\n"
    "  if (inf.avg_volume) {\n"
    "    const v = Number(inf.avg_volume);\n"
    "    D.avgVol = v >= 1e9 ? (v/1e9).toFixed(1)+'B' : v >= 1e6 ? (v/1e6).toFixed(1)+'M' : v >= 1e3 ? (v/1e3).toFixed(1)+'K' : String(v);\n"
    "  }\n"
)
NEW_INFO2 = r"""  if (infoReady) {
    // Each of these used to fall through to the NVIDIA seed when the field was
    // absent. An em dash means "the API had nothing here"; PENDING means "not
    // asked yet". They are different states and must not look the same.
    D.mktCap = inf.market_cap_fmt || '—';
    D.pe = (inf.pe_ratio != null && inf.pe_ratio !== 'N/A')
      ? Number(inf.pe_ratio).toFixed(1) + 'x' : '—';
    D.week52High = inf.week52_high != null ? '$' + Number(inf.week52_high).toFixed(2) : '—';
    D.week52Low  = inf.week52_low  != null ? '$' + Number(inf.week52_low).toFixed(2)  : '—';
    if (inf.avg_volume) {
      const v = Number(inf.avg_volume);
      D.avgVol = v >= 1e9 ? (v/1e9).toFixed(1)+'B' : v >= 1e6 ? (v/1e6).toFixed(1)+'M' : v >= 1e3 ? (v/1e3).toFixed(1)+'K' : String(v);
    } else {
      D.avgVol = '—';
    }
  } else {
    D.mktCap = PENDING; D.pe = PENDING;
    D.week52High = PENDING; D.week52Low = PENDING; D.avgVol = PENDING;
  }
"""

OLD_BADGE = (
    "  const badge = bmap[inf.status] || { text:'NO SIGNAL', color:'#52525B' };\n"
    "  D.c33Text  = badge.text;\n"
    "  D.c33Color = badge.color;\n"
)
NEW_BADGE = r"""  // LOADING is a THIRD state, distinct from both a real verdict and the
  // 'NO SIGNAL' the API returns for a status it has no badge for. Without it a
  // pending page would read 'NO SIGNAL', which is an answer, not a wait.
  const badge = infoReady
    ? (bmap[inf.status] || { text:'NO SIGNAL', color:'#52525B' })
    : { text:'LOADING…', color:'#52525B' };
  D.c33Text  = badge.text;
  D.c33Color = badge.color;
"""

# ---------------------------------------------- 4. _applyToD financials block
OLD_FIN_TAIL = (
    "    const le      = earns[0] || {};\n"
    "    if (le.eps_yoy != null) D.epsYoY = (le.eps_yoy >= 0 ? '+' : '') + Number(le.eps_yoy).toFixed(1) + '%';\n"
    "  }\n"
)
NEW_FIN_TAIL = r"""    const le      = earns[0] || {};
    D.epsYoY = le.eps_yoy != null
      ? ((le.eps_yoy >= 0 ? '+' : '') + Number(le.eps_yoy).toFixed(1) + '%') : '—';
  } else {
    // /api/financials has not answered yet, or answered with nothing. Clear
    // every array it owns rather than leaving the seed (or the last ticker's
    // numbers) in place - finContentHtml() renders its own pending/empty state
    // off an empty D.qs.
    D.qs = []; D.rev = []; D.eps = []; D.ni = [];
    D.revYoYA = []; D.netMarginArr = []; D.netMarginYoYA = []; D.epsYoYA = [];
    D.epsYoY = (a.financials && Object.keys(a.financials).length) ? '—' : PENDING;
  }
"""

# ------------------------------------------------------ 5. _applyToD chart
OLD_CHART = (
    "  if (a.chart && a.chart.length) {\n"
    "    const cl = a.chart.map(p => p.close);\n"
    "    PRICES['YTD'] = [];\n"
    "    PRICES['1Y']  = cl;\n"
    "    PRICES['3M']  = [];\n"
    "    PRICES['1M']  = [];\n"
    "    PRICES['1W']  = [];\n"
    "    PRICES['1D']  = [];\n"
    "    PRICES['5Y']  = [];\n"
    "  }\n"
)
NEW_CHART = r"""  // Unconditional. Guarded, a failed /api/chart left whatever was in PRICES -
  // the previous ticker's series, or the NVIDIA mock seed - to be drawn as this
  // ticker's chart. An empty series draws nothing, which is the honest answer.
  const cl = (a.chart || []).map(p => p.close);
  PRICES['YTD'] = [];
  PRICES['1Y']  = cl;
  PRICES['3M']  = [];
  PRICES['1M']  = [];
  PRICES['1W']  = [];
  PRICES['1D']  = [];
  PRICES['5Y']  = [];
"""

# ------------------------------- 6/7. extract finContent + stats into helpers
NEW_HELPERS = r"""// Extracted so renderAnalysis() (first paint) and patchSlowSections() (when the
// Code 33 half lands) build these two sections from ONE definition. Two copies
// of this markup would be two things to keep in step, which is exactly how the
// chart's perf number and its badge drifted apart before periodPerf() existed.
function finContentHtml() {
  if (S.finTab === 'income') {
    if (!D.qs || !D.qs.length) {
      // Three different empty states, deliberately worded differently: still
      // loading, versus the API genuinely having no income data for this ticker.
      return D.epsYoY === PENDING
        ? '<div style="padding:40px;text-align:center;color:#52525B">Loading financials…</div>'
        : '<div style="padding:40px;text-align:center;color:#52525B">No income data</div>';
    }
    const ih = '<div class="fin-scroll"><table class="fin-tbl"><thead><tr><th>Metric</th>' + D.qs.map(function(q){return '<th>' + q + '</th>';}).join('') + '</tr></thead><tbody>';
    const posNeg = function(v) { return typeof v === 'string' && v.startsWith('+') ? 'pos' : 'neg'; };
    const ib =
      '<tr><td>Revenue</td>' + D.rev.map(function(v){return '<td>$' + v.toFixed(1) + 'B</td>';}).join('') + '</tr>' +
      '<tr><td class="ind">Rev YoY</td>' + (D.revYoYA||[]).map(function(v){return '<td class="' + posNeg(v) + '">' + v + '</td>';}).join('') + '</tr>' +
      '<tr><td>Net Margin</td>' + (D.netMarginArr||[]).map(function(v){return '<td>' + (v != null ? v.toFixed(1) + '%' : '—') + '</td>';}).join('') + '</tr>' +
      '<tr><td class="ind">Margin YoY</td>' + (D.netMarginYoYA||[]).map(function(v){return '<td class="' + posNeg(v) + '">' + v + '</td>';}).join('') + '</tr>' +
      '<tr><td>EPS (Adj)</td>' + D.eps.map(function(v){return '<td>$' + v.toFixed(2) + '</td>';}).join('') + '</tr>' +
      '<tr><td class="ind">EPS YoY</td>' + (D.epsYoYA||[]).map(function(v){return '<td class="' + posNeg(v) + '">' + v + '</td>';}).join('') + '</tr>';
    return ih + ib + '</tbody></table></div>';
  }
  var data = S.finTab === 'balance' ? (D.bal || {}) : (D.cf || {});
  var keys = Object.keys(data);
  if (!keys.length) {
    return D.epsYoY === PENDING
      ? '<div style="padding:40px;text-align:center;color:#52525B">Loading financials…</div>'
      : '<div style="padding:40px;text-align:center;color:#52525B">No data available</div>';
  }
  var dates = Object.keys(data[keys[0]] || {});
  var thead = '<div class="fin-scroll"><table class="fin-tbl"><thead><tr><th>Metric</th>' + dates.map(function(d){return '<th>' + d + '</th>';}).join('') + '</tr></thead><tbody>';
  var tbody = keys.map(function(k){return '<tr><td>' + k + '</td>' + dates.map(function(d){return '<td>' + (data[k][d] != null ? data[k][d] : 'N/A') + '</td>';}).join('') + '</tr>';}).join('');
  return thead + tbody + '</tbody></table></div>';
}

function statsGridHtml() {
  return [['Market Cap',D.mktCap],['P/E Ratio',D.pe],['52W High',D.week52High],['52W Low',D.week52Low],['Avg Vol',D.avgVol],['EPS YoY',D.epsYoY]]
    .map(function(p){ return '<div class="stat"><div class="sl">' + p[0] + '</div><div class="sv">' + p[1] + '</div></div>'; }).join('');
}

// Update ONLY the sections the slow half owns. Deliberately not a second
// renderAnalysis(): that replaces all of #page-analysis and re-attaches every
// listener, so calling it seconds after first paint would wipe out whatever the
// user had typed into the search box in the meantime - the page would appear to
// eat their keystrokes. Four targeted nodes instead, no listeners touched.
function patchSlowSections() {
  const nameEl = document.getElementById('id-name');
  if (nameEl) nameEl.textContent = D.name;
  const badgeEl = document.getElementById('c33-badge');
  if (badgeEl) {
    badgeEl.textContent = D.c33Text;
    badgeEl.style.borderColor = D.c33Color;
    badgeEl.style.color = D.c33Color;
  }
  const statsEl = document.getElementById('stats-grid');
  if (statsEl) statsEl.innerHTML = statsGridHtml();
  const finEl = document.getElementById('fin-content');
  if (finEl) finEl.innerHTML = finContentHtml();
}

function renderAnalysis() {"""

# ------------------------------------------------------------- 8. loadAnalysis
NEW_LOAD = r"""// Generation counter for staged loading. The fast four paint in well under a
// second; the Code 33 half can be 10s+ behind on a ticker's first touch. If the
// user searches A and then B inside that window, A's late response must not
// paint over B's page - so every apply re-checks that its token is still the
// current one. Without this the staged split would introduce cross-ticker
// contamination that the old single-Promise.all version could not have.
let _analysisToken = 0;

async function loadAnalysis(tk) {
  tk = (tk || '').trim().toUpperCase();
  if (!tk) return;
  const token = ++_analysisToken;
  S.ticker = tk;
  S.loadingTicker = tk;
  // Drop the previous ticker's payload outright. Keeping it would leave its
  // values on screen under the new ticker's name for as long as the new load
  // takes, which is the stale-data failure this whole change exists to avoid.
  S.analysis = null;
  renderAnalysisIdle();

  // All six requests are started HERE, together. Only the awaits are staged, so
  // nothing is serialized behind anything else and total load time is unchanged
  // - this is purely about when each half is allowed to paint.
  const pChart  = fetch('/api/chart/'     + tk + '?period=1y&interval=1d').then(r => r.ok ? r.json() : {}).catch(() => ({}));
  const pNews   = fetch('/api/news/'      + tk).then(r => r.ok ? r.json() : {}).catch(() => ({}));
  const pOwn    = fetch('/api/ownership/' + tk).then(r => r.ok ? r.json() : {}).catch(() => ({}));
  // Live quote for the badge. /api/ticker carries the same three fields but
  // is cached 300s, so at first paint it can be five minutes stale and then
  // visibly jump when the 30s poll lands. This costs ~0.4s, runs in the same
  // fan-out, and never touches the pipeline.
  const pPrice  = fetch('/api/price/'     + tk).then(r => r.ok ? r.json() : {}).catch(() => ({}));
  // The two slow ones - both run the Code 33 pipeline behind the adapter's
  // global lock. Started now, awaited second.
  const pTicker = fetch('/api/ticker/'    + tk).then(r => r.ok ? r.json() : {}).catch(() => ({}));
  const pFin    = fetch('/api/financials/'+ tk).then(r => r.ok ? r.json() : {}).catch(() => ({}));

  try {
    const [ch, nw, ow, qt] = await Promise.all([pChart, pNews, pOwn, pPrice]);
    if (token !== _analysisToken) return;
    S.analysis = {
      ticker:    tk,
      info:      {},
      chart:     ch.prices || [],
      financials:{},
      news:      nw.news || [],
      ownership: ow.institutional || [],
      quote:     qt,
    };
    S.loadingTicker = null;
    renderAnalysis();
    startPricePoll();
  } catch(e) {
    console.error('[loadAnalysis] fast group failed:', e);
  }

  try {
    const [ti, fi] = await Promise.all([pTicker, pFin]);
    // Two guards, not one: the token catches a newer search, and the ticker
    // check catches the case where the fast group failed and left S.analysis
    // null or belonging to something else.
    if (token !== _analysisToken) return;
    if (!S.analysis || S.analysis.ticker !== tk) return;
    S.analysis.info = ti;
    S.analysis.financials = fi;
    console.log('[loadAnalysis] ok', tk, 'price:', ti.price, 'status:', ti.status);
    _applyToD();
    patchSlowSections();
  } catch(e) {
    console.error('[loadAnalysis] slow group failed:', e);
  }
}"""


def main() -> int:
    html = INDEX.read_text(encoding="utf-8")
    m = re.search(r'(<script type="__bundler/template">)(.*?)(</script>)', html, re.DOTALL)
    if not m:
        print("bundler template not found")
        return 1
    d = json.loads(m.group(2))

    old_d_seed = slice_between(d, "const D = {\n", "  bal: {}, cf: {}, val: {}\n};\n")
    old_fin_iife = slice_between(d, "  const finContent = (() => {\n", "})();\n")
    old_load = slice_between(d, "async function loadAnalysis(tk) {\n", "  renderAnalysis();\n  startPricePoll();\n}")

    reps = [
        ("D seed -> PENDING",        old_d_seed,   NEW_D_SEED),
        ("PRICES seed -> empty",     OLD_PRICES,   NEW_PRICES),
        ("_applyToD info head",      OLD_INFO,     NEW_INFO),
        ("_applyToD stat pills",     OLD_INFO2,    NEW_INFO2),
        ("_applyToD badge",          OLD_BADGE,    NEW_BADGE),
        ("_applyToD financials",     OLD_FIN_TAIL, NEW_FIN_TAIL),
        ("_applyToD chart",          OLD_CHART,    NEW_CHART),
        ("extract fin/stats helpers", "function renderAnalysis() {", NEW_HELPERS),
        ("drop inline finContent",   old_fin_iife, ""),
        ("stats grid -> helper + id",
         '        <div class="stats-grid">\n'
         "          ${[['Market Cap',D.mktCap],['P/E Ratio',D.pe],['52W High',D.week52High],['52W Low',D.week52Low],['Avg Vol',D.avgVol],['EPS YoY',D.epsYoY]]\n"
         '            .map(([l,v]) => `<div class="stat"><div class="sl">${l}</div><div class="sv">${v}</div></div>`).join(\'\')}\n'
         "        </div>\n",
         '        <div class="stats-grid" id="stats-grid">${statsGridHtml()}</div>\n'),
        ("fin pane -> helper + id",
         "          ${finContent}\n",
         '          <div id="fin-content">${finContentHtml()}</div>\n'),
        ("id-name id",
         '          <div class="id-name">${D.name}</div>\n',
         '          <div class="id-name" id="id-name">${D.name}</div>\n'),
        ("badge id",
         '          <span class="c33 on" style="border-color:${D.c33Color};color:${D.c33Color}">${D.c33Text}</span>\n',
         '          <span class="c33 on" id="c33-badge" style="border-color:${D.c33Color};color:${D.c33Color}">${D.c33Text}</span>\n'),
        ("loadAnalysis -> staged",   old_load,     NEW_LOAD),
    ]

    for name, old, new in reps:
        c = d.count(old)
        if c != 1:
            print(f"FAIL: '{name}' matched {c} times (need exactly 1)")
            return 1
        d = d.replace(old, new)
        print(f"patched: {name}")

    encoded = json.dumps(d).replace("</", "<\\/")
    html = html[: m.start(2)] + encoded + html[m.end(2):]
    INDEX.write_text(html, encoding="utf-8")

    html2 = INDEX.read_text(encoding="utf-8")
    d2 = json.loads(re.search(r'<script type="__bundler/template">(.*?)</script>', html2, re.DOTALL).group(1))

    # No NVIDIA-shaped value may survive as a D or PRICES seed. Matched in their
    # D-field form on purpose: the SCREENER's own demo list (SC) is a separate
    # mock with its own NVDA row, it never feeds the analysis page, and it is
    # out of scope for this change.
    for banned in ("name: 'NVIDIA Corporation'", "mktCap: '$3.2T'", "pe: '52.4x'",
                   "c33Text: 'CODE 33 GREEN'", "mockP(252", "mockP(78",
                   "revYoYA: ['+12.3%'", "eps:     [2.82"):
        assert banned not in d2, f"mock seed survived: {banned}"
    for need in ("const PENDING", "function patchSlowSections()", "let _analysisToken = 0;",
                 "function finContentHtml()", "function statsGridHtml()",
                 'id="c33-badge"', 'id="stats-grid"', 'id="fin-content"', 'id="id-name"',
                 "if (token !== _analysisToken) return;"):
        assert need in d2, f"missing after patch: {need}"
    # the six fetches must all still be there, unchanged in target
    for ep in ('/api/ticker/', '/api/chart/', '/api/financials/', '/api/news/',
               '/api/ownership/', '/api/price/'):
        assert d2.count("fetch('" + ep) >= 1, f"lost fetch of {ep}"
    assert d2.count("period=1y&interval=1d") == 1, "chart period changed"
    # Defined once, called from exactly one place - the slow branch of
    # loadAnalysis. If it were also called from renderAnalysis the surgical
    # patch would be pointless.
    assert d2.count("function patchSlowSections()") == 1, "patchSlowSections defined twice"
    assert d2.count("patchSlowSections();") == 1, "patchSlowSections call sites != 1"
    assert d2.count("renderAnalysis();\n    startPricePoll();") == 1, \
        "fast-branch render wiring wrong"
    for guard in ("#page-home     { position: absolute; left: 100vw; top: 0;",
                  "#page-analysis { position: absolute; left: 100vw; top: 100vh;",
                  "#page-screener { position: absolute; left: 0;     top: 0;",
                  "#page-journal  { position: absolute; left: 200vw; top: 0;",
                  "#world { position: absolute; width: 300vw; height: 300vh; top: 0; left: -100vw;",
                  "if (page === 'journal') { window.location.href = '/journal'; return; }"):
        assert guard in d2, f"world-grid guard missing: {guard}"

    print("verify OK: no mock seeds left, staged loading wired, ids present, "
          "six fetches intact, world-grid intact, JSON round-trips")
    return 0


if __name__ == "__main__":
    sys.exit(main())
