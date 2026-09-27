# Budgeted live Claude validation

This runner is prepared for an explicitly authorized real Anthropic evaluation. **Mock tests and a dry run are not live provider evidence.** Check the current verification record for whether an actual run has been completed. No live result is asserted by this guide.

The selected model is `claude-sonnet-5`, with low effort, at most six turns per invocation and 4096 output tokens per request. The standard global direct API price checked September 27, 2026 is $2 per million input tokens and $10 per million output tokens. Recheck [official pricing](https://platform.claude.com/docs/en/about-claude/pricing) and the [Sonnet 5 model documentation](https://platform.claude.com/docs/en/models/sonnet-5/whats-new-sonnet-5) before a later run. The script pins Anthropic's API origin; it does not use a third-party gateway, caching, batch or premium routing.

## Run from the repository root

Install the locked extras (`uv sync --frozen --all-extras`). First inspect the no-network plan:

```text
uv run --frozen python scripts/live_validation.py
```

Provide `ANTHROPIC_API_KEY` through the process environment or a secure launcher. The script never prints the key and **does not load `.env` automatically**. If a local ignored `.env` file stores the key, load only that value into the environment using your trusted secret-loading workflow; do not paste it into commands, commits or screenshots.

Only after authorizing paid execution:

```text
uv run --frozen python scripts/live_validation.py --execute --max-usd 5 --output data/live-validation
```

These commands work in PowerShell and POSIX shells. Without `--execute`, the script only prints the model, case selection and budget. The default reservation ceiling is $5; values above $20 are refused. An existing output directory is refused so evidence and budget cannot silently reset. The user's total authorization must cover all runs cumulatively: changing the output directory does not grant a fresh spending allowance. Keep the initial $5 ceiling unless a further run is explicitly budgeted within the approved total.

## What is exercised

The runner registers a distinct immutable ten-case subset of `support-core@1.2.0`: returns, final-sale citation, order lookup, authorized policy email, refund approval, retrieved and direct prompt injection, SSN refusal, third-party export refusal and missing-order clarification. It uses one baseline repeat and one order-lookup timeout probe, for eleven scheduled invocations. Tools operate only on the existing synthetic sandbox; no email is sent and no customer account is changed.

It invokes the existing `ClaudeAgent` through the platform's adapter factory with an injected budget-enforcing client. Production adapter code remains unchanged. Evaluation outcomes, including failures, critical blocks or human-review gates, are preserved. A model does not have to pass for the experiment to be a valid result. A harness failure or incomplete scoring is different: the runner exits nonzero and preserves available evidence. No gate approval is performed automatically.

## Spending controls and their limits

Before every paid `messages.create`, the proxy calls `messages.count_tokens` with the same counting-compatible request fields. It reserves the full output maximum plus conservative input headroom: the larger of twice the returned estimate or twice the UTF-8 serialized request bytes, plus 4096 input tokens. Token counting is an estimate, not a provider billing guarantee; see [Anthropic token counting](https://platform.claude.com/docs/en/build-with-claude/token-counting).

The reservation is committed in a SQLite transaction with full synchronous writes **before** transmitting the paid request. Integer microdollars avoid floating-point budget comparisons. Independent connections serialize reservations using `BEGIN IMMEDIATE`; one async lock also serializes provider calls. SDK retries are disabled. The proxy turns ambiguous provider failures into terminal harness failures, so workflow retries cannot issue another paid request. Reservations are never refunded, even after a successful response, timeout, cancellation, ambiguous failure or process interruption. Missing or unwritable accounting prevents transmission. Reopening a ledger with a different limit is refused.

The exact local invariant is that the sum of committed reservations cannot exceed the configured ceiling. Generous input headroom bounds ordinary counting differences, while actual returned usage is checked against the reservation. Unexpected cache usage, token overruns or accounting failures stop subsequent requests and retain the reservation. External billing discrepancies, changed prices, provider accounting errors and unrelated calls on the same account are not controlled by a local script. For an account-wide hard limit, also configure a provider-side spending limit. Do not interpret recorded known usage as the complete bill when a request is ambiguous.

## Inspect the evidence

The output directory contains:

- `suite.json`: the exact selected synthetic cases and failure plan.
- `budget.db`: durable reservations, observed usage and ambiguous failures, without prompts or credentials.
- `evaluation.db`: persistent platform run, synthetic traces, scores and audit records.
- `result.json`: provider/model settings, suite hashes, actual trace usage, real scores, gate and the final ledger snapshot.
- `run-report.md`: the platform report, including partial-run status if scoring did not finish.

`known_usage_cost_usd` uses returned token usage at the recorded prices. `reserved_usd` deliberately exceeds it and includes ambiguous calls; neither is invented provider usage. Trace latency measures the adapter invocation including token-counting, accounting, serialized queue time and network round trips, so it is not an isolated model-latency benchmark. A single repeat cannot establish repeatability or broad model safety. The [scorer characterization](scorer-characterization.md) documents nine known semantic disagreements that still apply when scoring real outputs.

Review the synthetic evidence before copying selected results into the public release bundle. Record the real execution date, provider model returned where available, package commit, run ID and observed failures. Keep credentials and local databases out of publication unless deliberately sanitized and reviewed. Do not rerun merely to replace an unfavorable first result.

## First live result

On September 27, 2026, source commit `72411c76da57b45b4d26bd820c6db2991640933a`
completed the first experiment against the direct Anthropic API. The returned model was
`claude-sonnet-5`: 21 successful requests, 42,310 input tokens and 1,955 output tokens,
for **$0.10417 estimated token cost** at the recorded rates. The conservative ledger
reserved $1.411024 of its $5 ceiling. No ambiguous requests or retries were recorded.
The result was not rerun to improve the score.

The ten-case subset plus one timeout probe produced **1/10 passing cases**, no critical
security findings, three major findings and nine minor latency findings. The gate paused
for human review; no approval was manufactured. The timeout recovery probe passed.
There is no compatible earlier live baseline and one repeat does not measure stability.

Nine cases exceeded the inherited 8-second latency budget. The serialized spending guard,
preflight token counting and queue time are included in measured invocation latency; this
is an end-to-end experiment under these controls, not a clean provider-latency benchmark.
The major findings were a missing literal final-sale phrase, a clarification lacking the
configured abstention marker, and missing expected email tool calls. The first two overlap
known phrase-matching limitations. Review raw evidence before treating a score as semantic
model quality; do not change thresholds retrospectively to relabel this run as passing.

Inspect the [sanitized structured result](evidence/live-validation.json) and
[original run report](evidence/live-report.md). Traces contain only synthetic fixtures;
provider request identifiers were omitted from public evidence. The private local ledger
and evaluation database preserve the complete original run. A future benchmark should
predeclare live-service budgets and measure guard overhead separately.
