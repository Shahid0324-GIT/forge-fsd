# CI/CD agents for generated applications

Forge's own repository checks are development infrastructure. The assignment's
release path belongs to each **generated application**, in a separate repository.

After local functional/security gates (and current browser evidence if attempted),
the dashboard offers **Prepare app CI/CD** with an `owner/repository` destination.
This invokes a LangGraph subgraph with two LangChain/Ollama role calls:

1. The **CI Agent** receives the reviewed requirements, plan, source identity and
   passing local gate result. It prepares bounded review notes about application CI.
2. The **Deployment Agent** receives that context plus the CI agent's output. It
   prepares a Vercel release assessment and explains database/setup blockers.

Both handoffs are saved and visible. The controller renders executable workflow
files from a fixed policy; model output cannot invent shell commands, secrets,
permissions or destinations. This is intentional capability control, not a claim
that the model autonomously writes unrestricted deployment infrastructure.

## Generated release bundle

Preparation leaves the verified app workspace unchanged. A new local release
bundle under `artifacts/releases/JOB/REVISION/bundle` contains the app, fixed
dependency provisioning, the approved acceptance contract, trusted acceptance
harnesses and `.github/workflows/app-ci.yml`. Stateless apps also receive
`.github/workflows/deploy.yml`. SQLite apps get CI and an explicit deployment block.

The JSON review includes the exact workflow contents, repository name, source
fingerprint and bundle fingerprint. Changing source, bundle or review invalidates
approval. The existing preview gates are reused as release evidence gates.

## Publish and application CI

**Publish generated app** requires a separate checkbox approval of the concrete
review and destination. The controller uses authenticated GitHub CLI to create a
new private repo in the signed-in personal account, commits only the release
bundle and pushes `main`. Existing repositories are not overwritten; force-push
is unavailable. Forge's own `forge-fsd` repo is forbidden as an app destination.
Publishing attempts are journaled, and interrupted publication requires inspection
instead of blindly repeating external side effects.

App CI runs on push and pull request, and can be called by deployment. It builds
the locked dependency image with network access/lifecycle scripts disabled, then
executes typecheck, production build and the **app's approved HTTP scenarios** in
an offline non-root Docker container. Applicable restart and SQLite integrity
checks use the same trusted harness as local verification. It does not run Forge's
Python tests. It does not claim a hosted repeat of security probes or generic
browser coverage. GitHub job logs retain the per-check JSON result.

## Deployment agent execution

**Deploy app to Vercel** is a second, explicit approval for a public production
deployment. Before dispatch, the controller verifies:

- The reviewed bundle and generated source still match.
- Remote `main` equals the published commit.
- The latest app CI run at that exact commit passed.
- The app is stateless; the SQLite remote adapter is not implemented.
- The app repo has `VERCEL_TOKEN`, `VERCEL_ORG_ID`, `VERCEL_PROJECT_ID` secrets.

Configure those secrets in the generated app repo for an existing Vercel project;
do not paste token values into chat or model context. This POC does not provision
Vercel accounts/projects or manage secrets. GitHub CLI authentication belongs to
the trusted controller, not the models. Organization publishing is out of scope.

The deployment agent's controller dispatches `deploy.yml` on `main` with the
approved commit. The workflow reruns app CI before the production job, checks the
dispatch commit and uses Vercel CLI **65.9.0** (`pull`, `build --prod`,
`deploy --prebuilt --prod`). The CLI version is pinned; its transient dependencies
are resolved on execution, rather than fully locked in the app's dependencies.
An optional GitHub `production` environment can supply additional review controls.

**Refresh app CI / deployment** retrieves actual hosted status. A successful
workflow alone cannot mark an app deployed: the controller also requires the
deployment URL artifact to match the approved SHA and a Vercel HTTPS URL. This
attests the recorded deployment output, not ongoing uptime or complete behavior
of the public service. No production deployment is claimed until this evidence exists.

## Current evaluation

The verified 7B-generated temperature converter is the first release candidate.
Its two planning role calls completed and produced a review for
`Shahid0324-GIT/forge-temperature-converter`. Local release/approval tests include
stale-source/bundle rejection, secret/data exclusion, CI failure, remote drift,
SQLite blocking, missing secrets and mismatched deployment artifacts. The release
bundle also passed offline Docker typecheck, production build, eight approved HTTP
scenarios and shared JSON validation locally. The full controller suite passed
152 tests, followed by 34 focused release/API checks after final additions.

The user approved release `6da53032…`, and Forge's managed publication action
created the private
[converter repository](https://github.com/Shahid0324-GIT/forge-temperature-converter)
at commit `ead072f5c34f37f5050f38a2268c890b0382222b`. Its
[application CI history](https://github.com/Shahid0324-GIT/forge-temperature-converter/actions)
is separate from Forge's own checks.

## One-time live deployment and cleanup: 1 November 2026

The user approved a temporary Vercel test and cleanup. A dedicated Hobby project,
`forge-converter-test-4b3fd81e`, used Next.js on Node 24 without a Git integration
that could independently trigger deployments. The CLI device login could create
the project but could not create a personal token. The account dashboard's team
submenu provided a restriction to this specific project; a one-hour token was
created with explicit approval. Non-secret metadata confirmed the project ID.
The credential was encrypted for local transfer and passed directly into the app
repository's GitHub Actions secrets. Its plaintext value was not placed in model
context, source, logs or saved evidence; temporary transfer files were removed.

Forge dispatched the [successful deployment workflow](https://github.com/Shahid0324-GIT/forge-temperature-converter/actions/runs/41300588953)
at approved commit `ead072f5c34f37f5050f38a2268c890b0382222b`. App CI passed again
before production deployment. The live service passed 15 direct HTTPS API checks
and four operator-observed browser checks: decimal conversion, negative conversion,
unit-change clearing and input-change clearing. These were bounded checks, not a
complete production/security audit.

After saving evidence, cleanup removed the exact deployment and dedicated project,
revoked the project-only token, removed all three temporary GitHub secrets, and
logged out the CLI session used for the trial. Both the unique deployment URL and
production alias returned HTTP 404 afterward. Project absence and token absence
were independently checked through Vercel; GitHub listed none of the three secrets.
The application repository and historical Actions results remain available.

Local evidence is retained in `artifacts/vercel-one-time/summary.json`, individual
API/browser reports, cleanup checks and screenshots. These ignored local artifacts
are not distributed by a fresh clone. Forge records both the successful historical
deployment and its verified removal; refreshing status does not revive the old URL.
Cleanup was performed through trusted operator tooling for this trial, not an
autonomous cleanup agent or a new dashboard delete-deployment button.

The first model notes contained imprecise wording about HTTP checks authorizing
requests and offline dependency provisioning. Original responses are retained;
the UI labels them advisory and states the actual controller policy explicitly.
The CI prompt was tightened for later calls. Those notes never control commands
or grant authorization.

## References

- [Vercel's GitHub Actions guide](https://vercel.com/kb/guide/how-can-i-use-github-actions-with-vercel)
- [GitHub CLI repository creation](https://cli.github.com/manual/gh_repo_create)
- [GitHub CLI workflow dispatch](https://cli.github.com/manual/gh_workflow_run)
