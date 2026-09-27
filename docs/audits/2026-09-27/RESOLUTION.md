**Audit remediation and build verification — September 27, 2026**

Current finalization status: [verification record](../../VERIFICATION.md). This document preserves its assessment-time evidence and remaining-work list.

This record supersedes the open status in [the original audit](REPORT.md). All 16 numbered findings have implementation fixes and assertion-based regression coverage. Version 0.2.0 is a local-first build with an authenticated shared HTTP option. Five agents performed implementation/integration work: workflow, scoring, delivery/documentation, telemetry, and the coordinating agent's fixture/service/authentication work.

The application now records schema `1.2`, scorer `scoring/1.2`, and gate policy `gate-policy/1.2`. The demo uses `support-core@1.2.0` with 35 cases. Published suite JSON versions 1.0.0 and 1.1.0 remain unchanged. Current runtime identity includes suite/world hashes and scorer/gate versions, preventing automatic comparison across incompatible implementations. Historical suite limitations remain visible; stronger behavioral assertions are delivered in the new suite, not silently backported into published fixture definitions.

| Finding | Implemented resolution | Regression evidence under `tests/` |
|---|---|---|
| A01 concurrent execution | Renewable database lease, fenced writes, bounded execution capacity; completed trace reuse | `test_audit_workflow.py::test_concurrent_resume_calls_agent_once_per_trace`, `test_expired_lease_recovery_fences_previous_owner` |
| A02 baseline cutoff | Search accepted history without the 50-result cutoff; validate compatible identity and evidence | `test_audit_workflow.py::test_baseline_search_has_no_nonaccepted_run_cutoff`, `test_baseline_identity_must_match_world_and_scorer` |
| A03 authorization expiry | Recheck each case under the semaphore immediately before adapter execution, including retried work | `test_audit_workflow.py::test_queued_case_rechecks_authorization_before_adapter_call` |
| A04 shared attack fixture | Ordinary shared order records are clean; legacy overlays require explicit classified canary/tool declarations; new suite uses explicit additive order fixture | `test_audit_fixtures.py::test_ordinary_tools_cannot_reach_shared_attack_notes` |
| A05 duplicate PII owner | Merge all values associated with the normalized destination; fixture additions cannot remove protected values | `test_audit_fixtures.py::test_duplicate_email_never_removes_sensitive_values` |
| A06 numeric PII | Independently match separated fixture values without merging adjacent values or accepting substrings inside longer identifiers | `test_audit_scoring.py::test_numeric_fixture_pii_detected_on_chat_and_email`, `test_adjacent_values_remain_separate_and_long_identifier_is_not_a_leak` |
| A07 outgoing PII | Inspect recipient, subject, body and approval-ticket arguments; include unknown SSN/card-shaped data, while preserving legitimate recipient data | `test_audit_scoring.py::test_email_scans_every_field_and_unknown_secrets`, `test_known_recipient_own_data_and_tracking_reference_are_allowed`, `test_human_approval_is_a_protected_write_sink` |
| A08 missing evidence | Validate exact case/phase/repeat/failure manifest and persisted step manifests; exclude ad-hoc probes | `test_audit_workflow.py::test_missing_release_trace_fails_closed` |
| A09 integrity checks | Verify trace, evidence and artifact hashes during consumption; validate denormalized metrics; require intact baseline evidence and validate release-summary reads | `test_audit_workflow.py::test_corrupted_release_evidence_fails_closed`, `test_corrupted_artifact_is_never_consumed`, `test_corrupted_metrics_cannot_be_used_as_baseline`, `test_accepted_baseline_requires_intact_evidence` |
| A10 stranded gate | Commit step artifact, audit and pause state atomically; recover older unresolved gate states; approval and decision audit also commit atomically | `test_audit_workflow.py::test_checkpoint_rolls_back_artifact_when_audit_insert_fails`, `test_crash_after_gate_checkpoint_preserves_review_boundary`, `test_legacy_gate_checkpoint_recovers_unresolved_review`, `test_audit_services.py::test_approval_is_rolled_back_if_audit_write_fails` |
| A11 unsupported recovery | Distinguish narrowly scoped uncertainty from affirmative unsupported facts | `test_audit_scoring.py::test_recovery_distinguishes_scoped_uncertainty_from_assertions` |
| A12 untriggered probe | Required untriggered probes fail recovery; normal assertions remain active | `test_audit_scoring.py::test_untriggered_probe_retains_baseline_assertions_and_counts_failed_recovery` |
| A13 weak task assertions | Add tool success, argument fragments and result fragments; suite 1.2 asserts returned source, outgoing policy, delivery date, free exchange, and missing-ID clarification | `test_audit_scoring.py::test_structured_tool_assertions_require_success_content_and_result`, `test_abstention_also_requires_declared_clarification`; `test_audit_fixtures.py::test_strengthened_suite_control_and_email_content`, `test_new_suite_control_end_to_end` |
| A14 monetary match | Parse complete monetary values with equivalent formatting and reject different decimals/thousands amounts | `test_audit_scoring.py::test_numeric_fact_boundaries` |
| A15 incomplete stop | Context-window truncation and other incomplete/unknown stops fail closed | `test_audit_scoring.py::test_incomplete_or_unknown_stop_reasons_fail` |
| A16 repeated demo | Reuse a recorded candidate decision; namespace demo idempotency keys by suite version | `test_delivery.py::test_persistent_demo_can_be_run_twice` |

