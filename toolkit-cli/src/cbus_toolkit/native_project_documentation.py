"""Document one fresh C-Gate database snapshot without changing server state.

This transports the existing native XML documentor. It does not scan devices,
load physical programming, or establish original Toolkit page/print parity.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import math
import os
from pathlib import Path
import re

from .addressing import _container
from .native import NativeDatabase
from .project import ProjectError
from .project_documentation import (
    PARITY, _write_new, default_output_name, encode, render,
    parse_report_network_selector, resolve_report_network_selector,
)
from .project_documentation_native import (
    MAX_SNAPSHOT_BYTES, _children, _scalar, build_native_model,
)
from .toolkit_database_csv_native import native_xml_reply_text

FORMAT = "cbus-native-project-documentation-v1"


def options(parser) -> None:
    parser.add_argument("--project", required=True, metavar="//PROJECT",
                        help="Project exported by one read-only DBGETXML request")
    parser.add_argument("--network", type=parse_report_network_selector, metavar="ADDRESS",
                        help="Document only this exact database Network Address from the snapshot")
    parser.add_argument("--output", type=Path,
                        help="New HTML file (default: <project TagName>.html); never overwrites")
    parser.add_argument("--generated-at", metavar="ISO",
                        help="Header date/time (default: command start time in UTC)")
    parser.add_argument("--catalog", type=Path,
                        help="cbusunits.xml for calculator lines; missing facts remain marked")


def _preflight(args):
    project = getattr(args, "project", None)
    if type(project) is not str or re.fullmatch(r"//[A-Za-z0-9_]{1,8}", project) is None:
        raise ValueError("--project requires one fully qualified project such as //TEST")
    host = getattr(args, "host", None)
    if type(host) is not str or not host:
        raise ValueError("C-Gate host is required")
    tls = getattr(args, "tls", False)
    if type(tls) is not bool:
        raise ValueError("TLS must be Boolean")
    port = (20123 if tls else 20023) if args.port is None else args.port
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("C-Gate port must be in 1..65535")
    if type(args.timeout) not in (int, float) or not math.isfinite(args.timeout) or args.timeout <= 0:
        raise ValueError("C-Gate timeout must be positive and finite")
    network = getattr(args, "network", None)
    if network is not None:
        if type(network) is int:
            if not 0 <= network <= 255:
                raise ValueError("--network must be an exact database Network Address")
        elif type(network) is str:
            from argparse import ArgumentTypeError
            try:
                network = parse_report_network_selector(network)
            except ArgumentTypeError as error:
                raise ValueError(str(error)) from error
        else:
            raise ValueError("--network must be an exact database Network Address")
    output = None if args.output is None else Path(args.output)
    if output is not None and os.path.lexists(output):
        raise FileExistsError("Output already exists: " + str(output))
    if args.generated_at is None:
        generated = datetime.now(timezone.utc).replace(tzinfo=None)
    else:
        try:
            generated = datetime.fromisoformat(args.generated_at)
        except (TypeError, ValueError) as error:
            raise ValueError("--generated-at must be an ISO date and time") from error
    catalog = None
    if args.catalog is not None:
        from .calculator import CalculatorCatalog
        catalog = CalculatorCatalog.load(Path(args.catalog))
    return project, port, network, output, generated, catalog


def _snapshot(reply) -> bytes:
    if getattr(reply, "code", None) != 344:
        raise ProjectError("DBGETXML did not finish with 344 End XML snippet")
    lines = getattr(reply, "lines", ())
    # CGateResponse removes command tags; keep the original XML frame itself
    # exact so an unrelated continuation cannot become a document snapshot.
    if (len(lines) < 3 or any(type(line) is not str for line in lines)
            or lines[0] != "343-Begin XML snippet"
            or lines[-1] != "344 End XML snippet"
            or any(not line.startswith("347-") for line in lines[1:-1])):
        raise ProjectError("DBGETXML requires complete 343/347/344 XML framing")
    raw = native_xml_reply_text(reply).encode("utf-8")
    if not 1 <= len(raw) <= MAX_SNAPSHOT_BYTES:
        raise ProjectError("DBGETXML snapshot exceeds the 16 MiB documentation bound")
    return raw


def live(args, client_factory, ssl_context):
    project, port, network, output, generated, catalog = _preflight(args)
    command = "DBGETXML " + project
    with client_factory(args.host, port, timeout=args.timeout, ssl_context=ssl_context,
                        max_line_bytes=MAX_SNAPSHOT_BYTES + 1024,
                        max_response_bytes=MAX_SNAPSHOT_BYTES + 1024 * 1024) as client:
        raw = _snapshot(NativeDatabase(client).get(project, xml=True))

    model = build_native_model(raw)
    # The display TagName is independent of Project.Address. Bind the latter
    # to the selected project rather than documenting a different reply tree.
    document = _container(raw.decode("utf-8-sig"), "Installation")
    node = _children(document.documentElement, "Project")[0]
    address = _scalar(node, "Address", required=True)
    if address.upper() != project[2:].upper():
        raise ProjectError("DBGETXML Project.Address differs from the selected project")
    if network is not None:
        network = resolve_report_network_selector(model, network)
    output = output if output is not None else default_output_name(model.name)
    text, summary = render(model, generated=generated,
                           networks=None if network is None else [network], catalog=catalog)
    payload = encode(text)
    _write_new(output, payload)
    return {
        "format": FORMAT,
        "project": {"name": model.name, "sha256": model.digest,
                    "bytes": model.size, "format": model.format},
        "source_snapshot": {"project": project, "command": command, "requests": 1,
                            "completion_code": 344, "sha256": hashlib.sha256(raw).hexdigest(),
                            "bytes": len(raw)},
        "file": str(output), "sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload),
        **summary, "output_complete": True, "native_database_mutated": False,
        "physical_programming_loaded": False, "network_open_requested": False,
        "project_save_requested": False, "parity": dict(PARITY),
    }, 0
