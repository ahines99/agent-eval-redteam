"""Local operations smoke against real subprocess servers and disposable databases."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_operations_over_real_http_and_restored_sqlite(tmp_path):
    script = Path(__file__).resolve().parents[1] / "scripts" / "verify_operations.py"
    evidence_path = tmp_path / "operations.json"
    result = subprocess.run(
        [sys.executable, str(script), "--output", str(evidence_path)],
        cwd=tmp_path, capture_output=True, text=True, timeout=120,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )
    assert result.returncode == 0, result.stderr
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert evidence["synthetic_only"]
    assert evidence["credential_rotation"]["old_token_status"] == 401
    assert evidence["credential_rotation"]["new_token_health"] == "ok"
    assert evidence["credential_rotation"]["same_process"]
    assert all(evidence["tenant_isolation"].values())
    assert evidence["admission"]["admitted_concurrent_requests"] == 16
    assert evidence["admission"]["overflow_status"] == 429
    assert evidence["admission"]["slots_released"]
    assert evidence["backup_restore"]["integrity_check"] == "ok"
    assert evidence["backup_restore"]["restored_http_report_matches"]
    assert evidence["backup_restore"]["release_decision"] == "eligible"
    assert evidence["limitations"]
