"""Explicit policy decisions from supplied facts; no free-form email parsing."""

from calendar import monthrange
from datetime import date
from decimal import Decimal

from .config import SCENARIO_DATE
from .models import CATEGORIES, ClaimDecision, TriageDecision, TriageFacts
from .pricing import RuleInputError


def _booleans(**flags):
    if any(type(value) is not bool for value in flags.values()):
        raise RuleInputError("Policy flags must be true/false booleans, not strings or numbers.")


def _elapsed(delivered_on: date | None, reported_on: date) -> int | None:
    if type(reported_on) is not date or (delivered_on is not None and type(delivered_on) is not date):
        raise RuleInputError("Delivery and report dates must be date values.")
    if delivered_on is None:
        return None
    days = (reported_on - delivered_on).days
    if days < 0:
        raise RuleInputError("Report date cannot be before delivery date.")
    return days


def stock_return(*, delivered_on: date | None, opened: bool, reported_on: date = SCENARIO_DATE, company_error: bool = False) -> ClaimDecision:
    _booleans(opened=opened, company_error=company_error)
    days = _elapsed(delivered_on, reported_on)
    reasons = []
    if opened:
        reasons.append("Opened stock cases cannot be returned.")
    if days is not None and days > 30:
        reasons.append(f"Reported {days} days after delivery, outside the 30-day return window.")
    if reasons:
        return ClaimDecision("not_eligible", tuple(reasons))
    if days is None:
        return ClaimDecision("needs_information", ("Delivery date is needed to check the 30-day return window.",))
    return ClaimDecision("eligible", ("Unopened stock item within 30 days of delivery; 15% restocking fee.",),
                         restocking_rate=Decimal("0.15"), return_shipping="company" if company_error else "customer")


def shipping_damage(*, delivered_on: date | None, damaged_cases: int, photos_received: bool = False, reported_on: date = SCENARIO_DATE) -> ClaimDecision:
    _booleans(photos_received=photos_received)
    if type(damaged_cases) is not int or damaged_cases <= 0:
        raise RuleInputError("Damaged case count must be a positive integer.")
    days = _elapsed(delivered_on, reported_on)
    if days is None:
        return ClaimDecision("needs_information", ("Delivery date required to check the 7-day damage reporting window.",))
    if days > 7:
        return ClaimDecision("outside_policy", (f"Reported {days} days after delivery; standard damage window is 7 days. Owner review needed for any exception.",), True)
    if not photos_received:
        return ClaimDecision("needs_information", ("Within the 7-day window; obtain actual damage photos before arranging replacements. No return required.",))
    return ClaimDecision("eligible", ("Free replacements for damaged cases; no return required. Delivery timing is not guaranteed.",), replacement_cases=damaged_cases)


def custom_complaint(*, delivered_on: date | None, production_path: str, manufacturing_defect: bool | None = None,
                     variation_within_close_match: bool | None = None, photos_received: bool = False,
                     reported_on: date = SCENARIO_DATE) -> ClaimDecision:
    _booleans(photos_received=photos_received)
    for value in (manufacturing_defect, variation_within_close_match):
        if value is not None and type(value) is not bool:
            raise RuleInputError("Defect assessments must be booleans or unknown.")
    days = _elapsed(delivered_on, reported_on)
    reasons = ["All custom-order complaints require owner review; no automatic reprint or credit."]
    if production_path == "In-house digital" and variation_within_close_match is True:
        reasons.append("Digital color variation within the approved close-match standard is not a defect; no PMS guarantee.")
    if days is not None and days > 14:
        reasons.append(f"Reported {days} days after delivery, outside the 14-day manufacturing-defect window.")
    if len(reasons) > 1:
        return ClaimDecision("outside_policy", tuple(reasons), True)
    if days is None:
        reasons.append("Confirm delivery date before assessing the 14-day window.")
    if manufacturing_defect is not True:
        reasons.append("Owner must determine whether this is a manufacturing defect; custom items are not returnable.")
    if not photos_received:
        reasons.append("Obtain actual photos for defect review.")
    if days is not None and manufacturing_defect is True and photos_received:
        reasons.append("Reported defect is within 14 days; policy provides reprint or credit, subject to owner review.")
        return ClaimDecision("owner_review", tuple(reasons), True)
    return ClaimDecision("needs_information", tuple(reasons), True)


