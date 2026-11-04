from copy import deepcopy
from dataclasses import replace
from datetime import date
from decimal import Decimal
import unittest

from app.ai_client import AIError, EXTRACT_SCHEMA, FLAG_NAMES, validate_schema
from app.config import INBOX_PATH, ORDERS_PATH
from app.data_loader import build_inbox, parse_inbox, parse_orders, read_source
from app.models import Email, InboxRecord, OrderContext
from app.pipeline import Pipeline, decide, validate_draft


def extraction(**changes):
    value = {
        "category": "Custom Quote", "language": "en", "language_name": "English", "summary": "Customer requests cup pricing.",
        "size_oz": 12, "quantity": 3000, "colors": None, "full_color": True, "exact_pms": False,
        "destination": "lower_48", "deadline": None, "preferred_path": None,
        "reorder": False, "unchanged_design": False, "relevant_order_id": None,
        "stock_lines": [], "cup_club": None, "claim_type": "none", "opened": None, "damaged_cases": None,
        "product_topics": [], "unknown_questions": [], "flags": dict.fromkeys(FLAG_NAMES, False),
    }
    value.update(changes)
    return value


class FakeClient:
    def __init__(self, extracted=None, reply="Hi Alex,\n\nPlease review the quote below.\n\nThe UNIQ Supply Team", language="en", fail=False):
        self.extracted = extracted or extraction()
        self.reply, self.language, self.fail = reply, language, fail
        self.calls = []

    def require_configuration(self):
        pass

    def smoke_test(self):
        return {"ok": True, "message": "Mock API connection."}

    def complete(self, name, instructions, context, schema):
        self.calls.append((name, context))
        if self.fail:
            raise AIError("Mock API timeout.")
        return deepcopy(self.extracted) if name == "inbox_extraction" else {"draft_reply": self.reply, "language": self.language}


