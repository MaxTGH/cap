"""List recurring charges (subscriptions) across every linked bank.

    .venv/bin/python subscriptions.py
    .venv/bin/python subscriptions.py --json   # one line of JSON (used by CAP)

Pulls the transaction history Plaid has for each bank (about 90 days with the
current links), groups charges by merchant and price, and keeps the ones that
repeat on a regular schedule. Prints merchant names and amounts to this terminal
only (no account numbers); nothing is written to disk.
"""
import json
import re
import statistics
import sys
from datetime import date, timedelta

import plaid
from plaid.model.transactions_sync_request import TransactionsSyncRequest

from common import load_tokens, plaid_client

# (label, min days between charges, max days, charges needed before we call it recurring)
FREQUENCIES = [
    ("weekly", 6, 8, 3),
    ("every 2 weeks", 13, 16, 3),
    ("monthly", 26, 35, 2),
    ("quarterly", 85, 97, 2),
    ("yearly", 355, 375, 2),
]
PRICE_WIGGLE = 1.25  # charges within 25% of each other count as the same subscription (tax, price increases)
# Card payments, transfers and paychecks repeat too, but aren't subscriptions.
SKIP_CATEGORIES = {"TRANSFER_IN", "TRANSFER_OUT", "LOAN_PAYMENTS", "INCOME"}
DAYS_PER_MONTH = 30.44


def merchant_key(name: str) -> str:
    """'SPOTIFY USA #12345' and 'Spotify USA 67890' -> 'spotify usa'."""
    return " ".join(re.sub(r"[^a-z]+", " ", name.lower()).split())


def price_groups(charges: list[dict]) -> list[list[dict]]:
    """Split one merchant's charges by price, so e.g. two Apple subscriptions stay separate."""
    groups = []
    for t in sorted(charges, key=lambda t: t["amount"]):
        if groups and t["amount"] <= groups[-1][0]["amount"] * PRICE_WIGGLE:
            groups[-1].append(t)
        else:
            groups.append([t])
    return groups


def match_frequency(gaps: list[int]) -> str | None:
    for label, lo, hi, needed in FREQUENCIES:
        if len(gaps) + 1 >= needed and all(lo <= g <= hi for g in gaps):
            return label
    return None


def find_subscriptions(transactions: list[dict], today: date) -> list[dict]:
    """transactions: [{"bank", "account", "date", "amount", "merchant", "category"}, ...]

    Plaid's convention: amount > 0 is money out. Returns one dict per subscription,
    active ones first, most expensive first.
    """
    by_merchant = {}
    for t in transactions:
        if t["amount"] <= 0 or t["category"] in SKIP_CATEGORIES:
            continue
        if key := merchant_key(t["merchant"]):
            by_merchant.setdefault(key, []).append(t)

    subs = []
    for charges in by_merchant.values():
        for group in price_groups(charges):
            group.sort(key=lambda t: t["date"])
            gaps = [(b["date"] - a["date"]).days for a, b in zip(group, group[1:])]
            frequency = match_frequency(gaps)
            if not frequency:
                continue
            last = group[-1]
            gap = statistics.median(gaps)
            expected = last["date"] + timedelta(days=round(gap))
            grace = max(5, round(gap * 0.25))
            subs.append({
                "merchant": last["merchant"],
                "where": f"{last['bank']} {last['account']}",
                "frequency": frequency,
                "amount": last["amount"],
                "count": len(group),
                "last": last["date"],
                "next": expected,
                "active": today <= expected + timedelta(days=grace),
                "per_month": last["amount"] * DAYS_PER_MONTH / gap,
            })
    return sorted(subs, key=lambda s: (not s["active"], -s["per_month"]))


