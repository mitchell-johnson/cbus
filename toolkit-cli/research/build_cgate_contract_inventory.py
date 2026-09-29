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
ACCESS_PATH = REPOSITORY / "rust" / "cbus-cgate" / "src" / "access.rs"
EVENT_MODE_PATH = REPOSITORY / "rust" / "cbus-cgate" / "src" / "lib.rs"
SURFACE_PATH = ROOT / "docs" / "toolkit-surface.json"
NATIVE_SESSION_PATH = (
    ROOT / "research" / "experiments" / "2026-09-25" / "cgate-session-native-acceptance.json"
)
NATIVE_SELECTOR_PATH = (
    REPOSITORY / "rust" / "testdata" / "fixtures"
    / "native_cgate_session_selectors.json"
)
NATIVE_INITIAL_ROLE_PATH = (
    REPOSITORY / "rust" / "testdata" / "fixtures"
    / "native_cgate_authorization_probe.json"
)
NATIVE_INITIAL_ROLE_SCRIPT_PATH = (
    REPOSITORY / "rust" / "cbus-cgate" / "research"
    / "native_authorization_probe.py"
)
NATIVE_ROLE_PATH = (
    REPOSITORY / "rust" / "testdata" / "fixtures"
    / "native_cgate_authorization_expansion_probe.json"
)
NATIVE_ROLE_SCRIPT_PATH = (
    REPOSITORY / "rust" / "cbus-cgate" / "research"
    / "native_authorization_matrix_expansion.py"
)
NATIVE_PROGRAMMING_ROLE_PATH = (
    REPOSITORY / "rust" / "testdata" / "fixtures"
    / "native_cgate_programming_authorization_probe.json"
)
NATIVE_PROGRAMMING_ROLE_SCRIPT_PATH = (
    REPOSITORY / "rust" / "cbus-cgate" / "research"
    / "native_programming_authorization_probe.py"
)
NATIVE_MEDIA_ROLE_PATH = (
    REPOSITORY / "rust" / "testdata" / "fixtures"
    / "native_cgate_media_authorization_probe.json"
)
NATIVE_MEDIA_ROLE_SCRIPT_PATH = (
    REPOSITORY / "rust" / "cbus-cgate" / "research"
    / "native_media_authorization_probe.py"
)
NATIVE_ADMIN_ROLE_PATH = (
    REPOSITORY / "rust" / "testdata" / "fixtures"
    / "native_cgate_admin_authorization_probe.json"
)
NATIVE_ADMIN_ROLE_SCRIPT_PATH = (
    REPOSITORY / "rust" / "cbus-cgate" / "research"
    / "native_admin_authorization_probe.py"
)
NATIVE_APPLICATION_ROLE_PATH = (
    REPOSITORY / "rust" / "testdata" / "fixtures"
    / "native_cgate_application_authorization_probe.json"
)
NATIVE_APPLICATION_ROLE_SCRIPT_PATH = (
    REPOSITORY / "rust" / "cbus-cgate" / "research"
    / "native_application_authorization_probe.py"
)
NATIVE_DALI_ROLE_PATH = (
    REPOSITORY / "rust" / "testdata" / "fixtures"
    / "native_cgate_dali_authorization_probe.json"
)
NATIVE_DALI_ROLE_SCRIPT_PATH = (
    REPOSITORY / "rust" / "cbus-cgate" / "research"
    / "native_dali_authorization_probe.py"
)
NATIVE_REMAINING_ROLE_PATH = (
    REPOSITORY / "rust" / "testdata" / "fixtures"
    / "native_cgate_remaining_authorization_probe.json"
)
NATIVE_REMAINING_ROLE_SCRIPT_PATH = (
    REPOSITORY / "rust" / "cbus-cgate" / "research"
    / "native_remaining_authorization_probe.py"
)
NATIVE_UNPROBED_ROLE_PATH = (
    REPOSITORY / "rust" / "testdata" / "fixtures"
    / "native_cgate_unprobed_authorization_probe.json"
)
NATIVE_UNPROBED_ROLE_SCRIPT_PATH = (
    REPOSITORY / "rust" / "cbus-cgate" / "research"
    / "native_unprobed_authorization_probe.py"
)
NATIVE_FINAL_ROLE_PATH = (
    REPOSITORY / "rust" / "testdata" / "fixtures"
    / "native_cgate_final_authorization_probe.json"
)
NATIVE_FINAL_ROLE_SCRIPT_PATH = (
    REPOSITORY / "rust" / "cbus-cgate" / "research"
    / "native_final_authorization_probe.py"
)
NATIVE_DALI_HELP_PATH = (
    REPOSITORY / "rust" / "testdata" / "fixtures"
    / "native_cgate_dali_help.json"
)
FIXTURE_DIRECTORY = REPOSITORY / "rust" / "testdata" / "fixtures"
# Application-family fixtures captured from owned native C-Gate 3.4.0.2001
# with a fake PCI. Each is pinned by digest; a changed fixture must be
# reviewed and re-pinned before any selector or envelope claim is rebuilt.
NATIVE_APPLICATION_FIXTURES: dict[str, dict[str, str | None]] = {
    "AIRCON": {
        "file": "native_cgate_aircon.json",
        "format": "native-cgate-aircon-evidence-v1",
        "sha256": "6b49eedb5b0ae3cf23085d33c04f6527151c6a41e2424b345e59ac7b3cef8315",
        "boundaries": "validated_boundaries",
    },
    "AUDIO": {
        "file": "native_cgate_audio.json",
        "format": "native-cgate-audio-evidence-v1",
        "sha256": "e68380c542c3902553f606a2f1783dd7b0e8371206107076936ac871d718fc87",
        "boundaries": "validated_boundaries",
    },
    "MEASUREMENT": {
        "file": "native_cgate_measurement.json",
        "format": None,
        "sha256": "6ef5b207f7cad5745aef425f674331667d5e03ed1795a7370b3a8163c576fbd2",
        "boundaries": "bounds",
    },
    "MEDIATRANSPORT": {
        "file": "native_cgate_mediatransport.json",
        "format": "native-cgate-mediatransport-evidence-v1",
        "sha256": "12c46dd05d6c7083cdefb28dd7ab4580b131757cf6fb044bf9298a68eed36692",
        "boundaries": "validated_boundaries",
    },
    "SECURITY": {
        "file": "native_cgate_security.json",
        "format": "native-cgate-security-evidence-v1",
        "sha256": "ea163445585448b369e30de0a43b7fb7c9d1fe2212dff08813c90271771d5d42",
        "boundaries": "validated_boundaries",
    },
    "TELEPHONY": {
        "file": "native_cgate_telephony.json",
        "format": "native-cgate-telephony-evidence-v1",
        "sha256": "42c34c046d6fc7773540e3be2c57adbbcd1779eb760e96b7714841f0f3e1b6ef",
        "boundaries": "validated_boundaries",
    },
}
# Service-family fixtures that retain reply shapes rather than one uniform
# invocation list. Each shape is attributed to a path by an explicit JSON
# pointer and class; the attribution basis is recorded with the evidence.
NATIVE_SHAPE_FIXTURES: dict[str, dict] = {
    "DEPLOY_QUEUE": {
        "file": "native_cgate_deploy_queue.json",
        "sha256": "5b25610c9bcbcc814472a36cf9bc61ae38d520560f7ed3d21a88d70c15c0d7f1",
        "oracle": {"version": "3.4.0.2001"},
        "attribution": "fixture shape keys and retained subcommand_help syntax",
        "paths": {
            "DEPLOY_QUEUE ADD": (
                ("accepted", "/native_shapes/add_success"),
                ("arity", "/native_shapes/missing_or_extra_single_name"),
                ("target", "/native_shapes/missing_programmer"),
                ("other", "/native_shapes/duplicate_add"),
            ),
            "DEPLOY_QUEUE DELETE": (
                ("accepted", "/native_shapes/delete_success"),
                ("arity", "/native_shapes/missing_or_extra_single_name"),
                ("other", "/native_shapes/delete_not_queued"),
            ),
            "DEPLOY_QUEUE DELETE_ALL": (
                ("accepted", "/native_shapes/empty_delete_all"),
                ("accepted", "/native_shapes/delete_all_rows"),
                ("arity", "/native_shapes/delete_all_extra_parameter"),
                ("value_domain", "/native_shapes/invalid_delete_type"),
            ),
            "DEPLOY_QUEUE LIST": (("accepted", "/native_shapes/empty_list"),),
            "DEPLOY_QUEUE RETRY": (
                ("accepted", "/native_shapes/retry_success_native"),
                ("arity", "/native_shapes/missing_or_extra_single_name"),
                ("target", "/native_shapes/missing_programmer"),
                ("other", "/native_shapes/retry_init"),
            ),
        },
    },
    "FILE": {
        "file": "native_cgate_file.json",
        "sha256": "ffe617d02e687834253f7bd54dfa3863f03528d0f67748652a35c25f9afa84ef",
        "oracle": {"version": "3.4.0.2001"},
        "attribution": "fixture shape keys; LS reuses DIR shapes only because ls_alias_exact is true",
        "paths": {
            "FILE DELETE": (
                ("accepted", "/directory/empty_directory_delete"),
                ("other", "/directory/nonempty_directory_delete"),
                ("target", "/errors/delete_missing"),
                ("value_domain", "/path_guard/delete_error"),
            ),
            "FILE DIR": (
                ("accepted", "/directory/empty"),
                ("accepted", "/directory/populated"),
                ("value_domain", "/path_guard/dir_error"),
            ),
            "FILE DOWNLOAD": (
                ("accepted", "/round_trip/download_envelope"),
                ("target", "/errors/download_missing"),
            ),
            "FILE LS": (
                ("accepted", "/directory/empty"),
                ("accepted", "/directory/populated"),
                ("value_domain", "/path_guard/dir_error"),
            ),
            "FILE MKDIR": (
                ("value_domain", "/path_guard/mkdir_error"),
                ("other", "/errors/mkdir_existing"),
            ),
            "FILE SHA256": (
                ("accepted", "/round_trip/sha256_response"),
                ("accepted", "/sha256/multiple_success"),
                ("target", "/sha256/missing"),
            ),
            "FILE UPLOAD": (
                ("accepted", "/round_trip/upload_response"),
                ("value_domain", "/errors/invalid_base64_character"),
                ("value_domain", "/errors/invalid_base64_padding"),
                ("other", "/errors/upload_without_document"),
            ),
        },
    },
    "PORT": {
        "file": "native_cgate_port.json",
        "sha256": "9e4231409117c5a2e9ba8c0c203a56b7a1c1748c70e0961cc25d2de139aa9a66",
        "oracle": {"version": "3.4.0 build 2001"},
        "attribution": "fixture shape keys named for each PORT subcommand",
        "paths": {
            "PORT CNISCAN": (
                ("accepted", "/legacy_discovery/row"),
                ("accepted", "/legacy_discovery/empty"),
                ("value_domain", "/legacy_discovery/observed_invalid_destination_prefix"),
                ("value_domain", "/legacy_discovery/observed_invalid_interface"),
            ),
            "PORT CNISCAN2": (("accepted", "/cni2_discovery/synthetic_native_response"),),
            "PORT IFLIST": (
                ("accepted", "/local_enumeration/iflist_row"),
                ("accepted", "/local_enumeration/iflist_empty"),
                ("arity", "/syntax_observations/iflist_extra_argument"),
            ),
            "PORT LIST": (
                ("accepted", "/local_enumeration/list_row"),
                ("accepted", "/local_enumeration/list_empty"),
                ("arity", "/syntax_observations/list_extra_argument"),
            ),
            "PORT PROBE": (
                ("accepted", "/probe/success"),
                ("accepted", "/probe/observed_synthetic_success"),
                ("arity", "/syntax_observations/probe_missing_type_or_address"),
                ("value_domain", "/probe/observed_unknown_type"),
                ("value_domain", "/syntax_observations/etherlite_malformed_or_negative_port"),
                ("other", "/probe/observed_connected_without_echo"),
                ("other", "/probe/observed_refused_loopback"),
            ),
            "PORT REFRESH": (
                ("arity", "/syntax_observations/refresh_extra_argument"),
                ("other", "/local_enumeration/refresh"),
            ),
        },
    },
    "PP_PROGRAMMER": {
        "file": "native_cgate_pp_programmer.json",
        "sha256": "a11854d5cfb7087383864a8ffa0ee52fa3e141532675acbf3bc59690aeaf64bf",
        "oracle": {"version": "3.4.0.2001"},
        "attribution": "fixture shape keys naming one PP or PROGRAMMER subcommand",
        "paths": {
            "PP CATALOG_INFO": (("accepted", "/native_shapes/catalog_metadata"),),
            "PP GET_RAW_DATA": (
                ("accepted", "/native_shapes/raw_initial"),
                ("accepted", "/native_shapes/raw_after_set"),
            ),
            "PP LIST_LOCK": (
                ("accepted", "/native_shapes/empty_lists/0"),
                ("accepted", "/native_shapes/lock_row"),
            ),
            "PP WRITE_PATCH": (
                ("arity", "/native_shapes/write_patch_selector/too_few"),
                ("target", "/native_shapes/write_patch_selector/bad_address"),
                ("value_domain", "/native_shapes/write_patch_selector/bad_patch_version"),
            ),
            "PROGRAMMER CREATE": (("accepted", "/native_shapes/programmer_create"),),
            "PROGRAMMER LIST": (("accepted", "/native_shapes/empty_lists/2"),),
            "PROGRAMMER STATUS": (("accepted", "/native_shapes/programmer_empty_status"),),
            "PROGRAMMER TRIGGER": (("accepted", "/native_shapes/programmer_start_receipt"),),
        },
    },
}
NATIVE_NET_FIXTURE = {
    "file": "native_cgate_net_lifecycle.json",
    "sha256": "8004c25aaccbaa7fd0993099be37dcab08751e7741097ccae61ed90eabe3d332",
    "format": "native-cgate-net-lifecycle-v1",
}
# Declarative-model form rules that dispose of a native counterexample the
# flat min/max arity cannot express. The marker must remain in manual.rs.
DECLARATIVE_FORM_RULES = {
    "AUDIO OUTPUT_ERROR_CODE": 'spec.name == "AUDIO OUTPUT_ERROR_CODE"',
}
NATIVE_FIXTURE_ADAPTER_RULE = (
    "A subaxis is resolved only when its pinned native fixture retains both an "
    "accepted (200) and a rejected native observation of that class for the "
    "path; otherwise it is partial with the retained observations."
)
LOCAL_CGATE_HARNESS_PATH = ROOT / "research" / "local_cgate.py"
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
ACCESS_ROLE_REF = "rust/cbus-cgate/src/access.rs#NATIVE_PROBED_ADDITIONAL_COMMANDS"
ACCESS_PROGRAMMING_ROLE_REF = "rust/cbus-cgate/src/access.rs#NATIVE_PROBED_PROGRAMMING_COMMANDS"
ACCESS_MEDIA_ROLE_REF = "rust/cbus-cgate/src/access.rs#NATIVE_PROBED_MEDIA_COMMANDS"
ACCESS_ADMIN_ROLE_REF = "rust/cbus-cgate/src/access.rs#NATIVE_PROBED_ADMIN_COMMANDS"
ACCESS_APPLICATION_ROLE_REF = "rust/cbus-cgate/src/access.rs#NATIVE_PROBED_APPLICATION_COMMANDS"
ACCESS_DALI_ROLE_REF = "rust/cbus-cgate/src/access.rs#NATIVE_PROBED_DALI_COMMANDS"
ACCESS_REMAINING_ROLE_REF = "rust/cbus-cgate/src/access.rs#NATIVE_PROBED_REMAINING_COMMANDS"
ACCESS_UNPROBED_ROLE_REF = "rust/cbus-cgate/src/access.rs#NATIVE_PROBED_UNPROBED_COMMANDS"
ACCESS_FINAL_ROLE_REF = "rust/cbus-cgate/src/access.rs#NATIVE_PROBED_FINAL_COMMANDS"
EVENT_MODE_REF = "rust/cbus-cgate/src/lib.rs#EventMode::parse"
NATIVE_SESSION_REF = (
    "toolkit-cli/research/experiments/2026-09-25/"
    "cgate-session-native-acceptance.json"
)
NATIVE_SELECTOR_REF = "rust/testdata/fixtures/native_cgate_session_selectors.json"
NATIVE_ROLE_REF = (
    "rust/testdata/fixtures/native_cgate_authorization_expansion_probe.json"
)
NATIVE_INITIAL_ROLE_REF = (
    "rust/testdata/fixtures/native_cgate_authorization_probe.json"
)
NATIVE_PROGRAMMING_ROLE_REF = (
    "rust/testdata/fixtures/native_cgate_programming_authorization_probe.json"
)
NATIVE_MEDIA_ROLE_REF = "rust/testdata/fixtures/native_cgate_media_authorization_probe.json"
NATIVE_ADMIN_ROLE_REF = "rust/testdata/fixtures/native_cgate_admin_authorization_probe.json"
NATIVE_APPLICATION_ROLE_REF = (
    "rust/testdata/fixtures/native_cgate_application_authorization_probe.json"
)
NATIVE_DALI_ROLE_REF = "rust/testdata/fixtures/native_cgate_dali_authorization_probe.json"
NATIVE_REMAINING_ROLE_REF = "rust/testdata/fixtures/native_cgate_remaining_authorization_probe.json"
NATIVE_UNPROBED_ROLE_REF = "rust/testdata/fixtures/native_cgate_unprobed_authorization_probe.json"
NATIVE_FINAL_ROLE_REF = "rust/testdata/fixtures/native_cgate_final_authorization_probe.json"
NATIVE_CGATE_JAR_SHA256 = (
    "3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630"
)
NATIVE_SESSION_EVIDENCE_SHA256 = (
    "d2752f56f3e0abcbff10d805e7803b29704337368b09580e5685e3b3bf6d3c5f"
)
NATIVE_SELECTOR_EVIDENCE_SHA256 = (
    "537a0718d94948010d27e2b3aa3e3abce1478d0af08448a4af7199d11766a562"
)
NATIVE_ROLE_EVIDENCE_SHA256 = (
    "716e9ff704e52a1487c00f11be055461d15efe22977c3a1ed7ccb9c582a6799e"
)
NATIVE_INITIAL_ROLE_EVIDENCE_SHA256 = (
    "c9f0ee5a5f261264cfd96d0f805712cb5b54fa398c1260386a981e0552e0fcd0"
)
NATIVE_PROGRAMMING_ROLE_EVIDENCE_SHA256 = (
    "cdcbb2507762c404c7ee2193893a3128c2250d35aedc15b98a4611a2ab7ade2f"
)
NATIVE_MEDIA_ROLE_EVIDENCE_SHA256 = (
    "e626683812d7b90f77de77ae502d4d0508c50329d35b73fbead24357270b851a"
)
NATIVE_ADMIN_ROLE_EVIDENCE_SHA256 = (
    "009794bf4b44e327b875fe1b3b5a7ec5e1bab262fb870e1af5e594b3160159ae"
)
NATIVE_APPLICATION_ROLE_EVIDENCE_SHA256 = (
    "5d11a1edb500a995422be2336fcec4feca4c4e07a931e3d64cc604a671191f7d"
)
NATIVE_DALI_ROLE_EVIDENCE_SHA256 = (
    "d2ffb8d86b296ea123b6b667d484e9c5415ec41b0db55c25f14ef6262f67af8f"
)
NATIVE_REMAINING_ROLE_EVIDENCE_SHA256 = (
    "5cc108b58e15d1caca464d8c73a4b0bd5e77c587f091a2f65db38fc435207bbd"
)
NATIVE_UNPROBED_ROLE_EVIDENCE_SHA256 = (
    "1630ef43544c0e08a1abc7c9a8b808bedc9dc02f44b8922b529588b663fd4b97"
)
NATIVE_FINAL_ROLE_EVIDENCE_SHA256 = (
    "bf5abdda888afbca356c00a0dcba21ac76fe465c653982904b8fe1a7eb3a5231"
)
NATIVE_ROLE_LEVELS = (
    "None", "Connect", "Monitor", "Operate", "Admin", "Program", "Debug", "Clipsal", "Max"
)
SESSION_PATHS = {"SESSION_ID", "SESSION_ID ALL", "SESSION_ID TAG", "EVENT", "QUIT"}
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


