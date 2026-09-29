#!/usr/bin/env python3
"""Seeded shared-OID index probe for owned native C-Gate and both Rust servers.

Each seed builds a synthetic project: two or three Networks created in a
random order, then complete Network documents submitted in another random
order. Applications (with Group and Level descendants) and Units draw their
OIDs from a small shared pool, so OIDs collide within and across Networks and
object kinds. The probe records which object `DBGETXML !OID` selects after
submission, after SAVE/CLOSE/LOAD, after OID-targeted DBDELETE, after an
unrelated DBSET, and after another SAVE/CLOSE/LOAD.

Unit addresses are distinct across Networks, and each object has a unique
TagName, so the selected object is identified by its root element and
TagName. The `units` profile instead places 2-16 Units, and at most one leaf
Application, in one Network. The `cross` profile creates two Networks in a
random order, each holding exactly one object per shared OID. Every CNI
address is the unopened 127.0.0.1:1.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import socket
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

import cgate_dbsetxml_replacement_edges as edge

ROOT = Path(__file__).resolve().parents[2]
POOL = [f"{digit * 8}-{digit * 4}-4{digit * 3}-8{digit * 3}-{digit * 12}" for digit in "abc"]


def fresh_oid(rng: random.Random) -> str:
    value = f"{rng.getrandbits(128):032x}"
    return f"{value[:8]}-{value[8:12]}-4{value[13:16]}-8{value[17:20]}-{value[20:]}"


def plan(seed: int) -> dict:
    """Deterministic project layout for one seed."""
    rng = random.Random(seed)
    networks = rng.sample([252, 253, 254], rng.choice([2, 3]))
    submission = rng.sample(networks, len(networks))
    unit_addresses = rng.sample(range(20, 60), 12)
    layout = {}
    for network in networks:
        applications = []
        for app in rng.sample(range(56, 64), rng.randint(0, 3)):
            groups = []
            for group in rng.sample(range(1, 6), rng.randint(0, 2)):
                levels = [{"address": level, "oid": pick(rng), "tag": f"n{network}a{app}g{group}l{level}"}
                          for level in rng.sample(range(1, 4), rng.randint(0, 1))]
                groups.append({"address": group, "oid": pick(rng), "tag": f"n{network}a{app}g{group}",
                               "levels": levels})
            applications.append({"address": app, "oid": pick(rng), "tag": f"n{network}a{app}", "groups": groups})
        units = [{"address": unit_addresses.pop(), "oid": pick(rng)} for _ in range(rng.randint(1, 4))]
        for unit in units:
            unit["tag"] = f"n{network}u{unit['address']}"
        layout[network] = {"applications": applications, "units": units}
    return {"seed": seed, "project": f"XOID{seed:03d}", "create_order": networks,
            "submit_order": submission, "networks": layout}


def plan_units(seed: int) -> dict:
    """One Network of 2-16 Units (and at most one leaf Application) per seed."""
    rng = random.Random(10_000 + seed)
    applications = []
    if rng.random() < 0.5:
        app = rng.choice(range(56, 64))
        applications.append({"address": app, "oid": rng.choice(POOL), "tag": f"n254a{app}", "groups": []})
    units = [{"address": address, "oid": pick(rng), "tag": f"n254u{address}"}
             for address in rng.sample(range(1, 250), rng.randint(2, 16))]
    return {"seed": seed, "project": f"XUNI{seed:03d}", "create_order": [254], "submit_order": [254],
            "networks": {254: {"applications": applications, "units": units}}}


def plan_cross(seed: int) -> dict:
    """Two Networks created in a random order, each holding one object per
    shared OID (Unit/Unit, Application/Unit or Unit/Application)."""
    rng = random.Random(20_000 + seed)
    networks = rng.sample([250, 251, 252, 253, 254], 2)
    addresses = rng.sample(range(1, 250), 12)
    apps = {network: rng.sample(range(56, 64), 3) for network in networks}
    layout = {network: {"applications": [], "units": []} for network in networks}
    for oid in POOL:
        kinds = rng.choice([("Unit", "Unit"), ("Application", "Unit"), ("Unit", "Application")])
        for network, kind in zip(networks, kinds):
            if kind == "Unit":
                address = addresses.pop()
                layout[network]["units"].append({"address": address, "oid": oid, "tag": f"n{network}u{address}"})
            else:
                app = apps[network].pop()
                layout[network]["applications"].append(
                    {"address": app, "oid": oid, "tag": f"n{network}a{app}", "groups": []})
    for network in networks:
        address = addresses.pop()
        layout[network]["units"].append({"address": address, "oid": fresh_oid(rng), "tag": f"n{network}u{address}"})
        rng.shuffle(layout[network]["units"])
        rng.shuffle(layout[network]["applications"])
    return {"seed": seed, "project": f"XCRS{seed:03d}", "create_order": networks,
            "submit_order": rng.sample(networks, 2), "networks": layout}


def pick(rng: random.Random) -> str:
    return rng.choice(POOL) if rng.random() < 0.6 else fresh_oid(rng)


def network_xml(network: int, content: dict, network_oid: str, interface_oid: str) -> str:
    def group(value: dict) -> str:
        levels = "".join(
            f'<Level Value="0"><OID>{level["oid"]}</OID><TagName>{level["tag"]}</TagName>'
            f'<Address>{level["address"]}</Address></Level>' for level in value["levels"])
        return (f'<Group><OID>{value["oid"]}</OID><TagName>{value["tag"]}</TagName>'
                f'<Address>{value["address"]}</Address>{levels}</Group>')
    applications = "".join(
        f'<Application><OID>{app["oid"]}</OID><TagName>{app["tag"]}</TagName>'
        f'<Address>{app["address"]}</Address>{"".join(group(g) for g in app["groups"])}</Application>'
        for app in content["applications"])
    units = "".join(
        f'<Unit><OID>{unit["oid"]}</OID><TagName>{unit["tag"]}</TagName><Address>{unit["address"]}</Address>'
        '<UnitType>KEYE1</UnitType><UnitName>Room</UnitName><FirmwareVersion>1.2.67</FirmwareVersion>'
        f'<PP Name="UnitAddress" Value="{unit["address"]}"/></Unit>'
        for unit in content["units"])
    return (f"<Network><OID>{network_oid}</OID><TagName>Local{network}</TagName>"
            f"<Address>{network}</Address><NetworkNumber>{network}</NetworkNumber>"
            f"<Interface><OID>{interface_oid}</OID><InterfaceType>Cni</InterfaceType>"
            f"<InterfaceAddress>127.0.0.1:1</InterfaceAddress></Interface>{applications}{units}</Network>")


def selected(row: dict) -> dict:
    code = edge.status(row)
    if code != 344:
        return {"status": code}
    root = ET.fromstring(edge.xml(row))
    return {"status": code, "element": root.tag, "tag": root.findtext("TagName")}


def run_seed(call, seed: int, profile: str) -> dict:
    layout = {"mixed": plan, "units": plan_units, "cross": plan_cross}[profile](seed)
    project = layout["project"]
    steps = []

    def query(step: str) -> None:
        steps.append({"step": step, "selected": {oid: selected(call(f"DBGETXML !{oid}")) for oid in POOL}})

    def lifecycle(step: str) -> None:
        for verb in ("SAVE", "CLOSE", "LOAD", "USE"):
            assert edge.status(call(f"PROJECT {verb} {project}")) == 200
        query(step)

    call(f"PROJECT NEW {project}")
    call(f"PROJECT USE {project}")
    for network in layout["create_order"]:
        assert edge.status(call(f"DBCREATENET {network} Local{network} Cni 127.0.0.1:1")) in (200, 301)
    statuses = []
    for network in layout["submit_order"]:
        base = ET.fromstring(edge.xml(call(f"DBGETXML //{project}/{network}")))
        document = network_xml(network, layout["networks"][network], base.findtext("OID"),
                               base.findtext("Interface/OID"))
        statuses.append(edge.status(call(f"DBSETXML //{project}/{network}", document)))
    steps.append({"step": "submit", "statuses": statuses})
    query("submitted")
    lifecycle("reloaded")
    deletes = {}
    for oid in POOL:
        deletes[oid] = edge.status(call(f"DBDELETE !{oid}"))
    steps.append({"step": "delete", "statuses": deletes})
    query("deleted")
    first = layout["submit_order"][0]
    steps.append({"step": "unrelated-dbset",
                  "status": edge.status(call(f"DBSET //{project}/{first}/TagName Renamed{first}"))})
    query("after-unrelated-dbset")
    lifecycle("deleted-reloaded")
    return {"seed": seed, "project": project, "plan": layout, "steps": steps}



def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, nargs="+", default=list(range(1, 13)))
    parser.add_argument("--product", choices=("native", "cgate-mock", "cmqttd"), required=True)
    parser.add_argument("--profile", choices=("mixed", "units", "cross"), default="mixed")
    parser.add_argument("--vendor", type=Path)
    parser.add_argument("--java", type=Path)
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    receipt = {"schema": "cgate-oid-index-probe-v1", "product": args.product, "profile": args.profile,
               "captured_utc": datetime.now(timezone.utc).isoformat(),
               "probe_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               "shared_oids": POOL, "physical_endpoint": False, "seeds": []}

    def drive(port: int) -> None:
        with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
            sock.settimeout(30)
            stream = sock.makefile("rwb", buffering=0)
            receipt["greeting"] = stream.readline().decode("utf-8")
            tag = 1000

            def call(command: str, document: str | None = None) -> dict:
                nonlocal tag
                row = edge.exchange(stream, tag, command, document)
                tag += 1
                return row

            for seed in args.seeds:
                receipt["seeds"].append(run_seed(call, seed, args.profile))

    if args.product == "native":
        import local_cgate
        from local_cgate import JAR_SHA256, LocalCGate
        with LocalCGate(args.vendor, java=args.java) as service:
            drive(service.port)
        report = service.report
        receipt["oracle"] = {"jar_sha256": JAR_SHA256, "java_sha256": hashlib.sha256(args.java.read_bytes()).hexdigest(),
                             "version": "3.4.0 build 2001",
                             "owned_loopback_listeners": report["listener_ownership_verified"],
                             "listeners": report["listeners"], "cleanup_complete": report["cleanup_complete"],
                             "process_exit_confirmed": report["process_exit_confirmed"],
                             "work_removed": report["work_removed"]}
        receipt["service_harness_sha256"] = hashlib.sha256(Path(local_cgate.__file__).read_bytes()).hexdigest()
    else:
        from cgate_dbsetxml_unit_differential import owned_server
        with owned_server(args.product, args.binary) as port:
            drive(port)
        receipt["binary_sha256"] = hashlib.sha256(args.binary.read_bytes()).hexdigest()
        receipt["source_revision"] = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    args.output.write_text(json.dumps(receipt, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
