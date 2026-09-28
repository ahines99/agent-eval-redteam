"""Execute the SQL-domain controls through the persistent release workflow, without model APIs."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from agent_eval_redteam.adapters.repositories import Repository
from agent_eval_redteam.adapters.sql_domain import DOMAIN_VERSION, fixture_hash, sql_suite
from agent_eval_redteam.domain.models import canonical_hash
from agent_eval_redteam.domain.project_models import AgentSpec
from agent_eval_redteam.domain.services import EvalPlatform


async def walkthrough(output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    repo = Repository("sqlite:///" + (output / "evaluation.db").resolve().as_posix())
    try:
        platform = EvalPlatform(repo)
        suite = sql_suite()
        platform.register_suite(suite, "sql-author")
        controls = []
        traces = []
        for preset, version, expected in [("hardened", "1.0.0", "eligible"),
                                           ("flawed", "1.1.0", "rejected"),
                                           ("unsafe", "0.9.0", "blocked")]:
            agent = platform.register_agent(AgentSpec(name="sql-control", version=version,
                adapter="scripted", owner="sql-author", config={"domain": "sql", "sql_preset": preset,
                "sql_version": DOMAIN_VERSION, "sql_fixture_sha256": fixture_hash()}))
            platform.authorize_security_testing(agent_id=agent.agent_id, approved_by="sql-security",
                categories=["prompt_injection", "pii"], reason="Synthetic SQL fixture and injection controls")
            run = await platform.start_run(agent_id=agent.agent_id, suite_id=suite.suite_id,
                suite_version=suite.version, requested_by="sql-author", idempotency_key="sql-" + preset)
            if run.release_decision == "awaiting_review":
                run = await platform.decide_gate(run_id=run.run_id, approver="sql-reviewer", decision="reject",
                                                reason="Preserved SQL result regression in flawed control")
            assert run.release_decision == expected, run.model_dump()
            controls.append({"preset": preset, **run.model_dump(mode="json")})
            traces.extend(t.model_dump(mode="json") for t in repo.traces_for(run.run_id))
            (output / f"{preset}-report.md").write_text(platform.run_report(run.run_id), encoding="utf-8")
        result = {"schema_version": 1, "domain_version": DOMAIN_VERSION, "fixture_sha256": fixture_hash(),
                  "suite": suite.model_dump(mode="json"), "controls": controls, "traces": traces,
                  "trace_hashes": {t["trace_id"]: canonical_hash(t) for t in traces},
                  "scope": ("Actual disposable SQLite queries and persistent platform workflow; scripted plans, "
                            "no text-to-SQL model quality or external data claim.")}
        (output / "controls.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        return result
    finally:
        repo.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("data/sql-walkthrough"))
    args = parser.parse_args()
    result = asyncio.run(walkthrough(args.output_dir))
    print(json.dumps([{key: c[key] for key in ("preset", "release_decision", "scorecard")}
                      for c in result["controls"]], indent=2))


if __name__ == "__main__":
    main()
