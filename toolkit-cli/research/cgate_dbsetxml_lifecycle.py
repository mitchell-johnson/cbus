#!/usr/bin/env python3
"""Capture DBSETXML unsaved-change lifecycle on owned original C-Gate 3.4.

Each phase uses a fresh, hash-pinned LocalCGate work directory and a synthetic
project whose CNI (127.0.0.1:1) is never opened. A "restart" terminates the
owned process, copies only its Projects directory into the next owned work
directory and starts that new process. Project file contents are recorded as
hashes plus whether the synthetic marker strings they contain are present.
"""

from __future__ import annotations

import argparse
import gzip
import io
import hashlib
import json
import shutil
import socket
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

import cgate_dbsetxml_replacement_edges as edge
import local_cgate
from local_cgate import JAR_SHA256, LocalCGate

PROJECT = "XLIFE"
MARKERS = ("SavedName", "UnsavedName", "ResavedName", "RestartName", "AutosaveName", "DbsetName")
UNIT_OID = "11111111-1111-4111-8111-111111111111"
APP_OID = "22222222-2222-4222-8222-222222222222"


def network(network_oid: str, interface_oid: str, unit_name: str, *, extra_unit: bool = False) -> str:
    units = unit(20, unit_name)
    if extra_unit:
        units += unit(21, unit_name, oid="33333333-3333-4333-8333-333333333333")
    return (f"<Network><OID>{network_oid}</OID><TagName>Local</TagName>"
            "<Address>254</Address><NetworkNumber>254</NetworkNumber>"
            f"<Interface><OID>{interface_oid}</OID><InterfaceType>Cni</InterfaceType>"
            "<InterfaceAddress>127.0.0.1:1</InterfaceAddress></Interface>"
            f"<Application><OID>{APP_OID}</OID><TagName>Lighting</TagName><Address>56</Address></Application>"
            f"{units}</Network>")


def unit(address: int, name: str, *, oid: str = UNIT_OID) -> str:
    return (f"<Unit><OID>{oid}</OID><TagName>{name}</TagName><Address>{address}</Address>"
            "<UnitType>KEYE1</UnitType><UnitName>Room</UnitName>"
            "<FirmwareVersion>1.2.67</FirmwareVersion></Unit>")


def disk(service: LocalCGate) -> dict:
    """Hash every Projects-directory file and report which synthetic markers it holds."""
    return _hash_tree(service.work / "Projects")


class Session:
    def __init__(self, service: LocalCGate, phase: str, rows: list, tag: int):
        self.service = service
        self.phase = phase
        self.rows = rows
        self.tag = tag
        self.sock = socket.create_connection(("127.0.0.1", service.port), timeout=5)
        self.sock.settimeout(15)
        self.stream = self.sock.makefile("rwb", buffering=0)
        self.greeting = self.stream.readline().decode("utf-8")

    def call(self, command: str, document: str | None = None) -> dict:
        row = edge.exchange(self.stream, self.tag, command, document)
        # Native 408 load diagnostics name the disposable work directory.
        work = str(self.service.work)
        row["response_lines"] = [line.replace("/private" + work, "<owned-work>").replace(work, "<owned-work>")
                                 for line in row["response_lines"]]
        row["phase"] = self.phase
        self.rows.append(row)
        self.tag += 1
        print(self.phase, row["tag"], edge.status(row), command,
              edge.xml(row)[:160] if command.startswith("DBGETXML") else row["response_lines"][-1].strip())
        return row

    def disk(self, label: str) -> None:
        self.rows.append({"tag": None, "phase": self.phase, "disk": label, "files": disk(self.service)})

    def close(self) -> None:
        self.stream.close()
        self.sock.close()


def configure(service: LocalCGate, autosave: str) -> None:
    path = service.work / "config/C-GateConfig.txt"
    text = path.read_text()
    assert "tag-autosave=no\n" in text
    path.write_text(text.replace("tag-autosave=no\n", f"tag-autosave={autosave}\n"))


def terminate(service: LocalCGate, keep: Path) -> None:
    """Stop the owned child (SIGTERM, as a service manager would) and keep its project files."""
    service.process.terminate()
    service.process.wait(timeout=20)
    shutil.copytree(service.work / "Projects", keep, dirs_exist_ok=True)


