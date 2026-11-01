# Automated browser checks and prepared CI

This phase keeps the local 7B model. Browser execution is a trusted controller
operation rather than another model's assertion that the UI works.

## Available in the dashboard

The converter workspace now offers **Test app in browser**. It uses an explicit
`temperature-converter-v1` profile; other app domains do not silently inherit its
coverage. A running temporary preview is stopped first. Functional verification
must match the current source before the action can execute.

The fixed profile covers eight cases: both conversion directions; negative and
decimal values; the stale-unit regression; value-change clearing; required input;
extra decimal precision; and visible feedback for one mocked API error. All other
conversion calls exercise the real generated application. This is an explicit
verification action, not automatic general browser-test generation for every app.

The app builds and runs in its verified immutable dependency image. Chromium runs
in a separate container, so application code cannot write the browser evidence
mount. Both containers use an internal-only network, publish no host ports, run
as non-root, drop capabilities and use resource/time limits. App source and trusted
test code are mounted read-only. Chromium's process sandbox is disabled inside
this Docker boundary; no host credentials or Docker socket are mounted.

Browser evidence records the source fingerprint, trusted harness fingerprint,
immutable image IDs, per-case results and failure screenshots. Failed, interrupted,
partial, source-stale or harness-stale evidence blocks a subsequent preview and
positive readiness assessment once browser testing has been attempted. Passing
evidence also has to match the current functional verification's immutable app image.
Browser checks cannot replace functional verification, security checks or human
preview approval. Cancel/shutdown cleanup checks resource ownership labels.

The browser dependency is separate from generated-app packages. It uses Playwright
1.64.1 with an npm lockfile and a pinned Node 24 base. OS packages are installed at
image build time; actual runtime image IDs are recorded rather than claiming
bit-for-bit rebuild reproducibility.

## Provisioning and reproduction

With Docker running, while the dashboard has no active operation:

```powershell
docker build --file templates/task-app/Dockerfile.dependencies --tag forge-task-deps:local templates/task-app
docker build --tag forge-browser-deps:local tests/browser
.\.venv\Scripts\python.exe scripts/check_browser_fixture.py
```

The evaluator uses a committed test fixture, not ignored local workspaces, saved
job databases or a model call. Its correct fixture is derived from the generated
converter. A second variant deliberately retains the result when the unit changes.
Calibration requires all eight checks to accept the correct fixture and only the
stale-unit check to reject the broken one. Infrastructure failures do not count as
successful rejection. Evidence is under `artifacts/browser-calibration/`.

The successful local calibration is
`45862e9bf87f48bcb1d7699758910d9f/calibration.json`. The correct fixture passed all
eight checks; the stale-unit fixture failed exactly
`source_unit_does_not_relabel_result`. Its screenshot was visually inspected.
An earlier Docker logging-option startup failure is retained separately; it was
corrected before this calibration passed.

The actual generated converter also passed all eight checks through the dashboard:
`artifacts/browser/4b3fd81eb76f4be19780ef9a1b98d156/8dd0699b6869469aba51c171fa92a445/report.json`.
Source: `18bd822eda60b01217b7fa77a41b9b1e30a47f910efabdf3e4d043dc070c8f3c`.
No generated app source was changed during this phase.

The full controller regression run passed 132 tests. After adding the immutable
runtime-evidence comparison, all 13 focused browser-policy tests passed. The
dashboard typecheck/production build passed. These were local checks; GitHub's
hosted jobs have not yet executed.

## GitHub Actions preparation

`.github/workflows/ci.yml` runs controller regression tests and the dashboard
typecheck/build on Windows and Ubuntu, plus the browser fixture calibration in
Linux Docker. It uses Python 3.14, Node 24, locked dependencies and official
actions pinned to verified full commit hashes. Reports and failed-browser PNGs
are retained for seven days. Repository permissions are read-only and checkout
credentials are not persisted.

CI requires no Ollama service, model weights, GPU, cloud keys or saved local runs.
It does not execute live model generation, broad security audits or deployment.
The workflow YAML and its action references were checked locally; no GitHub run
has occurred. A chosen remote repository and a push are still needed to demonstrate
hosted CI. This phase does not create a repository or publish source.

## References

- [Playwright Docker guidance](https://playwright.dev/docs/docker)
- [Playwright CI guidance](https://playwright.dev/docs/ci-intro)
- [Official setup-python action](https://github.com/actions/setup-python)
- [Official artifact action](https://github.com/actions/upload-artifact)
