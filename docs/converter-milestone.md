# Temperature converter evaluation

This example exercises a small two-role build using the installed
`qwen2.5-coder:7b`, saved handoffs and the normal verification/repair pipeline.

Job: `4b3fd81eb76f4be19780ef9a1b98d156`.
Approved plan revision:
`ae84c6dc7604d0322ca266ab671a0481393c57b87e2a4a08e9f13b233d86862d`.

## Scope and context

One page, no database, and `POST /api/convert` accepting
`{value:number,from:"C"|"F"}` and returning `{result:number,unit:"C"|"F"}`.
The backend owns `app/api/convert/route.ts`; the frontend owns `app/page.tsx`.
Inputs include negative temperatures. Invalid JSON shapes, source units and values
must return 400. The original request, proposed interfaces and reviewer corrections
remain in the job history.

After the user requested the next phase, the reviewed plan was approved through
the dashboard API. The backend generated its route first. The saved frontend
handoff contained that complete route; its contents matched the actual source.

## Observed controller failure and recovery

The first frontend call was rejected by a flawed literal-import preflight regex.
It interpreted a local variable and JSX attribute named `from` as module imports.
An unnecessary model correction call could not resolve that controller error, and
the run stopped. Those responses and the failed operation are retained under
`artifacts/operations/f1721410dd4f4bcbb22531e51826d985/`.

The preflight now associates `from` with import/export declarations. Regression
checks cover JSX attributes, local variables, compact imports, type imports,
dynamic imports and require calls. It remains a limited literal check, not a parser
or complete security assessment.

**Resume generation** supports one explicit retry of an approved, failed partial
generic build before any `GENERATED_UNVERIFIED` event. It checks the current plan
against its approval, preserves existing approved source paths, generates only
missing files, and still requires independent verification. It cannot resume an
unapproved plan, accept a stale approval or reset exhausted repair budgets.

The actual resumed converter preserved the backend byte-for-byte. It regenerated
only the frontend. Forge's narrow syntax normalizer corrected the leading bare
`use client;` to a quoted directive and recorded `SOURCE_ADJUSTED` with actor
`framework_controller`. This is disclosed controller assistance, not an unaided
model output. No developer rewrite of the application behavior was made at this
point. Verification outcomes are recorded separately in the job's reports.

The focused regression run passed 53 tests, the full suite passed 119 tests, and
the dashboard production build passed after these changes.

## Actual test-driven handoff

The compiler rejected the generated frontend's `number | null` input value.
QA read that actual failure, selected only `app/page.tsx`, and passed its diagnosis
to the frontend builder with the complete target and reference-only backend source.
This first repair attempt is recorded in `REPAIR_DIAGNOSIS` and two further
`AGENT_HANDOFF` events. No application behavior was manually rewritten to resolve it.

See the job's Activity, Agent handoffs and Reports for subsequent compiler, repair,
security and preview outcomes; generated source alone does not establish a completed app.

## Verified build outcome

After one model repair, the resulting source passed TypeScript, a Next.js production
build and all eight reviewed API scenarios, plus the shared malformed/null protocol
checks. The source fingerprint is
`b980b343b8ce742c85c42b24d842b8a892f090631647cb0a2586d3218226c3e0`.
Functional evidence:
`artifacts/verification/4b3fd81eb76f4be19780ef9a1b98d156/3cd792147056482d85e68f66d4e2fd41.json`.

The controller/handoff assertions in
`artifacts/general-app-evaluation/converter-handoff-proof.json` confirm the original
backend remained unchanged across generation resume and repair, seven handoffs
were saved, one model repair was consumed and no developer app-source rewrite was
recorded. Planning review, controller syntax normalization and the import-checker
software correction remain disclosed assistance.

Configured security gates passed, and a readiness report was produced. Browser
form testing is a separate remaining check, behind the explicit local-preview gate.
The result is a bounded POC example, not evidence of reliable arbitrary-app generation.

