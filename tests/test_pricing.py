from dataclasses import replace
from datetime import date
from decimal import Decimal as D
import unittest

from app.models import CustomRequest
from app.pricing import CATALOG, RuleInputError, add_business_days, custom_shipping, quote_custom, quote_options, quote_stock, stock_shipping


class CustomPricingTests(unittest.TestCase):
    def test_digital_quotes_with_deposit(self):
        quote = quote_custom(CustomRequest(12, 3000, full_color=True, destination="lower_48"), "In-house digital")
        self.assertTrue(quote.eligible)
        self.assertEqual((quote.cup_cost, quote.setup, quote.shipping, quote.total), (D("780"), D("0"), D("95"), D("875")))
        self.assertEqual((quote.deposit, quote.balance), (D("437.50"), D("437.50")))
        spanish_case = quote_custom(CustomRequest(8, 2000, full_color=True, destination="lower_48"), "In-house digital")
        self.assertEqual(spanish_case.total, D("535"))

    def test_digital_eligibility_boundaries(self):
        for qty, eligible in ((999, False), (1000, True), (9000, True), (9999, False), (10000, False), (1500, False)):
            with self.subTest(quantity=qty):
                self.assertEqual(quote_custom(CustomRequest(8, qty), "In-house digital").eligible, eligible)
        self.assertFalse(quote_custom(CustomRequest(16, 5000), "In-house digital").eligible)
        self.assertFalse(quote_custom(CustomRequest(8, 2000, exact_pms=True), "In-house digital").eligible)

    def test_usa_size_and_quantity_tiers(self):
        for size, prices in ((8, (".115", ".098", ".089")), (12, (".128", ".110", ".099")), (16, (".142", ".121", ".109"))):
            for qty, tier in ((10000, 0), (24000, 0), (25000, 1), (49000, 1), (50000, 2)):
                with self.subTest(size=size, quantity=qty):
                    quote = quote_custom(CustomRequest(size, qty, colors=2), "USA partner")
                    self.assertEqual(quote.unit_price, D(prices[tier]))
        for qty in (9000, 24999, 49999):
            self.assertFalse(quote_custom(CustomRequest(8, qty, colors=1), "USA partner").eligible)

    def test_color_surcharges_and_plates(self):
        for colors, unit, setup in ((1, ".089", "150"), (2, ".089", "300"), (3, ".099", "450"), (4, ".109", "600")):
            with self.subTest(colors=colors):
                quote = quote_custom(CustomRequest(8, 60000, colors=colors), "USA partner")
                self.assertEqual((quote.unit_price, quote.setup), (D(unit), D(setup)))
        for request in (CustomRequest(8, 10000), CustomRequest(8, 10000, colors=5), CustomRequest(8, 10000, colors=4, full_color=True)):
            self.assertFalse(quote_custom(request, "USA partner").eligible)

    def test_overseas_tiers_and_minimum(self):
        for size, prices in ((8, (".062", ".055")), (12, (".071", ".063")), (16, (".079", ".070"))):
            for qty, index in ((50000, 0), (99999, 0), (100000, 1)):
                with self.subTest(size=size, quantity=qty):
                    quote = quote_custom(CustomRequest(size, qty, full_color=True, exact_pms=True), "Overseas")
                    self.assertTrue(quote.eligible)
                    self.assertEqual((quote.unit_price, quote.setup), (D(prices[index]), D("400")))
        self.assertFalse(quote_custom(CustomRequest(8, 49999), "Overseas").eligible)

    def test_all_paths_report_unavailable_5000_16oz(self):
        quotes = quote_options(CustomRequest(16, 5000, colors=1))
        self.assertEqual(len(quotes), 3)
        self.assertFalse(any(quote.eligible for quote in quotes))
        alternative = quote_custom(CustomRequest(16, 10000, colors=1, destination="lower_48"), "USA partner")
        self.assertEqual(alternative.total, D("1665"))

    def test_reorder_requires_verification_and_same_path(self):
        request = CustomRequest(8, 50000, colors=2, destination="lower_48", same_design_verified=True, previous_path="USA partner")
        quote = quote_custom(request, "USA partner")
        self.assertEqual((quote.setup, quote.total), (D("0"), D("4450")))
        for unverified in (replace(request, same_design_verified=False), replace(request, previous_path="Overseas"), replace(request, previous_path=None)):
            self.assertEqual(quote_custom(unverified, "USA partner").setup, D("300"))
        overseas = quote_custom(replace(request, previous_path="Overseas"), "Overseas")
        self.assertEqual(overseas.setup, D("0"))

    def test_rush_is_fifteen_percent_of_cups_only(self):
        request = CustomRequest(8, 60000, colors=3, destination="lower_48", deadline=date(2027, 4, 5))
        regular = quote_custom(request, "USA partner")
        rush = quote_custom(request, "USA partner", rush=True)
        self.assertEqual(regular.total, D("6390"))
        self.assertEqual((rush.rush_fee, rush.setup, rush.total), (D("891"), D("450"), D("7281")))
        self.assertIn("Only the owner can confirm a rush.", rush.human_reasons)
        self.assertFalse(quote_custom(CustomRequest(8, 1000), "In-house digital", rush=True).eligible)

    def test_custom_shipping_exact_threshold(self):
        self.assertEqual(custom_shipping(D("2499.99"), "lower_48"), D("95"))
        self.assertEqual(custom_shipping(D("2500"), "lower_48"), D("0"))
        self.assertIsNone(custom_shipping(D("99999"), "outside_lower_48"))
        self.assertIsNone(custom_shipping(D("99999"), "unknown"))
        quote = quote_custom(CustomRequest(8, 20000, colors=2, exact_pms=True, destination="lower_48"), "USA partner")
        self.assertEqual((quote.subtotal, quote.shipping, quote.total), (D("2600"), D("0"), D("2600")))

    def test_unknown_freight_never_generates_total_or_deposit(self):
        for region in ("unknown", "outside_lower_48"):
            quote = quote_custom(CustomRequest(12, 30000, colors=2, destination=region), "USA partner")
            self.assertEqual(quote.subtotal, D("3600"))
            self.assertIsNone(quote.shipping)
            self.assertIsNone(quote.total)
            self.assertIsNone(quote.deposit)
            self.assertIn("final total and deposit pending", quote.math)
        self.assertTrue(quote.human_reasons)

    def test_production_dates_do_not_guarantee_delivery(self):
        request = CustomRequest(12, 3000, full_color=True, deadline=date(2027, 3, 27))
        window = quote_custom(request, "In-house digital").production
        self.assertEqual((window.earliest, window.latest), (date(2027, 3, 17), date(2027, 3, 22)))
        self.assertTrue(window.approval_assumed)
        self.assertEqual(window.deadline_status, "production_window_only")
        self.assertIn("not a guaranteed delivery", window.note)
        approved = quote_custom(replace(request, proof_approved_on=date(2027, 3, 12)), "In-house digital")
        self.assertFalse(approved.production.approval_assumed)
        self.assertEqual(approved.production.latest, date(2027, 3, 26))

    def test_deadline_boundaries_and_overseas_may_risk(self):
        request = CustomRequest(8, 60000, colors=3, deadline=date(2027, 4, 5))
        self.assertEqual(quote_custom(request, "Overseas").production.deadline_status, "too_soon")
        self.assertEqual(quote_custom(request, "USA partner").production.deadline_status, "tight")
        request = CustomRequest(16, 150000, colors=2, exact_pms=True, destination="lower_48", deadline=date(2027, 5, 1))
        overseas, usa = quote_custom(request, "Overseas"), quote_custom(request, "USA partner")
        self.assertEqual((overseas.total, usa.total), (D("10900"), D("16650")))
        self.assertEqual(overseas.production.earliest, date(2027, 5, 17))
        self.assertEqual(overseas.production.deadline_status, "too_soon")
        self.assertTrue(overseas.human_reasons)

    def test_invalid_facts_never_coerced(self):
        base = CustomRequest(8, 1000)
        for request in (replace(base, quantity=True), replace(base, quantity=1.5), replace(base, quantity=0), replace(base, colors=0), replace(base, full_color="false"), replace(base, same_design_verified="yes"), replace(base, destination="Canada"), replace(base, deadline="tomorrow")):
            with self.subTest(request=request), self.assertRaises(RuleInputError):
                quote_custom(request, "In-house digital")
        with self.assertRaises(RuleInputError):
            quote_custom(base, "invented")
        with self.assertRaises(RuleInputError):
            add_business_days(date(2027, 3, 8), -1)
        for amount in (D("NaN"), D("-1"), 2500):
            with self.subTest(amount=amount), self.assertRaises(RuleInputError):
                custom_shipping(amount, "lower_48")


