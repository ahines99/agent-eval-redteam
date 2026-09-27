"""Build an offline, paced presentation from the real raw demo recording."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
raw = [json.loads(line) for line in (ROOT / "docs/demo.cast").read_text(encoding="utf-8").splitlines()]
output = "".join(event[2] for event in raw[1:] if event[1] == "o")
chapters = [
    (
        "01 / Control",
        "Establish the accepted baseline",
        "The hardened reference passes all 35 declared cases. Its stored score and evidence establish the "
        "compatible baseline for the next version.",
        "1) Successful path:",
    ),
    (
        "02 / Review",
        "Catch the regression before release",
        "The candidate loses citations. Review pauses the workflow. The requester cannot approve their own "
        "run; a separate reviewer records rejection.",
        "2) Review path:",
    ),
    (
        "03 / Block",
        "Keep critical failures non-overridable",
        "The naive control triggers 17 critical findings. A reviewer cannot override this gate. Each "
        "finding links to the stored trace that supports it.",
        "3) Controlled failure path:",
    ),
    (
        "04 / Recovery",
        "Inject a real sandbox failure",
        "A lookup timeout tests whether the agent reports uncertainty instead of inventing an answer. The "
        "probe passes without changing the release evaluation.",
        "4) Ad-hoc failure injection",
    ),
    (
        "05 / Monitor",
        "Compare persisted results",
        "The monitor sees the drop against prior accepted behavior. Comparisons require matching suite, "
        "world, scorer and gate-policy identity.",
        "5) Regression monitor",
    ),
    (
        "06 / Evidence",
        "Inspect the decision after the run",
        "This is a synthetic harness demonstration, not a live-model benchmark. Scripted cost is simulated; "
        "hashes detect corruption but do not distrust the database administrator.",
        "6) Report for",
    ),
]
scenes = []
for index, (label, title, description, marker) in enumerate(chapters):
    start = output.index(marker)
    end = output.index(chapters[index + 1][3]) if index + 1 < len(chapters) else len(output)
    scenes.append(dict(label=label, title=title, description=description, terminal=output[start:end].strip()))
template = (ROOT / "docs/demo-template.html").read_text(encoding="utf-8")
(ROOT / "docs/demo.html").write_text(
    template.replace("__SCENES__", json.dumps(scenes).replace("</", "<\\/")), encoding="utf-8"
)
print("Built docs/demo.html: 6 scenes, 150-second edited presentation; original raw timing preserved in demo.cast")
