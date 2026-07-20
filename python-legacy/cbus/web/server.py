"""Web configuration interface for C-Bus ESP32 connections.

Provides a browser-based UI for:
- Configuring ESP32 WiFi/Serial connection settings
- Viewing device status and connection state
- Discovering ESP32 devices on the network
- Monitoring and controlling lighting groups
- Viewing command logs
"""
import json
import logging
from typing import Any, Dict, Optional

from aiohttp import web

logger = logging.getLogger(__name__)


class WebConfigServer:
    """Serves the web configuration interface and REST API."""

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8080,
        esp32_connection=None,
        emulator=None,
    ):
        self._host = host
        self._port = port
        self._esp32_connection = esp32_connection
        self._emulator = emulator
        self._app = web.Application()
        self._runner: Optional[web.AppRunner] = None
        self._config: Dict[str, Any] = {
            "connection_mode": "wifi",
            "wifi_host": "",
            "wifi_port": 10001,
            "serial_device": "/dev/ttyUSB0",
            "serial_baudrate": 9600,
            "reconnect": True,
            "reconnect_interval": 5,
            "max_reconnect_attempts": 0,
            "connect_timeout": 10,
            "timesync_frequency": 300,
            "handle_clock_requests": True,
            "mqtt_broker": "localhost",
            "mqtt_port": 1883,
            "mqtt_use_tls": False,
        }
        self._setup_routes()

    def _setup_routes(self):
        self._app.router.add_get("/", self._handle_index)
        self._app.router.add_get("/api/config", self._handle_get_config)
        self._app.router.add_post("/api/config", self._handle_set_config)
        self._app.router.add_get("/api/status", self._handle_get_status)
        self._app.router.add_get("/api/groups", self._handle_get_groups)
        self._app.router.add_post("/api/groups/{group_id}/level", self._handle_set_group)
        self._app.router.add_get("/api/discover", self._handle_discover)
        self._app.router.add_get("/api/logs", self._handle_get_logs)
        self._app.router.add_post("/api/connect", self._handle_connect)
        self._app.router.add_post("/api/disconnect", self._handle_disconnect)

    async def start(self):
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self._host, self._port)
        await site.start()
        logger.info("Web config server started on http://%s:%d", self._host, self._port)

    async def stop(self):
        if self._runner:
            await self._runner.cleanup()
            self._runner = None
        logger.info("Web config server stopped")

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop()

    # --- Page handler ---

    async def _handle_index(self, request: web.Request) -> web.Response:
        return web.Response(text=_INDEX_HTML, content_type="text/html")

    # --- API handlers ---

    async def _handle_get_config(self, request: web.Request) -> web.Response:
        return web.json_response(self._config)

    async def _handle_set_config(self, request: web.Request) -> web.Response:
        try:
            data = await request.json()
            for key in data:
                if key in self._config:
                    self._config[key] = data[key]
            logger.info("Config updated: %s", data)
            return web.json_response({"status": "ok", "config": self._config})
        except Exception as e:
            return web.json_response({"status": "error", "message": str(e)}, status=400)

    async def _handle_get_status(self, request: web.Request) -> web.Response:
        status = {
            "connected": False,
            "transport_type": None,
            "transport_state": "disconnected",
            "esp32_info": {},
            "connection_info": {},
            "emulator_running": False,
        }
        if self._esp32_connection:
            status["connected"] = self._esp32_connection.transport.is_connected
            status["transport_type"] = self._esp32_connection.transport.transport_type
            status["transport_state"] = self._esp32_connection.transport.state.value
            status["connection_info"] = self._esp32_connection.connection_info
            info = self._esp32_connection.esp32_info
            status["esp32_info"] = {
                "firmware_version": info.firmware_version,
                "device_type": info.device_type,
                "mac_address": info.mac_address,
                "ip_address": info.ip_address,
            }
        if self._emulator:
            status["emulator_running"] = self._emulator.is_running
            status["emulator_port"] = self._emulator.actual_port
            status["emulator_info"] = self._emulator.device_info
        return web.json_response(status)

    async def _handle_get_groups(self, request: web.Request) -> web.Response:
        groups = []
        if self._emulator:
            for g in self._emulator.groups[:256]:
                groups.append({
                    "id": g.group_id,
                    "name": g.name,
                    "level": g.level,
                    "is_on": g.is_on,
                })
        return web.json_response(groups)

    async def _handle_set_group(self, request: web.Request) -> web.Response:
        try:
            group_id = int(request.match_info["group_id"])
            if not (0 <= group_id <= 255):
                return web.json_response({"status": "error", "message": "group_id must be 0-255"}, status=400)
            data = await request.json()
            level = max(0, min(255, int(data.get("level", 0))))

            if self._emulator:
                self._emulator.set_group_level(group_id, level)

            if self._esp32_connection and self._esp32_connection.protocol:
                if level == 255:
                    await self._esp32_connection.protocol.lighting_group_on(group_id, 0x38)
                elif level == 0:
                    await self._esp32_connection.protocol.lighting_group_off(group_id, 0x38)
                else:
                    await self._esp32_connection.protocol.lighting_group_ramp(group_id, 0x38, 0, level)

            return web.json_response({"status": "ok", "group_id": group_id, "level": level})
        except Exception as e:
            return web.json_response({"status": "error", "message": str(e)}, status=400)

    async def _handle_discover(self, request: web.Request) -> web.Response:
        try:
            from cbus.esp32.discovery import ESP32Discovery
            discovery = ESP32Discovery(timeout=5.0)
            devices = await discovery.discover()
            return web.json_response([
                {"name": d.name, "host": d.host, "port": d.port, "properties": d.properties}
                for d in devices
            ])
        except Exception as e:
            return web.json_response({"status": "error", "message": str(e)}, status=500)

    async def _handle_get_logs(self, request: web.Request) -> web.Response:
        logs = []
        if self._emulator:
            for entry in self._emulator.command_log[-100:]:
                logs.append({
                    "type": entry.get("type", "unknown"),
                    "group": entry.get("group"),
                    "level": entry.get("level"),
                })
        return web.json_response(logs)

    async def _handle_connect(self, request: web.Request) -> web.Response:
        try:
            from cbus.esp32.connection import ESP32Connection, ESP32Config

            cfg = self._config
            if cfg["connection_mode"] == "wifi":
                esp32_config = ESP32Config.wifi(
                    cfg["wifi_host"],
                    port=cfg["wifi_port"],
                    reconnect=cfg["reconnect"],
                    reconnect_interval=cfg["reconnect_interval"],
                    max_reconnect_attempts=cfg["max_reconnect_attempts"],
                    connect_timeout=cfg["connect_timeout"],
                    timesync_frequency=cfg["timesync_frequency"],
                    handle_clock_requests=cfg["handle_clock_requests"],
                )
            else:
                esp32_config = ESP32Config.serial(
                    cfg["serial_device"],
                    baudrate=cfg["serial_baudrate"],
                    reconnect=cfg["reconnect"],
                    reconnect_interval=cfg["reconnect_interval"],
                    max_reconnect_attempts=cfg["max_reconnect_attempts"],
                    connect_timeout=cfg["connect_timeout"],
                    timesync_frequency=cfg["timesync_frequency"],
                    handle_clock_requests=cfg["handle_clock_requests"],
                )

            if self._esp32_connection:
                await self._esp32_connection.disconnect()

            self._esp32_connection = ESP32Connection(esp32_config)
            await self._esp32_connection.connect()
            return web.json_response({"status": "ok", "message": "Connected"})
        except Exception as e:
            return web.json_response({"status": "error", "message": str(e)}, status=500)

    async def _handle_disconnect(self, request: web.Request) -> web.Response:
        if self._esp32_connection:
            await self._esp32_connection.disconnect()
            self._esp32_connection = None
        return web.json_response({"status": "ok", "message": "Disconnected"})


