import pytest
import asyncio

from cbus.esp32.emulator.device import (
    ESP32Emulator,
    ESP32EmulatorConfig,
    EmulatedGroup,
)


class TestESP32EmulatorConfig:
    def test_default_config(self):
        config = ESP32EmulatorConfig()
        assert config.tcp_port == 10001
        assert config.firmware_version == "1.0.0"
        assert config.device_type == "ESP32-WROOM-EMULATED"
        assert config.network_id == 254
        assert config.num_groups == 256
        assert config.enable_mdns is False

    def test_custom_config(self):
        config = ESP32EmulatorConfig(tcp_port=9999, firmware_version="2.0.0")
        assert config.tcp_port == 9999
        assert config.firmware_version == "2.0.0"


class TestEmulatedGroup:
    def test_default_state(self):
        group = EmulatedGroup(group_id=1, name="Living Room")
        assert group.group_id == 1
        assert group.name == "Living Room"
        assert group.level == 0
        assert group.is_on is False

    def test_set_level(self):
        group = EmulatedGroup(group_id=1)
        group.level = 255
        assert group.is_on is True
        group.level = 0
        assert group.is_on is False

    def test_level_clamped(self):
        group = EmulatedGroup(group_id=1)
        group.level = 300
        assert group.level == 255
        group.level = -10
        assert group.level == 0


class TestESP32Emulator:
    @pytest.fixture
    def config(self):
        return ESP32EmulatorConfig(tcp_port=0)

    @pytest.fixture
    def emulator(self, config):
        return ESP32Emulator(config)

    def test_emulator_creation(self, emulator):
        assert emulator.is_running is False

    def test_initial_groups(self, emulator):
        assert len(emulator.groups) == 256
        assert emulator.groups[0].level == 0

    def test_get_group_level(self, emulator):
        assert emulator.get_group_level(1) == 0

    def test_set_group_level(self, emulator):
        emulator.set_group_level(1, 128)
        assert emulator.get_group_level(1) == 128

    def test_firmware_info(self, emulator):
        info = emulator.device_info
        assert info["firmware_version"] == "1.0.0"
        assert info["device_type"] == "ESP32-WROOM-EMULATED"

    @pytest.mark.asyncio
    async def test_start_stop(self, emulator):
        await emulator.start()
        assert emulator.is_running is True
        assert emulator.actual_port > 0
        await emulator.stop()
        assert emulator.is_running is False

    @pytest.mark.asyncio
    async def test_context_manager(self, emulator):
        async with emulator:
            assert emulator.is_running is True
        assert emulator.is_running is False
