# Autonomous workflow implementation checkpoints

Branch: `codex/autonomous-coordinator`. This follows `autonomous-poc-plan.md`.
The existing dashboard pipeline remains available while the new path is built.

## Increment 1: durable tasks

`tasks.py` adds an event-backed task ledger using the existing SQLite job store.
It stores task ownership, parent/dependency links, app-owned input artifacts, revisions,
observations and recovery plans. It does not prescribe app types or project structure.

Atomic version checks reject results from work that was revised in flight. Revising
an upstream task invalidates downstream consumers, preserves historical observations
and requires refreshed inputs/dependency revisions before execution. Task completion
does not set application readiness or replace the existing approval gates.

Progress uses required-check outcomes, not an agent's claim or a changed source hash.
Missing/stale evidence cannot complete a task. An action budget saves a resumable pause;
it is not a terminal two-repair limit. Action dispatch counts are not presented as
model-token usage. A reviewer can recommend retry, reassignment or a focused input
request, but cannot mark checks passed or remove required checks.

Focused verification: 10 task tests pass, including restart, revision races, dependency
invalidation, cycles, stale evidence, ownership and budget resume. This is controller
evidence, not a completed generated-app evaluation. Orchestration/tool integration is
the next increment.

Interrupted dispatches are saved before invocation and require outcome reconciliation
before replay; this avoids blindly repeating side effects after a process crash.

## Increment 2: coordinator and senior reviewer

`coordinator.py` runs a LangGraph task loop. Repeated failures escalate to an actual
senior-review child task with the failed task as its parent. A validated strategy can
retry or reassign work to a registered owner; subsequent tool evidence still decides
completion. Changing source alone is not progress. Reviewer errors remain evidence
and can be corrected within the saved action budget. Reaching that resource budget
pauses work; there is no terminal two-attempt/two-repair rule in this new loop.

`senior_review.py` uses the installed LangChain/Ollama adapter with a focused context:
the original goal, app artifacts, recent actual outcomes, registered owner capabilities
and previous strategies. Distinct model-visible retry/reassign/input variants prevent
conflicting action fields. Technical reviews do not acquire authority to ask user
questions unless the task explicitly delegates it. This does not restrict the primary
planner's ability to ask genuine business clarification questions.

The existing handoff/call reports now support explicit task/parent identities. Reviewer
artifacts record proposal validation only. No reviewer output can mark app tests passed,
remove required checks, approve publishing or expand tool permissions.

Ten coordinator tests cover recovery beyond the old two-attempt limit, real child-task
records, owner reassignment, budget resume, invalid reviewer corrections, fresh checks
after artifact changes and interrupted-action handling. Live diagnostic replays used
historical planning failures and the installed 7B model; no app repair was executed.

One early replay mixed a retry with a question and a later replay repeated that malformed
action. Those failures motivated the discriminated action protocol, not a weakened
validator. The final recorded replay is
`artifacts/recovery-evaluation/bd0ccb812d1e4a34a40d34e0cb77651f` (exit 0, one new model
call). Its proposal passed the control schema, but its owner selection contradicted
its textual recommendation. Strategy quality and effective app repair therefore remain
unproven; the real tool/evidence loop must assess the result. This role is the same
local model, not a correctness oracle.

## Increment 3: agent-authored design proposals

`autonomous_planning.py` introduces an opt-in path that does not call the business
operation/component compilers. A requirements task classifies the original request.
An understood request becomes a dependent planner child task carrying the original
scope and human clarification answers. The planner chooses the app-specific design,
interfaces, source manifest and test strategy. It can choose a client-only app without
API routes, stored entities or a mandatory backend task. Application type names are
not reserved by the controller.

The controller validates the delivery envelope, source paths, duplicate ownership,
protected package/configuration boundaries and the supported Next.js home entry.
This does not establish architectural completeness or working code. A genuine intake
question is saved and can be answered in the same run; the revised intake/dependency
revision and all prior evidence remain available. Paused work resumes with an explicit
per-task action-budget extension. Draft and intake snapshots are retained per attempt.

An uncommitted experiment that let the planner raise optional questions, followed by
another model pass to resolve them, did not reliably distinguish optional choices from
business blockers. It was rolled back rather than retained as another review layer.
Its evidence and source experiment remain under
`artifacts/autonomous-planning-evaluation/48ec85cfecc04cc7875b7e576717c05d`.
Requirements intake now owns clarification before architecture; the planner owns
ordinary design defaults. The app design itself remains agent-authored.

```powershell
.venv\Scripts\python.exe -m forge --db artifacts/autonomous-demo.sqlite3 autoplan "Build a small tip calculator with no saved data."
.venv\Scripts\python.exe -m forge --db artifacts/autonomous-demo.sqlite3 autoplan-resume JOB_ID --additional-actions 8
.venv\Scripts\python.exe -m forge --db artifacts/autonomous-demo.sqlite3 autoplan-answer JOB_ID --answer "Answer the pending business question here."
```

`autoplan` produces a proposal, not an approved or generated application.
`autoplan-resume` is for resource pauses; an interrupted dispatch additionally needs
outcome reconciliation before `--reconciled` is appropriate. An actual business
clarification uses `autoplan-answer`. No automatic publishing/deployment is added.

### Final verification for this increment

- Full Python suite: **235 passed**, exit 0; 13 upstream LangSmith deprecation warnings.
- CLI command registration/help and `git diff --check`: passed.
- No dashboard TypeScript files changed; no dependency/lockfile/model changes.
- Live command: `.venv\Scripts\python.exe scripts/evaluate_autonomous_planning.py`, exit 0.
  Evidence: `artifacts/autonomous-planning-evaluation/4770eb933bea4572b2f6dc2f5e0b66f1`.
  Its source snapshot matches the candidate implementation.

| Request | Outcome | Model calls | Seconds |
| --- | --- | --- | --- |
| Landing page | AUTONOMOUS_DRAFT_READY | 2 | 47.98 |
| Client-side calculator | AUTONOMOUS_DRAFT_READY | 2 | 40.57 |
| Local SQLite expense SPA | AUTONOMOUS_DRAFT_READY | 2 | 55.29 |

All reached proposal review without optional-question blockers. No recovery reviews
were necessary in these three successful planning cases; the separate tests/replays
exercise escalation. **No app source was generated, built, browser-tested or deployed
by this new path.** This is not a three-app E2E success claim.

Manual proposal review still found concerns: landing/calculator test strategies assume
Jest/React Testing Library, which are not in the current dependency base; calculator
assumptions conflict with its invalid-input requirements; landing contact-form behavior
is unspecified; the expense design needs a concrete UI/server/SQLite boundary and
explicit restart testing. These remain review findings, not passing coverage.

## Next increment

Expose the actual workspace/tool capabilities to the planner and builder, implement
owned source edits and controlled checks through the new coordinator, and execute one
small SPA through generate -> inspect -> repair -> retest. QA must use the original
requirements and available tooling, not just accept a draft's testing claims. Then
connect the verified path to the existing dashboard controls. Keep UI redesign,
Tailwind/new dependencies, complex apps and additional deployment targets deferred.

## Increment 4: scoped workspace tools and real isolated build checks

`workspace_tools.py` exposes typed `list_files`, `read_file`, `write_file` and
`check_build` requests. The controller binds a workspace, app-authored manifest and
active task; the model cannot supply another root, owner or shell command. Reads and
edits are recorded as actual tool spans. Writes require the latest file hash, enforce
task/QA ownership, protect runtime/package configuration and preserve the previous
source before mutation. Stale task revisions cannot perform tool operations.

The capability description reports declared app dependencies and the checks actually
implemented. It does not claim Jest, browser interaction or persistence coverage.
Pure client helpers under `lib` remain permitted; the tool does not impose the old
assumption that every `lib` module is server-only. Nested test paths require QA ownership.

