"""Deterministic prices from the fictional challenge knowledge base.

No AI, customer discounts, automatic quantity changes, or delivery guarantees.
"""

from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from .config import SCENARIO_DATE
from .models import (
    DESTINATIONS, PRODUCTION_PATHS, CustomQuote, CustomRequest, ProductionWindow,
    StockItem, StockQuote,
)

D = Decimal
ZERO = D("0.00")
DIGITAL = {8: D("0.22"), 12: D("0.26")}
USA = {8: (D("0.115"), D("0.098"), D("0.089")), 12: (D("0.128"), D("0.110"), D("0.099")), 16: (D("0.142"), D("0.121"), D("0.109"))}
OVERSEAS = {8: (D("0.062"), D("0.055")), 12: (D("0.071"), D("0.063")), 16: (D("0.079"), D("0.070"))}

CATALOG = {item.sku: item for item in (
    StockItem("KR-08", "8 oz Kraft Single Wall Paper Hot Cups", 1000, D("79.99"), "In stock"),
    StockItem("LID-80B", "Black Hot Cup Lids, 8 oz (80 mm)", 1000, D("49.99"), "In stock"),
    StockItem("IC-08S", "8 oz UNIQ Striped Ice Cream Cups", 1000, D("64.99"), "In stock"),
    StockItem("IC-12P", "12 oz UNIQ Polka Dot Ice Cream Cups", 1000, D("74.99"), "In stock"),
    StockItem("LID-IC", "Paper Lids for 8 oz / 12 oz Ice Cream Cups", 1000, D("44.99"), "In stock"),
    StockItem("TG-16", "16 oz Paper Pint To-Go Containers with Lids", 250, D("69.99"), "In stock"),
    StockItem("TG-32", "32 oz Paper Quart To-Go Containers with Lids", 250, D("89.99"), "Low stock; back March 22, 2027"),
    StockItem("SP-MIX", "Mixed Colors Super Dessert Spoons", 1000, D("29.99"), "In stock"),
    StockItem("SP-CC", "Color Changing Spoons (yellow to green)", 1000, D("109.99"), "In stock"),
    StockItem("ECO-12", "12 oz Compostable (PLA-lined) Ice Cream Cups", 1000, D("94.99"), "In stock"),
    StockItem("ECO-SPW", "Wooden Spoons (compostable)", 1000, D("39.99"), "Out of stock; no ETA"),
    StockItem("PET-16", "16 oz Clear PET Plastic Cold Cups", 1000, D("119.99"), "In stock"),
    StockItem("TUB-3W", "3 Gallon White Plastic Ice Cream Tubs", 10, D("69.99"), "In stock"),
)}


class RuleInputError(ValueError):
    """Missing or invalid explicit facts; never coerce into a guessed quote."""


def money(value: Decimal) -> Decimal:
    return value.quantize(D("0.01"), rounding=ROUND_HALF_UP)


def _positive_int(value, name):
    if type(value) is not int or value <= 0:
        raise RuleInputError(f"{name} must be a positive integer.")


def _destination(value):
    if value not in DESTINATIONS:
        raise RuleInputError("Destination must be lower_48, outside_lower_48, or unknown.")


def _subtotal(value):
    if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
        raise RuleInputError("Subtotal must be a finite, nonnegative Decimal.")


def custom_shipping(subtotal: Decimal, destination: str) -> Decimal | None:
    _destination(destination)
    _subtotal(subtotal)
    if destination != "lower_48":
        return None
    return ZERO if subtotal >= D("2500") else D("95.00")


def stock_shipping(subtotal: Decimal, destination: str, cup_club: bool) -> Decimal | None:
    _destination(destination)
    _subtotal(subtotal)
    if type(cup_club) is not bool:
        raise RuleInputError("Cup Club membership must be a boolean.")
    return ZERO if destination == "lower_48" and cup_club and subtotal >= D("199") else None


