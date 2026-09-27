"""Opt-in operational tracing. Prompts, outputs and exception text must never be exported."""

from __future__ import annotations

import atexit
import hashlib
import logging
import math
import os
import re
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from threading import RLock
from time import perf_counter
from typing import Any

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

log = logging.getLogger("agent_eval_redteam")
# Own our provider instead of replacing an embedding application's global provider.
tracer = trace.NoOpTracerProvider().get_tracer("agent_eval_redteam")
_provider: Any = None
_lock = RLock()
_IDENTIFIER = re.compile(r"[a-zA-Z0-9_.:/-]{1,128}\Z")
_TEXT_FIELDS = frozenset({
    "run_id", "case_id", "agent_id", "trace_id", "suite_id", "model", "phase",
    "injected_tool", "tool_name", "stop_reason", "error.type",
})
_NUMBER_FIELDS = frozenset({
    "attempt", "repeat", "tool_calls", "input_tokens", "output_tokens", "latency_ms", "cost_usd",
    "case_count", "finding_count",
})
_USER_IDS = frozenset({"agent_id", "case_id", "suite_id"})


def configure_telemetry() -> Any:
    """Configure once from standard OTEL environment variables, returning the owned provider.

    Explicit exporter or endpoint configuration opts in. Only OTLP HTTP/protobuf and console
    (stderr, safe for MCP stdio) are supported. Missing optional dependencies fail clearly when
    opted in. SDK sampler, batch processor, resource and HTTP exporter settings use SDK defaults
    and standard environment variables. No global tracer provider is changed.
    """
    global tracer, _provider
    with _lock:
        if _provider is not None:
            return _provider
        if os.environ.get("OTEL_SDK_DISABLED", "").strip().lower() == "true":
            return None
        exporters = os.environ.get("OTEL_TRACES_EXPORTER", "").strip().lower()
        if not exporters:
            if not (os.environ.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
                    or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")):
                return None
            exporters = "otlp"
        if exporters == "none":
            return None
        if exporters not in {"otlp", "console"}:
            raise ValueError("OTEL_TRACES_EXPORTER must be none, otlp, or console")
        protocol = os.environ.get("OTEL_EXPORTER_OTLP_TRACES_PROTOCOL",
                                  os.environ.get("OTEL_EXPORTER_OTLP_PROTOCOL", "http/protobuf"))
        if exporters == "otlp" and protocol != "http/protobuf":
            raise ValueError("Only OTLP http/protobuf is supported")
        try:
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

            if exporters == "otlp":
                from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

                exporter: Any = OTLPSpanExporter()
            else:
                exporter = ConsoleSpanExporter(out=sys.stderr)
        except ImportError as exc:
            raise RuntimeError("Tracing requires installation of agent-eval-redteam[observability]") from exc
        resource = Resource.create({"service.name": os.environ.get("OTEL_SERVICE_NAME", "agent-eval-redteam")})
        provider = TracerProvider(resource=resource, shutdown_on_exit=False)
        try:
            provider.add_span_processor(BatchSpanProcessor(exporter))
        except BaseException:
            exporter.shutdown()
            provider.shutdown()
            raise
        _provider = provider
        tracer = provider.get_tracer("agent_eval_redteam")
        atexit.register(shutdown_telemetry)
        return provider


def shutdown_telemetry() -> None:
    """Drain the configured batch exporter once and restore no-op tracing."""
    global tracer, _provider
    with _lock:
        provider, _provider = _provider, None
        tracer = trace.NoOpTracerProvider().get_tracer("agent_eval_redteam")
        if provider is not None:
            atexit.unregister(shutdown_telemetry)
            provider.shutdown()


class OperationalSpan:
    """Expose only filtered attributes; callers cannot accidentally record raw exception events."""

    def __init__(self, underlying: trace.Span) -> None:
        self._span = underlying

    def set_attribute(self, key: str, value: Any) -> None:
        # Registry IDs are user-chosen, unlike generated run/trace UUIDs. Preserve correlation
        # without exporting their raw value (agent IDs normally contain an @ separator).
        if key in _USER_IDS and isinstance(value, str):
            value = "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()
        text_value = key in _TEXT_FIELDS and isinstance(value, str) and _IDENTIFIER.fullmatch(value)
        number_value = (key in _NUMBER_FIELDS and isinstance(value, (int, float))
                        and not isinstance(value, bool) and math.isfinite(value) and value >= 0)
        if text_value or number_value:
            self._span.set_attribute(key, value)


@contextmanager
def span(name: str, **attributes: Any) -> Iterator[OperationalSpan]:
    """Record allowlisted operational attributes and class-only failures, including cancellation.

    Names must be static application operation names; identifier values must be non-sensitive.
    Arbitrary objects, free text, event payloads and exception messages are deliberately omitted.
    """
    with tracer.start_as_current_span(name, record_exception=False, set_status_on_exception=False) as underlying:
        safe = OperationalSpan(underlying)
        for key, value in attributes.items():
            safe.set_attribute(key, value)
        started = perf_counter()
        try:
            yield safe
        except BaseException as exc:
            safe.set_attribute("error.type", type(exc).__name__)
            underlying.set_status(Status(StatusCode.ERROR))
            raise
        finally:
            safe.set_attribute("latency_ms", (perf_counter() - started) * 1000)
