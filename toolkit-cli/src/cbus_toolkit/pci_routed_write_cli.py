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
from .pci_routed_write import RoutedWriteClient, journal_summary, journaled_write, recover_write
from .project import ProjectDocument, ProjectError


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
    parser.add_argument("unit", type=_byte, nargs="?")
    parser.add_argument("parameter", type=_byte, nargs="?")
    parser.add_argument("hex_data", type=_data, nargs="?")
    parser.add_argument("--expected-ack-tag", type=_byte,
                        help="Required for a WRITE: the exact ACK tag")
    mode = parser.add_mutually_exclusive_group()
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
    parser.add_argument("--journal", type=Path,
                        help="New exclusive attempt journal: baseline RECALL, fsynced record, then one WRITE")
    parser.add_argument("--recover", action="store_true",
                        help="Classify --journal by one fresh read-only RECALL; never writes or resends")
    parser.add_argument("--max-events", type=_limit, default=256)
    parser.add_argument("--max-received-bytes", type=_limit, default=32768)
    parser.set_defaults(_routed_write_parser=parser)


def _usage(args, message):
    """Report an invalid option combination with argparse's exit status 2."""
    parser = getattr(args, "_routed_write_parser", None)
    if parser is None:
        raise ValueError(message)
    parser.error(message)


def _plan_route(args, *, unit, ack_tag, source_network, target_network, local_unit, project_name):
    snapshot = read_project_snapshot(args.project_file)
    digest = project_sha256(snapshot)
    if args.project_sha256 is not None and args.project_sha256 != digest:
        raise ValueError(
            f"Project snapshot SHA-256 mismatch: expected {args.project_sha256}, got {digest}"
        )
    project = ProjectDocument.from_snapshot(snapshot, source=args.project_file)
    return plan_commissioning_route(
        project,
        project_digest=digest,
        source_network=source_network,
        target_network=target_network,
        target_unit=unit,
        local_unit=local_unit,
        expected_ack_tag=ack_tag,
        expected_project_name=project_name,
    )


def _recover(args):
    if args.journal is None:
        _usage(args, "--recover requires --journal")
    if (any(value is not None for value in (
            args.unit, args.parameter, args.hex_data, args.expected_ack_tag, args.expected_source,
            args.expected_destination, args.source_network, args.target_network, args.local_unit))
            or args.bridge or args.expected_route):
        _usage(args, "--recover reads every WRITE and route fact from --journal; only "
                         "--project-file, --project-name and --project-sha256 may recheck it")
    if args.project_file is None and (args.project_name is not None or args.project_sha256 is not None):
        _usage(args, "--project-name and --project-sha256 require --project-file")
    route_check = None
    if args.project_file is not None:
        def route_check(plan):
            if plan["mode"] != "typed":
                raise ValueError("A raw-mode journal has no project to recheck")
            saved = plan["route_plan"]
            fresh = _plan_route(
                args, unit=saved["target_unit"], ack_tag=saved["expected_ack_tag"],
                source_network=saved["source_network"], target_network=saved["target_network"],
                local_unit=saved["local_unit"],
                project_name=args.project_name or saved["project_name"])
            if fresh.as_dict() != saved:
                raise ProjectError(
                    "Project topology differs from the journaled route plan; no recovery RECALL was sent")
    report = recover_write(
        args.journal, host=args.host, port=args.port,
        timeout=5.0 if args.timeout is None else args.timeout,
        max_events=args.max_events, max_received_bytes=args.max_received_bytes,
        route_check=route_check)
    return report, 0 if report["resolved"] else 1


def _result(receipt, command, client, route_plan):
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
        result.update(
            logical_network_resolved=True,
            topology_fresh_at_handoff=True,
            route_plan=route_plan.as_dict(),
        )
    return result


def _journaled(args, command, expected, route_plan, timeout):
    observer = {}
    args._pci_routed_write_observer = observer
    handoff_check = None
    if route_plan is not None:
        saved = route_plan.as_dict()

        def handoff_check():
            # Exact bytes first, then a fresh plan from those bytes: either
            # change refuses before the journal or before the WRITE send.
            assert_fresh_project(args.project_file, route_plan.project_sha256)
            fresh = _plan_route(
                args, unit=args.unit, ack_tag=args.expected_ack_tag,
                source_network=args.source_network, target_network=args.target_network,
                local_unit=args.local_unit, project_name=args.project_name)
            if fresh.as_dict() != saved:
                raise ProjectError("Project route plan changed before the routed WRITE")

    try:
        receipt, attempt = journaled_write(
            command, expected=expected, expected_ack_tag=args.expected_ack_tag,
            journal=args.journal, host=args.host, port=args.port, timeout=timeout,
            command_checksum=args.checksum, max_events=args.max_events,
            max_received_bytes=args.max_received_bytes,
            project_sha256=None if route_plan is None else route_plan.project_sha256,
            route_plan=None if route_plan is None else route_plan.as_dict(),
            handoff_check=handoff_check, observer=observer)
    finally:
        client = observer.get("write_client")
        if client is not None:
            args._pci_routed_write_client = client
    args._pci_routed_write_evidence = client.last_evidence
    result = _result(receipt, command, client, route_plan)
    result["journal"] = journal_summary(attempt)
    return result, 0


