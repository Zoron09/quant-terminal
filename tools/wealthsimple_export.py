#!/usr/bin/env python3
"""
wealthsimple_export.py
Fetches Wealthsimple option trades and exports them to the sin-list JSON schema.

Usage:
    python wealthsimple_export.py --dry-run --start-date 2026-06-01
    python wealthsimple_export.py --start-date 2026-06-01 --end-date 2026-06-17

IMPORTANT - pick one --start-date and reuse it on every future run (e.g.
account inception, or a fixed date chosen once) rather than a rolling/
shifting window. FIFO leg-matching has no state persisted between runs --
a wider or shifted window can expose an earlier opening leg that wasn't
visible in a prior run, pairing the same closing leg with a different
opener and producing a different trade_id for what's economically the same
trade. Re-running the *same* range is always safe; changing the start date
between runs is what risks divergent pairings for overlapping trades.
"""

import argparse
import getpass
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

_ET = ZoneInfo("America/New_York")


def _fmt_et(dt):
    """Format a UTC datetime as US Eastern 12-hour time, e.g. '9:31 AM'."""
    et = dt.astimezone(_ET)
    return et.strftime("%I:%M %p").lstrip("0")
from pathlib import Path

SESSION_FILE = Path(__file__).parent / "session.json"
SCRIPT_DIR = Path(__file__).parent

DOW_MAP = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"}


# ---------------------------------------------------------------------------
# Atomic write helper
# ---------------------------------------------------------------------------

def _atomic_write_json(path, text):
    """Write text to path atomically: write to a sibling .tmp file, then
    Path.replace() it onto the target. Path.replace() is a single atomic
    rename on both Windows and POSIX, so the target is always either the
    complete previous version or the complete new version -- never a
    truncated/partial file, even if the process dies mid-write.

    The temp filename is qualified with this process's PID so two writers
    targeting the same file at the same time (e.g. the API server's
    background auto-fetch and Meet running this script by hand) never
    collide on the same temp file -- each writer gets its own temp file,
    each replace() is independently atomic, and whichever finishes last
    simply wins. No torn/partial file is ever possible either way."""
    tmp_path = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp_path.write_text(text)
    tmp_path.replace(path)


# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------

def _load_session():
    """Return a WSAPISession from session.json, or None if missing/invalid."""
    from ws_api import WSAPISession
    if not SESSION_FILE.exists():
        return None
    try:
        return WSAPISession.from_json(SESSION_FILE.read_text())
    except Exception:
        return None


def _save_session(sess):
    _atomic_write_json(SESSION_FILE, sess if isinstance(sess, str) else sess.to_json())


def _get_api():
    """Return an authenticated WealthsimpleAPI, prompting for credentials if needed."""
    from ws_api import WealthsimpleAPI, OTPRequiredException

    api = WealthsimpleAPI()
    sess = _load_session()

    if sess is not None:
        api = WealthsimpleAPI.from_token(sess, persist_session_fct=_save_session)
        try:
            api.check_oauth_token(persist_session_fct=_save_session)
            print("Using saved session.", file=sys.stderr)
            return api
        except Exception:
            print("Saved session expired — logging in again.", file=sys.stderr)

    # Fresh login
    username = input("Wealthsimple email: ")
    password = getpass.getpass("Wealthsimple password: ")
    try:
        sess = api.login(username, password, persist_session_fct=_save_session)
    except OTPRequiredException:
        otp = getpass.getpass("2FA code: ")
        sess = api.login(username, password, otp_answer=otp, persist_session_fct=_save_session)

    _save_session(sess)
    api.start_session(sess)
    return api


def get_cached_api_or_none():
    """Like _get_api(), but NEVER falls back to interactive login -- no
    input()/getpass() calls anywhere in this function, guaranteed. Returns
    an authenticated WealthsimpleAPI using ONLY the existing cached
    session.json (refreshing the access token via the cached refresh_token
    if needed, which is not a fresh login -- no credentials involved), or
    None if there's no session file, it's invalid, or it can't be refreshed.

    This is the only entry point safe to call from a long-running server
    process: a fresh login prompt reaching input()/getpass() inside a
    server process would hang that worker on stdin forever, which is
    exactly the failure mode this function exists to make impossible."""
    from ws_api import WealthsimpleAPI

    sess = _load_session()
    if sess is None:
        return None

    api = WealthsimpleAPI.from_token(sess, persist_session_fct=_save_session)
    try:
        api.check_oauth_token(persist_session_fct=_save_session)
        return api
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Account helpers
# ---------------------------------------------------------------------------

