#!/usr/bin/env python3
"""Capture native CGL 1.1 route, metadata and conflict behavior.

An owned loopback C-Gate 3.4.0.2001 child receives disposable database-only
projects. ``CGLP`` chains Bridge-type database Units 254→253→…→247 (seven
bridge hops, one beyond the six-network route bound) plus an unbridged island
network 240; its network 254 CNI endpoint is this process's loopback PCI
simulator so the capture can show that CGL IMPORT/EXPORT put nothing on the
PCI. ``CGLT`` holds a branching topology (UnitType prefixes, ``GATE``
substrings, a cycle, a dangling bridge, equal-length alternatives and a
reverse-only hop). ``CGLN`` records the nameless-object persistence hazard.

Replies are normalized for OIDs, ``createdTime`` and the simulator port. The
committed fixture keeps every stable exchange; the one large import is
summarized by line count, edges and SHA-256. No site project, vendor source,
hardware or LAN endpoint is used.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import tempfile
import time

from research.local_cgate import LocalCGate

FORMAT = "cbus-native-cgl-routes-v1"
CHAIN = (253, 252, 251, 250, 249, 248, 247)
TIMESTAMP = re.compile(r'"createdTime":"[^"]+"')
LARGE_GROUPS, LARGE_LEVELS = 255, 40


def cgl(local, networks, **root):
    return json.dumps({"cglVersion": "1.1", **root, "localNetwork": local, "networks": networks},
                      separators=(",", ":"))


LARGE_GENERATOR = {"function": "large_document", "localNetwork": 254, "network": 250, "application": 100,
                   "groups": LARGE_GROUPS, "levels_per_group": LARGE_LEVELS}


def large_document():
    """Application 100 on network 250 with 255 groups of 40 named levels."""
    groups = [{"address": group, "name": f"G{group}", "levels": [
        {"address": level, "name": f"L{level}"} for level in range(LARGE_LEVELS)]} for group in range(LARGE_GROUPS)]
    return cgl(254, [{"address": 250, "applications": [{"address": 100, "name": "Large", "groups": groups}]}])


class Connection:
    def __init__(self, port):
        self.socket = socket.create_connection(("127.0.0.1", port), timeout=120)
        self.reader = self.socket.makefile("rb")
        self.greeting = self.reader.readline().decode().rstrip("\r\n")
        self.tag = 0

    def call(self, command, document=None):
        self.tag += 1
        request = f"[{self.tag}] {command}"
        if document is not None:
            request += f" << END{self.tag}\r\n{document}\r\nEND{self.tag}"
        self.socket.sendall((request + "\r\n").encode())
        prefix, reply = f"[{self.tag}] ", []
        while True:
            raw = self.reader.readline()
            if not raw:
                raise RuntimeError(f"connection closed during {command}")
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            if not line.startswith(prefix):
                continue
            body = line[len(prefix):]
            reply.append(body)
            if len(body) >= 4 and body[:3].isdigit() and body[3] == " ":
                return reply

    def close(self):
        self.reader.close()
        self.socket.close()


class Capture:
    def __init__(self, port, simulator):
        self.port, self.simulator = port, simulator
        self.endpoint = None
        self.scenarios, self.current, self.connection = [], None, None

    def scenario(self, name, description, *, fresh=False):
        if fresh or self.connection is None:
            if self.connection is not None:
                self.connection.close()
            self.connection = Connection(self.port)
        self.current = {"name": name, "description": description, "steps": []}
        self.scenarios.append(self.current)

    def normalize(self, line):
        if self.endpoint:
            line = line.replace(self.endpoint, "<simulator>")
        line = TIMESTAMP.sub('"createdTime":"<timestamp>"', line)
        return re.sub(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", "<oid>", line)

    def run(self, command, document=None, *, setup=False, summarize=False, generator=None):
        expanded = command.replace("<simulator>", self.endpoint or "<simulator>")
        reply = [self.normalize(line) for line in self.connection.call(expanded, document)]
        step = {"command": command}
        if generator is not None:
            step["document_generator"] = generator
        elif document is not None:
            step["document"] = document
        if setup:
            step["setup"] = True
        if summarize:
            step["reply_summary"] = {"lines": len(reply), "first": [line[:160] for line in reply[:3]],
                                     "last": [line[:160] for line in reply[-3:]],
                                     "sha256": hashlib.sha256("\n".join(reply).encode()).hexdigest()}
        else:
            step["reply"] = reply
        self.current["steps"].append(step)
        return reply

    def wait_ok(self, network):
        deadline = time.monotonic() + 60
        while True:
            reply = self.connection.call(f"GET {network} state")
            if "state=ok" in reply[-1]:
                return
            if time.monotonic() > deadline:
                raise RuntimeError(f"network did not open: {reply}")
            time.sleep(0.2)

    def inbound(self):
        return sum(1 for record in self.simulator.wire_log if record["direction"] in ("rx", "in", "received"))


def chain_setup(cap, project):
    cap.run(f"PROJECT NEW {project}", setup=True)
    cap.run(f"PROJECT USE {project}", setup=True)
    cap.run("DBCREATENET 254 Local Cni <simulator>", setup=True)
    previous = 254
    for network in CHAIN:
        cap.run(f"DBCREATENET {network} Hop{254 - network} Bridge {previous}/p/{network}", setup=True)
        previous = network
    cap.run("DBCREATENET 240 Island Cni 127.0.0.2:29998", setup=True)
    previous = 254
    for network in CHAIN:
        for command in (f"DBADDSAFE //{project}/{previous} Unit {network} Bridge{network}",
                        f"DBSETSAFE //{project}/{previous}/p/{network}/UnitType BRIDGE",
                        f"DBSETSAFE //{project}/{previous}/p/{network}/UnitName BRIDGE"):
            cap.run(command, setup=True)
        previous = network
    cap.run("NET LOAD DB", setup=True)


def scenarios(cap):
    cap.scenario("no_project", "A fresh session has no project in use.", fresh=True)
    cap.run("CGL EXPORT")
    cap.run("CGL IMPORT")
    cap.run("CGL IMPORT NOPE", cgl(254, []))
    cap.run("CGL IMPORT NOPE")

    cap.scenario("chain_setup", "Bridge Units whose unit address names the far network form the route graph.")
    chain_setup(cap, "CGLP")
    cap.run("NET OPEN //CGLP/254", setup=True)
    cap.wait_ok("//CGLP/254")

    cap.scenario("export_routes", "The last selected project network is localNetwork; every network "
                 "reachable from it through at most six bridge Units is exported with its route.")
    for command in ("CGL EXPORT CGLP 254", "CGL EXPORT CGLP 250", "CGL EXPORT CGLP",
                    "CGL EXPORT CGLP 253,254", "CGL EXPORT CGLP 254,254 56", "CGL EXPORT CGLP ,",
                    "CGL EXPORT CGLP 256", "CGL EXPORT CGLP a", "CGL EXPORT CGLP 1-2",
                    "CGL EXPORT CGLP 1", "CGL EXPORT CGLP 254 56 extra", "CGL EXPORT NOPE"):
        cap.run(command)

    cap.scenario("import_routes", "Supplied routes are never validated: correct, wrong and empty routes "
                 "import when C-Gate can route the network; unroutable and absent networks are skipped.")
    before = cap.inbound()
    cap.run("CGL IMPORT CGLP", cgl(254, [
        {"address": 254, "name": "Renamed", "applications": [
            {"address": 56, "type": 202, "name": "Lighting", "groups": [
                {"address": 1, "name": "Lounge", "levels": [{"address": 255, "name": "On"}]}]},
            {"address": 202, "type": 56, "name": "Trigger", "groups": [{"address": 3, "name": "Scene"}]}]},
        {"address": 253, "route": [253], "applications": [{"address": 56, "name": "Correct"}]},
        {"address": 252, "route": [9, 9], "applications": [{"address": 56, "name": "Wrong",
                                                            "groups": [{"address": 4, "name": "G4"}]}]},
        {"address": 248, "applications": [{"address": 57, "name": "Empty route"}]},
        {"address": 247, "route": [253, 252, 251, 250, 249, 248, 247], "applications": [{"address": 56}]},
        {"address": 240, "applications": [{"address": 56}]},
        {"address": 99, "route": [99]}]))
    cap.run("CGL EXPORT CGLP 254")
    cap.current["pci_inbound_records_during_import_and_export"] = cap.inbound() - before

    cap.scenario("local_network_variants", "localNetwork need not be in the project; routing is "
                 "evaluated from it and is directional.")
    cap.run("CGL IMPORT CGLP", cgl(99, [{"address": 254, "applications": [{"address": 60, "name": "A60"}]},
                                        {"address": 253}]))
    cap.run("CGL IMPORT CGLP", cgl(250, [{"address": 254}, {"address": 247, "applications": [
        {"address": 61, "name": "A61"}]}]))
    cap.run("CGL IMPORT CGLP", cgl(254, []))
    cap.run("CGL IMPORT CGLP", '{"cglVersion":"1.1","localNetwork":254}')

    cap.scenario("conflicts", "Existing tag names are preserved while progress lines echo the document "
                 "name; network names, application types and duplicate entries do not replace state.")
    for command in ("DBADDSAFE //CGLP/251 Application 56 ExistingLighting",
                    "DBADDSAFE //CGLP/251/56 Group 5 ExistingGroup"):
        cap.run(command, setup=True)
    cap.run("CGL IMPORT CGLP", cgl(254, [
        {"address": 251, "name": "Other", "applications": [
            {"address": 56, "type": 203, "name": "Different", "groups": [
                {"address": 5, "name": "Also different"}, {"address": 6, "name": "Six"},
                {"address": 6, "name": "Duplicate six"}]},
            {"address": 56, "name": "Duplicate app", "groups": [{"address": 7, "name": "Seven"}]}]},
        {"address": 251, "applications": [{"address": 63, "type": "56", "name": 7,
                                           "groups": [{"address": "2", "name": True}]}]}]))
    cap.run("CGL IMPORT CGLP", cgl(254, [{"address": 251, "applications": [
        {"address": 56, "name": "Again", "groups": [{"address": 6, "name": "Again"}]}]}]))
    cap.run("CGL EXPORT CGLP 254 56,63")

    cap.scenario("metadata", "createdBy/createdTime are accepted then discarded; export always "
                 "regenerates them. Unknown fields, including numberOfExportedObjects, are rejected.")
    documents = [
        '{"cglVersion":"1.1","createdBy":"Someone","createdTime":"2020-01-02T03:04:05.678+00:00","localNetwork":254,"networks":[]}',
        '{"cglVersion":"1.1","createdBy":5,"createdTime":"2020-01-02T03:04:05Z","localNetwork":254,"networks":[]}',
        '{"cglVersion":"1.1","createdBy":null,"createdTime":"2020-01-02","localNetwork":254,"networks":[]}',
        '{"cglVersion":"1.1","createdTime":"2020-01-02T03:04:05","localNetwork":254,"networks":[]}',
        '{"cglVersion":"1.1","createdTime":1600000000000,"localNetwork":"254","networks":[]}',
        '{"cglVersion":"1.1","createdTime":null,"localNetwork":254,"networks":[]}',
        '{"cglVersion":"1.1","createdTime":"yesterday","localNetwork":254,"networks":[]}',
        '{"cglVersion":"1.1","localNetwork":254,"networks":[],"numberOfExportedObjects":3}',
        '{"cglVersion":"1.1","localNetwork":254,"bogus":1,"networks":[]}',
        '{"cglVersion":"1.1","localNetwork":254,"networks":[{"address":254,"extra":true}]}',
        '{"cglVersion":"1.1","localNetwork":254,"networks":[{"address":254,"applications":[{"address":1,"name":"x","extra":1}]}]}',
        '{"cglVersion":"1.1","localNetwork":254,"networks":[{"address":254,"applications":[{"address":1,"name":"x","groups":[{"address":1,"name":"g","levels":[{"address":1,"name":"l","extra":1}]}]}]}]}',
    ]
    for document in documents:
        cap.run("CGL IMPORT CGLP", document)

    cap.scenario("validation", "Version, JSON shape and address failures; later failures are not rolled back.")
    documents = [
        '{"cglVersion":"1.0","localNetwork":254,"networks":[]}',
        '{"cglVersion":1.1,"localNetwork":254,"networks":[]}',
        '{"localNetwork":254,"networks":[]}',
        '{"cglVersion":"1.1","networks":[]}',
        '{"cglVersion":"1.1","localNetwork":null,"networks":[]}',
        '{"cglVersion":"1.1","localNetwork":254,"networks":null}',
        '{"cglVersion":"1.1","localNetwork":254,"networks":[null]}',
        '{"cglVersion":"1.1","localNetwork":254,"networks":[{"address":256}]}',
        '{"cglVersion":"1.1","localNetwork":254,"localNetwork":253,"networks":[{"address":252,"applications":[{"address":70,"name":"A","name":"B"}]}]}',
        '{"cglVersion":"1.1","localNetwork":254,"networks":[]} trailing',
        '{"cglVersion":"1.1","localNetwork":254,"networks":[{"address":254,"route":"x"}]}',
        '{"cglVersion":"1.1","localNetwork":254,"networks":[{"address":240,"route":[999,-5,"7"]}]}',
        '{"cglVersion":"1.1","localNetwork":254,"networks":[{"address":254,"applications":[{"address":62,"type":"lighting","name":"A62"}]}]}',
        '{"cglVersion":"1.1","localNetwork":254,"networks":[{"address":254,"applications":[{"address":72.9,"name":"A72"},{"address":null,"name":"Zero"}]}]}',
        '{"cglVersion":"1.1","localNetwork":254,"networks":[{"address":254,"applications":[{"address":true,"name":"T"}]}]}',
        '{"cglVersion":"1.1","localNetwork":254,"networks":[{"address":254,"applications":[{"address":71,"name":"A71"}]},{"address":253,"applications":null}]}',
        '{"cglVersion":"1.1","localNetwork":254,"networks":[{"address":254,"applications":[{"address":300,"name":"Big"}]}]}',
        '{"cglVersion":"1.1","localNetwork":254,"networks":[{"address":254,"applications":[{"address":255,"name":"A255","groups":[{"address":255,"name":"G255","levels":[{"address":256,"name":"L"}]}]}]}]}',
        '{"cglVersion":"1.1","localNetwork":254,"networks":[{"address":254,"applications":[{"address":66,"name":"A66","groups":[{"address":1,"name":"G","levels":[{"address":-1,"name":"L"}]}]}]}]}',
        '[]',
        'not json',
        '',
    ]
    for document in documents:
        cap.run("CGL IMPORT CGLP", document)
    cap.run("CGL IMPORT CGLP")
    cap.run("CGL EXPORT CGLP 254 0,66,70,71,72,255")
    cap.run("DBGETXML //CGLP/254/255")

    cap.scenario("export_types", "Exported type keeps retained special applications and maps every other "
                 "application to 56; application 255 and group 255 are not exported.")
    for address in (0, 25, 38, 136, 203, 228, 254):
        cap.run(f"DBADDSAFE //CGLP/249 Application {address} App{address}", setup=True)
    cap.run("DBADDSAFE //CGLP/249/228 Group 255 Top", setup=True)
    cap.run("DBADDSAFE //CGLP/249/228 Group 254 High", setup=True)
    cap.run("CGL EXPORT CGLP 254 0,25,38,136,203,228,254,255")

    cap.scenario("large", "A 10,455-object import and export have no object limit.")
    cap.run("CGL IMPORT CGLP", large_document(), summarize=True, generator=LARGE_GENERATOR)
    cap.run("CGL EXPORT CGLP 254 100", summarize=True)

    cap.scenario("runtime_layer", "After a project reload every application and group in a document is "
                 "reported as created again although stored names are kept; a repeat in the same load is silent.")
    document = cgl(254, [{"address": 253, "applications": [{"address": 56, "name": "Renamed again", "groups": [
        {"address": 9, "name": "Nine"}]}]}])
    cap.run("CGL IMPORT CGLP", document)
    cap.run("CGL IMPORT CGLP", document)
    cap.run("NET CLOSE //CGLP/254", setup=True)
    cap.run("PROJECT SAVE CGLP", setup=True)
    cap.run("PROJECT CLOSE CGLP", setup=True)
    cap.run("PROJECT LOAD CGLP", setup=True)
    cap.run("PROJECT USE CGLP", setup=True)
    cap.run("NET LOAD DB", setup=True)
    cap.run("CGL IMPORT CGLP", document)
    cap.run("CGL IMPORT CGLP", document)
    cap.run("CGL EXPORT CGLP 254 56")

    cap.scenario("topology", "Route discovery walks database Units whose UnitType starts with BRIDGE or "
                 "contains GATE; the unit address names the next network; the first shortest path wins.")
    for command in ("PROJECT NEW CGLT", "PROJECT USE CGLT", "DBCREATENET 254 Local Cni 127.0.0.2:29999",
                    "DBCREATENET 10 A Bridge 254/p/10", "DBCREATENET 20 B Bridge 254/p/20",
                    "DBCREATENET 30 C Bridge 10/p/30", "DBCREATENET 40 D Cni 127.0.0.2:29997",
                    "DBCREATENET 50 E Cni 127.0.0.2:29996", "DBCREATENET 60 F Cni 127.0.0.2:29995"):
        cap.run(command, setup=True)
    for network, unit, unit_type in ((254, 20, "BRIDGEX"), (254, 10, "PCGATEWAY"), (10, 30, "BRIDGE"),
                                     (20, 30, "BRIDGE"), (30, 254, "BRIDGE"), (30, 40, "bridge"),
                                     (30, 50, "RELDN12"), (30, 99, "BRIDGE"), (254, 60, "XGATEY")):
        cap.run(f"DBADDSAFE //CGLT/{network} Unit {unit} U{network}x{unit}", setup=True)
        cap.run(f"DBSETSAFE //CGLT/{network}/p/{unit}/UnitType {unit_type}", setup=True)
    cap.run("NET LOAD DB", setup=True)
    for command in ("CGL EXPORT CGLT 254", "CGL EXPORT CGLT 30", "CGL EXPORT CGLT 20", "CGL EXPORT CGLT 40"):
        cap.run(command)
    cap.run("CGL IMPORT CGLT", cgl(254, [{"address": 30, "route": [10, 30]}, {"address": 40},
                                         {"address": 50}, {"address": 60}]))

    cap.scenario("nameless", "A nameless new object imports (reported as 'null') but leaves the project "
                 "unable to save or render that object as XML.")
    for command in ("PROJECT NEW CGLN", "PROJECT USE CGLN", "DBCREATENET 254 Local Cni 127.0.0.2:29999",
                    "NET LOAD DB"):
        cap.run(command, setup=True)
    cap.run("CGL IMPORT CGLN", cgl(254, [{"address": 254, "applications": [{"address": 56, "name": "L", "groups": [
        {"address": 1, "name": "G", "levels": [{"address": 7}]}, {"address": 2}]}]}]))
    cap.run("CGL EXPORT CGLN 254")
    cap.run("DBGETXML //CGLN/254/56/1")
    cap.run("PROJECT SAVE CGLN")
    cap.run("PROJECT CLOSE CGLN", setup=True)
    cap.connection.close()
    cap.connection = None


def capture(*, output_dir, vendor=None):
    from cbus_toolkit.simulator import PCISimulator
    vendor = Path(vendor or os.environ["CBUS_LOCAL_CGATE_VENDOR"])
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    simulator = PCISimulator(profile="synthetic", state_path=output / "cgl-pci-state.json")
    service = LocalCGate(vendor)
    (service.work / "config/access.txt").write_text("interface 127.0.0.1 Clipsal\n")
    report = {"format": FORMAT, "capture_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    with service, simulator.running("127.0.0.1", 0) as (_, port):
        cap = Capture(service.port, simulator)
        cap.endpoint = f"127.0.0.1:{port}"
        scenarios(cap)
        report["scenarios"] = cap.scenarios
        report["pci_wire_records"] = len(simulator.wire_log)
    report["local_service"] = {key: service.report.get(key) for key in (
        "vendor_jar_sha256", "java_sha256", "listener_ownership_verified", "cleanup_complete",
        "process_exit_confirmed", "work_removed")}
    path = output / "native-cgl-routes.json"
    path.write_text(json.dumps(report, indent=2) + "\n")
    report["report_path"] = str(path)
    return report


# Source-recovered and capture-confirmed rules. Offline tests check each
# against the committed transcript.
NATIVE_FACTS = {
    "route_graph": "A route edge N->A exists when database network N holds a Unit at address A whose UnitType "
                   "starts with BRIDGE or contains GATE (case-sensitive) and network A exists. Network "
                   "InterfaceType/InterfaceAddress are not consulted. Edges are directional.",
    "route_bound": "A route holds at most six networks after the local one; the first shortest path in "
                   "database Unit enumeration order wins.",
    "export_local": "CGL EXPORT's network list only selects localNetwork: the last project network (project "
                    "order) in the list. All networks reachable from it are exported in project order, with "
                    "their route unless local. An empty selection is 408 Local address is missing.",
    "export_shape": "Applications 0..254 and groups 0..254 are exported; levels 0..255. type keeps 25, 172, "
                    "173, 192, 202, 203, 205, 206, 208, 213, 223, 224, 228 and 251; every other application "
                    "exports as 56. Empty arrays are omitted, null names are written as null, and "
                    "numberOfExportedObjects counts applications, groups and levels but not networks.",
    "import_routes_ignored": "Document routes are never compared with C-Gate's route; they are only echoed "
                             "after the local network in the unroutable diagnostic.",
    "import_skip": "A network absent from the project is SKIPPED as not existing; an existing network not "
                   "reachable from localNetwork is SKIPPED as not routable; either makes the final reply "
                   "380 CGL import not completed. localNetwork need not exist.",
    "import_names": "Only missing tag objects receive the document name. Network names and application types "
                    "are never imported. Progress lines echo the document name even for preserved objects.",
    "import_runtime_layer": "Created lines follow the union of a volatile runtime layer and the tag database: "
                            "after a project load, applications and groups are reported again.",
    "import_levels": "Levels are created with Value equal to their address.",
    "import_coercion": "JSON follows Jackson defaults: unknown properties are 400, duplicate keys keep the last "
                       "value, trailing text is ignored, numeric strings and floats coerce to integers, null "
                       "integers are 0 and scalars coerce to name strings.",
    "import_failures": "Address, null-entry and null-list failures are 408 and keep every earlier change; "
                       "version and JSON failures are 400 before any change.",
    "nameless": "A nameless new tag object imports but makes PROJECT SAVE fail its NOT NULL constraint.",
    "configuration": "CglImportConfiguration is constructed with defaults for every import; its setters are "
                     "private and no command syntax reaches them.",
    "no_pci": "CGL IMPORT and EXPORT change or read only the project label graph and send nothing to the PCI.",
}


def fixture(report, source_report_sha256):
    return {
        "format": FORMAT,
        "oracle": {"product": "Schneider Electric C-Gate", "version": "3.4.0.2001",
                   "jar_sha256": report["local_service"]["vendor_jar_sha256"],
                   "java_sha256": report["local_service"]["java_sha256"],
                   "environment": "Owned loopback-only child with Clipsal interface access; disposable "
                                  "database-only projects; the only opened CNI endpoint was a loopback "
                                  "synthetic PCI simulator; no site project, hardware or LAN endpoint.",
                   "cleanup_complete": report["local_service"]["cleanup_complete"]},
        "capture_script_sha256": report["capture_script_sha256"],
        "raw_report_sha256": source_report_sha256,
        "comparison": "Replies are exact after <oid>, <timestamp> and <simulator> normalization. Steps marked "
                      "setup build state and are not compared across servers.",
        "native_facts": NATIVE_FACTS,
        "sanitization": {"site_project_retained": False, "credentials_retained": False,
                         "vendor_source_retained": False},
        "pci": {"network": "//CGLP/254 opened to the loopback synthetic simulator before the import_routes "
                           "scenario and closed before the reload in runtime_layer",
                "total_wire_records": report["pci_wire_records"]},
        "scenarios": report["scenarios"],
    }


PARSE_FAILED = "400 Syntax Error: CGL validation failed: Import Failed: "
NAMELESS_REFUSAL = ("408 Operation failed: CGL import failed: a new application, group or level "
                    "needs a name")


def canonical_export(line):
    """Export JSON with generated metadata masked and siblings in address order."""
    document = json.loads(line[4:])
    document["createdBy"], document["createdTime"] = "<creator>", "<timestamp>"

    def sort(items, children):
        items.sort(key=lambda item: item["address"])
        for item in items:
            if children and children[0] in item:
                sort(item[children[0]], children[1:])
    for network in document["networks"]:
        if "applications" in network:
            sort(network["applications"], ("groups", "levels"))
    return document


def vectors(fixture):
    """Ordered wire cases shared by cgate-mock, cmqttd and the Python client.

    Each group starts from an empty server and runs in order. Expectations
    are the native replies except the documented nameless-object refusal;
    setup rows need only succeed, parse failures keep the native prefix, and
    exports compare canonical JSON.
    """
    rows = []
    group = {"no_project": "session", "nameless": "nameless", "topology": "topology"}
    for scenario in fixture["scenarios"]:
        for index, step in enumerate(scenario["steps"]):
            command = step["command"]
            if command.startswith(("NET OPEN", "NET CLOSE", "DBGETXML", "PROJECT SAVE CGLN")):
                continue
            row = {"id": f"cgl-{scenario['name']}-{index}", "group": group.get(scenario["name"], "chain"),
                   "command": command}
            for key in ("document", "document_generator"):
                if key in step:
                    row[key] = step[key]
            if step.get("setup"):
                row["setup"] = True
            elif scenario["name"] == "nameless" and command.startswith("CGL IMPORT"):
                row["expect"] = [NAMELESS_REFUSAL]
                row["native_differs"] = ("native imports the nameless objects and then fails PROJECT SAVE; "
                                         "cmqttd refuses before mutation")
            elif scenario["name"] == "nameless":
                row["expect_export"] = {"first": "343-Begin CGL snippet", "document": {
                    "cglVersion": "1.1", "createdBy": "<creator>", "createdTime": "<timestamp>",
                    "localNetwork": 254, "networks": [{"address": 254, "name": "Local"}]},
                    "final": "344 End CGL snippet [numberOfExportedObjects:0]"}
                row["native_differs"] = "the refused import left nothing to export"
            elif "reply_summary" in step:
                summary = step["reply_summary"]
                row["expect_summary"] = {"lines": summary["lines"], "last": summary["last"][-1]}
                if command.startswith("CGL IMPORT"):
                    row["expect_summary"]["sha256"] = summary["sha256"]
            else:
                reply = step["reply"]
                if len(reply) == 1 and reply[0].startswith(PARSE_FAILED):
                    row["expect_prefix"] = PARSE_FAILED
                elif len(reply) == 3 and reply[1].startswith('347-{"cglVersion"'):
                    row["expect_export"] = {"first": reply[0], "document": canonical_export(reply[1]),
                                            "final": reply[2]}
                else:
                    row["expect"] = reply
            rows.append(row)
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--vendor", type=Path)
    parser.add_argument("--fixture", type=Path, help="Write the sanitized committed fixture here")
    parser.add_argument("--vectors", type=Path, help="Derive the wire vectors from --fixture (no capture)")
    args = parser.parse_args()
    if args.vectors:
        rows = vectors(json.loads(args.fixture.read_text()))
        args.vectors.write_text("".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows))
        print(json.dumps({"vectors": len(rows)}))
        return
    output = args.output_dir or Path(tempfile.mkdtemp(prefix="cbus-cgl-capture-"))
    report = capture(output_dir=output, vendor=args.vendor)
    if args.fixture:
        raw = hashlib.sha256(Path(report["report_path"]).read_bytes()).hexdigest()
        args.fixture.write_text(json.dumps(fixture(report, raw), indent=2) + "\n")
    print(json.dumps({"report": report["report_path"], "scenarios": len(report["scenarios"]),
                      "cleanup": report["local_service"]["cleanup_complete"]}))


if __name__ == "__main__":
    main()
