#!/usr/bin/env python3
# cmqttd.py - MQTT connector for C-Bus
# Copyright 2019-2020 Michael Farrell <micolous+git@gmail.com>
#
# This library is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with this library.  If not, see <http://www.gnu.org/licenses/>.

# Import the full asyncio module instead of just specific functions
import asyncio
from argparse import FileType
import json
import logging
from marshal import load
from typing import Any, BinaryIO, Dict, Optional, Text, TextIO, List, Union

import sys
import ssl

# platform-specific event loop policy for Windows
if sys.platform == 'win32':
    from asyncio import set_event_loop_policy, WindowsSelectorEventLoopPolicy
    set_event_loop_policy(WindowsSelectorEventLoopPolicy())

# CLI helper
from cbus.daemon.cli import parse_cli_args

from cbus.protocol import application
from cbus.logging_config import configure_logging

# Topic helpers centralised in topics.py
from cbus.daemon.topics import (
    _BINSENSOR_TOPIC_PREFIX, _LIGHT_TOPIC_PREFIX, _TOPIC_SET_SUFFIX,
    _TOPIC_CONF_SUFFIX, _TOPIC_STATE_SUFFIX, _APPLICATION_GROUP_SEPARATOR,
    ga_string, set_topic, state_topic, conf_topic,
    bin_sensor_state_topic, bin_sensor_conf_topic,
)
from cbus.common import MIN_GROUP_ADDR, MAX_GROUP_ADDR, check_ga, Application
from cbus.protocol.pciprotocol import PCIProtocol
from cbus.toolkit.cbz import CBZ
from cbus.toolkit.periodic import Periodic
from cbus.protocol.application import LightingApplication
from cbus.protocol.cal.report import LevelStatusReport,BinaryStatusReport

# using new MQTT gateway classes
from cbus.daemon.mqtt_gateway import CBusHandler, MqttClient

# Logging will be configured later in _main after CLI options are parsed

_META_TOPIC = 'homeassistant/binary_sensor/cbus_cmqttd'

logger = logging.getLogger(__name__)

def check_aa_lighting(app):
    if not app in LightingApplication.supported_applications():
        raise ValueError(
            'Application ${aa} is not a valid lighting application'.format(
                app))

def ga_range():
    return range(MIN_GROUP_ADDR, MAX_GROUP_ADDR + 1)

def default_light_name(group_addr,app_addr):
     return f'C-Bus Light {ga_string(group_addr,app_addr,True)}'

def get_topic_group_address(topic: Text) -> tuple[int,int | Application]:
    """Gets the group address for the given topic."""
    if not topic.startswith(_LIGHT_TOPIC_PREFIX):
        raise ValueError(
            f'Invalid topic {topic}, must start with {_LIGHT_TOPIC_PREFIX}')
    a1,*a2 = topic[len(_LIGHT_TOPIC_PREFIX):].split('/', maxsplit=1)[0].split(_APPLICATION_GROUP_SEPARATOR)
    aa,ga = (a1,a2[0]) if a2 else (Application.LIGHTING,a1)
    aa,ga = (int(aa),int(ga))
    check_ga(ga)
    
    return ga,aa

def read_cbz_labels(project_fh: FileType, cbus_network_name: Union[str, List[str], None]):
    """Parse a Toolkit CBZ/XML backup and return labels suitable for CBusHandler.

    Args:
        project_fh: Binary file-handle pointing at the CBZ/XML.
        cbus_network_name: Name of the C-Bus network to extract (or None to take first).

    Returns
    -------
    Dict[int, Tuple[str, Dict[int, str]]]
        Mapping of application address → (application name, {group address → group label}).
    """
    # Deferred import – avoid cost when labels aren't needed
    from cbus.toolkit.cbz import CBZ

    cbz = CBZ(project_fh)

    # Normalise cbus_network_name into string (Toolkit allows spaces)
    if isinstance(cbus_network_name, list):
        cbus_network_name = " ".join(cbus_network_name) if cbus_network_name else None

    chosen_network = None
    if cbus_network_name:
        for network in cbz.installation.project.network:
            if network.tag_name == cbus_network_name:
                chosen_network = network
                break
        if chosen_network is None:
            raise ValueError(f"CBus network '{cbus_network_name}' not found in project file")
    else:
        # Default to first network
        if not cbz.installation.project.network:
            raise ValueError("No networks found in CBZ project file")
        chosen_network = cbz.installation.project.network[0]

    # Build structure expected by mqtt_gateway.publish_all_lights
    labels: dict[int, tuple[str, dict[int, str]]] = {}
    for application in chosen_network.applications:
        group_labels: dict[int, str] = {group.address: group.tag_name for group in application.groups}
        labels[application.address] = (application.tag_name, group_labels)

    return labels