Security evidence:
`artifacts/security/4b3fd81eb76f4be19780ef9a1b98d156/edfd5bf27d3c4b778631b547b14690b6/report.json`.
Semgrep, secret-pattern scanning, npm/Python audits and prompt policy checks passed.
The model followed all five fixed injection attacks; policy blocked their dry-run
proposals. The legitimate read control passed. This is evidence for the configured
policy boundary, not model injection resistance or a complete security assessment.

Readiness evidence:
`artifacts/reports/4b3fd81eb76f4be19780ef9a1b98d156/9ef5708219e9491697f2c2920679294e.json`.
Assessment: `LOCALLY_VERIFIED_WITH_LIMITATIONS`. Nothing was deployed to the cloud.

## Preview findings and model repair

The user explicitly approved an expiring localhost preview. Browser checks passed
0 C to 32 F, 212 F to 100 C, -40 C to -40 F, and 36.5 C to 97.70 F. Empty required
input blocked submission. Fifteen additional direct HTTP cases passed, covering
both conversion directions, decimals, negative values, invalid types, missing
fields, malformed JSON and a nonfinite parsed JSON number.

A manual browser check then found that changing the source selector after conversion
relabeled the old result without recalculating. The screenshot and observations are
retained in `artifacts/general-app-evaluation/converter-browser-qa-initial.json`;
the matching HTTP evidence is `converter-preview-api-initial.json`.

The preview was stopped before any source changes. The operator-recorded browser
failure was explicitly identified as manual evidence and mapped into the existing
failed-check format in `converter-manual-failure-for-repair.json`. It is not claimed
as an automated browser test or an OS process exit. The normal pipeline received
that failure for the second and final allowed model repair; earlier attempts were
not reset. QA also received its earlier compiler diagnosis and the current source.
The numeric input's absent step attribute was noted separately: decimal conversion
did succeed in the tested browser, and explicit fractional-step support was requested
for clarity rather than falsely recorded as a failed decimal submission.

## Final preview result

The second model repair selected only the frontend and cleared result/error state
on value or source-unit changes. Fresh TypeScript, production-build and configured
API checks passed, followed by fresh configured security gates. The same approved
localhost preview was restarted; no additional permission scope or cloud deployment
was introduced.

Ten selected manual browser cases then passed, including the original stale-unit
reproduction, value-change clearing, both conversion directions, negative values,
decimals, extra input precision with rounded display, and empty required input
without a stale result. Fifteen direct HTTP checks passed again. Evidence:

- `artifacts/general-app-evaluation/converter-browser-qa-final.json`
- `artifacts/general-app-evaluation/converter-preview-api-final.json`
- `artifacts/dashboard/converter-browser-verified.png`

The final source fingerprint is
`18bd822eda60b01217b7fa77a41b9b1e30a47f910efabdf3e4d043dc070c8f3c`.
The final workflow proof in `converter-final-workflow-proof.json` confirms all nine
handoff snapshots match their recorded hashes, the second repair received the
earlier QA diagnosis and the current frontend, the backend stayed unchanged, and
the final frontend matches the recorded model response. Both allowed model repair
attempts were used. No developer rewrite of the app source was performed.

Final functional report:
`artifacts/verification/4b3fd81eb76f4be19780ef9a1b98d156/12d16c9d97be438b86ea1f4491268e3f.json`.
Final security report:
`artifacts/security/4b3fd81eb76f4be19780ef9a1b98d156/21ce71ae01584a95a2dd5443dccae609/report.json`.
Updated readiness report, including the source-bound browser evidence:
`artifacts/reports/4b3fd81eb76f4be19780ef9a1b98d156/d6b2dfb37bd64736acac71935b31e89a.json`.

This establishes a scoped end-to-end example with explicit reviewer/controller
assistance and model-generated repairs. It does not establish autonomous success
across app domains. Browser coverage is manual and limited to the in-app browser;
very large finite values and asynchronous UI request races remain outside these
checks. The preview automatically expires and the app is stateless.
