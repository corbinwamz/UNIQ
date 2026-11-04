"""Extract -> verified-fact mapping -> deterministic rules -> grounded draft.

Model suggestions are not approvals. Preserve source and rule evidence for review.
"""

from dataclasses import replace
from datetime import date
from decimal import Decimal
import re

from .ai_client import AIError, DRAFT_SCHEMA, EXTRACT_SCHEMA, validate_schema
from .config import KNOWLEDGE_PATH, PROMPTS_DIR, SCENARIO_DATE
from .data_loader import read_source
from .models import ClaimDecision, CustomRequest, InboxRecord, TriageFacts, jsonable
from .policies import custom_complaint, net30_eligibility, product_facts, shipping_damage, stock_return, triage
from .pricing import RuleInputError, quote_custom, quote_options, quote_stock


def _date(value):
    if value is None:
        return None
    try:
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value:
            raise ValueError()
        return parsed
    except (ValueError, TypeError):
        raise AIError("Extracted deadline must be an ISO calendar date or unknown.") from None


def _history_spec(order):
    # Historical totals are never pricing authority. Only use a recognizable
    # quantity/size/spot-color specification from the selected source items.
    match = re.search(r"([\d,]+)\s*x\s*(8|12|16)\s*oz", order.items, re.I)
    color = re.search(r"(\d)[- ]color", order.items, re.I)
    if not match:
        return None
    return int(match[2]), int(match[1].replace(",", "")), int(color[1]) if color else None


