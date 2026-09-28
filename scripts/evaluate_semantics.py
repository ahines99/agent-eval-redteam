"""Evaluate a frozen semantic packet or development corpus without changing release gates."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from agent_eval_redteam.domain.semantic import SEMANTIC_VERSION, SemanticPacket, evaluate_semantics


def evaluate_file(path: Path) -> dict[str, Any]:
    raw = path.read_bytes().replace(b"\r\n", b"\n")
    data = json.loads(raw)
    if "packets" in data:
        results = [{"id": row["id"], "expected_verdict": row["expected_verdict"],
                    "result": evaluate_semantics(SemanticPacket.model_validate(row["packet"]))}
                   for row in data["packets"]]
        provenance = {key: data[key] for key in ("authorship", "review_status")}
    else:
        results = [{"result": evaluate_semantics(SemanticPacket.model_validate(data))}]
        provenance = {"authorship": "provided packet; authorship not independently verified"}
    return {"schema_version": 1, "evaluator_version": SEMANTIC_VERSION,
            "input_file_sha256": hashlib.sha256(raw).hexdigest(), "provenance": provenance,
            "results": results}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    # Exclusive creation preserves prior experiments even if this command is repeated.
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as output:
        json.dump(evaluate_file(args.input), output, indent=2, ensure_ascii=False)
        output.write("\n")
    print(f"Wrote advisory report to {args.output}")


if __name__ == "__main__":
    main()
