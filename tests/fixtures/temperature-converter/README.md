# Fixed browser regression fixture

These two source files snapshot the model-generated temperature converter after
its compiler and manually observed browser repairs (job
`4b3fd81eb76f4be19780ef9a1b98d156`). They are test inputs, not a fallback template
for generated apps. The normal fixed Next.js scaffold is added by the evaluator.

The stale-unit calibration variant removes only the unit-change result clearing.
The same browser profile must accept the correct fixture and reject that variant.
Future reviewed fixture corrections must be documented here; CI never calls Ollama.
