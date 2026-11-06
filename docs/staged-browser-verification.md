# Staged browser verification

Browser testing stays part of autonomous verification. A build alone does not
establish application behavior.

## Execution order

1. Run type checking and a production build.
2. Open the homepage in isolated Chromium. Require a successful document
   response, visible content, the app's origin and no observed runtime errors.
   This fixed startup check does not need an LLM-authored acceptance contract.
   Actual application failures enter the existing owned-source repair loop;
   execution-environment failures pause without editing application code.
3. Independent QA derives and reviews a bounded contract from the approved
   request. QA receives no generated source. It includes a concise, complete
   interaction scenario when the application is interactive.
4. Execute a complete interaction scenario before the other frozen scenarios.
   If it fails, leave the remaining cases explicitly unexecuted and feed the
   failure to repair. Do not truncate stateful scenarios or weaken assertions.
5. Execute the remaining scenarios in fresh app/database/browser sessions.
   Complete coverage and current build, startup and acceptance evidence remain
   necessary for the existing app-check pass. Unsupported criteria continue to
   block complete success.

## Evidence and recovery

Startup evidence is tied to source, immutable app image and browser harness,
with hashes of the underlying build and smoke reports. It can be reused for the
same source, avoiding a duplicate build immediately before acceptance execution.
After a source repair it must be regenerated. Rechecking explicitly reruns
startup, and changed evidence cannot establish a current final pass.

Startup and behavior results are separate in Activity. A quota pause, exhausted
QA budget or rejected contract leaves behavior **unverified**. The existing
bounded dispatch and senior-review recovery policy remains in force; identical
rejected proposals after review do not produce unlimited retries.

Older app passes lack this new startup evidence and their browser harness has
changed. Their source and historical reports are retained, but they need a
recheck to establish a current pass.

These changes do not select a different model, change provider credentials,
start a preview or deploy an app. They do not assert security, screen-reader
behavior or persistence across a server restart.

## Verification evidence

The final complete controller suite passed **736 tests**, with 13 upstream
deprecation warnings, in 603.55 seconds. Results are saved in
`artifacts/staged-verification-release-1106.xml` and its `.txt` log.

The focused controller selection passed 64 tests. Seven subsequent integrity
checks passed, covering invalid startup identity and failed-evidence reuse. The
two workflow-order cases passed after correcting their read-only fixture.
The Node protocol/startup selection passed nine tests, and dashboard TypeScript
checking and production build passed.

Real Chromium calibration accepted healthy content and rejected blank and
HTTP-error pages. The final report is
`artifacts/navigation-calibration/74d7efac7c4f4803b36ad589a1761aa1/report.json`.
The actual startup runner also passed against the preserved notes app without
changing its source:
`artifacts/document-smoke-live/be59451201684f2aa1f9a7ad44fa7335/report.json`.
That observation is startup evidence only; its independent behavior evaluation
has not been resumed or promoted to a pass.
