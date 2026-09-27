# Current implementation handoff - 0.2.0 (2026-09-27)

For the latest portfolio completion state and verification, see [docs/VERIFICATION.md](docs/VERIFICATION.md).

This section supersedes all status statements, acceptance checkboxes, counts and skeletons
in the historical material below. The earlier plan and audit notes are preserved as history,
not as current instructions or proof that every possible defect has been eliminated.

## Implemented and locally verified

- Packaged Python CLI and typed MCP surface; four distinct procedural skills.
- Versioned synthetic suites: current `support-core@1.2.0` has 35 cases. Published 1.0.0 and
  1.1.0 JSON files are unchanged. New content/success/clarification assertions are explicit.
- Deterministic scoring/1.2, gate-policy/1.2 and schema label 1.2; complete trace manifests,
  evidence/artifact hash checks and metric consistency checks before release decisions.
- Atomic checkpoints, expiring ownership leases, fenced workflow writes and recovery of
  unresolved review gates. Persisted work is reused; a crash before trace persistence can
  repeat an external provider call. No exactly-once billing guarantee is made.
- Baselines and monitoring respect suite/world/scorer/gate identity. Prior blocks bind the
  agent version across suites; caller-provided baselines remain informational.
- Authorization immediately before each case adapter invocation; benign shared world;
  expanded disclosure checks; bounded suite/run/HTTP admission.
- Optional authenticated HTTP: hashed service tokens, server-derived actors, scopes and
  separate tenant databases. Stdio is locally trusted. TLS and operator provisioning remain
  deployment responsibilities; the token option is not an OIDC login system.
- Alembic initial/lease migrations; dependency lock and audit tooling; CI definitions;
  Docker/Compose; MIT license; opt-in OpenTelemetry export with filtered attributes.
- SQLite migration tests, actual stdio process restart and authenticated HTTP socket tests,
  repeated persistent demo, build and installed-wheel smoke. Locked Python 3.12 and 3.14
  environments each passed 242 tests with one PostgreSQL integration test skipped in the
  final local verification; measured Python 3.12 line coverage was 95.43%.
- Actual local terminal recording at [docs/demo.cast](docs/demo.cast), plus a three-minute
  narration script. The recording preserves real short execution timing; it is not a
  narrated three-minute video.
- Subsequent Linux validation executed a real Docker image build and behavioral smoke,
  plus PostgreSQL 17.11 backend contracts. Earlier counts above predate this portfolio
  finalization pass; see the latest resolution/release record.

## Remaining validation and accepted limitations

- Remote CI and an operational shared deployment require separate release-specific evidence.
- The first live Sonnet 5 run is preserved in docs/evidence/live-validation.json: 1/10
  cases passed under existing rules, no critical findings, review gate, $0.10417 estimated
  token cost. Scored cost thresholds are not a provider spending cap.
- Signing/HMAC or external evidence anchoring remains explicitly deferred. A database
  administrator can rewrite both content and hashes.
- Production deployment still needs TLS, secret distribution/rotation, separate database
  provisioning, backup/restore validation and real-data retention/encryption decisions.
- Phrase checks, PII detection and security classification are bounded heuristics. Scripted
  controls establish behavior on declared cases, not general model safety or production quality.
- A narrated video and publication are optional follow-up; nothing has been published.

Current references: [README](README.md), [architecture](docs/architecture.md),
[data contracts](docs/data_contracts.md), [threat model](docs/threat_model.md),
[deployment](docs/deployment.md), [audit resolution](docs/audits/2026-09-27/RESOLUTION.md).

---

# Historical plan and prior audit notes (superseded)

Everything below records the pre-0.2.0 plan or earlier implementation state. Old checked
acceptance items and claims that findings were fixed describe that earlier review; consult
the current status and resolution record above for present evidence and limitations.

# 14. Agent Evaluation and Red-Team Platform

