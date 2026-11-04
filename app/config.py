"""Project-root paths; no dependency on the current working directory."""

from datetime import date
from pathlib import Path
import os

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INBOX_PATH = PROJECT_ROOT / "inbox.csv"
ORDERS_PATH = PROJECT_ROOT / "orders.csv"
STATIC_DIR = Path(__file__).resolve().parent / "static"
SCENARIO_DATE = date(2027, 3, 8)
MAX_IMPORT_BYTES = 2 * 1024 * 1024
RUNS_DIR = PROJECT_ROOT / "output" / "runs"
PROMPTS_DIR = PROJECT_ROOT / "prompts"
KNOWLEDGE_PATH = PROJECT_ROOT / "knowledge_base.md"


def ai_settings() -> dict[str, str]:
    """Read only supported .env names; shell variables take precedence.

    No execution, interpolation, or global environment mutation. Reread on each
    operation so configuring .env does not require restarting the app.
    """
    values = {}
    path = PROJECT_ROOT / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            name, separator, value = line.partition("=")
            if separator and name.strip() in ("OPENAI_API_KEY", "OPENAI_MODEL"):
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                    value = value[1:-1]
                values[name.strip()] = value
    return {name: os.environ.get(name, values.get(name, "")).strip() for name in ("OPENAI_API_KEY", "OPENAI_MODEL")}