def add_business_days(start: date, days: int) -> date:
    if type(start) is not date or type(days) is not int or days < 0:
        raise RuleInputError("Business-day calculation needs a date and nonnegative integer days.")
    result = start
    while days:
        result += timedelta(days=1)
        if result.weekday() < 5:
            days -= 1
    return result


def production_window(request: CustomRequest, path: str, rush: bool = False, as_of: date = SCENARIO_DATE) -> ProductionWindow:
    if path not in PRODUCTION_PATHS or (rush and path != "USA partner"):
        raise RuleInputError("Unknown production path or unsupported rush path.")
    start = request.proof_approved_on or as_of
    if path == "In-house digital":
        earliest, latest = add_business_days(start, 7), add_business_days(start, 10)
    else:
        weeks = (2, 2) if rush else ((3, 4) if path == "USA partner" else (10, 12))
        earliest, latest = (start + timedelta(weeks=weeks[0]), start + timedelta(weeks=weeks[1]))
    status = "no_deadline"
    if request.deadline:
        status = "too_soon" if request.deadline < earliest else ("tight" if request.deadline <= latest else "production_window_only")
    note = "Lead time starts after proof approval; production estimates are not a guaranteed delivery date."
    if request.proof_approved_on is None:
        note += f" Conditional on proof approval on {as_of.isoformat()}."
    if path == "In-house digital":
        note += " Business days exclude weekends; holiday closures are not supplied."
    if path == "Overseas":
        note += " The 10-12 week lead time includes ocean freight."
    if rush:
        note += " Two-week rush is provisional and requires owner confirmation."
    return ProductionWindow(earliest, latest, request.proof_approved_on is None, status, note)


def quote_custom(request: CustomRequest, path: str, *, rush: bool = False, as_of: date = SCENARIO_DATE) -> CustomQuote:
    _positive_int(request.quantity, "Quantity")
    _positive_int(request.size_oz, "Size")
    _destination(request.destination)
    for value in (request.full_color, request.exact_pms, request.same_design_verified, rush):
        if type(value) is not bool:
            raise RuleInputError("Color, PMS, design-verification, and rush flags must be booleans.")
    if request.previous_path is not None and request.previous_path not in PRODUCTION_PATHS:
        raise RuleInputError("Previous production path is unknown.")
    for value in (request.proof_approved_on, request.deadline, as_of):
        if value is not None and type(value) is not date:
            raise RuleInputError("Proof, deadline, and scenario dates must be date values.")
    if request.colors is not None:
        _positive_int(request.colors, "Ink color count")
    if path not in PRODUCTION_PATHS:
        raise RuleInputError("Unknown production path.")
    reasons = []
    if request.size_oz not in (8, 12, 16):
        reasons.append("Only 8, 12, and 16 oz custom cups are listed.")
    if rush and path != "USA partner":
        reasons.append("Rush is only described for the USA partner path.")
    if path == "In-house digital":
        if request.size_oz not in DIGITAL:
            reasons.append("In-house digital supports 8 and 12 oz only.")
        if not 1000 <= request.quantity <= 9999 or request.quantity % 1000:
            reasons.append("Digital requires 1,000-9,999 cups in multiples of 1,000.")
        if request.exact_pms:
            reasons.append("Digital offers close color matching only, without a PMS guarantee.")
    elif path == "USA partner":
        if request.quantity < 10000 or request.quantity % 1000:
            reasons.append("USA partner requires at least 10,000 cups in multiples of 1,000 per size/design.")
        if request.colors is None:
            reasons.append("USA partner pricing requires an ink color count.")
        elif request.colors > 4:
            reasons.append("USA partner supports a maximum of four ink colors.")
        if request.full_color:
            reasons.append("Full-color/gradient artwork needs digital or overseas offset, or confirmed artwork changes for flexographic printing.")
    elif request.quantity < 50000:
        reasons.append("Overseas requires at least 50,000 cups per size/design.")
    if reasons:
        return CustomQuote(path, False, tuple(reasons), request.quantity)

    setup_reused = request.same_design_verified and request.previous_path == path
    if path == "In-house digital":
        unit, setup = DIGITAL[request.size_oz], ZERO
    elif path == "USA partner":
        tier = 2 if request.quantity >= 50000 else (1 if request.quantity >= 25000 else 0)
        unit = USA[request.size_oz][tier] + D("0.010") * max(0, request.colors - 2)
        setup = ZERO if setup_reused else D("150") * request.colors
    else:
        unit = OVERSEAS[request.size_oz][int(request.quantity >= 100000)]
        setup = ZERO if setup_reused else D("400.00")
    cup_cost = money(unit * request.quantity)
    rush_fee = money(cup_cost * D("0.15")) if rush else ZERO
    subtotal = money(cup_cost + rush_fee + setup)
    shipping = custom_shipping(subtotal, request.destination)
    total = money(subtotal + shipping) if shipping is not None else None
    deposit = money(total * D("0.50")) if total is not None else None
    balance = money(total - deposit) if total is not None else None
    production = production_window(request, path, rush, as_of)
    human = []
    if (total if total is not None else subtotal) >= D("5000"):
        human.append("Estimated order value is $5,000 or more.")
    if request.destination == "outside_lower_48":
        human.append("Owner must quote shipping outside the lower 48; duties are unknown.")
    if rush:
        human.append("Only the owner can confirm a rush.")
    if production.deadline_status in ("too_soon", "tight"):
        human.append("Deadline is at risk against the standard production window; owner review required.")
    math = f"{request.quantity:,} x ${unit} = ${cup_cost:,.2f} + setup ${setup:,.2f}"
    if rush:
        math += f" + rush (15% of cup cost only) ${rush_fee:,.2f}"
    math += f" = subtotal ${subtotal:,.2f}"
    math += f" + shipping ${shipping:,.2f} = ${total:,.2f}" if total is not None else "; shipping unknown; final total and deposit pending"
    terms = [
        "Estimate valid for 30 days; sales tax excluded.",
        "50% deposit starts production; balance due before shipping.",
        "Vector artwork required (AI, EPS, PDF, SVG); simple logo layout is free; custom design is $75/hour.",
        "Digital proof required; lead time begins at proof approval.",
        "Custom lids are not offered; stock lids are sold separately.",
    ]
    if request.destination == "unknown":
        terms.append("Confirm destination before quoting shipping or a final total.")
    if setup_reused:
        terms.append("Setup waived only for verified unchanged design on the same production path.")
    return CustomQuote(path, True, (), request.quantity, unit, cup_cost, setup, rush_fee,
                       subtotal, shipping, total, deposit, balance, math, production, tuple(human), tuple(terms))