`source_checks.py` and a controller-owned Node runner perform TypeScript and production
build checks without requiring task-manager routes, an API or a database. Execution
uses the existing dependency image by immutable ID, readonly source, no network,
non-root/resource limits and only the specific build harness mount. Source/image
lockfiles, final source and harness fingerprints are checked; missing evidence or
cleanup failures cannot pass. Containers use the existing verification cleanup labels.
This tool does not mark application behavior, browser checks or readiness as passed.

Verification:

- Full suite: **258 passed**, exit 0; 13 upstream LangSmith deprecation warnings.
- `.venv\Scripts\python.exe scripts/evaluate_workspace_tools.py`: exit 0.
- Actual Docker service: 29.8.2; existing image
  `sha256:50af5949229f75b3b1165845a38fb8a5206157845112e632a8940e8da1e6232d`.
- Evidence: `artifacts/tool-evaluation/01928df02fec4440808091f906a1d5eb`.
  A deliberately invalid static fixture failed TypeScript; its corrected version
  passed TypeScript and production build. Both containers and the disposable fixture
  were cleaned up. There were no model calls or downloads in this tool verification.

This is a verified tool increment, not an autonomous repair or generated-app success
claim. Model-driven file generation and independent behavior checks remain next.

## Increment 5: experimental model-driven source work and repair replay

`source_agent.py` adds a builder callback for the durable coordinator. It receives
the original request, agent-authored design, actual source and installed capability
inventory. The model proposes an owned file edit; the controller executes it through
the scoped workspace tools and records the model-call identity on the tool span.
File and workspace fingerprints reject proposals made against changed context.

Repairs delegate diagnosis to a QA child task, then propose exact-text replacements
in one owned file and run actual isolated checks. Patches must match uniquely and
are prepared fully before writing. Unchanged proposals cannot count as repairs.
Compiler locations include the actual line, column and expression. Subsequent
diagnoses retain real compiler evidence and the last tool rejection, rather than
replaying previous unverified reviewer hypotheses as if they were facts.

The evaluation scripts generate a disposable internal fixture from the previously
saved calculator design and resume its same task/source checkpoint. They archive
source, model calls, tool calls and build reports before removing the checked UUID
workspace. They do not approve a user app, publish, deploy or start a preview.

### Verification and observed limitations

- Full Python suite: **271 passed**, exit 0, 13 upstream LangSmith warnings.
- After the final context adjustment, the affected source/tool tests: **28 passed**,
  exit 0. `git diff --check` passed.
- A sandboxed pytest attempt could not create its temporary fixture directories
  (`OSError: could not create numbered dir`); the suite passed when run with access
  to its normal temporary directories. No dependencies or lockfiles changed.
- Evidence directory:
  `artifacts/source-agent-evaluation/6ebe47d5500d4765acfda72ef7271bae`.
- The installed 7B model generated the three declared source files. One proposal
  attempted an unavailable dependency and was rejected; a later proposal removed it.
- The generated candidate failed real TypeScript checks: a void-expression
  truthiness test, an incorrect relative import and an undeclared layout component.
  No generated application source was manually corrected.
- Initial and resumed repair attempts repeatedly returned unchanged code or an
  incorrect diagnosis. The coordinator saved resource pauses and all evidence;
  neither the reviewer nor a completed source-write task marked the app ready.
- Exact patches and compiler-location grounding are general tool improvements,
  **not proof that the model repair loop is reliable**. Application behavior and
  browser interaction remain NOT_TESTED. No successful autonomous app build or
  end-to-end readiness is claimed by this increment.

The next checkpoint must demonstrate effective source repair against actual checks,
then independent application behavior checks. Normal approval/dashboard integration
and the later UI redesign remain deferred; the dashboard still uses the older path.

### Increment 5a: precise feedback for ineffective patch entries

Each exact-text replacement must now change its matched text, including within a
mixed patch containing other valid edits. Rejection identifies the unchanged entry,
asks the builder to correct or omit it, and preserves all source. Tests cover the
invalid entry both before and after a valid replacement, plus the persisted failure
report. Focused source-worker/tool suite: **30 passed**, exit 0; diff check passed.
No live model replay was run for this small change. Model repair accuracy remains
unresolved; this improves tool feedback without claiming a successful app build.

### Increment 5b: repair-specific context and changing edit strategy

Repairs now use a shorter debugging instruction instead of the source-generation
instruction that required following QA's steps. QA's diagnosis is explicitly advisory;
actual compiler evidence and source take precedence. The builder retains the original
request, acceptance criteria, complete source and dependency inventory, without
repeating the draft's contradictory assumptions.

The builder can choose a complete-file replacement or an exact local patch. After
an unchanged or unmatched patch is rejected, the next dispatch requests a complete
corrected file rather than repeating the failing patch form. The same file/workspace
hash, ownership and nonempty-change guards apply. This selects an edit tool, not
application business types or architecture. An older tool rejection is no longer
carried forward past newer build evidence.

Verification: **276 Python tests passed**, exit 0, with 13 upstream LangSmith warnings;
the affected suite has **33 passing tests**. Tests cover both edit forms, fallback
after rejected patches, unchanged-file rejection and clearing obsolete tool errors.

Live replays use the same preserved fixture/evidence directory recorded above.
`resume-34.json` records a corrected relative import followed by a malformed patch
that introduced duplicate declarations. `resume-42.json` records no source progress
despite allowing a choice of edit tool. These failed evaluations motivated explicit
fallback after a rejected patch. Neither replay passed the build; both cleaned up
their disposable resources. No generated source was manually fixed.

The fallback replay **passed** (`resume-50.json`, command
`.venv\Scripts\python.exe scripts/resume_source_agent_evaluation.py artifacts/source-agent-evaluation/6ebe47d5500d4765acfda72ef7271bae --additional-actions 8`,
exit 0). From the saved failed checkpoint it used 8 dispatches: 5 builder/QA
repair attempts and 3 senior reviews, totaling 13 actual model calls. It corrected
duplicate declarations/imports with a whole-file edit, repaired the void-expression
handler with a local patch, and iterated on Next.js client-boundary errors.

Final build report: `source-checks/bed0cbf1f46349388c678dd65010c616/7d624033051f4f54b7db47586262e1e9.json`
within the same evidence directory. TypeScript and `next build --webpack` both exited
0. Source and harness remained unchanged during checks; cleanup reported no errors.
Archived source fingerprint:
`f8c55b8a65be4ab27a222a00226aaa8b5126dc15e5d5a4f828bcf22e7577cb9d`.

This demonstrates build recovery on **one previously failing fixture**, not general
repair reliability. Application behavior, browser checks and readiness remain
unverified. Source inspection suggests zero-tip results may remain hidden by the
generated display condition; independent behavior checks must cover that case.
After the replay started, the instructions were further clarified to put client
directives before imports rather than inside a component. The final affected-suite
rerun passed all 33 tests; the live replay used the preceding instruction wording.

### Increment 5c: recheck changed source before diagnosing it

A failed check's fingerprint must match the current workspace before its diagnostic
locations are supplied to QA or the builder. Otherwise the worker runs fresh checks
without a model call or source edit. Tests cover both newly passing and still-failing
source. Existing recovery tests now record the fresh result as the coordinator does,
so stale context cannot accidentally exercise a different branch.

## Increment 6: reproducible repair fixtures with independent browser checks

`scripts/evaluate_repair_regressions.py` seeds two deliberately faulty, committed
test fixtures. These are controlled repair evaluations, not model-generated app or
requirements-planning success claims. After initial seeding, all source corrections
must come from the model through the existing owned/hash-checked tools.

