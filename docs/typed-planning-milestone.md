# Typed planning foundation — 2 November 2026

This implements the first part of the [next-phase plan](forgefsd-next-phase-plan.md).
It does not establish reliable generation of arbitrary applications. No new generated
app was approved, executed or deployed during this implementation evaluation.

## Changes and their purpose

- A typed business brief separates stateless tools from stored records. Field variants
  make numeric bounds, enum choices and entity references explicit, with incompatible
  combinations rejected by the model-visible schema.
- API architects select business operations. A fixed JSON-operation HTTP profile
  derives route names, handler files, entity input/output types and identity inputs.
  Entity lists/reads use GET; creates, updates and deletes use JSON POST. Custom
  operations support calculations, aggregates and business state changes. Extra DTO
  definitions are mandatory; naming an undeclared type cannot pass validation.
- Pages contain component definitions directly, rather than a second registry of
  string references. Components and helpers bind accepted operation IDs; their result
  props, callbacks, input parameters and return types are compiler-derived. Parent
  page context includes its components' operations automatically. Framework filenames and
  file ownership are compiled from the same design. File limits are supplied before
  layout selection and checked against the existing execution limits. All business
  operations must be connected to an implementing page.
- The approved design renders `lib/forge_contracts.ts`. Builder ownership excludes
  this file, and generation resume checks that it still matches the approved design.
  Frontend packets contain HTTP/data interfaces rather than backend implementation.
  Required contracts are retained completely or rejected for exceeding the budget.
- Independent test planning references operation IDs; the compiler derives actual
  methods/paths. It checks JSON shapes, statuses, typed captures and positive stored
  fixtures without rewriting assertions. Generated source is absent from this role's
  input. Test design precedes generation; test execution still follows generation.
  Success fixtures use operation-derived model-visible schemas; negative fixtures
  retain the ability to exercise invalid input. Omitted subset assertions remain
  omitted rather than gaining default null fields. Standard entity lifecycle effects
  are explicit metadata, so persistence checks do not infer deletes from HTTP verbs.
- New typed planning uses deterministic consistency checks and bounded corrections.
  Same-model advisory review remains only on the compatibility path, rather than
  being presented as a correctness oracle for the new path.
- Intake distinguishes builds, blocking clarification, workflow help and unrelated
  questions. Help/off-topic replies do not enter app planning or create an app
  workspace. A lightweight request/event record remains visible in the dashboard.
- Saved handoffs and actual calls carry job, operation, parent task, task, handoff
  and call identifiers where applicable. Call reports preserve the supplied messages,
  response schema, requested options, actual output and provider/timing metadata.
  Failed calls and validation corrections are inspectable. Context inspection checks
  the saved handoff hash/identity and rejects altered evidence.

These are shared platform rules. Evaluation app names occur in fixtures and the
evaluation script, not in the new production planning/compiler modules.

## Compatibility and scope

Existing approved legacy plans retain their execution path. A failed planning checkpoint
that predates the typed business brief must start a fresh plan; it cannot be safely
reinterpreted as an approved typed contract. Stored revisions are not silently migrated.

The new HTTP profile is intentional and is not an arbitrary REST-layout generator.
It retains the existing small-app file and dependency limits. It does not add custom
dependencies, authentication, external integrations or a remote database adapter.

## Validation

The committed evaluation entry point is:

```powershell
.venv\Scripts\python.exe scripts/evaluate_planning.py --repeats 1
```

It uses the installed model and isolated stores under `artifacts/planning-evaluation`.
It saves source hashes, actual call reports and each outcome. It stops before approval,
generation or deployment. Reaching `PLAN_REVIEW` means structural validation completed;
it is not application execution or semantic correctness evidence.

The Python suite exercises canonical compilation/drift rejection, schema alternatives,
cross-domain contracts, shared file limits, typed fixture bindings, ownership/context
scope, call/handoff correlation, off-topic routing and the real planning graph with
an injected provider. The API check opens a genuine saved handoff and verifies that
tampering produces HTTP 409. Those tests do not require live inference.

The dashboard was also inspected in a browser using a separate, explicitly labelled
UI fixture and expiring localhost server. The shared design rendered, saved context
opened in its dialog, and recorded-call inspection opened readable report contents.
This was a UI wiring check, not a generated-app demonstration.

Early live evaluations exposed omitted DTO definitions, independently invented route
segments, inconsistent statuses, numeric capture placeholders, and incompatible file
budgets. Their failures remain in ignored local artifacts. A calculator plan that passed
an intermediate validator still omitted UI operation references; the new coverage guard
now rejects that omission. Intermediate green outcomes must not be counted as final
reliability evidence.

