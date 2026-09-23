"""The primary eval workflow: eight steps, each producing a deterministic, hashed artifact."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from ..adapters.agents import AgentAdapter, AgentOutcome, HarnessError
from ..adapters.claude_agent import estimate_cost
from ..adapters.repositories import Repository, canonical_hash, stable_id
from ..adapters.sandbox import Sandbox, world_ids
from ..domain.models import Confidence, EvidenceRef, Finding
from ..domain.policies import (
    PolicyViolation,
    check_run_allowed,
    check_suite_content,
    evaluate_gate,
    suite_authorizations,
)
from ..domain.project_models import (
    AgentRecord,
    CaseScore,
    Environment,
    EvalCase,
    EvalSuite,
    FailurePlan,
    GateOutcome,
    Phase,
    Scorecard,
    Trace,
)
from ..domain.scoring import SCORING_VERSION, score_trace
from ..domain.stats import aggregate, case_outcomes, compare, regression_alerts
from ..observability import span
from .base import RunContext, Status, StepResult, TransientError, run_steps

PROJECT_STEPS = [
    "Register system",
    "Load eval suite",
    "Run baseline",
    "Inject failures",
    "Score traces",
    "Compare versions/models",
    "Gate release",
    "Monitor regressions",
]
GATE_STEP = "Gate release"
CASE_TIMEOUT_S = 180
CONCURRENCY = 4


@dataclass
class EvalEnvironment:
    repo: Repository
    adapter_factory: Callable[[AgentRecord], AgentAdapter]
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)

    def agent(self, agent_id: str) -> AgentRecord:
        agent = self.repo.get_agent(agent_id)
        if agent is None:
            raise LookupError(f"agent {agent_id} is not registered")
        return agent

    def suite(self, suite_id: str, version: str) -> EvalSuite:
        found = self.repo.get_suite(suite_id, version)
        if found is None:
            raise LookupError(f"suite {suite_id}@{version} is not registered")
        suite, stored_hash = found
        if suite.content_hash() != stored_hash:
            raise PolicyViolation(f"suite {suite_id}@{version} content does not match its registered hash")
        return suite

    def authorize(self, agent: AgentRecord, suite: EvalSuite, case_ids: list[str] | None = None) -> None:
        """Re-check authorization with the current clock right before the agent is called."""
        check_run_allowed(agent, suite, self.repo.authorizations_for(agent.agent_id), self.clock(),
                          case_ids=case_ids)


# ------------------------------------------------------------------ harness


def trace_id_for(run_id: str, case_id: str, phase: Phase, repeat: int, failure: FailurePlan | None) -> str:
    tag = f"{failure.tool}:{failure.failure_type.value}" if failure else "-"
    return stable_id("trace", run_id, case_id, phase, str(repeat), tag)


async def run_case(adapter: AgentAdapter, agent: AgentRecord, suite: EvalSuite, case: EvalCase, *, run_id: str,
                   phase: Phase, repeat: int, failure: FailurePlan | None = None) -> Trace:
    budget = suite.budget_for(case)
    sandbox = Sandbox.for_case(case, failure=failure, max_tool_calls=budget.max_tool_calls)
    agent_error = None
    try:
        with span("agent_case", run_id=run_id, case_id=case.case_id, phase=phase, repeat=repeat,
                  agent_id=agent.agent_id, model=adapter.model,
                  injected_tool=failure.tool if failure else None) as case_span:
            outcome = await asyncio.wait_for(adapter.run(case.prompt, sandbox, repeat=repeat),
                                             timeout=CASE_TIMEOUT_S)
            case_span.set_attribute("tool_calls", len(sandbox.calls))
            case_span.set_attribute("stop_reason", outcome.stop_reason)
            case_span.set_attribute("input_tokens", outcome.input_tokens)
            case_span.set_attribute("output_tokens", outcome.output_tokens)
    except Exception as exc:  # noqa: BLE001 - classified below; only genuine agent failures are scored
        kind = adapter.classify_error(exc)
        if kind == "transient":
            raise TransientError(f"could not reach agent {agent.agent_id}: {type(exc).__name__}") from exc
        if kind == "harness":
            raise HarnessError(f"harness could not run agent {agent.agent_id}: {type(exc).__name__}: {exc}") from exc
        outcome = AgentOutcome(final_output="", stop_reason="agent_error", model=adapter.model)
        agent_error = f"{type(exc).__name__}: {exc}"
    latency = outcome.latency_ms if outcome.latency_ms is not None else 250 + sum(
        c.latency_ms for c in sandbox.calls)
    return Trace(
        trace_id=trace_id_for(run_id, case.case_id, phase, repeat, failure),
        run_id=run_id, case_id=case.case_id, phase=phase, repeat=repeat, agent_id=agent.agent_id,
        model=outcome.model, tool_calls=sandbox.calls, final_output=outcome.final_output,
        stop_reason=outcome.stop_reason, input_tokens=outcome.input_tokens, output_tokens=outcome.output_tokens,
        latency_ms=latency, cost_usd=estimate_cost(outcome.model, outcome.input_tokens, outcome.output_tokens),
        agent_error=agent_error, injected_failure=failure,
    )


async def _run_jobs(env: EvalEnvironment, jobs: Sequence[Callable[[], Awaitable[Trace]]], ids: list[str]) -> None:
    """Run jobs whose trace isn't stored yet; each trace is persisted as soon as it completes."""
    sem = asyncio.Semaphore(CONCURRENCY)

    async def one(job: Callable[[], Awaitable[Trace]]) -> None:
        async with sem:
            env.repo.save_trace(await job())

    pending = [one(job) for job, tid in zip(jobs, ids, strict=True) if not env.repo.trace_exists(tid)]
    results = await asyncio.gather(*pending, return_exceptions=True)
    errors = [r for r in results if isinstance(r, BaseException)]
    if errors:
        raise errors[0]