> **Revision 2026-09-23 (b): audit remediation.** A three-part audit (correctness, security, requirements)
> reported 32 findings: 4 high, 12 medium, 16 low. Some overlap between auditors. It also listed 11 test
> gaps, and found that this document overstated completion. All of them are fixed on branch
> `audit-fixes`, one commit per batch, each finding with a regression test. The main behavioural changes
> are:
>
> - **Authorization:** decided from case *content*, not the category label, and re-checked before every
>   agent call.
> - **Gating baseline:** always the last accepted run of the same agent on the same *suite version*.
>   Caller-chosen baselines are informational only.
> - **Blocked versions stay blocked** on every suite.
> - **Actor identities** are normalised before separation of duties is checked.
> - **Synthetic-PII checks** are strict and separator-agnostic.
> - **Scorers:** matching is whole-phrase, abnormal stops are scored, and email recipients may only receive
>   their own data.
> - **API errors** are classified as transient, harness or agent.
> - **New suite `support-core@1.1.0`** adds the duplicate-entity, contradictory-evidence and missing-field
>   cases this plan required.
> - **Versions:** `gate-policy/1.1` and `scoring/1.1`, and schema version 1.1 stamped on traces and
>   artifacts.
>
> Deferred by decision: signed (HMAC) hashes; see `docs/threat_model.md`.
>
> **Revision 2026-09-23 (a): feasibility pass.** The first vertical slice is implemented. The code skeletons
> further down are the original plan and are superseded by the code in `src/agent_eval_redteam/`. This
> section records where the plan changed and why.
>
> | Original plan | Problem | Resolution |
> |---|---|---|
> | Code under bare `src/` (`from src.mcp_server import mcp`), no build backend | `pip install .` would have installed top-level packages named `domain` and `workflows`; imports only worked from the repo root | Installable package `src/agent_eval_redteam/` (hatchling), console script `agent-eval` |
> | No system under test | An eval platform with nothing to evaluate can't demo or be tested | `AgentAdapter` protocol with deterministic **control agents** (known-good, known-bad, flaky) plus a live **Claude** adapter; all tools run in a **sandbox** so attacks and failures never reach real systems |
> | PostgreSQL required | Blocks the one-click local demo (no Docker on the dev box) | SQLAlchemy Core schema: SQLite by default, PostgreSQL via `DATABASE_URL` (`postgres` extra) |
> | fastapi, uvicorn, httpx, structlog, psycopg as hard deps | Unused; MCP SDK v2 already provides the ASGI app and HTTP client | Trimmed to mcp, pydantic, sqlalchemy, opentelemetry-api; optional extras `claude`, `postgres`, `dev` |
> | pytest-asyncio `asyncio_mode=auto` alongside `@pytest.mark.anyio` | Two async plugins fighting over the same tests | anyio only (`-p no:asyncio`), matching the MCP SDK |
> | "Compare versions" and "Monitor regressions" as linear steps in one run | Both need run history that didn't exist | `run_metrics` table; comparison uses an explicit baseline or the last *accepted* run; monitoring alerts on drops vs the history median and on recurring failures |
> | Approval boundaries as a string in a resource | Not enforced | Enforced server-side and fail-closed: production, authorization and gate rules in `domain/policies.py`, synthetic-PII validation in `domain/pii.py`, suite immutability in `domain/services.py` |
> | LLM-based scoring implied by "factuality/citation quality" | Non-reproducible verdicts | 10 deterministic per-trace dimensions: the mission's list with "repeatability" computed as a scorecard aggregate instead, plus calibration (abstaining when evidence is insufficient). The only model is the agent under test |
> | Four identical placeholder Skills | Not "dynamically useful" | Each Skill has its own procedure, decision tables and tool names; `security-redteam` ships a case-authoring reference |
>
> **Acceptance status (after remediation):** see the checklist at the end of this file. Each item now names
> the test that proves it. Test suite: 156 tests, 96% line coverage. Milestone 5 items are listed as open
> there.

## Implementation-agent handoff

### Mission
Test AI agents for factuality, tool correctness, permission adherence, prompt injection resistance, PII leakage, citation quality, latency, cost, repeatability, and recovery.

