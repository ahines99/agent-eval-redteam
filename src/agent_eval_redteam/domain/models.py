"""Cross-cutting contracts: evidence, findings, audit events."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

# Bumped whenever the persisted shape of traces, artifacts or findings changes.
SCHEMA_VERSION = "1.1"


def canonical_hash(obj: Any) -> str:
    """sha256 over JSON with sorted keys and compact separators."""
    blob = json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode()
    return "sha256:" + hashlib.sha256(blob).hexdigest()


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
