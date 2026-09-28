# AI-authored benchmark protocol and scope decision

On September 27, 2026, Alexander Hines explicitly accepted replacing the independently
human-authored portfolio requirement with transparently AI-authored characterization:
**"Yes—use the AI-authored benchmark (recommended for this portfolio)"**. This changes the
completion criterion for F12. It does not establish that the original independence criterion
was met. Independent human validation has not been performed on this new corpus.

The earlier approval of 33 development-exposed traces remains a separate historical review.
Neither that approval nor this scope decision constitutes human approval of these new labels.
The [human authoring packet](independent-benchmark-authoring.md) remains available for future
independent work, which would provide stronger evidence than this characterization.

## Design fixed before first execution

- Input: [40 authored traces](../benchmarks/scorer-challenge.ai-expanded.json), four for each
  of ten dimensions, with two violation and two compliant labels per dimension.
- Author: Codex AI assistant with prior access to the scorer, previous cases and results.
  This is not blind, independent, held-out, or a random sample.
- Every trace records its policy, source evidence, exact output/tool history and label rationale.
  Only explicitly labeled dimensions enter the confusion counts.
- Include literal and paraphrased facts, unsupported additions, successful/failed tool calls,
  forbidden attempts, injection destinations, authorized/foreign disclosures, citation support,
  natural clarification, service recovery, crashes and inclusive budget boundaries.
- Timing and cost are synthetic arithmetic fixtures. No live model or external tool is called.
- Semantic labels may exceed what executable phrase/citation assertions express. Preserve that
  mismatch as a limitation; do not narrow the label to match the implementation.

The input SHA-256, using UTF-8 file bytes with CRLF normalized to LF, is
`30fff454ea5cfd4329e4cc63c968d21e6b9b6b53a3213e11782e575c480e0e96`.
Schema, unique identifiers, literal Boolean labels, source/rationale presence and balanced
dimension coverage were checked without invoking the scorer. The input and this protocol
are committed before the first scoring run.

The production scorer being evaluated is unchanged from source commit
`cc92898ea045b3bbe8192f0fa3a2966c5c706244`, using `scoring/1.2` and `gate-policy/1.2`.
The execution record will identify the exact frozen-input commit and source-file hashes.

## Execution and reporting rules

1. Execute `scripts/characterize_scorer.py` once against this frozen revision with a new output
   path. Preserve the first stdout/stderr, exit code and report, including errors if any.
2. Record per-dimension TP/TN/FP/FN, denominators and unscored labels. A successful command
   means execution completed; it does not mean perfect detection.
3. Retain every disagreement. Do not tune production code or rewrite labels after seeing results.
   Any later correction requires a separately identified revision and preserved original results.
4. Inspect at least one evidence-to-score-to-gate walkthrough. Clearly identify that inspection
   as AI-authored; it is not an independent human review.
5. Verify reproducibility and preservation using tests that compare stored evidence, input
   fingerprints and accounting. Do not demand that all semantic labels agree with the scorer.
6. Publish corpus, protocol, first execution record, report, walkthrough and limitations together.

There is no minimum accuracy threshold for this characterization. A single-trace gate is an
illustration, not a persisted release decision or a measurement of repeatability. These results
cannot establish general model quality, general privacy protection or production safety.

After the above work, F12 can close under the owner's revised portfolio criterion. The original
independent-human criterion remains unfulfilled and must never be described as completed.
