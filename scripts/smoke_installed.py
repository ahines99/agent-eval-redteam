"""Verify installed-package behavior outside the checkout, with retained evidence."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    environment = {key: value for key, value in os.environ.items() if key not in {"PYTHONPATH", "DATABASE_URL"}}
    probe = """
import importlib.resources
from pathlib import Path
import sys
import agent_eval_redteam
assert not Path(agent_eval_redteam.__file__).resolve().is_relative_to(Path(sys.argv[1]) / 'src')
fixtures = importlib.resources.files('agent_eval_redteam.fixtures')
assert fixtures.joinpath('world.json').is_file()
assert fixtures.joinpath('suites', 'support-core.v1.2.0.json').is_file()
"""
    with tempfile.TemporaryDirectory(prefix="agent-eval-wheel-") as working:
        subprocess.run([sys.executable, "-c", probe, str(repo)], cwd=working, env=environment, check=True)
        url = "sqlite:///" + (Path(working) / "demo.db").as_posix()
        demo = subprocess.run([sys.executable, "-m", "agent_eval_redteam.cli", "demo", "--db", url],
                              cwd=working, env=environment, check=True, capture_output=True, text=True,
                              encoding="utf-8")
        for message in ("decision=awaiting_review", "separation of duties", "cannot be overridden",
                        "recovery: degraded gracefully", "alert:"):
            if message not in demo.stdout:
                raise AssertionError(f"Demo did not demonstrate {message!r}")
        command = [sys.executable, str(repo / "scripts" / "verify_demo.py"), "--db", url]
        if args.output_dir:
            destination = args.output_dir.resolve()
            destination.mkdir(parents=True, exist_ok=True)
            (destination / "demo.txt").write_text(demo.stdout, encoding="utf-8")
            command.extend(["--output-dir", str(destination)])
        subprocess.run(command, cwd=working, env=environment, check=True)
        sql_destination = (args.output_dir.resolve() / "sql-domain" if args.output_dir
                           else Path(working) / "sql-domain")
        sql = subprocess.run([sys.executable, str(repo / "scripts" / "sql_walkthrough.py"),
                              "--output-dir", str(sql_destination)], cwd=working, env=environment,
                             capture_output=True, text=True, encoding="utf-8")
        if sql.returncode:
            raise RuntimeError(f"Installed SQL walkthrough failed: {sql.stderr}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
