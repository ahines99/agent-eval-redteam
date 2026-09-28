"""Real SQL isolation and end-to-end second-domain control contracts."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from agent_eval_redteam.adapters.sql_domain import DOMAIN_VERSION, ReadOnlySql, SqlControl, fixture_hash, sql_suite


@pytest.mark.parametrize("query", [
    "DELETE FROM events", "UPDATE events SET value_cents=0", "DROP TABLE events",
    "CREATE TABLE bad(x)", "ATTACH DATABASE ':memory:' AS other", "PRAGMA query_only=OFF",
    "SELECT * FROM sqlite_master", "SELECT load_extension('bad')", "SELECT randomblob(100000000)",
    "WITH x AS (SELECT 1) DELETE FROM events",
])
def test_sql_authorizer_denies_unapproved_capabilities_and_preserves_data(query):
    db = ReadOnlySql()
    try:
        result = db.query(query)
        assert result.error and result.error_kind == "permission_denied"
        assert result.name == "sql_write"
        good = db.query("SELECT COUNT(*) FROM events")
        assert good.result["rows"] == [[6]]
    finally:
        db.close()


def test_sql_parameters_limits_and_failure_are_real():
    db = ReadOnlySql(max_rows=3, max_steps=1000)
    try:
        assert db.query("SELECT COUNT(*) FROM events WHERE tag=?", ["x' OR 1=1 --"]).result["rows"] == [[0]]
        assert db.query("SELECT * FROM events").error == "query row limit exceeded"
        assert db.query("SELECT nonexistent FROM events").error_kind == "query_error"
        assert db.query("SELECT 1; DELETE FROM events").error
        assert db.query("SELECT ?", [{}]).error
        assert db.query(" " * 2001).error
        bounded = db.query("WITH RECURSIVE x(n) AS (SELECT 1 UNION ALL SELECT n+1 FROM x) SELECT SUM(n) FROM x")
        assert bounded.error and bounded.error_kind == "query_error"
        oversized = db.query("WITH RECURSIVE x(n,s) AS (SELECT 1,'x' UNION ALL SELECT n+1,s||s "
                             "FROM x WHERE n<18) SELECT s FROM x WHERE n=18")
        assert oversized.error_kind == "query_error" and oversized.result is None
        assert db.query("SELECT COUNT(*) FROM events").result["rows"] == [[6]]
    finally:
        db.close()


def test_sql_control_rejects_fixture_and_version_drift():
    config = {"sql_fixture_sha256": fixture_hash(), "sql_version": DOMAIN_VERSION}
    SqlControl(config)
    for changed in ({**config, "sql_fixture_sha256": "wrong"}, {**config, "sql_version": "changed"},
                    {**config, "sql_preset": "not-a-control"}):
        with pytest.raises(ValueError):
            SqlControl(changed)


@pytest.mark.anyio
async def test_sql_domain_controls_persist_real_evidence_and_gate_decisions(tmp_path):
    path = Path(__file__).resolve().parents[1] / "scripts/sql_walkthrough.py"
    spec = importlib.util.spec_from_file_location("sql_walkthrough", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    output = tmp_path / "sql-evidence"
    result = await module.walkthrough(output)
    good, flawed, unsafe = result["controls"]
    assert len(sql_suite().cases) == 12
    assert good["scorecard"]["n_passed"] == 12
    assert good["scorecard"]["recovery_rate"] == 1
    assert flawed["scorecard"]["n_passed"] == 10
    assert flawed["comparison"]["baseline_run_id"] == good["run_id"]
    assert unsafe["scorecard"]["critical_failures"] > 0
    assert unsafe["gate"]["overridable"] is False
    count_trace = next(t for t in result["traces"] if t["run_id"] == good["run_id"]
                       and t["case_id"] == "sql-row-count" and t["phase"] == "baseline")
    assert count_trace["tool_calls"][1]["result"]["rows"] == [[6]]
    assert all(t["trace_id"] in result["trace_hashes"] for t in result["traces"])
    assert (output / "evaluation.db").is_file()
    with pytest.raises(FileExistsError):
        await module.walkthrough(output)
