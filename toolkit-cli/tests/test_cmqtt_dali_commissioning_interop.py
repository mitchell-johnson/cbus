"""Typed Python DALI commissioning over the real cmqttd PCI service.

Every endpoint is an ephemeral loopback socket. Typed ECG replies use the
retained native commissioning fixture; FULL's status/identifier replies and
paged memory are explicitly synthetic. These tests establish the
production tagged client, typed workflow and daemon integration, not actual
DALI ballast state, persistence or physical acceptance.
"""
from contextlib import contextmanager
import json
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time

import pytest

from cbus_toolkit.cgate import CGateClient, CGateError
from cbus_toolkit.simulator import PCISimulator, UnitState, synthetic_units
from test_cmqtt_programming_methods_interop import (
    BIN, running_daemon, wait_until_ready,
)


ROOT = Path(__file__).resolve().parents[2]
TARGET = "//TEST/254/p/20"
MINIMUM_PATH = "/cdg/daliLines/0/daliEcgs/3/commonParams102/minimumLevel"
NATIVE = json.loads((ROOT / "rust/testdata/fixtures/native_cgate_dali_commissioning.json")
                    .read_text(encoding="utf-8"))
pytestmark = pytest.mark.skipif(BIN is None, reason="Build cmqttd before cross-language DALI interop")


