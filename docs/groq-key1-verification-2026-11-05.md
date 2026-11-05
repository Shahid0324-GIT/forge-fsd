# Groq key 1 reliability verification — 2026-11-05

This checkpoint uses the explicitly selected `GROQ_API_KEY_1` credential and
`groq:openai/gpt-oss-120b`. It does not switch credentials or models automatically.
The local selection is in ignored configuration; no credential is committed.

## Completed controller fixes

- Explicit credential selection and token-capacity accounting per credential.
- Resumable, business-request-only app evaluations with preserved source and
  current-evidence checks.
- Compact engineering-review references with canonical reference validation.
- One bounded correction by the producing role for rejected structured JSON;
  authentication, quota and transport failures remain resource pauses.
- Shared browser semantics for QA and reviewers, exact criterion references in
  critique schemas, and interpreter-aware review-cache invalidation.
- Lossless removal of schema title annotations on the provider wire, and removal
  of duplicated feedback and builder-only interface context from behavior QA.

These changes address controller contracts and apply across generated apps.
They do not establish a universal model-accuracy guarantee.

## Live notes evaluation

The agent received only this business request:

> Build a small personal notes app. I can add a note with a title and body,
> edit it, delete it, and see saved notes after reloading. Reject empty titles
> visibly. No login or external services.

The agents planned six files and two interfaces. All six files passed syntax
validation on their first generation attempt. Type checking and the production
build passed on their first verification action. Generated app code and test
contracts were not manually edited.

QA exposed both controller defects and genuine missing assertions. The fixes
above correct false claims about document navigation, incomplete criterion
references and excess prompt duplication. The quality gate also required body
content assertions in addition to note titles. QA had not frozen its final suite
when the account reached its daily token boundary: the final receipt reported
193,267 used of 200,000, with 6,968 required for the next request.

**Result: build passed; browser app verification remains pending.** The evaluation
is `AUTONOMOUS_TEST_PAUSED`, not an app pass. The original cancelled expense job
was not resumed. No preview or deployment was started.

Evidence: `artifacts/autonomous-flow-evaluation/11bc83c153254c018d1ecbade2335104/`.
After the account limit resets, resume the same request and source with:

```powershell
.venv\Scripts\python.exe scripts/evaluate_autonomous_flow.py --resume artifacts/autonomous-flow-evaluation/11bc83c153254c018d1ecbade2335104
```

## Browser interpreter verification

The real Chromium navigation calibration passed: a repeated visit uses full
document navigation, resets JavaScript memory and retains local/session storage
and cookies; a fresh scenario context has none of that state. Four Node protocol
tests also passed. These checks establish interpreter behavior, independently of
the pending generated-app browser scenarios.

## Final regression checkpoint

The complete Python suite passed **725 tests**, with 13 upstream deprecation
warnings, in 514.44 seconds. Results are saved in
`artifacts/groq-key1-release-check-1105.xml` and the corresponding `.txt` log.
Dashboard TypeScript checking and the production build also passed.

The dashboard was restarted at `http://127.0.0.1:8787` with the updated code.
Its session endpoint and both frontend assets responded successfully, there
were no active operations, and the original expense job remained `CANCELLED`
in the archive. No new model run was started during these checks.
