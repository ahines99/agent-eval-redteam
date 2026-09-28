"""Predeclared repeated two-model experiment. Dry run by default; never resets its budget."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import random
import sqlite3
import subprocess
import time
from collections import defaultdict
from contextlib import closing
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from types import SimpleNamespace
from typing import Any

from live_validation import MAX_OUTPUT, BudgetedMessages, BudgetRefused, Ledger, validation_suite

from agent_eval_redteam.adapters.claude_agent import DEFAULT_SYSTEM_PROMPT, ClaudeAgent, ClaudeConfig
from agent_eval_redteam.adapters.repositories import Repository, canonical_hash
from agent_eval_redteam.adapters.sandbox import Sandbox, load_world
from agent_eval_redteam.domain.policies import GATE_POLICY_VERSION
from agent_eval_redteam.domain.project_models import AgentSpec, EvalSuite, FailurePlan
from agent_eval_redteam.domain.scoring import SCORING_VERSION, score_trace
from agent_eval_redteam.domain.services import EvalPlatform

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "benchmarks/live-experiment.v1.json"
FROZEN_MANIFEST = "benchmarks/live-experiment.v1.freeze.json"
INVOCATION: ContextVar[dict[str, Any] | None] = ContextVar("live_invocation", default=None)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*arguments: str) -> str:
    return subprocess.check_output(["git", *arguments], cwd=ROOT, text=True).strip()


def source_files() -> dict[str, str]:
    """Git object identities bind all runtime source and every direct study input."""
    fixed = {"scripts/live_experiment.py", "scripts/live_validation.py", "benchmarks/live-experiment.v1.json",
             "uv.lock", "pyproject.toml"}
    result = {}
    for line in git("ls-tree", "-r", "HEAD").splitlines():
        identity, path = line.split("\t", 1)
        if path.startswith("src/") or path in fixed:
            result[path] = identity.split()[2]
    if not fixed.issubset(result):
        raise ValueError("study sources and inputs must all be tracked in Git")
    return result


def configuration(path: Path = CONFIG) -> dict[str, Any]:
    config = json.loads(path.read_text(encoding="utf-8"))
    expected = [("claude-sonnet-5", "low", 2, 10), ("claude-haiku-4-5-20251001", None, 1, 5)]
    actual = [(m["id"], m["effort"], m["input_micros_per_token"], m["output_micros_per_token"])
              for m in config["models"]]
    if actual != expected or config["rounds"] != 3 or config["case_concurrency"] != 1:
        raise ValueError("this runner only supports the predeclared two-model, three-round profile")
    if (config["cumulative_reservation_micros"] != 12_000_000 or config["max_turns"] != 6
            or config["max_output_tokens"] != MAX_OUTPUT or config["sdk_max_retries"] != 0
            or config["prior_ledger"] != "data/live-validation/budget.db"
            or config["campaign_ledger"] != "data/live-study-budget.db"):
        raise ValueError("unsupported budget, storage, or request profile")
    return config


def study_suite(config: dict[str, Any]) -> EvalSuite:
    original = validation_suite()
    if config["case_ids"] != [case.case_id for case in original.cases]:
        raise ValueError("case selection differs from the frozen ten-case plan")
    if config["failure_probes"] != [{"case_id": "tool-order-status", "tool": "get_order_status",
                                     "failure_type": kind} for kind in ("timeout", "malformed")]:
        raise ValueError("failure probes differ from the frozen plan")
    return EvalSuite.model_validate({**original.model_dump(mode="json"), "suite_id": "live-comparison",
                                    "version": "1.0.0", "repeats": 1,
                                    "description": "Repeated two-model support study; original gate budgets",
                                    "failure_plans": [FailurePlan.model_validate(p).model_dump(mode="json")
                                                      for p in config["failure_probes"]]})


def history(path: Path, config: dict[str, Any]) -> dict[str, Any]:
    if not path.is_file():
        raise BudgetRefused("original accounting is required; no fresh allowance can be substituted")
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        rows, reserved, usage = db.execute(
            "SELECT COUNT(*), COALESCE(SUM(reserved),0), COALESCE(SUM(actual_micros),0) FROM requests"
        ).fetchone()
        states = db.execute("SELECT DISTINCT state FROM requests").fetchall()
    if (rows != config["expected_prior_completed_requests"]
            or reserved != config["expected_prior_reserved_micros"]
            or usage != config["expected_prior_usage_micros"] or states != [("completed",)]):
        raise BudgetRefused("prior accounting differs from the authorized historical snapshot")
    return {"ledger_sha256": sha(path), "reserved_micros": reserved, "known_usage_micros": usage,
            "completed_requests": rows}


def freeze(output: Path, config: dict[str, Any]) -> dict[str, Any]:
    if git("status", "--porcelain"):
        raise ValueError("commit the study inputs and implementation before freezing")
    suite = study_suite(config)
    manifest = {"schema_version": 1, "frozen_at": datetime.now(UTC).isoformat(),
                "source_commit": git("rev-parse", "HEAD"), "source_tree": git("rev-parse", "HEAD^{tree}"),
                "source_files": source_files(), "committed_manifest": FROZEN_MANIFEST,
                "lock_sha256": sha(ROOT / "uv.lock"), "config": config, "config_hash": canonical_hash(config),
                "suite": suite.model_dump(mode="json"), "suite_hash": suite.content_hash(),
                "system_prompt": DEFAULT_SYSTEM_PROMPT, "system_prompt_hash": canonical_hash(DEFAULT_SYSTEM_PROMPT),
                "tools": Sandbox().tool_definitions(), "world_hash": canonical_hash(load_world()),
                "scoring_version": SCORING_VERSION, "gate_policy_version": GATE_POLICY_VERSION,
                "prior_accounting": history(ROOT / config["prior_ledger"], config),
                "planned_invocations": 72, "sampling_seed": None,
                "analysis_seed": 20260928, "provider_origin": "https://api.anthropic.com"}
    manifest["manifest_hash"] = canonical_hash(manifest)
    target = ROOT / FROZEN_MANIFEST
    if target.exists():
        raise FileExistsError("the predeclared study manifest already exists; do not overwrite it")
    output.mkdir(parents=True, exist_ok=False)
    encoded = json.dumps(manifest, indent=2) + "\n"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(encoded, encoding="utf-8")
    (output / "manifest.json").write_text(encoded, encoding="utf-8")
    return manifest


def validate_manifest(manifest: dict[str, Any], config: dict[str, Any]) -> None:
    body = {k: v for k, v in manifest.items() if k != "manifest_hash"}
    if canonical_hash(body) != manifest["manifest_hash"]:
        raise ValueError("frozen manifest hash mismatch")
    if (manifest["config"] != config or manifest["config_hash"] != canonical_hash(config)
            or manifest["source_commit"] != git("merge-base", manifest["source_commit"], "HEAD")
            or manifest["source_files"] != source_files() or git("status", "--porcelain")
            or manifest["committed_manifest"] != FROZEN_MANIFEST
            or json.loads(git("show", "HEAD:" + FROZEN_MANIFEST)) != manifest
            or manifest["lock_sha256"] != sha(ROOT / "uv.lock")
            or manifest["suite_hash"] != study_suite(config).content_hash()
            or manifest["suite"] != study_suite(config).model_dump(mode="json")
            or manifest["system_prompt"] != DEFAULT_SYSTEM_PROMPT
            or manifest["tools"] != Sandbox().tool_definitions()
            or manifest["world_hash"] != canonical_hash(load_world())
            or manifest["scoring_version"] != SCORING_VERSION
            or manifest["gate_policy_version"] != GATE_POLICY_VERSION
            or manifest["prior_accounting"] != history(ROOT / config["prior_ledger"], config)):
        raise ValueError("source, inputs, pricing, or prior accounting drifted after freeze")


class CampaignLedger(Ledger):
    """One durable campaign, with the prior reservations charged once and no automatic restart."""

    def __init__(self, path: Path, manifest: dict[str, Any]) -> None:
        prior = manifest["prior_accounting"]
        super().__init__(path, manifest["config"]["cumulative_reservation_micros"])
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("CREATE TABLE IF NOT EXISTS campaign (id INTEGER PRIMARY KEY, manifest TEXT, state TEXT)")
            row = db.execute("SELECT manifest FROM campaign WHERE id=1").fetchone()
            if row and row[0] != manifest["manifest_hash"]:
                raise BudgetRefused("the shared campaign ledger is bound to another frozen manifest")
            if not row:
                if db.execute("SELECT COUNT(*) FROM requests").fetchone()[0]:
                    raise BudgetRefused("cannot attach a campaign to unrelated accounting")
                db.execute("INSERT INTO campaign VALUES (1, ?, 'prepared')", (manifest["manifest_hash"],))
                db.execute("INSERT INTO requests(reserved,counted_input,state,actual_micros,response_model) "
                           "VALUES (?,0,'historical',?,'prior-sonnet-experiment')",
                           (prior["reserved_micros"], prior["known_usage_micros"]))

    def claim(self) -> None:
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT state FROM campaign WHERE id=1").fetchone()[0] != "prepared":
                raise BudgetRefused("campaign already started; inspect preserved results, do not restart paid calls")
            db.execute("UPDATE campaign SET state='running' WHERE id=1")

    def reserve(self, amount: int, counted_input: int) -> int:
        if amount <= 0 or counted_input < 0:
            raise BudgetRefused("invalid reservation")
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT state FROM campaign WHERE id=1").fetchone()[0] != "running":
                raise BudgetRefused("campaign is not running")
            if db.execute("SELECT COUNT(*) FROM requests WHERE state IN ('reserved','ambiguous')").fetchone()[0]:
                raise BudgetRefused("unresolved paid request; further transmission refused")
            budget = db.execute("SELECT budget FROM settings WHERE id=1").fetchone()[0]
            spent = db.execute("SELECT COALESCE(SUM(reserved),0) FROM requests").fetchone()[0]
            if spent + amount > budget:
                raise BudgetRefused("cumulative historical plus campaign reservation ceiling reached")
            cursor = db.execute("INSERT INTO requests(reserved,counted_input,state) VALUES (?,?,'reserved')",
                                (amount, counted_input))
            assert cursor.lastrowid is not None
            return cursor.lastrowid

    def finish(self, complete: bool) -> None:
        with closing(self._connect()) as db, db:
            db.execute("UPDATE campaign SET state=? WHERE id=1", ("complete" if complete else "incomplete",))


class MeasuredAgent(ClaudeAgent):
    def __init__(self, config: dict[str, Any], *, client: Any, suite: EvalSuite,
                 records: list[dict[str, Any]], round_number: int) -> None:
        super().__init__(config, client=client)
        self.suite, self.records, self.round_number = suite, records, round_number

    async def run(self, prompt: str, sandbox: Sandbox, *, repeat: int) -> Any:
        case = next(case for case in self.suite.cases if case.prompt == prompt)
        failure = sandbox.failure
        record = {"model": self.model, "round": self.round_number, "case_id": case.case_id,
                  "phase": "injected" if failure else "baseline", "repeat": repeat,
                  "failure_type": failure.failure_type.value if failure else None, "requests": []}
        token = INVOCATION.set(record)
        started = time.perf_counter()
        try:
            result = await super().run(prompt, sandbox, repeat=repeat)
            record.update(status="completed", stop_reason=result.stop_reason,
                          input_tokens=result.input_tokens, output_tokens=result.output_tokens)
            return result
        except BaseException as exc:
            record.update(status="incomplete", error_kind=type(exc).__name__)
            raise
        finally:
            record["end_to_end_ms"] = (time.perf_counter() - started) * 1000
            record["failure_triggered"] = bool(failure and any(call.injected for call in sandbox.calls))
            self.records.append(record)
            INVOCATION.reset(token)


def observe_request(record: dict[str, Any]) -> None:
    invocation = INVOCATION.get()
    if invocation is None:
        raise BudgetRefused("paid request lacks invocation attribution")
    invocation["requests"].append(record)


def summarize(runs: list[dict[str, Any]], models: list[str]) -> dict[str, Any]:
    """Resample cases together across models/rounds; repetitions are not independent cases."""
    outcomes: dict[str, dict[str, list[int]]] = {model: defaultdict(list) for model in models}
    by_model: dict[str, Any] = {}
    for model in models:
        selected = [run for run in runs if run["model"] == model]
        baseline = [score for run in selected for score in run["scores"] if score["phase"] == "baseline"]
        for score in baseline:
            outcomes[model][score["case_id"]].append(int(score["passed"]))
        dimensions: dict[str, list[bool]] = defaultdict(list)
        for run in selected:
            for score in run["scores"]:
                for name, dimension in score["dimensions"].items():
                    if dimension["applicable"]:
                        dimensions[name].append(dimension["passed"])
        by_model[model] = {"scored_baseline_observations": len(baseline),
                           "passed_baseline_observations": sum(score["passed"] for score in baseline),
                           "per_case_repeated_outcomes": dict(outcomes[model]),
                           "dimensions": {name: {"passed": sum(values), "applicable": len(values)}
                                          for name, values in sorted(dimensions.items())}}
    cases = sorted(set(outcomes[models[0]]) & set(outcomes[models[1]]))
    # Refuse a seemingly precise comparison when a round/case is missing or unscored.
    complete = len(cases) == 10 and all(len(outcomes[m][case]) == 3 for m in models for case in cases)
    comparison: dict[str, Any] = {"available": complete, "unit": "paired case cluster across three rounds",
                                  "limitations": "Exploratory fixed synthetic sample; not population accuracy"}
    if complete:
        deltas = [mean(outcomes[models[0]][case]) - mean(outcomes[models[1]][case]) for case in cases]
        generator = random.Random(20260928)
        samples = sorted(mean(generator.choices(deltas, k=len(deltas))) for _ in range(2000))
        comparison.update(model_difference=f"{models[0]} minus {models[1]}", mean_delta=mean(deltas),
                          case_cluster_bootstrap_ci95=[samples[49], samples[1949]],
                          distinct_cases=10, resamples=2000, analysis_seed=20260928)
    return {"by_model": by_model, "paired_comparison": comparison}


def safe_budget(ledger: Ledger) -> dict[str, Any]:
    snapshot = ledger.snapshot()
    for request in snapshot["requests"]:
        request.pop("response_id", None)
    return snapshot


def completeness(config: dict[str, Any], records: list[dict[str, Any]],
                 runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    slots = []
    for round_number in range(1, 4):
        ordering = config["models"] if round_number % 2 else list(reversed(config["models"]))
        for model in ordering:
            cases = [(case_id, "baseline", None) for case_id in config["case_ids"]]
            cases += [(plan["case_id"], "injected", plan["failure_type"]) for plan in config["failure_probes"]]
            for case_id, phase, failure in cases:
                found = [row for row in records if row["model"] == model["id"] and row["round"] == round_number
                         and row["case_id"] == case_id and row["phase"] == phase and row["failure_type"] == failure]
                run = next((row for row in runs if row["model"] == model["id"]
                            and row["round"] == round_number), None)
                traces = [] if run is None else [trace for trace in run["traces"] if trace["case_id"] == case_id
                          and trace["phase"] == phase
                          and (trace.get("injected_failure") or {}).get("failure_type") == failure]
                slots.append({"model": model["id"], "round": round_number, "case_id": case_id,
                              "phase": phase, "failure_type": failure,
                              "status": found[0]["status"] if found else "not_started",
                              "failure_triggered": found[0]["failure_triggered"] if found else False,
                              "trace_persisted": len(traces) == 1,
                              "score_available": len(traces) == 1 and run is not None and bool(run["scores"])})
    return slots


def latency_summary(records: list[dict[str, Any]], models: list[str]) -> dict[str, Any]:
    def distribution(values: list[float]) -> dict[str, Any]:
        if not values:
            return {"n": 0, "mean_ms": None, "p50_ms": None, "p95_ms": None}
        ordered = sorted(values)
        return {"n": len(values), "mean_ms": mean(values),
                "p50_ms": ordered[max(0, math.ceil(len(values) * .5) - 1)],
                "p95_ms": ordered[max(0, math.ceil(len(values) * .95) - 1)]}
    output = {}
    for model in models:
        selected = [row for row in records if row["model"] == model]
        requests = [request for row in selected for request in row["requests"]]
        paid = [request for request in requests if "request_id" in request]
        output[model] = {"completed_invocations": sum(row["status"] == "completed" for row in selected),
                         "incomplete_invocations": sum(row["status"] != "completed" for row in selected),
                         "paid_request_attempts": len(paid),
                         "end_to_end": distribution([row["end_to_end_ms"] for row in selected]),
                         "request_components": {key: distribution([row[key] for row in requests])
                                                for key in ("queue_ms", "counting_ms", "reservation_ms",
                                                            "recording_ms", "total_ms")},
                         "paid_provider_http": distribution([row["provider_http_ms"] for row in paid])}
    return output


async def execute(output: Path, manifest: dict[str, Any], *, client: Any = None) -> dict[str, Any]:
    config = configuration()
    validate_manifest(manifest, config)
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise ValueError("ANTHROPIC_API_KEY must be supplied securely")
    if (output / "result.json").exists() or (output / "evaluation.db").exists():
        raise ValueError("study output already contains execution evidence")
    ledger = CampaignLedger(ROOT / config["campaign_ledger"], manifest)
    ledger.claim()
    if client is None:
        from anthropic import AsyncAnthropic
        client = AsyncAnthropic(max_retries=0, timeout=60, base_url="https://api.anthropic.com")
    suite = study_suite(config)
    repo = Repository("sqlite:///" + (output / "evaluation.db").resolve().as_posix())
    records: list[dict[str, Any]] = []
    runs: list[dict[str, Any]] = []
    report: dict[str, Any] = {"manifest_hash": manifest["manifest_hash"], "source_commit": manifest["source_commit"],
                              "manifest_commit": git("rev-parse", "HEAD"),
                              "started_at": datetime.now(UTC).isoformat(), "live_execution": True,
                              "planned_invocations": 72, "models": config["models"], "runs": runs,
                              "invocations": records, "complete": False}
    try:
        stop = False
        for round_number in range(1, 4):
            ordering = config["models"] if round_number % 2 else list(reversed(config["models"]))
            for model in ordering:
                guarded = BudgetedMessages(client.messages, ledger, model=model["id"],
                                           pricing=(model["input_micros_per_token"], model["output_micros_per_token"]),
                                           observer=observe_request, require_response_model=True)
                adapter_client = SimpleNamespace(messages=guarded)
                def factory(agent, adapter_client=adapter_client, round_number=round_number):
                    return MeasuredAgent(agent.config, client=adapter_client, suite=suite,
                                         records=records, round_number=round_number)
                platform = EvalPlatform(repo, adapter_factory=factory)
                platform.env.concurrency = config["case_concurrency"]
                platform.register_suite(suite, "live-study-reviewer")
                agent_config = {"model": model["id"], "effort": model["effort"], "max_turns": config["max_turns"]}
                ClaudeConfig.model_validate(agent_config).request_effort()
                agent = platform.register_agent(AgentSpec(name="study-" + model["id"], version="1.0.0",
                                                          adapter="claude", owner="live-study-reviewer",
                                                          config=agent_config))
                platform.authorize_security_testing(agent_id=agent.agent_id, approved_by="study-security-reviewer",
                                                    categories=["prompt_injection", "pii"],
                                                    reason="Predeclared synthetic repeated experiment")
                run: dict[str, Any] = {"model": model["id"], "round": round_number, "scores": [], "traces": [],
                                       "planned_baseline": 10, "planned_failure_probes": 2}
                runs.append(run)
                try:
                    summary = await platform.start_run(agent_id=agent.agent_id, suite_id=suite.suite_id,
                                                       suite_version=suite.version, requested_by="live-study-reviewer",
                                                       idempotency_key=f"study-round-{round_number}-{model['id']}")
                    run["summary"] = summary.model_dump(mode="json")
                    if summary.scorecard is None:
                        run["error_kind"] = "IncompleteEvaluation"
                        stop = True
                except Exception as exc:
                    run["error_kind"] = type(exc).__name__
                    stop = True
                stored = repo.run_by_idempotency_key(f"study-round-{round_number}-{model['id']}")
                if stored:
                    run_id = stored["run_id"]
                    run["run_id"] = run_id
                    run["traces"] = [trace.model_dump(mode="json") for trace in repo.traces_for(run_id)]
                    run["scores"] = [score_trace(suite.case(trace.case_id), suite, trace,
                                                Sandbox.for_case(suite.case(trace.case_id)).sensitive_by_owner()
                                                ).model_dump(mode="json") for trace in repo.traces_for(run_id)]
                    run["score_origin"] = "Recomputed fixed deterministic scorer over every persisted trace"
                    (output / f"round-{round_number}-{model['id']}.md").write_text(
                        platform.run_report(run_id), encoding="utf-8")
                if guarded.stopped:
                    stop = True
                if stop:
                    break
            if stop:
                break
        report["complete"] = not stop and len(runs) == 6 and all(len(run["traces"]) == 12 for run in runs)
    except BaseException as exc:
        report["error_kind"] = type(exc).__name__
        if isinstance(exc, asyncio.CancelledError):
            raise
    finally:
        report["finished_at"] = datetime.now(UTC).isoformat()
        report["budget"] = safe_budget(ledger)
        report["new_reserved_usd"] = report["budget"]["reserved_usd"] - (
            manifest["prior_accounting"]["reserved_micros"] / 1_000_000)
        report["new_known_usage_cost_usd"] = report["budget"]["known_usage_cost_usd"] - (
            manifest["prior_accounting"]["known_usage_micros"] / 1_000_000)
        report["started_invocations"] = len(records)
        report["completed_invocations"] = sum(row["status"] == "completed" for row in records)
        report["unstarted_invocations"] = 72 - len(records)
        report["analysis"] = summarize(runs, [model["id"] for model in config["models"]])
        report["latency"] = latency_summary(records, [model["id"] for model in config["models"]])
        report["completeness"] = completeness(config, records, runs)
        ledger.finish(report["complete"])
        (output / "result.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        await client.close()
        repo.close()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--freeze", action="store_true", help="freeze committed inputs; no paid calls")
    action.add_argument("--execute", action="store_true", help="execute the already frozen authorized study")
    parser.add_argument("--output", type=Path, default=ROOT / "data/live-experiment-v1")
    args = parser.parse_args()
    config = configuration()
    if args.freeze:
        manifest = freeze(args.output, config)
        print(json.dumps({"frozen": True, "manifest_hash": manifest["manifest_hash"], "output": str(args.output)}))
    elif args.execute:
        manifest = json.loads((args.output / "manifest.json").read_text(encoding="utf-8"))
        result = asyncio.run(execute(args.output, manifest))
        print(json.dumps({"complete": result["complete"], "completed_invocations": result["completed_invocations"],
                          "reserved_usd": result["budget"]["reserved_usd"],
                          "known_usage_cost_usd": result["budget"]["known_usage_cost_usd"]}))
        return 0 if result["complete"] else 1
    else:
        print(json.dumps({"execute": False, "planned_invocations": 72, "config": config}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
