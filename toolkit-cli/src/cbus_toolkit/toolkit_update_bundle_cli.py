"""CLI for exact-file update diagnostic provenance composition."""
from __future__ import annotations

from pathlib import Path

from .toolkit_update_bundle import MAX_REPORT_BYTES, compose_update_diagnostic_bundle
from .toolkit_update_conditions import MAX_JSON_BYTES
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
    command.add_argument("--catalogue-response", type=Path,
                         help="Exact raw catalogue HTTP response body used by both catalogue and metadata reports")
    command.add_argument("--revocation-input", type=Path,
                         help="Exact revocation data or raw API response used by the revocation report")
    command.add_argument("--conditions-input", type=Path,
                         help="Exact ClientConditionData JSON used by the condition report")
    command.add_argument("--context-input", type=Path,
                         help="Exact supplied context JSON used by the condition report")


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
    sources = {
        name: None if path is None else _read(path, limit)
        for name, path, limit in (
            ("catalogue_response", args.catalogue_response, MAX_REPORT_BYTES),
            ("revocation_input", args.revocation_input, MAX_REPORT_BYTES),
            ("conditions_input", args.conditions_input, MAX_JSON_BYTES),
            ("context_input", args.context_input, MAX_JSON_BYTES),
        )
    }
    result = compose_update_diagnostic_bundle(
        raw["catalogue"],
        raw["metadata"],
        raw["revocation"],
        raw["conditions"],
        node_id=args.node_id,
        catalogue_response_bytes=sources["catalogue_response"],
        revocation_input_bytes=sources["revocation_input"],
        conditions_input_bytes=sources["conditions_input"],
        context_input_bytes=sources["context_input"],
    )
    return result.as_dict(), int(not result.complete)
