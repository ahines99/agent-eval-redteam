**Repository audit — September 27, 2026**

Current finalization status: [verification record](../../VERIFICATION.md). This document preserves its assessment-time evidence and remaining-work list.

Historical audit of commit `231bdf9`. All 16 findings are now addressed; see [the remediation and verification record](RESOLUTION.md). The reproduction scripts in this directory target the audited revision; current regression tests are the remediation evidence.

The repository contains a working local evaluation MVP, with substantial tests and documentation. It is not ready to serve as a trusted release-control service. This review reproduced 16 defects: seven P1, eight P2, and one P3. Several can produce false passing results; others break authorization timing, regression comparison, or recovery. Passing the current test suite does not establish the stronger guarantees claimed in the handoff.

Recommendation: repair the P1 findings and evidence/workflow integrity findings before treating release decisions as authoritative. Continue using the offline demo for development. Keep shared deployment behind a separate readiness gate covering authenticated identities, authorization, tenant isolation, migrations, and operational validation.

Scope was the current `audit-fixes` checkout at `231bdf9`, all 48 tracked files, relevant prior context, code, fixtures, tests, packaging, documentation, and four repository Skills. Five agents participated: the coordinating agent handled integration/packaging and independent reproduction; four specialist agents reviewed security, scoring/statistics, workflow/persistence, and documentation/readiness. The security specialist supplied interim findings but its final response failed; the coordinating agent independently reproduced the security findings included here. No paid model requests, external deployments, merges, or implementation fixes were performed. Only this report and its reproduction scripts were added.

P1 means fix before trusting evaluation/release enforcement; P2 means material correctness, integrity, or reliability work; P3 means lower-impact usability work. These are engineering priorities, not CVSS ratings. Deployment prerequisites are listed separately rather than counted as new defects.

**Verified state and existing implementation**

| Area | Current evidence |
|---|---|
| Git | `audit-fixes`, six commits ahead of `main`; no commits unique to `main`; no remote configured; working tree clean before audit artifacts |
| Python 3.14.5 | 156 tests passed; Ruff passed; mypy passed across 21 source files |
| Coverage | 2,225 measured statements, 81 missed: 96% rounded line coverage; branch coverage was not measured |
| Fresh Python 3.12 | Created isolated venv, installed noneditable `.[dev,claude]`, built wheel successfully, 156 tests passed |
| Fresh dependency resolution | Included MCP 2.2.0, Anthropic 1.8.0, SQLAlchemy 2.1.1, Pydantic 2.13.5; successful resolution is a snapshot, not a lockfile |
| Installed package | Console demo succeeded outside the source directory, exercising packaged JSON fixtures |
| Offline controls | Hardened 35/35 and eligible; flaky 25/35 and review; naive 1/35 and blocked with 17 critical findings |
| Real stdio transport | 14 tools discovered; hardened 35/35 run; disk-backed SQLite retained the run across server restart; repeated idempotency key returned original run |
| Real local HTTP transport | Fresh installed package served through Uvicorn on loopback; MCP health and 14-tool discovery succeeded; server terminated after check |
| Application | Eight workflow steps; SQLite repository; PostgreSQL dialect/configuration support; typed registration, authorization, traces, findings, comparisons, approvals and reports |
| Evaluation | Ten trace-scoring dimensions; outcome repeatability, Wilson interval, p95, regression history; two bundled suites of 31 and 35 cases; nine sandbox tools; three scripted controls; Claude adapter |
| MCP and guidance | 14 tools, four resource definitions, three prompts, four distinct procedural Skills, architecture/data-contract/threat-model documents |

The global Python environment initially could not import the package directly because it was not installed there; tests add `src` to the import path. The bare Python 3.12 installation also lacked MCP. Those were environment setup conditions, not repository defects: the fresh installation resolved them.

Current tests exercise ordinary retries, partial baseline recovery, control outcomes, immutable versions, many policy refusals, in-process MCP, and fake-provider calls. Important uncovered dimensions are competing workers, crashes between database writes, partial/corrupt evidence, alternative PII representations, and whether the declared expected behavior is actually asserted.

**Reproduced findings**

**A01 — P1: concurrent resumes execute the same agent work twice.**

Locations: `src/agent_eval_redteam/domain/services.py:193`, `workflows/base.py:66`, `workflows/primary.py:128`.

