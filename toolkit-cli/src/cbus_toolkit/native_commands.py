"""Typed Toolkit command workflows recovered from the static decompile.

These commands send Toolkit's own command text and classify replies exactly as
far as ``research/toolkit-client/inventory.json`` records the recovered native
client classes (repository issue #161). A reply the inventory does not record
fails closed: the command is never retried and the receipt reports the
unmodeled reply. No handler claims a physical effect; the server-side
acceptance is the only claim a successful receipt makes.

The transport completes a reply only on a 1xx..6xx status row. Toolkit's own
parser additionally reads 7xx/8xx/9xx rows; when one of those arrives here the
typed receipt says so instead of pretending the row was classified.
"""
from __future__ import annotations

import re

from .cgate import CGateError
from .native import _project, _token

# Unit parameters named by the recovered Get* client classes (issue #162).
UNIT_GET_PARAMETERS = (
    "NetVoltage", "DCPVersion", "DSIChannelStatus", "DSIUnitStatus",
    "Current", "OpStats", "ChannelMode", "ControlMode", "ErrorState",
    "DCPPanic1InputActive", "DCPPanic2InputActive", "DCPPanic3InputActive",
    "DCPBackupGenActive", "DCPHalogenCleanupActive", "RawValue",
)

# Recovered text errors of the Get* client classes (issue #161). Status 420
# arrives as a reply code, so it is not part of this fragment list.
GET_TEXT_ERROR_FRAGMENTS = (
    "Parameter not found",
    "Network not found",
    "Unit not found",
    "Operation not supported by:",
    "Bad application address",
    "Syntax Error",
    "Bad object",
    "No Catalog Available",
)

# Recovered Do*-family error bodies (issue #161).
DO_TEXT_ERROR_FRAGMENTS = (
    "401 Bad object",
    "420 Access denied",
    "408 No Catalog Available",
)

# Recovered PortProbe error bodies (issue #161); 431/432/408 arrive as codes.
PORT_PROBE_TEXT_ERROR_FRAGMENTS = ("PC interface not detected",)
PORT_PROBE_ERROR_CODES = (431, 432, 408)

# Recovered ID error statuses (issue #161); 401 arrives as a status code and
# 821/827 arrive as rows without a 1xx..6xx status (see module docstring).
ID_ERROR_CODES = (827, 821)


class NativeCommandError(RuntimeError):
    """A typed native command failed; `details` completes the receipt."""

    def __init__(self, message, details):
        super().__init__(message)
        self.details = details


def _details(operation, command, extra=None):
    payload = {"operation": operation, "command": command, "sent": True,
               "automatic_replay": False, "cgate_accepted": False,
               "device_effects_verified": False}
    if extra:
        payload.update(extra)
    return payload


def _unmodeled(operation, command, reply_text):
    raise NativeCommandError(
        f"unmodeled C-Gate reply for {operation} ({command}): {reply_text!r}",
        _details(operation, command,
                 {"accepted": False, "cgate_accepted": False,
                  "reply_classification": "unmodeled"}))


def _refused(operation, command, response, codes=None, fragments=()):
    """Fail on a complete server error reply using the recorded fragments."""
    final = response.final if response is not None else ""
    code = final.split(" ", 1)[0]
    matched = bool(code in tuple(map(str, codes or ()))) or \
        any(fragment in final for fragment in fragments)
    classification = "recorded" if matched else "unrecorded"
    line = f"C-Gate refused {operation}: {final}"
    line += " (recorded native error)" if matched else "  reply classification: unrecorded"
    raise NativeCommandError(line, _details(operation, command, {
        "accepted": False, "cgate_accepted": False,
        "response": final, "reply_classification": classification,
        "matched_recorded_fragments": matched,
    }))


def _transport_refusal(operation, command, error, *, statusless_fallthrough=None):
    """Receipt for a transport-level rejection of one exact typed command.

    Toolkit's own parser completes every tagged row, including 7xx/8xx/9xx
    statuses; this transport only completes 1xx..6xx rows, so a reply without
    such a status is reported as `statusless_row` instead of a transport
    fault. Mirrors the shipped records honestly either way.
    """
    statusless = "did not begin with a status code" in str(error)
    if statusless and statusless_fallthrough:
        raise NativeCommandError(
            statusless_fallthrough,
            _details(operation, command, {"reply_classification": "statusless_row"}),
        ) from None
    line = f"C-Gate refused {operation}: {error}  reply classification: "
    line += "statusless_row" if statusless else "transport_error"
    raise NativeCommandError(
        line, _details(operation, command, {
            "reply_classification": "statusless_row" if statusless else "transport_error"}),
    ) from None


