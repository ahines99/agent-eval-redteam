"""Exercise a real MCP stdio server and save a readable synthetic review report."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
import uuid
from pathlib import Path

from mcp import Client, StdioServerParameters

ROOT = Path(__file__).resolve().parents[1]


async def walkthrough(output: Path, container: bool) -> None:
    with tempfile.TemporaryDirectory(prefix="agent-eval-mcp-") as working:
        environment = {**os.environ, "DATABASE_URL": "sqlite:///" + (Path(working) / "demo.db").as_posix()}
        if container:
            server = StdioServerParameters(command="docker", args=["compose", "run", "--rm", "-T", "eval", "serve"],
                                          cwd=ROOT)
        else:
            server = StdioServerParameters(command=sys.executable, args=["-m", "agent_eval_redteam.cli", "serve"],
                                          env=environment, cwd=ROOT)
        transcript = []

        async def call(client, name, **arguments):
            result = await client.call_tool(name, arguments)
            assert not result.is_error, (name, result.content)
            transcript.append({"tool": name, "result": result.structured_content})
            return result.structured_content

        async with Client(server) as client:
            health = await call(client, "healthcheck")
            assert health["status"] == "ok"
            agents = await call(client, "list_agents")
            assert len(agents["agents"]) >= 3
            await call(client, "list_eval_suites")
            runs = []
            for agent in ("support-bot@1.0.0", "support-bot@1.1.0-rc1"):
                await call(client, "authorize_security_testing", agent_id=agent, approved_by="security-reviewer",
                           categories=["prompt_injection", "pii"], reason="Synthetic portfolio walkthrough",
                           expires_in_hours=1)
                runs.append(await call(client, "run_eval_suite", agent_id=agent, suite_id="support-core",
                                       version="1.2.0", requested_by="author", idempotency_key=uuid.uuid4().hex))
            assert runs[0]["release_decision"] == "eligible"
            candidate = runs[1]
            assert candidate["status"] == "needs_review"
            refusal = await client.call_tool("decide_release_gate", {
                "run_id": candidate["run_id"], "approver": "author", "decision": "approve", "reason": "self review"})
            assert refusal.is_error and "separation of duties" in str(refusal.content)
            rejected = await call(client, "decide_release_gate", run_id=candidate["run_id"], approver="reviewer",
                                  decision="reject", reason="The candidate lost citations in ten cases")
            assert rejected["release_decision"] == "rejected"
            report = await client.read_resource(f"runs://{candidate['run_id']}/report")
            report_text = report.contents[0].text
        # A new process must see the run committed by the first process.
        async with Client(server) as client:
            persisted = await call(client, "get_run", run_id=candidate["run_id"])
            assert persisted["release_decision"] == "rejected"
        output.mkdir(parents=True, exist_ok=True)
        (output / "report.md").write_text(report_text, encoding="utf-8")
        (output / "transcript.json").write_text(json.dumps(transcript, indent=2) + "\n", encoding="utf-8")
        print(f"Verified MCP evaluation, policy refusal, review and process restart: {output}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("data/mcp-walkthrough"))
    parser.add_argument("--container", action="store_true", help="use Docker Compose stdio and its persistent volume")
    args = parser.parse_args()
    asyncio.run(walkthrough(args.output_dir, args.container))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
