"""One-shot patcher for the News Scanner tab (Stage 1).

Follows the project's mandated flow: decode the __bundler/template JSON ->
exact string replacements -> re-encode with <\\/ escaping -> write back. Each
replacement asserts exactly one match.

STRICTLY ADDITIVE. Every replacement below re-emits the anchor text verbatim
and adds new lines around it — no existing world-grid line is modified, no
existing rule is edited, and the journal cell is left completely alone. The
four touch points are the ones signed off for this feature:

  1. one new page div            (#page-news, empty like every other page div)
  2. one new CSS rule            (#page-news, positioned ABOVE home)
  3. one new PAGES entry         (news, the previously-unused down direction)
  4. two gesture branches + two key bindings, matching the existing pattern

Geometry: home sits at left:100vw/top:0 inside #world, and the only cardinal
direction with nothing wired to it is DOWN from home. So the news page goes at
top:-100vh (above home) and its PAGES translate is y:+innerHeight. #world's own
300vw x 300vh box does NOT need changing: the only clipping rule in the file is
#viewport{overflow:hidden}, which clips to the screen, not to #world's bounds.
"""
import json
import re
import sys
from pathlib import Path

INDEX = Path(__file__).resolve().parent.parent / "frontend" / "index.html"

# --- 1. page div ----------------------------------------------------------
OLD_DIV = """<div id="page-home"></div>
      <div id="page-analysis"></div>"""

NEW_DIV = """<div id="page-home"></div>
      <div id="page-news"></div>
      <div id="page-analysis"></div>"""

# --- 2. CSS ---------------------------------------------------------------
OLD_CSS = """    #page-journal  { position: absolute; left: 200vw; top: 0; width: 100vw; height: 100vh; overflow-y: auto; overflow-x: hidden; -webkit-overflow-scrolling: touch; }"""

NEW_CSS = """    #page-journal  { position: absolute; left: 200vw; top: 0; width: 100vw; height: 100vh; overflow-y: auto; overflow-x: hidden; -webkit-overflow-scrolling: touch; }
    /* News Scanner. Sits ABOVE home — the one cardinal direction from home with
       nothing bound to it. Outside #world's declared box on purpose; nothing
       clips it, since #viewport is what clips and it clips to the screen. */
    #page-news     { position: absolute; left: 100vw; top: -100vh; width: 100vw; height: 100vh; overflow-y: auto; overflow-x: hidden; -webkit-overflow-scrolling: touch; background: #000000; }
    .ns-wrap       { max-width: 980px; margin: 0 auto; padding: 40px 24px 80px; }
    .ns-head       { display: flex; align-items: baseline; justify-content: space-between; gap: 16px; flex-wrap: wrap; margin-bottom: 6px; }
    .ns-title      { font-family: 'DM Serif Display', serif; font-size: 34px; color: #FAFAFA; letter-spacing: 0.3px; }
    .ns-sub        { font-family: 'IBM Plex Mono', monospace; font-size: 11px; color: #52525B; letter-spacing: 0.6px; text-transform: uppercase; }
    .ns-controls   { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; margin: 22px 0 18px; }
    .ns-toggle     { display: inline-flex; border: 1px solid #2A2A2E; border-radius: 6px; overflow: hidden; }
    .ns-toggle button { background: transparent; border: 0; color: #52525B; font-family: 'Inter', sans-serif; font-size: 12px; letter-spacing: 0.4px; padding: 8px 14px; cursor: pointer; }
    .ns-toggle button.on { background: #141416; color: #D4A843; }
    .ns-input      { background: #141416; border: 1px solid #2A2A2E; border-radius: 6px; color: #FAFAFA; font-family: 'Inter', sans-serif; font-size: 13px; padding: 8px 12px; outline: none; }
    .ns-input:focus { border-color: #D4A843; }
    .ns-btn        { background: #141416; border: 1px solid #2A2A2E; border-radius: 6px; color: #FAFAFA; font-family: 'Inter', sans-serif; font-size: 12px; padding: 8px 12px; cursor: pointer; }
    .ns-btn:hover  { border-color: #D4A843; color: #D4A843; }
    .ns-chips      { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 18px; }
    .ns-chip       { display: inline-flex; align-items: center; gap: 6px; background: #141416; border: 1px solid #2A2A2E; border-radius: 999px; padding: 4px 10px; font-family: 'IBM Plex Mono', monospace; font-size: 11px; color: #FAFAFA; }
    .ns-chip span  { color: #52525B; cursor: pointer; }
    .ns-chip span:hover { color: #F87171; }
    .ns-item       { background: #141416; border: 1px solid #2A2A2E; border-radius: 8px; padding: 14px 16px; margin-bottom: 8px; }
    .ns-item-top   { display: flex; align-items: center; gap: 10px; margin-bottom: 6px; }
    .ns-src        { font-family: 'IBM Plex Mono', monospace; font-size: 10px; color: #52525B; letter-spacing: 0.6px; text-transform: uppercase; }
    .ns-tkr        { font-family: 'IBM Plex Mono', monospace; font-size: 11px; color: #D4A843; }
    .ns-time       { font-family: 'IBM Plex Mono', monospace; font-size: 10px; color: #52525B; margin-left: auto; }
    .ns-headline   { font-family: 'Inter', sans-serif; font-size: 14px; color: #FAFAFA; line-height: 1.45; text-decoration: none; display: block; }
    .ns-headline:hover { color: #D4A843; }
    .ns-empty      { color: #52525B; font-family: 'Inter', sans-serif; font-size: 13px; padding: 40px 0; text-align: center; }
    .ns-health     { display: flex; gap: 14px; flex-wrap: wrap; font-family: 'IBM Plex Mono', monospace; font-size: 10px; color: #52525B; margin-bottom: 20px; }
    .ns-ok         { color: #34D399; }
    .ns-bad        { color: #F87171; }"""

