# General small-app workflow

The task manager was the initial vertical slice, not the intended product scope.
Version-2 specifications remove its fixed entity, route and six-file manifest.
Version-1 task runs remain readable and use their existing build/repair/test path.

## Implemented boundaries

- Requirements describe the requested domain, entity fields and relationships,
  rendered pages, persistence choice and concrete HTTP acceptance scenarios.
- The architect declares API routes and frontend/backend ownership with explicit
  interface contracts. Requirements, plan and acceptance scenarios share the exact
  human-reviewed fingerprint. Builders cannot change them.
- A parent LangGraph still delegates to the compiled backend/frontend subgraph.
  Builders implement approved files from a minimal fixed Next.js scaffold rather
  than editing an existing task manager. Backend runs before frontend.
- The source writer takes ownership only from the validated approved manifest.
  Package files, configuration, the root layout, health route and test harness stay
  outside builder ownership. Case collisions and path escapes are rejected.
- The trusted generic harness loads its contract from a separate read-only mount,
  checks HTML page loads, executes approved HTTP scenarios, compares JSON subsets
  or expected text, and captures scalar IDs for subsequent requests. SQLite plans
  require a restart scenario; the Next server is actually stopped and restarted.
- Both generic repair attempts use the app-specific contract and QA-selected
  approved files. They never restore task-manager template code. All edits are
  followed by verification; model statements cannot mark a check passed.
- Preview smoke routes use the approved pages. Stateless readiness reports do not
  require a database restart check. Security prompt policy uses the current manifest.
- The dashboard displays pages, entities, API routes, proposed test inputs and
  expected results, and shared interface contracts before approval. Model selection
  is restricted to the two installed Qwen models and persisted per job. Existing
  jobs without a model record keep their 3B fallback. The global default stays 3B.

## POC scope

At most five static HTML pages, three entities with eight fields each, twelve
TypeScript source files, fifteen API routes and forty acceptance HTTP requests.
Next.js/React and built-in Node APIs use the fixed pinned dependency set. An app
may use SQLite or no database. Authentication, remote services, payments, additional
packages and cloud publishing remain outside this phase. Requests needing them
must produce clarification rather than an invented implementation claim.

These bounds permit custom calculations and domain logic, not only renamed CRUD
screens. They do not mean that every conceivable small app is currently supported.

## Verification and actual model trials

The full Python regression suite passed 101 tests and the dashboard production build
passed. New tests cover generic manifests, reserved paths, case collisions,
requirements/API alignment, approval enforcement, SQLite restart/capture contracts,
restricted repair selection, non-task specifications and persisted model selection.

Independent synthetic HTTP services calibrated the generic harness: a correct
calculator passed and an incorrect calculation failed; retained data passed restart
checks while data lost on restart failed. Evidence is in
`artifacts/general-app-evaluation/harness-calibration-final.json`. Reproduce it with
`python scripts/calibrate_app_harness.py` after provisioning the dependency image.
Fixtures are committed under `tests/fixtures/harness-contracts.json`. These synthetic
services test the harness, not the ability of the model to implement those apps.

Real 7B planning exposed omitted schema versions, missing HTTP methods, HTML/JSON
confusion and absent success fixtures. Schema/prompt changes reject those mistakes;
generic structured-output parsing permits one bounded correction retry. It does not
silently coerce an invalid proposal into success. Small-schema validation cannot
establish the semantic correctness of free-text requirements.

The first persisted calculator trial, `b238323a26f04adfb8ccc54a0a4b6b17`, was marked
failed during development review for empty success input fixtures. No source was
generated from that trial. Its evidence is preserved.

The corrected calculator job `b63aeecf213643c8911c9af8495f526a` reached review with
explicit numeric success and invalid-input fixtures. The user approved revision
`14783efb74da33db3951e4c786479e0b5a19296a33ad200846ed6a157febb971`.
Its generation and verification results must be read from the job's actual events;
approval alone is not evidence of a working app.

