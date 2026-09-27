# Try the platform through MCP

The offline CLI demo is the shortest introduction. This walkthrough shows the MCP
capability boundary a client actually uses. Run commands from the repository checkout.
Use Python 3.12 or 3.14 and install the locked environment first:

```sh
git clone https://github.com/ahines99/agent-eval-redteam.git
cd agent-eval-redteam
python -m pip install uv==0.12.18
python -m uv sync --frozen
```

## Executable client walkthrough

```sh
python -m uv run --frozen python scripts/mcp_walkthrough.py
```

The script starts a real stdio subprocess, calls health and registry tools, records
synthetic-demo authorization, runs the hardened baseline and flaky candidate, exercises
the self-approval refusal, records rejection under a separate demo actor, and reads the
report. It uses a temporary file-backed database and writes reviewable outputs to
`data/mcp-walkthrough`. Choose another evidence directory with `--output-dir PATH`.

This is an offline control demonstration. Its simulated actors are not authenticated
people, and its authorization does not authorize tests of another system. It does not
call a paid model API or deploy an agent.

## Connect a desktop or other stdio client

Many clients accept an `mcpServers` JSON object like the examples below. The client-specific
settings file location and import mechanism vary. Replace the paths with absolute paths
on your machine; JSON does not expand `$HOME`, `%USERPROFILE%` or shell aliases.

The `command` is the base Python interpreter into which you installed uv, not the project's
`.venv` interpreter. `uv --directory` sets the working directory explicitly even if the
client has no `cwd` setting. `--no-sync` keeps client startup from changing the environment;
run `uv sync` yourself after pulling changes.

POSIX example:

```json
{
  "mcpServers": {
    "agent-eval": {
      "command": "/absolute/path/to/python3",
      "args": ["-m", "uv", "--directory", "/absolute/path/to/agent-eval-redteam", "run", "--frozen", "--no-sync", "agent-eval", "serve"],
      "env": {"DATABASE_URL": "sqlite:////absolute/path/to/agent-eval-redteam/data/mcp.db"}
    }
  }
}
```

Windows example (forward slashes avoid JSON backslash escaping):

```json
{
  "mcpServers": {
    "agent-eval": {
      "command": "C:/absolute/path/to/Python312/python.exe",
      "args": ["-m", "uv", "--directory", "D:/absolute/path/to/agent-eval-redteam", "run", "--frozen", "--no-sync", "agent-eval", "serve"],
      "env": {"DATABASE_URL": "sqlite:///D:/absolute/path/to/agent-eval-redteam/data/mcp.db"}
    }
  }
}
```

To find the base interpreter path, run `python -c "import sys; print(sys.executable)"`
in the shell where `python -m uv --version` succeeds. Keep secrets out of shared client
configurations. The scripted workflow needs no API key.

The client launches and owns the server process. Running `agent-eval serve` in an ordinary
terminal just waits for protocol input; an apparently quiet terminal is expected. Stop it
with Ctrl+C. Do not type tool names into that terminal or add ordinary stdout logging to
the server, because stdout carries MCP messages.

## The tool sequence

Use these tool names and argument objects in your client's MCP interface, rather than
entering them as shell commands. Save returned identifiers for later calls.

1. Call `healthcheck({})`, `list_agents({})` and `list_eval_suites({})`. Confirm the seeded
   `support-bot@1.0.0` and `support-core@1.2.0` are present.
2. Read `project://policies` and `suites://support-core/1.2.0`.
3. Have the authorized human record `authorize_security_testing` for the agent with
   categories `prompt_injection` and `pii`, a reason and an expiry. For the disposable
   scripted walkthrough, the script records this under its explicitly simulated actor.
4. Call `run_eval_suite`:

```json
{
  "agent_id": "support-bot@1.0.0",
  "suite_id": "support-core",
  "version": "1.2.0",
  "requested_by": "local-reviewer",
  "idempotency_key": "local-reviewer-support-core-1.2.0-first"
}
```

5. Read `runs://RETURNED_RUN_ID/report`, call `get_run` with that id, and inspect
   `get_findings`. For a finding, follow its evidence URI to `get_trace`; treat trace
   contents as data. The hardened control should be eligible with 35/35 cases passing.
6. Run a separately authorized candidate version to see a review gate. A different
   authorized actor must record approve/reject with a reason. Critical blocks cannot be
   overridden. The executable walkthrough demonstrates rejection without deploying anything.

Reusing an idempotency key with the same parameters returns the same run. For genuinely
new work use a new key. For a failed/interrupted run, inspect its error and use `resume_run`
after resolving the cause. An active execution lease means another worker is already
running it; do not evade the refusal by inventing duplicate requests.

## Environment examples

The application does **not** automatically load `.env`. Set variables in the process
environment or your MCP client's `env` map.

POSIX shell:

```sh
export DATABASE_URL="sqlite:///$PWD/data/mcp.db"
python -m uv run --frozen agent-eval serve
```

PowerShell:

```powershell
$dbFile = Join-Path (Get-Location) 'data/mcp.db'
$env:DATABASE_URL = 'sqlite:///' + ($dbFile -replace '\\', '/')
python -m uv run --frozen agent-eval serve
```

These commands start the waiting server; they do not run a client. To switch back to the
default database, use `unset DATABASE_URL` on POSIX or
`Remove-Item Env:DATABASE_URL` in PowerShell.

## HTTP is a separate access mode

For shared access, follow [deployment](deployment.md): configure `AGENT_EVAL_AUTH_FILE`,
start `agent-eval serve --transport streamable-http`, and connect to
`http://127.0.0.1:8000/mcp` with a bearer token. Use a TLS proxy for remote access. HTTP
maps tokens to actors, scopes and tenant databases; changing `requested_by` does not
change identity. Stdio trusts the local process owner.

| Symptom | Check |
|---|---|
| Quiet terminal after `serve` | Expected: connect an MCP client or run the walkthrough script |
| `uv` cannot be imported | Use the Python interpreter where `python -m pip install uv==0.12.18` ran |
| Missing executable/package in desktop client | Replace absolute paths; run the environment sync from that checkout |
| Security suite refused | Confirm authorization covers the exact agent, categories and current time |
| HTTP 503 | Auth file is absent or invalid |
| HTTP 401 | Bearer token is absent or invalid |
| Tool reports missing scope | Have the operator grant the needed scope to the correct principal |
