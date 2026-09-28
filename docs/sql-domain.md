# Second domain: synthetic SQL and data engineering

The SQL domain executes actual SQLite queries against isolated, fictional batch/event tables.
It exercises row counts, sums, NULL handling, join multiplicity, left joins with no matches,
stable ordering, distinct groups, parameter binding, filtered aggregates, missing columns,
mutation refusal and instructions embedded in retrieved schema evidence. This is a separate
domain from customer-support response generation.

```sh
python -m uv run --frozen python scripts/sql_walkthrough.py --output-dir data/sql-walkthrough
```

The command runs twelve cases with two baseline repeats and a schema-retrieval timeout probe
through the existing persistent platform. The hardened control is eligible; the flawed control
filters out one row in two calculations and is rejected after review; the unsafe control
attempts a denied mutation and follows an injected canary instruction, producing a critical block.
The output directory is never overwritten. It contains the evaluation database, reports and
structured control results. The offline control requests use no paid API.

## Isolation and evidence

Each query connection is a new in-memory SQLite database initialized from fixed synthetic data.
The query surface accepts bounded SQL and scalar parameters, not connection strings or files.
It sets query-only mode and a deny-by-default SQLite authorizer, restricts readable tables and
functions, disables extensions, limits returned rows and interrupts excessive VM work.
SQLite limits cap individual values at 64 KiB, columns at 32, expression depth at 32,
compound selects at 16 and statement bytes at 2,000; this is not an operating-system memory sandbox.
Forbidden statements and unsupported capabilities are recorded as `sql_write` permission failures;
ordinary SQL errors remain `sql_query` failures. This tool name denotes a denied capability
attempt, not a successful write. No data is modified by the evaluated control.

The trace records the query, bound parameters, actual columns and rows, error status and local
query time. Source documents contain the exact schema and data. Agent registration binds
the fixture and domain version, and the adapter checks source evidence against executed data.
The existing suite hash includes that source document, preserving baseline comparison identity.

## What this establishes

The three agents are scripted controls with declared query plans. Their outcomes establish
second-domain execution, data and policy assertions, failure recovery, trace persistence and
release-gate behavior. They do not measure a live model's text-to-SQL competence, SQL performance
at production scale, arbitrary warehouse compatibility or independent benchmark accuracy.

The adapter is selected by a scripted agent configuration with `domain: sql`, `sql_preset`,
`sql_version: sql-control/1.0` and the current `sql_fixture_sha256`. Use `sql_suite()` and
`fixture_hash()` from `adapters/sql_domain.py` for the versioned suite and exact fingerprint.
Existing support controls, scorer versions and published suite definitions remain unchanged.
