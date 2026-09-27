"""Python CLI -> cmqttd -> independent routed PCI programming acceptance.

The peer in this module deliberately does not reuse the Rust protocol encoder,
decoder, transport, or cmqttd test support.  It implements only the literal
wire forms needed by the ten admitted PP methods and records every request.
These are scripted-PCI integration tests, not physical-device or power-cycle
acceptance.
"""
from contextlib import contextmanager
import json
from pathlib import Path
import re
import socket
import subprocess
import sys
import threading
import time

import pytest
from cbus_toolkit.simulator import PCISimulator


ROOT = Path(__file__).resolve().parents[2]
BIN = ROOT / "rust/target/debug/cmqttd"
METHODS = (
    "direct",
    "paged",
    "ncc",
    "edlt",
    "giu",
    "sgiu",
    "dali",
    "goc",
    "gocbyt",
    "goc2",
)
BRIDGE = 253
UNIT = 5
LOCAL_PCI = 16


class _DropConnection(Exception):
    pass


def _checksum(body):
    return bytes((*body, -sum(body) & 0xFF))


def _wire(bridge, unit, cal):
    body = bytes((0x86, bridge, LOCAL_PCI, 1, unit, *cal))
    return _checksum(body).hex().upper().encode("ascii") + b"\r\n"


def _reply(parameter, data):
    return bytes((0x80 | (len(data) + 1), parameter, *data))


