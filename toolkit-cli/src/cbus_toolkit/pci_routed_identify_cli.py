"""CLI for one raw IDENTIFY with an explicit independent reply path."""
import argparse
import copy
import re

from .pci import IdentifyCAL
from .pci_routing import RoutedCALCommand
from .pci_routing_cli import _byte
from .pci_routed_identify import RoutedIdentifyClient
from .pci_routed_read_topology import add_route_options, assert_route_fresh, resolve_route


def _count(text):
    value = _byte(text)
    if not 0 <= value <= 30:
        raise argparse.ArgumentTypeError('Expected IDENTIFY count must be in 0..30')
    return value


def _limit(text):
    if type(text) is not str or not re.fullmatch('[0-9]{1,7}', text):
        raise argparse.ArgumentTypeError('Expected a positive decimal resource limit')
    value = int(text)
    if value <= 0:
        raise argparse.ArgumentTypeError('Expected a positive decimal resource limit')
    return value


def options(operations):
    parser = operations.add_parser('routed-identify', help='Read raw IDENTIFY bytes through an explicit or project-resolved route')
    parser.add_argument('unit', type=_byte)
    parser.add_argument('attribute', type=_byte)
    parser.add_argument('--expected-count', type=_count, help='Require exactly 0..30 data bytes; omit to admit any supported wire count')
    add_route_options(parser)
    parser.add_argument('--max-events', type=_limit, default=256)
    parser.add_argument('--max-received-bytes', type=_limit, default=32768)


def run(args):
    topology_fresh_at_handoff = False
    args._pci_routed_identify_error = None
    args._pci_routed_identify_client = None
    args._pci_routed_identify_evidence = {'format': 'cbus-routed-identify-evidence-v1', 'complete': False,
        'stage': 'cli_preflight', 'connect_attempted': False, 'send_attempted': False,
        'resubmitted': False, 'logical_network_resolved': False}
    try:
        if args.area != 'pci' or args.action != 'routed-identify':
            raise ValueError('Unsupported routed IDENTIFY CLI operation')
        route_plan = None
        bridges, expected, route_plan = resolve_route(args)
        if route_plan is not None:
            assert_route_fresh(args, route_plan)
            args._pci_routed_identify_evidence.update(
                logical_network_resolved=True, route_plan=route_plan.as_dict())
        command = RoutedCALCommand(args.unit, IdentifyCAL(args.attribute),
                                   bridges=bridges, addressing='direct')
        client = RoutedIdentifyClient(args.host, args.port, timeout=5.0 if args.timeout is None else args.timeout,
            command_checksum=args.checksum, max_events=args.max_events, max_received_bytes=args.max_received_bytes)
        args._pci_routed_identify_client = client
        if route_plan is not None:
            assert_route_fresh(args, route_plan)
            topology_fresh_at_handoff = True
            args._pci_routed_identify_evidence['topology_fresh_at_handoff'] = True
        receipt = client.exchange(command, expected=expected, expected_count=args.expected_count)
        args._pci_routed_identify_evidence = client.last_evidence
        result = receipt.as_dict()
        result['requested'] = {'unit': command.unit, 'attribute': command.cal.attribute,
            'expected_count': args.expected_count, 'bridges': list(command.bridges), 'addressing': 'direct'}
        result['endpoint'] = {'host': client.host, 'port': client.port}
        if route_plan is not None:
            plan = route_plan.as_dict()
            result.update(logical_network_resolved=True, topology_fresh_at_handoff=True,
                          route_plan=plan)
            args._pci_routed_identify_evidence.update(
                logical_network_resolved=True, topology_fresh_at_handoff=True,
                route_plan=plan)
        return result, 0
    except BaseException as error:
        args._pci_routed_identify_error = error
        client = args._pci_routed_identify_client
        if client is not None and client.last_error is error:
            args._pci_routed_identify_evidence = client.last_evidence
        elif client is not None and type(client.last_evidence) is dict and client.last_evidence.get('complete'):
            args._pci_routed_identify_evidence = {'complete': False, 'stage': 'result_export',
                'result_export_failed': True, 'completed_exchange': client.last_evidence}
        if 'route_plan' in locals() and route_plan is not None:
            args._pci_routed_identify_evidence.update(
                logical_network_resolved=True,
                topology_fresh_at_handoff=topology_fresh_at_handoff,
                route_plan=route_plan.as_dict())
        raise


def error_payload(error, args):
    if (getattr(args, 'area', None) != 'pci' or getattr(args, 'action', None) != 'routed-identify'
            or getattr(args, '_pci_routed_identify_error', None) is not error):
        return {}
    try:
        return {'pci_routed_identify_evidence': copy.deepcopy(args._pci_routed_identify_evidence)}
    except BaseException:
        return {'pci_routed_identify_evidence': {'complete': False, 'evidence_export_failed': True}}