def partial(reason: str, *source_refs: str, known: object) -> dict:
    """Native evidence exists but does not bracket the subaxis."""
    return {
        "status": "partial",
        "reason": reason,
        "source_refs": list(source_refs),
        "known": known,
    }


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
        if statuses["unresolved"] == len(subaxes)
        else "partial"
    )
    return {"status": status, "subaxes": subaxes}


def validate_native_session_observations() -> None:
    """Reject a missing or weakened native trace before promoting session facts."""
    report = json.loads(NATIVE_SESSION_PATH.read_text(encoding="utf-8"))
    if (
        report.get("format") != "cbus-cgate-session-native-acceptance-v1"
        or report.get("passed") is not True
        or report.get("vendor_jar_sha256") != NATIVE_CGATE_JAR_SHA256
        or report.get("cleanup", {}).get("cleanup_complete") is not True
        or report.get("environment", {}).get("physical_networks_opened") is not False
    ):
        raise ValueError("Native C-Gate session acceptance trace is not admissible")
    actual = {(row["command"], row["status"]) for row in report["cases"]}
    required = {
        ("SESSION_ID", 300),
        ("SESSION_ID bogus", 400),
        ("SESSION_ID ALL", 300),
        ("SESSION_ID ALL ignored-by-native", 300),
        ("SESSION_ID TAG C-Bus   Toolkit test", 200),
        ("SESSION_ID TAG replacement", 408),
        ("SESSION_ID TAG", 400),
        ("EVENT", 306),
        ("EVENTS", 306),
        ("EVENTS ON", 200),
        ("EVENT OFF", 200),
        ("EVENT e5s1c1", 200),
    }
    closes = {
        row["command"]
        for row in report["connection_close_cases"]
        if row.get("eof_after_reply") is True
        and row.get("reply", "").endswith("204 Closing connection.")
    }
    if not required <= actual or closes != {"QUIT", "EXIT"}:
        raise ValueError("Native C-Gate session acceptance cases changed")
    stable_replies = {
        "SESSION_ID bogus": ["400 Syntax Error."],
        "SESSION_ID TAG C-Bus   Toolkit test": ["200 OK."],
        "SESSION_ID TAG replacement": [
            "408 Operation failed: tag name has already been set"
        ],
        "SESSION_ID TAG": ["400 Syntax Error: tag name not supplied"],
        "EVENTS ON": ["200 OK."],
        "EVENT OFF": ["200 OK."],
        "EVENT e5s1c1": ["200 OK."],
    }
    if any(
        row["reply"] != stable_replies[row["command"]]
        for row in report["cases"]
        if row["command"] in stable_replies
    ):
        raise ValueError("Native C-Gate session response evidence changed")
    if not all(
        len(row["reply"]) == 1
        and re.fullmatch(r"300 sessionID=cmd[0-9]+", row["reply"][0])
        for row in report["cases"]
        if row["command"] == "SESSION_ID"
    ):
        raise ValueError("Native C-Gate session ID response evidence changed")
    session_all_lines = [
        line
        for row in report["cases"]
        if row["command"] == "SESSION_ID ALL"
        for line in row["reply"]
    ]
    if not any(" origin=internal " in line for line in session_all_lines):
        raise ValueError("Native C-Gate internal command session evidence changed")
    if not any(
        row["reply"] == ["306 e0s0c0"]
        for row in report["cases"]
        if row["command"] in {"EVENT", "EVENTS"}
    ):
        raise ValueError("Native C-Gate initial event mode evidence changed")
    if report.get("observations") != {
        "external_session_ids_are_odd_cmd_numbers": True,
        "session_all_reports_origin_connection_time_and_optional_tag": True,
        "session_tag_is_one_shot": True,
        "session_all_ignores_trailing_words": True,
        "event_default": "e0s0c0",
        "events_alias_supported": True,
        "quit_and_exit_flush_204_then_close": True,
    }:
        raise ValueError("Native C-Gate session observations changed")
    if digest(NATIVE_SESSION_PATH) != NATIVE_SESSION_EVIDENCE_SHA256:
        raise ValueError("Native C-Gate session acceptance source changed")


