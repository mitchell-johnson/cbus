"""CLI for one raw routed WRITE with an exact independent ACK expectation."""
import argparse
import copy
from pathlib import Path
import re

from .commissioning_route import (
    assert_fresh_project,
    plan_commissioning_route,
    project_sha256,
    read_project_snapshot,
)
from .pci import WriteCAL
from .pci_routing import RoutedCALCommand
from .pci_routing_cli import _byte
from .pci_routed_recall import RoutedReplyPath
from .pci_routed_write import RoutedWriteClient
from .project import ProjectDocument


def _limit(text):
    if type(text) is not str or not re.fullmatch("[0-9]{1,7}", text):
        raise argparse.ArgumentTypeError("Expected a positive decimal resource limit")
    value = int(text)
    if value <= 0:
        raise argparse.ArgumentTypeError("Expected a positive decimal resource limit")
    return value


def _data(text):
    if type(text) is not str or len(text) > 60 or len(text) % 2 or not re.fullmatch("[0-9A-Fa-f]*", text):
        raise argparse.ArgumentTypeError("WRITE data must be 0..30 complete hexadecimal bytes")
    return bytes.fromhex(text)


def _sha256(text):
    if type(text) is not str or not re.fullmatch("[0-9A-Fa-f]{64}", text):
        raise argparse.ArgumentTypeError("Expected exactly 64 hexadecimal SHA-256 characters")
    return text.lower()


def options(operations):
    parser = operations.add_parser(
        "routed-write",
        help="Write once through a raw explicit or project-resolved route and require an exact ACK",
    )
    parser.add_argument("unit", type=_byte)
    parser.add_argument("parameter", type=_byte)
    parser.add_argument("hex_data", type=_data)
    parser.add_argument("--expected-ack-tag", type=_byte, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--project-file",
        type=Path,
        help="Legacy XML/CBZ project used to resolve and bind the typed topology",
    )
    mode.add_argument(
        "--expected-source",
        type=_byte,
        help="Raw mode: explicit outer source byte of the expected ACK",
    )
    parser.add_argument("--source-network", type=_byte,
                        help="Typed mode: network attached to this PCI/CNI")
    parser.add_argument("--target-network", type=_byte,
                        help="Typed mode: logical network containing UNIT")
    parser.add_argument("--project-name",
                        help="Typed mode: require this exact project TagName")
    parser.add_argument("--project-sha256", type=_sha256,
                        help="Typed mode: require this exact project-file snapshot")
    parser.add_argument("--bridge", type=_byte, action="append", default=[],
                        help="Raw mode: outgoing bridge byte; repeat in nearest-first order")
    parser.add_argument("--expected-destination", type=_byte,
                        help="Raw mode: explicit destination byte of the expected ACK")
    parser.add_argument("--expected-route", type=_byte, action="append", default=[],
                        help="Raw mode: expected incoming route byte; repeat in received order")
    parser.add_argument("--max-events", type=_limit, default=256)
    parser.add_argument("--max-received-bytes", type=_limit, default=32768)


