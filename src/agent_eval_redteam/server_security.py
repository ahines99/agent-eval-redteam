"""Explicit HTTP principals and database-per-tenant isolation; stdio stays locally trusted.

Credentials are high-entropy bearer tokens stored only as SHA-256 digests in an operator-owned JSON
file. Terminate TLS at the deployment proxy. The file is re-read for each request to allow revocation.
This deliberately small service-token option does not pretend to implement OIDC or user login.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from .domain.policies import PolicyViolation, normalize_actor

SCOPES = frozenset({"read", "run", "register", "authorize", "approve"})


class Credential(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    actor: str
    tenant: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    scopes: set[str]


class AccessConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenants: dict[str, str]
    principals: list[Credential]

    @model_validator(mode="after")
    def consistent(self) -> AccessConfig:
        locations = []
        for url in self.tenants.values():
            try:
                parsed = make_url(url)
            except ArgumentError as exc:
                raise ValueError("invalid tenant database URL") from exc
            if parsed.get_backend_name() == "sqlite":
                if (not parsed.database or parsed.database == ":memory:" or parsed.query
                        or parsed.database.startswith("file:")):
                    raise ValueError("HTTP SQLite tenants require persistent filenames without query overrides")
                locations.append(str(Path(parsed.database).resolve()).casefold())
            elif parsed.get_backend_name() == "postgresql":
                if not parsed.host or not parsed.database or parsed.query:
                    raise ValueError("PostgreSQL tenants need explicit host/database without query overrides")
                host = parsed.host.lower().rstrip(".")
                if host in {"localhost", "127.0.0.1", "::1"}:
                    host = "loopback"
                locations.append(f"postgresql://{host}:{parsed.port or 5432}/{parsed.database}")
            else:
                raise ValueError("only SQLite and PostgreSQL tenant databases are supported")
        if len(set(locations)) != len(locations):
            raise ValueError("each tenant requires a distinct database URL")
        # In-memory databases cannot persist a shared tenant's state across workers/restarts.
        if any(url in {"sqlite://", "sqlite:///:memory:"} for url in self.tenants.values()):
            raise ValueError("HTTP tenants require persistent databases")
        digests: set[str] = set()
        for principal in self.principals:
            principal.actor = normalize_actor(principal.actor)
            if principal.tenant not in self.tenants or not principal.scopes <= SCOPES:
                raise ValueError("unknown tenant or scope")
            if principal.token_sha256 in digests:
                raise ValueError("a token may identify only one principal")
            digests.add(principal.token_sha256)
        return self


@dataclass(frozen=True)
class Principal:
    actor: str
    tenant: str
    scopes: frozenset[str]
    database_url: str


current_principal: ContextVar[Principal | None] = ContextVar("eval_principal", default=None)


def require_scope(scope: str) -> None:
    principal = current_principal.get()
    if principal is not None and scope not in principal.scopes:
        raise PolicyViolation(f"authenticated principal lacks {scope!r} scope")


def actor_identity(claimed: str) -> str:
    principal = current_principal.get()
    return principal.actor if principal is not None else claimed


class AuthenticatedHTTP:
    """ASGI boundary: every HTTP request has a verified principal before MCP sees it."""

    def __init__(self, app: Any) -> None:
        self.app = app
        self.active_requests = 0

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        if self.active_requests >= 16:
            await self.reject(send, 429, "server request limit reached; retry later")
            return
        path = os.environ.get("AGENT_EVAL_AUTH_FILE")
        try:
            if not path:
                raise ValueError("missing auth configuration")
            config = AccessConfig.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))
        except (OSError, ValueError, PolicyViolation):
            await self.reject(send, 503, "HTTP access is not configured")
            return
        headers = dict(scope.get("headers", []))
        authorization = headers.get(b"authorization", b"").decode("latin-1")
        if not authorization.startswith("Bearer ") or len(authorization) > 4096:
            await self.reject(send, 401, "bearer token required")
            return
        token = authorization[7:]
        if len(token) < 32:
            await self.reject(send, 401, "invalid bearer token")
            return
        digest = hashlib.sha256(token.encode()).hexdigest()
        match = next((p for p in config.principals if hmac.compare_digest(p.token_sha256, digest)), None)
        if match is None:
            await self.reject(send, 401, "invalid bearer token")
            return
        principal = Principal(match.actor, match.tenant, frozenset(match.scopes), config.tenants[match.tenant])
        reset = current_principal.set(principal)
        self.active_requests += 1
        try:
            await self.app(scope, receive, send)
        finally:
            self.active_requests -= 1
            current_principal.reset(reset)

    @staticmethod
    async def reject(send: Any, status: int, message: str) -> None:
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"application/json"),
                                (b"www-authenticate", b"Bearer")]})
        await send({"type": "http.response.body", "body": json.dumps({"error": message}).encode()})
