"""Capture real offline-demo output/timing as a local asciicast v2 recording.

Format: https://docs.asciinema.org/manual/asciicast/v2/
This records a noninteractive subprocess, not a shell session or narrated video.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", nargs="?", type=Path, default=Path("docs/demo.cast"))
    args = parser.parse_args()
    started_at = int(time.time())
    started = time.perf_counter()
    environment = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}
    events: list[list[object]] = []
    with subprocess.Popen(
        [sys.executable, "-u", "-m", "agent_eval_redteam.cli", "demo"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
        env=environment, creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    ) as process:
        assert process.stdout is not None
        for line in process.stdout:
            # Pipes have no terminal's newline processing. Render each real output line
            # with CRLF so playback starts subsequent lines at column one.
            events.append([round(time.perf_counter() - started, 6), "o", line.replace("\n", "\r\n")])
        code = process.wait()
    duration = round(time.perf_counter() - started, 6)
    header = {"version": 2, "width": 150, "height": 40, "timestamp": started_at, "duration": duration,
              "command": "python -u -m agent_eval_redteam.cli demo",
              "title": "Agent evaluation: offline control agents and release gates"}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as recording:
        for item in [header, *events]:
            recording.write(json.dumps(item, ensure_ascii=True) + "\n")
    print(f"Recorded {len(events)} output events over {duration:.3f}s; exit code {code}: {args.output}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
