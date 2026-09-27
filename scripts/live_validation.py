"""Explicitly opted-in, budget-reserved synthetic Claude validation; no calls by default."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sqlite3
from contextlib import closing
from decimal import Decimal
from importlib.resources import files
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from agent_eval_redteam.adapters.agents import HarnessError
from agent_eval_redteam.adapters.claude_agent import ClaudeAgent
from agent_eval_redteam.adapters.repositories import Repository
from agent_eval_redteam.domain.project_models import AgentSpec, EvalSuite
from agent_eval_redteam.domain.services import EvalPlatform

MODEL = "claude-sonnet-5"
MAX_OUTPUT = 4096
INPUT_MICRODOLLARS = 2
OUTPUT_MICRODOLLARS = 10
CASE_IDS = (
    "fact-return-window", "cite-final-sale", "tool-order-status", "tool-email-policy",
    "perm-refund-request", "inj-kb-exfiltration", "inj-direct-override",
    "pii-ssn-request", "pii-third-party-export", "missing-order-id",
)


class BudgetRefused(HarnessError):
    """No paid request is allowed after this local preflight failure."""


def dollars_to_micros(value: str | Decimal) -> int:
    amount = Decimal(value)
    if not amount.is_finite() or not Decimal(0) < amount <= Decimal(20):
        raise ValueError("budget must be greater than zero and at most $20")
    return int(amount * 1_000_000)


class Ledger:
    """SQLite transactions serialize competing reservations before network transmission.

    Reservations are never refunded, including failed or cancelled requests. Existing
    ledgers can be read/reopened; their persisted budget cannot be raised by a new caller.
    """

    def __init__(self, path: Path, budget_micros: int) -> None:
        self.path = path
        if not 0 < budget_micros <= 20_000_000:
            raise ValueError("invalid budget")
        with closing(self._connect()) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY, budget INTEGER)")
            db.execute("INSERT OR IGNORE INTO settings VALUES (1, ?)", (budget_micros,))
            if db.execute("SELECT budget FROM settings WHERE id=1").fetchone()[0] != budget_micros:
                raise BudgetRefused("persisted budget differs; it cannot be reset or raised")
            db.execute("""CREATE TABLE IF NOT EXISTS requests (
                id INTEGER PRIMARY KEY, reserved INTEGER NOT NULL, counted_input INTEGER NOT NULL,
                state TEXT NOT NULL, input_tokens INTEGER, output_tokens INTEGER,
                actual_micros INTEGER, error_kind TEXT, response_model TEXT, response_id TEXT)""")

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=30)
        db.execute("PRAGMA synchronous=FULL")
        return db

    def reserve(self, amount: int, counted_input: int) -> int:
        if amount <= 0 or counted_input < 0:
            raise BudgetRefused("invalid reservation")
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            budget = db.execute("SELECT budget FROM settings WHERE id=1").fetchone()[0]
            spent = db.execute("SELECT COALESCE(SUM(reserved),0) FROM requests").fetchone()[0]
            if spent + amount > budget:
                raise BudgetRefused("remaining reserved request budget is insufficient")
            cursor = db.execute("INSERT INTO requests(reserved,counted_input,state) VALUES (?,?,'reserved')",
                                (amount, counted_input))
            assert cursor.lastrowid is not None
            return cursor.lastrowid

    def record(self, request_id: int, *, input_tokens: int | None = None,
               output_tokens: int | None = None, error_kind: str | None = None,
               response_model: str | None = None, response_id: str | None = None) -> None:
        actual = None
        if input_tokens is not None and output_tokens is not None:
            actual = input_tokens * INPUT_MICRODOLLARS + output_tokens * OUTPUT_MICRODOLLARS
        with closing(self._connect()) as db, db:
            db.execute("UPDATE requests SET state=?,input_tokens=?,output_tokens=?,actual_micros=?,error_kind=?, "
                       "response_model=?,response_id=? "
                       "WHERE id=?", ("ambiguous" if error_kind else "completed", input_tokens, output_tokens,
                                     actual, error_kind, response_model, response_id, request_id))

    def snapshot(self) -> dict[str, Any]:
        with closing(self._connect()) as db, db:
            db.row_factory = sqlite3.Row
            rows = [dict(row) for row in db.execute("SELECT * FROM requests ORDER BY id")]
            budget = db.execute("SELECT budget FROM settings WHERE id=1").fetchone()[0]
        return {"budget_usd": budget / 1_000_000,
                "reserved_usd": sum(row["reserved"] for row in rows) / 1_000_000,
                "known_usage_cost_usd": sum(row["actual_micros"] or 0 for row in rows) / 1_000_000,
                "requests": rows}


class BudgetedMessages:
    def __init__(self, messages: Any, ledger: Ledger) -> None:
        self.messages = messages
        self.ledger = ledger
        self.stopped = False
        # Serialize the whole request: no in-flight call can escape an accounting anomaly.
        self.lock = asyncio.Lock()

    async def create(self, **kwargs: Any) -> Any:
        async with self.lock:
            if self.stopped:
                raise BudgetRefused("live validation stopped after an earlier request failure")
            allowed = {"model", "max_tokens", "system", "tools", "messages", "output_config"}
            if set(kwargs) - allowed or kwargs.get("model") != MODEL:
                raise BudgetRefused("unpriced model or request feature")
            request = {**kwargs, "max_tokens": min(int(kwargs["max_tokens"]), MAX_OUTPUT)}
            if request["max_tokens"] <= 0:
                raise BudgetRefused("invalid output token bound")
            # Exact adapter requests are text-only, uncached, standard-rate requests.
            def dump(value: Any) -> Any:
                if hasattr(value, "model_dump"):
                    return value.model_dump(mode="json")
                raise TypeError("unsupported request object")
            serialized = json.dumps(request, default=dump)
            if any(f'"{key}"' in serialized for key in ("cache_control", "image", "document", "server_tool")):
                raise BudgetRefused("unsupported pricing feature in request")
            counting = {key: value for key, value in request.items() if key != "max_tokens"}
            try:
                counted = await self.messages.count_tokens(**counting)
                if type(counted.input_tokens) is not int or counted.input_tokens < 0:
                    raise BudgetRefused("invalid token count")
                # Count tokens is an estimate. Reserve generous text/serialization headroom as well.
                input_bound = max(counted.input_tokens * 2, len(serialized.encode("utf-8")) * 2) + 4096
                reserve = input_bound * INPUT_MICRODOLLARS + request["max_tokens"] * OUTPUT_MICRODOLLARS
                request_id = self.ledger.reserve(reserve, counted.input_tokens)
            except Exception as exc:
                self.stopped = True
                raise BudgetRefused(f"preflight refused: {type(exc).__name__}") from None
            try:
                response = await self.messages.create(**request)
                usage = response.usage
                if (type(usage.input_tokens) is not int or type(usage.output_tokens) is not int
                        or usage.input_tokens < 0 or usage.output_tokens < 0
                        or getattr(usage, "cache_creation_input_tokens", 0)
                        or getattr(usage, "cache_read_input_tokens", 0)
                        or usage.input_tokens > input_bound or usage.output_tokens > request["max_tokens"]):
                    raise BudgetRefused("provider usage exceeded priced request bounds; stop and inspect billing")
                self.ledger.record(request_id, input_tokens=usage.input_tokens, output_tokens=usage.output_tokens,
                                   response_model=getattr(response, "model", None),
                                   response_id=getattr(response, "id", None))
                return response
            except BaseException as exc:
                self.stopped = True
                self.ledger.record(request_id, error_kind=type(exc).__name__)
                if isinstance(exc, asyncio.CancelledError):
                    raise
                raise BudgetRefused(f"request stopped: {type(exc).__name__}; reservation retained") from None


def validation_suite() -> EvalSuite:
    source = files("agent_eval_redteam.fixtures").joinpath("suites/support-core.v1.2.0.json").read_text()
    suite = EvalSuite.model_validate_json(source)
    selected = [suite.case(case_id) for case_id in CASE_IDS]
    failures = [plan for plan in suite.failure_plans if plan.case_id in {"tool-order-status"}]
    return suite.model_copy(update={"suite_id": "live-validation", "version": "1.0.0", "repeats": 1,
                                    "cases": selected, "failure_plans": failures,
                                    "description": "Ten synthetic portfolio cases; one repeat and order failure probe"})


async def execute(output: Path, budget_micros: int) -> dict[str, Any]:
    from anthropic import AsyncAnthropic

    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise ValueError("ANTHROPIC_API_KEY must be set securely in the environment")
    output.mkdir(parents=True, exist_ok=False)
    ledger = Ledger(output / "budget.db", budget_micros)
    suite = validation_suite()
    (output / "suite.json").write_text(suite.model_dump_json(indent=2), encoding="utf-8")
    client = AsyncAnthropic(max_retries=0, timeout=60, base_url="https://api.anthropic.com")
    guarded = SimpleNamespace(messages=BudgetedMessages(client.messages, ledger))
    repo = Repository(f"sqlite:///{(output / 'evaluation.db').resolve().as_posix()}")
    platform = EvalPlatform(repo, adapter_factory=lambda record: ClaudeAgent(record.config, client=guarded))
    report: dict[str, Any] = {"provider": "Anthropic", "model": MODEL, "max_tokens_per_request": MAX_OUTPUT,
                              "max_turns": 6, "effort": "low", "sdk_max_retries": 0,
                              "pricing_usd_per_million": {"input": 2, "output": 10},
                              "pricing_source": "https://platform.claude.com/docs/en/about-claude/pricing",
                              "pricing_verified_date": "2026-09-27", "suite_hash": suite.content_hash(),
                              "suite_file_sha256": hashlib.sha256((output / "suite.json").read_bytes()).hexdigest(),
                              "live_execution": True, "model_pass_required": False}
    try:
        platform.register_suite(suite, "live-reviewer")
        agent = platform.register_agent(AgentSpec(name="live-sonnet-validation", version="1.0.0",
                                                  adapter="claude", owner="live-reviewer",
                                                  config={"model": MODEL, "effort": "low", "max_turns": 6}))
        platform.authorize_security_testing(agent_id=agent.agent_id, approved_by="live-security-reviewer",
                                            categories=["prompt_injection", "pii"],
                                            reason="Authorized synthetic portfolio validation; no external tools")
        try:
            summary = await platform.start_run(agent_id=agent.agent_id, suite_id=suite.suite_id,
                                                suite_version=suite.version, requested_by="live-reviewer",
                                                idempotency_key="live-validation-once")
            report["summary"] = summary.model_dump(mode="json")
            if summary.scorecard is None:
                report["error_kind"] = "IncompleteEvaluation"
        except Exception as exc:
            report["error_kind"] = type(exc).__name__
        runs = repo.runs_for_agent(agent.agent_id)
        if runs:
            run_id = runs[0]["run_id"]
            report["run_id"] = run_id
            report["traces"] = [trace.model_dump(mode="json") for trace in repo.traces_for(run_id)]
            (output / "run-report.md").write_text(platform.run_report(run_id), encoding="utf-8")
        return report
    finally:
        report["budget"] = ledger.snapshot()
        (output / "result.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        await client.close()
        repo.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="explicit opt-in to paid requests")
    parser.add_argument("--max-usd", default="5", help="reservation ceiling, >0 and <=20")
    parser.add_argument("--output", type=Path, default=Path("data/live-validation"))
    args = parser.parse_args()
    budget = dollars_to_micros(args.max_usd)
    if not args.execute:
        print(json.dumps({"execute": False, "model": MODEL, "budget_usd": budget / 1_000_000,
                          "cases": CASE_IDS, "failure_probes": len(validation_suite().failure_plans)}))
        return 0
    if args.output.exists():
        parser.error("output already exists; evidence and budget cannot be overwritten")
    try:
        report = asyncio.run(execute(args.output, budget))
    except Exception as exc:
        print(f"Live validation stopped: {type(exc).__name__}; inspect local evidence if created.")
        return 1
    print(json.dumps({"output": str(args.output), "budget": report["budget"],
                      "error_kind": report.get("error_kind")}))
    return 1 if report.get("error_kind") else 0


if __name__ == "__main__":
    raise SystemExit(main())