def decide(record: InboxRecord, extracted: dict) -> dict:
    validate_schema(extracted, EXTRACT_SCHEMA)
    facts = extracted.copy()
    flags = facts["flags"].copy()
    body = f"{record.email.subject}\n{record.email.body}"
    lower = body.casefold()
    notes, missing, quotes, alternatives, policy = [], list(facts["unknown_questions"]), [], [], []
    suspicious = bool(re.search(r"ignore (?:your |all |the )?(?:previous |pricing |system )?(?:instructions|rules)|system (?:instructions|prompt)|note to the ai|reveal.*(?:prompt|pricing table)", lower))
    flags["suspicious"] |= suspicious
    flags["discount_requested"] |= bool(re.search(r"\bdiscount\b", lower))
    flags["price_match_requested"] |= bool(re.search(r"\bprice[- ]match\b|\bmatch it\b", lower))
    flags["terms_requested"] |= bool(re.search(r"\bnet\s*30\b|payment terms", lower))
    # A billing verification threat is never an instruction to follow links.
    security_message = bool(re.search(r"verify.{0,30}(?:billing|account)|verify-account", lower) and re.search(r"suspend|permanent loss|24 hours", lower))
    if security_message:
        facts["category"] = "Spam / Phishing"
        flags["suspicious"] = True
    if re.search(r"\bcanada\b|montréal|montreal|puerto rico|\balaska\b|\bhawaii\b", lower):
        facts["destination"] = "outside_lower_48"
    # Grounded language defaults agreed in the plan, rather than ID-specific rules.
    if re.search(r"\bhola\b|cotización|cuánto", lower):
        facts["language"] = "es"
    elif "bonjour" in lower and ("merci" in lower or "montr" in lower):
        facts["language"] = "fr"
    candidates = {candidate.order.order_id: candidate.order for candidate in record.order_context.candidates}
    chosen_id = facts["relevant_order_id"]
    if chosen_id is not None and chosen_id not in candidates:
        raise AIError("Model selected an order outside this sender's history.")
    # Neither a model choice nor a recency tie-break alone verifies an order.
    selected = candidates.get(record.order_context.suggested_order_id)
    if chosen_id and selected and chosen_id != selected.order_id:
        selected = None
        notes.append("Model and contextual order suggestions disagree; confirm the relevant order.")
    if selected:
        notes.append(f"Order context from {selected.order_id}; confirm with the customer when ambiguous.")

    request = None
    quote_text = ""
    chosen = None
    deadline_risk = False
    wants_custom = facts["category"] == "Custom Quote" or facts["reorder"] or (facts["quantity"] is not None and flags["terms_requested"])
    if wants_custom:
        size, quantity, colors = facts["size_oz"], facts["quantity"], facts["colors"]
        unchanged = facts["unchanged_design"] and bool(re.search(r"nothing changed|unchanged|same logo|same design", lower))
        verified_reorder = False
        previous = None
        if facts["reorder"] and selected and selected.order_type == "Custom":
            previous = selected.production_path
            old_spec = _history_spec(selected)
            if old_spec:
                old_size, old_qty, old_colors = old_spec
                size = size if size is not None else old_size
                colors = colors if colors is not None else old_colors
                if quantity is None:
                    quantity = old_qty * (2 if re.search(r"\bdouble\b|\btwice\b", lower) else 1)
                verified_reorder = unchanged and (previous != "USA partner" or "plates on file" in selected.notes.casefold())
                notes.append("Reorder specification derived from source items; new pricing uses current code tables.")
            else:
                missing.append("Confirm the prior design specification and quantity.")
        if size is None or quantity is None:
            missing.append("Confirm cup size and quantity before quoting.")
            quote_text = "Quote pending: confirm cup size and quantity."
        else:
            request = CustomRequest(size, quantity, colors, facts["full_color"], facts["exact_pms"], facts["destination"], verified_reorder, previous, deadline=_date(facts["deadline"]))
            quotes = list(quote_options(request))
            eligible = [quote for quote in quotes if quote.eligible]
            # Do not choose the cheap path if it cannot reach even the production
            # window. Tight paths remain provisional and require owner review.
            feasible = [quote for quote in eligible if quote.production.deadline_status != "too_soon"]
            preferred = facts["preferred_path"] or (previous if facts["reorder"] else None)
            domestic_only = preferred == "USA partner"
            if domestic_only:
                feasible = [quote for quote in feasible if quote.path == "USA partner"]
            preferred_feasible = [quote for quote in feasible if quote.path == preferred]
            pool = preferred_feasible or feasible
            if pool:
                chosen = min(pool, key=lambda quote: (quote.production.deadline_status == "tight", quote.subtotal))
            if preferred and not preferred_feasible:
                notes.append("Requested production preference is unavailable or cannot meet even the production window; alternatives are conditional.")
            if not chosen and eligible:
                deadline_risk = True
                notes.append("No requested-spec path has a feasible production window; owner must assess alternatives.")
            if request.deadline and not feasible:
                deadline_risk = True
            if chosen and chosen.production.deadline_status == "tight":
                deadline_risk = True
            # A rush quote is a provisional alternative, never a confirmation.
            usa = next(quote for quote in quotes if quote.path == "USA partner")
            if usa.eligible and (flags["rush_requested"] or (request.deadline and usa.production.deadline_status in ("tight", "too_soon"))):
                rush = quote_custom(request, "USA partner", rush=True)
                alternatives.append({"label": "Provisional rush; owner confirmation required", "quote": rush})
            if not eligible and request.size_oz == 16 and request.quantity < 10000:
                larger = quote_custom(replace(request, quantity=10000, same_design_verified=False), "USA partner")
                if larger.eligible:
                    alternatives.append({"label": "Different quantity: 10,000 cups (not the requested quantity)", "quote": larger})
            if chosen:
                quote_text = f"{chosen.path}: {chosen.math}. Estimate valid 30 days; sales tax excluded."
            else:
                quote_text = "No confirmed quote for the requested specification. " + " ".join(f"{quote.path}: {'; '.join(quote.reasons) if not quote.eligible else quote.math + '; deadline review required'}" for quote in quotes)
            for alternative in alternatives:
                quote_text += f"\n{alternative['label']}: {alternative['quote'].path}: {alternative['quote'].math}."
            if colors is None and quantity >= 10000:
                missing.append("Confirm ink color count to calculate USA setup and any color surcharges.")
            if facts["destination"] == "unknown":
                missing.append("Confirm the shipping destination; freight and final total are incomplete.")
    stock = None
    if facts["stock_lines"]:
        lines = {}
        for line in facts["stock_lines"]:
            lines[line["sku"]] = lines.get(line["sku"], 0) + line["cases"]
        membership = facts["cup_club"] is True
        # Explicit current customer claim or sender-scoped historical membership,
        # not a model-invented eligibility flag.
        membership = membership and (bool(re.search(r"(?:i am|we are|i'm|we're).{0,15}cup club|cup club member", lower)) or any("cup club member" in order.notes.casefold() for order in candidates.values()))
        stock = quote_stock(lines, destination=facts["destination"], cup_club=membership)
        notes.append("Stock shipping is calculated at checkout unless verified free-shipping conditions apply.")
    claim = facts["claim_type"]
    if claim != "none":
        if selected is None:
            missing.append("Confirm order ID and delivery date before assessing the claim.")
        else:
            delivered = _date(selected.delivered_date or None)
            if claim == "shipping_damage":
                if facts["damaged_cases"] is None:
                    missing.append("Confirm how many cases were damaged.")
                else:
                    policy.append(shipping_damage(delivered_on=delivered, damaged_cases=facts["damaged_cases"], photos_received=False))
            elif claim == "stock_return":
                if selected.order_type != "Stock":
                    policy.append(ClaimDecision("owner_review", ("Custom items cannot be returned; owner must review the complaint.",), True))
                elif facts["opened"] is None:
                    missing.append("Confirm whether the cases are unopened.")
                else:
                    policy.append(stock_return(delivered_on=delivered, opened=facts["opened"]))
            else:
                policy.append(custom_complaint(delivered_on=delivered, production_path=selected.production_path, photos_received=False))
                # Always remind drafting of the approved digital standard, while
                # not deciding whether this actual variation is within tolerance.
                if selected.production_path == "In-house digital":
                    notes.append("Historical proof states close color match, no Pantone guarantee; owner must assess actual variation.")
    if facts["category"] == "Order Status" and selected is None:
        missing.append("Confirm order ID; no uniquely relevant tracking record is established.")
    if flags["terms_requested"]:
        if flags["new_account"] and re.search(r"brand new|brand-new|new (?:shop|account)|opening this summer", lower):
            policy.append(ClaimDecision("not_eligible", ("New account does not meet six-month history requirement for Net 30; owner review required. Standard custom payment is 50% deposit and balance before shipping.",), True))
        else:
            old_enough = [order for order in candidates.values() if date.fromisoformat(order.order_date) <= date(2026, 9, 8)]
            policy.append(net30_eligibility(min((date.fromisoformat(order.order_date) for order in old_enough), default=None)))
    topics = {topic: product_facts(topic) for topic in facts["product_topics"]}
    active_quotes = ([chosen] if chosen else []) + [alternative["quote"] for alternative in alternatives]
    estimated_values = [quote.total if quote.total is not None else quote.subtotal for quote in active_quotes]
    if not estimated_values:
        estimated_values = [quote.total if quote.total is not None else quote.subtotal for quote in quotes if quote.eligible]
    if stock:
        estimated_values.append(stock.total if stock.total is not None else stock.subtotal)
    quote_human = [reason for quote in active_quotes for reason in quote.human_reasons]
    if stock:
        quote_human.extend(stock.human_reasons)
    quote_human.extend(reason for decision in policy if decision.needs_human for reason in decision.reasons)
    decision = triage(TriageFacts(
        category=facts["category"], estimated_value=max(estimated_values, default=None),
        rush_requested=flags["rush_requested"], deadline_at_risk=deadline_risk,
        discount_requested=flags["discount_requested"], price_match_requested=flags["price_match_requested"],
        terms_requested=flags["terms_requested"], destination=facts["destination"],
        custom_complaint=claim == "custom_complaint" or (selected is not None and selected.order_type == "Custom" and facts["category"] == "Damage / Complaint"),
        upset_outside_policy=flags["upset_outside_policy"], legal_threat=flags["legal_threat"],
        chargeback=flags["chargeback"], press=flags["press"], suspicious=flags["suspicious"],
        unanswered_question=bool(facts["unknown_questions"]) or (facts["category"] == "Order Status" and selected is None),
        security_message=security_message, reply_today=flags["reply_today"], quote_human_reasons=tuple(quote_human),
    ))
    # Rendering uses a separate result; the structured extraction is retained as
    # model evidence and cannot overwrite final category/priority/prices.
    return jsonable({
        "triage": decision, "language": facts["language"], "language_name": facts["language_name"],
        "summary": facts["summary"], "quote": quote_text, "selected_quote": chosen,
        "quote_options": quotes, "alternatives": alternatives, "stock_quote": stock,
        "selected_order": selected, "policy_decisions": policy, "product_facts": topics,
        "missing_information": list(dict.fromkeys(missing)), "notes": notes,
    })


