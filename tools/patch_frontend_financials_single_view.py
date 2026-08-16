r"""One-shot patcher: Financials card becomes a single Revenue / Net Margin /
EPS view, with the Income Statement / Balance Sheet / Cash Flow tab strip gone.

Follows the project's mandated flow: decode the __bundler/template JSON ->
exact replacements -> re-encode with <\/ escaping -> write back. Every
replacement asserts exactly one match before it is applied.

Pairs with the api/server.py change that stops fetching tk.quarterly_balance_sheet
and tk.quarterly_cashflow and drops balance_sheet/cash_flow from the response, so
the data is genuinely gone rather than merely unrendered.

SIX replacements:
  1. finContentHtml() loses its balance/cashflow branch and the S.finTab test -
     it now always renders the income rows. The six <tr>s, the .fin-scroll /
     .fin-tbl markup, the .ind indent class and the pos/neg colouring are copied
     through byte-for-byte from what the Income Statement tab already rendered.
  2. the tab strip markup (div.tabs#fin-tabs and its three div.tab children)
  3. the #fin-tabs click listener
  4. _applyToD's D.bal / D.cf assignments (their source keys no longer exist)
  5. bal/cf in the D seed
  6. S.finTab, which nothing reads once the tabs are gone

DELIBERATELY NOT TOUCHED: the quarter columns (still D.qs, same count); every
number and its formatting; D.val and the response's valuation block; the .tabs
/.tab CSS rules, which are left in place rather than hunted down - unused CSS is
a /simplify matter, not a behaviour change. World grid CSS, #world's box,
PAGES, nav() and the journal redirect all asserted byte-present after.
"""
import json
import re
import sys
from pathlib import Path

INDEX = Path(__file__).resolve().parent.parent / "frontend" / "index.html"


def slice_between(src, start_anchor, end_anchor):
    i = src.index(start_anchor)
    j = src.index(end_anchor, i) + len(end_anchor)
    return src[i:j]


NEW_FIN = r"""// Single view: Revenue, Net Margin and EPS (Adj), each followed by its own YoY
// row. The Balance Sheet and Cash Flow branches are gone along with the tab
// strip that selected them, and /api/financials no longer fetches or returns
// either one - so there is no hidden panel here, there is no second dataset.
// Everything below is the Income Statement tab's own markup, unchanged.
function finContentHtml() {
  if (!D.qs || !D.qs.length) {
    // Two different empty states, deliberately worded differently: still
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
"""

OLD_TABS = (
    '        <div class="card">\n'
    '          <div class="card-hd">FINANCIALS</div>\n'
    '          <div class="tabs" id="fin-tabs">\n'
    "            <div class=\"tab${S.finTab==='income' ?' on':''}\" data-tab=\"income\">Income Statement</div>\n"
    "            <div class=\"tab${S.finTab==='balance'?' on':''}\" data-tab=\"balance\">Balance Sheet</div>\n"
    "            <div class=\"tab${S.finTab==='cashflow'?' on':''}\" data-tab=\"cashflow\">Cash Flow</div>\n"
    '          </div>\n'
    '          <div id="fin-content">${finContentHtml()}</div>\n'
    '        </div>\n'
)
NEW_TABS = (
    '        <div class="card">\n'
    '          <div class="card-hd">FINANCIALS</div>\n'
    '          <div id="fin-content">${finContentHtml()}</div>\n'
    '        </div>\n'
)

OLD_LISTENER = (
    "  document.getElementById('fin-tabs').addEventListener('click', e => {\n"
    "    const t = e.target.closest('.tab'); if (!t) return;\n"
    "    S.finTab = t.dataset.tab; renderAnalysis();\n"
    "  });\n"
)
NEW_LISTENER = ""

OLD_APPLY = (
    "  D.bal = (a.financials && a.financials.balance_sheet) || {};\n"
    "  D.cf  = (a.financials && a.financials.cash_flow)    || {};\n"
    "  D.val = (a.financials && a.financials.valuation)    || {};\n"
)
NEW_APPLY = (
    "  // balance_sheet / cash_flow are no longer fetched or returned by\n"
    "  // /api/financials, and nothing renders them - the card is a single\n"
    "  // Revenue / Net Margin / EPS view now.\n"
    "  D.val = (a.financials && a.financials.valuation)    || {};\n"
)

