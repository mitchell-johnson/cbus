#!/usr/bin/env python3
"""Resume one catalogue report with independent closed-network worker sessions.

The source report fixes the exact selected cases. Completed cases are preserved;
only not_run cases are dispatched. Each worker persists its own report, and this
coordinator merges complete results atomically. Commands are never replayed after
ambiguous failures. Use verify_catalog.py to create the initial report first.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import signal
import subprocess
import sys
import time

from verify_catalog import checkpoint, digest, now


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, default=20023)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--jobs", type=int, choices=range(1, 5), default=4)
    args = parser.parse_args()
    report = json.loads(args.output.read_text())
    if report.get("selection", {}).get("shard"):
        parser.error("Expected an unsharded source report")
    original_runs = deepcopy(report["runs"])
    base_run_count = len(original_runs)
    directory = args.output.parent / (args.output.stem + "-workers-" + str(len(report.get("parallel_runs", []))))
    directory.mkdir()
    parallel_run = {"started_at": now(), "jobs": args.jobs, "networks": list(range(250, 250 + args.jobs)),
                    "worker_directory": str(directory.resolve()), "base_run_count": base_run_count}
    report.setdefault("parallel_runs", []).append(parallel_run)
    checkpoint(args.output, report)
    workers = []
    try:
        for index in range(args.jobs):
            worker_report = deepcopy(report)
            worker_report["cases"] = deepcopy(report["cases"][index::args.jobs])
            worker_report.pop("parallel_runs", None)
            worker_report["selection"]["shard"] = f"{index}/{args.jobs}"
            worker_report["selection"]["case_ids_sha256"] = digest([case["id"] for case in worker_report["cases"]])
            path = directory / f"worker-{index}.json"
            checkpoint(path, worker_report)
            command = [sys.executable, str(Path(__file__).with_name("verify_catalog.py")), "--host", args.host,
                       "--port", str(args.port), "--catalog", report["catalog"]["path"], "--output", str(path),
                       "--resume", "--network", str(250 + index), "--shard", f"{index}/{args.jobs}"]
            for field, flag in (("all_revisions", "--all-revisions"), ("boundaries", "--boundaries")):
                if report["selection"][field]:
                    command.append(flag)
            if report["selection"]["filter"]:
                command.extend(["--filter", report["selection"]["filter"]])
            output = (directory / f"worker-{index}.log").open("w")
            process = subprocess.Popen(command, stdout=output, stderr=subprocess.STDOUT)
            workers.append((process, path, output))
        while True:
            finished = all(process.poll() is not None for process, _path, _output in workers)
            merged = {}
            runs = deepcopy(original_runs)
            for index, (_process, path, _output) in enumerate(workers):
                worker = json.loads(path.read_text())
                added_run_base = len(runs)
                for run in worker["runs"][base_run_count:]:
                    run = deepcopy(run)
                    run["worker_index"] = index
                    run["worker_report"] = str(path.resolve())
                    runs.append(run)
                for case in worker["cases"]:
                    if "result" not in case:
                        continue
                    result = case["result"]
                    local_index = result.get("run_index")
                    if local_index is not None and local_index >= base_run_count:
                        result["run_index"] = added_run_base + local_index - base_run_count
                        result["worker_report"] = str(path.resolve())
                    merged[case["id"]] = case
            report["cases"] = [merged.get(case["id"], case) for case in report["cases"]]
            report["runs"] = runs
            checkpoint(args.output, report)
            print(json.dumps(report["summary"]), flush=True)
            if finished:
                break
            time.sleep(10)
    except KeyboardInterrupt:
        parallel_run["stopped_reason"] = "Interrupted; worker sessions asked to close; remaining cases stay not_run"
        for process, _path, _output in workers:
            if process.poll() is None:
                process.send_signal(signal.SIGINT)
    finally:
        for process, _path, output in workers:
            try:
                process.wait(timeout=40)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(timeout=10)
            output.close()
        parallel_run["worker_exit_codes"] = [process.returncode for process, _path, _output in workers]
        parallel_run["finished_at"] = now()
        checkpoint(args.output, report)
    return 0 if report["summary"]["all_selected_cases_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
