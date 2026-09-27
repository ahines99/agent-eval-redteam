from __future__ import annotations

import pytest

from agent_eval_redteam.domain.models import AuditEvent
from agent_eval_redteam.domain.policies import PolicyViolation
from agent_eval_redteam.domain.project_models import EvalCase, EvalSuite
from agent_eval_redteam.domain.services import validate_suite_limits

from .conftest import CANDIDATE, HARDENED, run


@pytest.mark.anyio
async def test_idempotency_fingerprints_requester_and_comparison(authorized):
    baseline = await run(authorized, HARDENED)
    await run(authorized, HARDENED, idempotency_key="fingerprint")
    with pytest.raises(PolicyViolation, match="different run"):
        await run(authorized, HARDENED, idempotency_key="fingerprint", requested_by="bob")
    with pytest.raises(PolicyViolation, match="different run"):
        await run(authorized, HARDENED, idempotency_key="fingerprint", baseline_run_id=baseline.run_id)


def test_suite_limits_bound_work():
    cases = [EvalCase(case_id=f"case-{i}", category="factuality", prompt="Question", expected_policy="Answer")
             for i in range(129)]
    suite = EvalSuite(suite_id="bounded", version="1.0.0", description="Limits", cases=cases)
    with pytest.raises(PolicyViolation, match="128 cases"):
        validate_suite_limits(suite)
    suite = suite.model_copy(update={"cases": cases[:100], "repeats": 10})
    with pytest.raises(PolicyViolation, match="512 agent"):
        validate_suite_limits(suite)
    suite = suite.model_copy(update={"cases": [cases[0]], "repeats": 1})
    suite.cases[0].prompt = "x" * 20_001
    with pytest.raises(PolicyViolation, match="20,000"):
        validate_suite_limits(suite)


@pytest.mark.anyio
async def test_approval_is_rolled_back_if_audit_write_fails(authorized):
    result = await run(authorized, CANDIDATE)
    event = AuditEvent(run_id=result.run_id, step="Gate release", event_type="gate_approved", actor="bob",
                       created_at=authorized.env.clock())
    invalid_event = event.model_copy(update={"created_at": None})
    assert authorized.repo.insert_approval(run_id=result.run_id, gate="Gate release", decision="approve",
                                            approver="bob", reason="transaction rollback test", override=True,
                                            audit_event=invalid_event) is False
    assert authorized.repo.get_approval(result.run_id, "Gate release") is None
    assert authorized.get_run(result.run_id).release_decision == "awaiting_review"
