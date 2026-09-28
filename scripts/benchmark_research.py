"""Freeze/run authored research evidence or import independently supplied reviewer labels."""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import traceback
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_eval_redteam.domain.benchmark import (
    characterize,
    compare_reviews,
    fingerprint,
    load_corpus,
    reviewer_packet,
)

ROOT = Path(__file__).resolve().parents[1]
SOURCES = [
    "src/agent_eval_redteam/domain/benchmark.py",
    "src/agent_eval_redteam/domain/semantic.py",
    "src/agent_eval_redteam/domain/scoring.py",
    "src/agent_eval_redteam/domain/project_models.py",
    "src/agent_eval_redteam/domain/models.py",
    "uv.lock",
    "src/agent_eval_redteam/domain/pii.py",
    "scripts/benchmark_research.py",
]


def write_new(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.write("\n")


def freeze(corpus: Path, output: Path) -> None:
    data = load_corpus(corpus)  # Validates only; never calls any scorer.
    write_new(
        output,
        {
            "schema_version": 1,
            "corpus_id": data["corpus_id"],
            "corpus_path": corpus.resolve().relative_to(ROOT).as_posix(),
            "corpus_sha256": fingerprint(corpus),
            "frozen_at": datetime.now(UTC).isoformat(),
            "source_sha256": {p: fingerprint(ROOT / p) for p in SOURCES},
            "protocol": "AI-authored development-exposed paired scenarios. First execution after Git freeze. "
            "All disagreements retained; historical reports untouched. No model calls or human labels.",
        },
    )


def run(corpus: Path, manifest_path: Path, commit: str, output: Path) -> None:
    import hashlib

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest["corpus_sha256"] != fingerprint(corpus):
        raise ValueError("corpus changed after freeze")
    if set(manifest["source_sha256"]) != set(SOURCES):
        raise ValueError("freeze must cover the exact research source set")
    for relative, digest in manifest["source_sha256"].items():
        if fingerprint(ROOT / relative) != digest:
            raise ValueError(f"source changed after freeze: {relative}")
    full_commit = subprocess.check_output(
        ["git", "rev-parse", "--verify", commit + "^{commit}"], cwd=ROOT, text=True
    ).strip()
    # Both the corpus and freeze declaration must exist identically in the requested commit.
    for path in (corpus, manifest_path, *(ROOT / p for p in SOURCES)):
        relative = path.resolve().relative_to(ROOT).as_posix()
        blob = subprocess.check_output(["git", "show", f"{full_commit}:{relative}"], cwd=ROOT)
        if hashlib.sha256(blob.replace(b"\r\n", b"\n")).hexdigest() != fingerprint(path):
            raise ValueError(f"input not committed unchanged: {relative}")
    output.mkdir(parents=True, exist_ok=False)  # Reserve evidence destination before execution.
    started = datetime.now(UTC).isoformat()
    record = {
        "execution_role": "preserved research execution; first status established by committed evidence history",
        "frozen_input_commit": full_commit,
        "freeze_sha256": fingerprint(manifest_path),
        "manifest": manifest,
        "started_at": started,
        "python_version": platform.python_version(),
        "platform": platform.platform(),
    }
    try:
        report = characterize(corpus)
        write_new(output / "report.json", report)
        record.update(exit_code=0, output_sha256=fingerprint(output / "report.json"))
    except Exception as exc:
        with (output / "error.txt").open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(traceback.format_exc())
        record.update(
            exit_code=1,
            error_type=type(exc).__name__,
            error=str(exc),
            error_log_sha256=fingerprint(output / "error.txt"),
        )
        raise
    finally:
        record["finished_at"] = datetime.now(UTC).isoformat()
        write_new(output / "execution.json", record)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["freeze", "run", "export-review", "compare-reviews"])
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--frozen-input-commit")
    parser.add_argument("--review-a", type=Path)
    parser.add_argument("--review-b", type=Path)
    parser.add_argument("--adjudication", type=Path)
    args = parser.parse_args()
    if args.command == "freeze":
        freeze(args.corpus, args.output)
    elif args.command == "run":
        if not args.manifest or not args.frozen_input_commit:
            parser.error("run requires --manifest and --frozen-input-commit")
        run(args.corpus, args.manifest, args.frozen_input_commit, args.output)
    elif args.command == "export-review":
        write_new(args.output, reviewer_packet(args.corpus))
    else:
        if not args.review_a or not args.review_b:
            parser.error("compare-reviews requires --review-a and --review-b")
        read = lambda p: json.loads(p.read_text(encoding="utf-8"))  # noqa: E731
        write_new(
            args.output,
            compare_reviews(
                args.corpus,
                read(args.review_a),
                read(args.review_b),
                read(args.adjudication) if args.adjudication else None,
            ),
        )
    print(f"Saved {args.command}: {args.output}")


if __name__ == "__main__":
    main()
