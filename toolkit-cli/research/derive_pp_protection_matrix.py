#!/usr/bin/env python3
"""Derive the admitted physical PP method/protection pairs from decoded specs.

The output retains only method/protection/type names, declaration counts,
specification file names and SHA-256 digests of the decoded inputs.  It never
copies parameter names, addresses, defaults or any other specification text.

Counting is per ``<Param>`` declaration in each decoded file, before include
expansion, so an include file contributes once.  A missing ``ProgramMethod``
means ``direct`` and a missing ``Protection`` means ``none``; both match the
C-Gate 3.4 ``lP.h``/``lP.g`` defaults.  ``--check`` compares a fresh
derivation with the committed table without writing it.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import os
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "docs/pp-protection-matrix.json"
METHODS = ("direct", "paged", "ncc", "edlt", "giu", "sgiu", "dali", "goc", "gocbyt", "goc2")
PROTECTIONS = ("none", "checksum", "lock", "factory", "special")
# C-Gate 3.4 lP save loop (lines 1004-1229 of the owned CFR output): the
# protection class chooses the wire contract independently of the method.
SAVE_CONTRACT = {
    "none": "changed bytes use the method's tagged STORE",
    "checksum": "identical to none; the tag is a transaction index, no checksum field is rewritten",
    "lock": "dd UNLOCK of each group's first parameter, then the tagged STORE",
    "factory": "skipped, except Type=bit fields (internal class 14) which use the plain tagged STORE",
    "special": "always skipped by PP SAVE",
}


def _document(path: Path) -> ET.Element:
    raw = path.read_bytes()
    # Decoded Toolkit specifications carry a plain copyright line before XML.
    start = raw.find(b"<")
    if start < 0:
        raise ValueError(f"{path.name} contains no XML")
    return ET.fromstring(raw[start:])


def derive(directory: Path) -> dict:
    files = sorted(path for path in directory.glob("*.xml") if path.is_file())
    if not files:
        raise ValueError("No decoded .xml unit specifications were found")
    digests = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
    declarations: Counter[tuple[str, str]] = Counter()
    types: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    sources: dict[tuple[str, str], set[str]] = defaultdict(set)
    unknown: Counter[tuple[str, str]] = Counter()
    for path in files:
        for param in _document(path).iter("Param"):
            method = (param.findtext("ProgramMethod") or "").strip().lower() or "direct"
            protection = (param.findtext("Protection") or "").strip().lower() or "none"
            kind = (param.findtext("Type") or "").strip().lower() or "unspecified"
            if method not in METHODS or protection not in PROTECTIONS:
                unknown[(method, protection)] += 1
                continue
            declarations[(method, protection)] += 1
            types[(method, protection)][kind] += 1
            sources[(method, protection)].add(path.name)
    if unknown:
        raise ValueError(f"Unmodelled method/protection names: {sorted(unknown)}")
    pairs = []
    for method in METHODS:
        for protection in PROTECTIONS:
            key = (method, protection)
            if not declarations[key]:
                continue
            pairs.append({
                "id": f"{method}/{protection}",
                "method": method,
                "protection": protection,
                "declarations": declarations[key],
                "specification_files": len(sources[key]),
                "types": dict(sorted(types[key].items())),
                "sources": sorted(sources[key]),
                "native_save_contract": SAVE_CONTRACT[protection],
            })
    listing = "".join(f"{name} {digest}\n" for name, digest in digests.items())
    return {
        "format": "cbus-pp-protection-matrix-v1",
        "derivation": "toolkit-cli/research/derive_pp_protection_matrix.py",
        "input": {
            "kind": "decoded C-Bus Toolkit 1.18.0.2754 / C-Gate 3.4.0.2001 unit specifications",
            "files": len(digests),
            "listing_sha256": hashlib.sha256(listing.encode("ascii")).hexdigest(),
            "file_sha256": digests,
        },
        "rules": {
            "counting": "Param declarations per decoded file before include expansion",
            "missing_program_method": "direct",
            "missing_protection": "none",
            "native_source": "C-Gate 3.4 lP.g/lP.h protection and method codes; lP save loop",
        },
        "admitted_pairs": pairs,
        "methods_without_declarations": [
            method for method in METHODS
            if not any(pair["method"] == method for pair in pairs)
        ],
        "retained_material": "Names, counts and digests only; no specification text is retained.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("unitspec_dir", type=Path, nargs="?",
                        default=os.environ.get("CBUS_UNITSPEC_DIR"))
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true",
                        help="compare with the committed table instead of writing it")
    args = parser.parse_args()
    if args.unitspec_dir is None:
        parser.error("Pass the decoded specification directory or set CBUS_UNITSPEC_DIR")
    document = derive(Path(args.unitspec_dir))
    text = json.dumps(document, indent=2) + "\n"
    if args.check:
        if args.output.read_text(encoding="utf-8") != text:
            print(f"{args.output} differs from a fresh derivation", file=sys.stderr)
            return 1
        print(f"{args.output} matches {document['input']['files']} decoded specifications")
        return 0
    args.output.write_text(text, encoding="utf-8")
    print(f"Wrote {len(document['admitted_pairs'])} admitted pairs to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
