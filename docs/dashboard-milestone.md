# Live agent dashboard milestone

## Delivered

React/TypeScript/Vite UI, served by the local FastAPI control plane. Open through
`Start-ForgeFSD.cmd` or `python -m forge.dashboard`. Host binding is fixed to 127.0.0.1;
the default port is 8787. Reopening the launcher reuses a recognized existing service.

The normal user flow is:

1. Describe the supported task-management application.
2. Watch saved Requirements and Architect activity appear live.
3. Answer clarification questions when required.
4. Review requirements, assumptions and the exact plan revision.
5. Approve & build, or decline. Approval starts the controlled generation/check pipeline.
6. Inspect failed checks and the bounded repair history, not just the latest success.
7. Inspect security reports, including separate model/policy prompt-attack outcomes.
8. Separately approve local preview; open, stop or refresh its status through the UI.
9. Download source and read readiness reports.

No cloud publishing or database credentials are requested in this milestone.

## Code boundaries

| Module | Responsibility |
| --- | --- |
| `apps/web/src/App.tsx` | Request/review forms, agent roster, activity, report views and preview controls |
| `apps/web/src/style.css` | Responsive layout, accessibility states and visual presentation |
| `src/forge/api.py` | Local session, typed actions, event stream, safe reports and source download |
| `src/forge/operations.py` | Durable operation records, deduplication, one-worker lock, cancellation and budgets |
| `src/forge/dashboard_worker.py` | Calls the existing workflow stages in a subprocess; never fabricates outcomes |
| `src/forge/dashboard.py` | Local launcher, service reuse and graceful shutdown |

HTTP requests start a managed operation and return promptly. The job runs outside the
request lifetime. Server-sent events replay from sequence IDs, with heartbeat/reconnect
support; a periodic snapshot refresh also reconciles operation state. UI progress is
derived from actual persisted events, not artificial percentages or token animations.

The worker calls the same tested LangGraph agents/subgraphs and deterministic controllers
as the CLI. It stops at human decisions, does not skip failed verification, and cannot
start preview as a side effect of plan approval. The pipeline's repairs remain limited
to two, with the documented template fallback. Preview remains a separate approval.

## Local security controls

- Same-origin UI/API, localhost host validation, no permissive CORS.
- HttpOnly SameSite session cookie and a separate mutation token.
- Cross-origin requests, including those from the generated app's other localhost port,
  are rejected. CSP blocks embedding the dashboard in an untrusted page.
- Only enumerated actions; bounded descriptions/answers and request sizes.
- Source downloads exclude environment secrets, local data and dependency/build folders.
  Traversal/linked paths are rejected. Downloads wait for an active operation to finish.
- Reports are addressed by job event sequence, not arbitrary user-supplied paths; their
  resolved paths must stay under the artifact directory.
- Exact-revision review fingerprints and expected event sequences prevent stale actions.
- One worker operation at a time. Workers have a 30-minute budget and capped log output.
  Cancel terminates the owned process tree and cleans only matching labeled containers.
- Unexpected worker exit does not leave the job misleadingly marked as running.
- Python lockfile changes invalidate preview eligibility until the audit is refreshed.

This is a single local user's control plane, not multi-user account authentication.
The session is intentionally local and memory-resident; it is not suitable for exposing
the API on a network. The launcher never offers a public host binding.

## Actual verification

- React TypeScript check and Vite production build passed.
- The full regression run passed 69 tests before the service-reuse addition. The new
  launcher test and affected API checks also passed (12 tests). Existing dependency
  deprecation warnings remain visible, rather than suppressed.
- API tests cover local sessions, CSRF, hostile origins/hosts, duplicate submissions,
  current approval fingerprints, explicit preview consent, report path boundaries,
  source archive filtering, shutdown and event cursor replay.
- Worker tests use owned short-lived Python processes to verify one-worker locking,
  cancellation, deduplication, stale actions, normal completion and unexpected exit.
- Pipeline tests verify that failed checks cannot bypass the two-repair budget and
  that preview cannot start without its separate human approval.
- Dashboard npm audit reported zero advisories. The Python lockfile was updated for
  FastAPI/Uvicorn; the existing generated app's full security checks were refreshed and
  passed their configured gates. This is bounded scanner coverage, not proof of security.

Browser QA opened the real local dashboard, inspected the saved app, displayed security
reports and all five model-followed/policy-denied outcomes, submitted a new smoke-test
request through the form, watched agent activity, and observed PLAN_REVIEW. The new
smoke-test plan was not approved by automation. Browser QA also exercised the close
confirmation, graceful shutdown, reopening and saved history. Desktop layout was checked
for horizontal overflow; the normal narrow browser layout was visually inspected.

The existing task app's previously granted preview approval was reused for its unchanged
source revision. Preview startup through the dashboard completed, both local smoke routes
returned 200, and the Readiness Agent saved a new report. The dashboard visibly showed
PREVIEW_RUNNING and the app link. No new smoke-test plan approval or cloud action occurred.
The final browser screenshot is `artifacts/dashboard/dashboard.jpg`.

Evidence is local under `artifacts/dashboard`, `artifacts/test-results/dashboard.xml`,
and the job event/operation tables. Development smoke-test history remains inspectable.

## Remaining limitations

- The 3B model still invents or contradicts prose requirements. Human review is required;
  schema validation alone cannot establish semantic correctness. Compare a stronger local
  model before treating arbitrary new requests as reliable generation.
- The original generated app's browser form/API description-validation mismatch remains
  disclosed. HTTP acceptance tests do not replace browser interaction tests.
- Forceful server crashes are not fully reconciled: operations are marked interrupted,
  but an orphaned worker may require developer inspection. Do not run multiple servers
  against the same job database, or mix CLI operations with dashboard work.
- Ollama may finish an already submitted inference after its client worker is cancelled.
- Development prerequisites and dependency-image provisioning are still one-time setup,
  not an automatic installer. Missing prerequisites must be resolved by the developer.
- Raw diagnostic views are available for developers, but ordinary controls use readable
  labels. There is no multi-user access control, remote PostgreSQL adapter, GitHub CI or
  Vercel deployment yet.
