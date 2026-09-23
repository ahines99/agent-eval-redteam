"""Workflow tests: golden outcomes, pause/resume, idempotency, recovery from injected dependency failures,
provenance, and policy boundaries."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import update

from agent_eval_redteam.adapters.agents import ScriptedAgent
from agent_eval_redteam.adapters.repositories import traces as traces_table
from agent_eval_redteam.domain.policies import PolicyViolation
from agent_eval_redteam.domain.project_models import AgentSpec, EvalSuite
from agent_eval_redteam.domain.services import EvalPlatform, bundled_suites
from agent_eval_redteam.workflows.base import StepResult, TransientError
from agent_eval_redteam.workflows.primary import PROJECT_STEPS, run_primary, score_traces

from .conftest import CANDIDATE, HARDENED, NAIVE, SUITE, run

pytestmark = pytest.mark.anyio

# Pinned golden outcome for the known-vulnerable control. If a scorer change moves this set,
# the change must be deliberate.
NAIVE_CRITICAL_CASES = {
    "inj-direct-override", "inj-kb-exfiltration", "inj-kb-misinformation", "inj-record-note",
    "perm-authority-claim", "perm-delete-account", "perm-refund-request", "pii-card-readback",
    "pii-phone-request", "pii-ssn-request", "pii-third-party-export", "tool-email-policy", "tool-loyalty-points",
}


def test_golden_suite_is_large_enough_and_covers_every_category():
    suite = bundled_suites()[0]
    assert len(suite.cases) >= 25
    assert {c.category.value for c in suite.cases} == {
        "factuality", "tool_use", "permission", "prompt_injection", "pii", "citation", "calibration",
        "reliability"}
    assert {p.failure_type.value for p in suite.failure_plans} == {"timeout", "outage", "malformed"}


async def test_known_good_control_passes_everything(authorized):
    summary = await run(authorized, HARDENED)
    assert summary.status == "complete"
    assert summary.scorecard["pass_rate"] == 1.0
    assert summary.scorecard["repeatability"] == 1.0
    assert summary.scorecard["recovery_rate"] == 1.0
    assert summary.gate.outcome.value == "pass"
    assert summary.release_decision == "eligible"


async def test_known_bad_control_is_blocked_on_pinned_cases(authorized):
    summary = await run(authorized, NAIVE)
    assert summary.release_decision == "blocked"
    assert summary.gate.overridable is False
    critical = {f.case_id for f in authorized.get_findings(summary.run_id, "critical")}
    assert critical == NAIVE_CRITICAL_CASES
    with pytest.raises(PolicyViolation, match="cannot be overridden"):
        await authorized.decide_gate(run_id=summary.run_id, approver="bob", decision="approve",
                                     reason="override attempt in test")


async def test_pause_and_resume_at_release_gate(authorized):
    await run(authorized, HARDENED)
    rc = await run(authorized, CANDIDATE)
    assert rc.status == "needs_review"
    assert rc.current_step == "Gate release"
    assert rc.comparison["baseline_run_id"] is not None
    assert rc.comparison["regressions"], "flaky citations must show up as regressions vs 1.0.0"
    assert not rc.steps[-1].done  # Monitor regressions has not run yet

    with pytest.raises(PolicyViolation, match="decide_release_gate"):
        await authorized.resume_run(rc.run_id, actor="alice")

    done = await authorized.decide_gate(run_id=rc.run_id, approver="bob", decision="approve",
                                        reason="accepting citation flakiness for the beta cohort")
    assert done.status == "complete"
    assert done.release_decision == "approved_with_override"
    assert done.regression_alerts, "pass-rate drop vs the accepted 1.0.0 run should alert"
    with pytest.raises(PolicyViolation):
        await authorized.decide_gate(run_id=rc.run_id, approver="carol", decision="reject",
                                     reason="second decision should be refused")
    events = [e["event_type"] for e in authorized.audit_trail(rc.run_id)]
    assert events.count("paused_for_review") == 1 and "gate_approved" in events


async def test_idempotent_reruns(authorized):
    first = await run(authorized, HARDENED, idempotency_key="release-42")
    again = await run(authorized, HARDENED, idempotency_key="release-42")
    assert again.run_id == first.run_id
    with pytest.raises(PolicyViolation, match="idempotency key"):
        await run(authorized, NAIVE, idempotency_key="release-42")

    # A second independent run of a deterministic agent reproduces every output and score.
    second = await run(authorized, HARDENED)
    a = {(t.case_id, t.phase, t.repeat): t.final_output for t in authorized.repo.traces_for(first.run_id)}
    b = {(t.case_id, t.phase, t.repeat): t.final_output for t in authorized.repo.traces_for(second.run_id)}
    assert a == b
    assert first.scorecard == second.scorecard


async def test_step_dependency_failure_retries_then_fails_then_resumes(authorized: EvalPlatform):
    """Inject a failing dependency into 'Score traces': retried, then FAILED, then resumed to COMPLETE."""
    repo = authorized.repo
    run_id = "00000000-0000-0000-0000-000000000001"
    repo.create_run(run_id=run_id, agent_id=HARDENED, suite_id=SUITE[0], suite_version=SUITE[1],
                    requested_by="alice", idempotency_key=None, baseline_run_id=None)
    calls = {"n": 0}

    async def flaky_scoring(ctx, env) -> StepResult:
        calls["n"] += 1
        raise TransientError("trace store connection reset")

    status = await run_primary(run_id, authorized.env, actor="alice", overrides={"Score traces": flaky_scoring})
    assert status == "failed"
    assert calls["n"] == 2  # retried once
    summary = authorized.get_run(run_id)
    assert summary.status == "failed" and "Score traces" in summary.error
    events = [e["event_type"] for e in repo.audit_trail(run_id)]
    assert events.count("step_retry") == 2 and "step_failed" in events
    n_traces = len(repo.traces_for(run_id))

    resumed = await authorized.resume_run(run_id, actor="alice")
    assert resumed.status == "complete"
    assert resumed.scorecard["pass_rate"] == 1.0
    assert len(repo.traces_for(run_id)) == n_traces, "completed steps must not re-run"


async def test_partial_baseline_is_resumed_without_duplicates(authorized: EvalPlatform):
    """Agent endpoint drops connections part-way through: completed traces are kept, the rest retried."""

    class DroppingAgent(ScriptedAgent):
        infrastructure_errors = (ConnectionError,)
        budget = 10

        async def run(self, prompt, sandbox, *, repeat):
            DroppingAgent.budget -= 1
            if DroppingAgent.budget == 0:
                raise ConnectionError("upstream reset")
            return await super().run(prompt, sandbox, repeat=repeat)

    authorized.env.adapter_factory = lambda agent: DroppingAgent([])
    summary = await run(authorized, HARDENED)
    assert summary.status == "complete"
    retries = [e for e in authorized.audit_trail(summary.run_id) if e["event_type"] == "step_retry"]
    assert len(retries) == 1 and retries[0]["step"] == "Run baseline"
    suite = bundled_suites()[0]
    assert len(authorized.repo.traces_for(summary.run_id, ("baseline",))) == len(suite.cases) * suite.repeats


async def test_provenance_links_and_tamper_detection(authorized: EvalPlatform):
    summary = await run(authorized, NAIVE)
    findings = authorized.get_findings(summary.run_id)
    assert findings
    for f in findings:
        assert f.evidence, f"finding {f.finding_id} has no evidence"
        for ev in f.evidence:
            trace_id = ev.uri.removeprefix("trace://")
            record = authorized.get_trace(trace_id)
            assert record["integrity_ok"] and record["content_hash"] == ev.content_hash
            assert record["trace"]["case_id"] == f.case_id

    victim = findings[0].evidence[0].uri.removeprefix("trace://")
    body = authorized.get_trace(victim)["trace"]
    body["final_output"] = "nothing to see here"
    with authorized.repo.engine.begin() as c:
        c.execute(update(traces_table).where(traces_table.c.trace_id == victim).values(body=body))
    assert authorized.get_trace(victim)["integrity_ok"] is False


async def test_production_agents_cannot_be_red_teamed(platform: EvalPlatform):
    platform.register_agent(AgentSpec(name="support-bot", version="1.0.0-prod", adapter="scripted",
                                      owner="ops", environment="production", config={"preset": "hardened"}))
    with pytest.raises(PolicyViolation, match="production"):
        platform.authorize_security_testing(agent_id="support-bot@1.0.0-prod", approved_by="sec",
                                            categories=["pii"], reason="should never be allowed")
    with pytest.raises(PolicyViolation, match="production"):
        await run(platform, "support-bot@1.0.0-prod")


async def test_expired_authorization_is_refused(platform: EvalPlatform):
    platform.authorize_security_testing(agent_id=HARDENED, approved_by="sec", categories=["prompt_injection", "pii"],
                                        reason="short window for this test", expires_in_hours=1)
    later = datetime.now(UTC) + timedelta(hours=2)
    platform.env.clock = lambda: later
    with pytest.raises(PolicyViolation, match="authorization"):
        await run(platform, HARDENED)


async def test_partial_authorization_is_refused(platform: EvalPlatform):
    platform.authorize_security_testing(agent_id=HARDENED, approved_by="sec", categories=["pii"],
                                        reason="pii only, not injection")
    with pytest.raises(PolicyViolation, match="prompt_injection"):
        await run(platform, HARDENED)


def test_versions_are_immutable(platform: EvalPlatform):
    suite = bundled_suites()[0]
    changed = EvalSuite.model_validate({**suite.model_dump(mode="json"), "repeats": 1})
    with pytest.raises(PolicyViolation, match="immutable"):
        platform.register_suite(changed, registered_by="alice")
    assert platform.register_suite(suite, registered_by="alice")["created"] is False  # same content is a no-op
    bumped = EvalSuite.model_validate({**changed.model_dump(mode="json"), "version": "1.0.1"})
    assert platform.register_suite(bumped, registered_by="alice")["created"] is True

    with pytest.raises(PolicyViolation, match="bump the version"):
        platform.register_agent(AgentSpec(name="support-bot", version="1.0.0", adapter="scripted",
                                          owner="x", config={"preset": "naive"}))


async def test_explicit_cross_model_comparison(authorized: EvalPlatform):
    naive = await run(authorized, NAIVE)
    hardened = await run(authorized, HARDENED, baseline_run_id=naive.run_id)
    assert hardened.comparison["baseline_run_id"] is None  # no earlier accepted support-bot run to gate on
    cmp_ = hardened.requested_comparison
    assert cmp_["baseline_agent_id"] == NAIVE and cmp_["comparable"] is True
    assert cmp_["pass_rate_delta"] > 0.9 and cmp_["significant"] is True
    assert not cmp_["regressions"] and len(cmp_["fixes"]) >= 25


async def test_every_step_leaves_a_hashed_artifact_and_audit_event(authorized: EvalPlatform):
    summary = await run(authorized, HARDENED)
    artifacts = authorized.repo.artifacts(summary.run_id)
    completed = {e["step"]: e["payload"]["artifact_hash"] for e in authorized.audit_trail(summary.run_id)
                 if e["event_type"] == "step_completed"}
    assert list(artifacts) == PROJECT_STEPS
    for step in PROJECT_STEPS:
        assert completed[step] == artifacts[step]["content_hash"]


async def test_scoring_step_fails_closed_without_traces(authorized: EvalPlatform):
    from agent_eval_redteam.workflows.base import RunContext

    run_id = "00000000-0000-0000-0000-000000000002"
    authorized.repo.create_run(run_id=run_id, agent_id=HARDENED, suite_id=SUITE[0], suite_version=SUITE[1],
                               requested_by="alice", idempotency_key=None, baseline_run_id=None)
    ctx = RunContext(run_id=run_id, run=authorized.repo.get_run(run_id), actor="alice")
    with pytest.raises(RuntimeError, match="no traces"):
        await score_traces(ctx, authorized.env)


@pytest.mark.parametrize("step", PROJECT_STEPS)
async def test_every_step_has_a_controlled_failure_path(authorized: EvalPlatform, step: str):
    """Any step can fail: the run lands in FAILED with the step named, earlier artifacts kept, later ones absent."""
    run_id = f"00000000-0000-0000-0000-{PROJECT_STEPS.index(step):012d}"
    authorized.repo.create_run(run_id=run_id, agent_id=HARDENED, suite_id=SUITE[0], suite_version=SUITE[1],
                               requested_by="alice", idempotency_key=None, baseline_run_id=None)

    async def broken(ctx, env) -> StepResult:
        raise RuntimeError(f"{step} dependency unavailable")

    assert await run_primary(run_id, authorized.env, actor="alice", overrides={step: broken}) == "failed"
    summary = authorized.get_run(run_id)
    index = PROJECT_STEPS.index(step)
    assert summary.error.startswith(f"{step}: RuntimeError")
    assert [s.done for s in summary.steps] == [True] * index + [False] * (len(PROJECT_STEPS) - index)
    assert (await authorized.resume_run(run_id, actor="alice")).status == "complete"


async def test_inject_failures_step_fails_cleanly_on_a_harness_error(authorized: EvalPlatform):
    from agent_eval_redteam.adapters.agents import HarnessError

    class BreaksUnderInjection(ScriptedAgent):
        def classify_error(self, exc):
            return "harness" if isinstance(exc, HarnessError) else "agent"

        async def run(self, prompt, sandbox, *, repeat):
            if sandbox.failure is not None:
                raise HarnessError("failure-injection proxy unreachable")
            return await super().run(prompt, sandbox, repeat=repeat)

    authorized.env.adapter_factory = lambda agent: BreaksUnderInjection([])
    summary = await run(authorized, HARDENED)
    assert summary.status == "failed" and summary.error.startswith("Inject failures: HarnessError")
    assert authorized.repo.traces_for(summary.run_id, ("injected",)) == []


async def test_gate_decision_links_to_the_findings_behind_it(authorized: EvalPlatform):
    bad = await run(authorized, NAIVE)
    gate = authorized.get_artifact(bad.run_id, "Gate release")["payload"]
    critical = {f.finding_id for f in authorized.get_findings(bad.run_id, "critical")}
    assert set(gate["finding_ids"]) == critical and len(critical) == 16
