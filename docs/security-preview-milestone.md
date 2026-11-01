# Security gates, prompt evaluation and local preview

## Actual evidence

Job: `07e271d4f5114709b559692ba801e63c`.
Source fingerprint remained
`997d56a247abcea27f1060b2ac01ba63502ff328c92bcb099c3305d1473f5ddb`.

Security report:
`artifacts/security/07e271d4f5114709b559692ba801e63c/2b4952def4a140558d30897eb414b670/report.json`.
Readiness report:
`artifacts/reports/07e271d4f5114709b559692ba801e63c/1cb2deff3215431f8077fb177e41e2db.json`.
Both are local runtime artifacts, excluded from Git.

| Check | Result | Scope |
| --- | --- | --- |
| Semgrep | Passed configured gate | Four local rules, generated source, offline |
| Secret patterns | No configured pattern findings | Selected key/token markers and unexpected .env files |
| npm audit | Zero reported advisories | Generated app lockfile including dev dependencies |
| pip-audit 2.10.1 | No reported advisories | Control-plane Python lockfile, no package execution/resolution |
| Prompt evaluation | Enforcement gate passed | Five fixed attacks, one allowed-action control |
| Synthetic writer escape | Blocked, sentinel unchanged | Real writer, temporary synthetic file |

The Semgrep rules were also exercised against four deliberately unsafe static fixtures.
All four expected rule IDs were reported; fixture code was not executed. Evidence:
`artifacts/semgrep-positive-controls.json`.

## Critical distinction: model behavior versus enforcement

Qwen proposed the malicious action in all five attack scenarios. The policy evaluator
denied each proposal. The legitimate source inspection was allowed. Model-proposed
tools were not executed by this evaluation harness, so those results are **dry-run
policy decisions**, not evidence of an attack executing and being contained afterward.

Separately, a deterministic regression invoked the real workspace writer against a
synthetic traversal attempt and verified its outside sentinel remained unchanged.
No real credentials were read. This small suite does not establish general prompt-
injection resistance or comprehensive cybersecurity coverage.

## Enforcement and reporting

Required missing/error checks become UNVERIFIED and block the security gate. Blocking
static/secret findings, npm high/critical advisories, and any Python advisories pending
severity review also block. npm lower severities remain reportable without blocking.
There is no automatic exception/suppression mechanism. Agent summaries cannot override
check statuses. Source modifications invalidate eligibility for preview until reverified.

Registry queries are separate network-enabled metadata operations. npm receives package
inventory; pip-audit queries Python advisory metadata. Semgrep receives read-only source
mounts and runs without network. Security tooling is pinned in `security/tools.lock.txt`
and an immutable scanner image digest; tools are separate from the app environment.

## Preview lifecycle

The human explicitly authorized local preview in chat. The CLI recorded approval and
started a non-root, resource-limited app container. Source is mounted read-only, copied
to disposable tmpfs, and rebuilt without public network connectivity. No host credentials
or Docker socket are mounted. Database data is disposable and lost on preview stop.

This Docker engine did not provide host mappings for the initial internal-only network
configuration. That failed preview was cleaned up. The working topology is:

```text
Browser -> 127.0.0.1:<assigned port> -> trusted fixed-target HTTP proxy
                                            |
                                  internal Docker network
                                            |
                                   generated app :3000
```

Only trusted proxy code runs on the host-facing bridge. It forwards to one fixed app
identity and rejects CONNECT tunneling. The generated app has no default route. A
trusted runtime probe confirmed a public HTTPS request from the app failed. This is
one observed connectivity check, not proof of every network isolation property.
Container network controls do not constrain JavaScript running in the user's browser.

Both containers use approximately 30-minute expiry, read-only roots, dropped capabilities,
no privilege escalation, capped logs and process limits. The app has 6 GiB/4 CPUs; the
proxy 128 MiB/1 CPU. Stop validates Docker ownership labels before removing resources.
Stop/cleanup and a subsequent restart were exercised. Startup logs, container identity,
loopback port and smoke-test results are recorded. Root and task-list routes returned 200.
Empty Docker networks may remain after expiry until status/stop reconciliation.

The final preview at this milestone used port 56471; it is temporary, not a permanent URL.
No cloud deployment occurred.

## Readiness and upcoming dashboard

The Readiness Agent produces setup/deployment notes. Deterministic reporting includes
actual evidence, source revision, environment defaults and known limitations. It does
not claim universal security, production readiness or deployment. Report events do not
overwrite the running preview's lifecycle status.

Workflow events now have monotonically increasing sequence IDs, enabling the next
milestone's resumable real-time event stream. The planned dashboard will provide:
request intake, clarification forms, requirements/plan review, human approvals, agent
timeline, bounded repair progress, test/security reports, preview open/stop, and source
location. No terminal knowledge should be required for the normal workflow.

Remaining work includes authenticated control decisions, concurrency protection and
cancellation, browser UI validation, stronger model comparison, remote PostgreSQL,
GitHub CI/publishing and optional Vercel deployment. The known generated form/API
description-validation mismatch is still disclosed in the earlier milestone report.
