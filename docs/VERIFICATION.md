# Portfolio verification record

Updated September 27, 2026. This is the current status; audit reports preserve earlier snapshots.

The project is a local-first 0.2.1 release with an authenticated shared-server option.
The public website is a static demonstration; it does not accept credentials or run models.
The final audit found and the corrective release fixes a stale-review gate bypass. Full
portfolio finalization remains open for the independently human-authored benchmark (F12).

## Verified locally

- Windows / Python 3.14: 306 tests passed with real PostgreSQL enabled, 95.55% line coverage.
  Earlier Linux / Python 3.12 verification and the current remote matrix are recorded in
  release evidence and CI; the release manifest identifies each exact tested revision.
- Ruff passes; mypy passes across 22 production source files.
- PostgreSQL 17.11: sixteen backend tests pass, including independent connection contention,
  fencing, capacity, transactional rollback, retained-data migration, stale approvals,
  historical eligibility, immutable blocks and both block/approval transaction orders.
- Version-wide blocks are rechecked transactionally at gate publication and approval.
  Current release eligibility and baseline acceptance include later blocks, while historical
  artifacts and approval records remain unchanged. Reports identify the blocking run IDs.
- Linux Docker image builds and passes behavioral installed-package verification.
- Compose migrations and a real MCP stdio walkthrough pass across process restart using
  the persistent named volume.
- The wheel smoke verifies all three exact control outcomes, self-approval and critical
  override refusals, graceful timeout recovery and linked trace integrity.
- Local authenticated HTTP verifies credential rotation, tenant separation, scope checks,
  16 admitted requests plus overflow refusal, capacity recovery, stopped-service SQLite
  backup and report-equivalent restoration. [Evidence](evidence/operations.json).
- Private Docker HTTPS verifies TLS 1.3 with explicit local CA trust, certificate rejection,
  bearer authentication, actor identity, tenant isolation and scope enforcement. The backend
  has no published ports. [Deployment check](tls-proxy.md) and [evidence](evidence/tls-proxy.json).
- Real SDK OTLP HTTP delivery to a local receiver and the official OpenTelemetry Collector
  0.161.0 verifies hierarchy, filtered fields, exit flushing and collector shutdown.
  [Collector evidence](evidence/collector.json).
- The edited 150-second browser walkthrough has six populated chapters and functional
  seek/next/previous/play/pause logic verified in a JavaScript harness. Its static preview
  was visually inspected. Automated browser rendering was unavailable in the local session;
  this is not claimed as cross-browser visual certification.

## Portfolio item disposition

| Item | Current evidence / status |
|---|---|
| F01 PostgreSQL demo keys | Repaired; shared demo assertions run on SQLite and PostgreSQL |
| F02 behavioral delivery smoke | `scripts/verify_demo.py` and `scripts/smoke_installed.py`; installed container passed |
| F03 execution of delivery environments | Local Docker, Compose and PostgreSQL passed; remote PostgreSQL/container jobs passed; final matrix tracked in [CI](https://github.com/ahines99/agent-eval-redteam/actions/workflows/ci.yml) |
| F04 release snapshot/publication | Public main branch; tagged artifacts and checksums are published through [GitHub Releases](https://github.com/ahines99/agent-eval-redteam/releases) after successful CI |
| F05 reviewer onboarding | README, `docs/mcp-quickstart.md`, executable `scripts/mcp_walkthrough.py`; actual subprocess validated |
| F06 accessible demo | `docs/demo.html`, original recording and static preview; Pages deployment passed; public page returns the exact committed demo bytes |
| F07 case study | `docs/case-study.md`, including AI assistance and bounded results |
| F08 durable evidence | `docs/evidence/`, CI test/artifact uploads, `scripts/release_evidence.py` |
| F09 claim accuracy | Current docs distinguish implemented, locally verified and externally executed capabilities |
| F10 maintenance surface | Changelog, contribution guide, metadata and enabled GitHub private vulnerability reporting |
| F11 compatibility | Linux 3.12/3.13/3.14 and Windows 3.12 are covered by the remote matrix; Windows 3.14 is tested locally. Exact release counts and revisions are retained in the evidence bundle |
| F12 scorer characterization | **Partially complete.** Alexander Hines approved the existing 33 rows / 35 labels; all nine disagreements remain. The explicitly retained independent, held-out human benchmark and walkthrough are still pending |
| F13 PostgreSQL concurrency | Sixteen actual PostgreSQL tests passed; contracts include independent connections and serialized version-wide block/approval ordering |
| F14 live model validation | Real Sonnet 5 run complete: 21 requests, $0.10417 estimated token cost, 1/10 pass, review gate; preserved first result |
| F15 shared operations | Local HTTP operations and private Docker HTTPS deployment verified; no publicly hosted evaluation service claimed |
| F16 telemetry | Real official Collector transport verified; no external trace storage/UI claim |

## Final scope and human review

The user selected `ahines99/agent-eval-redteam` and a maximum $20 Anthropic budget.
The first live experiment used a conservative $5 reservation ceiling, reserved $1.411024
and recorded $0.10417 in estimated token usage cost. No Anthropic key is committed or included in the demo.
See [live validation](live-validation.md) for the controls and billing limitations.

Alexander Hines approved every row of [the label sheet](scorer-human-review.md) without
corrections on September 27, 2026. The [reviewed revision](../benchmarks/scorer-challenge.human-reviewed.json)
and [regenerated evidence](evidence/scorer-characterization.human-reviewed.json) preserve the
original labels and all nine disagreements. This completed review of that existing corpus;
it did not fulfill the original held-out independence criterion. The owner explicitly required
a separate independent human-authored benchmark after the final audit. Its
[authoring packet](independent-benchmark-authoring.md) is ready; cases, labels and independent
walkthrough review are pending. No AI-generated substitute is being counted as human authorship.

The published v0.2.0 artifacts preserve the pre-review snapshot. Its release includes a
separate human-review addendum tied to the later review commit; original package and evidence
checksums remain unchanged. Version 0.2.1 corrects the gate defect found after that release.
F01-F11 and F13-F16 are supported within the documented scope; **F12 and therefore full
portfolio finalization remain open**. See the [final audit resolution](audits/2026-09-27/FINAL_RESOLUTION.md).

No production certification, signed administrator-resistant evidence, real-data compliance
or generalized model-safety result is asserted. Those remain outside this synthetic portfolio.

## Reproduce

Use the commands in [CONTRIBUTING](../CONTRIBUTING.md), [deployment](deployment.md),
[operations verification](operations-verification.md) and [observability](observability.md).
The [private HTTPS check](tls-proxy.md) also runs in the container CI job.
The release evidence manifest binds package hashes and test reports to a source commit;
GitHub Actions independently records the exact revision for each run.
The [six-job release run](https://github.com/ahines99/agent-eval-redteam/actions/runs/36358321371)
passed on tagged commit `2a76eeb`; the release evidence includes that exact revision's CI record.

The first remote matrix exposed a corpus fingerprint difference caused solely by CRLF/LF checkouts. The fingerprint now normalizes line endings; labels and all nine disagreements are unchanged. A regression test covers both checkout forms.

The hosted Windows runner also exposed a five-second bootstrap HTTP timeout and a venv-launcher child cleanup issue in the operations verifier. It now uses a 60-second read bound and terminates its owned Windows process tree before deleting temporary databases; the behavior assertions remain unchanged.