def validate_native_selector_observations() -> None:
    """Bound EVENT and QUIT trailing-word claims to the owned native trace."""
    if digest(NATIVE_SELECTOR_PATH) != NATIVE_SELECTOR_EVIDENCE_SHA256:
        raise ValueError("Native C-Gate session selector source changed")
    report = json.loads(NATIVE_SELECTOR_PATH.read_text(encoding="utf-8"))
    if (
        report.get("format") != "native-cgate-session-selectors-v1"
        or report.get("target") != "C-Gate v3.4.0 build 2001"
        or report.get("vendor_jar_sha256") != NATIVE_CGATE_JAR_SHA256
        or report.get("physical_networks_opened") is not False
        or not isinstance(report.get("captures"), list)
        or len(report["captures"]) != 3
    ):
        raise ValueError("Native C-Gate session selector provenance changed")
    matrix = report["captures"][0]
    cleanup = matrix.get("cleanup", {})
    cases = matrix.get("cases")
    if (
        matrix.get("name") != "session_matrix"
        or matrix.get("listener_count") != 6
        or matrix.get("listeners_loopback_only") is not True
        or not isinstance(cases, list)
        or len(cases) != 43
        or any(
            cleanup.get(key) is not True
            for key in (
                "process_exit_confirmed", "reserved_sockets_closed",
                "log_closed", "work_removed", "cleanup_complete",
            )
        )
    ):
        raise ValueError("Native C-Gate session selector capture changed")
    expected = {
        "EVENT ON extra": 200,
        "EVENT e5s1c1 extra": 200,
        "EVENT OFF extra": 200,
        "QUIT extra": 204,
        "EXIT extra": 204,
    }
    for command, status in expected.items():
        matches = [case for case in cases if case.get("command") == command]
        if (
            len(matches) != 1
            or matches[0].get("status") != status
            or (status == 204 and matches[0].get("eof_after_reply") is not True)
            or not isinstance(matches[0].get("reply"), list)
            or len(matches[0]["reply"]) != 1
            or not re.match(rf"^\[[^]]+\] {status} ", matches[0]["reply"][0])
        ):
            raise ValueError(f"Native C-Gate session selector changed: {command}")


