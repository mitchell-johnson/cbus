#!/usr/bin/env python3
"""Capture C-Gate 3.4 inbound and command-issued Lighting event text.

A fresh LocalCGate child opens one disposable project whose only CNI endpoint
is this process's ephemeral Toolkit PCI simulator. The project database holds
one Lighting group with a synthetic OID so the load-change OID column can be
compared for a database-defined group and for lazily created groups. After
the network is healthy, synthetic monitor-mode SAL lines are written on the
simulator's accepted C-Gate connection and the resulting session event (#e#)
and status (#s#) rows are recorded. A second session then issues Lighting
commands so the command-context suffix is visible. No site project,
installed service, physical interface, or external listener is used.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import select
import socket
import sys
import threading
import time
import uuid
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "toolkit-cli/research"))
sys.path.insert(0, str(ROOT / "toolkit-cli/src"))
from local_cgate import JAR_SHA256, LocalCGate  # noqa: E402
from cbus_toolkit.simulator import PCISimulator  # noqa: E402

GROUP_OID = "77777777-7777-4777-8777-000000000007"

# (label, complete packet body before checksum). Lighting application 56 is
# 0x38; 48 is 0x30. A monitor PM row is 05 <source> <application> 00 <SAL>.
CASES = [
    ("on_source_4", "05043800" "7901"),
    ("off_source_4", "05043800" "0101"),
    ("off_repeat_source_4", "05043800" "0101"),
    ("ramp_instant_128_source_5", "05053800" "020180"),
    ("ramp_instant_255_source_5", "05053800" "0201FF"),
    ("ramp_instant_0_source_5", "05053800" "020100"),
    ("ramp_4s_200_source_6", "05063800" "0A01C8"),
    ("terminate_source_6", "05063800" "0901"),
    ("ramp_4s_0_source_6", "05063800" "0A0100"),
    ("ramp_1020s_77_source_6", "05063800" "7A014D"),
    ("terminate_idle_source_7", "05073800" "0920"),
    ("on_source_0", "05003800" "7902"),
    ("on_source_255", "05FF3800" "7903"),
    ("concatenated_source_7", "05073800" "79040105020680"),
    ("application_48_source_7", "05073000" "7901"),
    ("database_group_source_8", "05083800" "7907"),
    ("database_group_ramp_source_8", "05083800" "120740"),
    ("pm_routing_byte_source_9", "05093809" "790A"),
    ("ppm_one_bridge_source_9", "0309FE0938" "790B"),
]

# Commands issued on a separate command session after the SAL cases.
COMMANDS = [
    ("command_on", "LIGHTING ON //PROJECT/254/56/9"),
    ("command_ramp", "LIGHTING RAMP //PROJECT/254/56/9 100 4s"),
    ("command_terminate", "LIGHTING TERMINATERAMP //PROJECT/254/56/9"),
    ("command_off_database_group", "LIGHTING OFF //PROJECT/254/56/7"),
]


def checksummed(body: str) -> str:
    raw = bytes.fromhex(body)
    return body.upper() + f"{(-sum(raw)) & 0xFF:02X}"


class InjectingSimulator(PCISimulator):
    """Record the accepted C-Gate connection so monitor rows can be written."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.peers: list[socket.socket] = []
        self.peer_ready = threading.Event()

    def _connection(self, conn, connection, shutdown):
        self.peers.append(conn)
        self.peer_ready.set()
        return super()._connection(conn, connection, shutdown)

    def inject(self, line: str) -> None:
        for peer in list(self.peers):
            try:
                peer.sendall(line.encode("ascii") + b"\r\n")
            except OSError:
                pass


class Session:
    def __init__(self, port: int) -> None:
        self.peer = socket.create_connection(("127.0.0.1", port), timeout=30)
        self.pending = b""
        self.greeting = self.lines(until=lambda rows: rows, duration=10)

    def lines(self, *, until=None, duration: float = 0.5) -> list[str]:
        end = time.monotonic() + duration
        rows: list[str] = []
        while time.monotonic() < end:
            ready, _, _ = select.select([self.peer], [], [], max(0, end - time.monotonic()))
            if ready:
                chunk = self.peer.recv(65536)
                if not chunk:
                    break
                self.pending += chunk
                *complete, self.pending = self.pending.split(b"\n")
                rows.extend(row.decode("utf-8", errors="replace").rstrip("\r") for row in complete)
            if until is not None and until(rows):
                break
        return rows

    def command(self, tag: str, body: str, duration: float = 30, document: str | None = None) -> list[str]:
        request = f"[{tag}] {body}"
        if document is not None:
            request += f" << END{tag}\r\n{document}\r\nEND{tag}"
        self.peer.sendall((request + "\r\n").encode())
        prefix = f"[{tag}] "
        done = lambda rows: any(r.startswith(prefix) and len(r) > len(prefix) + 3 and r[len(prefix) + 3] == " " for r in rows)  # noqa: E731
        return self.lines(until=done, duration=duration)


def sanitize(row: str, project: str, oids: dict[str, str]) -> str:
    row = row.replace(project, "PROJECT")
    for oid, name in oids.items():
        row = row.replace(oid, name)
    row = re.sub(r"^#e# \d{8}-\d{6}(\.\d{3})? ", "#e# <timestamp> ", row)
    row = re.sub(r"\bcmd\d+\b", "cmd<session>", row)
    return row