class RoutedProgrammingPCI(PCISimulator):
    """Small stateful peer for the exact routed PP wire contract."""

    def __init__(self, *, overflow_on_first_recall=False, drop_on_method=None):
        super().__init__(profile="captured", command_checksum=True)
        self.standard = {0x20: bytearray((0x10, 0x11))}
        self.paged = {
            0x1FF: 0x20,
            0x200: 0x21,
            0x300: 0x30,
            0x301: 0x31,
        }
        self.oem = {
            0x10: 0x40,
            0x11: 0x41,
            0x20: 0x50,
            0x21: 0x51,
            0x30: 0x60,
            0x31: 0x61,
            0x40: 0x70,
            0x41: 0x71,
        }
        self.goc = {
            0x50: 0x80,
            0x51: 0x81,
            0x60: 0x90,
            0x61: 0x91,
            0x70: 0xA0,
            0x71: 0xA1,
        }
        self.selected_page = None
        self.oem_pointer = None
        self.goc_pointer = None
        self.requests = []
        self.stores = []
        self.noise_frames = 0
        self.nvm_executes = 0
        self.overflow_on_first_recall = overflow_on_first_recall
        self.overflow_sent = False
        self.drop_on_method = drop_on_method
        self.dropped = False
        self._peer_lock = threading.Lock()

    def _connection(self, conn, connection, shutdown):
        try:
            super()._connection(conn, connection, shutdown)
        except _DropConnection:
            # Returning from the request handler closes the TCP stream.  The
            # daemon must classify the in-flight mutation as uncertain and
            # must not replay it on its replacement connection.
            return

    @staticmethod
    def _method_for_oem(address):
        return {0x10: "edlt", 0x20: "giu", 0x30: "sgiu", 0x40: "dali"}[address]

    @staticmethod
    def _method_for_goc(address):
        return {0x50: "goc", 0x60: "gocbyt", 0x70: "goc2"}[address]

    def _response(self, code, cal, stale):
        # Each accepted transaction is preceded by three independently
        # complete distractions: neighbouring route, wrong terminal unit and
        # exact route/unit with a stale parameter or ACK tag.
        frames = (
            _wire(BRIDGE - 1, UNIT, cal)
            + _wire(BRIDGE, UNIT + 1, cal)
            + _wire(BRIDGE, UNIT, stale)
            + _wire(BRIDGE, UNIT, cal)
        )
        self.noise_frames += 3
        return (code + b"." if code else b"") + frames, None

    def _request(self, line):
        code = b""
        if line and ord("g") <= line[-1] <= ord("z"):
            code, line = line[-1:], line[:-1]
        if not line.startswith(b"\\"):
            raise AssertionError(f"unexpected PCI command {line!r}")
        raw = bytes.fromhex(line[1:].decode("ascii"))
        if len(raw) < 6 or sum(raw) & 0xFF:
            raise AssertionError(f"routed command lacks its exact checksum: {raw.hex()}")
        body = raw[:-1]
        if body[:4] != bytes((0x46, BRIDGE, 9, UNIT)):
            raise AssertionError(f"unexpected routed target: {body[:4].hex()}")
        cal = body[4:]
        with self._peer_lock:
            self.requests.append({
                "route": [BRIDGE],
                "unit": UNIT,
                "cal_hex": cal.hex().upper(),
                "checksum": raw[-1],
                "confirmation": code.decode("ascii") if code else None,
            })
        return code, cal

    def _read(self, memory, address, count):
        return bytes(memory[index] for index in range(address, address + count))

    def _store(self, method, parameter, tag, address, data):
        row = {
            "method": method,
            "route": [BRIDGE],
            "unit": UNIT,
            "parameter": parameter,
            "tag": tag,
            "address": address,
            "count": len(data),
            "data_hex": data.hex().upper(),
        }
        with self._peer_lock:
            self.stores.append(row)
        if self.drop_on_method == method and not self.dropped:
            self.dropped = True
            raise _DropConnection()

    def _command(self, line, context):
        if line in (b"~", b"A32100FF", b"A32200FF", b"A342000E", b"A3300079"):
            return b"", None
        code, cal = self._request(line)
        opcode = cal[0]

        if opcode == 0x21:
            if len(cal) != 2 or cal[1] not in (1, 2):
                raise AssertionError(f"unexpected IDENTIFY {cal.hex()}")
            parameter = cal[1]
            data = b"PPTEST" if parameter == 1 else b"1.0.00"
            answer = _reply(parameter, data)
            stale = _reply(parameter ^ 1, data)
            return self._response(code, answer, stale)

        if opcode == 0x1A:
            if len(cal) != 3 or cal[2] == 0:
                raise AssertionError(f"unexpected RECALL {cal.hex()}")
            parameter, count = cal[1:]
            if parameter == 0x20:
                data = bytes(self.standard[parameter][:count])
                method = "direct"
            elif parameter == 1 and self.oem_pointer is not None:
                data = self._read(self.oem, self.oem_pointer, count)
                method = self._method_for_oem(self.oem_pointer)
            elif parameter == 0xFF and self.goc_pointer is not None:
                data = self._read(self.goc, self.goc_pointer, count)
                method = self._method_for_goc(self.goc_pointer)
            else:
                raise AssertionError(f"RECALL has no selected memory: {cal.hex()}")
            with self._peer_lock:
                self.requests[-1].update(kind="recall", method=method,
                                         parameter=parameter, count=count)
            if self.overflow_on_first_recall and not self.overflow_sent:
                self.overflow_sent = True
                first = _reply(parameter, data[:1])
                excess = _reply(parameter, data)
                stale = _reply((parameter + 1) & 0xFF, data)
                frames = (_wire(BRIDGE - 1, UNIT, first)
                          + _wire(BRIDGE, UNIT, stale)
                          + _wire(BRIDGE, UNIT, first)
                          + _wire(BRIDGE, UNIT, excess))
                self.noise_frames += 2
                return (code + b"." if code else b"") + frames, None
            answer = _reply(parameter, data)
            stale = _reply((parameter + 1) & 0xFF, data)
            return self._response(code, answer, stale)

        if opcode == 0x1B:
            if len(cal) != 4 or cal[3] == 0:
                raise AssertionError(f"unexpected paged RECALL {cal.hex()}")
            page, parameter, count = cal[1:]
            address = page * 256 + parameter
            data = self._read(self.paged, address, count)
            method = "paged" if address < 0x300 else "ncc"
            with self._peer_lock:
                self.requests[-1].update(kind="paged-recall", method=method,
                                         parameter=parameter, page=page, count=count)
            answer = _reply(parameter, data)
            stale = _reply((parameter + 1) & 0xFF, data)
            return self._response(code, answer, stale)

        if opcode == 0x39:
            if len(cal) != 2:
                raise AssertionError(f"unexpected SET_PAGE {cal.hex()}")
            self.selected_page = cal[1]
            answer = _reply(cal[1], b"")
            stale = _reply((cal[1] + 1) & 0xFF, b"")
            with self._peer_lock:
                self.requests[-1].update(kind="set-page", page=cal[1], count=0)
            return self._response(code, answer, stale)

        if opcode == 0xE3 and len(cal) == 4 and cal[1:] == bytes((0x81, 0, 4)):
            self.nvm_executes += 1
            answer = bytes((0xE4, 0x83, 0, 4, 0))
            stale = bytes((0xE4, 0x83, 0, 5, 0))
            with self._peer_lock:
                self.requests[-1].update(kind="nvm-execute", group=0,
                                         operation=4, count=0)
            return self._response(code, answer, stale)

        if opcode & 0xE0 == 0xA0:
            declared = opcode & 0x1F
            if declared < 2 or len(cal) != declared + 1:
                raise AssertionError(f"malformed WRITE {cal.hex()}")
            parameter, data = cal[1], cal[2:]
            tag = data[0]
            method = None
            address = None

            if parameter == 0 and tag == 0x41 and len(data) in (3, 5):
                self.oem_pointer = int.from_bytes(data[1:], "little")
                method = self._method_for_oem(self.oem_pointer)
                address = self.oem_pointer
                kind = "oem-selector"
            elif parameter == 1 and tag == 0x42 and self.oem_pointer is not None:
                method = self._method_for_oem(self.oem_pointer)
                address = self.oem_pointer
                payload = data[1:]
                self._store(method, parameter, tag, address, payload)
                for offset, value in enumerate(payload):
                    self.oem[address + offset] = value
                self.oem_pointer += len(payload)
                kind = "store"
            elif parameter == 0xFC and data in (bytes((3, 0)), bytes((3, 1))):
                method = "giu"
                address = 0xFC
                kind = "giu-run-state"
            elif parameter == 0xFF and tag == 0x42 and len(data) == 3:
                self.goc_pointer = int.from_bytes(data[1:], "big")
                method = self._method_for_goc(self.goc_pointer)
                address = self.goc_pointer
                kind = "goc-selector"
            elif parameter == 0xFF and len(data) >= 4:
                address = int.from_bytes(data[1:3], "big")
                method = self._method_for_goc(address)
                payload = data[3:]
                self._store(method, parameter, tag, address, payload)
                for offset, value in enumerate(payload):
                    self.goc[address + offset] = value
                kind = "store"
            elif parameter == 0x20:
                method = "direct"
                address = parameter
                payload = data[1:]
                self._store(method, parameter, tag, address, payload)
                self.standard[parameter][:] = payload
                kind = "store"
            elif self.selected_page is not None:
                address = self.selected_page * 256 + parameter
                method = "paged" if address < 0x300 else "ncc"
                payload = data[1:]
                self._store(method, parameter, tag, address, payload)
                for offset, value in enumerate(payload):
                    self.paged[address + offset] = value
                kind = "store"
            else:
                raise AssertionError(f"unclassified WRITE {cal.hex()}")

            with self._peer_lock:
                self.requests[-1].update(kind=kind, method=method,
                                         parameter=parameter, tag=tag,
                                         address=address, count=max(0, len(data) - 1))
            answer = bytes((0x32, parameter, tag))
            stale = bytes((0x32, parameter, tag ^ 0xFF))
            return self._response(code, answer, stale)

        raise AssertionError(f"unsupported routed CAL {cal.hex()}")


