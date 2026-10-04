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


# JSON operation names must fail through the CLI error contract before any
# connection. Hashable scalars and unhashable containers share that contract.
NONSTRING_OPS = [[], {}, None, True, False, 0, 2.5]
NONSTRING_IDS = ["list", "object", "null", "true", "false", "integer", "fraction"]


@pytest.mark.parametrize("mode", ["preview", "apply"])
@pytest.mark.parametrize("op", NONSTRING_OPS, ids=NONSTRING_IDS)
def test_nonstring_output_operation_refuses_before_client_construction(op, mode, tmp_path):
    stdout, stderr = io.StringIO(), io.StringIO()
    argv = ["thermostat", "settings", mode, "//SYNTH/11/p/20", "--host", "127.0.0.1",
        "--port", "1", "--spec-dir", str(tmp_path), "--exclusive-project",
        "--output-operation", json.dumps({"op": op})]
    if mode == "apply":
        argv.extend(["--backup-project", "SYNTHBACKUP"])
    with redirect_stdout(stdout), redirect_stderr(stderr), patch(
            "cbus_toolkit.cgate.CGateClient", side_effect=AssertionError("Unexpected client construction")) as connect:
        status = cli.main(argv)
    result = json.loads(stderr.getvalue() or stdout.getvalue())
    assert status == 1 and result["type"] == "ThermostatTemplateError", result
    assert result["error"] == "Output operation name must be a string", result
    assert "Traceback" not in stdout.getvalue() + stderr.getvalue()
    connect.assert_not_called()


@pytest.mark.parametrize("op", NONSTRING_OPS, ids=NONSTRING_IDS)
def test_direct_damper_normalizer_refuses_nonstring_operation(op):
    from cbus_toolkit.thermostat_damper_controls import normalize_damper_operation
    from cbus_toolkit.thermostat_templates import ThermostatTemplateError

    with pytest.raises(ThermostatTemplateError, match="^Output operation name must be a string$"):
        normalize_damper_operation({"op": op})


VALID_DAMPER_RECORDS = [
    {"op": "damper-form-show"},
    {"op": "damper-after-show"},
    {"op": "damper-group-change", "zone": 1},
    {"op": "damper-modulation-binding", "checked": True},
    {"op": "damper-modulation-click", "checked": False},
    {"op": "damper-zone-update"},
    {"op": "damper-installed-zones", "value": 0},
]


@pytest.mark.parametrize("record", VALID_DAMPER_RECORDS, ids=lambda row: row["op"])
def test_seven_damper_operations_keep_their_normalized_fields(record):
    from cbus_toolkit.thermostat_damper_controls import normalize_damper_operation
    from cbus_toolkit.thermostat_output_groups import normalize_output_operations

    assert normalize_damper_operation(record) == record
    assert tuple(map(json.loads, normalize_output_operations([record]))) == (record,)


@pytest.mark.parametrize("record", [
    {"op": "select-output-group", "parameter": "HeatStage1Output", "address": 7},
    {"op": "add-output-group", "parameter": "HeatStage1Output", "outcome": "accept", "address": 8, "name": "Added Ω"},
    {"op": "edit-output-group", "parameter": "HeatStage1Output", "outcome": "accept", "name": "Edited Ω"},
], ids=["select", "add", "edit"])
def test_ordinary_output_operations_still_route_past_damper_normalizer(record):
    from cbus_toolkit.thermostat_damper_controls import normalize_damper_operation
    from cbus_toolkit.thermostat_output_groups import normalize_output_operations

    assert normalize_damper_operation(record) is None
    assert tuple(map(json.loads, normalize_output_operations([record]))) == (record,)


@pytest.mark.parametrize("mode", ["preview", "apply"])
def test_unknown_string_operation_preserves_structured_preconnection_refusal(mode, tmp_path):
    stdout, stderr = io.StringIO(), io.StringIO()
    argv = ["thermostat", "settings", mode, "//SYNTH/11/p/20", "--host", "127.0.0.1",
        "--port", "1", "--spec-dir", str(tmp_path), "--exclusive-project",
        "--output-operation", '{"op":"unknown-output-operation"}']
    if mode == "apply":
        argv.extend(["--backup-project", "SYNTHBACKUP"])
    with redirect_stdout(stdout), redirect_stderr(stderr), patch(
            "cbus_toolkit.cgate.CGateClient", side_effect=AssertionError("Unexpected client construction")) as connect:
        status = cli.main(argv)
    result = json.loads(stderr.getvalue() or stdout.getvalue())
    assert status == 1 and result["type"] == "ThermostatTemplateError", result
    assert result["error"] == "Unknown thermostat output operation: unknown-output-operation", result
    connect.assert_not_called()