# ------------------------------------------------------------------ steps


async def register_system(ctx: RunContext, env: EvalEnvironment) -> StepResult:
    agent = env.agent(ctx.run["agent_id"])
    recomputed = canonical_hash(agent.config)
    if recomputed != agent.config_hash:
        raise PolicyViolation(f"agent {agent.agent_id} config changed after registration; register a new version")
    return StepResult({"agent_id": agent.agent_id, "name": agent.name, "version": agent.version,
                       "adapter": agent.adapter.value, "environment": agent.environment.value,
                       "config_hash": agent.config_hash})


async def load_eval_suite(ctx: RunContext, env: EvalEnvironment) -> StepResult:
    suite = env.suite(ctx.run["suite_id"], ctx.run["suite_version"])
    check_suite_content(suite, reserved_ids=world_ids())
    agent = env.agent(ctx.run["agent_id"])
    auth = check_run_allowed(agent, suite, env.repo.authorizations_for(agent.agent_id), env.clock())
    categories: dict[str, int] = defaultdict(int)
    for c in suite.cases:
        categories[c.category.value] += 1
    return StepResult({
        "suite_id": suite.suite_id, "version": suite.version,
        "content_hash": suite.content_hash(),
        "n_cases": len(suite.cases), "repeats": suite.repeats, "categories": dict(sorted(categories.items())),
        "security_cases": {cid: sorted(needs) for cid, needs in suite_authorizations(suite).items()},
        "authorization_id": auth.authorization_id if auth else None,
        "failure_plans": len(suite.failure_plans),
    })


async def run_baseline(ctx: RunContext, env: EvalEnvironment) -> StepResult:
    agent = env.agent(ctx.run["agent_id"])
    suite = env.suite(ctx.run["suite_id"], ctx.run["suite_version"])
    env.authorize(agent, suite)
    adapter = env.adapter_factory(agent)
    jobs, ids = [], []
    for case in suite.cases:
        for r in range(suite.repeats):
            ids.append(trace_id_for(ctx.run_id, case.case_id, "baseline", r, None))
            jobs.append(lambda case=case, r=r: run_case(adapter, agent, suite, case, run_id=ctx.run_id,
                                                         phase="baseline", repeat=r))
    await _run_jobs(env, jobs, ids)
    crashed = sum(1 for t in env.repo.traces_for(ctx.run_id, ("baseline",)) if t.agent_error)
    return StepResult({"n_traces": len(ids), "trace_ids": ids, "agent_errors": crashed})


async def inject_failures(ctx: RunContext, env: EvalEnvironment) -> StepResult:
    agent = env.agent(ctx.run["agent_id"])
    suite = env.suite(ctx.run["suite_id"], ctx.run["suite_version"])
    if agent.environment is Environment.PRODUCTION or not suite.failure_plans:
        reason = "production agent" if agent.environment is Environment.PRODUCTION else "suite has no failure plans"
        return StepResult({"n_traces": 0, "trace_ids": [], "skipped": reason})
    env.authorize(agent, suite, [p.case_id for p in suite.failure_plans])
    adapter = env.adapter_factory(agent)
    jobs, ids = [], []
    for plan in suite.failure_plans:
        case = suite.case(plan.case_id)
        ids.append(trace_id_for(ctx.run_id, case.case_id, "injected", 0, plan))
        jobs.append(lambda case=case, plan=plan: run_case(adapter, agent, suite, case, run_id=ctx.run_id,
                                                           phase="injected", repeat=0, failure=plan))
    await _run_jobs(env, jobs, ids)
    return StepResult({"n_traces": len(ids), "trace_ids": ids,
                       "plans": [p.model_dump(mode="json") for p in suite.failure_plans]})


