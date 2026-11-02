# ForgeFSD

A local-first proof of concept for agent-assisted full-stack development, built with **Python, LangGraph, LangChain and Ollama**.

The assignment explores how agents can gather requirements, plan an application, delegate work, inspect real test results, review failures and iterate. Generated apps use **Next.js, React and TypeScript**, with **SQLite** for supported local persistence workflows. Docker isolates application execution from the controller.

**Status — 2 November 2026:** the core components and local dashboard are implemented. A newer autonomous coordinator is being integrated incrementally. It is **not yet a single, fully verified request-to-deployment workflow through the dashboard**. The distinctions below are intentional.

## What is built

| Component | Current capability |
| --- | --- |
| Requirements and planning | Local-model intake, clarification and reviewable application proposals. The newer planner lets agents choose app-specific structure and types within workspace/tool boundaries. |
| Task coordination | LangGraph orchestration, persistent task ownership/revisions, dependency invalidation and saved observations in SQLite. |
| Agents and subagents | Planner, builder, QA diagnosis and senior-review roles with recorded handoffs and model calls. These are separate role invocations using the same local model, not separately trained models. |
| Source tools | Scoped reads, complete-file writes and exact-text patches, guarded by ownership and file/workspace hashes. Models cannot select arbitrary host paths or shell commands. |
| Repair | Real failure evidence, QA diagnosis, senior-review escalation, alternative edit strategies and resumable resource pauses. Changed source is rechecked before old diagnostics can justify edits. |
| Verification | Isolated TypeScript and production builds. The earlier app workflow also has approved HTTP scenarios and applicable SQLite/restart checks. Browser coverage is explicit and profile-specific. |
| Dashboard | Local FastAPI API with React/Vite UI, live activity summaries, context inspection, plan approval, reports, source export, preview controls, run deletion/trash and dark mode. |
| Generated-app release | CI/deployment roles prepare policy-controlled release bundles. GitHub publishing and stateless Vercel deployment require separate approvals and credentials. |

Activity displays expose recorded handoffs, tool calls, source changes, model inputs/outputs and test evidence. They do not expose private model reasoning. Model-driven web browsing is not implemented.

## Two execution paths

**Existing dashboard workflow:** uses the earlier typed-planning pipeline, with human plan approval, generation, verification, bounded repairs and separate preview/release controls. It has known planning/model limitations. It does not yet use the newer autonomous coordinator by default.

**New autonomous path:** choose **Autonomous app workflow · experimental** in the dashboard. Agents clarify the request and propose their design. You can approve, decline or request changes; approval then starts delegated source generation, repair and isolated build checks. Saved resource pauses resume in the same job. Independent app-specific behavior checks, preview and release integration remain pending for this path. Controlled repair evaluations already exercise independent browser checks.

The intended flow is:

```text
Request -> requirements/clarification -> agent-authored plan -> human review
        -> delegated implementation -> independent checks -> repair/review loop
        -> approved preview -> generated-app CI -> separately approved deployment
```

This diagram describes the target integration; the two paths above describe what currently runs.

## Verified checkpoints

Latest local controller suite: **326 Python tests passed**. These use fake agents, temporary databases and mocked external services; they do not establish local-model accuracy. Dashboard TypeScript and production build also pass.

Separate live evaluations used the installed **qwen2.5-coder:7b**, real Docker builds and Chromium:

| Evaluation | Observed result |
| --- | --- |
| Previously failing calculator fixture | Model repairs reached passing TypeScript and production build. Its application behavior remains unverified. |
| Counter repair fixture | Initial component-contract failure; model repairs reached passing build and 2/2 browser assertions, including repeated increments by one. |
| Formatter repair fixture | Initial build passed but both browser assertions failed on lowercase output; one model repair reached passing build and 2/2 assertions. |
| Fresh counter planning and generation | Internal evaluation approved an agent-authored proposal; model-generated source reached passing TypeScript and production builds in 14 model calls. Behavior was not tested. |
| Dashboard counter with review feedback | Consent, same-job revision and restart/resume worked. Generation remained paused after repeated client-directive repair failures; no working-app claim. |

The counter and formatter start from **deliberately faulty, controller-authored test fixtures**. They evaluate repair, not autonomous generation from a fresh request. Their frozen browser assertions run in a separate container and cannot be edited by the builder. All source corrections after fixture setup came from model tool calls.