# --- 3. PAGES entry -------------------------------------------------------
OLD_PAGES = """  journal:  { x: -window.innerWidth, y: 0 },
};"""

NEW_PAGES = """  journal:  { x: -window.innerWidth, y: 0 },
  // News Scanner lives ABOVE home, so reaching it translates #world DOWN.
  news:     { x: 0,                  y: window.innerHeight },
};"""

# --- 4a. touch: down-from-home, up-from-news ------------------------------
OLD_TOUCH = """    if (S.page === 'home') {
      if (dy < -THRESHOLD) { nav('analysis'); return; }
    } else if (S.page === 'analysis') {"""

NEW_TOUCH = """    if (S.page === 'home') {
      if (dy < -THRESHOLD) { nav('analysis'); return; }
      if (dy > THRESHOLD)  { goNews(); return; }
    } else if (S.page === 'news') {
      const newsPage = document.getElementById('page-news');
      const nScroll = newsPage ? newsPage.scrollTop : 0;
      if (dy < -THRESHOLD && nScroll <= 10) { nav('home'); return; }
    } else if (S.page === 'analysis') {"""

# --- 4b. keyboard ---------------------------------------------------------
OLD_KEYS = """  if (e.key === 'ArrowLeft'  && S.page === 'journal')  nav('home');
});"""

NEW_KEYS = """  if (e.key === 'ArrowLeft'  && S.page === 'journal')  nav('home');
  if (e.key === 'ArrowDown'  && S.page === 'home')     goNews();
  if (e.key === 'ArrowUp'    && S.page === 'news')     nav('home');
});"""

# --- 5. the feature itself, appended at the end of the bundled script -----
OLD_BOOT = """// or a screener card click.
</script>"""