def _native_role_fixture_observations(
    inventory_paths: set[str], *, fixture_path: Path, fixture_digest: str,
    fixture_format: str, script_path: Path, registry_marker: str,
    expected_commands: int, label: str, response_command_count: int | None = None,
    capture_engine_path: Path | None = None,
    variant_command_count: int | None = None,
    help_fixture_path: Path | None = None,
) -> dict[str, dict]:
    """Bind exact invocations to captured floors; retain incomplete scope.

    A lower-role 420 followed by a non-420 at the recorded floor establishes
    entry to a later parser/handler stage. It does not prove authorization
    after object resolution or a successful physical send.
    """
    if digest(fixture_path) != fixture_digest:
        raise ValueError(f"Native C-Gate {label} source changed")
    report = json.loads(fixture_path.read_text(encoding="utf-8"))
    oracle = report.get("oracle", {})
    if (
        report.get("format") != fixture_format
        or oracle.get("version") != "3.4.0.2001"
        or oracle.get("jar_sha256") != NATIVE_CGATE_JAR_SHA256
        or any(
            oracle.get(field) is not True
            for field in (
                "listener_ownership_verified",
                "cleanup_complete",
                "process_exit_confirmed",
                "work_removed",
            )
        )
        or "no C-Bus endpoint" not in oracle.get("transport", "")
        or report.get("capture_script_sha256") != digest(script_path)
        or (
            capture_engine_path is not None
            and report.get("capture_engine_sha256") != digest(capture_engine_path)
        )
        or (
            help_fixture_path is not None
            and report.get("help_fixture_sha256") != digest(help_fixture_path)
        )
        or report.get("local_cgate_harness_sha256") != digest(LOCAL_CGATE_HARNESS_PATH)
    ):
        raise ValueError(f"Native C-Gate {label} provenance changed")

    commands = report.get("commands")
    roles = report.get("roles")
    if response_command_count is not None:
        # The original probe predates the top-level commands list. Its nine
        # role records retain the complete response-key set instead.
        none_record = roles.get("None") if isinstance(roles, dict) else None
        if (
            "commands" in report
            or not isinstance(none_record, dict)
            or not isinstance(none_record.get("responses"), dict)
        ):
            raise ValueError(f"Native C-Gate {label} response command set changed")
        commands = list(none_record["responses"])
    if (
        not isinstance(commands, list)
        or len(commands) != (
            response_command_count or variant_command_count or expected_commands
        )
        or any(not isinstance(command, str) or not command for command in commands)
        or len(commands) != len(set(commands))
        or not isinstance(roles, dict)
        or set(roles) != set(NATIVE_ROLE_LEVELS)
    ):
        raise ValueError(f"Native C-Gate {label} command/role set changed")

    access_source = ACCESS_PATH.read_text(encoding="utf-8")
    if registry_marker not in access_source:
        raise ValueError("Native C-Gate role registry is missing")
    start = access_source.index(registry_marker)
    end = access_source.find("];", start)
    if end < 0:
        raise ValueError("Native C-Gate role registry is incomplete")
    registry = re.findall(
        r'\(\s*"([^"]+)",\s*CgateAccessLevel::(\w+),?\s*\)',
        access_source[start:end],
    )
    if (
        len(registry) != expected_commands
        or len({path for path, _ in registry}) != len(registry)
        or any(level not in NATIVE_ROLE_LEVELS for _, level in registry)
    ):
        raise ValueError("Native C-Gate role registry changed")

    for level in NATIVE_ROLE_LEVELS:
        record = roles[level]
        if (
            not isinstance(record, dict)
            or record.get("query") != f"210 Access level: {level}"
            or record.get("login") != f"211 Access level set to: {level}"
            or not str(record.get("greeting", "")).startswith("201 Service ready:")
            or not isinstance(record.get("responses"), dict)
            or set(record["responses"]) != set(commands)
        ):
            raise ValueError(f"Native C-Gate {label} {level} session changed")

    command_paths: dict[str, str] = {}
    if variant_command_count is not None:
        for command in commands:
            matching_paths = [
                path for path, _ in registry
                if command == path or command.startswith(f"{path} ")
            ]
            if not matching_paths:
                raise ValueError(f"Native C-Gate {label} invocation has no registry path: {command}")
            command_paths[command] = max(matching_paths, key=len)
    help_paths = (
        json.loads(help_fixture_path.read_text(encoding="utf-8"))["paths"]
        if help_fixture_path is not None else {}
    )

    observations: dict[str, dict] = {}
    for path, minimum in registry:
        matching = [
            command for command in commands
            if (
                command_paths.get(command) == path
                if variant_command_count is not None
                else command == path or command.startswith(f"{path} ")
            )
        ]
        if variant_command_count is not None:
            first_help = help_paths[path][0] if help_fixture_path is not None else ""
            expected_variants = 2 if "[mode=(auto)]" in first_help else 1
            if len(matching) != expected_variants:
                raise ValueError(f"Native C-Gate {label} selector set changed for {path}")
            if len(matching) == 2 and (
                not matching[1].startswith(f"{path} poll ")
                or matching[0].startswith(f"{path} poll ")
            ):
                raise ValueError(f"Native C-Gate {label} poll selector changed for {path}")
        elif path in matching:
            matching = [path]
        elif len(matching) == 1:
            pass
        else:
            raise ValueError(f"Native C-Gate role invocation changed for {path}")
        floor_index = NATIVE_ROLE_LEVELS.index(minimum)
        selector_invocations = []
        for command in matching:
            for index, level in enumerate(NATIVE_ROLE_LEVELS):
                reply = roles[level]["responses"][command]
                if not isinstance(reply, str) or (reply == "420 Access denied.") != (
                    index < floor_index
                ):
                    raise ValueError(f"Native C-Gate role threshold changed for {command}")
            floor_reply = roles[minimum]["responses"][command]
            if not re.match(r"^[0-9]{3} ", floor_reply):
                raise ValueError(f"Native C-Gate role response changed for {command}")
            selector_invocations.append({
                "invocation": command,
                "at_floor_status": int(floor_reply[:3]),
            })

        # SHOW OBJECTS and SCENE PLAY are selectors beneath maintained
        # primary paths. Keep exact invocations without promoting every form.
        inventory_path = {"SHOW OBJECTS": "SHOW", "SCENE PLAY": "SCENE"}.get(path, path)
        if inventory_path not in inventory_paths or inventory_path in observations:
            raise ValueError(f"Native C-Gate role path is not uniquely inventoried: {path}")
        observations[inventory_path] = {
            "invocation": matching[0],
            "minimum_access_level_at_handler_entry": minimum,
            "lower_access_status": 420,
            "at_floor_status": selector_invocations[0]["at_floor_status"],
            "observed_roles": len(NATIVE_ROLE_LEVELS),
            "fixture_sha256": fixture_digest,
            "scope": "exact_invocation_only; no_later_object_or_physical_success_claim",
            **(
                {"selector_invocations": selector_invocations}
                if help_fixture_path is not None else {}
            ),
        }
    if len(observations) != expected_commands:
        raise ValueError(f"Native C-Gate {label} mapping changed")
    return observations