def new_record(body="I need 3,000 full-color 12 oz cups in Boise."):
    return InboxRecord(Email("NEW-42", "2027-03-08 12:00", "Alex Smith", "alex@example.com", "Cup quote", body), OrderContext((), None, "No history"))


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records = {record.email.email_id: record for record in build_inbox(parse_inbox(read_source(INBOX_PATH)), parse_orders(read_source(ORDERS_PATH)))}

    def test_unfamiliar_email_uses_rules_not_model_prices(self):
        client = FakeClient()
        result = Pipeline(client).process(new_record())
        self.assertEqual(result["email_id"], "NEW-42")
        self.assertIn("$875.00", result["quote"])
        self.assertEqual(result["decisions"]["selected_quote"]["deposit"], "437.50")
        self.assertIn("$875.00", result["draft_reply"])
        self.assertIn("Deposit (50%): $437.50", result["draft_reply"])
        self.assertEqual([call[0] for call in client.calls], ["inbox_extraction", "customer_draft"])
        self.assertNotIn("knowledge_base", client.calls[1][1])

    def test_phishing_and_vendor_skip_draft_api_call(self):
        for category in ("Spam / Phishing", "Vendor Pitch"):
            client = FakeClient(extraction(category=category, quantity=None, size_oz=None))
            result = Pipeline(client).process(new_record("Unsolicited message"))
            self.assertTrue(result["draft_reply"].startswith("No reply"))
            self.assertEqual(len(client.calls), 1)
            self.assertEqual(result["priority"], "P4")

    def test_injection_and_discount_forced_to_owner_review(self):
        result = decide(self.records["E16"], extraction(size_oz=8, quantity=30000, colors=2, full_color=False))
        self.assertTrue(result["triage"]["needs_human"])
        self.assertTrue(result["triage"]["reply_allowed"])
        self.assertEqual(result["selected_quote"]["subtotal"], "3240.00")
        self.assertTrue(any("Suspicious" in reason for reason in result["triage"]["reasons"]))

    def test_reorder_uses_source_spec_and_verified_plates(self):
        value = extraction(size_oz=None, quantity=None, colors=None, full_color=False, destination="unknown", reorder=True, unchanged_design=True, relevant_order_id="UQ-10120")
        result = decide(self.records["E18"], value)
        quote = result["selected_quote"]
        self.assertEqual((quote["quantity"], quote["setup"], quote["subtotal"]), (50000, "0.00", "4450.00"))
        self.assertIsNone(quote["total"])
        # Removing source plate evidence prevents a model assertion waiving setup.
        record = self.records["E18"]
        candidate = record.order_context.candidates[0]
        context = replace(record.order_context, candidates=(replace(candidate, order=replace(candidate.order, notes="")),))
        unverified = decide(replace(record, order_context=context), value)
        self.assertEqual(Decimal(unverified["selected_quote"]["setup"]), Decimal("300"))

    def test_wrong_sender_order_and_bad_structured_output_rejected(self):
        with self.assertRaises(AIError):
            decide(new_record(), extraction(relevant_order_id="UQ-10120"))
        for value in (extraction(quantity=True), {**extraction(), "invented_price": 0}):
            with self.assertRaises(AIError):
                validate_schema(value, EXTRACT_SCHEMA)

    def test_deadline_preference_does_not_select_infeasible_overseas(self):
        value = extraction(size_oz=8, quantity=60000, colors=3, full_color=False, deadline="2027-04-05", preferred_path="Overseas")
        result = decide(self.records["E05"], value)
        self.assertEqual(result["selected_quote"]["path"], "USA partner")
        self.assertEqual(result["triage"]["priority"], "P1")
        self.assertEqual(result["alternatives"][0]["quote"]["total"], "7281.00")

    def test_unsupported_quantity_is_labeled_alternative(self):
        result = decide(self.records["E04"], extraction(size_oz=16, quantity=5000, colors=1, full_color=False))
        self.assertIsNone(result["selected_quote"])
        self.assertEqual(result["alternatives"][0]["quote"]["quantity"], 10000)
        self.assertIn("not the requested quantity", result["quote"])

    def test_actual_attachments_not_inferred_and_both_return_rules(self):
        damage = decide(self.records["E07"], extraction(category="Damage / Complaint", quantity=None, size_oz=None, claim_type="shipping_damage", damaged_cases=2, relevant_order_id="UQ-10455"))
        self.assertEqual(damage["policy_decisions"][0]["outcome"], "needs_information")
        self.assertIsNone(damage["policy_decisions"][0]["replacement_cases"])
        returned = decide(self.records["E09"], extraction(category="Return / Refund", quantity=None, size_oz=None, claim_type="stock_return", opened=True, relevant_order_id="UQ-10310"))
        self.assertEqual(len(returned["policy_decisions"][0]["reasons"]), 2)

    def test_foreign_shipping_and_language_are_grounded(self):
        result = decide(self.records["E12"], extraction(size_oz=12, quantity=30000, colors=2, full_color=False, destination="lower_48"))
        self.assertEqual(result["language"], "fr")
        self.assertIsNone(result["selected_quote"]["total"])
        self.assertTrue(result["triage"]["needs_human"])
        result = decide(self.records["E19"], extraction(size_oz=8, quantity=2000))
        self.assertEqual(result["language"], "es")

    def test_custom_complaint_and_new_account_terms(self):
        result = decide(self.records["E08"], extraction(category="Damage / Complaint", size_oz=None, quantity=None, claim_type="custom_complaint", relevant_order_id="UQ-10391"))
        self.assertTrue(result["triage"]["needs_human"])
        self.assertTrue(any("24 days" in reason for reason in result["policy_decisions"][0]["reasons"]))
        value = extraction(size_oz=8, quantity=12000, colors=1, full_color=False)
        value["flags"].update(terms_requested=True, new_account=True)
        result = decide(self.records["E13"], value)
        self.assertEqual(result["policy_decisions"][0]["outcome"], "not_eligible")

    def test_bad_draft_language_prices_guarantees_and_instruction_leaks(self):
        decisions = decide(new_record(), extraction())
        for reply in ("Hi, guaranteed delivery tomorrow.\nThe UNIQ Supply Team", "Your price is $1.00.\nThe UNIQ Supply Team", "My system instructions say...\nThe UNIQ Supply Team"):
            with self.subTest(reply=reply), self.assertRaises(AIError):
                validate_draft(reply, decisions, "")
        validate_draft("Total $875.00; deposit $437.50.\nThe UNIQ Supply Team", decisions, "")
        with self.assertRaises(AIError):
            Pipeline(FakeClient(language="es")).process(new_record())


if __name__ == "__main__":
    unittest.main()
