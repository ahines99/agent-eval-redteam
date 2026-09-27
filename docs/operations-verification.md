# Local operations verification

Run this disposable smoke from the repository root after installing the project dependencies:

```shell
python scripts/verify_operations.py --output docs/evidence/operations.json
python -m pytest tests/test_operations.py -q
```

The script starts the actual authenticated MCP HTTP application in a separate Uvicorn process,
bound only to `127.0.0.1` on a temporary port. It creates temporary synthetic tenant databases and
cryptographically random bearer tokens. The tokens never appear in the output evidence; the
temporary auth file stores SHA-256 digests and is replaced atomically during rotation. Temporary
files and processes are cleaned up when the script finishes.

The verification checks:

- A registered owner and run requester come from the authenticated principal, overriding caller
  claims. A second read-only tenant cannot see the first tenant's added agent or run and cannot
  register an agent.
- Replacing the first principal's token in the auth file immediately rejects the old token with
  HTTP 401. The replacement token and the unchanged second tenant still work in the same process.
- Sixteen simultaneous authenticated requests are held at body-read. HTTP `100 Continue`
  handshakes establish that each reached the application. The next request receives HTTP 429.
  Completing those requests frees capacity, and a subsequent MCP healthcheck succeeds.
- A hardened scripted evaluation produces an eligible run and a readable report. After the
  server process has fully stopped, SQLite's backup API creates a snapshot and verifies
  `PRAGMA integrity_check`. A copy is restored to a different database path. A fresh server reads
  that restored database and returns the same run decision and byte-identical report.

[Recorded results](evidence/operations.json) include measured admission-response time, run ID,
backup and report hashes, and individual verification outcomes. The evidence contains no database
contents, bearer tokens, auth-file digests, personal information or remote service credentials.
The recorded report is from synthetic fixtures and a deterministic control agent; no model calls
or provider costs are involved.

This is bounded local operational evidence, not a deployed-service certification. It does not
exercise TLS, reverse-proxy forwarding, public hosting, remote credential distribution, distributed
workers, sustained load or PostgreSQL backups. Admission is a per-process bound and the measured
response time is a local observation, not a capacity estimate or latency promise. On Windows the
subprocess termination is not claimed to be a graceful signal shutdown; the script waits for full
process exit before taking the snapshot. OTLP exporter shutdown is verified separately in the
[observability check](observability.md).

For a real backup, stop all writers, protect the backup like the original trace database, restore
to a separate path, and verify known reports before switching traffic. SQLite's backup API is used
here to include any pending WAL content; copying only the main database file while writers or WAL
state remain active is not an equivalent procedure. Real deployments must establish their own
retention, encryption, recovery objectives, TLS/proxy configuration and credential distribution.