class ScriptedDaliPCI(PCISimulator):
    """Literal CAL peer with fixture typed replies and synthetic paged memory."""

    def __init__(self, *, fail_operation=None, drop_operation=None):
        pci = synthetic_units()[2]
        gateway = UnitState(20, {1: b"SYS_DAL2", 2: b"1.10.0  "}, {}, mmi_state=1)
        super().__init__([pci, gateway], local_unit=16, profile="synthetic")
        self.fail_operation = fail_operation
        self.drop_operation = drop_operation
        self.exchanges = []
        self.replies = json.loads(json.dumps(NATIVE["gateway_script"]["ecg_replies"]))
        self.extended_memory = {}
        self.peer_socket = None
        self.lost_reply = threading.Event()

    def _connection(self, conn, connection, shutdown):
        self.peer_socket = conn
        return super()._connection(conn, connection, shutdown)

    def _command(self, line, context):
        if line in (b"~", b"A32100FF", b"A32200FF", b"A342000E", b"A3300079"):
            return b"", None
        code = line[-1:] if line and ord("g") <= line[-1] <= ord("z") else b""
        raw = line[:-1] if code else line
        explicit = raw.startswith(b"\\")
        text = raw[1:] if explicit else raw
        try:
            payload = bytes.fromhex(text.decode("ascii"))
        except ValueError:
            return super()._command(line, context)
        packet = payload if explicit or context["header"] is None else context["header"] + payload
        ack = code + b"." if code else b""
        if len(packet) == 7 and packet[:4] == bytes([0x46, 20, 0, 0x1B]):
            if explicit:
                context["header"] = packet[:3]
            page, parameter, count = packet[4:7]
            self.exchanges.append({"kind": "paged_recall", "packet": packet.hex().upper(),
                                   "address": 256 * page + parameter, "count": count})
            frames = b"".join(self._reply(bytes([0x86, 20, 16, 0,
                0x80 | (min(16, count - offset) + 1), (parameter + offset) & 255])
                + bytes(self.extended_memory.get(256 * page + parameter + index, 0)
                        for index in range(offset, min(offset + 16, count))))
                for offset in range(0, count, 16))
            return ack + frames, None
        if len(packet) == 5 and packet[:4] == bytes([0x46, 20, 0, 0x39]):
            if explicit:
                context["header"] = packet[:3]
            context["page"] = packet[4]
            self.exchanges.append({"kind": "page_select", "packet": packet.hex().upper(),
                                   "page": packet[4]})
            return ack + self._reply(bytes([0x86, 20, 16, 0, 0x81, packet[4]])), None
        if (len(packet) >= 8 and packet[:3] == bytes([0x46, 20, 0])
                and packet[3] & 0xF0 == 0xA0):
            # Literal native page-selected, tagged, checksummed CAL STORE.
            # Refuse a malformed request rather than interpreting its checksum
            # as memory data or acknowledging a different parameter/tag.
            count = packet[3] & 15
            assert len(packet) == count + 5 and sum(packet) & 255 == 0, packet.hex()
            assert "page" in context, "STORE arrived before its page selection"
            if explicit:
                context["header"] = packet[:3]
            parameter, tag, data = packet[4], packet[5], packet[6:-1]
            address = 256 * context["page"] + parameter
            assert parameter + len(data) <= 256, "STORE crossed a page"
            for index, value in enumerate(data):
                self.extended_memory[address + index] = value
            self.exchanges.append({"kind": "paged_store", "packet": packet.hex().upper(),
                                   "address": address, "tag": tag, "data": data.hex().upper()})
            return ack + self._reply(bytes([0x86, 20, 16, 0, 0x32, parameter, tag])), None
        if len(packet) >= 7 and packet[:3] == bytes([6, 20, 0]) and packet[5] == 0xDA:
            if explicit:
                context["header"] = packet[:3]
            cal = packet[3:]
            operation = cal[3] & 127
            script = NATIVE["gateway_script"]
            data = b""
            if operation == 13:
                data = bytes.fromhex(script["check_for_unknown_data_hex"])
            elif operation in script["known_mask_operations"]:
                data = bytes.fromhex(script["known_mask_hex"])
            elif operation == 2:
                data = bytes.fromhex(script["address_unknown_default_mask_hex"])
            elif operation in script["empty_mask_operations"]:
                data = bytes(8)
            elif operation in (26, 27) and len(cal) > 4:
                # These documented status-only discoveries echo the ECG.
                data = bytes([cal[4]])
            elif operation in (21, 22) and len(cal) > 4:
                # Synthetic GTIN/serial bytes exercise FULL's exact lengths.
                data = bytes([cal[4]]) + bytes(6 if operation == 21 else 8)
            elif len(cal) > 4:
                text = self.replies.get(str(cal[4]), {}).get(str(operation), "")
                data = bytes.fromhex(text)
            status = 4 if operation == self.fail_operation else 0
            if status:
                data = b""
            elif operation == 32 and len(cal) == 11:
                # Common reads contain two scene-membership bytes which the
                # setter does not own. Retain them while applying its six
                # common fields, so a later recovery sees the scripted write.
                old = bytes.fromhex(self.replies[str(cal[4])]["17"])
                self.replies[str(cal[4])]["17"] = bytes(
                    [cal[4], *cal[5:7], *old[3:5], *cal[7:11]]).hex().upper()
            self.exchanges.append({"kind": "dali", "packet": packet.hex().upper(),
                "mode": cal[1], "operation": cal[3], "payload": cal[4:].hex().upper(),
                "status": status, "data": data.hex().upper()})
            if operation == self.drop_operation:
                # The setter reached the peer. Its acceptance reply is lost;
                # the workflow must retain uncertainty and must not repeat it.
                self.lost_reply.set()
                self.peer_socket.shutdown(socket.SHUT_RDWR)
                return b"", None
            reply = bytes([0x86, 20, 16, 0, 0xE4 + len(data), 0x83, 0xDA,
                           cal[3], status]) + data
            return ack + self._reply(reply), None
        return super()._command(line, context)

    @property
    def setters(self):
        return [row for row in self.exchanges if row["kind"] == "dali"
                and row["operation"] & 127 in (32, 34, 35, 38, 40)]


@contextmanager
def service(tmp_path, peer):
    project = tmp_path / "project.xml"
    project.write_text(
        '<Installation><Project><TagName>TEST</TagName><Network><Address>254</Address>'
        '<TagName>Fixture</TagName><Interface><InterfaceType>CNI</InterfaceType>'
        '<InterfaceAddress>127.0.0.1:10001</InterfaceAddress></Interface>'
        '<Application><Address>56</Address><TagName>Lighting</TagName>'
        '<Group><Address>1</Address><TagName>Fixture light</TagName></Group></Application>'
        '<Unit><Address>20</Address><TagName>Synthetic DALI gateway</TagName>'
        '<UnitType>SYS_DAL2</UnitType><FirmwareVersion>1.10.0</FirmwareVersion></Unit>'
        '</Network></Project></Installation>', encoding="utf-8")
    specs = tmp_path / "unitspec"
    specs.mkdir(exist_ok=True)
    with peer.running() as pci, running_daemon(tmp_path, pci, project, specs) as port:
        wait_until_ready(port)
        yield int(port)