### Definition of done
A credible MVP is not a chat demo. It must expose typed MCP capabilities, persist workflow state, preserve evidence/provenance, stop at approval boundaries, include at least one Agent Skill, and ship with integration tests. The demonstration should show a complete end-to-end run with both a successful path and a controlled failure/review path.

### Non-goals for v0.1
- Do not build autonomous irreversible actions.
- Do not let the LLM become the system of record.
- Do not hide deterministic calculations inside prompts.
- Do not create a generalized multi-agent framework before the primary workflow works.
- Do not optimize UI before evidence, contracts, and tests are stable.


## Reference architecture

Use a four-layer design:

1. **Data and capability layer**: source systems, deterministic calculation services, document/evidence stores, and domain APIs.
2. **MCP boundary**: small servers that expose typed tools, resources, and user-selectable prompts. MCP is the capability contract, not the business logic layer.
3. **Skill layer**: Agent Skills package procedural knowledge, review checklists, reference material, and scripts. A Skill should teach *how to perform the work*, not become a hidden database or hard-coded workflow engine.
4. **Workflow/orchestration layer**: state machine or durable workflow service coordinates steps, approvals, retries, parallel branches, and audit events.

**Why this split**
- Deterministic services own arithmetic, portfolio math, joins, permissions, and irreversible side effects.
- MCP gives the model a standardized, inspectable capability surface.
- Skills keep domain operating procedures version-controlled and progressively disclosed.
- The workflow engine owns state and recovery, preventing the LLM conversation itself from becoming the source of truth.

For local development use MCP over stdio or in-process tests. For deployed servers use Streamable HTTP behind authenticated ASGI infrastructure. Prefer the current stable Python MCP SDK v2 and Python 3.12+.



## Recommended stack

- Python 3.12
- `uv` for environment/package management
- MCP Python SDK v2
- FastAPI/Starlette only where non-MCP HTTP endpoints are needed
- Pydantic v2 for contracts
- PostgreSQL for operational state and audit logs
- pgvector or a managed vector store only where semantic retrieval is genuinely required
- Neo4j only for graph-heavy projects, not by default
- DuckDB/Polars for local analytical execution
- dbt for warehouse transformations where applicable
- Temporal, Prefect, or a small explicit state machine for durable workflows. Start with a simple state machine unless retries, timers, or distributed workers justify a workflow engine.
- OpenTelemetry for traces and metrics
- pytest + MCP in-process client tests
- Docker for reproducible deployment

Do not make the agent framework the center of the repository. Keep orchestration behind interfaces so Claude, another model, or a deterministic job can drive the same domain services.


## Project architecture

### MCP capability boundaries
- `agent-registry-mcp`: expose the smallest governed capability surface needed for agent registry.
- `eval-runner-mcp`: expose the smallest governed capability surface needed for eval runner.
- `trace-store-mcp`: expose the smallest governed capability surface needed for trace store.
- `failure-injector-mcp`: expose the smallest governed capability surface needed for failure injector.
- `policy-engine-mcp`: expose the smallest governed capability surface needed for policy engine.

**Decision:** prefer multiple narrow MCP servers only when capabilities have distinct authorization, lifecycle, or deployment needs. During MVP development, it is acceptable to expose them from one process behind separate modules. Split services later when operational boundaries justify it.

### Agent Skills
- `agent-evaluation`: procedural knowledge for agent evaluation.
- `security-redteam`: procedural knowledge for security redteam.
- `tool-use-eval`: procedural knowledge for tool use eval.
- `reliability-eval`: procedural knowledge for reliability eval.

**Decision:** Skills should contain checklists, decision rules, examples, and reference links. They should not embed secrets or act as mutable state. This follows the progressive-disclosure model: frontmatter advertises the Skill, the body provides procedure, and `references/` or `scripts/` provide deeper material only when needed.

### Primary workflow
1. **Register system**
2. **Load eval suite**
3. **Run baseline**
4. **Inject failures**
5. **Score traces**
6. **Compare versions/models**
7. **Gate release**
8. **Monitor regressions**

