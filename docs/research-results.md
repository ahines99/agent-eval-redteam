# Research extension: audit response and first results

Version 0.3.0 extends the existing local-first release-gating platform. The
[roadmap](research-roadmap.md) records the supplied audit, accepted scope and workstream owners.
The new inputs and implementation were committed as `0cb5896`; the live manifest was committed
as `2d90d89` before execution. Earlier release packages, labels, reports, scoring/1.2 and
gate-policy/1.2 remain unchanged.

## Audit disposition

| Audit gap | Delivered response | Remaining limit |
|---|---|---|
| Brittle phrase matching | Versioned structured/reference-grounded semantic advisory, duration equivalence, constrained language templates, citation support, known word-digit disclosures and explicit uncertainty | Constrained grammar and trusted configuration; not a general natural-language judge; cannot approve a release |
| Small exposed benchmark | 120 AI-authored traces across 60 paired families and two domains; frozen first results, per-dimension metrics, blinded exports and dual-review/adjudication tooling | AI-authored and development-exposed; no new human reviewers or independent accuracy claim |
| Support-only evaluation | Twelve SQL/data-engineering cases, real bounded SQLite queries, three controls and persistent evidence/gates | Scripted query plans; no live text-to-SQL competence measurement |
| Single small live result | Two pinned model profiles, three interleaved rounds, explicit failure probes, component timings, cumulative spending guard and case-level paired analysis | Ten selected synthetic cases, different model compute profiles, no production/SLA inference |
| Adoption and business impact | Honest scope and evidence inventory | No external adoption, customer-impact or production-traffic evidence; no artificial users or invented impact |

The requested five-agent team exceeded the runtime's available capacity. Three subagents were
reused across planning, implementation and cross-review; the coordinator owned SQL and integration.
This is five workstreams, not five independent agent reviews.

## Frozen 120-trace characterization

The [frozen corpus](../benchmarks/scorer-research-v1.json) retains the authored traces; the
[first report](evidence/research-benchmark-v1/report.json) preserves judgments and disagreements,
with source provenance in the [execution record](evidence/research-benchmark-v1/execution.json).
There are 60 support and 60 SQL traces, with twelve explicit labels for each of ten dimensions.
Each dimension has six violating and six compliant labels. Positive means a violation.

| Dimension | Precision | Recall | F1 | False positives | False negatives |
|---|---:|---:|---:|---:|---:|
| Calibration | .750 | 1.000 | .857 | 2 | 0 |
| Citation | 1.000 | .333 | .500 | 0 | 4 |
| Cost | 1.000 | 1.000 | 1.000 | 0 | 0 |
| Factuality | .833 | .833 | .833 | 1 | 1 |
| Injection resistance | 1.000 | 1.000 | 1.000 | 0 | 0 |
| Latency | 1.000 | 1.000 | 1.000 | 0 | 0 |
| Permission | 1.000 | .833 | .909 | 0 | 1 |
| PII leakage | 1.000 | .833 | .909 | 0 | 1 |
| Recovery | .857 | 1.000 | .923 | 1 | 0 |
| Tool correctness | 1.000 | 1.000 | 1.000 | 0 | 0 |

All 120 authored dimension labels were scored: four false positives and seven false negatives,
for eleven disagreements. This is characterization against intentionally selected AI labels,
not measured population accuracy. Paired examples are dependent, and cases were authored with
access to the implementation. The old 33-row human-reviewed and 40-trace AI corpora remain separate.

The new reviewer workflow exports neutral IDs in mixed order without author labels or scorer
verdicts. It binds submissions to the corpus, checks exact label coverage, retains rationales,
computes per-dimension agreement/kappa and supports a distinct adjudicator. Reviewer identities
and independence are self-declarations, not verified identities. **No new human submissions have
been received; no human agreement statistic is claimed.** See [review instructions](benchmark-research.md).

## Semantic advisory evidence

Twenty development-authored probes produced the expected verdicts in the
[first semantic report](evidence/semantic-research-v1.json): five supported, four contradicted
and eleven uncertain. Unknown qualifiers, unsupported language, conflicting sources and missing
grounding remain visible as uncertainty. These examples also influenced development, so perfect
agreement here is a contract demonstration, not an independently measured accuracy result.

The research corpus supplies semantic packets for 24 selected traces. The evaluator made
determinate whole-packet judgments on 22/24 (91.7% coverage), matching the packet labels on those
22; two packets were uncertain. These packet metrics are separate from the ten deterministic
dimension metrics. They do not justify claiming 100% semantic accuracy or replacing the gate.
Critical legacy findings remain effective even when a semantic advisory supports a claim.

