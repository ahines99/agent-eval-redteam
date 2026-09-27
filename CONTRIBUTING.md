# Contributing

The current scope is a local-first, synthetic agent-evaluation platform. Small changes
with a reproducible failure and clear evidence are easier to review than broad framework
expansions. Read the [architecture](docs/architecture.md), [contracts](docs/data_contracts.md)
and [threat model](docs/threat_model.md) before changing evaluation or access behavior.

## Development environment

From the checkout, use Python 3.12 or 3.14:

```sh
git clone https://github.com/ahines99/agent-eval-redteam.git
cd agent-eval-redteam
python -m pip install uv==0.12.18
python -m uv sync --frozen --all-extras
python -m uv run --frozen pytest --cov --cov-report=term-missing
python -m uv run --frozen ruff check src tests migrations scripts
python -m uv run --frozen mypy src
python -m uv run --frozen python -m build --no-isolation
```

Python metadata permits 3.12+; consult actual CI/release evidence for verified OS and
interpreter combinations. Optional PostgreSQL tests skip without `TEST_POSTGRES_URL`;
a skip is not a passing backend check. Use a disposable database as described in
[deployment](docs/deployment.md). No API credentials are required for ordinary tests.

## Propose and verify a change

1. Describe the concrete behavior being changed and how to reproduce it using synthetic data.
2. Add a focused regression test for a behavioral fix. For scoring, include both a passing
   and failing example where appropriate, and inspect the resulting finding/gate.
3. Run checks relevant to the change, then the release checks before proposing a merge.
   Include commands, outcomes and any skipped/unavailable environment in the description.
4. Update affected contracts, user instructions and the unreleased changelog entry.

Do not edit published suite JSON files to repair expectations. Publish a new suite version.
`expected_policy` is explanatory text; assertions belong in executable expectation fields.
When scoring, world or gate meaning changes, update the corresponding evaluation identity
and explain historical comparability. A passing scripted control is not an independent
quality benchmark.

Schema changes need a new Alembic revision with a frozen schema definition, plus fresh
installation and retained-data upgrade coverage. Never make old migrations import the
current evolving application metadata. Do not run destructive migration tests against
real or shared databases.

Update dependencies deliberately with `python -m uv lock --upgrade`, review the lock diff
and rerun tests/audit. Do not change the lock just to suppress a failed compatibility check.
Build release artifacts from the intended release snapshot, not an unrelated working tree.

## Data, credentials and disclosures

Use synthetic fixtures and reserved addresses. Keep API keys, bearer tokens, database
passwords, real customer data and private traces out of commits, screenshots and issues.
Live-model checks require an explicit model, authorization and budget; the scoring budget
is not a hard API spend limit. Shared service configuration requires separate authenticated
identities and tenant databases.

Report suspected vulnerabilities through the process in [SECURITY.md](SECURITY.md).
For ordinary bugs, include a minimal synthetic reproduction, environment versions and
expected/actual behavior. Do not attach a whole database or unredacted trace dump.

## Attribution

AI-assisted contributions are welcome. Describe material assistance and verification
honestly; do not claim independent human review, authorship history or benchmark accuracy
that the evidence does not establish. Contributions are provided under the repository's
[MIT license](LICENSE).
