"""CSV parsing and conservative, explainable order-context suggestions.

Suggestions are evidence for review, never authority to grant refunds or reuse
plates. All sender-matched history is retained, including ambiguous candidates.
"""

import csv
from datetime import date, datetime
import io
from pathlib import Path
import re

from .models import EMAIL_COLUMNS, ORDER_COLUMNS, Email, InboxRecord, Order, OrderCandidate, OrderContext


class DataValidationError(ValueError):
    """A source file cannot safely be used; message is suitable for the UI."""


def normalize_email(value: str) -> str:
    return value.strip().casefold()


def read_source(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        raise DataValidationError(f"Cannot read {path.name} as UTF-8 CSV.") from exc


def _rows(text: str, columns: tuple[str, ...], label: str) -> list[dict[str, str]]:
    try:
        reader = csv.reader(io.StringIO(text.lstrip("\ufeff"), newline=""), strict=True)
        header = next(reader, None)
        if not header:
            raise DataValidationError(f"{label}: CSV is empty; a header is required.")
        header = [name.strip() for name in header]
        if len(set(header)) != len(header) or any(not name for name in header):
            raise DataValidationError(f"{label}: duplicate or blank column names.")
        missing = set(columns) - set(header)
        if missing:
            raise DataValidationError(f"{label}: missing columns: {', '.join(sorted(missing))}.")
        result = []
        for fields in reader:
            if not fields or all(not field.strip() for field in fields):
                continue
            if len(fields) != len(header):
                raise DataValidationError(f"{label}: line {reader.line_num} has {len(fields)} fields; expected {len(header)}.")
            row = dict(zip(header, fields))
            result.append({name: row[name].strip() for name in columns})
        if not result:
            raise DataValidationError(f"{label}: no data rows found.")
        return result
    except csv.Error as exc:
        raise DataValidationError(f"{label}: malformed CSV: {exc}.") from exc


def _required(row: dict[str, str], names: tuple[str, ...], label: str) -> None:
    for name in names:
        if not row[name]:
            raise DataValidationError(f"{label}: {name} must not be blank.")


def _address(value: str, label: str) -> str:
    value = normalize_email(value)
    if not re.fullmatch(r"[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+", value):
        raise DataValidationError(f"{label}: invalid email address.")
    return value


def _unique(rows: list[dict[str, str]], key: str, label: str) -> None:
    seen = set()
    for row in rows:
        if row[key] in seen:
            raise DataValidationError(f"{label}: duplicate {key}: {row[key]}.")
        seen.add(row[key])


def parse_inbox(text: str) -> list[Email]:
    rows = _rows(text, EMAIL_COLUMNS, "Inbox")
    _unique(rows, "email_id", "Inbox")
    for row in rows:
        label = f"Inbox {row['email_id'] or '(missing ID)'}"
        _required(row, ("email_id", "received_at", "from_email", "body"), label)
        row["from_email"] = _address(row["from_email"], label)
        try:
            datetime.strptime(row["received_at"], "%Y-%m-%d %H:%M")
        except ValueError as exc:
            raise DataValidationError(f"{label}: received_at must be YYYY-MM-DD HH:MM.") from exc
    return [Email(**row) for row in rows]


def parse_orders(text: str) -> list[Order]:
    rows = _rows(text, ORDER_COLUMNS, "Orders")
    _unique(rows, "order_id", "Orders")
    for row in rows:
        label = f"Order {row['order_id'] or '(missing ID)'}"
        _required(row, ("order_id", "customer_email", "order_date", "order_type", "items", "production_path", "status"), label)
        row["customer_email"] = _address(row["customer_email"], label)
        for field in ("order_date", "ship_date", "delivered_date"):
            if row[field]:
                try:
                    if date.fromisoformat(row[field]).isoformat() != row[field]:
                        raise ValueError("Date is not in canonical YYYY-MM-DD format")
                except ValueError as exc:
                    raise DataValidationError(f"{label}: {field} must be YYYY-MM-DD.") from exc
    return [Order(**row) for row in rows]


def match_orders(email: Email, orders: list[Order]) -> OrderContext:
    history = [order for order in orders if normalize_email(order.customer_email) == normalize_email(email.from_email)]
    if not history:
        return OrderContext((), None, "No order history matches this sender's email address.")
    text = f"{email.subject}\n{email.body}".casefold()
    references = set(re.findall(r"\buq-\d+\b", text))
    reorder = bool(re.search(r"\breorder\b|same (?:cups|logo)|last spring", text))
    custom = reorder or bool(re.search(r"\bcustom\b|\bprinted\b|\bprint\b|\bpantone\b|\bbrand (?:blue|colo[u]?rs?)\b", text))
    status_request = bool(re.search(r"where (?:are|is)|haven't (?:gotten|received)|tracking|check on|still.*(?:waiting|arrived)", text))
    candidates = []
    for order in history:
        score = 0
        reasons = ["Exact normalized sender email match"]
        if references and order.order_id.casefold() in references:
            score += 100
            reasons.append("Order ID explicitly mentioned")
        if custom and order.order_type.casefold() == "custom":
            score += 4
            reasons.append("Custom/reorder wording matches custom order")
        if status_request and "transit" in order.status.casefold():
            score += 4
            reasons.append("Status question matches in-transit order")
        for word in ("cups", "spoons", "lids"):
            if re.search(rf"\b{word}\b", text) and re.search(rf"\b{word}\b", order.items.casefold()):
                score += 2
                reasons.append(f"Product mentioned: {word}")
        sizes = set(re.findall(r"\b(8|12|16|32)\s*oz\b", text))
        if sizes and sizes.intersection(re.findall(r"\b(8|12|16|32)\s*oz\b", order.items.casefold())):
            score += 2
            reasons.append("Cup size mentioned matches")
        candidates.append(OrderCandidate(order, score, tuple(reasons)))
    candidates.sort(key=lambda candidate: (candidate.score, candidate.order.order_date, candidate.order.order_id), reverse=True)
    # Explicit references that cannot be uniquely resolved must not silently
    # fall back to a similarly worded or more recent order.
    if references:
        referenced = [c for c in candidates if c.order.order_id.casefold() in references]
        if len(references) != 1 or len(referenced) != 1:
            return OrderContext(tuple(candidates), None, "Explicit order references are missing or ambiguous; review history.")
        return OrderContext(tuple(candidates), referenced[0].order.order_id, "Suggested by explicit order ID within this sender's history; confirm before action.")
    top = candidates[0]
    if top.score > 0 and (len(candidates) == 1 or top.score > candidates[1].score):
        return OrderContext(tuple(candidates), top.order.order_id, "Suggested by message context; confirm before action. All sender history is retained.")
    return OrderContext(tuple(candidates), None, "No unique contextual match; review candidate history. Recency alone is not sufficient.")


def build_inbox(emails: list[Email], orders: list[Order]) -> list[InboxRecord]:
    return [InboxRecord(email, match_orders(email, orders)) for email in emails]
