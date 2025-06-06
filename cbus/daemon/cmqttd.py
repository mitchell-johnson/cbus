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
from argparse import ArgumentParser, FileType
import json
import logging
from marshal import load
from typing import Any, BinaryIO, Dict, Optional, Text, TextIO

import paho.mqtt.client as mqtt
import sys

from cbus.protocol import application
from cbus.logging_config import configure_logging

if sys.platform == 'win32':
    from asyncio import set_event_loop_policy, WindowsSelectorEventLoopPolicy
    set_event_loop_policy(WindowsSelectorEventLoopPolicy())

try:
    from serial_asyncio import create_serial_connection
except ImportError:
    async def create_serial_connection(*_, **__):
        raise ImportError('Serial device support requires pyserial-asyncio')

from cbus.common import MIN_GROUP_ADDR, MAX_GROUP_ADDR, check_ga, Application
from cbus.paho_asyncio import AsyncioHelper
from cbus.protocol.pciprotocol import PCIProtocol
from cbus.toolkit.cbz import CBZ
from cbus.toolkit.periodic import Periodic
from cbus.protocol.application import LightingApplication
from cbus.protocol.cal.report import LevelStatusReport,BinaryStatusReport


# Configure logging at module import time
configure_logging('cbus')
logger = logging.getLogger('cbus')

_BINSENSOR_TOPIC_PREFIX = 'homeassistant/binary_sensor/cbus_'
_LIGHT_TOPIC_PREFIX = 'homeassistant/light/cbus_'
_TOPIC_SET_SUFFIX = '/set'
_TOPIC_CONF_SUFFIX = '/config'
_TOPIC_STATE_SUFFIX = '/state'
_META_TOPIC = 'homeassistant/binary_sensor/cbus_cmqttd'
_APPLICATION_GROUP_SEPARATOR = "_"

def check_aa_lighting(app):
    if not app in LightingApplication.supported_applications():
        raise ValueError(
            'Application ${aa} is not a valid lighting application'.format(
                app))

def ga_range():
    return range(MIN_GROUP_ADDR, MAX_GROUP_ADDR + 1)

def ga_string(group_addr: int, app_addr: int | Application, zeros=True) -> Text:
    #note: the logic is necessary to ensure backward compatibility with previous version
        if(app_addr==Application.LIGHTING):
            return   f'{group_addr:03d}' if zeros else f'{group_addr}'
        else:
            return f'{app_addr:03d}{_APPLICATION_GROUP_SEPARATOR}{group_addr:03d}'

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

def set_topic(group_addr: int, app_addr: int | Application) -> Text:
    """Gets the Set topic for a group address."""
    return (_LIGHT_TOPIC_PREFIX + ga_string(group_addr,app_addr,False) + _TOPIC_SET_SUFFIX )


def state_topic(group_addr: int, app_addr: int | Application) -> Text:
    """Gets the State topic for a group address."""
    return _LIGHT_TOPIC_PREFIX + ga_string(group_addr,app_addr,False) + _TOPIC_STATE_SUFFIX


def conf_topic(group_addr: int, app_addr: int | Application) -> Text:
    """Gets the Config topic for a group address."""
    return _LIGHT_TOPIC_PREFIX + ga_string(group_addr,app_addr,False) + _TOPIC_CONF_SUFFIX


def bin_sensor_state_topic(group_addr: int, app_addr: int | Application) -> Text:
    """Gets the Binary Sensor State topic for a group address."""
    return _BINSENSOR_TOPIC_PREFIX + ga_string(group_addr,app_addr,False) + _TOPIC_STATE_SUFFIX


def bin_sensor_conf_topic(group_addr: int, app_addr: int | Application) -> Text:
    """Gets the Binary Sensor Config topic for a group address."""
    return _BINSENSOR_TOPIC_PREFIX + ga_string(group_addr,app_addr,False) + _TOPIC_CONF_SUFFIX