def findings_from_scores(run_id: str, scores: list[CaseScore], evidence_ids: dict[str, str]) -> list[Finding]:
    """One finding per (case, phase, dimension) failure, linked to every failing trace as evidence."""
    groups: dict[tuple[str, str, str], list[CaseScore]] = defaultdict(list)
    totals: dict[tuple[str, str], int] = defaultdict(int)
    for s in scores:
        totals[(s.case_id, s.phase)] += 1
        for d in s.failures():
            groups[(s.case_id, s.phase, d.dimension.value)].append(s)
    out = []
    for (case_id, phase, dim), failing in sorted(groups.items()):
        first = failing[0].dimensions[dim]
        refs = [EvidenceRef(evidence_id=evidence_ids[s.trace_id], source_type="agent_trace",
                            uri=f"trace://{s.trace_id}", content_hash="") for s in failing]
        out.append(Finding(
            finding_id=stable_id("finding", run_id, case_id, phase, dim),
            finding_type=dim, severity=first.severity.value, case_id=case_id, confidence=Confidence.HIGH,
            title=f"{dim} failed on {case_id} ({phase})",
            statement=(f"{dim} failed in {len(failing)}/{totals[(case_id, phase)]} {phase} trace(s) of case "
                       f"{case_id}: {first.detail}"),
            evidence=refs,
            assumptions=["Deterministic scorer; the verdict is reproducible from the linked trace."],
        ))
    return out


async def score_traces(ctx: RunContext, env: EvalEnvironment) -> StepResult:
    agent = env.agent(ctx.run["agent_id"])
    suite = env.suite(ctx.run["suite_id"], ctx.run["suite_version"])
    traces = env.repo.traces_for(ctx.run_id)
    if not traces:
        raise RuntimeError("no traces to score")
    scores = []
    for t in traces:
        case = suite.case(t.case_id)
        scores.append(score_trace(case, suite, t, Sandbox.for_case(case).sensitive_by_owner()))
    card = aggregate(scores, [t.latency_ms for t in traces if t.phase == "baseline"],
                     sum(t.cost_usd for t in traces))
    outcomes = case_outcomes(scores)
    evidence_ids = {t.trace_id: stable_id("evidence", t.trace_id) for t in traces}
    findings = findings_from_scores(ctx.run_id, scores, evidence_ids)
    for f in findings:
        for ref in f.evidence:
            stored = env.repo.get_evidence(ref.evidence_id)
            if stored is None:
                raise RuntimeError(f"evidence {ref.evidence_id} missing for finding {f.finding_id}")
            ref.content_hash = stored.content_hash
        env.repo.save_finding(ctx.run_id, f)
    env.repo.save_run_metrics(run_id=ctx.run_id, agent_name=agent.name, suite_id=suite.suite_id,
                              suite_version=suite.version, scorecard=card.model_dump(mode="json"),
                              outcomes=outcomes)
    return StepResult({
        "scoring_version": SCORING_VERSION,
        "scorecard": card.model_dump(mode="json"),
        "case_outcomes": outcomes,
        "evidence_read": sorted(evidence_ids.values()),
        "n_findings": len(findings),
        "failures": [{"case_id": s.case_id, "phase": s.phase, "repeat": s.repeat,
                      "dimensions": [d.dimension.value for d in s.failures()]} for s in scores if not s.passed],
    })


def release_decision(repo: Repository, run_id: str, gate: dict[str, Any] | None) -> str:
    if gate is None:
        return "pending"
    outcome = gate["decision"]["outcome"]
    if outcome == GateOutcome.PASS:
        return "eligible"
    if outcome == GateOutcome.BLOCK:
        return "blocked"
    approval = repo.get_approval(run_id, GATE_STEP)
    if approval is None:
        return "awaiting_review"
    return "approved_with_override" if approval["decision"] == "approve" else "rejected"


def _accepted(repo: Repository, run_id: str) -> bool:
    gate = repo.artifacts(run_id).get(GATE_STEP)
    return release_decision(repo, run_id, gate["payload"] if gate else None) in {"eligible", "approved_with_override"}


def _comparison(env: EvalEnvironment, current: dict[str, Any], baseline_id: str) -> dict[str, Any]:
    base = env.repo.get_run_metrics(baseline_id)
    if base is None:
        raise LookupError(f"baseline run {baseline_id} has no scored metrics")
    same_suite = (current["suite_id"], current["suite_version"]) == (base["suite_id"], base["suite_version"])
    result = compare(Scorecard.model_validate(current["scorecard"]), current["case_outcomes"],
                     Scorecard.model_validate(base["scorecard"]), base["case_outcomes"], same_suite_version=same_suite)
    base_run = env.repo.get_run(baseline_id) or {}
    return {"baseline_run_id": baseline_id, "baseline_agent_id": base_run.get("agent_id"),
            "baseline_suite": f"{base['suite_id']}@{base['suite_version']}", **result}


