# Presenting the ForgeFSD POC

## What this demonstrates

Several specialist roles use one local Qwen2.5-Coder 7B model through LangChain.
LangGraph coordinates planning and delegates implementation to a builder subgraph.
A managed controller executes independent checks and a bounded QA/repair cycle.
SQLite stores run events and planning checkpoints; source and handoff snapshots
carry concrete work between roles. The goal is a small, inspectable agent workflow.

## Suggested walkthrough

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
  the first hosted run of the prepared GitHub CI workflow, remote database support
  and cloud deployment.
  Current security/prompt probes are bounded checks, not a complete security audit.
