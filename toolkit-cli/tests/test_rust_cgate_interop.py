"""Python-to-Rust interop: the real CGateClient and typed wrappers against cgate-mock.

Spawns the Rust `cgate-mock` TCP test double and drives it with the
production transport (`CGateClient`) plus the native wrapper classes the
CLI itself uses. This proves wire framing, tagging, event separation and
command semantics agree across the two implementations.

Payload literals asserted here (`imported=`, `UnitName=`, `unit=`) are the
documented mock contract, not native C-Gate output: they pin the
interoperability surface both sides implement. Status codes, framing and
the typed-wrapper flows are the native-fidelity claims.

The binary is located via CBUS_CGATE_MOCK_BIN or the sibling Rust
workspace output; the suite skips cleanly when it is absent. The vendor
unit-specification directory is located via CBUS_UNITSPEC_DIR or the
in-repo research copy; catalogue-backed tests skip without it.
"""
from __future__ import annotations

import os
import queue
import re
import socket
import subprocess
import time
import threading
import unittest
from pathlib import Path

from cbus_toolkit.cgate import CGateClient


def find_mock():
    override = os.environ.get("CBUS_CGATE_MOCK_BIN")
    if override and Path(override).is_file():
        return override
    candidate = Path(__file__).resolve().parents[2] / "rust" / "target" / "debug" / "cgate-mock"
    if candidate.is_file() and os.access(candidate, os.X_OK):
        # Guard against stale-binary false-greens: skip when the binary
        # predates the mock sources (rebuild with cargo build -p cbus-cgate).
        sources = Path(__file__).resolve().parents[2] / "rust" / "cbus-cgate"
        try:
            newest = max(
                entry.stat().st_mtime
                for entry in list(sources.rglob("*.rs")) + [sources / "Cargo.toml"])
        except (OSError, ValueError):
            newest = 0
        try:
            if candidate.stat().st_mtime < newest:
                return None
        except OSError:
            return None
        return str(candidate)
    return None


MOCK_BIN = find_mock()


def find_unitspec():
    override = os.environ.get("CBUS_UNITSPEC_DIR")
    if override and Path(override).is_dir():
        return override
    candidate = (Path(__file__).resolve().parents[2] / "toolkit-cli" / "research"
                 / "vendor" / "unitspec-plain")
    if candidate.is_dir() and (candidate / "KEYGL5.xml").is_file():
        return str(candidate)
    return None


UNITSPEC_DIR = find_unitspec()


