"""No provider traffic: study provenance, cumulative accounting, latency and repeated-run contracts."""
from __future__ import annotations

import asyncio
import importlib.util
import json
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_eval_redteam.adapters.claude_agent import ClaudeConfig, estimate_cost
from agent_eval_redteam.adapters.repositories import canonical_hash
from agent_eval_redteam.workflows import primary

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
# The executable imports its sibling legacy guard. Keep that executable import environment explicit.
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location("live_experiment", SCRIPTS / "live_experiment.py")
assert SPEC and SPEC.loader
study = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(study)
sys.path.remove(str(SCRIPTS))


@pytest.fixture
def frozen(tmp_path, monkeypatch):
    config = study.configuration()
    (tmp_path / "data/live-validation").mkdir(parents=True)
    (tmp_path / "uv.lock").write_text("synthetic lock", encoding="utf-8")
    old = study.Ledger(tmp_path / config["prior_ledger"], 5_000_000)
    # Preserve the exact authorized historical totals without making a provider request.
    with closing(old._connect()) as db, db:
        for index in range(21):
            db.execute("INSERT INTO requests(reserved,counted_input,state,actual_micros) VALUES (?,0,'completed',?)",
                       (1_411_024 if index == 0 else 0, 104_170 if index == 0 else 0))
    monkeypatch.setattr(study, "ROOT", tmp_path)
    def fake_git(*args):
        if args[0] == "status":
            return ""
        if args[0] == "show":
            return (tmp_path / study.FROZEN_MANIFEST).read_text(encoding="utf-8")
        return "a" * 40
    monkeypatch.setattr(study, "git", fake_git)
    monkeypatch.setattr(study, "source_files", lambda: {"scripts/live_experiment.py": "b" * 40})
    output = tmp_path / "study-output"
    manifest = study.freeze(output, config)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-not-a-key")
    return config, output, manifest


def test_dated_haiku_is_explicitly_priced_and_has_no_effort():
    assert ClaudeConfig(model="claude-haiku-4-5-20251001").request_effort() is None
    assert estimate_cost("claude-haiku-4-5-20251001", 1000, 100) == .0015
    with pytest.raises(ValueError):
        ClaudeConfig(model="claude-haiku-4-5-20251001", effort="low").request_effort()
    with pytest.raises(ValueError):
        ClaudeConfig(model="claude-haiku-4-5-20990101")


def test_freeze_binds_inputs_and_preserves_original_gate_budget(frozen):
    config, output, manifest = frozen
    study.validate_manifest(manifest, config)
    assert study.study_suite(config).default_budget.max_latency_ms == 8000
    assert manifest["planned_invocations"] == 72
    assert manifest["sampling_seed"] is None
    assert manifest["prior_accounting"]["reserved_micros"] == 1_411_024
    assert json.loads((output / "manifest.json").read_text()) == manifest
    with pytest.raises(FileExistsError):
        study.freeze(output, config)


@pytest.mark.parametrize("drift", ["hash", "prompt", "source", "dirty", "history", "suite", "lock", "code"])
def test_drift_refused_before_paid_calls(frozen, monkeypatch, drift):
    config, _, manifest = frozen
    if drift == "hash":
        manifest["planned_invocations"] = 71
    elif drift == "prompt":
        manifest["system_prompt"] = "Different instructions"
        manifest["manifest_hash"] = canonical_hash({k: v for k, v in manifest.items() if k != "manifest_hash"})
    elif drift == "source":
        monkeypatch.setattr(study, "git", lambda *args: "" if args[0] == "status" else "b" * 40)
    elif drift == "dirty":
        monkeypatch.setattr(study, "git", lambda *args: " M changed.py" if args[0] == "status" else "a" * 40)
    elif drift == "history":
        with closing(sqlite3.connect(study.ROOT / config["prior_ledger"])) as db, db:
            db.execute("UPDATE requests SET state='ambiguous' WHERE id=1")
    elif drift == "suite":
        manifest["suite"]["default_budget"]["max_latency_ms"] = 60000
        manifest["manifest_hash"] = canonical_hash({k: v for k, v in manifest.items() if k != "manifest_hash"})
    elif drift == "lock":
        (study.ROOT / "uv.lock").write_text("new lock")
    else:
        monkeypatch.setattr(study, "source_files", lambda: {"scripts/live_experiment.py": "c" * 40})
    with pytest.raises((ValueError, study.BudgetRefused)):
        study.validate_manifest(manifest, config)


