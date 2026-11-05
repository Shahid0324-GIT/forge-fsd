# Documentation-assisted agent recovery

ForgeFSD's autonomous roles can now read official technical references while
planning, reviewing, generating source or diagnosing a failure. Inference still
uses the model selected for the job. Documentation retrieval does not select a
cloud model, install packages or grant network access to the generated app.

## How it works

`OllamaAgents.generate` offers two response types through the actual decoding
schema: the role's normal answer, or `lookup_documentation`. The raw-source path
recognizes the same request before source decoding/writing. The controller reads
the references and resumes the same role with the original requirements and
retrieved evidence. A tool request can never be saved as an app source file.

Agents do not need a separate mandatory research call before every answer.
Uncertainty can trigger a lookup directly. Actual compiler/syntax diagnostics also
trigger retrieval before a recovery answer, even when the model is overconfident.
Implementation-review findings get one documentation reassessment before becoming
blocking feedback. Protocol corrections remain bounded; documentation-budget
failures retain their pause type through QA diagnosis instead of becoming app
defects that invite another source edit.

Queries rank an official-documentation index locally. Only the chosen public
documentation URLs are fetched; queries and application source are not sent to a
search engine. The index covers Next.js, React, TypeScript, Node 24 SQLite, browser
storage/forms and Playwright. Agents may also supply another documentation URL on
one of those official hosts. This is documentation retrieval, not unrestricted
web search. Next.js and React use their official Markdown endpoints, avoiding
oversized rendered hydration bundles.

## Evidence and boundaries

- Each answer has at most two lookups. Each lookup selects at most two pages.
- Only HTTPS official hosts are accepted; credentials, query strings, private
  destinations and redirects outside the allowed hosts are rejected. Anchors are
  removed before retrieval.
- Reads have socket/time/size limits. Scripts are never executed. Page excerpts
  are bounded; full retrieved text lives in a cache with integrity hashes and a
  24-hour freshness limit.
- Results carry source URLs, retrieval times, content/text hashes and report
  hashes. Post-lookup handoffs bind the next model call to its actual evidence.
- Engineering-review wire schemas use short evidence IDs. The packet maps each
  ID to a source path already present in the request, so requirements, runtime
  facts and documentation are not copied into a second facts table. The controller
  resolves IDs to canonical paths and quotations in durable feedback. This fixed
  a measured Groq request-size failure without dropping requirements or changing
  validation: the live review schema shrank from 11,139 to 7,646 characters and
  its messages from 31,849 to 22,605 characters; the resumed review completed.
- Task revision, version and cancellation are checked around retrieval. A stale
  lookup cannot authorize another answer or a source write.
- A failed fetch is recorded as unavailable, not as proof an API is unsupported.
  Unavailable/error text cannot become a technical review's cited fact.
- Review evidence and resolved source references are forwarded to the planner.
  Documentation cannot create new business requirements or replace installed
  capabilities, compilation, production builds or frozen browser assertions.

The dashboard shows `DOCUMENTATION_LOOKUP_STARTED` and
`DOCUMENTATION_LOOKUP_COMPLETED` events. Reports are under
`artifacts/documentation/<job-id>/`; model-call and handoff reports show exactly
which evidence the agent received.

## Prompt corrections

The shared adapter now accurately distinguishes reference lookup from command
execution. Planner instructions distinguish server database choice from storage
lifetime. `database=none` permits appropriate browser persistence. The ambiguous
capability sentence "No database is valid" was removed, as was an unnecessary
transient-state example that the small model was copying into persistence plans.

The implementation reviewer now checks a design as a design: missing source code
does not prove a planned feature is broken. It must read existing test steps
before reporting an omission, verify uncertain technical objections against
references, and withdraw concerns unsupported by actual scope or platform facts.
Optional security, placement and platform preferences cannot become user
requirements merely because a reference discusses them.

## Verification on November 5, 2026

Offline regressions cover explicit and automatic lookup, normal and root-model
answers, raw-source separation, intact/corrupt caches, unsafe URLs/redirects,
outages, post-lookup handoff integrity, stale-task rejection, bounded lookup loops,
review reassessment and source syntax gates. Live HTTP checks retrieved all
14 indexed pages successfully.

