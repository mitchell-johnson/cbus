"""Public CLI remains source-bound and avoids updater registry identity claims."""
from __future__ import annotations

import copy
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from unittest.mock import patch

from cbus_toolkit import cli
from cbus_toolkit.toolkit_update_rollout_registry import CohortRegistryRead
from cbus_toolkit import toolkit_update_rollout_registry_cli as command
from tests.test_toolkit_update_applicability import BASE, encode


class OwnedRegistry:
    path = "Software\\CBusToolkitCli\\Tests\\case-1\\SESUVisibility"
    entry = "Cohort"

    def __init__(self, read):
        self.snapshot = read
        self.calls = []

    def read(self):
        self.calls.append("read")
        return self.snapshot

    def write_decimal(self, value):
        self.calls.append(("write", value))
        self.snapshot = CohortRegistryRead("present", "REG_SZ", value)


def invoke(path, node_id, registry, *, ensure=False):
    output, error = io.StringIO(), io.StringIO()
    args = ["update-rollout-owned-registry", "--catalogue-response", str(path),
            "--node-id", node_id, "--owned-namespace", "case-1"]
    if ensure:
        args.append("--ensure-owned-key")
    with patch.object(command, "registry_backend", return_value=registry) as factory, \
         patch("socket.socket", side_effect=AssertionError("rollout initiated network I/O")), \
         redirect_stdout(output), redirect_stderr(error):
        code = cli.main(args)
    factory.assert_called_once_with("case-1", ensure_owned_key=ensure)
    return code, json.loads(output.getvalue() or error.getvalue())


def test_cli_owned_branch_and_exact_typed_receipt(tmp_path):
    source = copy.deepcopy(BASE)
    node = source["data"][0]
    node["data"]["visibilityInPercent"] = 42
    path = tmp_path / "catalogue.json"
    path.write_bytes(encode(source))
    registry = OwnedRegistry(CohortRegistryRead("present", "REG_DWORD", 41))
    code, result = invoke(path, node["nodeId"], registry)
    assert code == 0 and result["status"] == "passed"
    assert result["registry_read"] == {
        "state": "present", "kind": "REG_DWORD", "value": 41,
    }
    assert result["owned_registry_location"] == {
        "hive": "HKCU", "view": "Registry32", "key": registry.path,
        "entry": "Cohort", "ensure_requested": False,
    }
    assert result["registry_accessed"] is True
    assert result["original_updater_registry_identity_verified"] is False
    assert result["publisher_trust_evaluated"] is False
    assert result["install_permitted"] is False
    assert "url" not in result and "package_path" not in result
    assert registry.calls == ["read"]

    node["data"]["visibilityInPercent"] = 100
    path.write_bytes(encode(source))
    registry.calls.clear()
    code, result = invoke(path, node["nodeId"], registry)
    assert code == 2 and result["status"] == "unsupported"
    assert result["registry_accessed"] is False and registry.calls == []


def test_cli_explicit_ensure_option_and_absent_key(tmp_path):
    source = copy.deepcopy(BASE)
    node = source["data"][0]
    node["data"]["visibilityInPercent"] = 42
    path = tmp_path / "catalogue.json"
    path.write_bytes(encode(source))
    registry = OwnedRegistry(CohortRegistryRead("key_absent"))
    code, result = invoke(path, node["nodeId"], registry, ensure=True)
    assert code == 1 and result["status"] == "failed"
    assert result["owned_registry_location"]["ensure_requested"] is True
    assert result["registry_read"]["state"] == "key_absent"
    assert registry.calls == ["read"]
