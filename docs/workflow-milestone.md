# Requirements-to-plan milestone

## Implemented boundary

```text
CLI -> request validation -> create SQLite job
    -> LangGraph Requirements node -> validated requirements
        -> open questions? -> AWAITING_CLARIFICATION
        -> otherwise Architect node -> validated plan -> PLAN_REVIEW
    -> any agent/validation exception -> FAILED with saved diagnostics
```

The graph is a deterministic coordinator delegating to two LLM roles, not yet a
model-driven supervisor or the final builder subagent hierarchy. This distinction
keeps the first slice small and its claims accurate.

Implementation: `src/forge/schemas.py`, `agents.py`, `workflow.py`, `persistence.py`,
and the `python -m forge` CLI. Pydantic validates task CRUD, required fields, exact
routes, TypeScript App Router paths and frontend/backend file ownership. These are
planning constraints only, not an execution sandbox.

## Dependency evidence

Python 3.14.3 resolved and installed the dependencies using available wheels.
Direct dependencies are pinned in `requirements.in`; the complete tested set is
in `requirements.lock.txt`. `pip check` found no broken requirements.
The project was installed editable into its own `.venv`; no global packages changed.

## Real local-model evidence

Model: qwen2.5-coder:3b through LangChain's Ollama integration, JSON-schema mode.
SQLite evidence: `artifacts/jobs.sqlite3` (excluded from Git).

- Job `95395642dc004209ad13e56f07eebda3`: FAILED. Requirements validated, but the
  proposed plan omitted HTTP methods, used Pages Router paths and overlapped file
  ownership. Validation rejected it. This was a development run, not an automated repair.
- After explicitly constraining route values and explaining App Router ownership,
  job `6a3c12b7c42f48068acc63155f96d650` reached PLAN_REVIEW. Both agent calls returned
  validated objects with all five routes and separate frontend/backend manifests.

Plans are proposals. Suggested verification steps are not executed checks and are
not authoritative over the future trusted acceptance suite.

## Verification scope and limitations

Offline tests cover delegation order, persistence across store reopen, clarification
routing, malformed outputs, model timeouts, unsafe paths, overlapping ownership,
truncated completions and structured-output parsing failures.

Initial tests encountered sandbox restrictions in pytest's default temporary folder;
running with a workspace-local temporary directory resolved that setup issue.
Dependency deprecation warnings remain visible rather than suppressed.

There is no approval/resume API, generated application, build execution, prompt attack
suite, CI or cloud deployment in this slice. Crash recovery and a hard overall job
deadline remain future work. No application is labelled READY.

## Next milestone for review

Add persisted clarification answers and explicit plan approval, then the constrained
Next.js template and builder subgraph. Retain independent test/policy ownership in
the control plane; execute generated workloads only in verified isolation.
