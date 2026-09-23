"""Command line: `agent-eval demo` (offline end-to-end demo) and `agent-eval serve` (MCP server)."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

from .adapters.repositories import Repository
from .domain.services import EvalPlatform, RunSummary, bootstrap

SUITE = ("support-core", "1.0.0")


def _line(s: RunSummary) -> str:
    c = s.scorecard or {}
    rate = f"{c['pass_rate']:.2f}" if c else "-"
    critical = str(c.get("critical_failures", "-"))
    gate = s.gate.outcome.value if s.gate else "-"
    return (f"{s.agent_id:<24} status={s.status:<13} pass_rate={rate:<5} critical={critical:<3} gate={gate:<7} "
            f"decision={s.release_decision}")


async def demo(db_url: str) -> int:
    platform = EvalPlatform(Repository(db_url))
    try:
        return await _demo(platform)
    finally:
        platform.repo.close()


async def _demo(platform: EvalPlatform) -> int:
    bootstrap(platform)
    print("Seeded suite support-core@1.0.0 (31 cases, 5 failure plans) and three reference agents.\n")

    agents = ["support-bot@1.0.0", "support-bot@1.1.0-rc1", "support-bot-naive@0.9.0"]
    for agent_id in agents:
        platform.authorize_security_testing(agent_id=agent_id, approved_by="security-lead",
                                            categories=["prompt_injection", "pii"],
                                            reason="Scheduled red-team window for the support bot release")

    print("1) Successful path: hardened reference agent")
    good = await platform.start_run(agent_id=agents[0], suite_id=SUITE[0], suite_version=SUITE[1],
                                    requested_by="alice", idempotency_key="demo-v1.0.0")
    print("   " + _line(good))

    print("\n2) Review path: release candidate with flaky citations, compared against 1.0.0")
    rc = await platform.start_run(agent_id=agents[1], suite_id=SUITE[0], suite_version=SUITE[1],
                                  requested_by="alice", idempotency_key="demo-v1.1.0-rc1")
    print("   " + _line(rc))
    for reason in rc.gate.reasons if rc.gate else []:
        print(f"   gate: {reason}")
    try:
        await platform.decide_gate(run_id=rc.run_id, approver="alice", decision="approve", reason="looks fine to me")
    except Exception as exc:  # noqa: BLE001 - demo prints the refusal
        print(f"   refused: {exc}")
    rc = await platform.decide_gate(run_id=rc.run_id, approver="bob", decision="reject",
                                    reason="Citation regressions on 10 cases; fix before release")
    print("   after human review: " + _line(rc))

    print("\n3) Controlled failure path: naive agent")
    bad = await platform.start_run(agent_id=agents[2], suite_id=SUITE[0], suite_version=SUITE[1],
                                   requested_by="alice", idempotency_key="demo-v0.9.0")
    print("   " + _line(bad))
    for f in platform.get_findings(bad.run_id, "critical")[:5]:
        print(f"   critical: {f.statement}  (evidence {f.evidence[0].evidence_id[:8]})")
    try:
        await platform.decide_gate(run_id=bad.run_id, approver="bob", decision="approve", reason="ship it anyway")
    except Exception as exc:  # noqa: BLE001
        print(f"   override refused: {exc}")

    print("\n4) Ad-hoc failure injection on the hardened agent (timeout on order lookup)")
    score = await platform.inject_failure(run_id=good.run_id, case_id="tool-order-eta", tool="get_order_status",
                                          failure_type="timeout", requested_by="alice")
    print(f"   passed={score.passed} recovery: {score.dimensions['recovery'].detail}")

    report = platform.regression_report("support-bot", SUITE[0])
    print(f"\n5) Regression monitor for support-bot: {[r['pass_rate'] for r in report['runs']]}")
    for alert in report["alerts"]:
        print(f"   alert: {alert}")
    print("\n6) Report for the release candidate (also served as MCP resource runs://<run_id>/report)\n")
    print(platform.run_report(rc.run_id))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent-eval")
    sub = parser.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("demo", help="run the offline end-to-end demo")
    d.add_argument("--db", default="sqlite://", help="database URL (default: in-memory)")
    s = sub.add_parser("serve", help="run the MCP server")
    s.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    r = sub.add_parser("report", help="print a run report")
    r.add_argument("run_id")
    r.add_argument("--db", default=os.environ.get("DATABASE_URL", "sqlite:///./data/agent_eval.db"))
    args = parser.parse_args(argv)

    if args.cmd == "demo":
        return asyncio.run(demo(args.db))
    if args.cmd == "report":
        repo = Repository(args.db)
        try:
            print(EvalPlatform(repo).run_report(args.run_id))
        finally:
            repo.close()
        return 0
    from .mcp_server import get_platform, mcp

    get_platform()  # create the schema and seed bundled suites/agents before serving
    mcp.run(transport=args.transport)
    return 0


if __name__ == "__main__":
    sys.exit(main())
