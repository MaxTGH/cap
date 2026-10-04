# Balance check

Shows, for each linked bank, how much would be left in checking after paying off
that bank's credit cards. Uses Plaid's read-only API.

## Privacy

- **Bank passwords** are only ever typed into Plaid's login window, never into this program.
- **Plaid keys and bank access tokens** are stored in the macOS Keychain (service `balance-check`), never in files.
- **Access is read-only.** Plaid tokens can't move money. Revoke one anytime from the Plaid dashboard or your bank's "connected apps" settings.
- **Output** of `check.py` is per-bank totals only, with no account numbers or transactions. `subscriptions.py` prints merchant names and amounts of recurring charges (still no account numbers), to the terminal only.
- **Claude doesn't run these scripts.** `.claude/settings.json` blocks it from running them or reading the Keychain. That's a guardrail; the real protection is that you run them yourself.

## One-time setup

1. Sign up at [dashboard.plaid.com](https://dashboard.plaid.com/signup) and make sure the team is on the free **Trial** plan.
2. In the dashboard under **Developers → Keys**, copy your `client_id` and **Production** secret.
3. Save them to the Keychain (input is hidden):
   ```bash
   cd ~/Projects/balance-check
   uv run setup_keys.py
   ```
4. Link each bank once. A browser page opens; click **Open Plaid**, pick the bank, and log in:
   ```bash
   uv run link.py   # repeat once for each bank
   ```
   The Trial plan allows 10 connections total, and removing one doesn't free a slot, so don't re-link banks unnecessarily.

macOS may ask whether Python can use the Keychain. Click **Always Allow**.

## Daily use

```bash
uv run check.py
```

Prints each bank's checking, cards owed, amount left and PASS/WARN/FAIL, then an overall result. Exits with code 0 on PASS, 2 on WARN and 1 on FAIL. Add `--json` for one line of JSON (CAP uses this).

If a bank says it needs you to log in again (some banks ask periodically), use the name `link.py` printed when you linked it:
```bash
uv run link.py --update "My Bank"
```

## Subscriptions

```bash
uv run subscriptions.py
```

Lists charges that repeat on a regular schedule (weekly, every 2 weeks, monthly, quarterly) at a similar price, across every linked bank, with an estimated monthly total. Charges that missed their expected date are listed separately as possibly cancelled.

- Uses the ~90 days of history Plaid pulled when each bank was linked, so yearly charges won't show up, and a monthly charge needs at least 2 hits (weekly needs 3).
- Card payments, transfers and paychecks are skipped. Pending charges are ignored until they post.
- The detection logic and the balance rule are tested on made-up data: `uv run python -m unittest discover -s test_scripts`.

## How the numbers are counted

- **Checking:** the *available* balance of every checking account (accounts for pending debits). Savings is ignored.
- **Credit cards:** the *current* balance owed on every credit card.
- **Left, per bank:** that bank's checking − that bank's cards owed.
  - **PASS:** $100 or more left.
  - **WARN:** more than $0 but under $100 left.
  - **FAIL:** $0 or less left (the cards owed are at least as much as checking).
- **Overall:** FAIL if any bank fails, otherwise WARN if any bank warns, otherwise PASS. Change `WARN_BELOW` in `check.py` to move the warning line.
- A bank with cards but no checking account always fails.
- If any bank fails to respond, no result is shown, since partial totals would be misleading.

## Updating dependencies

```bash
uv sync --upgrade
```
