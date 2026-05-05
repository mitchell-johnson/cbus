"""Tests for ESP32 Home Assistant MQTT discovery with canonical IDs."""
import json
import pytest
from pathlib import Path

from cbus.esp32.ha_discovery import (
    GroupConfig,
    load_group_labels,
    build_light_discovery,
    build_binary_sensor_discovery,
    generate_all_discovery,
    generate_removal_topics,
    DEFAULT_LIGHTING_APP,
)


class TestGroupConfig:
    def test_topic_id_default_app(self):
        g = GroupConfig(group_addr=15, app_addr=56, label="bathroom fan")
        assert g.topic_id == "cbus_15"

    def test_topic_id_non_default_app(self):
        g = GroupConfig(group_addr=0, app_addr=202, label="Trigger Group 1")
        assert g.topic_id == "cbus_202_000"

    def test_unique_id_default_app(self):
        """unique_id must match old cmqttd format: cbus_light_<ga>"""
        g = GroupConfig(group_addr=15, app_addr=56, label="bathroom fan")
        assert g.unique_id == "cbus_light_15"

    def test_unique_id_non_default_app(self):
        g = GroupConfig(group_addr=0, app_addr=202, label="Trigger Group 1")
        assert g.unique_id == "cbus_light_202_000"

    def test_sensor_unique_id_default_app(self):
        g = GroupConfig(group_addr=27, app_addr=56, label="kitchen downlights")
        assert g.sensor_unique_id == "cbus_bin_sensor_27"

    def test_sensor_unique_id_non_default_app(self):
        g = GroupConfig(group_addr=0, app_addr=202, label="Trigger Group 1")
        assert g.sensor_unique_id == "cbus_bin_sensor_202_000"


class TestLoadGroupLabels:
    def test_load_config_file(self):
        config_path = Path(__file__).parent.parent / "config" / "cbus-group-labels.json"
        groups = load_group_labels(config_path)
        assert len(groups) == 44  # 43 lighting + 1 trigger

        # Check specific canonical entries
        lighting_groups = [g for g in groups if g.app_addr == 56]
        assert len(lighting_groups) == 43

        # Check bathroom fan at GA 15
        ga15 = next(g for g in lighting_groups if g.group_addr == 15)
        assert ga15.label == "bathroom fan"
        assert ga15.unique_id == "cbus_light_15"

        # Check kitchen downlights at GA 27
        ga27 = next(g for g in lighting_groups if g.group_addr == 27)
        assert ga27.label == "kitchen downlights"
        assert ga27.unique_id == "cbus_light_27"

        # Check trigger group
        trigger_groups = [g for g in groups if g.app_addr == 202]
        assert len(trigger_groups) == 1
        assert trigger_groups[0].label == "Trigger Group 1"


class TestBuildLightDiscovery:
    def test_canonical_unique_id(self):
        """Discovery payload must use cbus_light_<ga> not cbus_<ga>_light."""
        g = GroupConfig(group_addr=15, app_addr=56, label="bathroom fan")
        topic, payload = build_light_discovery(g)
        assert payload["unique_id"] == "cbus_light_15"
        # Must NOT be the old broken format
        assert payload["unique_id"] != "cbus_15_light"

    def test_uses_label_as_name(self):
        """Discovery name must be the configured label, not 'C-Bus Light 015'."""
        g = GroupConfig(group_addr=15, app_addr=56, label="bathroom fan")
        topic, payload = build_light_discovery(g)
        assert payload["name"] == "bathroom fan"
        assert payload["name"] != "C-Bus Light 015"

    def test_preserves_esp32_command_topics(self):
        """Command/state topics must match ESP32 firmware format."""
        g = GroupConfig(group_addr=15, app_addr=56, label="bathroom fan")
        topic, payload = build_light_discovery(g)
        assert payload["cmd_t"] == "homeassistant/light/cbus_15/set"
        assert payload["stat_t"] == "homeassistant/light/cbus_15/state"

    def test_config_topic(self):
        g = GroupConfig(group_addr=27, app_addr=56, label="kitchen downlights")
        topic, payload = build_light_discovery(g)
        assert topic == "homeassistant/light/cbus_27/config"

    def test_device_identifiers_use_canonical_id(self):
        g = GroupConfig(group_addr=0, app_addr=56, label="outside wall light")
        topic, payload = build_light_discovery(g)
        assert payload["device"]["identifiers"] == ["cbus_light_0"]

    def test_brightness_and_schema(self):
        g = GroupConfig(group_addr=0, app_addr=56, label="test")
        _, payload = build_light_discovery(g)
        assert payload["schema"] == "json"
        assert payload["brightness"] is True

    def test_non_default_app_topics(self):
        g = GroupConfig(group_addr=0, app_addr=202, label="Trigger Group 1")
        topic, payload = build_light_discovery(g)
        assert topic == "homeassistant/light/cbus_202_000/config"
        assert payload["cmd_t"] == "homeassistant/light/cbus_202_000/set"
        assert payload["unique_id"] == "cbus_light_202_000"