The counter exercises a component import/props mismatch, client boundary and
increment behavior. The formatter initially builds successfully but returns lowercase
text contrary to its request. Frozen browser assertions live in `tests/repair`,
outside both the app manifest and the application container. A separate browser
container receives the assertions but no source mount. It interacts with the real
app through an internal Docker network, without host ports or external requests.
The existing dependency/browser images are resolved by immutable IDs; nothing is
downloaded or installed.

The evaluation's controller-supplied check runner combines actual TypeScript,
production-build and browser evidence. A successful build cannot mask a failed
browser assertion, different source fingerprint or different app image. Coverage is
explicitly `PARTIAL_FROZEN_FIXTURE_ONLY`. The existing dashboard, converter browser
gate and application readiness/publishing gates are unchanged. This is not a new
automatic browser profile for arbitrary apps.

Browser reports include source/harness fingerprints, exact case results and cleanup
outcomes. Resource identities are written before Docker starts so interrupted
evaluations can be inspected. Normal failure/exit cleanup removes the owned browser
and app containers plus their internal network. Abrupt process death still requires
reconciliation of the saved resource record; this increment does not add a new
dashboard restart sweeper.

Reproduce with the installed 7B model and existing app/browser Docker images:

```powershell
.venv\Scripts\python.exe scripts/evaluate_repair_regressions.py --case formatter
.venv\Scripts\python.exe scripts/evaluate_repair_regressions.py --case counter
```

These commands require local Ollama and Docker. The Python tests mock those services
and do not run these live evaluations. Source snapshots, task ledgers, model/tool
calls, screenshots and reports are saved under `artifacts/repair-regressions`.

### Observed results

| Fixture | Initial evidence | Final evidence | Actual model calls |
| --- | --- | --- | --- |
| Formatter | Build passed; both browser assertions failed with lowercase page text | Build and 2/2 browser assertions passed | 2 |
| Counter | TypeScript failed on the component contract; browser not yet run | Build and 2/2 browser assertions passed | 8 |

- Formatter evidence: `fbddf7a6fb8045ce817d057af3a2350c/formatter` under the directory above;
  source fingerprint `e4004ee7a36b5b3abf3c66207144e3860755b785dd86a4710d56099f3921bf9f`.
- Counter evidence: `6eb2c8a1e69a46728900cdd879df27b6/counter`;
  source fingerprint `7ceecd3ddacc8c900a0eedccfc57160705a1186690976b25be38aba801ac993e`.
- Both commands exited 0. Final source archives match their build/browser reports.
  Disposable workspaces, containers and networks were confirmed removed.
- Full Python suite: **292 passed**, exit 0, with 13 upstream LangSmith warnings.
  Node syntax check and `git diff --check` passed. No dependencies, lockfiles or models changed.

The counter's increment bug was corrected by the model before its first browser
run; the formatter provides the direct failing-to-passing browser calibration.
This small sample does not establish general repair accuracy. Broader behavior,
database/restart checks and normal autonomous dashboard integration remain next.

## Increment 7a: managed-job planning adapter

`start_planning` starts intake/planning inside an already-created autonomous job,
preserving its request, job identity and managed-operation history. It rejects a
different workflow/model and repeat starts instead of creating duplicate task trees.
CLI planning now marks new jobs as autonomous and uses the same adapter. Existing
clarification/resume behavior is retained. This is the backend prerequisite for
dashboard routing; no dashboard controls change in this checkpoint.

Verification: **17 planning tests passed**, exit 0, including existing CLI cases,
same-job operation history, repeat-start rejection and model/workflow guards.

## Increment 7b: opt-in managed API routing

`POST /api/jobs` accepts `workflow: autonomous`; omitted workflow keeps the typed
pipeline. The worker routes from the saved job marker rather than an untrusted
replacement request. Clarification and resource-budget resume use the same job,
model and task history. CLI resume shares the same adapter. Interrupted dispatches
cannot resume through the dashboard without inspection/reconciliation.

API views identify the workflow and safe-resume availability. Reading an autonomous
proposal verifies its saved content hash and schema. Autonomous planning jobs cannot
enter legacy build, approval, preview or publishing actions. No UI selector or new
app-execution path is included in this checkpoint.

Verification: **42 focused API/planning/pipeline tests passed**, exit 0, covering
old API behavior, managed-job identity, immutable workflow selection, same-run
clarification/resume, interrupted-action rejection and proposal tampering.

## Increment 7c: autonomous planning controls in the dashboard

The new-application form offers **Autonomous planner · proposal only**, while the
existing app workflow remains the default. Autonomous runs show actual intake,
planner and senior-review activity, support same-run clarification and safe pause
resume, and open a structured, fingerprint-checked proposal report. The proposal's
architecture, source responsibilities, acceptance criteria, assumptions and suggested
tests are presented as unexecuted proposals. There is no approve/build control for
this mode yet. Legacy approvals and release behavior remain separate.

Verification:

- Full suite: **304 passed**, exit 0; 13 upstream LangSmith deprecation warnings.
- Dashboard TypeScript check and Vite production build: passed, exit 0.
- React checklist review: new proposal rendering uses escaped text, typed props,
  no extra listeners/effects, and explicit labels. Answer input is cleared after a
  successful submission so later clarification questions do not reuse old answers.
- Browser -> API -> managed worker -> local 7B -> SQLite tasks -> proposal display
  was inspected on a real run using a separate database. The planner's context
  dialog showed the original request, and browser console inspection returned no
  errors/warnings. The expiring test server was then closed through the UI.
- Evidence: `artifacts/dashboard-planning-smoke/f3161bbc571c498d86a41d21d18a2257`,
  including `result.json`, `job.json` and `proposal.jpg`.
- Job `4e470d35b05a419c850660bf8dbfc5d2` reached `AUTONOMOUS_DRAFT_READY` in one
  managed operation and **2 actual model calls**. No app was approved or executed;
  the regular dashboard database/run history was not used.

Content review still found an unnecessary backend for a local counter, an API
filename outside App Router's handler convention, and only manual suggested tests.
These remain open model/planning-quality findings. The UI/API integration passed;
this is not an end-to-end app build or a claim that the proposal is implementation-ready.
Before connecting approval and generation, ground plans in actual runtime capabilities
and ensure the execution loop can revise ineffective design decisions safely.

## Increment 7d: ground planning in the committed runtime

Planner handoffs now include dependencies/dev dependencies read from the committed
template package, its fingerprint, framework entrypoint conventions, available
verification coverage and server-only SQLite limitations. Test-framework availability
is derived from that inventory. Instructions distinguish optional HTTP handlers
from ordinary source helpers, without prescribing app business types or requiring
a backend. The original user request and clarification answers are preserved.

Full suite: **305 passed**, exit 0; 13 upstream LangSmith warnings. A separate
local-7B replay of the same counter request reached a proposal in **2 model calls**.
This time the design used only `app/page.tsx`, `app/layout.tsx` and `app/globals.css`,
with no backend or internet assumption. Evidence:
`artifacts/planning-context-evaluation/74045c70f51d41df94c4ecc331316573`.
This is one improved proposal, not proof of general planning quality. No application
was approved, generated or tested by that replay. Approval/source execution and
independent app-specific behavior checks remain the next integration step.

## Increment 8a: bind human decisions to immutable proposals

New proposals receive a separate immutable review snapshot with task/revision and
runtime/scaffold provenance. `autonomous_review.py` computes a review fingerprint
over the exact proposal, original inputs/answers, selected model and runtime. Approval
and rejection are serialized decisions; approval records source-generation/build scope
only and does not claim application correctness, preview or publishing permission.
Changed proposals, tasks, requirements or runtime invalidate the decision. Cancelled
and rejected jobs cannot reuse it. This checkpoint exposes no new UI execution action.