def validate_draft(reply: str, decisions: dict, knowledge: str) -> None:
    if not reply.strip() or len(reply) > 18000:
        raise AIError("Draft is empty or too long; review before retrying.")
    if not reply.rstrip().endswith("The UNIQ Supply Team"):
        raise AIError("Draft is missing the required team sign-off.")
    lower = reply.casefold()
    if any(fragment in lower for fragment in ("ignore your previous", "system instructions", "system prompt", "note to the ai", "| size |", "openai_api_key", "gemini_api_key")):
        raise AIError("Draft contains internal or suspicious instruction content; no draft accepted.")
    if re.search(r"\b(?:i|we)(?:'ve| have)? (?:processed|issued|shipped|refunded)\b|guarantee(?:d)? (?:delivery|arrival)|rush is confirmed|40% discount", lower):
        raise AIError("Draft claims an unauthorized action, guarantee, or discount.")
    # Reject invented currency amounts, including amounts injected by a customer.
    context = str(decisions)
    allowed = {Decimal(amount.replace(",", "")) for amount in re.findall(r"\$\s*([\d,]+(?:\.\d+)?)", context)}
    monetary_keys = {"unit_price", "cup_cost", "setup", "rush_fee", "subtotal", "shipping", "total", "deposit", "balance", "price"}
    def collect(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key in monetary_keys and isinstance(child, str):
                    allowed.add(Decimal(child))
                else:
                    collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)
    collect(decisions)
    for amount in re.findall(r"\$\s*([\d,]+(?:\.\d+)?)", reply):
        if Decimal(amount.replace(",", "")) not in allowed:
            raise AIError("Draft contains a price not present in the verified decision record.")
    # Long verbatim internal policy dumps are not a customer reply.
    if any(line.strip() in reply for line in knowledge.splitlines() if len(line.strip()) > 220):
        raise AIError("Draft copies an internal policy passage; shorten to a customer-specific reply.")


