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