class CBusHandler(PCIProtocol):
    """
    Glue to wire events from the PCI onto MQTT
    """
    mqtt_api = None

    def __init__(self, labels: Optional[Dict[int, Dict]], resync_frequency: int = 300, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.labels = (
            labels if labels is not None else {56:{}})  # type: Dict[int, Text]
        self._is_closing = False
        self._resync_frequency = resync_frequency

    def cleanup(self):
        """Clean up resources to prevent memory leaks."""
        if self._is_closing:
            return
        
        self._is_closing = True
        self.mqtt_api = None  # Remove circular reference
        logger.debug("CBusHandler resources cleaned up")

    def handle_cbus_packet(self, p):
        """Override to add logging for all incoming C-Bus packets."""
        logger.debug(f"C-Bus packet received: {p!r}")
        # Call parent implementation
        super().handle_cbus_packet(p)

    def connection_lost(self, exc):
        """Handle connection lost event."""
        logger.warning(f"C-Bus connection lost: {exc}")
        if self.mqtt_api:
            # Clear the group database since we've lost connection
            # This will force re-discovery when connection is restored
            self.mqtt_api.groupDB.clear()
            logger.info("Cleared group database due to connection loss")
        self.cleanup()
        super().connection_lost(exc)

    def connection_made(self, transport):
        """Handle connection made event."""
        logger.info("C-Bus connection established")
        super().connection_made(transport)
        
        # If we have an MQTT API connection, trigger initial status request
        if self.mqtt_api:
            logger.info("Requesting initial status after connection restore")
            for app_addr in LightingApplication.supported_applications():
                self.mqtt_api.queue_status_requests(self, app_addr)

    def on_lighting_group_ramp(self, source_addr, group_addr, app_addr, duration, level):
        if not self.mqtt_api or self._is_closing:
            return
        logger.info(f"C-Bus event received: RAMP - Source: {source_addr}, Group: {group_addr}, App: {app_addr}, Level: {level}, Duration: {duration}")
        self.mqtt_api.lighting_group_ramp(
            source_addr, group_addr, app_addr, duration, level)

    def on_lighting_group_on(self, source_addr, group_addr, app_addr):
        if not self.mqtt_api or self._is_closing:
            return
        logger.info(f"C-Bus event received: ON - Source: {source_addr}, Group: {group_addr}, App: {app_addr}")
        self.mqtt_api.lighting_group_on(source_addr, group_addr, app_addr)

    def on_lighting_group_off(self, source_addr, group_addr, app_addr):
        if not self.mqtt_api or self._is_closing:
            return
        logger.info(f"C-Bus event received: OFF - Source: {source_addr}, Group: {group_addr}, App: {app_addr}")
        self.mqtt_api.lighting_group_off(source_addr, group_addr, app_addr)
    
    def on_level_report(self, app_addr, start, report: LevelStatusReport):
        if not self.mqtt_api or self._is_closing:
            return
            
        groups = self.mqtt_api.groupDB.setdefault(app_addr, {})
        processed_count = 0
        new_groups_count = 0
        
        for val in report:
            # Fixed: Process all level reports, not just for already-published groups
            # This allows discovery of active groups that weren't in the labels
            if val is not None:  # Only process if we have a valid level
                was_published = start in groups
                
                # Ensure the group is published to MQTT if it has a state
                self.mqtt_api.check_published(start, app_addr)
                
                if not was_published:
                    new_groups_count += 1
                    logger.info(f"Discovered new active group {start} in application {app_addr} with level {val}")
                
                if val == 0:
                    self.on_lighting_group_off(0, start, app_addr)
                elif val == 255:
                    self.on_lighting_group_on(0, start, app_addr)
                else:
                    self.on_lighting_group_ramp(0, start, app_addr, 0, val)
                    
                processed_count += 1
            start += 1
        
        if processed_count > 0:
            logger.debug(f"Processed level report for application {app_addr}: {processed_count} active groups, {new_groups_count} newly discovered")

    def on_clock_request(self, source_addr):
        if not self._is_closing:
            asyncio.create_task(self.clock_datetime())


class MqttClient(mqtt.Client):

    def on_connect(self, client, userdata: CBusHandler, flags, rc):
        logger.info('Connected to MQTT broker')
        userdata.mqtt_api = self
        self.groupDB = {}
        self.publish_all_lights(userdata.labels)
        
        # Request status for all supported lighting applications
        # Fixed: Don't wait for groupDB to be populated - request status for all known lighting applications
        logger.info("Requesting initial status for all lighting applications")
        for app_addr in LightingApplication.supported_applications():
            self.queue_status_requests(userdata, app_addr)
        
        # Start periodic re-synchronization to keep MQTT in sync with real state
        resync_freq = getattr(userdata, '_resync_frequency', 300)
        self.start_periodic_resync(userdata, resync_freq)

    def start_periodic_resync(self, userdata, resync_frequency=300):
        """Start periodic re-synchronization to keep MQTT state accurate."""
        if resync_frequency <= 0:
            logger.info("Periodic re-synchronization disabled")
            return
            
        async def periodic_resync():
            logger.info(f"Starting periodic re-synchronization with frequency {resync_frequency}s")
            sync_count = 0
            while True:
                try:
                    # Wait for the specified interval
                    await asyncio.sleep(resync_frequency)
                    
                    if userdata._is_closing or not userdata.mqtt_api:
                        break
                    
                    sync_count += 1
                    logger.info(f"Starting periodic re-synchronization #{sync_count}")
                    
                    # Count total groups being processed
                    total_groups = sum(len(groups) for groups in self.groupDB.values())
                    logger.debug(f"Re-syncing state for {total_groups} published groups across {len(self.groupDB)} applications")
                    
                    # Request status for all supported lighting applications
                    for app_addr in LightingApplication.supported_applications():
                        self.queue_status_requests(userdata, app_addr)
                    
                    logger.debug(f"Periodic re-synchronization #{sync_count} requests queued")
                    
                except asyncio.CancelledError:
                    logger.info("Periodic re-sync task cancelled")
                    break
                except Exception as e:
                    logger.error(f"Error in periodic re-sync: {e}", exc_info=True)
                    # Continue after error, but wait a bit before retrying
                    await asyncio.sleep(30)
        
        # Start the periodic resync task
        asyncio.create_task(periodic_resync())

    def queue_status_requests(self, userdata, app_addr):
        """Queue status requests in a way that avoids memory leaks from lambdas in loops."""
        for block in range(0, 256, 32):
            # Create a proper function that doesn't use closure
            Periodic.throttler.enqueue(
                lambda block=block, app_addr=app_addr: 
                asyncio.create_task(userdata.request_status(block, app_addr)))

    async def switchLight(self, userdata, group_addr, app_addr, light_on, brightness, transition_time ):
        logger.info(f"switchLight executing: Group {group_addr}, App {app_addr}, State: {'ON' if light_on else 'OFF'}, Brightness: {brightness}, Transition: {transition_time}")
        # push state to CBus and republish on MQTT
        # DEBUG: This is where calls to turn the lights end up
        if light_on:
            if brightness == 255 and transition_time == 0:
                # lighting on
                logger.debug(f"Sending lighting_group_on command to C-Bus for group {group_addr}")
                await userdata.lighting_group_on(group_addr,app_addr)
                self.lighting_group_on(None, group_addr,app_addr)
            else:
                # ramp
                logger.debug(f"Sending lighting_group_ramp command to C-Bus for group {group_addr}, level {brightness}, duration {transition_time}")
                await userdata.lighting_group_ramp(group_addr, app_addr, transition_time, brightness)
                self.lighting_group_ramp(None, group_addr, app_addr, transition_time, brightness)
        else:
            # lighting off
            logger.debug(f"Sending lighting_group_off command to C-Bus for group {group_addr}")
            await userdata.lighting_group_off(group_addr,app_addr)
            self.lighting_group_off(None, group_addr,app_addr)

    def on_message(self, client, userdata: CBusHandler, msg: mqtt.MQTTMessage):

        # Removed hardcoded basicConfig line
        logger.debug(f'\n\nmessage received\n topic: {msg.topic} \n payload: {msg.payload}')
        """Handle a message from an MQTT subscription."""
        if not (msg.topic.startswith(_LIGHT_TOPIC_PREFIX) and
                msg.topic.endswith(_TOPIC_SET_SUFFIX)):
            return

        try:
            group_addr, app_addr = get_topic_group_address(msg.topic)
        except ValueError:
            # Invalid group address
            logging.error(f'Invalid group address in topic {msg.topic}')
            return

        # https://www.home-assistant.io/integrations/light.mqtt/#json-schema
        try:
            payload = json.loads(msg.payload)
        except Exception as e:
            logging.error(f'JSON parse error in {msg.topic}', exc_info=e)
            return
        light_on = payload['state'].upper() == 'ON'
        brightness = int(payload.get('brightness', 255))
        if brightness < 0:
            brightness = 0.
        if brightness > 255:
            brightness = 255
        transition_time = int(payload.get('transition', 0))
        if transition_time < 0:
            transition_time = 0

        logger.info(f"MQTT command: Group {group_addr}, App {app_addr}, State: {'ON' if light_on else 'OFF'}, Brightness: {brightness}, Transition: {transition_time}")
        Periodic.throttler.enqueue(lambda: asyncio.create_task(self.switchLight(userdata, group_addr, app_addr, light_on, brightness, transition_time)))

    def publish(self, topic: Text, payload: Dict[Text, Any]):
        """Publishes a payload as JSON."""
        payload = json.dumps(payload)
        return super().publish(topic, payload, 1, True)

    def publish_light(self, group_addr : int, app_addr :int | Application, app_labels:dict  = None):
                default_name = default_light_name(group_addr,app_addr)
                UID = f'cbus_light_{ga_string(group_addr,app_addr,False)}'
                name = default_name
                if app_labels:
                    _,labels =  app_labels.get(app_addr,(None,{}))
                    if labels:
                        name = labels.get(group_addr,name)
                UID = f'cbus_light_{ga_string(group_addr,app_addr,False)}'
                self.subscribe(set_topic(group_addr,app_addr), 2 )
                self.publish(conf_topic(group_addr,app_addr), {
                    'name': name,
                    'unique_id': UID,
                    'cmd_t': set_topic(group_addr,app_addr),
                    'stat_t': state_topic(group_addr,app_addr),
                    'schema': 'json',
                    'brightness': True,
                    'device': {
                        'identifiers': [UID],
                        'connections': [['cbus_group_address', str(group_addr)],['cbus_application_address', str(app_addr)]],
                        'sw_version': 'cmqttd https://github.com/micolous/cbus',
                        'name': default_name,
                        'manufacturer': 'Clipsal',
                        'model': 'C-Bus Lighting Application',
                        'via_device': 'cmqttd',
                    },
                })
                Sensor_UID = f'cbus_bin_sensor_{ga_string(group_addr,app_addr,False)}'
                self.publish(bin_sensor_conf_topic(group_addr,app_addr), {
                    'name': f'{name} (as binary sensor)',
                    'unique_id': Sensor_UID, 
                    'stat_t': bin_sensor_state_topic(group_addr,app_addr),
                    'device': {
                        'identifiers': [Sensor_UID],
                        'connections': [['cbus_group_address', str(group_addr)],['cbus_application_address', str(app_addr)]],
                        'sw_version': 'cmqttd https://github.com/micolous/cbus',
                        'name': default_name,
                        'manufacturer': 'Clipsal',
                        'model': 'C-Bus Lighting Application',
                        'via_device': 'cmqttd',
                    },
                })
                self.groupDB.setdefault(app_addr,{})[group_addr] = True
                


    def publish_all_lights(self, app_labels):
        """Publishes a configuration topic for all lights."""
        # Meta-device which holds all the C-Bus group addresses
        self.publish(_META_TOPIC + _TOPIC_CONF_SUFFIX, {
            '~': _META_TOPIC,
            'name': 'cmqttd',
            'unique_id': 'cmqttd',
            'stat_t': '~' + _TOPIC_STATE_SUFFIX,  # unused
            'device': {
                'identifiers': ['cmqttd'],
                'sw_version': 'cmqttd https://github.com/micolous/cbus',
                'name': 'cmqttd',
                'manufacturer': 'micolous',
                'model': 'libcbus',
            },
        })

        for app_addr,(_,labels) in app_labels.items():
            for group_addr in labels.keys():
                self.publish_light(group_addr,app_addr,app_labels)
                
    def check_published(self,group_addr: int, app_addr: int | Application):
        if not self.groupDB.setdefault(app_addr,{}).get(group_addr,False):
            self.publish_light(group_addr,app_addr)

    
    def publish_binary_sensor(self, group_addr: int, app_addr: int | Application, state: Optional[bool]):
        payload = 'ON' if state else 'OFF'
        return super().publish(
            bin_sensor_state_topic(group_addr,app_addr), payload, 1, True)

    def lighting_group_on(self, source_addr: Optional[int], group_addr: int, app_addr: int | Application):
        """Relays a lighting-on event from CBus to MQTT."""
        self.check_published(group_addr,app_addr)
        self.publish(state_topic(group_addr,app_addr), {
            'state': 'ON',
            'brightness': 255,
            'transition': 0,
            'cbus_source_addr': source_addr,
        })
        self.publish_binary_sensor(group_addr,app_addr, True)

    def lighting_group_off(self, source_addr: Optional[int], group_addr: int, app_addr: int | Application):
        """Relays a lighting-off event from CBus to MQTT."""
        self.check_published(group_addr,app_addr)
        self.publish(state_topic(group_addr,app_addr), {
            'state': 'OFF',
            'brightness': 0,
            'transition': 0,
            'cbus_source_addr': source_addr,
        })
        self.publish_binary_sensor(group_addr,app_addr, False)

    def lighting_group_ramp(self, source_addr: Optional[int], group_addr: int, app_addr:int|Application,
                            duration: int, level: int):
        """Relays a lighting-ramp event from CBus to MQTT."""
        self.check_published(group_addr,app_addr)
        self.publish(state_topic(group_addr,app_addr), {
            'state': 'ON',
            'brightness': level,
            'transition': duration,
            'cbus_source_addr': source_addr,
        })
        self.publish_binary_sensor(group_addr, app_addr, level > 0 if isinstance(level,int) else None)


def read_auth(client: mqtt.Client, auth_file: TextIO):
    """Reads authentication from a file."""
    username = auth_file.readline().strip()
    password = auth_file.readline().strip()
    client.username_pw_set(username, password)


def read_cbz_labels(cbz_file: BinaryIO, network_name = None) -> Dict[int, Text]:
    """Reads group address names from a given Toolkit CBZ file."""
    class obj():
        pass

    labels = {56:{}}  # type: Dict[int,Dict[int, Text]]

    cbz = CBZ(cbz_file)

    networks = [n for n in cbz.installation.project.network
                if n.interface.interface_type != 'bridge']
                
    if network_name:
        networks = [n for n in networks if n.tag_name == network_name]

    if len(networks) != 1:
        if network_name:
            logger.warning('Could not find a non-bridge network with name "%s" in project file.',network_name)
        else:
            logger.warning('Expected one non-bridge network in project file, found %d instead',len(networks))
        app = obj()
        app.address = 56
        app.tag_name = "Lighting"
        app.groups = []    
        net = obj()
        net.applications  = [app]
        networks = [net]

    applications = [a for a in networks[0].applications if a.address in LightingApplication.supported_applications()]
    
    if len(applications) == 0:
        logger.warning('Could not find any lighting application in project file.')
        app = obj()
        app.address = 56
        app.tag_name = "Lighting"
        app.groups = []   
        applications =  [app]

    for a in applications:
        l = {}
        if  a.groups:
            for group in a.groups:
                name = group.tag_name.strip()
                if not name or name in ('<Unused>', f'Group {group.address}'):
                    name = default_light_name(group.address,a.address)
                l[group.address] = name
        else:
            logger.warning('No label available in project file for application %d.',a.address)
            logger.warning('Will use default labels.')
            for ga in ga_range():
                l[ga] = default_light_name(ga,a.address)
        labels[a.address]=(a.tag_name,l)
    return labels

async def _main():
    # throttler is queue used used to stagger commmands
    throttler = Periodic(period=0.2)
    Periodic.throttler = throttler

    parser = ArgumentParser('cmqttd')
    parser.add_argument(
        '-d', '--debug', action='store_true',
        help='Enable debug logging')
    
    group = parser.add_argument_group('Logging options')
    group.add_argument(
        '-l', '--log-file',
        dest='log', default=None,
        help='Destination to write logs [default: stdout]')

    group.add_argument(
        '-v', '--verbosity',
        dest='verbosity', default='INFO', choices=(
            'CRITICAL', 'ERROR', 'WARNING', 'INFO', 'DEBUG'),
        help='Verbosity of logging to emit [default: %(default)s]')

    group = parser.add_argument_group('MQTT options')
    group.add_argument(
        '-b', '--broker-address',
        required=True,
        help='Address of the MQTT broker')

    group.add_argument(
        '-p', '--broker-port',
        type=int, default=0,
        help='Port to use to connect to the MQTT broker. [default: 8883 if '
             'using TLS (default), otherwise 1883]')

    group.add_argument(
        '--broker-keepalive',
        type=int, default=60, metavar='SECONDS',
        help='Send a MQTT keep-alive message every n seconds. Most people '
             'should not need to change this. [default: %(default)s seconds]')

    group.add_argument(
        '--broker-disable-tls',
        action='store_true',
        help='Disables TLS [default: TLS is enabled]. Setting this option is '
             'insecure.')

    group.add_argument(
        '-A', '--broker-auth',
        type=FileType('rt'),
        help='File containing the username and password to authenticate to the '
             'MQTT broker with. The first line in the file is the username, '
             'and the second line is the password. The file must be UTF-8 '
             'encoded. If not specified, authentication will be disabled '
             '(insecure!)')

    group.add_argument(
        '-c', '--broker-ca',
        help='Path to directory containing CA certificates to trust. If not '
             'specified, the default (Python) CA store is used instead.')

    group.add_argument(
        '-k', '--broker-client-cert',
        help='Path to PEM-encoded client certificate (public part). If not '
             'specified, client authentication will not be used. Must also '
             'supply the private key (-K).')

    group.add_argument(
        '-K', '--broker-client-key',
        help='Path to PEM-encoded client key (private part). If not '
             'specified, client authentication will not be used. Must also '
             'supply the public key (-k). If this file is encrypted, Python '
             'will prompt for the password at the command-line.')

    group = parser.add_argument_group(
        'C-Bus PCI options', 'You must specify exactly one of these options:')
    group = group.add_mutually_exclusive_group(required=True)

    group.add_argument(
        '-s', '--serial',
        dest='serial', default=None, metavar='DEVICE',
        help='Device node that the PCI is connected to. USB PCIs act as a '
             'cp210x USB-serial adapter. (example: -s /dev/ttyUSB0)')

    group.add_argument(
        '-t', '--tcp',
        dest='tcp', default=None, metavar='ADDR:PORT',
        help='IP address and TCP port where the C-Bus CNI or PCI is located '
             '(eg: -t 192.0.2.1:10001)')

    group = parser.add_argument_group('Time settings')
    group.add_argument(
        '-T', '--timesync', metavar='SECONDS',
        dest='timesync', type=int, default=300,
        help='Send time synchronisation packets every n seconds '
             '(or 0 to disable). [default: %(default)s seconds]')

    group.add_argument(
        '-C', '--no-clock',
        dest='no_clock', action='store_true',
        default=False,
        help='Do not respond to Clock Request SAL messages with the system '
             'time (ie: do not provide the CBus network the time when '
             'requested). Enable if your machine does not have a reliable '
             'time source, or you have another device on the CBus network '
             'providing time services. [default: %(default)s]')

    group.add_argument(
        '-S', '--status-resync', metavar='SECONDS',
        dest='status_resync', type=int, default=300,
        help='Request status updates from C-Bus every n seconds to keep '
             'MQTT state synchronized (or 0 to disable). This helps ensure '
             'MQTT doesn\'t get out of sync with real light states. '
             '[default: %(default)s seconds]')

    group = parser.add_argument_group('Label options')

    group.add_argument(
        '-P', '--project-file',
        type=FileType('rb'),
        help='Path to a C-Bus Toolkit project backup file (CBZ or XML) '
             'containing labels for group addresses to use. If not supplied, '
             'generated names like "C-Bus Light 001" will be used instead.'
    )

    group.add_argument(
        '-N', '--cbus-network',
        nargs='*',
        help='Name of the C-Bus network to be used in case a project file is provided'
             'and the project contains multiple networks.'
    )

    option = parser.parse_args()

    option.cbus_network = " ".join(option.cbus_network) 

    if bool(option.broker_client_cert) != bool(option.broker_client_key):
        return parser.error(
            'To use client certificates, both -k and -K must be specified.')

    global_logger = logging.getLogger('cbus')
    # Use the verbosity from command line if provided, otherwise env var will be used
    if option.verbosity:
        import os
        os.environ['CMQTTD_VERBOSITY'] = option.verbosity
    # Reconfigure logging with the potentially updated environment variable
    configure_logging('cbus')
    
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
    labels = (read_cbz_labels(option.project_file,option.cbus_network)
              if option.project_file else None)

    def factory():
        return CBusHandler(
            timesync_frequency=option.timesync,
            handle_clock_requests=not option.no_clock,
            connection_lost_future=connection_lost_future,
            labels=labels,
            resync_frequency=option.status_resync,
        )

    if option.serial:
        _, protocol = await create_serial_connection(
            loop, factory, option.serial, baudrate=9600)
    elif option.tcp:
        addr = option.tcp.split(':', 2)
        _, protocol = await loop.create_connection(
            factory, addr[0], int(addr[1]))

    mqtt_client = MqttClient(userdata=protocol)
    if option.broker_auth:
        read_auth(mqtt_client, option.broker_auth)
    if option.broker_disable_tls:
        logging.warning('Transport security disabled!')
        port = option.broker_port or 1883
    else:
        tls_args = {}
        if option.broker_ca:
            tls_args['ca_certs'] = option.broker_ca
        if option.broker_client_cert:
            tls_args['certfile'] = option.broker_client_cert
            tls_args['keyfile'] = option.broker_client_key
        mqtt_client.tls_set(**tls_args)
        port = option.broker_port or 8883

    aioh = AsyncioHelper(loop, mqtt_client)
    mqtt_client.connect(option.broker_address, port, option.broker_keepalive)

    try:
        await connection_lost_future
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info('Shutting down...')
    finally:
        # Clean up resources to prevent memory leaks
        logger.info('Cleaning up resources...')
        if 'transport' in locals() and transport is not None:
            transport.close()
        
        # Cancel all tasks
        await throttler.cleanup()
        
        if 'helper' in locals() and helper is not None:
            if hasattr(helper, 'misc') and helper.misc is not None:
                helper.misc.cancel()
        
        # Disconnect MQTT client if it exists
        if 'mqtt_client' in locals() and mqtt_client is not None:
            mqtt_client.disconnect()
            mqtt_client.loop_stop()
        
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
