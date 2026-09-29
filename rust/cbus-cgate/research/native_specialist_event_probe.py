#!/usr/bin/env python3
"""Capture C-Gate 3.4 inbound event text for the specialist applications.

A fresh LocalCGate child opens one disposable project whose only CNI endpoint
is this process's ephemeral Toolkit PCI simulator. After the network is
healthy, synthetic monitor-mode SAL lines (``05 <source> <application> 00
<SAL>``) are written on the simulator's accepted C-Gate connection and the
resulting session event (#e#) and status (#s#) rows are recorded.

This generalizes native_access_control_event_probe.py and
native_lighting_event_probe.py to Air-Conditioning, Audio, Security,
Measurement, Media Transport, Telephony, Identify, Short Message, Error
Reporting, Trigger Control, Enable Control, Clock and Temperature Broadcast.
Every application is exercised with the committed encode vectors (valid
forms), hand-written boundary SALs and invalid SALs (unknown opcodes,
truncation and trailing bytes). Nine further sessions subscribe at EVENT
levels 1..9 so each row's native reporting level is the lowest level that
delivered it. No site project, installed service, physical interface, or
external listener is used.
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

VECTORS = ROOT / "rust/testdata/vectors"

APPLICATIONS = {
    0x19: "temperature", 0xAC: "aircon", 0xAD: "shortmessage", 0xC0: "mediatransport",
    0xCA: "trigger", 0xCB: "enable", 0xCD: "audio", 0xCE: "ereport", 0xD0: "security",
    0xDF: "clock", 0xE0: "telephony", 0xE4: "measurement", 0xFB: "identify",
}

# Hand-written SALs (application, label, SAL hex). Valid forms beyond the
# vectors, numeric boundaries, and invalid shapes the decoders must reject.
EXTRA = [
    # Trigger Control 0xCA: trigger min/max, indicator kill, unknown, truncated.
    (0xCA, "trigger_min", "0200" "00"),
    (0xCA, "trigger_max", "02FF" "FF"),
    (0xCA, "trigger_group_1_action_7", "0201" "07"),
    (0xCA, "min_group_5", "0105"),
    (0xCA, "label_short", "A5" "05" "00" "00" "4142"),
    (0xCA, "indicator_kill_group_5", "0905"),
    (0xCA, "truncated_trigger", "0205"),
    (0xCA, "trailing_byte", "02050799"),
    # Enable Control 0xCB.
    (0xCB, "enable_min", "0200" "00"),
    (0xCB, "enable_max", "02FF" "FF"),
    (0xCB, "enable_mid", "020A" "80"),
    (0xCB, "unknown_opcode", "0A0A"),
    (0xCB, "truncated", "020A"),
    (0xCB, "trailing_byte", "020A8099"),
    # Clock 0xDF.
    (0xDF, "time_midnight", "0D01" "000000" "FF"),
    (0xDF, "time_max", "0D01" "173B3B" "FF"),
    (0xDF, "date_min", "0E02" "0000" "01" "01" "00"),
    (0xDF, "date_max", "0E02" "FFFF" "0C" "1F" "06"),
    (0xDF, "time_out_of_range", "0D01" "183C3C" "FF"),
    (0xDF, "date_month_13", "0E02" "07E9" "0D" "01" "00"),
    (0xDF, "request_refresh", "1103"),
    (0xDF, "unknown_variable", "0D09" "000000" "FF"),
    (0xDF, "truncated", "0D01" "00"),
    # Temperature 0x19.
    (0x19, "broadcast_zero", "0201" "00"),
    (0x19, "broadcast_max", "02FF" "FF"),
    (0x19, "broadcast_group_0", "0200" "80"),
    (0x19, "unknown_opcode", "0901" "00"),
    (0x19, "truncated", "0201"),
    # Identify 0xFB.
    (0xFB, "on_group_0", "7900"),
    (0xFB, "off_group_255", "01FF"),
    (0xFB, "ramp_instant_128", "020180"),
    (0xFB, "ramp_max_duration", "7A01FF"),
    (0xFB, "terminate", "0901"),
    (0xFB, "unknown_opcode", "0301"),
    (0xFB, "truncated_ramp", "0201"),
    # Measurement 0xE4.
    (0xE4, "data_units_max", "0E" "FFFF" "02" "7FFF" "7F" "FF"),
    (0xE4, "data_zero", "0E" "0000" "02" "0000" "00" "00"),
    (0xE4, "unknown_opcode", "0F" "0101" "02" "0000" "00" "00"),
    (0xE4, "truncated", "0E" "0101" "02" "27"),
    # Error Reporting 0xCE.
    (0xCE, "minimum", "05" "00" "00" "00" "00" "00"),
    (0xCE, "unknown_opcode", "0D" "00" "00" "00" "00" "00"),
    (0xCE, "truncated", "05" "00" "00"),
    # Short Message 0xAD.
    (0xAD, "refresh_max", "01FF"),
    (0xAD, "unknown_opcode", "0901"),
    (0xAD, "truncated_message", "A5" "01" "02"),
    # Air-Conditioning 0xAC.
    (0xAC, "zone_temperature_max", "15" "FF" "FF" "7FFF" "FF"),
    (0xAC, "zone_humidity_min", "1D" "00" "00" "0000" "00"),
    (0xAC, "plant_status_all", "05" "FF" "FF" "FF" "FF" "FF"),
    (0xAC, "unknown_opcode", "7F01"),
    (0xAC, "truncated_status", "0501"),
    # Audio 0xCD.
    (0xCD, "on_mux2_zone7", "79BF"),
    (0xCD, "ramp_level_0", "7A5700"),
    (0xCD, "unknown_opcode", "0357"),
    (0xCD, "truncated_ramp", "7A57"),
    # Security 0xD0.
    (0xD0, "zone_unsealed_1", "0A" "86" "01"),
    (0xD0, "zone_unsealed_0", "0A" "86" "00"),
    (0xD0, "zone_unsealed_127", "0A" "86" "7F"),
    (0xD0, "zone_unsealed_128", "0A" "86" "80"),
    (0xD0, "system_arm_127", "7A" "80" "7F"),
    (0xD0, "system_arm_128", "7A" "80" "80"),
    (0xD0, "battery_charging_5", "0A" "8C" "05"),
    (0xD0, "password_status_5", "0A" "90" "05"),
    (0xD0, "alarm_type_255", "0A" "93" "FF"),
    (0xD0, "unknown_event", "09" "9F"),
    (0xD0, "truncated_zone", "0A" "86"),
    # Media Transport 0xC0.
    (0xC0, "play_group_255", "79FF"),
    (0xC0, "track_name_empty", "82" "02" "00"),
    (0xC0, "unknown_opcode", "0B02"),
    (0xC0, "truncated_track", "8D" "02"),
    # Telephony 0xE0.
    (0xE0, "unknown_event", "0909"),
    (0xE0, "truncated_off_hook", "0A02"),
    (0xE0, "divert_empty", "A083"),
]

SOURCES = (4, 5, 6)


def checksummed(body: str) -> str:
    raw = bytes.fromhex(body)
    return body.upper() + f"{(-sum(raw)) & 0xFF:02X}"


def vector_cases() -> list[tuple[int, str, str]]:
    cases = []
    per_app: dict[int, int] = {}
    for path in sorted(VECTORS.glob("*.jsonl")):
        for line in path.read_text().splitlines():
            if not line.startswith("{"):
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            encoded = (row.get("expect_encode_hex") or "").upper()
            if (row.get("packet") or {}).get("checksum"):
                encoded = encoded[:-2]  # the vector's own PCI checksum byte
            if len(encoded) < 8 or not encoded.startswith("05") or encoded[4:6] != "00":
                continue
            application = int(encoded[2:4], 16)
            if application not in APPLICATIONS:
                continue
            # Temperature has a large broadcast grid; keep a representative slice.
            if application == 0x19 and per_app.get(application, 0) >= 8:
                continue
            per_app[application] = per_app.get(application, 0) + 1
            cases.append((application, row["id"], encoded[6:]))
    # Report-only SALs retained in the earlier per-application fixtures.
    fixtures = ROOT / "rust/testdata/fixtures"
    aircon = json.loads((fixtures / "native_cgate_aircon.json").read_text())
    for index, sal in enumerate(aircon["inbound_reports"]["sample_sal_hex"]):
        cases.append((0xAC, f"aircon-report-{index}", sal.upper()))
    telephony = json.loads((fixtures / "native_cgate_telephony.json").read_text())
    for index, event in enumerate(telephony["inbound_events"]):
        cases.append((0xE0, f"telephony-report-{index}", event["sal_hex"].upper()))
    audio = json.loads((fixtures / "native_cgate_audio.json").read_text())
    for event in audio["inbound_decoder"]["command_events"]:
        body = event["body_hex"].upper()
        cases.append((0xCD, f"audio-report-{event['event'].split()[0]}", body[8:]))
    return cases


def all_cases() -> list[dict]:
    seen = set()
    cases = []
    # A truncated Clock SAL raises a native "903 Critical Server Exception"
    # that stops all later monitor decoding, so it runs last.
    ordered = [case for case in vector_cases() + EXTRA if case[:2] != (0xDF, "truncated")]
    ordered.append(next(case for case in EXTRA if case[:2] == (0xDF, "truncated")))
    for index, (application, label, sal) in enumerate(ordered):
        if (application, sal) in seen:
            continue
        seen.add((application, sal))
        source = SOURCES[index % len(SOURCES)]
        body = f"05{source:02X}{application:02X}00{sal}"
        cases.append({"application": application, "label": label, "source": source,
                      "sal_hex": sal, "pci_line": checksummed(body)})
    return cases


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

    def lines(self, *, until=None, duration: float = 0.5, quiet: float | None = None) -> list[str]:
        end = time.monotonic() + duration
        last = time.monotonic()
        rows: list[str] = []
        while time.monotonic() < end:
            wait = max(0, end - time.monotonic())
            if quiet is not None:
                wait = min(wait, max(0, last + quiet - time.monotonic()))
            ready, _, _ = select.select([self.peer], [], [], wait)
            if ready:
                chunk = self.peer.recv(65536)
                if not chunk:
                    break
                last = time.monotonic()
                self.pending += chunk
                *complete, self.pending = self.pending.split(b"\n")
                rows.extend(row.decode("utf-8", errors="replace").rstrip("\r") for row in complete)
            elif quiet is not None and time.monotonic() >= last + quiet:
                break
            if until is not None and until(rows):
                break
        return rows

    def command(self, tag: str, body: str, duration: float = 30) -> list[str]:
        self.peer.sendall(f"[{tag}] {body}\r\n".encode())
        prefix = f"[{tag}] "
        done = lambda rows: any(r.startswith(prefix) and len(r) > len(prefix) + 3 and r[len(prefix) + 3] == " " for r in rows)  # noqa: E731
        return self.lines(until=done, duration=duration)


def sanitize(row: str, project: str) -> str:
    row = row.replace(project, "PROJECT")
    row = re.sub(r"^#e# \d{8}-\d{6}(\.\d{3})? ", "#e# <timestamp> ", row)
    return re.sub(r"\bcmd\d+\b", "cmd<session>", row)


def keep(row: str) -> bool:
    return row.startswith(("#e#", "#s#")) and " 700 cgate - Heartbeat." not in row


def capture(vendor: Path, java: Path, wait: float, quiet: float) -> dict:
    project = "SEP" + uuid.uuid4().hex[:5].upper()
    simulator = InjectingSimulator(profile="synthetic")
    service = LocalCGate(vendor, java=java)
    report: dict = {"project_placeholder": "PROJECT", "cases": [], "setup": [], "lazy_rows": []}
    with simulator.running("127.0.0.1", 0) as (_, simulator_port), service:
        setup = Session(service.port)
        endpoint = f"127.0.0.1:{simulator_port}"
        for index, text in enumerate([
            f"PROJECT NEW {project}",
            f"PROJECT USE {project}",
            f"DBCREATENET 254 SP_Probe Cni {endpoint}",
            f"PROJECT SAVE {project}",
            f"NET LOAD DB {project}",
            f"NET OPEN //{project}/254",
        ]):
            rows = setup.command(f"s{index}", text)
            final = sanitize(rows[-1], project) if rows else None
            if final:
                final = re.sub(r"OID=[0-9a-f-]+", "OID=<generated>", final)
            report["setup"].append({"command": sanitize(text, project).replace(endpoint, "SIMULATOR"),
                                    "final": final})
        healthy = False
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline and not healthy:
            rows = setup.command("st", f"GET //{project}/254 state")
            healthy = any(re.search(r"state\s*=\s*ok\b", row, re.I) for row in rows)
            report["network_state"] = [sanitize(row, project) for row in rows]
            if not healthy:
                time.sleep(1)
        report["network_healthy"] = healthy
        events = Session(service.port)
        report["event_mode_reply"] = events.command("ev", "EVENT e9s9c0")[-1:]
        levels = {}
        for level in range(1, 10):
            session = Session(service.port)
            session.command(f"l{level}", f"EVENT e{level}s0c0")
            levels[level] = session
        events.lines(duration=wait)
        for session in levels.values():
            session.lines(duration=0.1)
        loaded: set[int] = set()
        for case in all_cases():
            simulator.inject(case["pci_line"])
            rows = [row for row in events.lines(duration=wait, quiet=quiet) if keep(row)]
            # Collect the level sessions after the e9 session has gone quiet.
            seen_at = {level: [row for row in session.lines(duration=0.05, quiet=0.05) if keep(row)]
                       for level, session in levels.items()}
            clean = []
            for row in rows:
                text = sanitize(row, project)
                if "] loaded application" in text:
                    report["lazy_rows"].append({"application": case["application"], "row": text})
                    loaded.add(case["application"])
                    continue
                entry = {"row": text}
                if row.startswith("#e#"):
                    body = row.split(" ", 2)[2] if row.count(" ") >= 2 else row
                    entry["level"] = next((level for level in range(1, 10)
                                           if any(r.endswith(body) for r in seen_at[level])), None)
                clean.append(entry)
            report["cases"].append({**case, "rows": clean})
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
    parser.add_argument("--wait", type=float, default=2.0)
    parser.add_argument("--quiet", type=float, default=0.35)
    args = parser.parse_args()
    report = capture(args.vendor, args.java, args.wait, args.quiet)
    classes = {}
    import zipfile
    with zipfile.ZipFile(args.vendor / "cgate.jar") as jar:
        for name in sorted(jar.namelist()):
            if name.startswith("com/clipsal/cgate/cbus/app/") and name.endswith("Application.class"):
                classes[name] = hashlib.sha256(jar.read(name)).hexdigest()
        for name in ("BL.class", "bq.class"):
            classes[name] = hashlib.sha256(jar.read(name)).hexdigest()
    report["oracle"] = {"version": "3.4.0.2001", "jar_sha256": JAR_SHA256, "class_sha256": classes,
                        "captured_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    args.output.write_text(json.dumps(report, indent=1) + "\n")


if __name__ == "__main__":
    main()
