# Agent reliability audit — 5 November 2026

This change fixes controller behavior in the autonomous planning, source generation,
QA and repair paths. It does not edit a generated application or its frozen tests.
Local inference and Groq were used for live calibration; Claude was not called.

## Causes and corrections

| Cause | Correction |
| --- | --- |
| A malformed independent review was reported back as a failed QA proposal. QA could keep rewriting valid tests to compensate for another role's invalid response. | Validate and correct the review in the reviewer role, with one bounded correction. Repeated invalid decisions pause for inspection. A review/service pause can resume the same saved proposal without another author call. |
| QA correction context came from the ledger's 4,000-character exception summary. Longer review findings could lose their final required corrections. | Save complete rejection feedback separately and bind it to job, task revision, approved review and proposal hash. Retries receive that complete feedback; ledger summaries remain bounded. |
| Schema-invalid QA responses had no saved proposal and were excluded from completion-trace recovery. | Recover current-task validation-failure traces as correction input. Invalid proposals cannot become passing evidence. |
| Once the cumulative stall count passed two, every further failure could cause another senior review, leaving only one attempt to try its strategy. | Require two new worker observations between reviews. Stop a senior reviewer that repeats the same invalid decision twice. Action limits remain enforced. |
| New modules have no import graph, so source scoping could hide existing helpers and components precisely when the builder needed to choose their imports and interfaces. | Generation receives existing manifest implementations and the complete source manifest, including the final raw-source handoff. Repair keeps its narrower diagnostic scope. Check capacity again after target selection expands that scope. |
| Plans could assign source or test files to QA, although source generation forbids test edits and no arbitrary test-file runner exists. | Executable planning validates this capability boundary before approval. QA produces the independent browser contract outside the generated source workspace. Historical/tool manifests remain readable. |
| Local coding used an 8,192-token window despite substantial source, schema and protocol prompts. Large suite output was expanded only for Claude. Truncated JSON could be treated as a schema defect. | Local coding uses a 32,768-token context; source and acceptance-suite completions have a 6,000-token allowance on local/Groq as well. Incomplete completions pause before schema retry. Correction input is not silently cut at 16,000 characters. Trace budgets reflect the actual request. |
| Transport errors, missing dependency images, browser infrastructure errors and failed cleanup could enter source-repair loops. | Classify provider transport/service failures as resource pauses. Preserve verification environment failures through the tool boundary and pause before source repair. Genuine compiler/browser assertion failures still reach the owning builder. |

## Provider policy

The existing hybrid policy selects local Qwen 7B and Groq GPT-OSS 20B. It has no
automatic Claude fallback. Single-provider jobs keep their selected provider and
existing inference-approval requirements. These changes do not increase a saved
Claude allowance or change provider selection on a saved job.

The calibration script accepts explicit local/Groq model choices; Claude is not an
option:

```powershell
.venv\Scripts\python.exe scripts/evaluate_test_quality.py --model qwen2.5-coder:7b
.venv\Scripts\python.exe scripts/evaluate_test_quality.py --model groq:openai/gpt-oss-20b --generate-suite
```

The optional generated-suite case uses the actual bounded coordinator, QA author,
independent reviewer and frozen-contract loader. Its limit is six coordinator
dispatches. No generated application is executed by this script.

## Validation and limits

Regression tests exercise complete feedback recovery and tamper rejection,
reviewer-owned correction and proposal reuse, generation interfaces, invalid
execution manifests, completion/transport pauses, verification-environment pauses,
and recovery-review cadence. Existing ownership, authorization and evidence gates
remain in place.

The complete suite ran against the final production code: **650 passed, 3 failed**
in 452.44 seconds. All three failures were mock assertions requiring the old
3,000-token/8,192-context source settings; they prevented those tests from reaching
the source transport. After updating those test-only assertions to the new settings,
the entire source-transport module passed: **12 passed** in 0.97 seconds, including
all three failing cases. Production code did not change after the complete run.
The complete suite was not repeated after this test-only correction.

Logs: `artifacts/systemic-full-final-tests.txt` and
`artifacts/systemic-source-final-tests.txt`. The full run used a fresh directory
under Windows TEMP, outside the sandbox: its in-process async API tests stalled
inside the Windows sandbox. All provider requests in the regression suite are
mocked. Separate focused QA/review and provider selections also passed. These
overlap the complete suite and must not be added to its count. `git diff --check`
passed. The suite reported 13 existing upstream deprecation warnings.

Live local Qwen 7B calibration accepted meaningful calculator scenarios and rejected
a superficial page-title-only scenario. Groq 20B initially exposed an invalid
reviewer decision; this was not counted as a successful rejection. After reviewer
correction was implemented, Groq accepted the meaningful suite and rejected the
superficial suite.

