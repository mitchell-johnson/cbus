"""Preconnection schema guards for caller-explicit damper callbacks.

These tests deny client construction for malformed caller-explicit callbacks.
They do not import a producer to form expected graph/PP effects.
"""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from unittest.mock import patch

import pytest
from cbus_toolkit import cli


MALFORMED = [
    {"op": "damper-form-show", "cache": []},
    {"op": "damper-after-show", "scheduled": True},
    {"op": "damper-zone-update", "value": 3},
    {"op": "damper-group-change", "zone": True},
    {"op": "damper-group-change", "zone": 0},
    {"op": "damper-group-change", "zone": 5},
    {"op": "damper-group-change", "zone": 1, "sender": "foreign"},
    {"op": "damper-modulation-binding", "checked": 1},
    {"op": "damper-modulation-click", "checked": "true"},
    {"op": "damper-modulation-click", "value": True},
    {"op": "damper-installed-zones", "value": True},
    {"op": "damper-installed-zones", "value": 32},
]


@pytest.mark.parametrize("record", MALFORMED, ids=[
    "reject-caller-cache", "reject-invented-scheduling", "reject-update-mask",
    "reject-bool-zone", "reject-zone-zero", "reject-zone-five", "reject-foreign-sender",
    "reject-integer-checkbox", "reject-string-click", "reject-old-value-key",
    "reject-bool-installed-mask", "reject-mask-overflow"])
def test_damper_schema_refuses_before_client_construction(record, tmp_path):
    stdout, stderr = io.StringIO(), io.StringIO()
    argv = ["thermostat", "settings", "apply", "//SYNTH/11/p/20", "--host", "127.0.0.1",
        "--port", "1", "--spec-dir", str(tmp_path), "--exclusive-project",
        "--backup-project", "SYNTHBACKUP", "--output-operation", json.dumps(record)]
    with redirect_stdout(stdout), redirect_stderr(stderr), patch(
            "cbus_toolkit.cgate.CGateClient", side_effect=AssertionError("Unexpected client construction")) as connect:
        status = cli.main(argv)
    result = json.loads(stderr.getvalue() or stdout.getvalue())
    assert status == 1 and result["type"] == "ThermostatTemplateError", result
    assert "damper" in result["error"].lower(), result
    connect.assert_not_called()


def test_duplicate_JSON_and_constants_refuse_before_client_construction(tmp_path):
    for text in ('{"op":"damper-form-show","op":"damper-zone-update"}',
                 '{"op":"damper-installed-zones","value":NaN}'):
        stdout, stderr = io.StringIO(), io.StringIO()
        argv = ["thermostat", "settings", "preview", "//SYNTH/11/p/20", "--host", "127.0.0.1",
            "--port", "1", "--spec-dir", str(tmp_path), "--exclusive-project", "--output-operation", text]
        with redirect_stdout(stdout), redirect_stderr(stderr), patch(
                "cbus_toolkit.cgate.CGateClient", side_effect=AssertionError("Unexpected client construction")) as connect:
            status = cli.main(argv)
        result = json.loads(stderr.getvalue() or stdout.getvalue())
        assert status == 1 and "JSON" in result["error"], result
        connect.assert_not_called()
