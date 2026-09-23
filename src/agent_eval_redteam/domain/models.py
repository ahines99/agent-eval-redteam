"""Cross-cutting contracts: evidence, findings, audit events."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class Confidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class EvidenceRef(BaseModel):
    evidence_id: str
    source_type: str
    uri: str
    content_hash: str
    as_of: datetime | None = None


class Finding(BaseModel):
    finding_id: str
    finding_type: str
    title: str
    statement: str
    severity: str
    confidence: Confidence
    case_id: str | None = None
    evidence: list[EvidenceRef] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AuditEvent(BaseModel):
    run_id: str | None
    step: str
    event_type: str
    actor: str
    created_at: datetime
    payload: dict[str, Any] = Field(default_factory=dict)
