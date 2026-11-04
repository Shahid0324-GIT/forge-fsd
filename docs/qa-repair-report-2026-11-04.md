# QA repair checkpoint — 4 November 2026

## Changes

These increments change the controller's verification protocol and agent context.
They do not change generated calculator source, dependencies, lockfiles, models or
the approved $3 Claude allowance.

| Commit | Change |
| --- | --- |
| `4939273` | Represent mixed acceptance criteria with explicit partial coverage; bind capability review caches to the exact claim and scenarios. |
| `116eb82` | Share browser capability facts across planning and review; stop identical rejected proposals after senior review. |
| `d9c635e` | Preserve malformed-response validation when an adapter lacks optional model metadata. |
| `e8e8a16` | Describe exact full-text assertion semantics; flag conflicting expectations for review; bind new quality reviews to their protocol. |
| `8f14754` | Keep QA errors and recovered completions within the current task revision; version handoffs for every provider. |
| `b087a6f` | Explain unique-target requirements and framework-provided accessibility roles. |
| `59d0197` | Carry revision/version into completion events; verify real adapter-to-QA trace recovery. |

All seven code increments were pushed to `main` and `codex/autonomous-coordinator`.

## Regression checks

All commands use `.venv\Scripts\python.exe -m pytest` with a unique `--basetemp`
under `artifacts` and `--tb=short`. Tests make no live provider requests.

| Test selection | Result | Exit code |
| --- | --- | --- |
| `test_autonomous_acceptance.py`, `test_acceptance_coverage.py`, `test_acceptance_review.py` | 45 passed | 0 |
| `test_autonomous_testing.py` | 29 passed, including mixed criteria and stale evidence rejection | 0 |
| Acceptance, coordinator, review and planning | 89 passed | 0 |
| `test_agents.py` before the metadata fix | 3 failed, 6 passed; `AttributeError: 'OllamaAgents' object has no attribute 'model_name'` | 1 |
| `test_agents.py`, `test_anthropic_model.py` after the fix | 19 passed | 0 |
| Scenario structure, review, coverage and acceptance after exact-text changes | 57 passed | 0 |
| Acceptance, agent handoffs and hybrid routing after revision isolation | 53 passed | 0 |
| Scenario structure and provider-response validation after targeting clarification | 29 passed | 0 |
| Real completion-event recovery and provider-response validation at the final code checkpoint | 20 passed | 0 |
| Complete suite at its starting code checkpoint | 611 passed, 3 failed | 1 |
| Last-failed recheck after the metadata fix | All 3 passed | 0 |

These selections overlap; their counts must not be added as unique tests. They report
13 upstream LangSmith/Python deprecation warnings.

The complete suite took 2,244.34 seconds. Its output is saved in
`artifacts/qa-fix-full-tests.txt`. The command was:

```powershell
.venv\Scripts\python.exe -m pytest -q --basetemp artifacts/pytest-qa-fix-full-01 --tb=short > artifacts/qa-fix-full-tests.txt 2>&1
```

All three failures were the metadata errors listed above: the two parameterized
incomplete-response cases and the provider-parse-failure case. After the fix,
`pytest --lf` selected those three and all passed. The complete 19-test provider
selection also passed, followed by the final 20-test selection including actual
completion-event recovery. The full run started before the metadata fix and later
protocol/context commits; **the complete suite was not rerun at the final revision**.

Initial test setup also encountered a Windows default temporary-directory permission
error. Tests were rerun with repository-local temporary directories. Two collection
commands referenced nonexistent `test_handoffs.py` and `test_hybrid_routing.py`; both
exited 1 without running tests. The corrected selection uses
`test_agent_handoffs.py` and `test_hybrid.py` and passed all 53 tests.

## Live saved calculator

Job: `ef36b963c2864188b8ee9b9eb950863d`.

The first managed retry froze an independent contract and ran real isolated checks.
TypeScript and production build passed. Four of five browser scenarios failed;
reload defaults passed. The failed reports exposed two contract defects:

- Single-row text was compared by exact equality against a complete results region.
  The page displayed the correct calculated amounts, but those expectations could
  not all match the same unchanged region.
- An unnamed alert target matched both an app error and Next.js's route announcer.

The controller also hit its complete-source repair-context limit before a source
edit or paid repair completion. The inspection checkpoint preserved that evidence;
the old frozen contract was not edited or weakened.

A fresh QA task revision was explicitly recorded with unchanged approved requirements
and source. Its reviewer rejected bare amount checks because they did not associate
amounts with their labels. The next QA completion could not be reserved within the
remaining approved allowance, so no further request was sent.

Current status: **AUTONOMOUS_TEST_PAUSED**. Recorded cost is **$2.657480 of $3**,
across 61 total requests for this saved run. This checkpoint added 24 requests and
$1.005732 to its prior ledger. The reservation limit is conservative: a positive
remaining dollar balance does not guarantee another full response can be reserved.

No complete application pass, preview approval, security result, CI publication or
deployment is claimed for this calculator. Generated source is unchanged. Build and
browser reports contain no cleanup errors; Docker queries found no remaining
job-owned containers or networks. Historical contracts remain readable.

The remaining validation is to finish an independently approved QA contract under
the corrected protocol, execute it, and inspect any real failures before source
repair. Further paid requests must stay within an authorized allowance; this work
did not increase that allowance.

Model proposals can still omit useful label/value associations, as the fresh review
demonstrated. The complete-source repair-context capacity pause also needs rechecking
after a valid new contract executes. These changes address controller inconsistencies
and context provenance; they do not establish reliable autonomous completion for
every small app or a complete end-to-end calculator pass.