def fetch_bank(client, bank: str, token: str) -> tuple[list[dict], str]:
    """Every posted transaction Plaid has for one bank, plus Plaid's history-loading status."""
    for _ in range(3):
        cursor, found, accounts = "", {}, {}
        try:
            while True:
                resp = client.transactions_sync(TransactionsSyncRequest(access_token=token, cursor=cursor, count=500))
                for a in resp["accounts"]:
                    accounts[a.account_id] = a.subtype.value if a.subtype else a.type.value
                for t in resp["added"] + resp["modified"]:
                    found[t.transaction_id] = t
                for r in resp["removed"]:
                    found.pop(r.transaction_id, None)
                cursor = resp["next_cursor"]
                if not resp["has_more"]:
                    break
        except plaid.ApiException as e:
            # Plaid says to restart the whole loop if data changed mid-download.
            if "TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION" in (getattr(e, "body", "") or ""):
                continue
            raise
        transactions = []
        for t in found.values():
            if t.pending:  # pending charges get re-posted under a new ID once they settle
                continue
            pfc = t.get("personal_finance_category")
            transactions.append({
                "bank": bank,
                "account": accounts.get(t.account_id, "account"),
                "date": t.date,
                "amount": t.amount,
                "merchant": t.get("merchant_name") or t.name,
                "category": pfc.primary if pfc else None,
            })
        status = resp.get("transactions_update_status")
        return transactions, status.value if status else "TRANSACTIONS_UPDATE_STATUS_UNKNOWN"
    raise RuntimeError("bank data kept changing during download; try again shortly")


def main():
    client = plaid_client()
    tokens = load_tokens()
    if not tokens:
        sys.exit("No banks linked yet. Run: .venv/bin/python link.py")

    transactions, problems = [], []
    for bank, token in tokens.items():
        try:
            found, status = fetch_bank(client, bank, token)
        except plaid.ApiException as e:
            if "ITEM_LOGIN_REQUIRED" in (getattr(e, "body", "") or ""):
                problems.append(f"{bank}: needs re-login. Run: .venv/bin/python link.py --update \"{bank}\"")
            else:
                problems.append(f"{bank}: Plaid error (HTTP {e.status})")
            continue
        except RuntimeError as e:
            problems.append(f"{bank}: {e}")
            continue
        if status == "NOT_READY":
            problems.append(f"{bank}: Plaid is still loading history; try again in a few minutes")
        elif status == "INITIAL_UPDATE_COMPLETE":
            problems.append(f"{bank}: only the last ~30 days are loaded so far; results may be incomplete")
        transactions += found

    if not transactions:
        sys.exit("No transactions to look at." + "".join(f"\n  {p}" for p in problems))

    today = date.today()
    first = min(t["date"] for t in transactions)
    subs = find_subscriptions(transactions, today)
    if "--json" in sys.argv[1:]:
        print(json.dumps({
            "warnings": problems,
            "history_days": (today - first).days,
            "subscriptions": [{**s, "last": s["last"].isoformat(), "next": s["next"].isoformat()} for s in subs],
        }))
        return

    if problems:
        print("Warnings (these banks may be missing from the list):\n  " + "\n  ".join(problems) + "\n")
    print(f"Based on {(today - first).days} days of history ({first:%b %-d} to {today:%b %-d}).\n")

    def row(s):
        return (f"  {s['merchant'][:26]:<26} {s['frequency']:<13} ${s['amount']:>8,.2f}   "
                f"{s['where'][:28]:<28} last {s['last']:%b %-d}")

    active = [s for s in subs if s["active"]]
    stopped = [s for s in subs if not s["active"]]
    if active:
        print("Subscriptions:")
        for s in active:
            print(row(s) + f"   next ~{s['next']:%b %-d}")
        print(f"\nAbout ${sum(s['per_month'] for s in active):,.2f}/month in total.")
    else:
        print("No subscriptions found.")
    if stopped:
        print("\nMissed their last expected charge (maybe cancelled):")
        for s in stopped:
            print(row(s) + f"   expected ~{s['next']:%b %-d}")
    print("\nYearly charges won't show up until there's more than a year of history.")


if __name__ == "__main__":
    main()
