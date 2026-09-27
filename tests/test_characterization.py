"""Verify characterization accounting and reproducibility, not heuristic perfection."""

from __future__ import annotations

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


def test_corpus_fingerprint_is_stable_across_checkout_newlines(tmp_path):
    original = characterization.DEFAULT_CORPUS.read_bytes().replace(b"\r\n", b"\n")
    unix, windows = tmp_path / "unix.json", tmp_path / "windows.json"
    unix.write_bytes(original)
    windows.write_bytes(original.replace(b"\n", b"\r\n"))
    assert characterization.characterize(unix) == characterization.characterize(windows)


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
