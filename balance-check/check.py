"""Check how much checking would be left at each bank after paying off its credit cards.

    .venv/bin/python check.py
    .venv/bin/python check.py --json   # same result as one line of JSON (used by CAP)

For each linked bank: left = checking balance - credit cards owed at that bank.
  PASS  left >= $100 (WARN_BELOW)
  WARN  $0 < left < $100
  FAIL  left <= $0 (the cards would eat all of checking, or more)
Prints each bank's status and amount left, then an overall result: FAIL if any
bank fails, otherwise WARN if any bank warns, otherwise PASS. Prints totals only
(no account numbers or transactions). Exits 0 on PASS, 2 on WARN, 1 on FAIL, so
it can be scheduled later.
"""
import json
import sys

import plaid
from plaid.model.accounts_balance_get_request import AccountsBalanceGetRequest

from common import load_tokens, plaid_client

WARN_BELOW = 100.00
EXIT_CODES = {"pass": 0, "warn": 2, "fail": 1}


def status_of(left: float, warn_below: float = WARN_BELOW) -> str:
    if left <= 0:
        return "fail"
    return "warn" if left < warn_below else "pass"


def evaluate(accounts: list[dict], warn_below: float = WARN_BELOW) -> dict:
    """accounts: [{"bank", "type", "subtype", "available", "current"}, ...]

    Each bank gets left = checking - cards owed and a pass/warn/fail status. Overall is the worst one.
    """
    per_bank = {}
    for a in accounts:
        bank = per_bank.setdefault(a["bank"], {"checking": 0.0, "credit": 0.0})
        if a["type"] == "depository" and a["subtype"] == "checking":
            # Available accounts for pending debits; fall back to current if the bank omits it.
            bank["checking"] += a["available"] if a["available"] is not None else (a["current"] or 0.0)
        elif a["type"] == "credit":
            bank["credit"] += a["current"] or 0.0  # for credit accounts, current = amount owed
    for t in per_bank.values():
        t["left"] = t["checking"] - t["credit"]
        t["status"] = status_of(t["left"], warn_below)
    statuses = {t["status"] for t in per_bank.values()}
    overall = "fail" if "fail" in statuses else "warn" if "warn" in statuses else "pass"
    return {"per_bank": per_bank, "status": overall, "warn_below": warn_below}


def fetch_accounts() -> list[dict]:
    client = plaid_client()
    tokens = load_tokens()
    if not tokens:
        sys.exit("No banks linked yet. Run: .venv/bin/python link.py")
    accounts, problems = [], []
    for bank, token in tokens.items():
        try:
            resp = client.accounts_balance_get(AccountsBalanceGetRequest(access_token=token))
        except plaid.ApiException as e:
            code = getattr(e, "body", "") or ""
            if "ITEM_LOGIN_REQUIRED" in code:
                problems.append(f"{bank}: needs re-login. Run: .venv/bin/python link.py --update \"{bank}\"")
            else:
                problems.append(f"{bank}: Plaid error (HTTP {e.status})")
            continue
        for acc in resp["accounts"]:
            accounts.append({
                "bank": bank,
                "type": acc.type.value,
                "subtype": acc.subtype.value if acc.subtype else None,
                "available": acc.balances.available,
                "current": acc.balances.current,
            })
    if problems:
        # A missing bank would make the overall result wrong, so don't report PASS/FAIL.
        sys.exit("Could not read every bank:\n  " + "\n  ".join(problems))
    return accounts


def main():
    r = evaluate(fetch_accounts())
    if "--json" in sys.argv[1:]:
        print(json.dumps(r))
        sys.exit(EXIT_CODES[r["status"]])
    for bank, t in r["per_bank"].items():
        print(f"  {t['status'].upper():<4}  {bank:<24} checking ${t['checking']:>10,.2f}   "
              f"cards owed ${t['credit']:>10,.2f}   left ${t['left']:>10,.2f}")
    print({
        "pass": "\nOVERALL: PASS",
        "warn": f"\nOVERALL: WARN (under ${WARN_BELOW:,.0f} left after cards at the banks marked WARN)",
        "fail": "\nOVERALL: FAIL (cards owed are more than checking at the banks marked FAIL)",
    }[r["status"]])
    sys.exit(EXIT_CODES[r["status"]])


if __name__ == "__main__":
    main()
