"""Verify a private Docker backend through loopback Caddy HTTPS with an explicitly trusted local CA.

Build the application image first: docker build -t agent-eval-portfolio .
Run: python scripts/verify_tls_proxy.py [--wsl-distribution Ubuntu-22.04]
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import platform
import secrets
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

ROOT = Path(__file__).resolve().parents[1]
CADDY_TAG = "caddy:2.11.4-alpine"
CADDY_DIGEST = "sha256:6aeddd44c3078b0f9a35206472a11420648a79c184603ef95957d0a20044cb2b"
CADDY_IMAGE = "caddy@" + CADDY_DIGEST
CADDYFILE = """{
    admin off
    auto_https disable_redirects
    skip_install_trust
}
https://localhost:443 {
    tls internal
    reverse_proxy backend:8000
}
"""


def command(arguments: list[str], timeout: int = 30) -> str:
    result = subprocess.run(arguments, capture_output=True, text=True, timeout=timeout,
                            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
    if result.returncode:
        raise RuntimeError(f"local deployment command failed ({result.returncode}): {result.stderr.strip()}")
    return result.stdout.strip()


@asynccontextmanager
async def client(url: str, token: str, context: ssl.SSLContext) -> AsyncIterator[Any]:
    @asynccontextmanager
    async def transport():
        async with (
            httpx2.AsyncClient(headers={"Authorization": "Bearer " + token}, verify=context, trust_env=False) as http,
            streamable_http_client(url, http_client=http) as streams,
        ):
            yield streams

    async with Client(transport()) as connected:
        yield connected


async def verify_mcp(url: str, alpha: str, beta: str, context: ssl.SSLContext) -> dict[str, Any]:
    async with httpx2.AsyncClient(verify=context, trust_env=False) as http:
        # A valid Caddy certificate proves proxy readiness, not that Uvicorn has finished importing.
        # Poll without credentials; only the application's explicit auth refusal establishes readiness.
        started = time.monotonic()
        observed: dict[str, int] = {}
        while time.monotonic() - started < 30:
            try:
                response = await http.get(url, timeout=2)
            except httpx2.TransportError as exc:
                key = type(exc).__name__  # Never include request headers or raw exception text.
                observed[key] = observed.get(key, 0) + 1
            else:
                key = str(response.status_code)
                observed[key] = observed.get(key, 0) + 1
                if response.status_code == 401:
                    break
                if response.status_code not in {502, 503, 504}:
                    raise AssertionError(f"unexpected upstream readiness response: HTTP {response.status_code}")
            await asyncio.sleep(0.1)
        else:
            raise TimeoutError(f"backend auth boundary not ready after 30s; statuses/error classes: {observed}")
        readiness = {"required_status": 401, "observed": observed,
                     "elapsed_ms": round((time.monotonic() - started) * 1000, 3), "timeout_seconds": 30}
        # These remain independent, strict checks after the startup-only readiness gate.
        missing = (await http.get(url)).status_code
        invalid_headers = {"Authorization": "Bearer " + "invalid-synthetic-token-" * 3}
        invalid = (await http.get(url, headers=invalid_headers)).status_code
    assert missing == invalid == 401, f"auth boundary returned missing={missing}, invalid={invalid}; expected both 401"
    async with client(url, alpha, context) as connected:
        health = await connected.call_tool("healthcheck", {})
        assert not health.is_error and health.structured_content["status"] == "ok"
        registered = await connected.call_tool("register_agent", {
            "name": "tls-alpha-only", "version": "1", "adapter": "scripted", "owner": "spoofed-owner"})
        assert not registered.is_error
        assert registered.structured_content["owner"] == "tls-alpha"
        listed = await connected.call_tool("list_agents", {})
        assert "tls-alpha-only@1" in {agent["agent_id"] for agent in listed.structured_content["agents"]}
    async with client(url, beta, context) as connected:
        listed = await connected.call_tool("list_agents", {})
        assert not listed.is_error
        assert "tls-alpha-only@1" not in {agent["agent_id"] for agent in listed.structured_content["agents"]}
        denied = await connected.call_tool("register_agent", {
            "name": "denied", "version": "1", "adapter": "scripted", "owner": "tls-alpha"})
        assert denied.is_error
    return {"readiness": readiness, "missing_token_status": missing, "invalid_token_status": invalid,
            "authenticated_health": "ok",
            "actor_spoof_overridden": True, "cross_tenant_agent_hidden": True, "read_scope_mutation_refused": True}


def handshake(port: int, context: ssl.SSLContext, hostname: str = "localhost") -> dict[str, Any]:
    with (socket.create_connection(("127.0.0.1", port), timeout=5) as connection,
          context.wrap_socket(connection, server_hostname=hostname) as secured):
        cert = secured.getpeercert()
        der = secured.getpeercert(binary_form=True)
        cipher = secured.cipher()
        assert cert is not None and der is not None and cipher is not None
        return {"version": secured.version(), "cipher": cipher[0],
                "leaf_sha256": hashlib.sha256(der).hexdigest(),
                "subject_alt_names": cert.get("subjectAltName", []),
                "issuer": cert.get("issuer", [])}


def verify(args: argparse.Namespace, working: Path) -> dict[str, Any]:
    docker = (["wsl.exe", "-d", args.wsl_distribution, "--", "docker"] if args.wsl_distribution else ["docker"])

    def mapped(path: Path) -> str:
        if args.wsl_distribution:
            return command(["wsl.exe", "-d", args.wsl_distribution, "--", "wslpath", "-a", str(path)])
        return str(path)

    suffix = uuid.uuid4().hex[:10]
    prefix = "agent-eval-tls-verification-" + suffix
    network = prefix + "-network"
    frontend_network = prefix + "-frontend"
    backend, proxy = prefix + "-backend", prefix + "-proxy"
    created_containers: list[str] = []
    created_volumes: list[str] = []
    created_networks: list[str] = []
    alpha, beta = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    auth_path = working / "auth.json"
    auth_path.write_text(json.dumps({
        "tenants": {"alpha": "sqlite:////app/data/alpha.db", "beta": "sqlite:////app/data/beta.db"},
        "principals": [
            {"token_sha256": hashlib.sha256(alpha.encode()).hexdigest(), "actor": "tls-alpha",
             "tenant": "alpha", "scopes": ["read", "register"]},
            {"token_sha256": hashlib.sha256(beta.encode()).hexdigest(), "actor": "tls-beta",
             "tenant": "beta", "scopes": ["read"]},
        ],
    }), encoding="utf-8")
    # Auth configuration contains only digests; readable by the image's non-root application user.
    auth_path.chmod(0o644)
    config_path = working / "Caddyfile"
    config_path.write_text(CADDYFILE, encoding="utf-8")
    config_path.chmod(0o644)
    root_path = working / "root.crt"
    try:
        command([*docker, "pull", CADDY_IMAGE], timeout=180)
        app_image = json.loads(command([*docker, "image", "inspect", args.application_image]))[0]
        command([*docker, "network", "create", "--internal", network])
        created_networks.append(network)
        command([*docker, "network", "create", frontend_network])
        created_networks.append(frontend_network)
        for tag in ("application-data", "caddy-data", "caddy-config"):
            volume = prefix + "-" + tag
            command([*docker, "volume", "create", volume])
            created_volumes.append(volume)
        command([*docker, "create", "--name", backend, "--network", network, "--network-alias", "backend",
                 "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--tmpfs", "/tmp",
                 "--mount", f"type=volume,source={created_volumes[0]},target=/app/data",
                 "--mount", f"type=bind,source={mapped(auth_path)},target=/run/auth.json,readonly",
                 "--env", "AGENT_EVAL_AUTH_FILE=/run/auth.json", "--env", "OTEL_SDK_DISABLED=true",
                 "--entrypoint", "python", args.application_image, "-m", "uvicorn",
                 "agent_eval_redteam.mcp_server:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"])
        created_containers.append(backend)
        command([*docker, "start", backend])
        command([*docker, "create", "--name", proxy, "--network", frontend_network, "--read-only", "--cap-drop", "ALL",
                 "--cap-add", "NET_BIND_SERVICE",
                 "--security-opt", "no-new-privileges", "-p", "127.0.0.1::443",
                 "--mount", f"type=volume,source={created_volumes[1]},target=/data",
                 "--mount", f"type=volume,source={created_volumes[2]},target=/config",
                 "--mount", f"type=bind,source={mapped(config_path)},target=/etc/caddy/Caddyfile,readonly",
                 CADDY_IMAGE])
        created_containers.append(proxy)
        command([*docker, "network", "connect", network, proxy])
        command([*docker, "start", proxy])
        proxy_info = json.loads(command([*docker, "inspect", proxy]))[0]
        if not proxy_info["State"]["Running"]:
            # Startup logs contain no request data: no client or bearer token has been sent yet.
            failed = subprocess.run([*docker, "logs", proxy], capture_output=True, text=True, timeout=10)
            raise RuntimeError("Caddy startup failed: " + failed.stderr)
        backend_info = json.loads(command([*docker, "inspect", backend]))[0]
        network_info = json.loads(command([*docker, "network", "inspect", network]))[0]
        assert network_info["Internal"] is True
        assert not backend_info["HostConfig"]["PortBindings"]
        assert set(backend_info["NetworkSettings"]["Networks"]) == {network}
        assert backend_info["Config"]["User"] not in {"", "root", "0"}
        assert any(mount["Destination"] == "/run/auth.json" and not mount["RW"] for mount in backend_info["Mounts"])
        binding = proxy_info["NetworkSettings"]["Ports"]["443/tcp"][0]
        assert binding["HostIp"] == "127.0.0.1"
        port = int(binding["HostPort"])
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                command([*docker, "cp", proxy + ":/data/caddy/pki/authorities/local/root.crt", mapped(root_path)])
                context = ssl.create_default_context(cafile=str(root_path))
                tls = handshake(port, context)
                break
            except (RuntimeError, OSError):
                time.sleep(0.2)
        else:
            raise TimeoutError("local HTTPS proxy failed to provision its certificate or listen")
        assert context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
        for untrusted_context, hostname, expected_error in (
            (ssl.create_default_context(), "localhost", ssl.SSLCertVerificationError),
            (context, "wrong.invalid", ssl.SSLError),
        ):
            try:
                handshake(port, untrusted_context, hostname)
            except expected_error:
                pass
            else:
                raise AssertionError("TLS verification accepted an untrusted root or incorrect hostname")
        checks = asyncio.run(verify_mcp(f"https://localhost:{port}/mcp", alpha, beta, context))
        return {
            "schema_version": 1, "verified_at": datetime.now(UTC).isoformat(), "synthetic_only": True,
            "python": platform.python_version(), "client_platform": platform.platform(),
            "docker_context": "WSL " + args.wsl_distribution if args.wsl_distribution else "native Docker",
            "caddy_release": CADDY_TAG, "caddy_image_digest": CADDY_DIGEST, "caddy_image_id": proxy_info["Image"],
            "application_image": args.application_image, "application_image_id": app_image["Id"],
            "caddy_configuration": CADDYFILE,
            "tls": {**tls, "explicit_local_ca_trust": True, "certificate_verification_required": True,
                    "untrusted_ca_refused": True, "wrong_hostname_refused": True,
                    "root_certificate_sha256": hashlib.sha256(root_path.read_bytes()).hexdigest()},
            "network": {"proxy_host_binding": "127.0.0.1", "private_internal_network": True,
                        "backend_host_ports": [], "backend_non_root": True, "auth_mount_readonly": True},
            "mcp": checks, "raw_tokens_or_private_keys_saved": False,
            "limitations": ["Private loopback deployment only; no public hostname or remote service claimed",
                            "Ephemeral local CA explicitly trusted by the test client, not installed system-wide",
                            "Single backend process and local synthetic tenant databases; no HA or scale claim"],
            "sources": ["https://github.com/caddyserver/caddy/releases/tag/v2.11.4",
                        "https://hub.docker.com/_/caddy", "https://caddyserver.com/docs/automatic-https",
                        "https://caddyserver.com/docs/caddyfile/directives/reverse_proxy"],
        }
    finally:
        for container in reversed(created_containers):
            command([*docker, "rm", "--force", container])
        for volume in reversed(created_volumes):
            command([*docker, "volume", "rm", volume])
        for created_network in reversed(created_networks):
            command([*docker, "network", "rm", created_network])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wsl-distribution")
    parser.add_argument("--image", "--application-image", dest="application_image", default="agent-eval-portfolio")
    parser.add_argument("--output", type=Path, default=Path("docs/evidence/tls-proxy.json"))
    args = parser.parse_args()
    temporary_root = (ROOT / "data" / "verification").resolve()
    assert temporary_root.is_relative_to(ROOT)
    temporary_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="tls-proxy-", dir=temporary_root) as working:
        evidence = verify(args, Path(working))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(f"Verified trusted local TLS proxy, private backend and authenticated MCP: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