NEW_BOOT = """// or a screener card click.

// ════════════════════════════════════════════════════════
//  NEWS SCANNER — Stage 1 (headlines only)
// ════════════════════════════════════════════════════════
// Entirely additive. Reads /api/news-scanner/*, which shares no route prefix,
// no cache and no code with /api/news (the ticker-scoped analysis-page feed).
// No catalyst tagging and no article text at this stage — Stages 2 and 3.
const NS_API = '/api/news-scanner';
const NS = { mode: 'market', q: '', items: [], status: null, watchlist: [], loading: false };

function nsEsc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function nsAgo(ts) {
  if (!ts) return '';
  const s = Math.max(0, Math.floor(Date.now() / 1000 - ts));
  if (s < 60) return s + 's ago';
  if (s < 3600) return Math.floor(s / 60) + 'm ago';
  if (s < 86400) return Math.floor(s / 3600) + 'h ago';
  return Math.floor(s / 86400) + 'd ago';
}

function renderNewsShell() {
  const el = document.getElementById('page-news');
  if (!el || el.dataset.built) return;
  el.dataset.built = '1';
  el.innerHTML = `
    <div class="ns-wrap">
      <div class="ns-head">
        <div class="ns-title">News Scanner</div>
        <div class="ns-sub" id="ns-session"></div>
      </div>
      <div class="ns-health" id="ns-health"></div>
      <div class="ns-controls">
        <div class="ns-toggle">
          <button id="ns-mode-market" class="on">Whole market</button>
          <button id="ns-mode-watch">Watchlist</button>
        </div>
        <input class="ns-input" id="ns-search" placeholder="Search today's headlines" style="flex:1;min-width:200px">
        <input class="ns-input" id="ns-add" placeholder="Add ticker" style="width:120px">
        <button class="ns-btn" id="ns-add-btn">Add</button>
        <button class="ns-btn" id="ns-refresh">Refresh</button>
      </div>
      <div class="ns-chips" id="ns-chips"></div>
      <div id="ns-list"></div>
    </div>`;

  el.querySelector('#ns-mode-market').onclick = () => { NS.mode = 'market'; nsSyncMode(); loadNewsFeed(); };
  el.querySelector('#ns-mode-watch').onclick  = () => { NS.mode = 'watchlist'; nsSyncMode(); loadNewsFeed(); };
  el.querySelector('#ns-refresh').onclick     = () => loadNewsFeed();
  el.querySelector('#ns-add-btn').onclick     = () => nsAddTicker();
  el.querySelector('#ns-add').addEventListener('keydown', e => { if (e.key === 'Enter') nsAddTicker(); });
  let t = null;
  el.querySelector('#ns-search').addEventListener('input', e => {
    NS.q = e.target.value.trim();
    clearTimeout(t);
    t = setTimeout(loadNewsFeed, 250);
  });
}

function nsSyncMode() {
  const m = document.getElementById('ns-mode-market');
  const w = document.getElementById('ns-mode-watch');
  if (!m || !w) return;
  m.classList.toggle('on', NS.mode === 'market');
  w.classList.toggle('on', NS.mode === 'watchlist');
}

async function nsAddTicker() {
  const input = document.getElementById('ns-add');
  if (!input) return;
  const t = (input.value || '').trim().toUpperCase();
  if (!t) return;
  input.value = '';
  try {
    const r = await fetch(`${NS_API}/watchlist/${encodeURIComponent(t)}`, { method: 'POST' });
    const d = await r.json();
    if (d.tickers) { NS.watchlist = d.tickers; nsRenderChips(); }
  } catch (err) { console.warn('[news-scanner] add failed', err); }
}

async function nsRemoveTicker(t) {
  try {
    const r = await fetch(`${NS_API}/watchlist/${encodeURIComponent(t)}`, { method: 'DELETE' });
    const d = await r.json();
    if (d.tickers) { NS.watchlist = d.tickers; nsRenderChips(); if (NS.mode === 'watchlist') loadNewsFeed(); }
  } catch (err) { console.warn('[news-scanner] remove failed', err); }
}

function nsRenderChips() {
  const el = document.getElementById('ns-chips');
  if (!el) return;
  el.innerHTML = NS.watchlist.length
    ? NS.watchlist.map(t => `<div class="ns-chip">${nsEsc(t)}<span data-t="${nsEsc(t)}">x</span></div>`).join('')
    : '<div class="ns-sub">Watchlist empty</div>';
  el.querySelectorAll('.ns-chip span').forEach(s => { s.onclick = () => nsRemoveTicker(s.dataset.t); });
}

function nsRenderHealth() {
  const el = document.getElementById('ns-health');
  const se = document.getElementById('ns-session');
  if (!el || !NS.status) return;
  const s = NS.status;
  if (se) se.textContent = `session ${s.session_date} · ${s.items_today == null ? '?' : s.items_today} items`;
  const bits = Object.keys(s.sources || {}).map(k => {
    const v = s.sources[k];
    const bad = !!v.last_error;
    return `<span class="${bad ? 'ns-bad' : 'ns-ok'}">${nsEsc(k)}: ${bad ? 'error' : 'ok'}</span>`;
  });
  bits.push(`<span>${s.in_market_window ? 'polling' : 'idle (outside market hours)'}</span>`);
  el.innerHTML = bits.join('');
}

function nsRenderList() {
  const el = document.getElementById('ns-list');
  if (!el) return;
  if (!NS.items.length) {
    el.innerHTML = `<div class="ns-empty">${NS.loading ? 'Loading...' : 'No headlines for this view yet.'}</div>`;
    return;
  }
  el.innerHTML = NS.items.map(i => `
    <div class="ns-item">
      <div class="ns-item-top">
        <span class="ns-src">${nsEsc(i.source)}</span>
        ${i.ticker ? `<span class="ns-tkr">${nsEsc(i.ticker)}</span>` : ''}
        <span class="ns-time">${nsEsc(nsAgo(i.published || i.first_seen))}</span>
      </div>
      ${i.url
        ? `<a class="ns-headline" href="${nsEsc(i.url)}" target="_blank" rel="noopener noreferrer">${nsEsc(i.headline)}</a>`
        : `<div class="ns-headline">${nsEsc(i.headline)}</div>`}
    </div>`).join('');
}

async function loadNewsFeed() {
  NS.loading = true;
  try {
    const qs = `mode=${encodeURIComponent(NS.mode)}&limit=100` + (NS.q ? `&q=${encodeURIComponent(NS.q)}` : '');
    const [feedRes, statusRes, wlRes] = await Promise.all([
      fetch(`${NS_API}/feed?${qs}`),
      fetch(`${NS_API}/status`),
      fetch(`${NS_API}/watchlist`),
    ]);
    const feed = await feedRes.json();
    NS.items = feed.items || [];
    NS.status = await statusRes.json();
    NS.watchlist = (await wlRes.json()).tickers || [];
  } catch (err) {
    // Same principle as the backend: a failure here must be visible, not
    // silently swallowed into an empty page.
    console.warn('[news-scanner] load failed', err);
  }
  NS.loading = false;
  nsRenderHealth();
  nsRenderChips();
  nsRenderList();
}

function goNews() {
  nav('news');
  renderNewsShell();
  nsSyncMode();
  loadNewsFeed();
}

// Refresh while the tab is open. Checks S.page rather than being wired into
// nav(), so nav() itself stays untouched.
setInterval(() => { if (S.page === 'news') loadNewsFeed(); }, 30000);

renderNewsShell();
</script>"""

