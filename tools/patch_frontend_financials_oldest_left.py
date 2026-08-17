r"""One-shot patcher: reverse the Financials table's column order so the OLDEST
quarter is on the left and the newest on the right.

Follows the project's mandated flow: decode the __bundler/template JSON ->
exact replacement -> re-encode with <\/ escaping -> write back. The single
replacement asserts exactly one match.

PURE DISPLAY ORDER. No computed value is touched, nothing about what is fetched
changes, and `D` itself is NOT mutated - `.slice().reverse()` builds throwaway
copies for rendering only, so `_applyToD()` keeps writing newest-first exactly as
it does today and anything else reading those arrays sees the order it expects.

Why reversing the already-formatted strings is correct rather than lossy: each
YoY cell's pp delta is baked into its string by _applyToD(), computed against
that quarter's own predecessor. Reversing the array moves the cell, not its
contents, so every quarter keeps its own value AND its own delta. The oldest
quarter is the one _applyToD() gives no delta to (there is nothing older to
compare against), and after the reverse that unadorned cell lands leftmost -
which is where a reader expects a series to start from.
"""
import json
import re
import sys
from pathlib import Path

INDEX = Path(__file__).resolve().parent.parent / "frontend" / "index.html"

OLD = (
    "  const ih = '<div class=\"fin-scroll\"><table class=\"fin-tbl\"><thead><tr><th>Metric</th>' + D.qs.map(function(q){return '<th>' + q + '</th>';}).join('') + '</tr></thead><tbody>';\n"
    "  const posNeg = function(v) { return typeof v === 'string' && v.startsWith('+') ? 'pos' : 'neg'; };\n"
    "  const ib =\n"
    "    '<tr><td>Revenue</td>' + D.rev.map(function(v){return '<td>$' + v.toFixed(1) + 'B</td>';}).join('') + '</tr>' +\n"
    "    '<tr><td class=\"ind\">Rev YoY</td>' + (D.revYoYA||[]).map(function(v){return '<td class=\"' + posNeg(v) + '\">' + v + '</td>';}).join('') + '</tr>' +\n"
    "    '<tr><td>Net Margin</td>' + (D.netMarginArr||[]).map(function(v){return '<td>' + (v != null ? v.toFixed(1) + '%' : '—') + '</td>';}).join('') + '</tr>' +\n"
    "    '<tr><td class=\"ind\">Margin YoY</td>' + (D.netMarginYoYA||[]).map(function(v){return '<td class=\"' + posNeg(v) + '\">' + v + '</td>';}).join('') + '</tr>' +\n"
    "    '<tr><td>EPS (Adj)</td>' + D.eps.map(function(v){return '<td>$' + v.toFixed(2) + '</td>';}).join('') + '</tr>' +\n"
    "    '<tr><td class=\"ind\">EPS YoY</td>' + (D.epsYoYA||[]).map(function(v){return '<td class=\"' + posNeg(v) + '\">' + v + '</td>';}).join('') + '</tr>';\n"
)

NEW = (
    "  // Oldest quarter leftmost, newest rightmost - the reverse of the order\n"
    "  // _applyToD() builds these arrays in (it mirrors the API's newest-first\n"
    "  // earnings list). Reversed HERE, at render time, on throwaway copies:\n"
    "  // .slice() first so D is never mutated, because _applyToD() rebuilds from\n"
    "  // D on every patch and an in-place reverse would flip the table back and\n"
    "  // forth on each repaint. Display order only - every cell keeps its own\n"
    "  // value and its own pp delta, both of which are already baked into the\n"
    "  // string by _applyToD() against that quarter's own predecessor.\n"
    "  const cols   = (D.qs||[]).slice().reverse();\n"
    "  const rev    = (D.rev||[]).slice().reverse();\n"
    "  const revY   = (D.revYoYA||[]).slice().reverse();\n"
    "  const nmArr  = (D.netMarginArr||[]).slice().reverse();\n"
    "  const nmY    = (D.netMarginYoYA||[]).slice().reverse();\n"
    "  const epsArr = (D.eps||[]).slice().reverse();\n"
    "  const epsY   = (D.epsYoYA||[]).slice().reverse();\n"
    "  const ih = '<div class=\"fin-scroll\"><table class=\"fin-tbl\"><thead><tr><th>Metric</th>' + cols.map(function(q){return '<th>' + q + '</th>';}).join('') + '</tr></thead><tbody>';\n"
    "  const posNeg = function(v) { return typeof v === 'string' && v.startsWith('+') ? 'pos' : 'neg'; };\n"
    "  const ib =\n"
    "    '<tr><td>Revenue</td>' + rev.map(function(v){return '<td>$' + v.toFixed(1) + 'B</td>';}).join('') + '</tr>' +\n"
    "    '<tr><td class=\"ind\">Rev YoY</td>' + revY.map(function(v){return '<td class=\"' + posNeg(v) + '\">' + v + '</td>';}).join('') + '</tr>' +\n"
    "    '<tr><td>Net Margin</td>' + nmArr.map(function(v){return '<td>' + (v != null ? v.toFixed(1) + '%' : '—') + '</td>';}).join('') + '</tr>' +\n"
    "    '<tr><td class=\"ind\">Margin YoY</td>' + nmY.map(function(v){return '<td class=\"' + posNeg(v) + '\">' + v + '</td>';}).join('') + '</tr>' +\n"
    "    '<tr><td>EPS (Adj)</td>' + epsArr.map(function(v){return '<td>$' + v.toFixed(2) + '</td>';}).join('') + '</tr>' +\n"
    "    '<tr><td class=\"ind\">EPS YoY</td>' + epsY.map(function(v){return '<td class=\"' + posNeg(v) + '\">' + v + '</td>';}).join('') + '</tr>';\n"
)


