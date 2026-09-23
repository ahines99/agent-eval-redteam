# Threat model

## Assets
- Evaluation integrity: scores, findings and gate decisions people rely on to release agents.
- The approval boundary: nobody ships a blocked or unreviewed agent through this platform.
- Data: fixture PII (synthetic by rule), traces (may contain model output), credentials for live models.

## Actors
- **Operator** (runs evals via MCP/CLI), **approver** (records gate decisions and security authorizations).
- **Agent under test**: untrusted. Its output may contain injected instructions or leaked data.
- **Driving model**: Claude or another client calling the MCP tools. It's also untrusted; it can be steered by
  trace text it reads.

## Threats and controls

| Threat | Control | Where |
|---|---|---|
| Driving model is prompt-injected by trace text into approving a release | Gate decisions need an approver ≠ requester and a written reason; critical failures can't be overridden; `review_run` prompt forbids calling `decide_release_gate` | `policies.check_gate_decision`, `mcp_server.review_run` |
| Red-teaming a production agent | Production agents can't be authorized; security categories and failure injection are refused for them | `policies.check_run_allowed`, `check_failure_injection` |
| Real PII used in exfiltration tests | Suites with non-synthetic PII are rejected at registration and re-checked at run time | `domain/pii.py`, `policies.check_suite_content` |
| Agent actually exfiltrates or deletes something | Agent only sees sandbox tools: email is queued, privileged tools fail closed, attacker domains are reserved TLDs | `adapters/sandbox.py` |
| Leaked values copied into reports | PII findings count leaked values and never quote them | `scoring.score_pii` |
| Silent suite or agent drift ("same version", different content) | Immutable versions; content and config hashes re-verified at run time | `services.register_*`, `primary.register_system/load_eval_suite` |
| Tampering with stored traces to change a verdict | Trace and evidence hashes; `get_trace` reports `integrity_ok` | `repositories.save_trace`, `services.get_trace` |
| Duplicate or replayed runs | Idempotency keys; deterministic ids; one decision per gate | `repositories`, `approvals` unique key |
| Harness outage scored as agent failure (or the reverse) | Adapters declare `infrastructure_errors`, which are retried and never scored | `primary.run_case` |
| Model fallback hides which model was evaluated | Refusal fallbacks disabled for evaluated Claude agents; refusals recorded as outcomes | `claude_agent.py` |
| Secrets in Skills, prompts or logs | Credentials come only from the environment/SDK profile; spans carry ids and hashes only | `observability.py`, `skills/` |

## Known gaps (accepted for v0.1)
- **No authentication or identity on the MCP server.** `requested_by` and `approver` are caller-asserted
  strings, so separation of duties is only as strong as the identity behind them. Before any shared
  deployment, run the Streamable HTTP app behind an authenticating proxy (OIDC) and derive actor identity
  from the token server-side, never from tool arguments.
- **No per-tool authorization.** Anyone who can call the server can call `authorize_security_testing`.
  Split that tool into a separate server (or add scopes) when roles diverge.
- Traces store raw agent output. With synthetic fixtures that's acceptable; with real sandboxes, add
  retention limits and encryption at rest.
- Resource-exhaustion limits (max cases × repeats per run, concurrent runs) aren't enforced yet.
