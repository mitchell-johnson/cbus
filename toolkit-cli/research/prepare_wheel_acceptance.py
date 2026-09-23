#!/usr/bin/env python3
"""Freeze a matching wheel, test suite and local harnesses for installed tests."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import zipfile

from acceptance import ROOT, hashes, input_files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path)
    parser.add_argument("--output", type=Path, help="New directory; defaults to a wheel-hash directory under research/runtime")
    args = parser.parse_args()
    wheel = args.wheel.resolve()
    wheel_hash = hashlib.sha256(wheel.read_bytes()).hexdigest()
    output = (args.output or ROOT / "research/runtime" / ("wheel-acceptance-" + wheel_hash[:12])).resolve()
    if output.exists():
        parser.error("Snapshot already exists; choose a new output directory")
    with zipfile.ZipFile(wheel) as archive:
        names = [name for name in archive.namelist() if name.startswith("cbus_toolkit/")]
        expected = {"cbus_toolkit/" + path.name: path for path in (ROOT / "src/cbus_toolkit").iterdir()
                    if path.is_file() and path.suffix in (".py", ".json")}
        if len(names) != len(set(names)) or set(names) != set(expected):
            parser.error("Wheel package files differ from the local source package")
        payloads = {name: archive.read(name) for name in names}
        if any(payloads[name] != path.read_bytes() for name, path in expected.items()):
            parser.error("Wheel package content differs from the local source; rebuild the wheel")
    paths = input_files("test_*.py")
    paths.update(path for path in (ROOT / name for name in ("README.md", "COPYING", "COPYING.LESSER")) if path.is_file())
    before = hashes(paths)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="wheel-snapshot-", dir=output.parent) as temporary:
        stage = Path(temporary) / "snapshot"
        stage.mkdir()
        for path in sorted(paths):
            relative = path.relative_to(ROOT)
            destination = stage / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(payloads["cbus_toolkit/" + path.name] if relative.parts[:2] == ("src", "cbus_toolkit") else path.read_bytes())
        if hashes(paths) != before or set(input_files("test_*.py")) - paths:
            parser.error("Source or harness inputs changed during snapshot creation")
        copied = {str(path.relative_to(stage)): hashlib.sha256(path.read_bytes()).hexdigest()
                  for path in stage.rglob("*") if path.is_file()}
        if copied != before:
            parser.error("Copied snapshot differs from its source hashes")
        vendor = ROOT / "research/vendor"
        if vendor.is_dir():
            (stage / "research/vendor").symlink_to(vendor, target_is_directory=True)
        copied_wheel = stage / wheel.name
        shutil.copyfile(wheel, copied_wheel)
        if hashlib.sha256(copied_wheel.read_bytes()).hexdigest() != wheel_hash:
            parser.error("Wheel changed during snapshot creation")
        manifest = {"format": "cbus-installed-wheel-snapshot-v1", "wheel": wheel.name,
                    "wheel_sha256": wheel_hash, "package_files": sorted(names), "input_sha256": before,
                    "vendor_files": "Operator-owned vendor directory linked read-only by native test runners; not copied or packaged",
                    "scope": "Snapshot preparation is not test success or Toolkit parity"}
        (stage / "snapshot.json").write_text(json.dumps(manifest, indent=2) + "\n")
        stage.rename(output)
    print(json.dumps({"snapshot": str(output), "wheel_sha256": wheel_hash, "package_files": len(names),
                      "test_files": len(list((output / "tests").glob("test_*.py")))}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
