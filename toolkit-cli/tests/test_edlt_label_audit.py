"""Network-wide eDLT label baseline and drift acceptance automation."""
from __future__ import annotations

import copy
import json
from unittest.mock import patch

import pytest

from cbus_toolkit.cgate import CGateError, CGateResponse
from cbus_toolkit.cli import build_parser, run
from cbus_toolkit.edlt_label_audit import (
    baseline_from_inventory,
    capture_label_audit,
    compare_baselines,
    load_baseline,
    validate_baseline,
    write_baseline,
)
from test_cmqtt_inventory import InventoryClient, labelled, native


GROUPS = tuple([255] * 12 + [56, 27, 56, 25, 56, 33, 56, 24] + [255] * 24)


class AuditClient(InventoryClient):
    def __init__(self, identities, *, groups=None, **options):
        super().__init__(identities, **options)
        self.groups = {address: GROUPS for address in identities} | dict(groups or {})

    def command(self, command):
        words = command.split()
        if words[0] == "GET" and words[-1] == "WidgetGroups":
            self.calls.append(command)
            address = int(words[1].rsplit("/", 1)[1])
            values = ",".join(map(str, self.groups[address]))
            return native(f"300 {words[1]}: WidgetGroups={values}", 300)
        return super().command(command)


class BrokenGroupsClient(AuditClient):
    def command(self, command):
        if command.endswith(" WidgetGroups"):
            self.calls.append(command)
            return CGateResponse(("404 WidgetGroups unavailable",), "404 WidgetGroups unavailable", 404)
        return super().command(command)


class ErrorGroupsClient(AuditClient):
    def __init__(self, *args, transport=False, **options):
        super().__init__(*args, **options)
        self.transport = transport

    def command(self, command):
        if command == "GET //TEST/254/p/5 WidgetGroups":
            self.calls.append(command)
            if self.transport:
                raise RuntimeError("connection lost")
            raise CGateError(
                CGateResponse(
                    ("404 WidgetGroups unavailable",),
                    "404 WidgetGroups unavailable",
                    404,
                )
            )
        return super().command(command)


class Connection:
    def __init__(self, source):
        self.source = source

    def __enter__(self):
        return self.source

    def __exit__(self, *unused):
        return False


def client(*, first="Five", second="Nine", groups=None, serial="100.5"):
    identities = {
        5: ("KEYGL5", "5.5.00", serial),
        9: ("KEYGL5", "5.5.00", "100.9"),
    }
    return AuditClient(
        identities,
        images={5: labelled(first), 9: labelled(second)},
        groups=groups,
    )


def capture(source=None, **options):
    return capture_label_audit(source or client(), "//TEST/254", **options)


def test_capture_joins_one_fresh_inventory_with_cached_widget_groups():
    source = client()
    result = capture(source)

    assert result["complete"] and result["accepted"]
    assert result["baseline"]["unit_count"] == 2
    assert [unit["address"] for unit in result["baseline"]["units"]] == [
        "//TEST/254/p/5",
        "//TEST/254/p/9",
    ]
    assert all(len(unit["widget_groups"]) == 44 for unit in result["baseline"]["units"])
    assert all(unit["physical_image_sha256"] for unit in result["baseline"]["units"])
    assert all(unit["identity"]["serial"] for unit in result["baseline"]["units"])
    assert source.calls.count("NET SYNC //TEST/254 fast") == 1
    assert source.calls.count("GET //TEST/254/p/5 WidgetGroups") == 1
    assert source.calls.count("GET //TEST/254/p/9 WidgetGroups") == 1
    assert not any(call == "NET SYNC //TEST/254" for call in source.calls)
    assert not result["dynamic_labels_compared"]
    assert not result["physical_device_modified"]
    assert result["physical_device_volatile_state_modified"]


def test_configuration_and_label_modes_distinguish_unparsed_physical_bytes():
    expected = capture()["baseline"]
    changed = bytearray(labelled("Five"))
    changed[0x50] ^= 0x7F

    def changed_source():
        source = client()
        source.images[5] = bytes(changed)
        return source

    exact = capture(changed_source(), expected=expected, mode="exact")
    configuration = capture(changed_source(), expected=expected, mode="configuration")
    labels = capture(changed_source(), expected=expected, mode="labels")

    assert not exact["accepted"]
    assert exact["comparison"]["changed_units"][0]["changes"] == ["physical-image"]
    assert exact["comparison"]["changed_units"][0]["required_change"]
    assert configuration["accepted"] and configuration["comparison"]["matches"]
    assert configuration["comparison"]["changed_units"][0]["changes"] == [
        "physical-image"
    ]
    assert labels["accepted"] and labels["comparison"]["matches"]


def test_label_text_drift_fails_every_mode_and_names_all_digests():
    expected = capture()["baseline"]
    for mode in ("exact", "configuration", "labels"):
        result = capture(client(first="Garage"), expected=expected, mode=mode)
        assert not result["accepted"]
        row = result["comparison"]["changed_units"][0]
        assert row["address"] == "//TEST/254/p/5"
        assert row["changes"] == ["physical-image", "configuration", "labels"]
        assert row["required_change"]


def test_widget_groups_drift_is_required_in_every_mode():
    expected = capture()["baseline"]
    values = list(GROUPS)
    values[12] = 57
    for mode in ("exact", "configuration", "labels"):
        result = capture(
            client(groups={5: tuple(values)}), expected=expected, mode=mode
        )
        assert not result["accepted"]
        assert result["comparison"]["changed_units"][0]["changes"] == [
            "configuration",
            "labels",
            "widget-groups",
        ]


