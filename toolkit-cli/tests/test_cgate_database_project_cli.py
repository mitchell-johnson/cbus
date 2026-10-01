"""Selected database operations through actual CLI subprocesses and tagged peers."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import socket
import socketserver
import subprocess
import sys
import threading
import time

import pytest


SOURCE_OID = "11111111-1111-4111-8111-111111111111"
NEW_OID = "22222222-2222-4222-8222-222222222222"
GROUP_XML = (
    f"<Group><OID>{SOURCE_OID}</OID><TagName>Lamp</TagName>"
    "<Address>1</Address></Group>"
)
LEVEL_XML = f"<Level Value=\"7\"><OID>{SOURCE_OID}</OID><Address>7</Address></Level>"
ACTIONS = ("get", "set", "add", "copy", "delete", "validate")


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
        # Drain a queued reconnect before inspecting connection cardinality.
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


def xml_reply(tag, document=GROUP_XML):
    return [f"[{tag}] 347-{document}\n[{tag}] 344 End XML snippet\r\n".encode()]


def scalar_case(action, first_tag):
    cases = {
        "get": (["get", "//LAB/CustomA/TagName"], ["DBGET //LAB/CustomA/TagName"],
                [reply(first_tag, "342 CustomA/TagName=nCustomA")]),
        "set": (["set", f"!{SOURCE_OID}/TagName", "Edited name"],
                [f"DBSETSAFE !{SOURCE_OID}/TagName Edited name"], [reply(first_tag, "200 OK.")]),
        "add": (["add", "//LAB/CustomA", "application", "56", "Lighting"],
                ["DBADDSAFE //LAB/CustomA Application 56 Lighting"],
                [reply(first_tag, f"301 OID={NEW_OID}")]),
        "copy": (["copy", f"!{SOURCE_OID}", "//LAB/CustomA/56", "2", "Copied group"],
                 [f"DBGETXML !{SOURCE_OID}",
                  f"DBCOPYSAFE !{SOURCE_OID} //LAB/CustomA/56 2 Copied group"],
                 [xml_reply(first_tag), reply(first_tag + 1, f"301 OID={NEW_OID}")]),
        "delete": (["delete", f"!{SOURCE_OID}"], [f"DBDELETE !{SOURCE_OID}"],
                   [reply(first_tag, "200 OK.")]),
        "validate": (["validate", "//LAB/CustomA"], ["DBVALIDATE //LAB/CustomA"],
                     [reply(first_tag, "233 Network: Valid")]),
    }
    return cases[action]


def assert_one_connection(state, commands):
    assert state["connections"] == [[
        f"[{index}] {command}\r\n".encode() for index, command in enumerate(commands, 1)
    ]]


@pytest.mark.parametrize("action", ACTIONS)
def test_selected_leaf_uses_one_connection_before_every_database_command(action):
    arguments, commands, responses = scalar_case(action, 2)
    with scripted_peer([reply(1, "200 OK."), *responses]) as (endpoint, state):
        invoke(endpoint, arguments)
    assert_one_connection(state, ["PROJECT USE LAB", *commands])


@pytest.mark.parametrize("action", ACTIONS)
def test_omitted_project_keeps_existing_wire_and_path_behavior(action):
    arguments, commands, responses = scalar_case(action, 1)
    with scripted_peer(responses) as (endpoint, state):
        invoke(endpoint, arguments, project=None)
    assert_one_connection(state, commands)


@pytest.mark.parametrize("action", ACTIONS)
def test_selection_does_not_rewrite_another_projects_qualified_path_or_oid(action):
    arguments, commands, responses = scalar_case(action, 2)
    with scripted_peer([reply(1, "200 OK."), *responses]) as (endpoint, state):
        invoke(endpoint, arguments, project="OTHER")
    assert_one_connection(state, ["PROJECT USE OTHER", *commands])


@pytest.mark.parametrize("operation", ("add", "copy"))
def test_level_completion_uses_issued_oid_on_the_selected_connection(operation):
    if operation == "add":
        arguments = ["add", "//LAB/CustomA/56/1", "level", "8", "Reading"]
        commands = ["DBADDSAFE //LAB/CustomA/56/1 Level 8 Reading"]
        responses = [reply(2, f"301 OID={NEW_OID}")]
        identity_tag = 3
    else:
        arguments = ["copy", f"!{SOURCE_OID}", "//LAB/CustomA/56/1", "8", "Reading"]
        commands = [f"DBGETXML !{SOURCE_OID}",
                    f"DBCOPYSAFE !{SOURCE_OID} //LAB/CustomA/56/1 8 Reading"]
        responses = [xml_reply(2, LEVEL_XML), reply(3, f"301 OID={NEW_OID}")]
        identity_tag = 4
    commands += [f"DBGET !{NEW_OID}/OID", f"DBSETSAFE !{NEW_OID}/Value 8"]
    responses += [reply(identity_tag, f"342 !{NEW_OID}/OID={NEW_OID}"),
                  reply(identity_tag + 1, "200 OK.")]
    with scripted_peer([reply(1, "200 OK."), *responses]) as (endpoint, state):
        invoke(endpoint, arguments)
    assert_one_connection(state, ["PROJECT USE LAB", *commands])


@pytest.mark.parametrize("selection", [
    reply(1, "401 Refused"), reply(1, "440 No tag database"), reply(1, "501 Unavailable"),
    reply(1, "600 Confirmation required"), reply(1, "201 Unexpected success"),
    reply(1, "301 OID=" + NEW_OID), reply(1, "233 Unexpected success"),
    reply(9, "200 Wrong command tag"), [b"[1] 200 Truncated", None], [None], [.3],
], ids=["refused", "no-database", "unavailable", "confirmation", "unknown-success",
        "created", "validation", "wrong-tag", "truncated", "lost", "timeout"])
def test_selection_failure_stops_copy_preread_and_mutation_without_reconnect(selection):
    arguments, _, _ = scalar_case("copy", 2)
    with scripted_peer([selection]) as (endpoint, state):
        error = invoke(endpoint, arguments, expected=1)
    assert "error" in error
    assert_one_connection(state, ["PROJECT USE LAB"])


@pytest.mark.parametrize("action", ("set", "add", "copy", "delete"))
def test_lost_mutation_reply_never_replays_selection_or_mutation(action):
    arguments, commands, responses = scalar_case(action, 2)
    responses[-1] = [None]
    with scripted_peer([reply(1, "200 OK."), *responses]) as (endpoint, state):
        error = invoke(endpoint, arguments, expected=1)
    assert "outcome may be unknown" in error["error"]
    assert_one_connection(state, ["PROJECT USE LAB", *commands])


@pytest.mark.parametrize("operation", ("add", "copy"))
def test_lost_level_value_reply_cannot_send_cleanup_on_a_new_connection(operation):
    if operation == "add":
        arguments = ["add", "//LAB/CustomA/56/1", "level", "8", "Reading"]
        commands = ["DBADDSAFE //LAB/CustomA/56/1 Level 8 Reading"]
        responses = [reply(2, f"301 OID={NEW_OID}")]
        identity_tag = 3
    else:
        arguments = ["copy", f"!{SOURCE_OID}", "//LAB/CustomA/56/1", "8", "Reading"]
        commands = [f"DBGETXML !{SOURCE_OID}",
                    f"DBCOPYSAFE !{SOURCE_OID} //LAB/CustomA/56/1 8 Reading"]
        responses = [xml_reply(2, LEVEL_XML), reply(3, f"301 OID={NEW_OID}")]
        identity_tag = 4
    commands += [f"DBGET !{NEW_OID}/OID", f"DBSETSAFE !{NEW_OID}/Value 8"]
    responses += [reply(identity_tag, f"342 !{NEW_OID}/OID={NEW_OID}"), [None]]
    with scripted_peer([reply(1, "200 OK."), *responses]) as (endpoint, state):
        error = invoke(endpoint, arguments, expected=1)
    assert "outcome may be unknown" in error["error"]
    assert_one_connection(state, ["PROJECT USE LAB", *commands])


def xml_arguments(action, tmp_path):
    if action == "get-xml":
        return [action, f"!{SOURCE_OID}", "--output", tmp_path / "export.xml"]
    source = tmp_path / "source.xml"
    source.write_text(GROUP_XML + "\n", encoding="utf-8")
    return [action, f"!{SOURCE_OID}", source]


@pytest.mark.parametrize("action", (*ACTIONS, "get-xml", "set-xml"))
@pytest.mark.parametrize("project", ("", "LAB\nSHUTDOWN"), ids=("empty", "injection"))
def test_invalid_selected_project_is_rejected_before_any_socket(action, project, tmp_path):
    arguments = (xml_arguments(action, tmp_path) if action.endswith("xml")
                 else scalar_case(action, 2)[0])
    with scripted_peer([]) as (endpoint, state):
        error = invoke(endpoint, arguments, project=project, expected=1)
    assert "project" in error["error"].lower()
    assert state["connections"] == []


@pytest.mark.parametrize("project", ("NINECHARS", "../LAB", "LAB TWO"))
def test_invalid_project_length_path_or_whitespace_is_preconnection(project):
    with scripted_peer([]) as (endpoint, state):
        invoke(endpoint, ["get", "//LAB/CustomA/TagName"], project=project, expected=1)
    assert state["connections"] == []


def test_existing_xml_export_selects_once_and_preserves_exact_file_bytes(tmp_path):
    with scripted_peer([reply(1, "200 OK."), xml_reply(2)]) as (endpoint, state):
        result = invoke(endpoint, xml_arguments("get-xml", tmp_path))
    assert_one_connection(state, ["PROJECT USE LAB", f"DBGETXML !{SOURCE_OID}"])
    assert (tmp_path / "export.xml").read_bytes() == GROUP_XML.encode()
    assert result["sha256"] == hashlib.sha256(GROUP_XML.encode()).hexdigest()


def test_existing_guarded_xml_replace_and_readback_keep_one_selected_connection(tmp_path):
    arguments = xml_arguments("set-xml", tmp_path)
    arguments += ["--expect-current-sha256", hashlib.sha256(GROUP_XML.encode()).hexdigest(),
                  "--readback"]
    responses = [reply(1, "200 OK."), xml_reply(2), [], [],
                 reply(3, f"301 OID={SOURCE_OID}"), xml_reply(4)]
    with scripted_peer(responses) as (endpoint, state):
        result = invoke(endpoint, arguments)
    assert len(state["connections"]) == 1
    sent = state["connections"][0]
    assert sent[:2] == [b"[1] PROJECT USE LAB\r\n", f"[2] DBGETXML !{SOURCE_OID}\r\n".encode()]
    header, delimiter = sent[2].decode().rstrip("\r\n").split(" << ")
    assert header == f"[3] DBSETXML !{SOURCE_OID}"
    assert sent[3:] == [(GROUP_XML + "\n").encode(), (delimiter + "\r\n").encode(),
                        f"[4] DBGETXML !{SOURCE_OID}\r\n".encode()]
    assert result["readback"]["retrieved"]
    assert not result["project_save_requested"]


@pytest.mark.parametrize("action", (*ACTIONS, "get-xml", "set-xml"))
def test_database_project_help_describes_session_and_save_boundary(action):
    result = subprocess.run(
        [sys.executable, "-m", "cbus_toolkit", "cgate", "database", action, "--help"],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stderr
    help_text = " ".join(result.stdout.split())
    assert "--project PROJECT" in help_text
    assert "same C-Gate connection" in help_text
    assert "no project save" in help_text