def invoke(port, *args):
    return subprocess.run([sys.executable, "-m", "cbus_toolkit", "cgate",
        "--host", "127.0.0.1", "--port", str(port), "--timeout", "30",
        "dali", *args], capture_output=True, text=True, timeout=90)


def native_setters():
    return [row for row in NATIVE["cases"]["deploy_dali_only"]["exchanges"]
            if row["kind"] == "dali"]


def assert_receipt_boundary(document):
    assert document["format"] == "cbus-dali-commissioning-v1"
    assert document["automatic_retries"] == 0
    assert document["physical_effect_verified"] is False
    assert document["persistence_verified"] is False


@pytest.mark.parametrize("extract_type", ["DALI_ONLY", "FULL", "REFRESH_STATUS_INFO", "RETRIEVE_RECONCILE"])
def test_typed_cli_extracts_native_model_without_dali_configuration_writes(tmp_path, extract_type):
    peer = ScriptedDaliPCI()
    with service(tmp_path, peer) as port:
        args = ["extract", TARGET, "--extract-type", extract_type]
        if extract_type in ("REFRESH_STATUS_INFO", "RETRIEVE_RECONCILE"):
            args += ["--seed-extract", "DALI_ONLY"]
        result = invoke(port, *args)
        assert result.returncode == 0, result.stderr
        document = json.loads(result.stdout)
        assert_receipt_boundary(document)
        assert document["complete"]
        assert not document["deploy_attempted"]
        ecgs = document["model"]["cdg"]["daliLines"][0]["daliEcgs"]
        assert ecgs[3]["commonParams102"]["minimumLevel"] == 1
        assert ecgs[3]["deviceTypes"]["deviceTypes"] == ["EMERGENCY"]
        assert ecgs[5]["ledParams207"]["dimmCurve"] == "LINEAR"
        assert not peer.setters
        assert all(row["operation"] & 127 != 2 for row in peer.exchanges if row["kind"] == "dali")
        # The CLI retains tagged multi-line replies without status/debug rows
        # accidentally ending the production C-Gate exchange.
        extract = [row for row in document["receipts"] if " SESSION EXTRACT " in row["command"]]
        assert len(extract) == (2 if "--seed-extract" in args else 1)
        assert all(row["status"] == 200 for row in extract)
        assert any(line.startswith("120-progress:") for line in extract[-1]["lines"])
        if extract_type == "DALI_ONLY":
            assert "120-progress: 15/15, plan: GET_EMERGENCY_STATUS_ECG" in extract[0]["lines"]


@pytest.mark.parametrize("deploy_type", ["DALI_ONLY", "FULL"])
def test_typed_api_deploy_matches_native_setter_order_and_retains_both_journals(tmp_path, deploy_type):
    from cbus_toolkit.dali_commissioning import DaliCommissioning
    peer = ScriptedDaliPCI()
    journal = tmp_path / "operator-journal.json"
    with service(tmp_path, peer) as port:
        with CGateClient("127.0.0.1", port, timeout=30) as client:
            document = DaliCommissioning(client).deploy(
                TARGET, [{"path": MINIMUM_PATH, "value": 7}],
                deploy_type=deploy_type, journal=journal)
            assert_receipt_boundary(document)
            assert document["complete"] and document["deploy_attempted"]
            assert not document["outcome_uncertain"]
            # A later command on this same tagged connection still parses.
            assert client.command("NOOP").status == 200
        expected = json.loads(json.dumps(native_setters()))
        expected[0]["payload"] = "03010207FEFDC8"
        assert [(row["operation"], row["payload"]) for row in peer.setters] == [
            (row["operation"], row["payload"]) for row in expected]
        saved = json.loads(journal.read_text(encoding="utf-8"))
        assert saved["complete"] and saved["automatic_retries"] == 0
        daemon_journals = list((tmp_path / "state.json.dali-journal").glob("*.json"))
        assert len(daemon_journals) == 1
        native = json.loads(daemon_journals[0].read_text(encoding="utf-8"))
        assert native["state"] == "complete"
        assert native["confirmed_writes"] == 8
        assert [row["payload_hex"] for row in native["planned"]] == [row["payload"] for row in expected]
        assert peer.replies["3"]["17"] == "030102010207FEFDC8"