def run(args):
    topology_fresh_at_handoff = False
    args._pci_routed_write_error = None
    args._pci_routed_write_client = None
    args._pci_routed_write_evidence = {
        "format": "cbus-routed-write-evidence-v1",
        "complete": False,
        "stage": "cli_preflight",
        "connect_attempted": False,
        "send_attempted": False,
        "resubmitted": False,
        "logical_network_resolved": False,
    }
    try:
        if args.area != "pci" or args.action != "routed-write":
            raise ValueError("Unsupported routed WRITE CLI operation")
        route_plan = None
        if args.project_file is not None:
            if args.local_unit is None:
                raise ValueError("Typed routed-write requires --local-unit")
            if args.source_network is None or args.target_network is None:
                raise ValueError("Typed routed-write requires --source-network and --target-network")
            if args.bridge or args.expected_destination is not None or args.expected_route:
                raise ValueError("Typed routed-write does not accept raw route expectation options")
            snapshot = read_project_snapshot(args.project_file)
            digest = project_sha256(snapshot)
            if args.project_sha256 is not None and args.project_sha256 != digest:
                raise ValueError(
                    f"Project snapshot SHA-256 mismatch: expected {args.project_sha256}, got {digest}"
                )
            project = ProjectDocument.from_snapshot(snapshot, source=args.project_file)
            route_plan = plan_commissioning_route(
                project,
                project_digest=digest,
                source_network=args.source_network,
                target_network=args.target_network,
                target_unit=args.unit,
                local_unit=args.local_unit,
                expected_ack_tag=args.expected_ack_tag,
                expected_project_name=args.project_name,
            )
            # Detect a replacement during parsing/planning and repeat this
            # exact check immediately before the one-shot transport handoff.
            assert_fresh_project(args.project_file, digest)
            bridges = route_plan.bridges
            expected = route_plan.expected
            args._pci_routed_write_evidence.update(
                logical_network_resolved=True,
                route_plan=route_plan.as_dict(),
            )
        else:
            if args.local_unit is not None:
                raise ValueError(
                    "--local-unit is reserved for typed routed-write; raw mode supplies the complete ACK path"
                )
            if args.source_network is not None or args.target_network is not None:
                raise ValueError("Raw routed-write does not accept typed network selectors")
            if args.project_name is not None or args.project_sha256 is not None:
                raise ValueError("Raw routed-write does not accept project identity options")
            if args.expected_destination is None:
                raise ValueError("Raw routed-write requires --expected-destination")
            bridges = tuple(args.bridge)
            expected = RoutedReplyPath(
                args.expected_source,
                args.expected_destination,
                tuple(args.expected_route),
            )
        command = RoutedCALCommand(
            args.unit,
            WriteCAL(args.parameter, args.hex_data),
            bridges=bridges,
            addressing="direct",
        )
        client = RoutedWriteClient(
            args.host,
            args.port,
            timeout=5.0 if args.timeout is None else args.timeout,
            command_checksum=args.checksum,
            max_events=args.max_events,
            max_received_bytes=args.max_received_bytes,
        )
        args._pci_routed_write_client = client
        if route_plan is not None:
            assert_fresh_project(args.project_file, route_plan.project_sha256)
            topology_fresh_at_handoff = True
            args._pci_routed_write_evidence["topology_fresh_at_handoff"] = True
        receipt = client.exchange(command, expected=expected, expected_ack_tag=args.expected_ack_tag)
        args._pci_routed_write_evidence = client.last_evidence
        result = receipt.as_dict()
        result["requested"] = {
            "unit": command.unit,
            "parameter": command.cal.parameter,
            "data_hex": command.cal.data.hex().upper(),
            "bridges": list(command.bridges),
            "addressing": "direct",
        }
        result["endpoint"] = {"host": client.host, "port": client.port}
        if route_plan is not None:
            plan = route_plan.as_dict()
            result.update(
                logical_network_resolved=True,
                topology_fresh_at_handoff=True,
                route_plan=plan,
            )
            args._pci_routed_write_evidence.update(
                logical_network_resolved=True,
                topology_fresh_at_handoff=True,
                route_plan=plan,
            )
        return result, 0
    except BaseException as error:
        args._pci_routed_write_error = error
        client = args._pci_routed_write_client
        if client is not None and client.last_error is error:
            args._pci_routed_write_evidence = client.last_evidence
        elif client is not None and type(client.last_evidence) is dict and client.last_evidence.get("complete"):
            args._pci_routed_write_evidence = {
                "complete": False,
                "stage": "result_export",
                "result_export_failed": True,
                "completed_exchange": client.last_evidence,
            }
        if 'route_plan' in locals() and route_plan is not None:
            args._pci_routed_write_evidence.update(
                logical_network_resolved=True,
                topology_fresh_at_handoff=topology_fresh_at_handoff,
                route_plan=route_plan.as_dict(),
            )
        raise


def error_payload(error, args):
    if (getattr(args, "area", None) != "pci" or getattr(args, "action", None) != "routed-write"
            or getattr(args, "_pci_routed_write_error", None) is not error):
        return {}
    try:
        return {"pci_routed_write_evidence": copy.deepcopy(args._pci_routed_write_evidence)}
    except BaseException:
        return {"pci_routed_write_evidence": {"complete": False, "evidence_export_failed": True}}