def _write_project(path):
    unit_type = "PPTEST"
    path.write_text(
        '<Installation><Project oid="project"><TagName>TEST</TagName>'
        '<Network oid="local"><TagName>Local</TagName><Address>254</Address>'
        '<Interface><InterfaceType>CNI</InterfaceType>'
        '<InterfaceAddress>127.0.0.1:10001</InterfaceAddress></Interface>'
        '<Unit oid="pci"><Address>16</Address><UnitType>PC_CNI2</UnitType></Unit>'
        '<Unit oid="bridge"><Address>253</Address><UnitType>BRIDGE2N</UnitType></Unit>'
        '</Network><Network oid="remote"><TagName>Remote</TagName><Address>253</Address>'
        '<Interface><InterfaceType>Bridge</InterfaceType>'
        '<InterfaceAddress>254/p/253</InterfaceAddress></Interface>'
        f'<Unit oid="target"><Address>5</Address><UnitType>{unit_type}</UnitType>'
        '<FirmwareVersion>1.0.00</FirmwareVersion></Unit>'
        '</Network></Project></Installation>',
        encoding="utf-8",
    )
    return unit_type


def _write_spec(directory, unit_type, *, all_methods=True):
    if all_methods:
        rows = (
            ("direct", "$20"),
            ("paged", "$1FF"),
            ("ncc", "$300"),
            ("edlt", "$110"),
            ("giu", "$120"),
            ("sgiu", "$130"),
            ("dali", "$140"),
            ("goc", "$150"),
            ("gocbyt", "$160"),
            ("goc2", "$170"),
        )
    else:
        rows = (("direct", "$20"),)
    parameters = "".join(
        '<Param><Name>' + method + '</Name><Type>int</Type><Address>' + address
        + '</Address><ArraySize>2</ArraySize><ProgramMethod>' + method
        + '</ProgramMethod><Protection>none</Protection></Param>'
        for method, address in rows
    )
    (directory / f"{unit_type}.xml").write_text(
        f"<UnitSpecification><Parameters>{parameters}</Parameters></UnitSpecification>",
        encoding="utf-8",
    )


