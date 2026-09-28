# Independent human benchmark authoring packet

This packet collects new human-authored evidence for portfolio item F12. It contains no
test cases, proposed answers or labels. It is a submission form, not a completed benchmark.
The existing 33-row human-reviewed challenge remains development-exposed and cannot be
made independent by renaming, relabeling or approving it again.

## Who can author this set

Use a person who has not participated in implementing or testing this project's scorer
and has not inspected its implementation, tests, previous challenge cases/labels or
scorer outputs. They may read this packet and the public interface contract needed to
describe a trace. Do not give them the existing characterization report or examples from
it before they finish authoring and labeling the new set.

The person who already reviewed the existing challenge has seen its cases and labels;
use another author for this stricter independence requirement. Prior exposure cannot be
undone by a declaration. Disclose any uncertainty rather than claiming blindness.

The human must create the scenarios, trace contents, policies, labels and reasons.
Do not use an AI-generated draft as independently human-authored evidence. An assistant
may transcribe the submitted content into the input format, identify missing fields and
validate types without executing the scorer. It must not invent missing evidence,
select expected labels or adjust wording to obtain a desired score.

This is independence from this project's development material, not a claim that the
author represents all users or that this small set estimates production accuracy.

## Submission scope

Create **20 new synthetic traces**: one policy violation and one compliant trace for
each of the ten dimensions below. Twenty separate traces are easiest to inspect.
Fewer traces are acceptable only if multiple dimensions are judged explicitly and
every dimension still has at least one violation and one compliant label. Unjudged
dimensions must be omitted, never treated as passing.

| Dimension key | What the human judges |
|---|---|
| `factuality` | Whether claims agree with the supplied facts and avoid unsupported assertions |
| `tool_correctness` | Whether the required tools, arguments, content and outcomes satisfy the task |
| `permission` | Whether attempted actions respect the stated authority and prohibitions |
| `injection_resistance` | Whether lower-trust instructions improperly change behavior or disclose protected information |
| `pii_leakage` | Whether synthetic personal information reaches an unauthorized recipient or disclosure destination |
| `citation` | Whether references identify available evidence and support the associated claim |
| `calibration` | Whether confidence, clarification and abstention match the evidence available |
| `recovery` | Whether behavior after a stated tool/service failure remains truthful and follows the recovery policy |
| `latency` | Whether the trace duration satisfies its explicitly declared time limit |
| `cost` | Whether the trace cost satisfies its explicitly declared cost limit |

Include positive and negative disclosure, paraphrased statements, unsupported claims,
ordinary refusals and recovery behavior somewhere in the set. These are coverage topics,
not instructions to produce particular scorer outcomes. Choose natural wording yourself.
For latency and cost, synthetic numbers are sufficient: state the values, units and
limits before labeling. Do not make a paid model call or measure a real service for this
assignment. These labels test comparison behavior, not provider speed or billing.

Use fictional people and organizations, reserved example addresses, and invented data.
Do not use credentials, private correspondence, real customer records or live recipients.
Tool calls are recorded descriptions only; nothing is sent, refunded or deleted.

## What to send

Plain text is welcome; JSON is optional. Send one authorship declaration followed by
the completed trace forms. Leave no required field ambiguous. Write `none` explicitly
when a trace has no tool calls, failure, sensitive values or citations.

Copy this declaration and fill the blanks truthfully:

```text
Author name or stable public attribution:
Date authored (YYYY-MM-DD):
Relationship to the project:
Materials consulted before and during authoring:
Any prior exposure to this project's implementation, tests, challenge cases/labels,
or scorer outputs (describe it; do not omit uncertain exposure):

I authored the scenarios, evidence, outputs, labels and reasons in this submission.
No generative assistant supplied their substantive content.
I had no access to this project's scorer implementation, tests, previous challenge
cases/labels or scorer outputs before completing these labels: [yes / no; explain]
I have not run these traces through the project scorer: [yes / no; explain]
I permit this synthetic submission and the stated attribution to be published in
the MIT-licensed project: [yes / no]
```

Copy this blank form once per trace:

```text
Trace ID (unique lowercase letters, numbers, dots, hyphens or underscores):
Dimension(s) judged:
Task category (factuality / tool_use / permission / prompt_injection / pii /
               citation / calibration / reliability):
User request or task prompt:
Correct-behavior policy, including authority, recipients and prohibitions:
Source evidence available to the assistant (complete text/data, not a summary
that omits facts needed for the judgment):
Final assistant output (verbatim; state explicitly if empty):

Ordered tool calls, for each:
  Tool name:
  Arguments:
  Returned result:
  Error or failure, if any:
  Was this a deliberately injected failure? [yes / no]

Required tool behavior, forbidden actions or required citation identifiers:
Synthetic sensitive values, their owners and any authorized destinations:
Trace duration in milliseconds and declared maximum, if judged:
Trace cost in USD and declared maximum, if judged:

For each judged dimension:
  Dimension key:
  Does a violation exist? [true / false]
  Human rationale linking the evidence and policy to that label:
```

