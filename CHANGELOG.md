# Changelog

This file describes repository changes. A version heading does not imply a published
package, tag or successful external deployment; see release artifacts and validation evidence.

## 0.2.0 - 2026-09-27

### Evaluation and correctness

- Added complete release-trace manifests and verification of traces, evidence, artifacts
  and cached metrics before accepting release results.
- Added suite/world/scorer/gate identity to baseline comparability; accepted baseline
  selection no longer stops after 50 historical runs.
- Added `support-core@1.2.0` with explicit successful retrieval, tool result/message content
  and clarification assertions. Published 1.0.0/1.1.0 suite JSON remains unchanged.
- Fixed targeted disclosure, recovery, calibration and tool-scoring counterexamples;
  required failure probes that do not trigger now fail recovery.
- Updated semantic versions to schema 1.2, scoring/1.2 and gate-policy/1.2.

### Workflow and access

- Added exclusive execution leases, fenced writes, atomic checkpoints and recovery of
  unresolved review gates; persisted traces are reused after interrupted work.
- Moved authorization checks to the admitted case invocation boundary and moved attack
  fixtures out of the benign shared world.
- Added authenticated HTTP principals, server-derived actors, per-tool scopes and
  per-tenant database routing. Stdio remains locally trusted.
- Added bounded suite, active-run and HTTP-request admission.

### Delivery and review

- Added a dependency lock, CI definitions, dependency audit configuration, migration
  infrastructure, container configuration, MIT license and deployment documentation.
- Added local transport/restart, migration and regression coverage; optional backend
  tests and CI definitions require actual execution evidence before claiming validation.
- Added opt-in filtered OpenTelemetry export, an actual terminal capture, and reviewer
  onboarding/case-study/maintenance documentation.
- Published a static browser walkthrough, scorer challenge characterization, operational
  and official Collector evidence, and the first budgeted live Sonnet 5 result.
- Added cross-platform corpus fingerprinting and reliable owned-process cleanup in the
  Windows operations verifier.
- Verified private HTTPS through Caddy with explicit CA trust and a private Docker backend;
  included the deployment check and PostgreSQL test artifacts in CI.

### Limits retained

- No claim of exactly-once external API billing, general semantic scoring, independently
  human-validated detection accuracy or a production traffic benchmark.
- Live-model and private deployment results are bounded by their documented verification scope.
- Hash signing/external anchoring remains deferred; database administrators remain trusted.

## 0.1.0 implementation baseline

- Established typed MCP capabilities, deterministic scoring, synthetic sandbox controls,
  SQL persistence, the eight-step workflow and human release review.
- Added suites 1.0.0/1.1.0, a Claude adapter exercised with fake clients, four procedural
  skills and offline demonstration paths.
- Earlier audit notes and planning skeletons remain preserved as historical context in
  [IMPLEMENTATION_HANDOFF.md](IMPLEMENTATION_HANDOFF.md).