async def _main():
    # throttler is queue used used to stagger commmands
    throttler = Periodic(period=0.2)
    Periodic.throttler = throttler

    option = parse_cli_args()

    # Configure logging now that CLI options are known
    if option.verbosity:
        import os
        os.environ['CMQTTD_VERBOSITY'] = option.verbosity
    configure_logging('cbus')
    global_logger = logging.getLogger('cbus')
    
    # If log file is specified, add file handler
    if option.log:
        file_handler = logging.FileHandler(option.log)
        file_handler.setLevel(global_logger.level)
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(formatter)
        global_logger.addHandler(file_handler)

    loop = asyncio.get_event_loop()
    connection_lost_future = loop.create_future()
    
    try:
        labels = (read_cbz_labels(option.project_file,option.cbus_network)
                  if option.project_file else None)

        # Normalise cbus_network list -> single string (compat with previous behaviour)
        if hasattr(option, 'cbus_network') and option.cbus_network:
            option.cbus_network = " ".join(option.cbus_network)
        else:
            option.cbus_network = None

        # Validate client-cert/key pairing
        if bool(option.broker_client_cert) != bool(option.broker_client_key):
            raise SystemExit('To use client certificates, both --broker-client-cert (-k) and --broker-client-key (-K) must be specified.')

        def factory():
            return CBusHandler(
                timesync_frequency=option.timesync,
                handle_clock_requests=not option.no_clock,
                connection_lost_future=connection_lost_future,
                labels=labels,
            )

        # TCP connection is required
        addr_host, addr_port = option.tcp.split(':', 1)
        _, protocol = await loop.create_connection(factory, addr_host, int(addr_port))

        # TLS configuration
        if option.broker_disable_tls:
            logging.warning('Transport security disabled!')
            port = option.broker_port or 1883
            tls_kwargs = {}
        else:
            port = option.broker_port or 8883
            tls_context = ssl.create_default_context(cafile=option.broker_ca) if option.broker_ca else ssl.create_default_context()
            if option.broker_client_cert:
                tls_context.load_cert_chain(certfile=option.broker_client_cert, keyfile=option.broker_client_key)
            tls_kwargs = {'tls_context': tls_context}

        mqtt_client = MqttClient(protocol, option.broker_address, port, option.broker_keepalive, tls_kwargs)

        async with mqtt_client:  # type: ignore[arg-type]
            await connection_lost_future
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info('Shutting down...')
    except Exception as e:
        logger.critical("Unhandled exception: %s", e, exc_info=True)
    finally:
        # Clean up resources to prevent memory leaks
        logger.info('Cleaning up resources...')
        if 'transport' in locals() and 'transport' in vars() and transport is not None:
            transport.close()
        
        # Cancel all tasks
        await throttler.cleanup()
        
        # Clean up event loops
        loop = asyncio.get_event_loop()
        tasks = [t for t in asyncio.all_tasks(loop) if t is not asyncio.current_task()]
        for task in tasks:
            task.cancel()
        
        await asyncio.gather(*tasks, return_exceptions=True)
        logger.info('Cleanup complete')


def main():
    # work-around asyncio vs. setuptools console_scripts
    asyncio.run(_main())


if __name__ == '__main__':
    main()