def _build_account_labels(api):
    """Return {accountId: human-readable label} mapping."""
    accounts = api.get_accounts(open_only=True)
    labels = {}
    for acc in accounts:
        acc_id = acc.get("id") or acc.get("accountId", "")
        # Try various label fields the API might return
        label = (
            acc.get("nickname")
            or acc.get("name")
            or acc.get("accountType", "")
        )
        labels[acc_id] = label or acc_id
    return labels


def _get_account_ids(api):
    accounts = api.get_accounts(open_only=True)
    return [acc.get("id") or acc.get("accountId") for acc in accounts if acc.get("id") or acc.get("accountId")]


def _build_account_balances(api, account_labels):
    """Return {label: USD cash balance (float)} using get_account_balances()'s
    'sec-c-usd' field per account -- the actual segregated USD cash sitting
    in the account (real buying power for US options), NOT
    financials.currentCombined.netLiquidationValue (confirmed by direct
    investigation to be a blended CAD total that also includes position
    value, not just cash -- a materially different and misleading number
    for "what can I actually trade US options with").

    Unlike netLiquidationValue, this needs one get_account_balances() call
    PER account -- not free/riding on get_accounts()'s already-fetched
    response. Same cached session, no new auth scope, just an extra
    network round-trip per account. A failure on any one account's balance
    call is skipped, not fatal -- one flaky account's balance call must not
    take down the whole sync (trades still need to write either way).

    Keyed by the SAME resolved label _match_legs() puts into trade.acc
    (account_labels.get(acc_id, acc_id) -- nickname if one exists, else the
    raw account ID), not by the raw account ID directly. Getting this wrong
    silently breaks any account whose nickname differs from its ID (e.g.
    "Khich ke") while accidentally appearing to work for accounts with no
    nickname (where the label just falls back to being the raw ID) --
    confirmed by testing against real data, not assumed.

    Labels are summed, not overwritten, when two different raw accounts
    resolve to the same label -- confirmed against real data that this
    actually happens (two of Meet's own cash sub-accounts both carry the
    nickname "Meet"), and naively overwriting silently dropped one
    account's real dollar balance from the total. Summing is the only
    choice that never loses money regardless of what labels collide."""
    accounts = api.get_accounts(open_only=True)
    balances = {}
    for acc in accounts:
        acc_id = acc.get("id") or acc.get("accountId", "")
        if not acc_id:
            continue
        try:
            acc_balances = api.get_account_balances(acc_id)
            usd_cash = float(acc_balances.get("sec-c-usd") or 0)
        except Exception:
            continue
        label = account_labels.get(acc_id, acc_id)
        balances[label] = balances.get(label, 0.0) + usd_cash
    return balances


def _build_open_positions(api, account_labels):
    """Fetch LIVE option positions (current market value/unrealized P&L,
    not historical) via the FetchIdentityPositions GraphQL query -- confirmed
    working via direct investigation, cached session, no new login/scope.

    Calls do_graphql_query() directly rather than the get_identity_positions()
    convenience wrapper, because that wrapper hardcodes includeSecurity to its
    schema default (false) -- without it, optionDetails/quoteV2 never resolve
    and every position would look identical (no strike/expiry/bid/ask). This
    was confirmed by testing both ways during the investigation.

    Filters to genuine option positions only (security.optionDetails present)
    -- excludes fractional ETF/DRIP shares (e.g. XDIV, confirmed present on
    Meet's real account) which are not options and have optionDetails: null.

    A failure here is skipped, not fatal -- same as _build_account_balances,
    so one flaky call can't take down the whole sync (trades still need to
    write either way)."""
    try:
        raw_positions = api.do_graphql_query(
            "FetchIdentityPositions",
            {
                "identityId": api.get_token_info().get("identity_canonical_id"),
                "currency": "USD",
                "filter": {"securityIds": None},
                "includeAccountData": True,
                "includeSecurity": True,
            },
            "identity.financials.current.positions.edges",
            "array",
        )
    except Exception:
        return []

    def _amt(money_field):
        m = money_field or {}
        return float(m["amount"]) if m.get("amount") is not None else None

    positions = []
    for pos in raw_positions or []:
        security = pos.get("security") or {}
        option_details = security.get("optionDetails")
        if not option_details:
            continue  # not an option position (e.g. fractional ETF shares)

        accounts = pos.get("accounts") or []
        acc_id = accounts[0].get("id") if accounts else ""
        acc_label = account_labels.get(acc_id, acc_id)

        underlying_stock = (option_details.get("underlyingSecurity") or {}).get("stock") or {}
        quote = security.get("quoteV2") or {}

        positions.append({
            "ticker": underlying_stock.get("symbol", ""),
            "optionType": (option_details.get("optionType") or "").upper(),
            "strike": option_details.get("strikePrice"),
            "expiry": option_details.get("expiryDate"),
            "acc": acc_label,
            "quantity": pos.get("quantity"),
            "bookValue": _amt(pos.get("bookValue")),
            "averagePrice": _amt(pos.get("averagePrice")),
            "totalValue": _amt(pos.get("totalValue")),
            "unrealizedReturns": _amt(pos.get("unrealizedReturns")),
            "bid": quote.get("bid"),
            "ask": quote.get("ask"),
            "last": quote.get("last"),
            "mid": quote.get("mid"),
            "quotedAsOf": quote.get("quotedAsOf"),
            "entryDate": None,
            "entryTime": None,
        })
    return positions


