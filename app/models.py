"""Source evidence and typed business-rule requests and decisions."""

from dataclasses import asdict, dataclass, is_dataclass
from datetime import date
from decimal import Decimal

EMAIL_COLUMNS = ("email_id", "received_at", "from_name", "from_email", "subject", "body")
ORDER_COLUMNS = (
    "order_id", "customer_name", "customer_email", "order_date", "order_type",
    "items", "production_path", "order_total", "status", "ship_date",
    "delivered_date", "carrier", "tracking", "notes",
)
EXPORT_COLUMNS = ("email_id", "category", "priority", "needs_human", "quote", "draft_reply")
CATEGORIES = (
    "Custom Quote", "Stock Order / Product Question", "Order Status",
    "Damage / Complaint", "Return / Refund", "Billing / Terms",
    "Spam / Phishing", "Vendor Pitch", "Feedback / Praise",
)
PRIORITIES = ("P1", "P2", "P3", "P4")


@dataclass(frozen=True)
class Email:
    email_id: str
    received_at: str
    from_name: str
    from_email: str
    subject: str
    body: str


@dataclass(frozen=True)
class Order:
    order_id: str
    customer_name: str
    customer_email: str
    order_date: str
    order_type: str
    items: str
    production_path: str
    order_total: str
    status: str
    ship_date: str
    delivered_date: str
    carrier: str
    tracking: str
    notes: str


@dataclass(frozen=True)
class OrderCandidate:
    order: Order
    score: int
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class OrderContext:
    candidates: tuple[OrderCandidate, ...]
    suggested_order_id: str | None
    explanation: str


@dataclass(frozen=True)
class InboxRecord:
    email: Email
    order_context: OrderContext


# Business records contain explicit facts, not free-form customer instructions.
PRODUCTION_PATHS = ("In-house digital", "USA partner", "Overseas")
DESTINATIONS = ("lower_48", "outside_lower_48", "unknown")


@dataclass(frozen=True)
class CustomRequest:
    size_oz: int
    quantity: int
    colors: int | None = None
    full_color: bool = False
    exact_pms: bool = False
    destination: str = "unknown"
    same_design_verified: bool = False
    previous_path: str | None = None
    proof_approved_on: date | None = None
    deadline: date | None = None


@dataclass(frozen=True)
class ProductionWindow:
    earliest: date
    latest: date
    approval_assumed: bool
    deadline_status: str
    note: str


@dataclass(frozen=True)
class CustomQuote:
    path: str
    eligible: bool
    reasons: tuple[str, ...]
    quantity: int
    unit_price: Decimal | None = None
    cup_cost: Decimal | None = None
    setup: Decimal | None = None
    rush_fee: Decimal | None = None
    subtotal: Decimal | None = None
    shipping: Decimal | None = None
    total: Decimal | None = None
    deposit: Decimal | None = None
    balance: Decimal | None = None
    math: str = ""
    production: ProductionWindow | None = None
    human_reasons: tuple[str, ...] = ()
    terms: tuple[str, ...] = ()


@dataclass(frozen=True)
class StockItem:
    sku: str
    name: str
    pack: int
    price: Decimal
    availability: str


@dataclass(frozen=True)
class StockQuote:
    lines: tuple[str, ...]
    subtotal: Decimal
    shipping: Decimal | None
    total: Decimal | None
    availability: tuple[str, ...]
    human_reasons: tuple[str, ...]


@dataclass(frozen=True)
class ClaimDecision:
    outcome: str
    reasons: tuple[str, ...]
    needs_human: bool = False
    restocking_rate: Decimal | None = None
    return_shipping: str | None = None
    replacement_cases: int | None = None


@dataclass(frozen=True)
class TriageFacts:
    category: str
    estimated_value: Decimal | None = None
    rush_requested: bool = False
    deadline_at_risk: bool = False
    discount_requested: bool = False
    price_match_requested: bool = False
    terms_requested: bool = False
    destination: str = "unknown"
    custom_complaint: bool = False
    upset_outside_policy: bool = False
    legal_threat: bool = False
    chargeback: bool = False
    press: bool = False
    suspicious: bool = False
    unanswered_question: bool = False
    security_message: bool = False
    reply_today: bool = False
    quote_human_reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class TriageDecision:
    category: str
    priority: str
    needs_human: bool
    reasons: tuple[str, ...]
    reply_allowed: bool
    reply_reason: str


def jsonable(value):
    """Convert money to exact strings and dates to ISO, never float money."""
    if is_dataclass(value):
        return jsonable(asdict(value))
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: jsonable(child) for key, child in value.items()}
    if isinstance(value, (tuple, list)):
        return [jsonable(child) for child in value]
    return value
