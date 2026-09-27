from __future__ import annotations

import asyncio
import hashlib
import os

import pytest
from opentelemetry.trace import StatusCode

from agent_eval_redteam import observability


@pytest.fixture(autouse=True)
def clean_telemetry(monkeypatch):
    observability.shutdown_telemetry()
    for key in os.environ:
        if key.startswith("OTEL_"):
            monkeypatch.delenv(key)
    yield
    observability.shutdown_telemetry()


@pytest.fixture
def spans(monkeypatch):
    # Core installs can run without the optional SDK; observability CI installs the extra.
    sdk = pytest.importorskip("opentelemetry.sdk.trace")
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    exporter = InMemorySpanExporter()
    provider = sdk.TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(observability, "tracer", provider.get_tracer("test"))
    yield exporter
    provider.shutdown()


def test_default_does_not_configure_sdk_or_export(monkeypatch):
    monkeypatch.setenv("OTEL_SERVICE_NAME", "name-alone-is-not-opt-in")
    assert observability.configure_telemetry() is None
    with observability.span("noop", run_id="run-1"):
        pass
    assert observability._provider is None


@pytest.mark.parametrize("disable", ["OTEL_SDK_DISABLED", "OTEL_TRACES_EXPORTER"])
def test_explicit_disable_wins_over_endpoint(monkeypatch, disable):
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://unused.invalid")
    monkeypatch.setenv(disable, "true" if disable == "OTEL_SDK_DISABLED" else "none")
    assert observability.configure_telemetry() is None


def test_span_hierarchy_and_operational_fields(spans):
    with observability.span("step:Run baseline", run_id="run-1", attempt=1):  # noqa: SIM117 - show hierarchy
        with observability.span("agent_case", case_id="case-1", agent_id="agent-1", model="test-model",
                                phase="baseline", repeat=0, injected_tool="crm.lookup") as current:
            current.set_attribute("tool_calls", 2)
            current.set_attribute("input_tokens", 12)
            current.set_attribute("output_tokens", 8)
            current.set_attribute("cost_usd", 0.02)
            current.set_attribute("stop_reason", "end_turn")
    child, parent = spans.get_finished_spans()
    assert child.parent.span_id == parent.context.span_id
    assert child.context.trace_id == parent.context.trace_id
    assert parent.attributes["run_id"] == "run-1"
    assert child.attributes["tool_calls"] == 2
    assert child.attributes["input_tokens"] == 12
    assert child.attributes["output_tokens"] == 8
    assert child.attributes["cost_usd"] == 0.02
    assert child.attributes["injected_tool"] == "crm.lookup"
    assert child.attributes["agent_id"] == "sha256:" + hashlib.sha256(b"agent-1").hexdigest()
    assert child.attributes["latency_ms"] >= 0


@pytest.mark.parametrize("error", [RuntimeError, asyncio.CancelledError])
def test_exception_only_exports_class(spans, error):
    with pytest.raises(error), observability.span("agent_case"):
        raise error("prompt: customer@example.com, credential=secret-value")
    record, = spans.get_finished_spans()
    assert record.status.status_code == StatusCode.ERROR
    assert record.status.description is None
    assert record.attributes["error.type"] == error.__name__
    assert not record.events
    assert "secret-value" not in record.to_json()


def test_rejects_payloads_and_non_operational_attributes(spans):
    class Unsafe:
        def __str__(self):
            raise AssertionError("Do not stringify arbitrary payloads")

    with observability.span("agent_case", prompt="secret", output="private", actor="person@example.com",
                            authorization="Bearer secret", run_id=Unsafe()) as current:
        current.set_attribute("tool_calls", {"private": "data"})
        current.set_attribute("model", "person@example.com")
        current.set_attribute("stop_reason", "raw agent output with spaces")
        current.set_attribute("cost_usd", float("nan"))
        current.set_attribute("input_tokens", -1)
        current.set_attribute("output_tokens", True)
    record, = spans.get_finished_spans()
    assert set(record.attributes) == {"latency_ms"}


def test_user_defined_identifiers_are_hashed(spans):
    with observability.span("agent_case", agent_id="private@example.com@1", case_id="private case details"):
        pass
    record, = spans.get_finished_spans()
    assert record.attributes["agent_id"].startswith("sha256:")
    assert record.attributes["case_id"].startswith("sha256:")
    assert "private" not in record.to_json()


def test_console_configuration_idempotent_and_shutdown_flushes(monkeypatch, capsys):
    pytest.importorskip("opentelemetry.sdk")
    monkeypatch.setenv("OTEL_TRACES_EXPORTER", "console")
    monkeypatch.setenv("OTEL_SERVICE_NAME", "eval-test")
    provider = observability.configure_telemetry()
    assert observability.configure_telemetry() is provider
    assert provider.resource.attributes["service.name"] == "eval-test"
    with observability.span("configured", run_id="run-1"):
        pass
    observability.shutdown_telemetry()
    observability.shutdown_telemetry()
    captured = capsys.readouterr()
    assert captured.out == ""
    assert '"name": "configured"' in captured.err
    assert observability._provider is None


def test_otlp_endpoint_opts_in_without_network(monkeypatch):
    http = pytest.importorskip("opentelemetry.exporter.otlp.proto.http.trace_exporter")
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    exporter = InMemorySpanExporter()
    monkeypatch.setattr(http, "OTLPSpanExporter", lambda: exporter)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "https://collector.invalid/v1/traces")
    provider = observability.configure_telemetry()
    with observability.span("otlp-configured"):
        pass
    assert provider.force_flush()
    assert len(exporter.get_finished_spans()) == 1


@pytest.mark.parametrize("key,value", [("OTEL_TRACES_EXPORTER", "unknown"),
                                      ("OTEL_EXPORTER_OTLP_PROTOCOL", "grpc")])
def test_unsupported_configuration_fails_explicitly(monkeypatch, key, value):
    monkeypatch.setenv("OTEL_TRACES_EXPORTER", "otlp")
    monkeypatch.setenv(key, value)
    with pytest.raises(ValueError):
        observability.configure_telemetry()