Verification: **35 focused review/planning/API tests passed**, exit 0; 13 upstream
LangSmith deprecation warnings. No generated app code or model calls were executed
by the approval tests.

## Increment 8b: approved generation and isolated build execution

`autonomous_build.py` executes the approved manifest with durable per-file source
tasks, followed by a verification/repair task. Workers receive the original request,
clarifications, review feedback, complete relevant source and approved ownership.
Generation reviewers are limited to the file's owner; the build reviewer can reassign
repairs among registered owners. No task-manager source fallback is used.

Tool actions recheck plan authorization, including after model calls. Cancellation
prevents a returned proposal from writing source. Saved build pauses retain work;
resume rechecks current source and does not regenerate files already completed before
the repair phase. Untracked workspaces are never overwritten. The final status is
`AUTONOMOUS_BUILD_CHECKS_PASSED`, with application behavior explicitly `NOT_TESTED`;
it does not grant preview, security, readiness or publishing status.

Verification:

- **48 focused build/review/source/tool tests passed**, exit 0; 13 upstream warnings.
- `.venv\Scripts\python.exe scripts/evaluate_approved_build.py`: exit 0. The fixed
  internal counter request went through fresh local-model planning and source
  generation, then real isolated TypeScript/production builds, with **14 model calls**.
- Evidence: `artifacts/approved-build-evaluation/745726adee9f454f87fc03930edb3a43`.
  Approval actor is `internal_evaluation`; human approval is **not claimed**.
  No generated source was manually corrected. Source archive/report fingerprints
  match, and the disposable source workspace and verification containers were removed.
- Final source fingerprint:
  `1f2e4052dbc9e4fc327fdc790f31167e80b973c2bf9285418f6329c80a71259e`.

This checkpoint does not yet expose dashboard approval/build controls. App-specific
behavior tests, normal preview integration and safe technical design amendments remain
separate work; the live result proves build recovery, not that the counter works.

## Increment 8c: managed review, feedback and build routing

The managed API now accepts explicit consent plus the fingerprint from the loaded
proposal before dispatching autonomous generation. Approval, decline, request-changes,
continue-after-approval and saved-build resume remain separate actions. Preview and
publishing still cannot enter the autonomous workflow through legacy release actions.

Review feedback returns through requirements intake in the same job. Original inputs,
answers and feedback are retained; out-of-scope changes can ask a blocking question
before replanning. New snapshots/check reports have unique task/revision names so
earlier review evidence is not overwritten. Historical proposals cannot supply the
current decision token. Approval authorizes isolated development checks without
repeated permission for ordinary repairs; only build checks currently execute.

Workspace runtime files must still match the approved scaffold, including on resume.
The API marks build evidence stale if current source differs. Unexpected worker exits
and deletion/restoration recognize autonomous building/replanning states.

Verification: **325 Python tests passed**, exit 0; 13 upstream LangSmith warnings.
Tests include consent rejection, stale loaded proposals, decline without generation,
same-job feedback, changed runtime configuration and current-source evidence flags.
Dashboard controls are a separate following checkpoint.

## Increment 8d: dashboard decisions and saved execution

The experimental autonomous app workflow now exposes proposal consent, Approve & build,
decline and review feedback in the proposal viewer. Decisions carry the fingerprint of
the loaded report. Revised proposals reset the checkbox; stale reports cannot authorize
the current proposal. Accepted approval/feedback returns to the live workspace. Build
roles, tool activity, saved resume controls and source export are visible there. A build
pass explicitly leaves app behavior unverified; changed source is marked stale.

An isolated browser-operated counter evaluation verified same-job feedback adding a
Reset button, no generation before approval, stale-report rejection, fresh consent and
managed generation. Its first eight build-repair dispatches paused on a missing Next.js
client boundary after fixing a layout import. The dashboard was restarted against the
same test database, and Resume saved build retained source and approval. This is an
internal operator test, not a claim of actual user approval or application correctness.
Evidence: `artifacts/approval-ui-smoke/d140ba5bf33047a8827aa6da5fde8887`.

The failure also exposed imprecise framework instructions: the model alternated between
a missing directive and bare, invalid `use client`. Generation/repair instructions now
give the quoted source statement explicitly, without changing generated source by hand.
Senior-review context also retains human clarifications and feedback. These are general
framework/context corrections, not a counter implementation patch.

Verification: **326 Python tests passed**, exit 0, with 13 upstream LangSmith warnings;
dashboard TypeScript and Vite production build passed, exit 0. Live build recovery is
recorded separately from these controller checks; independent app behavior, preview and
release integration remain pending.

Live outcome: the resumed browser test reached another saved resource pause after
16 total verification-task dispatches. The model still alternated between missing
and invalid client directives despite the clarified instruction; senior review also
repeated an obsolete layout diagnosis. This is an unresolved model/context recovery
weakness, not a passing app demonstration. Nine build reports recorded no cleanup
errors. The source and job were archived with fingerprint
`46a963398f6857fbbb1cb6b68588418093fe98fec73f6185e868153a6db1eebe`;
the disposable workspace was removed and the isolated dashboard closed. No user run,
cloud resource or main dashboard database was changed. Next repair work should make
the current source/check evidence explicit to reviewers and verify that their proposed
correction addresses it, before broadening autonomous behavior-test integration.

## Increment 9: current evidence, repair cycles and framework diagnostics

Repair tools now predict the whole-workspace fingerprint before writing a correction.
An edit restoring an exactly previously failed workspace in the same task revision is
rejected without mutation, with the earlier failure supplied as feedback. Reusing an
earlier file after another module changes remains possible. This detects exact cycles;
it does not equate every semantically similar program or prevent every unproductive edit.

Senior review receives a primary current-check packet and latest tool error separately
from history and previous unsuccessful advice. Approved-build context includes the live
source fingerprint. QA and builders receive the same small framework reference.

The trusted build harness uses the installed TypeScript parser for source locations and
module structure, plus lexical detection of an unquoted directive. It reports missing
quoted client boundaries for named hook imports and client/server metadata conflicts.
These are advisory diagnostics, not a complete Next.js analyzer or substitute for the
compiler, production build or acceptance tests. It never executes app modules or rewrites
source. Both diagnostic modules are mounted read-only and included in the harness hash.

A frozen `client-boundary` regression starts with an invalid directive and metadata in
the interactive page. Its independent browser assertions cover initial zero, repeated
increments, reset and preserved document title. The model may edit page/layout source,
but cannot edit the assertions. This evaluates repair of a deliberately broken fixture,
not fresh app generation or arbitrary app support.

Verification: **330 Python tests passed**, exit 0, with 13 upstream LangSmith warnings;
`node --test tests/framework-diagnostics.test.mjs`: **3 passed**, exit 0. An initial
exploratory replay had its harness changed during execution; later checks were incomplete
and that replay is excluded as a verdict on the final code. Its evidence is retained at
`artifacts/repair-regressions/bd255bffcaf7423e98c4481a138fcfbe` with that limitation.

The first fixed-harness replay (`0ea6007e347b4ecfb08c85fc97ee8195`) corrected the
quoted directive through a model-proposed patch, passed the real build and passed
three of four browser assertions. It paused without restoring the document title.
QA recommended changing the layout but selected the page; the controller had narrowed
the builder's tool schema to that selected file, despite describing QA as advisory.

Incremental correction: QA now recommends a target without narrowing the builder's
existing role ownership. A builder can correct another owned module; cross-owner
writes remain prohibited. A regression verifies this behavior. Reviewer context no
longer repeats the previous strategy or observations belonging to older fingerprints;
those details remain in the ledger/reports. Focused handoff/build tests: **33 passed**,
exit 0. A fresh fixed-harness replay is recorded separately below.

