# cbus/daemon/topics.py
"""Topic and address helpers for cmqttd and related modules.

This module centralises MQTT topic conventions and C-Bus group/application
address helper functions so that they can be shared by the daemon, tests and
any future tooling.
"""
from __future__ import annotations

from typing import Text, Union

from cbus.common import Application, MIN_GROUP_ADDR, MAX_GROUP_ADDR, check_ga

# Topic fragments
_BINSENSOR_TOPIC_PREFIX = 'homeassistant/binary_sensor/cbus_'
_LIGHT_TOPIC_PREFIX = 'homeassistant/light/cbus_'
_TOPIC_SET_SUFFIX = '/set'
_TOPIC_CONF_SUFFIX = '/config'
_TOPIC_STATE_SUFFIX = '/state'

# Separator between application-address and group-address when non-default app
_APPLICATION_GROUP_SEPARATOR = "_"

__all__ = [
    '_BINSENSOR_TOPIC_PREFIX', '_LIGHT_TOPIC_PREFIX', '_TOPIC_SET_SUFFIX',
    '_TOPIC_CONF_SUFFIX', '_TOPIC_STATE_SUFFIX', '_APPLICATION_GROUP_SEPARATOR',
    'ga_string', 'set_topic', 'state_topic', 'conf_topic',
    'bin_sensor_state_topic', 'bin_sensor_conf_topic',
]


def ga_string(group_addr: int, app_addr: Union[int, Application], zeros: bool = True) -> Text:
    """Return the textual representation of a C-Bus (application, group) pair.

    For the default lighting application (Application.LIGHTING == 0x38) we keep
    the historic 3-digit format (e.g. "001"). For other apps we prepend the
    application address and a separator: "056_001".
    """
    if app_addr == Application.LIGHTING:
        return f"{group_addr:03d}" if zeros else f"{group_addr}"
    else:
        return f"{int(app_addr):03d}{_APPLICATION_GROUP_SEPARATOR}{group_addr:03d}"


# MQTT topic helpers ---------------------------------------------------------

def set_topic(group_addr: int, app_addr: Union[int, Application]) -> Text:
    """MQTT topic that receives commands for a (app, group)."""
    return _LIGHT_TOPIC_PREFIX + ga_string(group_addr, app_addr, False) + _TOPIC_SET_SUFFIX


def state_topic(group_addr: int, app_addr: Union[int, Application]) -> Text:
    """MQTT topic where we publish the current state for a (app, group)."""
    return _LIGHT_TOPIC_PREFIX + ga_string(group_addr, app_addr, False) + _TOPIC_STATE_SUFFIX


def conf_topic(group_addr: int, app_addr: Union[int, Application]) -> Text:
    """MQTT discovery config topic for a (app, group)."""
    return _LIGHT_TOPIC_PREFIX + ga_string(group_addr, app_addr, False) + _TOPIC_CONF_SUFFIX


def bin_sensor_state_topic(group_addr: int, app_addr: Union[int, Application]) -> Text:
    return _BINSENSOR_TOPIC_PREFIX + ga_string(group_addr, app_addr, False) + _TOPIC_STATE_SUFFIX


def bin_sensor_conf_topic(group_addr: int, app_addr: Union[int, Application]) -> Text:
    return _BINSENSOR_TOPIC_PREFIX + ga_string(group_addr, app_addr, False) + _TOPIC_CONF_SUFFIX 