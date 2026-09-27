"""Public offline CLI for a local SESU package-file descriptor receipt."""
from __future__ import annotations

from pathlib import Path

from .toolkit_update_metadata import MAX_NODE_BYTES, validate_node_id
from .toolkit_update_metadata_cli import _read
from .toolkit_update_package_file import MAX_PACKAGE_BYTES, inspect_update_package_file


def options(commands):
    command = commands.add_parser(
        "update-package-file",
        help="Compare one local file with an untrusted SESU catalogue descriptor; no download or install",
    )
    command.add_argument("--catalogue-response", type=Path, required=True,
                         help="Exact raw catalogue response body")
    command.add_argument("--node-id", required=True,
                         help="Unique catalogue node ID")
    command.add_argument("--file-id", required=True,
                         help="Unique file ID within that node")
    command.add_argument("--package-path", type=Path, required=True,
                         help="Already-local regular package file")
    command.add_argument("--max-package-bytes", type=int, default=MAX_PACKAGE_BYTES,
                         help="Positive maximum for the declared and observed file size")


def run(args):
    if args.area != "update-package-file":
        raise ValueError("Unsupported package-file command")
    validate_node_id(args.node_id)
    if type(args.max_package_bytes) is not int or not 0 < args.max_package_bytes <= MAX_PACKAGE_BYTES:
        raise ValueError("max_package_bytes must be a positive signed Int32 bound")
    catalogue_response = _read(args.catalogue_response, MAX_NODE_BYTES)
    receipt = inspect_update_package_file(
        catalogue_response,
        node_id=args.node_id,
        file_id=args.file_id,
        package_path=args.package_path,
        max_package_bytes=args.max_package_bytes,
    )
    return receipt.as_dict(), int(not receipt.bytes_match_catalogue_descriptor)
