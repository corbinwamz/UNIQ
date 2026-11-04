from datetime import date, timedelta
from decimal import Decimal as D
import unittest

from app.config import SCENARIO_DATE
from app.models import TriageFacts
from app.policies import custom_complaint, net30_eligibility, product_facts, shipping_damage, stock_return, triage
from app.pricing import RuleInputError


class ClaimPolicyTests(unittest.TestCase):
    def test_return_boundaries_and_opened_cases(self):
        for days, outcome in ((0, "eligible"), (30, "eligible"), (31, "not_eligible")):
            with self.subTest(days=days):
                result = stock_return(delivered_on=SCENARIO_DATE-timedelta(days=days), opened=False)
                self.assertEqual(result.outcome, outcome)
        result = stock_return(delivered_on=date(2027, 3, 1), opened=False)
        self.assertEqual(result.restocking_rate, D(".15"))
        self.assertEqual(result.return_shipping, "customer")
        self.assertEqual(stock_return(delivered_on=date(2027, 3, 1), opened=False, company_error=True).return_shipping, "company")
        self.assertEqual(stock_return(delivered_on=date(2027, 3, 1), opened=True).outcome, "not_eligible")

    def test_spoon_return_checks_both_opening_and_delivery(self):
        result = stock_return(delivered_on=date(2027, 1, 22), opened=True)
        self.assertEqual(result.outcome, "not_eligible")
        self.assertEqual(len(result.reasons), 2)
        self.assertIn("45 days", result.reasons[1])
        self.assertEqual(stock_return(delivered_on=date(2027, 1, 22), opened=False).outcome, "not_eligible")

    def test_missing_delivery_and_future_delivery(self):
        self.assertEqual(stock_return(delivered_on=None, opened=False).outcome, "needs_information")
        with self.assertRaises(RuleInputError):
            stock_return(delivered_on=date(2027, 3, 9), opened=False)
        with self.assertRaises(RuleInputError):
            shipping_damage(delivered_on=date(2027, 3, 5), damaged_cases=2, photos_received="false")
        with self.assertRaises(RuleInputError):
            stock_return(delivered_on="2027-03-05", opened=False)

    def test_damage_window_photos_and_cases(self):
        result = shipping_damage(delivered_on=date(2027, 3, 5), damaged_cases=2)
        self.assertEqual(result.outcome, "needs_information")
        self.assertIsNone(result.replacement_cases)
        eligible = shipping_damage(delivered_on=date(2027, 3, 5), damaged_cases=2, photos_received=True)
        self.assertEqual(eligible.replacement_cases, 2)
        for days, outcome in ((7, "eligible"), (8, "outside_policy")):
            with self.subTest(days=days):
                self.assertEqual(shipping_damage(delivered_on=SCENARIO_DATE-timedelta(days=days), damaged_cases=1, photos_received=True).outcome, outcome)
        self.assertEqual(shipping_damage(delivered_on=None, damaged_cases=1).outcome, "needs_information")
        with self.assertRaises(RuleInputError):
            shipping_damage(delivered_on=date(2027, 3, 5), damaged_cases=0)

    def test_custom_complaint_never_auto_grants_reprint(self):
        result = custom_complaint(delivered_on=date(2027, 2, 12), production_path="In-house digital")
        self.assertTrue(result.needs_human)
        self.assertEqual(result.outcome, "outside_policy")
        self.assertTrue(any("24 days" in reason for reason in result.reasons))
        # Do not decide a photographed color difference falls within standard
        # merely because this was a digital job.
        self.assertFalse(any("is not a defect" in reason for reason in result.reasons))
        confirmed = custom_complaint(delivered_on=date(2027, 3, 1), production_path="In-house digital", variation_within_close_match=True)
        self.assertEqual(confirmed.outcome, "outside_policy")

    def test_custom_defect_window_boundaries(self):
        for days, outcome in ((14, "owner_review"), (15, "outside_policy")):
            with self.subTest(days=days):
                result = custom_complaint(delivered_on=SCENARIO_DATE-timedelta(days=days), production_path="USA partner", manufacturing_defect=True, photos_received=True)
                self.assertTrue(result.needs_human)
                self.assertEqual(result.outcome, outcome)

    def test_net30_calendar_month_eligibility(self):
        self.assertEqual(net30_eligibility(date(2026, 9, 8)).outcome, "owner_review")
        self.assertEqual(net30_eligibility(date(2026, 9, 9)).outcome, "not_eligible")
        self.assertEqual(net30_eligibility(None).outcome, "needs_information")
        self.assertEqual(net30_eligibility(date(2026, 8, 31), as_of=date(2027, 2, 28)).outcome, "owner_review")
        self.assertTrue(net30_eligibility(date(2027, 3, 1)).needs_human)


