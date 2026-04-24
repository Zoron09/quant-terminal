"""Patch Bug 2 (Finnhub EPS wiring) and Bug 3 (recency check) in-place.
Uses line-number-based replacement to avoid unicode matching issues.
"""
import pathlib, sys

path = pathlib.Path('pages/15_stock_detail.py')
lines = path.read_text(encoding='utf-8').splitlines(keepends=True)

# Find anchor lines
eps_comment_line    = None
recency_comment_line = None

for i, line in enumerate(lines):
    stripped = line.rstrip('\r\n')
    if stripped.endswith('\u2500\u2500\u2500\u2500') and 'EPS YoY' in stripped and eps_comment_line is None:
        eps_comment_line = i
    if stripped.endswith('\u2500\u2500\u2500\u2500') and 'Recency check' in stripped and recency_comment_line is None:
        recency_comment_line = i

print(f"EPS YoY comment at line: {eps_comment_line}")
print(f"Recency check comment at line: {recency_comment_line}")

if eps_comment_line is None or recency_comment_line is None:
    print("ERROR: Could not find anchor lines")
    sys.exit(1)

# ── Replacement for EPS YoY block (lines eps_comment_line .. recency_comment_line-2) ──
new_eps_block = [
    "    # -- EPS YoY (BUG 2 FIX: Finnhub=primary adjusted, FMP=secondary, EDGAR=fallback)\n",
    "    # _date_first_yoy enforces strict source lock: same-source YoY pairs only.\n",
    "    eps_fh_clean = _sane_eps(fh_eps)\n",
    "\n",
    "    # Pass 1: Finnhub vs FMP (each source pairs only with itself inside the pool)\n",
    "    eps_yoy_final, eps_labels_final, eps_yoy_ends = _date_first_yoy(\n",
    "        eps_fh_clean, fh_eps_end, eps_fmp_clean, fmp_eps_end\n",
    "    )\n",
    "    # Pass 2: if < 3 YoY points, also attempt Finnhub vs EDGAR\n",
    "    if len(eps_yoy_final) < 3:\n",
    "        eps_yoy_e2, eps_labels_e2, eps_ends_e2 = _date_first_yoy(\n",
    "            eps_fh_clean, fh_eps_end, eps_edgar_clean, edgar_eps_end\n",
    "        )\n",
    "        if len(eps_yoy_e2) > len(eps_yoy_final):\n",
    "            eps_yoy_final    = eps_yoy_e2\n",
    "            eps_labels_final = eps_labels_e2\n",
    "            eps_yoy_ends     = eps_ends_e2\n",
    "\n",
    "    # Raw EPS for pre-profit check: prefer Finnhub > FMP > EDGAR\n",
    "    if eps_fh_clean:\n",
    "        eps_raw_final      = eps_fh_clean\n",
    "        eps_raw_ends_final = fh_eps_end\n",
    "    elif eps_fmp_clean:\n",
    "        eps_raw_final      = eps_fmp_clean\n",
    "        eps_raw_ends_final = fmp_eps_end\n",
    "    else:\n",
    "        eps_raw_final      = eps_edgar_clean\n",
    "        eps_raw_ends_final = edgar_eps_end\n",
    "    sources['eps'] = 'Finnhub|FMP|EDGAR' if eps_yoy_final else 'insufficient'\n",
]

# EPS block spans from eps_comment_line to recency_comment_line - 1 (exclusive, last is blank line)
# Find the blank line between them
eps_block_end = recency_comment_line - 1  # the blank line before recency comment

# ── Replacement for Recency block ──────────────────────────────────────────────
# Find end of recency block (last line before 'return {')
recency_block_end = None
for i in range(recency_comment_line, len(lines)):
    if lines[i].strip().startswith('return {'):
        recency_block_end = i - 1  # the blank line before return
        break

print(f"EPS block: lines {eps_comment_line}-{eps_block_end}")
print(f"Recency block: lines {recency_comment_line}-{recency_block_end}")

new_recency_block = [
    "    # -- Recency check (BUG 3 FIX) -----------------------------------------\n",
    "    # Use max end date across ALL rev sources (FMP + EDGAR), not EDGAR-only.\n",
    "    # Old code used edgar_rev_end -> false INSUFFICIENT when FMP has data\n",
    "    # but EDGAR lags (e.g. small caps not well covered by EDGAR XBRL).\n",
    "    all_rev_ends_combined = [e for e in (fmp_rev_end or []) + (edgar_rev_end or []) if e]\n",
    "    if not _is_recent(all_rev_ends_combined):\n",
    "        rev_yoy_final, rev_labels_final = [], []\n",
    "        rev_raw_final, rev_raw_ends_final = [], []\n",
    "        sources['rev'] = 'insufficient'\n",
]

# Apply: rebuild lines list with replacements
# First replace EPS block, then recency block (do recency first to avoid offset issues)
# Replace recency block
new_lines = (
    lines[:recency_comment_line] +
    new_recency_block +
    ["\n"] +  # blank line before 'return {'
    lines[recency_block_end + 1:]
)

# Now find the new position of eps comment (unchanged offset since we replaced below it)
new_lines = (
    new_lines[:eps_comment_line] +
    new_eps_block +
    ["\n"] +  # blank line before recency section
    new_lines[eps_block_end + 1:]
)

path.write_text(''.join(new_lines), encoding='utf-8')
print("\nBoth patches applied.")
print(f"Total lines: {len(new_lines)}")