REPLACEMENTS = [
    ("page-news div", OLD_DIV, NEW_DIV),
    ("page-news CSS", OLD_CSS, NEW_CSS),
    ("PAGES news entry", OLD_PAGES, NEW_PAGES),
    ("touch: down-from-home / up-from-news", OLD_TOUCH, NEW_TOUCH),
    ("keyboard: ArrowDown / ArrowUp", OLD_KEYS, NEW_KEYS),
    ("news scanner module", OLD_BOOT, NEW_BOOT),
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

    # verify: re-decode round-trip and confirm every patch survived
    html2 = INDEX.read_text(encoding="utf-8")
    m2 = re.search(r'<script type="__bundler/template">(.*?)</script>', html2, re.DOTALL)
    decoded2 = json.loads(m2.group(1))
    for name, _old, new in REPLACEMENTS:
        assert new in decoded2, f"verify failed: {name}"
    # the protected world-grid rules must be byte-identical to before
    for guard in [
        "#page-home     { position: absolute; left: 100vw; top: 0;",
        "#page-analysis { position: absolute; left: 100vw; top: 100vh;",
        "#page-screener { position: absolute; left: 0;     top: 0;",
        "#page-journal  { position: absolute; left: 200vw; top: 0;",
        "#world { position: absolute; width: 300vw; height: 300vh; top: 0; left: -100vw;",
        "if (page === 'journal') { window.location.href = '/journal'; return; }",
    ]:
        assert guard in decoded2, f"world-grid guard missing: {guard}"
    print("verify OK: all patches present, world-grid intact, JSON round-trips")
    return 0


if __name__ == "__main__":
    sys.exit(main())
