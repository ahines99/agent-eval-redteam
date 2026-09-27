"""Shared SQLite/PostgreSQL transaction contracts using independent database connections.

Every contract runs locally on SQLite. PostgreSQL variants are marked ``postgres``
and use a disposable, uniquely named schema via TEST_POSTGRES_URL.
"""
from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier

import pytest
from alembic import command
from sqlalchemy import create_engine, insert, inspect, text, update
from sqlalchemy.exc import IntegrityError

from agent_eval_redteam.adapters import repositories
from agent_eval_redteam.adapters.repositories import (
    Repository,
    agents,
    approvals,
    audit_events,
    canonical_hash,
    eval_suites,
    evidence,
    execution_leases,
    run_artifacts,
    stable_id,
    traces,
    workflow_runs,
)
from agent_eval_redteam.domain.models import AuditEvent
from agent_eval_redteam.domain.policies import PolicyViolation
from agent_eval_redteam.domain.project_models import Trace
from agent_eval_redteam.domain.services import EvalPlatform, bootstrap, bundled_suites

from .test_delivery import assert_schema_matches, migration_config
from .test_delivery import postgres_url as postgres_url  # noqa: F401 - shared pytest fixture


@pytest.fixture(params=["sqlite", pytest.param("postgres", marks=pytest.mark.postgres)])
def backend_url(request, tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    if request.param == "postgres":
        return request.getfixturevalue("postgres_url")
    return "sqlite:///" + str(tmp_path / "contracts.db")


@pytest.fixture
def repository_pair(backend_url):
    command.upgrade(migration_config(backend_url), "head")
    first, second = Repository(backend_url), Repository(backend_url)
    try:
        bootstrap(EvalPlatform(first))
        # Verify independent server sessions, not merely two Python wrappers over one connection.
        if first.engine.dialect.name == "postgresql":
            with first.engine.connect() as left, second.engine.connect() as right:
                assert left.scalar(text("SELECT pg_backend_pid()")) != right.scalar(text("SELECT pg_backend_pid()"))
        yield first, second
    finally:
        first.close()
        second.close()


def new_run(repo: Repository) -> str:
    run_id = str(uuid.uuid4())
    assert repo.create_run(run_id=run_id, agent_id="support-bot@1.0.0", suite_id="support-core",
                           suite_version="1.2.0", requested_by="alice", idempotency_key=None,
                           baseline_run_id=None)
    return run_id


def simultaneously(left, right):
    """Start independent database operations together; bounded barriers expose deadlocks as failures."""
    barrier = Barrier(2, timeout=10)

    def invoke(operation):
        barrier.wait()
        return operation()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(invoke, operation) for operation in (left, right)]
        return [future.result(timeout=20) for future in futures]


def attempt_claim(repo: Repository, run_id: str) -> tuple[str | None, str | None]:
    try:
        return repo.claim_run(run_id), None
    except PolicyViolation as exc:
        return None, str(exc)


def test_exclusive_lease_under_connection_contention(repository_pair):
    first, second = repository_pair
    run_id = new_run(first)
    for _ in range(3):
        results = simultaneously(lambda: attempt_claim(first, run_id), lambda: attempt_claim(second, run_id))
        winners = [(repo, owner) for repo, (owner, _) in zip(repository_pair, results, strict=True) if owner]
        assert len(winners) == 1
        assert sum(error is not None and "already executing" in error for _, error in results) == 1
        winner, owner = winners[0]
        winner.release_run(run_id, owner)
        assert not first.has_active_lease(run_id)


