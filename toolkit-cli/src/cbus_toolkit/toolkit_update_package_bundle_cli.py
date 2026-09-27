"""Public offline CLI for exact diagnostic-to-package source linkage."""
from __future__ import annotations

from pathlib import Path

from .toolkit_update_bundle import MAX_REPORT_BYTES
from .toolkit_update_conditions import MAX_JSON_BYTES
from .toolkit_update_metadata import MAX_CERTIFICATE_BYTES
from .toolkit_update_metadata_cli import _read
from .toolkit_update_package_bundle import compose_update_package_bundle
from .toolkit_update_package_file import MAX_PACKAGE_BYTES


def options(commands):
    command = commands.add_parser(
        "update-package-bundle",
        help="Reproduce update diagnostics and one local package receipt against exact source files",
    )
    for name in ("catalogue", "metadata", "revocation", "conditions"):
        command.add_argument("--" + name, type=Path, required=True)
    command.add_argument("--diagnostic-bundle", type=Path, required=True)
    command.add_argument("--package-receipt", type=Path, required=True)
    command.add_argument("--catalogue-response", type=Path, required=True)
    command.add_argument("--revocation-input", type=Path, required=True)
    command.add_argument("--conditions-input", type=Path, required=True)
    command.add_argument("--context-input", type=Path, required=True)
    command.add_argument("--metadata-certificate", type=Path)
    command.add_argument("--revocation-signer-certificate", type=Path)
    command.add_argument("--node-id", required=True)
    command.add_argument("--file-id", required=True)
    command.add_argument("--package-path", type=Path, required=True)
    command.add_argument("--max-package-bytes", type=int, default=MAX_PACKAGE_BYTES)


def run(args):
    if args.area != "update-package-bundle":
        raise ValueError("Unsupported update package bundle command")
    reports = {
        name: _read(getattr(args, name), MAX_REPORT_BYTES)
        for name in ("catalogue", "metadata", "revocation", "conditions")
    }
    sources = {
        name: _read(getattr(args, name), limit)
        for name, limit in (
            ("catalogue_response", MAX_REPORT_BYTES),
            ("revocation_input", MAX_REPORT_BYTES),
            ("conditions_input", MAX_JSON_BYTES),
            ("context_input", MAX_JSON_BYTES),
        )
    }
    for name in ("metadata_certificate", "revocation_signer_certificate"):
        path = getattr(args, name)
        sources[name] = None if path is None else _read(path, MAX_CERTIFICATE_BYTES)
    result = compose_update_package_bundle(
        reports["catalogue"],
        reports["metadata"],
        reports["revocation"],
        reports["conditions"],
        _read(args.diagnostic_bundle, MAX_REPORT_BYTES),
        _read(args.package_receipt, MAX_REPORT_BYTES),
        catalogue_response_bytes=sources["catalogue_response"],
        revocation_input_bytes=sources["revocation_input"],
        conditions_input_bytes=sources["conditions_input"],
        context_input_bytes=sources["context_input"],
        metadata_certificate_bytes=sources["metadata_certificate"],
        revocation_signer_certificate_bytes=sources["revocation_signer_certificate"],
        node_id=args.node_id,
        file_id=args.file_id,
        package_path=args.package_path,
        max_package_bytes=args.max_package_bytes,
    )
    return result.as_dict(), int(not result.complete)
