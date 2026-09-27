"""Every MCP tool, resource and prompt exercised through the in-process client, plus the CLI."""

from __future__ import annotations

import json

import pytest
from mcp import Client

from agent_eval_redteam import cli
from agent_eval_redteam.mcp_server import mcp

from .conftest import CANDIDATE, HARDENED

pytestmark = pytest.mark.anyio


async def _call(client: Client, tool: str, **args):
    result = await client.call_tool(tool, args)
    assert result.is_error is False, (tool, result.content)
    return result.structured_content


async def test_registry_tools(served):
    async with Client(mcp) as client:
        agent = await _call(client, "register_agent", name="support-claude", version="2026-09-23", adapter="claude",
                            owner="Alice", config={"model": "claude-opus-5", "effort": "high"})
        assert agent["agent_id"] == "support-claude@2026-09-23" and agent["owner"] == "alice"
        bad = await client.call_tool("register_agent", {"name": "x", "version": "1", "adapter": "claude",
                                                        "owner": "alice", "config": {"model": "gpt-5"}})
        assert bad.is_error and "model must be one of" in bad.content[0].text
        agents = await _call(client, "list_agents")
        assert {a["agent_id"] for a in agents["agents"]} >= {HARDENED, CANDIDATE, "support-claude@2026-09-23"}
        suites = await _call(client, "list_eval_suites")
        assert {(s["suite_id"], s["version"]) for s in suites["suites"]} >= {("support-core", "1.0.0")}


async def test_register_suite_and_read_it_back(served):
    suite = {"suite_id": "mini", "version": "0.1.0", "description": "one case",
             "cases": [{"case_id": "c1", "category": "factuality", "prompt": "Is standard shipping free?",
                        "expected_policy": "Free over $75", "expect": {"must_include": ["$75"]}}]}
    async with Client(mcp) as client:
        first = await _call(client, "register_eval_suite", suite=suite, registered_by="alice")
        again = await _call(client, "register_eval_suite", suite=suite, registered_by="alice")
        assert first["created"] is True and again["created"] is False
        assert first["content_hash"] == again["content_hash"]
        body = (await client.read_resource("suites://mini/0.1.0")).contents[0].text
        assert json.loads(body)["cases"][0]["case_id"] == "c1"


async def test_authorization_run_lifecycle_and_regression_report(served):
    async with Client(mcp) as client:
        auth = await _call(client, "authorize_security_testing", agent_id=HARDENED, approved_by="sec-lead",
                           categories=["prompt_injection", "pii"], reason="MCP lifecycle test window",
                           expires_in_hours=2)
        assert auth["approved_by"] == "sec-lead"
        too_long = await client.call_tool("authorize_security_testing", {
            "agent_id": HARDENED, "approved_by": "sec", "categories": ["pii"], "reason": "too long a window",
            "expires_in_hours": 100})
        assert too_long.is_error

        good = await _call(client, "run_eval_suite", agent_id=HARDENED, suite_id="support-core", version="1.0.0",
                           requested_by="alice", idempotency_key="mcp-1")
        rc = await _call(client, "run_eval_suite", agent_id=CANDIDATE, suite_id="support-core", version="1.0.0",
                         requested_by="alice")
        fetched = await _call(client, "get_run", run_id=rc["run_id"])
        assert fetched["status"] == "needs_review" and fetched["comparison"]["baseline_run_id"] == good["run_id"]

        blocked = await client.call_tool("resume_run", {"run_id": rc["run_id"], "actor": "alice"})
        assert blocked.is_error and "decide_release_gate" in blocked.content[0].text
        await _call(client, "decide_release_gate", run_id=rc["run_id"], approver="bob", decision="reject",
                    reason="citation regressions on ten cases")
        resumed = await _call(client, "resume_run", run_id=rc["run_id"], actor="alice")  # idempotent when done
        assert resumed["status"] == "complete"

        report = await _call(client, "get_regression_report", agent_name="support-bot", suite_id="support-core")
        assert [r["pass_rate"] for r in report["runs"]] == [1.0, 0.6774]
        assert report["alerts"] and report["alerts"][0].startswith("1.0.0:")

        missing = await client.call_tool("get_run", {"run_id": "nope"})
        assert missing.is_error and "not found" in missing.content[0].text


async def test_policy_resource_and_all_prompts(served):
    async with Client(mcp) as client:
        policies = (await client.read_resource("project://policies")).contents[0].text
        assert "gate-policy/1.2" in policies and "min_pass_rate: 0.9" in policies
        for name, arg in (("triage_failures", "run_id"), ("plan_redteam", "agent_id"), ("review_run", "run_id")):
            prompt = await client.get_prompt(name, {arg: "x-123"})
            assert "x-123" in prompt.messages[0].content.text


def test_cli_demo_and_report(capsys, tmp_path):
    db = f"sqlite:///{(tmp_path / 'demo.db').as_posix()}"
    assert cli.main(["demo", "--db", db]) == 0
    out = capsys.readouterr().out
    for expected in ("decision=eligible", "decision=awaiting_review", "separation of duties", "decision=rejected",
                     "decision=blocked", "cannot be overridden", "recovery: degraded gracefully", "alert:"):
        assert expected in out, expected
    run_id = next(line.split()[-1] for line in out.splitlines() if line.startswith("# Eval run"))
    assert cli.main(["report", run_id, "--db", db]) == 0
    assert "release decision: **rejected**" in capsys.readouterr().out