@contextmanager
def _running_daemon(tmp_path, pci, project, specs):
    with socket.socket() as broker:
        broker.bind(("127.0.0.1", 0))
        broker.listen(1)
        log_path = tmp_path / "programming-methods-daemon.log"
        with log_path.open("w+") as log:
            process = subprocess.Popen([
                str(BIN), "--tcp", f"{pci[0]}:{pci[1]}",
                "--broker-address", "127.0.0.1",
                "--broker-port", str(broker.getsockname()[1]),
                "--broker-disable-tls", "--timesync", "0", "--status-resync", "0",
                "--project-file", str(project), "--cgate-bind", "127.0.0.1:0",
                "--cgate-state", str(tmp_path / "state.json"),
                "--cgate-unitspec", str(specs),
            ], stdout=subprocess.DEVNULL, stderr=log)
            try:
                deadline = time.monotonic() + 20
                port = None
                output = ""
                while time.monotonic() < deadline:
                    log.seek(0)
                    output = log.read()
                    match = re.search(r"C-Gate service listening on 127\.0\.0\.1:(\d+)", output)
                    if match:
                        port = match[1]
                        break
                    assert process.poll() is None, output
                    time.sleep(0.02)
                assert port is not None, output
                yield port
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


def _invoke(port, method, value, *, timeout=180):
    return subprocess.run([
        sys.executable, "-m", "cbus_toolkit", "cgate",
        "--host", "127.0.0.1", "--port", str(port), "--timeout", "45",
        "physical-pp", "apply", "//TEST/253/p/5", "--method", method,
        "--set", method, " ".join(f"0x{byte:02X}" for byte in value),
    ], capture_output=True, text=True, timeout=timeout)


def _fixture(tmp_path, *, all_methods=True):
    specs = tmp_path / "unitspec"
    specs.mkdir()
    project = tmp_path / "project.xml"
    unit_type = _write_project(project)
    _write_spec(specs, unit_type, all_methods=all_methods)
    return project, specs


