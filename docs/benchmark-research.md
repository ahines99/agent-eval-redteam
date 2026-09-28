# Research benchmark and reviewer workflow

This version adds **120 explicitly AI-authored traces across 60 paired scenario families**:
60 customer-support traces and 60 SQL/data-engineering traces. Each of the ten dimensions has
six compliant and six violating labels. These are development-exposed, purposefully selected
examples, not independent human ground truth or a random estimate of real-world performance.

The corpus does not call a model or execute tools. SQL records are authored observations;
the [SQL domain walkthrough](sql-domain.md) separately runs actual isolated queries. Latency
and cost labels exercise inclusive arithmetic boundaries using invented values, not measured
performance or billing.

The earlier 33- and 40-trace corpora, their first results, and the production deterministic
scorer remain unchanged. Human approval of the earlier 33 rows does not transfer to these rows.
**No human reviewer has participated in this new benchmark.** The owner's accepted AI-authored
scope remains in force; the reviewer interface is a capability for later evidence collection.

## Coverage and dependence

| Dimension | Six scenario families (each has a compliant and violating variant) |
|---|---|
| Factuality | Notice-unit equivalence, coverage negation, unsupported extra benefit, SUM versus COUNT, null counting, join cardinality |
| Tool correctness | Object identity, prerequisite ordering, successful retrieval, aggregate query choice, bound parameter, result contract |
| Permission | Refund, account deletion, unauthorized email, SQL deletion, file attachment, schema alteration |
| Injection resistance | Document canary, punctuated canary, email command, schema-comment canary, query-write instruction, canary in arguments |
| PII leakage | Final answer, own versus foreign email data, approval ticket, query summary, spelled-out digits, email subject |
| Citation | Missing reference, fabricated reference, contradictory support claim, schema reference, aggregate reference, join reference |
| Calibration | Missing tracking ID, unknown refund, conflicting policies, missing table, ambiguous grain, unknown null policy |
| Recovery | Timeout, malformed document, outage, schema timeout, truncated answer, worker crash |
| Latency | Single lookup, ordered tools, long response, aggregate query, join, empty result; distinct boundary values |
| Cost | The same six workload contexts with distinct cost boundaries, including a zero-cost budget |

Two traces in a family are intentionally correlated. Count families and domains alongside
traces; do not describe 120 rows as 120 independent tasks. Budget families are arithmetic
boundary checks, not broad semantic diversity. Dimension labels concern only the named
behavior; other dimensions can fail independently on the same trace.

## Metrics and semantic comparison

Positive means a violation. For each dimension the report preserves TP, TN, FP, FN, labeled
count, scored count, unscored count, precision, recall, F1, false-positive/negative rates and
coverage. Precision is TP/(TP+FP); recall is TP/(TP+FN); F1 is 2TP/(2TP+FP+FN).
An undefined denominator is JSON `null`. Unscored labels are excluded from precision/recall
and explicitly reduce coverage. Always read coverage next to these conditional metrics.

Twenty-four factuality/citation traces also have trusted constrained-semantic packets.
Their whole-packet verdict is compared with a separately authored packet-level label.
`uncertain` remains unscored and requires review. Packet metrics are **not** semantic accuracy
for individual scoring dimensions. Missing packets never count as passing. The complete
legacy score remains visible beside the advisory result; advisory results do not alter gates.
All errors, disagreements and uncertainty are retained without tuning labels after execution.

## Freeze and first execution

The coordinator commits the corpus, protocol and source-bound freeze manifest before the
first full research execution. Validation-only tests do not score the authored corpus.

```sh
python -m uv run --frozen python scripts/benchmark_research.py freeze --corpus benchmarks/scorer-research-v1.json --output benchmarks/scorer-research-v1.freeze.json
# Commit the corpus, freeze manifest, protocol and implementation before execution.
python -m uv run --frozen python scripts/benchmark_research.py run --corpus benchmarks/scorer-research-v1.json --manifest benchmarks/scorer-research-v1.freeze.json --frozen-input-commit COMMIT_SHA --output docs/evidence/research-benchmark-v1
```

The runner verifies LF-normalized SHA-256 fingerprints for input and implementation and
checks that the same bytes existed at the specified commit. It exclusively creates the
output directory before scoring, saves `report.json` plus `execution.json`, and refuses to
overwrite an existing destination. Exceptions leave a nonzero execution record instead of
an apparently completed report. Execution timestamps belong only to the provenance record;
score reports are deterministic. Git history establishes which preserved execution was first;
a later reproduction does not automatically acquire that claim.

For reproduction use a fresh destination under `data/verification/`. If source files change,
use a separate clean checkout of the recorded commit rather than rewriting the first manifest.
This research-only command does not spend API funds or perform recorded tool actions.

## Two-reviewer import and adjudication

Export one packet and supply identical copies to two reviewers independently:

```sh
python -m uv run --frozen python scripts/benchmark_research.py export-review --corpus benchmarks/scorer-research-v1.json --output data/verification/reviewer-blank.json
```

The export includes policy, source, trace, sensitive-value map and blank dimension labels.
It excludes proposed labels, author rationale, semantic packets and scorer results. Neutral
IDs and a mixed deterministic order hide good/bad case IDs and paired ordering. This reduces
label leakage but cannot create independence for someone who has already seen the corpus.

Each reviewer fills `reviewer.id`, `reviewer.kind` (`human` or `ai`), an honest
`independence_declaration`, every boolean label and a rationale per case. `true` means violation.
Do not modify the case or trace. Reviewer identity and independence are self-declarations;
the software does not certify them. An AI reviewer must be recorded as `ai`.

```sh
python -m uv run --frozen python scripts/benchmark_research.py compare-reviews --corpus benchmarks/scorer-research-v1.json --review-a reviewer-a.json --review-b reviewer-b.json --output data/verification/reviewer-agreement.json
```

Imports require the exact corpus fingerprint, distinct identities and complete exact coverage.
Missing labels, duplicate/unknown cases, strings substituted for booleans and changed evidence
are rejected. The result retains both original submissions, labels, rationales and declarations,
and computes raw agreement and Cohen's kappa overall and by dimension. Kappa is undefined
(`null`) for a single-class identical judgment set with expected agreement one. Overall
agreement pools heterogeneous labels; per-dimension results and sample counts matter more.

Disagreements have `consensus: null`. They are never silently resolved using author labels or
scorer output. A third declared adjudicator can provide a JSON document:

```json
{
  "schema_version": 1,
  "corpus_sha256": "COPY_THE_PACKET_HASH",
  "adjudicator": {"id": "third-reviewer", "kind": "human"},
  "resolutions": [
    {"id": "ORIGINAL_ID_FROM_AGREEMENT_REPORT", "dimension": "factuality", "violation": true,
     "rationale": "Explain the evidence and policy supporting this resolution."}
  ]
}
```

Run `compare-reviews` again with `--adjudication adjudication.json` and a new output path.
Every disputed label requires an explicit resolution and nonempty rationale. The adjudicator
must differ from both reviewers. The original two labels remain intact alongside consensus.
The examples above are blank instructions, not fabricated human reviews or agreement evidence.

## Validation

```sh
python -m uv run --frozen pytest tests/test_benchmark_research.py
```

Tests exercise metrics, degenerate agreement, label blinding, exact review coverage, evidence
binding, adjudication, immutable outputs, source-change refusal, failed execution records,
semantic uncertainty and corpus-design validation. Toy fixtures exercise scoring; the full
120-trace first execution is a separately frozen experiment, not an implicit unit-test action.
