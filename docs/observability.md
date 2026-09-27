# Operational tracing

Tracing defaults to a no-op: installing the package or SDK does not create an exporter or contact a
collector. Install `pip install 'agent-eval-redteam[observability]'` to opt in. The CLI and HTTP entry
points call `configure_telemetry()`; embedded applications should call it before starting work.

Set `OTEL_TRACES_EXPORTER=otlp` and `OTEL_EXPORTER_OTLP_ENDPOINT=https://collector.example.com:4318`
for OTLP HTTP/protobuf. Alternatively, set `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` to the full traces
URL, including `/v1/traces`. Either endpoint also opts in when the exporter variable is absent.
Configure authentication through `OTEL_EXPORTER_OTLP_HEADERS` or the traces-specific variant.
Only `http/protobuf` is supported; explicitly requesting another protocol or exporter fails startup.
The SDK honors standard sampler, batch processor, certificate, timeout, and resource environment
settings. Use `OTEL_SERVICE_NAME` to override the default `agent-eval-redteam` service name.

For local inspection set `OTEL_TRACES_EXPORTER=console`; spans go to stderr so MCP stdio remains
valid. `OTEL_SDK_DISABLED=true` or `OTEL_TRACES_EXPORTER=none` disables tracing at startup even
when endpoint variables exist. Configuration is idempotent; restart to apply environment changes.

Workflow steps and agent cases emit parent/child spans. Allowed attributes are run, case, agent,
trace and suite IDs; model, phase and tool identifiers; stop reason; attempt/repeat and call counts;
input/output tokens; latency in milliseconds; cost in USD; case/finding counts; and error class.
Latency is measured wall-clock elapsed time. Other attributes, complex values, non-finite or negative
metrics, and free-text identifier values are discarded. Keep identifiers non-sensitive. Never put
prompts, outputs, names, addresses, credentials or other personal data in identifiers, span names or
operator-supplied resource attributes. Exceptions produce error status and class only: messages and
stack traces are not recorded. The durable audit trail remains in the database.
User-chosen agent, case and suite IDs are exported as `sha256:` digests for stable correlation;
generated run and trace IDs retain their original values.

The process owns a separate provider and does not replace a host application's global provider.
Normal interpreter exit drains the batch processor. Hosts with explicit lifespan handling should
call `shutdown_telemetry()` after all evaluation tasks complete; repeated shutdown calls are safe.
Forced termination cannot guarantee buffered spans are exported. These are tracing hooks; no
metrics or logs exporter is configured.

## Verify actual OTLP transport locally

After installing the observability extra, run:

```shell
python scripts/verify_otlp.py --output docs/evidence/otlp-transport.json
```

The command starts an HTTP receiver bound to a random localhost port, then runs the actual SDK
HTTP exporter in a separate Python process. The receiver decodes the OTLP protobuf request,
acknowledges it with the protocol's response message, and verifies one parent plus two child
spans, IDs, token/cost/tool fields, error class, and absence of synthetic private payloads. It also
checks a synthetic authentication header without saving its value. Two fresh processes verify
explicit shutdown and normal `atexit` delivery. A ten-minute batch interval ensures normal timer
exports cannot account for delivery during this short check.

The JSON output contains only synthetic span data and verification results. Span durations are
measured; token counts and cost are synthetic instrumentation inputs, not provider usage. Run
`python -m pytest tests/test_otlp_transport.py -q` for the repeatable integration check.

This first check validates the exporter, TCP/HTTP/protobuf transport and flushing against an
independent local receiver. The official Collector is exercised separately below.

## Verify the official Collector

The [official Collector release 0.161.0](https://github.com/open-telemetry/opentelemetry-collector-releases/releases/tag/v0.161.0)
was exercised locally using its contrib Docker image and the documented
[OTLP receiver plus detailed debug exporter](https://opentelemetry.io/docs/collector/install/docker/).
The image is pinned by immutable digest in `scripts/verify_collector.py`; the recorded image ID,
digest, configuration and parsed spans are in [collector evidence](evidence/collector.json).

```shell
# Docker available directly to this Python process:
python scripts/verify_collector.py --output docs/evidence/collector.json

# Windows Python using Docker inside the named WSL distribution:
python scripts/verify_collector.py --wsl-distribution Ubuntu-22.04 --output docs/evidence/collector.json
```

Docker must already be running. The script pulls the pinned image if needed, creates a uniquely
named temporary container, and publishes its OTLP HTTP receiver on a random **loopback-only** port.
The container uses a read-only filesystem, drops capabilities and has no network exporter.
Its only trace destination is the detailed debug log. The project SDK runs in a fresh subprocess
and sends one parent plus two children on normal interpreter exit, with a ten-minute batching
interval to establish shutdown delivery. The script parses the Collector's own decoded log output
and asserts IDs, relationships, tokens, cost, latency, class-only errors and absence of synthetic
private payloads. It also verifies a clean Collector stop, then removes that container and its
temporary configuration. Other containers and images are left intact.

This run validates project-to-official-Collector delivery on local Docker/WSL, including SDK
shutdown flushing. It does not establish a remote deployment, TLS, remote authentication policy,
persistent trace storage or a trace-viewing backend. Token/cost fields in this probe are synthetic;
span durations are measured. The earlier independent-receiver check remains useful for testing
the protocol without requiring Docker.