_INDEX_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>C-Bus ESP32 Configuration</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
         background: #1a1a2e; color: #e0e0e0; min-height: 100vh; }
  .container { max-width: 1200px; margin: 0 auto; padding: 20px; }
  h1 { color: #00d4ff; margin-bottom: 20px; font-size: 1.8em; }
  h2 { color: #00d4ff; margin: 15px 0 10px; font-size: 1.3em; border-bottom: 1px solid #333; padding-bottom: 5px; }
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
  @media (max-width: 768px) { .grid { grid-template-columns: 1fr; } }
  .card { background: #16213e; border-radius: 8px; padding: 20px; border: 1px solid #0f3460; }
  .status-bar { display: flex; gap: 15px; margin-bottom: 20px; flex-wrap: wrap; }
  .status-badge { padding: 6px 14px; border-radius: 20px; font-size: 0.85em; font-weight: 600; }
  .badge-ok { background: #00c853; color: #000; }
  .badge-err { background: #ff1744; color: #fff; }
  .badge-warn { background: #ff9100; color: #000; }
  .badge-info { background: #2979ff; color: #fff; }
  label { display: block; margin: 10px 0 4px; font-size: 0.9em; color: #aaa; }
  input, select { width: 100%; padding: 8px 12px; border: 1px solid #0f3460; border-radius: 4px;
                  background: #0a0f1e; color: #e0e0e0; font-size: 0.95em; }
  input:focus, select:focus { outline: none; border-color: #00d4ff; }
  button { padding: 10px 20px; border: none; border-radius: 4px; cursor: pointer;
           font-size: 0.95em; font-weight: 600; transition: background 0.2s; }
  .btn-primary { background: #00d4ff; color: #000; }
  .btn-primary:hover { background: #00b8d4; }
  .btn-danger { background: #ff1744; color: #fff; }
  .btn-danger:hover { background: #d50000; }
  .btn-secondary { background: #333; color: #e0e0e0; }
  .btn-secondary:hover { background: #444; }
  .btn-group { display: flex; gap: 10px; margin-top: 15px; flex-wrap: wrap; }
  .group-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(120px, 1fr)); gap: 8px; max-height: 400px; overflow-y: auto; }
  .group-item { background: #0a0f1e; border: 1px solid #0f3460; border-radius: 4px; padding: 8px;
                text-align: center; cursor: pointer; transition: all 0.2s; }
  .group-item.on { border-color: #00d4ff; background: #162447; }
  .group-item .name { font-size: 0.75em; color: #888; margin-bottom: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .group-item .level { font-size: 1.2em; font-weight: bold; }
  .group-item.on .level { color: #00d4ff; }
  .log-list { max-height: 300px; overflow-y: auto; font-family: monospace; font-size: 0.85em; }
  .log-entry { padding: 3px 8px; border-bottom: 1px solid #0f3460; }
  .log-entry:nth-child(even) { background: #0a0f1e; }
  .inline-group { display: flex; gap: 10px; align-items: end; }
  .inline-group > div { flex: 1; }
  .checkbox-row { display: flex; align-items: center; gap: 8px; margin: 10px 0; }
  .checkbox-row input { width: auto; }
  .discovered { background: #0a0f1e; border: 1px solid #0f3460; border-radius: 4px; padding: 10px; margin: 5px 0; cursor: pointer; }
  .discovered:hover { border-color: #00d4ff; }
  #toast { position: fixed; bottom: 20px; right: 20px; padding: 12px 24px; border-radius: 4px;
           display: none; z-index: 1000; font-weight: 600; }
</style>
</head>
<body>
<div class="container">
  <h1>C-Bus ESP32 Configuration</h1>

  <div class="status-bar" id="statusBar">
    <span class="status-badge badge-err" id="connBadge">Disconnected</span>
  </div>

  <div class="grid">
    <!-- Connection Settings -->
    <div class="card">
      <h2>Connection Settings</h2>
      <label>Connection Mode</label>
      <select id="connMode" onchange="toggleMode()">
        <option value="wifi">WiFi (TCP)</option>
        <option value="serial">Serial (UART)</option>
      </select>

      <div id="wifiSettings">
        <div class="inline-group">
          <div>
            <label>Host / IP Address</label>
            <input id="wifiHost" value="" placeholder="192.168.1.x">
          </div>
          <div>
            <label>Port</label>
            <input id="wifiPort" type="number" value="10001">
          </div>
        </div>
      </div>

      <div id="serialSettings" style="display:none">
        <div class="inline-group">
          <div>
            <label>Serial Device</label>
            <input id="serialDevice" value="/dev/ttyUSB0" placeholder="/dev/ttyUSB0">
          </div>
          <div>
            <label>Baud Rate</label>
            <select id="serialBaud">
              <option value="9600" selected>9600</option>
              <option value="19200">19200</option>
              <option value="38400">38400</option>
              <option value="57600">57600</option>
              <option value="115200">115200</option>
            </select>
          </div>
        </div>
      </div>

      <h2>Advanced</h2>
      <div class="checkbox-row">
        <input type="checkbox" id="reconnect" checked>
        <label for="reconnect" style="margin:0">Auto-reconnect</label>
      </div>
      <div class="inline-group">
        <div>
          <label>Reconnect Interval (s)</label>
          <input id="reconnInterval" type="number" value="5">
        </div>
        <div>
          <label>Max Attempts (0=unlimited)</label>
          <input id="maxReconn" type="number" value="0">
        </div>
      </div>
      <div class="inline-group">
        <div>
          <label>Connect Timeout (s)</label>
          <input id="connTimeout" type="number" value="10">
        </div>
        <div>
          <label>Time Sync Frequency (s)</label>
          <input id="timesync" type="number" value="300">
        </div>
      </div>

      <div class="btn-group">
        <button class="btn-primary" onclick="saveConfig()">Save Settings</button>
        <button class="btn-primary" onclick="doConnect()">Connect</button>
        <button class="btn-danger" onclick="doDisconnect()">Disconnect</button>
      </div>
    </div>

    <!-- Device Status -->
    <div class="card">
      <h2>Device Status</h2>
      <div id="statusInfo">
        <p style="color:#666">Not connected</p>
      </div>

      <h2>Discovery</h2>
      <button class="btn-secondary" onclick="doDiscover()">Scan for ESP32 Devices</button>
      <div id="discoveredDevices" style="margin-top:10px"></div>

      <h2>Command Log</h2>
      <div class="log-list" id="logList">
        <div class="log-entry" style="color:#666">No commands yet</div>
      </div>
      <button class="btn-secondary" onclick="refreshLogs()" style="margin-top:10px">Refresh Logs</button>
    </div>
  </div>

  <!-- Groups -->
  <div class="card" style="margin-top:20px">
    <h2>Lighting Groups</h2>
    <div class="btn-group" style="margin-bottom:15px">
      <button class="btn-secondary" onclick="refreshGroups()">Refresh</button>
      <button class="btn-primary" onclick="allOn()">All On</button>
      <button class="btn-danger" onclick="allOff()">All Off</button>
    </div>
    <div class="group-grid" id="groupGrid">
      <div style="color:#666">Click Refresh to load groups</div>
    </div>
  </div>
</div>

<div id="toast"></div>

<script>
function toast(msg, type) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.style.display = 'block';
  t.style.background = type === 'error' ? '#ff1744' : '#00c853';
  t.style.color = type === 'error' ? '#fff' : '#000';
  setTimeout(() => t.style.display = 'none', 3000);
}

function toggleMode() {
  const mode = document.getElementById('connMode').value;
  document.getElementById('wifiSettings').style.display = mode === 'wifi' ? 'block' : 'none';
  document.getElementById('serialSettings').style.display = mode === 'serial' ? 'block' : 'none';
}

async function api(method, path, body) {
  const opts = { method, headers: { 'Content-Type': 'application/json' } };
  if (body) opts.body = JSON.stringify(body);
  const res = await fetch('/api/' + path, opts);
  return res.json();
}

async function loadConfig() {
  const cfg = await api('GET', 'config');
  document.getElementById('connMode').value = cfg.connection_mode || 'wifi';
  document.getElementById('wifiHost').value = cfg.wifi_host || '';
  document.getElementById('wifiPort').value = cfg.wifi_port || 10001;
  document.getElementById('serialDevice').value = cfg.serial_device || '';
  document.getElementById('serialBaud').value = cfg.serial_baudrate || 9600;
  document.getElementById('reconnect').checked = cfg.reconnect !== false;
  document.getElementById('reconnInterval').value = cfg.reconnect_interval || 5;
  document.getElementById('maxReconn').value = cfg.max_reconnect_attempts || 0;
  document.getElementById('connTimeout').value = cfg.connect_timeout || 10;
  document.getElementById('timesync').value = cfg.timesync_frequency || 300;
  toggleMode();
}

async function saveConfig() {
  const cfg = {
    connection_mode: document.getElementById('connMode').value,
    wifi_host: document.getElementById('wifiHost').value,
    wifi_port: parseInt(document.getElementById('wifiPort').value),
    serial_device: document.getElementById('serialDevice').value,
    serial_baudrate: parseInt(document.getElementById('serialBaud').value),
    reconnect: document.getElementById('reconnect').checked,
    reconnect_interval: parseInt(document.getElementById('reconnInterval').value),
    max_reconnect_attempts: parseInt(document.getElementById('maxReconn').value),
    connect_timeout: parseInt(document.getElementById('connTimeout').value),
    timesync_frequency: parseInt(document.getElementById('timesync').value),
  };
  const res = await api('POST', 'config', cfg);
  toast(res.status === 'ok' ? 'Settings saved' : res.message, res.status === 'ok' ? 'ok' : 'error');
}

async function doConnect() {
  await saveConfig();
  const res = await api('POST', 'connect');
  toast(res.status === 'ok' ? 'Connected!' : res.message, res.status === 'ok' ? 'ok' : 'error');
  refreshStatus();
}

async function doDisconnect() {
  const res = await api('POST', 'disconnect');
  toast('Disconnected', 'ok');
  refreshStatus();
}

async function refreshStatus() {
  const s = await api('GET', 'status');
  const badge = document.getElementById('connBadge');
  if (s.connected) {
    badge.textContent = 'Connected (' + s.transport_type + ')';
    badge.className = 'status-badge badge-ok';
  } else {
    badge.textContent = s.transport_state.charAt(0).toUpperCase() + s.transport_state.slice(1);
    badge.className = 'status-badge ' + (s.transport_state === 'error' ? 'badge-err' :
                       s.transport_state === 'reconnecting' ? 'badge-warn' : 'badge-err');
  }

  let html = '<table style="width:100%">';
  if (s.connected) {
    for (const [k, v] of Object.entries(s.connection_info)) {
      html += '<tr><td style="color:#888;padding:3px 8px">' + k + '</td><td style="padding:3px 8px">' + v + '</td></tr>';
    }
    if (s.esp32_info) {
      for (const [k, v] of Object.entries(s.esp32_info)) {
        if (v) html += '<tr><td style="color:#888;padding:3px 8px">' + k + '</td><td style="padding:3px 8px">' + v + '</td></tr>';
      }
    }
  }
  if (s.emulator_running) {
    html += '<tr><td style="color:#888;padding:3px 8px">Emulator</td><td style="padding:3px 8px;color:#00c853">Running on port ' + s.emulator_port + '</td></tr>';
  }
  html += '</table>';
  if (!s.connected && !s.emulator_running) html = '<p style="color:#666">Not connected</p>';
  document.getElementById('statusInfo').innerHTML = html;
}

async function doDiscover() {
  document.getElementById('discoveredDevices').innerHTML = '<p style="color:#888">Scanning...</p>';
  const devices = await api('GET', 'discover');
  if (devices.length === 0) {
    document.getElementById('discoveredDevices').innerHTML = '<p style="color:#666">No devices found</p>';
    return;
  }
  let html = '';
  for (const d of devices) {
    html += '<div class="discovered" onclick="selectDevice(\\'' + d.host + '\\',' + d.port + ')">';
    html += '<strong>' + d.name + '</strong><br><span style="color:#888">' + d.host + ':' + d.port + '</span>';
    if (d.properties && d.properties.firmware) html += '<br><span style="color:#666">FW: ' + d.properties.firmware + '</span>';
    html += '</div>';
  }
  document.getElementById('discoveredDevices').innerHTML = html;
}

function selectDevice(host, port) {
  document.getElementById('connMode').value = 'wifi';
  document.getElementById('wifiHost').value = host;
  document.getElementById('wifiPort').value = port;
  toggleMode();
  toast('Device selected: ' + host + ':' + port, 'ok');
}

async function refreshGroups() {
  const groups = await api('GET', 'groups');
  if (groups.length === 0) {
    document.getElementById('groupGrid').innerHTML = '<div style="color:#666">No groups available</div>';
    return;
  }
  let html = '';
  for (const g of groups) {
    const cls = g.is_on ? 'group-item on' : 'group-item';
    html += '<div class="' + cls + '" onclick="toggleGroup(' + g.id + ',' + (g.is_on ? 0 : 255) + ')">';
    html += '<div class="name">' + g.name + '</div>';
    html += '<div class="level">' + g.level + '</div>';
    html += '</div>';
  }
  document.getElementById('groupGrid').innerHTML = html;
}

async function toggleGroup(id, level) {
  await api('POST', 'groups/' + id + '/level', { level });
  setTimeout(refreshGroups, 200);
}

async function allOn() {
  for (let i = 0; i < 256; i++) await api('POST', 'groups/' + i + '/level', { level: 255 });
  refreshGroups();
}

async function allOff() {
  for (let i = 0; i < 256; i++) await api('POST', 'groups/' + i + '/level', { level: 0 });
  refreshGroups();
}

async function refreshLogs() {
  const logs = await api('GET', 'logs');
  if (logs.length === 0) {
    document.getElementById('logList').innerHTML = '<div class="log-entry" style="color:#666">No commands yet</div>';
    return;
  }
  let html = '';
  for (const l of logs.reverse()) {
    let detail = l.type;
    if (l.group !== undefined && l.group !== null) detail += ' G' + l.group;
    if (l.level !== undefined && l.level !== null) detail += ' L' + l.level;
    html += '<div class="log-entry">' + detail + '</div>';
  }
  document.getElementById('logList').innerHTML = html;
}

// Auto-refresh status every 3 seconds
loadConfig();
refreshStatus();
setInterval(refreshStatus, 3000);
</script>
</body>
</html>
"""
