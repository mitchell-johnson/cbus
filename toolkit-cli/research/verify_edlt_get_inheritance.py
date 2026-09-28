#!/usr/bin/env python3
"""Verify the pinned C-Gate eDLT generic-GET property-registration boundary.

This audits only the class chain instantiated for CBusEdlt in C-Gate
3.4.0.2001. It is separate from LABEL command dispatch and makes no claim
about undocumented firmware requests or a physical display's cache.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import zipfile


FIXTURE = Path(__file__).parent / "fixtures/edlt-dynamic-cache-get-inheritance.json"
JAR_SHA256 = "3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630"
PROPERTY_MAP_SHA256 = "a44d99c45adb2621403fc0d6626efb4e7e2fdf48480a7b9ddd7bf5f1489f125e"
CLASSES = (
    "Bo", "Bw", "be", "com.clipsal.cgate.cbus.core.CBusUnit",
    "com.clipsal.cgate.cbus.dev.CBusBaseUnit",
    "com.clipsal.cgate.cbus.dev.CBus2Unit",
    "com.clipsal.cgate.cbus.dev.CBusOEMUnit",
    "com.clipsal.cgate.cbus.dev.CBusEdlt",
)
EXPECTED_PROPERTIES = (
    ("EventLevel", "State"),
    (),
    ("Address", "ClassName", "Name", "ShortName"),
    ("Address", "Application", "Application2", "CatalogNumber", "ErrorFlags",
     "LearnEnable", "PSyncTime", "PartName", "PatchVersion", "ProjectName",
     "SlotGroups", "Type", "UnitBlock", "Version", "Version2"),
    (),
    ("BurdenActive", "ClockGenActive", "GeneratingClock", "LearnActive",
     "NetVoltage", "Serial", "SerialNumber", "SummaryFlags"),
    ("FirmwareVersion",),
    ("WidgetGroups",),
)
EXPECTED_METHODS = (
    ("gc",), (), (), ("PSync", "QSync", "ResetErrorFlags", "Sync"),
    (), (), (), ("FactoryDefault",),
)
EXPECTED_INSERTIONS = ((2, 1), (0, 0), (8, 0), (30, 8),
                       (0, 0), (16, 0), (2, 0), (1, 1))
PROPERTY_TYPES = {"Cn", "Cf", "Cc"}
REGISTER = "Method Cl.a:(LCk;)V"
METHOD_REGISTER = "Method Cj.a:(LCh;)V"
INSTRUCTION = re.compile(r"^\s*\d+:\s+(\w+)\s+(.*)$")
STRING = re.compile(r"// String (.*)$")
NEW = re.compile(r"// class (.*)$")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _methods(disassembly: str) -> list[tuple[str, list[tuple[str, str]]]]:
    """Retain javap instructions grouped by the declaration preceding Code."""
    lines = disassembly.splitlines()
    methods: list[tuple[str, list[tuple[str, str]]]] = []
    for index, line in enumerate(lines):
        if line != "    Code:":
            continue
        _require(index > 0 and lines[index - 1].startswith("  "),
                 "unexpected javap method header")
        heading = lines[index - 1].strip()
        instructions = []
        for current in lines[index + 1:]:
            match = INSTRUCTION.match(current)
            if match:
                instructions.append((match.group(1), match.group(2)))
            elif current.startswith("  ") and not current.startswith("    "):
                break
        methods.append((heading, instructions))
    _require(methods, "no javap methods found")
    return methods


def _registrations(disassembly: str, simple_name: str) -> dict:
    """Collect every property/method-map insertion in this exact class.

    For each map insertion, the nearest property/method object construction
    supplies its first string literal as the declared name. All insertions
    must occur in constructors; later runtime additions would invalidate the
    bounded source conclusion and require a new analysis.
    """
    properties: set[str] = set()
    methods: set[str] = set()
    property_insertions = method_insertions = 0
    for heading, instructions in _methods(disassembly):
        for position, (_, operand) in enumerate(instructions):
            kind = ("property" if REGISTER in operand else
                    "method" if METHOD_REGISTER in operand else None)
            if kind is None:
                continue
            _require(heading.split("(", 1)[0].endswith(simple_name),
                     f"non-constructor {kind} insertion: {heading}")
            wanted = PROPERTY_TYPES if kind == "property" else {"Ch"}
            begin = next((cursor for cursor in range(position - 1, -1, -1)
                          if instructions[cursor][0] == "new" and
                          (match := NEW.search(instructions[cursor][1])) and
                          match.group(1) in wanted), None)
            _require(begin is not None, f"unresolved {kind} object: {heading}")
            name = next((match.group(1) for opcode, arg in instructions[begin + 1:position]
                         if opcode in ("ldc", "ldc_w") and (match := STRING.search(arg))), None)
            _require(bool(name), f"unresolved {kind} name: {heading}")
            if kind == "property":
                properties.add(name)
                property_insertions += 1
            else:
                methods.add(name)
                method_insertions += 1
    return {
        "properties": sorted(properties),
        "methods": sorted(methods),
        "property_insertions": property_insertions,
        "method_insertions": method_insertions,
    }


def inspect_source(cgate_app: Path, javap: Path) -> dict:
    jar_path = cgate_app / "cgate.jar"
    _require(sha256(jar_path.read_bytes()) == JAR_SHA256, "C-Gate JAR changed")
    records = []
    with zipfile.ZipFile(jar_path) as jar:
        for name in CLASSES:
            path = name.replace(".", "/") + ".class"
            bytecode = jar.read(path)
            result = subprocess.run(
                [str(javap), "-classpath", str(jar_path), "-c", "-p", name],
                capture_output=True, text=True, check=True,
            )
            _require(f"class {name} extends " in result.stdout or
                     (name == "Bo" and "class Bo extends " in result.stdout),
                     f"unexpected class declaration: {name}")
            declaration = next(line.strip() for line in result.stdout.splitlines()
                               if re.search(rf"\bclass {re.escape(name)} extends ", line))
            record = {"class": name, "class_sha256": sha256(bytecode),
                      "declaration": declaration}
            record.update(_registrations(result.stdout, name.rsplit(".", 1)[-1]))
            records.append(record)
        _require(sha256(jar.read("Cl.class")) == PROPERTY_MAP_SHA256,
                 "generic GET property map changed")
    map_disassembly = subprocess.run(
        [str(javap), "-classpath", str(jar_path), "-c", "-p", "Cl"],
        capture_output=True, text=True, check=True,
    ).stdout
    _require("Method Cl.a:(Ljava/lang/String;I)Ljava/lang/String;" in
             subprocess.run([str(javap), "-classpath", str(jar_path), "-c", "-p", "Bo"],
                            capture_output=True, text=True, check=True).stdout and
             "ParameterNotFoundException" in map_disassembly and
             "Method java/util/Hashtable.get:" in map_disassembly and
             "Method java/util/Hashtable.elements:" in map_disassembly,
             "generic GET property dispatch changed")
    return {"jar_sha256": JAR_SHA256, "class_chain": records,
            "property_map": {"class": "Cl", "class_sha256": PROPERTY_MAP_SHA256,
                             "unknown_name": "ParameterNotFoundException",
                             "named_get": "Bo delegates to Cl.a(String,int)",
                             "enumeration": "Cl map values"}}


def check_fixture(report: dict) -> None:
    _require(report["format"] == "cbus-edlt-get-inheritance-v1" and
             report["work_item"] == "P6.05" and
             report["target"]["cgate_jar_sha256"] == JAR_SHA256 and
             report["target"]["cgate_version"] == "3.4.0.2001",
             "fixture target changed")
    source = report["source"]
    _require(source["jar_sha256"] == JAR_SHA256 and
             [item["class"] for item in source["class_chain"]] == list(CLASSES),
             "class chain changed")
    _require(source["property_map"] == {
        "class": "Cl", "class_sha256": PROPERTY_MAP_SHA256,
        "unknown_name": "ParameterNotFoundException",
        "named_get": "Bo delegates to Cl.a(String,int)",
        "enumeration": "Cl map values",
    }, "GET property dispatch changed")
    for index, item in enumerate(source["class_chain"]):
        _require(item["properties"] == list(EXPECTED_PROPERTIES[index]) and
                 item["methods"] == list(EXPECTED_METHODS[index]) and
                 (item["property_insertions"], item["method_insertions"]) ==
                 EXPECTED_INSERTIONS[index] and
                 re.fullmatch(r"[0-9a-f]{64}", item["class_sha256"]) is not None,
                 f"audited registration set changed: {item['class']}")
    all_properties = [value for item in source["class_chain"] for value in item["properties"]]
    _require("WidgetGroups" in all_properties and
             "SlotGroups" in all_properties and
             not any("label" in value.lower() or "cache" in value.lower()
                     for value in all_properties),
             "GET property conclusion changed")
    _require(report["decision"] == {
        "declared_inherited_get_cache_property": False,
        "generic_get_open_unit_oracle_completed": False,
        "physical_device_cache_readback": False,
        "firmware_protocol_absence_proven": False,
    }, "unsafe or changed decision")
    _require(report["limitation"], "missing scope limitation")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cgate-app", type=Path,
                        help="ignored, pinned C-Gate app directory")
    parser.add_argument("--javap", type=Path,
                        help="Java 11 javap; required with --cgate-app")
    args = parser.parse_args()
    if bool(args.cgate_app) != bool(args.javap):
        parser.error("pass both --cgate-app and --javap for source verification")
    report = json.loads(FIXTURE.read_text())
    check_fixture(report)
    if args.cgate_app:
        _require(inspect_source(args.cgate_app, args.javap) == report["source"],
                 "pinned eDLT GET class chain or registration differs")
    print(json.dumps({"work_item": report["work_item"], "source_verified": bool(args.cgate_app),
                      "declared_inherited_get_cache_property": False,
                      "physical_device_cache_readback": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
