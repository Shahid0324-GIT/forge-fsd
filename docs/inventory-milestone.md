# Inventory evaluation

The inventory example tests a different domain with two related entities and
transactional business behavior. Its configured functional and security gates
passed after a substantial developer-reviewed reconstruction of the eight approved
source files. This is evidence for the workflow and its checks, not evidence that
the installed 7B model can reliably build arbitrary small apps unaided.

## Approved scope

One Next.js page, local SQLite, products with names/unit prices, and signed integer
stock movements referencing a product. Stock is derived from movement records and
inventory value is stock multiplied by unit price. Negative stock is rejected,
and checking stock plus inserting a movement happens in one transaction.

Job: `1ff5378844a0433c9819ac0489199b54`.
Approved revision: `a6578c9ff9957e42036a982247e5edc9240cd87d933ccfa1c78d3ae80eb84812`.
Human preview consent is separate from this plan approval.

## Workflow improvements driven by actual failures

- Generic planning now delegates to Requirements, Architect, and independent QA
  roles. Requirements no longer has to emit nested test fixtures in the same call.
- The model architecture schema requires exactly one frontend task and one backend
  task. The original request and clarification answers reach architecture and QA.
- QA emits native JSON bodies/assertions. The controller serializes them into the
  existing reviewed contract; it does not reinterpret assertion values. Structured
  capture bindings are also supported and tested with real isolated HTTP services.
- Captures must be defined before use. Persistence scenarios must create data and
  assert stored JSON after an actual process restart.
- Failed pre-review planning can resume its failed node through **Retry planning**.
  It is capped at two explicit retries and cannot bypass a human review checkpoint.
- Reviewer corrections preserve the previous plan event and create a new fingerprint
  and approval interrupt. A regression test rejects the superseded fingerprint.
- Source generation is bounded by a complete-contract context budget, includes only
  whole source files, and explicitly identifies omitted context. Helpers precede
  entry points. Platform examples ground the supported Node SQLite/App Router APIs.
- Literal import preflight rejects extra packages and workspace import escapes
  before accepting a generated file, with at most one correction call. This limited
  regex check is not a replacement for compilation or security scanning.
- Narrow source normalization removes a complete Markdown fence and adds a missing
  client directive where safe. Applied corrections are recorded in job history.
- Failed compiler checks attach the trusted platform reference for QA. The effect
  of these new aids on broader model completion rates still needs evaluation.
- The dashboard retains failed trials but no longer shows an older operation's
  failure banner after a later successful operation. Developer corrections remain
  explicitly disclosed in the workspace and readiness report.

## Model limitations and reviewer involvement

Several inventory planning trials were rejected for malformed fixtures, missing
ownership or missing restart phases. After the native JSON change, QA completed on
its first response. Review still caught a collection assertion represented as an
object instead of an array and an unrequested ASCII-only name restriction. Those
corrections were recorded before the user approved the revised plan.

The 7B builder then produced unsupported `sqlite`, `sqlite3`, `uuid`, and
`react-toastify` imports, older request-handler patterns, and inconsistent module
interfaces. Two automatic repairs did not resolve them. No packages were installed
to accommodate those outputs and no repair counters were reset.

The post-repair source snapshot is retained in
`artifacts/general-app-evaluation/inventory-before-developer-review.json`.
Worker-local bounded model traces and failed verification reports preserve the
earlier proposals and failures. Developer review replaced the eight approved files
with compatible implementations, recorded `SOURCE_ADJUSTED`, and marked the result
unverified before rerunning all checks.

## Actual verification

The corrected app passed:

1. TypeScript compilation.
2. Next.js production build.
3. Approved API behavior: create product, add ten units, remove three, derive stock
   seven/value 17.5, reject overdraw and zero quantity, reject missing product.
4. Persistence across stopping and restarting the application server.
5. Independent SQLite inspection: configured database file exists, integrity check
   succeeds, foreign-key checks find no violations, and declared reference fields
   have physical foreign-key declarations.

Configured Semgrep, secret-pattern, npm audit, Python audit, and prompt-policy gates
passed. In all five attack probes, the model followed the injection and the policy
blocked its dry-run proposal; the legitimate read control passed. This demonstrates
the configured boundary in that bounded suite, not model resistance or complete security.

Functional evidence: `artifacts/verification/1ff5378844a0433c9819ac0489199b54/b08e38f48e54480aa5d250b105619683.json`.
Security evidence: `artifacts/security/1ff5378844a0433c9819ac0489199b54/4a6b1726a92c4c50b08f250f59d8c66d/report.json`.

The SQLite gate itself was calibrated against a correct database and rejected
fixtures with orphaned rows, missing foreign keys, and an absent database. See
`artifacts/general-app-evaluation/database-gate-calibration.json` and reproduce it
with `python scripts/calibrate_database_gate.py` after provisioning the dependency image.

## Completed preview checks

On November 1, the expired preview was restarted under the existing human approval.
Eight selected manual browser cases passed: empty state, Unicode product creation,
stock addition/removal, overdraw rejection, zero/fraction rejection, and retention
after page refresh. The product ended at seven units and value 17.50.

Seventeen HTTP/concurrency cases passed. Two simultaneous requests each attempted
to remove seven units from ten: one returned 201, the other 400, leaving three.
Read-only inspection of the owned preview container confirmed exactly two movement
rows (the initial addition and one accepted removal), no foreign-key violations,
and a successful SQLite integrity check. Invalid JSON shapes, malformed JSON,
missing products, negative prices and invalid quantities were also rejected.

Evidence is saved in `artifacts/general-app-evaluation/inventory-browser-qa-final.json`
and `inventory-preview-api.json`, bound to source fingerprint
`bb3bb55f8105314868860586fb17f6fa369a75198518cb18e9d56af89e4f3258`.
Reproduce the HTTP checks in an authorized fresh preview, after creating the browser
fixture, with `python scripts/check_inventory_preview.py`.

The resumed Python regression suite passed **112 tests** (13 upstream deprecation
warnings). These manual cases supplement the configured gates; automated browser
acceptance across arbitrary generated apps remains unfinished.

Preview data is temporary and expires with the container; restart persistence
verification does not imply permanent cloud storage.
