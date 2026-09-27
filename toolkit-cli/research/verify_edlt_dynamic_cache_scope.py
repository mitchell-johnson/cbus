#!/usr/bin/env python3
"""Check the bounded Toolkit 1.18 / C-Gate 3.4 eDLT cache-read conclusion.

The committed fixture is useful without proprietary binaries.  Passing
``--cgate-app`` and ``--toolkit-app`` additionally verifies the exact source
artifacts and extracts the four native LABEL registrations from bytecode.
This is deliberately a release-specific command-surface check, not a proof
about undiscovered device firmware protocols.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import zipfile


FIXTURE = Path(__file__).parent / "fixtures/edlt-dynamic-cache-native-scope.json"
JAR_SHA256 = "3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630"
JAVA_SHA256 = "94e156397958bb83fda31ee16200580fd083b0fc0ed4a9ce795cfa44ff8e72f4"
CLASS_SHA256 = "f5871ca2e007efc5d2273e1282411c02f7f70848b3b36c44e93a38744817d3b7"
CODE_SHA256 = "0480c0507b2e6b4786427962628d03bb67c994f2f7111714ff59fc8ed407599c"
EDLT_CLASS_SHA256 = "6d9733794c5228700d00525f6c173ce4af6e4f11ed9ddc1c3a0673e73a492094"
TOOLKIT_EXE_SHA256 = "9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab"
EDLT_DLL_SHA256 = "75bc741234b52a168a4838fee305c309d3909571d2711f7580216b46b028e8d3"
LABEL_EDITOR_SHA256 = "508fa63db112a3ec07bf3cf834b41a0f26da3b0e7a428bc288bff0ec433a073b"
EDIT_LABELS_IL_SHA256 = "cd59aefbc4abced3f76f78263a5828ee3b18c6fcae412b142533dad7f083f1d9"
CLEAR_LABELS_IL_SHA256 = "6ed4945061aee74a96d2702cccd73fd137f45e80b4daa3afb681c42ac5026522"
SEND_LABELS_IL_SHA256 = "ac0379eb45c64e6f5db61b4c79987e756bf7e9bb77bf4ecc36ac053b8d73af6e"
HELP_CAPTURE_SHA256 = "60e80107817495039004006a0249272eda53edd03cf610aaafdc641733cda15f"
COMMAND_CAPTURE_SHA256 = "4c29ec800aef3c289fb272da87ffe20f45fca282d248654002445dda3569e721"
FULL_HELP_CENSUS_SHA256 = "c8645c25686c43ee86360334694bcc3efbbaf83490aadb48afc25ac7457e1c4f"
REGISTRATIONS = {"clear": "kx", "clearedlt": "ky", "kfiget": "kz", "kfiset": "kA"}
CLASS_PATH = "com/clipsal/cgate/cbus/label/LabelPrimaryCommand.class"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def check_evidence(evidence: dict) -> None:
    """Reject weakened claims, altered oracle results or ambiguous scope."""
    _require(evidence.get("format") == "cbus-edlt-dynamic-cache-native-scope-v1", "format changed")
    _require(evidence.get("work_item") == "P6.05", "work item changed")
    _require(evidence.get("scope_id") ==
             "P6.05-CGATE3402001-TOOLKIT118-NATIVE-LABEL-CACHE", "scope ID changed")
    target = evidence["target"]
    _require(target["toolkit_version"] == "1.18.0.2754" and
             target["cgate_version"] == "3.4.0.2001" and
             target["cgate_jar_sha256"] == JAR_SHA256 and
             target["java11_sha256"] == JAVA_SHA256 and
             target["toolkit_exe_sha256"] == TOOLKIT_EXE_SHA256,
             "target release changed")
    static = evidence["static_bytecode"]
    _require(static["label_primary_class"] == CLASS_PATH and
             static["class_sha256"] == CLASS_SHA256 and
             static["constructor_code_sha256"] == CODE_SHA256 and
             static["edlt_class_sha256"] == EDLT_CLASS_SHA256 and
             static["registered_subcommands"] == REGISTRATIONS and
             static["registered_command_count"] == 4, "LABEL registry evidence changed")
    ui = evidence["toolkit_bytecode"]
    _require(ui["edlt_dll_sha256"] == EDLT_DLL_SHA256 and
             ui["label_editor_dll_sha256"] == LABEL_EDITOR_SHA256 and
             ui["frm_edit_labels_il_sha256"] == EDIT_LABELS_IL_SHA256 and
             ui["frm_clear_labels_il_sha256"] == CLEAR_LABELS_IL_SHA256 and
             ui["label_editor_send_il_sha256"] == SEND_LABELS_IL_SHA256,
             "Toolkit assembly evidence changed")
    oracle = evidence["owned_loopback_oracle"]
    _require(oracle["read_only"] is True and oracle["cleanup_complete"] is True and
             oracle["help_star_lines"] >= 200 and
             oracle["raw_help_capture_sha256"] == HELP_CAPTURE_SHA256 and
             oracle["raw_command_capture_sha256"] == COMMAND_CAPTURE_SHA256,
             "owned oracle provenance incomplete")
    lines = oracle["help_label"]
    _require(len(lines) == 6 and lines[0] == "101-Help: LABEL commands:" and
             lines[1] == "101-Help:  LABEL ? Help for these commands", "LABEL help root changed")
    help_names = []
    for line in lines[2:]:
        match = re.fullmatch(r"101(?:-| )Help:  LABEL ([A-Z]+) - .*", line)
        _require(match is not None, "malformed LABEL help child")
        help_names.append(match.group(1).lower())
    _require(set(help_names) == set(REGISTRATIONS) and len(help_names) == 4,
             "LABEL help disagrees with registered children")
    _require(oracle["label_question"] == lines, "LABEL ? disagrees with HELP LABEL")
    expected_candidates = {
        "label_query_help": {f"HELP LABEL {item}" for item in ("GET", "READ", "CACHE", "INVENTORY")},
        "label_query_commands": {f"LABEL {item} //NO_SUCH/254/p/5" for item in
                                 ("GET", "READ", "CACHE", "INVENTORY")},
    }
    for family in ("label_query_help", "label_query_commands"):
        candidates = oracle[family]
        _require(set(candidates) == expected_candidates[family],
                 f"{family} candidate set changed")
        for command, response in candidates.items():
            _require(response == ["400 Syntax Error."], f"{command} is not a native syntax rejection")
    boundary = evidence["supported_boundary"]
    for key in ("native_label_cache_inventory", "physical_firmware_protocol_absence_proven",
                "cmqtt_observed_traffic_is_device_readback", "observed_traffic_complete",
                "toolkit_cli_device_readback"):
        _require(boundary[key] is False, f"unsafe {key} claim")
    _require("undocumented firmware" in evidence["claim"], "firmware caveat removed")
    census_ref = evidence["retained_full_help_census"]
    _require(census_ref == {
        "path": "research/fixtures/native-cgate-help-differential-acceptance.json",
        "sha256": FULL_HELP_CENSUS_SHA256,
        "target_profile": "target_cgate_3_4",
        "maintained_path_count": 431,
        "help_star_response_lines": 211,
    }, "full native help census reference changed")
    census_bytes = (FIXTURE.parents[2] / census_ref["path"]).read_bytes()
    _require(sha256(census_bytes) == FULL_HELP_CENSUS_SHA256,
             "retained full native help census changed")
    census = json.loads(census_bytes)
    profile = census["profiles"]["target_cgate_3_4"]
    _require(profile["cgate_jar"]["sha256"] == JAR_SHA256 and
             len(profile["rows"]) == 431 and
             len(profile["help_star"]["response"]) == 211,
             "full native help census target changed")


def _class_registration(class_bytes: bytes) -> tuple[dict[str, str], bytes]:
    """Decode only the pinned constructor's four registration slots.

    The exact class and Code digests are checked first by ``check_sources``.
    Fixed offsets here are intentional: a changed vendor release requires a
    fresh bytecode analysis rather than a permissive pattern search.
    """
    data = memoryview(class_bytes)
    offset = 0

    def take(size: int) -> bytes:
        nonlocal offset
        if offset + size > len(data):
            raise ValueError("truncated class file")
        value = bytes(data[offset:offset + size])
        offset += size
        return value

    def u1() -> int:
        return take(1)[0]

    def u2() -> int:
        return struct.unpack(">H", take(2))[0]

    def u4() -> int:
        return struct.unpack(">I", take(4))[0]

    _require(u4() == 0xCAFEBABE, "invalid class magic")
    take(4)  # class-file version
    pool = [None] * u2()
    index = 1
    while index < len(pool):
        tag = u1()
        if tag == 1:
            pool[index] = (tag, take(u2()).decode("utf-8"))
        elif tag in (7, 8, 16, 19, 20):
            pool[index] = (tag, u2())
        elif tag in (3, 4, 9, 10, 11, 12, 17, 18):
            pool[index] = (tag, take(4))
        elif tag in (5, 6):
            pool[index] = (tag, take(8))
            index += 1
        elif tag == 15:
            pool[index] = (tag, take(3))
        else:
            raise ValueError(f"unknown constant pool tag {tag}")
        index += 1

    def utf8(index: int) -> str:
        entry = pool[index]
        _require(entry is not None and entry[0] == 1, "invalid UTF8 constant")
        return entry[1]

    def attributes() -> list[tuple[str, bytes]]:
        return [(utf8(u2()), take(u4())) for _ in range(u2())]

    take(6)  # access, this, super
    take(2 * u2())  # interfaces
    for _ in range(u2()):  # fields
        take(6)
        attributes()
    constructor = None
    for _ in range(u2()):  # methods
        take(2)
        name, descriptor = utf8(u2()), utf8(u2())
        attrs = attributes()
        if name == "<init>" and descriptor == "()V":
            _require(constructor is None, "duplicate constructor")
            code = next((value for attr, value in attrs if attr == "Code"), None)
            _require(code is not None and len(code) >= 8, "missing constructor Code")
            length = struct.unpack_from(">I", code, 4)[0]
            constructor = code[8:8 + length]
    _require(constructor is not None and len(constructor) == 75, "unexpected constructor")

    # Native constructor has exactly four contiguous ldc/new/register blocks.
    registrations = {}
    for literal_at, class_at in ((23, 25), (36, 38), (49, 51), (62, 64)):
        _require(constructor[literal_at] == 0x12 and constructor[class_at] == 0xBB,
                 "LABEL registration instruction changed")
        string_entry = pool[constructor[literal_at + 1]]
        class_index = struct.unpack_from(">H", constructor, class_at + 1)[0]
        class_entry = pool[class_index]
        _require(string_entry is not None and string_entry[0] == 8 and
                 class_entry is not None and class_entry[0] == 7, "registration constants changed")
        registrations[utf8(string_entry[1])] = utf8(class_entry[1])
    return registrations, constructor


def check_sources(evidence: dict, cgate_app: Path, toolkit_app: Path) -> None:
    """Revalidate the exact ignored vendor files when locally available."""
    jar = cgate_app / "cgate.jar"
    _require(sha256(jar.read_bytes()) == JAR_SHA256, "C-Gate jar hash differs")
    with zipfile.ZipFile(jar) as archive:
        bytecode = archive.read(CLASS_PATH)
        edlt_bytecode = archive.read(evidence["static_bytecode"]["edlt_class"])
    _require(sha256(bytecode) == CLASS_SHA256, "LABEL class hash differs")
    registrations, constructor = _class_registration(bytecode)
    _require(sha256(constructor) == CODE_SHA256 and registrations == REGISTRATIONS,
             "native LABEL registration changed")
    static = evidence["static_bytecode"]
    _require(sha256(edlt_bytecode) ==
             static["edlt_class_sha256"], "native eDLT class hash differs")
    _require(bool(edlt_bytecode), "empty native eDLT class")
    target = evidence["target"]
    _require(sha256((toolkit_app / "CBusToolkit.exe").read_bytes()) ==
             target["toolkit_exe_sha256"], "Toolkit executable hash differs")
    ui = evidence["toolkit_bytecode"]
    _require(sha256((toolkit_app / "eDLT.dll").read_bytes()) ==
             ui["edlt_dll_sha256"], "Toolkit eDLT assembly hash differs")
    _require(sha256((toolkit_app / "LabelEditor.dll").read_bytes()) ==
             ui["label_editor_dll_sha256"], "Toolkit LabelEditor assembly hash differs")


def check_raw_captures(evidence: dict, help_path: Path, command_path: Path) -> None:
    """Recheck the private full native captures against committed excerpts."""
    oracle = evidence["owned_loopback_oracle"]
    target = evidence["target"]
    reports = []
    for path, digest in ((help_path, oracle["raw_help_capture_sha256"]),
                         (command_path, oracle["raw_command_capture_sha256"])):
        raw = path.read_bytes()
        _require(sha256(raw) == digest, f"native capture hash differs: {path.name}")
        report = json.loads(raw)
        _require(report["jar_sha256"] == target["cgate_jar_sha256"] and
                 report["java_sha256"] == target["java11_sha256"] and
                 report["read_only"] is True and report["cleanup_complete"] is True and
                 report["project_commands_sent"] == 0 and
                 report["mutation_commands_sent"] == 0,
                 f"native capture provenance differs: {path.name}")
        reports.append(report)

    def normalized(report: dict) -> dict[str, list[str]]:
        rows = {}
        for row in report["commands"]:
            _require(row["terminal"] is True and row["error"] is None,
                     f"incomplete native response: {row['command']}")
            rows[row["command"]] = [re.sub(r"^\[[^]]+\] ", "", line)
                                    for line in row["lines"]]
        _require(len(rows) == len(report["commands"]), "duplicate native command")
        return rows

    help_rows, command_rows = map(normalized, reports)
    _require(help_rows["HELP LABEL"] == oracle["help_label"] and
             len(help_rows["HELP *"]) == oracle["help_star_lines"],
             "native LABEL or full HELP differs")
    _require(command_rows["LABEL ?"] == oracle["label_question"],
             "native LABEL ? differs")
    for key, rows in (("label_query_help", help_rows),
                      ("label_query_commands", command_rows)):
        _require({name: rows[name] for name in oracle[key]} == oracle[key],
                 f"native {key} differs")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cgate-app", type=Path, help="Ignored pinned vendor C-Gate app directory")
    parser.add_argument("--toolkit-app", type=Path, help="Ignored pinned Toolkit app directory")
    parser.add_argument("--raw-help", type=Path, help="Private owned-loopback HELP capture")
    parser.add_argument("--raw-commands", type=Path, help="Private owned-loopback command capture")
    args = parser.parse_args()
    if bool(args.cgate_app) != bool(args.toolkit_app):
        parser.error("pass both --cgate-app and --toolkit-app for source verification")
    if bool(args.raw_help) != bool(args.raw_commands):
        parser.error("pass both --raw-help and --raw-commands for capture verification")
    evidence = json.loads(FIXTURE.read_text())
    check_evidence(evidence)
    if args.cgate_app:
        check_sources(evidence, args.cgate_app, args.toolkit_app)
    if args.raw_help:
        check_raw_captures(evidence, args.raw_help, args.raw_commands)
    print(json.dumps({"scope_id": evidence["scope_id"], "fixture_valid": True,
                      "vendor_source_verified": bool(args.cgate_app),
                      "native_capture_verified": bool(args.raw_help),
                      "device_cache_inventory": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
