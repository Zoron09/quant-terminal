#!/usr/bin/env python3
"""
wealthsimple_export.py
Fetches Wealthsimple option trades and exports them to the sin-list JSON schema.

Usage:
    python wealthsimple_export.py --dry-run --start-date 2026-06-01
    python wealthsimple_export.py --start-date 2026-06-01 --end-date 2026-06-17
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
    SESSION_FILE.write_text(sess if isinstance(sess, str) else sess.to_json())


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

                    trade = {
                        "id": trade_id,
                        "_close_cid": close_cid,  # used by _merge_fills; stripped before export
                        "date": date_str,
                        "pairs": symbol,
                        "session": "",
                        "model": "",
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


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Export Wealthsimple option trades to sin-list JSON schema.")
    parser.add_argument("--start-date", required=True, help="Start date YYYY-MM-DD")
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
    import_filename.write_text(trade_json)
    print(f"Written: {import_filename}")

    latest_filename = SCRIPT_DIR / "ws_import_latest.json"
    latest_filename.write_text(trade_json)
    print(f"Written: {latest_filename}")

    review_data = _needs_review_serializable(needs_review)
    review_filename.write_text(json.dumps(review_data, indent=2, default=str))
    print(f"Written: {review_filename} ({len(review_data)} item(s))")


if __name__ == "__main__":
    main()
