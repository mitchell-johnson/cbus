"""Public CLI for one verified, catalogue-bound package download; no install."""
from __future__ import annotations

from pathlib import Path

from .toolkit_update_bundle import MAX_REPORT_BYTES
from .toolkit_update_download import MAX_CA_BYTES, download_update_package
from .toolkit_update_metadata import MAX_NODE_BYTES
from .toolkit_update_metadata_cli import _read
from .toolkit_update_package_file import MAX_PACKAGE_BYTES


def options(commands):
    command = commands.add_parser(
        "update-download",
        help="Download one catalogue-bound package file over verified TLS; never installs or runs it",
    )
    command.add_argument("--catalogue-report", type=Path, required=True,
                         help="Complete update-catalogue report JSON")
    command.add_argument("--catalogue-response", type=Path, required=True,
                         help="Exact raw catalogue response body described by that report")
    command.add_argument("--package", "--node-id", dest="node_id", required=True,
                         help="Unique catalogue package node ID")
    command.add_argument("--file-id", required=True, help="Unique file ID within that node")
    command.add_argument("--output", type=Path, required=True,
                         help="Existing directory; the output name must not already exist")
    command.add_argument("--ca-file", type=Path,
                         help="Trust only this PEM/DER CA bundle instead of system trust")
    command.add_argument("--timeout", type=float, default=60,
                         help="Seconds per blocking socket operation (0 < timeout <= 300)")
    command.add_argument("--max-package-bytes", type=int, default=MAX_PACKAGE_BYTES,
                         help="Hard cap for the declared and received size")


def run(args):
    if args.area != "update-download":
        raise ValueError("Unsupported update download command")
    report = download_update_package(
        _read(args.catalogue_report, MAX_REPORT_BYTES),
        _read(args.catalogue_response, MAX_NODE_BYTES),
        node_id=args.node_id,
        file_id=args.file_id,
        output_dir=args.output,
        ca_bytes=_read(args.ca_file, MAX_CA_BYTES) if args.ca_file is not None else None,
        timeout=args.timeout,
        max_package_bytes=args.max_package_bytes,
    )
    return report, int(report["outcome"] != "downloaded")
