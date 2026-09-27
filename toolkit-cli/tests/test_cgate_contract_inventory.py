from __future__ import annotations

from collections import Counter
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys

import pytest

from cbus_toolkit import parity
from research import build_cgate_contract_inventory as contract_builder


ROOT = Path(__file__).resolve().parents[1]
INVENTORY_PATH = ROOT / "src/cbus_toolkit/cgate-contract-inventory.json"


def inventory() -> dict:
    return json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))


def contract_by_path(document: dict, path: str) -> dict:
    return next(row for row in document["contracts"] if row["path"] == path)


def test_inventory_is_deterministic_and_covers_both_routing_inventories() -> None:
    result = subprocess.run(
        [sys.executable, "research/build_cgate_contract_inventory.py", "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    document = inventory()
    assert document["counts"]["paths"] == 442
    assert document["counts"]["primary_paths"] == 431
    assert document["counts"]["supplement_paths"] == 11
    assert len({row["id"] for row in document["contracts"]}) == 442
    assert len({row["path"] for row in document["contracts"]}) == 442
    assert Counter(row["inventory"] for row in document["contracts"]) == {
        "primary": 431,
        "supplement": 11,
    }
    parity.validate_cgate_contract_inventory(
        document, raw=INVENTORY_PATH.read_bytes()
    )


def test_resolved_subaxes_are_exactly_counted_without_acceptance_inflation() -> None:
    counts = inventory()["counts"]
    assert counts["subaxis_status"]["selector_grammar.command_path"] == {
        "resolved": 442
    }
    assert counts["subaxis_status"]["selector_grammar.argument_arity"] == {
        "resolved": 3,
        "unresolved": 439,
    }
    assert counts["subaxis_status"]["selector_grammar.value_domains"] == {
        "resolved": 3,
        "unresolved": 439,
    }
    assert counts["declarative_argument_arities"] == 70
    known_arities = sum(
        "declarative_model_arity"
        in row["axes"]["selector_grammar"]["subaxes"]["argument_arity"].get(
            "known", {}
        )
        for row in inventory()["contracts"]
    )
    assert known_arities == 70
    assert counts["subaxis_status"]["authorization.programming_gate"] == {
        "resolved": 398,
        "unresolved": 44,
    }
    assert counts["subaxis_status"]["authorization.handler_roles"] == {
        "resolved": 5,
        "unresolved": 437,
    }
    assert counts["axis_status"]["authorization"] == {
        "partial": 437,
        "resolved": 5,
    }
    assert counts["subaxis_status"]["effects_routing.routing_class"] == {
        "resolved": 442
    }
    assert counts["subaxis_status"]["effects_routing.physical_io_boundary"] == {
        "resolved": 442
    }
    assert counts["subaxis_status"][
        "implementation_acceptance.functional_acceptance"
    ] == {"unresolved": 442}
    assert counts["axis_status"]["target_forms"] == {
        "resolved": 5,
        "unresolved": 437,
    }
    assert counts["subaxis_status"]["session_states.selection_and_locks"] == {
        "resolved": 5,
        "unresolved": 437,
    }
    assert counts["subaxis_status"]["effects_routing.state_effect"] == {
        "resolved": 9,
        "unresolved": 433,
    }


@pytest.mark.parametrize(
    ("path", "arity", "effect"),
    [
        ("SESSION_ID", {"minimum": 0, "maximum": 0}, "read_calling_id"),
        (
            "SESSION_ID ALL",
            {
                "minimum": 0,
                "maximum": None,
                "trailing_words": "ignored_by_native_and_endpoint",
            },
            "read_all_live_external_tcp_tls_sessions_only",
        ),
        ("SESSION_ID TAG", {"minimum": 1, "maximum": None}, "set_calling_tag_once"),
        (
            "EVENT",
            None,
            "replace_calling_connection_filter",
        ),
        ("QUIT", None, "flush_204_then_close"),
    ],
)
def test_native_session_contracts_are_bounded_and_preserve_open_axes(
    path: str, arity: dict | None, effect: str
) -> None:
    row = contract_by_path(inventory(), path)
    axes = row["axes"]
    argument_arity = axes["selector_grammar"]["subaxes"]["argument_arity"]
    if arity is None:
        assert argument_arity["status"] == "unresolved"
        assert argument_arity["known"]["observed_native_forms"]
    else:
        assert argument_arity["value"] == arity
    assert axes["session_states"]["status"] == "resolved"
    assert axes["target_forms"]["status"] == "resolved"
    assert axes["target_forms"]["subaxes"]["route_shape"]["value"] == (
        "command_connection_only_no_cbus_route"
    )
    if path == "SESSION_ID ALL":
        assert axes["target_forms"]["subaxes"]["address_shape"]["value"][
            "scope"
        ] == {
            "native": "all_open_command_sessions_including_internal_console",
            "endpoint": "live_external_tcp_tls_sessions_only",
        }
    state_effect = axes["effects_routing"]["subaxes"]["state_effect"]
    assert state_effect["status"] == "resolved"
    assert effect in state_effect["value"].values()
    assert contract_builder.NATIVE_SESSION_REF in state_effect["source_refs"]
    assert axes["response_event_envelopes"]["subaxes"]["command_envelope"][
        "status"
    ] == "unresolved"
    assert axes["authorization"]["subaxes"]["handler_roles"][
        "status"
    ] == "unresolved"
    assert axes["implementation_acceptance"]["subaxes"]["functional_acceptance"][
        "status"
    ] == "unresolved"


def test_native_session_trace_loss_fails_contract_generation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    changed = json.loads(contract_builder.NATIVE_SESSION_PATH.read_text())
    changed["cases"] = [
        row for row in changed["cases"] if row["command"] != "SESSION_ID TAG replacement"
    ]
    fixture = tmp_path / "changed-native-session.json"
    fixture.write_text(json.dumps(changed), encoding="utf-8")
    monkeypatch.setattr(contract_builder, "NATIVE_SESSION_PATH", fixture)
    with pytest.raises(ValueError, match="session acceptance cases changed"):
        contract_builder.build()


def test_native_internal_session_delta_cannot_be_silently_removed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    changed = json.loads(contract_builder.NATIVE_SESSION_PATH.read_text())
    for row in changed["cases"]:
        if row["command"] == "SESSION_ID ALL":
            row["reply"] = [
                line for line in row["reply"] if " origin=internal " not in line
            ]
    fixture = tmp_path / "without-internal-session.json"
    fixture.write_text(json.dumps(changed), encoding="utf-8")
    monkeypatch.setattr(contract_builder, "NATIVE_SESSION_PATH", fixture)
    with pytest.raises(ValueError, match="internal command session evidence changed"):
        contract_builder.build()


def test_native_session_status_without_matching_reply_cannot_resolve_contract(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    changed = json.loads(contract_builder.NATIVE_SESSION_PATH.read_text())
    for row in changed["cases"]:
        if row["command"] == "SESSION_ID TAG replacement":
            row["reply"] = ["408 Other result"]
    fixture = tmp_path / "changed-reply.json"
    fixture.write_text(json.dumps(changed), encoding="utf-8")
    monkeypatch.setattr(contract_builder, "NATIVE_SESSION_PATH", fixture)
    with pytest.raises(ValueError, match="session response evidence changed"):
        contract_builder.build()


@pytest.mark.parametrize("weakened", ["tagged_all", "trailing_all", "post_set_event"])
def test_unchecked_native_session_reply_changes_are_source_bound(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, weakened: str
) -> None:
    changed = json.loads(contract_builder.NATIVE_SESSION_PATH.read_text())
    if weakened == "tagged_all":
        rows = [row for row in changed["cases"] if row["command"] == "SESSION_ID ALL"]
        rows[1]["reply"] = [
            line for line in rows[1]["reply"] if "tag=C-Bus Toolkit test" not in line
        ]
    elif weakened == "trailing_all":
        row = next(
            row for row in changed["cases"]
            if row["command"] == "SESSION_ID ALL ignored-by-native"
        )
        row["reply"] = ["300 arbitrary"]
    else:
        row = next(
            row for row in changed["cases"]
            if row["command"] == "EVENT" and row["reply"] == ["306 e+s0c0"]
        )
        row["reply"] = ["306 e0s0c0"]
    fixture = tmp_path / f"weakened-{weakened}.json"
    fixture.write_text(json.dumps(changed), encoding="utf-8")
    monkeypatch.setattr(contract_builder, "NATIVE_SESSION_PATH", fixture)
    with pytest.raises(ValueError, match="session acceptance source changed"):
        contract_builder.build()


@pytest.mark.parametrize(
    ("path", "expected_status", "expected_value"),
    [
        ("LOGIN", "resolved", "session_auth_command_bypass"),
        ("BROADCAST_EVENT", "resolved", "required_when_gate_armed"),
        ("CMQTT CAPABILITIES", "resolved", "not_required_by_programming_gate"),
        ("AIRCON REFRESH", "resolved", "not_required_by_programming_gate"),
        (
            "AIRCON SET_WARD_ON",
            "resolved",
            "required_when_gate_armed",
        ),
        ("DALI GATEWAY PAGED_STORE", "resolved", "required_when_gate_armed"),
        ("DALI SESSION LIST", "resolved", "not_required_by_programming_gate"),
        ("DALI SESSION NEW", "resolved", "required_when_gate_armed"),
        ("DALI GATEWAY SAVE_TO_NVM", "unresolved", None),
        ("DO", "unresolved", None),
        ("SCENE", "unresolved", None),
    ],
)
def test_programming_gate_contract_tracks_service_policy(
    path: str, expected_status: str, expected_value: str | None
) -> None:
    row = contract_by_path(inventory(), path)
    gate = row["axes"]["authorization"]["subaxes"]["programming_gate"]
    assert gate["status"] == expected_status
    if expected_value is None:
        assert "value" not in gate
        assert gate["known"]["known_modes"] == [
            "required_when_gate_armed",
            "not_required_by_programming_gate",
        ]
    else:
        assert gate["value"] == expected_value


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("LOGIN", "allowed_authentication_command"),
        ("LOGOUT", "allowed_authentication_command"),
        ("EVENT", "handled_by_connection_event_mode_before_recovery_gate"),
        ("NOOP", "denied_until_login"),
    ],
)
def test_recovery_mode_records_connection_level_bypasses(
    path: str, expected: str
) -> None:
    row = contract_by_path(inventory(), path)
    recovery = row["axes"]["session_states"]["subaxes"]["recovery_mode"]
    assert recovery == {
        "status": "resolved",
        "value": expected,
        "source_refs": ["rust/cbus-cgate/src/service.rs#Service::handle"],
    }


def test_comment_recovery_and_tag_framing_variants_are_not_collapsed() -> None:
    document = inventory()
    hash_row = contract_by_path(document, "#")
    slash_row = contract_by_path(document, "//")
    hash_recovery = hash_row["axes"]["session_states"]["subaxes"]["recovery_mode"]
    assert hash_recovery["value"] == {
        "untagged": "consumed_before_recovery_gate",
        "tagged": "syntax_error_before_recovery_gate",
    }
    hash_framing = hash_row["axes"]["response_event_envelopes"]["subaxes"][
        "tag_and_completion_framing"
    ]["value"]
    slash_framing = slash_row["axes"]["response_event_envelopes"]["subaxes"][
        "tag_and_completion_framing"
    ]["value"]
    assert hash_framing == {
        "untagged": "no_response",
        "tagged": "untagged_400_syntax_error",
    }
    assert slash_framing == {
        "untagged": "no_response",
        "tagged": "tag_echoed_400_syntax_error",
    }


@pytest.mark.parametrize(
    ("path", "programming_gate"),
    [
        ("TELEPHONY CLEAR_DIVERSION", "required_when_gate_armed"),
        ("TELEPHONY DIVERT", "required_when_gate_armed"),
        ("TELEPHONY ISOLATE_SECONDARY_OUTLET", "required_when_gate_armed"),
        (
            "TELEPHONY RECALL_LAST_NUMBER_REQUEST",
            "not_required_by_programming_gate",
        ),
        ("TELEPHONY REJECT_INCOMING_CALL", "required_when_gate_armed"),
    ],
)
def test_all_telephony_commands_bind_program_access_separately_from_login_gate(
    path: str, programming_gate: str
) -> None:
    row = contract_by_path(inventory(), path)
    authorization = row["axes"]["authorization"]
    assert authorization["status"] == "resolved"
    assert authorization["subaxes"]["programming_gate"]["value"] == programming_gate
    assert authorization["subaxes"]["handler_roles"] == {
        "status": "resolved",
        "value": {
            "minimum_access_level": "Program",
            "enforced_before_physical_handler": True,
            "lower_access_result": 420,
        },
        "source_refs": [
            "rust/cbus-cgate/src/service.rs#Service::handle",
            "rust/cbus-cgate/src/capability_matrix.rs#CAPABILITY_MATRIX",
        ],
    }
    assert "Program ACCESS level" in row["routing_evidence"]
    assert "lower roles make no write" in row["routing_evidence"]


def test_inventory_rejects_axis_and_contract_digest_tampering() -> None:
    document = inventory()
    changed = deepcopy(document)
    contract = changed["contracts"][0]
    contract["axes"]["effects_routing"]["subaxes"]["routing_class"][
        "value"
    ] = "invented"
    with pytest.raises(ValueError, match="axes digest changed"):
        parity.validate_cgate_contract_inventory(changed)

    changed = deepcopy(document)
    contract = changed["contracts"][0]
    contract["routing_evidence"] += " changed"
    with pytest.raises(ValueError, match="contract digest changed"):
        parity.validate_cgate_contract_inventory(changed)


def test_packaged_register_binds_every_scope_row_to_the_inventory() -> None:
    package = ROOT / "src/cbus_toolkit"
    register_raw = (package / "parity-obligations.json").read_bytes()
    evidence_raw = (package / "parity-evidence.json").read_bytes()
    ledger_raw = (package / "capabilities.json").read_bytes()
    contract_raw = INVENTORY_PATH.read_bytes()
    register = json.loads(register_raw)
    evidence = json.loads(evidence_raw)
    ledger = json.loads(ledger_raw)
    contracts = json.loads(contract_raw)

    report = parity.evaluate(
        register,
        evidence,
        ledger,
        evidence_raw=evidence_raw,
        ledger_raw=ledger_raw,
        cgate_contract_inventory=contracts,
        cgate_contract_raw=contract_raw,
    )
    assert report["cgate_contracts"]["paths"] == 442
    assert report["cgate_contracts"]["subaxis_status"] == contracts["counts"][
        "subaxis_status"
    ]

    changed = deepcopy(register)
    scope = next(
        row for row in changed["scope_items"] if row["kind"] == "cgate_primary_path"
    )
    scope["contract_axes"]["effects_routing"]["subaxes"]["routing_class"][
        "value"
    ] = "invented"
    with pytest.raises(ValueError, match="axes digest changed"):
        parity.evaluate(
            changed,
            evidence,
            ledger,
            evidence_raw=evidence_raw,
            ledger_raw=ledger_raw,
            cgate_contract_inventory=contracts,
            cgate_contract_raw=contract_raw,
        )


def test_contract_inventory_bytes_are_digest_bound_by_the_register() -> None:
    package = ROOT / "src/cbus_toolkit"
    register = json.loads((package / "parity-obligations.json").read_text())
    document = inventory()
    raw = INVENTORY_PATH.read_bytes()
    assert register["source_digests"]["cgate_contract_inventory"] == sha256(
        raw
    ).hexdigest()
    changed_raw = raw.replace(b'"paths": 442', b'"paths": 443', 1)
    changed = json.loads(changed_raw)
    with pytest.raises(ValueError, match="fixed counts changed"):
        parity.validate_cgate_contract_inventory(changed, raw=changed_raw)


def test_contract_domain_cannot_resolve_while_any_axis_is_incomplete() -> None:
    package = ROOT / "src/cbus_toolkit"
    register = json.loads((package / "parity-obligations.json").read_text())
    evidence_raw = (package / "parity-evidence.json").read_bytes()
    ledger_raw = (package / "capabilities.json").read_bytes()
    contract_raw = INVENTORY_PATH.read_bytes()
    evidence = json.loads(evidence_raw)
    ledger = json.loads(ledger_raw)
    contracts = json.loads(contract_raw)
    domain = next(
        row
        for row in register["source_inventory"]
        if row["id"] == "cgate_selector_state_effect_contracts"
    )
    domain["resolved"] = True
    with pytest.raises(
        ValueError,
        match="cannot resolve while contract axes remain partial or unresolved",
    ):
        parity.evaluate(
            register,
            evidence,
            ledger,
            evidence_raw=evidence_raw,
            ledger_raw=ledger_raw,
            cgate_contract_inventory=contracts,
            cgate_contract_raw=contract_raw,
        )
