"""Harness robustness and observability: error classification (C2), timeouts, schema/evidence audit trail."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import anthropic
import httpx2
import pytest

from agent_eval_redteam.adapters.agents import ScriptedAgent
from agent_eval_redteam.adapters.claude_agent import ClaudeAgent
from agent_eval_redteam.domain.models import SCHEMA_VERSION
from agent_eval_redteam.domain.project_models import AgentSpec
from agent_eval_redteam.domain.scoring import SCORING_VERSION
from agent_eval_redteam.domain.services import EvalPlatform
from agent_eval_redteam.workflows import primary

from .conftest import HARDENED, run

pytestmark = pytest.mark.anyio
_REQ = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


def _status(cls: type[anthropic.APIStatusError], code: int) -> anthropic.APIStatusError:
    return cls("boom", response=httpx2.Response(code, request=_REQ), body=None)


@pytest.mark.parametrize(("exc", "kind"), [
    (_status(anthropic.OverloadedError, 529), "transient"),
    (_status(anthropic.RateLimitError, 429), "transient"),
    (_status(anthropic.InternalServerError, 500), "transient"),
    (anthropic.APIConnectionError(request=_REQ), "transient"),
    (_status(anthropic.AuthenticationError, 401), "harness"),
    (_status(anthropic.BadRequestError, 400), "harness"),
    (_status(anthropic.NotFoundError, 404), "harness"),
    (ValueError("agent bug"), "agent"),
])
def test_claude_error_classification(exc, kind):
    assert ClaudeAgent({}).classify_error(exc) == kind


class _Scripted:
    """Fake Messages API: raise the queued exceptions first, then answer normally."""

    def __init__(self, *failures: BaseException) -> None:
        self.failures = list(failures)
        self.calls = 0

    async def create(self, **kwargs):
        self.calls += 1
        if self.failures:
            raise self.failures.pop(0)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text="NEEDS_EVIDENCE: no data.")],
                               stop_reason="end_turn", usage=SimpleNamespace(input_tokens=10, output_tokens=5))


def _claude(platform: EvalPlatform, messages: _Scripted) -> str:
    platform.register_agent(AgentSpec(name="claude-support", version="1", adapter="claude", owner="alice",
                                      config={"model": "claude-sonnet-5"}))
    platform.authorize_security_testing(agent_id="claude-support@1", approved_by="sec",
                                        categories=["prompt_injection", "pii"], reason="harness test window")
    platform.env.adapter_factory = lambda agent: ClaudeAgent(agent.config, client=SimpleNamespace(messages=messages))
    return "claude-support@1"


async def test_bad_credentials_fail_the_run_without_blaming_the_agent(authorized: EvalPlatform):
    messages = _Scripted(*[_status(anthropic.AuthenticationError, 401)] * 500)
    agent_id = _claude(authorized, messages)
    failed = await run(authorized, agent_id)
    assert failed.status == "failed" and "harness could not run agent" in failed.error
    assert authorized.repo.traces_for(failed.run_id) == [], "no trace may be scored against the agent"
    events = [e["event_type"] for e in authorized.audit_trail(failed.run_id)]
    assert "step_retry" not in events  # harness errors are not retried

    messages.failures.clear()  # credentials fixed
    resumed = await authorized.resume_run(failed.run_id, actor="alice")
    assert resumed.status in {"complete", "needs_review"}
    assert all(t.agent_error is None for t in authorized.repo.traces_for(failed.run_id))


async def test_overloaded_api_is_retried_not_scored(authorized: EvalPlatform):
    messages = _Scripted(_status(anthropic.OverloadedError, 529))
    agent_id = _claude(authorized, messages)
    summary = await run(authorized, agent_id)
    assert summary.status in {"complete", "needs_review"}
    retries = [e for e in authorized.audit_trail(summary.run_id) if e["event_type"] == "step_retry"]
    assert len(retries) == 1 and "OverloadedError" in retries[0]["payload"]["error"]
    assert all(t.agent_error is None for t in authorized.repo.traces_for(summary.run_id))


async def test_slow_agent_times_out_and_is_scored_as_a_crash(authorized: EvalPlatform, monkeypatch):
    class Sleepy(ScriptedAgent):
        async def run(self, prompt, sandbox, *, repeat):
            if "O-5001" in prompt:
                await asyncio.sleep(5)
            return await super().run(prompt, sandbox, repeat=repeat)

    monkeypatch.setattr(primary, "CASE_TIMEOUT_S", 0.05)
    authorized.env.adapter_factory = lambda agent: Sleepy([])
    summary = await run(authorized, HARDENED)
    timed_out = [t for t in authorized.repo.traces_for(summary.run_id) if t.agent_error]
    assert timed_out and all("TimeoutError" in t.agent_error for t in timed_out)
    assert "tool-order-status" in summary.scorecard["failing_cases"]
    recovery = [f for f in authorized.get_findings(summary.run_id) if f.finding_type == "recovery"]
    assert any("crashed" in f.statement for f in recovery)


async def test_schema_scoring_version_and_evidence_reads_are_audited(authorized: EvalPlatform):
    summary = await run(authorized, HARDENED)
    trail = authorized.audit_trail(summary.run_id)
    completed = [e for e in trail if e["event_type"] == "step_completed"]
    assert completed and all(e["payload"]["schema_version"] == SCHEMA_VERSION for e in completed)
    scored = authorized.get_artifact(summary.run_id, "Score traces")["payload"]
    assert scored["scoring_version"] == SCORING_VERSION
    traces = authorized.repo.traces_for(summary.run_id)
    assert len(scored["evidence_read"]) == len(traces)
    assert all(t.schema_version == SCHEMA_VERSION for t in traces)

    authorized.get_trace(traces[0].trace_id, reader="Reviewer")
    authorized.get_findings(summary.run_id, reader="reviewer")
    reads = [e for e in authorized.audit_trail(summary.run_id) if e["event_type"] == "evidence_read"]
    assert [(e["actor"], e["payload"]["what"]) for e in reads] == [("reviewer", "trace"), ("reviewer", "findings")]
    assert reads[0]["payload"]["evidence_ids"] == [authorized.get_trace(traces[0].trace_id)["evidence_id"]]
