# Final audit correction record

The [three-agent audit](FINAL_AUDIT.md) reviewed commit `517f96c` and found a new gate defect.
The earlier "all remaining items complete" assessment was too strong. This record tracks the
correction in 0.2.1 and the owner's subsequent explicit benchmark scope decision.

| Finding | Disposition | Evidence |
|---|---|---|
| P1 stale review bypasses a version-wide block | Corrected in 0.2.1 | `tests/test_version_blocks.py`; SQLite and PostgreSQL end-to-end and transaction-order tests |
| P2 F12 completion overstates independent evidence | Closed under explicitly revised scope; independence is not claimed | Owner accepted AI-authored characterization; `docs/ai-benchmark-protocol.md` and `docs/scorer-ai-characterization.md` |
| P3 presentation encoding | README separators repaired; release descriptions normalized during publication | README link row and published release notes |

## Gate semantics and concurrency

The original sequence allowed a run awaiting review to become `approved_with_override` even
after another run blocked the same version. The fix refuses that approval without inserting
an approval or audit event. A historical PASS or earlier approval also becomes effectively
blocked and is excluded from future accepted-baseline selection. Historical gate artifacts,
their hashes and earlier approvals remain preserved. `version_block_run_ids` explains the
effective decision; the report distinguishes the recorded gate from current eligibility.

Gate publication and approval acquire the same agent-row transaction lock before reading
committed blocks or writing their result. A non-key no-op update provides a PostgreSQL row
lock and SQLite writer serialization. Both commit orders are covered with independent
connections: block-first refuses the approval; approval-first preserves its historical
record but becomes effectively blocked once the block commits. A decision read reflects
committed state when it reads; this is not a guarantee against future discoveries.

A PASS/REVIEW computed before a concurrently committed block is refreshed at checkpoint.
The final artifact hash, audit event, pause state and workflow context agree. Committed gate
artifacts cannot be replaced. Malformed or hash-corrupt prior gates fail closed, and a failed
monitoring step cannot erase a committed block. The existing policy threshold/scorer versions
are unchanged: this repairs enforcement of the already documented version-wide rule.

No database schema change or historical backfill is needed. The guard reads the existing
committed gates, so stored 0.2.0 runs receive the effective block when served by 0.2.1.

## Validation

- Full local Windows/Python 3.14 suite with real PostgreSQL 17.11: **306 passed**, no skips,
  **95.55% line coverage**.
- Eight new contracts run on both SQLite and PostgreSQL; the PostgreSQL CI job includes them.
- The independent correctness reviewer replayed the original sequence: approval refused,
  no partial approval write, effective block present, historical gate unchanged and no stale
  accepted baseline selected.
- Ruff and mypy validate the production changes. The corrected release's evidence bundle
  binds its CI results and artifact checksums to the exact source commit.

## Benchmark scope decision and completion

The existing 33-row/35-label corpus was authored with access to the scorer. Alexander Hines's
approval is retained and valid for those labels, but it does not make them held-out evidence.
After the audit, the owner initially retained the independent benchmark. Subsequently, when
asked explicitly about replacing that requirement, the owner answered: "Yes—use the AI-authored
benchmark (recommended for this portfolio)." The original independence criterion was replaced,
not fulfilled. No independent human validation is claimed for the new corpus.

The [protocol](../../ai-benchmark-protocol.md) and 40-trace input were committed before execution
at `145c986`. The first execution preserved its log, exact source/input hashes, complete results
and all six disagreements: three false positives and three false negatives, no unscored labels.
The [report](../../scorer-ai-characterization.md) records per-dimension counts and an AI-inspected
evidence-to-score-to-gate walkthrough, including a disclosure the scorer missed. No scorer or
label was changed to improve the result; the earlier human-reviewed corpus remains unchanged.

F12 is complete under that revised criterion. The authoring packet is retained for optional
future independent research. Package and historical evidence provenance remain distinct from
the later evidence addendum; current verification and release manifests identify each revision.
