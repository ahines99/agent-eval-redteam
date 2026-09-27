"""Real HTTP/protobuf transport integration, without contacting an external collector."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


def test_real_otlp_http_delivery_and_shutdown(tmp_path):
    pytest.importorskip("opentelemetry.exporter.otlp.proto.http.trace_exporter")
    root = Path(__file__).resolve().parents[1]
    output = tmp_path / "transport.json"
    result = subprocess.run(
        [sys.executable, str(root / "scripts" / "verify_otlp.py"), "--output", str(output)],
        cwd=tmp_path, capture_output=True, text=True, timeout=60,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )
    assert result.returncode == 0, result.stderr
    evidence = json.loads(output.read_text(encoding="utf-8"))
    assert evidence["synthetic_only"]
    assert {run["shutdown_mode"] for run in evidence["runs"]} == {"explicit", "atexit"}
    for run in evidence["runs"]:
        assert run["span_count"] == 3 and run["request_count"] >= 1
        assert run["hierarchy_verified"] and run["privacy_verified"] and run["shutdown_delivery_verified"]
        assert run["synthetic_header_verified"]
    assert "synthetic-payload-do-not-export" not in output.read_text(encoding="utf-8")
