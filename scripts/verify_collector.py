"""Run the official Collector locally and verify project spans in its detailed debug output.

Native Docker: python scripts/verify_collector.py
Windows/WSL Docker: python scripts/verify_collector.py --wsl-distribution Ubuntu-22.04
Only the uniquely named verification container is removed. No remote telemetry export occurs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import socket
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
IMAGE_TAG = "otel/opentelemetry-collector-contrib:0.161.0"
IMAGE_DIGEST = "sha256:fd328de2552466ad78385e1b1289c3f2402b1c45f265b252aab1955b42845ac1"
IMAGE = "otel/opentelemetry-collector-contrib@" + IMAGE_DIGEST
PRIVATE_MARKER = "synthetic-payload-do-not-export@example.invalid"
CONFIG = """receivers:
  otlp:
    protocols:
      http:
        endpoint: 0.0.0.0:4318
exporters:
  debug:
    verbosity: detailed
service:
  telemetry:
    logs:
      encoding: json
  pipelines:
    traces:
      receivers: [otlp]
      exporters: [debug]
"""


def command(arguments: list[str], timeout: int = 30) -> str:
    result = subprocess.run(arguments, capture_output=True, text=True, timeout=timeout,
                            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
    if result.returncode:
        raise RuntimeError(f"verification command failed with exit status {result.returncode}: {result.stderr.strip()}")
    return result.stdout + result.stderr


def parse_spans(logs: str) -> list[dict[str, Any]]:
    messages = []
    for line in logs.splitlines():
        if line.startswith("{"):
            record = json.loads(line)
            messages.append(record.get("msg", record.get("message", "")))
        else:
            messages.append(line)
    text = "\n".join(messages)
    records = []
    for section in re.split(r"\bSpan #\d+\s*\n", text)[1:]:
        def field(name: str, current: str = section) -> str:
            match = re.search(r"^[ \t]*" + re.escape(name) + r"[ \t]*:[ \t]*([^\n]*)", current, re.MULTILINE)
            if not match:
                raise AssertionError(f"collector span missing {name}")
            return match.group(1).strip()

        attributes: dict[str, Any] = {}
        for key, kind, value in re.findall(r"-> ([\w.]+): (Str|Int|Double)\(([^\n]*)\)", section):
            attributes[key] = int(value) if kind == "Int" else float(value) if kind == "Double" else value
        records.append({"name": field("Name"), "trace_id": field("Trace ID"), "span_id": field("ID"),
                        "parent_span_id": field("Parent ID"), "status_code": field("Status code"),
                        "status_message": field("Status message"), "attributes": attributes})
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wsl-distribution")
    parser.add_argument("--output", type=Path, default=Path("docs/evidence/collector.json"))
    args = parser.parse_args()
    docker = (["wsl.exe", "-d", args.wsl_distribution, "--", "docker"] if args.wsl_distribution else ["docker"])
    name = "agent-eval-collector-verification-" + uuid.uuid4().hex[:10]
    configuration = ROOT / "data" / "verification" / (name + ".yaml")
    configuration.parent.mkdir(parents=True, exist_ok=True)
    configuration.write_text(CONFIG, encoding="utf-8")
    mounted = str(configuration)
    if args.wsl_distribution:
        mounted = command(["wsl.exe", "-d", args.wsl_distribution, "--", "wslpath", "-a", mounted]).strip()
    created = False
    try:
        command([*docker, "pull", IMAGE], timeout=180)
        command([*docker, "create", "--name", name, "--read-only", "--cap-drop", "ALL",
                 "--security-opt", "no-new-privileges", "-p", "127.0.0.1::4318",
                 "--mount", f"type=bind,source={mounted},target=/etc/otelcol-contrib/config.yaml,readonly",
                 IMAGE, "--config=/etc/otelcol-contrib/config.yaml"])
        created = True
        command([*docker, "start", name])
        inspected = json.loads(command([*docker, "inspect", name]))[0]
        binding = inspected["NetworkSettings"]["Ports"]["4318/tcp"][0]
        assert binding["HostIp"] == "127.0.0.1"
        port = int(binding["HostPort"])
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=1):
                    break
            except OSError:
                time.sleep(0.1)
        else:
            raise TimeoutError("collector loopback receiver did not become ready")
        environment = {key: value for key, value in os.environ.items() if not key.startswith("OTEL_")}
        environment.update({
            "PYTHONPATH": str(ROOT / "src"), "OTEL_TRACES_EXPORTER": "otlp",
            "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": f"http://127.0.0.1:{port}/v1/traces",
            "OTEL_EXPORTER_OTLP_TRACES_TIMEOUT": "5", "OTEL_BSP_SCHEDULE_DELAY": "600000",
            "OTEL_SERVICE_NAME": "agent-eval-official-collector-verification", "OTEL_TRACES_SAMPLER": "always_on",
            "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost",
        })
        # Reuse the tested synthetic probe, exiting normally to exercise SDK atexit flushing.
        emitted = subprocess.run([sys.executable, str(ROOT / "scripts" / "verify_otlp.py"), "--emit", "atexit"],
                                 env=environment, capture_output=True, text=True, timeout=30,
                                 creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
        if emitted.returncode:
            raise RuntimeError("synthetic exporter process failed")
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            logs = command([*docker, "logs", name])
            records = parse_spans(logs)
            if len(records) == 3:
                break
            time.sleep(0.1)
        else:
            raise AssertionError("collector did not print exactly three decoded spans")
        assert PRIVATE_MARKER not in logs
        assert "agent-eval-official-collector-verification" in logs
        assert "exception.message" not in logs and "exception.stacktrace" not in logs
        by_name = {record["name"]: record for record in records}
        parent = by_name["transport_verification"]
        child = by_name["agent_case"]
        error = by_name["agent_case_error"]
        assert parent["parent_span_id"] == ""
        assert re.fullmatch(r"[0-9a-f]{32}", parent["trace_id"])
        for record in (child, error):
            assert record["parent_span_id"] == parent["span_id"]
            assert record["trace_id"] == parent["trace_id"]
        assert child["attributes"]["agent_id"] == "sha256:" + hashlib.sha256(PRIVATE_MARKER.encode()).hexdigest()
        assert child["attributes"]["tool_name"] == "crm.lookup"
        assert child["attributes"]["input_tokens"] == 17 and child["attributes"]["output_tokens"] == 9
        assert child["attributes"]["cost_usd"] == 0.0001
        assert error["status_code"] == "Error" and error["attributes"]["error.type"] == "RuntimeError"
        for record in records:
            assert record["status_message"] == ""
            assert record["attributes"]["latency_ms"] >= 0
            assert not {"prompt", "output", "authorization"} & record["attributes"].keys()
        command([*docker, "stop", "--time", "10", name])
        state = json.loads(command([*docker, "inspect", name]))[0]["State"]
        assert not state["Running"] and state["ExitCode"] == 0
        evidence = {
            "schema_version": 1, "verified_at": datetime.now(UTC).isoformat(),
            "python": platform.python_version(), "exporter_platform": platform.platform(),
            "docker_context": "WSL " + args.wsl_distribution if args.wsl_distribution else "native Docker",
            "collector_release": IMAGE_TAG, "collector_image_digest": IMAGE_DIGEST,
            "collector_image_id": inspected["Image"], "collector_configuration": CONFIG,
            "official_release_source": "https://github.com/open-telemetry/opentelemetry-collector-releases/releases/tag/v0.161.0",
            "official_setup_source": "https://opentelemetry.io/docs/collector/install/docker/",
            "synthetic_only": True, "collector_host_binding": "127.0.0.1",
            "collector_exit_code": state["ExitCode"], "span_count": len(records),
            "hierarchy_verified": True, "privacy_verified": True, "sdk_atexit_delivery_verified": True,
            "collector_debug_log_sha256": hashlib.sha256(logs.encode()).hexdigest(),
            "spans": sorted(records, key=lambda record: record["name"]),
            "limitations": ["Local official Collector with debug output only; no external telemetry destination",
                            "No TLS, remote authentication, persistent trace storage or UI verified",
                            "Token counts and cost are synthetic inputs; span latencies are measured"],
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
        print(f"Verified three project spans in official Collector {IMAGE_TAG}; evidence: {args.output}")
    finally:
        if created:
            command([*docker, "rm", "--force", name])
        configuration.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