### Human approval boundaries
- No destructive tests against production
- Synthetic PII for exfiltration tests
- Explicit authorization for security tests
- Version every eval suite

## Data and state model

Use PostgreSQL as the workflow source of truth. Minimum tables:

```sql
create table workflow_runs (
  run_id uuid primary key,
  project_type text not null,
  status text not null,
  current_step text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  requested_by text not null
);

create table evidence (
  evidence_id uuid primary key,
  run_id uuid references workflow_runs(run_id),
  source_uri text not null,
  source_type text not null,
  as_of timestamptz,
  content_hash text not null,
  metadata jsonb not null default '{}'::jsonb
);

create table findings (
  finding_id uuid primary key,
  run_id uuid references workflow_runs(run_id),
  finding_type text not null,
  statement text not null,
  confidence text not null,
  assumptions jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now()
);

create table finding_evidence (
  finding_id uuid references findings(finding_id),
  evidence_id uuid references evidence(evidence_id),
  relation text not null,
  primary key (finding_id, evidence_id, relation)
);

create table audit_events (
  event_id bigserial primary key,
  run_id uuid references workflow_runs(run_id),
  step text not null,
  actor text not null,
  event_type text not null,
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);
```

```python
# src/domain/models.py
from __future__ import annotations
from datetime import datetime
from enum import StrEnum
from typing import Any
from pydantic import BaseModel, Field

class Confidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

class EvidenceRef(BaseModel):
    source_id: str
    uri: str
    retrieved_at: datetime
    as_of: datetime | None = None
    excerpt_hash: str | None = None

class Finding(BaseModel):
    finding_id: str
    title: str
    statement: str
    confidence: Confidence
    evidence: list[EvidenceRef] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

class AuditEvent(BaseModel):
    run_id: str
    step: str
    event_type: str
    created_at: datetime
    actor: str
    payload: dict[str, Any] = Field(default_factory=dict)
```


### Project-specific contracts

```python
# src/domain/project_models.py
from datetime import datetime
from pydantic import BaseModel, Field
from .models import Confidence, EvidenceRef

class EvalCase(BaseModel):
    case_id: str
    category: str
    prompt: str
    expected_policy: str
    fixtures: dict = {}

class EvalResult(BaseModel):
    case_id: str
    passed: bool
    scores: dict[str, float]
    trace_id: str
    findings: list[str]

```

### Project-specific MCP tools

```python
# add to src/mcp_server.py
@mcp.tool()
def run_eval_suite(agent_id: str, suite_id: str, version: str) -> dict:
    return eval_runner.run(agent_id, suite_id, version)

@mcp.tool()
def inject_failure(run_id: str, failure_type: str) -> dict:
    return failure_lab.inject(run_id, failure_type, destructive=False)

```


## Repository skeleton

```text
agent-eval-redteam/
├── pyproject.toml
├── README.md
├── .env.example
├── docker-compose.yml
├── src/
│   ├── mcp_server.py
│   ├── domain/
│   │   ├── models.py
│   │   ├── project_models.py
│   │   ├── services.py
│   │   └── policies.py
│   ├── adapters/
│   │   ├── repositories.py
│   │   └── external.py
│   ├── workflows/
│   │   ├── base.py
│   │   └── primary.py
│   └── observability.py
├── skills/
│   ├── agent-evaluation/SKILL.md
│   ├── security-redteam/SKILL.md
│   ├── tool-use-eval/SKILL.md
│   ├── reliability-eval/SKILL.md
├── tests/
│   ├── test_mcp.py
│   ├── test_workflow.py
│   └── fixtures/
└── docs/
    ├── architecture.md
    ├── data_contracts.md
    └── threat_model.md
```

## Package skeleton