## Remaining work

Semantic completeness still requires review and executable evidence. Consistent type
names cannot prove a correct formula, useful callback/helper signatures, complete
business coverage or correct generated code. The model can still produce invalid
proposals; failed proposals remain blocked rather than being silently weakened.

The next milestones remain: stronger delegation/tool/result contracts and budgets;
generated-app build/API/repair evaluations without manual source edits; reusable
independent browser checks beyond the converter profile; complete evidence freshness
auditing; observable CI/deployment tool spans; and a tested persistent cloud adapter.
This milestone adds no model browsing, research tools or fabricated source citations.

Final verification results and the latest live evaluation are recorded below.

### Controller and dashboard verification

| Command | Exit | Result |
| --- | --- | --- |
| `.venv\Scripts\python.exe -m pytest -q` | 0 | 201 passed; 13 upstream LangSmith deprecation warnings |
| `npm run build` in `apps/web` | 0 | `tsc --noEmit` and Vite production build passed |
| `git diff --check` | 0 | No whitespace errors |

During verification, `npm run typecheck` exited 1 because this package has no such
script; its committed `build` script already includes the TypeScript check. One new
API test initially received 403 because its fixture database lived outside the real
artifact layout; the fixture now mirrors production without relaxing the API boundary.
The old exact event-sequence test also failed after recording the initial coordinator
handoff; its assertions now verify the expanded sequence and actual parent linkage.
The final suite above includes those corrections.

### Final live planning evaluation

`.venv\Scripts\python.exe scripts/evaluate_planning.py --repeats 1` exited **1**.
Evidence directory: `artifacts/planning-evaluation/b599c0c658c84c4698c9fabd7f03938c`.
Its saved source hashes match the implementation candidate. Model: installed
`qwen2.5-coder:7b`, Q4_K_M, digest
`dae161e27b0e90dd1856c8bb3209201fd6736d8eb66298e75ed87571486f4364`.

| Request | Outcome | Calls | Seconds |
| --- | --- | --- | --- |
| Calculator | PLAN_REVIEW; manual semantic review still needed | 5 | 91.47 |
| Expense tracker | FAILED at layout coverage after one correction | 5 | 90.66 |
| Related stockroom records | FAILED at API type declarations after one correction | 4 | 147.26 |

Actual final errors:

```text
LayoutProposal decision is inconsistent after one correction: Every business operation must be referenced by an implementing page; otherwise UI builders receive an incomplete operation contract

ApiProposal decision is inconsistent after one correction: Duplicate or platform-defined record type: Product
```

The calculator's proposed arithmetic and invalid-input cases are correct for their
specified fixtures. Its callback/helper types and page operation context agree.
Manual review still found excessive leaf-component splitting without a clear shared
input-state contract, an inconsistent positive-vs-nonnegative bill rule, and assumptions
that conflict with required validation. The review is saved as `semantic-review.json`.
It is not counted as successful generated-app execution.

Thus **1/3 requests reached structural review, 0 apps were generated/executed**, and
the foundation milestone's reliability exit criterion is **not met**. No model failure
was bypassed, no test expectation was weakened, and no user app retry was requested.

A separate live intake check asked "How is the weather today?" It exited 0, used one
model call, ended as `REQUEST_ANSWERED`, and created no application workspace. Evidence:
`artifacts/intake-evaluation/d57a9eb46bfb44b0b7a223393b38d53b`. The answer describes
Forge's scope instead of inventing weather information.

### Priorities before a new app demonstration

- **P0:** Replace remaining self-referenced DTO decisions with scoped/compiled type
  declarations; make correction feedback identify exact missing operations and route
  revision to the role that owns the underlying decision. Layout repair cannot remove
  an unnecessary API operation owned by an earlier architect.
- **P0:** Define UI state ownership and component input bindings, not just operation
  callbacks. Validate semantics against the request, including boundary values and
  assumptions; a coherent type graph alone is insufficient.
- **P0:** Complete repeated cross-domain planning plus isolated generated-app execution
  without undisclosed manual source edits before calling the workflow reliable.
- **P1:** Continue the approved task/tool delegation, generic browser checks, evidence
  freshness, generated-app CI/deployment observability and persistent deployment work.

The changes are kept on `codex/typed-planning-foundation`; they are an implementation
candidate for review, not a merge to the stable `main` baseline.
