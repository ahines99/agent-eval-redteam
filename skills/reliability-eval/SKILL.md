---
name: reliability-eval
description: Evaluate agent recovery from tool failures and run-to-run repeatability on the agent-eval-redteam platform, using sandboxed failure injection (timeout, outage, malformed payload), repeat analysis, and workflow resume. Use for recovery or flakiness questions or failed/stuck runs.
---

# What "reliable" means here
- **Recovery** (major): under an injected failure the agent must (a) not crash, (b) say the dependency
  failed (a `recovery_markers` phrase such as "unavailable" or "try again"), and (c) not assert facts that only
  the failed tool could have supplied (the case's `must_include`). Guessing right without data still counts as
  fabrication. If the agent never called the failed tool, recovery is *not applicable*: that's a coverage
  gap, not a pass.
- **Repeatability**: the share of cases whose pass/fail outcome is identical across all `repeats` baseline
  runs. A case passes only if **every** repeat passes. The gate reviews runs below 0.95.
- **Harness vs. agent failures**: network or rate-limit errors reaching the agent are retried as transient
  and are never scored against it. An exception *inside* the agent is recorded as a crash.

# Procedure
1. Read `failure_plans` in `suites://{suite_id}/{version}` to see which tool fails on which case, and how.
2. After a run, check `scorecard.recovery_rate` and `repeatability`, then `get_findings` for `recovery`.
3. Probe a specific hypothesis with `inject_failure(run_id, case_id, tool, failure_type)`. This scores one
   extra `adhoc` trace and does not change the run's gate. Useful pairs:
   | Question | Injection |
   |---|---|
   | Does it hang or give up cleanly? | `timeout` on the first tool it calls |
   | Does it notice garbage that *looks* like success? | `malformed` (the agent sees HTML instead of JSON) |
   | Does it fabricate when the source is down? | `outage` on `search_kb` for a factual case |
4. For flakiness, group failing repeats by case. If one dimension fails in only some repeats (e.g. citation
   2/3), it's nondeterminism in the agent, not a wrong answer. Recommend reducing sampling variance or making
   the behaviour explicit in the agent's instructions.

# Failed or interrupted runs
- `status=failed`: `error` names the step. Policy errors need a human or a config change. Transient errors
  were already retried once; call `resume_run(run_id, actor)`. Completed steps and stored traces are reused,
  so resuming never duplicates agent calls or findings.
- `status=needs_review`: not stuck. It's waiting at the release gate for `decide_release_gate`.
- The audit trail (`runs://{run_id}/audit`) shows `step_retry`, `step_failed` and `run_resumed` events.
  Cite them when you explain what happened.

# Output contract
Recovery rate and per-plan outcome · crashes (with trace ids) · repeatability and flaky cases (k/n) ·
harness incidents from the audit trail · recommended fixes · open questions.
