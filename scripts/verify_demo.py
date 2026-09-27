"""Assert persisted control outcomes; usable from source, wheel and container."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from agent_eval_redteam import __version__
from agent_eval_redteam.adapters.repositories import Repository
from agent_eval_redteam.cli import SUITE
from agent_eval_redteam.domain.policies import PolicyViolation
from agent_eval_redteam.domain.services import EvalPlatform


async def verify(url: str) -> tuple[dict, str]:
    repo = Repository(url)
    try:
        platform = EvalPlatform(repo)
        controls = []
        for suffix, expected, passed, critical in (
            ("v1.0.0", "eligible", 35, 0),
            ("v1.1.0-rc1", "rejected", 25, 0),
            ("v0.9.0", "blocked", 1, 17),
        ):
            row = repo.run_by_idempotency_key(f"demo-{SUITE[1]}-{suffix}")
            assert row is not None, f"Missing demo run {suffix}"
            run = platform.get_run(row["run_id"])
            assert run.status == "complete", run
            assert run.release_decision == expected, run
            assert run.scorecard is not None
            assert run.scorecard["n_cases"] == 35, run.scorecard
            assert run.scorecard["n_passed"] == passed, run.scorecard
            assert run.scorecard["critical_failures"] == critical, run.scorecard
            assert all(step.done for step in run.steps)
            controls.append(run.model_dump(mode="json"))
        good, candidate, bad = controls
        assert candidate["comparison"]["baseline_run_id"] == good["run_id"]
        assert candidate["regression_alerts"]
        refusals = {}
        for label, run_id, actor, expected in (
            ("self_approval", candidate["run_id"], "alice", "separation of duties"),
            ("critical_override", bad["run_id"], "reviewer", "cannot be overridden"),
        ):
            try:
                await platform.decide_gate(run_id=run_id, approver=actor, decision="approve", reason="smoke check")
            except PolicyViolation as exc:
                assert expected in str(exc), str(exc)
                refusals[label] = True
            else:
                raise AssertionError(f"Expected policy refusal: {label}")
        recovery = await platform.inject_failure(run_id=good["run_id"], case_id="tool-order-eta",
                                                tool="get_order_status", failure_type="timeout",
                                                requested_by="smoke-reviewer")
        assert recovery.passed and recovery.dimensions["recovery"].passed
        findings = platform.get_findings(candidate["run_id"])
        assert findings and findings[0].evidence
        example = platform.get_trace(findings[0].evidence[0].uri.removeprefix("trace://"))
        assert example["integrity_ok"]
        identity = platform.get_artifact(good["run_id"], "Score traces")["payload"]["evaluation_identity"]
        return {"version": __version__, "suite": f"{SUITE[0]}@{SUITE[1]}", "controls": controls,
                "evaluation_identity": identity, "refusals": refusals,
                "recovery": recovery.model_dump(mode="json"),
                "example_finding": findings[0].model_dump(mode="json"), "example_trace": example,
                "measurement_note": "Synthetic scripted controls; token costs are simulated, not provider billing."}, (
                    platform.run_report(candidate["run_id"]))
    finally:
        repo.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    results, report = asyncio.run(verify(args.db))
    if args.output_dir:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        (args.output_dir / "controls.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
        (args.output_dir / "candidate-report.md").write_text(report + "\n", encoding="utf-8")
    print("Verified 35/35 eligible, 25/35 rejected, 1/35 blocked; policy refusals, recovery and trace integrity.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