def capture(vendor: Path, java: Path, wait: float) -> dict:
    project = "LTP" + uuid.uuid4().hex[:5].upper()
    simulator = InjectingSimulator(profile="synthetic")
    service = LocalCGate(vendor, java=java)
    report: dict = {"project_placeholder": "PROJECT", "cases": [], "commands": [], "setup": []}
    oids: dict[str, str] = {}
    with simulator.running("127.0.0.1", 0) as (_, simulator_port), service:
        setup = Session(service.port)
        endpoint = f"127.0.0.1:{simulator_port}"

        def run(tag: str, text: str, document: str | None = None) -> list[str]:
            rows = setup.command(tag, text, document=document)
            final = sanitize(rows[-1], project, oids).replace(endpoint, "SIMULATOR") if rows else None
            report["setup"].append({"command": sanitize(text, project, oids).replace(endpoint, "SIMULATOR"),
                                    "final": final})
            return rows

        run("s0", f"PROJECT NEW {project}")
        run("s1", f"PROJECT USE {project}")
        run("s2", f"DBCREATENET 254 LT_Probe Cni {endpoint}")
        rows = setup.command("s3", f"DBGETXML //{project}/254")
        document = "".join(r.split("347-", 1)[1] for r in rows if "347-" in r).strip()
        baseline = ET.fromstring(document)
        network_oid = baseline.findtext("OID")
        interface_oid = baseline.findtext("Interface/OID")
        oids[network_oid] = "<network-oid>"
        oids[interface_oid] = "<interface-oid>"
        network = (f"<Network><OID>{network_oid}</OID><TagName>LT_Probe</TagName>"
                   "<Address>254</Address><NetworkNumber>254</NetworkNumber>"
                   f"<Interface><OID>{interface_oid}</OID><InterfaceType>Cni</InterfaceType>"
                   f"<InterfaceAddress>{endpoint}</InterfaceAddress></Interface>"
                   "<Application><OID>77777777-7777-4777-8777-000000000056</OID>"
                   "<TagName>Lighting</TagName><Address>56</Address>"
                   f"<Group><OID>{GROUP_OID}</OID><TagName>Kitchen</TagName><Address>7</Address></Group>"
                   "</Application></Network>")
        run("s4", f"DBSETXML //{project}/254", network)
        for index, text in enumerate([
            f"PROJECT SAVE {project}",
            f"NET LOAD DB {project}",
            f"NET OPEN //{project}/254",
            f"DBGET //{project}/254/56/7/OID",
        ], start=5):
            run(f"s{index}", text)
        healthy = False
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline and not healthy:
            rows = setup.command("st", f"GET //{project}/254 state")
            healthy = any(re.search(r"state\s*=\s*ok\b", row, re.I) for row in rows)
            report["network_state"] = [row.replace(project, "PROJECT") for row in rows]
            if not healthy:
                time.sleep(1)
        report["network_healthy"] = healthy
        events = Session(service.port)
        report["event_mode_reply"] = events.command("ev", "EVENT e9s9c0")[-1:]
        events.lines(duration=wait)

        def keep(rows: list[str]) -> list[str]:
            return [sanitize(row, project, oids) for row in rows
                    if row.startswith(("#e#", "#s#")) and " 700 cgate - Heartbeat." not in row]

        for label, body in CASES:
            line = checksummed(body)
            simulator.inject(line)
            rows = events.lines(duration=wait)
            report["cases"].append({"label": label, "pci_line": line, "rows": keep(rows)})
        commander = Session(service.port)
        for index, (label, text) in enumerate(COMMANDS):
            response = commander.command(f"c{index}", text.replace("PROJECT", project))
            rows = events.lines(duration=wait + 4.5 if "RAMP " in text else wait)
            report["commands"].append({"label": label, "command": text,
                                       "response": [sanitize(r, project, oids) for r in response],
                                       "rows": keep(rows)})
        report["cleanup"] = [setup.command("c0", f"NET CLOSE //{project}/254")[-1:],
                             setup.command("c1", f"PROJECT CLOSE {project}")[-1:],
                             setup.command("c2", f"PROJECT DELETE {project}")[-1:]]
    report["local_service"] = {key: service.report.get(key) for key in (
        "vendor_jar_sha256", "listener_ownership_verified", "cleanup_complete", "process_exit_confirmed")}
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vendor", type=Path, required=True)
    parser.add_argument("--java", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--wait", type=float, default=1.0)
    args = parser.parse_args()
    report = capture(args.vendor, args.java, args.wait)
    classes = {}
    import zipfile
    with zipfile.ZipFile(args.vendor / "cgate.jar") as jar:
        for name in ("BL.class", "bq.class"):
            classes[name] = hashlib.sha256(jar.read(name)).hexdigest()
    report["oracle"] = {"version": "3.4.0.2001", "jar_sha256": JAR_SHA256, "class_sha256": classes,
                        "captured_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    args.output.write_text(json.dumps(report, indent=1) + "\n")


if __name__ == "__main__":
    main()
