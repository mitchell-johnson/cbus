"""Explicit local file I/O boundary for the standalone offline workflow CLI."""
from __future__ import annotations

import argparse
import hashlib
import importlib
import os
import stat
import sys
import uuid

from .cli_support import InputError, MAX_INPUT_BYTES, decode_json, json_bytes

ADAPTERS = {
    "copy-paste": "copy_paste_input",
    "neo-editor": "neo_editor_input",
    "catalogue-groups": "catalogue_groups_input",
    "discovery-session": "discovery_session_input",
    "transfer-restore": "transfer_restore_input",
}
OPERATIONS = ("inspect", "validate", "plan")


class FileBoundaryError(ValueError):
    def __init__(self, message, code="file_boundary"):
        super().__init__(message)
        self.code = code


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise InputError(message, "invalid_arguments")


def _parent_fd(path):
    """Open every parent without following symlinks; return pinned dir + name."""
    text = os.fspath(path)
    if not isinstance(text, str) or not text or "\0" in text or text == "-":
        raise FileBoundaryError("Supply an explicit regular-file path", "invalid_path")
    required = ("O_DIRECTORY", "O_NOFOLLOW", "O_NONBLOCK")
    if any(not hasattr(os, name) for name in required):
        raise FileBoundaryError("Safe regular-file boundaries are unavailable on this platform", "unsupported_platform")
    absolute = text if os.path.isabs(text) else os.path.join(os.getcwd(), text)
    parts = [part for part in absolute.split(os.sep) if part and part != "."]
    if not parts or text.endswith(os.sep) or ".." in parts:
        raise FileBoundaryError("Supply a filename without parent traversal", "invalid_path")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK
    parent = os.open(os.sep, flags)
    try:
        for part in parts[:-1]:
            next_parent = os.open(part, flags, dir_fd=parent)
            os.close(parent)
            parent = next_parent
        return parent, parts[-1]
    except BaseException:
        os.close(parent)
        raise


