"""Inventory an installed/extracted vendor distribution without redistributing it.

Help topics and catalog entries are evidence of scope, not passing tests.
"""
from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from zipfile import ZipFile


class InventoryError(ValueError):
    pass


class _ContentsParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.entries = []
        self.current = None
        self.depth = 0

    def handle_starttag(self, tag, attrs):
        attrs = {k.lower(): v for k, v in attrs}
        if tag == "ul":
            self.depth += 1
        elif tag == "object" and attrs.get("type") == "text/sitemap":
            self.current = {"depth": self.depth}
        elif tag == "param" and self.current is not None:
            name = attrs.get("name", "").lower()
            if name in ("name", "local"):
                self.current["title" if name == "name" else "file"] = attrs.get("value", "")

    def handle_endtag(self, tag):
        if tag == "ul":
            self.depth = max(0, self.depth - 1)
        elif tag == "object" and self.current is not None:
            if "title" in self.current:
                self.entries.append(self.current)
            self.current = None


def read_help_contents(path):
    parser = _ContentsParser()
    parser.feed(Path(path).read_text(encoding="cp1252"))
    return parser.entries


def read_commands(path):
    """Parse C-Gate's own help/cmds.txt, retaining authoritative local syntax."""
    result = []
    for block in Path(path).read_text(encoding="cp1252").split("~#~"):
        lines = block.strip().splitlines()
        if not lines or "Syntax:" not in lines:
            continue
        command = lines[0].strip()
        if not re.fullmatch(r"[A-Z0-9_ #/?.-]+", command):
            raise InventoryError(f"Unrecognized command name: {command!r}")
        syntax_start = lines.index("Syntax:") + 1
        desc_start = lines.index("Description:") if "Description:" in lines else len(lines)
        result.append({"command": command,
                       "syntax": "\n".join(lines[syntax_start:desc_start]).strip(),
                       "description": "\n".join(lines[desc_start + 1:]).strip()})
    names = [x["command"] for x in result]
    if len(names) != len(set(names)):
        raise InventoryError("Duplicate command names in vendor command reference")
    return result


def read_unit_catalog(path):
    data = Path(path).read_bytes()
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise InventoryError("DTD/entity declarations are not supported")
    root = ET.fromstring(data)
    if root.tag != "CBusUnits":
        raise InventoryError("Expected a CBusUnits catalog")
    result = []
    for unit in root.findall("./Units/Unit"):
        row = {child.tag: child.text or "" for child in unit if child.tag != "FirmwareRevisions"}
        row["FirmwareRevisions"] = [
            {child.tag: child.text or "" for child in rev}
            for rev in unit.findall("./FirmwareRevisions/Revision")
        ]
        result.append(row)
    return result


class VendorInventory:
    def __init__(self, cgate_dir, help_dir=None):
        self.cgate_dir = Path(cgate_dir)
        self.help_dir = Path(help_dir) if help_dir else None
        if not (self.cgate_dir / "cgate.jar").is_file():
            raise InventoryError("C-Gate directory must contain cgate.jar")

    def commands(self):
        return read_commands(self.cgate_dir / "help" / "cmds.txt")

    def units(self):
        return read_unit_catalog(self.cgate_dir / "unitspec" / "cbusunits.xml")

    def help_topics(self):
        if self.help_dir is None:
            raise InventoryError("Specify the extracted Toolkit help directory")
        files = list(self.help_dir.glob("*.hhc"))
        if len(files) != 1:
            raise InventoryError("Expected exactly one .hhc contents file")
        return read_help_contents(files[0])

    def manifest(self):
        commands, units = self.commands(), self.units()
        specs = sorted(self.cgate_dir.joinpath("unitspec").glob("*.xml.es"))
        selected = [self.cgate_dir / "cgate.jar", self.cgate_dir / "help/cmds.txt",
                    self.cgate_dir / "unitspec/cbusunits.xml"] + specs
        hashes = {str(p.relative_to(self.cgate_dir)): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in selected}
        unit_types = sorted({rev["UnitType"] for u in units for rev in u["FirmwareRevisions"]
                             if "UnitType" in rev})
        topics = self.help_topics() if self.help_dir else []
        with ZipFile(self.cgate_dir / "cgate.jar") as jar:
            manifest = jar.read("META-INF/MANIFEST.MF").decode("utf-8")
        # JAR attributes can wrap onto a following line beginning with a space.
        manifest = manifest.replace("\r\n ", "").replace("\n ", "")
        attrs = dict(line.split(": ", 1) for line in manifest.splitlines() if ": " in line)
        return {"scope_status": "artifact_inventory_not_functional_coverage",
                "cgate_version": attrs.get("Implementation-Version"),
                "cgate_build": attrs.get("Build-Number"),
                "commands": [x["command"] for x in commands],
                "command_count": len(commands), "unit_catalog_entries": len(units),
                "unit_types": unit_types, "unit_type_count": len(unit_types),
                "firmware_revision_entries": sum(len(x["FirmwareRevisions"]) for x in units),
                "encrypted_unit_spec_count": len(specs), "help_topics": topics,
                "help_topic_count": len(topics), "sha256": hashes}