That replay (`00c3fe2a64654910ac947fa73147b933`) still paused on metadata after
correcting the directive. Inspection exposed another context gap: repair removed all
senior-review strategy data, including advice produced for the current source. Fresh
advice is now passed to both QA and builder only when the reviewed observation count
still matches; the existing source-fingerprint check rejects stale build locations.
Another observation invalidates that advice even if source bytes did not change.
Two regression variants verify fresh versus superseded advice; **24 focused tests
passed**, exit 0. Historical reviewer text is not blindly replayed.

Final fixed-harness client-boundary replay: **passed**, exit 0, with the same local
`qwen2.5-coder:7b`. The model quoted the directive, added the preserved title metadata
to `app/layout.tsx`, then removed the server-only export from the client page. All
post-fixture source changes were model-issued tool requests; no generated code was
manually corrected. It completed in **6 dispatches / 8 model calls**.

- TypeScript and production build: passed.
- Independent browser assertions: **4/4 passed** (initial zero, repeated increments,
  reset to zero and preserved document title).
- Final source, build and browser fingerprints match; source/harness remained
  unchanged during checks; verified image IDs match and cleanup reports no errors.
- Evidence: `artifacts/repair-regressions/cd8968c791054740a0befc9e028dac34/client-boundary`.
- Final source fingerprint:
  `2ff179f652559e9876c4e8636166a2d61e503f74af71f441e85c5ff3d6e765f3`.
- Final full controller suite: **333 passed**, exit 0, with 13 upstream warnings.

This demonstrates recovery on the frozen regression, not arbitrary application
generation or completion of the dashboard's independent app-QA integration.

Unrelated formatter replay with the same final code: **passed**, exit 0. Initial
TypeScript/build passed but both frozen browser assertions failed on lowercase output.
The model selected `lib/format.ts` and patched the transformation; final build and
**2/2 browser assertions passed** in 2 dispatches / 2 model calls. Evidence:
`artifacts/repair-regressions/cf8eea19e39b44e7885758fba572981f/formatter`.
Source fingerprint:
`e4004ee7a36b5b3abf3c66207144e3860755b785dd86a4710d56099f3921bf9f`.
No manual source corrections, dependency changes or model downloads were used.


## Increment 10: independent app acceptance contracts and repair integration

The autonomous workflow now defines browser assertions from the approved request,
clarifications, human feedback and design. Acceptance QA receives no generated source
or builder diagnosis. It produces a data-only contract with semantic targets and actual
assertions, referencing each approved criterion or explicitly marking it uncovered.
Coverage references are model proposals, not an independent semantic correctness oracle.

Contracts are frozen outside the generated workspace, bound to the review/model and a
completed QA task revision. Builders can read the contract for repairs but cannot write
it. A fixed Playwright interpreter executes the actions in a separate container; app
source is mounted only in the app container. Both use an internal network with no
published host ports. External navigation and arbitrary JavaScript/selectors are not
part of the protocol. Visibility is required for text/value assertions.

The existing generation/build stage is followed by acceptance QA in the managed worker.
Actual browser failures enter the existing source/QA-diagnosis/senior-review loop.
Resume retains the frozen contract, rechecks source and does not regenerate completed
files. Unsupported coverage blocks promotion rather than substituting superficial
assertions. Success is `AUTONOMOUS_APP_CHECKS_PASSED`, covering selected assertions;
no READY, security, restart-persistence, preview or release claim is added.

Source, contract, completed verification revision, combined report, nested build/browser
reports, harness fingerprints and image IDs are checked for current evidence. Dashboard
controls expose app-check resume, unsupported criteria, frozen contracts and stale passes.
The new workflow remains experimental; the older typed workflow is unchanged.

### Calibration and failure findings

- The generic runner accepted a fixed correct counter and rejected an increment-by-two
  counter at the expected assertion. Both apps first passed real builds. Calibration:
  `artifacts/acceptance-calibration/be9b368e63f84abbb606d0d3e07131bb`.
- An initial local-model trial froze `role: text`, which the initial target schema had
  incorrectly allowed. That trial was stopped and preserved unchanged at
  `artifacts/approved-build-evaluation/fed2870bf20e4831958d5702a92ca890`.
  Role targets now have an explicit supported enum, so invalid role names cannot be
  frozen. This is tool-protocol validation, not a business-app-specific correction.
- Cancellation exposed a preview resource lookup accepting a status string and missing
  orphan browser-network cleanup. Lookup now accepts actual preview resource records;
  cleanup finds networks by job/role labels and validates ownership/name before removal.
  Restart reconciles owned resources without replaying lost dispatches; cleanup failures
  remain visible. Interrupted work still requires inspection before resume.

The frozen test driver, assertion protocol and model context are separate from source
ownership. No new dependencies/models or external security-service signup were used.

A second trial (`8e39c0c282594e0aa604cd2c1ea47abf`) reached explicit blocked coverage,
not a pass. Its auto-approved proposal had expanded “No saved data” into browser
persistence, and QA also marked a routine display requirement unsupported. This trial
is not counted as meeting the original request. Planning/QA guidance now explicitly
preserves exclusions and distinguishes missing markup details from unavailable test
capabilities. The evaluation supports `--review-feedback`, exercising the existing
request-changes boundary before internal approval. Approval remains a real review
responsibility; automated coverage-index validation cannot prove semantic fidelity.

The reviewed trial `dc7e0ed9b5894994ae44eb9fcf53bf9e` exercised saved QA pauses and
source-preserving resumes, with the original frozen contract unchanged. It exposed two
further issues: advisory compiler hints from a passing build were presented before
actual browser failures, and a textbox was paired with a DOM-text assertion. Debugging
context is now reconstructed from actual controller execution reports; passing checks
and obsolete advisory summaries do not outrank current failures. The advisory parser
also accounts for erased type-only imports. Text and form-value assertions now have
separate target capabilities, so incompatible role/action combinations are rejected
before freezing. These are generic protocol/context fixes; no generated app source was
manually corrected. The old trial/contracts remain preserved as failed evaluations.

### Generic recovery and context corrections

Rejected QA proposals are saved outside the generated workspace. Corrections receive
that proposal and precise conflicting or missing criterion indices rather than
starting again without the failed context. A focused coverage-review task evaluates
claimed unsupported requirements against the actual browser capabilities. It receives
the original requirements and proposed coverage, never generated source. Genuine
unsupported coverage remains blocked. Deliberate re-evaluation creates a new QA
revision and preserves earlier frozen contracts; builders cannot revise assertions.

Browser failures now include the actual target match count, visibility, observed
text or form value, and a bounded accessibility snapshot. Missing targets are distinct
from value mismatches. This gives QA, builders and senior review concrete observations
rather than a timeout to speculate about. Checks and expected values are unchanged.

The internally reviewed counter evaluation `3f838feda4734021a5b01eb56762b3f7`
exercised these recovery paths. Its first contract incorrectly claimed reload testing
was unsupported. Re-evaluation preserved that contract and created revision 2 with
checks for initial zero, repeated increments by one and reset after page reload.
Saved source and revision-2 assertions were retained across subsequent repair pauses.
All app-source changes came through the local model's scoped edit tools. Operator
resumes restored byte-identical archived source and did not manually correct it.
These internal evaluations do not claim human approval or deployment readiness.

### Verified recovery checkpoint — 3 November 2026

The same internally reviewed counter finally reached `AUTONOMOUS_APP_CHECKS_PASSED`.
Both requirements-derived browser scenarios passed: initial zero with repeated increments
to one, two and three; then increments followed by a page reload resetting to zero.
TypeScript and production build also passed. The last resume used two model calls to
identify and correct the observed `Counter: 0` versus `0` text mismatch. The frozen
revision-2 assertions and earlier revision-1 contract remained unchanged.

