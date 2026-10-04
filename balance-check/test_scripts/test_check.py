"""Checks the balance rule on made-up accounts (never touches Plaid or the Keychain).

    uv run python -m unittest discover -s test_scripts
"""
import unittest

from check import evaluate


def acct(bank, kind, amount):
    if kind == "checking":
        return {"bank": bank, "type": "depository", "subtype": "checking", "available": amount, "current": amount}
    if kind == "savings":
        return {"bank": bank, "type": "depository", "subtype": "savings", "available": amount, "current": amount}
    return {"bank": bank, "type": "credit", "subtype": "credit card", "available": None, "current": amount}


class Evaluate(unittest.TestCase):
    def status(self, checking, owed):
        return evaluate([acct("A", "checking", checking), acct("A", "credit", owed)])["per_bank"]["A"]["status"]

    def test_tiers(self):
        self.assertEqual(self.status(1000, 500), "pass")    # $500 left
        self.assertEqual(self.status(1000, 900), "pass")    # exactly $100 left
        self.assertEqual(self.status(1000, 950), "warn")    # $50 left
        self.assertEqual(self.status(1000, 999.99), "warn") # 1 cent left
        self.assertEqual(self.status(1000, 1000), "fail")   # nothing left
        self.assertEqual(self.status(1000, 1200), "fail")   # cards exceed checking

    def test_left_is_checking_minus_cards(self):
        r = evaluate([acct("A", "checking", 800), acct("A", "checking", 200), acct("A", "credit", 300),
                      acct("A", "credit", 50), acct("A", "savings", 5000)])
        self.assertAlmostEqual(r["per_bank"]["A"]["left"], 650)  # savings ignored

    def test_available_preferred_over_current(self):
        a = acct("A", "checking", 500)
        a["available"] = 300  # a pending debit
        self.assertAlmostEqual(evaluate([a])["per_bank"]["A"]["left"], 300)

    def test_overall_is_worst_bank(self):
        ok = [acct("A", "checking", 1000)]
        warn = [acct("B", "checking", 1000), acct("B", "credit", 950)]
        fail = [acct("C", "checking", 100), acct("C", "credit", 200)]
        self.assertEqual(evaluate(ok)["status"], "pass")
        self.assertEqual(evaluate(ok + warn)["status"], "warn")
        self.assertEqual(evaluate(ok + warn + fail)["status"], "fail")

    def test_bank_with_only_cards_fails(self):
        self.assertEqual(evaluate([acct("A", "credit", 10)])["status"], "fail")


if __name__ == "__main__":
    unittest.main()