```toml
[project]
name = "agent-eval-redteam"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "mcp[cli]>=2,<3",
  "pydantic>=2.9",
  "fastapi>=0.115",
  "uvicorn>=0.30",
  "sqlalchemy>=2.0",
  "psycopg[binary]>=3.2",
  "httpx>=0.27",
  "structlog>=24.4",
  "opentelemetry-api>=1.27",
]

[project.optional-dependencies]
dev = ["pytest>=8", "pytest-asyncio>=0.24", "ruff>=0.7", "mypy>=1.12"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
```


## MCP server skeleton

```python
# src/mcp_server.py
from __future__ import annotations
from mcp.server import MCPServer
from pydantic import BaseModel, Field

mcp = MCPServer("Agent Evaluation and Red-Team Platform")

class Health(BaseModel):
    status: str
    version: str

@mcp.tool()
def healthcheck() -> Health:
    """Return service health for diagnostics."""
    return Health(status="ok", version="0.1.0")

@mcp.resource("project://policies")
def policies() -> str:
    """Human-readable operating and safety policies."""
    return "Read-only by default. Material actions require explicit approval."

@mcp.prompt()
def review_run(run_id: str) -> str:
    """Create a user-controlled review prompt for a workflow run."""
    return f"Review workflow run {run_id}. Separate facts, assumptions, and recommendations."

app = mcp.streamable_http_app()
```


## Workflow skeleton

```python
# src/workflows/base.py
from __future__ import annotations
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

class Status(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    NEEDS_REVIEW = "needs_review"
    COMPLETE = "complete"
    FAILED = "failed"

@dataclass
class RunState:
    run_id: str
    status: Status = Status.PENDING
    current_step: str | None = None
    artifacts: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

class Step(Protocol):
    name: str
    async def execute(self, state: RunState) -> RunState: ...

async def run_steps(state: RunState, steps: list[Step]) -> RunState:
    state.status = Status.RUNNING
    for step in steps:
        state.current_step = step.name
        try:
            state = await step.execute(state)
        except Exception as exc:
            state.errors.append(f"{step.name}: {exc}")
            state.status = Status.FAILED
            return state
        if state.status == Status.NEEDS_REVIEW:
            return state
    state.status = Status.COMPLETE
    return state
```


## Agent Skill skeleton

Create `skills/agent-evaluation/SKILL.md`:

```markdown
---
name: agent-evaluation
description: Use when the task requires the project's domain review procedure and evidence discipline.
---

# Objective
Produce a decision-ready output while preserving evidence, uncertainty, and human approval boundaries.

# Procedure
1. Read the relevant MCP resources before drawing conclusions.
2. Separate observations, calculations, assumptions, and recommendations.
3. Use deterministic tools for calculations.
4. Cite evidence identifiers for every material factual claim.
5. If evidence is insufficient, return `NEEDS_EVIDENCE` rather than guessing.
6. Escalate any material action to human approval.

# Output contract
- Summary
- Evidence-backed findings
- Assumptions
- Risks and counterarguments
- Recommended next actions
- Open questions
```


## Primary workflow implementation

```python
# src/workflows/primary.py
from dataclasses import dataclass
from .base import RunState, Status, run_steps

@dataclass
class FunctionalStep:
    name: str
    fn: callable

    async def execute(self, state: RunState) -> RunState:
        result = await self.fn(state)
        state.artifacts[self.name] = result
        return state

# Wire each project step to a domain service. The service returns structured data,
# not prose. A model-facing layer can summarize the structured artifacts later.
PROJECT_STEPS = ['Register system', 'Load eval suite', 'Run baseline', 'Inject failures', 'Score traces', 'Compare versions/models', 'Gate release', 'Monitor regressions']

async def run_primary(run_id: str, services) -> RunState:
    state = RunState(run_id=run_id)
    wired = []
    for name in PROJECT_STEPS:
        service = services.for_step(name)
        wired.append(FunctionalStep(name=name, fn=service.execute))
    return await run_steps(state, wired)
```

## Policy pattern

