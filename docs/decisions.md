# Decisions and Assumptions

## Accepted by the user

- Build the rules-plus-AI review tool: Python backend, plain browser interface, OpenAI Responses API.
- Code owns quote calculations and policy enforcement. AI extracts intent and drafts replies from verified decisions.
- Work step by step. Present an architecture review and pause for explicit user validation after every step.
- Maintain AGENTS.md as the incoming agent briefing and current implementation/handoff record.
- Use the agreed repository structure; create files only when their step begins.
- User will provide an API key locally. Keep secrets out of source, browser code, and chat.

## Working defaults from the accepted plan

- Use March 8, 2027 as the scenario date. Process every supplied email despite timestamp differences.
- The knowledge base governs business rules; orders.csv provides historical evidence. Do not treat historical order totals as current pricing authority.
- Original input files remain unchanged. inbox.txt duplicates inbox.csv.
- Match customer identity by normalized email and select relevant history; do not blindly use the latest order for every request.
- Use decimal arithmetic; distinguish production lead times from delivery estimates. Never guarantee arrival based solely on production time.
- Missing facts and unknown shipping/duties stay unresolved. Attachments mentioned in messages are unavailable unless supplied.
- Reply in Spanish for E19 and French for E12 as the accepted language assumption; general behavior must not depend on those IDs.
- Use local operation, saved files, and a six-column CSV export. No live mailbox, sending, deployment, authentication, or database.
- Configure API key and model through environment variables; missing configuration produces a clear setup error.
- Preserve completed records if another email fails. Replace a result only after successful retry. Export latest saved review edits.
- Simplify styling first if time tightens. Review gates remain mandatory. Review waiting time is excluded from the 55-minute implementation budget.

## Step 2 implementation decisions

- Use Python 3.11+ standard library for HTTP, dataclasses, CSV, and unittest; no dependency installation or API key is needed yet.
- Bind only to loopback; allowlist three static assets. Import CSV content through JSON, never a client-supplied path.
- Reject an entire invalid import before replacing the active inbox. In-memory state is deliberate until persistence in Step 5.
- Retain all sender history with explainable contextual scores; label any unique suggestion as provisional. Recency alone cannot resolve ambiguity. This is context selection, not intent classification or policy enforcement.
- Add tests/test_server.py to the agreed structure for real localhost HTTP integration checks.
- .env.example documents future variable names; it is not automatically loaded.

## Not established yet

No API configuration or access has been verified. No persistence format or AI processing route has been implemented. Launch and test commands are documented in README and AGENTS.md.

## Step 3 implementation decisions

- Implement reusable pure functions that consume explicit typed facts; defer email interpretation and orchestration to Step 4. Leave the browser's data-inspector behavior unchanged.
- Keep business request/quote/claim/triage dataclasses in models.py; pricing.py owns rates/catalog/calculation, policies.py owns claims, product facts, terms eligibility, and triage.
- Use Decimal with cent rounding (ROUND_HALF_UP) for monetary totals. Never coerce floats/strings into verified business flags; reject invalid quantities, dates, and flags.
- Return rejection reasons for unsupported paths without changing quantity. Overseas has a 50,000 minimum but no invented 1,000 increment rule. USA/digital require 1,000 increments.
- Treat full-color/gradient artwork as digital/offset; do not silently reduce it to flexographic spot colors.
- Waive setup only for an explicitly verified unchanged design on the same production path. Quote every alternative on its own terms, including setup.
- USA rush adds 15% to cups including extra-color charges, excludes setup, and always requires owner confirmation. Freight thresholds use cups (including rush) plus setup.
- Unknown/non-lower-48 shipping leaves full total and deposit unset. Sales tax is excluded. Design services remain a separate hourly charge, not an invented fixed fee.
- Start conditional lead-time windows at scenario-date proof approval only when actual approval is unknown; label this assumption. Weekday arithmetic excludes weekends but cannot account for an unspecified holiday calendar.
- Treat a deadline at/before the upper production bound as tight/too soon for review; even a later deadline is not an arrival guarantee because freight timing is unknown.
- Count claim windows inclusively in calendar days. Do not infer actual photo receipt from "pics attached". Do not decide a digital color variation is within tolerance without an explicit assessment.
- All custom complaints and payment-terms requests require owner review, including seemingly policy-eligible ones. Net 30 uses verified history and six calendar months.
- P4 describes no customer reply, not absence of owner/security attention. Vendor pitches receive no reply by default. Suspicious instructions in an otherwise legitimate quote still permit a policy-grounded draft for owner review.
