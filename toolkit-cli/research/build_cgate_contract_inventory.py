#!/usr/bin/env python3
"""Build the evidence-bounded C-Gate command contract inventory.

The routing matrix proves that a path reaches a handler.  It does not, by
itself, prove every selector, session, response or side-effect contract.  This
generator keeps those claims separate and records unresolved subaxes instead
of filling gaps from command names.
"""
from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = ROOT.parent
MATRIX_PATH = REPOSITORY / "rust" / "cbus-cgate" / "src" / "capability_matrix.rs"
MANUAL_PATH = REPOSITORY / "rust" / "cbus-cgate" / "src" / "manual.rs"
SERVICE_PATH = REPOSITORY / "rust" / "cbus-cgate" / "src" / "service.rs"
SURFACE_PATH = ROOT / "docs" / "toolkit-surface.json"
OUTPUT_PATH = ROOT / "src" / "cbus_toolkit" / "cgate-contract-inventory.json"

AXIS_SUBAXES = {
    "selector_grammar": ("command_path", "argument_arity", "value_domains"),
    "session_states": ("connection", "recovery_mode", "selection_and_locks"),
    "target_forms": ("address_shape", "route_shape"),
    "authorization": ("connection_policy", "programming_gate", "handler_roles"),
    "response_event_envelopes": (
        "tag_and_completion_framing",
        "command_envelope",
        "event_fanout",
    ),
    "effects_routing": ("routing_class", "physical_io_boundary", "state_effect"),
    "implementation_acceptance": (
        "endpoint_route",
        "native_obsolescence",
        "functional_acceptance",
    ),
}

MATRIX_REF = "rust/cbus-cgate/src/capability_matrix.rs#CAPABILITY_MATRIX"
SUPPLEMENT_REF = "rust/cbus-cgate/src/capability_matrix.rs#SUPPLEMENT_ROUTING"
MANUAL_REF = "rust/cbus-cgate/src/manual.rs#APPLICATION_COMMANDS+MEDIA_COMMANDS"
SERVICE_AUTH_REF = "rust/cbus-cgate/src/service.rs#requires_programming_auth"
SERVICE_SESSION_REF = "rust/cbus-cgate/src/service.rs#Service::handle"
TELEPHONY_PROGRAM_PATHS = {
    "TELEPHONY CLEAR_DIVERSION",
    "TELEPHONY DIVERT",
    "TELEPHONY ISOLATE_SECONDARY_OUTLET",
    "TELEPHONY RECALL_LAST_NUMBER_REQUEST",
    "TELEPHONY REJECT_INCOMING_CALL",
}


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def canonical_digest(value: dict) -> str:
    return sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def resolved(value: object, *source_refs: str) -> dict:
    return {"status": "resolved", "value": value, "source_refs": list(source_refs)}


def unresolved(reason: str, *source_refs: str, known: object | None = None) -> dict:
    result = {
        "status": "unresolved",
        "reason": reason,
        "source_refs": list(source_refs),
    }
    if known is not None:
        result["known"] = known
    return result


def capability_paths() -> tuple[list[dict], list[dict]]:
    text = MATRIX_PATH.read_text(encoding="utf-8")
    primary_text, supplement_text = text.split("pub const SUPPLEMENT_ROUTING", maxsplit=1)
    pattern = re.compile(
        r'CapabilityEntry \{ path: "([^"]+)", class: RoutingClass::(\w+), evidence: "([^"]*)" \}'
    )

    def rows(part: str, inventory: str) -> list[dict]:
        return [
            {
                "path": path,
                "inventory": inventory,
                "routing_class": routing,
                "routing_evidence": evidence,
            }
            for path, routing, evidence in pattern.findall(part)
        ]

    primary = rows(primary_text, "primary")
    supplement = rows(supplement_text, "supplement")
    if len(primary) != 431 or len(supplement) != 11:
        raise ValueError(
            f"Expected 431 primary and 11 supplement paths, found "
            f"{len(primary)} and {len(supplement)}"
        )
    paths = [row["path"] for row in primary + supplement]
    if len(paths) != len(set(paths)):
        raise ValueError("C-Gate capability paths must be unique across both inventories")
    return primary, supplement


