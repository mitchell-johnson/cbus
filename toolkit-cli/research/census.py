#!/usr/bin/env python3
"""Build a reproducible scope ledger from locally extracted vendor references.

No proprietary topic bodies or command descriptions are copied into the output.
The ledger inventories evidence; it deliberately does not infer passing tests
from a help topic, a command reference, a generic API, or a test filename.

Usage: python3 research/census.py [--check | --self-test]
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
HARDWARE_ROOTS = ("739.htm", "740.htm", "13689.htm", "2901.htm", "5407.htm",
                  "16300.htm", "1056.htm", "693.htm", "1765.htm")

# These are reviewed HHC roots, not guesses based on product terminology. The
# generator fails if a selected root disappears. Families intentionally overlap.
FAMILY_RULES = (
    ("projects", "Project lifecycle and backup", ("4639.htm", "4641.htm", "7281.htm")),
    ("networks", "Network configuration and connections", ("4634.htm", "4663.htm")),
    ("applications", "Applications, groups and levels", ("4606.htm", "4653.htm", "4657.htm", "4659.htm", "6599.htm", "15928.htm", "5711.htm", "5716.htm", "6613.htm", "5735.htm")),
    ("application_log", "Application log", ("4608.htm", "767.htm")),
    ("unit_database", "Database unit lifecycle", ("4645.htm", "4757.htm")),
    ("commissioning", "Physical unit commissioning and addressing", ("4647.htm", "4763.htm")),
    ("global_programming", "Global programming", ("4359.htm", "16943.htm")),
    ("templates", "Unit templates", ("16945.htm", "16946.htm", "16988.htm")),
    ("conversion", "Unit conversion", ("4358.htm", "1843.htm")),
    ("dynamic_labels", "Dynamic labels", ("4321.htm", "9118.htm")),
    ("scenes", "Scene programming", ("763.htm",)),
    ("timers", "Timer programming", ("744.htm",)),
    ("output_logic", "Relay and dimmer logic control", ("9433.htm",)),
    ("thermostat_schedule", "Thermostat scheduling", ("2782.htm", "2791.htm", "7036.htm")),
    ("macros", "Key macro and micro functions", ("1519.htm", "12109.htm", "14036.htm")),
    ("wireless", "Wireless units and commissioning", ("693.htm", "13994.htm")),
    ("controllers", "Controller integration", ("5407.htm", "16300.htm")),
    ("cgl", "Automation controller CGL exchange", ("16305.htm", "16306.htm", "16307.htm", "16308.htm")),
    ("reports", "Project, database and topology documentation", ("4317.htm", "7294.htm", "4357.htm", "4604.htm", "4601.htm")),
    ("topology", "Topology navigation", ("4649.htm", "379.htm")),
    ("firmware", "eDLT firmware update", ("19096.htm",)),
    ("diagnostics", "Network diagnosis and recovery", ("20144.htm", "20132.htm", "20136.htm", "11808.htm")),
    ("barcode", "Barcode scanner workflow", ("4590.htm",)),
    ("protocol_reference", "C-Bus application concepts and messages", ("4375.htm",)),
    ("unit_types", "Unit type reference", ("1945.htm",)),
    ("device_configuration", "Device configuration and device operation", HARDWARE_ROOTS),
)

# A candidate means a public command is constructed in a typed wrapper. This
# table makes no claim about argument variants, device support or acceptance.
WRAPPERS = (
    ("src/cbus_toolkit/native.py", "NativeProjects.list", ("PROJECT LIST",)),
    ("src/cbus_toolkit/native.py", "NativeProjects.directory", ("PROJECT DIR",)),
    ("src/cbus_toolkit/native.py", "NativeProjects.operation", tuple("PROJECT " + x for x in ("NEW", "USE", "LOAD", "SAVE", "CLOSE", "DELETE", "REPAIR", "COPY", "RENAME", "ARCHIVE", "RESTORE"))),
    ("src/cbus_toolkit/native.py", "NativeDatabase.get", ("DBGET", "DBGETXML")),
    ("src/cbus_toolkit/native.py", "NativeDatabase.create_network", ("PROJECT USE", "DBCREATENET", "NET LOAD")),
    ("src/cbus_toolkit/native.py", "NativeDatabase.add", ("DBADDSAFE",)),
    ("src/cbus_toolkit/native.py", "NativeDatabase.set", ("DBSETSAFE",)),
    ("src/cbus_toolkit/native.py", "NativeDatabase.copy", ("DBCOPYSAFE",)),
    ("src/cbus_toolkit/native.py", "NativeDatabase.delete", ("DBDELETE",)),
    ("src/cbus_toolkit/native.py", "NativeDatabase.validate", ("DBVALIDATE",)),
    ("src/cbus_toolkit/native.py", "NativeDatabase.rename_network", ("DBRENAMENETSAFE",)),
    ("src/cbus_toolkit/cli.py", "_cgate", ("ON", "OFF", "RAMP", "TERMINATERAMP", "GET")),
    ("src/cbus_toolkit/cgl.py", "NativeCGL.export", ("CGL EXPORT",)),
    ("src/cbus_toolkit/cgl.py", "NativeCGL.import_document", ("CGL IMPORT",)),
    ("src/cbus_toolkit/networks.py", "NativeNetworks.list", ("NET LIST", "NET LIST_ALL")),
    ("src/cbus_toolkit/networks.py", "NativeNetworks.open", ("NET OPEN",)),
    ("src/cbus_toolkit/networks.py", "NativeNetworks.close", ("NET CLOSE",)),
    ("src/cbus_toolkit/networks.py", "NativeNetworks.synchronize", ("NET SYNC",)),
    ("src/cbus_toolkit/networks.py", "NativeNetworks.sync_new", ("NET SYNCNEW",)),
    ("src/cbus_toolkit/networks.py", "NativeNetworks.discover", ("NET PINGU",)),
    ("src/cbus_toolkit/networks.py", "NativeNetworks.check_units", ("NET CHECKUNIT",)),
    ("src/cbus_toolkit/networks.py", "NativeNetworks.unravel", ("NET UNRAVEL", "NET UNRAVELUNIT")),
    ("src/cbus_toolkit/networks.py", "NativeNetworks.clocks", ("NET CLOCKS",)),
    ("src/cbus_toolkit/networks.py", "NativeNetworks.tree", ("TREE", "TREEXML", "TREEXMLDETAIL")),
    ("src/cbus_toolkit/networks.py", "NativeNetworks.rename", ("NET RENAME",)),
    ("src/cbus_toolkit/networks.py", "NativeNetworks.set_project_identity", ("NET SET_PROJECT_IDENTIFY",)),
    ("src/cbus_toolkit/networks.py", "NativeNetworks.calculate", ("CALCULATOR TEST",)),
    ("src/cbus_toolkit/labels.py", "NativeLabels.raw", ("LIGHTING LABEL", "TRIGGER LABEL", "ENABLE LABEL")),
    ("src/cbus_toolkit/labels.py", "NativeLabels.unicode_raw", ("LIGHTING UNICODELABEL", "TRIGGER UNICODELABEL")),
    ("src/cbus_toolkit/applications.py", "NativeTrigger.event", ("TRIGGER EVENT",)),
    ("src/cbus_toolkit/applications.py", "NativeTrigger.indicator_kill", ("TRIGGER INDICATORKILL",)),
    ("src/cbus_toolkit/events.py", "NativeEvents.subscribe", ("EVENT",)),
    ("src/cbus_toolkit/events.py", "NativeEvents.request_state", ("GETSTATE",)),
    ("src/cbus_toolkit/conversion.py", "NativeConversions._check", ("CONVERTUNIT CHECK",)),
    ("src/cbus_toolkit/conversion.py", "NativeConversions._convert", ("CONVERTUNIT CONVERT",)),
    ("src/cbus_toolkit/scenes.py", "NativeScenes.play", ("SCENE PLAY",)),
    ("src/cbus_toolkit/scenes.py", "NativeScenes.record", ("SCENE RECORD",)),
    ("src/cbus_toolkit/enable.py", "NativeEnable.set", ("ENABLE SET",)),
    ("src/cbus_toolkit/enable.py", "NativeEnable.remove", ("ENABLE REMOVE",)),
    ("src/cbus_toolkit/serials.py", "NativeSerials._get", ("GET",)),
    ("src/cbus_toolkit/serials.py", "NativeSerials.refresh", ("NET SYNC", "NET CHECKUNIT")),
    ("src/cbus_toolkit/physical_addressing.py", "PhysicalAddressing.apply", ("SET",)),
    ("src/cbus_toolkit/serial_commissioning.py", "SerialCommissioning.apply", ("SET",)),
)

GAPS = (
    ("P0", "device_semantics", "Resolve each device dialog's fields, dependencies and native serialization", ("device_configuration", "unit_types", "macros"),
     "Map each dialog control to an exact unit type/firmware parameter or command; test valid and invalid settings, roundtrip serialization and preservation of unrelated values. Generic PP get/set and catalogue creation do not verify a dialog's full semantics."),
    ("P0", "physical_commissioning", "Test commissioning against observable network behavior", ("commissioning", "networks", "diagnostics"),
     "Implement and verify scan, unravel, serial-number readdressing, database/network reconciliation, transfer and recovery workflows with a faithful simulator or hardware fixtures. A closed-network backend acceptance cannot verify bus effects."),
    ("P1", "scene_macro_timer", "Implement scene, macro and timer workflows", ("scenes", "macros", "timers", "output_logic"),
     "Resolve native tables, sequencing, capacity limits and interdependent parameters, then compare generated programming and simulated behavior with vendor outcomes for each applicable device family."),
    ("P1", "labels_and_bulk", "Verify dynamic labels and global programming", ("dynamic_labels", "global_programming"),
     "Cover label encodings and language variants, eDLT widgets/standby/colour settings, bulk selection, partial failure reporting and preservation of per-unit differences."),
    ("P1", "templates_conversion", "Verify vendor template exchange and unit conversion", ("templates", "conversion"),
     "Compare Toolkit template files and conversion results, including compatible parameter transfer, defaults, unsupported fields and identity/address handling. A custom parameter export is not proof of the vendor template format."),
    ("P1", "firmware_update", "Resolve and test the eDLT firmware updater workflow", ("firmware",),
     "Inventory the separate updater's inputs and protocol, version compatibility, staged transfer and recovery. The help topic establishes this surface; this ledger does not verify an implementation."),
    ("P1", "native_project_workflows", "Complete project exchange and documentation acceptance", ("projects", "cgl", "reports", "topology"),
     "Exercise vendor backups/restores, CGL import/export, project/database documentation and topology operations with comparable expected outputs, preserving identities and reference integrity."),
    ("P2", "specialized_devices", "Verify thermostat scheduling and wireless behavior", ("thermostat_schedule", "wireless", "controllers"),
     "Test schedules, zones, learn/join behavior and gateway mappings on the relevant devices. Determine which controller programming is delegated to external applications before expanding Toolkit scope."),
    ("P2", "remaining_application_protocols", "Verify remaining C-Gate application commands and configuration", ("protocol_reference", "application_log", "applications"),
     "Turn public command grammar variants into positive/negative acceptance cases, including monitoring and event streams. Keep reference-only protocol topics separate from Toolkit editors."),
    ("P2", "barcode_workflow", "Resolve scanner input and identification behavior", ("barcode",),
     "Specify scanner payloads, input handling and resulting project/unit selection or creation using vendor evidence; generic string input is insufficient evidence."),
)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def clean(text):
    return " ".join(text.split())


class ContentsParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.current = None
        self.entries = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "ul":
            self.depth += 1
        elif tag == "object" and values.get("type") == "text/sitemap":
            self.current = {"depth": self.depth, "contents_line": self.getpos()[0]}
        elif tag == "param" and self.current is not None:
            name = values.get("name", "").lower()
            if name in ("name", "local"):
                self.current["title" if name == "name" else "file"] = clean(values.get("value", ""))

    def handle_endtag(self, tag):
        if tag == "ul":
            self.depth -= 1
            if self.depth < 0:
                raise ValueError("Unbalanced help navigation list")
        elif tag == "object" and self.current is not None:
            if "title" in self.current:
                if not self.current.get("file"):
                    raise ValueError("Help navigation entry has no local file")
                self.entries.append(self.current)
            self.current = None


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.capture = None
        self.buffer = []
        self.title = ""
        self.headings = []
        self.anchors = []
        self.links = set()
        self.external_product_mentions = set()

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "title" or re.fullmatch("h[1-6]", tag):
            self.capture = (tag, self.getpos()[0])
            self.buffer = []
        anchor = values.get("id") or (values.get("name") if tag == "a" else None)
        if anchor:
            self.anchors.append({"name": anchor, "line": self.getpos()[0]})
        if tag == "a" and values.get("href"):
            href = urlsplit(values["href"])
            if not href.scheme and not href.netloc and href.path.lower().endswith((".htm", ".html")):
                self.links.add(unquote(href.path))

    def handle_data(self, data):
        if self.capture:
            self.buffer.append(data)
        # Names are metadata only; a mention does not establish an integration.
        for name in ("PICED", "CIRCA", "MARPA", "HomeGate", "Schedule Plus"):
            if re.search(r"\b" + re.escape(name) + r"\b", data, re.I):
                self.external_product_mentions.add(name)

    def handle_endtag(self, tag):
        if self.capture and self.capture[0] == tag:
            label = clean("".join(self.buffer))
            if tag == "title":
                self.title = label
            elif label:
                heading = {"tag": tag, "line": self.capture[1], "sha256": digest(label.encode("utf-8"))}
                # Long prose embedded in heading elements is deliberately omitted.
                if len(label) <= 140:
                    heading["label"] = label
                self.headings.append(heading)
            self.capture = None
            self.buffer = []


def parse_contents(path):
    parser = ContentsParser()
    parser.feed(path.read_text(encoding="cp1252"))
    if parser.depth:
        raise ValueError("Unclosed help navigation list")
    stack = []
    seen = set()
    for ordinal, item in enumerate(parser.entries):
        if item["file"] in seen:
            raise ValueError("Duplicate help topic local file: " + item["file"])
        seen.add(item["file"])
        if item["depth"] > len(stack) + 1:
            raise ValueError("Help navigation skipped a parent level")
        stack = stack[:item["depth"] - 1]
        item.update({"id": "help:" + item["file"], "ordinal": ordinal,
                     "parent_id": stack[-1] if stack else None,
                     "ancestor_ids": list(stack), "children": []})
        stack.append(item["id"])
    by_id = {row["id"]: row for row in parser.entries}
    for row in parser.entries:
        if row["parent_id"]:
            by_id[row["parent_id"]]["children"].append(row["id"])
    return parser.entries


def parse_commands(path):
    lines = path.read_text(encoding="cp1252").splitlines()
    cuts = [-1] + [i for i, line in enumerate(lines) if line == "~#~"] + [len(lines)]
    result = []
    for start, end in zip(cuts, cuts[1:]):
        indexed = [(i, lines[i]) for i in range(start + 1, end) if lines[i].strip()]
        if not indexed:
            continue
        header_line, command = indexed[0]
        syntax_marks = [i for i, line in indexed if line == "Syntax:"]
        if not syntax_marks:
            continue
        if len(syntax_marks) != 1 or not re.fullmatch(r"[A-Z0-9_ #/?.-]+", command):
            raise ValueError("Invalid command block at line " + str(header_line + 1))
        syntax_start = syntax_marks[0] + 1
        syntax_end = next((i for i in range(syntax_start, end) if lines[i] == "Description:"), end)
        syntax = "\n".join(lines[syntax_start:syntax_end]).strip()
        # The whole grammar remains in the vendor file. Only its checksum and
        # source locations are distributed, avoiding copied explanatory prose.
        result.append({"id": "cgate:" + command, "command": command,
                       "family": "DB" if command.startswith("DB") else command.split()[0],
                       "source": {"path": "research/vendor/cgate/app/help/cmds.txt", "line": header_line + 1,
                                  "syntax_start_line": syntax_start + 1, "syntax_end_line": syntax_end,
                                  "syntax_sha256": digest(syntax.encode("utf-8"))},
                       "raw_cli_route": "cbus-toolkit cgate exec '<command>'",
                       "typed_wrapper_candidates": [], "acceptance_status": "unassessed",
                       "acceptance_evidence": []})
    if len({r["command"] for r in result}) != len(result):
        raise ValueError("Duplicate C-Gate command block")
    return result


def symbols(path):
    """Return stable qualified names and current source locations, using AST."""
    result = {}
    tree = ast.parse(path.read_text(encoding="utf-8"))

    def visit(nodes, prefix=""):
        for node in nodes:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = prefix + node.name
                result[name] = {"symbol": name, "path": path.relative_to(ROOT).as_posix(),
                                "line": node.lineno, "end_line": node.end_lineno}
                visit(node.body, name + ".")
    visit(tree.body)
    return result


def artifact(path):
    data = path.read_bytes()
    return {"path": path.relative_to(ROOT).as_posix(), "bytes": len(data), "sha256": digest(data)}


def build(help_dir, command_path):
    contents = help_dir / "Toolkit Help.hhc"
    topics = parse_contents(contents)
    by_id = {t["id"]: t for t in topics}
    required_roots = {"help:" + f for _, _, files in FAMILY_RULES for f in files}
    required_roots.update("help:" + f for f in ("6536.htm", "6861.htm", "1519.htm", "1944.htm", "2182.htm", "13916.htm"))
    missing = required_roots - by_id.keys()
    if missing:
        raise ValueError("Reviewed scope roots missing: " + ", ".join(sorted(missing)))
    pages = {}
    for path in sorted(help_dir.glob("*.htm")):
        parser = PageParser()
        data = path.read_bytes()
        parser.feed(data.decode("cp1252"))
        pages[path.name] = {"file": path.name, "html_title": parser.title, "sha256": digest(data),
                            "headings": parser.headings, "anchors": parser.anchors,
                            "linked_topic_files": sorted(parser.links),
                            "external_product_mentions": sorted(parser.external_product_mentions)}
    for item in topics:
        if item["file"] not in pages:
            raise ValueError("Missing indexed topic: " + item["file"])
        item["page"] = pages[item["file"]]
        item["source"] = {"path": (help_dir / item["file"]).relative_to(ROOT).as_posix(),
                          "contents_path": contents.relative_to(ROOT).as_posix(),
                          "contents_line": item.pop("contents_line")}
        lineage = set(item["ancestor_ids"] + [item["id"]])
        item["family_ids"] = [key for key, _, roots in FAMILY_RULES if lineage.intersection("help:" + r for r in roots)]
        top = (item["ancestor_ids"] + [item["id"]])[0]
        item["root_id"] = top
        if top in {"help:4375.htm", "help:1945.htm", "help:1519.htm", "help:181.htm"}:
            role = "reference"
        elif top in {"help:4637.htm", "help:4635.htm", "help:691.htm"}:
            role = "workflow_documentation"
        elif top in {"help:" + f for f in HARDWARE_ROOTS}:
            role = "device_documentation"
        else:
            role = "navigation_or_support"
        item["role"] = role
        item["acceptance_status"] = "unassessed"
        item["acceptance_evidence"] = []

    def descendants(topic_id):
        return [t["id"] for t in topics if topic_id == t["id"] or topic_id in t["ancestor_ids"]]

    def tree(topic_id):
        topic = by_id[topic_id]
        return {"topic_id": topic_id, "title": topic["title"],
                "children": [tree(child) for child in topic["children"]]}

    families = []
    for key, label, roots in FAMILY_RULES:
        members = [t["id"] for t in topics if key in t["family_ids"]]
        families.append({"id": key, "name": label, "rule": "union_of_reviewed_navigation_subtrees",
                         "root_topic_ids": ["help:" + f for f in roots], "topic_ids": members,
                         "topic_count": len(members), "acceptance_status": "unassessed"})

    dialogs = []
    for topic in topics:
        title = topic["title"].lower()
        if topic["root_id"] not in {"help:" + f for f in HARDWARE_ROOTS}:
            continue
        if "configuration dialog box" not in title or title.startswith("example"):
            continue
        lineage = [by_id[i]["title"] for i in topic["ancestor_ids"]]
        dialogs.append({"id": "dialog:" + topic["file"], "topic_id": topic["id"],
                        "title": topic["title"], "device_path": lineage,
                        "scope_rule": "hardware_branch_title_contains_configuration_dialog_box",
                        "descendant_topic_ids": descendants(topic["id"]),
                        "direct_children": list(topic["children"]),
                        "acceptance_status": "unassessed", "acceptance_evidence": []})

    macro_leaves = [t["id"] for t in topics if "help:1519.htm" in t["ancestor_ids"] and not t["children"]]
    type_entries = [t["id"] for t in topics if t["parent_id"] in ("help:1944.htm", "help:2182.htm", "help:13916.htm")]
    command_rows = parse_commands(command_path)
    command_by_name = {r["command"]: r for r in command_rows}
    code_files = sorted({path for path, _, _ in WRAPPERS} | {"src/cbus_toolkit/programming.py"})
    source_symbols = {path: symbols(ROOT / path) for path in code_files if (ROOT / path).is_file()}
    extra_wrappers = []
    for path, symbol, names in WRAPPERS:
        ref = source_symbols.get(path, {}).get(symbol)
        if ref is None:
            raise ValueError("Reviewed wrapper missing: " + path + ":" + symbol)
        for name in names:
            if name in command_by_name:
                command_by_name[name]["typed_wrapper_candidates"].append(ref)
            else:
                extra_wrappers.append({"command": name, "source": ref,
                                       "status": "wrapper_not_in_public_reference"})
    raw_reference = source_symbols["src/cbus_toolkit/cli.py"]["_cgate"]
    unindexed = [row for filename, row in pages.items() if "help:" + filename not in by_id]
    branches = [{"topic_id": t["id"], "title": t["title"], "topic_count": len(descendants(t["id"]))}
                for t in topics if t["parent_id"] is None]
    command_families = []
    for name, count in sorted(Counter(c["family"] for c in command_rows).items()):
        rows = [c for c in command_rows if c["family"] == name]
        command_families.append({"name": name, "command_count": count,
                                 "typed_wrapper_candidate_count": sum(bool(c["typed_wrapper_candidates"]) for c in rows),
                                 "acceptance_verified_count": 0})
    gap_rows = [{"priority": priority, "id": key, "task": label, "family_ids": list(family_ids),
                 "acceptance_needed": needed, "assessment": "open_scope_item_not_proven_absent_from_code"}
                for priority, key, label, family_ids, needed in GAPS]
    test_assets = []
    for path in sorted((ROOT / "tests").glob("test_*.py")):
        tests = [ref for symbol, ref in symbols(path).items() if symbol.split(".")[-1].startswith("test_")]
        test_assets.append({**artifact(path), "test_definitions": len(tests),
                            "status": "source_present_results_not_imported"})
    external_mentions = [{"topic_id": t["id"], "products": t["page"]["external_product_mentions"]}
                         for t in topics if t["page"]["external_product_mentions"]]
    title_searches = []
    for name, pattern in (("scene", r"scene"), ("schedule", r"schedul"),
                          ("logic", r"logic"), ("firmware", r"firmware"),
                          ("security", r"security"), ("dynamic_labels", r"\bdlt\b|dynamic label"),
                          ("templates", r"template"), ("diagnostics", r"diagnos|unravel|recovery")):
        matches = [t["id"] for t in topics if re.search(pattern, t["title"], re.I)]
        title_searches.append({"name": name, "title_regex": pattern, "topic_ids": matches,
                               "status": "crosscutting_title_matches_requiring_manual_review"})
    missing_links = [{"file": filename, "target": target} for filename, page in pages.items()
                     for target in page["linked_topic_files"] if not (help_dir / target).is_file()]
    catalogue_path = ROOT / "research/vendor/cgate/app/unitspec/cbusunits.xml"
    catalogue = ET.fromstring(catalogue_path.read_bytes())
    revisions = catalogue.findall("./Units/Unit/FirmwareRevisions/Revision")
    native_manifest = ROOT / "research/vendor/cgate/app/cgate.jar"
    sources = [contents, command_path, catalogue_path, native_manifest]
    chm = ROOT / "research/vendor/toolkit/app/Toolkit Help.chm"
    if chm.is_file():
        sources.append(chm)
    backend_observations = []
    project_probe = ROOT / "docs/native-project-acceptance.json"
    if project_probe.is_file():
        probe = json.loads(project_probe.read_text(encoding="utf-8"))
        repairs = [r for r in probe.get("operations", []) if r.get("operation", "").startswith("repair-")
                   and r.get("status") == "fail" and "408" in r.get("error", "")
                   and "does not support this command" in r.get("error", "")]
        if repairs:
            backend_observations.append({"command": "PROJECT REPAIR", "status": "observed_backend_limitation",
                                         "finding": "The repository selected in this historical probe rejected repair with code 408. This observation does not establish the behavior of other repository types or the currently running service.",
                                         "evidence": artifact(project_probe), "operation_ids": [r["operation"] for r in repairs],
                                         "server": probe.get("server")})
    return {
        "schema_version": 1,
        "purpose": "Finite vendor documentation scope inventory; not a claim of complete Toolkit functionality or passing acceptance.",
        "vendor_release": {"toolkit": "1.18.0.2754", "cgate": "3.4.0.2001",
                           "release_basis": "extracted installer CBusToolkit-1.18.0.2754-CGate-3.4.0.2001-Setup.exe"},
        "reproduction": "python3 research/census.py; python3 research/census.py --check; python3 research/census.py --self-test",
        "source_artifacts": [artifact(path) for path in sources],
        "scope_rules": [
            "One indexed topic is one HHC entry, not one implemented function. Branch pages, tutorials, duplicated model/firmware dialogs and references stay distinct.",
            "One public command is one named cmds.txt block, including namespace help and comment commands. Grammar alternatives are hashed and source-referenced, not counted as separate features.",
            "Workflow families use explicitly reviewed HHC subtree roots and intentionally overlap. Their counts must not be summed as a functional denominator.",
            "Device dialogs are title-based candidates within hardware branches. A differently named editor may require manual review; this list is not a complete dialog-control inventory.",
            "Raw CLI command forwarding provides a route to the backend; it does not verify command arguments, authorization, responses, hardware effects, or Toolkit workflows.",
            "Typed wrapper candidates are manually reviewed mappings to existing Python symbols. Source presence is not behavioral verification.",
            "Every topic and public command starts unassessed. No test result is inferred from source files; no functional coverage percentage is computed.",
            "A complete parity claim also requires controls/branches in the executable, undocumented/internal commands, external tool boundaries, device/firmware variants and real bus effects beyond this documentation census.",
            "Only short topic/heading names, product mentions, IDs, paths, line numbers and hashes are emitted. Vendor prose, images and command descriptions remain local.",
        ],
        "counts": {
            "indexed_topics": len(topics), "indexed_topic_files": len({t["file"] for t in topics}),
            "html_files": len(pages), "unindexed_html_files": len(unindexed), "top_level_branches": len(branches),
            "workflow_families": len(families), "topics_with_workflow_family": sum(bool(t["family_ids"]) for t in topics),
            "device_dialog_candidates": len(dialogs), "macro_reference_leaves": len(macro_leaves),
            "unit_type_reference_entries": len(type_entries), "public_command_blocks": len(command_rows),
            "public_command_families": len(command_families),
            "public_commands_with_raw_route": len(command_rows),
            "public_commands_with_typed_wrapper_candidates": sum(bool(c["typed_wrapper_candidates"]) for c in command_rows),
            "topic_acceptance_verified": 0, "command_acceptance_verified": 0,
            "catalogue_units": len(catalogue.findall("./Units/Unit")), "catalogue_firmware_revisions": len(revisions),
            "catalogue_unit_types": len({r.findtext("UnitType") for r in revisions if r.findtext("UnitType")}),
            "html_heading_records": sum(len(p["headings"]) for p in pages.values()),
            "html_anchor_records": sum(len(p["anchors"]) for p in pages.values()),
        },
        "top_level_navigation": branches,
        "main_navigation_tree": tree("help:6536.htm"), "main_menu_tree": tree("help:6861.htm"),
        "workflow_families": families, "prioritized_open_scope": gap_rows,
        "device_dialog_candidates": dialogs,
        "macro_reference": {"root_topic_id": "help:1519.htm", "tree": tree("help:1519.htm"), "leaf_topic_ids": macro_leaves},
        "unit_type_reference_entries": type_entries,
        "external_product_mentions": external_mentions,
        "crosscutting_title_matches": title_searches,
        "local_topic_link_validation": {"checked_links": sum(len(p["linked_topic_files"]) for p in pages.values()),
                                        "missing_targets": missing_links},
        "scope_boundaries": [
            {"topic_ids": ["help:5414.htm", "help:13447.htm"], "finding": "These controller dialog topics identify PICED as the programming application. Define integration versus external-application scope before claiming controller editor parity."},
            {"topic_ids": ["help:12335.htm", "help:12336.htm", "help:12338.htm"], "finding": "Security is documented as an application/message reference; this evidence does not establish a Toolkit security-system editor."},
            {"topic_ids": ["help:2782.htm", "help:2791.htm", "help:7036.htm"], "finding": "The navigation explicitly documents thermostat scheduling; this does not establish a standalone general scheduler."},
            {"topic_ids": ["help:9433.htm", "help:9855.htm", "help:9858.htm"], "finding": "Relay/dimmer logic control is an explicit Toolkit workflow; controller logic-engine code editing may belong to external software."},
            {"topic_ids": ["help:19096.htm"], "finding": "Firmware updating is explicitly documented for the eDLT updater; other device updater scope needs separate evidence."},
        ],
        "public_command_families": command_families, "public_commands": command_rows,
        "raw_command_implementation": {"source": raw_reference, "route": "cbus-toolkit cgate exec '<command>'",
                                       "status": "static_forwarding_route_present_not_command_acceptance"},
        "wrappers_outside_public_reference": extra_wrappers,
        "backend_limitations": backend_observations,
        "internal_command_boundary": {"source": artifact(ROOT / "src/cbus_toolkit/programming.py"),
                                      "finding": "ProgrammingSession uses internal PP commands absent from this public reference; internal grammar and access-level acceptance need a separate ledger."},
        "implementation_sources": [artifact(ROOT / path) for path in code_files if (ROOT / path).is_file()],
        "test_source_inventory": test_assets,
        "unindexed_html": unindexed,
        "topics": topics,
    }


def escape(text):
    return str(text).replace("|", "\\|").replace("\n", " ")


def markdown(data):
    counts = data["counts"]
    topics = {t["id"]: t for t in data["topics"]}

    def link(topic_id):
        topic = topics[topic_id]
        return "[" + escape(topic["title"]) + "](../" + topic["source"]["path"] + ")"

    def nav_lines(tree, indent=0):
        result = ["  " * indent + "- " + link(tree["topic_id"])]
        for child in tree["children"]:
            result.extend(nav_lines(child, indent + 1))
        return result

    rows = ["# Toolkit 1.18 scope census", "",
            "This is a documentation inventory and implementation map, not a functional coverage report. "
            "The complete machine ledger is [toolkit-surface.json](toolkit-surface.json). "
            "Rebuild from the locally extracted vendor distribution with `python3 research/census.py`; "
            "use `--check` to detect changed sources or stale output and `--self-test` to test the parsers.", "",
            "The exact Toolkit help navigation contains **" + str(counts["indexed_topics"]) + " topics** in **" + str(counts["top_level_branches"]) +
            " branches**. The C-Gate public reference contains **" + str(counts["public_command_blocks"]) +
            " named command blocks**. All have a generic raw CLI forwarding route; **" + str(counts["public_commands_with_typed_wrapper_candidates"]) +
            "** have a mapped typed wrapper candidate. Neither count is proof that those workflows work. "
            "No acceptance results are imported into this ledger, so all topic and command acceptance states are `unassessed`.", "",
            "## Counting rules", ""]
    rows.extend("- " + text for text in data["scope_rules"])
    rows.extend(["", "The " + str(counts["unindexed_html_files"]) + " HTML files outside the navigation are help-frame/index templates, "
                 "not six additional established user functions. The JSON records their titles and hashes. "
                 "Every indexed topic has its navigation ancestry, source file and contents line, HTML title, short headings, anchors, "
                 "local topic links and source hash.", "", "## Main help branches", "",
                 "| Branch | Topics including branch |", "| --- | ---: |"])
    rows.extend("| " + link(r["topic_id"]) + " | " + str(r["topic_count"]) + " |" for r in data["top_level_navigation"])
    rows.extend(["", "## Toolkit navigation and menu", "", "These are the actual navigation-tree and main-menu help subtrees.", ""])
    rows.extend(nav_lines(data["main_navigation_tree"]))
    rows.append("")
    rows.extend(nav_lines(data["main_menu_tree"]))
    rows.extend(["", "## Workflow families", "", "Families overlap. Root topic links establish why each family is in scope; "
                 "the JSON contains all member topic IDs. Each still needs a testable behavioral specification.", "",
                 "| Family | Topics | Evidence roots |", "| --- | ---: | --- |"])
    rows.extend("| " + escape(f["name"]) + " | " + str(f["topic_count"]) + " | " + "; ".join(link(t) for t in f["root_topic_ids"]) + " |"
                for f in data["workflow_families"])
    rows.extend(["", "## Prioritized unresolved acceptance", "", "These are open scope items, not an automated assertion that their entire implementation is missing.", ""])
    for gap in data["prioritized_open_scope"]:
        rows.extend(["- **" + gap["priority"] + ": " + gap["task"] + ".** " + gap["acceptance_needed"], ""])
    rows.extend(["## Boundaries requiring explicit decisions", ""])
    rows.extend("- " + r["finding"] + " Evidence: " + "; ".join(link(i) for i in r["topic_ids"]) + "." for r in data["scope_boundaries"])
    rows.extend(["", "## Device dialog candidates", "",
                 "The hardware branches contain **" + str(counts["device_dialog_candidates"]) +
                 " configuration-dialog candidates** selected by their exact topic names. "
                 "Model and firmware variants remain separate even when titles repeat. "
                 "This inventory is a starting point for control-by-control parity; generic parameter editing is not a substitute for that assessment. "
                 "The JSON lists each dialog's descendant topic IDs and direct child tabs. "
                 "The separate unit catalogue contains " + str(counts["catalogue_units"]) + " unit records, " + str(counts["catalogue_firmware_revisions"]) +
                 " revision records and " + str(counts["catalogue_unit_types"]) + " unit types; none of these counts establish device acceptance.", "",
                 "| Dialog | Parent context | Subtree topics |", "| --- | --- | ---: |"])
    rows.extend("| " + link(d["topic_id"]) + " | " + escape(" / ".join(d["device_path"][-2:])) + " | " + str(len(d["descendant_topic_ids"])) + " |"
                for d in data["device_dialog_candidates"])
    rows.extend(["", "The JSON also contains the full macro/micro-function reference tree with **" + str(counts["macro_reference_leaves"]) +
                 " leaves**, and **" + str(counts["unit_type_reference_entries"]) +
                 " direct wired/wireless/remote unit-type reference entries**. Leaf and unit-type counts are documentation counts, not verified behaviors. "
                 "Crosscutting title searches separately locate scene, schedule, logic, firmware, security, label, template and diagnostic topics across all branches; "
                 "these search matches need manual review and do not enlarge the reviewed subtree families automatically.", "",
                 "## Public C-Gate command inventory", "",
                 "Every command block is recorded with its exact name, source line range, grammar checksum, raw route, mapped wrapper symbols and an empty acceptance-evidence list. "
                 "The command descriptions and full syntax prose remain in the local vendor reference. Namespace-help commands and comment commands are included. "
                 "The reference's spelling is preserved, including `SECURITY RAISE_ ALARM`.", "",
                 "| Command family | Public blocks | Typed wrapper candidates |", "| --- | ---: | ---: |"])
    rows.extend("| " + escape(r["name"]) + " | " + str(r["command_count"]) + " | " + str(r["typed_wrapper_candidate_count"]) + " |"
                for r in data["public_command_families"])
    rows.extend(["", "`PROJECT ARCHIVE` is constructed by the project wrapper but absent from this public command reference. "
                 "Internal `PP` programming commands are also outside it. A public-command census alone therefore cannot establish either the complete backend surface or Toolkit parity.", "",
                 "## Evidence and completion criteria", "",
                 "A defensible completion claim needs a reviewed mapping from each actionable help topic and executable control to Python behavior, "
                 "with positive, negative and preservation tests; device/firmware coverage; expected bus effects; and a justified disposition for "
                 "reference-only topics and external applications. Record actual test artifacts against ledger IDs, with the tested vendor build and fixture. "
                 "A feature must not become verified merely because a raw command or parameter name exists.", "",
                 "Source snapshots below make this census reproducible. Python source/test hashes in the JSON describe the inspected implementation snapshot; "
                 "they do not claim that those tests were executed.", "",
                 "| Artifact | SHA-256 |", "| --- | --- |"])
    rows.extend("| [" + escape(r["path"]) + "](../" + r["path"] + ") | `" + r["sha256"] + "` |" for r in data["source_artifacts"])
    for observation in data["backend_limitations"]:
        rows.extend(["", "Historical backend observation: `" + observation["command"] + "` returned 408 for the repository selected in the "
                     "[native project probe](native-project-acceptance.json). "
                     "That probe records " + str(len(observation["operation_ids"])) +
                     " rejected repair attempts. This is not a limitation established for every repository type or for the currently running service. "
                     "The separate [project repair research](project-repair-native.md) distinguishes SQLite and XML repository behavior. "
                     "[Portable XML repair](project-repair.md) has separate original-code, native-load and CLI file-boundary acceptance; "
                     "these results do not change this documentation census's unassessed topic states."])
    return "\n".join(rows) + "\n"


def validate(data):
    topics = data["topics"]
    ids = {t["id"] for t in topics}
    if len(topics) != len(ids):
        raise ValueError("Duplicate topic IDs")
    for row in topics:
        if row["parent_id"] and row["parent_id"] not in ids:
            raise ValueError("Missing navigation parent")
        if any(x not in ids for x in row["children"] + row["ancestor_ids"]):
            raise ValueError("Broken navigation reference")
    for row in data["workflow_families"]:
        if any(t not in ids for t in row["root_topic_ids"] + row["topic_ids"]):
            raise ValueError("Broken family reference")
    for boundary in data["scope_boundaries"]:
        if any(t not in ids for t in boundary["topic_ids"]):
            raise ValueError("Broken scope boundary reference")
    if sum(t["topic_count"] for t in data["top_level_navigation"]) != len(topics):
        raise ValueError("Top-level branches do not partition the topics")
    if sum(r["command_count"] for r in data["public_command_families"]) != len(data["public_commands"]):
        raise ValueError("Command family counts do not partition commands")
    if any(row["acceptance_status"] != "unassessed" or row["acceptance_evidence"] for row in topics + data["public_commands"]):
        raise ValueError("Generator must not invent acceptance evidence")
    if any("help:" + row["file"] in ids for row in data["local_topic_link_validation"]["missing_targets"]):
        raise ValueError("Help HTML contains unresolved local topic links")


def self_test():
    import tempfile
    import unittest

    class ParserTests(unittest.TestCase):
        def test_navigation_hierarchy_and_lines(self):
            with tempfile.TemporaryDirectory() as temp:
                p = Path(temp) / "contents.hhc"
                p.write_text('<UL>\n<LI><OBJECT type="text/sitemap"><param name="Name" value="A &amp; B"><param name="Local" value="1.htm"></OBJECT>\n<UL><LI><OBJECT type="text/sitemap"><param name="Name" value="Child"><param name="Local" value="2.htm"></OBJECT></UL></UL>')
                rows = parse_contents(p)
                self.assertEqual(rows[0]["title"], "A & B")
                self.assertEqual(rows[0]["contents_line"], 2)
                self.assertEqual(rows[1]["parent_id"], "help:1.htm")
                self.assertEqual(rows[0]["children"], ["help:2.htm"])

        def test_missing_and_duplicate_files_rejected(self):
            with tempfile.TemporaryDirectory() as temp:
                p = Path(temp) / "contents.hhc"
                entry = '<OBJECT type="text/sitemap"><param name="Name" value="A"><param name="Local" value="1.htm"></OBJECT>'
                p.write_text("<UL>" + entry + entry + "</UL>")
                with self.assertRaisesRegex(ValueError, "Duplicate"):
                    parse_contents(p)

        def test_commands_keep_source_ranges_and_preserve_typo(self):
            with tempfile.TemporaryDirectory() as temp:
                p = Path(temp) / "cmds.txt"
                p.write_text("#\nSyntax:\n# [text]\nDescription:\nprivate description\n~#~\nSECURITY RAISE_ ALARM\nSyntax:\nSECURITY RAISE_ALARM address\narg description\nDescription:\nprivate details\n")
                rows = parse_commands(p)
                self.assertEqual(rows[1]["command"], "SECURITY RAISE_ ALARM")
                self.assertEqual(rows[1]["source"]["line"], 7)
                self.assertEqual(rows[1]["source"]["syntax_start_line"], 9)
                self.assertEqual(rows[1]["source"]["syntax_end_line"], 10)
                self.assertNotIn("private", json.dumps(rows))

        def test_page_metadata_omits_body(self):
            p = PageParser()
            p.feed('<title> A &amp; B </title><h4>Short <b>heading</b></h4><a name="xyz"></a><a href="123.htm#x">go</a><p>secret body PICED</p><h2>' + "Long prose " * 30 + "</h2>")
            self.assertEqual(p.title, "A & B")
            self.assertEqual(p.headings[0]["label"], "Short heading")
            self.assertNotIn("label", p.headings[1])
            self.assertEqual(p.anchors[0]["name"], "xyz")
            self.assertEqual(p.links, {"123.htm"})
            self.assertEqual(p.external_product_mentions, {"PICED"})

    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ParserTests))
    return result.wasSuccessful()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if checked-in ledger differs from current source snapshot")
    parser.add_argument("--self-test", action="store_true", help="run parser regression tests without vendor files")
    args = parser.parse_args()
    if args.self_test:
        return 0 if self_test() else 1
    data = build(ROOT / "research/vendor/toolkit-help", ROOT / "research/vendor/cgate/app/help/cmds.txt")
    validate(data)
    outputs = {ROOT / "docs/toolkit-surface.json": json.dumps(data, ensure_ascii=False, indent=2) + "\n",
               ROOT / "docs/toolkit-surface.md": markdown(data)}
    stale = []
    for path, content in outputs.items():
        if args.check:
            if not path.is_file() or path.read_text(encoding="utf-8") != content:
                stale.append(path.relative_to(ROOT).as_posix())
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
    if stale:
        print("Stale census output: " + ", ".join(stale), file=sys.stderr)
        return 1
    print(json.dumps({"status": "current" if args.check else "generated", **data["counts"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
