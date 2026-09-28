"""Persistence-boundary, concurrent-worker and evidence-integrity regressions."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, update
from sqlalchemy.exc import IntegrityError

from agent_eval_redteam.adapters import repositories
from agent_eval_redteam.adapters.agents import ScriptedAgent
from agent_eval_redteam.adapters.repositories import (
    Repository,
    evidence,
    execution_leases,
    run_artifacts,
    run_metrics,
    traces,
)
from agent_eval_redteam.domain.models import AuditEvent
from agent_eval_redteam.domain.policies import PolicyViolation
from agent_eval_redteam.domain.services import bundled_suites
from agent_eval_redteam.workflows import primary

from .conftest import CANDIDATE, HARDENED, SUITE, gate_payload, run

pytestmark = pytest.mark.anyio


def pending(repo, run_id="audit-run"):
    repo.create_run(run_id=run_id, agent_id=HARDENED, suite_id=SUITE[0], suite_version=SUITE[1],
                    requested_by="alice", idempotency_key=None, baseline_run_id=None)
    return run_id


async def stopped_before_scoring(platform):
    rid = pending(platform.repo)

    async def stop(ctx, env):
        raise RuntimeError("audit stop before scoring")

    assert await primary.run_primary(rid, platform.env, actor="alice", overrides={"Score traces": stop}) == "failed"
    return rid


async def test_concurrent_resume_calls_agent_once_per_trace(authorized):
    entered, finish = asyncio.Event(), asyncio.Event()

    class Slow(ScriptedAgent):
        calls = 0

        async def run(self, prompt, sandbox, *, repeat):
            Slow.calls += 1
            entered.set()
            await finish.wait()
            return await super().run(prompt, sandbox, repeat=repeat)

    authorized.env.adapter_factory = lambda agent: Slow([])
    rid = pending(authorized.repo)
    first = asyncio.create_task(authorized.resume_run(rid, actor="alice"))
    try:
        await entered.wait()
        with pytest.raises(PolicyViolation, match="already executing"):
            await authorized.resume_run(rid, actor="bob")
    finally:
        finish.set()
        result = await first
    assert result.status == "complete"
    assert Slow.calls == len(authorized.repo.traces_for(rid))
    assert sum(e["event_type"] == "run_completed" for e in authorized.audit_trail(rid)) == 1
    assert not authorized.repo.has_active_lease(rid)


async def test_expired_lease_recovery_fences_previous_owner(tmp_path):
    url = f"sqlite:///{tmp_path / 'leases.db'}"
    first, second = Repository(url), Repository(url)
    try:
        rid = pending(first)
        owner = first.claim_run(rid)
        with pytest.raises(PolicyViolation, match="already executing"):
            second.claim_run(rid)
        with first.engine.begin() as c:
            c.execute(update(execution_leases).where(execution_leases.c.run_id == rid)
                      .values(expires_at=datetime.now(UTC) - timedelta(seconds=1)))
        successor = second.claim_run(rid)
        with first.execution_scope(rid, owner), pytest.raises(PolicyViolation, match="lease lost"):
            first.save_artifact(rid, "stale", {})
        first.release_run(rid, owner)
        assert second.has_active_lease(rid), "stale worker must not release its successor's lease"
        with second.execution_scope(rid, successor):
            second.save_artifact(rid, "current", {})
        assert set(first.artifacts(rid)) == {"current"}
        second.release_run(rid, successor)
    finally:
        first.close()
        second.close()


async def test_concurrent_run_capacity_is_released_and_expired(authorized, monkeypatch):
    monkeypatch.setattr(repositories, "MAX_ACTIVE_RUNS", 1)
    first = pending(authorized.repo, "capacity-first")
    second = pending(authorized.repo, "capacity-second")
    owner = authorized.repo.claim_run(first)
    with pytest.raises(PolicyViolation, match="concurrent run limit"):
        authorized.repo.claim_run(second)
    authorized.repo.release_run(first, owner)
    successor = authorized.repo.claim_run(second)
    with authorized.repo.engine.begin() as c:
        c.execute(update(execution_leases).where(execution_leases.c.run_id == second)
                  .values(expires_at=datetime.now(UTC) - timedelta(seconds=1)))
    authorized.repo.release_run(first, authorized.repo.claim_run(first))
    authorized.repo.release_run(second, successor)


async def test_checkpoint_rolls_back_artifact_when_audit_insert_fails(authorized):
    rid = pending(authorized.repo)
    event = AuditEvent(run_id=rid, step="Gate release", event_type="step_completed", actor="alice",
                       created_at=datetime.now(UTC)).model_copy(update={"event_type": None})
    with pytest.raises(IntegrityError):
        authorized.repo.checkpoint(rid, "Gate release", gate_payload(),
                                   [event], pause=True)
    assert authorized.repo.artifacts(rid) == {}
    assert authorized.repo.get_run(rid)["status"] == "pending"


async def test_crash_after_gate_checkpoint_preserves_review_boundary(authorized, monkeypatch):
    checkpoint = authorized.repo.checkpoint

    def crash_after_commit(run_id, step, payload, events, *, pause):
        digest = checkpoint(run_id, step, payload, events, pause=pause)
        if step == "Gate release":
            raise RuntimeError("process stopped after committed checkpoint")
        return digest

    monkeypatch.setattr(authorized.repo, "checkpoint", crash_after_commit)
    with pytest.raises(RuntimeError, match="process stopped"):
        await run(authorized, CANDIDATE, idempotency_key="crash-at-gate")
    rid = authorized.repo.run_by_idempotency_key("crash-at-gate")["run_id"]
    assert authorized.get_run(rid).status == "needs_review"
    assert any(e["event_type"] == "step_completed" and e["step"] == "Gate release"
               for e in authorized.audit_trail(rid))
    with pytest.raises(PolicyViolation, match="decide_release_gate"):
        await authorized.resume_run(rid, actor="alice")
    monkeypatch.setattr(authorized.repo, "checkpoint", checkpoint)
    result = await authorized.decide_gate(run_id=rid, approver="bob", decision="approve",
                                         reason="Independent review after process restart")
    assert result.status == "complete" and result.release_decision == "approved_with_override"


@pytest.mark.parametrize("legacy_status", ["running", "complete", "failed"])
async def test_legacy_gate_checkpoint_recovers_unresolved_review(authorized, legacy_status):
    result = await run(authorized, CANDIDATE)
    authorized.repo.update_run(result.run_id, status=legacy_status)
    assert authorized.repo.recover_review_state(result.run_id)
    assert authorized.get_run(result.run_id).status == "needs_review"
    assert await primary.run_primary(result.run_id, authorized.env, actor="alice") == "needs_review"


@pytest.mark.parametrize("phase", ["baseline", "injected"])
async def test_missing_release_trace_fails_closed(authorized, phase):
    rid = await stopped_before_scoring(authorized)
    victim = authorized.repo.traces_for(rid, (phase,))[0]
    with authorized.repo.engine.begin() as c:
        c.execute(delete(traces).where(traces.c.trace_id == victim.trace_id))
    result = await authorized.resume_run(rid, actor="alice")
    assert result.status == "failed" and "manifest" in result.error
    assert result.gate is None


@pytest.mark.parametrize("target", ["trace", "evidence"])
async def test_corrupted_release_evidence_fails_closed(authorized, target):
    rid = await stopped_before_scoring(authorized)
    victim = authorized.repo.traces_for(rid)[0]
    with authorized.repo.engine.begin() as c:
        if target == "trace":
            body = victim.model_dump(mode="json")
            body["final_output"] = "Corrupted output"
            c.execute(update(traces).where(traces.c.trace_id == victim.trace_id).values(body=body))
        else:
            c.execute(update(evidence).where(evidence.c.source_uri == f"trace://{victim.trace_id}")
                      .values(content_hash="sha256:corrupted"))
    result = await authorized.resume_run(rid, actor="alice")
    assert result.status == "failed" and "integrity" in result.error
    assert result.gate is None


async def test_corrupted_artifact_is_never_consumed(authorized):
    rid = await stopped_before_scoring(authorized)
    with authorized.repo.engine.begin() as c:
        c.execute(update(run_artifacts).where(run_artifacts.c.run_id == rid,
                                              run_artifacts.c.step == "Run baseline").values(payload={}))
    with pytest.raises(PolicyViolation, match="artifact integrity"):
        await authorized.resume_run(rid, actor="alice")


async def test_baseline_search_has_no_nonaccepted_run_cutoff(authorized):
    base = await run(authorized, HARDENED)
    metrics = authorized.repo.get_run_metrics(base.run_id)
    for number in range(51):
        rid = pending(authorized.repo, f"intervening-{number}")
        authorized.repo.save_run_metrics(run_id=rid, agent_name="support-bot", suite_id=SUITE[0],
                                         suite_version=SUITE[1], scorecard=metrics["scorecard"],
                                         outcomes=metrics["case_outcomes"])
        authorized.repo.update_run(rid, status="needs_review")
        authorized.repo.save_artifact(rid, "Gate release", gate_payload())
    result = await run(authorized, CANDIDATE)
    assert result.comparison["baseline_run_id"] == base.run_id


@pytest.mark.parametrize("changed", ["world_hash", "scoring_version", "gate_policy_version"])
async def test_baseline_identity_must_match_world_and_scorer(authorized, changed):
    base = await run(authorized, HARDENED)
    score = authorized.repo.artifacts(base.run_id)["Score traces"]["payload"]
    score["evaluation_identity"][changed] = "historical-implementation"
    authorized.repo.save_artifact(base.run_id, "Score traces", score)
    result = await run(authorized, CANDIDATE, baseline_run_id=base.run_id)
    assert result.comparison["baseline_run_id"] is None
    assert result.requested_comparison["comparable"] is False


async def test_resume_rejects_changed_evaluation_implementation(authorized, monkeypatch):
    rid = await stopped_before_scoring(authorized)
    monkeypatch.setattr(primary, "SCORING_VERSION", "scoring/future")
    with pytest.raises(PolicyViolation, match="implementation changed"):
        await authorized.resume_run(rid, actor="alice")


async def test_corrupted_metrics_cannot_be_used_as_baseline(authorized):
    base = await run(authorized, HARDENED)
    with authorized.repo.engine.begin() as c:
        c.execute(update(run_metrics).where(run_metrics.c.run_id == base.run_id).values(pass_rate=0.25))
    with pytest.raises(PolicyViolation, match="metrics do not match"):
        authorized.repo.validate_run_metrics(base.run_id)
    result = await run(authorized, CANDIDATE)
    assert result.status == "failed" and "metrics do not match" in result.error


async def test_accepted_baseline_requires_intact_evidence(authorized):
    base = await run(authorized, HARDENED)
    victim = authorized.repo.traces_for(base.run_id)[0]
    with authorized.repo.engine.begin() as c:
        c.execute(delete(evidence).where(evidence.c.source_uri == f"trace://{victim.trace_id}"))
    result = await run(authorized, CANDIDATE)
    assert result.status == "failed" and "integrity" in result.error


async def test_queued_case_rechecks_authorization_before_adapter_call(authorized, monkeypatch):
    suite = bundled_suites()[0].model_copy(update={
        "suite_id": "expiry-queue", "cases": [bundled_suites()[0].case("pii-ssn-request")],
        "repeats": 3, "failure_plans": [],
    })
    authorized.register_suite(suite, registered_by="alice")
    monkeypatch.setattr(primary, "CONCURRENCY", 1)
    ts = datetime.now(UTC)
    authorized.env.clock = lambda: ts

    class Expiring(ScriptedAgent):
        calls = 0

        async def run(self, prompt, sandbox, *, repeat):
            nonlocal ts
            Expiring.calls += 1
            ts += timedelta(days=4)
            return await super().run(prompt, sandbox, repeat=repeat)

    authorized.env.adapter_factory = lambda agent: Expiring([])
    result = await authorized.start_run(agent_id=HARDENED, suite_id=suite.suite_id,
                                        suite_version=suite.version, requested_by="alice")
    assert result.status == "failed" and "authorization" in result.error
    assert Expiring.calls == 1