def append_quote_summary(reply: str, decisions: dict) -> str:
    """Render monetary facts in code, so the reply cannot omit quote math.

    Prose stays model-generated; the short formula block uses localized labels
    for the three packet languages. Other languages retain the verified formula.
    """
    language = decisions["language"]
    labels = {
        "en": ("Estimated quote (sales tax excluded; valid 30 days)", "Alternative — different quantity", "Provisional rush — owner confirmation required", "Deposit", "Balance before shipping"),
        "es": ("Cotización estimada (sin impuesto; válida por 30 días)", "Alternativa — cantidad diferente", "Producción urgente provisional — requiere confirmación del propietario", "Anticipo", "Saldo antes del envío"),
        "fr": ("Devis estimatif (hors taxes; valable 30 jours)", "Autre option — quantité différente", "Production urgente provisoire — confirmation du propriétaire requise", "Acompte", "Solde avant expédition"),
    }
    heading, alternative_label, rush_label, deposit_label, balance_label = labels.get(language, labels["en"])
    def formula(quote):
        text = quote["math"]
        replacements = {
            "es": {"setup": "preparación", "shipping unknown; final total and deposit pending": "envío desconocido; total final y anticipo pendientes", "shipping": "envío", "rush (15% of cup cost only)": "urgencia (15% solo sobre los vasos)"},
            "fr": {"setup": "préparation", "subtotal": "sous-total", "shipping unknown; final total and deposit pending": "transport inconnu; total final et acompte en attente", "shipping": "transport", "rush (15% of cup cost only)": "urgence (15% du coût des gobelets uniquement)"},
        }
        for old, new in replacements.get(language, {}).items():
            text = text.replace(old, new)
        if quote["deposit"] is not None:
            text += f"\n{deposit_label} (50%): ${Decimal(quote['deposit']):,.2f}. {balance_label}: ${Decimal(quote['balance']):,.2f}."
        return text
    blocks = []
    if decisions["selected_quote"]:
        blocks.append(heading + ":\n" + formula(decisions["selected_quote"]))
    for alternative in decisions["alternatives"]:
        label = rush_label if "rush" in alternative["label"].casefold() else alternative_label
        blocks.append(label + ":\n" + formula(alternative["quote"]))
    stock = decisions["stock_quote"]
    if stock:
        # Stock lines already contain SKU, count, and exact multiplication.
        stock_text = "\n".join(stock["lines"])
        stock_text += f"\nSubtotal: ${Decimal(stock['subtotal']):,.2f}."
        stock_text += (f" Total: ${Decimal(stock['total']):,.2f}." if stock["total"] is not None else {"es": " Envío calculado al finalizar la compra; total final pendiente.", "fr": " Transport calculé à la commande; total final en attente."}.get(language, " Shipping calculated at checkout; final total pending."))
        blocks.append(stock_text)
    if not blocks:
        return reply
    signature = "The UNIQ Supply Team"
    return reply[:-len(signature)].rstrip() + "\n\n" + "\n\n".join(blocks) + "\n\n" + signature