This was a recovered evaluation across implementation fixes, coverage re-evaluation
and explicit resource-budget resumes, totaling 45 model calls across its saved attempts.
It is not evidence of one-shot reliability. Earlier failed trials remain archived.

- Final result: `artifacts/approved-build-evaluation/3f838feda4734021a5b01eb56762b3f7/resume-9f704939b1ee4a5a9d87506c680fcc01/result.json`.
- Final model-generated source fingerprint: `8b5b05d1e873466f438416ed53386d217db1d1a976f749478196051b697a49c7`.
- Combined, build and browser results passed for that source. Contract and harness
  fingerprints remained current; source was unchanged during verification. App image:
  `sha256:50af5949229f75b3b1165845a38fb8a5206157845112e632a8940e8da1e6232d`.
  Browser image: `sha256:fcc6a8a92698ef11fa73f933bfdf5c778f2609dda960b2c172312a1d2f30e58c`.
- Cleanup reported no errors. No evaluation-labelled containers or networks remained.
  Archived source and reports were retained; disposable workspaces were removed.
- An isolated dashboard using the evaluation database and a byte-identical source copy
  displayed the current pass and its limitations. Browser warning/error logs were empty.
  `dashboard-app-checks.png` records that view. The Close workspace control completed,
  the server exited with code 0 and the temporary source copy was removed. This verifies
  presentation/shutdown of the existing result, not browser-initiated generation.
- `.venv\Scripts\python.exe -m pytest -q`: **390 passed**, exit 0; 13 upstream
  LangSmith asyncio deprecation warnings.
- `node --test tests/framework-diagnostics.test.mjs tests/browser-protocol.test.mjs tests/browser-diagnostics.test.mjs`:
  **9 passed**, exit 0.
- `npm --prefix apps/web run build`: TypeScript check and production build passed,
  exit 0.

Next increments remain fresh dashboard-led generation, safe technical amendments,
SQLite restart/integrity checks, then preview and generated-app CI/release integration.
This checkpoint adds no security, cloud deployment or unrestricted-app guarantee.

## Increment 11: reject expired senior-review context

Regression tests exposed two source-freshness gaps. After reopening a saved pause,
the coordinator could escalate old-source failures before rechecking changed artifacts.
A source change during a senior-review model call could also leave an obsolete
reassignment eligible for application. The coordinator now requires current artifact
evidence before review and rejects a review if artifacts change during its invocation.
Rejected proposals remain in the audit reports and cannot change the parent owner.
The existing upstream-revision guard also passed a simulated in-flight change followed
by reopening the persisted ledger: the dependent task remains invalidated and cannot
accept or replay the expired worker result. These are deterministic orchestration tests,
not a new local-model or generated-app benchmark.

The QA-to-builder boundary also revalidates the active task, approved authorization,
protected runtime and source snapshot after diagnosis returns. Changed source triggers
fresh verification instead of forwarding expired source or repair advice. Changed
requirements, approval or runtime stop the handoff before the builder is invoked.
Parameterized regression cases reproduce all four changes during the QA model call.

Validation for increment 11:

- New regression cases reproduced both senior-review gaps and all four QA handoff
  races before the fixes. The upstream requirement-revision case passed unchanged.
- Coordinator/task/acceptance integration selection: **54 passed**, exit 0.
- Source-agent/scoped-tool selection: **47 passed**, exit 0.
- `.venv\Scripts\python.exe -m pytest -q --tb=short`: **397 passed**, exit 0,
  with 13 upstream LangSmith asyncio deprecation warnings. No external model,
  Docker app run or cloud service was required for these deterministic regressions.
- No frontend or dependency changes; the preceding dashboard build checkpoint remains
  the latest frontend validation. Actual live-model timing and a fresh dashboard-led
  generation remain separate E2E work.

## Increment 12: bind planner candidates to their producing revision

A fresh dashboard-led character-counter evaluation exposed a further context issue:
review feedback was present, but `candidate.json` from the previous design revision
was still supplied as `latest_proposal`. The local model copied the obsolete proposal.
Planner context now reuses a candidate only when its fingerprint has controller-observed
draft evidence in the active task revision. Failure context is filtered to that same
revision and fingerprint. Historical snapshots remain intact, and same-revision
failed-manifest recovery still receives its candidate. An externally replaced candidate
is omitted. Planning/review regressions: **29 passed**, exit 0, including both newly
failing freshness assertions after the fix. Live dashboard evaluation continues separately.

## Increment 13: distinguish rendered-text and control-value failures

The dashboard evaluation built successfully after a model-authored client-directive
repair, then stalled on a visible-text mismatch. Both QA and senior review described
the observed extra label but repeatedly recommended changing input handlers instead.
The browser diagnostics now classify `text_mismatch` and `value_mismatch` separately,
using the fixed interpreter's actual comparison semantics. They explain rendered text,
input values and accessible names without changing targets, expected values or waits.
QA and senior-review guidance uses those facts before speculating about state logic.
Changes were made only after the managed operation paused. The original contract and
paused source fingerprints were saved before resuming. Node regressions: **11 passed**;
browser/source/coordinator Python selection: **51 passed**, both exit 0. The model must
still demonstrate any effective source repair in execution; advice alone is not a pass.

### Fresh dashboard-led verification — 3 November 2026

The character-counter evaluation reached `AUTONOMOUS_APP_CHECKS_PASSED` through the
actual browser UI and managed worker subprocesses. The sequence was create request,
review plan, request changes twice, review the new proposal, approve as an internal
operator, generate source, run real build/repair, freeze independent assertions,
run browser checks, pause, and resume through the dashboard after increment 13.
The requirements, proposal and frozen contract retained the same job identity.
This was a recovered integration evaluation, not one-shot app generation or human approval.

- Evidence: `artifacts/dashboard-evaluation/d5e7d76594124c1cbe95a0f6c24758e8/result.json`.
- Job: `59651087c464444b95a4f4e0787f5621`.
- Source fingerprint: `4b32e5b522ef6b85c377d7030bb5779313f2c85c86eee372db3cd782f9cd9711`.
- Frozen contract fingerprint before/after resume:
  `e28998f92a0d6d6c0a26594104393e3e80259520e2286786476e46990af1aa85`.
- Actual typecheck/production build passed; **4/4** frozen browser scenarios passed:
  initial zero/empty input, counting `Hello, world!` including its space, Clear
  resetting input/count, and empty state after Clear followed by page reload.
- The reload scenario clears input first. It does **not** establish persistence
  behavior for nonempty text and cannot establish absence of a database or storage.
  That weakness remains visible, despite its criterion coverage index. A protocol-valid
  QA proposal is not a semantic proof; stronger scenario-quality checks remain work.
- Before archival, `evidence_current` returned true. Combined/build/browser results,
  source/contract/harness fingerprints and immutable image IDs matched. No source,
  contract or harness changed during the successful execution.
- Saved-context inspection worked in the browser. **25** handoff packets passed
  identity/hash validation; **12** repair-context source bindings matched. All **8**
  accepted source edits were model-initiated and matched expected workspace hashes.
- **25** recorded model invocations; about **24.48 minutes** from request to final
  result, including operator reviews, code fixes, validation and a saved pause. This
  is not an isolated model-latency benchmark. No app source was manually corrected.
- The dashboard showed the current selected-check pass and explicit limitations;
  browser warning/error logs were empty. `dashboard-passed.png` records the result.
  Close workspace completed; the isolated server exited with code 0. Source was
  archived byte-identically and the disposable workspace removed. No job-labelled
  containers or networks remained. The regular runs database was not used.
