"""Home Assistant MQTT discovery for ESP32 C-Bus bridge.

Publishes canonical HA discovery configs for configured C-Bus groups only,
using stable unique_id format (cbus_light_<ga>) matching the old cmqttd
convention. This prevents HomeKit duplicates caused by the firmware's generic
discovery of all 256 groups.

Designed to be run as an override layer: publishes retained discovery configs
that replace the firmware's generic ones, and clears discovery for unconfigured
groups.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from cbus.common import Application

logger = logging.getLogger(__name__)

DEFAULT_LIGHTING_APP = int(Application.LIGHTING)  # 0x38 = 56

# Matches firmware topic structure: homeassistant/light/cbus_<ga>/...
_LIGHT_TOPIC_PREFIX = "homeassistant/light/cbus_"
_BINSENSOR_TOPIC_PREFIX = "homeassistant/binary_sensor/cbus_"


@dataclass
class GroupConfig:
    """A configured C-Bus group with its canonical label."""
    group_addr: int
    app_addr: int
    label: str

    @property
    def topic_id(self) -> str:
        """Topic segment matching firmware/cmqttd topic IDs."""
        if self.app_addr == DEFAULT_LIGHTING_APP:
            return f"cbus_{self.group_addr}"
        return f"cbus_{self.app_addr}_{self.group_addr:03d}"

    @property
    def unique_id(self) -> str:
        """Canonical unique_id matching old cmqttd format: cbus_light_<suffix>."""
        if self.app_addr == DEFAULT_LIGHTING_APP:
            return f"cbus_light_{self.group_addr}"
        return f"cbus_light_{self.app_addr}_{self.group_addr:03d}"

    @property
    def sensor_unique_id(self) -> str:
        if self.app_addr == DEFAULT_LIGHTING_APP:
            return f"cbus_bin_sensor_{self.group_addr}"
        return f"cbus_bin_sensor_{self.app_addr}_{self.group_addr:03d}"


def load_group_labels(config_path: str | Path) -> List[GroupConfig]:
    """Load group labels from a JSON config file.

    Expected format:
    {
        "<section_name>": {
            "application_address": <int>,
            "groups": { "<group_addr>": "<label>", ... }
        },
        ...
    }
    """
    config_path = Path(config_path)
    with open(config_path) as f:
        data = json.load(f)

    groups = []
    for section in data.values():
        app_addr = section["application_address"]
        for ga_str, label in section["groups"].items():
            groups.append(GroupConfig(
                group_addr=int(ga_str),
                app_addr=app_addr,
                label=label,
            ))
    return groups


def build_light_discovery(group: GroupConfig) -> Tuple[str, dict]:
    """Build HA MQTT discovery payload for a light entity.

    Returns (topic, payload) tuple. Payload uses the canonical unique_id
    format and proper label name, with command/state topics matching the
    ESP32 firmware's topic structure.
    """
    topic_id = group.topic_id.removeprefix("cbus_")
    cmd_t = f"{_LIGHT_TOPIC_PREFIX}{topic_id}/set"
    stat_t = f"{_LIGHT_TOPIC_PREFIX}{topic_id}/state"
    conf_t = f"{_LIGHT_TOPIC_PREFIX}{topic_id}/config"

    payload = {
        "name": group.label,
        "unique_id": group.unique_id,
        "cmd_t": cmd_t,
        "stat_t": stat_t,
        "schema": "json",
        "brightness": True,
        "device": {
            "identifiers": [group.unique_id],
            "connections": [
                ["cbus_group_address", str(group.group_addr)],
                ["cbus_application_address", str(group.app_addr)],
            ],
            "sw_version": "cbus-esp32 https://github.com/mitchell-johnson/cbus",
            "name": f"C-Bus Light {group.group_addr:03d}" if group.app_addr == DEFAULT_LIGHTING_APP else f"C-Bus Light {group.app_addr}_{group.group_addr:03d}",
            "manufacturer": "Clipsal",
            "model": "C-Bus Lighting Application",
            "via_device": "cmqttd",
        },
    }
    return conf_t, payload


def build_binary_sensor_discovery(group: GroupConfig) -> Tuple[str, dict]:
    """Build HA MQTT discovery payload for a binary sensor entity."""
    topic_id = group.topic_id.removeprefix("cbus_")
    stat_t = f"{_BINSENSOR_TOPIC_PREFIX}{topic_id}/state"
    conf_t = f"{_BINSENSOR_TOPIC_PREFIX}{topic_id}/config"

    dev_name = f"C-Bus Light {group.group_addr:03d}" if group.app_addr == DEFAULT_LIGHTING_APP else f"C-Bus Light {group.app_addr}_{group.group_addr:03d}"

    payload = {
        "name": f"{group.label} (as binary sensor)",
        "unique_id": group.sensor_unique_id,
        "stat_t": stat_t,
        "device": {
            "identifiers": [group.sensor_unique_id],
            "sw_version": "cbus-esp32",
            "name": dev_name,
            "manufacturer": "Clipsal",
            "model": "C-Bus Lighting Application",
            "via_device": "cmqttd",
        },
    }
    return conf_t, payload


def generate_all_discovery(groups: List[GroupConfig]) -> List[Tuple[str, str]]:
    """Generate all discovery (topic, json_payload) pairs for configured groups.

    Returns list of (topic, json_string) tuples ready to be published as
    retained MQTT messages.
    """
    results = []
    for group in groups:
        topic, payload = build_light_discovery(group)
        results.append((topic, json.dumps(payload)))

        topic, payload = build_binary_sensor_discovery(group)
        results.append((topic, json.dumps(payload)))

    return results


def generate_removal_topics(groups: List[GroupConfig], max_group: int = 256) -> List[str]:
    """Generate MQTT topics that should be cleared (empty retained payload).

    For the default lighting app, generates clear topics for all group
    addresses 0..max_group-1 that are NOT in the configured groups list.
    This removes the firmware's generic discovery spam.
    """
    configured_gas = {g.group_addr for g in groups if g.app_addr == DEFAULT_LIGHTING_APP}
    removal_topics = []
    for ga in range(max_group):
        if ga not in configured_gas:
            removal_topics.append(f"{_LIGHT_TOPIC_PREFIX}{ga}/config")
            removal_topics.append(f"{_BINSENSOR_TOPIC_PREFIX}{ga}/config")
    return removal_topics