def native_handler_role_observations(inventory_paths: set[str]) -> dict[str, dict]:
    """Combine disjoint original role probes without resolving later checks."""
    initial = _native_role_fixture_observations(
        inventory_paths,
        fixture_path=NATIVE_INITIAL_ROLE_PATH,
        fixture_digest=NATIVE_INITIAL_ROLE_EVIDENCE_SHA256,
        fixture_format="native-cgate-authorization-probe-v1",
        script_path=NATIVE_INITIAL_ROLE_SCRIPT_PATH,
        registry_marker="pub(crate) const NATIVE_PROBED_COMMANDS",
        expected_commands=31,
        response_command_count=38,
        label="initial role",
    )
    additional = _native_role_fixture_observations(
        inventory_paths,
        fixture_path=NATIVE_ROLE_PATH,
        fixture_digest=NATIVE_ROLE_EVIDENCE_SHA256,
        fixture_format="native-cgate-authorization-expansion-v1",
        script_path=NATIVE_ROLE_SCRIPT_PATH,
        registry_marker="pub(crate) const NATIVE_PROBED_ADDITIONAL_COMMANDS",
        expected_commands=58,
        label="role expansion",
    )
    programming = _native_role_fixture_observations(
        inventory_paths,
        fixture_path=NATIVE_PROGRAMMING_ROLE_PATH,
        fixture_digest=NATIVE_PROGRAMMING_ROLE_EVIDENCE_SHA256,
        fixture_format="native-cgate-programming-authorization-v1",
        script_path=NATIVE_PROGRAMMING_ROLE_SCRIPT_PATH,
        registry_marker="pub(crate) const NATIVE_PROBED_PROGRAMMING_COMMANDS",
        expected_commands=40,
        label="programming role",
    )
    media = _native_role_fixture_observations(
        inventory_paths,
        fixture_path=NATIVE_MEDIA_ROLE_PATH,
        fixture_digest=NATIVE_MEDIA_ROLE_EVIDENCE_SHA256,
        fixture_format="native-cgate-media-authorization-v1",
        script_path=NATIVE_MEDIA_ROLE_SCRIPT_PATH,
        registry_marker="pub(crate) const NATIVE_PROBED_MEDIA_COMMANDS",
        expected_commands=44,
        label="media role",
    )
    admin = _native_role_fixture_observations(
        inventory_paths,
        fixture_path=NATIVE_ADMIN_ROLE_PATH,
        fixture_digest=NATIVE_ADMIN_ROLE_EVIDENCE_SHA256,
        fixture_format="native-cgate-admin-authorization-v1",
        script_path=NATIVE_ADMIN_ROLE_SCRIPT_PATH,
        registry_marker="pub(crate) const NATIVE_PROBED_ADMIN_COMMANDS",
        expected_commands=22,
        label="admin role",
    )
    application = _native_role_fixture_observations(
        inventory_paths,
        fixture_path=NATIVE_APPLICATION_ROLE_PATH,
        fixture_digest=NATIVE_APPLICATION_ROLE_EVIDENCE_SHA256,
        fixture_format="native-cgate-application-authorization-v1",
        script_path=NATIVE_APPLICATION_ROLE_SCRIPT_PATH,
        capture_engine_path=NATIVE_ADMIN_ROLE_SCRIPT_PATH,
        registry_marker="pub(crate) const NATIVE_PROBED_APPLICATION_COMMANDS",
        expected_commands=24,
        label="application role",
    )
    dali = _native_role_fixture_observations(
        inventory_paths,
        fixture_path=NATIVE_DALI_ROLE_PATH,
        fixture_digest=NATIVE_DALI_ROLE_EVIDENCE_SHA256,
        fixture_format="native-cgate-dali-authorization-v1",
        script_path=NATIVE_DALI_ROLE_SCRIPT_PATH,
        capture_engine_path=NATIVE_ADMIN_ROLE_SCRIPT_PATH,
        registry_marker="pub(crate) const NATIVE_PROBED_DALI_COMMANDS",
        expected_commands=126,
        variant_command_count=192,
        help_fixture_path=NATIVE_DALI_HELP_PATH,
        label="DALI handler and selector roles",
    )
    remaining = _native_role_fixture_observations(
        inventory_paths,
        fixture_path=NATIVE_REMAINING_ROLE_PATH,
        fixture_digest=NATIVE_REMAINING_ROLE_EVIDENCE_SHA256,
        fixture_format="native-cgate-remaining-authorization-v1",
        script_path=NATIVE_REMAINING_ROLE_SCRIPT_PATH,
        capture_engine_path=NATIVE_ADMIN_ROLE_SCRIPT_PATH,
        registry_marker="pub(crate) const NATIVE_PROBED_REMAINING_COMMANDS",
        expected_commands=31,
        variant_command_count=31,
        label="remaining handler roles",
    )
    unprobed = _native_role_fixture_observations(
        inventory_paths,
        fixture_path=NATIVE_UNPROBED_ROLE_PATH,
        fixture_digest=NATIVE_UNPROBED_ROLE_EVIDENCE_SHA256,
        fixture_format="native-cgate-unprobed-authorization-v1",
        script_path=NATIVE_UNPROBED_ROLE_SCRIPT_PATH,
        capture_engine_path=NATIVE_ADMIN_ROLE_SCRIPT_PATH,
        registry_marker="pub(crate) const NATIVE_PROBED_UNPROBED_COMMANDS",
        expected_commands=22,
        label="unprobed handler roles",
    )
    final = _native_role_fixture_observations(
        inventory_paths,
        fixture_path=NATIVE_FINAL_ROLE_PATH,
        fixture_digest=NATIVE_FINAL_ROLE_EVIDENCE_SHA256,
        fixture_format="native-cgate-final-authorization-v1",
        script_path=NATIVE_FINAL_ROLE_SCRIPT_PATH,
        capture_engine_path=NATIVE_ADMIN_ROLE_SCRIPT_PATH,
        registry_marker="pub(crate) const NATIVE_PROBED_FINAL_COMMANDS",
        expected_commands=33,
        label="final safe handler entries",
    )
    groups = (initial, additional, programming, media, admin, application, dali, remaining, unprobed, final)
    overlap = set().union(*(
        set(left) & set(right)
        for index, left in enumerate(groups)
        for right in groups[index + 1:]
    ))
    if overlap:
        raise ValueError(f"Native C-Gate role probes overlap: {sorted(overlap)}")
    return initial | additional | programming | media | admin | application | dali | remaining | unprobed | final


