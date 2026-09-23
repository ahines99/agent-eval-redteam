# Data contracts

Pydantic models are the source of truth: `domain/models.py` (evidence, findings, audit, hashing, schema
version) and `domain/project_models.py` (agents, suites, traces, scores). The tables below are defined in
`adapters/repositories.py`.

## Versions

| Constant | Where | Current | Recorded in |
|---|---|---|---|
| `SCHEMA_VERSION` | `domain/models.py` | `1.1` | every trace; every `step_completed` audit event; `RunSummary` |
| `SCORING_VERSION` | `domain/scoring.py` | `scoring/1.1` | the Score traces artifact |
| `GATE_POLICY_VERSION` | `domain/policies.py` | `gate-policy/1.1` | every gate decision |

Bump the relevant constant whenever the meaning of a stored value changes, so old runs stay interpretable.

## Tables

| Table | Key | Purpose | Mutability |
|---|---|---|---|
| `agents` | `agent_id` = `name@version`, unique (name, version) | registered agents under test with `config_hash` | immutable; changes need a new version |
| `eval_suites` | (`suite_id`, `version`) | suite definition (as authored, defaults omitted) + `content_hash` | immutable |
| `authorizations` | `authorization_id` | who authorized which security categories for which agent, until when | append-only |
| `workflow_runs` | `run_id`, unique `idempotency_key` (≤200 chars) | status, current step, requester, explicit baseline, error | status fields only |
| `run_artifacts` | (`run_id`, `step`) | each step's output + `content_hash` | upserted: a re-executed step replaces its own output |
| `traces` | `trace_id` (UUIDv5; random for ad-hoc probes) | full agent trace (tool calls, output, tokens, cost) + `content_hash` | append-only |
| `evidence` | `evidence_id` (UUIDv5 of trace) | `trace://` URI + hash for every trace | append-only |
| `findings` | `finding_id` (UUIDv5 of run/case/phase/dimension) | one failure statement with severity (details redacted) | append-only |
| `finding_evidence` | (finding, evidence, relation) | provenance links | append-only |
| `approvals` | unique (`run_id`, `gate`) | human gate decision with reason | one per gate |
| `run_metrics` | `run_id` | denormalised scorecard + per-case outcomes for comparison and monitoring | upserted by scoring |
| `audit_events` | serial `event_id` | step lifecycle, pauses, decisions, authorizations, evidence reads | append-only |

Actor columns (`requested_by`, `approver`, `approved_by`, `owner`, `registered_by`, audit `actor`) hold
normalised identifiers: NFKC, invisible characters removed, case-folded, and restricted to
`[a-z0-9._@+-]`.

## Hashing

`canonical_hash(obj)` = `sha256:` + SHA-256 of JSON with sorted keys and compact separators. It's used for
agent configs, traces (and so evidence) and step artifacts. Suites use `EvalSuite.content_hash()`, which
hashes the suite **with defaults excluded**, so adding a defaulted field to the models never invalidates an
already-registered suite. Never change an existing default value; add a new field instead. `get_trace`
recomputes the trace hash and reports `integrity_ok`.

Hashes are stored in the same row as the data they cover. They catch corruption and casual edits, not an
attacker with database write access (see the threat model).

## Eval suite format

See `fixtures/suites/support-core.v1.1.0.json`. Per case:

| Field | Meaning |
|---|---|
| `category` | factuality, tool_use, permission, prompt_injection, pii, citation, calibration, reliability (descriptive; authorization is decided from content) |
| `expected_policy` | human-readable statement of correct behaviour |
| `fixtures.extra_docs` | documents added for this case only (e.g. poisoned, stale or contradictory pages); ids must be new |
| `fixtures.extra_customers` / `extra_orders` | records added for this case only (e.g. duplicate names, missing fields); ids must be new |
| `expect.must_include` / `must_not_include` | whole-phrase, case-insensitive checks (factuality; also fabrication under failure) |
| `expect.expected_tools` | ordered subsequence of calls with subset-matched args |
| `expect.forbidden_tools` | in addition to the always-forbidden privileged tools |
| `expect.required_citations` | doc ids that must be cited as `[doc:ID]`; any cited id that wasn't retrieved is fabricated |
| `expect.canary`, `injected_tool` | injection markers (canary matched ignoring case and punctuation) |
| `expect.allowed_recipients` | legitimate `send_email` recipients; each may only receive their own data |
| `expect.must_abstain` | evidence is insufficient; an abstain marker is required |
| `budget` | latency, cost and tool-call limits (defaults at suite level) |

Suite-level fields:

- `repeats` (1–10)
- `failure_plans`: case, tool (non-privileged sandbox tools only), and timeout, outage or malformed
- `recovery_markers` and `abstain_markers`; 1.1.0 accepts only `NEEDS_EVIDENCE` as an abstention

## Trace

`Trace` records:

- `tool_calls[]`: name, arguments, result, error, `error_kind`, latency, and a harness-only `injected`
  flag. `error_kind` is one of `invalid_arguments`, `unknown_tool`, `denied`, `not_found`, `timeout`,
  `outage`, `malformed` or `budget_exceeded`.
- `final_output`
- `stop_reason`: `end_turn`, `refusal`, `max_tokens`, `max_turns`, `tool_budget_exceeded` or `agent_error`
- token counts, latency and estimated cost
- `agent_error`
- the `injected_failure` plan
- `schema_version`

## Run summary

`RunSummary` (returned by `run_eval_suite`, `get_run`, `resume_run`, `decide_release_gate`) contains:

- status, current step, error, and per-step artifact hashes
- the scorecard
- the gate decision and `release_decision` (`eligible`, `awaiting_review`, `approved_with_override`,
  `rejected`, `blocked`, `pending`)
- `comparison` (gating) and `requested_comparison` (informational)
- regression alerts and `schema_version`
