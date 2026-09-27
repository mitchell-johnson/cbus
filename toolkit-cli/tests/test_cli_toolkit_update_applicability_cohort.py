"""Public CLI contract for the caller-supplied cohort applicability path."""
from __future__ import annotations

import copy
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from unittest.mock import patch

from cbus_toolkit import cli
from tests.test_toolkit_update_applicability import AT, BASE, encode


def invoke(path, node_id, cohort="41"):
    output, error = io.StringIO(), io.StringIO()
    with redirect_stdout(output), redirect_stderr(error), \
         patch("socket.socket", side_effect=AssertionError("cohort preflight initiated network I/O")):
        code = cli.main([
            "update-applicability-cohort-preflight", "--catalogue-response", str(path),
            "--node-id", node_id, "--platform", "windows_x86_64",
            "--at-utc", AT, "--stored-cohort", cohort,
        ])
    return code, json.loads(output.getvalue() or error.getvalue())


def test_cli_pass_equal_and_predecessor_failure(tmp_path):
    source = copy.deepcopy(BASE)
    node = source["data"][0]
    node_id = node["nodeId"]
    path = tmp_path / "untrusted-catalogue.json"
    node["data"]["visibilityInPercent"] = 42
    path.write_bytes(encode(source))
    code, result = invoke(path, node_id)
    assert code == 0 and result["status"] == "passed"
    assert result["checks"]["rollout_gate_reached_under_supplied_context"] is True
    assert result["checks"]["rollout_gate_under_supplied_cohort"] is True
    assert result["registry_accessed"] is False
    assert result["cohort_persisted"] is False
    assert result["publisher_trust_evaluated"] is False
    assert result["install_permitted"] is False
    assert "url" not in result and "package_path" not in result

    node["data"]["visibilityInPercent"] = 41
    path.write_bytes(encode(source))
    code, result = invoke(path, node_id)
    assert code == 1 and result["status"] == "failed"
    assert result["checks"]["rollout_gate_reached_under_supplied_context"] is True
    assert result["checks"]["rollout_gate_under_supplied_cohort"] is False

    node["data"]["startDate"] = "2099-01-01T00:00:00Z"
    path.write_bytes(encode(source))
    code, result = invoke(path, node_id)
    assert code == 1 and result["status"] == "failed"
    assert result["checks"]["rollout_gate_reached_under_supplied_context"] is False
    assert result["checks"]["rollout_gate_under_supplied_cohort"] is None


def test_cli_rejects_unmodeled_input(tmp_path):
    source = copy.deepcopy(BASE)
    node = source["data"][0]
    node_id = node["nodeId"]
    path = tmp_path / "untrusted-catalogue.json"
    node["data"]["visibilityInPercent"] = 100
    path.write_bytes(encode(source))
    code, result = invoke(path, node_id)
    assert code == 2 and result["status"] == "unsupported"
    code, result = invoke(path, node_id, "-1")
    assert code == 1 and result["type"] == "ValueError"
    path.write_bytes(b'{"success":true,"success":true}')
    code, result = invoke(path, node_id)
    assert code == 1 and result["type"] == "ValueError"
