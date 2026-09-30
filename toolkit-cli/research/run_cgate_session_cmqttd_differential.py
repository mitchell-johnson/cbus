#!/usr/bin/env python3
"""Run the scoped SESSION_ID differential through cmqttd's real C-Gate port.

The daemon receives a synthetic PCI endpoint, an empty disposable project,
and a locally held broker socket. No house network or MQTT broker is used.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shlex
import socket
import subprocess
import sys
import tempfile
import time

from cbus_toolkit.simulator import PCISimulator
from cgate_session_differential import run


class InitializedPCI(PCISimulator):
    def _command(self, line, context):
        if line in (b"~", b"A32100FF", b"A32200FF", b"A342000E", b"A3300079"):
            return b"", None
        return super()._command(line, context)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cmqttd-bin", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    binary = args.cmqttd_bin.resolve()
    if not binary.is_file():
        parser.error(f"cmqttd executable missing: {binary}")
    receipt = None
    code = 2
    with tempfile.TemporaryDirectory(prefix="cbus-session-cmqttd-") as tmp:
        scratch = Path(tmp)
        project = scratch / "project.xml"
        project.write_text("<Installation><Project><TagName>SESSION_TEST</TagName>"
                           "<Network><Address>254</Address><TagName>Loopback</TagName>"
                           "</Network></Project></Installation>", encoding="utf-8")
        sim = InitializedPCI(profile="captured", command_checksum=True)
        with socket.socket() as broker, sim.running() as pci:
            broker.bind(("127.0.0.1", 0))
            broker.listen(1)
            log_path = scratch / "cmqttd.log"
            with log_path.open("w") as log:
                process = subprocess.Popen([
                    str(binary), "--tcp", f"{pci[0]}:{pci[1]}",
                    "--broker-address", "127.0.0.1",
                    "--broker-port", str(broker.getsockname()[1]),
                    "--broker-disable-tls", "--timesync", "0", "--status-resync", "0",
                    "--project-file", str(project), "--cgate-bind", "127.0.0.1:0",
                    "--cgate-state", str(scratch / "state.json"),
                ], stdout=subprocess.DEVNULL, stderr=log)
                try:
                    deadline = time.monotonic() + 15
                    port = None
                    while time.monotonic() < deadline:
                        output = log_path.read_text(encoding="utf-8")
                        match = re.search(r"C-Gate service listening on 127\.0\.0\.1:(\d+)", output)
                        if match:
                            port = int(match.group(1))
                            break
                        if process.poll() is not None:
                            raise RuntimeError(f"cmqttd exited before the C-Gate listener: {output}")
                        time.sleep(.02)
                    if port is None:
                        raise TimeoutError("cmqttd did not open a C-Gate listener")
                    receipt, code = run(binary, "current-build", port)
                    receipt["endpoint"] = "owned ephemeral 127.0.0.1 cmqttd C-Gate listener"
                    receipt["offline_provision"] = {
                        "pci": "PCISimulator captured profile",
                        "broker": "locally held socket, no MQTT exchange",
                        "project": "disposable empty XML",
                        "physical_networks_opened": False,
                    }
                except Exception as exc:
                    receipt, _ = run(binary, "current-build", -1)
                    receipt["errors"].append(f"launcher {type(exc).__name__}: {exc}")
                    receipt["result"] = "blocked"
                    code = 2
                finally:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
    assert receipt is not None
    receipt["command"] = shlex.join([sys.executable, *sys.argv])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: receipt[key] for key in ("result", "executed", "passed", "failed", "skipped", "errors")}))
    return code


if __name__ == "__main__":
    sys.exit(main())