def net30_eligibility(first_order_on: date | None, *, as_of: date = SCENARIO_DATE) -> ClaimDecision:
    """Use a verified history start, not merely the earliest row in a partial CSV."""
    if type(as_of) is not date or (first_order_on is not None and type(first_order_on) is not date):
        raise RuleInputError("History and scenario dates must be date values.")
    if first_order_on is None:
        return ClaimDecision("needs_information", ("Net 30 requires at least six months of order history and owner approval; history is unconfirmed.",), True)
    if first_order_on > as_of:
        raise RuleInputError("Order history cannot start in the future.")
    month = first_order_on.month - 1 + 6
    year = first_order_on.year + month // 12
    month = month % 12 + 1
    anniversary = date(year, month, min(first_order_on.day, monthrange(year, month)[1]))
    if as_of < anniversary:
        return ClaimDecision("not_eligible", ("Account has less than six months of order history; standard custom payment is 50% deposit and balance before shipping.",), True)
    return ClaimDecision("owner_review", ("Six-month history requirement met; only the owner can approve Net 30.",), True)


def triage(facts: TriageFacts) -> TriageDecision:
    _booleans(**{name: getattr(facts, name) for name in (
        "rush_requested", "deadline_at_risk", "discount_requested", "price_match_requested",
        "terms_requested", "custom_complaint", "upset_outside_policy", "legal_threat",
        "chargeback", "press", "suspicious", "unanswered_question", "security_message", "reply_today",
    )})
    if facts.category not in CATEGORIES:
        raise RuleInputError("Unknown email category.")
    if facts.destination not in ("lower_48", "outside_lower_48", "unknown"):
        raise RuleInputError("Unknown destination region.")
    if facts.estimated_value is not None and (not isinstance(facts.estimated_value, Decimal) or not facts.estimated_value.is_finite() or facts.estimated_value < 0):
        raise RuleInputError("Estimated value must be a finite, nonnegative Decimal.")
    reasons = list(facts.quote_human_reasons)
    high_value = facts.estimated_value is not None and facts.estimated_value >= Decimal("5000")
    checks = (
        (high_value, "Estimated order value is $5,000 or more."),
        (facts.rush_requested, "Only the owner can confirm a rush."),
        (facts.deadline_at_risk, "A requested deadline or guarantee is at risk."),
        (facts.discount_requested or facts.price_match_requested, "Discounts and price matching require owner review; published pricing applies."),
        (facts.terms_requested, "Payment terms require owner review and eligibility checks."),
        (facts.destination == "outside_lower_48", "Shipping outside the lower 48 requires the owner."),
        (facts.custom_complaint, "Custom-order complaint requires owner review."),
        (facts.upset_outside_policy, "Upset customer requests an exception to policy."),
        (facts.legal_threat or facts.chargeback or facts.press, "Legal threat, chargeback, or press requires the owner."),
        (facts.suspicious or facts.security_message, "Suspicious content or security risk requires owner review."),
        (facts.unanswered_question, "Knowledge base does not answer the question; never guess."),
    )
    reasons.extend(reason for flag, reason in checks if flag)
    reasons = tuple(dict.fromkeys(reasons))
    no_reply = facts.category in ("Spam / Phishing", "Vendor Pitch") or facts.security_message
    if no_reply:
        priority = "P4"
        reply_reason = "No reply: suspicious billing/security message; verify independently through a trusted account channel." if facts.category == "Spam / Phishing" or facts.security_message else "No reply: unsolicited vendor pitch."
    else:
        priority = "P1" if high_value or facts.deadline_at_risk or facts.rush_requested else ("P2" if reasons or facts.reply_today or facts.category in ("Custom Quote", "Order Status", "Damage / Complaint", "Return / Refund", "Billing / Terms") else "P3")
        reply_reason = "Draft for owner review before sending." if reasons else "Prepare a policy-grounded reply for human review."
    # Spam/phishing is itself a security category even if extraction omitted flags.
    if facts.category == "Spam / Phishing" and not (facts.suspicious or facts.security_message):
        reasons += ("Spam/phishing requires security review.",)
    return TriageDecision(facts.category, priority, bool(reasons), reasons, not no_reply, reply_reason)


def product_facts(product: str) -> tuple[str, ...]:
    facts = {
        "paper_ice_cream_cups": ("Food-safe and freezer-safe; cold/frozen foods only.", "Not for hot food; not microwave-safe."),
        "compostable_cups": ("Commercially compostable only; not home compostable.", "PLA-lined cups rated up to 110 F (43 C); not for hot soup or hot drinks."),
        "wooden_spoons": ("Commercially compostable only; not home compostable.",),
        "kraft_hot_cups": ("Rated for hot drinks up to 190 F.",),
        "company": ("Packaging only; no food, ice cream, or machines.",),
        "stock_shipping": ("Orders placed before 2 pm ship within one business day; no arrival guarantee.", "Cup Club members receive free lower-48 ground shipping on stock orders of $199 or more; otherwise shipping is calculated at checkout by weight and ZIP."),
        "samples": ("Free sample box ships in 2-3 business days, lower 48 only.",),
    }
    if product not in facts:
        raise RuleInputError("Product question is not covered; escalate rather than invent facts.")
    return facts[product]
