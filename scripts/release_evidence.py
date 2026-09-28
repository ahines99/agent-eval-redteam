"""Bundle successful test reports, source provenance and built artifact checksums."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import shutil
import subprocess
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def git(*arguments: str) -> str:
    return subprocess.check_output(["git", *arguments], cwd=ROOT, text=True).strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--junit", nargs="+", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("data/verification/release"))
    parser.add_argument("--require-clean", action="store_true")
    args = parser.parse_args()
    status = git("status", "--porcelain")
    if args.require_clean and status:
        raise SystemExit("Release evidence requires a clean committed tree")
    destination = args.output_dir.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    results = []
    for path in args.junit:
        root = ET.parse(path).getroot()
        suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
        counts = {name: sum(int(s.get(name, "0")) for s in suites)
                  for name in ("tests", "failures", "errors", "skipped")}
        if not counts["tests"] or counts["failures"] or counts["errors"]:
            raise SystemExit(f"Cannot certify failed or empty test report: {path.name}")
        results.append({"file": path.name, **counts})
        shutil.copy2(path, destination / path.name)
    version = importlib.metadata.version("agent-eval-redteam")
    artifacts = sorted((ROOT / "dist").glob(f"agent_eval_redteam-{version}*"))
    if len(artifacts) != 2:
        raise SystemExit(f"Build the {version} wheel and source distribution first")
    hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in artifacts}
    provenance = {"generated_at": datetime.now(UTC).isoformat(), "commit": git("rev-parse", "HEAD"),
                  "tree": git("rev-parse", "HEAD^{tree}"), "dirty": bool(status),
                  "package_version": version,
                  "python": platform.python_version(), "platform": platform.platform(),
                  "lock_sha256": hashlib.sha256((ROOT / "uv.lock").read_bytes()).hexdigest(),
                  "test_reports": results, "artifacts_sha256": hashes}
    (destination / "manifest.json").write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    # Keep historical and research evidence together, including nested execution records.
    shutil.copytree(ROOT / "docs/evidence", destination / "evidence", dirs_exist_ok=True)
    shutil.copytree(ROOT / "benchmarks", destination / "benchmarks", dirs_exist_ok=True)
    (ROOT / "dist/SHA256SUMS").write_text("".join(f"{digest}  {name}\n" for name, digest in hashes.items()),
                                         encoding="ascii")
    shutil.make_archive(str(ROOT / "dist" / f"verification-{version}"), "zip", destination)
    print(f"Release evidence saved to {destination}; source commit {provenance['commit']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
