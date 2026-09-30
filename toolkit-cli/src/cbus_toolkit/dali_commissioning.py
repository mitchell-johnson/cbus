"""Owned DALI sessions through cmqttd's tagged C-Gate transport.

Extraction can assign DALI addresses. Those modes and every deployment need
an exclusive, durable client attempt record. A record never authorizes replay.
Server replies prove gateway exchanges only; this workflow does not claim
downstream device state, per-field physical readback or power-cycle persistence.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable
from uuid import uuid4

from .cgate import CGateError
from .pci_selected_serial import _Journal
from .programming import quote_value


EXTRACT_TYPES = (
    "EXT_ONLY", "DALI_ONLY", "FULL", "REFRESH_STATUS_INFO",
    "RETRIEVE_RECONCILE", "COND_QUICK", "COND_EXTENDED", "RESCAN_FAULT",
)
DEPLOY_TYPES = ("EXT_ONLY", "DALI_ONLY", "FULL")
READ_ONLY_EXTRACT_TYPES = EXTRACT_TYPES[:5]
CONDITIONAL_EXTRACT_TYPES = EXTRACT_TYPES[5:]
LINES = ("A", "B", "BOTH")
MAX_EDITS_BYTES = 1024 * 1024
_TARGET = re.compile(r"//([A-Za-z0-9_]{1,8})/([0-9]{1,3})/p/([0-9]{1,3})")
_PATH = re.compile(r"/(?:[A-Za-z_][A-Za-z0-9_]*|[0-9]+)(?:/(?:[A-Za-z_][A-Za-z0-9_]*|[0-9]+))*")
_ECG_PROPERTY = re.compile(r"/cdg/daliLines/([0-9]+)/daliEcgs/([0-9]+)/(.+)")
_COMMON_FIELDS = frozenset({
    "groupMembershipBitmask16", "sceneMembershipBitmask16", "minimumLevel",
    "maximumLevel", "recoveryLevel", "failureLevel",
})
_EMERGENCY_FIELDS = frozenset({"emergencyLevel", "prolongTime", "timeout"})


class DaliCommissioningError(RuntimeError):
    """The attached receipt describes the last known phase without replay."""


def dali_target(value: str) -> str:
    match = _TARGET.fullmatch(value) if isinstance(value, str) else None
    if match is None or int(match[2]) > 255 or not 1 <= int(match[3]) <= 254:
        raise ValueError("DALI gateway must be //PROJECT/NETWORK/p/UNIT (network 0..255, unit 1..254)")
    return f"//{match[1]}/{int(match[2])}/p/{int(match[3])}"


def _json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=True, allow_nan=False, sort_keys=True,
                          separators=(",", ":"))
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError("DALI input must be finite JSON data") from error


def _unique_pairs(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError(f"Duplicate JSON property {name!r}")
        result[name] = value
    return result


def _parse_json(value: str):
    return json.loads(value, object_pairs_hook=_unique_pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(
                          ValueError(f"Nonfinite JSON value {value}")))


def validated_edits(edits: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Admit ordered single-property JSON edits and bounded extended-byte edits.

    Numeric JSON-pointer paths avoid ambiguous JXPath predicates. The service
    validates their existence and the complete native deployment model before
    any device write. Extended bytes use SET_EXT_PARAMS, never a model alias.
    """
    if not isinstance(edits, (list, tuple)) or not 1 <= len(edits) <= 1024:
        raise ValueError("DALI deployment needs 1..1024 ordered edits")
    encoded = _json(edits)
    if len(encoded.encode("utf-8")) > MAX_EDITS_BYTES:
        raise ValueError("DALI edits exceed 1 MiB")
    result = _parse_json(encoded)
    paths = []
    addresses = set()
    for edit in result:
        if not isinstance(edit, dict):
            raise ValueError("Each DALI edit must be an object")
        if set(edit) == {"path", "value"}:
            path = edit["path"]
            if not isinstance(path, str) or not _PATH.fullmatch(path) or len(path) > 1024:
                raise ValueError("DALI edit path must be a single absolute property path")
            if not path.startswith(("/cdg/", "/catalog/")):
                raise ValueError("Typed DALI edits must be below /cdg or /catalog")
            if len(quote_value(_json(edit["value"])).encode("utf-8")) > 512 * 1024:
                raise ValueError("One DALI property's encoded command exceeds 512 KiB")
            if any(path == prior or path.startswith(prior + "/") or prior.startswith(path + "/")
                   for prior in paths):
                raise ValueError("DALI edits must not repeat or overlap a property")
            paths.append(path)
        elif set(edit) == {"address", "bytes"}:
            address, values = edit["address"], edit["bytes"]
            if (type(address) is not int or not 256 <= address <= 11375
                    or not isinstance(values, list) or not 1 <= len(values) <= 16
                    or address + len(values) > 11376
                    or any(type(value) is not int or not 0 <= value <= 255 for value in values)):
                raise ValueError("Extended edits need 1..16 bytes in gateway addresses 256..11375")
            selected = set(range(address, address + len(values)))
            if addresses.intersection(selected):
                raise ValueError("DALI extended edits must not overlap")
            addresses.update(selected)
        else:
            raise ValueError("DALI edits require exactly path/value or address/bytes")
    return result