def apply_native_session_contract(path: str, axes: dict[str, dict]) -> None:
    """Expand only five command-session paths observed against original C-Gate.

    These are endpoint contracts, not functional acceptance or independent
    ACCESS-role findings. Uncaptured native error/event variants stay open.
    """
    if path not in SESSION_PATHS:
        return
    refs = (NATIVE_SESSION_REF, SERVICE_SESSION_REF)
    help_ref = f"toolkit-cli/docs/toolkit-surface.json#cgate:{path}"
    selector = axes["selector_grammar"]["subaxes"]
    arities: dict[str, object] = {
        "SESSION_ID": {"minimum": 0, "maximum": 0},
        "SESSION_ID ALL": {
            "minimum": 0,
            "maximum": None,
            "trailing_words": "ignored_by_native_and_endpoint",
        },
        "SESSION_ID TAG": {"minimum": 1, "maximum": None},
        "EVENT": {
            "query": 0, "set_minimum": 1, "set_maximum": None,
            "after_first_mode_word": "ignored_by_native_and_endpoint",
        },
        "QUIT": {
            "minimum": 0, "maximum": None, "alias": "EXIT",
            "trailing_words": "ignored_by_native_and_endpoint",
        },
    }
    arity_refs = (*refs, NATIVE_SELECTOR_REF) if path in {"EVENT", "QUIT"} else refs
    selector["argument_arity"] = resolved(arities[path], help_ref, *arity_refs)
    domains: dict[str, object] = {
        "SESSION_ID": "no_arguments",
        "SESSION_ID ALL": "ALL_selector_with_ignored_trailing_words",
        "EVENT": {
            "query": "no_argument",
            "set": ["ON", "OFF", "e[+0-9]s[01]c[01]"],
            "mode_case": "ON_OFF_case_insensitive; e_form_lowercase",
            "new_connection_default": "e0s0c0",
            "alias": "EVENTS",
        },
        "QUIT": {"verb": ["QUIT", "EXIT"]},
    }
    if path == "SESSION_ID TAG":
        selector["value_domains"] = unresolved(
            "Native tag length, character and quoting limits are not fully captured.",
            help_ref,
            *refs,
            known={
                "accepted_example": "C-Bus   Toolkit test",
                "endpoint_normalization": "collapse_whitespace_and_retain_literal_quotes",
                "one_shot": True,
            },
        )
    elif path == "EVENT":
        selector["value_domains"] = unresolved(
            "Native EVENT case, trailing-word and numeric mode forms exceed the retained trace and endpoint parser.",
            help_ref,
            *refs,
            EVENT_MODE_REF,
            known={"observed_native_forms": ["ON", "OFF", "e5s1c1"],
                   "new_connection_default": "e0s0c0", "alias": "EVENTS"},
        )
    else:
        domain_refs = (*refs, EVENT_MODE_REF) if path == "EVENT" else refs
        selector["value_domains"] = resolved(domains[path], help_ref, *domain_refs)

    session = axes["session_states"]["subaxes"]
    session["selection_and_locks"] = resolved(
        {
            "project_selection": "not_required",
            "network_selection": "not_required",
            "advisory_lock": "not_required",
            "programming_session": "not_required",
            "scope": "connected_command_session",
        },
        *refs,
    )
    targets = axes["target_forms"]["subaxes"]
    target_scope: object = (
        "all_open_command_sessions_including_internal_console"
        if path == "SESSION_ID ALL"
        else "calling_command_session"
    )
    targets["address_shape"] = resolved(
        {"cbus_address_argument": False, "scope": target_scope},
        help_ref,
        *refs,
    )
    targets["route_shape"] = resolved("command_connection_only_no_cbus_route", *refs)

    response = axes["response_event_envelopes"]["subaxes"]
    envelopes: dict[str, object] = {
        "SESSION_ID": {
            "query": "300 sessionID=cmdN",
            "invalid_subcommand": "400 Syntax Error.",
        },
        "SESSION_ID ALL": {
            "rows": "300-sessionID=cmdN ...",
            "terminal": "300 sessionID=cmdN ...",
            "trailing_words": "ignored",
        },
        "SESSION_ID TAG": {
            "first_assignment": "200 OK.",
            "missing_tag": "400 Syntax Error: tag name not supplied",
            "second_assignment": "408 Operation failed: tag name has already been set",
        },
        "QUIT": {"terminal": "204 Closing connection.", "then": "EOF"},
    }
    response["command_envelope"] = unresolved(
        "The native trace does not cover every syntax, access-policy, "
        "transport, timeout and event-interleaving envelope.",
        help_ref,
        *refs,
        known=(
            {"query": 306, "set": 200, "endpoint_invalid_mode": 400}
            if path == "EVENT"
            else envelopes[path]
        ),
    )

    effects = axes["effects_routing"]["subaxes"]
    state_effects: dict[str, object] = {
        "SESSION_ID": {
            "command_session_registry": "read_calling_id",
            "endpoint_audit_log": "append_command_record",
        },
        "SESSION_ID ALL": {
            "command_session_registry": "read_all_open_sessions_including_internal_console",
            "endpoint_audit_log": "append_command_record",
        },
        "SESSION_ID TAG": {
            "command_session_registry": "set_calling_tag_once",
            "endpoint_audit_log": "append_command_record",
        },
        "EVENT": {
            "query": "read_calling_connection_filter",
            "set": "replace_calling_connection_filter",
        },
        "QUIT": {
            "command_connection": "flush_204_then_close",
            "command_session_registry": "remove_calling_session",
            "advisory_and_programming_locks": "release_on_disconnect",
            "endpoint_audit_log": "append_command_record",
        },
    }
    effects["state_effect"] = resolved(state_effects[path], *refs)
    for axis_name in (
        "selector_grammar",
        "session_states",
        "target_forms",
        "response_event_envelopes",
        "effects_routing",
    ):
        axes[axis_name] = axis(axes[axis_name]["subaxes"])


def _fixture_ref(file_name: str) -> str:
    return f"rust/testdata/fixtures/{file_name}"


def _negative_class(response: str) -> str:
    if "Missing parameter" in response or "Too many parameters" in response:
        return "arity"
    if response.startswith(("401 ", "402 ")):
        return "target"
    if response.startswith(("400 ", "405 ", "408 ")):
        return "value_domain"
    raise ValueError(f"Unclassified native application response: {response!r}")


def _load_pinned_fixture(label: str, file_name: str, pinned: str) -> tuple[dict, dict]:
    fixture_path = FIXTURE_DIRECTORY / file_name
    fixture_digest = digest(fixture_path)
    if fixture_digest != pinned:
        raise ValueError(f"Native C-Gate {label} fixture changed")
    report = json.loads(fixture_path.read_text(encoding="utf-8"))
    if report.get("oracle", {}).get("jar_sha256") != NATIVE_CGATE_JAR_SHA256:
        raise ValueError(f"Native C-Gate {label} provenance changed")
    return report, {"path": _fixture_ref(file_name), "sha256": fixture_digest}


def _application_fixture_rows(family: str, report: dict) -> list[dict]:
    """Normalize exact invocations and, for MEASUREMENT, its error contract."""
    rows: list[dict] = []
    keys = ("commands", "negative_examples", "boundary_examples")
    for key in keys:
        for entry in report.get(key, []):
            command = entry.get("command")
            response = entry.get("status" if family == "MEASUREMENT" else "response")
            if not isinstance(command, str) or not isinstance(response, str):
                raise ValueError(f"Native C-Gate {family} fixture row is malformed")
            words = command.split()
            if words[0] != family or not re.match(r"^[0-9]{3}[ .]", response):
                raise ValueError(f"Native C-Gate {family} fixture row changed: {command}")
            arguments = words[2:]
            form = None
            if family == "AUDIO" and len(arguments) > 1:
                form = "Z" if arguments[1].upper() == "Z" else "multiplexer"
            rows.append({
                "path": " ".join(words[:2]).upper() if len(words) > 1 else family,
                "invocation": command,
                "arguments": len(arguments),
                "form": form,
                "response": response,
                "class": "accepted" if response.startswith("200 ") else _negative_class(response),
            })
    if family == "MEASUREMENT":
        contract = report.get("error_contract")
        if (
            not isinstance(contract, dict)
            or contract.get("missing") != ["channel", "value", "multiplier", "units"]
            or contract.get("extra") != "400 Syntax Error: Too many parameters"
        ):
            raise ValueError("Native C-Gate MEASUREMENT error contract changed")
        # The retained report keeps exact messages with ADDRESS/NAME
        # placeholders, not exact invocations; argument counts stay unknown.
        for name in contract["missing"]:
            rows.append({
                "path": "MEASUREMENT DATA", "missing_parameter": name,
                "pointer": "/error_contract/missing", "class": "arity",
            })
        for key in ("extra", "bad_integer", "out_of_range", "wrong_application",
                    "bad_device", "bad_channel"):
            response = contract.get(key)
            if not isinstance(response, str):
                raise ValueError("Native C-Gate MEASUREMENT error contract changed")
            rows.append({
                "path": "MEASUREMENT DATA", "response": response,
                "pointer": f"/error_contract/{key}", "class": _negative_class(response),
            })
    return rows


def _pointer(report: dict, pointer: str) -> object:
    value: object = report
    for part in pointer.strip("/").split("/"):
        if isinstance(value, list) and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
        elif isinstance(value, dict) and part in value:
            value = value[part]
        else:
            raise KeyError(pointer)
    return value


def _shape_fixture_rows(family: str, spec: dict, report: dict) -> list[dict]:
    """Read explicitly attributed reply shapes; a list keeps its terminal line."""
    oracle = report.get("oracle", {})
    if any(oracle.get(key) != value for key, value in spec["oracle"].items()):
        raise ValueError(f"Native C-Gate {family} provenance changed")
    if family == "FILE" and report.get("directory", {}).get("ls_alias_exact") is not True:
        raise ValueError("Native C-Gate FILE LS alias evidence changed")
    rows: list[dict] = []
    for path, shapes in spec["paths"].items():
        for kind, pointer in shapes:
            try:
                value = _pointer(report, pointer)
            except KeyError:
                raise ValueError(f"Native C-Gate {family} fixture shape changed: {pointer}") from None
            lines = value if isinstance(value, list) else [value]
            if not lines or not all(isinstance(line, str) and line for line in lines):
                raise ValueError(f"Native C-Gate {family} fixture shape changed: {pointer}")
            rows.append({
                "path": path, "response": lines[-1], "pointer": pointer, "class": kind,
            })
    return rows


