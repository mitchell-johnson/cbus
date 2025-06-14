"""Command-line interface definition for cmqttd.

This module isolates all `argparse` boiler-plate so that the daemon's runtime
logic can be imported without side-effects and to make argument-parsing
unit-testable.
"""
from __future__ import annotations

import argparse
from argparse import FileType, ArgumentParser
from typing import List, Optional


def build_arg_parser() -> ArgumentParser:
    """Return an `ArgumentParser` pre-configured with all cmqttd options."""
    parser = ArgumentParser(
        'cmqttd',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument('-d', '--debug', action='store_true', help='Enable debug logging')

    # Logging options -----------------------------------------------------
    group = parser.add_argument_group('Logging options')
    group.add_argument('-l', '--log-file', dest='log', default=None, help='Destination to write logs')
    group.add_argument('-v', '--verbosity', dest='verbosity', default='INFO', choices=('CRITICAL', 'ERROR', 'WARNING', 'INFO', 'DEBUG'), help='Verbosity to emit')

    # MQTT options --------------------------------------------------------
    group = parser.add_argument_group('MQTT options')
    group.add_argument('-b', '--broker-address', required=True, help='Address of the MQTT broker')
    group.add_argument('-p', '--broker-port', type=int, default=0, help='Port to use; 0 ⇒ auto')
    group.add_argument('--broker-keepalive', type=int, default=60, metavar='SECONDS', help='MQTT keep-alive')
    group.add_argument('--broker-disable-tls', action='store_true', help='Disable TLS (insecure)')
    group.add_argument('-A', '--broker-auth', type=FileType('rt'), help='File containing username and password (2 lines)')
    group.add_argument('-c', '--broker-ca', help='Path to directory containing CA certificates')
    group.add_argument('-k', '--broker-client-cert', help='PEM client certificate')
    group.add_argument('-K', '--broker-client-key', help='PEM client key (private)')

    # PCI / CNI connection -----------------------------------------------
    group = parser.add_argument_group('C-Bus PCI connection')
    group.add_argument('-t', '--tcp', dest='tcp', required=True, metavar='ADDR:PORT', help='IP address and TCP port of CNI/PCI (eg 192.168.1.10:10001)')

    # Time settings -------------------------------------------------------
    group = parser.add_argument_group('Time settings')
    group.add_argument('-T', '--timesync', metavar='SECONDS', dest='timesync', type=int, default=300, help='Send time synchronisation every n seconds (0 to disable)')
    group.add_argument('-C', '--no-clock', dest='no_clock', action='store_true', default=False, help='Do not respond to Clock Request SAL messages')
    group.add_argument('-S', '--status-resync', metavar='SECONDS', dest='status_resync', type=int, default=300, help='Request status updates every n seconds (0 to disable)')

    # Label options -------------------------------------------------------
    group = parser.add_argument_group('Label options')
    group.add_argument('-P', '--project-file', type=FileType('rb'), help='Path to a C-Bus Toolkit project backup (.cbz or .xml)')
    group.add_argument('-N', '--cbus-network', nargs='*', help='Name of the C-Bus network to use when project has multiple networks')

    return parser


def parse_cli_args(argv: Optional[List[str]] = None):
    """Parse *argv* (or *sys.argv* if None) and return the populated Namespace."""
    parser = build_arg_parser()
    return parser.parse_args(argv) 