def test_campaign_import_is_once_and_new_directory_cannot_restart(frozen):
    config, _, manifest = frozen
    path = study.ROOT / config["campaign_ledger"]
    ledger = study.CampaignLedger(path, manifest)
    assert ledger.snapshot()["reserved_usd"] == 1.411024
    assert len(study.CampaignLedger(path, manifest).snapshot()["requests"]) == 1
    ledger.claim()
    request = ledger.reserve(100, 10)
    ledger.record(request, input_tokens=10, output_tokens=2)
    with pytest.raises(study.BudgetRefused, match="already started"):
        study.CampaignLedger(path, manifest).claim()
    altered = {**manifest, "manifest_hash": "different-output-freeze"}
    with pytest.raises(study.BudgetRefused, match="another frozen manifest"):
        study.CampaignLedger(path, altered)


@pytest.mark.parametrize("state", ["reserved", "ambiguous"])
def test_unresolved_request_prevents_new_transmission_after_restart(frozen, state):
    config, _, manifest = frozen
    path = study.ROOT / config["campaign_ledger"]
    ledger = study.CampaignLedger(path, manifest)
    ledger.claim()
    request = ledger.reserve(100, 10)
    if state == "ambiguous":
        ledger.record(request, error_kind="TimeoutError")
    reopened = study.CampaignLedger(path, manifest)
    with pytest.raises(study.BudgetRefused, match="unresolved"):
        reopened.reserve(100, 10)
    assert reopened.snapshot()["reserved_usd"] == 1.411124


def test_cumulative_budget_includes_prior_and_serializes_connections(frozen):
    config, _, manifest = frozen
    path = study.ROOT / config["campaign_ledger"]
    ledger = study.CampaignLedger(path, manifest)
    ledger.claim()
    def reserve(_):
        try:
            return study.CampaignLedger(path, manifest).reserve(10_588_976, 10)
        except study.BudgetRefused:
            return None
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(reserve, range(4)))
    assert sum(value is not None for value in results) == 1
    ledger.record(next(value for value in results if value is not None), input_tokens=10, output_tokens=1)
    with pytest.raises(study.BudgetRefused, match="ceiling"):
        ledger.reserve(1, 0)
    assert ledger.snapshot()["reserved_usd"] == 12


class FakeMessages:
    def __init__(self, *, fail_at=None, wrong_model=False):
        self.calls = 0
        self.active = 0
        self.max_active = 0
        self.fail_at, self.wrong_model = fail_at, wrong_model

    async def count_tokens(self, **kwargs):
        assert "max_tokens" not in kwargs
        return SimpleNamespace(input_tokens=100)

    async def create(self, **kwargs):
        self.calls += 1
        self.active += 1
        self.max_active = max(self.active, self.max_active)
        try:
            await asyncio.sleep(0)
            if self.calls == self.fail_at:
                raise OSError("must-not-publish-provider-detail")
            if "haiku" in kwargs["model"]:
                assert "output_config" not in kwargs
            assert kwargs["max_tokens"] == 4096
            return SimpleNamespace(model="wrong" if self.wrong_model else kwargs["model"], id="private-response-id",
                                   usage=SimpleNamespace(input_tokens=100, output_tokens=20),
                                   content=[SimpleNamespace(type="text", text="NEEDS_EVIDENCE")],
                                   stop_reason="end_turn")
        finally:
            self.active -= 1


class FakeClient:
    def __init__(self, **kwargs):
        self.messages = FakeMessages(**kwargs)
        self.closed = False

    async def close(self):
        self.closed = True


