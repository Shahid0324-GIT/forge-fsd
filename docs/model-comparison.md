# Local model comparison — 31 October 2026

Both installed Qwen2.5 Coder models were tested with the same five prompts, JSON
schemas, temperature 0, 4096-token context and 1200-token response limit, twice.
The suite covers requirements extraction, exact HTTP routes, exported TypeScript
title validation, repairing title validation, and repairing a Node SQLite adapter.

| Model | All selected checks | Executable code / repair checks |
| --- | --- | --- |
| qwen2.5-coder:3b | 4/10 | 0/6 |
| qwen2.5-coder:7b | 8/10 | 4/6 |

The 3B model omitted a required named export, left invalid title handling broken,
and retained an explicitly prohibited SQLite export. The 7B model fixed the title
generation and repair cases, but also retained the prohibited `createTask` export
in both SQLite repair responses. The SQLite harness enforces that adapter contract;
passing TypeScript compilation alone is insufficient.

Manual review also found an unsupported assertion in the 7B requirements output
that persistence beyond the current session was unnecessary. The automated
requirements pass only checks selected entity, operation and field values. It
does not certify that free-text assumptions or acceptance criteria are correct.

Inference throughput was roughly 91–106 tokens/second for 3B and 20–25 for 7B.
The first request, including cold loading, took about 42 seconds and 180 seconds
respectively. Ollama reported partial GPU placement for 7B while loading. These
timings describe this machine and this test session, not general performance.

Generated code was compiled and run in network-disabled, non-root, read-only,
resource-limited Docker containers. Calibration accepted known correct title and
SQLite implementations and rejected a known incorrect title implementation.

Evidence:

- `artifacts/model-comparison/20261031T145917971321Z/metadata.json`
- `artifacts/model-comparison/20261031T145917971321Z/results.json`
- `artifacts/model-comparison/20261031T145917971321Z/summary.json`
- `artifacts/model-comparison/calibration-20261031/results.json`

This is a small fixed suite; greedy repeats are not independent statistical
samples. It does not test a complete generated Next.js app, actual LangChain
workflow schemas, or prompt-injection resistance. The default remains 3B pending
a full workflow evaluation of the stronger candidate. Both model weights remain
installed; neither was deleted. The comparison created no dashboard runs.

The same change adds persisted System/Light/Dark dashboard themes. Light and dark
rendering, dark preference persistence after reload, and the dark Trash dialog
were checked in the browser. The production UI build and all 75 Python regression
tests passed. Python tests needed a workspace-local temporary directory and local
socket access; the restricted first attempts were not successful runs.