OLD_SEED = "  bal: {}, cf: {}, val: {}\n"
NEW_SEED = "  val: {}\n"

OLD_STATE = "  page: 'home', ticker: '', tf: '1Y', finTab: 'income',\n"
NEW_STATE = "  page: 'home', ticker: '', tf: '1Y',\n"


def main() -> int:
    html = INDEX.read_text(encoding="utf-8")
    m = re.search(r'(<script type="__bundler/template">)(.*?)(</script>)', html, re.DOTALL)
    if not m:
        print("bundler template not found")
        return 1
    d = json.loads(m.group(2))

    old_fin = slice_between(
        d, "function finContentHtml() {\n",
        "  return thead + tbody + '</tbody></table></div>';\n}\n")

    reps = [
        ("finContentHtml -> single view", old_fin,      NEW_FIN),
        ("remove tab strip markup",       OLD_TABS,     NEW_TABS),
        ("remove #fin-tabs listener",     OLD_LISTENER, NEW_LISTENER),
        ("_applyToD drop bal/cf",         OLD_APPLY,    NEW_APPLY),
        ("D seed drop bal/cf",            OLD_SEED,     NEW_SEED),
        ("S drop finTab",                 OLD_STATE,    NEW_STATE),
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
    d2 = json.loads(re.search(r'<script type="__bundler/template">(.*?)</script>',
                              html2, re.DOTALL).group(1))

    # Every trace of the tabs and the two removed statements must be gone from
    # the CODE. The comments this patch adds name what was removed on purpose -
    # they are the record of why the card is single-view - so comment lines are
    # excluded by matching the marker rather than by matching their text.
    code_lines = [l for l in d2.splitlines() if not l.lstrip().startswith("//")]
    code = "\n".join(code_lines)
    for banned in ("finTab", "fin-tabs", "Balance Sheet", "Cash Flow",
                   "D.bal", "D.cf", "balance_sheet", "cash_flow",
                   'data-tab="income"'):
        assert banned not in code, f"still present after patch: {banned}"
    # ...and the three kept rows, with their deltas, must all survive
    for need in ("<tr><td>Revenue</td>", '<tr><td class="ind">Rev YoY</td>',
                 "<tr><td>Net Margin</td>", '<tr><td class="ind">Margin YoY</td>',
                 "<tr><td>EPS (Adj)</td>", '<tr><td class="ind">EPS YoY</td>',
                 'class="fin-scroll"', 'class="fin-tbl"', 'id="fin-content"',
                 "function finContentHtml()", "D.qs.map"):
        assert need in d2, f"missing after patch: {need}"
    assert d2.count("function finContentHtml()") == 1
    assert d2.count('<div class="card-hd">FINANCIALS</div>') == 1
    # the surgical-patch and staged-loading wiring must be untouched
    for need in ("function patchSlowSections()", "let _analysisToken = 0;",
                 "const PENDING", 'id="c33-badge"', 'id="stats-grid"'):
        assert need in d2, f"staged-loading wiring lost: {need}"
    for guard in ("#page-home     { position: absolute; left: 100vw; top: 0;",
                  "#page-analysis { position: absolute; left: 100vw; top: 100vh;",
                  "#page-screener { position: absolute; left: 0;     top: 0;",
                  "#page-journal  { position: absolute; left: 200vw; top: 0;",
                  "#world { position: absolute; width: 300vw; height: 300vh; top: 0; left: -100vw;",
                  "if (page === 'journal') { window.location.href = '/journal'; return; }"):
        assert guard in d2, f"world-grid guard missing: {guard}"

    print("verify OK: tabs gone, single income view kept with all six rows, "
          "staged-loading wiring intact, world-grid intact, JSON round-trips")
    return 0


if __name__ == "__main__":
    sys.exit(main())