The complete regression run passed **702 tests**, with 13 upstream deprecation
warnings (`artifacts/documentation-full-1105.txt` and its JUnit XML). Final
handoff/evidence propagation checks passed **78 tests**; the subsequent QA pause
and builder integration selection passed **3 tests**. Dashboard TypeScript and
Vite build checks passed.

In an isolated local `qwen2.5-coder:7b` run, the same business-only notes request
that previously stalled reached `AUTONOMOUS_DRAFT_READY` with one planner action
and one review action. It chose browser localStorage, preserved reload behavior
and visible empty-title validation, and needed no technical user answers. Evidence:
`artifacts/documentation-7b-planning-1105/result.json`.

A separate live 7B tool check requested documentation, read MDN and answered the
storage question correctly using the retrieved source URL. The controller
verified both the lookup and answer. Evidence:
`artifacts/documentation-7b-tool-1105/result.json`.

These establish planning and reference-tool behavior. They do not establish a new
end-to-end application build or guarantee every 7B critique is logically sound.
The previously stopped expense job was not resumed or manually repaired.

## Provider-output recovery

A subsequent Groq evaluation exposed two controller boundaries. Compact evidence
IDs removed a request-size failure. The next boundary was a provider rejection of
generated JSON. Groq's [structured-output documentation](https://console.groq.com/docs/structured-outputs)
describes output-validation failures separately from ordinary request failures.

The adapter now identifies `json_validate_failed` for structured requests as a
rejected candidate. Raw chat callers receive an error. Structured callers receive
an error result, never a valid parsed answer, even if that candidate could parse
locally. The producing role gets one schema-preserving correction. Repeated
rejection stops after that correction; credentials, quota and unknown request
errors do not enter this path. Malformed transport envelopes remain resource
failures. These distinctions prevent format repair from becoming an app-code
repair or requiring an operator to restart a whole agent role.

## QA protocol facts and review coverage

The live notes run exposed a false review claim that `visit` could be SPA
navigation. The actual interpreter uses Playwright `page.goto`. Capabilities now
publish exact action names, document-navigation semantics and fresh scenario
contexts from one shared description; coverage review no longer has a competing
handwritten action table. Static scenario facts identify same-path visits and
pre/post observation step indices without claiming the app executed.

Scope review receives the relevant proposed scenarios as well as requirements,
so a demand for another tool can be checked against the existing steps. The
quality review decoding schema binds its assessed indices and issue references
to the actual covered criteria/scenarios, including nonconsecutive indices.
Cached quality and coverage judgments include the actual interpreter identity.

`python scripts/check_navigation_semantics.py` executes the exact visit handler
in isolated Chromium: two visits reset JavaScript memory while preserving local
storage, session storage and cookies; a new context has none of that saved state.
It passed locally and is included in the browser CI job. The associated QA
selection passed 123 tests, semantic-cache checks passed 25, the Node protocol
selection passed four, and the complete controller suite passed 723 tests.
These verify runner and review behavior, not a generated-app pass.

## Compact wire schemas and behavior-QA context

Groq receives a title-annotation-free copy of the response schema; the original
Pydantic model remains authoritative. Only schema-node `title` annotations are
removed. Property names such as a note's `title`, constant/default/example objects,
descriptions, enums, bounds, required fields and references are preserved. The
[JSON Schema annotation specification](https://json-schema.org/understanding-json-schema/reference/annotations)
defines schema titles as descriptive metadata. The transport marks this policy
in response metadata so the saved original schema can be interpreted correctly.
The measured QA schema shrank from 9,764 to 8,539 compact JSON characters.

Independent behavior QA no longer receives builder-only module interface
declarations. Their hashes and the complete approved snapshot are retained.
Original requirements, behavior design, criteria, assumptions and the complete
previous test proposal stay in the prompt. A complete rejection is supplied once
instead of repeating its leading text in a second error field. This selection
passed 117 regressions, including preservation of literal data named `title` and
complete correction feedback.
