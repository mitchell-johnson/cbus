"""Issue #131: numeric Level Value SAFE writes update the ordinary typed owner.

The stateful remap lives server-side; the typed workflow
(`NativeDatabase.set` / `cbus-toolkit cgate database set`) must send the
admitted SAFE selector verbatim on the same selected connection for both the
numeric (`//PROJECT/NET/APP/GROUP/LEVEL/Value`) and issued-OID
(`!OID/Value`) shapes. Raw/out-of-range tails refuse without a reconnect;
missing/foreign shapes never alias.
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


LEVEL_OID = "44444444-4444-4444-8444-444444444444"


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


def test_numeric_level_value_set_sends_safe_selector():
    arguments = ["set", "//LAB/254/80/8/4/Value", "99"]
    commands = ["DBSETSAFE //LAB/254/80/8/4/Value 99"]
    with scripted_peer([reply(1, "200 OK."), reply(2, "200 OK")]) as (endpoint, state):
        invoke(endpoint, arguments)
    assert_one_connection(state, ["PROJECT USE LAB", *commands])


def test_issued_oid_level_value_set_sends_safe_selector():
    arguments = ["set", f"!{LEVEL_OID}/Value", "77"]
    commands = [f"DBSETSAFE !{LEVEL_OID}/Value 77"]
    with scripted_peer([reply(1, "200 OK."), reply(2, "200 OK")]) as (endpoint, state):
        invoke(endpoint, arguments)
    assert_one_connection(state, ["PROJECT USE LAB", *commands])


def test_netvar_level_value_set_sends_safe_selector():
    arguments = ["set", "//LAB/254/56/4/42/Value", "23"]
    commands = ["DBSETSAFE //LAB/254/56/4/42/Value 23"]
    with scripted_peer([reply(1, "200 OK."), reply(2, "200 OK")]) as (endpoint, state):
        invoke(endpoint, arguments)
    assert_one_connection(state, ["PROJECT USE LAB", *commands])


def test_numeric_level_invalid_value_reported_without_reconnect():
    arguments = ["set", "//LAB/254/80/8/4/Value", "oops"]
    commands = ["DBSETSAFE //LAB/254/80/8/4/Value oops"]
    responses = [reply(2, "400 Invalid level value")]
    with scripted_peer([reply(1, "200 OK."), *responses]) as (endpoint, state):
        error = invoke(endpoint, arguments, expected=1)
    assert "error" in error
    assert_one_connection(state, ["PROJECT USE LAB", *commands])


def test_missing_numeric_level_value_reported_without_reconnect():
    arguments = ["set", "//LAB/254/80/8/9/Value", "99"]
    commands = ["DBSETSAFE //LAB/254/80/8/9/Value 99"]
    responses = [reply(2, "401 Bad object or device ID: Ordinary numeric Level has no addressed owner")]
    with scripted_peer([reply(1, "200 OK."), *responses]) as (endpoint, state):
        error = invoke(endpoint, arguments, expected=1)
    assert "error" in error
    assert_one_connection(state, ["PROJECT USE LAB", *commands])
