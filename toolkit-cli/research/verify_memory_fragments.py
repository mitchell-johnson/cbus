#!/usr/bin/env python3
"""Verify internal-fragment memory layouts through the original C-Gate encoder.

The ordinary native memory corpus uses command-addressable parameters.  Two
single-bit DLT layouts occur only in the vendor's internal ``I_DLTF.xml``
fragment, so ``PP GET``/``PP SET`` cannot address them.  This bounded runner
loads that signed fragment through C-Gate's original ``md``/``lP`` classes,
invokes the original named encoder directly, and compares its raw bytes and
decoded values with the production Python ``MemoryCodec``.

No C-Gate server starts, no project is created, and the Java child runs under a
network-denied macOS sandbox.  Vendor files and decrypted specifications are
explicit inputs and are never copied into the report.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import socket
import subprocess
import sys
import tempfile
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cbus_toolkit.memory import MemoryCodec, MemoryImage
from cbus_toolkit.unitspec import UnitSpecStore


JAR_SHA256 = "3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630"
SIGNED_FRAGMENT_SHA256 = "06230884b82d9282a6a3c9d9ee7f283aea82967d11bc0b9f350bc7acf3b26f36"
PLAIN_FRAGMENT_SHA256 = "db1eee1f7c92271085514e11e0061b617dbb39094c318f5bf29c7e598f7d3c28"
PARAMETERS = ("LabelFlavourLSB", "LabelFlavourMSB")
VALUES = ((1, 0, 1, 0, 1, 0, 1, 0), (0, 1, 0, 1, 0, 1, 0, 1))
SEEDS = (0xA5, 0x5A)


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(65536):
            result.update(block)
    return result.hexdigest()


def require_file(path: str | Path, label: str) -> Path:
    value = Path(path).resolve(strict=True)
    if not value.is_file():
        raise ValueError(f"{label} must be a regular file")
    return value


def require_java11(java: Path) -> str:
    result = subprocess.run(
        [str(java), "-version"], capture_output=True, text=True, timeout=10, check=False
    )
    if result.returncode or 'version "11.' not in result.stderr:
        raise ValueError("The selected Java runtime must be Java 11")
    return result.stderr.strip()


def parse_original(output: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    witness = None
    layouts: dict[str, dict[str, str]] = {}
    cases: list[dict[str, Any]] = []
    complete = None
    for line in output.splitlines():
        if line == "Logging to file: logs/event.txt":
            continue
        fields = line.split("\t")
        if fields[0] == "WITNESS" and len(fields) == 3 and witness is None:
            witness = {"exception": fields[1], "message_base64": fields[2]}
        elif fields[0] == "LAYOUT" and len(fields) == 9 and fields[1] not in layouts:
            layouts[fields[1]] = {
                "type": fields[2], "address": fields[3], "array_size": fields[4],
                "bit_size": fields[5], "bit_address": fields[6],
                "array_skip": fields[7], "endian": fields[8],
            }
        elif fields[0] == "CASE" and len(fields) == 7:
            cases.append({
                "parameter": fields[1], "trial": int(fields[2]), "seed": int(fields[3]),
                "value": [int(value) for value in fields[4].split()],
                "native_raw_hex": fields[5],
                "native_decoded": [int(value) for value in fields[6].split()],
            })
        elif fields[0] == "COMPLETE" and len(fields) == 6 and complete is None:
            complete = {
                "layouts": int(fields[1]), "trials": int(fields[2]),
                **dict(field.split("=", 1) for field in fields[3:]),
            }
        else:
            raise ValueError("Unexpected original probe output")
    if witness is None or complete != {
        "layouts": 2, "trials": 4, "original_encoder_invoked": "true",
        "command_service_started": "false", "physical_io": "false",
    }:
        raise ValueError("Original probe did not reach its bounded terminal state")
    if set(layouts) != set(PARAMETERS) or len(cases) != 4:
        raise ValueError("Original probe returned an incomplete or duplicate matrix")
    return {"network_witness": witness, "layouts": layouts, "terminal": complete}, cases


def compare_cases(cases: list[dict[str, Any]], spec_directory: Path) -> list[dict[str, Any]]:
    codec = MemoryCodec(UnitSpecStore(spec_directory).load("I_DLTF.xml"))
    observed = {(case["parameter"], case["trial"]): case for case in cases}
    expected_keys = {(name, trial) for name in PARAMETERS for trial in range(2)}
    if set(observed) != expected_keys:
        raise ValueError("Original probe case identity matrix differs")
    results = []
    for name in PARAMETERS:
        layout = codec.layout(name)
        if (layout.parameter.type, layout.bit_size, layout.array_size, layout.array_skip,
                layout.endian) != ("bit", 1, 8, 0, "little"):
            raise ValueError(f"Unexpected decrypted fragment layout for {name}")
        for trial, (seed, value) in enumerate(zip(SEEDS, VALUES)):
            native = observed[(name, trial)]
            image = MemoryImage.from_bytes(bytes([seed]) * 8, start=layout.address)
            changed = codec.encode(name, list(value)).apply(image)
            raw = changed.read(layout.address, 8).hex()
            decoded = codec.decode(name, changed)
            passed = (
                native["seed"] == seed and native["value"] == list(value)
                and native["native_raw_hex"] == raw
                and native["native_decoded"] == decoded
                and raw != bytes([seed]).hex() * 8
            )
            results.append({
                "parameter": name,
                "layout": ["bit", 1, layout.bit_address, 0, 8, "little"],
                "trial": trial,
                "seed": seed,
                "value": list(value),
                "native_raw_hex": native["native_raw_hex"],
                "python_raw_hex": raw,
                "native_decoded": native["native_decoded"],
                "python_decoded": decoded,
                "status": "pass" if passed else "mismatch",
            })
    return results


def run(
    *,
    vendor: str | Path,
    spec_directory: str | Path,
    java: str | Path,
    javac: str | Path,
) -> dict[str, Any]:
    if sys.platform != "darwin":
        raise ValueError("The retained original-fragment runner requires macOS sandbox-exec")
    sandbox = require_file("/usr/bin/sandbox-exec", "sandbox-exec")
    java_path = require_file(java, "java")
    javac_path = require_file(javac, "javac")
    vendor_path = Path(vendor).resolve(strict=True)
    spec_path = Path(spec_directory).resolve(strict=True)
    if not vendor_path.is_dir() or not spec_path.is_dir():
        raise ValueError("Vendor and decrypted specification inputs must be directories")
    jar = require_file(vendor_path / "cgate.jar", "C-Gate jar")
    signed = require_file(vendor_path / "unitspec/I_DLTF.xml.es", "signed I_DLTF fragment")
    plain = require_file(spec_path / "I_DLTF.xml", "decrypted I_DLTF fragment")
    if digest(jar) != JAR_SHA256 or digest(signed) != SIGNED_FRAGMENT_SHA256:
        raise ValueError(
            "Original C-Gate jar or signed I_DLTF fragment differs from the "
            "pinned build"
        )
    if digest(plain) != PLAIN_FRAGMENT_SHA256:
        raise ValueError("Decrypted I_DLTF fragment differs from the pinned signed source")
    source = require_file(ROOT / "research/NativeMemoryFragmentProbe.java", "probe source")
    runner = Path(__file__).resolve(strict=True)
    memory_source = require_file(ROOT / "src/cbus_toolkit/memory.py", "memory codec")
    unitspec_source = require_file(ROOT / "src/cbus_toolkit/unitspec.py", "unit-spec reader")
    inputs = {
        "research/NativeMemoryFragmentProbe.java": source,
        "research/verify_memory_fragments.py": runner,
        "src/cbus_toolkit/memory.py": memory_source,
        "src/cbus_toolkit/unitspec.py": unitspec_source,
        "vendor_cgate.jar": jar,
        "vendor_I_DLTF.xml.es": signed,
        "decrypted_I_DLTF.xml": plain,
        "java": java_path,
        "javac": javac_path,
    }
    before = {label: digest(path) for label, path in inputs.items()}
    java_version = require_java11(java_path)

    with tempfile.TemporaryDirectory(prefix="cbus-memory-fragment-") as directory:
        work = Path(directory)
        (work / "home").mkdir()
        (work / "tmp").mkdir()
        (work / "logs").mkdir()
        (work / "unitspec").symlink_to(vendor_path / "unitspec", target_is_directory=True)
        profile = work / "network-denied.sb"
        profile.write_text("(version 1)\n(allow default)\n(deny network*)\n", encoding="ascii")
        copied_source = work / source.name
        copied_source.write_bytes(source.read_bytes())
        environment = {
            "HOME": str(work / "home"), "TMPDIR": str(work / "tmp") + "/",
            "PATH": "/usr/bin:/bin", "LANG": "en_US.UTF-8",
        }
        compile_command = [
            str(sandbox), "-f", str(profile), str(javac_path), "--release", "11",
            "-encoding", "UTF-8", "-cp", str(jar), "-d", str(work), str(copied_source),
        ]
        compile_result = subprocess.run(
            compile_command, cwd=work, env=environment, capture_output=True, text=True,
            timeout=30, check=False,
        )
        if compile_result.returncode or compile_result.stdout or compile_result.stderr:
            raise RuntimeError("Original fragment probe compilation failed or emitted output")

        witness_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            witness_socket.bind(("127.0.0.1", 0))
            witness_socket.listen(1)
            classpath = os.pathsep.join((str(work), str(jar), str(vendor_path / "lib/*")))
            command = [
                str(sandbox), "-f", str(profile), str(java_path), "-XX:-UsePerfData",
                "-Djava.io.tmpdir=" + str(work / "tmp"), "-Duser.home=" + str(work / "home"),
                "-Djava.awt.headless=true", "-cp", classpath, "NativeMemoryFragmentProbe",
                str(witness_socket.getsockname()[1]),
            ]
            original = subprocess.run(
                command, cwd=work, env=environment, capture_output=True, text=True,
                timeout=30, check=False,
            )
        finally:
            witness_socket.close()
        if original.returncode or original.stderr:
            raise RuntimeError("Original fragment probe failed or emitted stderr")
        original_meta, original_cases = parse_original(original.stdout)
        cases = compare_cases(original_cases, spec_path)
        class_file = work / "NativeMemoryFragmentProbe.class"
        report = {
            "format": "cbus-native-memory-fragment-acceptance-v1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "target": "Schneider Electric C-Gate 3.4.0 build 2001",
            "scope": (
                "Changing-value original C-Gate encoder acceptance for the two logical "
                "layouts present only in the internal I_DLTF fragment."
            ),
            "execution": {
                "platform": platform.platform(),
                "python": sys.version,
                "java_version": java_version,
                "java_sha256": digest(java_path),
                "javac_sha256": digest(javac_path),
                "network_denied": True,
                "server_started": False,
                "command_service_started": False,
                "physical_io": False,
                "automatic_retry": False,
                "compile_exit_code": compile_result.returncode,
                "original_exit_code": original.returncode,
                "original_stdout_sha256": hashlib.sha256(original.stdout.encode()).hexdigest(),
                "compiled_class_sha256": digest(class_file),
            },
            "source_sha256": {
                "research/NativeMemoryFragmentProbe.java": digest(source),
                "research/verify_memory_fragments.py": digest(runner),
                "src/cbus_toolkit/memory.py": digest(memory_source),
                "src/cbus_toolkit/unitspec.py": digest(unitspec_source),
                "vendor_cgate.jar": digest(jar),
                "vendor_I_DLTF.xml.es": digest(signed),
                "decrypted_I_DLTF.xml": digest(plain),
            },
            "original": original_meta,
            "cases": cases,
            "summary": {
                "distinct_layouts": len({tuple(case["layout"]) for case in cases}),
                "passing_layouts": len(
                    {
                        tuple(case["layout"])
                        for case in cases
                        if case["status"] == "pass"
                    }
                ),
                "passing_change_trials": sum(case["status"] == "pass" for case in cases),
                "failed_change_trials": sum(case["status"] != "pass" for case in cases),
            },
            "limitations": [
                "The two parameters are internal-fragment layouts and remain "
                "unavailable through PP GET/SET token commands.",
                "This proves host-side native encoder equivalence, not physical "
                "transfer, checksum, protection or device behavior.",
                "The probe invokes original C-Gate classes, not the original Toolkit GUI.",
            ],
            "inputs_unchanged": before
            == {label: digest(path) for label, path in inputs.items()},
        }
    if report["summary"] != {
        "distinct_layouts": 2, "passing_layouts": 2,
        "passing_change_trials": 4, "failed_change_trials": 0,
    } or not report["inputs_unchanged"]:
        raise RuntimeError("Fragment acceptance did not pass its complete bounded matrix")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--vendor",
        type=Path,
        required=True,
        help="extracted original C-Gate application directory",
    )
    parser.add_argument(
        "--spec-dir",
        type=Path,
        required=True,
        help="matching decrypted unit-specification directory",
    )
    parser.add_argument(
        "--java", type=Path, required=True, help="explicit Java 11 executable"
    )
    parser.add_argument(
        "--javac", type=Path, required=True, help="explicit Java 11 compiler"
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output already exists; choose a new path to preserve prior evidence")
    report = run(
        vendor=args.vendor,
        spec_directory=args.spec_dir,
        java=args.java,
        javac=args.javac,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"output": str(args.output), "summary": report["summary"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
