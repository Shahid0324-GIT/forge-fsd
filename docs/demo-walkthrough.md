# Presenting the ForgeFSD POC

## What this demonstrates

Several specialist roles use one local Qwen2.5-Coder 7B model through LangChain.
LangGraph coordinates planning and delegates implementation to a builder subgraph.
A managed controller executes independent checks and a bounded QA/repair cycle.
SQLite stores run events and planning checkpoints; source and handoff snapshots
carry concrete work between roles. The goal is a small, inspectable agent workflow.

## Suggested walkthrough

These steps use the existing local workspace. Historical jobs and their runtime
evidence are deliberately excluded from Git. A fresh clone can reproduce the
model-free converter browser calibration, or create a new run with local Ollama;
it will not contain the saved Temperature Converter run automatically.

1. Open Forge with `Start-ForgeFSD.cmd`. Select **Temperature Converter**.
   Show the original request and the reviewed two-file plan: one frontend page,
   one backend route, no database. Planning corrections remain visible.
2. Open **Agent handoffs**. Inspect Requirements → Architect and Architect → QA.
   The original request accompanies the requirements and proposed interfaces.
   Refresh the dashboard and show that the saved context remains available.
3. Inspect the build coordinator → Frontend handoff. Its `existing_source`
   includes the backend route generated earlier. The next role receives concrete
   source and API shapes, rather than relying on conversational memory.
4. Open **Activity** and **Reports**. Distinguish a generated file from a passing
   compiler/build/API check. Report only the checks actually completed for this run.
   Use **Test app in browser** to show the fixed converter profile executing without
   a model call. Its report lists eight cases and preserves failure screenshots.
5. Explain the repair path: test output → QA diagnosis → responsible builder →
   new independent checks, with at most two attempts. The converter records both:
   a compiler type error and a manually observed stale-result label defect. Show
   the retained failed reports and final passing evidence. Distinguish the manual
   browser observation from the automated compiler/API checks. The synthetic
   evaluation below is an additional controlled example.
6. Review and approve local preview through Forge's separate human gate. Exercise
   the conversion form and show a negative temperature. Preview data/runtime is
   disposable; this is not cloud deployment.
7. Show the generated application's separate repository and hosted app CI. The
   **App CI** and **Deployment** roles have saved handoffs and reviewable workflow
   files. Explain the separate publishing and production-deployment approvals.
   The converter's one-time Vercel deployment passed CI, 15 live API checks and
   four observed browser checks, then was deleted with its temporary credentials.
   Show the retained deployment run and cleanup report; its public URLs now return
   404. This demonstrates a completed test cycle, not a currently hosted service.

## Evidence for the repair example

`artifacts/handoff-evaluation/1c4063812f734ff6ab88464873dcc16e/result.json`
retains a trial where QA found the bug but the builder combined files. Import
preflight stopped the output before it was written. After separating target code
from reference-only code, the independent follow-up trial in
`artifacts/handoff-evaluation/2d132f8bf9484429971a4348176d41e9/result.json`
passed compiler checks and ten behavior assertions after one repair attempt.
That trial required no developer source correction. It is a deliberately planted
bug in a fixed fixture, not proof of arbitrary application generation.

## Questions to be ready for

- **Are the agents independent models?** They are separate role invocations using
  the same model. Delegation and interfaces define their responsibilities.
- **How do they communicate?** Through validated graph state, shared contracts,
  source files, saved diagnoses and inspectable handoff packets.
- **How does memory persist?** Planning checkpoints and events survive process
  boundaries; later calls reconstruct relevant context from saved artifacts.
  Full automatic recovery from a forced crash during every stage is unfinished.
- **Who decides completion?** Trusted checks and controller policy. A model saying
  “done” cannot make an app verified or bypass approval.
- **What if it cannot finish?** It stops with the failure and evidence after its
  budget is exhausted. Review can identify the next action; it does not loop forever.
- **What is still missing?** Browser profiles and evaluation across more app domains,
  remote database support and deployment for database-backed apps. Stateless
  Vercel deployment has been tested and the one-time deployment removed. Hosted controller/dashboard CI and
  converter browser calibration are available in the private repository's
  [Actions history](https://github.com/Shahid0324-GIT/forge-fsd/actions).
  Current security/prompt probes are bounded checks, not a complete security audit.
