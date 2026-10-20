"""Issue #125: typed Application readdress emits DBSETSAFE on the selected connection.

The stateful remap itself lives server-side; the typed workflow
(`NativeDatabase.set` / `cbus-toolkit cgate database set`) must send the
admitted SAFE selector verbatim on the same selected connection for both the
numeric (`//PROJECT/NET/APP/Address`) and issued-OID (`!OID/Address`) shapes.

Self-contained scripted-peer helpers mirror `test_cgate_database_project_cli`
(which cannot be imported: cross-module test imports do not resolve here).
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


APP_OID = "33333333-3333-4333-8333-333333333333"


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


def assert_one_connection(state, commands):
    assert state["connections"] == [[
        f"[{index}] {command}\r\n".encode() for index, command in enumerate(commands, 1)
    ]]


def test_application_address_set_sends_numeric_safe_selector():
    arguments = ["set", "//LAB/254/71/Address", "70"]
    commands = ["DBSETSAFE //LAB/254/71/Address 70"]
    with scripted_peer([reply(1, "200 OK."), reply(2, "200 OK")]) as (endpoint, state):
        invoke(endpoint, arguments)
    assert_one_connection(state, ["PROJECT USE LAB", *commands])


def test_application_address_set_sends_issued_oid_safe_selector():
    arguments = ["set", f"!{APP_OID}/Address", "72"]
    commands = [f"DBSETSAFE !{APP_OID}/Address 72"]
    with scripted_peer([reply(1, "200 OK."), reply(2, "200 OK")]) as (endpoint, state):
        invoke(endpoint, arguments)
    assert_one_connection(state, ["PROJECT USE LAB", *commands])


def test_application_address_conflict_is_reported_without_reconnect():
    arguments = ["set", "//LAB/254/70/Address", "66"]
    commands = ["DBSETSAFE //LAB/254/70/Address 66"]
    responses = [reply(2, "408 Operation failed: database Address is already in use")]
    with scripted_peer([reply(1, "200 OK."), *responses]) as (endpoint, state):
        error = invoke(endpoint, arguments, expected=1)
    assert "error" in error
    assert_one_connection(state, ["PROJECT USE LAB", *commands])


def test_application_address_noop_is_accepted_on_one_connection():
    arguments = ["set", "//LAB/254/70/Address", "70"]
    commands = ["DBSETSAFE //LAB/254/70/Address 70"]
    with scripted_peer([reply(1, "200 OK."), reply(2, "200 OK")]) as (endpoint, state):
        invoke(endpoint, arguments)
    assert_one_connection(state, ["PROJECT USE LAB", *commands])