def _fingerprint(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def read_regular_input(path):
    """Read a bounded stable regular file without opening pipes/devices/links."""
    parent = source = None
    try:
        parent, name = _parent_fd(path)
        declared = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if not stat.S_ISREG(declared.st_mode):
            raise FileBoundaryError("Input must be a regular nonsymlink file", "invalid_input_file")
        source = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        before = os.fstat(source)
        if not stat.S_ISREG(before.st_mode):
            raise FileBoundaryError("Input must be a regular nonsymlink file", "invalid_input_file")
        if _fingerprint(declared) != _fingerprint(before):
            raise FileBoundaryError("Input changed before its snapshot was read", "input_changed")
        if before.st_size > MAX_INPUT_BYTES:
            raise InputError("Input exceeds the 4 MiB JSON limit", "input_too_large")
        chunks, size = [], 0
        while True:
            chunk = os.read(source, min(65536, MAX_INPUT_BYTES + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > MAX_INPUT_BYTES:
                raise InputError("Input exceeds the 4 MiB JSON limit", "input_too_large")
        after = os.fstat(source)
        named = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if (not stat.S_ISREG(named.st_mode) or _fingerprint(before) != _fingerprint(after)
                or _fingerprint(after) != _fingerprint(named) or size != before.st_size):
            raise FileBoundaryError("Input changed while its snapshot was read", "input_changed")
        return b"".join(chunks)
    except OSError as error:
        raise FileBoundaryError("Could not read a regular nonsymlink input file", "input_file_error") from error
    finally:
        if source is not None:
            os.close(source)
        if parent is not None:
            os.close(parent)


def write_new_output(path, payload):
    """Publish complete bytes by an exclusive same-directory hard link.

    Existing destinations, including links and special files, are never opened
    or overwritten. Failures before publication remove only the owned temporary.
    The final file and parent directory are synced before success is reported.
    """
    if type(payload) is not bytes:
        raise FileBoundaryError("Output must be complete serialized bytes", "invalid_output")
    parent = temporary = None
    temp_name = None
    owned_temp_identity = None
    published = False
    try:
        parent, name = _parent_fd(path)
        try:
            os.stat(name, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise FileBoundaryError("Output already exists; select a new filename", "output_exists")
        temp_name = ".cbus-offline-" + uuid.uuid4().hex + ".tmp"
        temporary = os.open(temp_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                            0o600, dir_fd=parent)
        owned = os.fstat(temporary)
        owned_temp_identity = (owned.st_dev, owned.st_ino)
        offset = 0
        while offset < len(payload):
            count = os.write(temporary, payload[offset:])
            if count <= 0:
                raise OSError("Incomplete output write")
            offset += count
        os.fsync(temporary)
        complete = os.fstat(temporary)
        named = os.stat(temp_name, dir_fd=parent, follow_symlinks=False)
        if (not stat.S_ISREG(named.st_mode) or _fingerprint(named) != _fingerprint(complete)
                or (named.st_dev, named.st_ino) != owned_temp_identity):
            raise FileBoundaryError("Output temporary changed before publication", "output_changed")
        os.link(temp_name, name, src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False)
        published = True
        final = os.stat(name, dir_fd=parent, follow_symlinks=False)
        current = os.fstat(temporary)
        if (not stat.S_ISREG(final.st_mode) or (final.st_dev, final.st_ino) != owned_temp_identity
                or (final.st_size, final.st_mtime_ns) != (complete.st_size, complete.st_mtime_ns)
                or (current.st_size, current.st_mtime_ns) != (complete.st_size, complete.st_mtime_ns)):
            raise FileBoundaryError("Output was published but its identity is unconfirmed; inspect it without retrying",
                                    "output_published_unconfirmed")
        named = os.stat(temp_name, dir_fd=parent, follow_symlinks=False)
        if (named.st_dev, named.st_ino) == owned_temp_identity:
            os.unlink(temp_name, dir_fd=parent)
            temp_name = None
        else:
            raise FileBoundaryError("Output was published but its temporary identity changed; inspect it without retrying",
                                    "output_published_unconfirmed")
        os.fsync(parent)
        os.close(temporary)
        temporary = None
    except FileExistsError as error:
        raise FileBoundaryError("Output already exists; select a new filename", "output_exists") from error
    except OSError as error:
        code = "output_published_unconfirmed" if published else "output_file_error"
        message = ("Output was published but final synchronization is unconfirmed; inspect it without retrying"
                   if published else "Could not publish a new output file atomically")
        raise FileBoundaryError(message, code) from error
    finally:
        if temporary is not None:
            os.close(temporary)
        if temp_name is not None and parent is not None and owned_temp_identity is not None:
            try:
                named = os.stat(temp_name, dir_fd=parent, follow_symlinks=False)
                if (named.st_dev, named.st_ino) == owned_temp_identity:
                    os.unlink(temp_name, dir_fd=parent)
            except OSError:
                pass
        if parent is not None:
            os.close(parent)


def _envelope(**fields):
    return {"format": "cbus-offline-workflows-cli-v1", "preparation_only": True,
            "execution_enabled": False, "native_execution_enabled": False,
            "original_compatibility_verified": False, "external_persistence_verified": False,
            **fields}


def evaluate_input(workflow, operation, document):
    """Dispatch one parsed document to its pure, preparation-only adapter."""
    if workflow not in ADAPTERS or operation not in OPERATIONS:
        raise InputError("Unknown workflow or offline operation", "invalid_arguments")
    adapter = importlib.import_module("." + ADAPTERS[workflow], __package__)
    try:
        result = adapter.evaluate(document, operation)
    except InputError:
        raise
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError, UnicodeError) as error:
        raise InputError("Invalid offline workflow input", "invalid_input") from error
    if (type(result) is not dict or result.get("workflow") != workflow
            or result.get("operation") != operation
            or type(result.get("validation_passed")) is not bool
            or result.get("outcome") not in ("prepared", "refused", "unsupported", "uncertain", "cancelled", "inspected")):
        raise InputError("Invalid offline adapter result", "invalid_report")
    return result


def _arguments(parser):
    parser.add_argument("workflow", choices=tuple(ADAPTERS))
    parser.add_argument("operation", choices=OPERATIONS)
    parser.add_argument("--input", required=True, metavar="REGULAR_JSON", help="Strict UTF-8 JSON regular file, at most 4 MiB; no stdin or symlinks.")
    parser.add_argument("--output", metavar="NEW_JSON", help="Publish a new complete JSON file atomically; existing paths are refused.")
    parser.add_argument("--compact", action="store_true", default=argparse.SUPPRESS, help="Emit one deterministic JSON line.")
    return parser


def options(commands):
    """Register the public command's help using the same offline arguments."""
    return _arguments(commands.add_parser(
        "offline-workflows", help="Inspect, validate or plan caller-file offline workflows; no backend execution",
        description="Inspect, validate or plan caller-supplied offline workflows. Proposed local policies only; no server, device execution or original compatibility acceptance."))


def main(argv=None, *, prog="python -m cbus_toolkit.offline_workflows"):
    parser = _arguments(_Parser(prog=prog, description="Inspect, validate or plan caller-supplied offline workflows under proposed local policies. No server/device execution or original compatibility acceptance."))
    try:
        arguments = parser.parse_args(argv)
        raw = read_regular_input(arguments.input)
        report = evaluate_input(arguments.workflow, arguments.operation, decode_json(raw))
        envelope = _envelope(workflow=arguments.workflow, operation=arguments.operation,
                             input_sha256=hashlib.sha256(raw).hexdigest(), report=report)
        payload = json_bytes(envelope, compact=getattr(arguments, "compact", False))
        if arguments.output is not None:
            write_new_output(arguments.output, payload)
        sys.stdout.write(payload.decode("ascii"))
        if report["outcome"] in ("inspected", "cancelled"):
            return 0
        if report["outcome"] in ("refused", "unsupported", "uncertain"):
            return 3
        return 0 if report["validation_passed"] is True else 3
    except InputError as error:
        failure = error
        status = 4 if error.code in ("output_too_large", "invalid_report") else 2
    except FileBoundaryError as error:
        failure = error
        status = 4
    except OSError:
        status = 4
        failure = FileBoundaryError("Could not emit the report", "report_io_error")
    sys.stderr.write(json_bytes(_envelope(error={"code": failure.code, "message": str(failure)}), compact=True).decode("ascii"))
    return status
