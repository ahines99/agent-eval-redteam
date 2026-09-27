"""Verify local HTTP credential rotation, admission bounds, tenant isolation and SQLite restoration.

Run with the project's dependencies installed: python scripts/verify_operations.py
Only temporary synthetic databases and a localhost subprocess server are used.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import platform
import secrets
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

ROOT = Path(__file__).resolve().parents[1]


def write_auth(path: Path, databases: dict[str, Path], alpha: str, beta: str) -> None:
    configuration = {
        "tenants": {tenant: "sqlite:///" + str(database) for tenant, database in databases.items()},
        "principals": [
            {"token_sha256": hashlib.sha256(alpha.encode()).hexdigest(), "actor": "alpha-operator",
             "tenant": "alpha", "scopes": ["read", "register", "run", "authorize"]},
            {"token_sha256": hashlib.sha256(beta.encode()).hexdigest(), "actor": "beta-reader",
             "tenant": "beta", "scopes": ["read"]},
        ],
    }
    temporary = path.with_suffix(".new")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        json.dump(configuration, output)
    temporary.replace(path)


def status(url: str, token: str | None = None) -> int:
    headers = {"Authorization": "Bearer " + token} if token else {}
    request = urllib.request.Request(url, headers=headers)
    # Avoid environment proxy configuration: all requests here are strictly local.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=5) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        exc.close()
        return exc.code


@contextmanager
def server(working: Path, config: Path) -> Iterator[tuple[str, subprocess.Popen[str]]]:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    environment = {key: value for key, value in os.environ.items() if not key.startswith("OTEL_")}
    environment.update({"PYTHONPATH": str(ROOT / "src"), "AGENT_EVAL_AUTH_FILE": str(config),
                        "DATABASE_URL": "sqlite:///" + str(working / "unused-default.db"),
                        "OTEL_SDK_DISABLED": "true"})
    with (working / "server.log").open("w", encoding="utf-8") as output:
        process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "agent_eval_redteam.mcp_server:app", "--host", "127.0.0.1",
             "--port", str(port), "--no-access-log", "--timeout-graceful-shutdown", "5"],
            env=environment, cwd=working, stdout=output, stderr=output, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        url = f"http://127.0.0.1:{port}/mcp"
        try:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError("local HTTP server exited before becoming ready")
                try:
                    if status(url) == 401:
                        break
                except (urllib.error.URLError, TimeoutError):
                    pass
                time.sleep(0.05)
            else:
                raise TimeoutError("local HTTP server did not become ready")
            yield url, process
        finally:
            if sys.platform == "win32" and process.poll() is None:
                # A venv interpreter may be a launcher with a child interpreter. Terminating
                # only that launcher leaves the HTTP server holding SQLite files on Windows.
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                               capture_output=True, check=True)
            elif process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


@asynccontextmanager
async def client(url: str, token: str) -> AsyncIterator[Any]:
    @asynccontextmanager
    async def transport():
        async with (
            httpx2.AsyncClient(headers={"Authorization": "Bearer " + token}, trust_env=False,
                               timeout=httpx2.Timeout(60, connect=10)) as http,
            streamable_http_client(url, http_client=http) as streams,
        ):
            yield streams

    async with Client(transport()) as connected:
        yield connected


async def tool(connected: Any, name: str, arguments: dict[str, Any]) -> Any:
    result = await connected.call_tool(name, arguments)
    if result.is_error:
        raise AssertionError(f"synthetic operation {name} failed")
    return result.structured_content


async def prepare_and_check(url: str, alpha: str, beta: str) -> dict[str, Any]:
    async with client(url, alpha) as connected:
        registered = await tool(connected, "register_agent", {
            "name": "alpha-only", "version": "1", "adapter": "scripted", "owner": "spoofed-owner"})
        assert registered["owner"] == "alpha-operator"
        await tool(connected, "authorize_security_testing", {
            "agent_id": "support-bot@1.0.0", "approved_by": "spoofed-security",
            "categories": ["prompt_injection", "pii"], "reason": "Synthetic operations verification"})
        run = await tool(connected, "run_eval_suite", {
            "agent_id": "support-bot@1.0.0", "suite_id": "support-core", "version": "1.0.0",
            "requested_by": "spoofed-requester", "idempotency_key": "operations-backup-control"})
        assert run["requested_by"] == "alpha-operator" and run["release_decision"] == "eligible"
        resource = await connected.read_resource(f"runs://{run['run_id']}/report")
        report = "".join(part.text for part in resource.contents if hasattr(part, "text"))
        assert run["run_id"] in report
    async with client(url, beta) as connected:
        listed = await tool(connected, "list_agents", {})
        assert "alpha-only@1" not in {agent["agent_id"] for agent in listed["agents"]}
        denied = await connected.call_tool("register_agent", {
            "name": "denied", "version": "1", "adapter": "scripted", "owner": "beta-reader"})
        assert denied.is_error
        missing = await connected.call_tool("get_run", {"run_id": run["run_id"]})
        assert missing.is_error
    return {"run_id": run["run_id"], "report": report, "release_decision": run["release_decision"]}


async def healthy(url: str, token: str) -> None:
    async with client(url, token) as connected:
        assert (await tool(connected, "healthcheck", {}))["status"] == "ok"


def check_admission(url: str, token: str) -> dict[str, Any]:
    """Hold exactly sixteen admitted requests at body-read using HTTP 100 Continue handshakes."""
    port = int(url.split(":")[2].split("/")[0])
    pending: list[socket.socket] = []
    body = b'{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"healthcheck","arguments":{}}}'
    try:
        for _ in range(16):
            connection = socket.create_connection(("127.0.0.1", port), timeout=5)
            pending.append(connection)
            headers = (f"POST /mcp HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nAuthorization: Bearer {token}\r\n"
                       "Content-Type: application/json\r\nAccept: application/json, text/event-stream\r\n"
                       f"Content-Length: {len(body)}\r\nExpect: 100-continue\r\nConnection: close\r\n\r\n")
            connection.sendall(headers.encode("ascii"))
            response = b""
            while b"\r\n\r\n" not in response and len(response) < 8192:
                received = connection.recv(8192)
                if not received:
                    break
                response += received
            assert response.startswith(b"HTTP/1.1 100 Continue"), "request was not admitted to body-read"
        started = time.perf_counter()
        overflow = status(url, token)
        elapsed = (time.perf_counter() - started) * 1000
        assert overflow == 429
    finally:
        for connection in pending:
            # Complete the held request so the server exits its normal request path cleanly.
            try:
                connection.sendall(body)
                while connection.recv(65536):
                    pass
            finally:
                connection.close()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if status(url) == 401:
            break
        time.sleep(0.05)
    else:
        raise AssertionError("request slots were not released")
    return {"admitted_concurrent_requests": 16, "overflow_status": overflow,
            "overflow_response_ms": round(elapsed, 3), "slots_released": True,
            "scope": "one local process; bounded slow-body admission check, not throughput benchmark"}


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_verification(working: Path) -> dict[str, Any]:
    alpha, replacement, beta = (secrets.token_urlsafe(32) for _ in range(3))
    databases = {tenant: working / f"{tenant}.db" for tenant in ("alpha", "beta")}
    config = working / "auth.json"
    write_auth(config, databases, alpha, beta)
    with server(working, config) as (url, process):
        original_pid = process.pid
        initial = asyncio.run(prepare_and_check(url, alpha, beta))
        write_auth(config, databases, replacement, beta)
        assert status(url, alpha) == 401
        asyncio.run(healthy(url, replacement))
        asyncio.run(healthy(url, beta))
        assert process.pid == original_pid and process.poll() is None
        admission = check_admission(url, replacement)
        asyncio.run(healthy(url, replacement))
    assert process.poll() is not None

    # This is a stopped-service snapshot. SQLite backup consolidates any remaining WAL content.
    backup = working / "alpha-backup.db"
    restored = working / "alpha-restored.db"
    with closing(sqlite3.connect(databases["alpha"])) as source, closing(sqlite3.connect(backup)) as destination:
        source.backup(destination)
        assert destination.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    shutil.copy2(backup, restored)
    backup_hash = file_hash(backup)
    assert file_hash(restored) == backup_hash
    restored_databases = {**databases, "alpha": restored}
    write_auth(config, restored_databases, replacement, beta)
    with server(working, config) as (url, restored_process):
        async def read_restored() -> str:
            async with client(url, replacement) as connected:
                summary = await tool(connected, "get_run", {"run_id": initial["run_id"]})
                assert summary["release_decision"] == initial["release_decision"]
                resource = await connected.read_resource(f"runs://{initial['run_id']}/report")
                return "".join(part.text for part in resource.contents if hasattr(part, "text"))

        restored_report = asyncio.run(read_restored())
        assert restored_report == initial["report"]
    assert restored_process.poll() is not None
    return {
        "schema_version": 1, "verified_at": datetime.now(UTC).isoformat(),
        "python": platform.python_version(), "platform": platform.platform(), "synthetic_only": True,
        "credential_rotation": {"atomic_file_replacement": True, "old_token_status": 401,
                                "new_token_health": "ok", "other_tenant_health": "ok",
                                "same_process": True, "raw_tokens_saved": False},
        "tenant_isolation": {"separate_sqlite_files": True, "cross_tenant_registry_hidden": True,
                             "cross_tenant_run_refused": True, "scope_escalation_refused": True,
                             "claimed_actor_overridden": True},
        "admission": admission,
        "backup_restore": {"service_stopped_before_snapshot": True, "method": "sqlite3.Connection.backup",
                           "integrity_check": "ok", "backup_sha256": backup_hash,
                           "restored_copy_hash_matched": True, "restored_http_report_matches": True,
                           "run_id": initial["run_id"], "release_decision": initial["release_decision"],
                           "report_sha256": hashlib.sha256(restored_report.encode()).hexdigest()},
        "limitations": ["Loopback HTTP only; TLS/proxy/public hosting not exercised",
                        "One server process at a time; no distributed admission/load claim",
                        "Process termination waited before backup; graceful signal handling not asserted on Windows",
                        "Stopped-service SQLite restoration only; no PostgreSQL backup validation"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("docs/evidence/operations.json"))
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="agent-eval-operations-") as working:
        evidence = run_verification(Path(working))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(f"Verified local rotation, tenant isolation, bounded admission and restored report: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
