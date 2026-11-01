# First local inference experiment - 31 October 2026

## Candidate and execution

- Model: `qwen2.5-coder:3b`, digest prefix `f72c60cabf62`.
- Download completed successfully to the running server's configured D:\ollama\models path.
- Ollama: 0.40.13. RTX 2060 with 6 GB VRAM.
- `ollama ps` reported 100% GPU placement, 2.2 GB model allocation, 4096 context.
- Model options: temperature 0, 4096 context, 768 maximum output tokens.
- Each experiment made two calls per case: requirements, API contract, TypeScript code.
- Identical outputs at temperature zero are not independent reliability evidence.

## Experiment A

Evidence: `artifacts/inference/20261031T090251090523Z/results.json`.
All six outputs were valid against the small output schemas and completed normally.
Requirements passed selected semantic checks. Contract output omitted the single-record
GET endpoint, but the initial prompt did not explicitly enumerate every expected route;
that benchmark mismatch was corrected in experiment B.
The code field contained `400`, not an implementation. This exposed the need for
semantic code checks rather than schema validation alone.

First call wall time: 92.24 seconds, including approximately 40.03 seconds reported
model load duration. The remaining latency cannot be attributed solely to model loading.
Subsequent calls took 0.36-1.62 seconds, but some returned inadequate content.

## Experiment B

Evidence: `artifacts/inference/20261031T090456832822Z/results.json`.
Prompt changes: explicit endpoint list, an engineering system instruction, and a clear
requirement for full TypeScript source in the code field. A basic code-shape check was
added. Original evidence was preserved.

- 6/6 schema-valid completed responses.
- 2/2 requirements responses passed selected semantic checks.
- 2/2 API responses matched all required routes and status codes.
- 0/2 code responses met the requested exported-function shape.
- Warm call wall times: 0.73-2.01 seconds; reported generation approximately 106-108 tokens/s.

Manual inspection: code implemented trimming, empty-title rejection, the 120-character
limit, and returning the trimmed value. Both responses omitted the explicitly requested
`export` keyword. The benchmark exited with code 1, correctly retaining this failure.
Generated code was not executed. Code-shape checks do not prove behavioral correctness.

## Decision

Local inference and evidence capture work. The model is a fast baseline for constrained
structured tasks, not yet accepted as the final builder model. More representative
coding/repair tasks and isolated execution are needed. Consider comparing another model
only after reviewing the additional download/storage cost; none was downloaded here.

Next reviewable milestone: pin dependencies and implement a small LangGraph/LangChain
requirements-to-planner delegation flow with Pydantic validation and persisted events.
Do not expand into the entire platform before that flow is verified.