def _enrich_positions_with_entry_date(positions, needs_review):
    """PositionV2 (the live positions query) has no 'opened on' field -- it's
    a live snapshot, not a historical record. The real open date/time DOES
    exist, in this same run's needs_review data (the activity-feed leg that
    never got a matching closer), so this cross-references by
    ticker+strike+expiry to attach a real entry date rather than leaving it
    blank or guessing."""
    open_legs = [
        item for item in needs_review
        if item.get("reason") == "open position with no closing leg in date range"
    ]
    for pos in positions:
        for item in open_legs:
            leg = item.get("leg") or {}
            if (
                (leg.get("assetSymbol") or "").upper() == (pos["ticker"] or "").upper()
                and str(leg.get("strikePrice", "")) == str(pos["strike"])
                and leg.get("expiryDate") == pos["expiry"]
            ):
                open_dt = _parse_occurred_at(leg.get("occurredAt", ""))
                sentinel = datetime.min.replace(tzinfo=timezone.utc)
                if open_dt != sentinel:
                    open_dt_et = open_dt.astimezone(_ET)
                    pos["entryDate"] = open_dt_et.strftime("%Y-%m-%d")
                    pos["entryTime"] = _fmt_et(open_dt)
                break
    return positions


# ---------------------------------------------------------------------------
# Activity fetch + filter
# ---------------------------------------------------------------------------

def _is_option_activity(act):
    """True if this activity is an option buy/sell order."""
    contract_type = act.get("contractType")
    strike = act.get("strikePrice")
    expiry = act.get("expiryDate")
    return bool(contract_type and strike is not None and expiry)


def _fetch_option_activities(api, account_ids, start_dt, end_dt):
    """Fetch all activities in range and return only option orders."""
    all_acts = api.get_activities(
        account_id=account_ids,
        start_date=start_dt,
        end_date=end_dt,
        load_all=True,
        ignore_rejected=True,
    )

    option_acts = []
    seen_type_subtypes = set()

    for act in all_acts:
        t = act.get("type", "")
        st = act.get("subType", "")
        seen_type_subtypes.add((t, st))
        if _is_option_activity(act):
            option_acts.append(act)

    if not option_acts:
        print("\n[DEBUG] Zero option activities found. Unique (type, subType) combos seen:")
        for combo in sorted(seen_type_subtypes):
            print(f"  type={combo[0]!r}  subType={combo[1]!r}")
    else:
        # Diagnostic: show distinct (type, amountSign) combos to verify sign logic
        sign_combos = sorted({(a.get("type", ""), a.get("amountSign", "")) for a in option_acts})
        print(f"[diag] distinct (type, amountSign) across {len(option_acts)} option legs:", file=sys.stderr)
        for t, s in sign_combos:
            print(f"  type={t!r}  amountSign={s!r}", file=sys.stderr)

    return option_acts


# ---------------------------------------------------------------------------
# FIFO matching
# ---------------------------------------------------------------------------

def _parse_occurred_at(s):
    """Parse ISO8601 timestamp to datetime (UTC)."""
    if not s:
        return datetime.min.replace(tzinfo=timezone.utc)
    s = s.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)