async def compare_versions(ctx: RunContext, env: EvalEnvironment) -> StepResult:
    """Two comparisons, kept apart on purpose.

    gating: against the most recent *accepted* run of the same agent name on the same suite version that was
    requested before this one. Only this one can put a run into review, and the caller can't choose it.
    requested: against a caller-chosen baseline_run_id (e.g. another model). Informational only.
    """
    current = env.repo.get_run_metrics(ctx.run_id)
    assert current is not None
    run = env.repo.get_run(ctx.run_id) or ctx.run
    candidates = env.repo.metrics_history(current["agent_name"], current["suite_id"], current["suite_version"],
                                          limit=50, before=run["created_at"])
    gating_id = next((h["run_id"] for h in reversed(candidates)
                      if h["run_id"] != ctx.run_id and _accepted(env.repo, h["run_id"])), None)
    selection = f"last accepted run of {current['agent_name']} on {current['suite_id']}@{current['suite_version']}"
    artifact: dict[str, Any]
    if gating_id is None:
        artifact = {"baseline_run_id": None, "selection": selection,
                    "note": "no earlier accepted run on this suite version; gating comparison skipped"}
    else:
        artifact = {"selection": selection, **_comparison(env, current, gating_id)}
    requested_id = ctx.run.get("baseline_run_id")
    artifact["requested"] = _comparison(env, current, requested_id) if requested_id else None
    return StepResult(artifact)


async def gate_release(ctx: RunContext, env: EvalEnvironment) -> StepResult:
    card = Scorecard.model_validate(ctx.artifacts["Score traces"]["scorecard"])
    comparison = ctx.artifacts.get("Compare versions/models")
    gating = comparison if comparison and comparison.get("baseline_run_id") else None
    prior_blocks = []
    for other in env.repo.runs_for_agent(ctx.run["agent_id"]):
        if other["run_id"] == ctx.run_id:
            continue
        gate = env.repo.artifacts(other["run_id"]).get(GATE_STEP)
        if gate and gate["payload"]["decision"]["outcome"] == GateOutcome.BLOCK:
            prior_blocks.append(other["run_id"])
    decision = evaluate_gate(card, gating, prior_blocks)
    return StepResult({"decision": decision.model_dump(mode="json")}, pause=decision.outcome is GateOutcome.REVIEW)


async def monitor_regressions(ctx: RunContext, env: EvalEnvironment) -> StepResult:
    """Trend of this agent name on this exact suite version (case sets differ across versions)."""
    current = env.repo.get_run_metrics(ctx.run_id)
    assert current is not None
    history = env.repo.metrics_history(current["agent_name"], current["suite_id"], current["suite_version"])
    series = [{"run_id": h["run_id"], "agent_id": h["agent_id"], "pass_rate": h["pass_rate"],
               "failing_cases": h["scorecard"]["failing_cases"]} for h in history]
    return StepResult({"suite_version": current["suite_version"], "window": len(series),
                       "history": [{k: v for k, v in s.items() if k != "failing_cases"} for s in series],
                       "alerts": regression_alerts(series)})


STEP_FUNCTIONS: dict[str, Callable[[RunContext, EvalEnvironment], Awaitable[StepResult]]] = {
    "Register system": register_system,
    "Load eval suite": load_eval_suite,
    "Run baseline": run_baseline,
    "Inject failures": inject_failures,
    "Score traces": score_traces,
    "Compare versions/models": compare_versions,
    "Gate release": gate_release,
    "Monitor regressions": monitor_regressions,
}


@dataclass
class FunctionalStep:
    name: str
    fn: Callable[[RunContext, EvalEnvironment], Awaitable[StepResult]]
    env: EvalEnvironment

    async def execute(self, ctx: RunContext) -> StepResult:
        return await self.fn(ctx, self.env)


async def run_primary(run_id: str, env: EvalEnvironment, *, actor: str,
                      overrides: dict[str, Callable[..., Awaitable[StepResult]]] | None = None) -> Status:
    run = env.repo.get_run(run_id)
    if run is None:
        raise LookupError(f"run {run_id} not found")
    fns = {**STEP_FUNCTIONS, **(overrides or {})}
    steps = [FunctionalStep(name=name, fn=fns[name], env=env) for name in PROJECT_STEPS]
    return await run_steps(RunContext(run_id=run_id, run=run, actor=actor), steps, env.repo)
