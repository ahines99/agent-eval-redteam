"""No network calls: budget enforcement, durable ambiguity and race checks."""

from __future__ import annotations

import asyncio
import importlib.util
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

SPEC = importlib.util.spec_from_file_location(
    "live_validation", Path(__file__).resolve().parents[1] / "scripts" / "live_validation.py")
assert SPEC and SPEC.loader
live = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(live)


class FakeMessages:
    def __init__(self, *, fail=False, count_fail=False, usage_input=100):
        self.calls = 0
        self.counts = 0
        self.fail = fail
        self.count_fail = count_fail
        self.usage_input = usage_input

    async def count_tokens(self, **kwargs):
        assert "max_tokens" not in kwargs
        self.counts += 1
        if self.count_fail:
            raise OSError("private failure text")
        return SimpleNamespace(input_tokens=100)

    async def create(self, **kwargs):
        self.calls += 1
        assert kwargs["max_tokens"] == live.MAX_OUTPUT
        if self.fail:
            raise OSError("private failure text")
        return SimpleNamespace(usage=SimpleNamespace(input_tokens=self.usage_input, output_tokens=50))


REQUEST = {"model": live.MODEL, "max_tokens": 16000, "system": "Support synthetic users",
           "messages": [{"role": "user", "content": "Hello"}], "tools": [],
           "output_config": {"effort": "low"}}


@pytest.mark.parametrize("value", ["0", "-1", "20.01", "NaN", "Infinity"])
def test_invalid_budget(value):
    with pytest.raises(ValueError):
        live.dollars_to_micros(value)


def test_budget_conversion():
    assert live.dollars_to_micros("5") == 5_000_000
    assert live.dollars_to_micros("20") == 20_000_000


@pytest.mark.anyio
async def test_preflight_reservation_and_actual_usage(tmp_path):
    ledger = live.Ledger(tmp_path / "budget.db", 1_000_000)
    fake = FakeMessages()
    await live.BudgetedMessages(fake, ledger).create(**REQUEST)
    result = ledger.snapshot()
    assert fake.calls == fake.counts == 1
    assert result["known_usage_cost_usd"] == 0.0007
    assert result["reserved_usd"] > result["known_usage_cost_usd"]
    assert result["requests"][0]["state"] == "completed"
    assert live.Ledger(tmp_path / "budget.db", 1_000_000).snapshot() == result
    with pytest.raises(live.BudgetRefused):
        live.Ledger(tmp_path / "budget.db", 2_000_000)


@pytest.mark.anyio
@pytest.mark.parametrize("mode", ["small-budget", "count-failure", "storage-failure"])
async def test_no_paid_call_on_preflight_failure(tmp_path, monkeypatch, mode):
    ledger = live.Ledger(tmp_path / "budget.db", 1 if mode == "small-budget" else 1_000_000)
    fake = FakeMessages(count_fail=mode == "count-failure")
    if mode == "storage-failure":
        def fail(*args):
            raise OSError("disk full")
        monkeypatch.setattr(ledger, "reserve", fail)
    guarded = live.BudgetedMessages(fake, ledger)
    with pytest.raises(live.BudgetRefused):
        await guarded.create(**REQUEST)
    assert fake.calls == 0
    assert ledger.snapshot()["requests"] == []


@pytest.mark.anyio
async def test_ambiguous_failure_retains_reservation_and_stops(tmp_path):
    ledger = live.Ledger(tmp_path / "budget.db", 1_000_000)
    fake = FakeMessages(fail=True)
    guarded = live.BudgetedMessages(fake, ledger)
    with pytest.raises(live.BudgetRefused, match="reservation retained") as error:
        await guarded.create(**REQUEST)
    assert "private" not in str(error.value)
    snapshot = ledger.snapshot()
    assert snapshot["reserved_usd"] > 0
    assert snapshot["requests"][0]["state"] == "ambiguous"
    with pytest.raises(live.BudgetRefused):
        await guarded.create(**REQUEST)
    assert fake.calls == 1


@pytest.mark.anyio
async def test_usage_anomaly_stops_without_refund(tmp_path):
    ledger = live.Ledger(tmp_path / "budget.db", 1_000_000)
    guarded = live.BudgetedMessages(FakeMessages(usage_input=1_000_000), ledger)
    with pytest.raises(live.BudgetRefused):
        await guarded.create(**REQUEST)
    assert ledger.snapshot()["requests"][0]["state"] == "ambiguous"
    assert guarded.stopped


