# Architecture Reviews

## Protocol

For each step, record changes and purpose, components and data flow, code/AI boundaries, verification evidence, limitations, next proposed step, and the user's actual validation response. Pause at every review. Never infer validation from silence or general authorization to implement the full plan.

## Step 1 - Establish agent handoff

- Implementation status: Verified.
- Review status: Validated.
- Changes: created AGENTS.md and architecture, reviews, decisions, and process documents. This gives incoming agents an explicit navigation map, implementation tracker, and review gates.
- Components: AGENTS.md is the entry point; architecture.md maps modules and data flow; this file records validation; decisions.md stores accepted choices; process.md records actual work.
- Data flow: source files remain unchanged; documentation describes the future import -> rules/AI -> review -> export workflow.
- Code/AI boundary: no application code or AI integration exists. The target reserves calculations/policies for code and interpretation/drafting for AI.
- Verification: Python checks passed for five nonempty documents, all required AGENTS sections, all seven tracker steps, and absence of a premature app scaffold. SHA-256 comparison confirmed all five original source files are unchanged.
- Limitations: cannot launch an application, process emails, or export results yet. All target modules are explicitly labeled planned.
- Next proposed step: scaffold the backend and minimal browser shell; validate CSV input and demonstrate relevant order matching.
- User validation: "lets work on step 2". This explicitly authorizes the next step following the Step 1 review.

## Step 2 - Scaffold and load data

- Implementation status: Verified.
- Review status: Validated.
- Changes and purpose: added a dependency-free Python local server, CSV validation, typed source records, provisional context matching, a source inspector/import shell, setup instructions, and focused tests.
- Components and flow: source inbox + startup orders -> data_loader validation -> sender-address history -> contextual suggestions -> JSON API -> browser text rendering. A valid imported inbox replaces only in-memory records. Invalid imports preserve the previous dataset. Input files are not edited.
- Code/AI boundary: all matching is deterministic and explainable. AI, quote calculations, and policy enforcement are not implemented yet. Context suggestions never authorize a refund, plate reuse, or shipping promise.
- Examples: E07 suggests UQ-10455 while preserving Luis's spoon history; a spoon question selects older UQ-10433. E17 suggests in-transit UQ-10482. E18 suggests custom UQ-10120. Ambiguous matches remain unresolved even when one order is newer.
- Verification evidence: 15 unittest tests passed, including real HTTP GET/import/error/asset checks. JavaScript syntax passed with node --check. Source/assets loaded after changing working directory. SHA-256 hashes match for all five original inputs. Sandbox loopback restrictions caused the first HTTP test run to fail with WinError 10013; the full suite passed outside that restriction, including the final rerun.
- Limitations: browser visuals/interactions have not been manually exercised; asset delivery and JS syntax were checked. Imports persist in memory only. Matching uses conservative English context cues, not full multilingual understanding. Pricing, escalation, drafts, saved edits, and export remain later steps.
- Next proposed step: deterministic pricing and policy engine with decimal arithmetic, quote examples, and focused business-rule tests.
- User validation: "lets move to the next step". This authorizes Step 3 after the Step 2 review.

## Step 3 - Deterministic pricing and policies

- Implementation status: Verified.
- Review status: Awaiting user validation.
- Changes: added business records in models.py, pricing.py, policies.py, and independent pricing/policy tests. These consume explicit facts without AI or email-ID-specific behavior.
- Architecture: CustomRequest -> eligibility/rate tables -> decimal quote math, lead-time assessment, unknown-charge handling, and human reasons. Claim/history facts -> policy outcome. TriageFacts -> required escalation, priority, and reply allowance. Browser/HTTP routes remain the data inspector; integration comes in Step 4.
- Code/AI boundary: all arithmetic, thresholds, reporting windows, and mandatory human triggers are deterministic. AI will supply interpreted facts and prose later, but cannot supply authoritative prices or approvals.
- Evidence: all 45 tests passed, including 30 new pricing/policy tests and existing 15 loader/HTTP tests. Source SHA-256 hashes match for all five originals. Actual engine calculations below were run separately from tests.

| Example | Actual engine math, excluding sales tax |
| --- | --- |
| 20,000 8 oz, 2 inks, USA, lower 48 | 20,000 x $0.115 = $2,300 + $300 setup + $0 shipping = $2,600 |
| 3,000 12 oz, full color, digital, lower 48 | 3,000 x $0.26 = $780 + $95 shipping = $875; deposit $437.50 |
| 60,000 8 oz, 3 inks, USA provisional rush | 60,000 x $0.099 = $5,940 + $450 setup + $891 rush = $7,281; owner confirmation required |
| 50,000 8 oz, 2 inks, verified unchanged USA reorder | 50,000 x $0.089 = $4,450; no setup; free lower-48 freight |

- Policy examples: 5,000 custom 16 oz has no eligible production path; an explicitly separate 10,000-cup alternative totals $1,665. A May 1 overseas 150k 16 oz request cannot meet the timeline even though its $10,900 quote is cheaper than USA. Damage reported three days after delivery needs actual photos before replacement arrangement. Opened spoons delivered January 22 fail both the opened-case and 30-day rules. A February 12 custom delivery is 24 days old at the scenario date and needs owner review.
- Limitations: no automatic inbox processing, drafts, or pricing display yet. Exact freight transit and holiday schedules are unknown. Model configuration remains pending. All design/claim/history verification facts must be established from evidence, not inferred from a contextual match.
- Test correction: a deliberately mismatched Content-Length in the previous HTTP limit test intermittently reset Windows sockets. The test now sends rejection headers before any body, verifying the intended 413 response without invalid framing; full suite passed afterward.
- Next proposed step: structured AI extraction, rule orchestration, grounded draft generation, validation, and per-email error isolation. No new architecture step may start before validation.
- User validation: Not received.