def _leg_is_opener(act):
    """Opening = bought to open (BUY) or sold to open (SELL-side).
    We determine by amountSign: a debit (amountSign='negative') is buying,
    a credit (amountSign='positive') with a subType suggesting sell-to-open.

    Simpler heuristic: look at subType first, then fall back to amountSign.
    """
    subtype = (act.get("subType") or "").upper()
    atype = (act.get("type") or "").upper()

    # Explicit open/close in subType
    if "BUY_TO_OPEN" in subtype or "OPEN" in subtype and "BUY" in subtype:
        return True
    if "SELL_TO_OPEN" in subtype or "OPEN" in subtype and "SELL" in subtype:
        return True
    if "BUY_TO_CLOSE" in subtype or "CLOSE" in subtype and "BUY" in subtype:
        return False
    if "SELL_TO_CLOSE" in subtype or "CLOSE" in subtype and "SELL" in subtype:
        return False

    # Fall back: credit = received money = opener (sold to open) or closer (sold to close)
    # Debit = paid money = opener (bought to open) or closer (bought to close)
    # Without explicit open/close markers we track net position per contract group.
    # Return None to let the grouping logic decide.
    return None


def _leg_is_buy(act):
    """True if this leg was a buy (paid money = amountSign negative or type BUY)."""
    atype = (act.get("type") or "").upper()
    subtype = (act.get("subType") or "").upper()
    amount_sign = (act.get("amountSign") or "").lower()

    if "BUY" in atype or "BUY" in subtype:
        return True
    if "SELL" in atype or "SELL" in subtype:
        return False
    # Last resort: negative amount = paid = buy
    return amount_sign == "negative"


def _contract_key(act):
    return (
        act.get("accountId", ""),
        act.get("assetSymbol", ""),
        str(act.get("strikePrice", "")),
        act.get("expiryDate", ""),
        act.get("contractType", ""),
    )


def _cash_flow(act):
    """Signed cash flow for one leg from the account's perspective.
    BUY = money leaves account (negative). SELL = money enters (positive).
    WS amount field is always a positive magnitude regardless of amountSign,
    so sign is derived from the leg direction instead.
    """
    raw = float(act.get("amount") or 0)
    return -abs(raw) if _leg_is_buy(act) else abs(raw)


def _debug_leg(label, leg, remaining_after=None):
    cid = leg.get("canonicalId", "?")
    ts = (leg.get("occurredAt") or "")[:19]
    t = leg.get("type", "")
    st = leg.get("subType", "")
    qty = leg.get("assetQuantity", "?")
    amt = leg.get("amount", "?")
    sign = leg.get("amountSign", "")
    cf = _cash_flow(leg)
    line = f"    {label}: cid={cid}  {ts}  type={t!r} subType={st!r}  qty={qty}  amt={amt}({sign})  cf={cf:+.2f}"
    if remaining_after is not None:
        line += f"  remaining_after={remaining_after}"
    print(line)


