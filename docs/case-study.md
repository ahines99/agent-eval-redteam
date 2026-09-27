# Case study: making agent evaluations reviewable

## Problem and intended user

An agent can answer a happy-path question correctly and still leak data, misuse a tool,
invent a citation or behave badly when a dependency fails. A terminal demo alone also
leaves a reviewer asking which version ran, what evidence supports a verdict, and whether
an interrupted evaluation can safely continue.

This project is for an engineer or reviewer comparing agent versions before a release.
It turns a suite of declared expectations into stored traces, deterministic findings and
a release recommendation that another person can inspect. Its scope is a synthetic
support sandbox and an offline portfolio demonstration, with optional model and shared
server integrations.

## What the project contributes

The implementation combines a versioned case format, a tool sandbox, a manual agent
tool-use loop, deterministic scoring, persistent workflow state and a typed MCP interface.
The notable work is in the connections between them: an interrupted run must retain its
evidence, a changed scorer must not silently become an old baseline, and a review gate
must still require a decision after a crash.

Development and audit remediation were AI-assisted. The repository records the design,
tests and limitations so reviewers can assess the resulting implementation directly.
The scripted controls and suite were developed together; their agreement is engineered
test evidence, not independent human validation or a measurement of a live model's quality.

## Engineering decisions

| Decision | Benefit | Tradeoff |
|---|---|---|
| Deterministic scorers | A verdict can be reproduced from a trace and declared expectations | Phrase and pattern checks do not understand arbitrary meaning |
| Manual tool-use loop for Claude | Explicit tool boundary, trace capture and failure classification | Provider-specific request behavior needs live verification |
| SQLite first, SQLAlchemy repository | Reviewers can run the whole demo without infrastructure | PostgreSQL behavior must be tested separately; portability is not proof |
| Explicit state machine | Small, inspectable pause/resume and checkpoint logic | No scheduler or distributed workflow service is provided |
| MCP as the capability interface | CLI, tests and clients share domain services | The transport still needs concrete identity/access configuration when shared |
| Synthetic sandbox | Failure and adversarial cases have no real email/refund/delete effects | Results depend on how well the sandbox represents a target agent's environment |

The demo uses three controls with intentional differences. The hardened control passes
the current 35-case suite; the flaky candidate loses citations and requires review; the
naive control triggers critical failures and cannot be approved. A failed lookup tests
graceful recovery. These are known-control results, not a competitive benchmark.

## What the audit changed

The audit found that broad completion claims hid important edge cases. Concurrent
resumes could duplicate work, a crash around the gate could strand or bypass review,
partial evidence could produce misleading scores, and a bounded baseline search could
forget an older accepted run. Scoring and disclosure checks also had specific false
passes and false failures.

The repairs added leased workflow ownership and fenced writes, atomic checkpoints,
complete evidence manifests, stronger integrity checks and comparison identities that
include suite, sandbox world, scorer and gate policy. New suite assertions check successful
retrieval, message content and required clarification rather than relying on descriptive
policy prose. The [resolution record](audits/2026-09-27/RESOLUTION.md) links the detailed
findings and verification; the [architecture](architecture.md) describes the mechanisms.

## Evidence and practical limits

Start with the [browser walkthrough](demo.html), then run the offline demo or the
[real MCP client walkthrough](mcp-quickstart.md). Inspect a report, follow a finding to its
trace, and compare the gate reason to the declared case expectations. The repository also
contains migration, restart, authenticated-transport and scoring-regression tests.

Verification status belongs to the release evidence and actual CI logs. A workflow file,
an optional integration test or an implemented adapter is not proof that its external
service ran. The current documentation distinguishes local checks from PostgreSQL,
container, remote CI, live-model and deployed-service evidence.

There is no independent held-out human accuracy claim. Wilson intervals summarize this
case set, which is not production traffic. Content hashes do not defeat a database
administrator who can rewrite hashes too. A crash after a provider response but before
trace persistence can repeat that call; scored cost thresholds do not cap API spending.

## Lessons

The most useful evaluation checks are executable assertions tied to the behavior a reviewer
cares about. A prose rule such as “email the policy” needs assertions about the recipient,
content and successful tool result. Recovery must include whether a planned failure
actually occurred, and a green aggregate must require all expected evidence.

Persistence also needs precise claims. Reusing saved results is feasible; exactly-once
billing across an external API and a local database is a different guarantee. Keeping
that distinction visible makes this project more useful to a reviewer than a broader
claim that the workflow simply “survives every failure.”
