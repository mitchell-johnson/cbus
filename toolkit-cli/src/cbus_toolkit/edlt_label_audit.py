"""Deterministic live eDLT label baselines and post-programming comparisons.

The live reader deliberately keeps three different comparison strengths:

* ``exact`` compares the complete 9,216-byte physical-image digest;
* ``configuration`` compares the decoded label-bearing records and the opaque
  physical WidgetGroups mapping; and
* ``labels`` compares only label text, references, placement and mapping.

Transient dynamic-label observations are retained in the acquisition receipt
but never enter a baseline: cmqttd observes network SAL traffic and cannot
prove a device's current dynamic-label cache.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path

from .cmqtt import edlt_label_inventory
from .edlt_widget_groups import read_cached_edlt_widget_groups


BASELINE_FORMAT = "cbus-edlt-label-baseline-v1"
AUDIT_FORMAT = "cbus-edlt-label-audit-v1"
COMPARISON_MODES = ("exact", "configuration", "labels")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_MAX_BASELINE_BYTES = 8 * 1024 * 1024
_UNIT_FIELDS = {
    "address",
    "identity",
    "physical_image_sha256",
    "configuration_sha256",
    "labels_sha256",
    "widget_groups_sha256",
    "configuration",
    "labels",
    "widget_groups",
}
_LABEL_WIDGET_FIELDS = (
    "widget",
    "widget_type",
    "standby",
    "page",
    "position",
    "visible",
    "application",
    "group",
    "scene",
    "label_type",
    "label_source",
    "label_index",
    "label",
    "status_index",
    "status_text",
    "prefix_index",
    "prefix",
    "suffix_index",
    "suffix",
    "level_statuses",
    "static_references",
)


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _json_copy(value: object) -> object:
    # Round-tripping rejects accidental non-JSON values while making the
    # baseline independent from mutable acquisition dictionaries.
    return json.loads(_canonical(value))


def _identity(unit: dict[str, object]) -> dict[str, str]:
    serial_evidence = unit.get("physical_serial_evidence")
    if (
        unit.get("physical_serial_verified") is not True
        or not isinstance(serial_evidence, dict)
        or serial_evidence.get("stable") is not True
    ):
        raise ValueError("Every baseline unit requires stable physical serial evidence")
    identity = {
        "serial": serial_evidence.get("serial"),
        "unit_type": unit.get("unit_type"),
        "firmware": unit.get("firmware"),
    }
    if any(not isinstance(value, str) or not value for value in identity.values()):
        raise ValueError("Every baseline unit requires complete physical identity")
    return identity  # type: ignore[return-value]


def _configuration_projection(unit: dict[str, object], groups: list[int]) -> dict[str, object]:
    fields = (
        "page_mode",
        "navigation_variant",
        "page_names",
        "widgets",
        "static_strings",
        "special_static_references",
        "scenes",
        "static_text_crc_verified",
        "raw_static_text_crc_verified",
        "static_text_crc_method",
    )
    if any(field not in unit for field in fields):
        raise ValueError("Live eDLT receipt is missing decoded label configuration")
    return _json_copy({field: unit[field] for field in fields} | {"widget_groups": groups})  # type: ignore[return-value]


def _label_projection(configuration: dict[str, object]) -> dict[str, object]:
    widgets = configuration.get("widgets")
    if not isinstance(widgets, list):
        raise ValueError("Decoded eDLT widgets must be a JSON array")
    projected_widgets = []
    for widget in widgets:
        if not isinstance(widget, dict):
            raise ValueError("Decoded eDLT widget rows must be JSON objects")
        projected_widgets.append(
            {field: widget[field] for field in _LABEL_WIDGET_FIELDS if field in widget}
        )
    return {
        "page_names": copy.deepcopy(configuration["page_names"]),
        "widgets": projected_widgets,
        "static_strings": copy.deepcopy(configuration["static_strings"]),
        "special_static_references": copy.deepcopy(
            configuration["special_static_references"]
        ),
        "scenes": copy.deepcopy(configuration["scenes"]),
        "widget_groups": copy.deepcopy(configuration["widget_groups"]),
    }


def baseline_from_inventory(inventory: dict[str, object]) -> dict[str, object]:
    """Build one deterministic baseline from a complete augmented inventory."""
    if (
        not isinstance(inventory, dict)
        or inventory.get("format") != "cbus-edlt-label-inventory-v1"
        or inventory.get("complete") is not True
    ):
        raise ValueError("A baseline requires one complete live eDLT label inventory")
    network, units = inventory.get("network"), inventory.get("units")
    if not isinstance(network, str) or not isinstance(units, list) or len(units) > 256:
        raise ValueError("Invalid live eDLT inventory bounds")
    result_units = []
    seen = set()
    for raw_unit in units:
        if not isinstance(raw_unit, dict):
            raise ValueError("Live eDLT inventory units must be JSON objects")
        address = raw_unit.get("address")
        if not isinstance(address, str) or address in seen:
            raise ValueError("Live eDLT inventory contains an invalid or duplicate address")
        seen.add(address)
        mapping = raw_unit.get("widget_groups")
        if not isinstance(mapping, dict) or mapping.get("complete") is not True:
            raise ValueError("Every baseline unit requires a complete WidgetGroups read")
        groups = mapping.get("widget_groups")
        if (
            not isinstance(groups, list)
            or len(groups) != 44
            or any(type(value) is not int or not 0 <= value <= 255 for value in groups)
        ):
            raise ValueError("Every baseline unit requires exactly 44 WidgetGroups bytes")
        physical = raw_unit.get("memory_sha256")
        if not isinstance(physical, str) or _SHA256.fullmatch(physical) is None:
            raise ValueError("Every baseline unit requires a physical-image SHA-256")
        configuration = _configuration_projection(raw_unit, groups)
        labels = _label_projection(configuration)
        result_units.append(
            {
                "address": address,
                "identity": _identity(raw_unit),
                "physical_image_sha256": physical,
                "configuration_sha256": _digest(configuration),
                "labels_sha256": _digest(labels),
                "widget_groups_sha256": _digest(groups),
                "configuration": configuration,
                "labels": labels,
                "widget_groups": copy.deepcopy(groups),
            }
        )
    result_units.sort(key=lambda unit: int(unit["address"].rsplit("/", 1)[1]))
    return {
        "format": BASELINE_FORMAT,
        "network": network,
        "complete": True,
        "source": "physical-via-cmqttd",
        "units": result_units,
        "unit_count": len(result_units),
        "dynamic_labels_included": False,
        "dynamic_label_reason": "network observations are incomplete and recipient-unverified",
        "physical_snapshots_sequential": True,
        "network_snapshot_atomic": False,
    }


def validate_baseline(value: object) -> dict[str, object]:
    """Strictly validate a baseline and all stored fingerprints."""
    if not isinstance(value, dict) or set(value) != {
        "format",
        "network",
        "complete",
        "source",
        "units",
        "unit_count",
        "dynamic_labels_included",
        "dynamic_label_reason",
        "physical_snapshots_sequential",
        "network_snapshot_atomic",
    }:
        raise ValueError("Invalid eDLT label baseline document shape")
    if (
        value["format"] != BASELINE_FORMAT
        or value["complete"] is not True
        or value["source"] != "physical-via-cmqttd"
        or value["dynamic_labels_included"] is not False
        or value["physical_snapshots_sequential"] is not True
        or value["network_snapshot_atomic"] is not False
        or not isinstance(value["network"], str)
        or not isinstance(value["dynamic_label_reason"], str)
    ):
        raise ValueError("Invalid eDLT label baseline provenance")
    units = value["units"]
    if (
        not isinstance(units, list)
        or len(units) > 256
        or type(value["unit_count"]) is not int
        or value["unit_count"] != len(units)
    ):
        raise ValueError("Invalid eDLT label baseline unit bounds")
    addresses = []
    for unit in units:
        if not isinstance(unit, dict) or set(unit) != _UNIT_FIELDS:
            raise ValueError("Invalid eDLT label baseline unit shape")
        address, identity = unit["address"], unit["identity"]
        if not isinstance(address, str):
            raise ValueError("Invalid eDLT label baseline address")
        addresses.append(address)
        if (
            not isinstance(identity, dict)
            or set(identity) != {"serial", "unit_type", "firmware"}
            or any(not isinstance(item, str) or not item for item in identity.values())
        ):
            raise ValueError("Invalid eDLT label baseline identity")
        groups = unit["widget_groups"]
        if (
            not isinstance(groups, list)
            or len(groups) != 44
            or any(type(item) is not int or not 0 <= item <= 255 for item in groups)
        ):
            raise ValueError("Invalid eDLT label baseline WidgetGroups")
        for field in (
            "physical_image_sha256",
            "configuration_sha256",
            "labels_sha256",
            "widget_groups_sha256",
        ):
            if not isinstance(unit[field], str) or _SHA256.fullmatch(unit[field]) is None:
                raise ValueError("Invalid eDLT label baseline fingerprint")
        if unit["configuration_sha256"] != _digest(unit["configuration"]):
            raise ValueError("eDLT label baseline configuration fingerprint mismatch")
        if unit["labels_sha256"] != _digest(unit["labels"]):
            raise ValueError("eDLT label baseline labels fingerprint mismatch")
        if unit["widget_groups_sha256"] != _digest(groups):
            raise ValueError("eDLT label baseline WidgetGroups fingerprint mismatch")
    if len(set(addresses)) != len(addresses) or addresses != sorted(
        addresses, key=lambda address: int(address.rsplit("/", 1)[1])
    ):
        raise ValueError("eDLT label baseline units must be unique and numerically ordered")
    return _json_copy(value)  # type: ignore[return-value]


def load_baseline(path: Path) -> dict[str, object]:
    if not isinstance(path, Path):
        raise ValueError("Baseline path must be a filesystem path")
    size = path.stat().st_size
    if size > _MAX_BASELINE_BYTES:
        raise ValueError("eDLT label baseline exceeds 8 MiB")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except UnicodeDecodeError as error:
        raise ValueError("eDLT label baseline must be UTF-8 JSON") from error
    except json.JSONDecodeError as error:
        raise ValueError("eDLT label baseline is not valid JSON") from error
    return validate_baseline(value)


def write_baseline(path: Path, baseline: dict[str, object]) -> None:
    """Create a validated baseline exclusively; never replace prior evidence."""
    value = validate_baseline(baseline)
    with path.open("x", encoding="utf-8", newline="\n") as output:
        json.dump(value, output, indent=2, ensure_ascii=False)
        output.write("\n")


def compare_baselines(
    expected: dict[str, object], actual: dict[str, object], mode: str
) -> dict[str, object]:
    if mode not in COMPARISON_MODES:
        raise ValueError("Comparison mode must be exact, configuration or labels")
    expected = validate_baseline(expected)
    actual = validate_baseline(actual)
    if expected["network"] != actual["network"]:
        raise ValueError("Baseline network differs from the live requested network")
    old = {unit["address"]: unit for unit in expected["units"]}
    new = {unit["address"]: unit for unit in actual["units"]}
    added = sorted(set(new) - set(old), key=lambda address: int(address.rsplit("/", 1)[1]))
    removed = sorted(set(old) - set(new), key=lambda address: int(address.rsplit("/", 1)[1]))
    changed = []
    required = {
        "exact": {"identity", "physical-image", "widget-groups"},
        "configuration": {"identity", "configuration", "widget-groups"},
        "labels": {"identity", "labels", "widget-groups"},
    }[mode]
    for address in sorted(set(old) & set(new), key=lambda item: int(item.rsplit("/", 1)[1])):
        kinds = []
        if old[address]["identity"] != new[address]["identity"]:
            kinds.append("identity")
        if old[address]["physical_image_sha256"] != new[address]["physical_image_sha256"]:
            kinds.append("physical-image")
        if old[address]["configuration_sha256"] != new[address]["configuration_sha256"]:
            kinds.append("configuration")
        if old[address]["labels_sha256"] != new[address]["labels_sha256"]:
            kinds.append("labels")
        if old[address]["widget_groups_sha256"] != new[address]["widget_groups_sha256"]:
            kinds.append("widget-groups")
        if kinds:
            changed.append(
                {
                    "address": address,
                    "changes": kinds,
                    "required_change": bool(required.intersection(kinds)),
                }
            )
    required_changed = [item for item in changed if item["required_change"]]
    matches = not added and not removed and not required_changed
    return {
        "format": "cbus-edlt-label-comparison-v1",
        "mode": mode,
        "matches": matches,
        "network": actual["network"],
        "added_units": added,
        "removed_units": removed,
        "changed_units": changed,
        "required_changed_units": required_changed,
        "expected_unit_count": expected["unit_count"],
        "actual_unit_count": actual["unit_count"],
    }


def capture_label_audit(
    client,
    network: str,
    *,
    expected: dict[str, object] | None = None,
    mode: str = "configuration",
) -> dict[str, object]:
    """Acquire one fresh network inventory and compare its stable label state."""
    if mode not in COMPARISON_MODES:
        raise ValueError("Comparison mode must be exact, configuration or labels")
    from .cgate import CGateError

    inventory = edlt_label_inventory(client, network)
    group_errors = []
    connection_usable = not any(
        error.get("connection_usable") is False
        for error in inventory.get("read_errors", [])
        if isinstance(error, dict)
    )
    units = inventory.get("units", [])
    for position, unit in enumerate(units):
        address = unit["address"]
        if not connection_usable:
            group_errors.append(
                {
                    "address": address,
                    "type": "NotAttempted",
                    "error": "A prior transport failure made the connection unusable",
                }
            )
            continue
        try:
            unit["widget_groups"] = read_cached_edlt_widget_groups(client, address).as_dict()
        except CGateError as error:
            # A complete C-Gate error response leaves the tagged connection
            # synchronized, so later units remain safe to inspect.
            group_errors.append(
                {"address": address, "type": type(error).__name__, "error": str(error)[:1024]}
            )
        except RuntimeError as error:
            group_errors.append(
                {
                    "address": address,
                    "type": type(error).__name__,
                    "error": str(error)[:1024],
                    "connection_usable": False,
                }
            )
            connection_usable = False
            for remaining in units[position + 1 :]:
                group_errors.append(
                    {
                        "address": remaining["address"],
                        "type": "NotAttempted",
                        "error": "A prior transport failure made the connection unusable",
                    }
                )
            break
        except Exception as error:
            group_errors.append(
                {"address": address, "type": type(error).__name__, "error": str(error)[:1024]}
            )
    acquisition_complete = (
        inventory.get("complete") is True
        and not group_errors
        and all(isinstance(unit, dict) and "widget_groups" in unit for unit in units)
    )
    current = baseline_from_inventory(inventory) if acquisition_complete else None
    comparison = compare_baselines(expected, current, mode) if expected is not None and current is not None else None
    accepted = acquisition_complete and (comparison is None or comparison["matches"] is True)
    return {
        "format": AUDIT_FORMAT,
        "network": inventory.get("network", network),
        "mode": mode,
        "complete": acquisition_complete,
        "accepted": accepted,
        "inventory": inventory,
        "widget_groups_errors": group_errors,
        "baseline": current,
        "comparison": comparison,
        "comparison_not_run_reason": (
            "live acquisition was incomplete" if expected is not None and current is None else None
        ),
        "dynamic_labels_compared": False,
        "physical_device_modified": False,
        "physical_device_volatile_state_modified": True,
        "database_updated": False,
    }
