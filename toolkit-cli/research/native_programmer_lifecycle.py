#!/usr/bin/env python3
"""Capture native PROGRAMMER/DEPLOY_QUEUE lifecycle against an isolated KEY4 PCI simulator.

The owned loopback C-Gate 3.4.0.2001 child receives one disposable project
whose only CNI endpoint is this process's ephemeral simulator (the sparse
synthetic KEY4 fixture that ``verify_network.py`` uses for native PP). Real
PP_SET/PP_SAVE programmer instructions are run to completion, interrupted by an
injected simulator no-reply, cancelled, stopped, paused, deleted, queued behind
one another, retried explicitly and finally discarded by a native restart.

Only stable checkpoints are compared: every step either has a deterministic
reply or polls until a named terminal condition. Timestamps, the project name,
OIDs and ports are normalized. Unsolicited instruction replies and
``EVENT_CHANNEL`` notifications are compared as per-scenario multisets because
native delivery crosses threads. No site project, hardware, credentials or
vendor source is retained.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import threading
import time
import uuid

from research.local_cgate import LocalCGate
from research.verify_network import key4_simulator

FORMAT = "cbus-native-programmer-lifecycle-v1"
CHANNELS = ("deploy-queue.updated-entries", "deploy-queue.debug",
            "deploy-queue.started", "deploy-queue.ended")
UNIT_NAME = range(0x2A, 0x30)
TIMESTAMP = re.compile(r'"(createdTime|startedTime|endedTime)":"[^"]+"')


class RestartableLocalCGate(LocalCGate):
    """Terminate and relaunch the same owned child in its own work directory.

    Used once to observe native restart volatility; project files written by
    ``PROJECT SAVE`` survive while every runtime queue is discarded.
    """

    def restart(self):
        process = self.process
        process.terminate()
        try:
            process.wait(timeout=10)
        except Exception:
            process.kill()
            process.wait(timeout=5)
        self.log.close()
        self.process = None
        self._starting = False
        return self.start()


class FaultInjector:
    """Explicit simulator no-reply for STORE requests addressed to unit 4.

    ``after`` STOREs are answered normally once armed; every later STORE (and
    C-Gate's own retransmissions) receives no reply at all, as when a unit
    stops acknowledging mid-save. Other traffic is untouched.
    """

    def __init__(self, simulator):
        self.simulator = simulator
        self.original = simulator._command
        self.armed = None
        self.passed = 0
        self.dropped = 0
        simulator._command = self

    def arm(self, after):
        self.armed, self.passed = after, 0

    def disarm(self):
        self.armed = None

    def __call__(self, line, context):
        if self.armed is not None:
            body = line[:-1] if line and ord("g") <= line[-1] <= ord("z") else line
            try:
                if body.startswith(b"\\"):
                    payload = bytes.fromhex(body[1:].decode())
                elif not body.startswith(b"@") and context["header"] is not None:
                    payload = context["header"] + bytes.fromhex(body.decode())
                else:
                    payload = b""
            except ValueError:
                payload = b""
            if len(payload) > 3 and payload[:2] == b"\x46\x04":
                cal = payload[3:] if payload[2] == 0 else payload[4:]
                if cal and cal[0] & 0xE0 == 0xA0:
                    if self.passed >= self.armed:
                        if body.startswith(b"\\"):
                            context["header"] = payload[:3]
                        self.dropped += 1
                        self.simulator._record(-1, "rejected", line, "injected no-reply")
                        return b"", None
                    self.passed += 1
        return self.original(line, context)


class Connection:
    """Tagged command connection that keeps unsolicited lines separately."""

    def __init__(self, port, label, project):
        self.label, self.project = label, project
        self.socket = socket.create_connection(("127.0.0.1", port), timeout=10)
        self.socket.settimeout(None)
        self.reader = self.socket.makefile("rb")
        self.greeting = self.reader.readline().decode(errors="replace").strip()
        self.lines, self.unsolicited = [], []
        self.condition = threading.Condition()
        threading.Thread(target=self._read, daemon=True).start()
        self.sequence = 0

    def _read(self):
        while True:
            try:
                raw = self.reader.readline()
            except OSError:
                return
            if not raw:
                return
            with self.condition:
                self.lines.append(raw.decode(errors="replace").rstrip("\r\n"))
                self.condition.notify_all()

    def send(self, tag, text, timeout=60):
        self.socket.sendall(f"[{tag}] {text}\r\n".encode())
        prefix, reply = f"[{tag}] ", []
        deadline = time.monotonic() + timeout
        with self.condition:
            while True:
                while not self.lines:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return reply, False
                    self.condition.wait(remaining)
                line = self.lines.pop(0)
                if not line.startswith(prefix):
                    self.unsolicited.append(line)
                    continue
                body = line[len(prefix):]
                reply.append(body)
                if len(body) >= 4 and body[:3].isdigit() and body[3] == " ":
                    return reply, True

    def drain(self):
        with self.condition:
            self.unsolicited.extend(self.lines)
            self.lines.clear()
            taken, self.unsolicited = self.unsolicited, []
        return taken

    def close(self):
        try:
            self.socket.close()
        except OSError:
            pass


class EventListener(Connection):
    def __init__(self, port, project):
        super().__init__(port, "events", project)
        for channel in CHANNELS:
            reply, _ = self.send("sub", "EVENT_CHANNEL SUB " + channel)
            if reply[-1] != "200 OK: added":
                raise RuntimeError("Could not subscribe to " + channel)


class Capture:
    def __init__(self, port, project, simulator, injector):
        self.port, self.project = port, project
        self.simulator, self.injector = simulator, injector
        self.scenarios = []
        self.connections = {}
        self.events = None
        self.current = None
        self.endpoint = None

    def expand(self, text):
        text = text.replace("<project>", self.project)
        return text.replace("<simulator>", self.endpoint) if self.endpoint else text

    def normalize(self, line):
        line = line.replace(self.project, "<project>")
        line = TIMESTAMP.sub(lambda match: f'"{match[1]}":"<timestamp>"', line)
        return re.sub(r"OID=[0-9a-f-]{36}", "OID=<oid>", line)

    def connection(self, label):
        if label not in self.connections:
            self.connections[label] = Connection(self.port, label, self.project)
        return self.connections[label]

    def scenario(self, name, description):
        self.finish()
        self.current = {"name": name, "description": description, "steps": [],
                        "unsolicited": {}, "events": []}
        self.scenarios.append(self.current)
        self.events = EventListener(self.port, self.project)

    def finish(self, settle=1.0):
        if self.current is None:
            return
        time.sleep(settle)
        for label, connection in self.connections.items():
            lines = [self.normalize(line) for line in connection.drain()]
            if lines:
                self.current["unsolicited"][label] = sorted(lines)
        self.current["events"] = sorted(
            json.dumps(json.loads(line[len("#event "):]), sort_keys=True)
            for line in self.events.drain() if line.startswith("#event "))
        self.events.close()
        for connection in self.connections.values():
            connection.close()
        self.connections.clear()
        self.current = None

    def run(self, label, text, *, stable=True, timeout=60):
        connection = self.connection(label)
        connection.sequence += 1
        tag = f"{label.lower()}{len(self.current['steps'])}"
        reply, complete = connection.send(tag, self.expand(text), timeout)
        step = {"connection": label, "tag": tag, "command": text,
                "reply": [self.normalize(line) for line in reply]}
        if not complete:
            step["no_reply_within_seconds"] = timeout
        if not stable:
            step["volatile"] = True
        self.current["steps"].append(step)
        return reply

    def wait(self, label, text, predicate, *, timeout=60, description, volatile=False):
        connection = self.connection(label)
        deadline = time.monotonic() + timeout
        polls = 0
        while True:
            reply, _ = connection.send(f"w{polls}", self.expand(text))
            polls += 1
            if predicate(reply):
                break
            if time.monotonic() >= deadline:
                raise RuntimeError(f"Timed out waiting for {description}: {reply}")
            time.sleep(0.2)
        step = {"connection": label, "command": text, "until": description,
                "reply": [self.normalize(line) for line in reply]}
        if volatile:
            # The terminal condition is stable; counters racing a native
            # worker tick (for example STOP versus an instruction boundary) are not.
            step["volatile"] = True
        self.current["steps"].append(step)
        return reply

    def memory(self, label):
        memory = self.simulator.legacy_memory[4]
        value = bytes(memory[address] for address in UNIT_NAME).hex()
        self.current["steps"].append({"simulator_unit_name_bytes": label, "hex": value})
        return value


def state_of(name):
    def predicate(reply):
        return any(f'"progState":"{name}"' in line for line in reply)
    return predicate


def list_state(programmer, state):
    def predicate(reply):
        return any(f'"progName":"{programmer}","progState":"{state}"' in line
                   and ("endedTime\":null" not in line) for line in reply)
    return predicate


def status_json(reply):
    for line in reply:
        if line.startswith("130-"):
            return json.loads(line[4:])
    raise ValueError(reply)


def open_session(capture):
    capture.run("A", "PROJECT USE <project>")
    capture.run("A", "PP LOCK L //<project>/254")
    capture.run("A", "PP START S L")
    capture.run("A", "PP LOAD S //<project>/254/p/4")
    capture.run("A", "PP GET S UnitName")


def scenarios(capture):
    save = "//<project>/254/p/4"
    capture.scenario("direct_completion",
                     "PROGRAMMER TRIGGER START from a second connection runs PP_SET then PP_SAVE; "
                     "each instruction's reply is echoed to the ADD_INSTRUCTION connection with its tag.")
    open_session(capture)
    capture.memory("before")
    capture.run("A", "PROGRAMMER CREATE P1 Task1 Route1")
    capture.run("A", "PROGRAMMER ADD_INSTRUCTION P1 PP_SET S UnitName PQA1")
    capture.run("A", "PROGRAMMER ADD_INSTRUCTION P1 PP_SAVE S " + save)
    capture.run("A", "PROGRAMMER STATUS P1")
    capture.run("A", "PROGRAMMER LIST")
    capture.run("B", "PROGRAMMER TRIGGER P1 START")
    capture.wait("B", "PROGRAMMER STATUS P1", state_of("STOPPED"), description="P1 STOPPED")
    capture.run("B", "PROGRAMMER LIST")
    capture.run("B", "DEPLOY_QUEUE LIST")
    capture.memory("after_P1")

    capture.scenario("deploy_fault_partial_and_retry",
                     "DEPLOY_QUEUE ADD of five PP instructions; the second PP_SAVE receives no reply; "
                     "the task group ends ERROR with the first save durable; explicit RETRY replays every instruction.")
    capture.run("A", "PROGRAMMER CREATE P2 Task2 Route2")
    for value in ("PQB2", None, "PQC3", None, "PQD4"):
        if value is None:
            capture.run("A", "PROGRAMMER ADD_INSTRUCTION P2 PP_SAVE S " + save)
        else:
            capture.run("A", "PROGRAMMER ADD_INSTRUCTION P2 PP_SET S UnitName " + value)
    capture.injector.arm(after=1)
    capture.run("A", "DEPLOY_QUEUE ADD P2")
    capture.wait("A", "DEPLOY_QUEUE LIST", list_state("P2", "ERROR"), timeout=90, description="P2 ERROR")
    capture.run("A", "PROGRAMMER STATUS P2")
    capture.run("A", "PROGRAMMER LIST")
    capture.run("A", "PP GET S UnitName")
    capture.memory("after_partial_P2")
    capture.current["injected_no_reply_stores"] = capture.injector.dropped
    capture.injector.disarm()
    capture.run("B", "DEPLOY_QUEUE RETRY P2")
    capture.wait("B", "DEPLOY_QUEUE LIST", list_state("P2", "STOPPED"), timeout=60, description="P2 STOPPED")
    capture.run("B", "PROGRAMMER STATUS P2")
    capture.memory("after_retry_P2")
    capture.run("B", "DEPLOY_QUEUE RETRY P2")
    capture.wait("B", "DEPLOY_QUEUE LIST", list_state("P2", "STOPPED"), timeout=60, description="P2 STOPPED again")

    capture.scenario("serial_queue_pending_delete",
                     "Task groups run one at a time; pending INIT entries can be deleted or bulk-deleted, "
                     "the active entry cannot, and RETRY rejects INIT.")
    capture.run("A", "DEPLOY_QUEUE DELETE_ALL")
    for name, count in (("Q1", 2), ("Q2", 1), ("Q3", 1)):
        capture.run("A", f"PROGRAMMER CREATE {name} T{name} R{name}")
        for index in range(count):
            capture.run("A", f"PROGRAMMER TEST {name} step{index}")
    for name in ("Q1", "Q2", "Q3"):
        capture.run("A", "DEPLOY_QUEUE ADD " + name)
    capture.wait("A", "PROGRAMMER STATUS Q1", state_of("RUNNING"), description="Q1 RUNNING",
                 volatile=True)
    capture.run("A", "PROGRAMMER STATUS Q2")
    capture.run("A", "DEPLOY_QUEUE LIST", stable=False)
    capture.run("A", "DEPLOY_QUEUE DELETE Q1")
    capture.run("A", "DEPLOY_QUEUE DELETE Q3")
    capture.run("A", "DEPLOY_QUEUE RETRY Q2")
    capture.run("A", "DEPLOY_QUEUE ADD Q2")
    capture.run("A", "DEPLOY_QUEUE DELETE_ALL PENDING")
    capture.run("A", "PROGRAMMER STATUS Q3")
    capture.wait("A", "DEPLOY_QUEUE LIST", list_state("Q1", "STOPPED"), timeout=30, description="Q1 STOPPED")
    capture.run("A", "PROGRAMMER STATUS Q1")
    capture.run("A", "DEPLOY_QUEUE DELETE_ALL COMPLETED")
    capture.run("A", "DEPLOY_QUEUE LIST")

    capture.scenario("cancel_stop_and_retry_reinit",
                     "CANCEL_INSTRUCTION on queued/running/cancelled/missing instructions, STOP mid-run, "
                     "terminal-state errors, and RETRY re-queuing cancelled instructions.")
    capture.run("A", "PROGRAMMER CREATE C1 TC1 RC1")
    for step in ("a", "b", "c"):
        capture.run("A", "PROGRAMMER TEST C1 " + step)
    capture.run("A", "PROGRAMMER CANCEL_INSTRUCTION C1 3")
    capture.run("A", "DEPLOY_QUEUE ADD C1")
    capture.wait("A", "PROGRAMMER STATUS C1",
                 lambda reply: status_json(reply)["progState"] == "RUNNING" and status_json(reply)["queueCount"] == 2,
                 description="C1 running instruction 1", volatile=True)
    capture.run("A", "PROGRAMMER CANCEL_INSTRUCTION C1 1")
    capture.wait("A", "PROGRAMMER STATUS C1", lambda reply: status_json(reply)["queueCount"] == 1,
                 description="C1 advanced to instruction 2", volatile=True)
    capture.run("A", "PROGRAMMER CANCEL_INSTRUCTION C1 1")
    capture.run("A", "PROGRAMMER CANCEL_INSTRUCTION C1 9")
    capture.run("A", "PROGRAMMER TRIGGER C1 STOP")
    capture.wait("A", "PROGRAMMER STATUS C1", state_of("STOPPED"), description="C1 STOPPED", volatile=True)
    capture.wait("A", "DEPLOY_QUEUE LIST", list_state("C1", "STOPPED"), description="C1 completed", volatile=True)
    capture.run("A", "PROGRAMMER TRIGGER C1 STOP")
    capture.run("A", "PROGRAMMER TRIGGER C1 START")
    capture.run("A", "PROGRAMMER TRIGGER C1 RESUME")
    capture.run("A", "PROGRAMMER ADD_INSTRUCTION C1 PP_END S")
    capture.run("A", "PROGRAMMER TEST C1 d")
    capture.run("A", "PROGRAMMER CANCEL_INSTRUCTION C1 2")
    capture.run("A", "DEPLOY_QUEUE RETRY C1")
    capture.wait("A", "PROGRAMMER STATUS C1", lambda reply: status_json(reply)["totalCount"] == 4
                 and status_json(reply)["progState"] == "RUNNING" and status_json(reply)["remainingSeconds"] >= 10,
                 description="C1 retried with all four TEST instructions queued", volatile=True)
    capture.run("A", "PROGRAMMER TRIGGER C1 STOP")
    capture.wait("A", "DEPLOY_QUEUE LIST", list_state("C1", "STOPPED"), description="C1 completed again",
                 volatile=True)

    capture.scenario("terminal_add_and_retry_admission",
                     "ADD of an already STOPPED or ERROR programmer files it without re-execution; "
                     "RETRY of a terminal programmer outside the queue is refused.")
    capture.run("A", "DEPLOY_QUEUE DELETE_ALL")
    capture.run("A", "PROGRAMMER CREATE T1 TT1 RT1")
    capture.run("A", "PROGRAMMER TRIGGER T1 START")
    capture.wait("A", "PROGRAMMER STATUS T1", state_of("STOPPED"), description="T1 STOPPED")
    capture.run("A", "PROGRAMMER CREATE E1 TE1 RE1")
    capture.run("A", "PROGRAMMER ADD_INSTRUCTION E1 PP_SET S UnitName PQE5")
    capture.run("A", "PROGRAMMER ADD_INSTRUCTION E1 PP_SET S NoSuchParam 1")
    capture.run("A", "PROGRAMMER ADD_INSTRUCTION E1 PP_SET S UnitName PQE6")
    capture.run("A", "PROGRAMMER TRIGGER E1 START")
    capture.wait("A", "PROGRAMMER STATUS E1", state_of("ERROR"), description="E1 ERROR")
    capture.run("A", "PROGRAMMER STATUS E1")
    capture.run("A", "PP GET S UnitName")
    capture.run("A", "DEPLOY_QUEUE RETRY T1")
    capture.run("A", "DEPLOY_QUEUE RETRY E1")
    capture.run("A", "DEPLOY_QUEUE ADD T1")
    capture.run("A", "DEPLOY_QUEUE ADD E1")
    capture.wait("A", "DEPLOY_QUEUE LIST", lambda reply: len(reply) == 3 and "endedTime\":null" not in "".join(reply),
                 description="T1 completed and E1 failed")
    capture.run("A", "PROGRAMMER STATUS E1")
    capture.run("A", "DEPLOY_QUEUE DELETE_ALL FAILED")
    capture.run("A", "DEPLOY_QUEUE DELETE T1")
    capture.run("A", "DEPLOY_QUEUE LIST")

    capture.scenario("delete_running_and_late_instruction",
                     "An instruction added while running is executed; PROGRAMMER DELETE orphans the running "
                     "queue entry, which only bulk deletion can remove.")
    capture.run("A", "PROGRAMMER CREATE D1 TD1 RD1")
    capture.run("A", "PROGRAMMER TEST D1 a")
    capture.run("A", "DEPLOY_QUEUE ADD D1")
    capture.wait("A", "PROGRAMMER STATUS D1", state_of("RUNNING"), description="D1 RUNNING",
                 volatile=True)
    capture.run("A", "PROGRAMMER ADD_INSTRUCTION D1 PP_END Missing")
    capture.run("A", "PROGRAMMER DELETE D1")
    capture.run("A", "PROGRAMMER STATUS D1")
    capture.wait("A", "DEPLOY_QUEUE LIST", list_state("D1", "ERROR"), timeout=30, description="orphan D1 ERROR")
    capture.run("A", "DEPLOY_QUEUE DELETE D1")
    capture.run("A", "DEPLOY_QUEUE RETRY D1")
    capture.run("A", "DEPLOY_QUEUE DELETE_ALL")
    capture.run("A", "DEPLOY_QUEUE LIST")

    capture.scenario("error_and_pause_stop",
                     "TRIGGER ERROR mid-TEST ends the queue entry in ERROR; PAUSE then STOP ends STOPPED.")
    capture.run("A", "PROGRAMMER CREATE R1 TR1 RR1")
    capture.run("A", "PROGRAMMER TEST R1 a")
    capture.run("A", "PROGRAMMER TEST R1 b")
    capture.run("A", "DEPLOY_QUEUE ADD R1")
    capture.wait("A", "PROGRAMMER STATUS R1", state_of("RUNNING"), description="R1 RUNNING",
                 volatile=True)
    capture.run("A", "PROGRAMMER TRIGGER R1 ERROR")
    capture.wait("A", "DEPLOY_QUEUE LIST", list_state("R1", "ERROR"), description="R1 failed", volatile=True)
    capture.run("A", "PROGRAMMER CREATE S1 TS1 RS1")
    capture.run("A", "PROGRAMMER TEST S1 a")
    capture.run("A", "PROGRAMMER TEST S1 b")
    capture.run("A", "DEPLOY_QUEUE ADD S1")
    capture.wait("A", "PROGRAMMER STATUS S1", state_of("RUNNING"), description="S1 RUNNING",
                 volatile=True)
    capture.run("A", "PROGRAMMER TRIGGER S1 PAUSE")
    capture.run("A", "PROGRAMMER TRIGGER S1 PAUSE")
    capture.run("A", "PROGRAMMER STATUS S1", stable=False)
    capture.run("A", "PROGRAMMER TRIGGER S1 STOP")
    capture.wait("A", "DEPLOY_QUEUE LIST", list_state("S1", "STOPPED"), description="S1 completed", volatile=True)
    capture.run("A", "PROGRAMMER STATUS S1", stable=False)
    capture.run("A", "PROGRAMMER CREATE I1 TI1 RI1")
    capture.run("A", "PROGRAMMER TEST I1 a")
    capture.run("A", "PROGRAMMER TRIGGER I1 PAUSE")
    capture.run("A", "PROGRAMMER TRIGGER I1 RESUME")
    time.sleep(4)
    capture.run("A", "PROGRAMMER STATUS I1")
    capture.run("A", "PROGRAMMER TRIGGER I1 bogus")

    capture.scenario("started_pause_resume_deadlock",
                     "RESUME of a started, paused programmer never replies in C-Gate 3.4.0.2001; the "
                     "programmer stays PAUSED. Captured last because the task group is wedged until restart.")
    capture.run("A", "PROGRAMMER CREATE W1 TW1 RW1")
    capture.run("A", "PROGRAMMER TEST W1 a")
    capture.run("A", "PROGRAMMER TEST W1 b")
    capture.run("A", "PROGRAMMER TRIGGER W1 START")
    capture.wait("A", "PROGRAMMER STATUS W1", state_of("RUNNING"), description="W1 RUNNING",
                 volatile=True)
    capture.run("A", "PROGRAMMER TRIGGER W1 PAUSE")
    # Let the worker observe PAUSED and park; an immediate RESUME can win the race.
    time.sleep(1)
    capture.run("A", "PROGRAMMER TRIGGER W1 RESUME", timeout=8)
    capture.run("B", "PROGRAMMER STATUS W1", stable=False)
    capture.run("B", "PROGRAMMER TRIGGER W1 STOP", timeout=5)
    capture.finish()


def capture(*, output_dir, vendor=None):
    vendor = Path(vendor or os.environ["CBUS_LOCAL_CGATE_VENDOR"])
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    project = "DQ" + uuid.uuid4().hex[:6].upper()
    simulator = key4_simulator(output / (project + "-wire.jsonl"), output / (project + "-state.json"))
    injector = FaultInjector(simulator)
    service = RestartableLocalCGate(vendor)
    # Native PP LOCK/START/LOAD/SAVE require the Clipsal level on this loopback-only child.
    (service.work / "config/access.txt").write_text("interface 127.0.0.1 Clipsal\n")
    script = Path(__file__)
    report = {"format": FORMAT, "project_placeholder": "<project>",
              "capture_script_sha256": hashlib.sha256(script.read_bytes()).hexdigest(),
              "simulator_fixture_sha256": hashlib.sha256((script.parent / "fixtures/key4-synthetic.json").read_bytes()).hexdigest(),
              "scenarios": []}
    with service, simulator.running("127.0.0.1", 0) as (_, simulator_port):
        cap = Capture(service.port, project, simulator, injector)
        cap.endpoint = f"127.0.0.1:{simulator_port}"
        cap.scenario("setup", "Disposable project whose only network is the loopback KEY4 simulator.")
        cap.run("A", "PROJECT NEW <project>")
        cap.run("A", "PROJECT USE <project>")
        cap.run("A", "DBCREATENET 254 PCI_Oracle Cni <simulator>", stable=False)
        cap.run("A", "PROJECT SAVE <project>")
        cap.run("A", "NET LOAD DB <project>")
        cap.run("A", "NET OPEN //<project>/254", stable=False)
        cap.wait("A", "GET //<project>/254 state", lambda reply: "state=ok" in reply[-1], timeout=60,
                 description="network ok")
        cap.run("A", "PROGRAMMER LIST")
        cap.run("A", "DEPLOY_QUEUE LIST")
        scenarios(cap)

        # Restart volatility: project files persist, runtime queues do not.
        cap.finish()
        service.restart()
        cap.scenario("restart_volatility", "Native restart discards PROGRAMMER, DEPLOY_QUEUE and PP state; "
                     "simulator memory written by confirmed saves persists independently.")
        cap.run("A", "PROGRAMMER LIST")
        cap.run("A", "DEPLOY_QUEUE LIST")
        cap.run("A", "PP UNITS")
        cap.run("A", "PP LIST_LOCK")
        cap.run("A", "PROGRAMMER STATUS P2")
        cap.run("A", "DEPLOY_QUEUE RETRY P2")
        cap.memory("after_restart")
        cap.run("A", "PROJECT LOAD <project>", stable=False)
        cap.run("A", "PROJECT CLOSE <project>", stable=False)
        cap.run("A", "PROJECT DELETE <project>", stable=False)
        cap.finish(settle=0.2)
        report["scenarios"] = cap.scenarios
    report["local_service"] = {key: service.report.get(key) for key in (
        "vendor_jar_sha256", "java_sha256", "listener_ownership_verified", "cleanup_complete",
        "process_exit_confirmed", "work_removed")}
    report["unsupported_simulator_requests"] = [
        record for record in simulator.wire_log
        if "reason" in record and record["reason"] != "injected no-reply"]
    path = output / "native-programmer-lifecycle.json"
    path.write_text(json.dumps(report, indent=2) + "\n")
    report["report_path"] = str(path)
    return report


def volatile_projection(reply):
    """Keep only the programmer states and final status of a racing reply."""
    states = []
    for line in reply:
        if line.startswith("130-"):
            row = json.loads(line[4:])
            states.append({"progName": row.get("progName"), "progState": row["progState"],
                           "endedTime": None if row.get("endedTime", "") is None else
                           ("<timestamp>" if "endedTime" in row else "<absent>")})
    return {"volatile": True, "states": states, "final_code": reply[-1][:3] if reply else None}


def comparable(report):
    """Stable projection used for fixture equality: volatile replies keep only states."""
    scenarios = []
    for scenario in report["scenarios"]:
        steps = []
        for step in scenario["steps"]:
            step = dict(step)
            step.pop("tag", None)
            if step.pop("volatile", False):
                step["reply"] = volatile_projection(step["reply"])
            steps.append(step)
        scenarios.append({"name": scenario["name"], "steps": steps,
                          "unsolicited": scenario["unsolicited"],
                          "events": dict(sorted(Counter(scenario["events"]).items())),
                          **({"injected_no_reply_stores": scenario["injected_no_reply_stores"]}
                             if "injected_no_reply_stores" in scenario else {})})
    return scenarios


# Conclusions drawn from the scenarios above and the owned class hashes in
# native_cgate_deploy_queue.json / native_cgate_pp_programmer.json. The
# offline test checks each against the committed transcript.
NATIVE_FACTS = {
    "instruction_reply_echo": "Each executed PP instruction's reply lines are sent to the connection that issued "
                              "its ADD_INSTRUCTION, under that command's tag; TEST and cancelled instructions echo nothing.",
    "failed_instruction_counts": "A failed instruction leaves queueCount and remainingSeconds; later queued "
                                 "instructions stay counted while the programmer is ERROR.",
    "partial_outcome": "A no-reply on the second PP_SAVE leaves the first save durable in the unit; the "
                       "session holds the unsaved later value.",
    "retry_replays_everything": "RETRY reinitializes every instruction, including completed and cancelled ones, "
                                "and re-executes the whole task group; it emits removeTaskGroup then addTaskGroup.",
    "retry_admission": "RETRY needs a STOPPED/ERROR programmer in the failed/completed collections: INIT is "
                       "502 illegal state, an unqueued terminal programmer is 501 failed: could not retry programmer.",
    "serial_queue": "One task group is active at a time; later entries stay INIT with startedTime null.",
    "pending_delete": "DELETE removes a pending entry and its programmer; the active entry returns 502.",
    "delete_all": "ALL removes pending, failed and completed entries but never the active one.",
    "terminal_add": "ADD of a STOPPED or ERROR programmer files it at once (ended event, no started) without execution.",
    "late_instruction": "ADD_INSTRUCTION while RUNNING is accepted and executed.",
    "registry_delete_while_running": "PROGRAMMER DELETE leaves the running entry executing; only DELETE_ALL removes "
                                     "the orphan and reports 501-failed: could not delete programmer.",
    "cancel": "CANCEL_INSTRUCTION of a running TEST ends it; repeating it returns 200; an unknown id is "
              "402 Operation not supported by: failed: command not found.",
    "transition_errors": "Refused transitions are 400 Syntax Error: failed: transition of X is not allowed on STATE.",
    "terminal_add_instruction": "ADD_INSTRUCTION on a terminal programmer is 402 Operation not supported by: "
                                "failed: programmer in unsupported state; PROGRAMMER TEST is still accepted.",
    "init_pause_resume": "PAUSE then RESUME before START reaches RUNNING with no worker; nothing executes.",
    "started_pause_resume_deadlock": "RESUME of a started, paused programmer never replies (the worker parks "
                                     "holding the pause monitor that RESUME needs); later triggers also block.",
    "restart": "A daemon restart discards PROGRAMMER, DEPLOY_QUEUE, PP locks and sessions; unit memory is unaffected.",
    "timing": "Instruction pacing, 500 ms queue polling and roughly 20 s unit no-reply failure are timing, "
              "not compared.",
}


def fixture(report, source_report_sha256):
    return {
        "format": FORMAT,
        "oracle": {"product": "Schneider Electric C-Gate", "version": "3.4.0.2001",
                   "jar_sha256": report["local_service"]["vendor_jar_sha256"],
                   "java_sha256": report["local_service"]["java_sha256"],
                   "environment": "Owned loopback-only child with Clipsal interface access; one disposable project "
                                  "whose only CNI endpoint was the loopback synthetic KEY4 simulator; no site project, "
                                  "hardware or LAN endpoint.",
                   "cleanup_complete": report["local_service"]["cleanup_complete"]},
        "capture_script_sha256": report["capture_script_sha256"],
        "simulator_fixture_sha256": report["simulator_fixture_sha256"],
        "raw_report_sha256": source_report_sha256,
        "comparison": "Steps are compared exactly after <project>, <oid> and <timestamp> normalization; "
                      "volatile replies race native worker ticks, so only their programmer states and final "
                      "code are kept. "
                      "Unsolicited lines and EVENT_CHANNEL events are per-scenario multisets.",
        "native_facts": NATIVE_FACTS,
        "sanitization": {"site_project_retained": False, "network_identifiers_retained": False,
                         "credentials_retained": False, "vendor_source_retained": False},
        "scenarios": comparable(report),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--vendor", type=Path)
    parser.add_argument("--fixture", type=Path, help="Write the sanitized committed fixture here")
    parser.add_argument("--from-report", type=Path, help="Rebuild the fixture from an earlier raw report")
    args = parser.parse_args()
    if args.from_report:
        report = json.loads(args.from_report.read_text())
        report["report_path"] = str(args.from_report)
    else:
        report = capture(output_dir=args.output_dir, vendor=args.vendor)
    if args.fixture:
        raw = hashlib.sha256(Path(report["report_path"]).read_bytes()).hexdigest()
        args.fixture.write_text(json.dumps(fixture(report, raw), indent=2) + "\n")
    print(json.dumps({"report": report["report_path"], "scenarios": len(report["scenarios"]),
                      "cleanup": report["local_service"]["cleanup_complete"]}))


if __name__ == "__main__":
    main()
