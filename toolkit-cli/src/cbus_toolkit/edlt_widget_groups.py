"""Read the physical KEYGL5 WidgetGroups mapping cached by cmqttd.

The embedded C-Gate service populates this property during ``NET SYNC``.
This client deliberately uses that shared service instead of opening a second
PCI/CNI connection or interpreting the opaque 44-byte mapping.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


_UNIT_PATH = re.compile(r"//([A-Za-z0-9_]{1,8})/([0-9]{1,3})/p/([0-9]{1,3})")
_DECIMAL_BYTE = re.compile(r"0|[1-9][0-9]*")
_VALUE_COUNT = 44


def unit_path(value: str) -> str:
    """Validate and canonicalize one fully qualified physical unit path."""
    match = _UNIT_PATH.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        raise ValueError(
            "Use a fully qualified //PROJECT/NETWORK/p/UNIT address"
        )
    network, unit = int(match[2]), int(match[3])
    if network > 255 or unit > 255:
        raise ValueError("C-Bus network and unit addresses must be in 0..255")
    return f"//{match[1]}/{network}/p/{unit}"


def _response(response, operation: str):
    """Return a bounded C-Gate envelope after checking its internal shape."""
    status = getattr(response, "status", None)
    lines = getattr(response, "lines", None)
    final = getattr(response, "final", None)
    if (
        type(status) is not int
        or type(lines) is not tuple
        or not lines
        or any(type(line) is not str for line in lines)
        or final != lines[-1]
    ):
        raise ValueError(f"Malformed C-Gate {operation} response envelope")
    return status, lines


def _require_sync(response) -> None:
    status, lines = _response(response, "NET SYNC")
    if status != 200 or re.fullmatch(r"200 .+", lines[-1]) is None:
        raise RuntimeError("Physical NET SYNC did not complete successfully")
    if any(re.fullmatch(r"1[0-9]{2}-.+", line) is None for line in lines[:-1]):
        raise ValueError("Unexpected C-Gate NET SYNC response envelope")


def _parse_values(response, address: str) -> tuple[int, ...]:
    status, lines = _response(response, "WidgetGroups")
    prefix = f"300 {address}: WidgetGroups="
    if status != 300 or len(lines) != 1 or not lines[0].startswith(prefix):
        raise ValueError("Unexpected C-Gate WidgetGroups response envelope")
    payload = lines[0][len(prefix):]
    tokens = payload.split(",")
    if len(tokens) != _VALUE_COUNT:
        raise ValueError("WidgetGroups must contain exactly 44 decimal bytes")
    if any(_DECIMAL_BYTE.fullmatch(token) is None for token in tokens):
        raise ValueError("WidgetGroups contains a malformed unsigned decimal byte")
    if any(len(token) > 3 for token in tokens):
        raise ValueError("WidgetGroups byte is outside 0..255")
    values = tuple(int(token) for token in tokens)
    if any(value > 255 for value in values):
        raise ValueError("WidgetGroups byte is outside 0..255")
    return values


@dataclass(frozen=True)
class EdltWidgetGroups:
    """One opaque mapping and the exact synchronized-cache read evidence."""

    address: str
    network: str
    values: tuple[int, ...]
    sync_command: str
    get_command: str

    def as_dict(self) -> dict[str, object]:
        return {
            "format": "cbus-edlt-widget-groups-v1",
            "complete": True,
            "address": self.address,
            "network": self.network,
            "widget_groups": list(self.values),
            "byte_count": len(self.values),
            "native_decimal_csv": ",".join(map(str, self.values)),
            "opaque": True,
            "source": "physical-synchronized-cache",
            "network_sync": {
                "command": self.sync_command,
                "status": 200,
                "completed": True,
                "scope": "entire-network",
                "persistent_configuration_read_only": True,
                "volatile_oem_selector_write": True,
            },
            "property_read": {
                "command": self.get_command,
                "status": 300,
                "property": "WidgetGroups",
            },
            "widget_groups_device_readback": True,
            "dynamic_label_cache_readback": False,
            "rendering_verified": False,
            "persistence_verified": False,
            "network_snapshot_atomic": False,
            "physical_observations_sequential": True,
            "database_updated": False,
            "persistent_device_configuration_modified": False,
            "physical_device_volatile_state_modified": True,
        }


def read_edlt_widget_groups(client, address: str) -> EdltWidgetGroups:
    """Synchronize one network and consume its exact cached unit property."""
    address = unit_path(address)
    network = address.rsplit("/p/", 1)[0]
    sync_command = f"NET SYNC {network}"
    get_command = f"GET {address} WidgetGroups"
    _require_sync(client.command(sync_command))
    values = _parse_values(client.command(get_command), address)
    return EdltWidgetGroups(address, network, values, sync_command, get_command)
