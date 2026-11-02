# Autonomous ForgeFSD POC plan

Agreed direction, 2 November 2026. This supersedes the implementation direction in
`forgefsd-next-phase-plan.md`; the earlier audit and typed-planning evaluation remain
historical evidence. The redesign described here is not yet implemented.

## What the demonstration must establish

A user supplies the app goal and functionality. Agents analyse it, choose a design,
delegate implementation, use tools, inspect actual results, revise decisions, test,
prepare app CI and request deployment approval. The demonstration must show actual
parent/child work and evidence-driven iteration, rather than role labels around a
fixed generator. Sequential execution on the local 7B model is sufficient.

## Keep the product scope small

Use the existing Next.js App Router, React and Node platform. Support:

- Landing pages: content, navigation, calls to action and responsive layout.
- Small single-page apps: calculators, quizzes and similar interactive tools.
- A small single-page full-stack app: local SQLite records, validation and a few
  business rules. This retains the database/backend part of the assignment.

The agent chooses whether an API, database or reusable components are necessary.
A landing page must not be forced to invent API routes, CRUD entities or database
tests. A calculator need not use a backend just to satisfy the harness. Initial
evaluation should include a landing page, a stateless SPA and a persistent SPA,
including a held-out request without app-name branches in production code.

Avoid authentication, payments, external integrations, arbitrary dependency installs,
large multipage systems and multiple deployment providers for this POC. Keep one
supported package/runtime base and use the installed Ollama model. These are declared
platform capabilities; business types, routes, structure and UI behavior are agent
decisions within that platform.

Stateless apps can use the existing approved Vercel release path. SQLite apps remain
local until a persistent hosting path exists. A stateless deployment plus a separate
local database app must not be represented as deployment of a persistent full-stack
app. If the assignment requires the same deployed app to retain database data, one
persistent deployment adapter is necessary; a multi-cloud abstraction is not.

## Minimal agent team and working loop

Keep a coordinator with registered planner, builder and QA subagents. Retain the
existing generated-app CI and deployment roles for the release stage. One builder
can implement a small complete app; delegate separate frontend/backend tasks when
the planner finds that division useful. Do not require a fixed number of agents,
files, components or business entities for every request.

The LangGraph loop is:

1. Understand the request; clarify only missing business requirements or unsupported
   capabilities. Planner proposes architecture, interfaces, tasks and testable behavior.
2. Review the proposal for consistency; retain the existing human plan approval gate.
3. Coordinator delegates tasks with the original goal, relevant artifacts, dependencies
   and the current revision. Subagents return artifacts, findings and requested changes.
4. Agents request tools to inspect/edit assigned source and run supported checks.
   The controller executes validated tool requests and records their real results.
5. QA compares behavior with the user requirements. Failures return to the responsible
   role; architecture problems return to the planner, implementation problems to the
   builder. Dependent tasks are refreshed when their inputs change.
6. Repeat within an explicit call/repair budget. Ask the user only for a business
   decision, approval or genuine capability blocker. Checkpoint unfinished work.
7. Passing evidence enables separately approved preview, app publishing/CI and deployment.

Evaluate the installed model's tool calling first. Use native tool calls if reliable;
otherwise use a small validated action envelope for delegate, request-tool, revise,
ask-user and finish. Do not build both execution systems or add another agent framework.

## Agent-owned design, small shared state

Agents create their own private types and implementation details. Shared API/data
interfaces are app-owned artifacts authored by the agents, with a revision and owner.
A shared interface can be revised through a recorded change request. A conflicting
definition should be explained and reconciled by its owners rather than blindly
rejected or silently overwritten. Relevant consumers receive the new revision.

Use the existing job/event store plus a small task/result envelope: task ID, parent,
owner, goal, dependencies, artifact references/revision, status and remaining budget.
No new database service, vector store, distributed scheduler or enterprise type registry
is needed. Save durable artifacts and short factual summaries; retrieve relevant files
instead of resending every prior message. Persist actual model/tool calls and outcomes.

Evidence belongs to the tested source revision. Design/source changes invalidate
affected evidence; final validation must match the final source fingerprint. Model
claims alone never establish passing tests or successful deployment.

## What changes in the existing code

| Area | Intended change |
| --- | --- |
| `workflow.py`, `agents.py`, `planning.py` | Replace fixed proposal/retry sequencing with the coordinator's bounded delegate/tool/revise loop. Keep LangGraph/LangChain/Ollama. |
| `schemas.py`, `contracts.py` | Keep strict execution/task envelopes. Let agents author app designs; remove mandatory API/CRUD counts and prescribed business interfaces from the new path. |
| `operations_design.py`, `layout_design.py` | Retire the mandatory business-operation and component-interface compilers from the new path. Preserve only mechanical framework validation/rendering where useful. |
| `workspace.py`, `builders.py` | Let the agent propose a project manifest and file tasks within its workspace. Reuse safe paths, protected control-plane boundaries and the existing dependency base. |
| `repair.py` | Return actual diagnostics to the task owner; permit recorded design revisions and refresh affected tasks instead of only retrying the last schema. |
| `verification.py`, `acceptance_design.py`, `browser_testing.py` | Select checks applicable to the app. Support landing-page/UI checks, SPA interactions, API checks when present, and persistence checks when storage exists. |
| `releases.py` | Reuse app publishing and deployment approvals; expose actual CI/deployment actions/results to the coordinator. |
| `persistence.py`, `handoffs.py`, `invocations.py`, dashboard | Extend the existing records/UI with task ownership, revisions and actual tool spans; avoid another observability system or dashboard rewrite. |

Do not rewrite everything at once or preserve two permanent generators. Build the
minimal new coordinator path, demonstrate it, then remove superseded planning machinery
once its replacement passes the evaluation. Existing saved evidence remains readable;
old approvals are not silently reinterpreted as approval of a new design.

## Tools and testing without overbuilding

Start with workspace read/list, owned file edits, and controlled typecheck/build/test
requests in Docker. Reuse existing preview and release operations. No unrestricted
host shell or credential access is required to demonstrate autonomy. Web research is
optional later; never display fetched sources or tool actions that did not happen.

QA derives expected behavior from the request, independently of generated logic. It
may inspect DOM/source for selectors and diagnosis without treating implementation
outputs as the expected answer. Keep the runner and required checks outside builder
ownership. Use a small reusable browser recipe for navigation, filling, clicking and
asserting visible behavior; do not add a custom profile per app.

## Implementation order and exit checks

1. Implement the task/action loop and a minimal tool dispatcher. Verify real delegation,
   tool results, correction routing, revision propagation and stopping budgets.
2. Complete a landing page and stateless SPA end to end. Verify generation, build,
   browser behavior and at least one genuine diagnose/fix/retest cycle.
3. Complete a small SQLite SPA with independent functional and restart-persistence checks.
4. Exercise generated-app CI and one approved stateless deployment; verify the live
   app and cleanup. Address persistent deployment only if the assignment requires it.
5. Reuse the dashboard timeline to present the evidence, then prepare the assignment demo.

Record model calls, repairs, duration, missing coverage and any manual intervention.
Do not count hand-edited app repairs as autonomous success. A happy-path landing page
alone does not establish the full-stack, database or iteration parts of the assignment.
