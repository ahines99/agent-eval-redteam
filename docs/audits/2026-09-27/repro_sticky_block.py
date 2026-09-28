"""Read-only repository audit: demonstrate stale approval after version-wide block.

Uses only an in-memory SQLite store and scripted reference agents. No paid calls.
Historical reproduction for commit 517f96c. Corrected versions refuse the approval.
Current regression coverage: tests/test_version_blocks.py.
"""
import asyncio
import json

from agent_eval_redteam.adapters.repositories import Repository
from agent_eval_redteam.domain.project_models import AgentSpec, EvalSuite
from agent_eval_redteam.domain.services import EvalPlatform, bootstrap, bundled_suites


async def main():
    platform = EvalPlatform(Repository("sqlite://"))
    try:
        bootstrap(platform)
        agent_id = "support-bot-naive@0.9.0"
        platform.authorize_security_testing(
            agent_id=agent_id, approved_by="security-lead",
            categories=["prompt_injection", "pii"], reason="final audit reproduction only",
        )
        case = bundled_suites()[0].case("tool-order-status").model_dump(mode="json")
        case["budget"] = {"max_latency_ms": 1}
        platform.register_suite(EvalSuite.model_validate({
            "suite_id": "old-review", "version": "1.0.0", "description": "audit",
            "repeats": 1, "cases": [case],
        }), "alice")
        older = await platform.start_run(
            agent_id=agent_id, suite_id="old-review", suite_version="1.0.0", requested_by="alice",
        )
        blocked = await platform.start_run(
            agent_id=agent_id, suite_id="support-core", suite_version="1.2.0", requested_by="alice",
        )
        approved = await platform.decide_gate(
            run_id=older.run_id, approver="bob", decision="approve",
            reason="Reviewed isolated latency miss",
        )
        fresh = await platform.start_run(
            agent_id=agent_id, suite_id="old-review", suite_version="1.0.0", requested_by="alice",
        )
        platform.register_agent(AgentSpec(
            name="support-bot-naive", version="1.0.0", adapter="scripted", owner="alice",
            config={"preset": "hardened"},
        ))
        next_version = await platform.start_run(
            agent_id="support-bot-naive@1.0.0", suite_id="old-review", suite_version="1.0.0",
            requested_by="alice",
        )
        result = {
            "older_initial_decision": older.release_decision,
            "later_security_run_decision": blocked.release_decision,
            "older_after_later_block_and_approval": approved.release_decision,
            "fresh_same_version_decision": fresh.release_decision,
            "new_version_uses_old_approved_blocked_version_as_baseline":
                next_version.comparison["baseline_run_id"] == older.run_id,
        }
        assert result == {
            "older_initial_decision": "awaiting_review",
            "later_security_run_decision": "blocked",
            "older_after_later_block_and_approval": "approved_with_override",
            "fresh_same_version_decision": "blocked",
            "new_version_uses_old_approved_blocked_version_as_baseline": True,
        }, result
        print(json.dumps(result, indent=2))
    finally:
        platform.repo.close()


if __name__ == "__main__":
    asyncio.run(main())