def apiver(client):
    """Toolkit always runs `apiver` and demands a 138 version row (issue #161).

    Success requires the recorded ``x=a.b`` value shape; the recovered 400
    error and any other completion fail closed as unmodeled replies.
    """
    command = "apiver"
    operation = "apiver"
    try:
        response = client.command(command)
    except CGateError as error:
        _refused(operation, command, error.response, fragments=("Syntax Error",))
    except RuntimeError as error:
        _transport_refusal(operation, command, error)
    final = response.final
    body = final.split(" ", 1)[1] if final.startswith("138 ") else None
    if body is not None and re.fullmatch(r"[A-Za-z0-9_]+=[0-9]+(\.[0-9]+)*", body):
        return {"operation": operation, "command": command, "sent": True,
                "accepted": True, "cgate_accepted": True,
                "protocol_reply": body, "automatic_replay": False,
                "device_effects_verified": False}
    _unmodeled(operation, command, final)


def config_obget(client, object_path, key):
    """Toolkit `config obget <object> <key>`; a `303 ` row finishes (issue #161)."""
    command = f"config obget {_token(object_path, 'object')} {_token(key, 'key')}"
    return _config_result(client, "config-obget", command)


def config_obset(client, object_path, key, value=None):
    """Toolkit `config obset <object> <key> [<value>]` (issue #162).

    Per the maintained CONFIG family, OBSET is a durable internal override;
    a successful receipt reports a local configuration change, never a host
    or device effect.
    """
    command = f"config obset {_token(object_path, 'object')} {_token(key, 'key')}"
    if value is not None:
        command += " " + _token(value, "value")
    return _config_result(client, "config-obset", command)


def _config_result(client, operation, command):
    try:
        response = client.command(command)
    except CGateError as error:
        _refused(operation, command, error.response,
                 fragments=("400 Syntax Error", "401 Bad object or device ID"))
    except RuntimeError as error:
        _transport_refusal(operation, command, error)
    if response.status == 303:
        return {"operation": operation, "command": command, "sent": True,
                "cgate_accepted": True, "rows": list(response.lines),
                "response": response.final, "automatic_replay": False,
                "device_effects_verified": False,
                "durable_override_intended": operation == "config-obset"}
    _unmodeled(operation, command, response.final)


def label_kfiget(client, address, group):
    """Toolkit `label kfiget <net>/<app> <group>` (issue #162).

    The recovered KFIGet class reads ``300-kfi...`` continuation rows and a
    ``300 kfi...`` final row; anything else fails closed. The argument layout
    is one of the recovery's low-confidence items and stays documented as such.
    """
    if isinstance(group, bool) or not isinstance(group, int) or not 0 <= group <= 255:
        raise ValueError("KFI group must be an integer in 0..255")
    command = f"label kfiget {_token(address, 'label address')} {group}"
    operation = "label-kfiget"
    try:
        response = client.command(command)
    except CGateError as error:
        _refused(operation, command, error.response)
    except RuntimeError as error:
        _transport_refusal(operation, command, error)
    rows = list(response.lines)
    if rows and all(
        (row.startswith("300-kfi") if row.startswith("300-")
         else row.startswith("300 kfi"))
        for row in rows
    ) and not response.final.startswith("300-"):
        return {"operation": operation, "command": command, "sent": True,
                "cgate_accepted": True, "rows": rows,
                "response": response.final, "automatic_replay": False,
                "device_effects_verified": False,
                "argument_layout_confidence": "low"}
    _unmodeled(operation, command, response.final)


def port_list(client):
    """Toolkit's `port list` — 125 rows, a `125 ` row finishes (issue #161).

    The recovered class scans 125- rows and finishes on `125 `; its reported
    "no ports" case is the same completion with an empty list. Anything
    else fails closed.
    """
    command = "port list"
    operation = "port-list"
    try:
        response = client.command(command)
    except CGateError as error:
        _refused(operation, command, error.response)
    except RuntimeError as error:
        _transport_refusal(operation, command, error)
    if response.status not in (125, 126):
        _unmodeled(operation, command, response.final)
    data_rows = [row for row in response.lines if row.startswith("125-")]
    empty = response.status == 126 or "no ports" in response.final
    if empty and data_rows:
        # The recovered fragment marks an empty list; it must not coexist
        # with port rows.
        _unmodeled(operation, command, response.final)
    return {"operation": operation, "command": command, "sent": True,
            "cgate_accepted": True, "rows": data_rows,
            "no_ports": empty,
            "response": response.final, "automatic_replay": False,
            "device_effects_verified": False}


