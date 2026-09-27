"""Reproduce the pinned SESU static-string decode without executing its DLL.

Usage: python research/derive_sesu_registry_identity.py /path/to/SesuBrick.DAD.dll
The proprietary DLL is an explicit local input and is never copied or written.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys


SOURCE_SHA256 = "21a6b2fb74d9b308d22c740ca0a1d887d80a067cccc03f59e4dd1bbb6c9c4b0c"
BLOB_OFFSET = 16896  # FieldRVA 0x6000 in the pinned PE image.
BLOB_SIZE = 9105
BLOB_SHA256 = "315677be6c1ae4099f70792b7fe19d06414442870e98c06fe0b236ec73f7fb47"
SLICES = {
    "key": (8997, 54, "57f0f52acb8adad9b03f0c9a5e37e699bbed6a1ec17fce771af177fe6ac412fb"),
    "entry": (9051, 29, "20e7024bae28f143fadcc7233135f69e7d711a23f196a84a49cf087c50354364"),
}


def decode(path: Path) -> dict[str, str]:
    original = path.read_bytes()
    if len(original) != 69704 or hashlib.sha256(original).hexdigest() != SOURCE_SHA256:
        raise ValueError("Input is not the pinned original SESU 3.0.7 assembly")
    blob = original[BLOB_OFFSET:BLOB_OFFSET + BLOB_SIZE]
    if hashlib.sha256(blob).hexdigest() != BLOB_SHA256:
        raise ValueError("Pinned SESU string blob differs")
    result = {}
    for name, (offset, length, digest) in SLICES.items():
        encoded = blob[offset:offset + length]
        decoded = bytes(byte ^ (index & 255) ^ 170
                        for index, byte in enumerate(encoded, offset))
        if hashlib.sha256(decoded).hexdigest() != digest:
            raise ValueError("Pinned SESU " + name + " slice differs")
        result[name] = decoded.decode("utf-8", errors="strict")
    return result


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: derive_sesu_registry_identity.py ORIGINAL_DLL")
    print(json.dumps({"source_sha256": SOURCE_SHA256, **decode(Path(sys.argv[1]))},
                     ensure_ascii=True, sort_keys=True))
