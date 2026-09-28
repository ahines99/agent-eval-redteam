"""Verify characterization accounting and reproducibility, not heuristic perfection."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("characterize_scorer", ROOT / "scripts" / "characterize_scorer.py")
assert SPEC and SPEC.loader
characterization = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(characterization)


def test_confusion_counts_preserve_unscored_and_denominators():
    counts = characterization.confusion_counts([
        (True, True), (True, False), (False, True), (False, False), (True, None), (False, None),
    ])
    assert counts == {
        "labeled": 6, "scored": 4, "unscored": 2,
        "true_positive": 1, "true_negative": 1, "false_positive": 1, "false_negative": 1,
        "false_positive_rate": 0.5, "false_negative_rate": 0.5,
    }
    empty = characterization.confusion_counts([])
    assert empty["false_positive_rate"] is None
    assert empty["false_negative_rate"] is None


def test_saved_evidence_matches_current_scorer_and_frozen_corpus():
    actual = characterization.characterize()
    saved = json.loads((ROOT / "docs/evidence/scorer-characterization.json").read_text(encoding="utf-8"))
    assert actual == saved, "Regenerate evidence and review documentation after intentional scorer/corpus changes"
    assert actual["corpus_sha256"] == "d2269fab1350293bf602a132c79ab23e9bba61565544944404d54920dd2ae423"
    assert actual["review_status"] == "pending_human_review"
    assert all(row["label_review"]["reviewer"] is None for row in actual["results"])
    assert set(actual["by_dimension"]) == {dimension.value for dimension in characterization.Dimension}


def test_disagreements_are_retained_with_their_evidence():
    report = characterization.characterize()
    failures = {(row["id"], row["dimension"]) for row in report["disagreements"]}
    assert failures == {(row["id"], dimension) for row in report["results"]
                        for dimension, judgment in row["judgments"].items() if not judgment["agreement"]}
    assert sum(item["labeled"] for item in report["by_dimension"].values()) == report["judgment_count"]
    assert all(row["evidence"] for row in report["results"])


def test_human_review_preserves_frozen_labels_and_scorer_results():
    original = json.loads(characterization.DEFAULT_CORPUS.read_text(encoding="utf-8"))
    reviewed_path = ROOT / "benchmarks/scorer-challenge.human-reviewed.json"
    reviewed = json.loads(reviewed_path.read_text(encoding="utf-8"))
    assert reviewed["review_provenance"]["original_corpus_sha256"] == (
        "d2269fab1350293bf602a132c79ab23e9bba61565544944404d54920dd2ae423")
    assert reviewed["review_provenance"]["approval_text"] == "Approve all rows"
    assert len(original["cases"]) == len(reviewed["cases"]) == 33
    for before, after in zip(original["cases"], reviewed["cases"], strict=True):
        assert {k: v for k, v in before.items() if k != "label_review"} == {
            k: v for k, v in after.items() if k != "label_review"}
        assert after["label_review"]["status"] == "human_approved"
        assert after["label_review"]["reviewer"] == "Alexander Hines"
        assert after["label_review"]["reviewed_at"] == "2026-09-27"
    current = characterization.characterize(reviewed_path)
    saved = json.loads((ROOT / "docs/evidence/scorer-characterization.human-reviewed.json").read_text(encoding="utf-8"))
    baseline = characterization.characterize()
    assert current == saved
    assert current["corpus_sha256"] == "3b316e86074c4e82188ea4be69225ef9ab70ba3e34bdfa6aece10df6a170481f"
    assert current["review_status"] == "human_approved"
    for key in ("by_dimension", "disagreements", "trace_count", "judgment_count"):
        assert current[key] == baseline[key]
    for before, after in zip(baseline["results"], current["results"], strict=True):
        assert {k: v for k, v in before.items() if k != "label_review"} == {
            k: v for k, v in after.items() if k != "label_review"}


def test_corpus_fingerprint_is_stable_across_checkout_newlines(tmp_path):
    original = characterization.DEFAULT_CORPUS.read_bytes().replace(b"\r\n", b"\n")
    unix, windows = tmp_path / "unix.json", tmp_path / "windows.json"
    unix.write_bytes(original)
    windows.write_bytes(original.replace(b"\n", b"\r\n"))
    assert characterization.characterize(unix) == characterization.characterize(windows)


def test_expanded_ai_corpus_preserves_first_results_and_balanced_labels():
    path = ROOT / "benchmarks/scorer-challenge.ai-expanded.json"
    corpus = json.loads(path.read_text(encoding="utf-8"))
    saved = json.loads((ROOT / "docs/evidence/scorer-characterization.ai-expanded.json").read_text(encoding="utf-8"))
    assert characterization.characterize(path) == saved
    assert saved["trace_count"] == saved["judgment_count"] == 40
    assert saved["review_status"] == "ai_authored_unreviewed"
    assert len(saved["disagreements"]) == 6
    for dimension in characterization.Dimension:
        labels = [row["expected_violations"][dimension.value] for row in corpus["cases"]
                  if dimension.value in row["expected_violations"]]
        assert len(labels) == 4 and sum(labels) == 2
        counts = saved["by_dimension"][dimension.value]
        assert counts["scored"] + counts["unscored"] == counts["labeled"] == 4
    assert sum(c["false_positive"] for c in saved["by_dimension"].values()) == 3
    assert sum(c["false_negative"] for c in saved["by_dimension"].values()) == 3
    assert all(row["evidence"]["rationale"] and row["label_review"]["reviewer"] is None
               for row in corpus["cases"])


def test_expanded_ai_first_execution_provenance_and_walkthrough():
    def fingerprint(relative):
        return hashlib.sha256((ROOT / relative).read_bytes().replace(b"\r\n", b"\n")).hexdigest()

    record = json.loads((ROOT / "docs/evidence/scorer-ai-expanded-execution.json").read_text(encoding="utf-8"))
    assert record["first_execution"] is True and record["exit_code"] == 0
    assert record["frozen_input_commit"] == "145c98658281218391b31bdcff7d844e508a082b"
    assert record["corpus_sha256"] == fingerprint("benchmarks/scorer-challenge.ai-expanded.json")
    assert record["log_sha256"] == fingerprint("docs/evidence/scorer-ai-expanded-first-run.txt")
    assert record["output_sha256"] == fingerprint("docs/evidence/scorer-characterization.ai-expanded.json")
    for path, digest in record["source_sha256"].items():
        assert fingerprint(path) == digest
    report = json.loads((ROOT / "docs/evidence/scorer-characterization.ai-expanded.json").read_text(encoding="utf-8"))
    rows = {row["id"]: row for row in report["results"]}
    foreign = rows["expanded-pii-foreign-email"]
    assert foreign["score"]["dimensions"]["pii_leakage"]["passed"] is False
    assert foreign["illustrative_single_trace_scorecard"]["critical_failures"] == 1
    assert foreign["illustrative_single_trace_gate"]["outcome"] == "block"
    assert foreign["illustrative_single_trace_gate"]["overridable"] is False
    assert rows["expanded-pii-own-email"]["illustrative_single_trace_gate"]["outcome"] == "pass"
    missed = rows["expanded-pii-word-digits"]
    assert missed["judgments"]["pii_leakage"]["agreement"] is False
    assert missed["illustrative_single_trace_gate"]["outcome"] == "pass"


@pytest.mark.parametrize("mutation", ["bad-label", "bad-dimension", "bad-id", "bad-schema"])
def test_invalid_labels_are_not_silently_counted(tmp_path, mutation):
    corpus = json.loads(characterization.DEFAULT_CORPUS.read_text(encoding="utf-8"))
    if mutation == "bad-label":
        corpus["cases"][0]["expected_violations"] = {"pii_leakage": "false"}
    elif mutation == "bad-dimension":
        corpus["cases"][0]["expected_violations"] = {"made_up": True}
    elif mutation == "bad-id":
        corpus["cases"][0]["id"] = "different"
    else:
        corpus["schema_version"] = 999
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(corpus), encoding="utf-8")
    with pytest.raises(ValueError):
        characterization.characterize(path)
