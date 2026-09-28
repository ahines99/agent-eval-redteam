"""A small, explicit, restartable state machine.

Every completed step persists its artifact (with a content hash) and an audit event before the next
step starts. Re-running a run therefore skips completed steps, which makes resume-after-crash and
resume-after-approval the same operation. Steps must be idempotent (all writes use deterministic ids).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol

from ..domain.models import SCHEMA_VERSION, AuditEvent, canonical_hash
from ..domain.policies import PolicyViolation
from ..observability import log, span


class Status(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    NEEDS_REVIEW = "needs_review"
    COMPLETE = "complete"
    FAILED = "failed"


class TransientError(Exception):
    """A dependency hiccup worth retrying (timeouts, connection resets)."""


@dataclass
class StepResult:
    artifact: dict[str, Any]
    pause: bool = False  # stop at a human approval boundary


@dataclass
class RunContext:
    run_id: str
    run: dict[str, Any]
    actor: str
    artifacts: dict[str, dict[str, Any]] = field(default_factory=dict)


class Step(Protocol):
    name: str

    async def execute(self, ctx: RunContext) -> StepResult: ...


class RunStore(Protocol):
    def update_run(self, run_id: str, **values: Any) -> None: ...
    def save_artifact(self, run_id: str, step: str, payload: dict[str, Any]) -> str: ...
    def artifacts(self, run_id: str) -> dict[str, dict[str, Any]]: ...
    def audit(self, event: AuditEvent) -> None: ...
    def transition_run(self, run_id: str, events: list[AuditEvent], **values: Any) -> None: ...
    def checkpoint(self, run_id: str, step: str, payload: dict[str, Any], events: list[AuditEvent],
                   *, pause: bool) -> tuple[dict[str, Any], bool]: ...
    def get_approval(self, run_id: str, gate: str) -> dict[str, Any] | None: ...


def _event(ctx: RunContext, step: str, event_type: str, **payload: Any) -> AuditEvent:
    return AuditEvent(run_id=ctx.run_id, step=step, event_type=event_type, actor=ctx.actor,
                      created_at=datetime.now(UTC),
                      payload=payload)


async def run_steps(ctx: RunContext, steps: Sequence[Step], store: RunStore, *, max_attempts: int = 2) -> Status:
    done = store.artifacts(ctx.run_id)
    ctx.artifacts = {name: a["payload"] for name, a in done.items()}
    gate = ctx.artifacts.get("Gate release")
    if (gate and gate["decision"]["outcome"] == "review"
            and store.get_approval(ctx.run_id, "Gate release") is None):
        store.transition_run(ctx.run_id, [_event(ctx, "Gate release", "paused_for_review")],
                             status=Status.NEEDS_REVIEW.value, current_step="Gate release")
        return Status.NEEDS_REVIEW
    store.transition_run(ctx.run_id, [_event(ctx, "workflow", "run_started", resumed_steps=sorted(done))],
                         status=Status.RUNNING.value, error=None)

    for step in steps:
        if step.name in done:
            continue
        store.transition_run(ctx.run_id, [_event(ctx, step.name, "step_started")], current_step=step.name)
        for attempt in range(1, max_attempts + 1):
            try:
                with span(f"step:{step.name}", run_id=ctx.run_id, attempt=attempt):
                    result = await step.execute(ctx)
                break
            except TransientError as exc:
                store.audit(_event(ctx, step.name, "step_retry", attempt=attempt, error=str(exc)))
                if attempt == max_attempts:
                    return _fail(ctx, store, step.name, f"transient failure after {attempt} attempts: {exc}")
            except PolicyViolation as exc:
                return _fail(ctx, store, step.name, f"policy: {exc}")
            except Exception as exc:  # noqa: BLE001 - any step crash must land in a controlled FAILED state
                log.exception("step %s crashed", step.name)
                return _fail(ctx, store, step.name, f"{type(exc).__name__}: {exc}")

        digest = canonical_hash(result.artifact)
        events = [_event(ctx, step.name, "step_completed", artifact_hash=digest, schema_version=SCHEMA_VERSION)]
        if result.pause:
            events.append(_event(ctx, step.name, "paused_for_review"))
        artifact, pause = store.checkpoint(ctx.run_id, step.name, result.artifact, events, pause=result.pause)
        ctx.artifacts[step.name] = artifact
        if pause:
            return Status.NEEDS_REVIEW

    store.transition_run(ctx.run_id, [_event(ctx, "workflow", "run_completed")],
                         status=Status.COMPLETE.value, current_step=None)
    return Status.COMPLETE


def _fail(ctx: RunContext, store: RunStore, step: str, message: str) -> Status:
    store.transition_run(ctx.run_id, [_event(ctx, step, "step_failed", error=message)],
                         status=Status.FAILED.value, error=f"{step}: {message}")
    return Status.FAILED
