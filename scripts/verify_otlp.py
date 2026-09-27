"""Verify the real OTLP HTTP exporter against a local protobuf receiver, without a collector claim.

Run: python scripts/verify_otlp.py --output docs/evidence/otlp-transport.json
Requires the project's observability extra. No external network or model calls are made.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import secrets
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_MARKER = "synthetic-payload-do-not-export@example.invalid"


def emit(mode: str) -> None:
    """Executed in an isolated subprocess with the actual SDK HTTP exporter."""
    from agent_eval_redteam.observability import configure_telemetry, shutdown_telemetry, span

    configure_telemetry()
    with span("transport_verification", run_id="synthetic-run-1", case_count=2):
        with span("agent_case", agent_id=PRIVATE_MARKER, case_id="synthetic-case-1",
                  tool_name="crm.lookup", input_tokens=17, output_tokens=9, cost_usd=0.0001,
                  prompt=PRIVATE_MARKER, output=PRIVATE_MARKER, authorization=PRIVATE_MARKER):
            pass
        try:
            with span("agent_case_error", case_id="synthetic-case-2"):
                raise RuntimeError(PRIVATE_MARKER)
        except RuntimeError:
            pass
    if mode == "explicit":
        shutdown_telemetry()
    # atexit mode deliberately returns without a force_flush or explicit shutdown.


def verify(mode: str) -> dict[str, Any]:
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
        ExportTraceServiceRequest,
        ExportTraceServiceResponse,
    )

    requests: list[dict[str, Any]] = []
    errors: list[str] = []
    auth_token = secrets.token_hex(24)

    class Receiver(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            pass

        def do_POST(self) -> None:  # noqa: N802 - standard library HTTP handler contract
            try:
                self.connection.settimeout(5)
                if self.path != "/v1/traces" or self.headers.get("x-smoke-token") != auth_token:
                    raise ValueError("invalid receiver path or synthetic header")
                if self.headers.get("Content-Type") != "application/x-protobuf":
                    raise ValueError("expected OTLP protobuf")
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 1_048_576:
                    raise ValueError("unexpected payload length")
                body = self.rfile.read(length)
                if PRIVATE_MARKER.encode() in body or auth_token.encode() in body:
                    raise ValueError("private marker leaked into trace body")
                message = ExportTraceServiceRequest()
                message.ParseFromString(body)
                requests.append({"message": message, "bytes": len(body)})
                response = ExportTraceServiceResponse().SerializeToString()
                self.send_response(200)
                self.send_header("Content-Type", "application/x-protobuf")
                self.send_header("Content-Length", str(len(response)))
                self.end_headers()
                self.wfile.write(response)
            except Exception as exc:
                errors.append(type(exc).__name__)
                self.send_error(400, "OTLP verification rejected request")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Receiver)
    receiver = Thread(target=server.serve_forever, daemon=True)
    receiver.start()
    environment = {key: value for key, value in os.environ.items() if not key.startswith("OTEL_")}
    environment.update({
        "PYTHONPATH": str(ROOT / "src"),
        "OTEL_TRACES_EXPORTER": "otlp",
        "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": f"http://127.0.0.1:{server.server_port}/v1/traces",
        "OTEL_EXPORTER_OTLP_TRACES_HEADERS": "x-smoke-token=" + auth_token,
        "OTEL_EXPORTER_OTLP_TRACES_TIMEOUT": "5",
        "OTEL_BSP_SCHEDULE_DELAY": "600000",
        "OTEL_SERVICE_NAME": "agent-eval-transport-smoke",
        "OTEL_TRACES_SAMPLER": "always_on",
        "NO_PROXY": "127.0.0.1,localhost",
        "no_proxy": "127.0.0.1,localhost",
    })
    try:
        with tempfile.TemporaryDirectory(prefix="agent-eval-otlp-") as working:
            result = subprocess.run(
                [sys.executable, str(Path(__file__).resolve()), "--emit", mode],
                cwd=working, env=environment, capture_output=True, text=True, timeout=30,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
        if result.returncode:
            # Child logs could contain exporter endpoint/header settings: do not persist them.
            raise RuntimeError(f"exporter subprocess failed with exit status {result.returncode}")
    finally:
        server.shutdown()
        server.server_close()
        receiver.join(timeout=5)
    if errors or not requests:
        raise AssertionError("receiver rejected OTLP or received no requests")

    records: list[dict[str, Any]] = []
    services: set[str] = set()
    for request in requests:
        for resource in request["message"].resource_spans:
            services.update(item.value.string_value for item in resource.resource.attributes
                            if item.key == "service.name")
            for scope in resource.scope_spans:
                for record in scope.spans:
                    attributes = {item.key: getattr(item.value, item.value.WhichOneof("value"))
                                  for item in record.attributes}
                    records.append({
                        "name": record.name, "trace_id": record.trace_id.hex(), "span_id": record.span_id.hex(),
                        "parent_span_id": record.parent_span_id.hex(), "attributes": attributes,
                        "status_code": record.status.code, "status_message": record.status.message,
                        "event_count": len(record.events),
                        "duration_ms": (record.end_time_unix_nano - record.start_time_unix_nano) / 1_000_000,
                    })
    assert services == {"agent-eval-transport-smoke"}
    assert len(records) == 3
    by_name = {record["name"]: record for record in records}
    parent = by_name["transport_verification"]
    child = by_name["agent_case"]
    error = by_name["agent_case_error"]
    assert not parent["parent_span_id"]
    assert parent["attributes"]["run_id"] == "synthetic-run-1"
    for record in (child, error):
        assert record["parent_span_id"] == parent["span_id"]
        assert record["trace_id"] == parent["trace_id"]
    assert child["attributes"]["agent_id"] == "sha256:" + hashlib.sha256(PRIVATE_MARKER.encode()).hexdigest()
    assert child["attributes"]["tool_name"] == "crm.lookup"
    assert child["attributes"]["input_tokens"] == 17
    assert child["attributes"]["output_tokens"] == 9
    assert child["attributes"]["cost_usd"] == 0.0001
    assert error["status_code"] == 2  # OTLP STATUS_CODE_ERROR
    assert error["attributes"]["error.type"] == "RuntimeError"
    for record in records:
        assert record["attributes"]["latency_ms"] >= 0
        assert record["duration_ms"] >= 0
        assert record["event_count"] == 0 and record["status_message"] == ""
        assert not {"prompt", "output", "authorization"} & record["attributes"].keys()
    return {
        "shutdown_mode": mode, "transport": "OTLP HTTP/protobuf over localhost TCP",
        "request_count": len(requests), "received_bytes": sum(request["bytes"] for request in requests),
        "span_count": len(records), "synthetic_header_verified": True,
        "hierarchy_verified": True, "privacy_verified": True, "shutdown_delivery_verified": True,
        "spans": sorted(records, key=lambda record: record["name"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("docs/evidence/otlp-transport.json"))
    parser.add_argument("--emit", choices=("explicit", "atexit"), help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.emit:
        emit(args.emit)
        return 0
    result = {
        "schema_version": 1, "verified_at": datetime.now(UTC).isoformat(),
        "python": platform.python_version(), "platform": platform.platform(),
        "scope": "Real SDK exporter and local independent protobuf receiver; no official collector deployment.",
        "synthetic_only": True, "runs": [verify("explicit"), verify("atexit")],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"Verified 6 spans over OTLP HTTP, explicit and atexit flushing; evidence: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
