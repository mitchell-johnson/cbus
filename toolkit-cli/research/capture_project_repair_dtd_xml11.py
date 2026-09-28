#!/usr/bin/env python3
"""Capture the XML 1.1/internal-DTD intersection from pinned C-Gate methods."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

from project_repair_original import run_original


SOURCES = {
    "plain": b'<?xml version="1.1"?><!DOCTYPE Project [<!ENTITY x "OK">]><Project>&x;</Project>',
    "quoted-gt": b'<?xml version="1.1"?><!DOCTYPE Project [<!ENTITY x "A>B">]><Project>&x;</Project>',
    "c0-entity": b'<?xml version="1.1"?><!DOCTYPE Project [<!ENTITY x "&#x1f;">]><Project>&x;</Project>',
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--java", type=Path, required=True)
    parser.add_argument("--javac", type=Path, required=True)
    parser.add_argument("--vendor", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    cases = [
        {"id": f"{name}-{operation}", "input_hex": source.hex(), "operation": operation}
        for name, source in SOURCES.items()
        for operation in ("repair", "tidy", "full")
    ]
    report = run_original(cases, java=args.java, javac=args.javac, vendor=args.vendor)
    assert report["java_exit_code"] == 0 and report["temporary_directory_removed"]
    rows = [{**case, **native} for case, native in zip(cases, report["rows"])]
    fixture = {
        "format": "cbus-project-repair-dtd-xml11-original-v1",
        "captured_utc": datetime.now(timezone.utc).isoformat(),
        "capture_script_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
        "source_pins": {Path(path).name: digest for path, digest in report["inputs"].items()},
        "probe_class_sha256": report["class_sha256"],
        "stdout_sha256": report["stdout_sha256"],
        "stderr_sha256": report["stderr_sha256"],
        "java_exit_code": report["java_exit_code"],
        "temporary_directory_removed": report["temporary_directory_removed"],
        "rows": rows,
    }
    args.output.write_text(json.dumps(fixture, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
