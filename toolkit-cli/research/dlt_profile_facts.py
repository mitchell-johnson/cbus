#!/usr/bin/env python3
"""Derive sanitized DLT/eDLT profile and eDLT firmware-package facts.

Inputs are the owned Toolkit 1.18.0.2754 / C-Gate 3.4.0.2001 installation:
the C-Gate ``cbusunits.xml`` catalogue, decoded unit specifications, the
extracted Toolkit help topics, ``CBusToolkit.exe`` and the four encrypted
``eDLTFirmware_*.zip`` packages.

The profile receipt keeps only unit types, catalogue numbers, catalogue
revision ranges and flags, specification file names/digests/version bounds,
help topic IDs with the unit types and catalogue names they state, and
digests of the Toolkit instruction ranges that define LabelFlavour
composition. It copies no specification parameter text, help prose or
instruction bytes.

The firmware receipt reads only each zip's central directory: entry names,
sizes, CRC fields, method/flag/extra-field numbers and DOS timestamps, plus
the zip SHA-256. No entry is opened, decompressed or decrypted, and no
archive password is used or recorded.

``--check`` compares a fresh derivation with the committed receipts.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
from pathlib import Path
import re
import struct
import sys
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PROFILE_OUTPUT = ROOT / "research/fixtures/dlt-profile-facts.json"
FIRMWARE_OUTPUT = ROOT / "research/fixtures/edlt-firmware-package-facts.json"
DLT_TYPES = ("KEYBL5", "KEYML5", "KEYDL4", "KEYGL5")
SPECS = ("KEYL5.xml", "KEYL4.xml", "I_DLT.xml", "I_DLTF.xml", "I_NEOCORE.xml", "KEYGL5.xml")
HELP_TOPICS = ("1944", "2092", "2111", "2113", "2160", "2500", "2501", "2506", "4825", "4838", "4898",
               "18867", "19689", "19690", "20052", "20070", "20071", "20072", "20073", "20074")
HELP_UNIT_TYPES = re.compile(r"\b(KEY[BMDG]L[45]|KEYL[45]|KEYH5)\b")
HELP_CATALOG_NAMES = re.compile(r"\b((?:[A-Z]{1,3})?5[0-9]{3}E?DL?[A-Z]?)\b")
# Toolkit 1.18.0.2754 CBusToolkit.exe (ImageBase 0x600000). The map file names
# these routines; the digests pin the exact instruction ranges reviewed.
TOOLKIT_EXE_SHA256 = "9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab"
TOOLKIT_RANGES = (
    ("TInputKeyExtensionNeo.GetLabelFlavour", 0xC99CEC, 0x25,
     "returns the stored zero-based flavour plus one"),
    ("TInputKeyExtensionNeo.SetLabelFlavour", 0xC99E00, 0x54,
     "stores the requested one-based flavour minus one"),
    ("TCBusDynamicLabelInputCGateAgent.ctor LabelFlavourLSB/MSB fields", 0x121B90F, 0x4C,
     "binds PP LabelFlavourLSB to agent field +0x20C and LabelFlavourMSB to +0x210"),
    ("TCBusDynamicLabelInputCGateAgent.LoadLabelFlavours compose", 0x121BF1D, 0x13,
     "per key: SetLabelFlavour(2*min(MSB,1) + min(LSB,1) + 1)"),
    ("TCBusDynamicLabelInputCGateAgent.SaveLabelFlavours LSB", 0x121D0FB, 0x2B,
     "per key: LSB = (GetLabelFlavour - 1) mod 2"),
    ("TCBusDynamicLabelInputCGateAgent.SaveLabelFlavours MSB", 0x121D13C, 0x20,
     "per key: MSB = (GetLabelFlavour - 1) div 2"),
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _xml(path: Path) -> ET.Element:
    raw = path.read_bytes()
    start = raw.find(b"<")
    if start < 0:
        raise ValueError(f"{path.name} contains no XML")
    return ET.fromstring(raw[start:])


def _catalogue(path: Path) -> dict:
    root = _xml(path)
    types: dict[str, dict] = {}
    for unit in root.iter("Unit"):
        revisions = unit.find("FirmwareRevisions")
        if revisions is None:
            continue
        catalogue = (unit.findtext("CatalogNumber") or "").strip()
        for revision in revisions.findall("Revision"):
            unit_type = (revision.findtext("UnitType") or "").strip()
            if unit_type not in DLT_TYPES:
                continue
            row = types.setdefault(unit_type, {"catalog_numbers": [], "revisions": [], "spec_filenames": [],
                                                "class_names": [], "input_count": None, "group_count": None})
            if catalogue not in row["catalog_numbers"]:
                row["catalog_numbers"].append(catalogue)
            for key, field in (("spec_filenames", "UnitSpecName"), ("class_names", "ClassName")):
                value = (revision.findtext(field) or "").strip()
                if value not in row[key]:
                    row[key].append(value)
            for key, field in (("input_count", "InputCount"), ("group_count", "GroupCount")):
                value = int(unit.findtext(field) or "0")
                if row[key] not in (None, value):
                    raise ValueError(f"{unit_type} catalogue {field} differs between entries")
                row[key] = value
            item = {"catalog_number": catalogue, "min": revision.findtext("MinVersion").strip(),
                    "max": revision.findtext("MaxVersion").strip(),
                    "internal": (revision.findtext("IsInternal") or "").strip().lower() == "true",
                    "default": (revision.findtext("IsDefault") or "").strip().lower() == "true"}
            row["revisions"].append(item)
    for row in types.values():
        ranges = {}
        for item in row["revisions"]:
            ranges.setdefault((item["min"], item["max"], item["internal"], item["default"]), []).append(
                item["catalog_number"])
        # Every catalogue number of one type carries identical revision rows.
        if any(sorted(numbers) != sorted(row["catalog_numbers"]) for numbers in ranges.values()):
            raise ValueError("Catalogue numbers of one unit type have different revision rows")
        row["revisions"] = [{"min": key[0], "max": key[1], "internal": key[2], "default": key[3]}
                            for key in ranges]
        row["catalog_numbers"].sort()
    return types


def _specs(directory: Path) -> dict:
    result = {}
    for name in SPECS:
        path = directory / name
        root = _xml(path)
        result[name] = {
            "sha256": _sha256(path.read_bytes()),
            "type": (root.findtext("Type") or "").strip().strip('"'),
            "min_version": (root.findtext("MinVersion") or "").strip(),
            "max_version": (root.findtext("MaxVersion") or "").strip(),
            "includes": [(item.text or "").strip() for item in root.iter("Include")],
            "declared_parameters": len(root.findall("./Parameters/Param")),
        }
    all_includes = set()
    for path in sorted(directory.glob("*.xml")):
        try:
            all_includes.update((item.text or "").strip() for item in _xml(path).iter("Include"))
        except ET.ParseError:
            continue
    for name, row in result.items():
        row["included_by_any_spec"] = name in all_includes
    return result


def _help(directory: Path) -> list:
    rows = []
    for topic in HELP_TOPICS:
        path = directory / f"{topic}.htm"
        raw = path.read_bytes()
        text = html.unescape(re.sub(r"<[^>]+>", " ", raw.decode("latin-1")))
        rows.append({"topic_id": f"help:{topic}.htm", "sha256": _sha256(raw),
                     "unit_types": sorted(set(HELP_UNIT_TYPES.findall(text))),
                     "catalog_names": sorted(set(HELP_CATALOG_NAMES.findall(text)))})
    return rows


def _toolkit(path: Path) -> dict:
    image = path.read_bytes()
    if _sha256(image) != TOOLKIT_EXE_SHA256:
        raise ValueError("Expected the pinned Toolkit 1.18.0.2754 CBusToolkit.exe")
    u16 = lambda offset: struct.unpack_from("<H", image, offset)[0]
    u32 = lambda offset: struct.unpack_from("<I", image, offset)[0]
    pe = u32(60)
    optional = pe + 24
    sections = optional + u16(pe + 20)
    base = u32(optional + 28)

    def read(va: int, length: int) -> bytes:
        rva = va - base
        for index in range(u16(pe + 6)):
            offset = sections + index * 40
            start = u32(offset + 12)
            if start <= rva < start + max(u32(offset + 8), u32(offset + 16)):
                raw = u32(offset + 20) + rva - start
                return image[raw:raw + length]
        raise ValueError("Virtual address is outside the PE sections")

    return {"sha256": TOOLKIT_EXE_SHA256, "image_base": hex(base),
            "ranges": [{"routine": name, "va": hex(va), "length": length, "sha256": _sha256(read(va, length)),
                        "semantics": meaning} for name, va, length, meaning in TOOLKIT_RANGES]}


def _aes_extra(extra: bytes) -> dict | None:
    offset = 0
    while offset + 4 <= len(extra):
        header, size = struct.unpack_from("<HH", extra, offset)
        body = extra[offset + 4:offset + 4 + size]
        if header == 0x9901 and size == 7:
            version, vendor, strength, method = struct.unpack("<H2sBH", body)
            return {"header_id": "0x9901", "vendor_version": f"AE-{version}", "vendor_id": vendor.decode("ascii"),
                    "strength_bits": {1: 128, 2: 192, 3: 256}.get(strength), "actual_compression_method": method}
        offset += 4 + size
    return None


def firmware_facts(directory: Path) -> dict:
    packages = []
    for path in sorted(directory.glob("eDLTFirmware_*.zip")):
        data = path.read_bytes()
        with zipfile.ZipFile(path) as archive:
            entries = []
            for info in archive.infolist():
                extra_ids = []
                offset = 0
                while offset + 4 <= len(info.extra):
                    header, size = struct.unpack_from("<HH", info.extra, offset)
                    extra_ids.append(f"0x{header:04x}")
                    offset += 4 + size
                aes = _aes_extra(info.extra)
                if info.compress_type == 99 and aes is not None:
                    encryption = f"winzip-aes-{aes['strength_bits']} ({aes['vendor_version']})"
                elif info.flag_bits & 1:
                    encryption = "pkware-traditional"
                else:
                    encryption = "none"
                entries.append({
                    "name": info.filename, "uncompressed_bytes": info.file_size,
                    "compressed_bytes": info.compress_size, "crc32": f"{info.CRC:08x}",
                    "compression_method": info.compress_type, "general_purpose_flags": f"0x{info.flag_bits:04x}",
                    "encrypted": bool(info.flag_bits & 1), "encryption": encryption, "aes_extra": aes,
                    "extra_field_ids": extra_ids, "version_needed": info.extract_version,
                    "version_made_by": info.create_version, "made_by_system": info.create_system,
                    "dos_timestamp": "%04d-%02d-%02dT%02d:%02d:%02d" % info.date_time,
                    "local_header_offset": info.header_offset})
            packages.append({"name": path.name, "bytes": len(data), "sha256": _sha256(data),
                             "package_version": path.stem.split("_", 1)[1], "comment_bytes": len(archive.comment),
                             "entries": entries})
    if [row["package_version"] for row in packages] != ["1.3.0", "1.4.0", "1.5.0", "1.7.0"]:
        raise ValueError("Expected the four Toolkit 1.18 eDLT firmware packages")
    return {
        "format": "cbus-edlt-firmware-package-facts-v1",
        "source": "Toolkit 1.18.0.2754 app/Firmware/eDLTFirmware",
        "method": "zip central directory only; no entry opened, decompressed or decrypted; no password used",
        "packages": packages,
        "cbus_firmware_mapping": {
            "status": "unmapped",
            "reason": ("Package versions 1.3.0..1.7.0 name updater main images; C-Bus IDENTIFY reports "
                       "catalogue revisions such as 5.5.00. No retained source maps a package to a C-Bus "
                       "firmware revision, so no eDLT profile is admitted from a package version."),
        },
    }


def profile_facts(catalogue: Path, spec_dir: Path, help_dir: Path, toolkit_exe: Path) -> dict:
    types = _catalogue(catalogue)
    help_rows = _help(help_dir)
    catalog_numbers = {number for row in types.values() for number in row["catalog_numbers"]}
    help_names = {name for row in help_rows for name in row["catalog_names"]}
    help_only = sorted(help_names - catalog_numbers)
    keygl5_help = sorted({name for row in help_rows if "KEYGL5" in row["unit_types"] for name in row["catalog_names"]})
    return {
        "format": "cbus-dlt-profile-facts-v1",
        "target": "Toolkit 1.18.0.2754 / C-Gate 3.4.0.2001",
        "inputs": {"cbusunits.xml": _sha256(catalogue.read_bytes())},
        "unit_types": types,
        "specifications": _specs(spec_dir),
        "help_topics": help_rows,
        "toolkit_label_flavour": _toolkit(toolkit_exe),
        "catalogue_alias_findings": {
            "help_catalog_names_not_in_catalogue": help_only,
            "keygl5_help_catalog_names": keygl5_help,
            "keygl5_catalogue_numbers": types["KEYGL5"]["catalog_numbers"],
            "help_names_5055EDL": "5055EDL" in help_names,
            "help_topic_20074_unit_types": next(row["unit_types"] for row in help_rows
                                                if row["topic_id"] == "help:20074.htm"),
            "catalogue_has_KEYH5": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--catalogue", type=Path, required=True, help="C-Gate app/unitspec/cbusunits.xml")
    parser.add_argument("--spec-dir", type=Path, required=True, help="Decoded unit specification directory")
    parser.add_argument("--help-dir", type=Path, required=True, help="Extracted Toolkit help topic directory")
    parser.add_argument("--toolkit-exe", type=Path, required=True, help="Toolkit 1.18.0.2754 CBusToolkit.exe")
    parser.add_argument("--firmware-dir", type=Path, required=True, help="Toolkit app/Firmware/eDLTFirmware")
    parser.add_argument("--check", action="store_true", help="Compare with the committed receipts")
    args = parser.parse_args()
    outputs = {PROFILE_OUTPUT: profile_facts(args.catalogue, args.spec_dir, args.help_dir, args.toolkit_exe),
               FIRMWARE_OUTPUT: firmware_facts(args.firmware_dir)}
    if outputs[PROFILE_OUTPUT]["catalogue_alias_findings"]["catalogue_has_KEYH5"] != (
            "KEYH5" in args.catalogue.read_text(encoding="latin-1")):
        raise ValueError("KEYH5 catalogue finding changed")
    for path, document in outputs.items():
        text = json.dumps(document, indent=2, sort_keys=False) + "\n"
        if args.check:
            if path.read_text() != text:
                print(f"{path.relative_to(ROOT)} differs from a fresh derivation", file=sys.stderr)
                return 1
        else:
            path.write_text(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
