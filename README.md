# ForgeFSD

A local-first proof of concept for agent-assisted full-stack development, built with **Python, LangGraph, LangChain and Ollama**.

New autonomous jobs can also opt into **Groq GPT-OSS 20B or 120B**. The controller remains
local; hosted inference sends requirements, source context and diagnostics to Groq.
Ollama remains the default and existing jobs retain their saved model.

An explicit **Hybrid · 7B first + Groq assistance** option is available for new autonomous
jobs. Routine intake, generation and QA start locally. Planning, independent quality
review and senior review use Groq; invalid output or repeated lack of progress can
escalate a task revision. Each routing decision is recorded against its current
handoff. Provider limits pause work rather than silently switching providers.

The assignment explores how agents can gather requirements, plan an application, delegate work, inspect real test results, review failures and iterate. Generated apps use **Next.js, React and TypeScript**, with **SQLite** for supported local persistence workflows. Docker isolates application execution from the controller.

**Status — 4 November 2026:** the autonomous coordinator and dashboard support reviewed generation, independent browser checks, repair and separately approved local preview. Verified stateless apps can now prepare generated-app CI/deployment bundles; a generated counter has completed publishing and hosted build/homepage-smoke CI at its exact approved commit. It is **not yet a single, fully verified request-to-deployment workflow through the dashboard**.

## What is built

| Component | Current capability |
| --- | --- |
| Requirements and planning | Local-model intake, clarification and reviewable application proposals. The newer planner lets agents choose app-specific structure and types within workspace/tool boundaries. |
| Task coordination | LangGraph orchestration, persistent task ownership/revisions, dependency invalidation and saved observations in SQLite. |
| Agents and subagents | Planner, builder, QA diagnosis, test-quality, requirements-scope and senior-review roles with recorded handoffs and model calls. These are separate role invocations using the selected model or explicit hybrid policy, not separately trained models. |
| Source tools | Scoped reads, complete-file writes and exact-text patches, guarded by ownership and file/workspace hashes. The autonomous Ollama writer separates raw code from structured target metadata to preserve JSX quotes. Runtime/API references and snapshot-based import diagnostics support repairs. Models cannot select arbitrary host paths or shell commands. |
| Repair | Real failure evidence, QA diagnosis, senior-review escalation, alternative edit strategies and resumable resource pauses. Changed source is rechecked before old diagnostics can justify edits. |
| Verification | Isolated TypeScript and production builds. The earlier app workflow also has approved HTTP scenarios and applicable SQLite/restart checks. The autonomous path freezes requirements-derived browser assertions outside app source, executes them separately and feeds failures into repair. Supported scenarios can run with explicit coverage gaps; those gaps still prevent a complete pass. Database restart is not part of this browser protocol. |
| Test quality | New suites must observe action results and challenge reload behavior with meaningful state. A separate critic reviews covered requirements; requirements-scope review separates grounded blockers from optional suggestions. Reviews are bound to the exact proposal and revision. Model judgments remain fallible. |
| Dashboard | Local FastAPI API with React/Vite UI, live activity summaries, context inspection, plan approval, reports, source export, preview controls, run deletion/trash and dark mode. |
| Generated-app release | CI/deployment roles prepare policy-controlled release bundles. GitHub publishing and stateless Vercel deployment require separate approvals and credentials. |

Activity displays expose recorded handoffs, tool calls, source changes, model inputs/outputs and test evidence. They do not expose private model reasoning. Model-driven web browsing is not implemented.

## Two execution paths

**Existing app workflow:** the earlier typed-planning pipeline remains selectable for compatibility, with human plan approval, generation, verification, bounded repairs and separate preview/release controls. It has known planning/model limitations.

**Autonomous path (dashboard default):** agents clarify the request and propose their design. You can approve, decline or request changes; approval then starts delegated source generation, build checks, independent acceptance QA and repair against frozen browser assertions. QA receives the approved requirements/design without generated source. Its proposed suite passes structural checks and separate test-quality/scope review before freezing. Saved build and QA resource pauses resume in the same job. Unsupported criteria block a complete app-check pass; available scenarios can still execute and produce current, explicitly partial evidence. A complete current pass enables a separately approved, localhost-only preview with disposable data and a 30-minute lifetime. This does not claim security audits or cloud readiness. Verified stateless apps can prepare a release bundle through CI/deployment roles. Its hosted CI scope is TypeScript, production build and homepage HTTP smoke; it does not replay the frozen browser suite. SQLite release adaptation remains pending.

The intended flow is:

```text
Request -> requirements/clarification -> agent-authored plan -> human review
        -> delegated implementation -> independent checks -> repair/review loop
        -> approved preview -> generated-app CI -> separately approved deployment
```

This diagram describes the target integration; the two paths above describe what currently runs.

## Verified checkpoints

Latest complete controller checkpoint: **587 Python tests passed** (13 upstream deprecation warnings). Subsequent release/provider changes passed focused regression selections; see implementation checkpoints for their scope. These use fake agents, temporary databases and mocked external services; they do not establish model accuracy. A separate live hybrid counter completed intake, planning, approved generation, build, independent QA and repair: all five criteria passed a ten-step frozen browser scenario, and the final evidence matched current source. That run used five local calls, six Groq calls and eleven saved handoffs, with no manual app-source corrections. The SQLite notes app now passes its build and both frozen browser scenarios (add/list/delete, invalid title and reload persistence). One approved SQLite-file-location criterion remains explicitly uncovered, so its dashboard status is partial coverage rather than a complete pass. The counter additionally passed local preview interaction checks and generated-app hosted build/homepage-smoke CI. Eleven Node tests cover framework diagnostics, the browser protocol and failure evidence. Dashboard TypeScript and production build also pass.

Separate live evaluations used the installed **qwen2.5-coder:7b**, real Docker builds and Chromium:

| Evaluation | Observed result |
| --- | --- |
| Previously failing calculator fixture | Model repairs reached passing TypeScript and production build. Its application behavior remains unverified. |
| Counter repair fixture | Initial component-contract failure; model repairs reached passing build and 2/2 browser assertions, including repeated increments by one. |
| Formatter repair fixture | Initial build passed but both browser assertions failed on lowercase output; one model repair reached passing build and 2/2 assertions. |
| Fresh counter planning and generation | Internal evaluation approved an agent-authored proposal; model-generated source reached passing TypeScript and production builds in 14 model calls. Behavior was not tested. |
| Dashboard counter with review feedback | Consent, same-job revision and restart/resume worked. Generation remained paused after repeated client-directive repair failures; no working-app claim. |
| Next.js client-boundary repair fixture | After the repair-loop fixes, the same 7B model corrected the directive and moved metadata to the server layout. Real build and 4/4 frozen browser assertions passed in 8 model calls. |
| Fresh counter with independent QA | Reviewed model-generated source eventually passed build and 2/2 requirements-derived browser scenarios, including reload reset. This recovered evaluation required coverage re-evaluation and several saved repair resumes; it was not a one-shot success. No manual app-source corrections. |
| Dashboard-led character counter | UI request, two review revisions, approval, generation, build repair, independent QA and saved-check resume reached 4/4 browser scenarios. Planner-context and diagnostic fixes were required. The reload scenario clears first, so persistence of nonempty text is not established. |
| Dashboard-led SQLite notes | Runtime references removed the unavailable-ORM blocker; raw source produced complete JSX. Build repair still repeated incorrect imports/client-boundary edits despite current source and diagnostic facts. Cycle checks rejected repeated failed source; the job was archived paused. No build, behavior or persistence pass is claimed. |

The counter and formatter start from **deliberately faulty, controller-authored test fixtures**. They evaluate repair, not autonomous generation from a fresh request. Their frozen browser assertions run in a separate container and cannot be edited by the builder. All source corrections after fixture setup came from model tool calls.

Results are tied to source/harness fingerprints and immutable image IDs. These small evaluations do not establish general coding reliability, unrestricted app support or production security. Detailed evidence and limitations are in [implementation checkpoints](docs/autonomous-implementation.md).

Handoffs validate task revisions and source fingerprints. Changed source is rechecked before senior review; review results are rejected if artifacts change during generation. QA-to-builder handoffs revalidate the task, approval, runtime and source after diagnosis returns. Regression tests exercise these races and reopening a saved pause. Historical records remain available for audit without being treated as current repair evidence.

## Requirements

The current development environment targets **Windows with PowerShell**, **Python 3.14**, **Node.js 24 with npm**, **Docker Desktop running Linux containers**, and **Ollama** listening at `http://127.0.0.1:11434`.

- Use `qwen2.5-coder:7b` for the newer planning and repair evaluations. The older CLI also supports a 3B model and some older commands still default to it.
- Local inference and Docker builds require sufficient memory and disk space; runtime depends on the machine.
- Initial package/image/model provisioning needs internet access. Unit tests do not require Docker or Ollama; live evaluations require both. Browser evaluation traffic stays on an internal Docker network.
- GitHub CLI authentication and Vercel credentials are optional release prerequisites, not required for local planning or repair demonstrations.

## Setup

From PowerShell:

```powershell
git clone https://github.com/Shahid0324-GIT/forge-fsd.git
cd forge-fsd
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
npm --prefix apps/web ci --ignore-scripts
npm --prefix apps/web run build
```

Use the committed lockfiles. The dashboard build includes its TypeScript check. Provision the existing fixed dependency images once:

```powershell
docker build --file templates/task-app/Dockerfile.dependencies --tag forge-task-deps:local templates/task-app
docker build --tag forge-browser-deps:local tests/browser
```

The second image includes Chromium and is needed for browser evaluations. These build commands download dependencies; evaluation runs use existing images with `--pull=never`.

Check the installed local model:

```powershell
ollama list
```

If the required model is absent, install it explicitly; this is a model download, not a dependency of the unit tests:

```powershell
ollama pull qwen2.5-coder:7b
```

### Optional Groq setup

To select a second local credential, set `FORGE_GROQ_KEY_NAME=GROQ_API_KEY_1`
in the environment or ignored `.env.local`, alongside that credential. The default
slot is `GROQ_API_KEY`. Selection is explicit: a missing selected key fails before
inference, and quotas never trigger automatic key rotation. Environment values
override the file for the same slot. Rate-limit receipts are isolated by model
and credential; separate keys may still share Groq account quotas.

Create an API key in [Groq Console](https://console.groq.com/keys), copy
[.env.example](.env.example) to `.env.local` and replace the placeholder locally.
Never commit or paste the key into chat. Alternatively set `GROQ_API_KEY` in the
controller's environment. No extra package, model download or lockfile change is needed.

Refresh the dashboard, choose **Autonomous app workflow · experimental**, then
**Hosted · Groq GPT-OSS 20B** (or 120B), or **Hybrid · 7B first + Groq assistance**.
Hybrid also requires the installed `qwen2.5-coder:7b` model. These are explicit choices for a new job; saved Ollama
jobs are not silently switched. Groq availability, account rate limits and credits
apply. The adapter uses best-effort JSON-schema output plus the same local Pydantic
validation and source/build/QA gates; provider output alone is not a pass.

Groq `json_validate_failed` responses are treated as rejected model output, with
one same-role correction against the unchanged schema. They are never accepted
as chat completions or application evidence. Only a bounded JSON candidate is
retained in ignored local model traces; provider error prose is excluded.
Authentication, quota, request-size and invalid-envelope errors remain resource
pauses, so app builders do not try to fix them by editing application code.

## Repeatable autonomous app checks

Run a business-only request through planning, internal evaluation approval,
generation, isolated build and frozen browser checks:

```powershell
python scripts/evaluate_autonomous_flow.py --case notes --model groq:openai/gpt-oss-120b
```

Cases include `counter`, `notes` and `expenses`. The default model is local 7B;
Groq is used only when selected explicitly. The script prints its evidence
directory under `artifacts/autonomous-flow-evaluation`. Resume that exact run with
`--resume <directory>`; its saved model, request and assertions are retained.
Failed runs preserve their workspace under `workspace/.flow-evaluations`.
A pass requires current build/browser evidence and complete frozen coverage, not
just a success status. This is an internal test actor, not human approval,
preview, publication or a claim of general model accuracy.

## Run the dashboard

After setup, double-click **Start-ForgeFSD.cmd**, or run:

```powershell
.\.venv\Scripts\python.exe -m forge.dashboard
```

Open [http://127.0.0.1:8787](http://127.0.0.1:8787). Describe a small app, inspect the proposed requirements and acceptance checks, then approve the plan before generation. Preview and publishing/deployment have separate approvals.

The **Planning workflow** selector defaults to **Existing app workflow**. Choose **Autonomous app workflow · experimental**, open **Review design proposal**, and inspect the design before checking consent and choosing **Approve & build**. **Request changes** returns feedback through requirements intake and creates a new review snapshot; earlier consent cannot authorize a revised proposal. **Decline plan** stops before generation.

Routine source repairs run without repeated approval. **Resume saved build** grants eight additional dispatches while retaining completed source and the original approval; interrupted in-flight work still needs inspection. A **Build checks passed** result covers TypeScript and the production build only. It does not establish correct app behavior or readiness for preview/deployment. Independent QA follows a successful build automatically. Older build-only runs can use **Check app behavior**. **Resume app checks** retains frozen assertions and saved source. A **Selected app checks passed** result covers those assertions only; changed source, contracts or evidence are marked stale. Unsupported requirements remain visible as blocked coverage. **Re-evaluate test coverage** creates a separate QA revision and preserves the previous contract; fresh app checks are required before a new pass.

Run one dashboard process and avoid concurrent CLI/evaluation operations. Closing a tab does not cancel its managed operation; use the dashboard controls to stop work or close the workspace. Interrupted dispatches need inspection and cannot be blindly replayed through the resume button.

## Reproduce the newer agent demonstrations

Run these while no dashboard operation is active.

### Agent-authored planning

```powershell
.\.venv\Scripts\python.exe -m forge --db artifacts/autonomous-demo.sqlite3 autoplan "Build a small tip calculator with a bill, tip percentage and party size. No saved data." --model qwen2.5-coder:7b
```

This produces a reviewable design proposal, not a built application. For a saved resource pause or genuine clarification request:

```powershell
.\.venv\Scripts\python.exe -m forge --db artifacts/autonomous-demo.sqlite3 autoplan-resume JOB_ID --additional-actions 8
.\.venv\Scripts\python.exe -m forge --db artifacts/autonomous-demo.sqlite3 autoplan-answer JOB_ID --answer "Your answer to the pending question"
```

Inspect interrupted dispatch outcomes before claiming they are reconciled. Resource pauses preserve history; a model reviewer cannot declare failed tests successful or bypass approval.

### Repair with independent browser checks

```powershell
.\.venv\Scripts\python.exe scripts/evaluate_repair_regressions.py --case formatter
.\.venv\Scripts\python.exe scripts/evaluate_repair_regressions.py --case counter
.\.venv\Scripts\python.exe scripts/evaluate_repair_regressions.py --case client-boundary
```

These use real local inference, Docker builds and browser interactions. The scripts save initial failures, task/model/tool traces, final source and reports under `artifacts/repair-regressions/`, then remove disposable fixture workspaces, containers and networks. They publish no host preview ports or cloud deployments. A failed or paused evaluation exits nonzero; inspect the saved evidence rather than treating a pause as success.

### Independent acceptance QA and runner calibration

```powershell
.\.venv\Scripts\python.exe scripts/evaluate_acceptance_protocol.py
.\.venv\Scripts\python.exe scripts/evaluate_approved_build.py --app-checks
```

The first command uses fixed correct/incorrect fixtures to check that the runner accepts
valid behavior and rejects faulty behavior. The second uses actual local-model planning,
an explicit internal evaluation approval, generated source and requirements-derived QA.
Neither command claims actual human approval, a preview or deployment. Artifacts and
source archives are saved locally; disposable workspaces/resources are cleaned up.

QA produces a bounded data-only browser contract using semantic roles, labels and visible
text. Arbitrary JavaScript/selectors and external navigation are unsupported. Contracts are
frozen outside the app workspace and cannot be edited by builders. Coverage references are
QA proposals, not proof that every requirement was interpreted correctly; reports expose
scenarios and uncovered criteria for inspection. The current protocol does not verify
SQLite persistence after restart, security or cloud deployment.

## Run automated tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pip check
npm --prefix apps/web run build
node --test tests/framework-diagnostics.test.mjs tests/browser-protocol.test.mjs tests/browser-diagnostics.test.mjs
```

Python tests and dashboard checks are separate from the live model evaluations. Runtime artifacts, historical runs, model weights, generated workspaces and local environment files are excluded from Git. A fresh clone does not include previous run evidence; use the reproduction commands to create new evidence.

The framework diagnostic tests use the dashboard's locked TypeScript package. Live build checks run static parser diagnostics in the isolated dependency image, alongside the real compiler/build. Diagnostics explain invalid module directives and client/server metadata conflicts; they do not rewrite source or establish app behavior. Repairs that exactly restore a failed workspace in the same task revision are rejected before writing.

## CI, deployment and safety boundaries

Generated applications have their own CI/deployment preparation path; see [generated-app CI/CD](docs/generated-app-cicd.md). A previous stateless converter completed a one-time CI/Vercel test; the temporary deployment and credentials were removed. That historical result does not verify the new autonomous path.

ForgeFSD's own hosted workflow is paused/manual-only. Generated-app CI is a separate capability. Local verification remains available.

Local SQLite is supported in applicable app workflows. **Remote database provisioning/adapters and SQLite-backed Vercel deployment are not implemented.** Stateless deployment needs an existing Vercel project, repository secrets and separate approval. Never commit credentials or place them in model prompts; generated code receives neither controller credentials nor the Docker socket.

The earlier pipeline includes limited static, dependency, secret-pattern and prompt-injection checks. Coverage is incomplete and is not a production security certification. Its preview stage also needs the configured scanner tools and audit access; see [security/preview setup](docs/security-preview-milestone.md). No external security-service signup is needed for the planning and repair demos above. Those demos do not bypass or satisfy the older preview security gates.

## Remaining work

1. Broaden test-quality calibration and dashboard-led SQLite demonstrations. New-suite structural checks and independent test/scope review are implemented; semantic completeness is not guaranteed.
2. Support safe technical design revision when execution reveals a manifest problem, retaining human review for changes to the requested scope.
3. Broaden repair and behavior coverage, including SQLite integrity and persistence after restart through the updated path.
4. Integrate/revalidate generated-app CI and publishing against that path; database-backed cloud deployment remains separate work.
5. Prepare a repeatable assignment walkthrough. Larger UI redesigns, new packages, complex apps and additional deployment targets are deferred.

Current scope is small landing pages, stateless SPAs and supported single-user SQLite apps. Authentication, payments, arbitrary integrations, unrestricted package installation, multi-user production operation and general-purpose autonomous deployment are outside the demonstrated POC.

## Code and documentation

| Location | Purpose |
| --- | --- |
| `src/forge/autonomous_planning.py` | Intake and agent-authored design proposals |
| `src/forge/autonomous_review.py`, `autonomous_build.py` | Immutable plan decisions, approved generation and saved build recovery |
| `src/forge/autonomous_acceptance.py`, `autonomous_testing.py`, `acceptance_browser.py` | Frozen independent QA contracts, app-check repair and isolated browser execution |
| `src/forge/tasks.py`, `coordinator.py`, `senior_review.py` | Durable delegation, revisions, recovery and review |
| `src/forge/source_agent.py`, `workspace_tools.py` | Model-proposed source edits and scoped tools |
| `src/forge/source_checks.py`, `repair_fixture_browser.py` | Isolated build checks and controlled browser evaluations |
| `src/forge/dashboard.py`, `apps/web/` | Local API and React/Vite dashboard |
| `src/forge/releases.py` | Generated-app CI/CD preparation and approved release operations |
| `templates/`, `tests/` | Locked app scaffold, trusted checks and regression fixtures |

Start with [implementation checkpoints](docs/autonomous-implementation.md) and the [autonomous POC plan](docs/autonomous-poc-plan.md). Earlier milestone notes document the evolution, including failed trials and developer-corrected apps; they are historical evidence, not guarantees about the current path. See also [dashboard architecture](docs/dashboard-milestone.md), [generated-app CI/CD](docs/generated-app-cicd.md) and the [earlier demo walkthrough](docs/demo-walkthrough.md).

### Explicit Claude recovery

Claude is an opt-in recovery provider, not part of the automatic hybrid fallback. Save `ANTHROPIC_API_KEY` in ignored `.env.local`; the currently supported recovery model is `anthropic:claude-opus-5-5`. No additional SDK or dependency installation is required. Recovery workers without an approved run budget share an allowance of four requests across model copies, with at most 3,000 output tokens per request and no automatic HTTP retries. This is a request allowance, not a monetary spending limit; restarting a worker creates a new allowance.

The operator can propose and explicitly approve an inference change only at a saved idle build/QA pause using `forge.execution_models`. Approval binds the current plan, source fingerprint, task revision and version. The original approved plan and frozen test contract keep their recorded model identity. This advanced recovery control is not yet a dashboard model-switch button. Normal dashboard creation defaults and the local-first hybrid policy remain unchanged.

Browser scenarios now run in separate app containers with fresh temporary databases. Reloads within a scenario retain that scenario's data. This prevents fixtures from one case contaminating another. Reports aggregate every frozen case and verify each child report's hash, source, harness and images. The last full Python checkpoint passed 587 tests; the subsequent isolation/recheck selection passed 17 checks and both live app verifications passed their supported assertions.


### Fresh Claude-only demo with a run allowance

The autonomous dashboard now offers **Claude · Opus 5.5 · $3 run budget**. Creating its plan explicitly authorizes an application-side $3 API allowance; approving source generation is still a separate decision. Prompts, generated source and diagnostics are sent to Anthropic. The allowance persists in the run database across role changes, retries and worker restarts. It reserves a conservative maximum before each request, settles known usage and retains full reservations when usage is uncertain. The dashboard shows used/reserved cost. A request that does not fit pauses before contacting the provider.

This guard uses the verified Opus 5.5 base rates of $4/M input and $20/M output tokens, conservatively accounting for possible cache usage. It is not an Anthropic account billing limit and excludes taxes. Pricing changes require reviewing the guard. Earlier recovery runs without an explicitly approved run allowance retain their four-request worker limit. No existing run or generated application is changed by selecting Claude for a fresh run.