- Docker Desktop was initially stopped and was started before execution. Existing
  app/browser image IDs matched the earlier checkpoint; no dependencies or models
  were downloaded or upgraded.

Final validation: `.venv\Scripts\python.exe -m pytest -q --tb=short`:
**398 passed**, exit 0, with 13 upstream LangSmith deprecation warnings.
`node --test tests/framework-diagnostics.test.mjs tests/browser-protocol.test.mjs tests/browser-diagnostics.test.mjs`:
**11 passed**, exit 0. No frontend changes; the prior TypeScript/build result remains
that component's latest validation. Security, app preview, SQLite restart/integrity,
publishing and deployment were not part of this run. Next work is stronger QA
scenario quality, then a small SQLite dashboard-led flow and remaining release stages.

## Increment 14: observable-state checks before freezing QA scenarios

New suites must observe the result of their final interaction. Same-path reload tests
must observe state after setup and before reload, then observe the reload result before
another interaction can hide it. A known baseline that is unchanged before and after
reload cannot establish a reset/persistence distinction. These checks inspect only the
action protocol, never app names, source, fields or business types; grouped form actions
and navigation to another route remain valid. Unknown initial state is not invented.
Rejected proposals are retained and returned to the QA correction loop with scenario,
step and reason. New contracts record structural-quality version 1; legacy contracts
remain readable without claiming this newer validation. This is structural evidence,
not semantic completeness or database-restart evidence. Scenario/contract/repair
regressions: **41 passed**, exit 0, with the existing 13 upstream warnings.

## Increment 15: review test effectiveness without expanding app scope

New app-QA proposals pass a separate test-quality reviewer before freezing. It receives
the original requirements, review feedback, approved criterion text and proposed steps,
never generated source. It must assess every covered criterion and reference existing
scenarios. Proposed blockers go to a narrowly scoped requirements reviewer: optional
robustness advice cannot invent new requested features. Blocking classifications require
an exact requirement quote; optional coverage remains a suggestion. Both roles use the
existing local model. This is additional scrutiny, not an independent-model semantic oracle.

The critique, scope assessment and effective findings are preserved together, bound to
the exact proposal fingerprint, parent revision and approved review. Their real child
tasks must have matching completed evidence when a frozen contract is loaded. Changing
either reviewer task or its evidence invalidates a prior app-check pass. Identical
proposals reuse their exact review rather than paying for another identical critique;
new proposals receive new reviews. Rejected proposals return to the saved QA correction
loop. The dashboard exposes test-quality and requirements-scope activity. Older contracts
remain explicitly unreviewed rather than being silently credited with these new gates.

`scripts/evaluate_test_quality.py` calibrates two fixed proposals with the installed 7B
model, without generating or executing an app. The meaningful proposal exercises three
different arithmetic inputs/results; the superficial proposal asserts only a page title.
The final calibration accepted the former and rejected the latter with valid findings:
`artifacts/test-quality-evaluation/90f4d0c513c74050b6682feef0ed5422/result.json`, exit 0.
Earlier failed calibrations are preserved (`70e92616…`, `f4683726…`, `e275b814…`,
`a0ba32cc…`): the critic expanded validation scope, and initial scope-protocol outputs
omitted evidence or contradicted their explanation. Explicit classification variants
now require a quote for blockers at schema level, followed by an actual-text check.
Those failures do not count as successful negative cases. This bounded calibration
does not establish general QA reliability or any generated-app success.

Reviewer/scope regressions: **16 passed**, exit 0. Separate app-result tests confirm
changed reviewer evidence/task invalidates a pass: **2 passed**, exit 0. Dashboard
TypeScript and production build passed with the new activity labels. Full-suite and
SQLite workflow results are recorded separately below when completed.

Full regression checkpoint for increments 14–15:
`.venv\Scripts\python.exe -m pytest -q --tb=short`: **427 passed**, exit 0,
with 13 upstream LangSmith warnings. `npm --prefix apps/web run build` passed
TypeScript checking and production compilation, exit 0. The separate SQLite dashboard
trial is not included in the calibration/regression result and does not yet imply a
working SQLite app.

## Increment 16: prevent answered clarification loops

The SQLite planning trial repeated an identical persistence question after the operator
answered it. Intake now rejects a repeated answered question (normalizing case, whitespace
and terminal punctuation) before persisting another question. Its next attempt receives
the actual rejected question/answer pair as a protocol error. Intake also receives only
current-revision errors and fresh senior advice, so a model can correct routing instead
of losing that feedback. Instructions distinguish historical question alternatives and
quoted rejected proposals from actual user decisions. No app/domain names are used in
the guard. Existing genuine-clarification and review flows remain supported. Planning/
review selection: **30 passed**, exit 0; no generated app was changed by this increment.

## Increment 17: review clarification ownership before asking the user

Intake clarification proposals now pass a narrow ownership review. The existing model
must distinguish genuinely missing business/capability choices from implementation
questions already delegated to the planner. Technical questions can route to planning
without fabricating a human answer; genuine unsupported requests still ask the user.
The decision quotes the actual request/feedback/answers and is saved in a real child
task with its own handoff and evidence. Stale parent state or invented quotes reject
the review. This is a fallible model routing judgment, not new implementation authority.
The dashboard identifies requirements-review activity separately from test review.

Local calibration (`scripts/evaluate_intake_review.py`) correctly delegated an API/
server-client design question and retained a payment-capability question for the user:
`artifacts/intake-review-evaluation/6309679f999b48f48cc5f1f567e2ed16/result.json`, exit 0.
No app was generated/executed in that calibration. Planning/review selection:
**32 passed**, exit 0. The preceding full checkpoint for increment 16 was **428 passed**;
the complete suite for this integration is recorded after it finishes.

## Increment 18: give implementers supported-runtime knowledge

The SQLite build paused after repeatedly proposing unavailable Prisma imports. Planning
had named native Node SQLite, but source-tool context listed npm dependencies without
its API reference. Builders and senior review now share bounded implementation facts:
Next.js server HTTP/client boundaries and, for SQLite apps, `node:sqlite`/`DatabaseSync`,
prepared reads/writes, bound parameters and the controller's `SQLITE_PATH`. This supplies
supported alternatives without adding packages, prescribing business types or changing
generated app source. Stateless apps do not receive SQLite-specific guidance. Tool and
runtime permissions remain unchanged. Generation also excludes recovery advice once
newer observations supersede the reviewed evidence.

`scripts/check_runtime_reference.py` checks these native APIs offline in the existing
immutable dependency image. It creates a temporary file database, uses bound statements,
reads rows, closes/reopens the database, then removes the probe container. This is not a
generated-app database test. The recorded probe passed, exit 0:
`artifacts/runtime-reference-evaluation/9cb38e29179b45179402581009a89cb6/report.json`.
It reports Node **24.22.2** and installed SQLite type-declaration SHA-256
`9ba17a5bdbeb17c5584000b1ae4b3552116f2151f6c04830c070ef36bf4cecec`.
Source/tool/build regressions: **57 passed**, exit 0. The last full checkpoint before
these changes was **430 passed**, with the existing 13 upstream warnings.

## Increment 19: source-text transport independent of structured metadata

Several normally completed JSON source responses ended mid-JSX, including the first
quoted attribute. A parser comparison reused the archived task context: the historical
source had five syntax diagnostics; raw-source generation had none. The initial probe
is `artifacts/source-transport-evaluation/1bfad11a0caf4d0e8c1936fdd0ec173b/result.json`.
The new adapter repeated that syntax result at
`artifacts/source-transport-evaluation/055cf23563034354991b7e3a11f2ca6b/result.json`.
These are syntax-only comparisons, not full app passes or proof of a universal cause.