def _match_legs(option_acts, account_labels, debug=False):
    """
    FIFO-match opening legs to closing legs within each contract group.
    Returns (trades, needs_review).
    """
    # Sort all legs chronologically
    sorted_acts = sorted(option_acts, key=lambda a: _parse_occurred_at(a.get("occurredAt")))

    # Group by contract identity
    groups = defaultdict(list)
    for act in sorted_acts:
        groups[_contract_key(act)].append(act)

    trades = []
    needs_review = []

    for key, legs in groups.items():
        account_id, symbol, strike, expiry, contract_type = key
        acc_label = account_labels.get(account_id, account_id)

        # Track open position as a queue of (quantity, leg) tuples
        # Positive qty = long position, negative qty = short position
        open_queue = []  # list of {"qty": float, "leg": act, "is_buy": bool}
        unmatched = []

        for leg in legs:
            qty = float(leg.get("assetQuantity") or 0)
            if qty == 0:
                needs_review.append({"leg": leg, "reason": "zero assetQuantity"})
                continue

            is_buy = _leg_is_buy(leg)

            # Determine if this is an opener or closer
            is_opener = _leg_is_opener(leg)

            if is_opener is None:
                # Infer from queue state
                if not open_queue:
                    is_opener = True
                else:
                    queue_is_buy = open_queue[0]["is_buy"]
                    # Opposite direction = closer
                    is_opener = (is_buy == queue_is_buy)

            if is_opener:
                open_queue.append({"qty": qty, "leg": leg, "is_buy": is_buy})
            else:
                # This is a closing leg — FIFO match against open_queue
                remaining_close_qty = qty
                while remaining_close_qty > 0 and open_queue:
                    open_item = open_queue[0]
                    matched_qty = min(remaining_close_qty, open_item["qty"])

                    open_leg = open_item["leg"]
                    close_leg = leg

                    # Proportional cash flows for the matched quantity slice
                    open_total_qty = float(open_leg.get("assetQuantity") or 1)
                    close_total_qty = float(close_leg.get("assetQuantity") or 1)

                    open_cf = _cash_flow(open_leg) * (matched_qty / open_total_qty)
                    close_cf = _cash_flow(close_leg) * (matched_qty / close_total_qty)

                    open_fees = float(open_leg.get("fees") or 0) * (matched_qty / open_total_qty)
                    close_fees = float(close_leg.get("fees") or 0) * (matched_qty / close_total_qty)

                    # PnL = net cash flow (sell proceeds - buy costs) minus fees
                    pnl = round(open_cf + close_cf - open_fees - close_fees, 4)

                    # Entry/exit prices per contract (display only — always positive)
                    entry_price = abs(open_cf / matched_qty) if matched_qty else 0
                    exit_price = abs(close_cf / matched_qty) if matched_qty else 0

                    # Date/time from opening leg (date in UTC, times in local tz)
                    open_dt_str = open_leg.get("occurredAt", "")
                    open_dt = _parse_occurred_at(open_dt_str)
                    _sentinel = datetime.min.replace(tzinfo=timezone.utc)
                    open_dt_et = open_dt.astimezone(_ET) if open_dt != _sentinel else None
                    date_str = open_dt_et.strftime("%Y-%m-%d") if open_dt_et else ""
                    dow = DOW_MAP.get(open_dt_et.weekday(), "") if open_dt_et else ""
                    entry_time = _fmt_et(open_dt) if open_dt != _sentinel else ""
                    close_dt = _parse_occurred_at(close_leg.get("occurredAt", ""))
                    exit_time = _fmt_et(close_dt) if close_dt != _sentinel else ""
                    exit_date_et = close_dt.astimezone(_ET).strftime("%Y-%m-%d") if close_dt != _sentinel else ""
                    exit_date = exit_date_et if exit_date_et != date_str else ""

                    # Deterministic id unique per open+close pair — prevents collision
                    # when one close leg is split across multiple open lots (Bug 2)
                    open_cid = open_leg.get("canonicalId", "")
                    close_cid = close_leg.get("canonicalId", "")
                    trade_id = f"{open_cid}_{close_cid}"

                    currency = open_leg.get("currency") or close_leg.get("currency") or ""
                    if currency and currency != "USD":
                        print(
                            f"[currency] WARNING: {symbol} trade ({open_cid}_{close_cid}) is {currency}, not USD -- "
                            f"journal currently assumes USD throughout; this trade needs manual review.",
                            file=sys.stderr,
                        )

                    trade = {
                        "id": trade_id,
                        "_close_cid": close_cid,  # used by _merge_fills; stripped before export
                        "date": date_str,
                        "pairs": symbol,
                        "session": "",
                        "model": "",
                        "currency": currency,
                        "dir": "LONG" if (open_leg.get("contractType") or "").lower() == "call" else "SHORT",
                        "pnl": pnl,
                        "contracts": int(matched_qty),
                        "entry": round(entry_price, 4),
                        "entryTime": entry_time,
                        "exit": round(exit_price, 4),
                        "exitTime": exit_time,
                        "exitDate": exit_date_et,
                        "ew": "",
                        "acc": acc_label,
                        "rating": None,
                        "fp": False,
                        "be": False,
                        "win": pnl > 0,
                        "ptags": [],
                        "ntags": [],
                        "notes": "",
                        "dow": dow,
                    }
                    trades.append(trade)

                    # Reduce quantities
                    open_item["qty"] -= matched_qty
                    remaining_close_qty -= matched_qty
                    if open_item["qty"] <= 0:
                        open_queue.pop(0)

                    if debug:
                        print(f"  TRADE {len(trades)}: {trade['date']} {symbol} {trade['dir']} x{int(matched_qty)}  pnl={pnl}  entry={trade['entry']}  exit={trade['exit']}")
                        _debug_leg("  OPEN ", open_leg, remaining_after=open_item["qty"])
                        _debug_leg("  CLOSE", close_leg, remaining_after=remaining_close_qty)

                if remaining_close_qty > 0:
                    needs_review.append({
                        "leg": close_leg,
                        "reason": f"no matching open leg for {remaining_close_qty} contracts (possible assignment or prior-range open)",
                    })

        # Anything left in open_queue has no closing leg in range
        for item in open_queue:
            nr_dt = _parse_occurred_at(item["leg"].get("occurredAt", ""))
            nr_sentinel = datetime.min.replace(tzinfo=timezone.utc)
            nr_open_time = _fmt_et(nr_dt) if nr_dt != nr_sentinel else ""
            needs_review.append({
                "leg": item["leg"],
                "openTime": nr_open_time,
                "reason": "open position with no closing leg in date range",
            })

    return trades, needs_review