def run(args):
    topology_fresh_at_handoff = False
    args._pci_routed_write_error = None
    args._pci_routed_write_client = None
    args._pci_routed_write_observer = None
    args._pci_routed_write_evidence = {
        "format": "cbus-routed-write-evidence-v1",
        "complete": False,
        "stage": "cli_preflight",
        "connect_attempted": False,
        "send_attempted": False,
        "resubmitted": False,
        "logical_network_resolved": False,
    }
    route_plan = None
    try:
        if args.area != "pci" or args.action != "routed-write":
            raise ValueError("Unsupported routed WRITE CLI operation")
        if args.recover:
            return _recover(args)
        if args.unit is None or args.parameter is None or args.hex_data is None:
            _usage(args, "routed-write requires UNIT PARAMETER HEX_DATA")
        if args.expected_ack_tag is None:
            _usage(args, "routed-write requires --expected-ack-tag")
        if args.project_file is None and args.expected_source is None:
            _usage(args, "routed-write requires --project-file or --expected-source")
        if args.project_file is not None:
            if args.local_unit is None:
                raise ValueError("Typed routed-write requires --local-unit")
            if args.source_network is None or args.target_network is None:
                raise ValueError("Typed routed-write requires --source-network and --target-network")
            if args.bridge or args.expected_destination is not None or args.expected_route:
                raise ValueError("Typed routed-write does not accept raw route expectation options")
            route_plan = _plan_route(
                args, unit=args.unit, ack_tag=args.expected_ack_tag,
                source_network=args.source_network, target_network=args.target_network,
                local_unit=args.local_unit, project_name=args.project_name)
            # Detect a replacement during parsing/planning and repeat this
            # exact check immediately before the one-shot transport handoff.
            assert_fresh_project(args.project_file, route_plan.project_sha256)
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
        timeout = 5.0 if args.timeout is None else args.timeout
        if args.journal is not None:
            return _journaled(args, command, expected, route_plan, timeout)
        client = RoutedWriteClient(
            args.host,
            args.port,
            timeout=timeout,
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
        return _result(receipt, command, client, route_plan), 0
    except BaseException as error:
        args._pci_routed_write_error = error
        client = args._pci_routed_write_client
        observer = args._pci_routed_write_observer
        if client is not None and client.last_error is error:
            args._pci_routed_write_evidence = client.last_evidence
        elif observer is not None and client is not None and type(client.last_evidence) is dict:
            # Journaled path: the exchange evidence (possibly complete but not
            # accepted, e.g. a generation change after send) is the record.
            args._pci_routed_write_evidence = client.last_evidence
        elif client is not None and type(client.last_evidence) is dict and client.last_evidence.get("complete"):
            args._pci_routed_write_evidence = {
                "complete": False,
                "stage": "result_export",
                "result_export_failed": True,
                "completed_exchange": client.last_evidence,
            }
        if route_plan is not None and type(args._pci_routed_write_evidence) is dict:
            args._pci_routed_write_evidence = dict(args._pci_routed_write_evidence)
            args._pci_routed_write_evidence.update(
                logical_network_resolved=True,
                topology_fresh_at_handoff=bool(
                    topology_fresh_at_handoff
                    or args._pci_routed_write_evidence.get("handoff_check_passed") is True),
                route_plan=route_plan.as_dict(),
            )
        raise


def error_payload(error, args):
    if (getattr(args, "area", None) != "pci" or getattr(args, "action", None) != "routed-write"
            or getattr(args, "_pci_routed_write_error", None) is not error):
        return {}
    try:
        payload = {"pci_routed_write_evidence": copy.deepcopy(args._pci_routed_write_evidence)}
        observer = getattr(args, "_pci_routed_write_observer", None)
        if observer is not None:
            summary = journal_summary(observer.get("journal"))
            if summary["path"] is None and args.journal is not None:
                summary["path"] = str(Path(args.journal).absolute())
            if "journal_update_error" in observer:
                summary["update_error"] = copy.deepcopy(observer["journal_update_error"])
            payload["pci_routed_write_journal"] = summary
            if "baseline_evidence" in observer:
                payload["pci_routed_write_baseline_evidence"] = copy.deepcopy(observer["baseline_evidence"])
            if "receipt" in observer:
                payload["pci_routed_write_unaccepted_receipt"] = observer["receipt"].as_dict()
        return payload
    except BaseException:
        return {"pci_routed_write_evidence": {"complete": False, "evidence_export_failed": True}}
