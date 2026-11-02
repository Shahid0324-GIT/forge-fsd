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
