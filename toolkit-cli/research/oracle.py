#!/usr/bin/env python3
"""Manage a disposable, localhost-only C-Gate 3.4 reference service in Docker."""
from __future__ import annotations

import argparse
import json
import socket
import subprocess
import time
from pathlib import Path

IMAGE = "eclipse-temurin:11-jre@sha256:36d9ed86b75e03d756fd4f3b9fdcf952451ddce4a4c451d23cf457ef2d591920"


def docker(*args, **kwargs):
    return subprocess.run(["docker", *args], check=True, text=True, capture_output=True, **kwargs).stdout.strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "stop", "status"))
    parser.add_argument("--name", default="cbus-toolkit-oracle")
    parser.add_argument("--cgate-dir", type=Path, default=Path(__file__).parent / "vendor/cgate/app")
    parser.add_argument("--state-dir", type=Path, default=Path(__file__).parent / "runtime/cgate")
    parser.add_argument("--port", type=int, default=20023)
    args = parser.parse_args()
    if args.action == "stop":
        print(docker("stop", args.name))
        return
    if args.action == "status":
        print(docker("inspect", "--format", "{{json .State}}", args.name))
        return
    if not (args.cgate_dir / "cgate.jar").is_file():
        parser.error("Extract the Toolkit vendor installer first")
    existing = subprocess.run(["docker", "inspect", args.name], capture_output=True, text=True)
    if existing.returncode == 0:
        parser.error("Container already exists; inspect it or use another --name")
    state = args.state_dir.resolve()
    state.mkdir(parents=True, exist_ok=True)
    for name in ("config", "tag", "logs"):
        (state / name).mkdir(exist_ok=True)
    # These symlinks resolve inside the container, whose root is isolated.
    for name in ("lib", "key", "unitspec", "help", "transform", "dali_catalogue"):
        target = state / name
        if not target.is_symlink() and not target.exists():
            target.symlink_to("/opt/cgate/" + name, target_is_directory=True)
    cid = docker("run", "-d", "--name", args.name,
                 "--label", "cbus-toolkit.role=disposable-oracle",
                 "-p", f"127.0.0.1:{args.port}:20023",
                 "-v", f"{args.cgate_dir.resolve()}:/opt/cgate:ro",
                 "-v", f"{state}:/work", "-w", "/work", IMAGE,
                 "java", "-Xms64M", "-Xmx512M", "-jar", "/opt/cgate/cgate.jar")
    gateway = docker("inspect", "--format", "{{range .NetworkSettings.Networks}}{{.Gateway}}{{end}}", args.name)
    access = state / "config/access.txt"
    # A new local test instance only. The port is never published on LAN addresses.
    access.write_text("interface 127.0.0.1 Program\ninterface localhost Program\n"
                      "interface 0:0:0:0:0:0:0:1 Program\n" + f"remote {gateway} Clipsal\n")
    docker("restart", args.name)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", args.port), 1) as s:
                s.settimeout(1)
                greeting = s.recv(4096).decode("utf-8")
                if greeting.startswith("201 "):
                    print(json.dumps({"container": cid, "greeting": greeting.strip(),
                                      "port": args.port, "state": str(state)}, indent=2))
                    return
        except OSError:
            pass
        time.sleep(0.1)
    raise RuntimeError("C-Gate did not become ready; inspect docker logs " + args.name)


if __name__ == "__main__":
    main()
