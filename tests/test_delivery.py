"""Migration and installed-runtime integration checks.

PostgreSQL tests use a new, uniquely named schema and remove only that schema.
Set TEST_POSTGRES_URL to a disposable test database to opt in.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import socket
import subprocess
import sys
import urllib.error
import urllib.request
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import httpx2
import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from mcp import Client, StdioServerParameters
from mcp.client.streamable_http import streamable_http_client
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from agent_eval_redteam.adapters.repositories import Repository, metadata
from agent_eval_redteam.cli import SUITE, _demo, main
from agent_eval_redteam.domain.services import EvalPlatform

ROOT = Path(__file__).resolve().parents[1]


def migration_config(url: str) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


def assert_schema_matches(url: str) -> None:
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            assert compare_metadata(MigrationContext.configure(connection), metadata) == []
    finally:
        engine.dispose()


def assert_demo_contract(platform: EvalPlatform) -> None:
    """The same persisted demo assertions run on SQLite and PostgreSQL."""
    expected_runs = [("1.0.0", "support-bot", "eligible"),
                     ("1.1.0-rc1", "support-bot", "rejected"),
                     ("0.9.0", "support-bot-naive", "blocked")]
    for version, name, expected in expected_runs:
        key = f"demo-{SUITE[1]}-v{version}"
        stored = platform.repo.run_by_idempotency_key(key)
        assert stored is not None, f"demo did not persist its current suite-versioned key: {key}"
        result = platform.get_run(stored["run_id"])
        assert result.agent_id == f"{name}@{version}"
        assert result.suite == f"{SUITE[0]}@{SUITE[1]}"
        assert result.status == "complete"
        assert result.release_decision == expected
        assert result.scorecard is not None
        assert result.scorecard["n_cases"] == 35
        if expected == "eligible":
            assert result.scorecard["n_passed"] == 35
            assert result.scorecard["critical_failures"] == 0
            assert result.scorecard["recovery_rate"] == 1.0
        elif expected == "rejected":
            approval = platform.repo.get_approval(result.run_id, "Gate release")
            assert approval is not None and approval["decision"] == "reject"
            assert approval["approver"] != result.requested_by
        else:
            assert result.scorecard["critical_failures"] > 0
            assert result.gate is not None and not result.gate.overridable


def test_migrations_upgrade_legacy_data_and_match_models(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    url = "sqlite:///" + str(tmp_path / "nested" / "migration.db")
    config = migration_config(url)
    command.upgrade(config, "0001")
    engine = create_engine(url)
    try:
        with engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO audit_events (run_id, step, actor, event_type, payload, created_at) "
                "VALUES (NULL, 'legacy', 'test', 'retained', '{}', '2026-01-01 00:00:00')"
            ))
        command.upgrade(config, "head")
        command.upgrade(config, "head")
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT COUNT(*) FROM audit_events WHERE event_type='retained'")) == 1
            assert "execution_leases" in inspect(connection).get_table_names()
        assert_schema_matches(url)
        command.check(config)
        # Downgrade is exercised only against this disposable test database.
        command.downgrade(config, "base")
        assert set(inspect(engine).get_table_names()) == {"alembic_version"}
    finally:
        engine.dispose()


@pytest.fixture
def postgres_url(monkeypatch):
    url = os.environ.get("TEST_POSTGRES_URL")
    if not url:
        pytest.skip("TEST_POSTGRES_URL is not set; PostgreSQL runs in the CI service job")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    schema = "eval_test_" + uuid.uuid4().hex
    engine = create_engine(url)
    try:
        with engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        isolated = make_url(url).update_query_dict({"options": f"-csearch_path={schema}"})
        yield isolated.render_as_string(hide_password=False)
    finally:
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        engine.dispose()


@pytest.mark.postgres
@pytest.mark.anyio
async def test_postgres_migrations_and_full_demo(postgres_url):
    config = migration_config(postgres_url)
    command.upgrade(config, "head")
    assert_schema_matches(postgres_url)
    repo = Repository(postgres_url)
    try:
        platform = EvalPlatform(repo)
        assert await _demo(platform) == 0
        assert_demo_contract(platform)
    finally:
        repo.close()
    command.check(config)


def test_persistent_demo_can_be_run_twice(tmp_path, capsys):
    url = "sqlite:///" + str(tmp_path / "demo.db")
    assert main(["demo", "--db", url]) == 0
    assert main(["demo", "--db", url]) == 0
    assert "decision=eligible" in capsys.readouterr().out
    repo = Repository(url)
    try:
        assert_demo_contract(EvalPlatform(repo))
    finally:
        repo.close()


def process_environment(tmp_path) -> dict[str, str]:
    return {**os.environ, "PYTHONPATH": str(ROOT / "src"),
            "DATABASE_URL": "sqlite:///" + str(tmp_path / "process.db")}


@pytest.mark.anyio
async def test_stdio_subprocess_persists_registry_after_restart(tmp_path):
    server = StdioServerParameters(command=sys.executable, args=["-m", "agent_eval_redteam.cli", "serve"],
                                   env=process_environment(tmp_path), cwd=tmp_path)
    async with Client(server) as client:
        result = await client.call_tool("register_agent", {"name": "restart-control", "version": "1",
            "adapter": "scripted", "owner": "tester", "config": {"preset": "hardened"}})
        assert not result.is_error
    async with Client(server) as client:
        result = await client.call_tool("list_agents", {})
        assert not result.is_error
        assert "restart-control@1" in json.dumps(result.structured_content)


@pytest.mark.anyio
async def test_authenticated_http_over_real_socket(tmp_path):
    token = "delivery-test-token-" + uuid.uuid4().hex
    config = tmp_path / "auth.json"
    config.write_text(json.dumps({
        "tenants": {"test": "sqlite:///" + str(tmp_path / "tenant.db")},
        "principals": [{"token_sha256": hashlib.sha256(token.encode()).hexdigest(),
                        "actor": "tester", "tenant": "test", "scopes": ["read"]}],
    }), encoding="utf-8")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    url = f"http://127.0.0.1:{port}/mcp"
    environment = {**process_environment(tmp_path), "AGENT_EVAL_AUTH_FILE": str(config)}
    with (tmp_path / "server.log").open("w", encoding="utf-8") as output:
        process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "agent_eval_redteam.mcp_server:app", "--host", "127.0.0.1",
             "--port", str(port)], env=environment, cwd=tmp_path, stdout=output, stderr=output,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        try:
            for _ in range(150):
                if process.poll() is not None:
                    pytest.fail("HTTP server exited: " + (tmp_path / "server.log").read_text(encoding="utf-8"))
                try:
                    with urllib.request.urlopen(url, timeout=0.2):
                        pytest.fail("HTTP server accepted a request without authentication")
                except urllib.error.HTTPError as exc:
                    assert exc.code == 401
                    break
                except urllib.error.URLError:
                    await asyncio.sleep(0.05)
            else:
                pytest.fail("HTTP server did not become ready")

            @asynccontextmanager
            async def transport():
                async with (
                    httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"}) as http,
                    streamable_http_client(url, http_client=http) as (read, write),
                ):
                    yield read, write

            async with Client(transport()) as client:
                health = await client.call_tool("healthcheck", {})
                assert not health.is_error
                assert health.structured_content["status"] == "ok"
                denied = await client.call_tool("register_agent", {"name": "denied", "version": "1",
                    "adapter": "scripted", "owner": "spoofed", "config": {"preset": "hardened"}})
                assert denied.is_error
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
