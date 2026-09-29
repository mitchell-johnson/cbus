#!/usr/bin/env python3
"""Rebuild the private installer audit from Setup.exe and compare it to the pins.

The fixed chain is: the Toolkit Inno Setup installer is unpacked with
innoextract into ``extracted-20260926``; its nested C-Gate Inno Setup installer
(``tmp/cgate-...-setup.exe``) is unpacked into ``cgate-extracted-20260926``; and
the Toolkit CHM is unpacked with 7-Zip into ``help-20260926``. Every
installer-rooted record in ``original-artifact-provenance.json`` is then
recomputed from the rebuilt tree. Nothing is executed from the installer, and
the printed receipt contains only tool versions, digests and counts.

This checks extraction reproducibility, not publisher signatures. Authenticode
verification needs a verifier this runner does not provide; see
docs/original-artifact-provenance.md.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys


SOURCE = Path(__file__).with_name("pin_original_artifacts.py")
SPEC = importlib.util.spec_from_file_location("pin_original_artifacts", SOURCE)
assert SPEC and SPEC.loader
pin = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pin)

FORMAT = "cbus-installer-extraction-receipt-v1"
TOOLKIT_SETUP_SHA256 = "34811c4837ab484061760ebe8b02d059c59b57d8a40a8324391aa1bdd12f9c41"
NESTED_CGATE = "extracted-20260926/tmp/cgate-3.4.0_2001-JRE-11.0.24_8-setup.exe"
HELP_CHM = "extracted-20260926/app/Toolkit Help.chm"


def _tool(name: str) -> tuple[str, dict[str, str]]:
    path = shutil.which(name)
    if path is None:
        raise pin.PinError(f"Required extraction tool is missing: {name}")
    probe = [path, "--version"] if name == "innoextract" else [path]
    result = subprocess.run(probe, capture_output=True, text=True, check=False)
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        raise pin.PinError(f"Cannot identify extraction tool version: {name}")
    return path, {"name": name, "version": lines[0], "sha256": pin._sha_file(Path(path).resolve())[1]}


def _run(command: list[str]) -> None:
    result = subprocess.run(command, capture_output=True, check=False)
    if result.returncode:
        raise pin.PinError(f"Extraction step failed: {Path(command[0]).name} exited {result.returncode}")


def compare(manifest: dict, root: Path) -> dict[str, int]:
    """Recompute every installer-rooted manifest record from ``root``."""
    records = [record for record in manifest["artifacts"] if record["root"] == "installer"]
    if not records:
        raise pin.PinError("Manifest has no installer-rooted records")
    mismatched = []
    for record in records:
        path = pin._member(root, record["path"], directory=record["kind"] != "file")
        if record["kind"] == "file":
            size, digest = pin._sha_file(path)
            fresh = {**record, "size_bytes": size, "sha256": digest}
        else:
            fresh = {**record, **pin._tree(path, flat_binaries=record["kind"] == "flat-exe-dll")}
        if fresh != record:
            mismatched.append(record["id"])
    if mismatched:
        raise pin.PinError("Reproduced extraction differs from the pins: " + ", ".join(mismatched))
    return {"records": len(records),
            "files": sum(1 if r["kind"] == "file" else r["file_count"] for r in records)}


def reproduce(setup: Path, output: Path, manifest: dict) -> dict[str, object]:
    size, digest = pin._sha_file(setup)
    if digest != TOOLKIT_SETUP_SHA256:
        raise pin.PinError("Setup.exe is not the pinned Toolkit 1.18.0.2754 installer")
    if output.exists() and any(output.iterdir()):
        raise pin.PinError("Output directory must be absent or empty")
    innoextract, inno = _tool("innoextract")
    sevenzip, seven = _tool("7zz")
    output.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(setup, output / "setup.exe")
    _run([innoextract, "--silent", "-d", str(output / "extracted-20260926"), str(output / "setup.exe")])
    nested = pin._member(output, NESTED_CGATE, directory=False)
    _run([innoextract, "--silent", "-d", str(output / "cgate-extracted-20260926"), str(nested)])
    chm = pin._member(output, HELP_CHM, directory=False)
    _run([sevenzip, "x", "-y", "-bso0", "-bsp0", str(chm), "-o" + str(output / "help-20260926")])
    return {"format": FORMAT, "setup_sha256": digest, "setup_bytes": size,
            "tools": [inno, seven], "compared": compare(manifest, output), "identical": True}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--setup", required=True, type=Path, help="private Toolkit Setup.exe")
    parser.add_argument("--output", required=True, type=Path, help="new private installer-audit root")
    parser.add_argument("--manifest", type=Path, default=pin.MANIFEST)
    args = parser.parse_args(argv)
    try:
        receipt = reproduce(args.setup, args.output, pin._strict_json(args.manifest))
    except OSError:
        print("installer extraction failed: a private input could not be read", file=sys.stderr)
        return 1
    except (pin.PinError, KeyError, TypeError) as error:
        print(f"installer extraction failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
