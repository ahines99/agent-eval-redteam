# Data contracts

Pydantic models in `domain/models.py` and `domain/project_models.py` define runtime
contracts. SQLAlchemy tables live in `adapters/repositories.py`; migrations are frozen
in `migrations/versions/`. This describes application version 0.2.0.

| Version | Current | Purpose |
|---|---|---|
| `SCHEMA_VERSION` | `1.2` | Trace/run summary and completion-event interpretation |
| `SCORING_VERSION` | `scoring/1.2` | Scoring artifact and evaluation identity |
| `GATE_POLICY_VERSION` | `gate-policy/1.2` | Gate decisions and evaluation identity |
| Alembic revision | `0002` | Initial SQL schema plus execution leases |

Schema labels and migration revisions serve different purposes. Increment semantic
versions when interpretation changes; create migrations when SQL schema changes.

## Persistence

| Table | Key / behavior |
|---|---|
| `agents` | `agent_id=name@version`; immutable specification/config hash |
| `eval_suites` | Suite id/version; immutable authored definition/hash |
| `authorizations` | Authorization id; agent, categories, approver, reason and expiry |
| `workflow_runs` | Run id; unique optional idempotency key, status, requester and suite |
| `execution_leases` | Run id; owner and expiry, used to fence workflow writes |
| `run_artifacts` | Run/step; hashed checkpoint payload |
| `traces` | Deterministic release id, random ad-hoc id; JSON body/hash |
| `evidence` | Evidence id; trace URI and matching hash |
| `findings` | Run/case/phase/dimension id; severity and redacted statement |
| `finding_evidence` | Finding/evidence/relation links |
| `approvals` | Unique run/gate; decision, actor, reason, override flag |
| `run_metrics` | Run id; scorecard/case outcomes checked against score artifact |
| `audit_events` | Serial id; workflow, authorization, decision and evidence-read events |

Checkpoints atomically write artifacts, completion events and pause state. Application
operations preserve evidence/decisions; database administrators can still modify tables.
Hashes are not signatures or external immutable anchors.

Actor ids are NFKC-normalized, stripped of invisible format characters, case-folded and
restricted to ASCII identifiers. HTTP replaces caller actor fields with its authenticated
principal; stdio trusts its caller. Idempotency keys are 1–200 characters and cannot be
reused with different run parameters.

## Suite expectations

See `fixtures/suites/support-core.v1.2.0.json`. Published 1.0.0/1.1.0 JSON files remain
unchanged; new assertions belong in a new version.

| Field | Meaning |
|---|---|
| `category` | Reporting label; authorization additionally examines content |
| `expected_policy` | Human-readable behavior; not an executable assertion |
| `fixtures.extra_docs/customers/orders` | Case-local records with new ids |
| `expect.must_include/must_not_include` | Whole-phrase output checks; calibration includes required clarification phrases |
| `expect.expected_tools[].name/args` | Ordered call subsequence; argument subset match |
| `expected_tools[].args_contains` | Required phrases in named arguments, such as email body |
| `expected_tools[].result_contains` | Required phrases in serialized tool results |
| `expected_tools[].require_success` | Successful non-null result with no recorded error |
| `expect.forbidden_tools` | Additional forbidden attempts beyond refund/delete |
| `expect.required_citations` | Required `[doc:ID]` references; cited ids must be retrieved |
| `expect.canary/injected_tool` | Injection outcome signals |
| `expect.allowed_recipients` | Allowed email destinations, each restricted to its own customer's data |
| `expect.must_abstain` | Abstention marker plus all required clarification assertions |
| `budget` | Scored latency/cost thresholds; enforced tool-call count |

Repeats range from 1–10. Failure plans name a case, non-privileged tool and timeout,
outage or malformed response. An untriggered probe fails recovery. Suite 1.2.0 requires
explicit `NEEDS_EVIDENCE` abstention. Suite hashes exclude defaults; do not change old
field defaults casually, because that can change behavior without changing authored content.

## Evidence and identity

`canonical_hash` is SHA-256 over canonical JSON. Release traces record run/case/phase/repeat,
agent/model, tool calls/results/errors, final output, stop reason, tokens, latency,
estimated cost, failure plan and schema version. Evidence uses `trace://<trace_id>`.
All expected traces must exist and match identities/hashes before release scoring.
`get_trace` returns stored hash, evidence id and `integrity_ok` for inspection.

Loading/scoring artifacts record `evaluation_identity`: suite hash, world hash, scorer
version and gate-policy version. Comparisons need matching identity for `comparable=true`.
Historical results without matching identity are not current release baselines and are
not automatically rescored.

## Returned run and scorecard

`RunSummary` contains status, step/error, per-step hashes, scorecard, gate, release decision,
gating `comparison`, informational `requested_comparison`, alerts and schema version.
Release decisions are `eligible`, `awaiting_review`, `approved_with_override`, `rejected`,
`blocked` or `pending`.

Pass rate counts complete cases and includes a Wilson 95% interval. Dimension rates count
applicable trace checks. Repeatability measures consistent baseline pass/fail outcomes.
Recovery is nullable when no probe applies. Reports include baseline p95 latency and
aggregate estimated cost; neither is a production service guarantee.
