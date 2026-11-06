# QA correction context

The live tip-calculator evaluation exposed a correction request exceeding the
Groq account's per-request token budget. Its first QA proposal had been generated
successfully; repeating the implementation narrative alongside the complete
proposal and reviewer feedback made the correction substantially larger.

Initial QA still receives the full approved design narrative. When correcting a
saved proposal with bound, complete feedback, the controller retains every
original requirement, clarification, criterion, assumption, prior assertion and
feedback item. The unchanged builder narrative is retained by hash in the saved
handoff rather than repeated in that correction prompt. No approved snapshot,
generated source or QA proposal is edited by this projection.

Opaque review and protocol hashes are recorded in handoffs and controller
bindings, outside QA's model input: the QA response does not return those hashes.
Output schema validation and the checks that bind reports to the approved review
remain unchanged. The role instructions reference the authoritative shared
protocol instead of duplicating its full navigation and assertion descriptions.

The shared facts also distinguish Playwright `fill` from physical typing. A
nonnumeric fill into a native number input throws a tool error; it cannot prove
that typed letters are ignored. Native number inputs have the `spinbutton` role.
Unsupported reviewer suggestions do not add actions to the browser protocol.

Validation: 147 QA/provider regressions passed. Real isolated Chromium confirmed
valid numeric fills, rejected nonnumeric fills and the native role in
`artifacts/navigation-calibration/86573dc28b66489583c078f524577189/report.json`.
Actual resumed app verification remains separate from these controller checks.
