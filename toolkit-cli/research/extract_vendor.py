#!/usr/bin/env python3
"""Extract a user-supplied Toolkit 1.18.0 installer/archive for interoperability.

Requires innoextract and 7zz (e.g. brew install innoextract sevenzip).
Vendor binaries, help and decoded schemas remain outside version control.
Does not execute the installer or install Windows services.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import zipfile
from pathlib import Path

INSTALLER = "CBusToolkit-1.18.0.2754-CGate-3.4.0.2001-Setup.exe"
CGATE = "cgate-3.4.0_2001-JRE-11.0.24_8-setup.exe"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, default=Path(__file__).parent / "vendor")
    args = parser.parse_args()
    for tool in ("innoextract", "7zz"):
        if shutil.which(tool) is None:
            parser.error(f"Install {tool} first")
    args.output.mkdir(parents=True, exist_ok=True)
    installer = args.source
    if zipfile.is_zipfile(args.source):
        with zipfile.ZipFile(args.source) as archive:
            entries = [i for i in archive.infolist() if i.filename == INSTALLER]
            if len(entries) != 1 or entries[0].file_size > 500_000_000:
                parser.error("Archive must contain exactly the Toolkit 1.18.0 installer")
            installer = args.output / INSTALLER
            data = archive.read(entries[0])
            if installer.exists() and installer.read_bytes() != data:
                parser.error("Existing installer differs; use a new output directory")
            installer.write_bytes(data)
    if installer.name != INSTALLER:
        parser.error(f"Expected {INSTALLER}")
    digest = hashlib.sha256(installer.read_bytes()).hexdigest()
    subprocess.run(["innoextract", "-s", "-d", str(args.output / "toolkit"), str(installer)], check=True)
    subprocess.run(["innoextract", "-s", "-d", str(args.output / "cgate"),
                    str(args.output / "toolkit" / "tmp" / CGATE)], check=True)
    subprocess.run(["7zz", "x", "-y", "-bso0", "-bsp0", "-o" + str(args.output / "toolkit-help"),
                    str(args.output / "toolkit" / "app" / "Toolkit Help.chm")], check=True)
    print(json.dumps({"installer_sha256": digest, "cgate_dir": str(args.output / "cgate" / "app"),
                      "help_dir": str(args.output / "toolkit-help")}, indent=2))


if __name__ == "__main__":
    main()