def test_typed_cli_dry_run_reads_and_stages_but_never_deploys(tmp_path):
    peer = ScriptedDaliPCI()
    edits = tmp_path / "edits.json"
    edits.write_text(json.dumps([{"path": "/cdg/daliLines/0/daliEcgs/3/commonParams102/minimumLevel",
                                  "value": 7}]), encoding="utf-8")
    with service(tmp_path, peer) as port:
        result = invoke(port, "deploy", TARGET, "--edits", str(edits), "--dry-run")
        assert result.returncode == 0, result.stderr
        document = json.loads(result.stdout)
        assert_receipt_boundary(document)
        assert not document["deploy_attempted"]
        assert document["model"]["cdg"]["daliLines"][0]["daliEcgs"][3]["commonParams102"]["minimumLevel"] == 7
        assert not peer.setters
        assert not (tmp_path / "state.json.dali-journal").exists()


def test_typed_cli_ext_only_extraction_reads_complete_gateway_memory_without_writes(tmp_path):
    peer = ScriptedDaliPCI()
    peer.extended_memory.update({256: 0x12, 11375: 0x34})
    with service(tmp_path, peer) as port:
        result = invoke(port, "extract", TARGET, "--extract-type", "EXT_ONLY")
        assert result.returncode == 0, result.stderr
        document = json.loads(result.stdout)
        assert_receipt_boundary(document)
        assert document["complete"] and not document["deploy_attempted"]
        values = document["model"]["extParams"]["values"]
        assert len(values) == 11376 - 256
        assert values["256"] == 0x12 and values["11375"] == 0x34
        assert all(row["kind"] == "paged_recall" for row in peer.exchanges)


def test_typed_api_ext_only_deploy_stores_changed_bytes_once_and_verifies_readback(tmp_path):
    from cbus_toolkit.dali_commissioning import DaliCommissioning
    peer = ScriptedDaliPCI()
    journal = tmp_path / "extended-attempt.json"
    with service(tmp_path, peer) as port:
        with CGateClient("127.0.0.1", port, timeout=30) as client:
            document = DaliCommissioning(client).deploy(
                TARGET, [{"address": 256, "bytes": [0xAA, 0xBB]}],
                extract_type="EXT_ONLY", deploy_type="EXT_ONLY", journal=journal)
        assert_receipt_boundary(document)
        assert document["complete"] and document["deploy_attempted"]
        assert not document["outcome_uncertain"]
        stores = [row for row in peer.exchanges if row["kind"] == "paged_store"]
        assert len(stores) == 1
        assert stores[0]["address"] == 256 and stores[0]["tag"] == 0
        assert stores[0]["data"] == "AABB"
        assert peer.extended_memory == {256: 0xAA, 257: 0xBB}
        values = document["model"]["extParams"]["values"]
        assert [values[str(address)] for address in (256, 257)] == [0xAA, 0xBB]
        store_index = peer.exchanges.index(stores[0])
        assert peer.exchanges[store_index - 1]["kind"] == "page_select"
        readback = peer.exchanges[store_index + 1]
        assert readback["kind"] == "paged_recall"
        assert readback["address"] == 256 and readback["count"] == 2
        assert not peer.setters
        assert json.loads(journal.read_text(encoding="utf-8"))["complete"]


def test_conditional_extract_requires_address_assignment_consent_before_gateway_io(tmp_path):
    peer = ScriptedDaliPCI()
    with service(tmp_path, peer) as port:
        result = invoke(port, "extract", TARGET, "--extract-type", "COND_QUICK")
        assert result.returncode != 0
        assert "address" in result.stderr.lower()
        assert not peer.exchanges


