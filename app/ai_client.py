"""Gemini REST client; structured JSON, finite timeouts, sanitized errors."""

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import quote

from .config import ai_settings
from .models import CATEGORIES, DESTINATIONS, PRODUCTION_PATHS


class AIError(ValueError):
    pass


def obj(properties):
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


STRING = {"type": "string"}
BOOL = {"type": "boolean"}
NULL_INT = {"type": ["integer", "null"]}
NULL_STRING = {"type": ["string", "null"]}
FLAG_NAMES = (
    "rush_requested", "discount_requested", "price_match_requested", "terms_requested",
    "upset_outside_policy", "legal_threat", "chargeback", "press", "suspicious", "reply_today",
    "guaranteed_delivery", "new_account",
)
EXTRACT_SCHEMA = obj({
    "category": {"type": "string", "enum": list(CATEGORIES)},
    "language": {"type": "string", "enum": ["en", "es", "fr", "other"]},
    "language_name": STRING,
    "summary": STRING,
    "size_oz": NULL_INT, "quantity": NULL_INT, "colors": NULL_INT,
    "full_color": BOOL, "exact_pms": BOOL,
    "destination": {"type": "string", "enum": list(DESTINATIONS)},
    "deadline": NULL_STRING,
    "preferred_path": {"type": ["string", "null"], "enum": [None, *PRODUCTION_PATHS]},
    "reorder": BOOL, "unchanged_design": BOOL,
    "relevant_order_id": NULL_STRING,
    "stock_lines": {"type": "array", "items": obj({"sku": STRING, "cases": {"type": "integer"}})},
    "cup_club": {"type": ["boolean", "null"]},
    "claim_type": {"type": "string", "enum": ["none", "stock_return", "shipping_damage", "custom_complaint"]},
    "opened": {"type": ["boolean", "null"]}, "damaged_cases": NULL_INT,
    "product_topics": {"type": "array", "items": {"type": "string", "enum": ["paper_ice_cream_cups", "compostable_cups", "wooden_spoons", "kraft_hot_cups", "company", "stock_shipping", "samples"]}},
    "unknown_questions": {"type": "array", "items": STRING},
    "flags": obj({name: BOOL for name in FLAG_NAMES}),
})
DRAFT_SCHEMA = obj({"draft_reply": STRING, "language": STRING})
SMOKE_SCHEMA = obj({"ok": BOOL})


def validate_schema(value, schema, location="response"):
    """Validate the small JSON-schema subset used above, even with mock clients."""
    types = schema["type"]
    if isinstance(types, str):
        types = [types]
    matches = {
        "null": value is None,
        "object": type(value) is dict,
        "array": type(value) is list,
        "string": type(value) is str,
        "integer": type(value) is int,
        "boolean": type(value) is bool,
    }
    if not any(matches.get(kind, False) for kind in types):
        raise AIError(f"Invalid structured output at {location}.")
    if "enum" in schema and value not in schema["enum"]:
        raise AIError(f"Unsupported structured value at {location}.")
    if value is None:
        return
    if type(value) is dict:
        properties = schema["properties"]
        if set(value) != set(properties):
            raise AIError(f"Missing or unexpected structured fields at {location}.")
        for name, child in properties.items():
            validate_schema(value[name], child, f"{location}.{name}")
    elif type(value) is list:
        for item in value:
            validate_schema(item, schema["items"], f"{location}[]")


class GeminiClient:
    def __init__(self, settings=None, transport=None):
        self.settings = settings if settings is not None else ai_settings()
        self.transport = transport or urlopen

    def require_configuration(self):
        if not self.settings.get("GEMINI_API_KEY") or not self.settings.get("GEMINI_MODEL"):
            raise AIError("Set GEMINI_API_KEY and GEMINI_MODEL in the local .env file or shell environment. Never paste the key into chat.")

    def complete(self, name, instructions, context, schema):
        self.require_configuration()
        payload = {
            "systemInstruction": {"parts": [{"text": instructions}]},
            "contents": [{"role": "user", "parts": [{"text": json.dumps(context, ensure_ascii=False)}]}],
            "generationConfig": {"responseMimeType": "application/json", "responseJsonSchema": schema, "maxOutputTokens": 8192},
        }
        model = self.settings["GEMINI_MODEL"].removeprefix("models/")
        endpoint = "https://generativelanguage.googleapis.com/v1beta/models/" + quote(model, safe="") + ":generateContent"
        request = Request(endpoint, data=json.dumps(payload).encode("utf-8"), headers={
            "x-goog-api-key": self.settings["GEMINI_API_KEY"],
            "Content-Type": "application/json",
        })
        try:
            with self.transport(request, timeout=90) as response:
                result = json.load(response)
        except HTTPError as exc:
            messages = {401: "Gemini authentication failed; check your local key.", 403: "Gemini access denied; check account/model access.", 404: "Configured Gemini model was not found or does not support generateContent. Check GEMINI_MODEL.", 429: "Gemini rate or quota limit reached; check usage before retrying.", 400: "Gemini rejected the request; check the key, model, and structured-output support."}
            raise AIError(messages.get(exc.code, f"API request failed (HTTP {exc.code}); retry later.")) from None
        except (URLError, TimeoutError, OSError):
            raise AIError("API connection failed or timed out. Check connectivity and retry.") from None
        except (ValueError, UnicodeError):
            raise AIError("API returned an unreadable response.") from None
        if not isinstance(result, dict):
            raise AIError("Gemini returned an unreadable response.")
        if result.get("promptFeedback", {}).get("blockReason"):
            raise AIError("Gemini blocked this request; review the email manually.")
        candidates = result.get("candidates")
        if not isinstance(candidates, list) or not candidates or not isinstance(candidates[0], dict):
            raise AIError("Gemini returned no completed candidate; no draft was accepted.")
        candidate = candidates[0]
        if candidate.get("finishReason") != "STOP":
            raise AIError("Gemini response was blocked, incomplete, or truncated; no draft was accepted.")
        chunks = []
        for part in candidate.get("content", {}).get("parts", []):
            if isinstance(part, dict) and isinstance(part.get("text"), str) and not part.get("thought"):
                chunks.append(part["text"])
        try:
            parsed = json.loads("".join(chunks))
        except (ValueError, TypeError):
            raise AIError("Model did not return valid structured JSON.") from None
        validate_schema(parsed, schema)
        return parsed

    def smoke_test(self):
        result = self.complete("connection_check", "Return {\"ok\":true} to confirm structured output support.", {}, SMOKE_SCHEMA)
        if result["ok"] is not True:
            raise AIError("API configuration check did not succeed.")
        return {"ok": True, "message": "Gemini connection and structured output verified."}