Two concurrent `resume_run` calls both see incomplete work. Neither obtains an atomic execution lease. Reproduction produced 196 adapter calls for 98 stored traces and two `run_completed` events. Stable IDs prevent duplicate final rows in this example, but do not prevent duplicate paid requests, excess concurrency, or competition between nondeterministic outputs. This occurred within one process, so it is not limited to a future distributed deployment.

Fix: acquire a database-backed run lease with ownership/fencing; reject or report an active executor and recover only expired ownership. Add simultaneous-resume, start/resume, and stale-worker tests. Evidence: `repro_workflow.py`, `CONCURRENT` output.

**A02 — P1: 50 newer nonaccepted runs erase regression protection against an older accepted baseline.**

Location: `src/agent_eval_redteam/workflows/primary.py:309`.

The comparison selects the newest 50 scored runs before looking for an accepted run. With one accepted baseline followed by 50 review results, the next candidate gets `baseline_run_id=None` and reports that no earlier accepted run exists. The fixture reproduction seeds valid review-state rows directly to avoid running 50 redundant suites. This proves skipped regression comparison; the demonstrated candidate still needs review for its independent threshold failures.

Fix: filter accepted runs before applying limits, or paginate until an eligible baseline is found. Test accepted baselines behind more than 50 review/rejected/blocked results. Evidence: `repro_workflow.py`, `BASELINE_WINDOW`.

**A03 — P1: queued agent calls continue after security authorization expires.**

Locations: `src/agent_eval_redteam/workflows/primary.py:128`, `:172`, `:188`.

Authorization is checked at the beginning of an agent-calling step, not immediately before each queued invocation. An eight-case security suite with a one-hour authorization and a controllable clock ran all eight cases; seven calls began after expiry. This contradicts the per-call guarantee in README/handoff text.

Fix: revalidate the relevant case authorization after acquiring the concurrency semaphore and immediately before invoking the adapter, including retries. Specify separately what happens to a call already in flight when its authorization expires. Evidence: `repro_authorization.py`, `expiry calls=8 after_expiry=7`.

**A04 — P1: a shared attack fixture is reachable without security authorization.**

Locations: `src/agent_eval_redteam/domain/policies.py:105`, `fixtures/world.json` order `O-5004`.

`required_authorizations` inspects the case's prompt and extra fixtures but not attack content already in the shared sandbox world. A factuality case asking for O-5004's status needs no authorization. A production-registered naive control then receives the planted instruction, attempts `issue_refund`, and echoes its canary. The sandbox still denies the refund: this is a test-authorization/production-label boundary violation, not a real refund or compromise of a live production system.

Fix: move attack-bearing records into explicitly classified per-case fixtures, or attach/enforce security metadata on all shared records the case can reach. Add a production-registered lookup test. This is a concrete built-in fixture gap, beyond the documented possibility that arbitrary prompt classifiers miss some attacks. Evidence: `repro_authorization.py`, `shared_world`.

**A05 — P1: duplicate customer email addresses remove secrets from the PII inventory.**

Location: `src/agent_eval_redteam/adapters/sandbox.py:163`.

`sensitive_by_owner` uses a dictionary comprehension keyed by email. An additional customer with a new ID but an existing email overwrites the original customer's sensitive-value list. Registration accepts the fixture. In the reproduced case, printing the original customer's synthetic phone number passes the PII scorer after adding a different phone under that email.

Fix: preserve the union of sensitive values and model ownership by stable customer identity; handle shared email addresses explicitly. Do not let fixture additions reduce the protected inventory. Test both final-output and outgoing-email detection. Evidence: `repro_owner.py`, `PII SAME EMAIL ... True`.

**A06 — P1: numeric PII normalization loses detectable secrets.**

Locations: `src/agent_eval_redteam/domain/pii.py:171`, `domain/scoring.py:168`.

The fixture values `000/12/3456`, `4111/1111/1111/1111`, and `212/555/0142` all pass PII scoring. Slash separators evade the current normalization. Separately, placing an SSN, phone, and card together using spaces can merge their digits into one long run; `leaked_values` then returns an empty list. The earlier fix for accidental substring matches introduced a different boundary problem.

Fix: use separator-aware matching that preserves individual value boundaries; retain negative tests for unrelated longer identifiers. Cover slashes, adjacent values, punctuation, Unicode formats and actual outgoing messages. Evidence: `repro_scoring.py` and `repro_authorization.py` (`adjacent_numeric_values []`).

**A07 — P1: outgoing-email PII checks miss recipient-embedded and nonfixture secrets.**

Location: `src/agent_eval_redteam/domain/scoring.py:177`.