@pytest.mark.anyio
async def test_complete_two_model_three_round_execution_preserves_failing_results(frozen):
    _, output, manifest = frozen
    client = FakeClient()
    result = await study.execute(output, manifest, client=client)
    assert result["complete"]
    assert client.messages.calls == result["completed_invocations"] == result["started_invocations"] == 72
    assert client.messages.max_active == 1 and client.closed
    assert result["unstarted_invocations"] == 0
    assert len(result["completeness"]) == 72 and all(row["score_available"] for row in result["completeness"])
    assert [run["round"] for run in result["runs"]] == [1, 1, 2, 2, 3, 3]
    models = [model["id"] for model in result["models"]]
    assert [run["model"] for run in result["runs"]] == [models[0], models[1], models[1], models[0], *models]
    assert all(len(run["scores"]) == len(run["traces"]) == 12 for run in result["runs"])
    assert all(run["summary"]["scorecard"]["pass_rate"] < 1 for run in result["runs"])
    assert len([row for row in result["invocations"] if row["phase"] == "injected"]) == 12
    assert result["analysis"]["paired_comparison"]["available"]
    assert result["budget"]["reserved_usd"] < 12
    assert result["new_known_usage_cost_usd"] == pytest.approx(.0216)
    public = (output / "result.json").read_text()
    assert "private-response-id" not in public and "synthetic-not-a-key" not in public
    assert all(len(row["requests"]) == 1 for row in result["invocations"])
    with pytest.raises(ValueError, match="execution evidence"):
        await study.execute(output, manifest, client=FakeClient())


@pytest.mark.anyio
@pytest.mark.parametrize("mode", ["failure", "wrong-model"])
async def test_failure_is_preserved_no_retry_and_missing_cases_are_explicit(frozen, mode):
    _, output, manifest = frozen
    client = FakeClient(fail_at=2 if mode == "failure" else None, wrong_model=mode == "wrong-model")
    result = await study.execute(output, manifest, client=client)
    assert not result["complete"] and client.closed
    assert client.messages.calls == (2 if mode == "failure" else 1)
    assert result["unstarted_invocations"] > 0
    assert result["started_invocations"] > result["completed_invocations"]
    assert not result["analysis"]["paired_comparison"]["available"]
    assert len(result["completeness"]) == 72
    assert any(row["status"] == "not_started" for row in result["completeness"])
    assert any(row["state"] == "ambiguous" for row in result["budget"]["requests"])
    assert "must-not-publish-provider-detail" not in (output / "result.json").read_text()


@pytest.mark.anyio
async def test_request_timing_separates_provider_counting_and_accounting(tmp_path):
    ticks = [0.0]
    clock = lambda: ticks[0]  # noqa: E731
    ledger = study.Ledger(tmp_path / "timed.db", 1_000_000)
    reserve, record = ledger.reserve, ledger.record
    def timed_reserve(*args):
        ticks[0] += .003
        return reserve(*args)
    def timed_record(*args, **kwargs):
        ticks[0] += .004
        return record(*args, **kwargs)
    ledger.reserve, ledger.record = timed_reserve, timed_record
    class TimedMessages(FakeMessages):
        async def count_tokens(self, **kwargs):
            ticks[0] += .011
            return await super().count_tokens(**kwargs)
        async def create(self, **kwargs):
            ticks[0] += .029
            return await super().create(**kwargs)
    timings = []
    guard = study.BudgetedMessages(TimedMessages(), ledger, clock=clock, observer=timings.append)
    await guard.create(model="claude-sonnet-5", max_tokens=16000, system="synthetic", tools=[], messages=[])
    assert timings[0]["queue_ms"] == 0
    assert timings[0]["counting_ms"] == pytest.approx(11)
    assert timings[0]["reservation_ms"] == pytest.approx(3)
    assert timings[0]["provider_http_ms"] == pytest.approx(29)
    assert timings[0]["recording_ms"] == pytest.approx(4)
    assert timings[0]["total_ms"] == pytest.approx(47)


