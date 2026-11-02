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
