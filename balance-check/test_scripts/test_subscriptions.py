"""Checks subscription detection on made-up transactions (never touches Plaid or the Keychain).

    .venv/bin/python -m unittest test_subscriptions
"""
import unittest
from datetime import date, timedelta

from subscriptions import find_subscriptions

TODAY = date(2026, 10, 4)


def charge(merchant, day, amount, category="ENTERTAINMENT", bank="Demo Bank", account="credit card"):
    return {"bank": bank, "account": account, "date": day, "amount": amount,
            "merchant": merchant, "category": category}


def monthly(merchant, amount, last, times=3, **kw):
    return [charge(merchant, last - timedelta(days=30 * i), amount, **kw) for i in range(times)]


class FindSubscriptions(unittest.TestCase):
    def names(self, txns):
        return {s["merchant"]: s for s in find_subscriptions(txns, TODAY)}

    def test_monthly_charge_found(self):
        subs = self.names(monthly("Netflix", 15.49, date(2026, 9, 21)))
        self.assertEqual(subs["Netflix"]["frequency"], "monthly")
        self.assertTrue(subs["Netflix"]["active"])
        self.assertEqual(subs["Netflix"]["next"], date(2026, 10, 21))

    def test_messy_bank_descriptions_grouped(self):
        txns = [charge("SPOTIFY USA #1234", date(2026, 8, 15), 11.99),
                charge("Spotify USA 98765", date(2026, 9, 15), 11.99)]
        self.assertEqual(len(find_subscriptions(txns, TODAY)), 1)

    def test_price_increase_still_one_subscription(self):
        txns = [charge("Hulu", date(2026, 8, 1), 15.49), charge("Hulu", date(2026, 9, 1), 17.99)]
        [sub] = find_subscriptions(txns, TODAY)
        self.assertEqual(sub["amount"], 17.99)

    def test_two_subscriptions_same_merchant_kept_apart(self):
        txns = monthly("Apple", 2.99, date(2026, 9, 10)) + monthly("Apple", 9.99, date(2026, 9, 25))
        self.assertEqual(sorted(s["amount"] for s in find_subscriptions(txns, TODAY)), [2.99, 9.99])

    def test_irregular_shopping_ignored(self):
        txns = [charge("Trader Joe's", date(2026, 7, d), a, category="FOOD_AND_DRINK")
                for d, a in [(3, 42.10), (11, 18.75), (19, 63.20), (30, 25.00)]]
        self.assertEqual(find_subscriptions(txns, TODAY), [])

    def test_card_payments_and_paychecks_ignored(self):
        txns = monthly("Demo Bank Credit Card Payment", 500.00, date(2026, 9, 28),
                       category="LOAN_PAYMENTS", account="checking")
        txns += monthly("Employer Payroll", -2000.00, date(2026, 9, 30), category="INCOME")
        self.assertEqual(find_subscriptions(txns, TODAY), [])

    def test_two_weekly_charges_not_enough(self):
        txns = [charge("Coffee Club", date(2026, 9, 20), 5.00), charge("Coffee Club", date(2026, 9, 27), 5.00)]
        self.assertEqual(find_subscriptions(txns, TODAY), [])

    def test_weekly_needs_three(self):
        txns = [charge("Meal Kit", date(2026, 9, d), 60.00) for d in (13, 20, 27)]
        [sub] = find_subscriptions(txns, TODAY)
        self.assertEqual(sub["frequency"], "weekly")
        self.assertAlmostEqual(sub["per_month"], 60.00 * 30.44 / 7)

    def test_missed_charge_flagged_as_maybe_cancelled(self):
        subs = self.names(monthly("Gym", 40.00, date(2026, 8, 20)))  # next was due ~Sep 19
        self.assertFalse(subs["Gym"]["active"])

    def test_active_sorted_before_stopped_then_by_cost(self):
        txns = (monthly("Gym", 40.00, date(2026, 8, 20)) + monthly("Netflix", 15.49, date(2026, 9, 21))
                + monthly("Max", 16.99, date(2026, 9, 18)))
        self.assertEqual([s["merchant"] for s in find_subscriptions(txns, TODAY)], ["Max", "Netflix", "Gym"])


if __name__ == "__main__":
    unittest.main()
