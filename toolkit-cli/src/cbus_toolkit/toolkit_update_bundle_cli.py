"""CLI for exact-file update diagnostic provenance composition."""
from __future__ import annotations

from pathlib import Path

from .toolkit_update_bundle import MAX_REPORT_BYTES, compose_update_diagnostic_bundle
from .toolkit_update_metadata import validate_node_id
from .toolkit_update_metadata_cli import _read


def options(commands):
    command = commands.add_parser(
        "update-diagnostic-bundle",
        help=(
            "Link exact catalogue, metadata, revocation and condition report files "
            "without claiming update trust or availability"
        ),
    )
    command.add_argument("--catalogue", type=Path, required=True)
    command.add_argument("--metadata", type=Path, required=True)
    command.add_argument("--revocation", type=Path, required=True)
    command.add_argument("--conditions", type=Path, required=True)
    command.add_argument("--node-id", required=True)


def run(args):
    if args.area != "update-diagnostic-bundle":
        raise ValueError("Unsupported update diagnostic bundle command")
    validate_node_id(args.node_id)
    paths = {
        "catalogue": args.catalogue,
        "metadata": args.metadata,
        "revocation": args.revocation,
        "conditions": args.conditions,
    }
    raw = {name: _read(path, MAX_REPORT_BYTES) for name, path in paths.items()}
    result = compose_update_diagnostic_bundle(
        raw["catalogue"],
        raw["metadata"],
        raw["revocation"],
        raw["conditions"],
        node_id=args.node_id,
    )
    return result.as_dict(), int(not result.complete)
