#!/usr/bin/env python3
"""Decode local Toolkit 1.18/C-Gate 3.4 unit specifications for interoperability.

The fixed format constants below were obtained from the bundled C-Gate 3.4.0
reader (class By, AES/GCM/NoPadding). They are distribution-format constants,
not user credentials. AES-GCM authentication is always verified. Requires
cryptography, installed only in the research environment.
"""
import argparse
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("unitspec_dir", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    cipher = AESGCM(bytes.fromhex("6c3cfe61c11100425d9a23bdc586a147"))
    nonce = bytes.fromhex("da5700d482660ea026d14750e25fc926")
    inputs = sorted(args.unitspec_dir.glob("*.xml.es"))
    if not inputs:
        parser.error("No encrypted .xml.es specifications found")
    # Authenticate every input before writing any output.
    decoded = [(p.name[:-3], cipher.decrypt(nonce, p.read_bytes(), None)) for p in inputs]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, data in decoded:
        target = args.output_dir / name
        if target.exists() and target.read_bytes() != data:
            parser.error(f"Existing output differs: {target}")
    for name, data in decoded:
        (args.output_dir / name).write_bytes(data)
    print(f"Authenticated and decoded {len(decoded)} vendor XML files.")


if __name__ == "__main__":
    main()