The calculator's generated frontend failed the production build. Both model repair
attempts failed to add the required client directive; this failure history remains.
A developer review applied a new narrow framework-controller rule that prepends
`"use client";` to a frontend TSX hook module missing it, while refusing known mixed
server/client modules. This syntax normalization is now logged as `SOURCE_ADJUSTED`
and applied to future generic builder/repair outputs. It does not change business
logic. No model repair attempts were reset. Subsequent verification passed typecheck,
production build, HTML page loading and all three approved calculator API scenarios.
This is a model-generated app with a disclosed controller correction, not a claim
that the model completed it unaided.

The first security run blocked because the pinned Node audit image was absent.
The official pinned image was restored and security checks were rerun. Inspect the
latest security event/report for the result; the missing audit was not marked passed.
The repeated run passed the configured Semgrep, secret-pattern, npm, Python and
prompt-policy gates. All five 7B attack proposals still followed the injected
instructions and were denied by policy; this does not demonstrate model resistance.
The readiness assessment is `LOCALLY_VERIFIED_WITH_LIMITATIONS`.

The authorized preview was opened for browser QA. The normal 100/15/4 calculation,
negative bill and zero-party cases behaved as expected. Additional browser/API
checks then found fractional parties accepted and malformed/null JSON returning
500, which the original proposed scenarios had missed. Those findings were saved
in `calculator-extra-validation.json`, recorded as `BROWSER_QA_FAILED`, and the
preview was stopped. Developer review corrected the backend checks and added input
labels, numeric constraints, accessible result/error states and currency formatting.
These are explicitly developer-reviewed fixes, not successful automatic model repairs.
The model repair budget remains exhausted. Fresh functional/security checks passed
for the updated source revision. Browser re-testing passed five selected cases and
nine direct API probes, including fractional parties, malformed/null/array input,
missing fields and decimal display. Evidence is saved in
`artifacts/general-app-evaluation/calculator-browser-qa-final.json` and recorded in
`BROWSER_QA_PASSED` against the exact source fingerprint. Readiness reports include
that scoped manual evidence and the developer/controller correction history.

An observed stop/status race during preview cleanup was also corrected: removal
of an already-removed, previously ownership-checked resource is idempotent. Other
Docker removal failures still propagate. Regression coverage exercises both cases.

The shared generic HTTP harness now additionally rejects malformed JSON and null
payload handling returning anything other than 400/422 on concrete POST endpoints.
These protocol probes supplement model-proposed scenarios and do not test every
possible input type or parameterized mutation endpoint.

## Remaining evidence required

- Evaluate different generated database apps and relationships, not just schema fixtures.
- Broaden automated browser interaction acceptance beyond the fixed converter
  profile now available in the dashboard; HTTP page loads alone do not test forms.
- Broaden prompt-attack cases, including attempts to alter the dynamic manifest or
  weaken proposed test assertions. Current five probes and writer regression are bounded.
- Improve source-context budgets and integration-contract precision for larger plans.
- Complete force-crash recovery, GitHub CI, a remote-database adapter and deployment.

The legacy planner has a four-node-call budget; the generic planner has a five-node
budget including clarification rounds. Each generic structured-output invocation
can internally make up to two model calls for correction. File generation is capped by the twelve-file manifest,
and repairs remain capped at two. The managed worker retains its overall deadline.


## Independent QA planning revision

The inventory evaluation exposed the cost of asking one small model to emit both
business requirements and nested test fixtures. New generic runs now use three
planning roles: Requirements Agent emits a small business brief, Architect emits
exactly one frontend and one backend task with explicit interfaces, and independent
QA emits concrete acceptance scenarios against the original request and architecture.
The complete combined requirements, plan and QA scenarios still require the same
human fingerprint approval before any source generation. Older saved review
checkpoints remain compatible.

The generic graph allows up to five model-node invocations including clarification
rounds; generic structured-output calls allow one correction retry each. Backend
and frontend file generation follow each approved manifest's file order so helpers
can precede their dependents. Coding inputs retain complete contracts and include
only whole existing source files within a bounded input budget; omitted files are
explicitly identified, never silently truncated. Worker-local response diagnostics
record bounded raw model outputs and validation failures without cloud tracing.

Acceptance validation now rejects references to captures before their definition,
vacuous restart checks, and persistence tests that never create data. These checks
cannot prove all business semantics; human review and independent execution remain
necessary. Inventory trial results are recorded separately under
`artifacts/general-app-evaluation/inventory-request*.json` and the job event store.