The full Groq QA-authoring calibration also completed: it froze three scenarios in
four coordinator dispatches. This exercised a real schema-invalid first proposal,
proposal recovery, independent review, senior recovery and a corrected contract.
The report is at
`artifacts/test-quality-evaluation/dd8c44734af2408e8a1183e167036790/result.json`.
The local reviewer calibration report is at
`artifacts/test-quality-evaluation/609ad31d60b9453680162cf6078781fd/result.json`.

Docker's Linux engine was unavailable during this audit. A complete generated-app
build/browser pass is therefore not established. Model review is judgment, not proof
of application correctness. Oversized complete contexts still pause rather than
discarding source or requirements. Reviews bound to an earlier review protocol
need fresh review evidence under the current protocol.

## Live counter follow-up

After starting Docker and the dashboard, job
`6cd00155cb364681ad1108f5d414abec` generated a counter with Increment, Decrement,
Reset, negative values, repeated clicks and reset on reload. The operator requested
two design revisions before approval to keep internal-technology proof and an
unrequested keyboard check out of the browser feature criteria. Architectural
constraints on persistence remained in the design.

Local 7B generated both source files and passed the initial real build. Live QA
then exposed two further controller defects:

- The arbitrary 16-step per-scenario ceiling rejected a 17-step correction. The
  controller now shares the existing **96-step total budget** across up to six
  scenarios. Complete stateful sequences can remain together. Coverage and
  observation validators are unchanged; the overall step allowance did not grow.
- A newer schema-invalid model response could be hidden by an older persisted
  proposal. Context now compares controller-recorded dispatch identities and
  recovers the latest candidate. It revalidates that candidate under the current
  protocol, so an obsolete schema limit does not mask the remaining real defect.

The focused QA/protocol/browser-wiring selection passed **121 tests** after those
changes, including new shared-budget and newer-candidate regressions. Log:
`artifacts/live-qa-budget-tests.txt`. The earlier complete-suite run predates these
two follow-up changes; the complete suite was not rerun afterward.

Groq 20B exhausted its daily token quota during QA. The saved job was explicitly
switched to Groq 120B through the existing source/task-bound inference approval
mechanism. The idle dashboard was restarted to load the verified controller
changes. No Claude calls were made.

QA froze a **21-step scenario covering all seven approved criteria**, with no
uncovered items. The browser exposed a semantic-target mismatch: the contract
expected the live count to be the page heading. The agents changed the two owned
UI modules, removing the static heading and assigning the live count its heading
role. The numeric logic and frozen assertions were retained. No generated app
source was manually edited.

Fresh real TypeScript, production build and all frozen browser assertions passed.
The local preview was then checked visibly: three increments produced 3, four
decrements produced -1, Reset produced 0, and reloading from 2 produced 0.
Evidence is saved in `artifacts/live-counter-validation.json`; the screenshot is
`artifacts/live-counter-preview.png`. The dashboard remains at
`http://127.0.0.1:8787/`; the disposable preview was opened at
`http://127.0.0.1:51320/` with its normal approximately 30-minute lifetime.

This establishes a working small app after review, controller fixes, provider
resumes and agent-authored markup repairs. It does not establish one-shot or
generally reliable autonomous completion for arbitrary apps.

## Independence and implementation follow-up

The user's 7B expense run was stopped and remains cancelled. Its generated source
was not manually corrected or resumed. The weak plan exposed a coordination gap:
manifest/schema validation allowed technical contradictions through, and separate
builders had no explicit agreement about shared signatures.

The controller now adds an internal engineering review before business-scope
approval. The reviewer sees the original request, actual runtime and verification
capabilities, and the complete agent-authored design. Findings must quote the
actual proposal and select a controller-supplied request/runtime/contradiction reference, and the reviewer
must assess every declared file. At most three blocking findings return per pass;
unspecified cosmetic choices and invented platform requirements are excluded.
Empty-list evidence references are encoded directly in the decoding schema.
Basis quotations are resolved by the controller and saved with the review;
the model selects schema-constrained fact references instead of copying facts
inside prose wrappers. References do not establish that the model's reasoning
is correct; execution and independent behavior checks remain necessary.
Findings return to the planner
as full structured feedback. Invalid reviewer references are corrected by the
reviewer within a bounded protocol; service failures preserve the candidate for
review recovery rather than rewriting it. Saved feedback is task/revision,
proposal-hash and evidence-hash bound. This remains model critique, not proof.

App designs can declare their own module, HTTP or server-action agreements:
providers, consumers and exact public signatures. The controller validates paths,
unique identities and acyclic dependencies without inventing application types
or API names. Providers are generated before consumers. Builders receive the
relevant agreements and actual source. Legacy designs retain their existing
context behavior. Multi-owner new designs require explicit interface agreements.

