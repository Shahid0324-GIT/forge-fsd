# ForgeFSD: workflow audit and next-phase plan

Planning date: 1 November 2026. Runtime reviewed at `b29861d`.

This document is a plan, not an implemented feature list. No generation, deployment, dependency upgrade, new security scan or model download was started for this review. The static inventory in `artifacts/full-workflow-audit/source-inventory.json` covers all 23 Python modules (3,209 lines); the runtime paths, dashboard, trusted test runners, release renderer, controller CI and relevant regression tests were also inspected. The earlier planning audit and two local model probes are retained in `artifacts/planning-system-audit/`.

## Assignment alignment

The intended demonstration is: a user supplies business functionality; a coordinator delegates to specialist agents/subagents; those roles exchange explicit context, design and implement a full-stack app, define and run tests, repair failures, prepare that app's CI, and perform a separately approved deployment.

The repository contains genuine pieces of this workflow, including LangGraph orchestration, compiled child graphs, local LangChain/Ollama calls, SQLite state/checkpoints, trusted Docker verification, generated-app GitHub CI and an approved Vercel workflow. Reliable generation across app domains and a fully visible, tool-using agent workflow are not established yet. Persistent database apps currently lack the implemented cloud adapter needed for the Vercel path.

| Area | Current code | Consequence / required improvement |
|---|---|---|
| Intake | `ApplicationRequest` validates length/model; API creates a planning job | No intent or capability routing; unrelated questions enter app planning |
| Requirements | Role call returns an `AppBrief` | Fields, constraints and relationships can remain ambiguous or inconsistent |
| Architecture | Role emits routes, files and prose contracts separately | Multiple representations can disagree; substring checks do not prove interfaces |
| Planning graph | Requirements, clarification, architect, acceptance planning, approval | Real orchestration exists; test planning is distinct from later execution |
| Subagents | Build parent delegates to a compiled backend→frontend child graph | Predefined role nodes, sequential execution; not arbitrary dynamic agent spawning |
| Context | Snapshot files, sender/recipient metadata, hashes, whole-file source packets | Useful transport foundation; semantic consistency and exact call correlation are incomplete |
| Model tools | Structured JSON proposals, no live browsing/execution tool loop | Models do not currently search the internet, inspect pages or execute shell commands |
| Tests | Model proposes API scenarios; trusted Node/Docker harness executes them | App tests exist; domain-independent browser coverage does not—current automated profile is converter-specific |
| Repairs | Actual failure reports → QA diagnosis → bounded source edits → re-verification | Good direction; interface guessing and generation failures can stop before useful repair |
| CI/deployment roles | Models produce notes; controller renders YAML and performs approved GitHub/CI/deployment operations | These are currently advisory planning roles, with controller-owned execution |
| Release | App-specific CI, exact-commit gate, release fingerprint and separate deployment approval | Preserve these controls; add clear tool traces and post-deployment application checks |
| Lifecycle/reporting | Operation workers, cancellation, previews, cleanup and readiness reports | Prior audit found restart/cleanup/evidence-consistency gaps; statuses must describe actual current evidence |

Calling an operation worker subprocess a subagent would be misleading: it hosts the job. The builder child nodes are the implementation subagents. Multiple specialist roles currently use the same selected model, with different prompts and input packets.

## Why the errors keep occurring