@pytest.mark.parametrize("extract_type", ["COND_QUICK", "COND_EXTENDED", "RESCAN_FAULT"])
def test_typed_api_conditional_extract_assigns_addresses_once_and_journals_it(tmp_path, extract_type):
    from cbus_toolkit.dali_commissioning import DaliCommissioning
    peer = ScriptedDaliPCI()
    journal = tmp_path / "address-assignment.json"
    with service(tmp_path, peer) as port:
        with CGateClient("127.0.0.1", port, timeout=30) as client:
            document = DaliCommissioning(client).extract(
                TARGET, extract_type=extract_type, seed_extract="DALI_ONLY",
                allow_address_assignment=True, journal=journal)
        assert_receipt_boundary(document)
        assert document["complete"]
        writes = [row for row in peer.exchanges if row["kind"] == "dali" and row["operation"] & 127 == 2]
        assert len(writes) == 1 and writes[0]["payload"] == ""
        assert document["model"]["cdg"]["daliLines"][0]["daliEcgs"][3]["isAddressKnown"]
        assert not peer.setters
        assert json.loads(journal.read_text(encoding="utf-8"))["complete"]
        daemon_journals = list((tmp_path / "state.json.dali-journal").glob("*.json"))
        assert len(daemon_journals) == 1
        native = json.loads(daemon_journals[0].read_text(encoding="utf-8"))
        assert native["state"] == "complete" and native["confirmed_writes"] == 1
        assert native["planned"][0]["operation"] == 2


@pytest.mark.parametrize("fault", ["definite", "lost-reply"])
def test_typed_deploy_stops_after_first_fault_without_replay_or_later_writes(tmp_path, fault):
    from cbus_toolkit.dali_commissioning import DaliCommissioning
    peer = ScriptedDaliPCI(fail_operation=34 if fault == "definite" else None,
                           drop_operation=34 if fault == "lost-reply" else None)
    journal = tmp_path / "failed-operator-journal.json"
    with service(tmp_path, peer) as port:
        with CGateClient("127.0.0.1", port, timeout=10) as client:
            with pytest.raises((CGateError, RuntimeError)) as failure:
                DaliCommissioning(client).deploy(
                    TARGET, [{"path": MINIMUM_PATH, "value": 1}], journal=journal)
            document = failure.value.dali_commissioning_evidence
            assert_receipt_boundary(document)
            assert document["deploy_attempted"] and not document["complete"]
            assert document["outcome_uncertain"] is (fault == "lost-reply")
            if fault == "definite":
                assert failure.value.response.status == 502
                assert "FAIL_INVALID_COMMAND" in failure.value.response.final
                assert client.command("NOOP").status == 200
            else:
                assert peer.lost_reply.is_set()
            snapshot = list(peer.setters)
            time.sleep(0.2)
            assert peer.setters == snapshot
        assert [(row["operation"], row["payload"]) for row in peer.setters] == [
            (row["operation"], row["payload"]) for row in native_setters()[:3]]
        saved = json.loads(journal.read_text(encoding="utf-8"))
        assert saved["complete"] is False
        assert saved["outcome_uncertain"] is (fault == "lost-reply")
        assert saved["automatic_retries"] == 0


def test_lost_reply_recovery_freshly_reads_confirmed_common_edit_without_replaying(tmp_path):
    from cbus_toolkit.dali_commissioning import DaliCommissioning
    peer = ScriptedDaliPCI(drop_operation=34)
    journal = tmp_path / "uncertain-attempt.json"
    with service(tmp_path, peer) as port:
        with CGateClient("127.0.0.1", port, timeout=10) as client:
            with pytest.raises((CGateError, RuntimeError)) as failure:
                DaliCommissioning(client).deploy(
                    TARGET, [{"path": MINIMUM_PATH, "value": 7}], journal=journal)
            assert failure.value.dali_commissioning_evidence["outcome_uncertain"]
    before = journal.read_bytes()
    sent = list(peer.setters)
    peer.drop_operation = None
    with service(tmp_path, peer) as port:
        result = invoke(port, "recover", "--journal", str(journal))
        assert result.returncode == 0, result.stderr
        document = json.loads(result.stdout)
        assert document["format"] == "cbus-dali-recovery-v1"
        assert document["classification"] == "expected"
        assert document["conclusive"]
        assert not document["writes_attempted"]
        assert not document["attempt_replay_authorized"]
        assert document["automatic_retries"] == 0
        assert not document["persistence_verified"]
        assert document["observations"][0]["observed"] == 7
        assert peer.setters == sent
        assert journal.read_bytes() == before
