# Process Record

## Planning and source inspection

The original challenge PDF, knowledge base, inbox, and order history were inspected during planning. inbox.csv and inbox.txt contain the same 20 emails. The user selected rules plus AI, API-backed processing, the file structure, and a mandatory architecture review after each step.

## Actual implementation work

### Step 1

- Inspected workspace before writing: only five source files existed; no existing AGENTS.md or application.
- Captured SHA-256 hashes of the five original inputs before creating documentation.
- Created AGENTS.md plus architecture.md, reviews.md, decisions.md, and this process record.
- Document verification passed using the bundled Python executable: five nonempty documents, required AGENTS sections, all seven tracker steps, and no premature app scaffold.
- Post-write SHA-256 comparison passed for all five original inputs; contents unchanged.
- At Step 1 close, validation was pending and Step 2 had not started. The user's subsequent validation and Step 2 work are recorded below.

## Key instruction used

The user's implementation request requires: "Complete one step at a time. After every step, present an architecture review and pause for your validation before starting the next step."

This instruction is an explicit review gate, not permission to proceed through all seven steps without pausing.

### Step 2 implementation and checks

- User validated Step 1 by saying: "lets work on step 2".
- Implemented config/models/data loader, Python HTTP server, three browser assets, setup files, and loader/HTTP tests. No API client, pricing, or policy modules were added.
- All 20 inbox rows and 12 historical orders load. Quote/newline/Unicode/BOM handling, duplicate IDs, malformed headers/rows, missing fields, email/date validation, contextual matches, and ambiguity are tested.
- Added a real HTTP test module to validate assets, inbox/health routes, new CSV import, malformed import preservation, content type, size limits, and refusal to serve arbitrary files.
- The first sandbox test run passed loader tests but blocked loopback requests (WinError 10013). Reviewed execution outside the sandbox passed all 15 tests. Final rerun after date-validation changes also passed all 15.
- JavaScript syntax check passed with the bundled Node executable. Verified source loading and asset paths from a different working directory. Original five SHA-256 hashes still match the Step 1 baseline.
- Browser visual/interaction QA has not been performed. Static delivery and JS syntax have been verified.
- At Step 2 close, the review awaited user validation and Step 3 had not begun. Subsequent validation and implementation are recorded below.
- Started the local app at http://127.0.0.1:8765 for user review. Launch printed the expected Step 2 startup message.

### Step 3 implementation and checks

- User validated Step 2 by saying: "lets move to the next step".
- Re-read knowledge_base.md, shared models/config, existing handoff and decision records before implementing.
- Added typed business records, independent deterministic pricing and policy modules, 17 pricing tests, and 13 policy tests. No API calls, browser pricing, or email extraction added.
- Focused new suites passed. The first full regression run exposed an intermittent Windows reset in the old oversized HTTP test, which declared a large body while sending two bytes. Changed that check to send only rejection headers before any body; the complete 45-test regression then passed.
- Ran representative quote calculations separately: $2,600, $875, $7,281 provisional rush, $4,450 verified reorder. Checked damage photos remain required and both grounds apply to the opened-spoon return.
- Compared hashes against the original baseline: all five input files remain unchanged.
- Step 3 review is Awaiting user validation. Step 4 has not started; browser remains the Step 2 data inspector.

## API prompts and model runs

None yet. During Step 4, save actual extraction/drafting prompts under prompts/, record model configuration without secrets, and describe representative failures and corrections here. Do not claim planned prompts or runs were used.

## Verification plan

- Input: quoted CSV fields, required headers, unique IDs, normalized matching, relevant history.
- Pricing: quantity boundaries, unsupported paths/sizes, extra colors, setup exemptions, freight thresholds, rush calculations, escalation at $5,000.
- Policies: E07 damage, E08 custom complaint, E09 return, E17 tracking, E18 reorder.
- Judgment: E02/E03/E05 deadlines; phishing no reply; hostile instructions cannot override rules or expose instructions.
- Communication: grounded drafts, math, allowed brand voice, Spanish/French handling.
- Reuse: unfamiliar email; no hardcoded email-ID behavior.
- Export: exactly one row per input email, six required columns, latest saved edits.

## Known limitations

Data scaffold, standalone pricing/policy decisions, and 45 tests exist. No model calls, automatic rules-to-email processing, generated replies, saved review edits, export, or submission write-up exists yet. Imported inboxes are memory-only. API key/model configuration is pending. Further implementation remains gated by step reviews.
