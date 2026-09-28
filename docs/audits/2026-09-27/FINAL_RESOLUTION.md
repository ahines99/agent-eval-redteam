# Final audit correction record

The [three-agent audit](FINAL_AUDIT.md) reviewed commit `517f96c` and found a new gate defect.
The earlier "all remaining items complete" assessment was too strong. This record tracks the
correction in 0.2.1 and the explicitly retained independent-benchmark requirement.

| Finding | Disposition | Evidence |
|---|---|---|
| P1 stale review bypasses a version-wide block | Corrected in 0.2.1 | `tests/test_version_blocks.py`; SQLite and PostgreSQL end-to-end and transaction-order tests |
| P2 F12 completion overstates independent evidence | Documentation corrected; original requirement remains open | Owner selected an independent human-authored benchmark; `docs/independent-benchmark-authoring.md` |
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

## Independent benchmark remains required

The existing 33-row/35-label corpus was authored with access to the scorer. Alexander Hines's
approval is retained and valid for those labels, but it does not make them held-out evidence.
After the audit, the owner explicitly chose to require the independent benchmark rather
than narrow F12 to the existing characterization.

An unexposed human author must provide new synthetic traces, evidence, labels, rationales and
an authorship declaration using the authoring packet. Clerical transcription is returned for
their confirmation, then frozen before the first scoring run. The first results and failures
must be preserved, and the author/reviewer must inspect an evidence-to-score-to-gate walkthrough.
No cases or labels have been manufactured to claim this work is complete.

The corrected software release can be published while this research-evidence requirement is
pending. The complete portfolio goal must not be marked achieved until the independent input
has been incorporated and verified.
