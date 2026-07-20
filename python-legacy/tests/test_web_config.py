"""Tests for the web configuration interface."""
import pytest
import pytest_asyncio
import asyncio
import json

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, TestClient, TestServer

from cbus.web.server import WebConfigServer
from cbus.esp32.emulator.device import ESP32Emulator, ESP32EmulatorConfig


@pytest_asyncio.fixture
async def emulator():
    config = ESP32EmulatorConfig(tcp_port=0, response_delay_ms=1.0)
    emu = ESP32Emulator(config)
    await emu.start()
    yield emu
    await emu.stop()


@pytest_asyncio.fixture
async def web_server(emulator):
    server = WebConfigServer(host="127.0.0.1", port=0, emulator=emulator)
    # Use aiohttp test client instead of starting a real server
    yield server, emulator


class TestWebConfigAPI:
    @pytest.mark.asyncio
    async def test_get_config(self, web_server):
        server, emu = web_server
        client = TestClient(TestServer(server._app))
        await client.start_server()
        try:
            resp = await client.get("/api/config")
            assert resp.status == 200
            data = await resp.json()
            assert "connection_mode" in data
            assert "wifi_host" in data
            assert "wifi_port" in data
            assert "serial_device" in data
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_set_config(self, web_server):
        server, emu = web_server
        client = TestClient(TestServer(server._app))
        await client.start_server()
        try:
            resp = await client.post(
                "/api/config",
                json={"wifi_host": "10.0.0.1", "wifi_port": 9999},
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["status"] == "ok"
            assert data["config"]["wifi_host"] == "10.0.0.1"
            assert data["config"]["wifi_port"] == 9999
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_get_status(self, web_server):
        server, emu = web_server
        client = TestClient(TestServer(server._app))
        await client.start_server()
        try:
            resp = await client.get("/api/status")
            assert resp.status == 200
            data = await resp.json()
            assert "connected" in data
            assert "emulator_running" in data
            assert data["emulator_running"] is True
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_get_groups(self, web_server):
        server, emu = web_server
        emu.set_group_level(0, 128)
        emu.set_group_level(1, 255)
        client = TestClient(TestServer(server._app))
        await client.start_server()
        try:
            resp = await client.get("/api/groups")
            assert resp.status == 200
            data = await resp.json()
            assert len(data) == 256
            assert data[0]["level"] == 128
            assert data[1]["level"] == 255
            assert data[1]["is_on"] is True
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_set_group_level(self, web_server):
        server, emu = web_server
        client = TestClient(TestServer(server._app))
        await client.start_server()
        try:
            resp = await client.post(
                "/api/groups/5/level",
                json={"level": 200},
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["status"] == "ok"
            assert data["group_id"] == 5
            assert emu.get_group_level(5) == 200
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_get_logs(self, web_server):
        server, emu = web_server
        client = TestClient(TestServer(server._app))
        await client.start_server()
        try:
            resp = await client.get("/api/logs")
            assert resp.status == 200
            data = await resp.json()
            assert isinstance(data, list)
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_index_page(self, web_server):
        server, emu = web_server
        client = TestClient(TestServer(server._app))
        await client.start_server()
        try:
            resp = await client.get("/")
            assert resp.status == 200
            text = await resp.text()
            assert "C-Bus ESP32 Configuration" in text
            assert "Connection Settings" in text
            assert "Lighting Groups" in text
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_disconnect_api(self, web_server):
        server, emu = web_server
        client = TestClient(TestServer(server._app))
        await client.start_server()
        try:
            resp = await client.post("/api/disconnect")
            assert resp.status == 200
            data = await resp.json()
            assert data["status"] == "ok"
        finally:
            await client.close()
