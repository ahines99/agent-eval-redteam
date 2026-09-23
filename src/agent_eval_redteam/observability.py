"""Tracing and logging hooks.

OpenTelemetry API calls are no-ops until an SDK/exporter is configured by the host process, so this
adds no runtime dependency on a collector. The durable record is the `audit_events` table; spans are
for latency analysis. Only ids, hashes and counts are attached, never prompts, outputs or PII.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from opentelemetry import trace

tracer = trace.get_tracer("agent_eval_redteam")
log = logging.getLogger("agent_eval_redteam")


@contextmanager
def span(name: str, **attributes: Any) -> Iterator[Any]:
    with tracer.start_as_current_span(name) as s:
        for key, value in attributes.items():
            if value is not None:
                s.set_attribute(key, value if isinstance(value, (str, int, float, bool)) else str(value))
        yield s