def test_expired_owner_cannot_write_or_release_successor(repository_pair):
    first, second = repository_pair
    run_id = new_run(first)
    stale_owner = first.claim_run(run_id)
    with second.engine.begin() as connection:
        connection.execute(update(execution_leases).where(execution_leases.c.run_id == run_id)
                           .values(expires_at=datetime.now(UTC) - timedelta(seconds=1)))
    current_owner = second.claim_run(run_id)
    assert current_owner != stale_owner
    try:
        with first.execution_scope(run_id, stale_owner):
            with pytest.raises(PolicyViolation, match="lease lost"):
                first.save_artifact(run_id, "stale-write", {})
            with pytest.raises(PolicyViolation, match="lease lost"):
                first.update_run(run_id, status="complete")
            with pytest.raises(PolicyViolation, match="lease lost"):
                first.audit(AuditEvent(run_id=run_id, step="workflow", actor="stale", event_type="stale-write",
                                       created_at=datetime.now(UTC)))
        first.release_run(run_id, stale_owner)
        assert second.has_active_lease(run_id)
        assert second.get_run(run_id)["status"] == "pending"
        assert second.audit_trail(run_id) == []
        with second.execution_scope(run_id, current_owner):
            second.save_artifact(run_id, "current-write", {"owner": "successor"})
        assert set(first.artifacts(run_id)) == {"current-write"}
    finally:
        second.release_run(run_id, current_owner)


def test_capacity_admission_is_atomic_across_connections(repository_pair, monkeypatch):
    monkeypatch.setattr(repositories, "MAX_ACTIVE_RUNS", 1)
    first, second = repository_pair
    run_ids = [new_run(first), new_run(first)]
    results = simultaneously(lambda: attempt_claim(first, run_ids[0]), lambda: attempt_claim(second, run_ids[1]))
    assert sum(owner is not None for owner, _ in results) == 1
    assert sum(error is not None and "concurrent run limit" in error for _, error in results) == 1
    winner_index = next(index for index, (owner, _) in enumerate(results) if owner is not None)
    loser_index = 1 - winner_index
    winner = repository_pair[winner_index]
    winner.release_run(run_ids[winner_index], results[winner_index][0])
    loser = repository_pair[loser_index]
    owner = loser.claim_run(run_ids[loser_index])
    loser.release_run(run_ids[loser_index], owner)


@pytest.mark.parametrize("operation", ["checkpoint", "transition"])
def test_failed_audit_insert_rolls_back_entire_transition(repository_pair, operation):
    first, observer = repository_pair
    run_id = new_run(first)
    owner = first.claim_run(run_id)
    event = AuditEvent(run_id=run_id, step="Gate release", actor="alice", event_type="step_completed",
                       created_at=datetime.now(UTC))
    malformed = event.model_copy(update={"event_type": None})
    try:
        with first.execution_scope(run_id, owner), pytest.raises(IntegrityError):
            if operation == "checkpoint":
                first.checkpoint(run_id, "Gate release", {"decision": {"outcome": "review"}},
                                 [event, malformed], pause=True)
            else:
                first.transition_run(run_id, [event, malformed], status="complete", current_step=None)
        assert observer.get_run(run_id)["status"] == "pending"
        assert observer.artifacts(run_id) == {}
        assert observer.audit_trail(run_id) == []
        # PostgreSQL must remain usable after the aborted transaction, including its fencing path.
        with first.execution_scope(run_id, owner):
            first.checkpoint(run_id, "Gate release", {"decision": {"outcome": "review"}}, [event], pause=True)
        assert observer.get_run(run_id)["status"] == "needs_review"
        assert len(observer.audit_trail(run_id)) == 1
        assert "Gate release" in observer.artifacts(run_id)
    finally:
        first.release_run(run_id, owner)


def test_competing_approvals_preserve_exactly_one_decision(repository_pair):
    first, second = repository_pair
    run_id = new_run(first)

    def decide(repo, decision, actor):
        return repo.insert_approval(run_id=run_id, gate="Gate release", decision=decision, approver=actor,
                                    reason="Concurrent independent review", override=decision == "approve")

    results = simultaneously(lambda: decide(first, "approve", "bob"), lambda: decide(second, "reject", "carol"))
    assert sorted(results) == [False, True]
    winner = first.get_approval(run_id, "Gate release")
    assert winner is not None
    expected = ("approve", "bob", True) if results[0] else ("reject", "carol", False)
    assert (winner["decision"], winner["approver"], winner["override"]) == expected
    assert second.get_approval(run_id, "Gate release") == winner
    assert not decide(second, "approve" if winner["decision"] == "reject" else "reject", "dave")
    assert first.get_approval(run_id, "Gate release") == winner