Results are tied to source/harness fingerprints and immutable image IDs. These small evaluations do not establish general coding reliability, unrestricted app support or production security. Detailed evidence and limitations are in [implementation checkpoints](docs/autonomous-implementation.md).

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

## Run the dashboard

After setup, double-click **Start-ForgeFSD.cmd**, or run:

```powershell
.\.venv\Scripts\python.exe -m forge.dashboard
```

Open [http://127.0.0.1:8787](http://127.0.0.1:8787). Describe a small app, inspect the proposed requirements and acceptance checks, then approve the plan before generation. Preview and publishing/deployment have separate approvals.

The **Planning workflow** selector defaults to **Existing app workflow**. Choose **Autonomous app workflow · experimental**, open **Review design proposal**, and inspect the design before checking consent and choosing **Approve & build**. **Request changes** returns feedback through requirements intake and creates a new review snapshot; earlier consent cannot authorize a revised proposal. **Decline plan** stops before generation.

Routine source repairs run without repeated approval. **Resume saved build** grants eight additional dispatches while retaining completed source and the original approval; interrupted in-flight work still needs inspection. A **Build checks passed** result covers TypeScript and the production build only. It does not establish correct app behavior or readiness for preview/deployment. Changed source is shown as stale evidence.

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
```

These use real local inference, Docker builds and browser interactions. The scripts save initial failures, task/model/tool traces, final source and reports under `artifacts/repair-regressions/`, then remove disposable fixture workspaces, containers and networks. They publish no host preview ports or cloud deployments. A failed or paused evaluation exits nonzero; inspect the saved evidence rather than treating a pause as success.

## Run automated tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pip check
npm --prefix apps/web run build
```

Python tests and dashboard checks are separate from the live model evaluations. Runtime artifacts, historical runs, model weights, generated workspaces and local environment files are excluded from Git. A fresh clone does not include previous run evidence; use the reproduction commands to create new evidence.

## CI, deployment and safety boundaries

Generated applications have their own CI/deployment preparation path; see [generated-app CI/CD](docs/generated-app-cicd.md). A previous stateless converter completed a one-time CI/Vercel test; the temporary deployment and credentials were removed. That historical result does not verify the new autonomous path.

ForgeFSD's own hosted workflow is paused/manual-only. Generated-app CI is a separate capability. Local verification remains available.

Local SQLite is supported in applicable app workflows. **Remote database provisioning/adapters and SQLite-backed Vercel deployment are not implemented.** Stateless deployment needs an existing Vercel project, repository secrets and separate approval. Never commit credentials or place them in model prompts; generated code receives neither controller credentials nor the Docker socket.

The earlier pipeline includes limited static, dependency, secret-pattern and prompt-injection checks. Coverage is incomplete and is not a production security certification. Its preview stage also needs the configured scanner tools and audit access; see [security/preview setup](docs/security-preview-milestone.md). No external security-service signup is needed for the planning and repair demos above. Those demos do not bypass or satisfy the older preview security gates.

## Remaining work

1. Add independent app-specific behavior checks to approved autonomous generation, then verify a fresh request-to-app run without manual source corrections.
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
| `src/forge/tasks.py`, `coordinator.py`, `senior_review.py` | Durable delegation, revisions, recovery and review |
| `src/forge/source_agent.py`, `workspace_tools.py` | Model-proposed source edits and scoped tools |
| `src/forge/source_checks.py`, `repair_fixture_browser.py` | Isolated build checks and controlled browser evaluations |
| `src/forge/dashboard.py`, `apps/web/` | Local API and React/Vite dashboard |
| `src/forge/releases.py` | Generated-app CI/CD preparation and approved release operations |
| `templates/`, `tests/` | Locked app scaffold, trusted checks and regression fixtures |

Start with [implementation checkpoints](docs/autonomous-implementation.md) and the [autonomous POC plan](docs/autonomous-poc-plan.md). Earlier milestone notes document the evolution, including failed trials and developer-corrected apps; they are historical evidence, not guarantees about the current path. See also [dashboard architecture](docs/dashboard-milestone.md), [generated-app CI/CD](docs/generated-app-cicd.md) and the [earlier demo walkthrough](docs/demo-walkthrough.md).