def main() -> int:
    html = INDEX.read_text(encoding="utf-8")
    m = re.search(r'(<script type="__bundler/template">)(.*?)(</script>)', html, re.DOTALL)
    if not m:
        print("bundler template not found")
        return 1
    d = json.loads(m.group(2))

    c = d.count(OLD)
    if c != 1:
        print(f"FAIL: financials row builder matched {c} times (need exactly 1)")
        return 1
    d = d.replace(OLD, NEW)
    print("patched: financials table columns -> oldest left, newest right")

    encoded = json.dumps(d).replace("</", "<\\/")
    html = html[: m.start(2)] + encoded + html[m.end(2):]
    INDEX.write_text(html, encoding="utf-8")

    html2 = INDEX.read_text(encoding="utf-8")
    d2 = json.loads(re.search(r'<script type="__bundler/template">(.*?)</script>',
                              html2, re.DOTALL).group(1))
    assert OLD not in d2, "old row builder still present"
    for need in (".slice().reverse()", "const cols   = (D.qs||[]).slice().reverse();",
                 "cols.map(function(q)"):
        assert need in d2, f"missing after patch: {need}"
    # D must never be reversed in place, anywhere
    assert "D.qs.reverse()" not in d2 and "D.rev.reverse()" not in d2, "in-place reverse of D"
    assert d2.count(".slice().reverse()") == 7, \
        f"expected 7 reversed copies, found {d2.count('.slice().reverse()')}"
    # rows, styling and structure must be untouched
    for need in ("<tr><td>Revenue</td>", '<tr><td class="ind">Rev YoY</td>',
                 "<tr><td>Net Margin</td>", '<tr><td class="ind">Margin YoY</td>',
                 "<tr><td>EPS (Adj)</td>", '<tr><td class="ind">EPS YoY</td>',
                 'class="fin-scroll"', 'class="fin-tbl"', 'id="fin-content"',
                 "<th>Metric</th>", "function finContentHtml()"):
        assert need in d2, f"missing after patch: {need}"
    assert d2.count("function finContentHtml()") == 1
    # nothing from the earlier rounds may have moved
    for need in ("function patchSlowSections()", "let _analysisToken = 0;",
                 "const PENDING", "function periodPerf", "function fmtChange"):
        assert need in d2, f"earlier work disturbed: {need}"
    code = "\n".join(l for l in d2.splitlines() if not l.lstrip().startswith("//"))
    for banned in ("fin-tabs", "finTab", "Balance Sheet", "Cash Flow"):
        assert banned not in code, f"removed feature came back: {banned}"
    for guard in ("#page-home     { position: absolute; left: 100vw; top: 0;",
                  "#page-analysis { position: absolute; left: 100vw; top: 100vh;",
                  "#page-screener { position: absolute; left: 0;     top: 0;",
                  "#page-journal  { position: absolute; left: 200vw; top: 0;",
                  "#world { position: absolute; width: 300vw; height: 300vh; top: 0; left: -100vw;",
                  "if (page === 'journal') { window.location.href = '/journal'; return; }"):
        assert guard in d2, f"world-grid guard missing: {guard}"

    print("verify OK: columns reversed at render time, D not mutated, six rows and "
          "styling unchanged, earlier work intact, world-grid intact, JSON round-trips")
    return 0


if __name__ == "__main__":
    sys.exit(main())