def _net_fixture_rows(report: dict) -> list[dict]:
    """Exact owned-loopback NET invocations; obsolete paths stay with the matrix."""
    oracle = report.get("oracle", {})
    if (
        report.get("schema") != NATIVE_NET_FIXTURE["format"]
        or oracle.get("version") != "3.4.0"
        or oracle.get("build") != 2001
        or oracle.get("site_project_used") is not False
        or oracle.get("real_cbus_contacted") is not False
    ):
        raise ValueError("Native C-Gate NET lifecycle provenance changed")
    rows: list[dict] = []
    for key in ("no_project_and_obsolete", "disposable_project", "cross_project_and_errors"):
        for entry in report.get("runtime", {}).get(key, []):
            command, code, final = entry.get("command"), entry.get("code"), entry.get("final")
            if (
                not isinstance(command, str)
                or type(code) is not int
                or not isinstance(final, str)
                or not final.startswith(f"{code}")
            ):
                raise ValueError(f"Native C-Gate NET lifecycle row changed: {command!r}")
            words = command.split()
            if words[0] != "NET" or "This command is obsolete." in final:
                continue
            kind = (
                "accepted" if code < 400
                else "value_domain" if code == 400
                else "target" if code == 401
                else "other"
            )
            rows.append({
                "path": " ".join(words[:2]).upper(),
                "invocation": command,
                "arguments": len(words) - 2,
                "response": final,
                "class": kind,
            })
    return rows


def _observation(row: dict) -> dict:
    return {
        key: row[key]
        for key in (
            "invocation", "arguments", "form", "response", "missing_parameter", "pointer"
        )
        if row.get(key) is not None
    }


def _arity_bounds(accepted: list[dict], rejected: list[dict]) -> dict:
    """Report a bound only where a counted native rejection brackets it."""
    bounds: dict[str, dict] = {}
    counted = [row for row in accepted if row.get("arguments") is not None]
    for form in sorted({row.get("form") or "all" for row in counted}):
        counts = [row["arguments"] for row in counted if (row.get("form") or "all") == form]
        applicable = [
            row for row in rejected
            if row.get("arguments") is not None
            and row.get("form") in (None, form if form != "all" else None)
        ]
        missing = {
            row["arguments"] for row in applicable
            if "Missing parameter" in row["response"]
        }
        extra = {
            row["arguments"] for row in applicable
            if "Too many parameters" in row["response"]
        }
        bounds[form] = {
            "minimum": min(counts) if min(counts) - 1 in missing else None,
            "maximum": max(counts) if max(counts) + 1 in extra else None,
        }
    return bounds


def _declarative_reconciliation(
    path: str, arity: dict | None, accepted: list[dict], rejected: list[dict],
    manual_text: str,
) -> dict | None:
    if arity is None:
        return None
    low = arity["minimum_after_command"]
    high = arity["maximum_after_command"]

    def inside(count: int) -> bool:
        return count >= low and (high is None or count <= high)

    contradictions = [
        {**_observation(row), "model": "rejects"}
        for row in accepted
        if row.get("arguments") is not None and not inside(row["arguments"])
    ] + [
        {**_observation(row), "model": "accepts"}
        for row in rejected
        if row.get("arguments") is not None and inside(row["arguments"])
    ]
    counted = [row for row in accepted + rejected if row.get("arguments") is not None]
    result: dict[str, object] = {
        "declarative_model_arity": arity,
        "status": (
            "contradicted_by_native"
            if contradictions
            else "no_native_counterexample"
            if counted
            else "no_counted_native_observation"
        ),
    }
    if contradictions:
        result["contradictions"] = contradictions
        marker = DECLARATIVE_FORM_RULES.get(path)
        result["model_disposition"] = (
            "manual_model_form_rule_rejects_native_counterexample"
            if marker is not None and marker in manual_text
            else "unaddressed"
        )
    return result


def _resolve_native_path(
    path: str, observed: list[dict], fixture: dict, *,
    boundaries_ref: str | None, attribution: str | None,
    arity: dict | None, manual_text: str,
) -> tuple[dict[str, dict], dict | None]:
    """Apply the positive-and-negative rule to one path's native rows."""
    ref = fixture["path"]
    accepted = [row for row in observed if row["class"] == "accepted"]
    arity_rejected = [row for row in observed if row["class"] == "arity"]
    domain_rejected = [row for row in observed if row["class"] == "value_domain"]
    errors = [row for row in observed if row["class"] != "accepted" and row.get("response")]
    refs = (ref, MANUAL_REF) if arity is not None else (ref,)
    base = {
        "native_fixture": fixture,
        **({"attribution": attribution} if attribution else {}),
    }
    reconciled = _declarative_reconciliation(
        path, arity, accepted, arity_rejected, manual_text
    )
    no_accepted = "The native fixture retains no accepted invocation for this path."
    arity_evidence = {
        **base,
        "argument_counting": "whitespace_words_after_subcommand_including_target",
        "accepted": [_observation(row) for row in accepted],
        "rejected": [_observation(row) for row in arity_rejected],
        **({"declarative_model_reconciliation": reconciled} if reconciled else {}),
    }
    if accepted and arity_rejected:
        argument_arity = resolved(
            {**arity_evidence, "bracketed_bounds": _arity_bounds(accepted, arity_rejected)},
            *refs,
        )
    else:
        argument_arity = partial(
            no_accepted if not accepted else
            "The native fixture retains accepted invocations but no "
            "Missing-parameter or Too-many-parameters rejection for this path.",
            *refs,
            known=arity_evidence,
        )
    domain_evidence = {
        **base,
        **({"fixture_boundaries": boundaries_ref} if boundaries_ref else {}),
        "accepted": [_observation(row) for row in accepted],
        "rejected": [_observation(row) for row in domain_rejected],
    }
    value_domains = (
        resolved(domain_evidence, ref)
        if accepted and domain_rejected
        else partial(
            no_accepted if not accepted else
            "The native fixture retains accepted values but no value "
            "rejection for this path.",
            ref,
            known=domain_evidence,
        )
    )
    envelope_evidence = {
        **base,
        "accepted": sorted({row["response"] for row in accepted}),
        "rejected": [_observation(row) for row in errors],
        "scope": "native_command_reply_only; success is not device acceptance",
    }
    command_envelope = (
        resolved(envelope_evidence, ref)
        if accepted and errors
        else partial(
            no_accepted if not accepted else
            "The native fixture retains only success replies for this "
            "path; no native error envelope is captured.",
            ref,
            known=envelope_evidence,
        )
    )
    return {
        "argument_arity": argument_arity,
        "value_domains": value_domains,
        "command_envelope": command_envelope,
    }, reconciled


def native_application_contracts(
    inventory_paths: set[str], arities: dict[str, dict[str, int | None]],
) -> tuple[dict[str, dict[str, dict]], dict]:
    """Resolve arity, value-domain and envelope subaxes from native fixtures.

    Each subaxis needs an accepted and a same-class rejected native
    observation for the path. Anything less stays partial.
    """
    manual_text = MANUAL_PATH.read_text(encoding="utf-8")
    groups: list[tuple[str, str, dict, list[dict], str | None, str | None]] = []
    for family, spec in NATIVE_APPLICATION_FIXTURES.items():
        report, fixture = _load_pinned_fixture(
            f"{family} application", str(spec["file"]), str(spec["sha256"])
        )
        if (
            report.get("format") != spec["format"]
            or report["oracle"].get("version") != "3.4.0.2001"
            or not isinstance(report.get(str(spec["boundaries"])), dict)
        ):
            raise ValueError(f"Native C-Gate {family} application provenance changed")
        groups.append((
            family, f"native_{family.lower()}_application", fixture,
            _application_fixture_rows(family, report),
            f"{fixture['path']}#{spec['boundaries']}", None,
        ))
    for family, spec in NATIVE_SHAPE_FIXTURES.items():
        report, fixture = _load_pinned_fixture(family, spec["file"], spec["sha256"])
        groups.append((
            family, f"native_{family.lower()}_contract", fixture,
            _shape_fixture_rows(family, spec, report), None, spec["attribution"],
        ))
    report, fixture = _load_pinned_fixture(
        "NET lifecycle", NATIVE_NET_FIXTURE["file"], NATIVE_NET_FIXTURE["sha256"]
    )
    groups.append((
        "NET", "native_net_lifecycle_contract", fixture, _net_fixture_rows(report),
        None, None,
    ))

    contracts: dict[str, dict[str, dict]] = {}
    fixtures: dict[str, dict] = {}
    reconciliation: dict[str, list] = {
        "no_native_counterexample": [],
        "contradicted_by_native": [],
        "no_counted_native_observation": [],
    }
    for family, source_name, fixture, rows, boundaries_ref, attribution in groups:
        by_path: dict[str, list[dict]] = {}
        for row in rows:
            if row["path"] not in inventory_paths:
                # Unknown-subcommand probes (for example SECURITY BOGUS)
                # belong to the family root, which this adapter leaves open.
                if row["path"].split()[-1] != "BOGUS":
                    raise ValueError(f"Native C-Gate fixture path is not inventoried: {row['path']}")
                continue
            by_path.setdefault(row["path"], []).append(row)
        if set(by_path) & set(contracts):
            raise ValueError(f"Native C-Gate fixture adapters overlap: {family}")
        fixtures[family] = {
            **fixture,
            "source": source_name,
            "observations": sum(len(value) for value in by_path.values()),
            "paths": len(by_path),
        }
        for path, observed in sorted(by_path.items()):
            contracts[path], reconciled = _resolve_native_path(
                path, observed, fixture,
                boundaries_ref=boundaries_ref, attribution=attribution,
                arity=arities.get(path), manual_text=manual_text,
            )
            if reconciled is not None:
                reconciliation[str(reconciled["status"])].append(path)
    summary = {
        "rule": NATIVE_FIXTURE_ADAPTER_RULE,
        "fixtures": fixtures,
        "declarative_arity_reconciliation": {
            status: sorted(paths) for status, paths in reconciliation.items()
        },
    }
    return contracts, summary


