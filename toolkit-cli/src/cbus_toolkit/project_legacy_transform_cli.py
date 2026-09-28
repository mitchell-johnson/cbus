"""Exclusive file boundary for the bounded legacy project version transform."""
from __future__ import annotations

import copy
import os
from pathlib import Path
import stat

from .project_legacy_transform import transform_repaired_legacy_project
from .project_repair import DEFAULT_MAX_BYTES


def options(commands):
    parser = commands.add_parser(
        "transform-legacy", help="Convert a repaired DBVersion 2.2 XML file to 2.3 in a new file"
    )
    parser.add_argument("file", type=Path)
    parser.add_argument("--output", type=Path, help="New output path; existing files are never replaced")
    parser.add_argument("--dry-run", action="store_true", help="Validate and hash without creating a file")
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)


class LegacyProjectTransformFileError(ValueError):
    def __init__(self, cause: Exception, evidence: dict):
        super().__init__(str(cause))
        self.original_error = cause
        self.details = evidence


class LegacyProjectTransformFileOperation:
    def __init__(self):
        self.last_error = None
        self.last_evidence = None

    def run(self, source, *, output=None, dry_run=False, max_bytes=DEFAULT_MAX_BYTES):
        self.last_error = self.last_evidence = None
        state = {
            "operation": "project-transform-legacy", "stage": "validate", "complete": False,
            "source": None, "output": None, "dry_run": dry_run if type(dry_run) is bool else None,
            "source_bytes": 0, "source_closed": False,
            "output_create_attempted": False, "output_may_exist": False,
            "output_created": False,
            "output_bytes_confirmed": 0, "output_closed": False, "output_fsync_succeeded": False,
            "output_may_be_partial": False, "source_modified": False,
            "native_load_verified": False, "physical_io_attempted": False,
            "transform": None, "error": None, "cleanup_errors": [],
        }
        handles = {"source": None, "output": None}
        primary = None

        def close(which):
            handle = handles[which]
            if handle is not None:
                handles[which] = None
                os.close(handle)
                state[which + "_closed"] = True

        try:
            if type(dry_run) is not bool:
                raise ValueError("dry_run must be a boolean")
            if type(max_bytes) is not int or not 1 <= max_bytes <= 64 * 1024 * 1024:
                raise ValueError("max_bytes must be an integer from 1 to 67108864")
            if output is None and not dry_run:
                raise ValueError("--output is required unless --dry-run is selected")
            source = Path(source)
            output = Path(output) if output is not None else None
            state.update(source=str(source), output=str(output) if output is not None else None)
            state["stage"] = "source_stat"
            if not stat.S_ISREG(os.lstat(source).st_mode):
                raise ValueError("Source must be a regular file, not a symlink or special file")
            state["stage"] = "source_open"
            flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
            handles["source"] = os.open(source, flags)
            info = os.fstat(handles["source"])
            if not stat.S_ISREG(info.st_mode):
                raise ValueError("Opened source is not a regular file")
            if info.st_size > max_bytes:
                raise ValueError("Source exceeds max_bytes")
            state["stage"] = "source_read"
            chunks = []
            while True:
                chunk = os.read(handles["source"], min(65536, max_bytes - state["source_bytes"] + 1))
                if type(chunk) is not bytes:
                    raise TypeError("Source reader must return bytes")
                if not chunk:
                    break
                state["source_bytes"] += len(chunk)
                if state["source_bytes"] > max_bytes:
                    raise ValueError("Source grew beyond max_bytes while reading")
                chunks.append(chunk)
            state["stage"] = "source_close"
            close("source")
            state["stage"] = "transform"
            converted = transform_repaired_legacy_project(b"".join(chunks), max_bytes=max_bytes)
            state["transform"] = converted.as_dict()
            if not dry_run:
                state.update(stage="output_create", output_create_attempted=True,
                             output_may_exist=True)
                handles["output"] = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o666)
                state["output_created"] = True
                state["stage"] = "output_write"
                data = memoryview(converted.transformed_xml)
                while state["output_bytes_confirmed"] < len(data):
                    remaining = data[state["output_bytes_confirmed"]:]
                    written = os.write(handles["output"], remaining)
                    if type(written) is not int or not 0 < written <= len(remaining):
                        raise OSError("Output writer returned an invalid or zero byte count")
                    state["output_bytes_confirmed"] += written
                state["stage"] = "output_fsync"
                os.fsync(handles["output"])
                state["output_fsync_succeeded"] = True
                state["stage"] = "output_close"
                close("output")
            state.update(stage="complete", complete=True)
        except BaseException as error:
            primary = error
        finally:
            for which in ("output", "source"):
                if handles[which] is not None:
                    try:
                        close(which)
                    except BaseException as error:
                        state["cleanup_errors"].append({"resource": which, "type": type(error).__name__})
                        if primary is None:
                            primary = error
        if primary is not None:
            state.update(complete=False, output_may_be_partial=state["output_create_attempted"],
                         error={"type": type(primary).__name__, "message": str(primary)[:4096]})
        self.last_evidence = copy.deepcopy(state)
        if primary is not None:
            if not isinstance(primary, Exception):
                self.last_error = primary
                raise primary
            wrapped = LegacyProjectTransformFileError(primary, state)
            self.last_error = wrapped
            raise wrapped from primary
        return state


def run(args):
    operation = LegacyProjectTransformFileOperation()
    args._legacy_project_transform_operation = operation
    return operation.run(args.file, output=args.output, dry_run=args.dry_run,
                         max_bytes=args.max_bytes), 0


def error_payload(error, args):
    if getattr(args, "area", None) != "project" or getattr(args, "action", None) != "transform-legacy":
        return {}
    operation = getattr(args, "_legacy_project_transform_operation", None)
    if operation is not None and operation.last_error is error and isinstance(operation.last_evidence, dict):
        return {"project_legacy_transform_evidence": copy.deepcopy(operation.last_evidence)}
    return {}
