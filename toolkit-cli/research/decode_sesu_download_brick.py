"""Reproduce the pinned SESU DownloadBrick static-string decode without executing it.

Usage: python research/decode_sesu_download_brick.py /path/to/DownloadBrick.dll
The proprietary DLL is an explicit local input and is never copied or written.
The printed strings anchor the static review in
research/fixtures/toolkit-update-download-source-review.json.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys


SOURCE_SHA256 = "1971a76d143d3e7c1afa2a27cb99f15afca81de195530d4b4e72dae201cc0d3f"
SOURCE_SIZE = 46208
BLOB_OFFSET = 12724  # FieldRVA 0x4FB4 in the pinned PE image.
BLOB_SIZE = 4166
BLOB_SHA256 = "9e83c68df7566cd188f094e2eebd9d37ff905f2986f234c387774a4a80c5d7cf"
SLICES = {
    "settings_key": (1, 43, "60795f750482928ef49fd353acf4c0ee2ebf62f43fcdf311879363ca3a618147"),
    "keep_bad_signature_value": (44, 25, "6be7f524a08c4c45a1e303de604f4b66bc80639bcdb9d960ade9d9e5487a7134"),
    "partial_suffix": (365, 8, "0b63f5510c52650aa9a57e27dd98b904dbc714cfbe5acc8033dbb3d6d04b628b"),
    "integrity_failure_log": (1736, 37, "17b66947fe4894ae758f65d617ded4daa0eda849463433338294db3d18f910da"),
    "production_host_1": (2202, 33, "53afa18c163214ab719723f419a692ed728fd9dca2efcc58d0ba07e7d1a8224b"),
    "production_host_2": (2235, 35, "0f4d1b6d90af3ba056ea0ef38e414f28af1d7fd5c31cf05397c27d2eb827e68d"),
    "integrity_failure_message": (3711, 66, "d4190dda0243a70013c91554f1a9db7ffd2919d5907e5e2a54a6dd6a94204bd6"),
    "production_signature_message": (3898, 76, "4ab74b42b917b79075d3eed5804984a11074e28f49dbdb692e43c76e8640ab6d"),
}


def decode(path: Path) -> dict[str, str]:
    original = path.read_bytes()
    if len(original) != SOURCE_SIZE or hashlib.sha256(original).hexdigest() != SOURCE_SHA256:
        raise ValueError("Input is not the pinned original SESU DownloadBrick assembly")
    blob = original[BLOB_OFFSET:BLOB_OFFSET + BLOB_SIZE]
    if hashlib.sha256(blob).hexdigest() != BLOB_SHA256:
        raise ValueError("Pinned DownloadBrick string blob differs")
    result = {}
    for name, (offset, length, digest) in SLICES.items():
        decoded = bytes(byte ^ (index & 255) ^ 170
                        for index, byte in enumerate(blob[offset:offset + length], offset))
        if hashlib.sha256(decoded).hexdigest() != digest:
            raise ValueError("Pinned DownloadBrick " + name + " slice differs")
        result[name] = decoded.decode("utf-8", errors="strict")
    return result


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: decode_sesu_download_brick.py ORIGINAL_DLL")
    print(json.dumps({"source_sha256": SOURCE_SHA256, **decode(Path(sys.argv[1]))},
                     ensure_ascii=True, sort_keys=True, indent=2))