1. **The model carries mechanical consistency work.** It repeatedly translates the same decision into API paths, Next.js filenames, manifests, prose interfaces and test fixtures. These should share one authoritative representation.
2. **Constraints are partly hidden in Python validators.** The latest prose-path guard is absent from the model-visible JSON schema and accepts a path reference without establishing a usable interface. Fixing it would expose the missing handler file next.
3. **Business facts are insufficiently typed.** The latest brief contains an enum without options and a computed total among entity fields. Builders and testers then guess independently.
4. **Smaller prompts alone are insufficient.** In a live diagnostic, a narrowly scoped endpoint task still produced incorrect Next.js filenames. The model can return valid JSON with an invalid design.
5. **The latest architecture failure was not context exhaustion.** A live replay completed normally with 1,395 input tokens and 432 output tokens under the configured 8,192-token context. Saved builder packets also included the relevant backend files. This does not rule out context-budget problems elsewhere.
6. **Retry loops often repeat a broad task.** The saved architecture attempts were identical. Generic correction instructions contain irrelevant stage-specific details, while semantic review calls can raise incorrect findings.
7. **Context logs do not fully describe each invocation.** The saved handoff records logical context, but not every effective prompt/schema/options/retry packet. Model-call files lack a complete task/handoff correlation envelope. A hash proves identity of recorded bytes, not that the model received or followed the correct contract.
8. **Tests and capability claims have been conflated.** The 167-test controller result does not prove live model generation reliability. Representative generated apps need their own build, behavioral, persistence and browser evidence.

These are shared pipeline issues. Production logic must not branch on an app name to repair them. Domain-specific evaluation cases are appropriate tests, not production templates.

## Decisions and boundaries

- Keep Python, LangGraph, LangChain, Ollama and the supported Next.js platform.
- The user states functionality. Agents choose app-specific data, operations, UI composition and meaningful defaults.
- A typed design adapter handles framework conventions and consistency. It does not invent business behavior, replace failed apps with templates, or rewrite approved tests to match source.
- Support varied domains within declared capabilities. Requests exceeding supported features receive an explanation or business clarification before generation. Do not silently turn every app into CRUD or promise arbitrary frameworks/integrations.
- Preserve human approval for the reviewed plan, preview, publishing and cloud deployment. A material design change creates a new revision and invalidates affected approvals/evidence.
- Keep the selected 7B model initially and measure the revised workflow before considering another download/provider.
- Internet research is optional and explicit. A successful offline/local workflow should not require a documentation search for every file.

## What users will be able to observe

The UI should expose concise decision summaries, declared assumptions, task delegation, generated-code drafts, tool requests/results, evidence sources, tests, repairs and approval boundaries. It should not claim to display private internal model reasoning.

Example intended activity, not an existing execution transcript:

1. Coordinator delegates a bounded task to the backend builder.
2. Builder requests the current API contract and a relevant source file.
3. Controller validates and executes those reads; returned file/version references appear inline.
4. Builder proposes a file; the draft is visible and marked unverified.
5. Controller accepts the complete validated proposal and records its source fingerprint.
6. Verification runs the configured checks and reports actual exits/assertions.
7. Failed evidence is passed to a repair task with its original contract and fresh source.

Do not display an intention such as “I will test the API” as evidence that a test ran. A model summary must never create a passing status.

Use a common event envelope: run ID, task ID, parent task ID, invocation/span ID, actor, event type, timestamps, status, input/output artifact references, design revision and applicable source fingerprint. Tool records add the tool name, redacted arguments, approval decision where applicable, duration, exit/result, bounded output and failure reason. Distinguish requested, blocked, running, completed, failed, cancelled, stale and skipped.

The main workspace remains the live activity view. Expandable details show exact handoffs, file diffs, tool output and source excerpts; tabs retain full history, tests, source files, sources and releases. A bounded recent view must link to the full trace rather than hide earlier failures. Reopening a page should reconstruct the same trace from persistent events.

Code drafts may be streamed if the installed model/adapter supports this reliably. Partial content remains a display artifact until complete output passes validation. Token streaming is not a correctness signal. Failures and cancellation remain visible even when generation ends early.

## Internet and source provenance

Currently the model has no documentation search/browser tools. `agents.py` invokes a structured model response; it does not execute a `ToolNode` or an equivalent browsing loop. The bundled platform reference is a local source. Controller network activity includes dependency/audit services, GitHub and deployment; these must not be described as agent web research.

Add a controlled source/research capability when a task genuinely needs it:

- Search/fetch documentation through registered tools, initially focused on relevant official documentation.
- Record the real query, URL, fetch outcome, timestamp, content hash and excerpt/portion supplied to the agent.
- Distinguish fetched content, cached content, bundled references and model suggestions.
- Display failed requests and the absence of a source; never invent source links or claim a page was read when it was not fetched.
- Treat fetched content as reference data. It cannot change workflow policy, grant permissions or authorize commands.
- Keep credentials out of model context and readable trace output.

Tools available to Codex during development are not automatically tools available inside ForgeFSD. Forge needs its own registered tools, dispatcher, permissions and event records.

## Conversational intake and the weather example

Current behavior: `How is the weather today?` passes the input schema and would enter app planning. No intent router or live-weather tool exists. Whether the model invents an app brief, asks a question or fails is not deterministic and was not exercised by this audit.

Planned intake routes:

| Intent | Behavior |
|---|---|
| Create an app | Start requirements gathering after capability assessment |
| Change the current app | Capture a requirements delta, assess affected tasks and create a reviewed revision |
| Explain/help with Forge or this project | Answer from project state and documented capabilities; do not create a build job |
| Unrelated request | Explain scope without inventing live information or creating an application |
| Ambiguous request | Ask a focused clarification before choosing a workflow |

Weather questions should receive a clear statement that live weather is not connected. A request to *build a weather app* is different: it needs an external-data capability decision, with explicit setup or limitations. No keyword-only app-name allowlist should control supported domains.

Conversational intake is not a commitment to build a general-purpose chatbot. Its role is to preserve the user's app goal and handle relevant follow-ups. An unrelated message must not mutate an approved app specification or be smuggled into another agent's task.

## Implementation sequence

### Milestone 1 — Typed design and consistent handoffs (P0)

- Add a versioned app design with requirement IDs, concrete field rules/enums/references, computed outputs, operations, input/output shapes, error behavior, UI interactions and test coverage references.
- Compile Next.js route paths/files, manifests and interface packets from that single design. Preserve explicit user-specified interfaces where supported.
- Validate references, ownership, database capability, route consistency and required context before human approval.
- Introduce the shared task/context/event envelope. Save the actual canonical input packet, prompt/schema version, model/options and completion metadata for every call and correction.
- Budget relevant context explicitly; keep required interfaces/current repair source complete. Retrieve or split work when required context does not fit.
- Remove duplicated decision representations through the migration, rather than adding more prose exceptions. Preserve old run records and fingerprints.

Exit: different natural-language requests produce coherent reviewable designs and traceable handoffs; saved failures are regression cases. No user-supplied folder tree or internal schema syntax is necessary.

### Milestone 2 — Intake, task delegation and bounded tool use (P0/P1)

- Route intent/capability before creating a development job.
- Have the coordinator instantiate bounded task specifications for registered roles, with parent/child IDs, dependencies, expected artifacts and budgets.
- Make delegation and returned results explicit in LangGraph state. Scheduling can remain sequential on the local GPU; concurrency is not required to demonstrate subagents.
- Add scoped tools for reading declared project context, inspecting contracts and requesting supported checks. File writes remain reviewed proposals applied by the controller within task ownership.
- Evaluate the installed model's tool-request behavior. Use validated structured action requests and a controlled dispatcher if native tool calling is unsuitable. Do not introduce unrestricted shell access.
- Count actual model/tool invocations and elapsed budget, not just logical planning nodes. Resume the failed task against the same revision and preserve retry counts.

Exit: a trace demonstrates actual parent→child delegation, context/tool requests and child results. Help/off-topic requests do not launch app builds.

### Milestone 3 — Generation, independent tests and repairs (P0)