def apply_native_application_contract(
    path: str, axes: dict[str, dict], contracts: dict[str, dict[str, dict]],
    help_digest: str | None,
) -> None:
    contract = contracts.get(path)
    if contract is None:
        return
    selector = axes["selector_grammar"]["subaxes"]
    selector["argument_arity"] = contract["argument_arity"]
    selector["value_domains"] = contract["value_domains"]
    if help_digest is not None:
        for name in ("argument_arity", "value_domains"):
            evidence = selector[name].get("value") or selector[name]["known"]
            evidence["help_syntax_sha256"] = help_digest
    axes["response_event_envelopes"]["subaxes"]["command_envelope"] = (
        contract["command_envelope"]
    )
    for axis_name in ("selector_grammar", "response_event_envelopes"):
        axes[axis_name] = axis(axes[axis_name]["subaxes"])


def build_row(
    row: dict,
    arities: dict[str, dict[str, int | None]],
    syntax_hashes: dict[str, str],
    native_roles: dict[str, dict],
    application_contracts: dict[str, dict[str, dict]],
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
    if observed := native_roles.get(path):
        role_ref, access_ref = {
            NATIVE_INITIAL_ROLE_EVIDENCE_SHA256: (
                NATIVE_INITIAL_ROLE_REF, "rust/cbus-cgate/src/access.rs#NATIVE_PROBED_COMMANDS"
            ),
            NATIVE_ROLE_EVIDENCE_SHA256: (NATIVE_ROLE_REF, ACCESS_ROLE_REF),
            NATIVE_PROGRAMMING_ROLE_EVIDENCE_SHA256: (
                NATIVE_PROGRAMMING_ROLE_REF, ACCESS_PROGRAMMING_ROLE_REF
            ),
            NATIVE_MEDIA_ROLE_EVIDENCE_SHA256: (
                NATIVE_MEDIA_ROLE_REF, ACCESS_MEDIA_ROLE_REF
            ),
            NATIVE_ADMIN_ROLE_EVIDENCE_SHA256: (
                NATIVE_ADMIN_ROLE_REF, ACCESS_ADMIN_ROLE_REF
            ),
            NATIVE_APPLICATION_ROLE_EVIDENCE_SHA256: (
                NATIVE_APPLICATION_ROLE_REF, ACCESS_APPLICATION_ROLE_REF
            ),
            NATIVE_DALI_ROLE_EVIDENCE_SHA256: (
                NATIVE_DALI_ROLE_REF, ACCESS_DALI_ROLE_REF
            ),
            NATIVE_REMAINING_ROLE_EVIDENCE_SHA256: (
                NATIVE_REMAINING_ROLE_REF, ACCESS_REMAINING_ROLE_REF
            ),
            NATIVE_UNPROBED_ROLE_EVIDENCE_SHA256: (
                NATIVE_UNPROBED_ROLE_REF, ACCESS_UNPROBED_ROLE_REF
            ),
            NATIVE_FINAL_ROLE_EVIDENCE_SHA256: (
                NATIVE_FINAL_ROLE_REF, ACCESS_FINAL_ROLE_REF
            ),
        }[observed["fixture_sha256"]]
        handler_roles = unresolved(
            (
                "Two native handler-entry selector invocations and their lower-role "
                "denials are captured; other selectors, object-specific checks and "
                "successful physical delivery remain unverified."
                if len(observed.get("selector_invocations", [])) == 2
                else "One native handler-entry invocation and its lower-role denial are "
                "captured; other selectors, object-specific checks and successful "
                "physical delivery remain unverified."
            ),
            role_ref,
            access_ref,
            SERVICE_SESSION_REF,
            known={"native_handler_entry": observed},
        )
    else:
        handler_roles = unresolved(
            "Command-specific Clipsal/Max role filtering and object-level authorization are not yet normalized per path.",
            SERVICE_SESSION_REF,
            matrix_ref,
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
    apply_native_session_contract(path, axes)
    apply_native_application_contract(path, axes, application_contracts, help_digest)
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
    validate_native_session_observations()
    validate_native_selector_observations()
    primary, supplement = capability_paths()
    native_roles = native_handler_role_observations(
        {row["path"] for row in primary + supplement}
    )
    arities = application_arities()
    syntax_hashes = public_syntax_hashes()
    application_contracts, application_summary = native_application_contracts(
        {row["path"] for row in primary + supplement}, arities
    )
    contracts = [
        build_row(row, arities, syntax_hashes, native_roles, application_contracts)
        for row in primary + supplement
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
        "inventory_version": "cgate-contracts-2026-09-29.1",
        "purpose": "Evidence-bounded per-path contracts; unresolved fields are explicit and route coverage is not functional acceptance.",
        "sources": {
            "capability_matrix": {"sha256": digest(MATRIX_PATH)},
            "manual": {"sha256": digest(MANUAL_PATH)},
            "service": {"sha256": digest(SERVICE_PATH)},
            "event_mode": {"sha256": digest(EVENT_MODE_PATH)},
            "authorization_policy": {"sha256": authorization_source_digest()},
            "access_handler_registry": {"sha256": digest(ACCESS_PATH)},
            "toolkit_surface": {"sha256": digest(SURFACE_PATH)},
            "native_session_acceptance": {"sha256": digest(NATIVE_SESSION_PATH)},
            "native_session_selectors": {"sha256": digest(NATIVE_SELECTOR_PATH)},
            "native_initial_handler_roles": {"sha256": digest(NATIVE_INITIAL_ROLE_PATH)},
            "native_handler_role_expansion": {"sha256": digest(NATIVE_ROLE_PATH)},
            "native_programming_handler_roles": {"sha256": digest(NATIVE_PROGRAMMING_ROLE_PATH)},
            "native_media_handler_roles": {"sha256": digest(NATIVE_MEDIA_ROLE_PATH)},
            "native_admin_handler_roles": {"sha256": digest(NATIVE_ADMIN_ROLE_PATH)},
            "native_application_handler_roles": {"sha256": digest(NATIVE_APPLICATION_ROLE_PATH)},
            "native_dali_handler_selector_roles": {"sha256": digest(NATIVE_DALI_ROLE_PATH)},
            "native_remaining_handler_roles": {"sha256": digest(NATIVE_REMAINING_ROLE_PATH)},
            "native_unprobed_handler_roles": {"sha256": digest(NATIVE_UNPROBED_ROLE_PATH)},
            "native_final_handler_roles": {"sha256": digest(NATIVE_FINAL_ROLE_PATH)},
            **{
                summary["source"]: {"sha256": summary["sha256"]}
                for summary in application_summary["fixtures"].values()
            },
        },
        "counts": {
            "paths": len(contracts),
            "primary_paths": len(primary),
            "supplement_paths": len(supplement),
            "declarative_argument_arities": len(arities),
            "public_help_syntax_hashes": len(syntax_hashes),
            "native_handler_role_observations": len(native_roles),
            "native_handler_role_unresolved": sum(
                1
                for row in contracts
                if row["path"] in native_roles
                and row["axes"]["authorization"]["subaxes"]["handler_roles"]["status"]
                == "unresolved"
            ),
            "axis_status": axis_counts,
            "subaxis_status": subaxis_counts,
        },
        "axis_schema": {key: list(value) for key, value in AXIS_SUBAXES.items()},
        "native_application_fixture_adapters": application_summary,
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
