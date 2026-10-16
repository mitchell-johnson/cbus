"""Literal bulk relay and fault boundaries on owned synthetic loopback peers."""
import time
import threading

import pytest

from cbus_toolkit.cgate import CGateClient, CGateError
from test_cgate import peer
from test_cgate_barcode_database_interop import FaultGate


@pytest.mark.parametrize("mode", ["ordinary", "drop", "change", "refuse"])
def test_bulk_reply_preserves_fault_boundary_and_exact_once(mode):
    continuation = b"".join(f"[1] 315-P{i}=0x0\r\n".encode() for i in range(844))
    terminal = b"[1] 200 OK\r\n"
    response = continuation + terminal
    callbacks = []
    with peer([[response[:57], response[57:]]], connection_timeout=2) as (address, commands):
        with FaultGate(address, "ABSENT" if mode == "ordinary" else "PP SAVE_TO_SOURCE",
                       mode, callback=lambda: callbacks.append(bytes.fromhex(gate.rows[0]["response_hex"]))) as gate:
            begun = time.monotonic()
            with CGateClient(*gate.endpoint, timeout=3) as client:
                if mode == "drop":
                    with pytest.raises(RuntimeError, match="connection ended"):
                        client.command("PP SAVE_TO_SOURCE session")
                elif mode == "refuse":
                    with pytest.raises(CGateError) as failure:
                        client.command("PP SAVE_TO_SOURCE session")
                    assert failure.value.response.status == 408
                else:
                    result = client.command("PP SAVE_TO_SOURCE session")
                    assert result.status == 200
            assert gate.rows[0]["done"].wait(2)
            row = gate.rows[0]
            row["bulk_elapsed_seconds"] = time.monotonic() - begun
            greeting = b"201 Service ready: fixture\r\n"
            assert bytes.fromhex(row["request_hex"]) == b"[1] PP SAVE_TO_SOURCE session\r\n"
            if mode == "refuse":
                assert bytes.fromhex(row["response_hex"]) == greeting + b"[1] 408 Controlled barcode refusal\r\n"
                assert row["forwarded_request_hex"] == ""
            else:
                assert bytes.fromhex(row["forwarded_request_hex"]) == b"[1] PP SAVE_TO_SOURCE session\r\n"
                assert bytes.fromhex(row["backend_response_hex"]) == greeting + response
                assert bytes.fromhex(row["response_hex"]) == greeting + continuation + (b"" if mode == "drop" else terminal)
            if mode == "drop":
                assert bytes.fromhex(row["lost_backend_terminal_hex"]) == terminal
            if mode == "change":
                assert callbacks == [greeting + continuation]
                assert row["controlled_change_completed"]
        assert commands == ([] if mode == "refuse" else [b"[1] PP SAVE_TO_SOURCE session\r\n"])


def test_refused_document_never_reaches_backend():
    with peer([[]], connection_timeout=2) as (address, commands):
        with FaultGate(address, "DBSETXML", "refuse") as gate:
            with CGateClient(*gate.endpoint, timeout=3) as client:
                with pytest.raises(CGateError) as failure:
                    client.command_document("DBSETXML //SYNTH", "<Note>literal</Note>")
                assert failure.value.response.status == 408
            assert gate.rows[0]["done"].wait(2)
            assert gate.rows[0]["forwarded_request_hex"] == ""
            assert gate.matches == 1
        assert commands == []


def test_bulk_chunk_uses_one_reply_send(monkeypatch):
    import test_cgate_barcode_database_interop as helper

    class Socket:
        def __init__(self, chunks):
            self.chunks, self.sent = iter(chunks), []

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def settimeout(self, value):
            pass

        def setsockopt(self, *args):
            pass

        def recv(self, count):
            return next(self.chunks)

        def sendall(self, data):
            self.sent.append(bytes(data))

    greeting = b"201 Service ready: fixture\r\n"
    reply = b"".join(f"[1] 315-P{i}=0x0\r\n".encode() for i in range(844)) + b"[1] 200 OK\r\n"
    caller = Socket([b"[1] PP GET session *\r\n", b""])
    backend = Socket([greeting, reply])
    schedule = iter([backend, caller, backend, caller])
    monkeypatch.setattr(helper.socket, "create_connection", lambda *args, **kwargs: backend)
    monkeypatch.setattr(helper.select, "select", lambda *args: ([next(schedule)], [], []))
    row = {"request_hex": "", "response_hex": "", "done": threading.Event()}
    gate = FaultGate(("127.0.0.1", 1), "ABSENT", "drop")
    gate._relay(caller, row)
    assert caller.sent == [greeting, reply]
    assert backend.sent == [b"[1] PP GET session *\r\n"]
    assert bytes.fromhex(row["backend_response_hex"]) == greeting + reply
    assert row["closed"] and row["done"].is_set() and not gate.errors