def application_arities() -> dict[str, dict[str, int | None]]:
    text = MANUAL_PATH.read_text(encoding="utf-8")
    start = text.index("pub const APPLICATION_COMMANDS")
    end = text.index("/// Match a two-word application command exactly.", start)
    pattern = re.compile(
        r'ApplicationSpec\s*\{\s*name:\s*"([^"]+)",\s*'
        r"min_args:\s*(\d+),\s*max_args:\s*(Some\((\d+)\)|None),\s*\}",
        re.S,
    )
    result: dict[str, dict[str, int | None]] = {}
    for name, minimum, maximum_form, maximum in pattern.findall(text[start:end]):
        result[name] = {
            "minimum_after_command": int(minimum),
            "maximum_after_command": int(maximum) if maximum_form != "None" else None,
        }
    if len(result) != 70:
        raise ValueError(f"Expected 70 declarative application arities, found {len(result)}")
    return result


def public_syntax_hashes() -> dict[str, str]:
    surface = json.loads(SURFACE_PATH.read_text(encoding="utf-8"))
    result: dict[str, str] = {}
    for command in surface["public_commands"]:
        path = command["command"]
        syntax_digest = command["source"]["syntax_sha256"]
        if path in result:
            raise ValueError(f"Duplicate public command syntax: {path}")
        result[path] = syntax_digest
    if len(result) != 209:
        raise ValueError(f"Expected 209 public command blocks, found {len(result)}")
    return result


def authorization_source_digest() -> str:
    text = SERVICE_PATH.read_text(encoding="utf-8")
    start = text.index("fn requires_programming_auth(")
    end = text.index("\nfn local_command(", start)
    return sha256(text[start:end].encode()).hexdigest()


def dali_programming_gate(parts: list[str]) -> str:
    if len(parts) < 2:
        return "not_required_by_programming_gate"
    if len(parts) >= 3 and parts[1] == "CATALOG":
        return (
            "required_when_gate_armed"
            if parts[2] == "RELOAD"
            else "not_required_by_programming_gate"
        )
    if len(parts) >= 3 and parts[1] in {"ERROR_REPORTING", "MEASUREMENT"}:
        return (
            "required_when_gate_armed"
            if parts[2].startswith("SET_")
            else "not_required_by_programming_gate"
        )
    if len(parts) >= 3 and parts[1] == "GATEWAY":
        command = parts[2]
        mutating = {
            "FACTORY_RESET",
            "LOAD_PRESET",
            "RESTART",
            "SAVE_TO_NVM",
            "PAGED_STORE",
            "SET_EXTENDED_PARAMETERS",
            "WRITE_EXTENDED_PARAMETERS",
            "SET_PRIMARY_ADDRESS",
            "SET_VIRTUAL_GROUP",
        }
        if command not in mutating:
            return "not_required_by_programming_gate"
        if command in {"FACTORY_RESET", "LOAD_PRESET", "RESTART", "SAVE_TO_NVM"}:
            return "invocation_variant_dependent"
        return "required_when_gate_armed"
    if len(parts) >= 3 and parts[1] == "SESSION":
        return (
            "not_required_by_programming_gate"
            if parts[2] in {"LIST", "GET", "MULTIGET"}
            else "required_when_gate_armed"
        )
    command_index = 2 if len(parts) >= 2 and parts[1] == "EMERGENCY" else 1
    if len(parts) <= command_index:
        return "not_required_by_programming_gate"
    mutating = {
        "FACTORY_RESET",
        "ADDRESS_UNKNOWN",
        "REASSIGN_ONE",
        "SWAP_TWO",
        "REPLACE_BAD",
        "REMOVE_MANY",
        "WINK_ECG_ON",
        "WINK_ECG_OFF",
        "RECALL_MAX",
        "RECALL_MIN",
        "RECALL_OFF",
        "RECALL_MAX_MANY",
        "RECALL_OFF_MANY",
        "TRIGGER_SCENE",
        "SET_SCENE_VALUES_LOW",
        "SET_SCENE_VALUES_HIGH",
        "SET_SCENE_LEVEL_MANY",
        "SET_MIN_MANY",
        "SET_MAX_MANY",
        "SET_RECOVERY_MANY",
        "SET_FAILURE_MANY",
        "SET_GROUP_MANY",
        "REMOVE_GROUP_MANY",
        "SET_COMMON_PARAMS",
        "SET_LED_PARAMS",
        "SET_COLOUR_TEMPERATURE",
        "SET_COLOUR_POWER_FAIL_PARAMS",
        "SET_PARAMS",
        "SET_LEVEL_MANY",
        "SET_PROLONG_MANY",
        "SET_TEST_TIMEOUT_MANY",
        "START_FUNCTION_TEST",
        "START_DURATION_TEST",
        "STOP_TEST",
        "REST",
        "INHIBIT",
        "RELIGHT",
        "UPDATE_TEST_STATUS",
    }
    return (
        "invocation_variant_dependent"
        if parts[command_index] in mutating
        else "not_required_by_programming_gate"
    )


