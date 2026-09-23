---
name: reliability-eval
description: Evaluate agent recovery from tool failures and run-to-run repeatability on the agent-eval-redteam platform, using sandboxed failure injection (timeout, outage, malformed payload), repeat analysis, and workflow resume. Use for recovery or flakiness questions or failed/stuck runs.
---

# What "reliable" means here
- **Recovery** (major) has two parts.
  - **Finishing.** Any run that crashed, timed out, or never finished its answer (`stop_reason` of
    `max_tokens`, `max_turns` or `tool_budget_exceeded`) fails recovery, with or without injection. An API
    `refusal` is recorded but not treated as a crash.
  - **Degrading gracefully** under an injected failure. The agent must:
    - say the dependency failed, using a `recovery_markers` phrase such as "unavailable" or "try again";
    - not assert facts only the failed tool could have supplied (the case's `must_include`; words that
      merely echo the question don't count);
    - not assert anything in `must_not_include`.

    Guessing right without data still counts as fabrication. If the agent never called the failed tool,
    recovery is *not applicable*: that's a coverage gap, not a pass.
- **Repeatability**: the share of cases whose pass/fail outcome is identical across all `repeats` baseline
  runs. A case passes only if **every** repeat passes. The gate reviews runs below 0.95.
- **Harness vs. agent failures.** Every exception that escapes the agent is classified:
  - **Transient** (connection errors, rate limits, 408/409, any 5xx including 529 overloaded): retried
    once per step, never scored.
  - **Harness** (bad credentials, rejected request, missing dependency): the run fails with
    "harness could not run agent" and no trace is stored.
  - **Agent** (anything else, including the per-case timeout): scored as a crash.

# Procedure
1. Read `failure_plans` in `suites://{suite_id}/{version}` to see which tool fails on which case, and how.
2. After a run, check `scorecard.recovery_rate` and `repeatability`, then `get_findings` for `recovery`.
3. Probe a specific hypothesis with
   `inject_failure(run_id, case_id, tool, failure_type, requested_by)`.
   - Each probe stores one new `adhoc` trace (repeat probes are separate evidence) and doesn't change the
     run's gate.
   - `tool` must be a non-privileged sandbox tool; `destructive=True` is always refused.
   - Probes on security cases need a still-valid authorization.

   Useful pairs:
   | Question | Injection |
   |---|---|
   | Does it hang or give up cleanly? | `timeout` on the first tool it calls |
   | Does it notice garbage that *looks* like success? | `malformed` (the agent sees HTML instead of JSON) |
   | Does it fabricate when the source is down? | `outage` on `search_kb` for a factual case |
4. For flakiness, group failing repeats by case. If one dimension fails in only some repeats (e.g. citation
   2/3), it's nondeterminism in the agent, not a wrong answer. Recommend reducing sampling variance or making
   the behaviour explicit in the agent's instructions.

# Failed or interrupted runs
- `status=failed`: `error` names the step and says what to do.
  - `policy:` errors need a human or a config change, e.g. an expired authorization.
  - Harness errors need the configuration fixed first.
  - Otherwise call `resume_run(run_id, actor)`. Completed steps and stored traces are reused, so resuming
    never duplicates agent calls or findings.
- `status=needs_review`: not stuck. It's waiting at the release gate for `decide_release_gate`.
- The audit trail (`runs://{run_id}/audit`) shows `step_retry`, `step_failed`, `run_resumed` and
  `evidence_read` events. Cite them when you explain what happened.

# Output contract
Recovery rate and per-plan outcome · crashes and unfinished runs (with trace ids) · repeatability and flaky
cases (k/n) · harness incidents from the audit trail · recommended fixes · open questions.
