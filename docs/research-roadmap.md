# Research evidence roadmap — audit response

Baseline: public `v0.2.1`, main `2f318dc`. This roadmap responds to the supplied external
portfolio assessment. It extends the completed local-first project; it does not rewrite its
workflow engine or retroactively change published results.

Implementation and first experiments are complete in 0.3.0. The
[audit disposition and preserved results](research-results.md) map each workstream to its
evidence and remaining limits; the [verification record](VERIFICATION.md) tracks delivery.
The live study completed all 72 invocations with $0.484913 estimated new token cost.

## Review of the assessment

The substantive gaps are valid: deterministic scoring has semantic blind spots, the labeled
data is development-exposed, evidence covers one application domain, and the live experiment
is too small and instrumented too coarsely for a model comparison. Public SaaS operation,
external adoption and business impact have not occurred. They cannot be established by adding
source code, generating artificial users or treating AI labels as independent human judgments.

The owner's earlier decision accepting transparent AI-authored characterization remains in
force. We will supply stronger benchmark/reviewer infrastructure, while reporting actual
human participation as absent unless genuine reviewer submissions arrive. No new public
hosting, customer outreach, real customer data or production-SLA claim is part of this work.

## Team and execution constraint

The user requested five agents for both planning and implementation. The runtime rejected
additional agents with `agent thread limit reached`, including after a planning agent finished.
The three available agents are reused for implementation: semantic evaluation, benchmark and
review tooling, and live experiments. The coordinating agent owns the second domain and
integration/release work. Five workstreams are retained; this is not represented as a
five-agent independent review.

## Finalized implementation plan

| ID | Workstream and owner | Deliverables | Acceptance evidence |
|---|---|---|---|
| R1 | Structured semantics — semantic agent | Versioned opt-in advisory evaluator; deterministic result retained; grounded structured claims, constrained language templates, unit equivalence, citation support, known word-digit disclosures and explicit uncertainty | Contradictions fail; uncovered/ambiguous text requires review; existing critical blocks cannot be relaxed; legacy scorer and frozen reports remain unchanged |
| R2 | Benchmark quality — benchmark agent | At least 120 purposefully varied AI-authored traces, domain/family accounting, precision/recall/F1/coverage, blinded exports, two-reviewer import, disagreement adjudication and agreement statistics | Corpus/protocol committed before first experiment; non-overwrite outputs; invalid labels/provenance rejected; absent humans never become fabricated agreement; original data preserved |
| R3 | Second domain — coordinator | Synthetic read-only SQL/data-engineering environment, actual isolated SQLite queries, versioned cases and hardened/flawed controls executed through the existing persistent platform | Query results checked against explicit expectations; denied mutations recorded; schema/aggregation/join/null/order cases; failure handling; trace/report/gate evidence saved |
| R4 | Repeated live study — live agent | Two pinned Claude models, three interleaved rounds, fixed cases and repeated failure probes, source/config/pricing manifest, component latency and paired case-level analysis | No-network budget/provenance/timing tests first; committed manifest before paid calls; cumulative reservations include prior experiment; first results and partial failures retained |
| R5 | Integration and delivery — coordinator | Reproducible commands, honest current-state documentation, release package and evidence, CI and compatibility verification | Focused tests, full CI, PostgreSQL/container/installed-wheel verification, release hashes, clear separation of deterministic gates and advisory research outputs |

The semantic evaluator is constrained reference-grounded checking, not a general-purpose
natural-language judge. Its supported/contradicted/uncertain outcomes remain advisory and do
not approve deployments or override existing gates. Promotion into mandatory release policy
would require a separately calibrated, versioned policy change.

The second domain uses fictional structured data. SQLite authorizer restrictions, read-only
mode, row/statement bounds and execution interruption protect its disposable query surface.
No database credentials or arbitrary files are exposed to the evaluated control.

## Live-study contract

Use `claude-sonnet-5` and `claude-haiku-4-5-20251001`, three rounds each, the same ten baseline
cases and two failure probes per round. Alternate model order across rounds. These are repeated
runs, not seed-controlled experiments. Freeze exact inputs, tools, prices, settings and source
identity before execution. Preserve the original ten-case experiment without modification.

The previous ledger reserved $1.411024 and recorded $0.104170 known token cost. Carry those
reservations into a shared campaign ledger and use a **$12 cumulative reservation ceiling**,
within the owner's existing $20 total authorization. Reservations precede transmission and
are not refunded after success, ambiguity or interruption. SDK retries remain disabled.
Budget exhaustion produces explicit partial evidence rather than silently starting a fresh
allowance. No other provider or paid service is authorized by this plan.

Report queue wait, token counting, accounting and paid provider HTTP round trip separately
from adapter end-to-end latency. HTTP duration includes network and provider processing; it
is not pure inference time or time to first token. Keep gate thresholds fixed before execution.
Report model/round/case denominators, completeness, token usage, estimated cost and uncertainty.
Repeated observations of ten cases are not an enlarged independent sample of real-world tasks.

## Ordering and publication

1. Complete this audit-to-roadmap mapping and agree module ownership.
2. Implement R1, R2 and R4 in parallel while the coordinator implements R3.
3. Run focused tests, inspect interfaces and freeze new corpora/study configuration in Git.
4. Execute the first offline characterization and budgeted live study; preserve every result.
5. Inspect results, update current claims, run full validation and publish a new release with
   source-bound evidence. Do not replace original release assets or tune labels after results.

## Remaining external evidence

Dual independent human annotations, genuine external adoption, measured customer impact,
production traffic and an SLA remain external evidence opportunities. The delivered reviewer
workflow can collect such evidence, but its existence does not prove human agreement. The
published results will state exactly which experiments and reviews actually occurred.
