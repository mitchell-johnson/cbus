#!/usr/bin/env python3
"""Capture C-Gate 3.4 inbound Access Control (application 213) event text.

A fresh LocalCGate child opens one disposable project whose only CNI endpoint
is this process's ephemeral Toolkit PCI simulator. After the network is
healthy, synthetic monitor-mode SAL lines are written on the simulator's
accepted C-Gate connection and the resulting session event (#e#) and status
(#s#) rows are recorded. No site project, installed service, physical
interface, or external listener is used.
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

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "toolkit-cli/research"))
sys.path.insert(0, str(ROOT / "toolkit-cli/src"))
from local_cgate import JAR_SHA256, LocalCGate  # noqa: E402
from cbus_toolkit.simulator import PCISimulator  # noqa: E402

# (label, SAL body after the 05 <source> D5 00 header, source unit)
CASES = [
    ("close", "020709", 4),
    ("lock", "0A0709", 4),
    ("left_open", "120102", 5),
    ("forced_open", "1A0102", 5),
    ("closed", "220102", 5),
    ("exit_request", "3200FE", 6),
    ("request_valid", "A607090112AB00", 6),
    ("request_invalid_empty", "C3070902", 6),
    ("request_invalid_max", "DFFEFE02" + "".join(f"{i:02X}" for i in range(28)), 6),
    ("concatenated", "1A0708A4070801AA", 7),
    ("close_three_bytes", "03070901", 7),
    ("zone_255", "02FF09", 7),
    ("point_255", "0207FF", 7),
    ("direction_3", "A3070903", 7),
    ("request_too_short", "A20709", 7),
    ("unknown_short_5", "2A0709", 7),
    ("unknown_long_0", "830709", 7),
    ("unknown_long_3", "E3070901", 7),
    ("truncated", "A6070901", 7),
    ("range_then_valid", "02FF09220304", 7),
    ("trailing_byte", "22030499", 7),
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

    def command(self, tag: str, body: str, duration: float = 30) -> list[str]:
        self.peer.sendall(f"[{tag}] {body}\r\n".encode())
        prefix = f"[{tag}] "
        done = lambda rows: any(r.startswith(prefix) and len(r) > len(prefix) + 3 and r[len(prefix) + 3] == " " for r in rows)  # noqa: E731
        return self.lines(until=done, duration=duration)


def capture(vendor: Path, java: Path, wait: float) -> dict:
    project = "ACP" + uuid.uuid4().hex[:5].upper()
    simulator = InjectingSimulator(profile="synthetic")
    service = LocalCGate(vendor, java=java)
    report: dict = {"project_placeholder": "PROJECT", "cases": [], "setup": []}
    with simulator.running("127.0.0.1", 0) as (_, simulator_port), service:
        setup = Session(service.port)
        endpoint = f"127.0.0.1:{simulator_port}"
        for index, text in enumerate([
            f"PROJECT NEW {project}",
            f"PROJECT USE {project}",
            f"DBCREATENET 254 AC_Probe Cni {endpoint}",
            f"PROJECT SAVE {project}",
            f"NET LOAD DB {project}",
            f"NET OPEN //{project}/254",
        ]):
            rows = setup.command(f"s{index}", text)
            final = rows[-1].replace(project, "PROJECT") if rows else None
            if final:
                final = re.sub(r"OID=[0-9a-f-]+", "OID=<generated>", final)
            report["setup"].append({"command": text.replace(project, "PROJECT").replace(endpoint, "SIMULATOR"),
                                    "final": final})
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
        for label, body, source in CASES:
            line = checksummed(f"05{source:02X}D500{body}")
            simulator.inject(line)
            rows = events.lines(duration=wait)
            kept = [re.sub(r"^#e# \d{8}-\d{6}\.\d{3} ", "#e# <timestamp> ", row.replace(project, "PROJECT"))
                    for row in rows if "213" in row or "access" in row.lower()]
            report["cases"].append({"label": label, "sal_hex": body, "source": source,
                                    "pci_line": line, "rows": kept})
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
        for name in ("com/clipsal/cgate/cbus/app/accesscontrol/CBusAccessControlApplication.class", "bc.class", "S.class", "BL.class"):
            classes[name] = hashlib.sha256(jar.read(name)).hexdigest()
    report["oracle"] = {"version": "3.4.0.2001", "jar_sha256": JAR_SHA256, "class_sha256": classes,
                        "captured_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    args.output.write_text(json.dumps(report, indent=1) + "\n")


if __name__ == "__main__":
    main()
