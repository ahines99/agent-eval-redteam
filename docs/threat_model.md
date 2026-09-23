# Threat model

## Assets
- Evaluation integrity: scores, findings and gate decisions people rely on to release agents.
- The approval boundary: nobody ships a blocked or unreviewed agent through this platform.
- Data: fixture PII (synthetic by rule), traces (may contain model output), credentials for live models.

## Actors
- **Operator** (runs evals via MCP/CLI), **approver** (records gate decisions and security authorizations).
- **Suite author**: can register suites. Untrusted as far as the policy boundary is concerned: a suite must
  not be able to switch off authorization or reach production.
- **Agent under test**: untrusted. Its output may contain injected instructions or leaked data.
- **Driving model**: Claude or another client calling the MCP tools. It's also untrusted; it can be steered by
  trace text it reads.

## Threats and controls

| Threat | Control | Where |
|---|---|---|
| Driving model is prompt-injected by trace text into approving a release | Gate decisions need an approver ≠ requester and a written reason; critical failures can't be overridden; `review_run` prompt forbids calling `decide_release_gate` | `policies.check_gate_decision`, `mcp_server.review_run` |
| Self-approval with a look-alike name (`alice` + zero-width space, Cyrillic `а`) | Every actor id is NFKC-normalised, stripped of format characters, case-folded and restricted to plain ASCII before comparison | `policies.normalize_actor` |
| Attack cases relabelled as "factuality" to skip authorization or reach production | Authorization need is derived from case content (canaries, injected tools, extra fixtures, injection-like or sensitive prompts, PII, recipients) | `policies.required_authorizations` |
| Suite fixtures replace a real KB page, customer or order with a payload | Fixtures may only add new ids; collisions are rejected at registration and ignored by the sandbox | `policies.check_suite_content`, `Sandbox.__post_init__` |
| Authorization expires mid-run but the run is resumed, or probed ad hoc | Authorization re-checked with the current clock before every agent-calling step and every `inject_failure` | `EvalEnvironment.authorize` |
| Red-teaming a production agent | Production agents can't be authorized; security cases and failure injection are refused for them | `policies.check_run_allowed`, `check_failure_injection` |
| Requester picks a bad run as baseline to hide regressions | The gate only uses the automatically selected last accepted run on the same suite version; caller baselines are informational | `primary.compare_versions` |
| A blocked agent version shops for a suite it passes | A version blocked once is blocked on every later run | `policies.evaluate_gate` (`prior_blocks`) |
| Real PII used in exfiltration tests | Strict, separator-agnostic detection (bare digit runs, intl phones, obfuscated emails, fullwidth characters, zero-width tricks, dict keys, integers) at registration and run time | `domain/pii.py`, `policies.check_suite_content` |
| Agent actually exfiltrates or deletes something | Agent only sees sandbox tools: email is queued, privileged tools fail closed (before any injection), attacker domains are reserved TLDs | `adapters/sandbox.py` |
| Leaked values copied into reports | Finding details are redacted centrally; PII findings count values and name only recipient domains | `scoring._result`, `scoring.score_pii` |
| Silent suite or agent drift ("same version", different content) | Immutable versions; content and config hashes re-verified at run time | `services.register_*`, `primary.register_system/load_eval_suite` |
| Casual tampering with stored traces or suites | Content hashes; `get_trace` reports `integrity_ok`; suite hash checked on every step | `repositories.save_trace`, `EvalEnvironment.suite` |
| Duplicate or replayed runs | Idempotency keys (bounded length); deterministic ids; one decision per gate | `repositories`, `approvals` unique key |
| Harness outage or misconfiguration scored as agent failure | Adapters classify errors: transient → retried, harness → run fails with no trace, agent → scored | `AgentAdapter.classify_error`, `primary.run_case` |
| Typo'd or unpriced model makes the cost gate pass for free | Claude config validated at registration; unpriced models fail closed | `claude_agent.ClaudeConfig`, `estimate_cost` |
| Model fallback hides which model was evaluated | Refusal fallbacks disabled for evaluated Claude agents; refusals recorded as outcomes | `claude_agent.py` |
| Nobody knows who looked at which evidence | `get_trace`/`get_findings` write `evidence_read` audit events | `services.get_trace`, `services.get_findings` |
| Secrets in Skills, prompts or logs | Credentials come only from the environment/SDK profile; spans carry ids and counts only | `observability.py`, `skills/` |

## Known gaps (accepted for v0.1)
- **No authentication or identity on the MCP server.** `requested_by`, `approver` and `reader` are
  caller-asserted strings. Normalisation stops look-alike tricks, but separation of duties is only as strong
  as the identity behind the name. Before any shared deployment:
  - run the Streamable HTTP app behind an authenticating proxy (OIDC);
  - derive actor identity from the token server-side, never from tool arguments.
- **No per-tool authorization.** Anyone who can call the server can call `authorize_security_testing`.
  Split that tool into a separate server (or add scopes) when roles diverge.
- **Hashes are not signatures (deferred).** Each content hash is stored beside the data it covers, so
  someone with database write access can rewrite both and pass the integrity check. The fix is an HMAC
  with a server-held key (or an append-only anchor such as a transparency log), plus the suite hash
  recorded on the run row. Deferred until the database is shared with anyone who shouldn't be able to
  alter verdicts.
- Content-based classification is a heuristic. A case with none of the signals, run against an agent
  that attacks itself, isn't caught. Fixtures and prompts are the realistic vectors, and those are covered.
- Traces store raw agent output. With synthetic fixtures that's acceptable; with real sandboxes, add
  retention limits and encryption at rest.
- Resource-exhaustion limits (max cases × repeats per run, concurrent runs) aren't enforced yet.