# ---------------------------------------------------------------------------
# Fill merging — collapse split-fill trades sharing the same closing order
# ---------------------------------------------------------------------------

def _merge_fills(trades):
    """Group trades by their closing canonicalId.
    Multiple fills against the same closing order are merged into one row:
      - contracts  = sum
      - entry      = weighted average
      - pnl        = sum
      - entryTime  = earliest fill's entryTime (already first due to FIFO order)
      - fills      = [{qty, entry, entryTime}, ...] for UI badge
    Single-fill trades pass through unchanged (no fills field added).
    """
    from collections import OrderedDict

    groups = OrderedDict()
    for t in trades:
        key = t.get("_close_cid") or t["id"].rsplit("_", 1)[-1]
        groups.setdefault(key, []).append(t)

    merged = []
    for key, group in groups.items():
        if len(group) == 1:
            t = dict(group[0])
            t.pop("_close_cid", None)
            merged.append(t)
        else:
            total_qty = sum(t["contracts"] for t in group)
            total_cost = sum(t["entry"] * t["contracts"] for t in group)
            total_pnl = sum(t["pnl"] for t in group)
            weighted_entry = round(total_cost / total_qty, 4) if total_qty else 0

            fills = [
                {"qty": t["contracts"], "entry": t["entry"], "entryTime": t["entryTime"]}
                for t in group
            ]

            base = dict(group[0])
            base.pop("_close_cid", None)
            base["id"] = f"merged_{key}"
            base["contracts"] = total_qty
            base["entry"] = weighted_entry
            base["pnl"] = round(total_pnl, 4)
            base["win"] = total_pnl > 0
            base["fills"] = fills
            merged.append(base)

    return merged


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def _print_summary(trades, needs_review_count):
    if not trades:
        print("No matched trades.")
        return
    header = f"{'Date':<12} {'Ticker':<8} {'Dir':<6} {'Contracts':>9} {'Entry':>8} {'Exit':>8} {'PNL':>10}"
    print(header)
    print("-" * len(header))
    for t in trades:
        fills = t.get("fills") or []
        tag = f"  [{len(fills)} fills]" if len(fills) > 1 else ""
        print(
            f"{t['date']:<12} {t['pairs']:<8} {t['dir']:<6} "
            f"{t['contracts']:>9} {t['entry']:>8.2f} {t['exit']:>8.2f} {t['pnl']:>10.2f}{tag}"
        )
    print(f"\nTotal trades: {len(trades)}  |  Needs review: {needs_review_count}")


def _needs_review_serializable(needs_review):
    """Convert datetime objects in leg data to strings for JSON serialization."""
    out = []
    for item in needs_review:
        leg = {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in item["leg"].items()}
        out.append({"leg": leg, "reason": item["reason"]})
    return out


