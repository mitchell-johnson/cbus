"""Public command reports observation only, with exact source and user inputs."""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
from unittest.mock import patch

from cbus_toolkit import cli
from cbus_toolkit import windows_sesu_current_user_cohort as current


def invoke(*extra):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli.main([
            "update-rollout-current-user", "--source-assembly", "original.dll",
            "--expected-source-sha256", current.ORIGINAL_SHA256,
            "--expected-user-sid", "S-1-5-21-100-200-300-1001", *extra,
        ])
    return code, json.loads(out.getvalue() or err.getvalue())


def test_public_command_reports_only_pinned_read_only_observation():
    with patch.object(current, "_source_sha256", return_value=current.ORIGINAL_SHA256), \
         patch.object(current, "_current_process_sid", return_value="S-1-5-21-100-200-300-1001"), \
         patch.object(current, "_read_hkcu_registry32", return_value=("present", "41", 1)), \
         patch.dict("sys.modules", {"winreg": type("Reg", (), {"REG_SZ": 1, "REG_DWORD": 4})()}):
        code, result = invoke()
    assert code == 0
    assert result["status"] == "observed"
    assert result["stored_cohort"] == 41
    assert result["registry_entry"] == "VisibilityExpectedGreaterThan"
    assert result["source_assembly_sha256"] == current.ORIGINAL_SHA256
    assert result["source_assembly_verified"] is True
    assert result["user_sid_verified"] is True
    assert result["rollout_gate_evaluated"] is False


def test_public_command_rejects_unpinned_source_before_registry_access():
    with patch.object(current, "_read_hkcu_registry32") as registry:
        code, result = invoke("--expected-source-sha256", "0" * 64)
    assert code == 1 and result["type"] == "ValueError"
    registry.assert_not_called()
