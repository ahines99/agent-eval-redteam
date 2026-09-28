# Final portfolio audit

Historical audit at `517f96c`. See [the correction record](FINAL_RESOLUTION.md) for subsequent
fixes and the subsequent benchmark scope decision. The reproduction deliberately
asserts the old faulty behavior; 0.2.1 refuses its stale approval instead. Current regression
coverage is in `tests/test_version_blocks.py`.

Audited revision: `517f96c9b1a6d948cf97502d048199f713dfbb22`.

Verdict: **not fully finalized yet**. One reproducible high-priority gate defect remains. Delivery,
release assets, onboarding and bounded evidence are substantially ready. The earlier completion
assessment missed the stale-review sequence below and should not be treated as proof of correctness.

Three agents independently audited correctness/security, delivery/operations, and portfolio/evidence.
The parent independently ran the full local test suite and reproduced the gate defect. The audit
changed no tracked source files or remote state. All paid-model evidence was inspected offline;
no additional paid calls were made.

## P1 — An older pending review bypasses a later block of the same agent version

Locations:

- `src/agent_eval_redteam/domain/services.py:226`: approval operates on the existing gate artifact.
- `src/agent_eval_redteam/domain/services.py:234`: decision checks do not revalidate version-wide blocks.
- `src/agent_eval_redteam/workflows/primary.py:327`: effective release decision uses only the run's gate and approval.
- `src/agent_eval_redteam/workflows/primary.py:341`: accepted-baseline classification inherits that decision.
- `src/agent_eval_redteam/workflows/primary.py:395`: prior blocks are checked at initial gate computation.
- `src/agent_eval_redteam/domain/policies.py:192` and `docs/threat_model.md:29`: a blocked agent version must stay blocked.

Reproduction uses only supported platform methods, an in-memory SQLite database and scripted agents:

1. Start a small, noncritical suite for `support-bot-naive@0.9.0`; its latency result pauses for review.
2. Run the full security suite against that same version; it becomes blocked.
3. Have a distinct approver approve the older pending run.
4. Start another run of the blocked version, then a new agent version on the small suite.

Actual output, independently reproduced by the parent:

```json
{
  "older_initial_decision": "awaiting_review",
  "later_security_run_decision": "blocked",
  "older_after_later_block_and_approval": "approved_with_override",
  "fresh_same_version_decision": "blocked",
  "new_version_uses_old_approved_blocked_version_as_baseline": true
}
```

Saved reproduction: `repro_sticky_block.py`; the original run's output is reproduced above.
Run from the repository root:

```shell
uv run --frozen python docs/audits/2026-09-27/repro_sticky_block.py
```

Impact: a central release-policy invariant is bypassed without database tampering, an untrusted
administrator, a concurrency race or external model calls. A stale approval also influences the
automatically selected regression baseline. The platform does not deploy an agent, so this is a
release-decision correctness defect, not evidence of an actual deployment or data breach.

Required correction: retain historical evidence while enforcing the version-wide block during
approval and effective acceptance/baseline selection. Add regression coverage for the reproduced
sequence and concurrent block/approval ordering; define historical versus currently effective
acceptance explicitly. Verify SQLite and PostgreSQL behavior before publishing the corrected release.

## P2 — F12 completion accounting does not match its original independence criterion

`docs/audits/2026-09-27/PORTFOLIO_GAPS.md:37` requested a held-out, human-labeled corpus and an
independently inspected walkthrough. `docs/VERIFICATION.md:50` and `:71` close F12 and all F01-F16,
but `docs/scorer-characterization.md:5` explicitly describes development-exposed, agent-authored
examples; line 67 distinguishes human label approval from an independent audit of the narrative.

The approval is valid: Alexander Hines approved all 33 rows / 35 labels unchanged. That closes label
review, but it does not make this a held-out benchmark. Current scientific limitations are candid;
the mismatch is in checklist completion accounting.

Correction: explicitly document that the original independence criterion remains unmet/deferred
within the scoped portfolio, or supply the missing independently developed/held-out evidence.
Do not relabel the existing corpus as blind or held-out. This discrepancy is distinct from the P1
functional blocker and does not invalidate the recorded human approval.

## P3 — Minor presentation encoding defects

`README.md:14` has literal `?` between its three links. The published v0.2.0 release notes contain
two actual `Â·` separators and repeated CRCRLF line endings. These are cosmetic; links and release
integrity work. Normalize the separators/encoding as optional polish.

## Verification performed

- Full local Windows / Python 3.14 suite: **282 passed, 8 PostgreSQL tests skipped**, 95.46% line coverage,
  64.33 seconds. Local JUnit and coverage were saved under `data/verification/final-audit/`;
  the source-bound published CI evidence preserves the corresponding release checks.
- Current remote CI: [36360236028](https://github.com/ahines99/agent-eval-redteam/actions/runs/36360236028),
  exact audited SHA, all six jobs successful. Four matrix jobs each pass 282 tests; the separate
  PostgreSQL job passes all eight backend tests.
- Delivery agent separately ran focused delivery, SQLite migration/concurrency, actual HTTP
  operations and actual OTLP checks: **13 passed**. PostgreSQL execution was verified in CI.
- Portfolio agent reran characterization checks: **9 passed**; traces, labels and nine disagreements
  remain unchanged in the reviewed revision.
- All six public release assets downloaded afresh; GitHub digests and both checksum files match.
  All 28 original evidence hashes and 13 review-addendum hashes verify. Their CI revisions agree
  with their manifests. Original tagged packages and later review evidence are clearly separated.
- CI actually builds packages, checks an installed wheel outside the checkout, runs the container
  behavior smoke, migrates Compose storage, verifies MCP restart persistence and private HTTPS.
- PostgreSQL contracts exercise independent connections, ownership/fencing, admission races,
  transactional rollback, competing approvals, retained-data migration and demo behavior.
- Public HTTPS demo returns 200 and matches the exact committed Git object. Relative Markdown
  destinations resolve; preview is readable. Browser rendering across platforms was not certified.
- MIT licensing, contributor/security guidance, package URLs and enabled private vulnerability
  reporting are present.
- Live evidence reconciles to 21 requests, 42,310 input tokens, 1,955 output tokens and $0.10417
  estimated token cost. The reported 1/10 pass and review-required gate are accurately disclosed.

The nine known semantic scorer disagreements, trusted database administrators, private loopback
hosting, single-process deployment scope, lack of production-load certification and development-
exposed data remain documented limitations. They are not silently counted as general safety,
accuracy or production certification. Passing the existing tests does not cover the P1 sequence.

## Minimum remaining work

1. Fix P1 and add meaningful sequential/concurrent regression coverage.
2. Reconcile F12's original requirement with the actual evidence and agreed portfolio scope.
3. Run the appropriate checks and publish corrected code/evidence. P3 can be addressed alongside
   that work, but it is not a functional release blocker.

This report records findings only; no repairs were applied during the audit.