def run_phase(vendor: Path, java: Path, phase: str, autosave: str, rows: list, tag: int,
              body, *, seed: Path | None = None, keep: Path | None = None) -> tuple[dict, int]:
    service = LocalCGate(vendor, java=java)
    configure(service, autosave)
    if seed is not None:
        shutil.copytree(seed, service.work / "Projects", dirs_exist_ok=True)
    with service:
        session = Session(service, phase, rows, tag)
        try:
            body(session)
        finally:
            session.close()
        tag = session.tag
        if keep is not None:
            terminate(service, keep)
    report = service.report
    return ({"phase": phase, "tag_autosave": autosave, "greeting": session.greeting,
             "seeded_from_previous_tag_directory": seed is not None,
             "terminated_with_sigterm": keep is not None,
             "owned_loopback_listeners": report["listener_ownership_verified"],
             "listeners": report["listeners"], "cleanup_complete": report["cleanup_complete"],
             "process_exit_confirmed": report["process_exit_confirmed"],
             "work_removed": report["work_removed"]}, tag)


def setup(session: Session, name: str) -> tuple[str, str]:
    session.call(f"PROJECT NEW {PROJECT}")
    session.call(f"PROJECT USE {PROJECT}")
    session.call("DBCREATENET 254 Local Cni 127.0.0.1:1")
    baseline = ET.fromstring(edge.xml(session.call(f"DBGETXML //{PROJECT}/254")))
    network_oid, interface_oid = baseline.findtext("OID"), baseline.findtext("Interface/OID")
    assert network_oid and interface_oid
    session.disk("after-create")
    session.call(f"DBSETXML //{PROJECT}/254", network(network_oid, interface_oid, name))
    session.disk("after-unsaved-dbsetxml")
    session.call(f"PROJECT SAVE {PROJECT}")
    session.disk("after-save")
    return network_oid, interface_oid


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vendor", type=Path, required=True)
    parser.add_argument("--java", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows: list[dict] = []
    phases: list[dict] = []
    ids: dict[str, str] = {}
    scratch = Path(tempfile.mkdtemp(prefix="cbus-dbsetxml-lifecycle-"))
    try:
        # Phase A: tag-autosave=no; CLOSE/LOAD with and without SAVE, LOAD
        # while loaded, and a SIGTERM restart after an unsaved replacement.
        def phase_a(s: Session) -> None:
            net, iface = setup(s, "SavedName")
            ids.update(network=net, interface=iface)
            unsaved = network(net, iface, "UnsavedName", extra_unit=True)
            s.call(f"DBSETXML //{PROJECT}/254", unsaved)
            s.call(f"DBGETXML //{PROJECT}/254")
            s.disk("after-unsaved-replacement")
            s.call(f"PROJECT CLOSE {PROJECT}")
            s.disk("after-close-without-save")
            s.call(f"PROJECT LOAD {PROJECT}")
            s.call(f"PROJECT USE {PROJECT}")
            s.call(f"DBGETXML //{PROJECT}/254")
            s.call(f"DBGETXML //{PROJECT}/254/p/21")
            # Same unsaved edit, then SAVE before CLOSE/LOAD.
            s.call(f"DBSETXML //{PROJECT}/254", network(net, iface, "ResavedName", extra_unit=True))
            s.call(f"PROJECT SAVE {PROJECT}")
            s.disk("after-resave")
            s.call(f"PROJECT CLOSE {PROJECT}")
            s.call(f"PROJECT LOAD {PROJECT}")
            s.call(f"PROJECT USE {PROJECT}")
            s.call(f"DBGETXML //{PROJECT}/254")
            # PROJECT LOAD of an already loaded project with unsaved edits.
            s.call(f"DBSETXML //{PROJECT}/254", network(net, iface, "UnsavedName"))
            s.call(f"PROJECT LOAD {PROJECT}")
            s.call(f"DBGETXML //{PROJECT}/254")
            # A scalar DBSET follows the same save boundary as DBSETXML.
            s.call(f"DBSET //{PROJECT}/254/p/20/TagName DbsetName")
            s.call(f"PROJECT CLOSE {PROJECT}")
            s.call(f"PROJECT LOAD {PROJECT}")
            s.call(f"PROJECT USE {PROJECT}")
            s.call(f"DBGETXML //{PROJECT}/254/p/20")
            # Leave an unsaved replacement in memory for the restart.
            s.call(f"DBSETXML //{PROJECT}/254", network(net, iface, "RestartName", extra_unit=True))
            s.call(f"DBGETXML //{PROJECT}/254/p/20")
            s.disk("before-sigterm")

        keep_a = scratch / "a"
        info, tag = run_phase(args.vendor, args.java, "no-autosave", "no", rows, 100, phase_a, keep=keep_a)
        phases.append(info)
        rows.append({"tag": None, "phase": "no-autosave", "disk": "after-sigterm",
                     "files": _hash_tree(keep_a)})

        def phase_b(s: Session) -> None:
            s.call("PROJECT LIST")
            s.call(f"PROJECT LOAD {PROJECT}")
            s.call(f"PROJECT USE {PROJECT}")
            s.call(f"DBGETXML //{PROJECT}/254")
            s.call(f"DBGETXML //{PROJECT}/254/p/21")

        info, tag = run_phase(args.vendor, args.java, "restart-after-no-autosave", "no", rows, 300,
                              phase_b, seed=keep_a)
        phases.append(info)

        # Phase C: tag-autosave=yes (documented for learn updates only).
        def phase_c(s: Session) -> None:
            net, iface = setup(s, "SavedName")
            s.call(f"DBSETXML //{PROJECT}/254", network(net, iface, "AutosaveName", extra_unit=True))
            s.disk("after-unsaved-replacement")
            s.call(f"PROJECT CLOSE {PROJECT}")
            s.disk("after-close-without-save")
            s.call(f"PROJECT LOAD {PROJECT}")
            s.call(f"PROJECT USE {PROJECT}")
            s.call(f"DBGETXML //{PROJECT}/254")
            s.call(f"DBSETXML //{PROJECT}/254", network(net, iface, "RestartName", extra_unit=True))
            s.disk("before-sigterm")

        keep_c = scratch / "c"
        info, tag = run_phase(args.vendor, args.java, "autosave", "yes", rows, 500, phase_c, keep=keep_c)
        phases.append(info)
        rows.append({"tag": None, "phase": "autosave", "disk": "after-sigterm",
                     "files": _hash_tree(keep_c)})

        def phase_d(s: Session) -> None:
            s.call(f"PROJECT LOAD {PROJECT}")
            s.call(f"PROJECT USE {PROJECT}")
            s.call(f"DBGETXML //{PROJECT}/254")

        info, tag = run_phase(args.vendor, args.java, "restart-after-autosave", "yes", rows, 700,
                              phase_d, seed=keep_c)
        phases.append(info)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    data = {
        "schema": "native-cgate-dbsetxml-lifecycle-v1",
        "captured_utc": datetime.now(timezone.utc).isoformat(),
        "oracle": {"jar_sha256": JAR_SHA256, "java_sha256": hashlib.sha256(args.java.read_bytes()).hexdigest(),
                   "version": "3.4.0 build 2001", "physical_endpoint": False},
        "capture_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "service_harness_sha256": hashlib.sha256(Path(local_cgate.__file__).read_bytes()).hexdigest(),
        "project": PROJECT,
        "network_oid": ids["network"],
        "interface_oid": ids["interface"],
        "phases": phases,
        "cases": rows,
    }
    args.output.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _plain(data: bytes) -> bytes:
    """Return the searchable bytes of a raw, gzip or zip project file."""
    try:
        return gzip.decompress(data)
    except OSError:
        pass
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            return b"".join(archive.read(name) for name in archive.namelist())
    except zipfile.BadZipFile:
        return data


def _hash_tree(root: Path) -> dict:
    files = {}
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        data = path.read_bytes()
        files[str(path.relative_to(root))] = {
            "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data),
            "markers": [marker for marker in MARKERS if marker.encode() in _plain(data)]}
    return files


if __name__ == "__main__":
    main()