@pytest.mark.skipif(not BIN.exists(), reason="Build cmqttd before cross-language interop")
def test_real_cli_programs_all_ten_methods_through_routed_scripted_pci(tmp_path):
    """Prove the full software boundary without claiming physical acceptance."""
    project, specs = _fixture(tmp_path)
    peer = RoutedProgrammingPCI()
    expected = {
        method: bytes((0xB0 + index, 0xC0 + index))
        for index, method in enumerate(METHODS)
    }
    results = {}
    with peer.running() as pci, _running_daemon(tmp_path, pci, project, specs) as port:
        for method in METHODS:
            result = _invoke(port, method, expected[method])
            assert result.returncode == 0, (method, result.stderr)
            value = json.loads(result.stdout)
            assert value["method"] == method
            assert value["complete"]
            assert value["save_attempts"] == 1
            assert value["automatic_write_retries"] == 0
            assert value["staged_readback_verified"]
            assert value["fresh_physical_readback_verified"]
            assert not value["power_cycle_persistence_verified"]
            assert not value["hardware_method_matrix_accepted"]
            results[method] = value

    assert bytes(peer.standard[0x20]) == expected["direct"]
    assert bytes(peer.paged[index] for index in (0x1FF, 0x200)) == expected["paged"]
    assert bytes(peer.paged[index] for index in (0x300, 0x301)) == expected["ncc"]
    for method, address in (("edlt", 0x10), ("giu", 0x20),
                            ("sgiu", 0x30), ("dali", 0x40)):
        assert bytes(peer.oem[index] for index in (address, address + 1)) == expected[method]
    for method, address in (("goc", 0x50), ("gocbyt", 0x60), ("goc2", 0x70)):
        assert bytes(peer.goc[index] for index in (address, address + 1)) == expected[method]

    stores_by_method = {method: [] for method in METHODS}
    for row in peer.stores:
        stores_by_method[row["method"]].append(row)
        assert row["route"] == [BRIDGE]
        assert row["unit"] == UNIT
        assert 1 <= row["count"] <= 2
    assert all(stores_by_method.values())
    for method, rows in stores_by_method.items():
        assert b"".join(bytes.fromhex(row["data_hex"]) for row in rows) == expected[method]
        expected_tags = (
            list(range(len(rows))) if method == "paged"
            else [0x42] if method in ("edlt", "giu", "sgiu", "dali")
            else [0]
        )
        assert [row["tag"] for row in rows] == expected_tags
    assert peer.nvm_executes == len(METHODS)
    assert peer.noise_frames > 300
    assert {row["unit"] for row in peer.requests} == {UNIT}
    assert {tuple(row["route"]) for row in peer.requests} == {(BRIDGE,)}
    assert len({row["connection"] for row in peer.wire_log}) == 1
    assert set(results) == set(METHODS)


@pytest.mark.skipif(not BIN.exists(), reason="Build cmqttd before cross-language interop")
def test_routed_programming_rejects_excess_correlated_readback_before_any_save(tmp_path):
    project, specs = _fixture(tmp_path, all_methods=False)
    peer = RoutedProgrammingPCI(overflow_on_first_recall=True)
    with peer.running() as pci, _running_daemon(tmp_path, pci, project, specs) as port:
        result = _invoke(port, "direct", b"\xD0\xD1")
    assert result.returncode == 1
    error = json.loads(result.stderr)
    evidence = error["physical_programming_evidence"]
    assert evidence["phase"].startswith("physical-load")
    assert not evidence["save_attempted"]
    assert not peer.stores
    assert peer.overflow_sent


@pytest.mark.skipif(not BIN.exists(), reason="Build cmqttd before cross-language interop")
def test_routed_programming_disconnect_after_store_is_uncertain_and_never_replayed(tmp_path):
    project, specs = _fixture(tmp_path, all_methods=False)
    peer = RoutedProgrammingPCI(drop_on_method="direct")
    with peer.running() as pci, _running_daemon(tmp_path, pci, project, specs) as port:
        result = _invoke(port, "direct", b"\xE0\xE1")
    assert result.returncode == 1
    error = json.loads(result.stderr)
    evidence = error["physical_programming_evidence"]
    assert evidence["save_attempts"] == 1
    assert evidence["save_attempted"]
    assert evidence["save_outcome_uncertain"]
    direct_stores = [row for row in peer.stores if row["method"] == "direct"]
    assert len(direct_stores) == 1
    assert direct_stores[0]["data_hex"] == "E0E1"
    assert peer.dropped
