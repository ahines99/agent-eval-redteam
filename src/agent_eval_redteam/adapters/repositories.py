"""Persistence: the workflow system of record (SQLAlchemy Core; SQLite locally, PostgreSQL in deployment)."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    PrimaryKeyConstraint,
    String,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
    insert,
    select,
    update,
)
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool

from ..domain.models import AuditEvent, Confidence, EvidenceRef, Finding
from ..domain.policies import Authorization
from ..domain.project_models import AgentRecord, EvalSuite, Trace

NAMESPACE = uuid.UUID("7f1d2c3e-4b5a-4c6d-9e8f-0a1b2c3d4e5f")


def now() -> datetime:
    return datetime.now(UTC)


def canonical_hash(obj: Any) -> str:
    blob = json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode()
    return "sha256:" + hashlib.sha256(blob).hexdigest()


def stable_id(*parts: str) -> str:
    """Deterministic ids make every write idempotent: re-executing a step re-derives the same keys."""
    return str(uuid.uuid5(NAMESPACE, "|".join(parts)))


metadata = MetaData()

agents = Table(
    "agents", metadata,
    Column("agent_id", String(160), primary_key=True),
    Column("name", String(64), nullable=False),
    Column("version", String(64), nullable=False),
    Column("adapter", String(32), nullable=False),
    Column("environment", String(32), nullable=False),
    Column("owner", Text, nullable=False),
    Column("config", JSON, nullable=False),
    Column("config_hash", String(80), nullable=False),
    Column("registered_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("name", "version"),
)

eval_suites = Table(
    "eval_suites", metadata,
    Column("suite_id", String(64), nullable=False),
    Column("version", String(32), nullable=False),
    Column("content_hash", String(80), nullable=False),
    Column("definition", JSON, nullable=False),
    Column("registered_by", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint("suite_id", "version"),
)

authorizations = Table(
    "authorizations", metadata,
    Column("authorization_id", String(36), primary_key=True),
    Column("agent_id", String(160), ForeignKey("agents.agent_id"), nullable=False),
    Column("categories", JSON, nullable=False),
    Column("approved_by", Text, nullable=False),
    Column("reason", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
)

workflow_runs = Table(
    "workflow_runs", metadata,
    Column("run_id", String(36), primary_key=True),
    Column("project_type", Text, nullable=False),
    Column("status", String(32), nullable=False),
    Column("current_step", Text),
    Column("agent_id", String(160), ForeignKey("agents.agent_id"), nullable=False),
    Column("suite_id", String(64), nullable=False),
    Column("suite_version", String(32), nullable=False),
    Column("baseline_run_id", String(36)),
    Column("idempotency_key", String(200), unique=True),
    Column("requested_by", Text, nullable=False),
    Column("error", Text),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

run_artifacts = Table(
    "run_artifacts", metadata,
    Column("run_id", String(36), ForeignKey("workflow_runs.run_id"), nullable=False),
    Column("step", String(64), nullable=False),
    Column("payload", JSON, nullable=False),
    Column("content_hash", String(80), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint("run_id", "step"),
)

traces = Table(
    "traces", metadata,
    Column("trace_id", String(36), primary_key=True),
    Column("run_id", String(36), ForeignKey("workflow_runs.run_id"), nullable=False),
    Column("case_id", String(64), nullable=False),
    Column("phase", String(16), nullable=False),
    Column("repeat", Integer, nullable=False),
    Column("content_hash", String(80), nullable=False),
    Column("body", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

evidence = Table(
    "evidence", metadata,
    Column("evidence_id", String(36), primary_key=True),
    Column("run_id", String(36), ForeignKey("workflow_runs.run_id")),
    Column("source_uri", Text, nullable=False),
    Column("source_type", String(32), nullable=False),
    Column("as_of", DateTime(timezone=True)),
    Column("content_hash", String(80), nullable=False),
    Column("metadata", JSON, nullable=False, default=dict),
)

findings = Table(
    "findings", metadata,
    Column("finding_id", String(36), primary_key=True),
    Column("run_id", String(36), ForeignKey("workflow_runs.run_id")),
    Column("finding_type", String(64), nullable=False),
    Column("severity", String(16), nullable=False),
    Column("case_id", String(64)),
    Column("title", Text, nullable=False),
    Column("statement", Text, nullable=False),
    Column("confidence", String(16), nullable=False),
    Column("assumptions", JSON, nullable=False, default=list),
    Column("metadata", JSON, nullable=False, default=dict),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

finding_evidence = Table(
    "finding_evidence", metadata,
    Column("finding_id", String(36), ForeignKey("findings.finding_id"), nullable=False),
    Column("evidence_id", String(36), ForeignKey("evidence.evidence_id"), nullable=False),
    Column("relation", String(32), nullable=False),
    PrimaryKeyConstraint("finding_id", "evidence_id", "relation"),
)

approvals = Table(
    "approvals", metadata,
    Column("approval_id", String(36), primary_key=True),
    Column("run_id", String(36), ForeignKey("workflow_runs.run_id"), nullable=False),
    Column("gate", String(64), nullable=False),
    Column("decision", String(16), nullable=False),
    Column("approver", Text, nullable=False),
    Column("reason", Text, nullable=False),
    Column("override", Boolean, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("run_id", "gate"),
)

audit_events = Table(
    "audit_events", metadata,
    Column("event_id", Integer, primary_key=True, autoincrement=True),
    Column("run_id", String(36)),
    Column("step", Text, nullable=False),
    Column("actor", Text, nullable=False),
    Column("event_type", String(64), nullable=False),
    Column("payload", JSON, nullable=False, default=dict),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

run_metrics = Table(  # denormalised per-run summary used for comparison and regression monitoring
    "run_metrics", metadata,
    Column("run_id", String(36), ForeignKey("workflow_runs.run_id"), primary_key=True),
    Column("agent_name", String(64), nullable=False),
    Column("suite_id", String(64), nullable=False),
    Column("suite_version", String(32), nullable=False),
    Column("pass_rate", Float, nullable=False),
    Column("scorecard", JSON, nullable=False),
    Column("case_outcomes", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)


def _aware(dt: datetime | None) -> datetime | None:
    # SQLite drops tzinfo; everything is stored in UTC.
    return dt.replace(tzinfo=UTC) if dt is not None and dt.tzinfo is None else dt


class Repository:
    def __init__(self, url: str) -> None:
        kwargs: dict[str, Any] = {}
        if url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False}
            if ":memory:" in url or url in {"sqlite://", "sqlite+pysqlite://"}:
                kwargs["poolclass"] = StaticPool
            else:
                db_path = url.split("///", 1)[-1]
                Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.engine: Engine = create_engine(url, **kwargs)
        metadata.create_all(self.engine)

    # ------------------------------------------------------------ agents

    def insert_agent(self, rec: AgentRecord) -> None:
        with self.engine.begin() as c:
            c.execute(insert(agents).values(**rec.model_dump(mode="python")))

    def get_agent(self, agent_id: str) -> AgentRecord | None:
        with self.engine.connect() as c:
            row = c.execute(select(agents).where(agents.c.agent_id == agent_id)).mappings().first()
        return AgentRecord(**{**row, "registered_at": _aware(row["registered_at"])}) if row else None

    def list_agents(self) -> list[AgentRecord]:
        with self.engine.connect() as c:
            rows = c.execute(select(agents).order_by(agents.c.name, agents.c.version)).mappings().all()
        return [AgentRecord(**{**r, "registered_at": _aware(r["registered_at"])}) for r in rows]

    # ------------------------------------------------------------ suites

    def insert_suite(self, suite: EvalSuite, content_hash: str, registered_by: str) -> None:
        with self.engine.begin() as c:
            c.execute(insert(eval_suites).values(
                suite_id=suite.suite_id, version=suite.version, content_hash=content_hash,
                definition=suite.model_dump(mode="json"), registered_by=registered_by, created_at=now()))

    def get_suite(self, suite_id: str, version: str) -> tuple[EvalSuite, str] | None:
        with self.engine.connect() as c:
            row = c.execute(select(eval_suites).where(eval_suites.c.suite_id == suite_id,
                                                      eval_suites.c.version == version)).mappings().first()
        return (EvalSuite.model_validate(row["definition"]), row["content_hash"]) if row else None

    def list_suites(self) -> list[dict[str, Any]]:
        with self.engine.connect() as c:
            rows = c.execute(select(eval_suites.c.suite_id, eval_suites.c.version, eval_suites.c.content_hash,
                                    eval_suites.c.definition)).mappings().all()
        return [{"suite_id": r["suite_id"], "version": r["version"], "content_hash": r["content_hash"],
                 "n_cases": len(r["definition"]["cases"]), "description": r["definition"]["description"]}
                for r in rows]

    # ------------------------------------------------------------ authorizations

    def insert_authorization(self, auth: Authorization) -> None:
        with self.engine.begin() as c:
            c.execute(insert(authorizations).values(**auth.model_dump(mode="python")))

    def authorizations_for(self, agent_id: str) -> list[Authorization]:
        with self.engine.connect() as c:
            rows = c.execute(select(authorizations).where(authorizations.c.agent_id == agent_id)).mappings().all()
        return [Authorization(**{**r, "created_at": _aware(r["created_at"]), "expires_at": _aware(r["expires_at"])})
                for r in rows]

    # ------------------------------------------------------------ runs

    def create_run(self, *, run_id: str, agent_id: str, suite_id: str, suite_version: str, requested_by: str,
                   idempotency_key: str | None, baseline_run_id: str | None) -> bool:
        """Insert a run; returns False if the idempotency key already exists."""
        ts = now()
        try:
            with self.engine.begin() as c:
                c.execute(insert(workflow_runs).values(
                    run_id=run_id, project_type="agent-eval-redteam", status="pending", current_step=None,
                    agent_id=agent_id, suite_id=suite_id, suite_version=suite_version,
                    baseline_run_id=baseline_run_id, idempotency_key=idempotency_key,
                    requested_by=requested_by, created_at=ts, updated_at=ts))
        except IntegrityError:
            return False
        return True

    def run_by_idempotency_key(self, key: str) -> dict[str, Any] | None:
        with self.engine.connect() as c:
            row = c.execute(select(workflow_runs).where(workflow_runs.c.idempotency_key == key)).mappings().first()
        return dict(row) if row else None

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as c:
            row = c.execute(select(workflow_runs).where(workflow_runs.c.run_id == run_id)).mappings().first()
        return dict(row) if row else None

    def update_run(self, run_id: str, **values: Any) -> None:
        with self.engine.begin() as c:
            c.execute(update(workflow_runs).where(workflow_runs.c.run_id == run_id).values(**values,
                                                                                           updated_at=now()))

    def save_artifact(self, run_id: str, step: str, payload: dict[str, Any]) -> str:
        digest = canonical_hash(payload)
        with self.engine.begin() as c:
            exists = c.execute(select(run_artifacts.c.step).where(run_artifacts.c.run_id == run_id,
                                                                  run_artifacts.c.step == step)).first()
            if exists:
                c.execute(update(run_artifacts).where(run_artifacts.c.run_id == run_id, run_artifacts.c.step == step)
                          .values(payload=payload, content_hash=digest))
            else:
                c.execute(insert(run_artifacts).values(run_id=run_id, step=step, payload=payload,
                                                       content_hash=digest, created_at=now()))
        return digest

    def artifacts(self, run_id: str) -> dict[str, dict[str, Any]]:
        with self.engine.connect() as c:
            rows = c.execute(select(run_artifacts).where(run_artifacts.c.run_id == run_id)
                             .order_by(run_artifacts.c.created_at)).mappings().all()
        return {r["step"]: {"payload": r["payload"], "content_hash": r["content_hash"]} for r in rows}

    # ------------------------------------------------------------ traces and evidence

    def save_trace(self, trace: Trace) -> str:
        """Persist a trace and its evidence row; idempotent on trace_id. Returns the evidence id."""
        body = trace.model_dump(mode="json")
        digest = canonical_hash(body)
        evidence_id = stable_id("evidence", trace.trace_id)
        with self.engine.begin() as c:
            if c.execute(select(traces.c.trace_id).where(traces.c.trace_id == trace.trace_id)).first():
                return evidence_id
            c.execute(insert(traces).values(trace_id=trace.trace_id, run_id=trace.run_id, case_id=trace.case_id,
                                            phase=trace.phase, repeat=trace.repeat, content_hash=digest, body=body,
                                            created_at=now()))
            c.execute(insert(evidence).values(
                evidence_id=evidence_id, run_id=trace.run_id, source_uri=f"trace://{trace.trace_id}",
                source_type="agent_trace", as_of=now(), content_hash=digest,
                metadata={"case_id": trace.case_id, "phase": trace.phase, "repeat": trace.repeat}))
        return evidence_id

    def get_trace(self, trace_id: str) -> tuple[Trace, str] | None:
        with self.engine.connect() as c:
            row = c.execute(select(traces).where(traces.c.trace_id == trace_id)).mappings().first()
        return (Trace.model_validate(row["body"]), row["content_hash"]) if row else None

    def traces_for(self, run_id: str, phases: tuple[str, ...] = ("baseline", "injected")) -> list[Trace]:
        with self.engine.connect() as c:
            rows = c.execute(select(traces.c.body).where(traces.c.run_id == run_id, traces.c.phase.in_(phases))
                             .order_by(traces.c.case_id, traces.c.phase, traces.c.repeat)).all()
        return [Trace.model_validate(r[0]) for r in rows]

    def trace_exists(self, trace_id: str) -> bool:
        with self.engine.connect() as c:
            return c.execute(select(traces.c.trace_id).where(traces.c.trace_id == trace_id)).first() is not None

    def get_evidence(self, evidence_id: str) -> EvidenceRef | None:
        with self.engine.connect() as c:
            row = c.execute(select(evidence).where(evidence.c.evidence_id == evidence_id)).mappings().first()
        if not row:
            return None
        return EvidenceRef(evidence_id=row["evidence_id"], source_type=row["source_type"], uri=row["source_uri"],
                           content_hash=row["content_hash"], as_of=_aware(row["as_of"]))

    # ------------------------------------------------------------ findings

    def save_finding(self, run_id: str, f: Finding) -> None:
        with self.engine.begin() as c:
            if c.execute(select(findings.c.finding_id).where(findings.c.finding_id == f.finding_id)).first():
                return
            c.execute(insert(findings).values(
                finding_id=f.finding_id, run_id=run_id, finding_type=f.finding_type, severity=f.severity,
                case_id=f.case_id, title=f.title, statement=f.statement, confidence=f.confidence.value,
                assumptions=f.assumptions, metadata=f.metadata, created_at=now()))
            for ev in f.evidence:
                c.execute(insert(finding_evidence).values(finding_id=f.finding_id, evidence_id=ev.evidence_id,
                                                          relation="supports"))

    def findings_for(self, run_id: str) -> list[Finding]:
        with self.engine.connect() as c:
            rows = c.execute(select(findings).where(findings.c.run_id == run_id)
                             .order_by(findings.c.severity, findings.c.case_id, findings.c.finding_type)
                             ).mappings().all()
            links = c.execute(select(finding_evidence.c.finding_id, evidence)
                              .join(evidence, evidence.c.evidence_id == finding_evidence.c.evidence_id)
                              .where(evidence.c.run_id == run_id)).mappings().all()
        by_finding: dict[str, list[EvidenceRef]] = {}
        for link in links:
            by_finding.setdefault(link["finding_id"], []).append(EvidenceRef(
                evidence_id=link["evidence_id"], source_type=link["source_type"], uri=link["source_uri"],
                content_hash=link["content_hash"], as_of=_aware(link["as_of"])))
        return [Finding(finding_id=r["finding_id"], finding_type=r["finding_type"], title=r["title"],
                        statement=r["statement"], severity=r["severity"], confidence=Confidence(r["confidence"]),
                        case_id=r["case_id"], evidence=by_finding.get(r["finding_id"], []),
                        assumptions=r["assumptions"], metadata=r["metadata"]) for r in rows]

    # ------------------------------------------------------------ approvals, metrics, audit

    def insert_approval(self, *, run_id: str, gate: str, decision: str, approver: str, reason: str,
                        override: bool) -> bool:
        try:
            with self.engine.begin() as c:
                c.execute(insert(approvals).values(approval_id=str(uuid.uuid4()), run_id=run_id, gate=gate,
                                                   decision=decision, approver=approver, reason=reason,
                                                   override=override, created_at=now()))
        except IntegrityError:
            return False
        return True

    def get_approval(self, run_id: str, gate: str) -> dict[str, Any] | None:
        with self.engine.connect() as c:
            row = c.execute(select(approvals).where(approvals.c.run_id == run_id, approvals.c.gate == gate)
                            ).mappings().first()
        return dict(row) if row else None

    def save_run_metrics(self, *, run_id: str, agent_name: str, suite_id: str, suite_version: str,
                         scorecard: dict[str, Any], outcomes: dict[str, bool]) -> None:
        with self.engine.begin() as c:
            if c.execute(select(run_metrics.c.run_id).where(run_metrics.c.run_id == run_id)).first():
                c.execute(update(run_metrics).where(run_metrics.c.run_id == run_id).values(
                    pass_rate=scorecard["pass_rate"], scorecard=scorecard, case_outcomes=outcomes))
                return
            c.execute(insert(run_metrics).values(run_id=run_id, agent_name=agent_name, suite_id=suite_id,
                                                 suite_version=suite_version, pass_rate=scorecard["pass_rate"],
                                                 scorecard=scorecard, case_outcomes=outcomes, created_at=now()))

    def metrics_history(self, agent_name: str, suite_id: str, limit: int = 10) -> list[dict[str, Any]]:
        """Most recent scored runs for an agent name + suite, oldest first, excluding FAILED runs."""
        with self.engine.connect() as c:
            rows = c.execute(
                select(run_metrics, workflow_runs.c.status, workflow_runs.c.agent_id)
                .join(workflow_runs, workflow_runs.c.run_id == run_metrics.c.run_id)
                .where(run_metrics.c.agent_name == agent_name, run_metrics.c.suite_id == suite_id,
                       workflow_runs.c.status != "failed")
                .order_by(run_metrics.c.created_at.desc()).limit(limit)).mappings().all()
        return [dict(r) for r in reversed(rows)]

    def get_run_metrics(self, run_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as c:
            row = c.execute(select(run_metrics).where(run_metrics.c.run_id == run_id)).mappings().first()
        return dict(row) if row else None

    def audit(self, event: AuditEvent) -> None:
        with self.engine.begin() as c:
            c.execute(insert(audit_events).values(**event.model_dump(mode="python")))

    def audit_trail(self, run_id: str) -> list[dict[str, Any]]:
        with self.engine.connect() as c:
            rows = c.execute(select(audit_events).where(audit_events.c.run_id == run_id)
                             .order_by(audit_events.c.event_id)).mappings().all()
        return [dict(r) for r in rows]
