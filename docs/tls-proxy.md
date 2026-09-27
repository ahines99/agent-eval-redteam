# Private HTTPS deployment verification

This is a runnable local demonstration of the secured shared-service option. The application runs
in a private Docker network behind Caddy. Only Caddy publishes a host port, and that port is bound
to `127.0.0.1`. It is not a public or remotely hosted deployment.

The [recorded evidence](evidence/tls-proxy.json) was produced by an actual HTTPS MCP client against
the application container. It records the negotiated TLS version and cipher, certificate
fingerprints, exact image identities, network assertions and authentication outcomes. The probe
uses synthetic agents and temporary tenant databases. It makes no model calls.

## Run the check

With Python dependencies installed and Docker running, from the repository root:

```shell
uv sync --frozen --all-extras
docker build -t agent-eval-portfolio .
uv run --frozen python scripts/verify_tls_proxy.py --image agent-eval-portfolio
```

For Windows Python with Docker running inside WSL Ubuntu:

```powershell
wsl.exe -d Ubuntu-22.04 -- docker build -t agent-eval-portfolio .
.venv\Scripts\python.exe scripts/verify_tls_proxy.py --wsl-distribution Ubuntu-22.04 --image agent-eval-portfolio
```

The default evidence output is `docs/evidence/tls-proxy.json`; use `--output PATH` to change it.
After TLS is ready, the script waits up to 30 seconds for the backend's unauthenticated HTTP 401
response. Caddy can serve its certificate before Uvicorn has finished starting; temporary proxy
502/503/504 responses are recorded during this readiness phase. Missing-token, invalid-token and
authenticated MCP checks then run independently with their original strict assertions. Readiness
timing and status counts appear in the evidence; a timeout reports status/error classes without
request headers or credential data.
The image option also permits CI to test its freshly built image without rebuilding it. The script
records the application's image ID, so evidence identifies the tested artifact. It pulls Caddy by
the immutable digest pinned in the script, which corresponds to the official
[Caddy 2.11.4 release](https://github.com/caddyserver/caddy/releases/tag/v2.11.4) and
[Docker image](https://hub.docker.com/_/caddy).

## What the deployment verifies

The temporary Caddy configuration is:

```caddyfile
{
    admin off
    auto_https disable_redirects
    skip_install_trust
}
https://localhost:443 {
    tls internal
    reverse_proxy backend:8000
}
```

This uses Caddy's [local certificate authority](https://caddyserver.com/docs/automatic-https) and
[HTTP reverse proxy](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy). The application
still validates bearer tokens itself; proxy headers never establish actor identity. Caddy forwards
the HTTP requests, including authorization, to the private backend.

The script proves that:

- The backend has no published host ports, runs as its non-root application user, belongs only to
  an internal Docker network, and receives its digest-only authentication configuration through a
  read-only mount. Both containers have read-only root filesystems. Their writable state lives in
  temporary named volumes. Caddy has only the `NET_BIND_SERVICE` capability needed by its binary;
  the backend has no capabilities.
- The client explicitly trusts the temporary Caddy root certificate through its own SSL context.
  Certificate verification and hostname checking remain enabled. No system trust store is modified
  and no verification-bypass flag is used. A client without that CA rejects the certificate; an
  unknown hostname is rejected during the TLS handshake.
- Missing and invalid bearer tokens return HTTP 401 through HTTPS. An authenticated MCP healthcheck
  and agent registration succeed. The registered owner is the authenticated actor despite a
  conflicting caller-supplied owner. A different tenant cannot see that agent, and its read-only
  credential cannot register an agent.

Caddy is attached to two networks: a frontend bridge that permits its loopback port publication,
and the internal backend network. The backend is attached only to the latter. Docker inspection
checks these facts; it does not merely assume them from the command line.

Only public certificate fingerprints and synthetic outcomes are saved. Raw bearer tokens stay in
client memory. Caddy generates its CA private keys inside its temporary data volume; those keys are
never copied to the host or evidence. The copied root certificate is public and temporary. The
script removes only its uniquely named containers, volumes, networks and temporary files afterward,
including the local CA and synthetic databases. Existing application and PostgreSQL containers are
not touched. Downloaded images remain cached for repeat runs.

## Scope and remaining deployment decisions

This provides real evidence for a **private, loopback HTTPS service** with an explicitly trusted
local CA. It complements the [rotation, admission and backup checks](operations-verification.md).
It does not prove public DNS, publicly trusted certificate issuance, remote credential distribution,
firewall configuration, high availability or sustained load. It runs one backend process.

A public portfolio can link to static reports and evidence while the evaluation service stays
private. Exposing a real service requires a separately chosen hostname, network policy and operator
ownership; replace this temporary local CA with the deployment's certificate policy, retain protected
tenant storage, and distribute credentials through the operator's secret-management process. This
smoke deliberately performs none of that publication or hosting work.