def test_added_removed_and_identity_changes_are_explicit():
    expected = capture()["baseline"]
    replacement = capture(client(serial="101.5"))["baseline"]
    comparison = compare_baselines(expected, replacement, "labels")
    assert not comparison["matches"]
    assert comparison["changed_units"][0]["changes"] == ["identity"]

    removed = copy.deepcopy(replacement)
    removed["units"].pop()
    removed["unit_count"] = 1
    comparison = compare_baselines(expected, removed, "configuration")
    assert comparison["removed_units"] == ["//TEST/254/p/9"]


def test_incomplete_widget_groups_never_produces_or_compares_a_baseline():
    identities = {5: ("KEYGL5", "5.5.00", "100.5")}
    source = BrokenGroupsClient(identities, images={5: labelled("Five")})
    result = capture_label_audit(
        source, "//TEST/254", expected=capture()["baseline"]
    )

    assert not result["complete"] and not result["accepted"]
    assert result["baseline"] is None and result["comparison"] is None
    assert result["comparison_not_run_reason"] == "live acquisition was incomplete"
    assert result["widget_groups_errors"][0]["address"] == "//TEST/254/p/5"


def test_complete_cgate_rejection_keeps_later_group_reads_safe():
    identities = {
        5: ("KEYGL5", "5.5.00", "100.5"),
        9: ("KEYGL5", "5.5.00", "100.9"),
    }
    source = ErrorGroupsClient(
        identities, images={5: labelled("Five"), 9: labelled("Nine")}
    )
    result = capture_label_audit(source, "//TEST/254")

    assert not result["complete"]
    assert result["widget_groups_errors"][0]["type"] == "CGateError"
    assert source.calls.count("GET //TEST/254/p/9 WidgetGroups") == 1
    assert "widget_groups" in result["inventory"]["units"][1]


def test_transport_failure_prevents_later_group_read():
    identities = {
        5: ("KEYGL5", "5.5.00", "100.5"),
        9: ("KEYGL5", "5.5.00", "100.9"),
    }
    source = ErrorGroupsClient(
        identities,
        images={5: labelled("Five"), 9: labelled("Nine")},
        transport=True,
    )
    result = capture_label_audit(source, "//TEST/254")

    assert not result["complete"]
    assert result["widget_groups_errors"][0]["connection_usable"] is False
    assert result["widget_groups_errors"][1]["type"] == "NotAttempted"
    assert "GET //TEST/254/p/9 WidgetGroups" not in source.calls


def test_baseline_validation_detects_tampering_and_file_write_is_exclusive(tmp_path):
    baseline = capture()["baseline"]
    target = tmp_path / "labels.json"
    write_baseline(target, baseline)
    assert load_baseline(target) == baseline
    with pytest.raises(FileExistsError):
        write_baseline(target, baseline)

    tampered = json.loads(target.read_text())
    tampered["units"][0]["labels"]["static_strings"][0]["text"] = "Tampered"
    with pytest.raises(ValueError, match="labels fingerprint mismatch"):
        validate_baseline(tampered)


def test_baseline_requires_complete_serial_bound_inventory():
    inventory = capture()["inventory"]
    inventory["complete"] = False
    with pytest.raises(ValueError, match="complete live"):
        baseline_from_inventory(inventory)


def test_cli_contract_has_guarded_capture_compare_and_create_modes():
    parser = build_parser()
    compare = parser.parse_args(
        [
            "cgate",
            "edlt-label-audit",
            "//TEST/254",
            "--mode",
            "labels",
            "--baseline",
            "prior.json",
        ]
    )
    assert compare.network == "//TEST/254"
    assert compare.mode == "labels"
    assert str(compare.baseline) == "prior.json"

    create = parser.parse_args(
        ["cgate", "edlt-label-audit", "//TEST/254", "--write-baseline", "new.json"]
    )
    assert create.mode == "configuration"
    assert str(create.write_baseline) == "new.json"
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "cgate",
                "edlt-label-audit",
                "//TEST/254",
                "--baseline",
                "a.json",
                "--write-baseline",
                "b.json",
            ]
        )


def test_cli_dispatch_writes_complete_baseline_and_returns_drift_status(tmp_path):
    parser = build_parser()
    baseline = tmp_path / "baseline.json"
    args = parser.parse_args(
        [
            "cgate",
            "edlt-label-audit",
            "//TEST/254",
            "--write-baseline",
            str(baseline),
        ]
    )
    with patch("cbus_toolkit.cgate.CGateClient", return_value=Connection(client())):
        result, status = run(args)
    assert status == 0 and result["accepted"]
    assert result["baseline_written"] == str(baseline)
    assert load_baseline(baseline)["unit_count"] == 2

    args = parser.parse_args(
        [
            "cgate",
            "edlt-label-audit",
            "//TEST/254",
            "--mode",
            "labels",
            "--baseline",
            str(baseline),
        ]
    )
    with patch(
        "cbus_toolkit.cgate.CGateClient",
        return_value=Connection(client(first="Changed")),
    ):
        result, status = run(args)
    assert status == 1 and not result["accepted"]
    assert not result["comparison"]["matches"]


def test_cli_rejects_tampered_baseline_before_connection(tmp_path):
    baseline = capture()["baseline"]
    baseline["units"][0]["labels"]["static_strings"][0]["text"] = "tampered"
    path = tmp_path / "tampered.json"
    path.write_text(json.dumps(baseline), encoding="utf-8")
    args = build_parser().parse_args(
        ["cgate", "edlt-label-audit", "//TEST/254", "--baseline", str(path)]
    )
    with patch("cbus_toolkit.cgate.CGateClient") as constructor:
        with pytest.raises(ValueError, match="labels fingerprint mismatch"):
            run(args)
    constructor.assert_not_called()
