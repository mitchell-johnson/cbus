"""Status-report projections preserve missing facts and native selection rules."""
from types import SimpleNamespace

import pytest

from cbus_toolkit import project_documentation_status as status


def unit(address=1, kind="KEY1", firmware="1.2.67", interval="30"):
    return SimpleNamespace(address=address, unit_type=kind, firmware=firmware,
                           parameters={} if interval is None else {"StatusReportInterval": interval})


def test_empty_and_verified_noninput_networks_are_known_none():
    assert status.minimum_status_report([]).known
    result = status.minimum_status_report([unit(kind="RELDN8", firmware="2.7.00", interval=None)])
    assert result.known and result.seconds is None and result.unit is None


def test_interface_membership_does_not_depend_on_pp_presence():
    result = status.minimum_status_report([unit(interval=None)])
    assert not result.known
    assert "missing or invalid" in result.issues[0]
    assert status.input_interface("KEY1", "1.2.67") == (True, "TKey1")


@pytest.mark.parametrize("kind,firmware", [("FAKE", "1.0"), ("KEY1", ""), ("KEY1", "10"),
                                          ("KEYA1", "1.3.00"), ("KEY1", "invalid"), ("KEY1", "2147483648"), ("KEY1", "9" * 5000)])
def test_unknown_profile_cannot_be_treated_as_noninput(kind, firmware):
    assert not status.minimum_status_report([unit(kind=kind, firmware=firmware)]).known


def test_first_matching_factory_registration_wins_even_if_later_class_exposes_interface():
    # The original registers KEYGL5 twice; TCBusEDLTUnit is first and does not
    # expose this old Delphi input interface. TKEYGL5 later does expose it.
    assert status.input_interface("keygl5", "5.5.00") == (False, "TCBusEDLTUnit")
    result = status.minimum_status_report([unit(kind="KEYGL5", firmware="5.5.00", interval="1")])
    assert result.known and result.seconds is None


@pytest.mark.parametrize("kind", ["PC_GIM", "SENCT4"])
def test_interface_without_recovered_pp_mapping_stays_unknown(kind):
    result = status.minimum_status_report([unit(kind=kind, firmware="1.0")])
    assert not result.known
    assert "mapping is unrecovered" in result.issues[0]


@pytest.mark.parametrize("value,expected", [("0", 0), ("1", 1), ("2", 2), ("255", 255),
                                             ("-1", -1), ("+20", 20), ("$0A", 10),
                                             ("0x0a", 10), (" 42 ", 42), ("99998", 99998)])
def test_getter_value_is_not_ui_clamped_or_scaled(value, expected):
    sample = unit(interval=value)
    result = status.minimum_status_report([sample])
    assert result.known and result.seconds == expected and result.unit is sample


@pytest.mark.parametrize("value", ["99999", "100000", "2147483647"])
def test_native_sentinel_is_preserved(value):
    result = status.minimum_status_report([unit(interval=value)])
    assert result.known and result.seconds is None and result.unit is None


@pytest.mark.parametrize("value", [None, "", "1 2", "1.2", "no", "2147483648", "-2147483649", "9" * 5000])
def test_incomplete_or_invalid_values_prevent_a_false_minimum(value):
    result = status.minimum_status_report([unit(interval="0"), unit(2, interval=value)])
    assert not result.known and result.seconds is None


def test_first_tie_in_supplied_manager_order_is_retained():
    samples = [unit(7, interval="20"), unit(2, interval="20"), unit(1, interval="30")]
    result = status.minimum_status_report(samples)
    assert result.known and result.seconds == 20 and result.unit is samples[0]


def test_iope_independent_input_interface_uses_same_verbatim_pp():
    sample = unit(kind="IOPE2C4", firmware="1.0", interval="7")
    result = status.minimum_status_report([sample])
    assert result.known and result.seconds == 7
    assert result.basis == "stored_pp_snapshot; original programming-load success/failure not observed"


def test_retained_source_receipt_matches_runtime_membership():
    import hashlib
    import json
    from pathlib import Path

    receipt = Path(__file__).resolve().parents[1] / "research/experiments/2026-09-30/project-documentor-status-static.json"
    evidence = json.loads(receipt.read_text())
    assert evidence["model_module_sha256"] == hashlib.sha256(Path(status.__file__).read_bytes()).hexdigest()
    assert all(evidence["checks"].values())
    assert evidence["registration_count"] == 425
    assert evidence["input_registration_count"] == 108
    assert {name for name, value in evidence["classes"].items() if value} == status.INPUT_CLASSES
    assert {name for name, value in evidence["classes"].items() if not value} == status.NONINPUT_CLASSES
    assert not evidence["original_executed"]
    assert not evidence["original_generated_page_compared"]
