# ForgeFSD

Local-first agentic full-stack development POC using LangGraph, LangChain and Ollama.

Generated applications have their own CI/deployment agents and separate review,
publish and deploy controls. See [generated-app CI/CD](docs/generated-app-cicd.md).
The badge below checks Forge itself; it is not evidence of a generated app's CI.

The converter completed a separate app CI and one-time Vercel deployment test.
Its live API/browser checks passed, then the deployment, test project and temporary
credentials were removed. The generated-app CI/CD guide retains the workflow links
and describes the local evidence and remaining database-deployment limitations.

[![ForgeFSD checks](https://github.com/Shahid0324-GIT/forge-fsd/actions/workflows/ci.yml/badge.svg)](https://github.com/Shahid0324-GIT/forge-fsd/actions/workflows/ci.yml)

The repository is private. Hosted CI checks Windows/Ubuntu controller tests and
dashboard builds, plus the fixed converter browser calibration on Linux. See
[CI runs](https://github.com/Shahid0324-GIT/forge-fsd/actions) for current results.
Saved local jobs, model weights and runtime evidence are excluded from Git; a fresh
clone starts without the historical demonstration runs described in the milestone notes.

## Current milestone: general small-app workflow (experimental)

**Normal use no longer needs terminal commands.** Double-click `Start-ForgeFSD.cmd`
to open the local dashboard at http://127.0.0.1:8787. If it is already running, the
launcher reopens the existing workspace. Use **New application** to describe a small
app, choose the installed 3B or 7B model, answer questions, review the plan and its
acceptance checks, and select **Approve & build**. The controlled
pipeline then generates, verifies, attempts bounded repairs, audits and prepares reports.
Starting the generated app preview requires a separate checkbox approval.

The dashboard includes a live event stream, agent activity, requirements/plan review,
test/security reports, source ZIP download, preview start/stop and a workspace-close
control. The control plane is local-only. Generated-app publishing uses GitHub CLI;
stateless Vercel deployment needs separate approval and project secrets.
The main workspace shows recent agent actions, validation corrections and expandable
handoffs inline, with larger text and separate tabs for detailed history and evidence.
These are recorded activity summaries, not private model reasoning. New dashboard runs
default to the installed 7B option; CLI/API defaults and existing jobs are unchanged.
Planning retries send the rejected proposal and a concise validation error back to the
model for one bounded correction. Invalid proposals still stop before human approval;
this recovery path does not guarantee that a local model will produce a valid plan.
Builder corrections likewise receive the rejected source and concrete import/boundary
errors. Client-side SQLite imports remain rejected, including files that already declare
`"use client"`; correcting an import path does not make a database module browser-safe.
Users supply the app idea and functionality. New planning runs classify the request,
then create a typed business brief, business operations, UI/helper layout and independent
acceptance recipes. One compiler derives HTTP routes, Next.js files and shared TypeScript
interfaces from those decisions. The HTTP profile uses GET for entity reads/lists and
JSON POST for mutations; custom operations support calculations and domain rules.
Builders cannot edit the controller-rendered interface file. Legacy approved runs retain
their saved plans; a failed checkpoint without a typed brief must start a fresh plan.
New typed planning uses deterministic consistency checks and bounded corrections rather
than same-model advisory reviewers as its correctness gate. Test design precedes code;
actual application checks run after generation. Human approval remains required.

Model-call inspection records the actual prompts, schema, output and metadata, linked
to the saved handoff and parent task. Help and unrelated requests end without building
an app. No web browsing or model-driven execution tools have been added by this milestone.
See [typed planning implementation](docs/typed-planning-milestone.md) for validation,
remaining work and limits. This remains experimental: valid contracts alone do not
establish complete requirement coverage or successful generated-app execution.

**Test planning happens before building; test execution happens afterward.** The acceptance
planner defines the expected behavior from the request and API contract, independently of
generated code. Its reviewer checks coverage, response shapes and fixture lifecycles,
including data remaining for restart checks. After approval and generation, the Docker
runner executes application checks and returns failures to the repair workflow. Existing
approved runs are not silently rewritten by these new planning reviews.
The top bar offers **System theme**, **Light mode**, and **Dark mode**; the browser
remembers your choice. New version-2 plans support different single-user app domains,
up to five static pages, three data entities and twelve generated source files.
SQLite persistence or a stateless app is supported. Authentication, payments, external
services and additional dependencies require further implementation; the agents
should clarify those requests instead of silently reducing them to task CRUD.
This is experimental: full generated-app evaluation across multiple domains is
still in progress. Older version-1 task runs retain their existing execution path.
The local 7B model needed substantial developer corrections in the inventory trial.
Passing gates for that corrected app does not establish autonomous coding reliability.
Use **Delete run** in a run's header at any stage to stop its work/preview and hide it
in **Trash · deleted runs**. Source, reports and checkpoints are retained for restoration;
this does not reclaim their disk space. Restoring interrupted work does not restart it.
Your source and event history survive closing the page. Temporary preview data does not
survive stopping the preview.

### One-time developer setup for the dashboard

After the Python setup below, from the repository directory:

```powershell
npm --prefix apps/web ci --ignore-scripts
npm --prefix apps/web run build
.\.venv\Scripts\python.exe -m forge.dashboard
```

The FastAPI process serves the built React/Vite assets and API on one origin. Run one
dashboard process, not multiple Uvicorn workers. Jobs run in managed subprocesses and
continue through a page refresh. A single global operation lock protects local resources;
duplicate request IDs are idempotent and stale action views are rejected. CLI tools remain
available for development, but do not run them concurrently with dashboard operations.

Actions require a local browser session and CSRF token. Foreign origins, including a
generated app's separate localhost port, cannot operate the control API. The API never
accepts arbitrary shell commands, filesystem roots or model providers from the UI.
**Close workspace** gracefully stops active workers/previews. After a forceful process
crash, interrupted work needs developer inspection; this is not production crash recovery.

See [dashboard architecture and verification](docs/dashboard-milestone.md).
See [general small-app architecture and evidence](docs/general-app-workflow.md).
See [inventory evaluation and model limitations](docs/inventory-milestone.md).
See [agent handoffs, saved context and focused repair](docs/agent-context-milestone.md).
See [assignment demo walkthrough](docs/demo-walkthrough.md).
See [temperature converter evaluation and generation recovery](docs/converter-milestone.md).
See [automated browser checks and prepared CI](docs/browser-ci-milestone.md).

For the temperature-converter demo, **Test app in browser** runs a fixed Chromium
profile and saves per-case evidence. Provision its separate test image once using
the browser/CI guide above. Other app domains still need their own reviewed browser
profiles. The GitHub Actions workflow runs in the private repository linked above;
it does not run live model generation or deploy generated applications.

### Local model comparison

With both models installed and the dependency image provisioned (see below), run:

```powershell
.\.venv\Scripts\python.exe scripts/compare_models.py --models qwen2.5-coder:3b qwen2.5-coder:7b --repeats 2
```

This runs five fixed cases twice per model: requirements, API contract, TypeScript
generation, title-validation repair, and a Node SQLite adapter repair. Generated
code compiles and executes only in restricted, network-disabled Docker containers.
Raw responses, timings, model digests, image identity and behavior results are saved
under `artifacts/model-comparison`. The small repeated suite does not establish
general reliability or prompt-injection resistance and does not change app defaults.
Run it while no dashboard operation is active because it unloads the selected models.

## Earlier milestone: security gates and controlled local preview

Implemented security checks: offline Semgrep with four local rules, limited secret
patterns, npm lockfile audit, Python lockfile audit, and five prompt-injection probes
plus a legitimate source-read control. Missing or failed required checks block preview.
Model behavior and policy enforcement are reported separately: the current 3B model
followed all five attacks, while policy denied each dry-run proposal.

```powershell
# One-time scanner setup, separate from the application environment:
python -m venv .tools/security
.\.tools\security\Scripts\python.exe -m pip install -r security/tools.lock.txt
docker pull semgrep/semgrep@sha256:451b3d875c00dac7ed5db5293e584a07de11449a409c10b3c2d2652f429630b6

.\.venv\Scripts\python.exe -m forge security JOB_ID
.\.venv\Scripts\python.exe -m forge preview start JOB_ID --approve
.\.venv\Scripts\python.exe -m forge preview status JOB_ID
.\.venv\Scripts\python.exe -m forge preview stop JOB_ID
.\.venv\Scripts\python.exe -m forge report JOB_ID
```

Dependency audits require registry access and disclose package inventories, not source.
Semgrep scans source offline. Preview approval is separate from plan approval. The app
runs on an internal-only network; a trusted fixed-target proxy exposes a localhost-only
URL. Both containers expire after approximately 30 minutes, with disposable database
contents. `preview stop` removes containers and networks; `preview status` reconciles
expiry and cleans leftover networks. Automatic container expiry alone may leave empty
networks until one of these commands runs. The dashboard will automate these controls.

Read [security/preview evidence](docs/security-preview-milestone.md) for coverage and
limitations. The agent dashboard and control API are the next milestone; CLI commands
are the current developer interface, not the intended end-user experience.

## Earlier milestone: approved generation and isolated verification

The CLI now supports durable LangGraph review interrupts, a nested backend/frontend
builder subgraph, isolated checks, and two bounded repair attempts. A real generated
task app passed type checking, production build, trusted CRUD/API tests and persistence
across server restart. Security and browser interaction checks remain unverified.

See [generation evidence and limitations](docs/generation-milestone.md).

```powershell
# Start a new plan; inspect its requirements, plan and fingerprint before approval.
.\.venv\Scripts\python.exe -m forge plan "Build a single-user task manager using local SQLite"
.\.venv\Scripts\python.exe -m forge inspect JOB_ID
.\.venv\Scripts\python.exe -m forge answer JOB_ID --answer "Your answer to the pending question"
.\.venv\Scripts\python.exe -m forge approve JOB_ID --fingerprint FULL_REVIEW_FINGERPRINT
# Or: python -m forge reject JOB_ID --fingerprint FULL_REVIEW_FINGERPRINT
.\.venv\Scripts\python.exe -m forge build JOB_ID

# Separate network-enabled provisioning of fixed dependencies, lifecycle scripts disabled:
docker build --file templates/task-app/Dockerfile.dependencies --tag forge-task-deps:local templates/task-app

# Offline, isolated generated-code execution:
.\.venv\Scripts\python.exe -m forge verify JOB_ID
# If a compiler failure can be attributed safely to builder-owned files:
.\.venv\Scripts\python.exe -m forge repair JOB_ID
.\.venv\Scripts\python.exe -m forge verify JOB_ID
```

Model calls and Docker execution must be available to the invoking terminal.
Approval and clarification resume the saved checkpoint in a separate process.
The current CLI assumes one operator and one active operation per job; concurrent
resume locking and automatic crash reconciliation are not yet implemented.
Pre-checkpointer jobs from the earlier milestone remain inspectable but must be
replanned to use approval/resume. The current assumptions schema is template-constrained.

Builds are template-based; some generated files may remain identical to their baseline.
At most six initial file-generation calls are made. Repair is compiler-location-driven:
attempt one uses a QA-guided model edit, attempt two restores only implicated files
from the trusted template. Acceptance failures without attributable compiler locations
require review; they do not trigger speculative automatic edits.

The verification container has no networking, public ports, host credentials, or Docker
socket. It reads source/tests through read-only mounts and executes from disposable
tmpfs. It is non-root with a read-only root filesystem, dropped capabilities, resource
limits, a 600-second host execution timeout and bounded output. Trusted tests run in
the same container, in a separate process; this is not a hardened multi-tenant sandbox.

No public preview is left running by `verify`. `FUNCTIONALLY_VERIFIED` is not `READY`.
Source changes require re-verification. Human identity is the local CLI operator;
there is no authenticated multi-user control plane yet.

## Earlier milestone: requirements-to-plan workflow

Initially implemented: a LangGraph flow delegates to Requirements and Architect agent nodes.
LangChain calls local Ollama with JSON-schema structured output; Pydantic rejects
invalid contracts. SQLite stores job status, validated outputs and event history.
The graph stops at `PLAN_REVIEW`, `AWAITING_CLARIFICATION`, or `FAILED`.
The initial slice did not write or execute generated application code.

### Setup (PowerShell, from the repository directory)

Verified with Windows Python 3.14.3. The lock file pins the tested dependency set.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
```

Start Ollama with `qwen2.5-coder:3b` available, then run:

```powershell
.\.venv\Scripts\python.exe -m forge plan "Build a single-user task manager with title, description, status, create, list, view, update and delete. Use local SQLite. No authentication or deployment."
.\.venv\Scripts\python.exe -m forge inspect YOUR_JOB_ID
```

Default database: `artifacts/jobs.sqlite3`. Override with `--db PATH` before the
subcommand. Exit code 1 means the job failed; 0 means the planning stage ended,
not that an application was built or verified. Inputs and validated outputs are
stored locally; do not put credentials in application descriptions.

### Tests

```powershell
New-Item -ItemType Directory -Path artifacts/test-tmp -Force | Out-Null
.\.venv\Scripts\python.exe -m pytest -q --basetemp=artifacts/test-tmp/local
.\.venv\Scripts\python.exe -m pip check
```

The `--basetemp` directory is disposable and managed by pytest; never point it at
source code or valuable artifacts. Tests use fake agents and temporary databases,
so they do not require Ollama. Real-model evidence is described in
[the workflow milestone report](docs/workflow-milestone.md).

### Limits of the initial planning slice (superseded above where implemented)

- At most two sequential model calls per run; no automatic retries.
- 4096-token context, 1600-token output cap and a 180-second HTTP client timeout.
  This is not a hard server-side cancellation or total job deadline.
- Cloud tracing is disabled around agent calls.
- Clarification questions and plan-review states are persisted stopping points,
  not yet resumable LangGraph interrupts or human approval commands.
- No crash resume, builders, tool execution, security scans, CI or deployment yet.
- Schema/contract validation does not prove requirement completeness or security.
- File manifests receive lexical checks only; future writes require resolved-path
  and workspace-boundary enforcement.

## Earlier milestone: inference experiment

The full agent workflow is not implemented yet. This script benchmarks a local
model before choosing it for the workflow. It uses Python's standard library only.

```powershell
python scripts/benchmark_ollama.py --model qwen2.5-coder:3b --repeats 2
```

Requires Ollama listening on `127.0.0.1:11434` with the selected model already installed.
Results are saved under `artifacts/inference/<UTC timestamp>/results.json`.
Requests are limited to a 4096-token context, 768 output tokens and a 240-second
client timeout per call. A timeout does not guarantee server-side inference cancellation.
There are no automatic retries. Six calls are made by default.

The experiment checks output shape and selected API-contract requirements. It records
raw responses and timing. It does not execute generated code or establish full coding
correctness, prompt-injection resistance, or reliability over long workflows.
The small validator supports only the schema features used by this experiment;
production agent boundaries will use Pydantic.

Build/test workloads will require isolation. Model calls run locally outside those
workloads, and publishing credentials will never be passed to generated code.

See [environment findings](docs/environment.md).