def test_upgrade_preserves_run_evidence_review_and_audit(backend_url):
    config = migration_config(backend_url)
    command.upgrade(config, "0001")
    engine = create_engine(backend_url)
    run_id, trace_id = str(uuid.uuid4()), str(uuid.uuid4())
    ts = datetime.now(UTC)
    suite = bundled_suites()[-1]
    trace = Trace(trace_id=trace_id, run_id=run_id, case_id=suite.cases[0].case_id, phase="baseline",
                  repeat=0, agent_id="legacy@1", model="scripted-reference", final_output="retained output")
    body = trace.model_dump(mode="json")
    digest = canonical_hash(body)
    evidence_id = stable_id("evidence", trace_id)
    gate = {"decision": {"outcome": "review"}}
    try:
        with engine.begin() as connection:
            assert "execution_leases" not in inspect(connection).get_table_names()
            connection.execute(insert(agents).values(agent_id="legacy@1", name="legacy", version="1",
                adapter="scripted", environment="sandbox", owner="alice", config={}, config_hash=canonical_hash({}),
                registered_at=ts))
            connection.execute(insert(eval_suites).values(suite_id=suite.suite_id, version=suite.version,
                content_hash=suite.content_hash(), definition=suite.model_dump(mode="json", exclude_defaults=True),
                registered_by="alice", created_at=ts))
            connection.execute(insert(workflow_runs).values(run_id=run_id, project_type="agent-eval-redteam",
                status="needs_review", current_step="Gate release", agent_id="legacy@1", suite_id=suite.suite_id,
                suite_version=suite.version, requested_by="alice", created_at=ts, updated_at=ts))
            connection.execute(insert(traces).values(trace_id=trace_id, run_id=run_id, case_id=trace.case_id,
                phase=trace.phase, repeat=0, content_hash=digest, body=body, created_at=ts))
            connection.execute(insert(evidence).values(evidence_id=evidence_id, run_id=run_id,
                source_uri=f"trace://{trace_id}", source_type="agent_trace", as_of=ts, content_hash=digest,
                metadata={"case_id": trace.case_id, "phase": "baseline", "repeat": 0}))
            connection.execute(insert(run_artifacts).values(run_id=run_id, step="Gate release", payload=gate,
                content_hash=canonical_hash(gate), created_at=ts))
            connection.execute(insert(approvals).values(approval_id=str(uuid.uuid4()), run_id=run_id,
                gate="Gate release", decision="reject", approver="bob", reason="retained review",
                override=False, created_at=ts))
            connection.execute(insert(audit_events).values(run_id=run_id, step="Gate release", actor="bob",
                event_type="gate_rejected", payload={"retained": True}, created_at=ts))
        command.upgrade(config, "head")
        command.upgrade(config, "head")
        assert_schema_matches(backend_url)
        command.check(config)
        repo = Repository(backend_url)
        try:
            assert repo.get_run(run_id)["status"] == "needs_review"
            assert repo.get_trace(trace_id) == (trace, digest)
            assert repo.get_evidence(evidence_id).content_hash == digest
            assert repo.artifacts(run_id)["Gate release"]["payload"] == gate
            assert repo.get_approval(run_id, "Gate release")["decision"] == "reject"
            assert repo.audit_trail(run_id)[0]["payload"] == {"retained": True}
            owner = repo.claim_run(run_id)
            assert repo.has_active_lease(run_id)
            repo.release_run(run_id, owner)
        finally:
            repo.close()
    finally:
        engine.dispose()