@pytest.mark.anyio
async def test_provider_concurrency_cannot_oversubscribe(tmp_path):
    ledger = live.Ledger(tmp_path / "budget.db", 60_000)
    fake = FakeMessages()
    guarded = live.BudgetedMessages(fake, ledger)
    results = await asyncio.gather(*(guarded.create(**REQUEST) for _ in range(5)), return_exceptions=True)
    assert sum(isinstance(result, live.BudgetRefused) for result in results) == 4
    assert fake.calls == 1
    assert ledger.snapshot()["reserved_usd"] <= 0.06


def test_independent_ledger_connections_serialize_reservations(tmp_path):
    path = tmp_path / "budget.db"
    live.Ledger(path, 100)
    def reserve(_):
        try:
            live.Ledger(path, 100).reserve(60, 10)
            return True
        except live.BudgetRefused:
            return False
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(reserve, range(8))) == 1


@pytest.mark.anyio
@pytest.mark.parametrize("extra", [{"stream": True}, {"model": "unpriced"}, {"cache_control": {}}])
async def test_unpriced_request_features_refused(tmp_path, extra):
    ledger = live.Ledger(tmp_path / "budget.db", 1_000_000)
    fake = FakeMessages()
    with pytest.raises(live.BudgetRefused):
        await live.BudgetedMessages(fake, ledger).create(**{**REQUEST, **extra})
    assert fake.calls == fake.counts == 0


def test_small_suite_retains_recovery_and_security_cases():
    suite = live.validation_suite()
    assert len(suite.cases) == 10
    assert suite.repeats == 1
    assert len(suite.failure_plans) == 1
    assert {case.category.value for case in suite.cases} >= {"prompt_injection", "pii", "tool_use", "citation"}


@pytest.mark.anyio
async def test_paid_call_sees_committed_reservation(tmp_path):
    path = tmp_path / "budget.db"
    ledger = live.Ledger(path, 1_000_000)
    fake = FakeMessages()
    original = fake.create
    async def inspect_reservation(**kwargs):
        other_connection = live.Ledger(path, 1_000_000)
        assert other_connection.snapshot()["requests"][0]["state"] == "reserved"
        return await original(**kwargs)
    fake.create = inspect_reservation
    await live.BudgetedMessages(fake, ledger).create(**REQUEST)


@pytest.mark.anyio
async def test_cancelled_request_keeps_reservation(tmp_path):
    ledger = live.Ledger(tmp_path / "budget.db", 1_000_000)
    fake = FakeMessages()
    async def cancel(**kwargs):
        raise asyncio.CancelledError()
    fake.create = cancel
    with pytest.raises(asyncio.CancelledError):
        await live.BudgetedMessages(fake, ledger).create(**REQUEST)
    assert ledger.snapshot()["requests"][0]["error_kind"] == "CancelledError"
    assert ledger.snapshot()["reserved_usd"] > 0


@pytest.mark.anyio
async def test_full_runner_with_mocked_sdk_preserves_actual_failing_outcomes(tmp_path, monkeypatch):
    import anthropic

    class FakeClient:
        def __init__(self, **kwargs):
            assert kwargs["max_retries"] == 0
            assert kwargs["base_url"] == "https://api.anthropic.com"
            self.messages = FakeMessages()
            original = self.messages.create
            async def response(**request):
                out = await original(**request)
                out.content = [SimpleNamespace(type="text", text="NEEDS_EVIDENCE")]
                out.stop_reason = "end_turn"
                return out
            self.messages.create = response

        async def close(self):
            pass

    monkeypatch.setattr(anthropic, "AsyncAnthropic", FakeClient)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-test-credential")
    output = tmp_path / "run"
    report = await live.execute(output, 5_000_000)
    assert "error_kind" not in report
    assert len(report["traces"]) == 11
    assert report["summary"]["scorecard"]["pass_rate"] < 1
    assert report["budget"]["reserved_usd"] < 5
    assert (output / "result.json").is_file()
    assert (output / "run-report.md").is_file()
    with pytest.raises(FileExistsError):
        await live.execute(output, 5_000_000)


@pytest.mark.anyio
async def test_missing_key_does_not_create_evidence_or_call_provider(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    output = tmp_path / "run"
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        await live.execute(output, 5_000_000)
    assert not output.exists()
