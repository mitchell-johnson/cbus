"""Python-to-Rust interop: the real CGateClient and typed wrappers against cgate-mock.

Spawns the Rust `cgate-mock` TCP test double and drives it with the
production transport (`CGateClient`) plus the native wrapper classes the
CLI itself uses. This proves wire framing, tagging, event separation and
command semantics agree across the two implementations.

Payload literals asserted here (`UnitName=`, `unit=`) are the documented mock
contract, not native C-Gate output: they pin the
interoperability surface both sides implement. Status codes, framing and
the typed-wrapper flows are the native-fidelity claims.

The binary is located via CBUS_CGATE_MOCK_BIN or the sibling Rust
workspace output; the suite skips cleanly when it is absent. The vendor
unit-specification directory is located via CBUS_UNITSPEC_DIR or the
in-repo research copy; catalogue-backed tests skip without it.
"""
from __future__ import annotations

import json
import os
import queue
import re
import socket
import subprocess
import time
import threading
import unittest
from pathlib import Path

from cbus_toolkit.cgate import CGateClient, CGateError


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
        from cbus_toolkit.programming import Programmer, xml_text
        import xml.etree.ElementTree as ET
        NativeDatabase(self.client).create_unit(
            "//TEST/254", 20, "Lounge", "KEY1", "1.2.67")
        programmer = Programmer(self.client)
        with programmer.load("//TEST/254", "/db//TEST/254/p/20") as session:
            # Frame an explicitly staged PP value, not scalar Unit metadata
            # or an invented default when no specification is configured.
            session.set("UnitName", "PPNAME")
            single = self.client.command(f"PP GET {session.name} UnitName")
            self.assertEqual(single.code, 315)
            self.assertEqual(len(single.lines), 1)
            self.assertEqual(single.final, "315 UnitName=PPNAME")
            all_values = self.client.command(f"PP GET {session.name} *")
            self.assertEqual(all_values.code, 315)
            self.assertTrue(all_values.final.startswith("315 "))
            session.save_to_source()
        quick = programmer.quickget("//TEST/254/p/20", "UnitName")
        self.assertEqual(quick.code, 315)
        self.assertEqual(quick.final, "315 UnitName=PPNAME")
        scalar = self.client.command("DBGET //TEST/254/p/20/UnitName")
        self.assertTrue(any(line.startswith("342-") and line.endswith("UnitName=KEY1")
                            for line in scalar.lines))
        document = ET.fromstring(xml_text(self.client.command("DBGETXML //TEST/254/p/20")))
        self.assertEqual(document.findtext("UnitName"), "KEY1")
        self.assertEqual({row.get("Name"): row.get("Value") for row in document.findall("PP")}["UnitName"],
                         "PPNAME")
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
        # UnitName is a database field: native C-Gate rejects the runtime
        # GET form with 402, so read it through the database layer.
        fields = database.get("//TEST/254/p/20/UnitName")
        self.assertTrue(any("UnitName=LOUNGE" in line for line in fields.lines))
        database.delete("//TEST/254/p/20")

        # A never-commanded level is readable only when its group exists in
        # the database. Native/live unknown groups remain a 408 rather than
        # inventing a zero-valued bus observation.
        database.add("//TEST/254", "application", 56, "Lighting")
        database.add("//TEST/254/56", "group", 9, "Untouched")

        # Scene playback over the real executor.
        from cbus_toolkit.scenes import SceneAction, SceneExecutor, SceneFile
        played = SceneExecutor(self.client).play(SceneFile((
            SceneAction("//TEST/254/56/1", 255),
            SceneAction("//TEST/254/56/2", 128, 20))))
        self.assertTrue(played.queued)
        self.assertEqual(len(played.responses), 2)

        # Behavioral round-trip: record samples the played levels back.
        # Levels are mock behavior (instant apply, durable untouched groups
        # read 0), not native device fidelity; the assertion pins the
        # write-then-observe contract both sides implement.
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

    def test_native_label_cache_clear_wrapper_matches_rust_mock_contract(self):
        from cbus_toolkit.labels import NativeLabelCache

        labels = NativeLabelCache(self.client)
        all_keys = labels.clear("//TEST/252/56", 0)
        one_key = labels.clear("//TEST/252/203", 255, key=8)
        self.assertEqual(all_keys["native_command"], "LABEL CLEAR //TEST/252/56 0")
        self.assertEqual(
            one_key["native_command"], "LABEL CLEAR //TEST/252/203 255 8"
        )
        for result in (all_keys, one_key):
            self.assertTrue(result["native_accepted"])
            self.assertTrue(result["pci_confirmation_received"])
            self.assertFalse(result["delivery_outcome_known"])
            self.assertFalse(result["labels_cleared_verified"])
            self.assertFalse(result["persistence_verified"])
            self.assertFalse(result["device_readback"])

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
        scalar_name = self.client.command("DBGET //TEST/254/p/20/UnitName")
        self.assertTrue(any(line.startswith("342-") and line.endswith("UnitName=KEY1")
                            for line in scalar_name.lines))
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
            if not UNITSPEC_DIR:
                with self.assertRaises(CGateError) as absent:
                    self.client.command(f"PP GET {session.name} UnitName")
                self.assertEqual(absent.exception.response.code, 460)
        self.assertNotIn("FirmwareVersion", values)
        if UNITSPEC_DIR:
            self.assertTrue(values["UnitName"].startswith("NEWUNIT"))
            self.assertEqual(values["UnitAddress"], "20")
        else:
            # Without a catalogue the mock cannot invent reset defaults.
            # Scalar UnitName stays separate; UnitAddress is introduced
            # only by the explicit PP SET/SAVE round-trip below.
            self.assertNotIn("UnitName", values)
            self.assertNotIn("UnitAddress", values)
            # QUICKGET retains its documented database-field fallback;
            # this does not introduce UnitName into the session PP namespace.
            quick = Programmer(self.client).quickget("//TEST/254/p/20", "UnitName")
            self.assertEqual(quick.final, "315 UnitName=KEY1")
        # Explicit staging round-trips verbatim through SAVE and LOAD.
        with Programmer(self.client).load("//TEST/254", "/db//TEST/254/p/20") as session:
            session.set("UnitAddress", "20")
            session.save_to_source()
        with Programmer(self.client).load("//TEST/254", "/db//TEST/254/p/20") as session:
            reread = session.values()
        self.assertEqual(reread["UnitAddress"], "20")
        self.assertEqual(reread.get("UnitName"), values.get("UnitName"))
        scalar_name = self.client.command("DBGET //TEST/254/p/20/UnitName")
        self.assertTrue(any(line.startswith("342-") and line.endswith("UnitName=KEY1")
                            for line in scalar_name.lines))

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
        self.client.command("SET //TEST/254 Retries 0")
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
        self.client.command("SET //TEST/254 Retries 0")
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
        self.client.command("SET //TEST/254 Retries 0")
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
        # Here-document import validates bounded CGL 1.1 JSON and returns the
        # native progress envelope.
        document = {"cglVersion": "1.1", "localNetwork": 254, "networks": [
            {"address": 254, "applications": [
                {"address": 57, "name": "Local Application", "groups": [
                    {"address": 2, "name": "Hall"}]}]}]}
        imported = self.client.command_document(
            "CGL IMPORT TEST", json.dumps(document))
        self.assertTrue(any("Created new group 254/57/2 ('Hall')" in line
                            for line in imported.lines))
        stored = self.client.command_document(
            "DBSETXML //TEST/254/p/20/UnitName", "LOUNGE\n")
        self.assertEqual(stored.code, 200)

    def test_cgl_route_vectors_match_native_capture(self):
        """Every native-derived CGL vector through a fresh mock per group."""
        from research import native_cgl_routes as routes
        from cbus_toolkit.cgl import NativeCGL
        vectors_path = Path(__file__).resolve().parents[2] / "rust/testdata/vectors/cgate_cgl_routes.jsonl"
        rows = [json.loads(line) for line in vectors_path.read_text().splitlines()]
        groups = {}
        for row in rows:
            groups.setdefault(row["group"], []).append(row)
        for group, members in groups.items():
            port = self.port if group == rows[0]["group"] else self._spawn_mock()
            with socket.create_connection(("127.0.0.1", port), timeout=30) as sock, \
                    sock.makefile("rb") as reader:
                reader.readline()
                for index, row in enumerate(members):
                    document = row.get("document")
                    if "document_generator" in row:
                        document = routes.large_document()
                    command = row["command"].replace("<simulator>", "127.0.0.2:29999")
                    request = f"[{index}] {command}"
                    if document is not None:
                        request += f" << END{index}\r\n{document}\r\nEND{index}"
                    sock.sendall((request + "\r\n").encode())
                    reply = []
                    while True:
                        line = reader.readline().decode().rstrip("\r\n")
                        self.assertTrue(line, row["id"])
                        if not line.startswith(f"[{index}] "):
                            continue
                        reply.append(re.sub(r"OID=[0-9a-fA-F-]{36}", "OID=<oid>", line[len(f"[{index}] "):]))
                        if re.match(r"\d{3} ", reply[-1]):
                            break
                    with self.subTest(vector=row["id"]):
                        if row.get("setup"):
                            self.assertLess(int(reply[-1][:3]), 400, reply)
                        elif "expect" in row:
                            self.assertEqual(reply, row["expect"])
                        elif "expect_prefix" in row:
                            self.assertTrue(reply[-1].startswith(row["expect_prefix"]), reply)
                        elif "expect_export" in row:
                            expected = row["expect_export"]
                            self.assertEqual((reply[0], reply[-1]), (expected["first"], expected["final"]))
                            self.assertEqual(routes.canonical_export(reply[1]), expected["document"])
                        else:
                            expected = row["expect_summary"]
                            self.assertEqual((len(reply), reply[-1][:160]), (expected["lines"], expected["last"]))
        # The typed Python client reads the Rust export of the routed chain.
        port = self._spawn_mock()
        with CGateClient("127.0.0.1", port, timeout=10.0) as client:
            for row in groups["chain"]:
                if row.get("setup") and not row["command"].startswith("NET "):
                    client.command(row["command"].replace("<simulator>", "127.0.0.2:29999"))
            exported = NativeCGL(client).export("CGLP", networks=[254])
        self.assertEqual([network.get("route", []) for network in exported["networks"]][-1],
                         [253, 252, 251, 250, 249, 248])

    def _spawn_mock(self):
        process = subprocess.Popen([MOCK_BIN, "--bind", "127.0.0.1:0"], stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, text=True)

        def stop():
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5.0)
            process.stdout.close()
        self.addCleanup(stop)
        match = re.fullmatch(r"cgate-mock listening on 127\.0\.0\.1:(\d+)\s*", process.stdout.readline(512))
        self.assertIsNotNone(match)
        return int(match[1])

    def test_typed_unit_document_drops_unmodeled_markup_like_native_mapper(self):
        from cbus_toolkit.native import NativeDatabase
        from cbus_toolkit.programming import xml_text

        self.client.command("PROJECT NEW TEST")
        self.client.command("DBCREATENET 254 Local Cni 127.0.0.1:10001")
        database = NativeDatabase(self.client)
        database.add("//TEST/254", "unit", 20, "Original")
        database.set("//TEST/254/p/20/UnitType", "KEYE1")
        database.set("//TEST/254/p/20/FirmwareVersion", "1.2.67")
        initial = xml_text(database.get("//TEST/254/p/20", xml=True))
        match = re.search(r"<OID>([0-9a-fA-F-]{36})</OID>", initial)
        self.assertIsNotNone(match)
        oid = match.group(1)

        replacement = (
            '<Unit xmlns:x="urn:interop" x:mode="preserve">'
            f"<OID>{oid}</OID><Address>21</Address><TagName>Moved</TagName>"
            "<UnitType>KEYE1</UnitType><UnitName>Moved</UnitName>"
            "<FirmwareVersion>1.2.67</FirmwareVersion>"
            '<!--opaque-comment--><Description><x:Opaque order="1">'
            '<x:Nested>yes</x:Nested></x:Opaque></Description>'
            '<PP Name="UnitAddress" Value="21"/></Unit>'
        )
        with self.assertRaises(CGateError) as refused:
            self.client.command_document(
                "DBSETXML //TEST/254/p/20",
                replacement.replace("<UnitName>Moved</UnitName>", ""))
        self.assertEqual(refused.exception.response.code, 446)
        self.assertEqual(xml_text(database.get("//TEST/254/p/20", xml=True)), initial)
        replaced = self.client.command_document(
            "DBSETXML //TEST/254/p/20", replacement)
        self.assertEqual(replaced.code, 301)
        self.assertEqual(replaced.final, f"301 OID={oid}")

        moved = xml_text(database.get("//TEST/254/p/21", xml=True))
        self.assertNotIn('x:mode="preserve"', moved)
        self.assertNotIn('xmlns:x="urn:interop"', moved)
        self.assertNotIn("<!--opaque-comment-->", moved)
        self.assertNotIn("<x:Nested>yes</x:Nested>", moved)
        self.assertIn("<Description></Description>", moved)
        self.assertIn('<PP Name="UnitAddress" Value="21"/>', moved)

        # Later modeled changes retain the scalar/PP projection only.
        database.set("//TEST/254/p/21/TagName", "Projected")
        database.set("//TEST/254/p/21/UnitAddress", "22")
        projected = xml_text(database.get("//TEST/254/p/21", xml=True))
        self.assertIn("<TagName>Projected</TagName>", projected)
        self.assertIn('<PP Name="UnitAddress" Value="22"/>', projected)
        self.assertNotIn('x:mode="preserve"', projected)
        self.assertNotIn("<!--opaque-comment-->", projected)
        self.assertNotIn("<x:Nested>yes</x:Nested>", projected)
        self.assertIn("<Description></Description>", projected)

    def test_typed_container_document_replaces_complete_subtree(self):
        from cbus_toolkit.native import NativeDatabase
        from cbus_toolkit.programming import xml_text

        self.client.command("PROJECT NEW XMLT")
        self.client.command("DBCREATENET 254 Local Cni 127.0.0.1:1")
        added = self.client.command("DBADD 254 Application")
        old_oid = added.final.rsplit("=", 1)[-1]
        self.client.command(f"DBSET !{old_oid}/Address 56")
        self.client.command(f"DBSET !{old_oid}/TagName Original")
        replacement = (
            '<Application xmlns:x="urn:interop" x:source="python">'
            '<OID>60000000-0000-4000-8000-000000000001</OID>'
            '<TagName>Moved</TagName><Address>58</Address>'
            '<Group><OID>60000000-0000-4000-8000-000000000002</OID>'
            '<TagName>Scenes</TagName><Address>10</Address>'
            '<Level Value="128">'
            '<OID>60000000-0000-4000-8000-000000000003</OID>'
            '<TagName>Evening</TagName><Address>1</Address></Level></Group>'
            '<!--kept--><x:Metadata>opaque</x:Metadata></Application>'
        )
        replaced = self.client.command_document(
            f"DBSETXML !{old_oid}", replacement)
        self.assertEqual(replaced.code, 301)
        self.assertEqual(
            replaced.final,
            "301 OID=60000000-0000-4000-8000-000000000001")

        database = NativeDatabase(self.client)
        readback = xml_text(database.get("//XMLT/254/58", xml=True))
        self.assertIn('<Application>', readback)
        self.assertNotIn('xmlns:x="urn:interop"', readback)
        self.assertNotIn('x:source="python"', readback)
        self.assertIn('<Level', readback)
        self.assertIn('Value="128"', readback)
        self.assertIn('<Address>1</Address>', readback)
        self.assertNotIn('<!--kept-->', readback)
        self.assertNotIn('<x:Metadata>opaque</x:Metadata>', readback)
        with self.assertRaises(RuntimeError):
            database.get("//XMLT/254/56", xml=True)
        with self.assertRaises(RuntimeError):
            self.client.command(f"DBGET !{old_oid}/OID")

    def test_group_dlt_document_roundtrip(self):
        from xml.etree import ElementTree as ET

        from cbus_toolkit.native import NativeDatabase
        from cbus_toolkit.programming import xml_text

        self.client.command("PROJECT NEW XMLD")
        self.client.command("DBCREATENET 254 Local Cni 127.0.0.1:1")
        database = NativeDatabase(self.client)
        network = xml_text(database.get("//XMLD/254", xml=True))
        tree = (
            "<Application><OID>33333333-3333-4333-8333-333333333333</OID>"
            "<TagName>Lighting</TagName><Address>56</Address>"
            "<Group><OID>44444444-4444-4444-8444-444444444444</OID>"
            "<TagName>Garage</TagName><Address>1</Address></Group></Application>")
        self.assertEqual(self.client.command_document(
            "DBSETXML //XMLD/254",
            network.replace("</Network>", tree + "</Network>")).code, 301)
        group_path = "//XMLD/254/56/1"
        group = xml_text(database.get(group_path, xml=True))
        label = ("<TagsDLT><TagDLT><LanguageID>1</LanguageID><FlavourID>1</FlavourID>"
                 "<TagType>TEXT</TagType><TagValue>Garage scene</TagValue>"
                 "</TagDLT></TagsDLT>")
        self.assertEqual(self.client.command_document(
            "DBSETXML " + group_path,
            group.replace("</Group>", label + "</Group>")).code, 301)
        read = ET.fromstring(xml_text(database.get(group_path, xml=True)))
        tag = read.find("TagsDLT/TagDLT")
        self.assertEqual(tag.findtext("TagValue"), "Garage scene")
        issued_oid = tag.findtext("OID")
        self.assertIsNotNone(issued_oid)
        self.client.command("PROJECT SAVE XMLD")
        self.client.command("PROJECT CLOSE XMLD")
        self.client.command("PROJECT LOAD XMLD")
        self.client.command("PROJECT USE XMLD")
        network_after = ET.fromstring(xml_text(database.get("//XMLD/254", xml=True)))
        retained = network_after.find(".//Group/TagsDLT/TagDLT")
        self.assertEqual(retained.findtext("OID"), issued_oid)
        self.assertEqual(retained.findtext("TagValue"), "Garage scene")

    def test_public_cli_exports_and_replaces_complete_group_xml_file(self):
        import hashlib
        import sys
        import tempfile
        from xml.etree import ElementTree as ET

        from cbus_toolkit.native import NativeDatabase
        from cbus_toolkit.programming import xml_text

        self.client.command("PROJECT NEW XMLC")
        self.client.command("DBCREATENET 254 Local Cni 127.0.0.1:1")
        database = NativeDatabase(self.client)
        network = xml_text(database.get("//XMLC/254", xml=True))
        tree = (
            "<Application><OID>33333333-3333-4333-8333-333333333333</OID>"
            "<TagName>Lighting</TagName><Address>56</Address>"
            "<Group><OID>44444444-4444-4444-8444-444444444444</OID>"
            "<TagName>Garage</TagName><Address>1</Address></Group></Application>")
        self.assertEqual(self.client.command_document(
            "DBSETXML //XMLC/254",
            network.replace("</Network>", tree + "</Network>")).code, 301)

        def invoke(*arguments):
            process = subprocess.run(
                [sys.executable, "-m", "cbus_toolkit", "cgate", "--host", "127.0.0.1",
                 "--port", str(self.port), "database", *map(str, arguments)],
                text=True, capture_output=True, timeout=15,
            )
            return process.returncode, json.loads(process.stdout or process.stderr)

        group_path = "//XMLC/254/56/1"
        with tempfile.TemporaryDirectory() as directory:
            original = Path(directory) / "group.xml"
            status, export = invoke("get-xml", group_path, "--project", "XMLC",
                                    "--output", original)
            self.assertEqual(status, 0)
            self.assertEqual(export["format"], "cbus-cgate-dbgetxml-export-v1")
            baseline = original.read_bytes()
            self.assertEqual(export["sha256"], hashlib.sha256(baseline).hexdigest())
            self.assertEqual(ET.fromstring(baseline).tag, "Group")
            status, refusal = invoke("get-xml", group_path, "--project", "XMLC",
                                     "--output", original)
            self.assertEqual(status, 1)
            self.assertIn("already exists", refusal["error"])
            self.assertEqual(original.read_bytes(), baseline)

            label = ("<TagsDLT><TagDLT><LanguageID>1</LanguageID><FlavourID>1</FlavourID>"
                     "<TagType>TEXT</TagType><TagValue>Garage scene</TagValue>"
                     "</TagDLT></TagsDLT>")
            replacement = Path(directory) / "replacement.xml"
            replacement.write_text(baseline.decode("utf-8").replace(
                "</Group>", label + "</Group>"), encoding="utf-8")
            status, applied = invoke(
                "set-xml", group_path, replacement, "--project", "XMLC",
                "--expect-current-sha256", export["sha256"], "--readback",
            )
            self.assertEqual(status, 0)
            self.assertTrue(applied["accepted"])
            self.assertEqual(applied["response"]["status"], 301)
            self.assertTrue(applied["readback"]["retrieved"])
            self.assertFalse(applied["project_save_requested"])
            group = ET.fromstring(xml_text(database.get(group_path, xml=True)))
            self.assertEqual(group.findtext("TagsDLT/TagDLT/TagValue"), "Garage scene")

            status, refusal = invoke(
                "set-xml", group_path, replacement, "--project", "XMLC",
                "--expect-current-sha256", "0" * 64,
            )
            self.assertEqual(status, 1)
            self.assertIn("SHA-256 differs", refusal["error"])
            self.assertEqual(
                xml_text(database.get(group_path, xml=True)).count("Garage scene"), 1
            )

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

    def test_public_cli_network_diagnose_matches_mock_native_envelopes(self):
        """Toolkit Diagnostics dialog through the real CLI and cgate-mock.

        The mock has no bus: present units keep the native zero summary
        (NetVoltage 0.5, BurdenActive no) and a unit without a
        ClockGenEnable parameter answers native 460. This pins the
        cross-language envelopes, not voltages, burdens or clocks.
        """
        import sys

        for command in (
            "PROJECT NEW DIAGNOSE",
            "PROJECT USE DIAGNOSE",
            "DBCREATENET 254 Diag Cni 127.0.0.1:10001",
            "DBADDSAFE //DIAGNOSE/254 Unit 16 U16",
            "DBSETSAFE //DIAGNOSE/254/p/16/UnitType PC_CNIED",
            "DBADDSAFE //DIAGNOSE/254 Unit 20 U20",
            "DBSETSAFE //DIAGNOSE/254/p/20/UnitType KEYGL5",
            "DBADDSAFE //DIAGNOSE/254 Unit 99 U99",
            "DBSETSAFE //DIAGNOSE/254/p/99/UnitType KEYE1",
            "MOCK BUS-DEL //DIAGNOSE/254 99",
            "NET OPEN //DIAGNOSE/254",
        ):
            self.client.command(command)

        def diagnose(*arguments):
            process = subprocess.run(
                [sys.executable, "-m", "cbus_toolkit", "cgate", "--host", "127.0.0.1",
                 "--port", str(self.port), "network", "diagnose", "//DIAGNOSE/254",
                 "--project", "DIAGNOSE", *arguments],
                text=True, capture_output=True, timeout=30,
            )
            return process.returncode, json.loads(process.stdout or process.stderr)

        status, report = diagnose()
        # Unit 99 is database-only, so the run is incomplete (exit 1).
        self.assertEqual(status, 1, report)
        self.assertEqual(report["pingu_addresses"], [16, 20])
        units = {row["address"]: row for row in report["units"]}
        self.assertEqual(
            {key: units[16][key] for key in ("found", "voltage", "voltage_text", "burden",
                                             "burden_basis", "clock", "clock_basis", "errors")},
            {"found": "present", "voltage": 0.5, "voltage_text": "0.5", "burden": "not-enabled",
             "burden_basis": "native-burdenactive", "clock": "not-enabled",
             "clock_basis": "no-clockgenenable-parameter", "errors": []})
        self.assertEqual((units[20]["burden_basis"], units[20]["clock_basis"]),
                         ("toolkit-unit-type-rule", "toolkit-unit-type-rule"))
        self.assertEqual({key: units[99][key] for key in ("found", "voltage", "burden", "clock")},
                         {"found": "not-found", "voltage": "unknown", "burden": "unknown",
                          "clock": "unknown"})
        self.assertFalse(report["complete"])
        self.assertFalse(report["absent_units_queried"])
        sent = [row["command"] for row in report["commands"]]
        self.assertFalse(any("/p/99" in command for command in sent), sent)
        self.assertFalse(any("/p/20 Psync" in command or "/p/20 BurdenActive" in command
                             for command in sent), sent)
        replies = {row["command"]: row["lines"] for row in report["commands"]}
        self.assertEqual(replies["DO //DIAGNOSE/254/p/16 Psync"],
                         ["202 Done: //DIAGNOSE/254/p/16"])
        self.assertEqual([lines for command, lines in replies.items()
                          if command.endswith(" ClockGenEnable")],
                         [["460 No such parameter: ClockGenEnable"]])

        # Present units only, with every requested field known: exit 0.
        status, report = diagnose("--unit", "16", "--unit", "20")
        self.assertEqual(status, 0, report)
        self.assertTrue(report["complete"])


if __name__ == "__main__":
    unittest.main()
