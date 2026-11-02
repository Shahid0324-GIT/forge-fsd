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