def run_export_with_cached_session(start_date_str, end_date_str, ticker_filter=""):
    """Run the full fetch -> match -> merge -> write pipeline using ONLY the
    cached session (get_cached_api_or_none() -- never prompts, never logs in).
    Reuses the exact same fetch/match/merge/write building blocks as main(),
    nothing duplicated.

    Returns True if a cached session was available and the run completed
    (files written), False if there's no valid cached session (caller should
    treat existing on-disk data as stale rather than attempt anything else).
    Any other failure (network, matching) raises -- caller decides how to
    log/handle it; this function does not swallow errors silently."""
    api = get_cached_api_or_none()
    if api is None:
        return False

    start_dt = datetime.strptime(start_date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end_dt = datetime.strptime(end_date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc) + timedelta(days=1)

    account_ids = _get_account_ids(api)
    if not account_ids:
        return False

    account_labels = _build_account_labels(api)
    account_balances = _build_account_balances(api, account_labels)
    option_acts = _fetch_option_activities(api, account_ids, start_dt, end_dt)
    if ticker_filter:
        option_acts = [a for a in option_acts if (a.get("assetSymbol") or "").upper() == ticker_filter.upper()]

    trades, needs_review = _match_legs(option_acts, account_labels)
    trades = _merge_fills(trades)
    open_positions = _build_open_positions(api, account_labels)
    open_positions = _enrich_positions_with_entry_date(open_positions, needs_review)

    import_filename = SCRIPT_DIR / f"ws_import_{start_date_str}_{end_date_str}.json"
    review_filename = SCRIPT_DIR / "needs_review.json"
    latest_filename = SCRIPT_DIR / "ws_import_latest.json"
    balances_filename = SCRIPT_DIR / "account_balances.json"
    positions_filename = SCRIPT_DIR / "open_positions.json"

    trade_json = json.dumps(trades, indent=2, default=str)
    _atomic_write_json(import_filename, trade_json)
    _atomic_write_json(latest_filename, trade_json)
    _atomic_write_json(review_filename, json.dumps(_needs_review_serializable(needs_review), indent=2, default=str))
    _atomic_write_json(balances_filename, json.dumps(account_balances, indent=2))
    _atomic_write_json(positions_filename, json.dumps(open_positions, indent=2, default=str))
    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Export Wealthsimple option trades to sin-list JSON schema.")
    parser.add_argument("--start-date", required=True, help="Start date YYYY-MM-DD. Reuse the SAME start date on every future run (don't shift the window) -- see module docstring for why.")
    parser.add_argument("--end-date", default=datetime.now().strftime("%Y-%m-%d"), help="End date YYYY-MM-DD (default: today)")
    parser.add_argument("--dry-run", action="store_true", help="Print summary only, write no files")
    parser.add_argument("--debug", action="store_true", help="Print raw leg records for each matched trade")
    parser.add_argument("--ticker", default="", help="Filter debug output to this ticker only")
    args = parser.parse_args()

    start_dt = datetime.strptime(args.start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    # _iso_z inside get_activities strips time to date-only, so the API sees "2026-06-01".
    # Add 1 day so the end date is exclusive-inclusive (covers all of the user's end date).
    end_dt = datetime.strptime(args.end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc) + timedelta(days=1)

    print(f"Fetching option trades {args.start_date} -> {args.end_date} ...")
    api = _get_api()

    account_ids = _get_account_ids(api)
    if not account_ids:
        print("No open accounts found.", file=sys.stderr)
        sys.exit(1)
    print(f"Found {len(account_ids)} account(s).", file=sys.stderr)

    account_labels = _build_account_labels(api)

    option_acts = _fetch_option_activities(api, account_ids, start_dt, end_dt)
    print(f"Found {len(option_acts)} option activity leg(s).", file=sys.stderr)

    if args.ticker:
        option_acts = [a for a in option_acts if (a.get("assetSymbol") or "").upper() == args.ticker.upper()]
    trades, needs_review = _match_legs(option_acts, account_labels, debug=args.debug)
    trades = _merge_fills(trades)

    _print_summary(trades, len(needs_review))

    if args.dry_run:
        print("\n[dry-run] No files written.")
        return

    # Write output files
    import_filename = SCRIPT_DIR / f"ws_import_{args.start_date}_{args.end_date}.json"
    review_filename = SCRIPT_DIR / "needs_review.json"

    trade_json = json.dumps(trades, indent=2, default=str)
    _atomic_write_json(import_filename, trade_json)
    print(f"Written: {import_filename}")

    latest_filename = SCRIPT_DIR / "ws_import_latest.json"
    _atomic_write_json(latest_filename, trade_json)
    print(f"Written: {latest_filename}")

    review_data = _needs_review_serializable(needs_review)
    _atomic_write_json(review_filename, json.dumps(review_data, indent=2, default=str))
    print(f"Written: {review_filename} ({len(review_data)} item(s))")


if __name__ == "__main__":
    main()
