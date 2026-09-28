# Repeated live-model study

This is a predeclared integration and exploratory comparison study, not a population model-quality
benchmark. The [original experiment](live-validation.md), its thresholds and first unfavorable result
remain unchanged. The new [configuration](../benchmarks/live-experiment.v1.json) selects two pinned
models, three interleaved rounds and the same ten synthetic support cases. Each round includes two
order-tool failure probes (`timeout` and `malformed`), giving **72 scheduled invocations**. Each
invocation can make up to six paid requests; an invocation is not an API request.

## Configuration and pricing

The model profiles are `claude-sonnet-5` with low effort and `claude-haiku-4-5-20251001` without an
effort parameter. The exact system prompt, tool definitions, fixture world, cases, prices, settings,
source commit, runtime source identities, dependency lock and evaluator versions are frozen before
paid execution. The API returns a model identifier which must match the requested profile.
No fallback model is permitted.

Anthropic documents Sonnet's dateless ID as a fixed snapshot; older Haiku requires its dated ID.
Serving infrastructure can still change. See [model versioning](https://platform.claude.com/docs/en/about-claude/models/model-ids-and-versions).
The direct global API input/output prices checked for this study are $2/$10 per million tokens for
Sonnet and $1/$5 for Haiku. These are a dated snapshot, not a promise about future prices; see
[official pricing](https://platform.claude.com/docs/en/about-claude/pricing). No caching, batch,
premium routing or other paid provider is used. Sonnet uses adaptive thinking with low effort;
Haiku's effort field is omitted. The settings are explicit profiles, not identical internal
computation budgets. No provider random seed is claimed or sent.

Models run in opposite orders on successive rounds: Sonnet/Haiku, Haiku/Sonnet, Sonnet/Haiku.
Cases run in the declared order, followed by failure probes. Case concurrency is **one**, and
SDK retries are disabled. This removes artificial parallel queue contention from the comparison.
The eight-second end-to-end gate budget is retained from the original suite. It may still fail
live calls; component measurements explain those results without retroactively changing gates.

## Freeze and execute

Install the locked extras, then inspect the dry-run plan. This command performs no network calls:

```shell
uv run --frozen python scripts/live_experiment.py
```

Before freezing, commit all implementation/configuration changes and ensure a clean worktree.
The original private accounting database must exist at `data/live-validation/budget.db`. The
script validates its 21 completed requests, $1.411024 retained reservations and $0.104170 known
token cost, reads it without writes, and binds its hash into the manifest.

```shell
uv run --frozen python scripts/live_experiment.py --freeze --output data/live-experiment-v1
git add benchmarks/live-experiment.v1.freeze.json
git commit -m "Freeze repeated live-study manifest before execution"
```

Freeze writes a public manifest at `benchmarks/live-experiment.v1.freeze.json` and an identical
local copy in the output directory. It refuses an existing manifest/output; do not delete one to
obtain a fresh allowance. The manifest's implementation commit must remain an ancestor of the
execution commit. Execution requires the manifest in Git HEAD, a clean worktree and unchanged
Git object identities for **all** `src/` files, both live scripts, the study configuration,
`pyproject.toml` and `uv.lock`. This permits the manifest commit without permitting executable drift.

Supply `ANTHROPIC_API_KEY` through the process environment using the established secret-loading
workflow. No key is printed, embedded in the manifest or loaded from a committed file. After
the frozen plan has been authorized for paid execution:

```shell
uv run --frozen python scripts/live_experiment.py --execute --output data/live-experiment-v1
```

The shared campaign ledger is fixed at `data/live-study-budget.db`, independent of the output
directory. Its cumulative reservation ceiling is **$12**, including the original **$1.411024**
debit, leaving **$10.588976** for new reservations. This remains within the owner's $20 total
authorization. Changing output directories, reopening the ledger or repeating the command does
not reset the budget or re-run the experiment. A campaign can be claimed once. A crash, ambiguous
request or interrupted campaign requires inspection; the runner offers no automatic paid resume.

Reservations are committed before paid transmission using SQLite full synchronous writes and
`BEGIN IMMEDIATE`. Every request reserves the full 4,096-token output allowance plus conservative
input headroom based on the provider's token counter and serialized request size. No reservation
is refunded. Missing accounting, exceeded bounds, unexpected cache usage, changed model identity
or an ambiguous provider result prevents subsequent paid requests. The inherited limitations of
local cost guards remain: actual billing, changed prices and unrelated account activity require
provider-side controls. See [token counting](https://platform.claude.com/docs/en/build-with-claude/token-counting).

## Measurements and completeness

Request timings use a monotonic clock and separate:

- lock/queue wait;
- token-counting HTTP call;
- durable reservation and response-accounting writes;
- paid provider HTTP round trip;
- total guarded request duration.

Invocation end-to-end time is measured separately and retained in normal traces. Provider HTTP
time includes client/network and remote processing; it is **not pure inference latency or time
to first token**. Simulated sandbox tool latency is not substituted for measured elapsed time.
Summaries show sample counts, means and nearest-rank p50/p95 values; sparse samples are not an SLA.

The result lists all 72 planned slots with completed/incomplete/not-started status, trace/score
availability and whether the selected failure actually reached an intercepted tool call. A model
that never calls that tool has not demonstrated recovery merely because a failure plan existed.
Partial runs retain completed traces and recomputed fixed-scorer diagnostics, while the platform
run remains incomplete; diagnostic scores do not manufacture a successful release gate.

Analysis reports per-model and per-round raw results, all applicable dimension denominators,
per-case repeated outcomes, request counts, returned tokens and costs. The paired comparison
resamples the ten **case clusters**, carrying both models and all three rounds together. Its
2,000-resample bootstrap uses a fixed analysis RNG seed, unrelated to provider sampling. It is
suppressed if baseline rounds/cases are missing. An interval on ten selected synthetic cases
does not establish independent population accuracy or generalized model safety. Repeated failures,
truncations, refusals and unfavorable scores remain visible; the study is not rerun to improve them.

## Artifacts and validation

The output directory contains the frozen `manifest.json`, private `evaluation.db`, per-model/round
Markdown reports and `result.json`. The separate private campaign database stores durable accounting.
Public result JSON omits provider request identifiers and contains only synthetic prompts/traces;
review it before publication. Known estimated usage and retained reservation ceilings are distinct.
The report identifies both the frozen implementation commit and the later committed-manifest revision.

```shell
uv run --frozen pytest tests/test_live_budget.py tests/test_live_experiment.py -q
```

These tests make no provider calls. They exercise cumulative historical debit, independent SQLite
connections, interrupted/ambiguous accounting, immutable manifest/source checks, timing boundaries,
single-case concurrency, all 72 mocked invocations, partial evidence preservation and paired-case
analysis. Mock execution proves the runner's contracts; only a separately preserved actual result
is live-model evidence. No live result is asserted by this guide alone.
