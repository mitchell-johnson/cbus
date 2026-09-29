"""CLI adapters for keyboard-wedge barcode parsing and offline unit creation."""
from __future__ import annotations

import os
from pathlib import Path
import sys

from .barcode_scanner import BarcodeCatalog, BarcodeError, add_unit, parse, wedge_lines


def options(commands) -> None:
    parser = commands.add_parser("barcode", help="Interpret C-Bus barcode scanner text with Toolkit 1.18 rules")
    actions = parser.add_subparsers(dest="action", required=True)
    parse_parser = actions.add_parser("parse", help="Classify scans for the Units view and unit dialogs; no files change")
    parse_parser.add_argument("text", nargs="?", help="Scanner text; omit to read keyboard-wedge lines from stdin")


def project_options(ops) -> None:
    from .cli import _byte

    parser = ops.add_parser("add-unit", help="Add a unit from a C-Bus software configuration barcode (Units view F10)")
    parser.add_argument("file", type=Path)
    parser.add_argument("--network", type=_byte, required=True, help="Network address whose Units node receives the scan")
    parser.add_argument("--barcode", required=True, help="Scanned text, or - to read exactly one wedge line from stdin")
    parser.add_argument("--catalog", type=Path, default=os.environ.get("CBUS_UNIT_CATALOG"),
                        help="CBusUnits catalogue (cbusunits.xml); defaults to CBUS_UNIT_CATALOG")
    parser.add_argument("--address", type=_byte, help="Tag Name dialog address instead of the next free address")
    parser.add_argument("--tag-name", help="Tag Name dialog text (default NEWUNIT)")
    parser.add_argument("--output", type=Path, help="Write to a copy instead of updating the input file")


def _scans(text: str | None) -> list[str]:
    raw = sys.stdin.read() if text is None or text == "-" else text
    return wedge_lines(raw)


def run(args):
    scans = _scans(args.text)
    if not scans:
        raise BarcodeError("No scan: the input is empty after removing carriage returns", code="empty_input")
    return {"count": len(scans), "scans": [parse(scan) for scan in scans]}, 0


def run_add_unit(args):
    from .project import ProjectDocument

    scans = _scans(args.barcode) if args.barcode == "-" else wedge_lines(args.barcode)
    if len(scans) != 1:
        raise BarcodeError("Supply exactly one nonempty scan", code="invalid_input", scans=len(scans))
    if args.catalog is None:
        raise ValueError("Use --catalog or CBUS_UNIT_CATALOG to locate cbusunits.xml")
    catalog = BarcodeCatalog.load(args.catalog)
    document = ProjectDocument.load(args.file)
    result = add_unit(document, f"/network/{args.network}", scans[0], catalog,
                      address=args.address, tag_name=args.tag_name)
    saved = document.save(args.output or args.file) if result["changed"] else None
    return {"file": saved, "result": result}, 0
