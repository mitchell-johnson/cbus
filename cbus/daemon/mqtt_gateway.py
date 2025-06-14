"""MQTT ↔︎ C-Bus glue layer.

Contains `CBusHandler` (sub-classing `PCIProtocol`) which feeds C-Bus events
into MQTT, and `MqttClient` which transfers MQTT commands back to C-Bus.
Separated from `cmqttd.py` so the core logic can be reused/imported without
pulling in CLI parsing or other runtime concerns.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, Optional, Text, Union

import contextlib
import ssl

from cbus.common import Application, MIN_GROUP_ADDR, MAX_GROUP_ADDR, check_ga
from cbus.daemon.topics import (
    _BINSENSOR_TOPIC_PREFIX, _LIGHT_TOPIC_PREFIX, _TOPIC_SET_SUFFIX,
    _TOPIC_CONF_SUFFIX, _TOPIC_STATE_SUFFIX, _APPLICATION_GROUP_SEPARATOR,
    ga_string, set_topic, state_topic, conf_topic,
    bin_sensor_state_topic, bin_sensor_conf_topic,
)
from cbus.protocol.application import LightingApplication
from cbus.protocol.cal.report import LevelStatusReport
from cbus.protocol.pciprotocol import PCIProtocol
from cbus.toolkit.periodic import Periodic

# asyncio-mqtt for native async MQTT operations
from aiomqtt import Client as AioMqttClient, MqttError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def ga_range():
    return range(MIN_GROUP_ADDR, MAX_GROUP_ADDR + 1)


def default_light_name(group_addr: int, app_addr: Union[int, Application]) -> str:
    return f'C-Bus Light {ga_string(group_addr, app_addr, True)}'


def get_topic_group_address(topic: str) -> tuple[int, Union[int, Application]]:
    """Extract (group_addr, app_addr) from a command topic."""
    if not topic.startswith(_LIGHT_TOPIC_PREFIX):
        raise ValueError(f'Invalid topic {topic}, must start with {_LIGHT_TOPIC_PREFIX}')
    a1, *a2 = topic[len(_LIGHT_TOPIC_PREFIX):].split('/', maxsplit=1)[0].split(_APPLICATION_GROUP_SEPARATOR)
    aa, ga = (a1, a2[0]) if a2 else (Application.LIGHTING, a1)
    aa, ga = (int(aa), int(ga))
    check_ga(ga)
    return ga, aa


# ---------------------------------------------------------------------------
# Core classes
# ---------------------------------------------------------------------------

class CBusHandler(PCIProtocol):
    """Bridge between a PCIProtocol connection and an MQTT client."""

    mqtt_api: Optional['MqttClient'] = None

    def __init__(self, labels: Optional[Dict[int, Dict]], *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.labels = labels if labels is not None else {56: {}}
        self._is_closing = False

    # --- lifecycle helpers ------------------------------------------------
    def cleanup(self):
        if self._is_closing:
            return
        self._is_closing = True
        self.mqtt_api = None
        logger.debug("CBusHandler cleaned up")

    # --- PCIProtocol hooks ------------------------------------------------
    def handle_cbus_packet(self, p):
        logger.debug(f"C-Bus packet received: {p!r}")
        super().handle_cbus_packet(p)

    def connection_lost(self, exc):
        logger.warning(f"C-Bus connection lost: {exc}")
        if self.mqtt_api:
            self.mqtt_api.groupDB.clear()
        self.cleanup()
        super().connection_lost(exc)

    def connection_made(self, transport):
        logger.info("C-Bus connection established")
        super().connection_made(transport)
        if self.mqtt_api:
            for app_addr in LightingApplication.supported_applications():
                self.mqtt_api.queue_status_requests(self, app_addr)

    # --- Event relays -----------------------------------------------------
    def on_lighting_group_ramp(self, source_addr, group_addr, app_addr, duration, level):
        if not self.mqtt_api or self._is_closing:
            return
        self.mqtt_api.lighting_group_ramp(source_addr, group_addr, app_addr, duration, level)

    def on_lighting_group_on(self, source_addr, group_addr, app_addr):
        if not self.mqtt_api or self._is_closing:
            return
        self.mqtt_api.lighting_group_on(source_addr, group_addr, app_addr)

    def on_lighting_group_off(self, source_addr, group_addr, app_addr):
        if not self.mqtt_api or self._is_closing:
            return
        self.mqtt_api.lighting_group_off(source_addr, group_addr, app_addr)

    def on_level_report(self, app_addr, start, report: LevelStatusReport):
        if not self.mqtt_api or self._is_closing:
            return
        groups = self.mqtt_api.groupDB.setdefault(app_addr, {})
        for val in report:
            if val is not None:
                was_published = start in groups
                self.mqtt_api.check_published(start, app_addr)
                if val == 0:
                    self.on_lighting_group_off(0, start, app_addr)
                elif val == 255:
                    self.on_lighting_group_on(0, start, app_addr)
                else:
                    self.on_lighting_group_ramp(0, start, app_addr, 0, val)
            start += 1

    def on_clock_request(self, source_addr):
        if not self._is_closing:
            asyncio.create_task(self.clock_datetime())


# ------------------------------------------------------------------------------------
# New asyncio-native MQTT client wrapper
# ------------------------------------------------------------------------------------


class MqttClient:
    """Async context manager that owns an *asyncio-mqtt* Client and exposes
    the helper methods that cmqttd expects (publish_light, lighting_group_on,…).
    """

    def __init__(self, userdata: CBusHandler, host: str, port: int, keepalive: int, tls_kwargs: dict | None):
        self._userdata = userdata
        self._host = host
        self._port = port
        self._keepalive = keepalive
        self._tls_kwargs = tls_kwargs or {}
        self._client: Optional[AioMqttClient] = None
        self.groupDB: Dict[int, Dict[int, bool]] = {}

    # ------------------------------------------------------------------
    async def __aenter__(self):
        self._client_cm = AioMqttClient(
            hostname=self._host,
            port=self._port,
            keepalive=self._keepalive,
            logger=logger,
            **self._tls_kwargs,
        )
        # Enter the aiomqtt context (establishes the network connection)
        self._client = await self._client_cm.__aenter__()

        logger.info("Connected to MQTT broker %s:%s", self._host, self._port)

        # Set up background message dispatcher
        self._dispatcher_task = asyncio.create_task(self._dispatcher_loop())
        logger.debug("Message dispatcher loop started")

        # Notify on MQTT client connect
        self._userdata.mqtt_api = self
        self.publish_all_lights(self._userdata.labels)
        for app_addr in LightingApplication.supported_applications():
            self.queue_status_requests(self._userdata, app_addr)

        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self._dispatcher_task:
            self._dispatcher_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._dispatcher_task
        # Cleanly close the underlying aiomqtt Client context
        if hasattr(self, "_client_cm") and self._client_cm is not None:
            await self._client_cm.__aexit__(exc_type, exc, tb)

    # ------------------------------------------------------------------
    async def _dispatcher_loop(self):
        logger.debug("Dispatcher loop starting…")
        assert self._client is not None
        try:
            result = await self._client.subscribe("homeassistant/light/#")
            logger.info("Subscribed to 'homeassistant/light/#' (result=%s)", result)

            async for msg in self._client.messages:
                logger.debug("MQTT message received on topic '%s': %s", msg.topic, msg.payload[:200])
                handled = await self._handle_message(msg)
                if not handled:
                    logger.debug("Message on topic '%s' ignored by handler", msg.topic)
        except Exception:
            logger.exception("Dispatcher loop crashed")

    async def _handle_message(self, msg):
        topic = str(msg.topic)
        if not (topic.startswith(_LIGHT_TOPIC_PREFIX) and topic.endswith(_TOPIC_SET_SUFFIX)):
            return False
        try:
            group_addr, app_addr = get_topic_group_address(topic)
        except ValueError:
            logger.error("Invalid group address in topic %s", topic)
            return False
        try:
            payload = json.loads(msg.payload)
        except json.JSONDecodeError as e:
            logger.error("JSON parse error in %s", topic, exc_info=e)
            return False
        light_on = payload['state'].upper() == 'ON'
        brightness = max(0, min(255, int(payload.get('brightness', 255))))
        transition = max(0, int(payload.get('transition', 0)))
        logger.info("Command parsed: GA=%d, App=%s, state=%s, brightness=%d, transition=%d", group_addr, app_addr, 'ON' if light_on else 'OFF', brightness, transition)
        Periodic.throttler.enqueue(lambda: asyncio.create_task(self.switchLight(self._userdata, group_addr, app_addr, light_on, brightness, transition)))
        return True

    # ------------------------------------------------------------------
    def publish(self, topic: str, payload: dict | str | bytes, qos: int = 1, retain: bool = True):
        """Schedule a publish and return the asyncio Task."""
        if isinstance(payload, dict):
            payload = json.dumps(payload)
        if isinstance(payload, str):
            payload = payload.encode()
        if self._client is None:
            raise RuntimeError("MQTT client not connected yet")
        return asyncio.create_task(self._client.publish(topic, payload, qos, retain))

    def subscribe(self, topic: str, qos: int):
        if self._client is None:
            raise RuntimeError("MQTT client not connected yet")
        return asyncio.create_task(self._client.subscribe(topic, qos))

    # Existing helper methods (queue_status_requests, publish_light, etc.) remain unchanged below

    def queue_status_requests(self, userdata: CBusHandler, app_addr):
        for block in range(0, 256, 32):
            Periodic.throttler.enqueue(lambda block=block, app_addr=app_addr: asyncio.create_task(userdata.request_status(block, app_addr)))

    async def switchLight(self, userdata: CBusHandler, group_addr, app_addr, light_on, brightness, transition):
        if light_on:
            if brightness == 255 and transition == 0:
                await userdata.lighting_group_on(group_addr, app_addr)
                self.lighting_group_on(None, group_addr, app_addr)
            else:
                await userdata.lighting_group_ramp(group_addr, app_addr, transition, brightness)
                self.lighting_group_ramp(None, group_addr, app_addr, transition, brightness)
        else:
            await userdata.lighting_group_off(group_addr, app_addr)
            self.lighting_group_off(None, group_addr, app_addr)
        return True

    def publish_light(self, group_addr: int, app_addr: Union[int, Application], app_labels: dict | None = None):
        default_name = default_light_name(group_addr, app_addr)
        uid = f'cbus_light_{ga_string(group_addr, app_addr, False)}'
        name = default_name
        if app_labels:
            _, labels = app_labels.get(app_addr, (None, {}))
            name = labels.get(group_addr, name)
        self.subscribe(set_topic(group_addr, app_addr), 2)
        self.publish(conf_topic(group_addr, app_addr), {
            'name': name,
            'unique_id': uid,
            'cmd_t': set_topic(group_addr, app_addr),
            'stat_t': state_topic(group_addr, app_addr),
            'schema': 'json',
            'brightness': True,
            'device': {
                'identifiers': [uid],
                'connections': [['cbus_group_address', str(group_addr)], ['cbus_application_address', str(app_addr)]],
                'sw_version': 'cmqttd https://github.com/mitchell-johnson/cbus',
                'name': default_name,
                'manufacturer': 'Clipsal',
                'model': 'C-Bus Lighting Application',
                'via_device': 'cmqttd',
            },
        })
        sensor_uid = f'cbus_bin_sensor_{ga_string(group_addr, app_addr, False)}'
        self.publish(bin_sensor_conf_topic(group_addr, app_addr), {
            'name': f'{name} (as binary sensor)',
            'unique_id': sensor_uid,
            'stat_t': bin_sensor_state_topic(group_addr, app_addr),
            'device': {
                'identifiers': [sensor_uid],
                'connections': [['cbus_group_address', str(group_addr)], ['cbus_application_address', str(app_addr)]],
                'sw_version': 'cmqttd https://github.com/mitchell-johnson/cbus',
                'name': default_name,
                'manufacturer': 'Clipsal',
                'model': 'C-Bus Lighting Application',
                'via_device': 'cmqttd',
            },
        })
        self.groupDB.setdefault(app_addr, {})[group_addr] = True

    def publish_all_lights(self, app_labels):
        meta_topic = 'homeassistant/binary_sensor/cbus_cmqttd'
        self.publish(meta_topic + _TOPIC_CONF_SUFFIX, {
            '~': meta_topic,
            'name': 'cmqttd',
            'unique_id': 'cmqttd',
            'stat_t': '~' + _TOPIC_STATE_SUFFIX,
            'device': {
                'identifiers': ['cmqttd'],
                'sw_version': 'cmqttd https://github.com/mitchell-johnson/cbus',
                'name': 'cmqttd',
                'manufacturer': 'micolous',
                'model': 'libcbus',
            },
        })
        for app_addr, (_, labels) in app_labels.items():
            for group_addr in labels.keys():
                self.publish_light(group_addr, app_addr, app_labels)

    def publish_binary_sensor(self, group_addr: int, app_addr: Union[int, Application], state: Optional[bool]):
        payload = 'ON' if state else 'OFF'
        return self.publish(bin_sensor_state_topic(group_addr, app_addr), payload, 1, True)

    def lighting_group_on(self, source_addr: Optional[int], group_addr: int, app_addr: Union[int, Application]):
        self.check_published(group_addr, app_addr)
        self.publish(state_topic(group_addr, app_addr), {'state': 'ON', 'brightness': 255, 'transition': 0, 'cbus_source_addr': source_addr})
        self.publish_binary_sensor(group_addr, app_addr, True)

    def lighting_group_off(self, source_addr: Optional[int], group_addr: int, app_addr: Union[int, Application]):
        self.check_published(group_addr, app_addr)
        self.publish(state_topic(group_addr, app_addr), {'state': 'OFF', 'brightness': 0, 'transition': 0, 'cbus_source_addr': source_addr})
        self.publish_binary_sensor(group_addr, app_addr, False)

    def lighting_group_ramp(self, source_addr: Optional[int], group_addr: int, app_addr: Union[int, Application], duration: int, level: int):
        self.check_published(group_addr, app_addr)
        self.publish(state_topic(group_addr, app_addr), {'state': 'ON', 'brightness': level, 'transition': duration, 'cbus_source_addr': source_addr})
        self.publish_binary_sensor(group_addr, app_addr, level > 0 if isinstance(level, int) else None)

    def check_published(self, group_addr: int, app_addr: Union[int, Application]):
        if not self.groupDB.setdefault(app_addr, {}).get(group_addr, False):
            self.publish_light(group_addr, app_addr) 