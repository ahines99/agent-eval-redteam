"""Research-only benchmark accounting and provenance-bound reviewer interchange.

A declared reviewer kind is not identity verification. AI-authored labels remain AI-authored.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from .project_models import Dimension, EvalCase, EvalSuite, Trace
from .scoring import SCORING_VERSION, score_trace

BENCHMARK_VERSION = "benchmark-research/1.0"


def fingerprint(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def metrics(observations: list[tuple[bool, bool | None]]) -> dict[str, Any]:
    """Positive is violation. Abstentions are coverage loss, not negative predictions."""
    tp = sum(want and got is True for want, got in observations)
    tn = sum(not want and got is False for want, got in observations)
    fp = sum(not want and got is True for want, got in observations)
    fn = sum(want and got is False for want, got in observations)
    unscored = sum(got is None for _, got in observations)
    count = len(observations)
    return {
        "labeled": count,
        "scored": count - unscored,
        "unscored": unscored,
        "true_positive": tp,
        "true_negative": tn,
        "false_positive": fp,
        "false_negative": fn,
        "precision": tp / (tp + fp) if tp + fp else None,
        "recall": tp / (tp + fn) if tp + fn else None,
        "f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None,
        "coverage": (count - unscored) / count if count else None,
        "false_positive_rate": fp / (fp + tn) if fp + tn else None,
        "false_negative_rate": fn / (fn + tp) if fn + tp else None,
    }


def agreement(pairs: list[tuple[bool, bool]]) -> dict[str, Any]:
    n = len(pairs)
    observed = sum(a == b for a, b in pairs) / n if n else None
    expected = (
        (
            (
                sum(a for a, _ in pairs) * sum(b for _, b in pairs)
                + sum(not a for a, _ in pairs) * sum(not b for _, b in pairs)
            )
            / n**2
        )
        if n
        else None
    )
    return {
        "paired_labels": n,
        "observed_agreement": observed,
        "expected_agreement": expected,
        "cohen_kappa": (observed - expected) / (1 - expected)
        if observed is not None and expected is not None and expected < 1
        else None,
    }


def load_corpus(path: Path) -> dict[str, Any]:
    corpus = json.loads(path.read_text(encoding="utf-8"))
    if corpus.get("schema_version") != 1 or not corpus.get("cases"):
        raise ValueError("nonempty schema_version 1 corpus required")
    if not corpus.get("authorship") or not corpus.get("review_status"):
        raise ValueError("explicit authorship and review status required")
    ids = set()
    for row in corpus["cases"]:
        case = EvalCase.model_validate(row["case"])
        if row["id"] in ids or row["id"] != case.case_id:
            raise ValueError("unique matching case IDs required")
        ids.add(row["id"])
        if not row.get("domain") or not row.get("family") or not row.get("evidence", {}).get("rationale"):
            raise ValueError("domain, family and rationale required")
        if not row.get("expected_violations"):
            raise ValueError("at least one dimension label required")
        for dimension, label in row["expected_violations"].items():
            Dimension(dimension)
            if type(label) is not bool:
                raise ValueError("labels must be literal booleans")
        if "expected_semantic_violation" in row and (
            type(row["expected_semantic_violation"]) is not bool
            or not row.get("semantic_family")
            or not row.get("semantic_packet")
        ):
            raise ValueError("semantic labels require a literal boolean, family and packet")
        trace_for(row)
    return corpus


def trace_for(row: dict[str, Any]) -> Trace:
    protected = {"trace_id", "run_id", "case_id", "agent_id", "model", "phase", "repeat"}
    if protected.intersection(row["trace"]):
        raise ValueError("authored trace cannot override benchmark identity")
    return Trace.model_validate(
        {
            "trace_id": "research-" + row["id"],
            "run_id": "research-only",
            "case_id": row["id"],
            "agent_id": "authored",
            "model": "no-model-called",
            "phase": "baseline",
            "repeat": 0,
            **row["trace"],
        }
    )


def characterize(path: Path) -> dict[str, Any]:
    from .semantic import SemanticPacket, evaluate_semantics

    corpus = load_corpus(path)
    suite = EvalSuite(
        suite_id="scorer-research",
        version="1.0.0",
        repeats=1,
        description=corpus["authorship"],
        cases=[EvalCase.model_validate(r["case"]) for r in corpus["cases"]],
    )
    observations: dict[str, list[tuple[bool, bool | None]]] = {}
    semantic_observations: dict[str, list[tuple[bool, bool | None]]] = {}
    results = []
    for row, case in zip(corpus["cases"], suite.cases, strict=True):
        trace = trace_for(row)
        score = score_trace(case, suite, trace, corpus["sensitive"])
        judgments = {}
        for dim, expected in row["expected_violations"].items():
            result = score.dimensions[dim]
            detected = not result.passed if result.applicable and result.passed is not None else None
            observations.setdefault(dim, []).append((expected, detected))
            judgments[dim] = {
                "expected_violation": expected,
                "detected_violation": detected,
                "agreement": detected is not None and detected == expected,
            }
        advisory = None
        if "semantic_packet" in row:
            config = row["semantic_packet"]
            if {"case", "trace", "sensitive"}.intersection(config):
                raise ValueError("semantic packet cannot override evidence")
            advisory = evaluate_semantics(
                SemanticPacket.model_validate(
                    {**config, "case": case, "trace": trace, "sensitive": corpus["sensitive"]}
                )
            )
        # Whole-packet verdict is compared only to explicitly authored packet-level labels.
        # It is never reinterpreted as an individual dimension prediction.
        if "expected_semantic_violation" in row:
            expected = row["expected_semantic_violation"]
            if type(expected) is not bool:
                raise ValueError("semantic labels must be literal booleans")
            verdict = advisory["verdict"] if advisory else "uncertain"
            predicted = {"supported": False, "contradicted": True, "uncertain": None}[verdict]
            semantic_observations.setdefault(row["semantic_family"], []).append((expected, predicted))
        results.append(
            {
                "id": row["id"],
                "domain": row["domain"],
                "family": row["family"],
                "evidence": row["evidence"],
                "judgments": judgments,
                "deterministic_score": score.model_dump(mode="json"),
                "semantic_advisory": advisory,
            }
        )
    return {
        "schema_version": 1,
        "benchmark_version": BENCHMARK_VERSION,
        "scoring_version": SCORING_VERSION,
        "corpus_id": corpus["corpus_id"],
        "corpus_sha256": fingerprint(path),
        "authorship": corpus["authorship"],
        "review_status": corpus["review_status"],
        "metric_semantics": "Violation positive; precision/recall exclude abstentions; inspect coverage. "
        "Purposeful paired AI examples are not independent samples or human ground truth.",
        "trace_count": len(results),
        "family_count": len({r["family"] for r in results}),
        "by_domain": dict(sorted(Counter(r["domain"] for r in results).items())),
        "by_family": dict(sorted(Counter(r["family"] for r in results).items())),
        "by_dimension": {d: metrics(obs) for d, obs in sorted(observations.items())},
        "semantic_packet_metrics": {d: metrics(obs) for d, obs in sorted(semantic_observations.items())},
        "semantic_scope": "Packet-level advisory verdicts only; uncertain or missing is unscored. "
        "No release decision is relaxed. Metrics are not dimension-level semantic accuracy.",
        "disagreements": [
            {"id": r["id"], "dimension": d, **j}
            for r in results
            for d, j in r["judgments"].items()
            if not j["agreement"]
        ],
        "results": results,
    }


def _blind_rows(corpus: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    # Neutral IDs and a deterministic mixed order prevent good/bad IDs and paired ordering leaking labels.
    ordered = sorted(corpus["cases"], key=lambda row: hashlib.sha256(row["id"].encode()).hexdigest())
    return [(f"item-{i:04d}", row) for i, row in enumerate(ordered, 1)]


def reviewer_packet(path: Path) -> dict[str, Any]:
    corpus = load_corpus(path)
    cases = []
    for alias, row in _blind_rows(corpus):
        case, trace = copy.deepcopy(row["case"]), copy.deepcopy(row["trace"])
        case["case_id"] = alias
        if trace.get("injected_failure"):
            trace["injected_failure"]["case_id"] = alias
        cases.append(
            {
                "id": alias,
                "case": case,
                "trace": trace,
                "source": row["evidence"].get("source"),
                "domain": row["domain"],
                "labels": {d: None for d in row["expected_violations"]},
                "rationale": "",
            }
        )
    return {
        "schema_version": 1,
        "corpus_id": corpus["corpus_id"],
        "corpus_sha256": fingerprint(path),
        "instructions": "Review without author labels or scorer outputs. true means violation. "
        "Declare identity, human/AI kind and exposure honestly. Declaration is not verified identity.",
        "reviewer": {"id": "", "kind": "", "independence_declaration": ""},
        "cases": cases,
        "sensitive": corpus["sensitive"],
    }


def _review(path: Path, review: dict[str, Any]) -> tuple[dict[str, Any], dict[tuple[str, str], bool]]:
    corpus = load_corpus(path)
    if review.get("schema_version") != 1 or review.get("corpus_sha256") != fingerprint(path):
        raise ValueError("review schema/corpus fingerprint mismatch")
    person = review["reviewer"]
    if (
        not str(person.get("id", "")).strip()
        or person.get("kind") not in {"human", "ai"}
        or not str(person.get("independence_declaration", "")).strip()
    ):
        raise ValueError("reviewer identity, human/ai kind and exposure declaration required")
    expected = {(r["id"], d) for r in corpus["cases"] for d in r["expected_violations"]}
    aliases = {alias: row["id"] for alias, row in _blind_rows(corpus)}
    packet_rows = {row["id"]: row for row in reviewer_packet(path)["cases"]}
    labels = {}
    row_ids = set()
    for row in review["cases"]:
        if row["id"] in row_ids or not str(row.get("rationale", "")).strip():
            raise ValueError("unique reviewer case IDs and rationale required")
        row_ids.add(row["id"])
        for dimension, value in row["labels"].items():
            if type(value) is not bool:
                raise ValueError("complete literal boolean reviewer labels required")
            if row["id"] not in aliases:
                raise ValueError("unknown blinded case ID")
            labels[(aliases[row["id"]], dimension)] = value
        original = packet_rows.get(row["id"])
        if original is None or any(field in row and row[field] != original[field] for field in ("case", "trace")):
            raise ValueError("reviewer evidence differs from frozen corpus")
    if set(labels) != expected or row_ids != set(aliases):
        raise ValueError("review must cover exactly all corpus dimension labels")
    return person, labels


def compare_reviews(
    path: Path, first: dict[str, Any], second: dict[str, Any], adjudication: dict[str, Any] | None = None
) -> dict[str, Any]:
    a, labels_a = _review(path, first)
    b, labels_b = _review(path, second)
    if a["id"].strip().casefold() == b["id"].strip().casefold():
        raise ValueError("two distinct reviewer identities required")
    disputed = {key for key in labels_a if labels_a[key] != labels_b[key]}
    resolved: dict[tuple[str, str], bool] = {}
    if adjudication is not None:
        if adjudication.get("corpus_sha256") != fingerprint(path) or adjudication.get("schema_version") != 1:
            raise ValueError("adjudication schema/corpus fingerprint mismatch")
        person = adjudication.get("adjudicator", {})
        if (
            not person.get("id")
            or person.get("kind") not in {"human", "ai"}
            or person["id"].strip().casefold() in {a["id"].strip().casefold(), b["id"].strip().casefold()}
        ):
            raise ValueError("distinct declared human/ai adjudicator required")
        for row in adjudication.get("resolutions", []):
            key = (row["id"], row["dimension"])
            if key in resolved or key not in disputed or type(row["violation"]) is not bool or not row.get("rationale"):
                raise ValueError("unique disputed resolutions with boolean label and rationale required")
            resolved[key] = row["violation"]
        if set(resolved) != disputed:
            raise ValueError("adjudication must explicitly resolve every disagreement")
    dims = sorted({d for _, d in labels_a})
    return {
        "schema_version": 1,
        "corpus_sha256": fingerprint(path),
        "reviewers": [a, b],
        "review_submissions": [first, second],
        "identity_status": "Self-declarations only; identity and independence are not externally verified.",
        "by_dimension": {d: agreement([(labels_a[k], labels_b[k]) for k in labels_a if k[1] == d]) for d in dims},
        "overall": agreement([(labels_a[k], labels_b[k]) for k in labels_a]),
        "disagreement_count": len(disputed),
        "adjudication_complete": disputed <= resolved.keys(),
        "adjudication": adjudication,
        "labels": [
            {
                "id": k[0],
                "dimension": k[1],
                "reviewer_a": labels_a[k],
                "reviewer_b": labels_b[k],
                "consensus": resolved.get(k) if k in disputed else labels_a[k],
            }
            for k in sorted(labels_a)
        ],
    }
