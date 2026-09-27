# Portfolio verification record

Updated September 27, 2026. This is the current status; audit reports preserve earlier snapshots.

The project is a local-first 0.2.0 release with an authenticated shared-server option.
The public website is a static demonstration; it does not accept credentials or run models.

## Verified locally

- Windows / Python 3.14 and Linux / Python 3.12: full suite passed, including PostgreSQL.
  Latest complete local runs each passed 287 tests; Windows line coverage was 95.50%.
  Additional final budget tests are recorded in the release evidence and CI.
- Ruff passes; mypy passes across 22 production source files.
- PostgreSQL 17.11: eight backend tests pass, including independent connection contention,
  fencing, capacity, transactional rollback, approval races and retained-data migration.
- Linux Docker image builds and passes behavioral installed-package verification.
- Compose migrations and a real MCP stdio walkthrough pass across process restart using
  the persistent named volume.
- The wheel smoke verifies all three exact control outcomes, self-approval and critical
  override refusals, graceful timeout recovery and linked trace integrity.
- Local authenticated HTTP verifies credential rotation, tenant separation, scope checks,
  16 admitted requests plus overflow refusal, capacity recovery, stopped-service SQLite
  backup and report-equivalent restoration. [Evidence](evidence/operations.json).
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
| F04 release snapshot/publication | Repository published on main; release tag and artifacts follow successful final CI |
| F05 reviewer onboarding | README, `docs/mcp-quickstart.md`, executable `scripts/mcp_walkthrough.py`; actual subprocess validated |
| F06 accessible demo | `docs/demo.html`, original recording and static preview; Pages deployment passed; public page returns the exact committed demo bytes |
| F07 case study | `docs/case-study.md`, including AI assistance and bounded results |
| F08 durable evidence | `docs/evidence/`, CI test/artifact uploads, `scripts/release_evidence.py` |
| F09 claim accuracy | Current docs distinguish implemented, locally verified and externally executed capabilities |
| F10 maintenance surface | Changelog, contribution guide, metadata and enabled GitHub private vulnerability reporting |
| F11 compatibility | Linux/Windows local evidence; remote matrix configured for Linux 3.12/3.13/3.14 and Windows 3.12 |
| F12 scorer characterization | 33 traces / 35 proposed labels; nine disagreements retained; **independent human review pending** |
| F13 PostgreSQL concurrency | Eight actual PostgreSQL tests passed; contracts cover separate connections and competing actors |
| F14 live model validation | Real Sonnet 5 run complete: 21 requests, $0.10417 estimated token cost, 1/10 pass, review gate; preserved first result |
| F15 shared operations | Local HTTP operations verified; no publicly hosted evaluation service or TLS deployment claimed |
| F16 telemetry | Real official Collector transport verified; no external trace storage/UI claim |

## Remaining external input

The user selected `ahines99/agent-eval-redteam` and a maximum $20 Anthropic budget.
The first live experiment used a conservative $5 reservation ceiling, reserved $1.411024
and recorded $0.10417 in estimated token usage cost. No Anthropic key is committed or included in the demo.
See [live validation](live-validation.md) for the controls and billing limitations.

An independent human must review [the label sheet](scorer-human-review.md) before the
challenge corpus can be described as human-validated. Its labels and results remain visible;
passing the bundled suite does not resolve the nine documented semantic disagreements.

No production certification, signed administrator-resistant evidence, real-data compliance
or generalized model-safety result is asserted. Those remain outside this synthetic portfolio.

## Reproduce

Use the commands in [CONTRIBUTING](../CONTRIBUTING.md), [deployment](deployment.md),
[operations verification](operations-verification.md) and [observability](observability.md).
The release evidence manifest binds package hashes and test reports to a source commit;
GitHub Actions independently records the exact revision for each run.

The first remote matrix exposed a corpus fingerprint difference caused solely by CRLF/LF checkouts. The fingerprint now normalizes line endings; labels and all nine disagreements are unchanged. A regression test covers both checkout forms.