def load_edits(path: Path) -> list[dict[str, Any]]:
    with Path(path).open("rb") as source:
        raw = source.read(MAX_EDITS_BYTES + 1)
    if len(raw) > MAX_EDITS_BYTES:
        raise ValueError("DALI edits file exceeds 1 MiB")
    try:
        value = _parse_json(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("DALI edits file must contain UTF-8 JSON") from error
    return validated_edits(value)


def deployment_edit_dispositions(edits, line, addresses, *, dry_run):
    """Bind requested edits to the selected source-recovered physical plan.

    DALI SESSION SET admits general metadata. Physical deployment consumes a
    smaller set of writable ECG properties; accepting an arbitrary SET as a
    deployable edit would silently omit the user's requested change.
    """
    result = []
    selected_lines = {0} if line == "A" else {1} if line == "B" else {0, 1}
    for edit in edits:
        if "address" in edit:
            result.append({"kind": "extended", "address": edit["address"],
                           "disposition": "planned-extended-device-bytes"})
            continue
        path = edit["path"]
        match = _ECG_PROPERTY.fullmatch(path)
        if match is None:
            if dry_run:
                result.append({"kind": "property", "path": path,
                               "disposition": "session-only-metadata"})
                continue
            raise ValueError("Physical DALI edits must name a writable ECG property; metadata is staged only")
        line_index, slot = int(match[1]), int(match[2])
        if line_index not in selected_lines or not 0 <= slot <= 63:
            raise ValueError("DALI edit is outside the selected line or ECG model slots")
        if addresses is not None and slot not in addresses:
            raise ValueError("DALI edit is outside the selected ECG addresses")
        suffix = match[3]
        structure, _, field = suffix.partition("/")
        scene = re.fullmatch(r"scene/([0-9]+)/level", suffix)
        limit, device_type, step = 255, None, None
        if structure == "commonParams102" and field in _COMMON_FIELDS:
            limit = 65535 if field.endswith("Bitmask16") else 255
            step = "SET_SCENE_VALUES_ECG" if field == "sceneMembershipBitmask16" else "SET_COMMON_PARAMS_ECG"
        elif scene is not None and int(scene[1]) <= 15:
            step = "SET_SCENE_VALUES_ECG"
        elif suffix == "ledParams207/dimmCurve":
            device_type, step = "LED", "SET_LED_PARAMS_ECG"
        elif structure == "emergencyParams202" and field in _EMERGENCY_FIELDS:
            device_type, step = "EMERGENCY", "SET_EMERGENCY_PARAMS_ECG"
        elif dry_run:
            result.append({"kind": "property", "path": path,
                           "disposition": "session-only-metadata"})
            continue
        else:
            raise ValueError("DALI property is not consumed by the native typed deployment plan")
        value = edit["value"]
        if device_type == "LED":
            if value not in ("LINEAR", "LOGARITHMIC"):
                raise ValueError("LED dimmCurve must be LINEAR or LOGARITHMIC")
        elif type(value) is not int or not 0 <= value <= limit:
            raise ValueError(f"DALI writable property needs an integer in 0..{limit}")
        row = {"kind": "property", "path": path, "line_index": line_index,
               "ecg_slot": slot, "step": step, "device_type": device_type,
               "disposition": "planned-native-device-field"}
        if scene is not None:
            row["scene_index"] = int(scene[1])
        result.append(row)
    return result


def _selection(target, line, extract_type, addresses):
    target = dali_target(target)
    if line not in LINES:
        raise ValueError("DALI line must be A, B or BOTH")
    if extract_type not in EXTRACT_TYPES:
        raise ValueError("Unsupported DALI extraction type")
    if addresses is not None:
        if (not isinstance(addresses, (list, tuple)) or not 1 <= len(addresses) <= 64
                or any(type(value) is not int or not 0 <= value <= 63 for value in addresses)
                or len(set(addresses)) != len(addresses)):
            raise ValueError("DALI ECG selection must contain 1..64 distinct addresses in 0..63")
        addresses = list(addresses)
    return target, addresses


def _reply(response) -> dict[str, Any]:
    lines, status = getattr(response, "lines", None), getattr(response, "status", None)
    if (not isinstance(lines, tuple) or not lines or type(status) is not int
            or any(not isinstance(line, str) for line in lines)
            or getattr(response, "final", None) != lines[-1]
            or not lines[-1].startswith(f"{status:03} ")):
        raise DaliCommissioningError("Malformed DALI command response envelope")
    return {"status": status, "lines": list(lines)}


def _model(response) -> dict[str, Any]:
    receipt = _reply(response)
    rows = receipt["lines"]
    if receipt["status"] != 200 or len(rows) != 3 or rows[0] != "120-/" or not rows[1].startswith("120-"):
        raise DaliCommissioningError("DALI SESSION GET did not return one complete root model")
    try:
        model = _parse_json(rows[1][4:])
    except (json.JSONDecodeError, ValueError) as error:
        raise DaliCommissioningError("DALI SESSION GET returned malformed JSON") from error
    if not isinstance(model, dict) or not isinstance(model.get("cdg"), dict):
        raise DaliCommissioningError("DALI SESSION GET returned no typed gateway model")
    return model


def _property(model, path):
    value = model
    for component in path.strip("/").split("/"):
        if isinstance(value, list) and component.isdecimal():
            index = int(component)
            if index >= len(value):
                raise ValueError(f"DALI model property is absent: {path}")
            value = value[index]
        elif isinstance(value, dict) and component in value:
            value = value[component]
        else:
            raise ValueError(f"DALI model property is absent: {path}")
    return value


def _edit_observations(model, edits, *, staged=False):
    observations = []
    for edit in edits:
        if "path" in edit:
            observations.append({"kind": "property", "path": edit["path"],
                                 "value": _property(model, edit["path"])})
        else:
            values = model.get("extParams", {}).get("targetValues" if staged else "values", {})
            observations.append({"kind": "extended", "address": edit["address"],
                                 "value": [values.get(str(edit["address"] + offset))
                                           for offset in range(len(edit["bytes"]))]})
    return observations


def _same_json(left, right):
    return _json(left) == _json(right)


def _admit_model_dispositions(model, dispositions):
    for disposition in dispositions:
        if disposition["disposition"] != "planned-native-device-field":
            continue
        prefix = f"/cdg/daliLines/{disposition['line_index']}/daliEcgs/{disposition['ecg_slot']}"
        ecg = _property(model, prefix)
        if (not isinstance(ecg, dict) or ecg.get("isKnown") is not True
                or ecg.get("isMissing") is True or ecg.get("isConflicting") is True):
            raise DaliCommissioningError("Requested DALI edit targets an ECG excluded from native deployment")
        address = ecg.get("shortAddress", disposition["ecg_slot"])
        if type(address) is not int or address != disposition["ecg_slot"]:
            raise DaliCommissioningError("Requested ECG slot does not match its physical short address")
        required_type = disposition["device_type"]
        types = ecg.get("deviceTypes", [])
        if isinstance(types, dict):
            types = types.get("deviceTypes", [])
        if required_type is not None and (not isinstance(types, list) or required_type not in types):
            raise DaliCommissioningError("Requested DALI property does not match the ECG device type")
        if "scene_index" in disposition:
            params = ecg.get("commonParams102")
            membership = params.get("sceneMembershipBitmask16") if isinstance(params, dict) else None
            if type(membership) is not int or membership & (1 << disposition["scene_index"]) == 0:
                raise DaliCommissioningError("Requested scene level is excluded by its staged scene membership")


class DaliCommissioning:
    """One generated session, one chosen target, no automatic command replay."""

    def __init__(self, client):
        self.client = client
        self.last_evidence: dict[str, Any] | None = None

    def _base(self, target, line, extract_type, addresses, journal):
        evidence = {
            "format": "cbus-dali-commissioning-v1", "operation_id": uuid4().hex,
            "target": target, "line": line, "extract_type": extract_type,
            "ecg_addresses": addresses, "session": "dali_" + uuid4().hex,
            "phase": "preflight", "complete": False, "receipts": [],
            "extract_attempted": False, "deploy_attempted": False,
            "address_assignment_attempted": False, "outcome_uncertain": False,
            "mutating_command_issued": False, "mutation_terminal_received": False,
            "send_may_have_occurred": False, "automatic_retries": 0,
            "rolled_back": False, "physical_effect_verified": False,
            "physical_write_readback_verified": False, "persistence_verified": False,
            "read_only_recovery_only": True, "session_ended": False,
            "operation_completed": False,
            "exclusive_commissioning_ownership_required": True,
            "review_to_write_atomic": False,
            "server_journal_format": "cmqttd-dali-commissioning-journal-v1",
            "journal": str(Path(journal).absolute()) if journal is not None else None,
        }
        self.last_evidence = evidence
        return evidence

    @staticmethod
    def _bind_plan(evidence):
        names = ("operation", "target", "line", "extract_type", "ecg_addresses",
                 "seed_extract", "deploy_type", "edits", "dry_run")
        evidence["plan"] = {name: evidence.get(name) for name in names}
        evidence["plan_sha256"] = hashlib.sha256(_json(evidence["plan"]).encode()).hexdigest()

    def _issue(self, evidence, operation, command):
        try:
            response = self.client.command(command)
        except CGateError as error:
            evidence["receipts"].append({"operation": operation, "command": command,
                                         **_reply(error.response)})
            raise
        receipt = {"operation": operation, "command": command, **_reply(response)}
        evidence["receipts"].append(receipt)
        if receipt["status"] != 200:
            raise DaliCommissioningError(f"DALI {operation} did not return status 200")
        return response

    def _mutating_issue(self, evidence, operation, command):
        evidence["mutating_command_issued"] = True
        try:
            response = self._issue(evidence, operation, command)
        except CGateError as error:
            evidence["mutation_terminal_received"] = True
            final = error.response.final
            # A complete C-Gate reply is not a completed device exchange:
            # 503 transport failures and exhausted AUTO busy/pending states
            # explicitly retain uncertain physical outcomes in cmqttd.
            definite = (error.response.status in (400, 408, 440, 501)
                        or "no bus command was sent" in final
                        or (error.response.status == 502 and re.search(
                            r"error response: (?:NAK|FAIL_INVALID_DEVICE_TYPE|FAIL_INVALID_COMMAND|"
                            r"FAIL_INVALID_PARAMETER|FAIL_INCORRECT_LENGTH)(?: during|$)", final)))
            evidence["outcome_uncertain"] = not definite
            raise
        evidence["mutation_terminal_received"] = True
        evidence["outcome_uncertain"] = False
        return response

    def _preflight(self, evidence, *, deploy_type=None, seed_extract=None):
        prior = evidence.get("capabilities")
        response = self._issue(evidence, "capabilities", "CMQTT CAPABILITIES")
        rows = response.lines
        if len(rows) != 2 or not rows[0].startswith("200-"):
            raise DaliCommissioningError("Malformed CMQTT CAPABILITIES response")
        try:
            capabilities = _parse_json(rows[0][4:])
        except (ValueError, json.JSONDecodeError) as error:
            raise DaliCommissioningError("Malformed CMQTT CAPABILITIES JSON") from error
        if not isinstance(capabilities, dict):
            raise DaliCommissioningError("CMQTT CAPABILITIES is not an object")
        names = (
            "service", "pci_connected", "pci_generation", "programming_lane_state",
            "dali_extended_cal", "dali_delivery_semantics", "dali_session_ext_only",
            "dali_session_typed_extract_plans", "dali_session_typed_deploy_plans",
            "dali_session_conditional_extract_commit", "dali_session_typed_deploy_failure",
            "dali_session_typed_deploy_readback", "dali_commissioning_journal",
        )
        evidence["capabilities"] = {name: capabilities.get(name) for name in names}
        requirements = [
            (capabilities.get("service") == "cmqttd", "selected service is not cmqttd"),
            (capabilities.get("pci_connected") is True, "cmqttd has no connected PCI"),
            (type(capabilities.get("pci_generation")) is int, "missing PCI generation"),
            (capabilities.get("programming_lane_state") == "ready", "programming lane needs reconnect"),
            (capabilities.get("dali_extended_cal") is True, "DALI extended CAL is unavailable"),
            (capabilities.get("dali_delivery_semantics") == "source-correlated-exactly-once-no-replay",
             "DALI delivery does not advertise exact-once/no-replay"),
        ]
        for mode in (evidence["extract_type"], seed_extract):
            if mode is None:
                continue
            plans = capabilities.get("dali_session_typed_extract_plans")
            accepted = capabilities.get("dali_session_ext_only") is True if mode == "EXT_ONLY" else (
                isinstance(plans, list) and all(isinstance(item, str) for item in plans) and mode in plans)
            requirements.append((accepted, f"DALI extraction {mode} is unavailable"))
        conditional = evidence["extract_type"] in CONDITIONAL_EXTRACT_TYPES
        if conditional:
            requirements.append((capabilities.get("dali_session_conditional_extract_commit") ==
                                 "atomic-before-address-unknown-step-by-step-after",
                                 "conditional extraction commit semantics are unavailable"))
        if deploy_type is not None:
            plans = capabilities.get("dali_session_typed_deploy_plans")
            requirements.extend([
                (isinstance(plans, list) and all(isinstance(item, str) for item in plans)
                 and deploy_type in plans, f"DALI deployment {deploy_type} is unavailable"),
                (capabilities.get("dali_session_typed_deploy_failure") ==
                 "stop-at-first-fault-no-rollback-no-replay", "DALI fault/no-replay contract is unavailable"),
                (capabilities.get("dali_session_typed_deploy_readback") == "none-native",
                 "unknown DALI deployment readback contract"),
            ])
        if conditional or deploy_type is not None:
            requirements.append((capabilities.get("dali_commissioning_journal") ==
                                 "cmqttd-dali-commissioning-journal-v1",
                                 "server DALI attempt journal is unavailable"))
        for accepted, reason in requirements:
            if not accepted:
                raise DaliCommissioningError(reason)
        if prior is not None and prior.get("pci_generation") != capabilities.get("pci_generation"):
            evidence["previous_capabilities"] = prior
            raise DaliCommissioningError("PCI generation changed after the initial DALI read; no deployment was sent")

    def _extract(self, evidence, mode, *, operation="extract", mutating=False):
        selection = evidence["ecg_addresses"]
        tail = " " + ",".join(str(address) for address in selection) if selection else ""
        command = (f"DALI SESSION EXTRACT {evidence['session']} {evidence['target']} "
                   f"{evidence['line']} {mode}{tail}")
        evidence["phase"] = operation
        evidence["extract_attempted"] = True
        return (self._mutating_issue if mutating else self._issue)(evidence, operation, command)

    def _get(self, evidence):
        return _model(self._issue(evidence, "get-model", f"DALI SESSION GET {evidence['session']} /"))

    @staticmethod
    def _record(evidence, journal):
        if journal is not None:
            journal.write(evidence)
            evidence["journal_update"] = dict(journal.last_update)

    def _run(self, evidence, action, *, journal=None, deploy_type=None, seed_extract=None):
        owned = False
        pending = None
        writer = _Journal(journal) if journal is not None else None
        try:
            self._preflight(evidence, deploy_type=deploy_type, seed_extract=seed_extract)
            self._record(evidence, writer)
            self._issue(evidence, "new-session", f"DALI SESSION NEW {evidence['session']} "
                        + evidence["target"].split("/")[2])
            owned = True
            if seed_extract is not None:
                self._extract(evidence, seed_extract, operation="seed-extract")
            action(evidence, writer)
            # END is a part of this owned-session workflow. Record the
            # completed operation separately, then publish full completion
            # only after its cleanup has succeeded.
            evidence.update(phase="operation-complete", operation_completed=True)
            self._record(evidence, writer)
        except BaseException as error:
            pending = error
            # A complete application error can follow confirmed or uncertain
            # device writes. Preserve the gateway uncertainty classification
            # independently of receipt framing and cleanup success.
            if evidence["send_may_have_occurred"] and not evidence["mutation_terminal_received"]:
                evidence["outcome_uncertain"] = True
            evidence.update(phase="outcome-uncertain" if evidence["outcome_uncertain"] else "failed",
                            complete=False, error={"type": type(error).__name__, "message": str(error)})
            if writer is not None and writer.expected is not None and not writer.failed:
                try:
                    self._record(evidence, writer)
                except BaseException as journal_error:
                    evidence["journal_error"] = {"type": type(journal_error).__name__, "message": str(journal_error)}
            error.dali_commissioning_evidence = evidence
            raise
        finally:
            if owned and getattr(self.client, "connected", True):
                try:
                    self._issue(evidence, "end-session", f"DALI SESSION END {evidence['session']}")
                    evidence["session_ended"] = True
                    if pending is None:
                        evidence.update(phase="complete", complete=True)
                    if writer is not None and not writer.failed:
                        self._record(evidence, writer)
                except BaseException as cleanup:
                    evidence["cleanup_error"] = {"type": type(cleanup).__name__, "message": str(cleanup)}
                    if pending is None:
                        evidence.update(phase="cleanup-failed", complete=False)
                    if writer is not None and writer.expected is not None and not writer.failed:
                        try:
                            self._record(evidence, writer)
                        except BaseException as journal_error:
                            evidence["cleanup_journal_error"] = {
                                "type": type(journal_error).__name__, "message": str(journal_error)}
                    if pending is None:
                        cleanup.dali_commissioning_evidence = evidence
                        raise
            elif owned:
                evidence["session_cleanup_skipped"] = "transport closed; no reconnect or replay"
                if pending is None:
                    evidence.update(phase="cleanup-failed", complete=False)
                    cleanup = DaliCommissioningError("DALI session cleanup unavailable; transport closed")
                    evidence["cleanup_error"] = {"type": type(cleanup).__name__, "message": str(cleanup)}
                    if writer is not None and writer.expected is not None and not writer.failed:
                        try:
                            self._record(evidence, writer)
                        except BaseException as journal_error:
                            evidence["cleanup_journal_error"] = {
                                "type": type(journal_error).__name__, "message": str(journal_error)}
                    cleanup.dali_commissioning_evidence = evidence
                    raise cleanup
        return evidence

    def extract(self, target, *, line="A", extract_type="DALI_ONLY", addresses=None,
                seed_extract=None, allow_address_assignment=False, journal=None):
        target, addresses = _selection(target, line, extract_type, addresses)
        if seed_extract is not None and seed_extract not in READ_ONLY_EXTRACT_TYPES:
            raise ValueError("Seed extraction must be a read-only extraction type")
        conditional = extract_type in CONDITIONAL_EXTRACT_TYPES
        if conditional and (allow_address_assignment is not True or journal is None):
            raise ValueError("Conditional extraction assigns DALI addresses; require --allow-address-assignment and --journal")
        if not conditional and allow_address_assignment:
            raise ValueError("Address-assignment permission is only meaningful for conditional extraction")
        if journal is not None and Path(journal).exists():
            raise ValueError("DALI attempt journal already exists; it cannot authorize replay")
        evidence = self._base(target, line, extract_type, addresses, journal)
        evidence.update(operation="extract", seed_extract=seed_extract, read_only=not conditional)
        self._bind_plan(evidence)

        def action(evidence, writer):
            if conditional:
                if seed_extract is not None:
                    self._preflight(evidence, seed_extract=seed_extract)
                evidence.update(phase="address-assignment-attempt", address_assignment_attempted=True,
                                send_may_have_occurred=True, outcome_uncertain=True)
                self._record(evidence, writer)
            self._extract(evidence, extract_type, mutating=conditional)
            evidence["outcome_uncertain"] = False
            evidence["model"] = self._get(evidence)
            evidence["model_sha256"] = hashlib.sha256(_json(evidence["model"]).encode()).hexdigest()
        return self._run(evidence, action, journal=journal, seed_extract=seed_extract)

    def deploy(self, target, edits, *, line="A", deploy_type="DALI_ONLY",
               extract_type="DALI_ONLY", addresses=None, dry_run=False, journal=None):
        target, addresses = _selection(target, line, extract_type, addresses)
        edits = validated_edits(edits)
        if type(dry_run) is not bool or deploy_type not in DEPLOY_TYPES:
            raise ValueError("DALI deployment needs a supported deploy type and Boolean dry_run")
        if extract_type not in READ_ONLY_EXTRACT_TYPES:
            raise ValueError("Deployment's initial extraction must be read-only")
        if deploy_type == "EXT_ONLY" and any("path" in edit for edit in edits):
            raise ValueError("EXT_ONLY deployment cannot contain typed model edits")
        if deploy_type == "DALI_ONLY" and any("address" in edit for edit in edits):
            raise ValueError("DALI_ONLY deployment cannot contain extended-byte edits")
        if deploy_type == "FULL" and any(edit.get("path", "").startswith("/catalog/") for edit in edits):
            raise ValueError("FULL deployment after catalogue edits is unsupported by cmqttd")
        dispositions = deployment_edit_dispositions(edits, line, addresses, dry_run=dry_run)
        if not dry_run and journal is None:
            raise ValueError("DALI deployment requires an exclusive --journal before device writes")
        if journal is not None and Path(journal).exists():
            raise ValueError("DALI attempt journal already exists; it cannot authorize replay")
        evidence = self._base(target, line, extract_type, addresses, journal)
        evidence.update(operation="deploy", deploy_type=deploy_type, edits=edits,
                        edits_sha256=hashlib.sha256(_json(edits).encode()).hexdigest(), dry_run=dry_run,
                        edit_dispositions=dispositions)
        self._bind_plan(evidence)

        def action(evidence, writer):
            self._extract(evidence, extract_type)
            before = self._get(evidence)
            evidence["initial_model_sha256"] = hashlib.sha256(_json(before).encode()).hexdigest()
            # Prove every property exists before the first staged change.
            evidence["before_edits"] = _edit_observations(before, edits)
            evidence["before_edits_sha256"] = hashlib.sha256(_json(evidence["before_edits"]).encode()).hexdigest()
            evidence["phase"] = "stage-edits"
            for edit in edits:
                if "path" in edit:
                    command = (f"DALI SESSION SET {evidence['session']} {edit['path']} "
                               + quote_value(_json(edit["value"])))
                else:
                    command = (f"DALI SESSION SET_EXT_PARAMS {evidence['session']} {edit['address']} "
                               + " ".join(str(value) for value in edit["bytes"]))
                self._issue(evidence, "stage-edit", command)
            evidence["model"] = self._get(evidence)
            evidence["model_sha256"] = hashlib.sha256(_json(evidence["model"]).encode()).hexdigest()
            evidence["staged_edits"] = _edit_observations(evidence["model"], edits, staged=True)
            evidence["staged_edits_sha256"] = hashlib.sha256(_json(evidence["staged_edits"]).encode()).hexdigest()
            for edit, observation in zip(edits, evidence["staged_edits"], strict=True):
                expected = edit.get("value") if "path" in edit else edit["bytes"]
                if not _same_json(observation["value"], expected):
                    raise DaliCommissioningError("DALI staged model does not retain the reviewed edit")
            if not dry_run:
                _admit_model_dispositions(evidence["model"], dispositions)
            if dry_run:
                return
            # The seed read and SET operations can take minutes. A replacement
            # transport cannot silently inherit this client plan's old image.
            self._preflight(evidence, deploy_type=deploy_type)
            tail = " " + ",".join(str(value) for value in addresses) if addresses else ""
            evidence.update(phase="deploy-attempt", deploy_attempted=True,
                            send_may_have_occurred=True, outcome_uncertain=True)
            self._record(evidence, writer)
            self._mutating_issue(evidence, "deploy", f"DALI SESSION DEPLOY {evidence['session']} "
                                 f"{target} {line} {deploy_type}{tail}")
            evidence["outcome_uncertain"] = False
            # This is the retained session model, not a second physical read.
            evidence["model"] = self._get(evidence)
            evidence["model_sha256"] = hashlib.sha256(_json(evidence["model"]).encode()).hexdigest()
        return self._run(evidence, action, journal=journal, deploy_type=deploy_type)

    def recover(self, journal, *, extract_type=None):
        """Compare a saved attempt with fresh reads; never deploy or resume it.

        The journal hash validates the recorded plan's consistency, not its
        authenticity. Matching fields do not establish which writer caused
        them, device atomicity, unedited native deploy fields or persistence.
        """
        path = Path(journal)
        with path.open("rb") as source:
            raw = source.read(16 * 1024 * 1024 + 1)
        if len(raw) > 16 * 1024 * 1024:
            raise ValueError("DALI attempt journal exceeds 16 MiB")
        try:
            saved = _parse_json(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as error:
            raise ValueError("DALI attempt journal must contain UTF-8 JSON") from error
        if not isinstance(saved, dict) or saved.get("format") != "cbus-dali-commissioning-v1":
            raise ValueError("Unsupported DALI attempt journal")
        plan = saved.get("plan")
        plan_names = {"operation", "target", "line", "extract_type", "ecg_addresses",
                      "seed_extract", "deploy_type", "edits", "dry_run"}
        if (not isinstance(plan, dict) or set(plan) != plan_names
                or saved.get("plan_sha256") != hashlib.sha256(_json(plan).encode()).hexdigest()
                or any(not _same_json(saved.get(name), value) for name, value in plan.items())):
            raise ValueError("DALI attempt journal does not match its bound plan")
        target, addresses = _selection(plan["target"], plan["line"], plan["extract_type"], plan["ecg_addresses"])
        edits = validated_edits(plan["edits"]) if plan["operation"] == "deploy" else []
        if plan["operation"] not in ("deploy", "extract"):
            raise ValueError("Unknown DALI attempt operation")
        if plan["operation"] == "deploy" and (
                plan["deploy_type"] not in DEPLOY_TYPES or type(plan["dry_run"]) is not bool
                or plan["extract_type"] not in READ_ONLY_EXTRACT_TYPES):
            raise ValueError("DALI deployment journal has invalid selector facts")
        if edits and saved.get("edits_sha256") != hashlib.sha256(_json(edits).encode()).hexdigest():
            raise ValueError("DALI journal edits do not match their digest")
        before = saved.get("before_edits", [])
        if edits and (not isinstance(before, list) or len(before) != len(edits)):
            raise ValueError("DALI journal has no complete pre-edit observations")
        if edits and saved.get("before_edits_sha256") != hashlib.sha256(_json(before).encode()).hexdigest():
            raise ValueError("DALI journal pre-edit observations do not match their digest")
        if edits and saved.get("staged_edits_sha256") != hashlib.sha256(_json(saved.get("staged_edits")).encode()).hexdigest():
            raise ValueError("DALI journal staged observations do not match their digest")
        for edit, observation in zip(edits, before, strict=True):
            expected_keys = {"kind", "path", "value"} if "path" in edit else {"kind", "address", "value"}
            if (not isinstance(observation, dict) or set(observation) != expected_keys
                    or observation.get("kind") != ("property" if "path" in edit else "extended")
                    or observation.get("path" if "path" in edit else "address") != edit.get("path", edit.get("address"))):
                raise ValueError("DALI journal pre-edit observations do not match its edits")
        if extract_type is None:
            has_extended = any("address" in edit for edit in edits)
            has_typed = any("path" in edit for edit in edits)
            extract_type = "FULL" if has_extended and has_typed else "EXT_ONLY" if has_extended else "DALI_ONLY"
        if extract_type not in READ_ONLY_EXTRACT_TYPES:
            raise ValueError("Recovery must use a read-only extraction type")
        result = {
            "format": "cbus-dali-recovery-v1", "journal": str(path.absolute()),
            "journal_sha256": hashlib.sha256(raw).hexdigest(), "plan_sha256": saved["plan_sha256"],
            "target": target, "classification": "unreadable", "conclusive": False,
            "observations": [], "writes_attempted": False, "automatic_retries": 0,
            "attempt_replay_authorized": False, "persistence_verified": False,
            "physical_effect_verified": False, "original_journal_modified": False,
        }
        try:
            observation = self.extract(target, line=plan["line"], extract_type=extract_type, addresses=addresses)
        except BaseException as error:
            result["fresh_extraction"] = getattr(error, "dali_commissioning_evidence", None)
            result["error"] = {"type": type(error).__name__, "message": str(error)}
            error.dali_commissioning_evidence = result
            raise
        result["fresh_extraction"] = observation
        model = observation["model"]
        for edit, previous in zip(edits, before, strict=True):
            row = {"kind": previous["kind"], "before": previous["value"],
                   "expected": edit["value"] if "path" in edit else edit["bytes"]}
            row["path" if "path" in edit else "address"] = edit.get("path", edit.get("address"))
            try:
                actual = _edit_observations(model, [edit])[0]["value"]
                readable = not ("address" in edit and any(value is None for value in actual))
            except ValueError:
                actual, readable = None, False
            row["observed"] = actual
            if not readable:
                row["classification"] = "unreadable"
            elif _same_json(actual, row["expected"]):
                row["classification"] = "expected"
            elif _same_json(actual, row["before"]):
                row["classification"] = "unchanged"
            else:
                row["classification"] = "mixed"
            result["observations"].append(row)
        classes = {row["classification"] for row in result["observations"]}
        if classes and "unreadable" not in classes:
            result["classification"] = next(iter(classes)) if len(classes) == 1 else "mixed"
            result["conclusive"] = True
        elif not edits:
            result["reason"] = "address-assignment attempt has no per-device before/expected edit contract"
        result["scope"] = "reviewed edited fields only; native deployment may write additional fields"
        self.last_evidence = result
        return result


def error_payload(error):
    evidence = getattr(error, "dali_commissioning_evidence", None)
    return {"dali_commissioning_evidence": evidence} if isinstance(evidence, dict) else {}
