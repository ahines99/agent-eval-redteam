"""Characterize frozen, agent-authored labels; disagreements are results, not test failures."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from agent_eval_redteam.domain.policies import GATE_POLICY_VERSION, evaluate_gate
from agent_eval_redteam.domain.project_models import Dimension, EvalCase, EvalSuite, Trace
from agent_eval_redteam.domain.scoring import SCORING_VERSION, score_trace
from agent_eval_redteam.domain.stats import aggregate

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CORPUS = ROOT / "benchmarks" / "scorer-challenge.json"
DEFAULT_OUTPUT = ROOT / "docs" / "evidence" / "scorer-characterization.json"


def confusion_counts(observations: list[tuple[bool, bool | None]]) -> dict[str, Any]:
    """Positive means a violation; NA remains unscored, never an implicit success."""
    tp = sum(expected and actual is True for expected, actual in observations)
    tn = sum(not expected and actual is False for expected, actual in observations)
    fp = sum(not expected and actual is True for expected, actual in observations)
    fn = sum(expected and actual is False for expected, actual in observations)
    unscored = sum(actual is None for _, actual in observations)
    return {
        "labeled": len(observations), "scored": len(observations) - unscored, "unscored": unscored,
        "true_positive": tp, "true_negative": tn, "false_positive": fp, "false_negative": fn,
        "false_positive_rate": fp / (fp + tn) if fp + tn else None,
        "false_negative_rate": fn / (fn + tp) if fn + tp else None,
    }


def characterize(corpus_path: Path = DEFAULT_CORPUS) -> dict[str, Any]:
    # Git can materialize CRLF on Windows. Freeze content independently of checkout newlines.
    raw = corpus_path.read_bytes().replace(b"\r\n", b"\n")
    corpus = json.loads(raw)
    if corpus["schema_version"] != 1:
        raise ValueError("unsupported challenge corpus schema")
    cases = [EvalCase.model_validate(row["case"]) for row in corpus["cases"]]
    suite = EvalSuite(suite_id="scorer-challenge", version="1.0.0", repeats=1,
                      description=corpus["authorship"], cases=cases)
    observations: dict[str, list[tuple[bool, bool | None]]] = {}
    results = []
    for row, case in zip(corpus["cases"], cases, strict=True):
        if row["id"] != case.case_id:
            raise ValueError("challenge ID and case ID differ")
        trace = Trace.model_validate({
            "trace_id": f"challenge-{case.case_id}", "run_id": "characterization-only",
            "case_id": case.case_id, "phase": "baseline", "repeat": 0,
            "agent_id": "authored-trace", "model": "no-model-called", **row["trace"],
        })
        score = score_trace(case, suite, trace, corpus["sensitive"])
        judgments = {}
        for dimension, expected in row["expected_violations"].items():
            Dimension(dimension)
            if type(expected) is not bool:
                raise ValueError("labels must be literal booleans")
            result = score.dimensions[dimension]
            actual = not result.passed if result.applicable and result.passed is not None else None
            observations.setdefault(dimension, []).append((expected, actual))
            judgments[dimension] = {
                "expected_violation": expected, "detected_violation": actual,
                "agreement": actual is not None and expected == actual,
                "scorer_detail": result.detail,
            }
        scorecard = aggregate([score], [trace.latency_ms], trace.cost_usd)
        gate = evaluate_gate(scorecard, None)
        results.append({"id": row["id"], "evidence": row["evidence"],
                        "label_review": row["label_review"], "judgments": judgments,
                        "score": score.model_dump(mode="json"),
                        "illustrative_single_trace_scorecard": scorecard.model_dump(mode="json"),
                        "illustrative_single_trace_gate": gate.model_dump(mode="json")})
    disagreements = [{"id": row["id"], "dimension": dimension, **judgment}
                     for row in results for dimension, judgment in row["judgments"].items()
                     if not judgment["agreement"]]
    return {
        "schema_version": 1, "corpus_id": corpus["corpus_id"],
        "corpus_sha256": hashlib.sha256(raw).hexdigest(),
        "corpus_hash_format": "UTF-8 file bytes with CRLF normalized to LF",
        "scoring_version": SCORING_VERSION, "gate_policy_version": GATE_POLICY_VERSION,
        "authorship": corpus["authorship"], "review_status": corpus["review_status"],
        "metric_semantics": "Positive means violation. Rates exclude unscored labels; inspect their counts.",
        "gate_scope": "Single authored trace only; not a production release or measured repeatability.",
        "trace_count": len(results), "judgment_count": sum(map(len, observations.values())),
        "by_dimension": {key: confusion_counts(value) for key, value in sorted(observations.items())},
        "disagreements": disagreements, "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = characterize(args.corpus)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("corpus_sha256", "trace_count", "judgment_count",
                                                 "by_dimension", "disagreements")}, indent=2))


if __name__ == "__main__":
    main()