class TriageTests(unittest.TestCase):
    def test_high_value_threshold_and_priorities(self):
        for value, human, priority in (("4999.99", False, "P2"), ("5000", True, "P1")):
            with self.subTest(value=value):
                decision = triage(TriageFacts("Custom Quote", estimated_value=D(value)))
                self.assertEqual((decision.needs_human, decision.priority), (human, priority))
        self.assertEqual(triage(TriageFacts("Feedback / Praise")).priority, "P3")
        self.assertEqual(triage(TriageFacts("Stock Order / Product Question", reply_today=True)).priority, "P2")

    def test_all_required_escalation_triggers(self):
        flags = ("rush_requested", "deadline_at_risk", "discount_requested", "price_match_requested", "terms_requested", "custom_complaint", "upset_outside_policy", "legal_threat", "chargeback", "press", "suspicious", "unanswered_question")
        for flag in flags:
            with self.subTest(flag=flag):
                decision = triage(TriageFacts("Custom Quote", **{flag: True}))
                self.assertTrue(decision.needs_human)
                self.assertTrue(decision.reasons)
        self.assertTrue(triage(TriageFacts("Custom Quote", destination="outside_lower_48")).needs_human)
        self.assertEqual(triage(TriageFacts("Custom Quote", deadline_at_risk=True)).priority, "P1")

    def test_phishing_and_vendor_pitch_no_reply(self):
        phishing = triage(TriageFacts("Spam / Phishing"))
        self.assertEqual((phishing.priority, phishing.needs_human, phishing.reply_allowed), ("P4", True, False))
        vendor = triage(TriageFacts("Vendor Pitch"))
        self.assertEqual((vendor.priority, vendor.needs_human, vendor.reply_allowed), ("P4", False, False))

    def test_injection_flags_do_not_erase_legitimate_quote(self):
        decision = triage(TriageFacts("Custom Quote", suspicious=True, discount_requested=True))
        self.assertTrue(decision.needs_human)
        self.assertTrue(decision.reply_allowed)
        self.assertEqual(decision.category, "Custom Quote")

    def test_unknown_value_and_invalid_inputs(self):
        self.assertFalse(triage(TriageFacts("Custom Quote")).needs_human)
        for facts in (TriageFacts("Unknown"), TriageFacts("Custom Quote", estimated_value=5000), TriageFacts("Custom Quote", estimated_value=D("NaN")), TriageFacts("Custom Quote", destination="Mars"), TriageFacts("Custom Quote", suspicious="false")):
            with self.subTest(facts=facts), self.assertRaises(RuleInputError):
                triage(facts)

    def test_known_product_facts_and_unknown_questions(self):
        self.assertTrue(any("110 F" in fact for fact in product_facts("compostable_cups")))
        self.assertTrue(any("not home" in fact for fact in product_facts("compostable_cups")))
        self.assertTrue(any("Not for hot" in fact for fact in product_facts("paper_ice_cream_cups")))
        with self.assertRaises(RuleInputError):
            product_facts("soup_safe_pint_container")


if __name__ == "__main__":
    unittest.main()
