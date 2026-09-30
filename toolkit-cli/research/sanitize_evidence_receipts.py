#!/usr/bin/env python3
"""Publish declared evidence derivatives without private runtime coordinates.

This post-processing seam does not execute a replay or change source fingerprints.
The unchanged family validators must accept both the raw and derivative receipts.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shlex
import stat
import sys
from typing import Callable


ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = ROOT.parent
MARKER = "publication_sanitization"
FORMAT = "cbus-evidence-sanitized-derivative-v1"
MAX_BYTES = 32 * 1024 * 1024
LOCAL_COORDINATE = re.compile(
    r"/(?:Users|Volumes|home|root|tmp|Applications|Library|System|opt|usr|srv|mnt|media|workspace)/"
    r"|/private/(?:tmp|var)/|/var/(?:folders|tmp)/"
    r"|/run/user/|~/|(?<![A-Za-z0-9])[A-Za-z]:[\\/]"
)
FORMATS = {
    "session": "cgate-session-differential-v2",
    "tagged": "cgate-tagged-session-differential-v1",
    "unit": "cgate-dbsetxml-unit-mapper-differential-v1",
}


def _pairs(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key in evidence")
        result[key] = value
    return result


def parse(raw: bytes) -> dict:
    if len(raw) > MAX_BYTES:
        raise ValueError("evidence exceeds the bounded input size")
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
                       parse_constant=lambda _: (_ for _ in ()).throw(
                           ValueError("nonfinite JSON value in evidence")))
    if not isinstance(value, dict) or MARKER in value:
        raise ValueError("expected a raw evidence object without a publication marker")
    return value


def local_coordinate_fields(value: object, pointer: str = "") -> list[str]:
    """Report JSON pointers only; never print rejected private values."""
    found = []
    if isinstance(value, dict):
        for key, child in value.items():
            escaped = key.replace("~", "~0").replace("/", "~1")
            if LOCAL_COORDINATE.search(key):
                found.append(pointer + "/<private-key>")
                escaped = "<private-key>"
            found.extend(local_coordinate_fields(child, pointer + "/" + escaped))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(local_coordinate_fields(child, pointer + "/" + str(index)))
    elif isinstance(value, str) and LOCAL_COORDINATE.search(value):
        found.append(pointer)
    return found


def _validator(kind: str) -> Callable[[dict], None]:
    # Importing these modules reads/validates retained evidence; their run/main
    # functions are never invoked by this helper.
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    if kind == "session":
        from research.cgate_session_differential import validate_passed_receipt
        return validate_passed_receipt
    if kind == "tagged":
        from research.cgate_tagged_session_differential import validate_passed_receipt
        return validate_passed_receipt
    if kind == "unit":
        from research.cgate_dbsetxml_unit_differential import validate_receipt
        return validate_receipt
    raise ValueError("unknown differential receipt family")


def _private_archive(raw: bytes, folder: Path, kind: str) -> str:
    folder = folder.resolve()
    if any((parent / ".git").exists() for parent in (folder, *folder.parents)):
        raise ValueError("raw evidence archive must be outside every Git checkout")
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    folder.chmod(0o700)
    digest = sha256(raw).hexdigest()
    target = folder / f"{kind}-{digest}.json"
    try:
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                             | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        descriptor = os.open(target, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "rb") as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode) or handle.read() != raw:
                raise ValueError("existing private raw archive does not match")
            os.fchmod(handle.fileno(), 0o600)
    else:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    if target.read_bytes() != raw:
        raise ValueError("private raw archive verification failed")
    return digest


def _template(command: str) -> tuple[str, list[str]]:
    """Normalize approved invocation path roles, keeping arguments and order."""
    if not isinstance(command, str) or not command.strip():
        raise ValueError("evidence lacks a nonempty command")
    tokens = shlex.split(command)
    if any(token in {";", "&&", "||", "|", ">", ">>", "<"} for token in tokens):
        raise ValueError("compound shell invocations require separate review")
    result = []
    roles = []
    for index, token in enumerate(tokens):
        if not LOCAL_COORDINATE.search(token):
            result.append(shlex.quote(token))
            continue
        previous = tokens[index - 1] if index else ""
        name = token.replace("\\", "/").rsplit("/", 1)[-1]
        if token.startswith("PYTHONPATH="):
            role, replacement = "acceptance_pythonpath", 'PYTHONPATH="${CBUS_ACCEPTANCE_PYTHONPATH}"'
        elif re.fullmatch(r"python(?:3(?:\.\d+)?)?(?:\.exe)?", name):
            role, replacement = "python_interpreter", '"${CBUS_EVIDENCE_PYTHON}"'
        elif previous in {"--mock-bin", "--cmqttd-bin"}:
            role = "cgate_mock_binary" if previous == "--mock-bin" else "cmqttd_binary"
            replacement = '"${CBUS_CGATE_MOCK_BIN}"' if previous == "--mock-bin" else '"${CBUS_CMQTTD_BIN}"'
        elif previous == "--output-dir":
            role, replacement = "report_output_directory", '"${CBUS_DIFFERENTIAL_OUTPUT_DIR}"'
        elif previous == "--output":
            if not re.fullmatch(r"[A-Za-z0-9_.-]+\.json", name):
                raise ValueError("unsupported report output name")
            role = "report_output_file"
            replacement = '"${CBUS_DIFFERENTIAL_OUTPUT_DIR}/' + name + '"'
        elif name in {"cgate_session_differential.py", "run_cgate_session_cmqttd_differential.py",
                      "cgate_tagged_session_differential.py", "cgate_dbsetxml_unit_differential.py"}:
            role, replacement = "research_script", "research/" + name
        elif re.fullmatch(r"test_[A-Za-z0-9_]+\.py", name) and "/tests/" in token.replace("\\", "/"):
            role, replacement = "acceptance_test_file", '"${CBUS_TEST_ROOT}/' + name + '"'
        else:
            raise ValueError("unrecognized private command path role")
        roles.append(role)
        result.append(replacement)
    if not roles:
        raise ValueError("command has no approved private path role to sanitize")
    return " ".join(result), sorted(set(roles))


def sanitize(raw: bytes, *, kind: str, private_raw_dir: Path) -> bytes:
    original = parse(raw)
    derivative = deepcopy(original)
    mappings = []
    validator = None
    if kind in FORMATS:
        if original.get("format") != FORMATS[kind]:
            raise ValueError("receipt family does not match its declared format")
        validator = _validator(kind)
        validator(original)
        product = original.get("product")
        if product not in {"cgate-mock", "cmqttd"}:
            raise ValueError("unsupported product identity")
        artifact_key = "binary" if kind == "unit" else "rust_artifact"
        artifact = derivative[artifact_key]
        path = artifact.pop("path", None)
        if not isinstance(path, str) or not path:
            raise ValueError("raw receipt lacks its artifact path")
        if "name" in artifact:
            raise ValueError("raw artifact already has a publication name")
        artifact["name"] = product
        mappings.append({"json_pointer": "/" + artifact_key + "/path",
                         "action": "omit", "roles": ["local_rust_binary_coordinate"],
                         "artifact_name_pointer": "/" + artifact_key + "/name"})
        derivative["command"], roles = _template(original["command"])
        mappings.append({"json_pointer": "/command", "action": "role_template",
                         "roles": roles})
        # Compare the entire technical payload, rather than a handpicked digest list.
        expected = deepcopy(original)
        expected[artifact_key].pop("path")
        expected[artifact_key]["name"] = product
        expected["command"] = derivative["command"]
    elif kind == "closure":
        if original.get("schema_version") != 1 or not isinstance(original.get("receipts"), list):
            raise ValueError("unsupported closure metadata document")
        expected = deepcopy(original)
        for index, receipt in enumerate(derivative["receipts"]):
            if not isinstance(receipt, dict) or not isinstance(receipt.get("integration"), dict):
                raise ValueError("closure receipt lacks integration metadata")
            commands = receipt["integration"].get("commands")
            if not isinstance(commands, list):
                raise ValueError("closure receipt lacks command metadata")
            for command_index, record in enumerate(commands):
                if not isinstance(record, dict) or not isinstance(record.get("command"), str) or not record["command"].strip():
                    raise ValueError("closure receipt lacks a nonempty command")
                if not LOCAL_COORDINATE.search(record["command"]):
                    continue
                record["command"], roles = _template(record["command"])
                expected["receipts"][index]["integration"]["commands"][command_index]["command"] = record["command"]
                mappings.append({"json_pointer": f"/receipts/{index}/integration/commands/{command_index}/command",
                                 "action": "role_template", "roles": roles})
        if not mappings:
            raise ValueError("closure metadata has no approved private commands")
    else:
        raise ValueError("unknown evidence kind")
    if derivative != expected:
        raise ValueError("sanitization changed the technical payload")
    remaining = local_coordinate_fields(derivative)
    if remaining:
        raise ValueError("unmapped local coordinates remain at " + ", ".join(remaining))
    if validator is not None:
        validator(derivative)
    raw_digest = _private_archive(raw, private_raw_dir, kind)
    derivative[MARKER] = {
        "format": FORMAT,
        "raw_file_sha256": raw_digest,
        "raw_retained_privately": True,
        "field_mapping": mappings,
        "command_form": "role-based reproduction template; exact invocation retained privately",
        "working_directory_role": "toolkit-cli; installed/source context remains in recorded scope",
        "technical_payload_preserved": True,
        "new_execution_claimed_by_sanitization": False,
    }
    if local_coordinate_fields(derivative):
        raise ValueError("publication marker contains local coordinates")
    return (json.dumps(derivative, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=(*FORMATS, "closure"), required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--private-raw-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        with args.input.open("rb") as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                raise ValueError("evidence input must be a regular file")
            raw = handle.read(MAX_BYTES + 1)
        derivative = sanitize(raw, kind=args.kind, private_raw_dir=args.private_raw_dir)
        args.output.write_bytes(derivative)
    except (ValueError, OSError, UnicodeError, KeyError, TypeError) as error:
        # Third-party validation errors can contain coordinates; suppress values.
        print(json.dumps({"result": "refused", "error_type": type(error).__name__}), file=sys.stderr)
        raise SystemExit(1) from None
    print(json.dumps({"result": "sanitized_derivative_written",
                      "raw_sha256": sha256(raw).hexdigest(),
                      "derivative_sha256": sha256(derivative).hexdigest(),
                      "new_execution_claimed": False}))


if __name__ == "__main__":
    main()
