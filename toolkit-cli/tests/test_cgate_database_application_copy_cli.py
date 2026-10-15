"""Issue #124: typed Application copy emits DBGETXML preread + DBCOPYSAFE on one connection.

The complete subtree duplication lives server-side; the typed workflow
(`NativeDatabase.copy` / `cbus-toolkit cgate database copy`) must read the
source XML and send the admitted SAFE copy verbatim on the same selected
connection, returning the native 301 OID receipt without reconnect or replay.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
import socket
import socketserver
import subprocess
import sys
import threading
import time


APP_XML = (
    "<Application><OID>33333333-3333-4333-8333-333333333333</OID>"
    "<TagName>Src70</TagName><Address>70</Address></Application>"
)
NEW_OID = "44444444-4444-4444-8444-444444444444"


@contextmanager
def scripted_peer(responses):
    """Record every accepted connection, including any erroneous reconnect."""
    state = {"connections": [], "errors": []}
    lock = threading.Lock()
    workers = []

    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            self.connection.settimeout(2)
            with lock:
                sent = []
                state["connections"].append(sent)
                workers.append(threading.current_thread())
            try:
                self.connection.sendall(b"201 Service ready: fixture\r\n")
                while command := self.rfile.readline():
                    sent.append(command)
                    index = len(sent) - 1
                    if index >= len(responses):
                        tag = command.partition(b"]")[0] + b"]"
                        self.connection.sendall(tag + b" 400 Unexpected command\r\n")
                        continue
                    for fragment in responses[index]:
                        if fragment is None:
                            self.connection.shutdown(socket.SHUT_WR)
                            return
                        if isinstance(fragment, float):
                            time.sleep(fragment)
                        else:
                            self.connection.sendall(fragment)
            except (BrokenPipeError, ConnectionResetError, socket.timeout):
                pass
            except BaseException as error:
                state["errors"].append(error)

    class Server(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True

    server = Server(("127.0.0.1", 0), Handler)
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": .01}, daemon=True,
    )
    thread.start()
    try:
        yield server.server_address, state
    finally:
        time.sleep(.02)
        server.shutdown()
        server.server_close()
        thread.join(2)
        for worker in workers:
            worker.join(2)
            assert not worker.is_alive()
        assert not state["errors"], state["errors"]


def invoke(endpoint, arguments, *, project="LAB", expected=0):
    command = [
        sys.executable, "-m", "cbus_toolkit", "cgate", "--host", endpoint[0],
        "--port", str(endpoint[1]), "--timeout", ".1", "database", *map(str, arguments),
    ]
    if project is not None:
        command += ["--project", project]
    result = subprocess.run(command, capture_output=True, text=True, timeout=15)
    assert result.returncode == expected, result.stdout + result.stderr
    return json.loads(result.stdout or result.stderr)


def reply(tag, terminal):
    return [f"[{tag}] {terminal}\r\n".encode()]


def xml_reply(tag, document=APP_XML):
    return [f"[{tag}] 347-{document}\n[{tag}] 344 End XML snippet\r\n".encode()]


def assert_one_connection(state, commands):
    assert state["connections"] == [[
        f"[{index}] {command}\r\n".encode() for index, command in enumerate(commands, 1)
    ]]


def test_application_copy_sends_preread_and_safe_copy_on_one_connection():
    arguments = ["copy", "//LAB/254/70", "//LAB/254", "72", "Copy70"]
    commands = [
        "DBGETXML //LAB/254/70",
        "DBCOPYSAFE //LAB/254/70 //LAB/254 72 Copy70",
    ]
    responses = [xml_reply(2), reply(3, f"301 OID={NEW_OID}")]
    with scripted_peer([reply(1, "200 OK."), *responses]) as (endpoint, state):
        result = invoke(endpoint, arguments)
    assert NEW_OID in json.dumps(result)
    assert_one_connection(state, ["PROJECT USE LAB", *commands])


def test_application_copy_conflict_is_reported_without_reconnect_or_replay():
    arguments = ["copy", "//LAB/254/70", "//LAB/254", "71", "Clash71"]
    commands = [
        "DBGETXML //LAB/254/70",
        "DBCOPYSAFE //LAB/254/70 //LAB/254 71 Clash71",
    ]
    responses = [xml_reply(2), reply(3, "409 Application already exists")]
    with scripted_peer([reply(1, "200 OK."), *responses]) as (endpoint, state):
        error = invoke(endpoint, arguments, expected=1)
    assert "error" in error
    assert_one_connection(state, ["PROJECT USE LAB", *commands])


def test_application_copy_lost_success_does_not_reconnect():
    # A dropped connection after the copy receipt is a lost success: the CLI
    # must surface the transport failure without opening a second connection
    # or replaying DBCOPYSAFE.
    arguments = ["copy", "//LAB/254/70", "//LAB/254", "72", "Copy70"]
    commands = [
        "DBGETXML //LAB/254/70",
        "DBCOPYSAFE //LAB/254/70 //LAB/254 72 Copy70",
    ]
    responses = [xml_reply(2), [None]]
    with scripted_peer([reply(1, "200 OK."), *responses]) as (endpoint, state):
        error = invoke(endpoint, arguments, expected=1)
    assert "error" in error
    assert_one_connection(state, ["PROJECT USE LAB", *commands])