def programming_gate(path: str) -> str:
    parts = path.split()
    verb = parts[0]
    sub = parts[1] if len(parts) > 1 else ""
    if verb in {"LOGIN", "LOGOUT"}:
        return "session_auth_command_bypass"
    if verb in {"ACCESSCONTROL", "ACCESS_CONTROL"}:
        required = sub in {"CLOSE", "LOCK"}
    elif verb in {"SHUTDOWN", "CONFIRM", "RUN", "STOP", "TEST_SPAM"}:
        required = True
    elif verb == "LOG":
        required = sub == "EXTRACT"
    elif verb == "CONVERTUNIT":
        required = sub == "CONVERT"
    elif verb == "BROADCAST_EVENT":
        required = True
    elif verb == "ACCESS":
        required = sub in {"ADD", "DELETE", "LOAD", "SAVE"}
    elif verb == "CONFIG":
        required = sub in {"SET", "LOAD", "SAVE", "OBSET", "OBRESET"}
    elif verb == "FILE":
        required = sub in {"UPLOAD", "DELETE", "MKDIR"}
    elif verb == "PORT":
        required = sub in {"CNISCAN", "CNISCAN2", "PROBE", "REFRESH"}
    elif verb == "MEASUREMENT":
        required = sub == "DATA"
    elif verb == "AIRCON":
        required = bool(sub and sub != "REFRESH")
    elif verb == "AUDIO":
        required = bool(
            sub
            and sub
            not in {
                "CURRENT_FEED",
                "OUTPUT_DEVICE_STATUS_REQUEST",
                "OUTPUT_ERROR_CODE",
                "REQUEST_CURRENT_FEED",
                "ZONE_DESCRIPTOR_REQUEST",
                "ZONE_FEED_LABEL_REQUEST",
            }
        )
    elif verb == "SECURITY":
        required = bool(sub and sub not in {"STATUS_REQUEST", "REQUEST_ZONE_NAME"})
    elif verb == "MEDIATRANSPORT":
        required = bool(sub and sub not in {"STATUS_REQUEST", "ENUMERATE"})
    elif verb == "TELEPHONY":
        required = bool(sub and sub != "RECALL_LAST_NUMBER_REQUEST")
    elif verb == "IDENTIFY":
        required = bool(sub)
    elif verb == "SHORTMESSAGE":
        required = sub == "SEND"
    elif verb == "EREPORT":
        required = sub == "MESSAGE"
    elif verb == "DALI":
        return dali_programming_gate(parts)
    elif verb == "PP":
        required = sub in {
            "LOCK",
            "UNLOCK",
            "CANCEL_LOCK",
            "START",
            "END",
            "NEW",
            "LOAD",
            "LOAD_FROM_FILE",
            "SAVE",
            "SAVE_TO_SOURCE",
            "SET",
            "RESET",
            "RESET_TO_DEFAULTS",
            "COPY",
            "WRITE_PATCH",
            "SET_RAW_DATA",
            "RELOAD_CATALOG",
        }
    elif verb == "PROGRAMMER":
        required = sub in {
            "CREATE",
            "DELETE",
            "ADD_INSTRUCTION",
            "CANCEL_INSTRUCTION",
            "TEST",
            "TRIGGER",
        }
    elif verb == "DEPLOY_QUEUE":
        required = sub in {"ADD", "DELETE", "DELETE_ALL", "RETRY"}
    elif verb == "PROJECT":
        required = sub in {
            "NEW",
            "LOAD",
            "SAVE",
            "START",
            "STOP",
            "CLOSE",
            "DELETE",
            "COPY",
            "RENAME",
            "ARCHIVE",
            "RESTORE",
            "REPAIR",
        }
    elif verb == "EVENT_CHANNEL":
        required = sub in {"SUB", "UNSUB"}
    elif verb in {"LOCK", "UNLOCK"}:
        required = True
    elif verb == "CGL":
        required = sub == "IMPORT"
    elif verb == "REPOSITORY":
        required = sub == "USE"
    elif verb in {"SET", "NEW"}:
        required = True
    elif verb == "NET":
        required = sub in {
            "CREATE",
            "DELETE",
            "FLUSH",
            "LEARN",
            "LOAD",
            "OPEN",
            "CLOSE",
            "RENAME",
            "SAVE",
            "SET_PROJECT_IDENTIFY",
            "UNRAVEL",
            "UNRAVELUNIT",
        }
    elif verb == "NETWORK":
        required = sub == "LOCATE"
    elif verb == "LABEL":
        required = sub in {"CLEAR", "CLEAREDLT", "KFIGET", "KFISET"}
    elif verb == "SCENE":
        return "invocation_variant_dependent"
    elif verb == "DO":
        return "invocation_variant_dependent"
    elif verb in {
        "DBADD",
        "DBCOPY",
        "DBCREATE",
        "DBNEW",
        "DBRENAMENET",
        "DBRENAMENETSAFE",
        "DBSET",
        "DBSETSAFE",
        "DBSETXML",
        "DBUPDATE",
        "DBADDSAFE",
        "DBCOPYSAFE",
        "DBDELETE",
        "DBSAVE",
        "DBLOAD",
        "DBCREATENET",
        "DBCREATEAPP",
        "DBCREATEGROUP",
        "DBCREATEUNIT",
    }:
        required = True
    else:
        required = False
    return "required_when_gate_armed" if required else "not_required_by_programming_gate"