The adapter returns one raw source body without JSON grammar constraints, retaining
model-call identity, input/output traces, disabled cloud tracing and completion checks.
It rejects empty, oversized, incomplete-fenced or multiple-fenced-block responses rather than
truncating them. Structured planning/QA protocols remain unchanged. The scoped writer
still owns path and hash validation; this increment does not yet connect the adapter
to app writes. Adapter/decoder/existing-agent selection: **20 passed**, exit 0.
`scripts/evaluate_source_transport.py <archived-model-call.json>` replays an archived
TSX source proposal without executing either candidate as app code.

## Increment 20: connect raw source to the existing scoped writer

The autonomous builder now uses raw source when its adapter supports it. For repairs
with multiple owned files it first selects a target through a small literal-path
schema, then generates that file's complete source body. A single assigned generation
target needs no extra selection call. Path, expected file hash, expected workspace
fingerprint and change requirement remain controller-bound. Ownership, dependency
policy, runtime authorization and actual build/browser checks are unchanged. The raw
body call's identity is recorded on the write; source is never executed on the host.
Legacy structured adapters remain supported. The builder can choose another owned
module when QA's target is wrong, and cannot choose another owner's file.

Regression tests cover quote/unicode preservation, multiple owned-file selection,
unauthorized targets, and source/task changes during selection or body generation.
Combined source selection: **43 passed**, exit 0; a further normalization-boundary
test passed in the **12-test** decoder selection. Dashboard TypeScript and production
build passed. No generated app source has been manually corrected; the paused notes
app is resumed separately to test actual compilation/behavior with this transport.

Full regression checkpoint after increment 20: **451 passed**, exit 0, with the
existing 13 upstream LangSmith deprecation warnings (229.21 seconds).

## Increment 21: ground missing-import diagnosis in snapshot path facts

The resumed notes build produced complete page/layout source, but repairs then toggled
the client directive while leaving unresolved imports. The existing cycle guard rejected
restoring a previously failed snapshot; the job paused without a build-pass claim.

For relative-module TS2307 diagnostics, QA and builders now receive the normalized
import base and matching existing source paths from the same fingerprinted snapshot.
Candidates are bounded and explicitly advisory; no missing module/export is invented.
Next.js API route candidates identify the HTTP boundary so a corrected path is not
mistaken for permission to import a server handler into client code. External package
and alias resolution are not guessed. These facts neither edit app source nor add
dependencies or override ownership. Implementation choices remain model-owned.

Import-reference/source-agent/raw-writer regressions: **39 passed**, exit 0, with
13 existing upstream warnings. Live effectiveness is evaluated separately; passing
controller tests does not establish that the model will choose the correct repair.

Final regression checkpoint: **458 passed**, exit 0, in 341.68 seconds, with
13 existing upstream LangSmith deprecation warnings. The dashboard production build
was already verified for increment 20; increment 21 changes no frontend code.

The additional live repair window did **not** resolve the notes build. Both the QA
and builder handoffs contained the correct path candidates and HTTP boundary facts,
but the model still proposed a previously failed page. The cycle guard rejected it.
This is evidence of a repair-selection limitation despite available context, not
evidence that stale/missing context explains every failure.

Checkpoint: `artifacts/sqlite-dashboard-evaluation/7443bd9ec7cf4c65985a3cad0be5825a/result.json`.
All **73** saved handoffs passed identity/context-hash validation. Final source
fingerprint: `0ccf56d0605dc69b9fc5220b2c4ba413f0e2ae48a7769aba04400db153b3a156`.
The source was archived with the same fingerprint before removing only its disposable
live workspace. The temporary dashboard stopped, and no trial containers remained.
The default dashboard database was not used. No manual app-source correction,
browser acceptance, database persistence, security, preview or release success is
claimed. The source/history remain available for a later controlled replay.

Next repair work should evaluate a structured recovery from rejected source cycles:
retain the rejected candidate's failure as explicitly historical evidence, require
the next plan to address its unresolved causes, and compare effectiveness on multiple
fixtures. This remains planned work; path hints alone did not solve this trial.

## Increment 22: explicit recovery actions for rejected source cycles

Cycle recovery now retrieves the matching failed build observation from the same task
revision. It labels that evidence as historical, separately from the current source
diagnostics. An error string alone, an earlier revision, or an unrelated/successful
check cannot supply historical build evidence. Senior review receives this distinction.

When raw-source repair selects a file with cycle obligations, a bounded structured
planning call requires one concrete action for every reported current/historical
failure in that file. Missing actions block source generation. The replacement body
receives those actions instead of the ordinary QA/target hypotheses that repeated the
loop. The model still chooses implementation and target; the plan is not proof that
an edit works. Source/task authorization is revalidated after planning and at write.
No app-specific fields, endpoints, source patches, dependency changes or relaxed gates
are introduced. Historical diagnostic positions are not represented as current lines.

Repair/coordinator selection: **53 passed**, exit 0. Cycle/raw-source selection after
adding source/revision-race cases: **14 passed**, exit 0. Dashboard TypeScript and
production build passed. Both Python runs report the existing 13 upstream warnings.
Live replay and full regression are recorded separately after execution.

Increment 22 full suite: **466 passed**, exit 0, in 269.30 seconds, with the
existing 13 warnings. Its live replay remained paused: the model supplied actions
for both failures but still copied the invalid import. Completeness of a repair plan
is not semantic correctness.

## Increment 23: reimplement a selected file after a rejected cycle

Three isolated source-context probes compared the installed model on the saved
failure. Readable whole-file input (`705fa0a42b5f424db2c0075974c7a91d`) and smaller
input (`d2d77581a5ae498587f0b09baaecf868`) retained the import failure. Those experimental
format changes were discarded. Reimplementation without the broken target body
(`2a64ece109b44b15bc0ff56708423f98`) generated HTTP calls instead of the invalid route
import, but still failed TypeScript state typing. None is a working-app result.
Evidence is under `artifacts/source-context-evaluation/`; compilation used disposable
source copies and did not modify the saved app.

The cycle-only raw-writer fallback now requests independent reimplementation of the
selected file. It retains requirements, other modules' actual source, current/historical
failure facts and controller-owned write hashes. The target body and its excerpt are
explicitly omitted from that final body handoff to avoid copying the failed implementation;
the complete snapshot remains in the preceding QA/target records. Ordinary generation
and non-cycle repairs continue to receive the current body. File ownership, protected
runtime, final compilation and independent acceptance checks remain authoritative.
No probe candidate is copied into the app. Cycle/raw-source/transport selection:
**26 passed**, exit 0, with the existing 13 upstream warnings.

Live reimplementation changed the model-generated page to use HTTP requests, but
introduced state typing and nonexistent-export errors. It remained build-paused.
This is progress beyond the exact import cycle, not a successful app or a general
model-reliability result. No isolated probe candidate was copied into the app.

## Increment 24: route unambiguous compiler evidence to its source owner

Build and acceptance coordinators can now hand a current compiler failure to the
existing owner when every located diagnostic belongs to that single other role.
Mixed-owner or noncompiler failures remain ordinary agent/reviewer decisions. Routing
uses the same-revision, same-source-fingerprint report and rechecks source around the
decision. The ledger records a controller handoff rather than pretending a senior
model made it. It preserves task revision, required checks, history and remaining
action budget; no new file permissions or workers are granted. In-flight tasks cannot
be reassigned. This prevents frontend retries from being the only way to resolve
backend-only build errors, without weakening final global compilation.

Routing/coordinator/build/acceptance integration: **42 passed**, exit 0, with the
existing 13 upstream warnings. Tests cover stale source/revision, ambiguous failures,
unregistered workers, source changes during routing and exhausted budgets.
