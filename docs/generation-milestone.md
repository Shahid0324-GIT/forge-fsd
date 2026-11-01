# Human review, builder delegation and isolated verification

## Actual outcome

Approved job: `07e271d4f5114709b559692ba801e63c`.
The human explicitly approved the requirements and plan in chat before the CLI approval
was recorded. Review fingerprint:
`b2d38980f53254c89ade7e5ab6a3a02939245d5a8808e0ce76d75f011145ca38`.

The final selected functional checks passed against source fingerprint:
`997d56a247abcea27f1060b2ac01ba63502ff328c92bcb099c3305d1473f5ddb`.

Source: `workspace/07e271d4f5114709b559692ba801e63c`.
Evidence: `artifacts/verification/07e271d4f5114709b559692ba801e63c/b306cfda3caf4a26a6151df8ac66cf77.json`.
These local runtime directories are excluded from Git.

| Check | Exit code | Duration |
| --- | --- | --- |
| TypeScript | 0 | 1.88 s |
| Production build | 0 | 11.85 s |
| HTTP frontend smoke and API acceptance | 0 | 0.77 s |
| Persistence after server restart | 0 | 0.70 s |

No application is marked READY. Security and browser interaction coverage remain unverified.

## Agent and graph boundaries

The planning graph uses SQLite-backed LangGraph interrupts for clarification and exact-
revision approval. It resumes through `Command(resume=...)`. Requirements are regenerated
with recorded question/answer pairs, within a maximum of two clarification rounds and
four planning model calls. Cloud tracing is disabled around graph execution.

The builder controller validates approval and the six-file manifest, creates a fresh
workspace from the task template, then invokes a compiled implementation subgraph as
a node in a parent graph. That subgraph runs the backend and frontend builder nodes
sequentially. Each file is generated through the local LangChain/Ollama model.

Backend ownership: `lib/db.ts`, `lib/tasks.ts`, and both task Route Handler files.
Frontend ownership: `app/page.tsx` and `app/components/task-form.tsx`.
Shared contracts, dependencies, scaffolding and trusted tests are outside model write
permissions. The writer checks path traversal, symlinks/junctions and ownership.
These checks assume no hostile concurrent host process racing file operations.

## Failure and repair evidence

The first actual container type check failed with exit code 2. Qwen added obsolete
SQLite statement methods and placed item operations in a collection route. The
verification container returned exit code 1 and the job became VERIFICATION_FAILED.

Repair attempt one: QA interpreted compiler output; a model repair changed only the
two implicated files. Reverification failed. The initial failure evidence is preserved
in `06b28294f2da4b7786328b5651152832.json`; the first repaired failure is preserved
in `e88517f66a7c4986a30566c17d44fcae.json` in the same job evidence directory.

Repair attempt two: QA ran again, then deterministic policy restored only those two
implicated files from the trusted supported template. It did not change tests, other
generated files, or acceptance criteria. Final checks then passed. This is explicitly
a template fallback, not a successful free-form model-written repair.

Some initial generated files reproduced their template baseline. This POC demonstrates
constrained template-based generation, not arbitrary application synthesis. The 3B model
still needs comparison against stronger candidates before final builder selection.

## Dependency provisioning and isolation

Node 24 image digest:
`sha256:c86ecead9e55a5210ac1727de38a4ca840bf03dcaf34dc9749addbf383b1920c`.
Next.js 16.4.3, React/React DOM 19.3.1 and TypeScript 5.9.3 were installed in a separate
network-enabled container-image build with npm lifecycle scripts disabled. The actual
resolved lockfile was exported into the template and generated source before final checks.
Future dependency image builds use that lockfile via `npm ci`.

Application execution: network disabled, non-root UID 1000, read-only root, all
capabilities dropped, no privilege escalation, 6 GiB memory, 4 CPUs and 256 PIDs.
Source and trusted tests are mounted read-only; source is copied into a disposable
2 GiB working tmpfs. No host credentials, Docker socket or public ports are exposed.
The source hash was unchanged after execution. Containers are forcibly cleaned up.

Each phase records its command, exit code and bounded logs under the outer timestamp,
source fingerprint and immutable dependency image ID. The harness stops after a failed
phase. It does not call missing later checks passed.

## Remaining limits

- No dashboard/control API, general repair routing, scanners, prompt-injection suite,
  persistent local preview, remote PostgreSQL, GitHub CI or Vercel deployment yet.
- HTTP frontend smoke verifies rendering, not browser interactions. Inspection found
  that the generated form requires a nonempty description while the API allows empty
  descriptions; align this contract when browser tests are added.
- Model/HTTP timeouts are not a hard global job deadline or server-side cancellation.
- Local single-operator workflow; concurrent resume locking and crash reconciliation
  remain future work. Interrupted builds are inspectable but not automatically resumable.
- A fingerprint covers source, not every external dependency or host configuration;
  image IDs and the dependency lock are recorded separately.
- Container controls reduce risk but are not proof against every hostile workload.

Next milestone: security/prompt-injection gates and a controlled preview, then browser
tests and a minimal dashboard. All unfinished checks must remain visible in reports.