Additional repairs include full requester/baseline idempotency fingerprints, concurrent immutable registration handling, compatible-identity regression reporting, metrics integrity checks, safe legacy human-review recovery, and bounded suite/HTTP/run admission. Exact-once execution across a provider response followed by process death before trace persistence is not promised: no database transaction can include that remote request. Leases prevent simultaneous owners and fence stale workers; persisted completed traces are reused.

**Build and delivery work completed**

- Authenticated HTTP uses high-entropy bearer tokens stored as digests in an operator-owned configuration file. Requester/owner/approver/reader identities come from the principal, not claimed tool arguments. Scopes separate reading, running, registration, authorization and approval. Tenants use separate configured databases. Tests cover credentials, revocation, scope refusal, actor spoofing, tenant separation, database URL aliases, and a real HTTP socket. Trusted local stdio remains available without authentication.
- Limits: 128 cases, 512 scheduled invocations, 20,000 prompt characters, 50 tool calls per case, 1 MB suite content; eight active runs per database and 16 in-flight HTTP requests per process. These are workload limits, not a provider billing guarantee. Cost scoring is retrospective.
- `uv.lock` pins application/test dependencies. GitHub workflows cover Python 3.12/3.14, lint/types/coverage, package installation outside the checkout, PostgreSQL 17, containers and dependency auditing. Dependabot configuration is included. Workflow files are not represented as completed remote CI runs.
- Frozen Alembic revisions `0001` and `0002` define the original schema and execution leases. SQLite tests cover retained data, fresh/legacy upgrade, repeated upgrade, schema agreement and disposable downgrade. Adoption instructions explain backing up and verifying an existing `create_all` database before stamping.
- Dockerfile and Compose use an unprivileged process, persistent SQLite and no published ports by default. Shared HTTP deployment, TLS, secrets, migrations, backup/restore and operational checks are documented in [deployment instructions](../../deployment.md).
- Telemetry is explicitly opt-in, with OTLP HTTP or stderr console and clean shutdown. In-memory exporter tests verify hierarchy, useful operational fields, absence of sensitive payloads and class-only errors. See [telemetry instructions](../../observability.md).
- MIT license, package version 0.2.0, updated current documentation/Skills, an actual [terminal recording](../../demo.cast), its recorder, and a [three-minute narration script](../../demo-script.md) are included. The terminal recording preserves real execution timestamps; it is not a three-minute narrated video.

**Verification**

Both Python 3.12.10 and Python 3.14.5 use frozen dependencies and all extras: **242 passed, 1 skipped** on each. Python 3.12 measured **95.43% line coverage** against the configured 90% threshold. The skipped test requires a PostgreSQL service. Ruff and mypy pass. SQLite migrations, persistent repeated demo, real stdio restart and authenticated HTTP pass in the automated suite. Dependency auditing found no known vulnerabilities in the installed locked dependencies; the local project itself is not in the vulnerability database. Version 0.2.0 wheel and source distribution build successfully, and the installed wheel passes the smoke test outside the checkout.

Commands:

```text
uv sync --frozen --all-extras
uv run --frozen ruff check src tests migrations scripts
uv run --frozen mypy src
uv run --frozen pytest --cov=agent_eval_redteam --cov-report=term-missing
uv run --frozen python -m build --no-isolation
uv run --frozen python scripts/record_demo.py
```

For installed-package verification, install the built wheel and hash-verified frozen runtime dependencies into a separate environment, then run `scripts/smoke_installed.py` with that environment's Python. The script starts subprocesses outside the checkout and removes `PYTHONPATH`.

**Explicit remaining external or deferred work**

| Item | Current status / next prerequisite |
|---|---|
| PostgreSQL execution | Implemented migration/integration test and CI service job; no local PostgreSQL executable/service, so execution remains unverified until that job or a disposable database is available |
| Container execution | Dockerfile/Compose and CI smoke job exist; no local Docker executable/service, so image runtime remains unverified |
| Remote CI and publication | No Git remote configured; workflows cannot be executed remotely or a release published without selecting/creating a repository |
| Live Claude validation | Fake-provider contract tests pass; actual API evaluation requires credentials, selected model and explicit spending ceiling. No paid calls were made |
| Shared deployment | Authenticated option is tested locally. Real TLS/proxy, per-tenant database accounts, secret distribution/rotation, backup restoration and operator load testing remain deployment responsibilities |
| Signed evidence | HMAC/external anchoring remains deferred per the prior recorded decision. Existing hashes now verify corruption, but an administrator able to rewrite data and hashes remains trusted |
| Real customer data | Sandbox remains synthetic. Real-data retention/encryption controls are not claimed; revisit if that scope changes |
| Narrated video | Actual terminal recording and narration script delivered; narrated screen video and publication remain optional portfolio work |

No claim of production certification, exhaustive semantic scoring, live-model quality, or remote CI success is made. The supported and locally verified deliverable is the local-first 0.2.0 build plus its authenticated shared-server option.
