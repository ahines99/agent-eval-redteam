"""Deterministic statistics: aggregation, confidence intervals, run comparison, regression monitoring."""

from __future__ import annotations

import math
from collections import defaultdict
from statistics import median
from typing import Any

from .project_models import CaseScore, Scorecard, Severity


def wilson_interval(successes: int, n: int, z: float = 1.959964) -> tuple[float, float]:
    """95% Wilson score interval for a binomial proportion (well-behaved at small n and p near 0/1)."""
    if n == 0:
        return (0.0, 1.0)
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4))


def percentile(values: list[int], pct: float) -> int:
    """Nearest-rank percentile."""
    if not values:
        return 0
    ordered = sorted(values)
    rank = max(1, math.ceil(pct / 100 * len(ordered)))
    return ordered[rank - 1]


def case_outcomes(scores: list[CaseScore]) -> dict[str, bool]:
    """A case passes only if every baseline repeat passes and every injected-failure variant passes."""
    out: dict[str, bool] = {}
    for s in scores:
        if s.phase == "adhoc":
            continue
        out[s.case_id] = out.get(s.case_id, True) and s.passed
    return out


def aggregate(scores: list[CaseScore], latencies_ms: list[int], total_cost_usd: float) -> Scorecard:
    baseline = [s for s in scores if s.phase == "baseline"]
    injected = [s for s in scores if s.phase == "injected"]
    outcomes = case_outcomes(scores)
    n_cases = len(outcomes)
    n_passed = sum(outcomes.values())

    by_case: dict[str, set[bool]] = defaultdict(set)
    for s in baseline:
        by_case[s.case_id].add(s.passed)
    repeatability = (sum(1 for v in by_case.values() if len(v) == 1) / len(by_case)) if by_case else 1.0

    dim_total: dict[str, int] = defaultdict(int)
    dim_pass: dict[str, int] = defaultdict(int)
    failures: dict[Severity, set[tuple[str, str, str]]] = defaultdict(set)
    for s in baseline + injected:
        for name, d in s.dimensions.items():
            if not d.applicable:
                continue
            dim_total[name] += 1
            if d.passed:
                dim_pass[name] += 1
            else:
                failures[d.severity].add((s.case_id, s.phase, name))

    recovery = [s.dimensions["recovery"] for s in injected if s.dimensions["recovery"].applicable]
    recovery_rate = (sum(1 for d in recovery if d.passed) / len(recovery)) if recovery else None

    return Scorecard(
        n_cases=n_cases,
        n_passed=n_passed,
        pass_rate=round(n_passed / n_cases, 4) if n_cases else 0.0,
        pass_rate_ci95=wilson_interval(n_passed, n_cases),
        dimension_pass_rates={k: round(dim_pass[k] / dim_total[k], 4) for k in sorted(dim_total)},
        critical_failures=len(failures[Severity.CRITICAL]),
        major_failures=len(failures[Severity.MAJOR]),
        minor_failures=len(failures[Severity.MINOR]),
        repeatability=round(repeatability, 4),
        recovery_rate=None if recovery_rate is None else round(recovery_rate, 4),
        failing_cases=sorted(c for c, ok in outcomes.items() if not ok),
        p95_latency_ms=percentile(latencies_ms, 95),
        total_cost_usd=round(total_cost_usd, 6),
    )


def compare(current: Scorecard, current_outcomes: dict[str, bool], baseline: Scorecard,
            baseline_outcomes: dict[str, bool], *, same_suite_version: bool) -> dict[str, Any]:
    common = sorted(set(current_outcomes) & set(baseline_outcomes))
    regressions = [c for c in common if baseline_outcomes[c] and not current_outcomes[c]]
    fixes = [c for c in common if not baseline_outcomes[c] and current_outcomes[c]]
    lo_c, hi_c = current.pass_rate_ci95
    lo_b, hi_b = baseline.pass_rate_ci95
    dims = sorted(set(current.dimension_pass_rates) | set(baseline.dimension_pass_rates))
    return {
        "comparable": same_suite_version,
        "common_cases": len(common),
        "pass_rate_delta": round(current.pass_rate - baseline.pass_rate, 4),
        # Conservative: only call a change significant when the 95% intervals do not overlap.
        "significant": hi_c < lo_b or hi_b < lo_c,
        "regressions": regressions,
        "fixes": fixes,
        "dimension_deltas": {
            d: round(current.dimension_pass_rates.get(d, 0.0) - baseline.dimension_pass_rates.get(d, 0.0), 4)
            for d in dims
        },
    }


def regression_alerts(history: list[dict[str, Any]], *, drop_tolerance: float = 0.05,
                      recurring_window: int = 3) -> list[str]:
    """History is oldest-first: [{"run_id", "pass_rate", "failing_cases"}, ...]; the last entry is current."""
    if len(history) < 2:
        return []
    alerts = []
    current, prior = history[-1], history[:-1]
    ref = median(h["pass_rate"] for h in prior)
    if current["pass_rate"] < ref - drop_tolerance:
        alerts.append(f"pass rate {current['pass_rate']:.2f} is below the prior median {ref:.2f} "
                      f"by more than {drop_tolerance:.2f}")
    window = history[-recurring_window:]
    if len(window) == recurring_window:
        counts: dict[str, int] = defaultdict(int)
        for h in window:
            for c in h["failing_cases"]:
                counts[c] += 1
        recurring = sorted(c for c, n in counts.items() if n >= 2)
        if recurring:
            alerts.append(f"cases failing in >=2 of the last {recurring_window} runs: {recurring}")
    return alerts
