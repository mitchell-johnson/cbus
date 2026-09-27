"""CLI adapter for guarded physical PP inspection and editing."""
from __future__ import annotations

from .physical_programming import (
    PhysicalProgramming,
    SUPPORTED_METHODS,
    physical_unit_path,
)


def options(parser) -> None:
    actions = parser.add_subparsers(dest="remote_action", required=True)

    inspect = actions.add_parser(
        "inspect",
        help="LOAD one physical unit and read parameters for one programming method",
    )
    inspect.add_argument("source", type=physical_unit_path)
    inspect.add_argument("--method", choices=SUPPORTED_METHODS, required=True)
    inspect.add_argument(
        "--parameter",
        action="append",
        help="Read this parameter; repeat as needed (default: every parameter using --method)",
    )

    apply = actions.add_parser(
        "apply",
        help="LOAD, edit, save once, then verify through a fresh physical LOAD",
    )
    apply.add_argument("source", type=physical_unit_path)
    apply.add_argument("--method", choices=SUPPORTED_METHODS, required=True)
    apply.add_argument(
        "--set",
        dest="edits",
        action="append",
        nargs=2,
        metavar=("PARAMETER", "VALUE"),
        required=True,
        help="Stage one native parameter value; repeat within the same owned PP session",
    )
    apply.add_argument(
        "--destination",
        type=physical_unit_path,
        help="Use native PP SAVE to this physical unit; omission uses PP SAVE_TO_SOURCE",
    )
    apply.add_argument(
        "--dry-run",
        action="store_true",
        help="LOAD, stage and read back in the temporary session without SAVE",
    )


def run(args, client):
    workflow = PhysicalProgramming(client)
    if args.remote_action == "inspect":
        return workflow.inspect(
            args.source,
            method=args.method,
            parameters=args.parameter,
        ), 0
    if args.remote_action == "apply":
        return workflow.apply(
            args.source,
            args.edits,
            method=args.method,
            destination=args.destination,
            dry_run=args.dry_run,
        ), 0
    raise ValueError("Unknown physical PP action")