PII scoring passes a `send_email` body containing an SSN-shaped value outside the fixture inventory, because generic detection is applied to final output rather than the email payload. It also passes a recipient local part containing the fixture SSN, with a harmless subject/body, because the recipient field is not scanned as content. These examples are isolated synthetic tool traces; no messages were sent.

Fix: apply fixture and generic sensitive-data detection to all egress fields, distinguishing a legitimate recipient address from sensitive content embedded in it. Define which other tool arguments count as protected sinks. Evidence: `repro_scoring.py`, `PII-TOOL` email examples. The separate `request_human_approval` example is an additional sink-policy question, not required to establish this finding.

**A08 — P2: scoring accepts incomplete evidence and can make a full-suite run eligible.**

Location: `src/agent_eval_redteam/workflows/primary.py:232`.

Scoring rejects zero traces, but does not validate the expected case/repeat/failure manifest. After stopping before scoring and deleting 97 of 98 stored traces, resume returned `complete`, `eligible`, and `n_cases=1` for the 31-case suite. Completed baseline/injection artifacts prevented regeneration. This requires corrupted/missing stored data or an inconsistent restore; there is no public trace-deletion tool.

Fix: require an exact expected trace manifest, with correct phase/repeat/agent/failure-plan identities and linked evidence, before computing metrics. Explicitly exclude ad-hoc probes from release-scoring input. Evidence: `repro_workflow.py`, `MISSING_TRACES`.

**A09 — P2: the verdict path ignores an existing failed integrity check.**

Locations: `src/agent_eval_redteam/workflows/primary.py:235`, `workflows/base.py:67`, `domain/services.py:271`.

After changing one stored trace body without updating its hash, `get_trace` correctly returned `integrity_ok=False`. Resuming scoring still completed and marked the run eligible. Existing step artifacts also load without verifying their content hashes. The reproduced trace edit was benign appended text, demonstrating consumption of known-inconsistent evidence rather than claiming a particular adversarial verdict change.

Fix: validate trace, evidence and artifact hashes whenever they are consumed for resume, scoring, comparison or gating. Fail with an integrity error. This work is separate from deferred HMAC signing: ordinary existing hashes are sufficient to detect this example. Evidence: `repro_integrity.py`.

**A10 — P2: a crash after gate persistence strands human review.**

Locations: `src/agent_eval_redteam/workflows/base.py:92`, `domain/services.py:198`.

The gate artifact, audit event and `needs_review` status commit separately. Simulated process death after saving the review artifact leaves the run `running`. Resume skips the stored gate and finishes with `status=complete`, `release_decision=awaiting_review`, no approval, and monitoring executed. A subsequent legitimate gate decision is refused because the run is complete. This does not make the release eligible; it makes review unresolvable through the public workflow.

Fix: atomically persist the step artifact, completion event and next state, and reconstruct unresolved review requirements from the gate artifact on every resume. Test faults between persistence operations, not only exceptions inside step functions. Evidence: `repro_workflow.py`, `CRASH_GATE`.

**A11 — P2: recovery scoring accepts an affirmative unsupported answer.**

Location: `src/agent_eval_redteam/domain/scoring.py:239`.

For `tool-order-delivered`, a malformed injected order result followed by “The service is unavailable, but your order was delivered.” passes the entire case. The scorer exempts `delivered` from fabrication checks because that word appeared in the question. An exemption intended for honest uncertainty also permits an assertion.

Fix: define explicit recovery answer contracts or assertion-aware checks, covering both echoed uncertainty and affirmative claims. Evidence: `repro_scoring.py`, `RECOVERY-FABRICATION True`.

**A12 — P2: an unexercised failure probe with no answer passes.**

Locations: `src/agent_eval_redteam/domain/scoring.py:93`, `:233`, `:253`; `domain/stats.py:68`.

A planned timeout trace with no calls and an empty response passes `tool-order-status`. Normal dimensions are disabled because a failure was planned; recovery becomes inapplicable because the agent never triggered it. If no probes trigger, recovery rate can be `None` and the gate skips that threshold.

Fix: preserve ordinary expectations when an injection does not occur; track required-probe coverage separately and prevent an unexercised probe from being labeled successful recovery. Evidence: `repro_scoring.py`, `UNTRIGGERED True`.

**A13 — P2: the email-policy fixture does not test whether the right message was sent.**

Locations: `src/agent_eval_redteam/fixtures/suites/support-core.v1.1.0.json:292`, `domain/scoring.py:113` (also present in suite 1.0.0).

