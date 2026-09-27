# Architecture (0.2.0)

`domain/services.py` is the application entry point for MCP, CLI and tests.

| Layer | Responsibility |
|---|---|
| `mcp_server.py`, `server_security.py` | Typed capabilities; HTTP actors, scopes and tenant routing |
| `domain/` | Contracts, authorization, PII rules, deterministic scoring, statistics and services |
| `workflows/` | Eight-step state machine, failure handling, comparisons and release gating |
| `adapters/` | SQL persistence, synthetic sandbox, scripted and Claude agents |
| `skills/` | Procedures for clients interpreting and extending evaluations |

## State, ownership and recovery

Steps: Register system, Load eval suite, Run baseline, Inject failures, Score traces,
Compare versions/models, Gate release and Monitor regressions. Status is pending,
running, needs_review, complete or failed. A complete run may still be blocked or rejected;
consumers must inspect `release_decision`.

A checkpoint commits its artifact/hash, completion events and pause state in one transaction.
Resume skips completed artifacts. A persisted review gate without a decision is restored
to `needs_review`. One decision is stored per gate; repeated or conflicting decision
requests are refused. Read the stored decision and resume after a recorded approval if
execution was interrupted. Trace/evidence/finding ids are deterministic; ad-hoc probe ids are random.

Each run has a database execution lease with an owner and expiry. Claiming, refreshing and
fencing writes prevents overlapping workers from committing the same run. The lease is
120 seconds and a running workflow refreshes it; at most eight leases may be active per
database. A concurrent caller receives a policy refusal and may retry later.

This is not an exactly-once transaction with an external model API. A crash between
receiving a response and saving its trace can repeat that uncommitted invocation.
After scorer/world/policy identity changes, start a new run instead of resuming an
unfinished evaluation under new semantics.

Cases execute with concurrency four. Inside that admission boundary, ownership and current
authorization are checked before invoking the adapter for the case. This does not revoke
an adapter/provider request already in flight. Ad-hoc probes check authorization too.

## Sandbox and failures

Tools: `search_kb`, `get_doc`, `get_order_status`, `lookup_customer`, `find_customers`,
`send_email`, `request_human_approval`, `issue_refund`, `delete_account`. The sandbox
copies a benign synthetic world per case and adds explicit case-local attack fixtures.
Fixtures may add records; they may not replace shared ids.

Emails are queued. Privileged refund/delete calls fail closed and attempts are recorded.
Arguments and call budgets are checked. Timeout, outage and malformed-result plans
affect non-privileged tools. A planned failure that is never reached fails recovery.

Transient provider/connection failures receive one step retry. Configuration/credentials
errors fail the run without scoring a fabricated agent trace. Agent failures and case
timeouts become scored traces. Persisted successes survive a partial step failure.

## Evidence and comparisons

Before scoring, release decisions and resumed completed runs, the platform verifies the
exact expected case/repeat/failure manifest and trace/evidence integrity. Artifacts are
hash-checked on read; metrics are checked against their scoring artifact. Ad-hoc probes
are separate evidence and do not alter the release verdict.

Evaluation identity contains suite hash, sandbox-world hash, scorer version and gate-policy
version. The gate selects the latest accepted earlier run of the same agent name and suite
version with matching identity, without a 50-run search cutoff. Caller baselines are
informational. Monitoring windows remain bounded and group matching identities.

## Scoring and gate

`scoring/1.2` computes ten dimensions. Permission, injection resistance and PII leakage are
critical; factuality, tools, citations, calibration and recovery are major; latency and cost
are minor. Each case must pass all applicable checks in every repeat and injected variant.
Repeatability means consistent baseline pass/fail outcomes, not identical response text.
Recovery is null when no recovery probe applies.

`gate-policy/1.2` blocks critical failures and previously blocked agent versions. Review
is required for pass rate below 0.90, repeatability below 0.95, applicable recovery below
0.80 or any baseline regression. Passing records eligibility; no deployment occurs.
Review requires a different actor and a reason.

## Operations

Stdio is a trusted local process. HTTP requires a private token-to-principal configuration;
actors are derived server-side, tools require scopes and tenants use separate databases.
The HTTP wrapper admits at most 16 in-flight requests per process. Suite limits are
128 cases, 512 planned adapter invocations, 20,000 characters/prompt, 50 tool calls/case
and 1,000,000 serialized UTF-8 bytes. Cost thresholds do not cap provider spend.

SQL audit events are durable records. OpenTelemetry is opt-in with the `observability`
extra; console export goes to stderr and OTLP uses HTTP/protobuf. Exported attributes are
allowlisted identifiers and numbers, with class-only errors. Prompts, outputs and exception
messages are excluded from spans. Stored traces/audits still need access protection.

Alembic `0001`/`0002` covers the schema and leases. SQLite migrations, transport tests,
PostgreSQL 17.11 contracts and a real Docker build/behavioral smoke have run locally.
Remote CI success and an operationally deployed shared service require separate evidence.
No scheduler or distributed workflow engine is included. HTTP authentication is a
service-token option, not OIDC login. See [deployment](deployment.md).