class StockPricingTests(unittest.TestCase):
    def test_catalog_and_coffee_cart(self):
        self.assertEqual(len(CATALOG), 13)
        quote = quote_stock({"KR-08": 2}, destination="lower_48")
        self.assertEqual(quote.subtotal, D("159.98"))
        self.assertIsNone(quote.shipping)
        self.assertIsNone(quote.total)

    def test_stock_freight_membership_and_threshold(self):
        self.assertIsNone(stock_shipping(D("198.99"), "lower_48", True))
        self.assertEqual(stock_shipping(D("199"), "lower_48", True), D("0"))
        self.assertIsNone(stock_shipping(D("199"), "lower_48", False))
        self.assertIsNone(stock_shipping(D("199"), "outside_lower_48", True))
        quote = quote_stock({"IC-08S": 5, "LID-IC": 2}, destination="lower_48", cup_club=True)
        self.assertEqual(quote.total, D("414.93"))

    def test_low_and_out_of_stock_are_never_promised_available(self):
        quote = quote_stock({"TG-32": 1, "ECO-SPW": 1})
        self.assertIn("Low stock", quote.availability[0])
        self.assertIn("Out of stock; no ETA", quote.availability[1])
        self.assertTrue(quote_stock({"KR-08": 100}).human_reasons)

    def test_invalid_stock_request(self):
        for lines in ({}, {"INVENTED": 1}, {"KR-08": 0}, {"KR-08": True}):
            with self.subTest(lines=lines), self.assertRaises(RuleInputError):
                quote_stock(lines)


if __name__ == "__main__":
    unittest.main()
