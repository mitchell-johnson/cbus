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
import logging
from typing import List, Union

import sys
import ssl

# platform-specific event loop policy for Windows
if sys.platform == 'win32':
    from asyncio import set_event_loop_policy, WindowsSelectorEventLoopPolicy
    set_event_loop_policy(WindowsSelectorEventLoopPolicy())

# CLI helper
from cbus.daemon.cli import parse_cli_args

from cbus.logging_config import configure_logging

from cbus.toolkit.periodic import Periodic

# using new MQTT gateway classes
from cbus.daemon.mqtt_gateway import CBusHandler, MqttClient

# Logging will be configured later in _main after CLI options are parsed

logger = logging.getLogger(__name__)

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
    for app_def in chosen_network.applications:
        group_labels: dict[int, str] = {group.address: group.tag_name for group in app_def.groups}
        labels[app_def.address] = (app_def.tag_name, group_labels)

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

    loop = asyncio.get_running_loop()

    # Mutable container so factory closure always gets the current future
    future_holder = [loop.create_future()]

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
                connection_lost_future=future_holder[0],
                labels=labels,
            )

        esp32_conn = None  # track for cleanup
        protocol = None

        if option.tcp:
            # Legacy TCP connection to CNI/PCI
            addr_host, addr_port = option.tcp.split(':', 1)
            _, protocol = await loop.create_connection(factory, addr_host, int(addr_port))
        elif option.esp32_wifi or option.esp32_serial or getattr(option, 'esp32_discover', False):
            from cbus.esp32.connection import ESP32Connection, ESP32Config

            common_kwargs = dict(
                reconnect_interval=option.esp32_reconnect_interval,
                max_reconnect_attempts=option.esp32_max_reconnect,
                timesync_frequency=option.timesync,
                handle_clock_requests=not option.no_clock,
            )

            if option.esp32_discover:
                from cbus.esp32.discovery import ESP32Discovery
                discovery = ESP32Discovery(timeout=10.0)
                devices = await discovery.discover()
                if not devices:
                    raise SystemExit('No ESP32 C-Bus bridge devices found on the network')
                logger.info("Found %d ESP32 device(s), connecting to first: %s", len(devices), devices[0])
                esp32_config = ESP32Config.wifi(
                    devices[0].host, devices[0].port,
                    **common_kwargs,
                )
            elif option.esp32_wifi:
                addr = option.esp32_wifi
                host = addr.rsplit(':', 1)[0] if ':' in addr else addr
                port = int(addr.rsplit(':', 1)[1]) if ':' in addr else 10001
                esp32_config = ESP32Config.wifi(
                    host, port,
                    **common_kwargs,
                )
            else:
                esp32_config = ESP32Config.serial(
                    option.esp32_serial,
                    baudrate=option.esp32_baudrate,
                    **common_kwargs,
                )

            esp32_conn = ESP32Connection(esp32_config)
            esp32_conn.transport._protocol_factory = factory
            await esp32_conn.connect()
            protocol = esp32_conn.transport.protocol

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
            if esp32_conn and esp32_conn._config.reconnect:
                # ESP32 mode: reconnect loop with fresh futures
                while True:
                    await future_holder[0]
                    logger.warning("Connection lost. Waiting for reconnection...")
                    # Wait for transport to reconnect (transport handles its own reconnect loop)
                    max_wait = esp32_conn._config.max_reconnect_attempts or 999
                    reconnected = False
                    for _ in range(max_wait):
                        await asyncio.sleep(esp32_conn._config.reconnect_interval)
                        if esp32_conn.transport.is_connected:
                            # Create fresh future for the next disconnect
                            future_holder[0] = loop.create_future()
                            # Rebind MQTT to the new protocol instance
                            protocol = esp32_conn.transport.protocol
                            protocol._connection_lost_future = future_holder[0]
                            mqtt_client._userdata = protocol
                            protocol.mqtt_api = mqtt_client
                            logger.info("Reconnected. MQTT bridge re-bound.")
                            reconnected = True
                            break
                    if not reconnected:
                        logger.error("Reconnection exhausted. Shutting down.")
                        break
            else:
                await future_holder[0]
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info('Shutting down...')
    except Exception as e:
        logger.critical("Unhandled exception: %s", e, exc_info=True)
    finally:
        # Clean up resources to prevent memory leaks
        logger.info('Cleaning up resources...')

        # Close ESP32 connection if used
        if esp32_conn is not None:
            logger.info('Closing ESP32 connection')
            await esp32_conn.disconnect()
        # Close transport if protocol was created and has a transport
        elif protocol is not None and hasattr(protocol, '_transport') and protocol._transport is not None:
            logger.info('Closing C-Bus transport')
            protocol._transport.close()

        # Cancel all tasks
        await throttler.cleanup()

        # Clean up event loops
        loop = asyncio.get_event_loop()
        tasks = [t for t in asyncio.all_tasks(loop) if t is not asyncio.current_task()]
        if tasks:
            logger.info('Cancelling %s remaining tasks', len(tasks))
            for task in tasks:
                task.cancel()

            await asyncio.gather(*tasks, return_exceptions=True)
        logger.info('Cleanup complete')


def main():
    # work-around asyncio vs. setuptools console_scripts
    asyncio.run(_main())


if __name__ == '__main__':
    main()