@unittest.skipUnless(MOCK_BIN, "cgate-mock binary is not built")
class RustInteropTests(unittest.TestCase):
    def setUp(self):
        command = [MOCK_BIN, "--bind", "127.0.0.1:0"]
        if UNITSPEC_DIR:
            # Catalogue-backed sessions: INFO serves the real spec and
            # LOAD seeds spec defaults, mirroring native schema loads.
            command += ["--unitspec", UNITSPEC_DIR]
        self.process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        # Register cleanup before startup checks: unittest skips tearDown
        # when setUp fails, and a missing greeting must not leak a child.
        self.addCleanup(self._stop_process)
        lines = queue.Queue()
        self.startup_reader = threading.Thread(
            target=lambda: lines.put(self.process.stdout.readline(512)),
            daemon=True)
        self.startup_reader.start()
        try:
            line = lines.get(timeout=10.0)
        except queue.Empty:
            self.fail("cgate-mock did not report its port within 10 seconds")
        match = re.fullmatch(r"cgate-mock listening on 127\.0\.0\.1:(\d+)\s*", line)
        if not match:
            self.fail(f"cgate-mock did not report a port: {line!r}")
        self.port = int(match[1])
        self.client = CGateClient("127.0.0.1", self.port, timeout=10.0)
        self.addCleanup(self.client.close)
        deadline = time.monotonic() + 10.0
        while True:
            try:
                self.client.connect()
                break
            except (OSError, RuntimeError):
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.05)

    def _stop_process(self):
        try:
            if self.process.poll() is None:
                self.process.kill()
            self.process.wait(timeout=5.0)
        finally:
            self.process.stdout.close()
            if hasattr(self, "startup_reader"):
                self.startup_reader.join(timeout=1.0)

    def test_parameter_replies_terminate_with_native_315(self):
        self.client.command("PROJECT NEW TEST")
        self.client.command("DBCREATENET 254 Local Cni 127.0.0.1:10001")
        from cbus_toolkit.native import NativeDatabase
        from cbus_toolkit.programming import Programmer
        NativeDatabase(self.client).create_unit(
            "//TEST/254", 20, "Lounge", "KEY1", "1.2.67")
        programmer = Programmer(self.client)
        with programmer.load("//TEST/254", "/db//TEST/254/p/20") as session:
            single = self.client.command(f"PP GET {session.name} UnitName")
            self.assertEqual(single.code, 315)
            self.assertEqual(len(single.lines), 1)
            self.assertTrue(single.final.startswith("315 UnitName="))
            all_values = self.client.command(f"PP GET {session.name} *")
            self.assertEqual(all_values.code, 315)
            self.assertTrue(all_values.final.startswith("315 "))
        quick = programmer.quickget("//TEST/254/p/20", "UnitName")
        self.assertEqual(quick.code, 315)
        self.assertTrue(quick.final.startswith("315 UnitName="))
        self.assertEqual(self.client.command("NOOP").code, 200)

    def test_typed_wrapper_cycle(self):
        from cbus_toolkit.native import NativeDatabase, NativeProjects
        from cbus_toolkit.networks import NativeNetworks

        projects = NativeProjects(self.client)
        projects.operation("new", "TEST")
        listed = projects.list()
        self.assertTrue(any("TEST" in line for line in listed.lines))

        database = NativeDatabase(self.client)
        database.create_network("TEST", 254, "Local", "Cni", "127.0.0.1:10001")

        networks = NativeNetworks(self.client)
        networks.open("//TEST/254")
        networks.synchronize("//TEST/254", fast=True)
        self.assertEqual(networks.state("//TEST/254"), "ok")
        self.assertEqual(networks.wait_ready("//TEST/254"), {"ready": True, "state": "ok"})

        # Database unit lifecycle through the native SAFE verbs.
        database.add("//TEST/254", "unit", 20, "Lounge")
        database.set("//TEST/254/p/20/UnitName", "LOUNGE")
        fields = self.client.command("GET //TEST/254/p/20 UnitName")
        self.assertTrue(any("UnitName=LOUNGE" in line for line in fields.lines))
        database.delete("//TEST/254/p/20")

        # Scene playback over the real executor.
        from cbus_toolkit.scenes import SceneAction, SceneExecutor, SceneFile
        played = SceneExecutor(self.client).play(SceneFile((
            SceneAction("//TEST/254/56/1", 255),
            SceneAction("//TEST/254/56/2", 128, 20))))
        self.assertTrue(played.queued)
        self.assertEqual(len(played.responses), 2)

        # Behavioral round-trip: record samples the played levels back.
        # Levels are mock behavior (instant apply, untouched groups read 0),
        # not native device fidelity; the assertion pins the write-then-
        # observe contract both sides implement.
        recorded = SceneExecutor(self.client).record(SceneFile((
            SceneAction("//TEST/254/56/1", 0),
            SceneAction("//TEST/254/56/2", 0),
            SceneAction("//TEST/254/56/9", 0))))
        self.assertEqual(
            [(a.address, a.level) for a in recorded.actions],
            [("//TEST/254/56/1", 255),
             ("//TEST/254/56/2", 128),
             ("//TEST/254/56/9", 0)])

        # Application events through the real wrappers.
        from cbus_toolkit.applications import NativeTrigger
        from cbus_toolkit.enable import NativeEnable
        NativeTrigger(self.client).event("//TEST/254/56", 42)
        NativeEnable(self.client).set("//TEST/254/56", 173)

        # Server events observed on this session proveReport shape parity.
        self.assertTrue(any(line.startswith("#e#") for line in self.client.events))

        projects.operation("save", "TEST")

    def test_create_unit_parameter_round_trip(self):
        # Full native creation flow through the real database + programmer
        # wrappers: DBADD, field writes, PP LOCK/START/NEW/SET/SAVE and
        # session teardown, then an independent read-back session.
        from cbus_toolkit.native import NativeDatabase
        from cbus_toolkit.programming import Programmer
        self.client.command("PROJECT NEW TEST")
        self.client.command("DBCREATENET 254 Local Cni 127.0.0.1:10001")
        result = NativeDatabase(self.client).create_unit(
            "//TEST/254", 20, "Lounge", "KEY1", "1.2.67")
        self.assertEqual(result["unit"], "//TEST/254/p/20")
        # Identity is observable through native 342 DBGET rows.
        identity = self.client.command("DBGET //TEST/254/p/20/UnitType")
        self.assertTrue(any(
            line.startswith("342-") and line.endswith("=KEY1")
            for line in identity.lines))
        # A fresh session loading the database record reads back every
        # staged value. Identity travels struct-side (native `PP GET *`
        # carries no identity rows, as the eDLT snapshotter requires).
        # With catalogue seeding, create_unit stages UnitAddress like
        # native (the reset session already carries the default), while
        # RESET_TO_DEFAULTS restores catalogue defaults verbatim —
        # including UnitName.
        with Programmer(self.client).load("//TEST/254", "/db//TEST/254/p/20") as session:
            self.assertEqual((session.unit_type, session.firmware), ("KEY1", "1.2.67"))
            values = session.values()
        self.assertTrue(values["UnitName"].startswith("NEWUNIT"))
        self.assertNotIn("FirmwareVersion", values)
        self.assertEqual(values["UnitAddress"], "20")
        # Explicit staging round-trips verbatim through SAVE and LOAD.
        with Programmer(self.client).load("//TEST/254", "/db//TEST/254/p/20") as session:
            session.set("UnitAddress", "20")
            session.save_to_source()
        with Programmer(self.client).load("//TEST/254", "/db//TEST/254/p/20") as session:
            reread = session.values()
        self.assertEqual(reread["UnitAddress"], "20")

    def test_event_modes_query_isolation_and_filtering(self):
        # Manual 4.5.83 subscription semantics through the production
        # event wrapper: a bare query reports `306 <mode>`, modes are
        # per-connection, and an `e0` stream stays silent while a
        # subscribed one observes the same broadcast.
        import uuid
        from cbus_toolkit.events import NativeEvents
        project = "M" + uuid.uuid4().hex[:7].upper()
        stream = CGateClient("127.0.0.1", self.port, timeout=2.0)
        writer = CGateClient("127.0.0.1", self.port, timeout=5.0)
        try:
            stream.connect()
            writer.connect()
            monitor = NativeEvents(stream)
            query = stream.command("EVENT")
            self.assertEqual(query.code, 306)
            self.assertTrue(query.final.endswith("306 e+s0c0"))
            monitor.subscribe("e0s0c0")
            query = stream.command("EVENT")
            self.assertTrue(query.final.endswith("306 e0s0c0"))
            # Writer isolation: the reader's mode never touches the
            # writer's session, which keeps the console default.
            query = writer.command("EVENT")
            self.assertTrue(query.final.endswith("306 e+s0c0"))
            writer.command("PROJECT NEW " + project)
            with self.assertRaises(RuntimeError):
                monitor.read()
            # A timed-out read closes the stream (client posture), so
            # reconnect for the positive control on a fresh session and
            # a fresh project (CLOSE does not delete).
            stream.connect()
            monitor.subscribe("e8s1c1")
            project = "N" + uuid.uuid4().hex[:7].upper()
            writer.command("PROJECT NEW " + project)
            try:
                records = []
                for _ in range(100):
                    event = monitor.read()
                    records.append(event)
                    if project in event.raw:
                        break
                self.assertTrue(any(project in event.raw for event in records))
            finally:
                writer.command("PROJECT CLOSE " + project)
        finally:
            stream.close()
            writer.close()
    def test_event_stream_across_connections(self):
        # Mirror of the native acceptance shape (NativeEventTests): one
        # subscribed stream observes another session's project creation,
        # then goes quiet after OFF. Event text is the mock contract
        # (`#e# project <name> created`); the subscribe/read/unsubscribe
        # flow is the native-fidelity claim.
        import uuid
        from cbus_toolkit.events import NativeEvents
        project = "E" + uuid.uuid4().hex[:7].upper()
        stream = CGateClient("127.0.0.1", self.port, timeout=5.0)
        writer = CGateClient("127.0.0.1", self.port, timeout=5.0)
        try:
            stream.connect()
            writer.connect()
            monitor = NativeEvents(stream)
            monitor.subscribe("e8s1c1")
            writer.command("PROJECT NEW " + project)
            try:
                records = []
                for _ in range(100):
                    event = monitor.read()
                    records.append(event)
                    if project in event.raw:
                        break
                self.assertTrue(any(project in event.raw for event in records))
                self.assertFalse(stream.events_lost)
                monitor.subscribe("OFF")
                self.assertEqual(stream.command("NOOP").code, 200)
            finally:
                writer.command("PROJECT CLOSE " + project)
        finally:
            stream.close()
            writer.close()

    def test_project_verbs_registries_and_validation(self):
        # Project lifecycle verbs, the read-only repository inventory
        # (exact empty 124: this model tracks no server repositories),
        # GETSTATE snapshots and native 233 validation, all through the
        # production wrappers. Payload literals are the documented mock
        # contract; status codes and reply shapes are native fidelity.
        from cbus_toolkit.events import NativeEvents
        from cbus_toolkit.native import NativeDatabase, NativeProjects
        from cbus_toolkit.repositories import NativeRepositories
        projects = NativeProjects(self.client)
        projects.operation("new", "TEST")
        self.assertTrue(any("TEST" in line for line in projects.list().lines))
        self.assertTrue(any("TEST" in line for line in projects.directory().lines))
        projects.operation("rename", "TEST", other="TEST2")
        inventory = NativeRepositories(self.client).list()
        self.assertEqual(inventory.repositories, ())
        self.assertEqual(inventory.current_state, "unknown")
        database = NativeDatabase(self.client)
        database.create_network("TEST2", 254, "Local", "Cni", "127.0.0.1:10001")
        monitor = NativeEvents(self.client)
        monitor.subscribe("e8s1c1")
        state = monitor.request_state("//TEST2/254")
        self.assertTrue(state.successful)
        self.assertTrue(any(
            line.endswith("state=closed") for line in state.lines))
        validated = database.validate("//TEST2/254/p/20")
        self.assertEqual(validated.code, 233)
        self.assertTrue(all(
            line.startswith("233-") or line.startswith("233 ")
            for line in validated.lines))

    def test_physical_readdress_confirmed_moved(self):
        # Full physical addressing flow through the real PhysicalAddressing
        # wrapper: plan (runtime/database/MMI guards + refresh), scalar SET
        # write, and independent verification ending in confirmed_moved.
        # The mock moves the physical layer only, so the database hash is
        # stable across the write exactly like native. KEYE1/2.5.00 is the
        # profile the workflow verifies.
        from cbus_toolkit.physical_addressing import PhysicalAddressing
        self.client.command("PROJECT NEW TEST")
        self.client.command("DBCREATENET 254 Local Cni 127.0.0.1:10001")
        self.client.command("DBADDSAFE //TEST/254 Unit 4 Key")
        self.client.command("DBSETSAFE //TEST/254/p/4/UnitType KEYE1")
        self.client.command("DBSETSAFE //TEST/254/p/4/FirmwareVersion 2.5.00")
        self.client.command("DBSETSAFE //TEST/254/p/4/SerialNumber 101136.1558")
        self.client.command("NET OPEN //TEST/254")
        outcome = PhysicalAddressing(self.client).readdress(
            "//TEST/254/p/4", 6, expected_serial="101136.1558")
        self.assertEqual(outcome["outcome"], "confirmed_moved")
        self.assertTrue(outcome["moved"])
        # The database record stays put while the bus unit moves: layer
        # split invariant, read through the native database wrapper.
        from cbus_toolkit.native import NativeDatabase
        identity = NativeDatabase(self.client).get("//TEST/254/p/4/UnitType")
        self.assertTrue(any("KEYE1" in line for line in identity.lines))

    def test_serial_commission_confirmed_moved(self):
        # Single unaddressed KEYE1 at 255 commissioned onto an existing
        # database unit with the same serial/type/firmware, through the
        # real SerialCommissioning wrapper. The destination is staged
        # database-without-physical via MOCK BUS-DEL (an explicit
        # mock-only fixture verb — physical placement has no C-Gate
        # command). Serial content is mock inventory, not observed buses.
        from cbus_toolkit.serial_commissioning import SerialCommissioning
        self.client.command("PROJECT NEW TEST")
        self.client.command("DBCREATENET 254 Local Cni 127.0.0.1:10001")
        for address in (255, 6):
            self.client.command(f"DBADDSAFE //TEST/254 Unit {address} U{address}")
            self.client.command(f"DBSETSAFE //TEST/254/p/{address}/UnitType KEYE1")
            self.client.command(f"DBSETSAFE //TEST/254/p/{address}/FirmwareVersion 2.5.00")
            self.client.command(f"DBSETSAFE //TEST/254/p/{address}/SerialNumber 101136.1558")
        # Split the layers: the source stays physical-only (database
        # record deleted) while the destination stays database-only
        # (bus presence dropped) — the commissioning topology.
        self.client.command("DBDELETE //TEST/254/p/255")
        self.client.command("MOCK BUS-DEL //TEST/254 6")
        self.client.command("NET OPEN //TEST/254")
        outcome = SerialCommissioning(self.client).commission(
            "//TEST/254/p/255", 6, expected_serial="101136.1558")
        self.assertEqual(outcome["outcome"], "confirmed_moved")

    def test_serials_refresh_and_database_inventory(self):
        # Serial identity flows through the real NativeSerials wrapper:
        # cached reads, guarded whole-network refresh (SYNC fast +
        # CHECKUNIT multiplicity + per-unit 300 field reads), and the
        # database inventory parsed from real Network XML. Serial content
        # is mock inventory (database-known units); physical observation
        # is not claimed.
        from cbus_toolkit.addressing import DatabaseAddressing
        from cbus_toolkit.serials import NativeSerials
        self.client.command("PROJECT NEW TEST")
        self.client.command("DBCREATENET 254 Local Cni 127.0.0.1:10001")
        serials = NativeSerials(self.client)
        addressing = DatabaseAddressing(self.client)
        for address, unit_type, serial in (
                (4, "KEYE1", "101136.1558"), (5, "KEYE1", "101136.1559")):
            self.client.command(f"DBADDSAFE //TEST/254 Unit {address} U{address}")
            self.client.command(f"DBSETSAFE //TEST/254/p/{address}/UnitType {unit_type}")
            self.client.command(f"DBSETSAFE //TEST/254/p/{address}/FirmwareVersion 2.5.00")
            self.client.command(f"DBSETSAFE //TEST/254/p/{address}/SerialNumber {serial}")
        self.client.command("NET OPEN //TEST/254")
        cached = serials.cached("//TEST/254")
        self.assertEqual(
            sorted((r.address, r.status) for r in cached.records),
            [(4, "ok"), (5, "ok")])
        refreshed = serials.refresh("//TEST/254")
        self.assertTrue(refreshed.refresh_completed)
        self.assertFalse(refreshed.errors)
        self.assertEqual(
            sorted((r.address, r.serial, r.status) for r in refreshed.records),
            [(4, "101136.1558", "ok"), (5, "101136.1559", "ok")])
        inventory = addressing.inventory("//TEST/254")
        self.assertEqual(
            sorted((u.address, u.unit_type, u.serial) for u in inventory),
            [(4, "KEYE1", "101136.1558"), (5, "KEYE1", "101136.1559")])

    def test_edlt_label_clear_accepted(self):
        # Guarded one-shot dynamic-label clear through the real
        # EdltDynamicLabelClear wrapper: identity/coverage guards plus the
        # native LABEL CLEAREDLT request ending in native_accepted.
        # Physical erasure is unverified by design (see wrapper docs).
        from cbus_toolkit.edlt_label_clear import EdltDynamicLabelClear
        self.client.command("PROJECT NEW TEST")
        self.client.command("DBCREATENET 254 Local Cni 127.0.0.1:10001")
        self.client.command("DBADDSAFE //TEST/254 Unit 5 Panel")
        self.client.command("DBSETSAFE //TEST/254/p/5/UnitType KEYGL5")
        self.client.command("DBSETSAFE //TEST/254/p/5/FirmwareVersion 5.5.00")
        self.client.command("DBSETSAFE //TEST/254/p/5/SerialNumber 101183.1666")
        self.client.command("NET OPEN //TEST/254")
        manager = EdltDynamicLabelClear(self.client)
        plan = manager.plan("//TEST/254/p/5", expected_serial="101183.1666")
        evidence = manager.request(plan)
        self.assertTrue(evidence["native_accepted"])
        self.assertEqual(evidence["outcome"], "native_accepted")

    @unittest.skipUnless(UNITSPEC_DIR, "vendor unitspec directory is absent")
    def test_edlt_lighting_programming_round_trip(self):
        # eDLT widget programming through the real EdltLighting helper
        # against the vendor KEYGL5 specification: catalogue-backed LOAD
        # seeds the full schema (no test-side import), widget configure
        # applies, SAVE persists, and an independent reload observes the
        # identical parameter set. Byte semantics belong to the helper
        # (covered offline); transport, persistence and schema agreement
        # are what this pins.
        from cbus_toolkit.edlt import EdltLighting
        from cbus_toolkit.native import NativeDatabase
        from cbus_toolkit.programming import Programmer
        from cbus_toolkit.unitspec import UnitSpecStore
        self.client.command("PROJECT NEW TEST")
        self.client.command("DBCREATENET 254 Local Cni 127.0.0.1:10001")
        NativeDatabase(self.client).create_unit(
            "//TEST/254", 20, "Panel", "KEYGL5", "5.5.00", catalog_number="5055EDL")
        spec = UnitSpecStore(Path(UNITSPEC_DIR)).load("KEYGL5.xml")
        edlt = EdltLighting(spec)
        programmer = Programmer(self.client)
        with programmer.load("//TEST/254", "/db//TEST/254/p/20") as session:
            result = edlt.configure(
                session, page=1, position=1, group=42, mode="off-on",
                label_text="Lamp", status_type="percent")
            self.assertTrue(result["verified"])
            before = session.values()
            session.save_to_source()
        with programmer.load("//TEST/254", "/db//TEST/254/p/20") as session:
            after = session.values()
        self.assertEqual(before, after)
        self.assertEqual(len(after), len(spec.parameters))

    def test_level_oid_and_documents(self):
        from cbus_toolkit.native import NativeDatabase
        NativeDatabase(self.client)  # wrapper import surface only
        self.client.command("PROJECT NEW TEST")
        self.client.command("DBCREATENET 254 Local Cni 127.0.0.1:10001")
        # Level creation answers 301 + OID; the OID resolves with 342.
        added = self.client.command("DBADDSAFE //TEST/254/56 Level 1 Evening")
        self.assertEqual(added.code, 301)
        oid = added.final.rsplit("=", 1)[-1]
        identity = self.client.command(f"DBGET !{oid}/OID")
        self.assertEqual(identity.code, 342)
        self.assertTrue(identity.final.endswith(oid))
        # Here-document import counts non-blank lines.
        imported = self.client.command_document("CGL IMPORT TEST", "a\n\nb\nc\n")
        self.assertIn("imported=3", imported.lines[0])
        stored = self.client.command_document(
            "DBSETXML //TEST/254/p/20/UnitName", "LOUNGE\n")
        self.assertEqual(stored.code, 200)

    def test_named_trigger_event_resolves_through_level_xml(self):
        # End-to-end tag resolution with production wrappers only: create
        # and initialize a level (the wrapper performs the native 301 +
        # Value-init sequence), resolve its name through the mock's group
        # document, fire the trigger, then copy the level and resolve the
        # copy's tag too.
        from cbus_toolkit.applications import ApplicationError, NativeTrigger
        from cbus_toolkit.native import NativeDatabase
        self.client.command("PROJECT NEW TEST")
        self.client.command("DBCREATENET 254 Local Cni 127.0.0.1:10001")
        database = NativeDatabase(self.client)
        database.add("//TEST/254/56/1", "level", 1, "Evening")
        trigger = NativeTrigger(self.client)
        # The resolved selector is the initialized Value byte.
        self.assertEqual(trigger.resolve_level_tag("//TEST/254/56/1", "Evening"), 1)
        trigger.event("//TEST/254/56/1", "Evening")
        # Copying a level answers the native 301 flow and initializes the
        # copy's value; its tag resolves through the same document.
        source = self.client.command("DBADDSAFE //TEST/254/56/1 Level 5 Source")
        oid = source.final.rsplit("=", 1)[-1]
        database.copy(f"!{oid}", "//TEST/254/56/1", 6, "Copied")
        self.assertEqual(trigger.resolve_level_tag("//TEST/254/56/1", "Copied"), 6)
        trigger.event("//TEST/254/56/1", "Copied")
        # Unknown tags still fail before anything is sent.
        with self.assertRaises(ApplicationError):
            trigger.event("//TEST/254/56/1", "Missing")
        # A raw `!oid/Value` read completes on the wire (space final)
        # with the initialized byte.
        created = self.client.command("DBADDSAFE //TEST/254/56/1 Level 7 Wired")
        wired_oid = created.final.rsplit("=", 1)[-1]
        self.client.command(f"DBSETSAFE !{wired_oid}/Value 7")
        value = self.client.command(f"DBGET !{wired_oid}/Value")
        self.assertEqual(value.code, 342)
        self.assertTrue(value.final.endswith("=7"))


if __name__ == "__main__":
    unittest.main()
