# Three-minute demonstration script

Before recording, run `uv sync --frozen --all-extras` and the tests. Use a terminal with
readable type and no credentials visible. The default demo is in memory and offline.
This is a narration script. The accompanying [demo.cast](demo.cast) records actual CLI
output with measured timing; it is a short terminal recording, not a three-minute video.
Replay it locally with `asciinema play docs/demo.cast`. Regenerate with
`uv run --frozen python scripts/record_demo.py`; stdout and stderr are combined, line
endings are normalized for terminal playback, and no artificial pauses are added.
The recorder follows the [asciicast v2 format](https://docs.asciinema.org/manual/asciicast/v2/).

| Time | Action | Narration |
|---|---|---|
| 0:00–0:25 | Show README architecture and MCP tool table. | This platform evaluates an agent in a synthetic support sandbox. Code scores traces and controls release gates; an LLM does not decide the score. |
| 0:25–0:45 | Run `uv run --frozen agent-eval demo`. | One command runs the hardened, flaky and naive control agents over 35 versioned cases, including tool failures and adversarial inputs. No API key is needed. |
| 0:45–1:15 | Highlight successful hardened run and candidate review. | The control passes; the candidate drops citations. The gate compares it to an accepted version and requests review. The requester cannot approve their own run. |
| 1:15–1:40 | Highlight naive-agent critical failures and refused override. | The unsafe control triggers injection, permission or data-disclosure failures. Critical failures block release, and an override cannot erase them. |
| 1:40–2:00 | Show failure injection and regression alert. | A failed lookup checks graceful recovery. The monitor compares stored results and flags quality drops. These operations remain inside the sandbox. |
| 2:00–2:30 | Show report, findings and evidence identifiers. | Every finding points back to stored trace evidence. Artifacts, hashes and audit events make the decision inspectable after the client conversation ends. |
| 2:30–3:00 | Show test result and limitations. | The suite tests deterministic controls and integration boundaries. Shared hosting needs configured authentication and operations; a separate budgeted live-model run establishes model-specific results. |

Optional persistent follow-up: run `agent-eval demo --db sqlite:///./data/demo.db`, capture
the printed run id, and run `agent-eval report RUN_ID --db sqlite:///./data/demo.db` in a
second terminal. Use a fresh database for each recorded demo. The ordinary in-memory
command is repeatable without managing retained demo records.
