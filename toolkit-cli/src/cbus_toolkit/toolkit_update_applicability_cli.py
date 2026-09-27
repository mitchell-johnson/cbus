"""Public offline preflight for the captured SESU applicability branch."""
from __future__ import annotations

from pathlib import Path

from .toolkit_update_applicability import PLATFORMS, inspect_update_applicability
from .toolkit_update_metadata import MAX_NODE_BYTES, validate_context, validate_node_id
from .toolkit_update_metadata_cli import _read


def options(commands):
    command = commands.add_parser(
        "update-applicability-preflight",
        help="Inspect one untrusted catalogue node under an explicit UTC/platform context; no publisher or install trust",
    )
    command.add_argument("--catalogue-response", type=Path, required=True,
                         help="Exact raw catalogue response body")
    command.add_argument("--node-id", required=True, help="Unique catalogue node ID")
    command.add_argument("--platform", choices=PLATFORMS, required=True,
                         help="Explicit original Windows file-selection target")
    command.add_argument("--at-utc", required=True,
                         help="Explicit evaluation instant YYYY-MM-DDTHH:MM:SS[.fffffff]Z")


def run(args):
    if args.area != "update-applicability-preflight":
        raise ValueError("Unsupported applicability-preflight command")
    validate_node_id(args.node_id)
    validate_context(args.at_utc)
    source = _read(args.catalogue_response, MAX_NODE_BYTES)
    result = inspect_update_applicability(
        source, node_id=args.node_id, platform=args.platform, at_utc=args.at_utc,
    )
    return result.as_dict(), {"passed": 0, "failed": 1, "unsupported": 2}[result.status]
