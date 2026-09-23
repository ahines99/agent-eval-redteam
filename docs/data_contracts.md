# Data contracts

Pydantic models are the source of truth: `domain/models.py` (evidence, findings, audit) and
`domain/project_models.py` (agents, suites, traces, scores). The tables below are defined in
`adapters/repositories.py`.

## Tables

| Table | Key | Purpose | Mutability |
|---|---|---|---|
| `agents` | `agent_id` = `name@version`, unique (name, version) | registered agents under test with `config_hash` | immutable; changes need a new version |
| `eval_suites` | (`suite_id`, `version`) | suite definition + `content_hash` | immutable |
| `authorizations` | `authorization_id` | who authorized which security categories for which agent, until when | append-only |
| `workflow_runs` | `run_id`, unique `idempotency_key` | status, current step, requester, error | status fields only |
| `run_artifacts` | (`run_id`, `step`) | each step's output + `content_hash` | written once per step |
| `traces` | `trace_id` (UUIDv5) | full agent trace (tool calls, output, tokens, cost) + `content_hash` | append-only |
| `evidence` | `evidence_id` (UUIDv5 of trace) | `trace://` URI + hash for every trace | append-only |
| `findings` | `finding_id` (UUIDv5 of run/case/phase/dimension) | one failure statement with severity | append-only |
| `finding_evidence` | (finding, evidence, relation) | provenance links | append-only |
| `approvals` | unique (`run_id`, `gate`) | human gate decision with reason | one per gate |
| `run_metrics` | `run_id` | denormalised scorecard + per-case outcomes for comparison and monitoring | upserted by scoring |
| `audit_events` | serial `event_id` | every step start/completion/retry/failure, pause, decision, authorization | append-only |

## Hashing

`canonical_hash(obj)` = `sha256:` + SHA-256 of JSON with sorted keys and compact separators. It's used for
agent configs, suite definitions, traces (and so evidence) and step artifacts. `get_trace` recomputes it
and reports `integrity_ok`.

## Eval suite format

See `fixtures/suites/support-core.v1.0.0.json`. Per case:

| Field | Meaning |
|---|---|
| `category` | factuality, tool_use, permission, prompt_injection, pii, citation, calibration, reliability |
| `expected_policy` | human-readable statement of correct behaviour |
| `fixtures.extra_docs` | documents added to the sandbox for this case only (e.g. poisoned or stale pages) |
| `expect.must_include` / `must_not_include` | normalised substring checks (factuality; also fabrication under failure) |
| `expect.expected_tools` | ordered subsequence of calls with subset-matched args |
| `expect.forbidden_tools` | in addition to the always-forbidden privileged tools |
| `expect.required_citations` | doc ids that must be cited as `[doc:ID]`; any cited id that wasn't retrieved is fabricated |
| `expect.canary`, `injected_tool` | injection markers |
| `expect.allowed_recipients` | legitimate `send_email` recipients |
| `expect.must_abstain` | evidence is insufficient; an abstain marker (e.g. `NEEDS_EVIDENCE`) is required |
| `budget` | latency, cost and tool-call limits (defaults at suite level) |

Suite-level: `repeats` (1-10), `failure_plans` (case, tool, timeout|outage|malformed), and
`recovery_markers`/`abstain_markers`.

## Trace

`Trace` records `tool_calls[]` (name, arguments, result, error, `error_kind`, latency, and a
harness-only `injected` flag), `final_output`, `stop_reason` (`end_turn`, `refusal`, `max_turns`,
`tool_budget_exceeded`, `agent_error`), token counts, latency, estimated cost, `agent_error`, and the
`injected_failure` plan.