def axis(subaxes: dict[str, dict]) -> dict:
    statuses = Counter(value["status"] for value in subaxes.values())
    status = (
        "resolved"
        if statuses["resolved"] == len(subaxes)
        else "unresolved"
        if statuses["resolved"] == 0
        else "partial"
    )
    return {"status": status, "subaxes": subaxes}


def build_row(
    row: dict,
    arities: dict[str, dict[str, int | None]],
    syntax_hashes: dict[str, str],
) -> dict:
    path = row["path"]
    matrix_ref = MATRIX_REF if row["inventory"] == "primary" else SUPPLEMENT_REF
    arity = arities.get(path)
    help_digest = syntax_hashes.get(path)
    selector_refs = [matrix_ref]
    if arity is not None:
        selector_refs.append(MANUAL_REF)
    if help_digest is not None:
        selector_refs.append(f"toolkit-cli/docs/toolkit-surface.json#cgate:{path}")
    selector = {
        "command_path": resolved(path.split(), matrix_ref),
        "argument_arity": unresolved(
            (
                "A declarative model arity exists, but it is not yet independently reconciled with every production service parser branch."
                if arity is not None
                else "No machine-readable argument-count contract is committed for this path."
            ),
            *selector_refs,
            known={
                **({"declarative_model_arity": arity} if arity is not None else {}),
                **({"help_syntax_sha256": help_digest} if help_digest else {}),
            }
            or None,
        ),
        "value_domains": unresolved(
            "Argument names, ranges, aliases and conditional branches are not yet normalized into a structured contract.",
            *selector_refs,
            known={"help_syntax_sha256": help_digest} if help_digest else None,
        ),
    }
    if path in {"LOGIN", "LOGOUT"}:
        recovery_value: object = "allowed_authentication_command"
    elif path in {"#", "//"}:
        recovery_value = {
            "untagged": "consumed_before_recovery_gate",
            "tagged": "syntax_error_before_recovery_gate",
        }
    elif path == "EVENT":
        recovery_value = "handled_by_connection_event_mode_before_recovery_gate"
    else:
        recovery_value = "denied_until_login"
    session = {
        "connection": resolved("connected_line_session", SERVICE_SESSION_REF),
        "recovery_mode": resolved(recovery_value, SERVICE_SESSION_REF),
        "selection_and_locks": unresolved(
            "Selected project/network, event subscription, advisory lock and programming-session preconditions are not yet mapped per path.",
            SERVICE_SESSION_REF,
            matrix_ref,
        ),
    }
    targets = {
        "address_shape": unresolved(
            "Accepted path, OID, serial, unit, application and group target forms are not yet normalized per path.",
            matrix_ref,
            *selector_refs[1:],
        ),
        "route_shape": unresolved(
            "Direct, selected-network and bridged-route applicability is not yet normalized per selector variant.",
            matrix_ref,
        ),
    }
    gate = programming_gate(path)
    gate_axis = (
        unresolved(
            "LOGIN-gate behavior depends on invocation arguments within this command path.",
            SERVICE_AUTH_REF,
            known={"known_modes": ["required_when_gate_armed", "not_required_by_programming_gate"]},
        )
        if gate == "invocation_variant_dependent"
        else resolved(gate, SERVICE_AUTH_REF)
    )
    handler_roles = (
        resolved(
            {
                "minimum_access_level": "Program",
                "enforced_before_physical_handler": True,
                "lower_access_result": 420,
            },
            SERVICE_SESSION_REF,
            matrix_ref,
        )
        if path in TELEPHONY_PROGRAM_PATHS
        else unresolved(
            "Command-specific Clipsal/Max role filtering and object-level authorization are not yet normalized per path.",
            SERVICE_SESSION_REF,
            matrix_ref,
        )
    )
    authorization = {
        "connection_policy": resolved(
            "peer_access_policy_then_recovery_login_policy", SERVICE_SESSION_REF
        ),
        "programming_gate": gate_axis,
        "handler_roles": handler_roles,
    }
    silent = path in {"#", "//"}
    obsolete = row["routing_class"] == "Obsolete400"
    if path == "#":
        framing = {
            "untagged": "no_response",
            "tagged": "untagged_400_syntax_error",
        }
    elif path == "//":
        framing = {
            "untagged": "no_response",
            "tagged": "tag_echoed_400_syntax_error",
        }
    else:
        framing = "parsed_tag_used_for_tagged_numeric_status_response"
    response = {
        "tag_and_completion_framing": resolved(
            framing,
            SERVICE_SESSION_REF,
            matrix_ref,
        ),
        "command_envelope": (
            resolved(framing, SERVICE_SESSION_REF, matrix_ref)
            if silent
            else unresolved(
                "Exact success, syntax, state, transport and timeout envelopes are not yet structured for every selector variant.",
                matrix_ref,
                known={"native_obsolete_status": 400} if obsolete else None,
            )
        ),
        "event_fanout": (
            resolved("none", matrix_ref)
            if silent or obsolete
            else unresolved(
                "Synchronous response versus asynchronous event classes, filters and ordering are not yet structured per variant.",
                matrix_ref,
            )
        ),
    }
    routing_class = row["routing_class"]
    io_boundary = {
        "Physical": "physical_or_bus_observed_primary_route",
        "LocalDatabase": "local_database_or_connection_state_no_bus_io",
        "FailClosed502": "fail_closed_no_bus_io",
        "Obsolete400": "native_obsolete_no_bus_io",
        "Rejected4xx": "rejected_no_bus_io",
    }[routing_class]
    effects = {
        "routing_class": resolved(routing_class, matrix_ref),
        "physical_io_boundary": resolved(io_boundary, matrix_ref),
        "state_effect": (
            resolved("none", matrix_ref)
            if silent or obsolete
            else unresolved(
                "The matrix evidence describes the primary route but does not normalize every database, cache, session, event and device effect.",
                matrix_ref,
                known={"routing_evidence": row["routing_evidence"]},
            )
        ),
    }
    endpoint_route = {
        "Physical": "implemented_physical_route",
        "LocalDatabase": "implemented_local_or_session_route",
        "FailClosed502": "implemented_fail_closed_route",
        "Obsolete400": "implemented_native_obsolete_response",
        "Rejected4xx": "implemented_rejection_route",
    }[routing_class]
    implementation = {
        "endpoint_route": resolved(endpoint_route, matrix_ref),
        "native_obsolescence": resolved(obsolete, matrix_ref),
        "functional_acceptance": unresolved(
            "No parity evidence receipt accepts all selector, state, error, differential, physical and recovery dimensions for this path.",
            "toolkit-cli/src/cbus_toolkit/parity-evidence.json",
        ),
    }
    axes = {
        "selector_grammar": axis(selector),
        "session_states": axis(session),
        "target_forms": axis(targets),
        "authorization": axis(authorization),
        "response_event_envelopes": axis(response),
        "effects_routing": axis(effects),
        "implementation_acceptance": axis(implementation),
    }
    contract = {
        "id": f"cgate-contract:{sha256(path.encode()).hexdigest()[:16]}",
        "path": path,
        "inventory": row["inventory"],
        "routing_evidence": row["routing_evidence"],
        "axes": axes,
    }
    contract["axes_sha256"] = canonical_digest(axes)
    contract["contract_sha256"] = canonical_digest(contract)
    return contract