def port_probe(client, name):
    """Toolkit `port probe <port>`; `230 ok` succeeds (issue #161)."""
    command = f"port probe {_token(name, 'port name')}"
    operation = "port-probe"
    try:
        response = client.command(command)
    except CGateError as error:
        _refused(operation, command, error.response,
                 PORT_PROBE_ERROR_CODES, PORT_PROBE_TEXT_ERROR_FRAGMENTS)
    except RuntimeError as error:
        _transport_refusal(operation, command, error)
    if response.status == 230 and response.final == "230 ok":
        return {"operation": operation, "command": command, "sent": True,
                "cgate_accepted": True, "response": response.final,
                "automatic_replay": False, "device_effects_verified": False}
    _unmodeled(operation, command, response.final)


def port_cniscan(client, name, fast=False):
    """Toolkit `port cniscan <range> [fast]`; row `130 ` finishes (issue #161)."""
    command = f"port cniscan {_token(name, 'port name')}" + (" fast" if fast else "")
    operation = "port-cniscan"
    try:
        response = client.command(command)
    except CGateError as error:
        _refused(operation, command, error.response)
    except RuntimeError as error:
        _transport_refusal(operation, command, error)
    if response.status == 130:
        return {"operation": operation, "command": command, "sent": True,
                "cgate_accepted": True, "rows": list(response.lines),
                "response": response.final, "automatic_replay": False,
                "device_effects_verified": False}
    _unmodeled(operation, command, response.final)


def unit_parameter(client, address, parameter):
    """Toolkit's `get <unit> X` family using the recovered class checks.

    Success requires a `300 ` final row (plus the recorded `dcpversion`
    fragment for DCPVersion); the recovered text errors and 420 classify as
    server refusals, and every other reply fails closed (issue #161).
    """
    if parameter not in UNIT_GET_PARAMETERS:
        raise ValueError(
            "Parameter must be one of the recovered unit GET parameters: "
            + ", ".join(UNIT_GET_PARAMETERS))
    command = f"GET {_token(address, 'unit address')} {parameter}"
    operation = "unit-get"
    try:
        response = client.command(command)
    except CGateError as error:
        _refused(operation, command, error.response,
                 (420,), GET_TEXT_ERROR_FRAGMENTS)
    except RuntimeError as error:
        _transport_refusal(operation, command, error)
    final = response.final
    if response.status == 300:
        if parameter == "DCPVersion" and "dcpversion" not in final:
            _unmodeled(operation, command, final)
        return {"operation": operation, "command": command, "sent": True,
                "cgate_accepted": True, "parameter": parameter,
                "rows": list(response.lines), "response": final,
                "automatic_replay": False, "device_effects_verified": False,
                "value_readback_verified": False}
    _unmodeled(operation, command, final)


def unit_do(client, address, operation_command):
    """Toolkit's `do <unit> readrawvalues` (issues #161 and #162).

    Success requires the recorded ``202 Done`` row of the
    SyncReadRawValuesSingleUnravel class; that class records no error
    fragments, so server refusals here are honest unrecorded failures. This
    sends one read-oriented unit command; op-stats persistence is not
    verified here.
    """
    if operation_command != "readrawvalues":
        raise ValueError("Supported DO operation: readrawvalues "
                         "(reset-hardware has its own gated command)")
    command = f"DO {_token(address, 'unit address')} {operation_command}"
    return _do_result(client, "unit-do-readrawvalues", command,
                      error_provenance="SyncReadRawValuesSingleUnravel records only the 202 Done success")


def unit_reset_hardware(client, address):
    """Toolkit's destructive `do <unit> ResetHardware` (issues #161 and #162).

    The caller must pass --request before anything is sent. One exact command
    is sent once; an uncertain outcome is never retried, and no receipt
    claims the physical reset verified. The recovered
    DoPsyncResetHardwareRecallResetOpStats class owns the recorded error
    fragments used here.
    """
    command = f"DO {_token(address, 'unit address')} ResetHardware"
    return _do_result(client, "unit-reset-hardware", command,
                      error_provenance=None)