Every newly generated TypeScript/TSX file is parsed before dependent work is
delegated. The trusted TypeScript parser receives source as text, imports no app
code, and ignores app compiler plugins/configuration. Its bounded diagnostics and
the complete saved file return to the responsible builder's normal task loop.
Unavailable parser tooling pauses as an environment problem. Syntax success is
separate from the existing isolated typecheck, production build and frozen browser
assertions; none of those gates are replaced. CI installs the existing locked
dashboard dependency providing TypeScript before controller tests.

The activity feed now exposes failed task checks and the engineering-review role,
so a schema-valid model response cannot conceal a rejected technical check.

Regression coverage includes internal critique-to-planner correction without user
technical answers, reviewer protocol correction and bounded failure, preserved
candidates across review outages, dependency ordering/cycles, scoped interface
context, actual valid/invalid TypeScript parsing, and a provider syntax failure
repaired before its consumer is generated. A parser test also contains filesystem
side effects and a compiler-plugin declaration and verifies neither is executed.

The changes add general coordination and verification mechanisms. They do not
install app-specific source, folders, DTOs or test answers, and they do not make a
7B model capable of reliably solving every application request. Selected local
jobs retain local inference; there is no automatic Claude or Groq fallback.

### Verification and remaining limitation

The complete controller run passed **676 tests** (13 upstream deprecation
warnings), saved in `artifacts/reliability-final-1105.txt` and its JUnit XML.
After the final fact-reference protocol and byte-exact syntax hashing changes,
focused planning/review checks passed **41 tests** and syntax/builder checks
passed **8 tests**. The dashboard typecheck/Vite build passed. The idle dashboard
was gracefully restarted; its HTML, both bundled assets, authenticated job API
and empty active-operation list were checked. The expense job remained CANCELLED.

Actual 7B-only experiments were isolated from dashboard jobs. The request supplied
only notes-app behavior (add/edit/delete, reload persistence, visible empty-title
validation), with no source, folder tree, types or API design. Earlier review
attempts repeated invalid quotation references. With controller-resolved fact
references, the reviewer produced valid structured feedback and the planner
changed its transient-state proposal to browser local storage itself.

The next review nevertheless invented storage/security concerns and cited an
acceptance criterion as its own supposed contradiction. Its protocol correction
repeated that invalid reference, and the controller paused with the exact reason.
The final isolated job is `ac1b61dcfc1e41c8a6b6f8c33620c2f1`; its result and full
model/handoff evidence are under `artifacts/reliability-7b-references-1105/`.
No Groq or Claude inference was used. No generated application source was edited.

This establishes tested coordination, evidence checks and bounded recovery, plus
one real agent-to-agent planning correction. It does **not** establish reliable
7B-only autonomous generation. In particular, the added internal review can still
pause on poor 7B reasoning; well-formed fact references cannot prove that a model's
critique is logically sound. The isolated notes proposal was not approved, built
or browser-verified. This limitation remains unresolved and must not be reported
as a successful app-generation test.

## Documentation-assisted recovery follow-up

The next review found ambiguous capability wording and prompt priming in addition
to model limitations. "No database is valid" was being read as no persistence
support, and an unnecessary transient-state example was copied into a notes plan.
Capabilities now state the actual browser/server storage options; database choice
and required state lifetime are explicitly separate.

Autonomous roles now have a real bounded official-documentation lookup response
in both structured and raw-source adapters. Compiler/syntax failures trigger
reference retrieval automatically. Technical review findings are reassessed with
documentation before blocking. Sources and post-lookup inputs are saved with
task/version/hash provenance, and resolved evidence reaches the planner. Failed
fetches are not technology facts, and lookup-budget pauses retain their type
through QA diagnosis. No new inference provider or app network capability is added.

The complete regression run passed **702 tests**; final provenance/routing
follow-ups passed **78 tests**, with **3** further QA-pause/builder checks passing.
The dashboard build passed. All **14** official indexed pages were live-verified.

The same business-only notes request now reached AUTONOMOUS_DRAFT_READY with one
planner action and one engineering-review action using local 7B. It selected
localStorage and preserved reload persistence and empty-title validation. A
separate real 7B evaluation requested documentation and correctly answered using
the retrieved MDN URL. No cloud inference or human app-code fixes were used.

These supersede the earlier planning/tool results, but do not establish a new
full application build/browser pass. The stopped expense run was left cancelled.
See [Documentation-assisted agent recovery](documentation-assisted-agents.md) for
the architecture, scope and exact evidence locations.