class TestBuildBinarySensorDiscovery:
    def test_sensor_canonical_id(self):
        g = GroupConfig(group_addr=15, app_addr=56, label="bathroom fan")
        topic, payload = build_binary_sensor_discovery(g)
        assert payload["unique_id"] == "cbus_bin_sensor_15"

    def test_sensor_name_includes_label(self):
        g = GroupConfig(group_addr=15, app_addr=56, label="bathroom fan")
        _, payload = build_binary_sensor_discovery(g)
        assert payload["name"] == "bathroom fan (as binary sensor)"

    def test_sensor_config_topic(self):
        g = GroupConfig(group_addr=15, app_addr=56, label="bathroom fan")
        topic, _ = build_binary_sensor_discovery(g)
        assert topic == "homeassistant/binary_sensor/cbus_15/config"


class TestGenerateAllDiscovery:
    def test_produces_light_and_sensor_per_group(self):
        groups = [
            GroupConfig(group_addr=15, app_addr=56, label="bathroom fan"),
            GroupConfig(group_addr=27, app_addr=56, label="kitchen downlights"),
        ]
        results = generate_all_discovery(groups)
        # 2 groups x 2 entities (light + binary sensor) = 4
        assert len(results) == 4

        topics = [t for t, _ in results]
        assert "homeassistant/light/cbus_15/config" in topics
        assert "homeassistant/binary_sensor/cbus_15/config" in topics
        assert "homeassistant/light/cbus_27/config" in topics
        assert "homeassistant/binary_sensor/cbus_27/config" in topics

    def test_payloads_are_valid_json(self):
        groups = [GroupConfig(group_addr=0, app_addr=56, label="test light")]
        results = generate_all_discovery(groups)
        for _, payload_json in results:
            parsed = json.loads(payload_json)
            assert "unique_id" in parsed

    def test_no_generic_groups_in_output(self):
        """Only configured groups appear - no generic 'C-Bus Light 043' etc."""
        config_path = Path(__file__).parent.parent / "config" / "cbus-group-labels.json"
        groups = load_group_labels(config_path)
        results = generate_all_discovery(groups)

        for _, payload_json in results:
            parsed = json.loads(payload_json)
            name = parsed["name"]
            # Should never have generic firmware-style names
            assert not name.startswith("C-Bus Light 0"), f"Generic name found: {name}"
            assert not name.startswith("C-Bus Light 1"), f"Generic name found: {name}"


class TestGenerateRemovalTopics:
    def test_removes_unconfigured_groups(self):
        """Groups not in config should get empty-payload removal topics."""
        groups = [
            GroupConfig(group_addr=0, app_addr=56, label="test"),
            GroupConfig(group_addr=15, app_addr=56, label="test2"),
        ]
        removals = generate_removal_topics(groups, max_group=20)
        # 20 groups total - 2 configured = 18 to remove, each has light + sensor
        assert len(removals) == 36

        # Configured groups must NOT be in removal list
        assert "homeassistant/light/cbus_0/config" not in removals
        assert "homeassistant/light/cbus_15/config" not in removals

        # Unconfigured groups MUST be in removal list
        assert "homeassistant/light/cbus_1/config" in removals
        assert "homeassistant/binary_sensor/cbus_1/config" in removals
        assert "homeassistant/light/cbus_43/config" not in removals  # > max_group

    def test_no_discovery_spam_for_43_through_255(self):
        """The full config should mark groups 43-255 for removal."""
        config_path = Path(__file__).parent.parent / "config" / "cbus-group-labels.json"
        groups = load_group_labels(config_path)
        removals = generate_removal_topics(groups)

        # Groups 43-254 should all be removed (255 not in default lighting app config)
        for ga in range(43, 255):
            assert f"homeassistant/light/cbus_{ga}/config" in removals
            assert f"homeassistant/binary_sensor/cbus_{ga}/config" in removals

    def test_configured_groups_not_removed(self):
        config_path = Path(__file__).parent.parent / "config" / "cbus-group-labels.json"
        groups = load_group_labels(config_path)
        removals = generate_removal_topics(groups)

        # All 43 lighting groups (0-42) must NOT be in removal list
        for ga in range(43):
            assert f"homeassistant/light/cbus_{ga}/config" not in removals