def build() -> dict:
    primary, supplement = capability_paths()
    arities = application_arities()
    syntax_hashes = public_syntax_hashes()
    contracts = [
        build_row(row, arities, syntax_hashes) for row in primary + supplement
    ]
    axis_counts: dict[str, dict[str, int]] = {}
    subaxis_counts: dict[str, dict[str, int]] = {}
    for axis_name, subaxis_names in AXIS_SUBAXES.items():
        axis_counts[axis_name] = dict(
            sorted(Counter(row["axes"][axis_name]["status"] for row in contracts).items())
        )
        for subaxis_name in subaxis_names:
            key = f"{axis_name}.{subaxis_name}"
            subaxis_counts[key] = dict(
                sorted(
                    Counter(
                        row["axes"][axis_name]["subaxes"][subaxis_name]["status"]
                        for row in contracts
                    ).items()
                )
            )
    return {
        "schema_version": 1,
        "target": "C-Gate 3.4.0.2001 command endpoint",
        "inventory_version": "cgate-contracts-2026-09-27.1",
        "purpose": "Evidence-bounded per-path contracts; unresolved fields are explicit and route coverage is not functional acceptance.",
        "sources": {
            "capability_matrix": {"sha256": digest(MATRIX_PATH)},
            "manual": {"sha256": digest(MANUAL_PATH)},
            "service": {"sha256": digest(SERVICE_PATH)},
            "authorization_policy": {"sha256": authorization_source_digest()},
            "toolkit_surface": {"sha256": digest(SURFACE_PATH)},
        },
        "counts": {
            "paths": len(contracts),
            "primary_paths": len(primary),
            "supplement_paths": len(supplement),
            "declarative_argument_arities": len(arities),
            "public_help_syntax_hashes": len(syntax_hashes),
            "axis_status": axis_counts,
            "subaxis_status": subaxis_counts,
        },
        "axis_schema": {key: list(value) for key, value in AXIS_SUBAXES.items()},
        "contracts": contracts,
    }


def render(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    content = render(build())
    if args.check:
        if not OUTPUT_PATH.is_file() or OUTPUT_PATH.read_text(encoding="utf-8") != content:
            raise SystemExit(f"stale C-Gate contract inventory: {OUTPUT_PATH.relative_to(ROOT)}")
    else:
        OUTPUT_PATH.write_text(content, encoding="utf-8")
    document = json.loads(content)
    print(
        json.dumps(
            {
                "status": "current" if args.check else "generated",
                **{key: document["counts"][key] for key in ("paths", "primary_paths", "supplement_paths")},
                "axis_status": document["counts"]["axis_status"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