@pytest.mark.anyio
async def test_guard_queue_delay_is_separate_and_missing_manifest_refuses_execution(frozen):
    config, output, manifest = frozen
    ticks = [0.0]
    timings = []
    ledger = study.Ledger(study.ROOT / "timing.db", 1_000_000)
    guard = study.BudgetedMessages(FakeMessages(), ledger, clock=lambda: ticks[0], observer=timings.append)
    await guard.lock.acquire()
    task = asyncio.create_task(guard.create(model="claude-sonnet-5", max_tokens=4096,
                                           system="synthetic", tools=[], messages=[]))
    await asyncio.sleep(0)
    ticks[0] = .5
    guard.lock.release()
    await task
    assert timings[0]["queue_ms"] == pytest.approx(500)
    assert timings[0]["provider_http_ms"] == 0
    (study.ROOT / study.FROZEN_MANIFEST).unlink()
    client = FakeClient()
    with pytest.raises(FileNotFoundError):
        await study.execute(output, manifest, client=client)
    assert client.messages.calls == 0
    assert not (study.ROOT / config["campaign_ledger"]).exists()


@pytest.mark.anyio
async def test_mid_study_budget_refusal_preserves_partial_evidence(frozen, monkeypatch):
    _, output, manifest = frozen
    reserve = study.CampaignLedger.reserve
    attempts = [0]
    def bounded(self, *args):
        attempts[0] += 1
        if attempts[0] > 1:
            raise study.BudgetRefused("synthetic exhausted budget")
        return reserve(self, *args)
    monkeypatch.setattr(study.CampaignLedger, "reserve", bounded)
    client = FakeClient()
    result = await study.execute(output, manifest, client=client)
    assert not result["complete"] and client.messages.calls == 1
    assert result["completed_invocations"] == 1
    assert result["budget"]["requests"][-1]["state"] == "completed"
    assert any(request["state"] == "preflight_refused"
               for row in result["invocations"] for request in row["requests"])


@pytest.mark.anyio
async def test_failure_before_current_run_does_not_reuse_prior_round(frozen, monkeypatch):
    _, output, manifest = frozen
    start_run = study.EvalPlatform.start_run
    async def fail_later(self, **kwargs):
        if kwargs["idempotency_key"].startswith("study-round-2-"):
            raise RuntimeError("synthetic failure before creation")
        return await start_run(self, **kwargs)
    monkeypatch.setattr(study.EvalPlatform, "start_run", fail_later)
    result = await study.execute(output, manifest, client=FakeClient())
    assert not result["complete"] and len(result["runs"]) == 3
    failed = result["runs"][-1]
    assert failed["scores"] == failed["traces"] == [] and "run_id" not in failed
    assert result["completed_invocations"] == 24
    assert not result["analysis"]["paired_comparison"]["available"]


@pytest.mark.anyio
async def test_environment_concurrency_one_and_invalid_settings():
    active, maximum = 0, 0
    saved = []
    async def job():
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        await asyncio.sleep(0)
        active -= 1
        return "trace"
    env = SimpleNamespace(concurrency=1, repo=SimpleNamespace(save_trace=saved.append, trace_exists=lambda _: False))
    await primary._run_jobs(env, [job] * 5, [str(index) for index in range(5)])
    assert maximum == 1 and len(saved) == 5
    for invalid in (0, 5, True, 1.5):
        env.concurrency = invalid
        with pytest.raises(ValueError):
            await primary._run_jobs(env, [], [])


def test_paired_bootstrap_uses_ten_cases_and_refuses_missing_repeats():
    runs = [{"model": model, "scores": [{"case_id": str(case), "phase": "baseline", "passed": model == "a",
                                         "dimensions": {}} for case in range(10)]}
            for model in ("a", "b") for _ in range(3)]
    result = study.summarize(runs, ["a", "b"])["paired_comparison"]
    assert result["distinct_cases"] == 10
    assert result["mean_delta"] == 1 and result["case_cluster_bootstrap_ci95"] == [1, 1]
    runs.pop()
    assert not study.summarize(runs, ["a", "b"])["paired_comparison"]["available"]