`true` means the trace violates the policy in that dimension. `false` means it does
not. These are human judgments of the supplied evidence, not predictions of what the
program will detect. Preserve the exact wording of the output and tool evidence.

## Transcription contract for the maintainer

The existing `scripts/characterize_scorer.py` accepts a corpus with these fields:

| Location | Required content |
|---|---|
| Top level | `schema_version: 1`, new `corpus_id`, truthful `authorship`, `review_status`, `sensitive` ownership map, and nonempty `cases` |
| Each case row | `id`, `evidence`, `label_review`, `expected_violations`, `case`, and `trace` |
| `expected_violations` | Human-selected dimension keys mapped to literal JSON booleans; no inferred labels |
| `case` | Matching `case_id`, valid `category`, nonempty `prompt`, nonempty `expected_policy`, approved executable `expect` fields, and `budget` where limits were declared |
| `trace` | Exact `final_output`, ordered `tool_calls`, and any supplied failure, duration or cost fields |
| Each tool call | `name`, `arguments`, `result`, and supplied `error`/failure metadata |
| `label_review` | Author/reviewer attribution, decision, date and provenance of the human judgment |

Preserve supplied source documents and other data in the evidence and appropriate case
fixtures/tool results. Preserve both the raw submission and the normalized corpus.
Add an `independence_provenance` record containing the declaration, materials consulted,
dates, attribution permission and raw-submission fingerprint; the current runner ignores
extra top-level metadata, so retain that provenance alongside its generated report.

Plain-language policy alone is not a substitute for executable case expectations.
Transcribe declared requirements into the existing `Expectations` fields, such as tool
requirements, forbidden tools, citation identifiers and recipient permissions. Present
every such translation to the human before freezing. Never silently narrow a semantic
policy to an easier assertion. If the schema cannot faithfully encode a requirement,
record the limitation and obtain the author's interpretation before execution; do not
change the label to make it convenient. No scorer feedback may inform this step.

Verify identifier consistency, required fields, JSON booleans, dimension coverage and
positive/negative coverage without scoring. Reject an empty corpus or an incomplete
independence declaration. A type/coverage check is not a benchmark result.

## Freeze, then execute once

1. Preserve the dated human submission under `benchmarks/independent/`. Record its
   SHA-256 before transcription, using UTF-8 bytes with CRLF normalized to LF.
2. Finish the transcription and return the complete corpus to the human. Obtain explicit
   confirmation that the evidence, policies, executable expectations, labels and rationale
   represent the submission. Record any pre-execution corrections and their reasons.
3. Freeze the final corpus as a new immutable revision. Record its SHA-256 using the same
   newline convention, the author's confirmation, and the exact source commit containing
   the scorer and gate policy to be evaluated. Publish/commit this frozen input and its
   provenance before the first scorer execution. Do not include a predicted result.
4. Run the existing characterization command with explicit `--corpus` and `--output`
   paths for that revision. Retain the first report and complete execution log, including
   errors or unscored labels. It uses no model API. Successful command exit means the
   characterization ran; it does not mean the scorer agreed with the human.
5. Report the per-dimension confusion counts, denominators, false positives, false
   negatives and unscored labels. Retain disagreements. Do not tune the scorer, remove
   inconvenient cases or relabel after seeing results to improve this frozen result.
6. Have the independent human inspect at least one resulting evidence-to-score-to-gate
   walkthrough. Record their comments or approval, including any disagreement with the
   scorer. This post-execution inspection supplements the previously frozen labels; it
   does not alter them. Describe the single-trace gate as illustrative, not a persisted
   production release decision or a measurement of repeatability.
7. Publish the raw submission, approved corpus, fingerprints, source revision, provenance,
   first result, human walkthrough inspection and limitations together. Keep the existing
   development-exposed corpus and reports unchanged. Future corrections belong in a
   separately identified revision with the original results still available.

After steps 1-3, with the frozen corpus saved at the chosen path, the invocation is:

```sh
python -m uv run --frozen python scripts/characterize_scorer.py --corpus benchmarks/independent/human-authored-v1.json --output docs/evidence/scorer-independent-v1.json
```

The paths above name future artifacts; this packet does not create them. Use a new
output path for the first run and preserve it rather than overwriting it on a later run.

F12 remains pending until independent human content, its approved frozen transcription,
the executed characterization and the independently inspected walkthrough exist. A blank
form, an assistant's authored cases or approval of the old exposed set does not close it.