```python
# src/domain/policies.py
from pydantic import BaseModel

class ActionDecision(BaseModel):
    allowed: bool
    requires_human_approval: bool
    reason: str

def check_action(action: str, risk_tier: str, has_approval: bool) -> ActionDecision:
    if risk_tier in {"high", "critical"} and not has_approval:
        return ActionDecision(allowed=False, requires_human_approval=True,
                              reason="Material action requires explicit human approval")
    return ActionDecision(allowed=True, requires_human_approval=False, reason="Policy satisfied")
```

## Evaluation strategy

Build evaluation before polishing prompts. Minimum evaluation dimensions:

1. **Tool correctness:** selected the right capability and supplied valid arguments.
2. **Evidence fidelity:** material claims resolve to stored evidence.
3. **Calculation fidelity:** numeric outputs match deterministic reference implementation.
4. **Permission fidelity:** forbidden actions fail closed.
5. **Uncertainty calibration:** insufficient evidence becomes an explicit unknown.
6. **Recovery:** tool timeout, malformed source data, and partial source outage produce controlled behavior.
7. **Cost/latency:** trace per-run model and tool costs.

Create a golden dataset of at least 25 representative cases before calling the MVP complete. Add adversarial cases for prompt injection, stale data, duplicate entities, contradictory evidence, and missing required fields.

## Testing skeleton

```python
# tests/test_mcp.py
import pytest
from mcp import Client
from src.mcp_server import mcp

@pytest.mark.anyio
async def test_healthcheck():
    async with Client(mcp) as client:
        result = await client.call_tool("healthcheck", {})
        assert result.is_error is False
        assert result.structured_content["status"] == "ok"
```


Add tests for:
- each project-specific MCP tool
- authorization/approval rejection
- workflow pause/resume
- idempotent reruns
- provenance links
- deterministic calculation fixtures
- at least one injected dependency failure

## Observability

Every run should emit:
- `run_id`, `step`, `tool_name`, `model`, latency, token/cost estimate
- input/output schema version
- evidence IDs read
- approval events
- failure/retry events
- final outcome and whether a human changed the recommendation

Never log secrets or raw sensitive payloads. Store hashes/IDs where possible.

## Security and threat model

- Use service accounts with least privilege.
- Treat all retrieved text as untrusted data, never as executable instructions.
- Keep credentials outside Skills and prompts.
- Enforce tenant/company scope server-side, not in natural language.
- Use read-only data access for discovery/analysis by default.
- For uploaded documents, retain immutable originals and derived text separately.
- Add explicit egress rules for any tool that can send email, create tickets, place orders, or modify production data.

## Milestones

### Milestone 0: contracts and fixtures
- Define source schemas and output contracts.
- Build synthetic or public-data fixtures.
- Write golden tests before agent orchestration.

### Milestone 1: deterministic core
- Implement adapters and calculation services.
- Persist runs, evidence, findings, and audit events.
- Demonstrate the workflow without an LLM where possible.

### Milestone 2: MCP surface
- Expose narrow typed tools/resources/prompts.
- Test with an in-process MCP client.
- Add auth and tenant scoping before remote deployment.

### Milestone 3: Skills and model reasoning
- Add the first procedural Skill.
- Introduce model reasoning only at judgment/synthesis steps.
- Preserve structured inputs/outputs around every call.

### Milestone 4: approvals and recovery
- Pause at human review points.
- Add retries, timeout handling, and idempotency.
- Exercise failure injection.

### Milestone 5: demo and portfolio polish
- One-click local demo with seeded data.
- Architecture diagram and threat model.
- 3-minute recorded demo script.
- README section titled `Why this is not just a chatbot`.

## Acceptance checklist

Each item names the test(s) that prove it (files under `tests/`).

