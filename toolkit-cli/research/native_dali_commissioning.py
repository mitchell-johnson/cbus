#!/usr/bin/env python3
"""Capture native C-Gate 3.4 DALI typed deployment and conditional extraction.

One owned loopback ``LocalCGate`` opens a disposable project whose CNI is a
research-only scripted ``SYS_DAL2`` gateway at unit 20 on an ephemeral
loopback port. Nothing connects to a real CNI, PCI, DALI gateway or C-Bus
network. The gateway answers every DALI extended-CAL request from a fixed
synthetic script (two ECGs: 3 is EMERGENCY and 5 is LED) and answers paged
extended-memory recalls with zero bytes. These replies are fixture choices,
not firmware or ballast claims.

``--output`` receives the sanitized committed transcript: each case's exact
C-Gate commands and replies, with the random project replaced by ``DALI``,
and the ordered gateway exchanges (full request packet, reply status and
data) plus paged recalls. ``cbus-cgate`` replays it as a differential test.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from uuid import uuid4

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "src"))

from cbus_toolkit.cgate import CGateClient, CGateError  # noqa: E402
from cbus_toolkit.native import NativeDatabase, NativeProjects  # noqa: E402
from cbus_toolkit.networks import NativeNetworks  # noqa: E402
from cbus_toolkit.simulator import PCISimulator, UnitState, synthetic_units  # noqa: E402
from local_cgate import JAR_SHA256, LocalCGate  # noqa: E402

FORMAT = "cbus-native-dali-commissioning-v1"
SANITIZED_NETWORK = "//DALI/254"
GATEWAY = 20
DALI_DEVICE_TYPE = 0xDA
KNOWN_MASK = bytes([0x28]) + bytes(7)  # ECGs 3 and 5.
ECGS = {
    3: {16: [1] + [255] * 7, 17: [1, 2, 1, 2, 1, 254, 253, 200], 18: [1, 5, 0],
        19: [10] + [255] * 7, 20: [255, 30] + [255] * 6, 23: [180, 4, 7, 100, 254, 7, 4],
        24: [1, 2, 3, 4, 5, 6, 7]},
    5: {16: [6] + [255] * 7, 17: [0, 0, 0, 0, 2, 250, 255, 255], 18: [1, 3, 0],
        19: [255] * 8, 20: [255] * 8, 25: [1, 0]},
}

# name -> (fresh session setup commands, captured command, script options)
CASES = {
    "deploy_empty_session": ([], "DALI SESSION DEPLOY {s} {gw} A DALI_ONLY", {}),
    "deploy_dali_only": (["DALI SESSION EXTRACT {s} {gw} A DALI_ONLY"],
                         "DALI SESSION DEPLOY {s} {gw} A DALI_ONLY", {}),
    "deploy_dali_only_scene_fault": (["DALI SESSION EXTRACT {s} {gw} A DALI_ONLY"],
                                     "DALI SESSION DEPLOY {s} {gw} A DALI_ONLY", {"fail": {34: 4}}),
    "deploy_full": (["DALI SESSION EXTRACT {s} {gw} A DALI_ONLY"],
                    "DALI SESSION DEPLOY {s} {gw} A FULL", {}),
    "deploy_full_missing_common": (["DALI SESSION EXTRACT {s} {gw} A COND_QUICK"],
                                   "DALI SESSION DEPLOY {s} {gw} A FULL", {}),
    "cond_quick": (["DALI SESSION EXTRACT {s} {gw} A DALI_ONLY"],
                   "DALI SESSION EXTRACT {s} {gw} A COND_QUICK", {}),
    "cond_extended_discovery": (["DALI SESSION EXTRACT {s} {gw} A DALI_ONLY"],
                                "DALI SESSION EXTRACT {s} {gw} A COND_EXTENDED", {"address_mask": 0x68}),
    "rescan_fault_address_unknown_rejected": (["DALI SESSION EXTRACT {s} {gw} A DALI_ONLY"],
                                              "DALI SESSION EXTRACT {s} {gw} A RESCAN_FAULT", {"fail": {2: 4}}),
}


class DaliGatewayFixture(PCISimulator):
    """PCI plus one scripted SYS_DAL2 gateway; records every gateway exchange."""

    def __init__(self):
        pci = synthetic_units()[2]
        gateway = UnitState(GATEWAY, {1: b"SYS_DAL2", 2: b"1.10.0  ", 4: bytes.fromhex("FFFFFF000018B10616A20005")},
                            {0x21: bytes.fromhex("FFFF9B192D8229E4FF923AF3"), 0x20: bytes([GATEWAY]),
                             0x23: bytes.fromhex("9B192D8229E4"), 0x2A: bytes.fromhex("B64CF6BB1A9E"),
                             0x30: b"\x55", 0xF2: b"\xff"}, mmi_state=1)
        super().__init__([pci, gateway], local_unit=pci.address, profile="synthetic", physical_memory={},
                         response_delay=0.01)
        self.options = {}
        self.exchanges = []

    def _dali(self, mode, operation, data):
        base = operation & 0x7F
        if base in self.options.get("fail", {}):
            return self.options["fail"][base], b""
        if base == 13:
            return 0, b"\x00"
        if base == 2:
            return 0, bytes([self.options.get("address_mask", 0x28)]) + bytes(7)
        if base in (4, 7):
            return 0, KNOWN_MASK
        if base in (9, 10, 11):
            return 0, bytes(8)
        if mode != 0x81 or not data or base not in ECGS.get(data[0], {}):
            return 0, b""
        return 0, bytes([data[0]] + ECGS[data[0]][base])

    def _command(self, line, context):
        code = line[-1:] if line and ord("g") <= line[-1] <= ord("z") else b""
        raw = line[:-1] if code else line
        explicit = raw.startswith(b"\\")
        text = raw[1:] if explicit else raw
        try:
            payload = bytes.fromhex(text.decode())
        except ValueError:
            return super()._command(line, context)
        packet = payload if explicit or context["header"] is None or raw.startswith(b"@") else context["header"] + payload
        ack = code + b"." if code else b""
        if len(packet) == 7 and packet[:4] == bytes([0x46, GATEWAY, 0, 0x1B]):
            if explicit:
                context["header"] = packet[:3]
            page, parameter, count = packet[4:7]
            self.exchanges.append({"kind": "paged_recall", "packet": packet.hex().upper(),
                                   "address": (page << 8) + parameter, "count": count, "fill": 0})
            data = bytearray(count)
            if page == 0:
                for key, value in self.units[GATEWAY].parameters.items():
                    for index, byte in enumerate(value):
                        if parameter <= key + index < parameter + count:
                            data[key + index - parameter] = byte
            frames = b"".join(self._reply(bytes([0x86, GATEWAY, self.local_unit, 0,
                                                 0x80 | (len(data[offset:offset + 16]) + 1),
                                                 (parameter + offset) & 0xFF]) + bytes(data[offset:offset + 16]))
                              for offset in range(0, count, 16))
            return ack + frames, None
        if len(packet) >= 7 and packet[:3] == bytes([0x06, GATEWAY, 0]) and packet[5] == DALI_DEVICE_TYPE:
            if explicit:
                context["header"] = packet[:3]
            cal = packet[3:]
            status, data = self._dali(cal[1], cal[3], cal[4:])
            self.exchanges.append({"kind": "dali", "packet": packet.hex().upper(), "mode": cal[1],
                                   "operation": cal[3], "payload": cal[4:].hex().upper(),
                                   "status": status, "data": data.hex().upper()})
            reply = bytes([0x86, GATEWAY, self.local_unit, 0, 0xE4 + len(data), 0x83, DALI_DEVICE_TYPE,
                           cal[3], status]) + data
            return ack + self._reply(reply), None
        return super()._command(line, context)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vendor", type=Path, default=os.environ.get("CBUS_LOCAL_CGATE_VENDOR"))
    parser.add_argument("--java", type=Path, default=os.environ.get("CBUS_CGATE_JAVA"))
    parser.add_argument("--output", type=Path,
                        default=HERE.parents[1] / "rust/testdata/fixtures/native_cgate_dali_commissioning.json")
    args = parser.parse_args()
    service = LocalCGate(args.vendor, java=args.java)
    try:
        (service.work / "config/access.txt").write_text("interface 127.0.0.1 Clipsal\n")
    except BaseException as error:
        service._cleanup_preserving(error)
        raise
    fixture = DaliGatewayFixture()
    project = "DA" + uuid4().hex[:6].upper()
    network = f"//{project}/254"

    def sanitize(text):
        return text.replace(network, SANITIZED_NETWORK).replace(project, "DALI")

    def run(client, command):
        try:
            response = client.command(command)
            return response.status, list(response.lines)
        except CGateError as error:
            return error.response.status, list(error.response.lines)

    results = {}
    with service, fixture.running("127.0.0.1", 0) as (_, port):
        with CGateClient("127.0.0.1", service.port, timeout=600) as client:
            projects, db = NativeProjects(client), NativeDatabase(client)
            projects.operation("new", project)
            try:
                db.create_network(project, 254, "Dali", "Cni", "127.0.0.1:" + str(port))
                db.create_unit(network, GATEWAY, "Gateway", "SYS_DAL2", "1.10.0")
                projects.operation("save", project)
                for setting in ("AutoUnravel no", "AutoUpdate no", "Retries 0"):
                    run(client, "SET " + network + " " + setting)
                NativeNetworks(client).open(network)
                deadline = time.monotonic() + 25
                while time.monotonic() < deadline:
                    if any("running" in line for line in run(client, "GET " + network + " InterfaceState")[1]):
                        break
                    time.sleep(.2)
                else:
                    raise RuntimeError("No running interface")
                # Native creates the CDG object only after discovering unit 20.
                run(client, "NET SYNC " + network)
                # The catalogue load fails without vendor device files but
                # loads the parameter tables SESSION NEW requires.
                run(client, "DALI CATALOG RELOAD")
                gateway = network + f"/p/{GATEWAY}"
                for index, (name, (setup, captured, options)) in enumerate(CASES.items()):
                    session = f"case{index}"
                    fixture.options = {}
                    setup_results = [run(client, f"DALI SESSION NEW {session}")]
                    for command in setup:
                        setup_results.append(run(client, command.format(s=session, gw=gateway)))
                    if any(status != 200 for status, _ in setup_results):
                        raise RuntimeError(f"{name}: setup failed {setup_results}")
                    fixture.options = options
                    start = len(fixture.exchanges)
                    command = captured.format(s=session, gw=gateway)
                    status, lines = run(client, command)
                    results[name] = {
                        "setup": [sanitize(command.format(s=session, gw=gateway)) for command in setup],
                        "fixture_options": {key: ({str(k): v for k, v in value.items()} if isinstance(value, dict) else value)
                                            for key, value in options.items()},
                        "command": sanitize(command), "status": status,
                        "reply": [sanitize(line) for line in lines],
                        "exchanges": fixture.exchanges[start:]}
                    print(name, status, lines[-1], len(results[name]["exchanges"]), flush=True)
                    run(client, f"DALI SESSION END {session}")
            finally:
                for command in ("NET CLOSE " + network, "PROJECT CLOSE " + project, "PROJECT DELETE " + project):
                    try:
                        client.command(command)
                    except Exception:  # Research cleanup is best effort.
                        pass
    oracle = {key: service.report.get(key) for key in (
        "vendor_jar_sha256", "java_sha256", "listener_ownership_verified", "cleanup_complete",
        "process_exit_confirmed", "work_removed")}
    oracle.update(version="3.4.0 build 2001", physical_endpoint=False)
    document = {"format": FORMAT,
                "scope": "Owned loopback native C-Gate 3.4.0 build 2001 against a research-only scripted SYS_DAL2 "
                         "gateway at unit 20. Synthetic ECG replies and zero-filled extended memory are fixture "
                         "choices, not gateway, ballast, persistence or hardware evidence.",
                "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "jar_sha256": JAR_SHA256, "oracle": oracle,
                "capture_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "gateway_unit": GATEWAY,
                "gateway_script": {
                    "check_for_unknown_data_hex": "00",
                    "known_mask_operations": [4, 7], "known_mask_hex": KNOWN_MASK.hex().upper(),
                    "address_unknown_default_mask_hex": (bytes([0x28]) + bytes(7)).hex().upper(),
                    "empty_mask_operations": [9, 10, 11],
                    "ecg_replies": {str(address): {str(op): bytes([address] + data).hex().upper()
                                                   for op, data in replies.items()}
                                    for address, replies in ECGS.items()},
                    "other_replies": "SUCCESS with no data; paged recalls return zero bytes"},
                "cases": results}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=2) + "\n")


if __name__ == "__main__":
    main()
