"""Saved-project route admission shared by typed routed RECALL and IDENTIFY."""
from __future__ import annotations

import argparse
from pathlib import Path
import re

from .commissioning_route import (
    CommissioningRoutePlan,
    assert_fresh_project,
    plan_commissioning_route,
    project_sha256,
    read_project_snapshot,
)
from .pci_routed_recall import RoutedReplyPath
from .project import ProjectDocument


def sha256_argument(text: str) -> str:
    if type(text) is not str or not re.fullmatch(r"[0-9A-Fa-f]{64}", text):
        raise argparse.ArgumentTypeError("Expected exactly 64 hexadecimal SHA-256 characters")
    return text.lower()


def add_route_options(parser: argparse.ArgumentParser) -> None:
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--project-file", type=Path,
                      help="Legacy XML/CBZ project used to resolve and bind the typed topology")
    from .pci_routing_cli import _byte
    mode.add_argument("--expected-source", type=_byte,
                      help="Raw mode: explicit outer source byte of the expected reply")
    parser.add_argument("--source-network", type=_byte,
                        help="Typed mode: network attached to this PCI/CNI")
    parser.add_argument("--target-network", type=_byte,
                        help="Typed mode: logical network containing UNIT")
    parser.add_argument("--project-name",
                        help="Typed mode: require this exact project TagName")
    parser.add_argument("--project-sha256", type=sha256_argument,
                        help="Typed mode: require this exact project-file snapshot")
    parser.add_argument("--bridge", type=_byte, action="append", default=[],
                        help="Raw mode: outgoing bridge byte; repeat in nearest-first order")
    parser.add_argument("--expected-destination", type=_byte,
                        help="Raw mode: explicit destination byte of the expected reply")
    parser.add_argument("--expected-route", type=_byte, action="append", default=[],
                        help="Raw mode: expected incoming route byte; repeat in received order")


def resolve_route(args) -> tuple[tuple[int, ...], RoutedReplyPath, CommissioningRoutePlan | None]:
    """Resolve route before I/O, preserving independent raw and typed modes."""
    if args.project_file is None:
        if args.local_unit is not None:
            raise ValueError("--local-unit is reserved for typed routed reads; raw mode supplies the reply path")
        if args.source_network is not None or args.target_network is not None:
            raise ValueError("Raw routed read does not accept typed network selectors")
        if args.project_name is not None or args.project_sha256 is not None:
            raise ValueError("Raw routed read does not accept project identity options")
        if args.expected_destination is None:
            raise ValueError("Raw routed read requires --expected-destination")
        return tuple(args.bridge), RoutedReplyPath(
            args.expected_source, args.expected_destination, tuple(args.expected_route)), None

    if args.local_unit is None:
        raise ValueError("Typed routed read requires --local-unit")
    if args.source_network is None or args.target_network is None:
        raise ValueError("Typed routed read requires --source-network and --target-network")
    if args.bridge or args.expected_destination is not None or args.expected_route:
        raise ValueError("Typed routed read does not accept raw route expectation options")
    snapshot = read_project_snapshot(args.project_file)
    digest = project_sha256(snapshot)
    if args.project_sha256 is not None and args.project_sha256 != digest:
        raise ValueError(
            f"Project snapshot SHA-256 mismatch: expected {args.project_sha256}, got {digest}")
    project = ProjectDocument.from_snapshot(snapshot, source=args.project_file)
    plan = plan_commissioning_route(
        project,
        project_digest=digest,
        source_network=args.source_network,
        target_network=args.target_network,
        target_unit=args.unit,
        local_unit=args.local_unit,
        expected_project_name=args.project_name,
    )
    return plan.bridges, plan.expected, plan


def assert_route_fresh(args, plan: CommissioningRoutePlan) -> None:
    """Recheck the exact file bytes at the one-shot transport handoff."""
    assert_fresh_project(args.project_file, plan.project_sha256)
