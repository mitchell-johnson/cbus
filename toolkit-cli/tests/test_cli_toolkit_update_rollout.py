"""CLI contract for source-bound, supplied-cohort rollout comparison."""
from __future__ import annotations

import copy
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from unittest.mock import patch

from cbus_toolkit import cli
from tests.test_toolkit_update_applicability import BASE, encode


def invoke(path, node_id, cohort="41"):
    output, error = io.StringIO(), io.StringIO()
    with redirect_stdout(output), redirect_stderr(error), \
         patch("socket.socket", side_effect=AssertionError("rollout command initiated network I/O")):
        code = cli.main([
            "update-rollout-cohort", "--catalogue-response", str(path),
            "--node-id", node_id, "--stored-cohort", cohort,
        ])
    return code, json.loads(output.getvalue() or error.getvalue())


def test_cli_pass_fail_unsupported_and_malformed(tmp_path):
    source = copy.deepcopy(BASE)
    node = source["data"][0]
    node_id = node["nodeId"]
    path = tmp_path / "catalogue.json"
    node["data"]["visibilityInPercent"] = 42
    path.write_bytes(encode(source))
    code, result = invoke(path, node_id)
    assert code == 0 and result["status"] == "passed"
    assert result["rollout_gate_under_supplied_cohort"] is True
    assert result["registry_accessed"] is False
    assert result["cohort_persisted"] is False
    assert result["publisher_trust_evaluated"] is False
    assert result["install_permitted"] is False

    node["data"]["visibilityInPercent"] = 41
    path.write_bytes(encode(source))
    code, result = invoke(path, node_id)
    assert code == 1 and result["status"] == "failed"

    node["data"]["visibilityInPercent"] = 100
    path.write_bytes(encode(source))
    code, result = invoke(path, node_id)
    assert code == 2 and result["status"] == "unsupported"

    code, result = invoke(path, node_id, "bad")
    assert code == 1 and result["type"] == "ValueError"
