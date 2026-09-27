"""Public CLI contract for the bounded offline SESU applicability preflight."""
from __future__ import annotations

import copy
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from unittest.mock import patch

import pytest

from cbus_toolkit import cli
from tests.test_toolkit_update_applicability import AT, BASE, encode


def _invoke(path, node_id, *, platform="windows_x86_64"):
    output, error = io.StringIO(), io.StringIO()
    with redirect_stdout(output), redirect_stderr(error), \
         patch("socket.socket", side_effect=AssertionError("preflight initiated network I/O")):
        code = cli.main([
            "update-applicability-preflight", "--catalogue-response", str(path),
            "--node-id", node_id, "--platform", platform, "--at-utc", AT,
        ])
    return code, json.loads(output.getvalue() or error.getvalue())


def test_public_cli_positive_negative_and_unsupported(tmp_path):
    source = copy.deepcopy(BASE)
    node_id = source["data"][0]["nodeId"]
    path = tmp_path / "catalogue.json"
    path.write_bytes(encode(source))
    code, result = _invoke(path, node_id)
    assert code == 0 and result["status"] == "passed"
    assert result["applicability_under_supplied_context"] is True
    assert result["publisher_trust_evaluated"] is False
    assert result["install_permitted"] is False
    assert result["network_request_initiated"] is False
    assert "url" not in result and "package_path" not in result

    source["data"][0]["data"]["expireDate"] = "2000-01-01T00:00:00Z"
    path.write_bytes(encode(source))
    code, result = _invoke(path, node_id)
    assert code == 1 and result["status"] == "failed"
    assert result["applicability_under_supplied_context"] is False

    source["data"][0]["data"]["visibilityInPercent"] = 99
    path.write_bytes(encode(source))
    code, result = _invoke(path, node_id)
    assert code == 2 and result["status"] == "unsupported"
    assert result["applicability_under_supplied_context"] is None
    assert result["registry_accessed"] is False


def test_cli_rejects_ambiguous_source_and_unsafe_file(tmp_path):
    source = copy.deepcopy(BASE)
    node_id = source["data"][0]["nodeId"]
    path = tmp_path / "catalogue.json"
    path.write_bytes(b'{"success":true,"success":true}')
    code, result = _invoke(path, node_id)
    assert code == 1 and result["type"] == "ValueError"
    path.write_bytes(encode(source))
    link = tmp_path / "link.json"
    try:
        link.symlink_to(path)
    except OSError as error:
        if os.name == "nt":
            pytest.skip(f"Windows symlink creation unavailable: {error}")
        raise
    code, result = _invoke(link, node_id)
    assert code == 1 and result["type"] == "ValueError"
