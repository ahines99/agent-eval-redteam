from __future__ import annotations

import pytest

from agent_eval_redteam import mcp_server
from agent_eval_redteam.adapters.repositories import Repository
from agent_eval_redteam.domain.policies import GATE_POLICY_VERSION
from agent_eval_redteam.domain.services import EvalPlatform, bootstrap

HARDENED = "support-bot@1.0.0"
CANDIDATE = "support-bot@1.1.0-rc1"
NAIVE = "support-bot-naive@0.9.0"
SUITE = ("support-core", "1.0.0")


def gate_payload(outcome="review"):
    return {"decision": {"outcome": outcome, "policy_version": GATE_POLICY_VERSION,
                         "reasons": ["Synthetic test gate"], "overridable": outcome == "review"}}


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def platform():
    p = EvalPlatform(Repository("sqlite://"))
    bootstrap(p)
    yield p
    p.repo.close()


@pytest.fixture
def authorized(platform: EvalPlatform) -> EvalPlatform:
    for agent_id in (HARDENED, CANDIDATE, NAIVE):
        platform.authorize_security_testing(agent_id=agent_id, approved_by="security-lead",
                                            categories=["prompt_injection", "pii"],
                                            reason="authorized red-team window for tests")
    return platform


@pytest.fixture
def served(authorized: EvalPlatform):
    mcp_server.set_platform(authorized)
    yield authorized
    mcp_server.set_platform(None)


async def run(platform: EvalPlatform, agent_id: str, **kw):
    return await platform.start_run(agent_id=agent_id, suite_id=SUITE[0], suite_version=SUITE[1],
                                    requested_by=kw.pop("requested_by", "alice"), **kw)
