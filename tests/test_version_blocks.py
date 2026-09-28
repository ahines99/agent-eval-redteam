"""Version-wide release invariants, including independent-connection commit ordering."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Event

import pytest
from sqlalchemy import event, update

from agent_eval_redteam.adapters.repositories import canonical_hash, run_artifacts
from agent_eval_redteam.domain.models import AuditEvent
from agent_eval_redteam.domain.policies import PolicyViolation
from agent_eval_redteam.domain.project_models import AgentSpec, EvalSuite
from agent_eval_redteam.domain.services import EvalPlatform, bundled_suites
from agent_eval_redteam.workflows.primary import GATE_STEP, release_decision

from .conftest import HARDENED, NAIVE, gate_payload
from .test_delivery import postgres_url as postgres_url  # noqa: F401
from .test_postgres_contracts import backend_url as backend_url  # noqa: F401
from .test_postgres_contracts import new_run
from .test_postgres_contracts import repository_pair as repository_pair  # noqa: F401


def small_suite(platform, name, *, latency=8000):
    case = bundled_suites()[0].case("tool-order-status").model_dump(mode="json")
    case["budget"] = {"max_latency_ms": latency}
    suite = EvalSuite.model_validate({"suite_id": name, "version": "1.0.0", "description": "version block test",
                                     "repeats": 1, "cases": [case]})
    platform.register_suite(suite, "alice")
    return suite


async def start(platform, suite, agent_id=NAIVE):
    return await platform.start_run(agent_id=agent_id, suite_id=suite.suite_id,
                                    suite_version=suite.version, requested_by="alice")


@pytest.mark.anyio
async def test_later_block_revokes_old_eligibility_and_prevents_stale_approval(repository_pair):
    repo, _ = repository_pair
    platform = EvalPlatform(repo)
    platform.authorize_security_testing(agent_id=NAIVE, approved_by="security-lead",
                                        categories=["pii", "prompt_injection"], reason="synthetic regression")
    review_suite = small_suite(platform, "review", latency=1)
    pass_suite = small_suite(platform, "pass")
    pending = await start(platform, review_suite)
    approved = await start(platform, review_suite)
    approved = await platform.decide_gate(run_id=approved.run_id, approver="bob", decision="approve",
                                          reason="Reviewed latency finding")
    eligible = await start(platform, pass_suite)
    assert pending.release_decision == "awaiting_review"
    assert approved.release_decision == "approved_with_override"
    assert eligible.release_decision == "eligible"
    snapshots = {r.run_id: repo.artifacts(r.run_id) for r in (pending, approved, eligible)}
    old_approval = repo.get_approval(approved.run_id, GATE_STEP)
    blocked = await platform.start_run(agent_id=NAIVE, suite_id="support-core", suite_version="1.2.0",
                                        requested_by="alice")
    assert blocked.release_decision == "blocked"
    for run in (pending, approved, eligible):
        current = platform.get_run(run.run_id)
        assert current.release_decision == "blocked"
        assert blocked.run_id in current.version_block_run_ids
        assert repo.artifacts(run.run_id) == snapshots[run.run_id]
        assert "Effective version-wide block" in platform.run_report(run.run_id)
    with pytest.raises(PolicyViolation, match="version-wide block"):
        await platform.decide_gate(run_id=pending.run_id, approver="bob", decision="approve",
                                   reason="Attempt stale approval after block")
    assert repo.get_approval(pending.run_id, GATE_STEP) is None
    assert not any(e["event_type"] == "gate_approved" for e in repo.audit_trail(pending.run_id))
    assert repo.get_approval(approved.run_id, GATE_STEP) == old_approval
    assert (await start(platform, review_suite)).release_decision == "blocked"
    platform.register_agent(AgentSpec(name="support-bot-naive", version="1.0.0", adapter="scripted", owner="alice",
                                      config={"preset": "hardened"}))
    for suite in (review_suite, pass_suite):
        successor = await start(platform, suite, "support-bot-naive@1.0.0")
        assert successor.comparison["baseline_run_id"] is None
    rejected = await platform.decide_gate(run_id=pending.run_id, approver="bob", decision="reject",
                                          reason="Close review of blocked version")
    assert rejected.status == "complete" and rejected.release_decision == "blocked"


@pytest.mark.anyio
@pytest.mark.parametrize("latency", [1, 8000], ids=["stale-review", "stale-pass"])
async def test_block_before_checkpoint_cannot_commit_a_stale_pause(repository_pair, monkeypatch, latency):
    repo, concurrent = repository_pair
    platform = EvalPlatform(repo)
    suite = small_suite(platform, "checkpoint-race", latency=latency)
    blocker = new_run(concurrent)  # Same HARDENED agent version as this evaluation.
    original = repo.checkpoint

    def publish_block_first(run_id, step, payload, events, *, pause):
        if step == GATE_STEP:
            assert payload["decision"]["outcome"] == ("review" if latency == 1 else "pass")
            concurrent.checkpoint(blocker, GATE_STEP, gate_payload("block"), [], pause=False)
        return original(run_id, step, payload, events, pause=pause)

    monkeypatch.setattr(repo, "checkpoint", publish_block_first)
    result = await start(platform, suite, HARDENED)
    assert result.status == "complete" and result.release_decision == "blocked"
    assert result.gate.outcome == "block" and not result.gate.overridable
    artifact = repo.artifacts(result.run_id)[GATE_STEP]
    assert artifact["payload"]["prior_blocks"] == [blocker]
    events = repo.audit_trail(result.run_id)
    assert not any(e["event_type"] == "paused_for_review" for e in events)
    completed = next(e for e in events if e["step"] == GATE_STEP and e["event_type"] == "step_completed")
    assert completed["payload"]["artifact_hash"] == artifact["content_hash"]
    assert artifact["content_hash"] == canonical_hash(artifact["payload"])


@pytest.mark.parametrize("first_operation", ["approve", "block"])
def test_approval_and_block_have_serialized_commit_order(repository_pair, first_operation):
    first, second = repository_pair
    pending, blocker = new_run(first), new_run(first)
    first.checkpoint(pending, GATE_STEP, gate_payload(), [], pause=True)
    entered, release, second_attempt = Event(), Event(), Event()

    def hold_agent_lock(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("UPDATE agents SET") and not entered.is_set():
            entered.set()
            assert release.wait(10), "test did not release the held agent lock"

    def observe_second(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("UPDATE agents SET"):
            second_attempt.set()

    def perform(repo, operation):
        if operation == "block":
            repo.checkpoint(blocker, GATE_STEP, gate_payload("block"), [], pause=False)
            return "blocked"
        audit = AuditEvent(run_id=pending, step=GATE_STEP, actor="bob", event_type="gate_approved",
                           created_at=datetime.now(UTC))
        try:
            assert repo.insert_approval(run_id=pending, gate=GATE_STEP, decision="approve", approver="bob",
                                         reason="Independent review", override=True, audit_event=audit)
            return "approved"
        except PolicyViolation:
            return "refused"

    event.listen(first.engine, "after_cursor_execute", hold_agent_lock)
    event.listen(second.engine, "before_cursor_execute", observe_second)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            initial = pool.submit(perform, first, first_operation)
            try:
                assert entered.wait(10)
                later = pool.submit(perform, second, "block" if first_operation == "approve" else "approve")
                assert second_attempt.wait(10)
                assert not later.done(), "second writer must wait for the first version transaction"
            finally:
                release.set()
            results = [initial.result(timeout=15), later.result(timeout=15)]
        assert results == (["approved", "blocked"] if first_operation == "approve" else ["blocked", "refused"])
        assert (first.get_approval(pending, GATE_STEP) is not None) == (first_operation == "approve")
        assert len(first.audit_trail(pending)) == (1 if first_operation == "approve" else 0)
        assert release_decision(first, pending, first.artifacts(pending)[GATE_STEP]["payload"]) == "blocked"
    finally:
        release.set()
        event.remove(first.engine, "after_cursor_execute", hold_agent_lock)
        event.remove(second.engine, "before_cursor_execute", observe_second)


@pytest.mark.parametrize("corruption", ["hash", "shape"])
def test_corrupt_version_gate_fails_closed_for_approvals_and_reads(repository_pair, corruption):
    repo, observer = repository_pair
    pending, blocker = new_run(repo), new_run(repo)
    repo.checkpoint(pending, GATE_STEP, gate_payload(), [], pause=True)
    repo.checkpoint(blocker, GATE_STEP, gate_payload("block"), [], pause=False)
    bad = {"decision": {"outcome": "pass"}}
    values = {"payload": bad}
    if corruption == "shape":
        values["content_hash"] = canonical_hash(bad)
    with repo.engine.begin() as connection:
        connection.execute(update(run_artifacts).where(run_artifacts.c.run_id == blocker).values(**values))
    with pytest.raises(PolicyViolation, match="artifact integrity|invalid committed"):
        observer.version_blocks(pending)
    with pytest.raises(PolicyViolation, match="artifact integrity|invalid committed"):
        observer.insert_approval(run_id=pending, gate=GATE_STEP, decision="approve", approver="bob",
                                 reason="Independent review", override=True)
    assert repo.get_approval(pending, GATE_STEP) is None


def test_committed_block_survives_failed_monitoring_and_cannot_be_replaced(repository_pair):
    repo, observer = repository_pair
    blocker = new_run(repo)
    repo.checkpoint(blocker, GATE_STEP, gate_payload("block"), [], pause=False)
    original = repo.artifacts(blocker)
    repo.update_run(blocker, status="failed", error="monitor failed after gate commit")
    assert observer.version_blocks(blocker) == [blocker]
    with pytest.raises(PolicyViolation, match="immutable"):
        repo.save_artifact(blocker, GATE_STEP, gate_payload("pass"))
    assert observer.artifacts(blocker) == original