## Actual SQL execution

The [persistent control evidence](evidence/sql-domain-v1/controls.json) contains twelve cases,
two baseline repeats and one retrieval-timeout probe per control: 75 stored traces across the
three controls. The hardened control passed 12/12 cases and was eligible. The flawed control
passed 10/12, exposing incorrect row count and sum calculations, and was rejected after review.
The unsafe control passed 10/12 but recorded two critical findings and was blocked.

SQLite executes the actual queries; traces retain SQL, parameters and returned rows. Isolation
uses disposable in-memory data, denied write/file/extension capabilities, row and VM-step limits,
and bounded SQLite values, statements and expression depth. Local sub-millisecond query timings
can round to zero; they are not warehouse performance measurements. See [SQL domain](sql-domain.md).

## Preserved repeated live study

The [full result](evidence/live-experiment-v1/result.json),
[manifest](../benchmarks/live-experiment.v1.freeze.json) and per-round reports preserve the
first execution. All 72 invocations completed, producing 72 traces and 138 paid API requests
(69 per model). All twelve planned failure probes actually triggered; the fixed scorer marked
all twelve as recovered. No API request was ambiguous, retried or left unaccounted for.

| Profile | Baseline passes by round | Baseline observations passed | Invocation p50 / p95 | Mean paid HTTP round trip |
|---|---|---|---|---|
| Sonnet 5, low effort | 8/10, 7/10, 7/10 | 22/30 (73.3%) | 3.217 s / 9.619 s | 1.932 s (69 requests) |
| Haiku 4.5, dated snapshot | 8/10, 8/10, 8/10 | 24/30 (80.0%) | 2.132 s / 5.579 s | 1.198 s (69 requests) |

Invocation latency includes all requests and local work, across 36 invocations per model.
The report separates queue, token-counting and durable-accounting time; HTTP duration is not
pure inference latency. All original eight-second gate thresholds remained unchanged.

Sonnet's three rounds remained awaiting review. Haiku's first round awaited review and its
second and third rounds were blocked: its final response repeated the synthetic customer's
email address during the email-policy case, which the unchanged disclosure policy classifies
as critical. This is evidence of behavior under this declared policy, not a claim that real
customer data was leaked. Both models failed the fixed tool sequence/content contract on that
case in all rounds and failed the missing-order calibration contract. The complete traces are
available to distinguish model behavior from limitations of those deterministic expectations.
Later version-wide blocks also affect current eligibility of earlier runs; stored per-round
summaries retain the decision snapshot at the time of execution. No gate was approved.

The paired case-cluster bootstrap estimates Sonnet-minus-Haiku baseline pass-rate difference
at -6.67 percentage points, with an exploratory 95% interval of [-20, 0] points. The sample is
ten selected cases observed three times per model, not thirty independent cases or evidence
that Haiku is generally better. The higher pass count also does not negate its critical findings.
The first older Sonnet result remains 1/10; scheduling and request conditions changed, so the
new result is not a controlled estimate of a model improvement.

The campaign used 258,908 input and 11,490 output tokens, for **$0.484913** in estimated new token
cost. New conservative reservations were $6.912648. Including the prior experiment, retained
reservations are **$8.323672** against the $12 ceiling, and known token cost is **$0.589083**.
These are local accounting estimates, not an Anthropic invoice or unrelated-account spending.
Private databases and API credentials are excluded from the published artifacts.

## Review findings resolved before freezing

Cross-review caught an unparsed source exception that could have produced an overconfident
semantic verdict; incomplete source parsing now requires review. SQL recursive concatenation
could grow values before the VM-step limit; connection-level size limits now stop it. A failed
later live round could fall back to a previous run's results; results now require the exact
round/model idempotency key. Regression checks cover these cases.

The full local suite passed 392 tests with sixteen PostgreSQL-only skips on Windows/Python 3.14,
at 95.77% line coverage. Ruff and mypy passed, including all 25 production source files.
Remote matrix, PostgreSQL, container and installed-wheel evidence are tracked in the
[verification record](VERIFICATION.md) and source-bound release bundle.

## Portfolio framing

Describe this as an **AI-assisted engineering project for auditable agent evaluation and release
gating**, with an additional research layer that measures and exposes scorer limitations.
Its strongest evidence is persistent workflow correctness, constrained execution, reproducible
experiments, honest uncertainty and source-bound delivery. Avoid claims of generalized model
safety, independent human validation, customer adoption, production operation or business savings.
