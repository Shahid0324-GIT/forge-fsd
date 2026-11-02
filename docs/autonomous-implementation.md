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
