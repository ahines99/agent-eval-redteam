"""Application services: the single entry point used by the MCP server, the CLI and tests.

Everything that decides or mutates state lives here or below; the MCP layer only adapts types.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from importlib import resources
from typing import Any

from pydantic import BaseModel

from ..adapters.agents import AgentAdapter, build_adapter
from ..adapters.repositories import Repository, canonical_hash, stable_id
from ..adapters.sandbox import Sandbox, world_ids
from ..workflows.base import Status
from ..workflows.primary import (
    GATE_STEP,
    PROJECT_STEPS,
    EvalEnvironment,
    release_decision,
    run_case,
    run_primary,
)
from .models import SCHEMA_VERSION, AuditEvent, Finding
from .policies import (
    MAX_AUTHORIZATION_HOURS,
    MAX_IDEMPOTENCY_KEY,
    Authorization,
    PolicyViolation,
    check_failure_injection,
    check_gate_decision,
    check_run_allowed,
    check_suite_content,
    normalize_actor,
)
from .project_models import (
    SECURITY_CATEGORIES,
    AdapterKind,
    AgentRecord,
    AgentSpec,
    CaseScore,
    EvalSuite,
    FailurePlan,
    FailureType,
    GateDecision,
)
from .scoring import score_trace
from .stats import regression_alerts


class StepView(BaseModel):
    step: str
    done: bool
    artifact_hash: str | None = None


class RunSummary(BaseModel):
    run_id: str
    status: str
    current_step: str | None
    agent_id: str
    suite: str
    requested_by: str
    error: str | None
    steps: list[StepView]
    scorecard: dict[str, Any] | None
    gate: GateDecision | None
    release_decision: str
    comparison: dict[str, Any] | None
    requested_comparison: dict[str, Any] | None
    regression_alerts: list[str]
    schema_version: str = SCHEMA_VERSION


class EvalPlatform:
    def __init__(self, repo: Repository, *, adapter_factory: Any = None, clock: Any = None) -> None:
        self.repo = repo
        self.env = EvalEnvironment(repo=repo, adapter_factory=adapter_factory or build_adapter,
                                   clock=clock or (lambda: datetime.now(UTC)))

    def _audit(self, run_id: str | None, step: str, event_type: str, actor: str, **payload: Any) -> None:
        self.repo.audit(AuditEvent(run_id=run_id, step=step, event_type=event_type, actor=actor,
                                   created_at=self.env.clock(), payload=payload))

    # ------------------------------------------------------------ registry

    def register_agent(self, spec: AgentSpec) -> AgentRecord:
        spec = spec.model_copy(update={"owner": normalize_actor(spec.owner, "owner")})
        # Build the adapter once so a bad preset, flaw list, model id or effort fails at registration.
        build_adapter(AgentRecord(**spec.model_dump(), agent_id="probe", config_hash="",
                                  registered_at=self.env.clock()))
        agent_id = f"{spec.name}@{spec.version}"
        config_hash = canonical_hash(spec.config)
        existing = self.repo.get_agent(agent_id)
        if existing:
            same = (existing.config_hash == config_hash and existing.adapter == spec.adapter
                    and existing.environment == spec.environment)
            if not same:
                raise PolicyViolation(f"{agent_id} is already registered with a different configuration; "
                                      "bump the version instead of mutating a registered agent")
            return existing
        rec = AgentRecord(**spec.model_dump(), agent_id=agent_id, config_hash=config_hash,
                          registered_at=self.env.clock())
        self.repo.insert_agent(rec)
        self._audit(None, "agent-registry", "agent_registered", spec.owner, agent_id=agent_id,
                    config_hash=config_hash, environment=spec.environment.value)
        return rec

    def list_agents(self) -> list[AgentRecord]:
        return self.repo.list_agents()

    def register_suite(self, suite: EvalSuite, registered_by: str) -> dict[str, Any]:
        registered_by = normalize_actor(registered_by, "registered_by")
        check_suite_content(suite, reserved_ids=world_ids())
        digest = suite.content_hash()
        existing = self.repo.get_suite(suite.suite_id, suite.version)
        if existing:
            if existing[1] != digest:
                raise PolicyViolation(f"{suite.suite_id}@{suite.version} already exists with different content; "
                                      "eval suites are immutable per version, publish a new version")
            return {"suite_id": suite.suite_id, "version": suite.version, "content_hash": digest, "created": False}
        self.repo.insert_suite(suite, digest, registered_by)
        self._audit(None, "eval-suites", "suite_registered", registered_by, suite=f"{suite.suite_id}@{suite.version}",
                    content_hash=digest)
        return {"suite_id": suite.suite_id, "version": suite.version, "content_hash": digest, "created": True}

    def list_suites(self) -> list[dict[str, Any]]:
        return self.repo.list_suites()

    def authorize_security_testing(self, *, agent_id: str, approved_by: str, categories: list[str], reason: str,
                                   expires_in_hours: int = 24) -> Authorization:
        approved_by = normalize_actor(approved_by, "approved_by")
        agent = self.env.agent(agent_id)
        unknown = set(categories) - {c.value for c in SECURITY_CATEGORIES}
        if unknown:
            raise PolicyViolation(f"not security categories: {sorted(unknown)}")
        if not 1 <= expires_in_hours <= MAX_AUTHORIZATION_HOURS:
            raise PolicyViolation(f"authorizations last 1-{MAX_AUTHORIZATION_HOURS} hours")
        if agent.environment.value == "production":
            raise PolicyViolation("security testing cannot be authorized against production agents")
        if len(reason.strip()) < 10:
            raise PolicyViolation("a written reason (at least 10 characters) is required")
        ts = self.env.clock()
        auth = Authorization(authorization_id=str(uuid.uuid4()), agent_id=agent_id, categories=sorted(categories),
                             approved_by=approved_by, reason=reason, created_at=ts,
                             expires_at=ts + timedelta(hours=expires_in_hours))
        self.repo.insert_authorization(auth)
        self._audit(None, "policy-engine", "security_testing_authorized", approved_by, agent_id=agent_id,
                    categories=auth.categories, expires_at=auth.expires_at.isoformat())
        return auth

    # ------------------------------------------------------------ runs

    async def start_run(self, *, agent_id: str, suite_id: str, suite_version: str, requested_by: str,
                        idempotency_key: str | None = None, baseline_run_id: str | None = None) -> RunSummary:
        requested_by = normalize_actor(requested_by, "requested_by")
        if idempotency_key is not None and not 1 <= len(idempotency_key) <= MAX_IDEMPOTENCY_KEY:
            raise PolicyViolation(f"idempotency_key must be 1-{MAX_IDEMPOTENCY_KEY} characters")
        if idempotency_key:
            prior = self.repo.run_by_idempotency_key(idempotency_key)
            if prior:
                same = (prior["agent_id"], prior["suite_id"], prior["suite_version"]) == (
                    agent_id, suite_id, suite_version)
                if not same:
                    raise PolicyViolation("idempotency key was already used for a different run request")
                return self.get_run(prior["run_id"])
        # Validate before creating anything, so a refused request leaves no half-created run.
        self.env.agent(agent_id)
        self.env.suite(suite_id, suite_version)
        if baseline_run_id and self.repo.get_run(baseline_run_id) is None:
            raise LookupError(f"baseline run {baseline_run_id} not found")
        if baseline_run_id and self.repo.get_run_metrics(baseline_run_id) is None:
            raise PolicyViolation(f"baseline run {baseline_run_id} has not been scored yet; pick a scored run")
        check_run_allowed(self.env.agent(agent_id), self.env.suite(suite_id, suite_version),
                          self.repo.authorizations_for(agent_id), self.env.clock())

        run_id = str(uuid.uuid4())
        if not self.repo.create_run(run_id=run_id, agent_id=agent_id, suite_id=suite_id,
                                    suite_version=suite_version, requested_by=requested_by,
                                    idempotency_key=idempotency_key, baseline_run_id=baseline_run_id):
            prior = self.repo.run_by_idempotency_key(idempotency_key or "")
            assert prior is not None
            return self.get_run(prior["run_id"])
        self._audit(run_id, "workflow", "run_requested", requested_by, agent_id=agent_id,
                    suite=f"{suite_id}@{suite_version}")
        await run_primary(run_id, self.env, actor=requested_by)
        return self.get_run(run_id)

    async def resume_run(self, run_id: str, *, actor: str, overrides: dict[str, Any] | None = None) -> RunSummary:
        actor = normalize_actor(actor)
        run = self._run(run_id)
        if run["status"] == Status.COMPLETE:
            return self.get_run(run_id)
        if run["status"] == Status.NEEDS_REVIEW and self.repo.get_approval(run_id, GATE_STEP) is None:
            raise PolicyViolation("run is waiting at the release gate; record a decision with "
                                  "decide_release_gate first")
        self._audit(run_id, "workflow", "run_resumed", actor, from_status=run["status"])
        await run_primary(run_id, self.env, actor=actor, overrides=overrides)
        return self.get_run(run_id)

    async def decide_gate(self, *, run_id: str, approver: str, decision: str, reason: str) -> RunSummary:
        approver = normalize_actor(approver, "approver")
        run = self._run(run_id)
        gate = self._gate(run_id)
        if gate is None:
            raise PolicyViolation(f"run is {run['status']} and has not reached the release gate")
        check_gate_decision(gate, requested_by=run["requested_by"], approver=approver, decision=decision,
                            reason=reason)
        if run["status"] != Status.NEEDS_REVIEW:
            raise PolicyViolation(f"run is {run['status']}; only runs waiting at the gate take a decision")
        if not self.repo.insert_approval(run_id=run_id, gate=GATE_STEP, decision=decision, approver=approver,
                                         reason=reason, override=decision == "approve"):
            raise PolicyViolation("a gate decision has already been recorded for this run")
        self._audit(run_id, GATE_STEP, f"gate_{decision}d", approver, reason=reason,
                    gate_reasons=gate.reasons)
        return await self.resume_run(run_id, actor=approver)

    # ------------------------------------------------------------ reads

    def _run(self, run_id: str) -> dict[str, Any]:
        run = self.repo.get_run(run_id)
        if run is None:
            raise LookupError(f"run {run_id} not found")
        return run

    def _gate(self, run_id: str) -> GateDecision | None:
        gate = self.repo.artifacts(run_id).get(GATE_STEP)
        return GateDecision.model_validate(gate["payload"]["decision"]) if gate else None

    def get_run(self, run_id: str) -> RunSummary:
        run = self._run(run_id)
        arts = self.repo.artifacts(run_id)
        score = arts.get("Score traces", {}).get("payload")
        gate = arts.get(GATE_STEP, {}).get("payload")
        comparison = arts.get("Compare versions/models", {}).get("payload")
        monitor = arts.get("Monitor regressions", {}).get("payload")
        return RunSummary(
            run_id=run_id, status=run["status"], current_step=run["current_step"], agent_id=run["agent_id"],
            suite=f"{run['suite_id']}@{run['suite_version']}", requested_by=run["requested_by"], error=run["error"],
            steps=[StepView(step=s, done=s in arts, artifact_hash=arts.get(s, {}).get("content_hash"))
                   for s in PROJECT_STEPS],
            scorecard=score["scorecard"] if score else None,
            gate=GateDecision.model_validate(gate["decision"]) if gate else None,
            release_decision=release_decision(self.repo, run_id, gate),
            comparison={k: v for k, v in comparison.items() if k != "requested"} if comparison else None,
            requested_comparison=comparison.get("requested") if comparison else None,
            regression_alerts=monitor["alerts"] if monitor else [],
        )

    def get_artifact(self, run_id: str, step: str) -> dict[str, Any]:
        self._run(run_id)
        art = self.repo.artifacts(run_id).get(step)
        if art is None:
            raise LookupError(f"step {step!r} has no artifact for run {run_id}")
        return art

    def get_findings(self, run_id: str, severity: str | None = None) -> list[Finding]:
        self._run(run_id)
        found = self.repo.findings_for(run_id)
        return [f for f in found if severity is None or f.severity == severity]

    def get_trace(self, trace_id: str) -> dict[str, Any]:
        found = self.repo.get_trace(trace_id)
        if found is None:
            raise LookupError(f"trace {trace_id} not found")
        trace, stored_hash = found
        recomputed = canonical_hash(trace.model_dump(mode="json"))
        return {"trace": trace.model_dump(mode="json"), "content_hash": stored_hash,
                "integrity_ok": recomputed == stored_hash, "evidence_id": stable_id("evidence", trace_id)}

    def audit_trail(self, run_id: str) -> list[dict[str, Any]]:
        self._run(run_id)
        return self.repo.audit_trail(run_id)

    def regression_report(self, agent_name: str, suite_id: str, suite_version: str | None = None) -> dict[str, Any]:
        """History per suite version (pass rates on different case sets aren't comparable)."""
        history = self.repo.metrics_history(agent_name, suite_id, suite_version, limit=50)
        by_version: dict[str, list[dict[str, Any]]] = {}
        for h in history:
            by_version.setdefault(h["suite_version"], []).append({
                "run_id": h["run_id"], "agent_id": h["agent_id"], "suite_version": h["suite_version"],
                "pass_rate": h["pass_rate"], "failing_cases": h["scorecard"]["failing_cases"],
                "created_at": h["run_created_at"].isoformat()})
        runs = [r for rows in by_version.values() for r in rows]
        alerts = [f"{version}: {a}" for version, rows in sorted(by_version.items()) for a in regression_alerts(rows)]
        return {"agent_name": agent_name, "suite_id": suite_id, "suite_version": suite_version, "runs": runs,
                "alerts": alerts}

    # ------------------------------------------------------------ ad-hoc failure injection

    async def inject_failure(self, *, run_id: str, case_id: str, tool: str, failure_type: str, requested_by: str,
                             destructive: bool = False) -> CaseScore:
        requested_by = normalize_actor(requested_by, "requested_by")
        run = self._run(run_id)
        agent = self.env.agent(run["agent_id"])
        check_failure_injection(agent, destructive=destructive)
        if "Run baseline" not in self.repo.artifacts(run_id):
            raise PolicyViolation("run a baseline before injecting ad-hoc failures")
        suite = self.env.suite(run["suite_id"], run["suite_version"])
        try:
            case = suite.case(case_id)
        except KeyError:
            raise LookupError(f"case {case_id!r} is not in {suite.suite_id}@{suite.version}") from None
        plan = FailurePlan(case_id=case_id, tool=tool, failure_type=FailureType(failure_type))
        self.env.authorize(agent, suite, [case_id])  # same authorization rules as a full run, checked now
        adapter: AgentAdapter = self.env.adapter_factory(agent)
        trace = await run_case(adapter, agent, suite, case, run_id=run_id, phase="adhoc", repeat=0, failure=plan)
        # Every ad-hoc probe is its own piece of evidence, even when repeated with identical parameters.
        trace = trace.model_copy(update={"trace_id": str(uuid.uuid4())})
        self.repo.save_trace(trace)
        self._audit(run_id, "failure-injector", "failure_injected", requested_by, case_id=case_id, tool=tool,
                    failure_type=failure_type, trace_id=trace.trace_id)
        return score_trace(case, suite, trace, Sandbox.for_case(case).sensitive_by_owner())

    # ------------------------------------------------------------ run report (for resources/prompts)

    def run_report(self, run_id: str) -> str:
        s = self.get_run(run_id)
        lines = [f"# Eval run {s.run_id}", "", f"- Agent: `{s.agent_id}`", f"- Suite: `{s.suite}`",
                 f"- Status: **{s.status}** (release decision: **{s.release_decision}**)"]
        if s.error:
            lines.append(f"- Error: {s.error}")
        if s.scorecard:
            c = s.scorecard
            lo, hi = c["pass_rate_ci95"]
            lines += ["", "## Scorecard", f"- Cases passed: {c['n_passed']}/{c['n_cases']} "
                      f"(pass rate {c['pass_rate']:.2f}, 95% CI {lo:.2f}-{hi:.2f})",
                      f"- Failures: {c['critical_failures']} critical, {c['major_failures']} major, "
                      f"{c['minor_failures']} minor", f"- Repeatability: {c['repeatability']:.2f}",
                      f"- Recovery rate: {c['recovery_rate']}",
                      f"- p95 latency: {c['p95_latency_ms']} ms; total cost ${c['total_cost_usd']:.4f}",
                      "", "| dimension | pass rate |", "|---|---|"]
            lines += [f"| {d} | {r:.2f} |" for d, r in c["dimension_pass_rates"].items()]
        if s.gate:
            lines += ["", f"## Gate: {s.gate.outcome.value} ({s.gate.policy_version})"]
            lines += [f"- {r}" for r in s.gate.reasons]
        for title, cmp_ in (("Gating comparison", s.comparison), ("Requested comparison (informational)",
                                                                   s.requested_comparison)):
            if not cmp_ or not cmp_.get("baseline_run_id"):
                continue
            lines += ["", f"## {title} vs {cmp_['baseline_run_id']} ({cmp_.get('baseline_agent_id')}, "
                      f"{cmp_.get('baseline_suite')})",
                      f"- Comparable: {cmp_['comparable']}; pass-rate delta: {cmp_['pass_rate_delta']:+.2f} "
                      f"(significant: {cmp_['significant']})",
                      f"- Regressions: {cmp_['regressions'] or 'none'}", f"- Fixes: {cmp_['fixes'] or 'none'}"]
        if s.regression_alerts:
            lines += ["", "## Regression alerts"] + [f"- {a}" for a in s.regression_alerts]
        findings = self.repo.findings_for(run_id)
        if findings:
            lines += ["", "## Findings (evidence ids in brackets)"]
            for f in findings:
                ev = ", ".join(e.evidence_id[:8] for e in f.evidence)
                lines.append(f"- **{f.severity}** {f.statement} [{ev}]")
        return "\n".join(lines)


# ------------------------------------------------------------ bootstrap


def bundled_suites() -> list[EvalSuite]:
    folder = resources.files("agent_eval_redteam.fixtures").joinpath("suites")
    return [EvalSuite.model_validate(json.loads(p.read_text(encoding="utf-8")))
            for p in sorted(folder.iterdir(), key=lambda p: p.name) if p.name.endswith(".json")]


REFERENCE_AGENTS = [
    AgentSpec(name="support-bot", version="1.0.0", adapter=AdapterKind.SCRIPTED, owner="platform-team",
              config={"preset": "hardened"}),
    AgentSpec(name="support-bot", version="1.1.0-rc1", adapter=AdapterKind.SCRIPTED, owner="platform-team",
              config={"preset": "flaky-candidate"}),
    AgentSpec(name="support-bot-naive", version="0.9.0", adapter=AdapterKind.SCRIPTED, owner="platform-team",
              config={"preset": "naive"}),
]


def bootstrap(platform: EvalPlatform) -> None:
    """Idempotently load bundled suites and the reference (control) agents."""
    for suite in bundled_suites():
        platform.register_suite(suite, registered_by="bootstrap")
    for spec in REFERENCE_AGENTS:
        platform.register_agent(spec)
