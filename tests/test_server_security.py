from __future__ import annotations

import hashlib
import json

import pytest
from mcp import Client

from agent_eval_redteam import mcp_server
from agent_eval_redteam.server_security import AccessConfig, AuthenticatedHTTP, Principal, current_principal


def config(tmp_path, scopes=("read", "register", "run")):
    token = "test-credential-" + "a" * 48
    path = tmp_path / "access.json"
    path.write_text(json.dumps({
        "tenants": {"alpha": f"sqlite:///{tmp_path / 'alpha.db'}"},
        "principals": [{"token_sha256": hashlib.sha256(token.encode()).hexdigest(), "actor": "alice",
                        "tenant": "alpha", "scopes": list(scopes)}],
    }))
    return path, token


@pytest.mark.parametrize("tenants", [
    {"a": "postgresql+psycopg://alice:one@localhost/test", "b": "postgresql://bob:two@127.0.0.1:5432/test"},
    {"a": "sqlite:///./duplicate.db", "b": "sqlite:///duplicate.db"},
    {"a": "sqlite:///file:shared"},
    {"a": "not a database URL"},
])
def test_database_aliases_and_invalid_locations_are_rejected(tenants):
    with pytest.raises(ValueError):
        AccessConfig.model_validate({"tenants": tenants, "principals": []})


@pytest.mark.anyio
async def test_authenticated_approver_cannot_impersonate_second_person(authorized):
    from .conftest import CANDIDATE, run

    result = await run(authorized, CANDIDATE)
    principal = Principal("alice", "gate-test", frozenset({"approve"}), "sqlite:///unused.db")
    mcp_server._tenant_platforms[(principal.tenant, principal.database_url)] = authorized
    reset = current_principal.set(principal)
    try:
        async with Client(mcp_server.mcp) as client:
            denied = await client.call_tool("decide_release_gate", {
                "run_id": result.run_id, "approver": "bob", "decision": "approve",
                "reason": "Claimed name must not override token identity"})
            assert denied.is_error and "separation of duties" in str(denied.content)
        assert authorized.repo.get_approval(result.run_id, "Gate release") is None
    finally:
        current_principal.reset(reset)
        mcp_server._tenant_platforms.pop((principal.tenant, principal.database_url))


@pytest.mark.anyio
async def test_http_requires_credentials_and_resets_context(tmp_path, monkeypatch):
    observed = []

    async def downstream(scope, receive, send):
        observed.append(current_principal.get())
        await send({"type": "http.response.start", "status": 200})

    app = AuthenticatedHTTP(downstream)

    async def request(token=""):
        responses = []

        async def send(message):
            responses.append(message)

        await app({"type": "http", "headers": [(b"authorization", token.encode())]}, None, send)
        assert current_principal.get() is None
        return responses[0]["status"]

    monkeypatch.delenv("AGENT_EVAL_AUTH_FILE", raising=False)
    assert await request() == 503
    path, token = config(tmp_path)
    monkeypatch.setenv("AGENT_EVAL_AUTH_FILE", str(path))
    assert await request() == 401
    assert await request("Bearer " + "wrong" * 10) == 401
    assert await request("Bearer " + token) == 200
    assert observed[0].actor == "alice"
    # Credentials can be revoked without retaining a session's earlier authorization.
    path.write_text('{"tenants": {}, "principals": []}')
    assert await request("Bearer " + token) == 401


@pytest.mark.anyio
async def test_mcp_uses_authenticated_actor_and_isolates_tenants(tmp_path):
    first = Principal("alice", "first", frozenset({"read", "register"}), f"sqlite:///{tmp_path / 'a.db'}")
    second = Principal("bob", "second", frozenset({"read"}), f"sqlite:///{tmp_path / 'b.db'}")
    try:
        reset = current_principal.set(first)
        try:
            async with Client(mcp_server.mcp) as client:
                response = await client.call_tool("register_agent", {
                    "name": "tenant-only", "version": "1", "adapter": "scripted", "owner": "impersonated"})
                assert not response.is_error, response.content
                assert response.structured_content["owner"] == "alice"
                refused = await client.call_tool("authorize_security_testing", {
                    "agent_id": "tenant-only@1", "approved_by": "admin", "categories": ["pii"],
                    "reason": "Unauthorized scope escalation"})
                assert refused.is_error and "scope" in str(refused.content)
        finally:
            current_principal.reset(reset)
        reset = current_principal.set(second)
        try:
            async with Client(mcp_server.mcp) as client:
                response = await client.call_tool("list_agents", {})
                assert all(a["name"] != "tenant-only" for a in response.structured_content["agents"])
                refused = await client.call_tool("register_agent", {
                    "name": "denied", "version": "1", "adapter": "scripted", "owner": "bob"})
                assert refused.is_error
        finally:
            current_principal.reset(reset)
    finally:
        for key in list(mcp_server._tenant_platforms):
            if key[0] in {"first", "second"}:
                mcp_server._tenant_platforms.pop(key).repo.close()
