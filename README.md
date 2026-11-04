# UNIQ Inbox Review Tool

Current stage: Step 3. The local app loads the 20 source emails, validates CSV input, and displays sender-matched order history. The Python pricing/policy engine is implemented and tested independently. AI extraction/drafting, connecting rules to email processing, persistence, and export are not implemented yet; the browser remains the Step 2 data inspector.

## Run

Requires Python 3.11 or newer. Steps 2-3 have no third-party dependencies and need no API key.

From the project root:

```powershell
python -m app.server
```

On this Windows machine, Python is bundled but not on PATH:

```powershell
& 'C:/Users/corbi/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' -m app.server
```

Open http://127.0.0.1:8765 in a browser. Use `--port 8766` to choose another port. Stop with Ctrl+C. Launch from the project root, or put the project root on PYTHONPATH before invoking `-m app.server` from elsewhere. Source and asset paths are resolved relative to the project, not the shell directory.

## Use

- Select an email to inspect its body and all order history matched by normalized sender email.
- A suggested order is a heuristic, not a final decision or policy authorization. Ties and missing explicit references remain unresolved. Recency is only a display tie-breaker.
- Import a UTF-8 inbox CSV using the provided file control. Required columns: `email_id,received_at,from_name,from_email,subject,body`. Extra columns are ignored. Names and subjects may be blank; IDs, sender addresses, timestamps, and bodies may not. Timestamps use `YYYY-MM-DD HH:MM`.
- Commas and multiline fields must be CSV-quoted. Duplicate IDs, missing columns, malformed rows, bad addresses, and invalid dates produce errors. Invalid imports leave the current inbox intact.
- Imported inboxes replace only the in-memory dataset. Restarting loads the supplied inbox again. Source files are never overwritten.
- Order history is loaded from orders.csv on startup. No arbitrary filesystem path is accepted through the API.

## Verify

```powershell
python -m unittest discover -s tests -v
```

Use the bundled executable above in place of `python` if needed. Tests use the standard library and ephemeral loopback ports; no model calls or credentials are involved.

## Navigate

Read AGENTS.md first. docs/architecture.md maps modules and data flow; docs/reviews.md records step reviews and actual validation. App source lives under app/, focused tests under tests/. Planned prompts and generated outputs will be introduced in later steps.

Future AI configuration uses OPENAI_API_KEY and OPENAI_MODEL environment variables. .env.example is a template only; automatic .env loading is not implemented.

## Business-rule API (Step 3)

- app.models.CustomRequest contains explicit size, quantity, ink count, artwork/PMS requirements, destination region, verified reorder facts, and optional proof/deadline dates.
- app.pricing.quote_options(request) returns all three production paths, including rejection reasons. quote_custom(request, path, rush=True) evaluates a provisional USA rush; it never authorizes one.
- app.pricing.quote_stock({"KR-08": 2}, destination="lower_48") calculates stock merchandise. Shipping is unknown unless the documented Cup Club conditions establish free shipping.
- app.policies provides stock_return, shipping_damage, custom_complaint, net30_eligibility, product_facts, and triage. Inputs are explicit facts; these functions do not parse messages.
- Monetary results use Decimal, unknown shipping/totals/deposits use None, and production windows use date values. Dates and money must be serialized explicitly when the AI pipeline is added; never convert money to floats.
- A verified unchanged design on the same production path is required to waive setup. A provisional order-context suggestion alone does not establish this.
- Use a verified history start for Net 30; the earliest row in a partial recent-order CSV does not prove a customer is new.

Run the full test command above to verify all 45 loader, HTTP, pricing, and policy tests. No rules have been automatically applied to the supplied inbox yet.