Actual sandbox calls that search an irrelevant query, look up C-1002, and queue an email saying “Buy crypto” to the expected recipient pass the full email-policy case. The declared task is to email the return policy, but the assertions check tool sequence and recipient, not message content or successful policy retrieval.

Fix: add structured assertions for outgoing content and supporting retrieval. Review other fixture assertions against their stated policy: delivery date, free exchanges, and requesting a missing order ID are examples needing closer coverage. Publish changed fixtures as a new suite version. Evidence: `repro_scoring.py`, `WRONG EMAIL True`.

**A14 — P2: monetary matching accepts a materially different amount.**

Location: `src/agent_eval_redteam/domain/scoring.py:39`.

`fact-free-shipping` accepts “Free over $75,000.” as satisfying `$75`. The negative word boundary also permits `$75.99`. Existing tests cover `$750`, but punctuation ends the current match.

Fix: parse numeric/currency tokens or implement numeric boundaries separately from word boundaries; test decimals, thousands separators and equivalent correct formats. Evidence: `repro_scoring.py`, `WRONG AMOUNT True`.

**A15 — P2: context-window truncation is treated as a normal completed response.**

Locations: `src/agent_eval_redteam/adapters/claude_agent.py:140`, `domain/scoring.py:32`.

The adapter preserves non-tool stop reasons, but the abnormal-stop set omits `model_context_window_exceeded`. A calibration trace containing `NEEDS_EVIDENCE` with this stop reason passes, and recovery is marked inapplicable. Anthropic documents this stop reason as context-limit truncation, including on newer models without a beta header. This is a deterministic fake-response/scoring reproduction, not a live-provider observation. [Official stop-reason documentation](https://platform.claude.com/docs/en/build-with-claude/handling-stop-reasons).

Fix: classify supported truncation reasons explicitly and fail closed on unsupported/incomplete outcomes; add fake-SDK contract tests. `pause_turn` is also worth defensive handling if server tools are introduced, but those tools are not configured now, so it is not counted as an independent current defect. Evidence: `repro_stops.py`.

**A16 — P3: repeating the demo with the same persistent database crashes.**

Locations: `src/agent_eval_redteam/cli.py:49`, `:59`.

`agent-eval demo --db sqlite:///...` succeeds once, then exits 1 on the second invocation. Its fixed idempotency keys return the already rejected candidate, after which the demo unconditionally tries to reject it again. The error is “run is complete; only runs waiting at the gate take a decision.” Default in-memory demo usage is unaffected.

Fix: reuse recorded decisions when reusing demo runs, or deliberately namespace each demo session. Reproduction: run the CLI twice against the same fresh temporary SQLite filename.

**Remaining work beyond these defects**

| Priority / trigger | Work that remains | Evidence / acceptance criterion | Who does what |
|---|---|---|---|
| Before shared deployment | Authenticated, server-derived requester/approver/reader identities; per-tool roles; tenant isolation | Explicit gaps in `docs/threat_model.md:41` and handoff. A login proxy alone does not bind tool argument names to authenticated users | User selects deployment and identity provider; agent implements identity binding, scopes and isolation tests |
| Before operational database use/schema evolution | Alembic migrations, upgrade/rollback or recovery plan, PostgreSQL integration tests, backup/restore verification | Current schema uses `create_all`; common tests use in-memory SQLite | Agent implements after supported deployment database is selected |
| Next engineering batch | CI on Python 3.12 and 3.14; test/lint/type/build/installed-package checks; coverage tooling and threshold | No tracked CI; `README.md:88` claims “every CI run”; dev extra does not include coverage tooling | Agent |
| Next engineering batch | Lock or constraints for application/test environments; dependency review | Broad version ranges and no lock/constraints/scanning config | Agent; preserve library metadata ranges as appropriate |
| Next engineering batch | Committed stdio process, HTTP, SQLite restart, PostgreSQL and concurrent-worker tests | Manual checks here passed, but current tracked MCP tests use in-process `Client(mcp)` | Agent |
| Before material paid evaluations/shared use | Global run/case limits, bounded spend and concurrency, cancellation behavior | Threat model explicitly defers resource-exhaustion limits; case tool/turn caps do not bound total run spend | Agent proposes limits; user sets spend ceiling |
| Before claiming live-provider readiness | One bounded real Claude evaluation, with selected model and explicit budget; capture request/response usage and configuration | Live path currently covered by fake clients only | User supplies approved credentials/model/budget; agent runs validation |
| Operational deployment | OpenTelemetry SDK/exporter setup, useful cost/tool/error attributes, exporter tests and runbook | Hooks default to no-op; handoff says more fields are present in spans than code emits; audit tests do not verify spans | Agent; user selects telemetry destination if needed |
| Publication/demo polish | Dockerfile/Compose and verified image, deployment/runbook instructions, three-minute script and recording | Missing files; handoff explicitly leaves these open | Agent prepares image/script/docs; user chooses recording/publication |
| Publication | License, repository remote, project URLs and release/versioning process | No LICENSE, remote or project URL metadata | User selects license/hosting; agent adds configuration and release artifacts |
| Documentation repair | Replace unqualified completion claims; update 146-test README count to 156; document command that measures coverage; explain scorer limits | README, handoff and Skills repeat per-call/resume guarantees disproved above | Agent, alongside implementation fixes |
| Deferred by prior decision | Signed or externally anchored evidence | Documented HMAC/signature deferral; does not excuse A09's missing verification | Keep deferred for local trusted storage; revisit before sharing mutable evidence storage |
| If real data is introduced | Retention, access review, encryption and redaction design | Current sandbox is synthetic; traces store raw model output | User establishes data scope; agent implements appropriate controls |

Deterministic grading is reproducible, but these keyword/provenance proxies do not establish general semantic factuality. Repeatability measures equal pass/fail outcomes, not identical answers. Controls tailored to the same fixtures are useful regression checks, but do not independently calibrate the scorers. Document these limitations and add independently authored challenge traces.

The code architecture is coherent for a local MVP. There is no need to replace it with a generalized agent framework to address this backlog. Most urgent work belongs in boundary validation, transactional workflow execution and stronger test oracles.

**Recommended sequence and ownership**

1. Agent engineering: repair A01–A07, then A08–A10; add regression tests reproducing each failure before its fix. Acceptance: single execution ownership, authorization checked per queued call, preserved baseline, no demonstrated PII bypasses, verified complete evidence, and recoverable human gates.
2. Agent engineering: repair A11–A16, strengthen expected behavior and publish a new suite version. Version changed scoring/gate behavior; keep old results interpretable.
3. Agent engineering: add CI, dependency constraints, installed-package/process/database checks, operational documentation, and correct completion claims.
4. User decision: choose local portfolio tool versus shared service. Recommendation: finish the local correctness work first; defer shared deployment until identity and tenant controls have explicit tests.
5. User decision: choose live model and maximum spend, repository hosting/license, and whether signed evidence remains deferred. No paid validation is necessary to fix the reproduced defects.
6. Review and merge: the existing branch is structurally mergeable into `main`, but merging alone does not resolve this audit. Recommendation: land the repairs with reviewable tests, then merge as an explicitly scoped local MVP. Do not label it deployment-ready based on the current green suite.

No immediate clarification is required to begin the engineering fixes. The user decisions above become prerequisites only for publishing, spending money, or shared deployment.

**Reproduction and verification notes**

Run from the repository root in an environment with the dev dependencies installed:

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
python -m pytest -q -p no:cacheprovider
python -m ruff check src tests
python -m mypy src
python docs/audits/2026-09-27/repro_workflow.py
python docs/audits/2026-09-27/repro_scoring.py
python docs/audits/2026-09-27/repro_owner.py
python docs/audits/2026-09-27/repro_authorization.py
python docs/audits/2026-09-27/repro_integrity.py
python docs/audits/2026-09-27/repro_stops.py
```

The reproduction scripts use in-memory SQLite, fixture data and scripted/fake behavior. They print observations and deliberately exercise failure paths; they are audit evidence, not a replacement for assertion-based regression tests. Expected logged exceptions in the workflow/integrity scripts deliberately stop before scoring. They neither call a paid model nor send email. The missing/corrupt-evidence examples intentionally mutate only the in-memory audit database.

Coverage was measured with separately available `pytest-cov` using `--cov=agent_eval_redteam --cov-report=term-missing`. The report's fresh Python 3.12 test run used the newly installed dependencies, but pytest's configured `src` path means that run tested checkout source; the separate console demo outside the checkout verified the installed wheel and bundled resources.

Not verified: actual Anthropic API behavior/spend, PostgreSQL execution, Docker image behavior, production authentication or load, real-data controls, branch coverage, or absence of all possible vulnerabilities. The current official model/effort documentation was consulted to avoid incorrectly labeling valid supported model IDs as defects; no model migration is required by this audit. [Official effort compatibility](https://platform.claude.com/docs/en/build-with-claude/effort), [model overview](https://platform.claude.com/docs/en/models/overview).
