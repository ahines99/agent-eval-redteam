# Running and maintaining the platform

The default is a local stdio MCP process with SQLite. Shared HTTP requires authenticated
identities and role enforcement; putting caller-supplied actor names behind a proxy alone
does not establish those identities.

## Shared HTTP

Set `AGENT_EVAL_AUTH_FILE` to a private JSON file outside the repository:

```json
{
  "tenants": {"acme": "sqlite:///./data/acme.db"},
  "principals": [
    {"token_sha256": "SHA256_HEX_OF_RANDOM_TOKEN", "actor": "alice", "tenant": "acme",
     "scopes": ["read", "run", "register"]},
    {"token_sha256": "SHA256_HEX_OF_DIFFERENT_RANDOM_TOKEN", "actor": "reviewer", "tenant": "acme",
     "scopes": ["read", "authorize", "approve"]}
  ]
}
```

Replace the placeholders with SHA-256 digests of separate cryptographically random
tokens (at least 32 characters); distribute the raw tokens through your secret manager.
Restrict file access to the server operator. Give each tenant a separate database URL and
each person only the scopes they need. Clients send `Authorization: Bearer TOKEN`.
The server derives actor fields from the authenticated principal and checks each tool's
scope. A caller cannot choose another tenant's database through tool arguments.

Start `agent-eval serve --transport streamable-http`; it binds to loopback port 8000.
Use a TLS reverse proxy for remote clients and keep the backend private. Missing auth
configuration returns 503; missing or invalid bearer tokens return 401. Stdio remains a
locally trusted transport: access to its process is the authorization boundary. Do not
expose an unauthenticated stdio-to-network bridge. Apply migrations separately to every
tenant database before serving requests.

## Reproducible environment

Install Python 3.12 or 3.14 and uv 0.12.18, then run:

```sh
python -m pip install uv==0.12.18
uv sync --frozen --all-extras
uv run --frozen pytest --cov --cov-report=term-missing
uv run --frozen ruff check src tests migrations scripts
uv run --frozen mypy src
uv run --frozen python -m build --no-isolation
uv run --frozen agent-eval demo
```

`uv.lock` records dependency versions and artifact hashes. Update deliberately with
`uv lock --upgrade`, run the checks, and review the lock diff. CI is configured to exercise
the Python matrix, an installed wheel outside the source tree, PostgreSQL and containers.
The dependency workflow is configured for scheduled and dependency-change scans;
Dependabot configuration requests dependency, workflow and base-image updates. These
definitions are not execution evidence. Use the linked workflow results and the
[resolution record](audits/2026-09-27/RESOLUTION.md) to identify completed checks.

Local Linux verification now includes a real Docker image build and behavioral container
smoke, plus PostgreSQL 17.11 repository/migration contract checks. Those runs do not prove
that [remote CI](https://github.com/ahines99/agent-eval-redteam/actions) passed, nor that a
shared service has been deployed. Use release-specific evidence for the exact snapshot.

## Database migrations

For a new database, set `DATABASE_URL` in the process environment, then:

```sh
uv run --frozen alembic upgrade head
uv run --frozen alembic check
uv run --frozen agent-eval serve
```

The SQLite default is `sqlite:///./data/agent_eval.db`; parent directories are created.
PostgreSQL uses `postgresql+psycopg://USER:PASSWORD@HOST/DB` and the `postgres` extra.
The migration runner reads `DATABASE_URL` directly, so passwords containing `%` are safe.
It does not load `.env` automatically. Avoid putting passwords in committed configuration.

The migration history contains a frozen initial schema (`0001`) and execution leases
(`0002`). Existing installations created by `Repository.create_all` have no Alembic
version. Stop the server, back up the database, and compare that database to the initial
schema before adopting migrations: an unchanged pre-lease database may be stamped
`0001` and then upgraded to `head`; a verified current schema may be stamped `head`.
Do not blindly stamp a database with unknown schema or use downgrade on retained data.
Run `alembic check` after adoption. Application startup still creates absent tables for
local convenience; run migrations explicitly before starting a managed deployment.

When changing schema, generate a new revision with `alembic revision --autogenerate -m
"description"`, inspect it, and test both fresh installs and upgrades with retained data.
Migration files must never import the evolving application metadata as their schema.

For SQLite backups, stop the process and copy the database before restarting; restore
to a separate path and test `agent-eval report RUN_ID --db sqlite:///RESTORED_PATH`.
For PostgreSQL, use the operator's `pg_dump`/`pg_restore` procedure and verify the restored
database before switching traffic. Keep backups subject to the same access policy as traces.

## Container

```sh
docker build -t agent-eval .
docker run --rm agent-eval demo
docker compose run --rm --entrypoint alembic eval upgrade head
docker compose run --rm --no-deps eval serve
```

The image runs as an unprivileged user, installs frozen runtime dependencies, and defaults
to stdio. Compose persists SQLite in a named volume, drops capabilities, and publishes
no network ports. Use `docker compose run --rm -T eval serve` for an MCP client stdio
command; set its working directory to this repository. No API key is required for the
offline demo. The base image is updated through Dependabot; builds are not claimed to be
bit-for-bit reproducible across base-image updates.

The image includes PostgreSQL and migrations. To add live Claude or OTLP telemetry,
include the corresponding `claude` or `observability` extras in the image installation
and pass credentials through the deployment secret store. Never bake credentials into
the image or use the CI database password outside its disposable CI service.

## PostgreSQL integration locally

Set `TEST_POSTGRES_URL` to a disposable database whose user may create schemas, then run
`uv run --frozen pytest tests/test_delivery.py tests/test_postgres_contracts.py -m postgres -v`.
Each test creates and drops
only a UUID-named schema. Without that variable, PostgreSQL tests explicitly skip.
They verify migrations, model/schema agreement, the full control-agent demo and gate
paths, plus repository ownership, fencing, admission and transaction contracts.
Docker/PostgreSQL checks require their services; CI jobs are configured to run
them. A skipped local test or a workflow definition does not establish backend validation.

## Optional telemetry

Install the `observability` extra (included by `uv sync --all-extras`). Set
`OTEL_TRACES_EXPORTER=console` for stderr output, or set `OTEL_TRACES_EXPORTER=otlp` and
`OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` to the collector's HTTP/protobuf traces endpoint.
`OTEL_SERVICE_NAME` defaults to `agent-eval-redteam`. OTLP gRPC is not supported. Without
explicit exporter/endpoint configuration tracing is disabled; `OTEL_SDK_DISABLED=true`
or `OTEL_TRACES_EXPORTER=none` also disables it. Standard SDK batching/sampling settings
apply. Keep collector credentials in deployment secrets.

The exporter includes filtered operation identifiers, counts, measured durations and
class-only failures. It excludes prompt/output content and exception messages. This
does not redact stored trace bodies or ordinary application error logs. Console export
uses stderr so it does not corrupt MCP stdio protocol messages.

## Release evidence

The [private HTTPS deployment check](tls-proxy.md) runs the application behind Caddy with
explicit CA trust, authentication and tenant isolation checks. It publishes only a loopback
proxy port and leaves the backend on a private Docker network.

Keep the commit id, dependency lock, test/coverage output, migration version and demo
report together for each release. Passing scripted controls validates the harness's known
cases; it does not establish live-model quality or production traffic coverage.
Live API evaluations need an explicit model, credentials, scope and budget.