- Give builders concrete shared types/interfaces and relevant stable platform references; use supported database/runtime adapters where mechanical behavior can be standardized.
- Design app-specific API and browser test recipes independently from generated source. Export readable and executable test artifacts.
- Represent fixture identities and effects explicitly. Do not infer every business workflow from HTTP verbs or force non-CRUD apps into a CRUD fixture model.
- Replace the converter-only coverage assumption with reusable browser actions/assertions driven by the approved UI contract. Keep the runner outside builder ownership.
- Run typecheck/build/API/business checks, applicable persistence checks and supported browser interactions against the final candidate. Do not mark unavailable coverage as passed.
- Send actual failing evidence and fresh source into bounded repairs. Specification changes require a new review; tests cannot be weakened to make a repair pass.
- Centralize evidence status by design revision, source fingerprint, harness/version and relevant image/commit identity. New failures or edits supersede old passing evidence.

Exit: a persistent app and a stateless app complete the configured flow without undisclosed manual source edits. A developer-assisted repair is recorded separately, not counted as autonomous success.

### Milestone 4 — Observable app CI and deployment (P1)

- Upgrade CI/deployment roles from notes-only output to bounded structured recipes/proposals grounded in the same design and evidence.
- Render approved workflows through trusted templates; test that the generated app's CI executes its own tests at the reviewed commit.
- Expose GitHub preparation/publish/status and deployment requests/results as real tool spans, with separate approvals and no credential values in model packets or logs.
- Add post-deployment application checks. The current URL artifact plus successful deployment workflow establishes a deployment event, not complete live application behavior.
- Choose a deployment-compatible persistence profile before generation. Current Vercel support is stateless; a same-app database-to-cloud demonstration requires an implemented/tested remote adapter, or a supported persistent-container target. A remote URL alone cannot convert Node SQLite source.
- Validate the chosen persistent deployment path, including restart/redeploy persistence and any required isolated CI database test profile. Provider setup is explicit human-controlled configuration.
- Track preview/cloud resource ownership and cleanup outcomes. Temporary deployment removal requires the appropriate approval and verified removal; failed cleanup must stay visible.

Exit: the same reviewed app has passing hosted CI and a verified deployment, or an explicit actionable deployment blocker. To claim the complete database-app assignment story, complete the persistent deployment path as well.

### Milestone 5 — Live workspace and source viewer (P1)

Build the UI on the shared event envelope rather than reconstructing actions from status strings. Show active parent/child tasks, short decision summaries, current file drafts/diffs, tool spans, test assertions, sources and blockers inline. Reuse the existing SSE/history/context dialog foundation. Preserve readable typography, keyboard access and reduced-motion behavior.

Core event instrumentation starts in Milestone 1; richer presentation follows stable execution. Avoid another polished UI layer that masks missing execution capabilities.

## Evaluation and release gates

Use several app domains with different behavior: calculations, persistent records, related-data operations, and a rule-based non-CRUD workflow. Include held-out natural-language requests. Domain fixtures belong in evaluation data; production code must not recognize those app names to succeed.

For each case, record: requirement coverage, design coherence, enum/reference completeness, route-file consistency, fixture lifecycle, first-pass build/API result, repair count, browser coverage, persistence result, manual intervention, actual call/token budgets and duration. Include off-topic requests, ambiguous requests, edits, cancellation and restart recovery.

Run controller regressions, then live-model planning evaluations, then isolated generated-app execution. Green mocked tests are necessary regression evidence but insufficient generation evidence. Do not ask the user to repeatedly discover basic pipeline defects during a demonstration.

A complete demonstration should be replayable from requirement to final evidence, with clear agent roles and real tool records. Limit the claim to evaluated supported capabilities rather than promising every possible application.

## Tomorrow's starting point

Start with Milestone 1 and the intent-routing contract. Agree the typed design and task/event envelope, migrate the architect/acceptance handoff, and replay the saved route/interface/fixture failures. Add live planning evaluation before another full user-driven build. Continue to generation and tools once this checkpoint is stable; do not force all milestones into one session.

This session ends with planning only. Runtime code remains unchanged. Implementation starts in the next development session, incorporating the user's review and priorities.
