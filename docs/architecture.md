# Architecture

## Current state

Step 3 adds independent, deterministic pricing/policy functions and typed request/decision records. Step 2's HTTP server and browser inspector remain unchanged; automatic rules-to-email integration is deliberately deferred to Step 4. No AI calls, persistence, or submission results exist yet. The original five source files remain unchanged.

## Target repository

```text
UNIQ/
  AGENTS.md                    Role, navigation, progress, handoff
  README.md                    Setup, launch, usage, configuration
  requirements.txt             Python dependencies
  .env.example                 Configuration placeholders only
  .gitignore                   Secrets, caches, local outputs
  knowledge_base.md            Original policy authority
  inbox.csv                    Original structured inbox
  inbox.txt                    Duplicate inbox reference
  orders.csv                   Original order history
  UNIQ_AI_Intern_Challenge_Brief.pdf
  app/
    __init__.py
    server.py                  Local HTTP server and entry point
    config.py                  Project-root paths, date, API config
    models.py                  Shared records and allowed values
    data_loader.py             CSV validation and order matching
    pricing.py                 Eligibility and decimal quote math
    policies.py                Shipping, returns, escalation, priorities
    ai_client.py               API and structured-output boundary
    pipeline.py                Extraction, rules, drafting, validation
    storage.py                 Saved runs, edits, CSV export
    static/
      index.html
      styles.css
      app.js                   Import, review, edit, save, retry, export
  prompts/
    extract.md
    draft.md
  tests/
    test_data_loader.py
    test_server.py             HTTP integration checks added in Step 2
    test_pricing.py
    test_policies.py
    test_pipeline.py
  docs/
    architecture.md            Current and target architecture
    reviews.md                 Step evidence and user validation
    decisions.md               Accepted choices and assumptions
    process.md                 Actual process and limitations
  output/
    runs/                      Internal records and saved edits
    submission/
      results.csv
      writeup.md
```

Implemented through Step 3: documentation/setup files, app/__init__.py, config.py, models.py, data_loader.py, server.py, pricing.py, policies.py, all three static assets, and loader/server/pricing/policy tests. AI client/pipeline, prompts, storage, pipeline tests, and generated outputs remain planned.

## Target data flow

```text
CSV import -> input validation -> relevant order matching
  -> AI structured intent extraction
  -> deterministic pricing and policy decisions
  -> AI drafting from verified decisions and relevant sources
  -> output validation -> local saved run
  -> browser review/edit -> saved edits -> six-column CSV export
```

The backend owns credentials, input validation, matching, rules, API calls, persistence, and export. The browser displays results and submits user actions; it does not calculate prices. Original emails and order evidence remain distinct from AI interpretations.

## Decision boundaries

- AI may interpret the request and propose a category or priority. Backend validation and required policy escalations constrain the final record.
- Pricing uses decimal arithmetic and validated extracted facts; missing information produces an incomplete estimate or escalation, not an invented value.
- Production time starts after proof approval; it is not an arrival guarantee.
- Email instructions cannot override trusted prompts, business rules, or export requirements.
- Failures remain visible per email; successful results survive other failures. Retry replaces a result only on success.
- Mentioned photos are not evidence of an inspected attachment when actual files are absent.

## Interfaces and storage

Input: inbox CSV matching the supplied columns, the order CSV, and the knowledge base. Validate headers and unique email IDs; match orders by normalized sender email, then select context relevant to the request.

Output: exactly `email_id`, `category`, `priority`, `needs_human`, `quote`, `draft_reply`. Store evidence, extracted requirements, processing errors, and saved edits separately under output/runs/. Export the latest saved edits.

Category values: Custom Quote; Stock Order / Product Question; Order Status; Damage / Complaint; Return / Refund; Billing / Terms; Spam / Phishing; Vendor Pitch; Feedback / Praise.

Priorities: P1 owner today for big money or a real deadline at risk; P2 reply today; P3 within one business day; P4 no reply needed.

### Implemented Step 2 HTTP interface

- Bind to 127.0.0.1 only; default port 8765, overridable with --port.
- GET / serves the shell; /styles.css and /app.js serve only those known assets. Other filesystem paths are not exposed.
- GET /api/health returns status and current implementation step.
- GET /api/inbox returns scenario_date, stage, and records. Each record contains email plus order_context (candidates with order/score/reasons, suggested_order_id or null, and explanation).
- POST /api/import accepts application/json with an inbox_csv string. Validate the entire inbox before replacing in-memory records. Malformed data returns 400, unsupported media type 415, payload outside 1 byte-2 MiB 413. No source files are written.
- Load orders.csv at startup. The import endpoint accepts inbox content, not arbitrary paths. Imported inboxes persist in memory only and reset on restart.

