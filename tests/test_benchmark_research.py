"""Research accounting uses toy fixtures; do not execute the authored corpus before its freeze."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

from agent_eval_redteam.domain.benchmark import (
    agreement,
    characterize,
    compare_reviews,
    fingerprint,
    load_corpus,
    metrics,
    reviewer_packet,
)

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("benchmark_cli", ROOT / "scripts/benchmark_research.py")
assert SPEC and SPEC.loader
cli = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cli)


@pytest.fixture
def corpus(tmp_path):
    cases = []
    for i, violation in enumerate([True, False]):
        cases.append(
            {
                "id": f"fixture-{i}",
                "domain": "test",
                "family": "test-fact",
                "evidence": {"source": "The status is ready.", "rationale": "Toy test judgment."},
                "expected_violations": {"factuality": violation},
                "case": {
                    "case_id": f"fixture-{i}",
                    "category": "factuality",
                    "prompt": "State status.",
                    "expected_policy": "State ready.",
                    "expect": {"must_include": ["ready"]},
                },
                "trace": {"final_output": "Wrong." if violation else "The status is ready."},
            }
        )
    value = {
        "schema_version": 1,
        "corpus_id": "toy",
        "authorship": "Test fixture, AI authored.",
        "review_status": "ai_authored_unreviewed",
        "sensitive": {},
        "cases": cases,
    }
    path = tmp_path / "corpus.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def review(path, identity, labels):
    packet = reviewer_packet(path)
    packet["reviewer"] = {"id": identity, "kind": "ai", "independence_declaration": "Synthetic unit test."}
    for row, label in zip(packet["cases"], labels, strict=True):
        row["labels"] = {"factuality": label}
        row["rationale"] = "Unit-test label."
    return packet


def test_confusion_metrics_do_not_turn_abstention_into_accuracy():
    result = metrics([(True, True), (True, False), (False, True), (False, False), (True, None)])
    assert result["precision"] == result["recall"] == result["f1"] == 0.5
    assert result["coverage"] == 0.8 and result["unscored"] == 1
    wrong = metrics([(True, False), (False, True)])
    assert wrong["f1"] == 0
    empty = metrics([])
    assert empty["precision"] is empty["recall"] is empty["f1"] is empty["coverage"] is None
    assert metrics([(False, False)])["precision"] is None
    assert metrics([(True, None)])["recall"] is None


def test_agreement_balanced_identical_opposite_and_degenerate():
    assert agreement([(True, True), (False, False)])["cohen_kappa"] == 1
    assert agreement([(True, False), (False, True)])["cohen_kappa"] == -1
    assert agreement([(True, True), (True, True)])["cohen_kappa"] is None
    assert agreement([])["observed_agreement"] is None


def test_blinded_packet_does_not_export_author_labels_rationales_or_score(corpus):
    packet = reviewer_packet(corpus)
    serialized = json.dumps(packet)
    assert "expected_violations" not in serialized and "Toy test judgment" not in serialized
    assert "fixture-0" not in serialized and "fixture-1" not in serialized
    assert all(r["labels"] == {"factuality": None} for r in packet["cases"])
    assert packet["corpus_sha256"] == fingerprint(corpus)


def test_disputes_need_explicit_distinct_adjudicator_and_stay_unresolved(corpus):
    first, second = review(corpus, "A", [True, False]), review(corpus, "B", [False, False])
    initial = compare_reviews(corpus, first, second)
    assert initial["disagreement_count"] == 1 and initial["adjudication_complete"] is False
    disputed = next(r for r in initial["labels"] if r["reviewer_a"] != r["reviewer_b"])
    assert disputed["consensus"] is None
    adjudication = {
        "schema_version": 1,
        "corpus_sha256": fingerprint(corpus),
        "adjudicator": {"id": "C", "kind": "ai"},
        "resolutions": [
            {"id": disputed["id"], "dimension": "factuality", "violation": True, "rationale": "Read source and trace."}
        ],
    }
    final = compare_reviews(corpus, first, second, adjudication)
    assert final["adjudication_complete"] is True
    assert next(r for r in final["labels"] if r["id"] == disputed["id"])["consensus"] is True
    assert final["reviewers"][0]["kind"] == "ai"
    assert final["overall"]["paired_labels"] == 2
    for change in ["identity", "hash", "incomplete", "extra", "string-label", "no-rationale"]:
        invalid = copy.deepcopy(adjudication)
        if change == "identity":
            invalid["adjudicator"]["id"] = "a"
        elif change == "hash":
            invalid["corpus_sha256"] = "bad"
        elif change == "incomplete":
            invalid["resolutions"] = []
        elif change == "extra":
            invalid["resolutions"].append(invalid["resolutions"][0])
        elif change == "string-label":
            invalid["resolutions"][0]["violation"] = "true"
        else:
            invalid["resolutions"][0]["rationale"] = ""
        with pytest.raises(ValueError):
            compare_reviews(corpus, first, second, invalid)


@pytest.mark.parametrize(
    "mutation",
    ["same-id", "missing", "extra", "duplicate", "string-label", "hash", "no-kind", "no-declaration", "evidence"],
)
def test_invalid_reviewer_submissions_fail_closed(corpus, mutation):
    first, second = review(corpus, "A", [True, False]), review(corpus, "B", [True, False])
    if mutation == "same-id":
        second["reviewer"]["id"] = " A "
    elif mutation == "missing":
        second["cases"].pop()
    elif mutation == "extra":
        second["cases"].append({"id": "extra", "labels": {}, "rationale": "Extra"})
    elif mutation == "duplicate":
        second["cases"].append(second["cases"][0])
    elif mutation == "string-label":
        second["cases"][0]["labels"]["factuality"] = "true"
    elif mutation == "hash":
        second["corpus_sha256"] = "bad"
    elif mutation == "no-kind":
        second["reviewer"]["kind"] = "unspecified"
    elif mutation == "no-declaration":
        second["reviewer"]["independence_declaration"] = ""
    else:
        second["cases"][0]["trace"]["final_output"] = "Modified by reviewer."
    with pytest.raises(ValueError):
        compare_reviews(corpus, first, second)


@pytest.mark.parametrize("mutation", ["duplicate", "id", "label", "dimension", "family", "identity", "semantic"])
def test_invalid_authored_corpus(corpus, mutation):
    value = json.loads(corpus.read_text())
    if mutation == "duplicate":
        value["cases"].append(value["cases"][0])
    elif mutation == "id":
        value["cases"][0]["id"] = "wrong"
    elif mutation == "label":
        value["cases"][0]["expected_violations"]["factuality"] = 1
    elif mutation == "dimension":
        value["cases"][0]["expected_violations"] = {"unknown": True}
    elif mutation == "family":
        value["cases"][0]["family"] = ""
    elif mutation == "identity":
        value["cases"][0]["trace"]["case_id"] = "wrong"
    else:
        value["cases"][0]["expected_semantic_violation"] = "true"
    corpus.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        load_corpus(corpus)


def test_toy_characterization_preserves_predictions_without_semantic_invention(corpus):
    report = characterize(corpus)
    assert report["by_dimension"]["factuality"]["precision"] == 1
    assert report["semantic_packet_metrics"] == {}
    assert all(r["semantic_advisory"] is None for r in report["results"])
    assert report["family_count"] == 1 and report["trace_count"] == 2


def test_authored_research_design_validation_only():
    data = load_corpus(ROOT / "benchmarks/scorer-research-v1.json")
    assert len(data["cases"]) == 120
    assert len({r["family"] for r in data["cases"]}) == 60
    assert sum(r["domain"] == "sql" for r in data["cases"]) == 60
    for dimension in [
        d.value for d in __import__("agent_eval_redteam.domain.project_models", fromlist=["Dimension"]).Dimension
    ]:
        values = [r["expected_violations"][dimension] for r in data["cases"] if dimension in r["expected_violations"]]
        assert len(values) == 12 and sum(values) == 6
    assert data["review_status"] == "ai_authored_unreviewed"


def test_write_new_never_overwrites_evidence(tmp_path):
    path = tmp_path / "report.json"
    cli.write_new(path, {"first": True})
    with pytest.raises(FileExistsError):
        cli.write_new(path, {"first": False})
    assert json.loads(path.read_text()) == {"first": True}


def test_fingerprint_handles_checkout_newlines(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.write_bytes(b"one\ntwo\n")
    b.write_bytes(b"one\r\ntwo\r\n")
    assert fingerprint(a) == fingerprint(b)


def test_freeze_enforcement_and_failure_record(corpus, tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    source = tmp_path / "source.py"
    source.write_text("# test source\n")
    monkeypatch.setattr(cli, "SOURCES", ["source.py"])
    manifest = tmp_path / "freeze.json"
    cli.freeze(corpus, manifest)
    original = json.loads(manifest.read_text())

    def git(command, **kwargs):
        if command[1] == "rev-parse":
            return "a" * 40
        return (tmp_path / command[-1].split(":", 1)[1]).read_bytes()

    monkeypatch.setattr(cli.subprocess, "check_output", git)
    # platform.platform() may itself invoke subprocess on Linux. Keep runtime metadata
    # deterministic so the Git-only fake cannot intercept an unrelated system probe.
    monkeypatch.setattr(cli.platform, "platform", lambda: "synthetic-test-platform")
    # A changed source refuses execution before a result destination is created.
    source.write_text("# changed\n")
    with pytest.raises(ValueError, match="source changed"):
        cli.run(corpus, manifest, "HEAD", tmp_path / "refused")
    assert not (tmp_path / "refused").exists()
    source.write_text("# test source\n")
    corrupted = copy.deepcopy(original)
    corrupted["source_sha256"] = {}
    manifest.write_text(json.dumps(corrupted))
    with pytest.raises(ValueError, match="exact research source set"):
        cli.run(corpus, manifest, "HEAD", tmp_path / "refused")
    manifest.write_text(json.dumps(original))

    def fail(_):
        raise RuntimeError("deliberate execution failure")

    monkeypatch.setattr(cli, "characterize", fail)
    output = tmp_path / "first"
    with pytest.raises(RuntimeError, match="deliberate"):
        cli.run(corpus, manifest, "HEAD", output)
    record = json.loads((output / "execution.json").read_text())
    assert record["exit_code"] == 1 and record["error_type"] == "RuntimeError"
    assert record["platform"] == "synthetic-test-platform"
    assert record["manifest"] == original
    with pytest.raises(FileExistsError):
        cli.run(corpus, manifest, "HEAD", output)
    monkeypatch.setattr(cli, "characterize", lambda _: {"test": True})
    cli.run(corpus, manifest, "HEAD", tmp_path / "reproduction")
    succeeded = json.loads((tmp_path / "reproduction/execution.json").read_text())
    assert succeeded["output_sha256"] == fingerprint(tmp_path / "reproduction/report.json")


def test_semantic_packet_uncertainty_does_not_become_pass(corpus):
    value = json.loads(corpus.read_text())
    row = value["cases"][0]
    row.update(
        semantic_packet={
            "references": [{"reference_id": "source", "text": "Status is ready."}],
            "templates": [
                {"subject": "system", "predicate": "status", "prefix": "Status is ", "aliases": {"ready": "ready"}}
            ],
        },
        expected_semantic_violation=True,
        semantic_family="test",
    )
    corpus.write_text(json.dumps(value))
    report = characterize(corpus)
    assert report["semantic_packet_metrics"]["test"]["unscored"] == 1
    assert report["semantic_packet_metrics"]["test"]["coverage"] == 0
    assert report["results"][0]["semantic_advisory"]["review_required"] is True