class Pipeline:
    def __init__(self, client):
        self.client = client

    def process(self, record: InboxRecord) -> dict:
        knowledge = read_source(KNOWLEDGE_PATH)
        extracted = self.client.complete("inbox_extraction", (PROMPTS_DIR / "extract.md").read_text(encoding="utf-8"),
                                         {"scenario_date": SCENARIO_DATE.isoformat(), "knowledge_base": knowledge, "record": jsonable(record)}, EXTRACT_SCHEMA)
        decisions = decide(record, extracted)
        triage_result = decisions["triage"]
        if not triage_result["reply_allowed"]:
            reply = triage_result["reply_reason"]
        else:
            generated = self.client.complete("customer_draft", (PROMPTS_DIR / "draft.md").read_text(encoding="utf-8"),
                                             {"customer": jsonable(record.email), "verified_decisions": decisions}, DRAFT_SCHEMA)
            validate_schema(generated, DRAFT_SCHEMA)
            if generated["language"] != decisions["language"]:
                raise AIError("Draft language does not match the customer language.")
            reply = generated["draft_reply"].strip()
            validate_draft(reply, decisions, knowledge)
            reply = append_quote_summary(reply, decisions)
        return {
            "email_id": record.email.email_id, "category": triage_result["category"],
            "priority": triage_result["priority"],
            "needs_human": ("Yes — " + "; ".join(triage_result["reasons"])) if triage_result["needs_human"] else "No — standard policy response.",
            "quote": decisions["quote"], "draft_reply": reply,
            "decisions": decisions, "extraction": extracted,
        }