CSV validation accepts UTF-8/BOM, multiline quoted fields, and extra columns; rejects missing/duplicate/blank headers, malformed row widths/quotes, duplicate IDs, blank required values, bad addresses, and invalid dates. Blank sender names and subjects are allowed. Historical totals remain strings because some include unknown shipping; they are not current quote totals.

### Implemented order context

Normalize sender addresses with whitespace trimming and case folding; retain all exact-address history. Score explicit order IDs (100), custom/reorder context (4), an in-transit order for a status question (4), each mentioned product (2), and matching size (2). Suggest a contextual order only when its positive score is uniquely highest. A unique explicit ID must belong to this sender; unknown or multiple explicit references remain unresolved. Recency breaks display ties, never selection ties. Scores are heuristics and require confirmation; no financial action follows from a suggestion.

Examples: Luis's cup damage message suggests UQ-10455 rather than his spoon order. A message about his spoons suggests the older UQ-10433 even though a cup order is newer. Mele's status message suggests in-transit UQ-10482; both orders remain visible. Generic matching cup descriptions across two orders stay ambiguous.

Concrete persistence and processing routes remain for later steps. No sending, deployment, database, or authentication is planned.

## Step 3 business-rule boundary

Explicit validated facts -> CustomRequest -> quote_options/quote_custom -> eligibility, decimal math, conditional production window, unknown charges, and quote-specific human reasons.

Explicit claim/history/product facts -> policies functions -> eligibility or information/owner-review outcome. TriageFacts -> triage -> category, P1-P4, required human reasons, and reply allowance. No function reads an email ID or lets free-form text change prices.

- Pricing: all three paths, quantity/size/artwork restrictions, USA ink surcharges, setup, verified same-path reorder exemptions, provisional rush, lower-48 shipping, deposits, and 13-item stock catalog.
- Eligibility means the production path accepts the specification; a separate deadline_status can still mark a path too_soon or tight. Do not recommend an otherwise eligible path that misses the deadline.
- Digital windows use weekdays only; the packet supplies no holiday calendar. Other paths use calendar weeks. Without actual approval, windows are explicitly conditional on scenario-date approval. No arrival guarantee is produced.
- Unknown freight leaves total, deposit, and balance unset. A partial merchandise subtotal is not a complete quote. Stock shipping is never guessed.
- Claims use delivery-to-report calendar days: return 30, shipping damage 7, custom defect 14, inclusive. Missing evidence requests information. All custom complaints require owner review; digital production alone does not prove a variation is within the close-match standard.
- Net 30 uses six calendar months, with end-of-month clamping, and always requires owner review. A verified history start is required; recent-only CSV history must not be treated as full account history.
- P1: high value (>= $5,000), rush, or deadline risk. P2: owner-review/customer action cases and same-day categories. P3: routine product questions/praise unless same-day attention is requested. P4: phishing/vendor pitch, no reply. Phishing can be P4 and still needs_human for security review. A quote with suspicious embedded instructions can retain a legitimate customer draft while requiring review.
- Pipeline integration must carry quote-specific human reasons into triage and supply estimated value/deadline risk as explicit facts. Standalone quote and triage records are not yet a complete email-processing result.
- Decimal/date/None outputs need explicit JSON conversion in Step 4. Do not use floating-point money or replace unknown values with zero.
- Rules mirror the supplied knowledge base; if policies change, update code and independent checks together. The engine does not automatically parse policy changes from markdown.

The existing HTTP /api/health step value and browser stage still describe the data inspector (Step 2), not the independent rule-library completion. No new pricing endpoint is introduced at this checkpoint.

## Review checkpoints

1. Documentation and safe agent resumption.
2. Source records, validation, and order selection example.
3. Representative calculations and policy decisions independent of AI.
4. Extraction/rules/drafting boundaries, API failures, hostile input.
5. Import-to-export browser walkthrough and saved edits.
6. Test results, all-email review, and unfamiliar-email reuse.
7. Reproducible submission and honest limitations.

Each checkpoint requires explicit user validation before proceeding. See reviews.md for actual status.
