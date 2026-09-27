# Threat model (0.2.0)

Assets: evaluation integrity, evidence, release decisions, synthetic fixtures, model
credentials and tenant data. Operators, approvers and suite authors have different roles.
Agents under test and driving MCP clients may encounter untrusted instructions.
The server host/database administrator remains trusted.

## Boundaries and controls

| Threat | Implemented control |
|---|---|
| Spoofed HTTP actor | Token digest maps to server-derived actor; caller fields replaced |
| Unauthorized tool operation | Scopes `read`, `run`, `register`, `authorize`, `approve` |
| Cross-tenant access | Server-selected tenant database; distinct SQLite paths checked |
| Shared server lacks credentials | Invalid/missing config returns 503; bad/missing token returns 401 |
| Self-approval / confusing identities | Normalized ASCII actors; approver differs from requester |
| Trace text steers review | Evidence treated as data; prompt requests human decision; server gate rules remain binding |
| Relabeled attack cases | Content-based authorization, including planted fixtures and sensitive requests |
| Authorization expires in queue | Recheck inside concurrency slot immediately before case adapter invocation |
| Hidden attack in shared world | Benign shared world; explicit attack fixtures local to authorized cases |
| Production/destructive red-teaming | Production security suites/failure injection refused; destructive injection disabled |
| Real email/refund/delete effects | Queued email; privileged tools refused; attempts scored |
| Personal data in authored suites | Synthetic-range validation of prompts, fixtures, keys and numeric values |
| Leakage through write arguments | Answer, email destination/subject/body and approval-request checks; finding redaction |
| Missing/tampered release evidence | Exact manifest, hashes, evidence links, artifacts and metric consistency verified |
| Concurrent workflow commits | Expiring leases, heartbeat, fenced writes and deterministic ids |
| Crash around human review | Atomic checkpoint and pause; unresolved review restored to `needs_review` |
| Weak chosen baseline | Automatic accepted baseline with matching evaluation identity; caller baseline informational |
| Blocked version shops suites | Earlier block remains binding for that agent version |
| Resource exhaustion | Suite admission limits, eight active runs/database, 16 HTTP requests/process |
| Sensitive telemetry | Opt-in export with allowlisted identifiers/counts and class-only failures |

Classification and PII detection are heuristics. Tests cover declared patterns, not every
possible attack, personal datum or encoding. Report a pass as evidence about its suite.

## Deployment trust

Stdio trusts access to the local process; it does not authenticate actor names independently.
HTTP uses high-entropy service tokens, not OIDC login. Keep config private, issue separate
tokens per actor, grant least scopes, terminate TLS at a proxy and keep the backend private.
Config is reread on each request; revocation does not cancel already accepted work.

For PostgreSQL, provision separate databases/credentials with least privilege. Distinct
URL strings cannot prove arbitrary DNS aliases or routing lead to separate stores.
Verify isolation operationally. See [deployment](deployment.md).

## Explicit limitations

- **Signing remains deferred.** A database writer can alter hashes and data together.
  HMAC/signatures or an external append-only anchor would change this boundary.
- **Remote calls are not exactly once.** A crash before trace persistence can repeat a
  model invocation. Leases prevent conflicting commits, not all duplicate provider billing.
- **Limits are not spend caps.** Per-suite limits are 128 cases, 512 planned invocations,
  20,000-character prompts, 50 tool calls/case and 1,000,000 serialized bytes. No aggregate
  provider billing cap or organization-wide quota exists; cost thresholds score completed
  traces. HTTP concurrency is per process.
- **Storage retains raw traces.** Synthetic inputs do not guarantee model output lacks
  sensitive text. Protect traces, error/audit data and backups; decide retention,
  encryption and deletion policies before introducing real-data sandboxes.
- **Authorization has case granularity.** Expiry blocks the next adapter invocation;
  it does not revoke an already-running provider/tool loop.
- **Validation is bounded.** Local tests, stdio/HTTP transport, SQLite migrations,
  PostgreSQL 17.11 contracts and Docker build/behavioral smoke have run. Live Claude
  evaluation, remote CI and operational shared deployment require separate evidence;
  no production security certification is claimed.

See [audit resolution](audits/2026-09-27/RESOLUTION.md) for the remediation record.