def _do_result(client, operation, command, error_provenance=None):
    try:
        response = client.command(command)
    except CGateError as error:
        _refused(operation, command, error.response,
                 fragments=DO_TEXT_ERROR_FRAGMENTS if error_provenance is None else ())
    except RuntimeError as error:
        _transport_refusal(operation, command, error)
    if response.final == "202 Done":
        receipt = {"operation": operation, "command": command, "sent": True,
                   "cgate_accepted": True, "response": response.final,
                   "automatic_replay": False, "device_effects_verified": False,
                   "unit_persistence_verified": False}
        if error_provenance is not None:
            receipt["recorded_error_provenance"] = error_provenance
        return receipt
    _unmodeled(operation, command, response.final)


def unit_id(client, address, attribute):
    """Toolkit's `ID <addr> type|version` (issues #161 and #162).

    Exactly one 1xx..6xx row is accepted, and only ``300 type=`` or
    ``300 version=``. The recovered 401 classifies as a server refusal;
    821/827 arrive as rows without a 1xx..6xx status, so with this transport
    they cannot be matched individually and the class's own recorded
    fallthrough is used instead of one of those codes.
    """
    if attribute not in ("type", "version"):
        raise ValueError("Attribute must be type or version")
    command = f"ID {_token(address, 'unit address')} {attribute}"
    operation = "unit-id"
    try:
        response = client.command(command)
    except CGateError as error:
        _refused(operation, command, error.response,
                 fragments=("Bad object or device ID",))
    except RuntimeError as error:
        # Toolkit's ID class reads 7xx/8xx/9xx rows (821/827 are recorded
        # errors); this transport cannot complete those rows, so the class's
        # recorded fallthrough is used without claiming a fragment match.
        _transport_refusal(operation, command, error,
                           statusless_fallthrough="Could not read unit ID (reply without a 1xx..6xx status row)")
    rows = list(response.lines)
    final = response.final
    prefix = f"300 {attribute}="
    if len(rows) == 1 and final.startswith(prefix):
        return {"operation": operation, "command": command, "sent": True,
                "cgate_accepted": True, "attribute": attribute,
                "value": final[len(prefix):], "response": final,
                "automatic_replay": False, "device_effects_verified": False,
                "recorded_status_row_layout": "exactly one 300 row"}
    raise NativeCommandError(
        f"Could not read unit ID from {final!r}",
        _details(operation, command, {"cgate_accepted": False,
                                      "accepted": False,
                                      "response": final,
                                      "reply_classification": "unmodeled"}))


def transform_migrate_sql(client, name):
    """Run Toolkit's recovered `TRANSFORM MIGRATE_SQL <project>` (issue #160).

    The migration shares TRANSFORM PROJECT's recovered reply family: `199`
    rows ending with a "200 OK" row complete the migration; 401/402/405/408,
    a "420 Access denied" or a "460 ... to be filled" refusal fail. A
    successful row whose text names dbversion or schemaversion starts
    Toolkit's upgrade flow; the receipt marks the row without treating it
    as an error.
    """
    operation = "transform-migrate-sql"
    command = f"TRANSFORM MIGRATE_SQL {_project(name)}"
    try:
        response = client.command(command)
    except CGateError as error:
        final = error.response.final
        matched = ("Access denied" in final or "to be filled" in final
                   or final.split(" ", 1)[0] in ("401", "402", "405", "408", "420", "460"))
        line = f"C-Gate refused {operation}: {final}"
        line += " (recorded native error)" if matched else "  reply classification: unrecorded"
        raise NativeCommandError(line, _details(operation, command, {
            "accepted": False, "response": final,
            "reply_classification": "recorded" if matched else "unrecorded",
        })) from None
    except RuntimeError as error:
        _transport_refusal(operation, command, error)
    if response.status != 200:
        # Toolkit's transform rows end on the "200 OK" row; anything else
        # finishing first (for example a lone "199 " row) fails closed.
        _unmodeled(operation, command, response.final)
    receipt = {"operation": operation, "command": command, "sent": True,
               "accepted": True, "cgate_accepted": True,
               "status": response.status, "rows": list(response.lines),
               "response": response.final, "automatic_replay": False,
               "device_effects_verified": False}
    receipt["native_upgrade_flow_detected"] = (
        "dbversion" in response.final or "schemaversion" in response.final)
    return receipt
