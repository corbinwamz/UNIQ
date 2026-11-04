import csv
from dataclasses import replace
import io
import unittest

from app.config import INBOX_PATH, ORDERS_PATH
from app.data_loader import DataValidationError, build_inbox, match_orders, parse_inbox, parse_orders, read_source
from app.models import EMAIL_COLUMNS


def inbox_csv(**changes):
    values = dict(zip(EMAIL_COLUMNS, ("NEW-1", "2027-03-08 12:00", "New Customer", "new@example.com", "Question", 'Hello,\nI need cups with "our logo".')))
    values.update(changes)
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=EMAIL_COLUMNS)
    writer.writeheader()
    writer.writerow(values)
    return output.getvalue()


class LoaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inbox_text = read_source(INBOX_PATH)
        cls.orders_text = read_source(ORDERS_PATH)
        cls.emails = parse_inbox(cls.inbox_text)
        cls.orders = parse_orders(cls.orders_text)

    def test_source_counts_and_original_text(self):
        self.assertEqual(len(self.emails), 20)
        self.assertEqual(len(self.orders), 12)
        self.assertIn("\n", self.emails[0].body)
        self.assertIn("Étienne", self.emails[11].body)
        self.assertIn("25,000", self.orders[0].items)
        self.assertEqual(len(build_inbox(self.emails, self.orders)), 20)

    def test_quoted_multiline_bom_and_normalization(self):
        email = parse_inbox("\ufeff" + inbox_csv(from_email="  NEW@Example.COM  "))[0]
        self.assertEqual(email.from_email, "new@example.com")
        self.assertEqual(email.body, 'Hello,\nI need cups with "our logo".')

    def test_blank_name_and_subject_allowed(self):
        self.assertEqual(parse_inbox(inbox_csv(from_name="", subject=""))[0].subject, "")

    def test_duplicate_email_id_rejected(self):
        with self.assertRaisesRegex(DataValidationError, "duplicate email_id"):
            parse_inbox(self.inbox_text + self.inbox_text.split("\n", 1)[1])

    def test_duplicate_order_id_rejected(self):
        with self.assertRaisesRegex(DataValidationError, "duplicate order_id"):
            parse_orders(self.orders_text + self.orders_text.split("\n", 1)[1])

    def test_invalid_input_errors(self):
        cases = [
            ("", "header"),
            ("email_id,body\nA,hello", "missing columns"),
            (",".join(EMAIL_COLUMNS) + ",email_id\n", "duplicate or blank"),
            (",".join(EMAIL_COLUMNS) + "\nA,b", "fields"),
            (",".join(EMAIL_COLUMNS) + '\n"unterminated', "malformed CSV"),
            (",".join(EMAIL_COLUMNS), "no data rows"),
            (inbox_csv(from_email="not-an-address"), "invalid email"),
            (inbox_csv(received_at="2027-02-30 12:00"), "received_at"),
            (inbox_csv(body=""), "body must not be blank"),
        ]
        for text, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(DataValidationError, message):
                parse_inbox(text)

    def test_invalid_order_date_rejected(self):
        for invalid_date in ("2026-99-12", "20260512"):
            with self.subTest(date=invalid_date), self.assertRaisesRegex(DataValidationError, "delivered_date"):
                parse_orders(self.orders_text.replace("2026-05-12", invalid_date))

    def test_relevant_order_examples_and_all_history_retained(self):
        expectations = {"E07": "UQ-10455", "E08": "UQ-10391", "E09": "UQ-10310", "E17": "UQ-10482", "E18": "UQ-10120"}
        for email in self.emails:
            if email.email_id in expectations:
                with self.subTest(email=email.email_id):
                    context = match_orders(email, self.orders)
                    self.assertEqual(context.suggested_order_id, expectations[email.email_id])
                    expected_history = [order for order in self.orders if order.customer_email == email.from_email]
                    self.assertEqual(len(context.candidates), len(expected_history))

    def test_does_not_always_choose_latest_order(self):
        email = next(email for email in self.emails if email.email_id == "E07")
        email = replace(email, subject="Spoons", body="The spoons from our order were damaged.")
        context = match_orders(email, self.orders)
        self.assertEqual(context.suggested_order_id, "UQ-10433")
        self.assertEqual(len(context.candidates), 2)

    def test_ambiguous_context_not_resolved_by_recency(self):
        email = next(email for email in self.emails if email.email_id == "E17")
        email = replace(email, subject="Cups", body="A question about my cups.")
        self.assertIsNone(match_orders(email, self.orders).suggested_order_id)

    def test_explicit_reference_is_sender_scoped(self):
        email = next(email for email in self.emails if email.email_id == "E17")
        context = match_orders(replace(email, body="Checking order UQ-10461."), self.orders)
        self.assertEqual(context.suggested_order_id, "UQ-10461")
        self.assertIsNone(match_orders(replace(email, body="Checking UQ-10120."), self.orders).suggested_order_id)

    def test_normalized_sender_unknown_sender_and_no_context(self):
        email = self.emails[0]
        self.assertEqual(len(match_orders(replace(email, from_email=" JENNA@FROYOFIESTA.COM "), self.orders).candidates), 1)
        self.assertFalse(match_orders(replace(email, from_email="unknown@example.com"), self.orders).candidates)
        self.assertIsNone(match_orders(replace(email, subject="Hello", body="Hello there"), self.orders).suggested_order_id)


if __name__ == "__main__":
    unittest.main()
