#!/usr/bin/env python3
"""Native project archive/restore/rename/repair acceptance on a disposable server.

All project names are random; archives remain in the chosen server directory
as acceptance artifacts. No network is opened. --host is intentionally required.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import uuid

from cbus_toolkit.cgate import CGateClient
from cbus_toolkit.native import NativeDatabase, NativeProjects


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, default=20023)
    parser.add_argument("--server-archive-dir", required=True)
    parser.add_argument("--output", type=Path, default=Path(__file__).parent / "runtime/project-acceptance.json")
    args = parser.parse_args()
    report = {"time": datetime.now(timezone.utc).isoformat(), "host": args.host, "port": args.port,
              "scope": "Native offline project operations; not Toolkit functional parity", "operations": [], "cleanup": []}
    names = set()
    loaded = set()

    def record(operation, function):
        try:
            result = function()
            item = {"operation": operation, "status": "pass", "reply": list(result.lines)}
        except (ValueError, OSError, RuntimeError) as error:
            item = {"operation": operation, "status": "fail", "error": str(error)}
        report["operations"].append(item)
        return item["status"] == "pass"

    def name():
        return "V" + uuid.uuid4().hex[:7].upper()

    with CGateClient(args.host, args.port) as client:
        report["server"] = client.command("GET cgate version").final
        projects, db = NativeProjects(client), NativeDatabase(client)
        source = name()
        projects.operation("new", source)
        loaded.add(source)
        try:
            db.set(f"//{source}/Project/Description", "Disposable cbus-toolkit project acceptance")
            db.create_network(source, 254, "Local", "Cni", "127.0.0.1:1")
            db.add(f"//{source}/254", "application", 56, "Lighting")
            db.add(f"//{source}/254/56", "group", 1, "Acceptance")
            projects.operation("save", source)
            names.add(source)
            for extension in ("zip", "gz", "db"):
                archive = args.server_archive_dir.rstrip("/") + "/" + source + "." + extension
                destination = name()
                if not record("archive-" + extension, lambda: projects.operation("archive", source, archive)):
                    continue
                if not record("restore-" + extension, lambda: projects.operation("restore", destination, archive)):
                    continue
                names.add(destination)
                projects.operation("load", destination)
                loaded.add(destination)
                def verify():
                    result = db.get(f"//{destination}/254/56/1/TagName")
                    if not any("=Acceptance" in line for line in result.lines):
                        raise RuntimeError("Restored group differs from archived group")
                    return result
                record("verify-restored-" + extension, verify)
                projects.operation("close", destination)
                loaded.remove(destination)
                renamed = name()
                if record("rename-" + extension, lambda: projects.operation("rename", destination, renamed)):
                    names.remove(destination)
                    names.add(renamed)
                    projects.operation("load", renamed)
                    loaded.add(renamed)
                    record("read-renamed-" + extension, lambda: db.get(f"//{renamed}/254/56/1/TagName"))
                    projects.operation("close", renamed)
                    loaded.remove(renamed)
                    # Record actual support. A 408 is a failed feature, not a pass.
                    record("repair-" + extension, lambda: projects.operation("repair", renamed))
        finally:
            for project in sorted(loaded):
                try:
                    projects.operation("close", project)
                except (OSError, RuntimeError) as error:
                    report["cleanup"].append({"project": project, "operation": "close", "error": str(error)})
            for project in sorted(names):
                try:
                    projects.operation("delete", project)
                except (OSError, RuntimeError) as error:
                    report["cleanup"].append({"project": project, "operation": "delete", "error": str(error)})
    report["summary"] = {"passed": sum(item["status"] == "pass" for item in report["operations"]),
                          "failed": sum(item["status"] != "pass" for item in report["operations"])}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"output": str(args.output), **report["summary"]}))
    return int(bool(report["summary"]["failed"] or report["cleanup"]))


if __name__ == "__main__":
    raise SystemExit(main())