- [x] **Every step has a deterministic artifact, an audit event and a failure path.** This covers all eight:
      Register system, Load eval suite, Run baseline, Inject failures, Score traces, Compare versions/models,
      Gate release and Monitor regressions.
      - Artifacts and audit events: `test_every_step_leaves_a_hashed_artifact_and_audit_event`.
      - A controlled failure and resume for each step:
        `test_every_step_has_a_controlled_failure_path[...]` (parametrised over all eight).
      - Natural failure paths:
        - Register system: `test_agent_config_tampering_fails_the_run`.
        - Load eval suite: `test_suite_tampering_fails_closed`.
        - Run baseline: `test_resume_after_authorization_expiry_makes_no_agent_calls`,
          `test_bad_credentials_fail_the_run_without_blaming_the_agent`.
        - Inject failures: `test_inject_failures_step_fails_cleanly_on_a_harness_error`.
        - Score traces: `test_step_dependency_failure_retries_then_fails_then_resumes`,
          `test_scoring_step_fails_closed_without_traces`.
        - Compare versions/models: `test_explicit_baseline_must_be_scored`.
- [x] **Every material recommendation includes supporting evidence or explicitly says evidence is
      insufficient.**
      - Findings link to hashed trace evidence: `test_provenance_links_and_tamper_detection`.
      - Gate decisions list the finding ids behind them:
        `test_gate_decision_links_to_the_findings_behind_it`.
      - The `review_run` prompt requires `NEEDS_EVIDENCE`.
- [x] **All irreversible actions are disabled or human-approved.**
      - Privileged sandbox tools fail closed, even under failure injection.
      - Destructive injection is refused.
      - The release gate records a human decision and deploys nothing.
      - Tests: `test_privileged_tools_fail_closed_even_under_injection`,
        `test_destructive_injection_is_refused`.
- [x] **MCP tools have typed schemas and integration tests.** All 14 tools, 4 resources and 3 prompts are
      exercised through the in-process MCP client (`test_mcp.py`, `test_mcp_surface.py`).
- [x] **At least one Skill is dynamically useful and not just duplicate prompt text.** The four Skills have
      distinct procedures and decision tables, and they name only tools, fields and rules that exist
      (re-checked in the audit).
- [x] **All arithmetic/financial/statistical calculations have deterministic tests.** Wilson interval,
      percentile, `aggregate`, `compare`, regression alerts, and cost estimation (`test_calculations.py`,
      `test_policies_and_stats.py`).
- [x] **The demo can survive one injected tool failure.**
      - Demo step 4.
      - Sandbox failure plans in every run.
      - Harness failures: `test_overloaded_api_is_retried_not_scored`,
        `test_partial_baseline_is_resumed_without_duplicates`.
- [x] **Golden dataset of at least 25 cases, including adversarial cases** for prompt injection, stale
      data, duplicate entities, contradictory evidence and missing required fields. That's
      `support-core@1.1.0` with 35 cases (`test_suite_110_adds_the_spec_adversarial_cases`,
      `test_controls_on_suite_110`).
- [x] **Observability.**
      - Every run records `run_id`, step, tool, model, latency, tokens and cost in traces and spans.
      - Schema version is on traces and audit events; the evidence ids that were read are recorded.
      - Approval, failure and retry events are audited.
      - Test: `test_schema_scoring_version_and_evidence_reads_are_audited`.

Not met (security section): least-privilege service accounts and tenant scoping. There is no
authentication layer yet, so these depend on the deployment decision recorded in `docs/threat_model.md`.

Open (Milestone 5 polish):
- Dockerfile/compose (not verifiable on the dev machine, which has no Docker)
- a recorded 3-minute demo
- authentication in front of the HTTP transport
- Alembic migrations
- a first evaluation against the live Claude API

## First implementation-agent tasks

1. Scaffold the repository exactly as shown.
2. Implement Pydantic contracts and PostgreSQL migrations.
3. Implement one adapter using fixtures, not live credentials.
4. Implement the primary deterministic service.
5. Expose only 2-4 MCP tools for the first vertical slice.
6. Create `agent-evaluation` Skill.
7. Write five golden integration tests.
8. Run the complete workflow on fixture data.
9. Add the approval gate.
10. Only then connect additional sources or models.

## Handoff note to the coding agent
Do not broaden scope until the first vertical slice is demonstrably correct, auditable, and restartable. Prefer boring deterministic code over agent autonomy. Every time a model is introduced, document why a deterministic rule is insufficient and define an evaluation for that model-dependent decision.