def quote_options(request: CustomRequest, *, as_of: date = SCENARIO_DATE) -> tuple[CustomQuote, ...]:
    """Return every path, including rejection reasons; never silently round quantity."""
    return tuple(quote_custom(request, path, as_of=as_of) for path in PRODUCTION_PATHS)


def quote_stock(lines: dict[str, int], *, destination: str = "unknown", cup_club: bool = False) -> StockQuote:
    _destination(destination)
    if type(cup_club) is not bool:
        raise RuleInputError("Cup Club membership must be a boolean.")
    if not lines:
        raise RuleInputError("At least one stock SKU/case count is required.")
    subtotal, math, availability = ZERO, [], []
    for sku, cases in lines.items():
        _positive_int(cases, "Case count")
        if sku not in CATALOG:
            raise RuleInputError(f"Unknown stock SKU: {sku}.")
        item = CATALOG[sku]
        cost = money(item.price * cases)
        subtotal += cost
        math.append(f"{cases} case(s) x {sku} at ${item.price} = ${cost:,.2f}")
        availability.append(f"{sku}: {item.availability}")
    shipping = stock_shipping(subtotal, destination, cup_club)
    total = money(subtotal + shipping) if shipping is not None else None
    human = []
    if subtotal >= D("5000"):
        human.append("Estimated order value is $5,000 or more.")
    if destination == "outside_lower_48":
        human.append("Owner must handle shipping outside the lower 48.")
    return StockQuote(tuple(math), subtotal, shipping, total, tuple(availability), tuple(human))
