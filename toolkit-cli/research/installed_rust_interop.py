#!/usr/bin/env python3
"""Fresh installed-wheel acceptance of the maintained owned Rust interop selections.

No Cargo, original software, native service or hardware provisioning occurs here.
The full default declaration and an explicit focused subset are different scopes.
"""
from __future__ import annotations

import argparse
import base64
from collections import Counter
import csv
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import stat
import subprocess
import sys
import time
import zipfile
import xml.etree.ElementTree as ET
import signal

FORMAT = "cbus-installed-rust-interop-v1"
TARGETS = {"mock": "check-cgate-interop", "daemon": "check-cmqtt-interop"}
OPTIONAL_SKIPS = {
    "tests/test_rust_cgate_interop.py::RustInteropTests::test_edlt_lighting_programming_round_trip":
        {"kind": "decorator.skipUnless", "reason": "vendor unitspec directory is absent"},
    "tests/test_cmqtt_programming_methods_interop.py::test_protection_matrix_matches_a_fresh_derivation":
        {"kind": "decorator.skipif", "reason": "Set CBUS_UNITSPEC_DIR to re-derive the matrix from decoded specs"},
}
SELECTOR = re.compile(r"tests/[A-Za-z0-9_./-]+\.py(?:::[^\r\n]+)?\Z")


class GateError(ValueError):
    """A declared gate cannot be accepted."""


def require(condition, message):
    if not condition:
        raise GateError(message)


def pin(path):
    path = Path(path)
    data = path.read_bytes()
    return {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def binary_identity(path):
    path = Path(path).absolute()
    require(path.is_file() and os.access(path, os.X_OK), f"Required executable missing: {path}")
    return {"path": str(path), "resolved": str(path.resolve()), **pin(path)}


def assert_quiet(before, after):
    require(before == after, "Frozen input bytes changed")
    return True


def declared_selections(make_text):
    result = {}
    for backend, target in TARGETS.items():
        marker = target + ": compile\n"
        require(make_text.count(marker) == 1, f"Expected one maintained {target} declaration")
        body = make_text.split(marker, 1)[1].split("\n\n", 1)[0]
        tokens = shlex.split(body.replace("\\\n", " "))
        require(tokens.count("pytest") == 1, f"Expected one pytest command in {target}")
        tail = tokens[tokens.index("pytest") + 1:]
        selectors = [token for token in tail if SELECTOR.fullmatch(token)]
        require(selectors and len(selectors) == len(set(selectors)),
                f"Missing or duplicate selectors in {target}")
        require(all(".." not in Path(s.split("::", 1)[0]).parts for s in selectors),
                "Unsafe test selector path")
        quoted = re.findall(r"'(tests/[^']+::[^']+)'", body)
        require(len(quoted) == len(set(quoted)) and set(quoted) <= set(selectors),
                "Quoted declaration does not match parsed selectors")
        result[backend] = {
            "selectors": selectors,
            "required_ids": [s for s in selectors if "::" in s],
            "whole_modules": [s for s in selectors if "::" not in s],
            "required_modules": sorted({s.split("::", 1)[0] for s in selectors}),
            "quoted_ids": quoted,
        }
    require(not (set(result["mock"]["required_ids"]) & set(result["daemon"]["required_ids"])),
            "Backend declarations overlap")
    return result


def choose_selections(plans, selects=None, *, backend=None):
    if backend is not None:
        require(selects is None, "Backend and focused selectors are mutually exclusive")
        require(isinstance(backend, str) and backend in TARGETS and backend in plans,
                "Backend must be mock or daemon")
        return {backend: plans[backend]}, "full-maintained-backend-declaration"
    if selects is None:
        return plans, "full-maintained-declaration"
    require(isinstance(selects, list) and selects and
            all(isinstance(s, str) and s for s in selects) and len(selects) == len(set(selects)),
            "Explicit selection must be nonempty unique registered selectors")
    registered = {s for p in plans.values() for s in p["selectors"]}
    require(set(selects) <= registered, "Focused selector is not registered by Make")
    chosen = {}
    for backend, p in plans.items():
        rows = [s for s in p["selectors"] if s in selects]
        if rows:
            chosen[backend] = {
                "selectors": rows, "required_ids": [s for s in rows if "::" in s],
                "whole_modules": [s for s in rows if "::" not in s],
                "required_modules": sorted({s.split("::", 1)[0] for s in rows}),
                "quoted_ids": [s for s in rows if s in p["quoted_ids"]],
            }
    return chosen, "focused-explicit-subset"


def audit_backend_matrix(evidence, plans, *, expected_revision=None, expected_inputs=None,
                         expected_package=None):
    """Combine two independently verified backend epochs without merging their traces."""
    require(isinstance(evidence, list) and len(evidence) == len(TARGETS),
            "Matrix requires exactly two backend epochs")
    require(set(plans) == set(TARGETS), "Matrix configuration lacks a backend")
    common_inputs = common_package = common_revision = common_runner = None
    phases = {}
    for value in evidence:
        summary = value["summary"]
        backend = summary.get("backend")
        require(isinstance(backend, str) and backend in TARGETS and backend not in phases,
                "Missing, foreign or duplicate matrix backend")
        require(summary.get("format") == FORMAT and summary.get("passed") is True and
                all(summary.get(key) is True for key in
                    ("source_quiet", "copied_reference_quiet", "binaries_quiet")),
                "Backend terminal gate did not pass")
        require(summary.get("scope") == "full-maintained-backend-declaration" and
                summary.get("configured_rosters") == plans and
                summary.get("selected_rosters") == {backend: plans[backend]} and
                set(summary.get("phases", {})) == {backend},
                "Backend epoch does not preserve its complete maintained declaration")
        revision = summary.get("source_revision")
        inputs, after = value["source_before"], value["source_after"]
        package = summary.get("package_before", {})
        files = package.get("files")
        require(isinstance(revision, str) and revision and isinstance(inputs, dict) and inputs and
                inputs == after and summary.get("input_count") == len(inputs),
                "Backend source revision/map is absent or changed")
        require(isinstance(files, dict) and files and package.get("file_count") == len(files) and
                summary.get("package_after") == package,
                "Backend package map is absent or changed")
        require(summary.get("binaries_before") and
                summary.get("binaries_before") == summary.get("binaries_after"),
                "Backend executable identities changed")
        require(summary.get("optional_skip_admission", {}).get("allowed") == OPTIONAL_SKIPS,
                "Backend optional skips differ from the bounded census")
        if common_inputs is None:
            common_inputs, common_package, common_revision = inputs, files, revision
            common_runner = summary.get("runner_inputs")
        require(inputs == common_inputs and files == common_package and revision == common_revision and
                summary.get("runner_inputs") == common_runner and common_runner,
                "Matrix source, product payload or runner inputs differ")
        if expected_revision is not None:
            require(revision == expected_revision, "Matrix source revision differs from checkout")
        if expected_inputs is not None:
            assert_quiet(expected_inputs, inputs)
        if expected_package is not None:
            assert_quiet(expected_package, files)
        phase = summary["phases"][backend]
        selection = value["selection"]  # Re-audited raw JUnit/trace at the artifact boundary.
        require(phase.get("selection") == selection and
                phase.get("actual_parent_counts") == selection.get("parent_counts") and
                phase.get("unitemized_subtests") == selection.get("unitemized_subtests"),
                "Backend terminal selection differs from retained raw evidence")
        required = selection.get("required_ids", [])
        require(isinstance(required, list) and len(required) == len(set(required)) and
                set(plans[backend]["required_ids"]) <= set(required) and
                all(nodeid in plans[backend]["required_ids"] or
                    nodeid.split("::", 1)[0] in plans[backend]["whole_modules"] for nodeid in required) and
                selection.get("required_passed") == len(required),
                "Backend omitted or substituted a required explicit/core body")
        for key in ("collection", "pytest"):
            require(phase.get(key, {}).get("exit") == 0 and
                    phase.get(key, {}).get("timed_out") is False,
                    "Backend command failed or timed out")
        for key in ("collection_origins", "origins"):
            origins = phase.get(key, {})
            require(origins.get("violations") == 0 and
                    type(origins.get("python_processes")) is int and origins["python_processes"] > 0 and
                    origins.get("owned_rust_children") == origins.get("owned_rust_reaped") and
                    type(origins.get("owned_rust_reaped")) is int,
                    "Backend import or child cleanup audit is incomplete")
        phases[backend] = {"explicit_required_passed": len(plans[backend]["required_ids"]),
                           "whole_modules": plans[backend]["whole_modules"], "selection": selection,
                           "binaries": summary["binaries_after"]}
    require(set(phases) == set(TARGETS), "Matrix backend union is incomplete")
    explicit = [nodeid for plan in plans.values() for nodeid in plan["required_ids"]]
    require(len(explicit) == len(set(explicit)), "Matrix declarations overlap")
    return {"format": "cbus-installed-rust-interop-matrix-v1", "passed": True,
            "scope": "two-complete-maintained-backend-epochs", "source_revision": common_revision,
            "source_input_count": len(common_inputs), "package_file_count": len(common_package),
            "explicit_required_passed": len(explicit), "explicit_required_ids": sorted(explicit),
            "whole_modules": {backend: plan["whole_modules"] for backend, plan in plans.items()},
            "phases": phases,
            "limits": ["Two separate process epochs; traces/JUnit are not concatenated",
                       "Executable identities are pinned separately, not asserted equal across jobs",
                       "Artifact verification does not rerun services or establish native/physical acceptance"]}


def read_backend_evidence(summary_path, plans, auditor):
    """Bind a terminal summary to retained collection/JUnit/trace and guard bytes."""
    summary_path = Path(summary_path)
    require(summary_path.is_file() and not summary_path.is_symlink(), "Summary artifact is not regular")
    summary = json.loads(summary_path.read_text())
    backend = summary.get("backend")
    require(isinstance(backend, str) and backend in plans, "Artifact backend is absent or foreign")
    directory, plan = summary_path.parent, plans[backend]
    phase = summary.get("phases", {}).get(backend, {})
    phase_directory = directory / backend
    for name, key in (("collection-trace.json", "collection_trace"), ("trace.json", "trace"),
                      ("junit.xml", "junit"), ("audit-receipt.json", "maintained_audit")):
        require((phase_directory / name).is_file() and not (phase_directory / name).is_symlink(),
                "Retained phase artifact is not regular")
        require(pin(phase_directory / name) == phase.get(key), "Retained phase artifact changed")
    guard_files = {}
    for path in phase_directory.rglob("*.jsonl"):
        require(path.is_file() and not path.is_symlink(), "Retained guard artifact is not regular")
        guard_files[path.relative_to(phase_directory).as_posix()] = pin(path)
    require(guard_files and guard_files == phase.get("guard_data_files"),
            "Retained guard file roster/bytes changed")
    collection = json.loads((phase_directory / "collection-trace.json").read_text())
    expected = collection.get("collected", [])
    require(expected and len(expected) == len(set(expected)) and not collection.get("deselected") and
            set(plan["required_ids"]) <= set(expected) and
            all(nodeid in plan["required_ids"] or nodeid.split("::", 1)[0] in plan["whole_modules"]
                for nodeid in expected), "Retained collection is outside the full backend declaration")
    junit, trace = phase_directory / "junit.xml", phase_directory / "trace.json"
    maintained = add_skip_reasons(auditor.audit(junit, trace, plan["required_modules"]), junit)
    required = sorted(set(expected) - (set(OPTIONAL_SKIPS) - set(plan["required_ids"])))
    selection = audit_selection(maintained, required, plan["required_modules"], OPTIONAL_SKIPS,
                                expected_collected=expected)
    require(json.loads((directory / "package-before.json").read_text()) == summary.get("package_before"),
            "Retained package descriptor differs from summary")
    return {"summary": summary, "selection": selection,
            "source_before": json.loads((directory / "source-before.json").read_text()),
            "source_after": json.loads((directory / "source-after.json").read_text()),
            "artifacts": {"summary": pin(summary_path),
                          "source_before": pin(directory / "source-before.json"),
                          "source_after": pin(directory / "source-after.json"),
                          "guard_files": guard_files}}


def audit_selection(receipt, required_ids, required_modules, optional_skips=(), *, expected_collected=None):
    require(receipt.get("passed") is True and receipt.get("pytest_exit") == 0,
            "Maintained JUnit/trace audit did not pass")
    required = list(required_ids)
    require((required or required_modules) and len(required) == len(set(required)),
            "Required IDs/modules must be nonempty and unique")
    collected, started, cases, calls = (receipt.get(k) for k in
                                        ("collected", "started", "cases", "call_events"))
    require(all(isinstance(x, list) for x in (collected, started, cases, calls)),
            "Missing execution lists")
    require(not receipt.get("deselected", []), "Selection deselected tests")
    require(len(collected) == len(set(collected)) and
            Counter(collected) == Counter(started) == Counter(c["id"] for c in cases),
            "Collected/started/JUnit identity mismatch")
    if expected_collected is not None:
        require(Counter(collected) == Counter(expected_collected), "Unexpected collected selection closure")
    require(all(n.split("::", 1)[0] in required_modules for n in collected),
            "Collected body is outside declared modules")
    require(set(required) <= set(collected), "Required case was not collected")
    case_map = {c["id"]: c for c in cases}
    require(len(case_map) == len(cases), "Duplicate JUnit ID")
    call_map = {}
    for event in calls:
        require(event.get("id") in case_map, "Call event has no JUnit identity")
        call_map.setdefault(event["id"], []).append(event.get("outcome"))
    for nodeid in required:
        require(case_map[nodeid]["outcome"] == "passed" and
                "passed" in call_map.get(nodeid, []) and
                not (set(call_map.get(nodeid, [])) - {"passed"}),
                f"Required body did not pass: {nodeid}")
    allowed = set(optional_skips)
    for case in cases:
        require(case["outcome"] == "passed" or
                (case["outcome"] == "skipped" and case["id"] in allowed and case["id"] not in required),
                f"Unexpected skipped/failed body: {case['id']}")
        if case["outcome"] == "skipped" and isinstance(optional_skips, dict):
            require(case.get("skip_reason") == optional_skips[case["id"]]["reason"],
                    "Optional skip reason does not match census")
        if case["outcome"] == "passed":
            require("passed" in call_map.get(case["id"], []) and
                    not (set(call_map.get(case["id"], [])) - {"passed"}),
                    "Passing JUnit body lacks passing calls")
    for module in required_modules:
        require(any(n.startswith(module + "::") and c["outcome"] == "passed" and
                    "passed" in call_map.get(n, []) for n, c in case_map.items()),
                f"Required module has no passing body: {module}")
    parents = Counter(c["outcome"] for c in cases)
    return {"required_ids": required, "required_passed": len(required),
            "parent_counts": dict(parents), "parent_total": len(cases),
            "unitemized_subtests": receipt.get("unitemized_subtests", {}),
            "optional_skipped_ids": sorted(c["id"] for c in cases if c["outcome"] == "skipped")}


def package_files(directory, *, allow_source_caches=False):
    root = Path(directory)
    require(root.is_dir() and not root.is_symlink(), "Package root is missing or a symlink")
    result = {}
    for p in sorted(root.rglob("*")):
        require(not p.is_symlink(), "Package member is a symlink")
        relative = p.relative_to(root)
        if allow_source_caches and "__pycache__" in relative.parts:
            require(p.is_dir() or (p.is_file() and p.suffix in {".pyc", ".pyo"}),
                    "Source cache contains a non-bytecode member")
            continue  # Ignored source work products are neither copied nor executed.
        require("__pycache__" not in relative.parts and p.suffix not in {".pyc", ".pyo"},
                "Product bytecode cache is not admitted")
        if p.is_file():
            result[p.relative_to(root).as_posix()] = pin(p)
    require(result, "Empty package")
    return result


def verify_record(installed_package):
    installed = Path(installed_package)
    site = installed.parent
    rows = list(site.glob("cbus_toolkit_cli-*.dist-info/RECORD"))
    require(len(rows) == 1, "Expected one installed distribution RECORD")
    record = rows[0]
    seen = set()
    venv = site.parent.parent.parent.resolve()
    for row in csv.reader(record.read_text().splitlines()):
        require(len(row) == 3 and row[0] not in seen, "Duplicate or malformed RECORD entry")
        seen.add(row[0])
        target = (site / row[0]).resolve()
        require(target.is_relative_to(venv) and target.is_file(), "RECORD target missing or outside venv")
        digest, size = row[1:]
        if not digest:
            require(not size and (target == record.resolve() or "__pycache__" in target.parts),
                    "Unexpected unhashed RECORD member")
            continue
        require(digest.startswith("sha256=") and size.isdecimal(), "Unsupported RECORD hash/size")
        raw = target.read_bytes()
        expected = base64.urlsafe_b64encode(hashlib.sha256(raw).digest()).rstrip(b"=").decode()
        require(digest == "sha256=" + expected and int(size) == len(raw), "RECORD bytes changed")
    require({str(p.relative_to(site)) for p in installed.rglob("*") if p.is_file()
             and "__pycache__" not in p.parts} <= seen, "Package file is absent from RECORD")
    return {"record": pin(record), "entries": len(seen)}


def package_identity(source_package, wheel_path, installed_package):
    source = package_files(source_package, allow_source_caches=True)
    installed = package_files(installed_package)
    require(source == installed, "Source/installed package roster or bytes differ")
    wheel = {}
    with zipfile.ZipFile(wheel_path) as z:
        names = z.namelist()
        require(len(names) == len(set(names)), "Duplicate wheel ZIP member")
        for name in names:
            require(not name.startswith("/") and ".." not in Path(name).parts,
                    "Unsafe wheel member path")
            info = z.getinfo(name)
            require(stat.S_IFMT(info.external_attr >> 16) != stat.S_IFLNK, "Wheel symlink member")
            if name.startswith("cbus_toolkit/") and not name.endswith("/"):
                raw = z.read(name)
                wheel[name[len("cbus_toolkit/"):]] = {
                    "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
    require(source == wheel, "Source/wheel package roster or bytes differ")
    return {"file_count": len(source), "files": source, "wheel": pin(wheel_path),
            "record": verify_record(installed_package)}


def audit_origins(records, launches, pytest_pid, selected_python, installed_package,
                  package_files, *, expected_config_sha256=None):
    require(records and isinstance(pytest_pid, int), "Missing actual pytest origin records")
    selected = Path(selected_python).absolute()
    package = Path(installed_package).resolve()
    prefix = selected.parent.parent.resolve()
    expected = {pytest_pid} | {r["pid"] for r in launches if r.get("role") == "python"}
    require(all(type(r.get("pid")) is int and r.get("role") in {"python", "owned-rust"}
                and r.get("owner_pid") in expected and type(r.get("returncode")) is int
                for r in launches), "Malformed/unreaped/foreign-owner child launch")
    require(len(launches) == len({r["pid"] for r in launches}), "Duplicate child launch PID")
    require(all(r["pid"] != pytest_pid for r in launches), "Root pytest PID appears as its own descendant")
    pending = {r["pid"]: r["owner_pid"] for r in launches if r["role"] == "python"}
    rooted = {pytest_pid}
    while pending:
        ready = {pid for pid, owner in pending.items() if owner in rooted and pid != owner}
        require(ready, "Python launch lineage is not rooted at actual pytest PID")
        rooted.update(ready)
        pending = {pid: owner for pid, owner in pending.items() if pid not in ready}
    by_pid = {}
    for row in records:
        require(isinstance(row, dict) and type(row.get("pid")) is int and row["pid"] in expected,
                "Foreign/malformed origin PID")
        require(row.get("kind") != "violation", "Guard reported an import violation")
        require(row.get("kind") in {"startup", "terminal", "module"}, "Unknown origin event")
        if expected_config_sha256 is not None:
            require(row.get("config_sha256") == expected_config_sha256, "Foreign guard configuration")
        by_pid.setdefault(row["pid"], []).append(row)
        if row["kind"] in {"startup", "terminal"}:
            require(Path(row["executable"]).resolve() == selected.resolve() and
                    Path(row["prefix"]).resolve() == prefix, "Wrong interpreter/venv authority")
        modules = row.get("modules", {})
        require(isinstance(modules, dict), "Invalid module origin map")
        for name, item in modules.items():
            require(name == "cbus_toolkit" or name.startswith("cbus_toolkit."),
                    "Unexpected guarded module name")
            origin = Path(item["path"]).resolve()
            require(origin.is_relative_to(package), "Product imported from outside installed package")
            relative = origin.relative_to(package).as_posix()
            require(relative in package_files and
                    {k: item[k] for k in ("sha256", "bytes")} == package_files[relative],
                    "Imported product bytes differ from frozen installation")
    require(set(by_pid) == expected, "Launched Python process has no guard receipts")
    for pid, rows in by_pid.items():
        kinds = Counter(r["kind"] for r in rows)
        require(kinds["startup"] == kinds["terminal"] == 1, "Missing/duplicate process origin phase")
        require(rows[0]["kind"] == "startup" and rows[-1]["kind"] == "terminal",
                "Process origin phases are out of order")
        terminal = next(r for r in rows if r["kind"] == "terminal")
        startup = rows[0]
        if pid != pytest_pid:
            owner = next(r["owner_pid"] for r in launches if r["pid"] == pid)
            require(type(startup.get("ppid")) is int and startup["ppid"] == owner,
                    "Observed child parent is missing or differs from launch owner")
        require(terminal.get("guard_active") is True, "Guard was disabled before process exit")
        if pid == pytest_pid or any(r.get("role") == "python" and r["pid"] == pid and
                                   r.get("product_cli") for r in launches):
            require("cbus_toolkit" in terminal["modules"], "Product process has no terminal product import")
    rust = [r for r in launches if r.get("role") == "owned-rust"]
    require(all(type(r.get("returncode")) is int for r in rust), "Owned Rust child was not reaped")
    return {"pytest_pid": pytest_pid, "python_processes": len(expected),
            "origin_records": len(records), "product_import_events": sum(r["kind"] == "module" for r in records),
            "owned_rust_children": len(rust), "owned_rust_reaped": len(rust),
            "violations": 0, "scope": "guarded Python launches and observed product module loads"}


def read_jsonl(path):
    data = Path(path).read_bytes()
    require(not data or data.endswith(b"\n"), "Truncated guard JSONL")
    rows = [json.loads(line) for line in data.splitlines()]
    require(all(isinstance(row, dict) for row in rows), "Invalid guard JSONL row")
    return rows


def read_guard(directory):
    directory = Path(directory)
    records = []
    for path in sorted(directory.glob("origins-*.jsonl")):
        rows = read_jsonl(path)
        require(all(path.name == f"origins-{row['pid']}.jsonl" for row in rows),
                "Origin file PID mismatch")
        records.extend(rows)
    launch_rows = []
    for path in sorted(directory.glob("launches-*.jsonl")):
        rows = read_jsonl(path)
        require(all(path.name == f"launches-{row['owner_pid']}.jsonl" for row in rows),
                "Launch file owner mismatch")
        launch_rows.extend(rows)
    paired = {}
    for row in launch_rows:
        key = row["pid"]
        require(row.get("event") in {"launch", "terminal"}, "Unknown child launch event")
        pair = paired.setdefault(key, [])
        pair.append(row)
    launches = []
    for pair in paired.values():
        require(len(pair) == 2 and [r["event"] for r in pair] == ["launch", "terminal"],
                "Child launch lacks ordered terminal record")
        require({k: v for k, v in pair[0].items() if k not in {"event", "returncode"}} ==
                {k: v for k, v in pair[1].items() if k not in {"event", "returncode"}},
                "Child launch identity changed")
        launches.append(pair[1])
    return records, launches


def census_optional_skips(census_path):
    value = json.loads(Path(census_path).read_text())
    matches = {nodeid: [] for nodeid in OPTIONAL_SKIPS}
    def walk(node):
        if isinstance(node, dict):
            if node.get("scope") in matches and "kind" in node and "reason" in node:
                matches[node["scope"]].append({"kind": node["kind"], "reason": node["reason"]})
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)
    walk(value)
    require(all(rows == [OPTIONAL_SKIPS[nodeid]] for nodeid, rows in matches.items()),
            "Optional skip admission does not match current source census")
    return {"census": pin(census_path), "allowed": OPTIONAL_SKIPS}


def add_skip_reasons(receipt, junit_path):
    skipped = {}
    for case in ET.parse(junit_path).getroot().iter("testcase"):
        nodeid = next((p.attrib.get("value") for p in case.findall("./properties/property")
                       if p.attrib.get("name") == "cbus_ci_nodeid"), None)
        skip = case.find("skipped")
        if skip is not None:
            require(nodeid and nodeid not in skipped, "Skipped JUnit case lacks unique node ID")
            # Pytest prefixes unittest decorator reasons with 'Skipped: '.
            message = skip.attrib.get("message", "")
            skipped[nodeid] = message.removeprefix("Skipped: ")
    for case in receipt["cases"]:
        if case["outcome"] == "skipped":
            require(case["id"] in skipped, "Skipped receipt has no raw JUnit reason")
            case["skip_reason"] = skipped[case["id"]]
    return receipt


def source_inputs(repository):
    repository = Path(repository)
    raw = subprocess.check_output(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
                                  cwd=repository)
    result = {}
    for name in sorted(set(os.fsdecode(row) for row in raw.split(b"\0") if row)):
        require(not Path(name).is_absolute() and ".." not in Path(name).parts, "Unsafe repository input")
        path = repository / name
        require(not path.is_symlink() and path.is_file(), "Repository input is missing/non-regular")
        result[name] = pin(path)
    require(result, "No frozen repository inputs")
    return result


def copy_reference(repository, stage, inputs):
    stage = Path(stage)
    stage.mkdir()
    for name, expected in inputs.items():
        target = stage / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(Path(repository) / name, target)
        require(pin(target) == expected and target.stat().st_ino != (Path(repository) / name).stat().st_ino,
                "Reference copy lacks distinct inode or exact bytes")
    return {"files": len(inputs), "distinct_inodes": True, "mode": "regular internal reference copy"}


def copied_inputs(stage, inputs, extras=None):
    extras = extras or {}
    result = {}
    found = {}
    for path in Path(stage).rglob("*"):
        require(not path.is_symlink(), "Reference contains a symlink")
        if path.is_file():
            found[path.relative_to(stage).as_posix()] = pin(path)
    require(set(found) == set(inputs) | set(extras) and
            all(found[name] == expected for name, expected in extras.items()),
            "Reference has undeclared or changed extras")
    for name in inputs:
        path = Path(stage) / name
        require(path.is_file() and not path.is_symlink(), "Reference input is missing/non-regular")
        result[name] = pin(path)
    return result


def clean_environment():
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CBUS_", "PYTEST_"))
           and k not in {"PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"}}
    env.update(PYTHONNOUSERSITE="1", PYTHONDONTWRITEBYTECODE="1")
    return env


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def run_command(argv, *, cwd, env, log, timeout):
    started = time.monotonic()
    with Path(log).open("wb") as handle:
        process = subprocess.Popen([str(v) for v in argv], cwd=cwd, env=env,
                                   stdout=handle, stderr=subprocess.STDOUT, start_new_session=True)
        timed_out = False
        try:
            code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            # This group was created by this invocation, never a shared service group.
            os.killpg(process.pid, signal.SIGTERM)
            try:
                code = process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                code = process.wait()
        # Child processes inherit this freshly created session unless a helper
        # deliberately creates another one. Guard-held Popen handles separately
        # reap recognized Python/Rust children before their own interpreter exits.
        group_cleanup = "already-empty"
        try:
            os.killpg(process.pid, signal.SIGTERM)
            group_cleanup = "sent-SIGTERM-to-owned-command-group"
        except ProcessLookupError:
            pass
    return {"argv": [str(v) for v in argv], "cwd": str(cwd), "pid": process.pid,
            "exit": code, "timed_out": timed_out, "seconds": time.monotonic() - started,
            "group_cleanup": group_cleanup, "log": str(log), "log_pin": pin(log)}


def guard_hook(guard_path, config_path):
    # A literal .pth import works even when a test's child changes PYTHONPATH.
    # It introduces no product sys.path entry and cannot conceal source fallback.
    return ("import importlib.util; _cbi_s=importlib.util.spec_from_file_location('_cbus_owned_interop_guard', "
            + repr(str(guard_path)) + "); _cbi_m=importlib.util.module_from_spec(_cbi_s); "
            "_cbi_s.loader.exec_module(_cbi_m); _cbi_m.activate(" + repr(str(config_path)) + ")\n")


def install_guard(site, guard_path, config_path, config):
    write_json(config_path, config)
    hook = Path(site) / "zz_cbus_owned_interop_guard.pth"
    require(not hook.exists(), "Owned guard hook already exists")
    hook.write_text(guard_hook(guard_path, config_path))
    return {"hook": pin(hook), "guard": pin(guard_path), "config": pin(config_path)}


def load_auditor(path):
    spec = importlib.util.spec_from_file_location("cbus_maintained_ci_auditor", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def positive_timeout(value):
    try:
        seconds = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("Timeout must be a positive integer") from error
    if seconds <= 0:
        raise argparse.ArgumentTypeError("Timeout must be a positive integer")
    return seconds


def argument_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--toolkit-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--mock-bin", type=Path, required=True)
    parser.add_argument("--cmqttd-bin", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--builder-python", type=Path, default=Path(sys.executable))
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--select", action="append", default=None)
    selection.add_argument("--backend", choices=tuple(TARGETS))
    parser.add_argument("--timeout", type=positive_timeout, default=7200)
    return parser


def matrix_main(argv):
    parser = argparse.ArgumentParser(description="Verify two retained full backend wheel epochs; no services")
    parser.add_argument("--summary", action="append", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--toolkit-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--job-result", choices=("success", "failure", "cancelled", "skipped"))
    args = parser.parse_args(argv)
    toolkit = args.toolkit_root.resolve()
    output = args.output.absolute()
    require(not output.resolve().is_relative_to(toolkit.parent) and not output.exists(),
            "Aggregate output must be new and outside the repository")
    output.parent.mkdir(parents=True, exist_ok=True)
    result = {"format": "cbus-installed-rust-interop-matrix-v1", "passed": False}
    try:
        require(args.job_result in (None, "success"), "Hosted backend matrix jobs did not all succeed")
        require(len(args.summary) == 2 and len({p.resolve() for p in args.summary}) == 2,
                "Two distinct backend summary artifacts are required")
        plans = declared_selections((toolkit / "Makefile").read_text())
        auditor = load_auditor(toolkit / "research/ci_test_results.py")
        evidence = [read_backend_evidence(path, plans, auditor) for path in args.summary]
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=toolkit.parent,
                                           text=True).strip()
        inputs = source_inputs(toolkit.parent)
        package = package_files(toolkit / "src/cbus_toolkit", allow_source_caches=True)
        result = audit_backend_matrix(evidence, plans, expected_revision=revision,
                                      expected_inputs=inputs, expected_package=package)
        result["artifacts"] = {value["summary"]["backend"]: value["artifacts"] for value in evidence}
        result["hosted_backend_job_result"] = args.job_result
    except Exception as error:
        result["error"] = {"type": type(error).__name__, "message": str(error)}
    write_json(output, result)
    print(json.dumps({"passed": result["passed"], "scope": result.get("scope"),
                      "error": result.get("error")}, sort_keys=True))
    return 0 if result["passed"] else 1


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "audit-backend-matrix":
        return matrix_main(argv[1:])
    args = argument_parser().parse_args(argv)
    toolkit = args.toolkit_root.resolve()
    repository = toolkit.parent
    output = args.output.absolute()
    require(args.timeout > 0, "Timeout must be positive")
    require(not output.resolve().is_relative_to(repository),
            "Output must be outside the original repository")
    require(not output.exists(), "Output directory already exists; preserve previous attempts")
    output.mkdir(parents=True)
    summary = {"format": FORMAT, "passed": False, "phases": {}, "commands": [],
               "limits": ["Owned Rust servers and installed Python only; no original/native/hardware acceptance",
                          "Focused acceptance does not execute the full configured CI declaration",
                          "Guard checks recognized direct Python/console launches, source-loader imports and terminal loaded modules",
                          "No universal adversarial executed-code or arbitrary non-Python descendant attestation"]}
    commands = summary["commands"]
    def command(name, argv, *, cwd=output, env=None):
        row = run_command(argv, cwd=cwd, env=env or clean_environment(),
                          log=output / (name + ".log"), timeout=args.timeout)
        row["name"] = name
        commands.append(row)
        write_json(output / "commands.json", commands)
        return row
    before = None
    try:
        require(sys.version_info >= (3, 13), "Python 3.13 or newer is required")
        before = source_inputs(repository)
        write_json(output / "source-before.json", before)
        binary_before = {"mock": binary_identity(args.mock_bin), "daemon": binary_identity(args.cmqttd_bin)}
        summary["binaries_before"] = binary_before
        plans = declared_selections((toolkit / "Makefile").read_text())
        chosen, scope = choose_selections(plans, args.select, backend=args.backend)
        summary.update(scope=scope, backend=args.backend, command_timeout_seconds=args.timeout,
                       configured_rosters=plans, selected_rosters=chosen,
                       input_count=len(before), source_revision=subprocess.check_output(
                           ["git", "rev-parse", "HEAD"], cwd=repository, text=True).strip())
        write_json(output / "selections.json", {"configured": plans, "selected": chosen,
                                               "scope": scope, "backend": args.backend})
        skip_admission = census_optional_skips(toolkit / "research/release-gates/skip-census.json")
        summary["optional_skip_admission"] = skip_admission
        stage = output / "reference"
        summary["reference"] = copy_reference(repository, stage, before)
        stage_toolkit = stage / toolkit.name
        # Inert pointer for the maintained audit's revision readback; no Git writes occur.
        gitdir = subprocess.check_output(["git", "rev-parse", "--absolute-git-dir"],
                                          cwd=repository, text=True).strip()
        (stage / ".git").write_text("gitdir: " + gitdir + "\n")
        stage_extras = {".git": pin(stage / ".git")}
        summary["reference"]["permitted_extras"] = stage_extras
        builder = output / "builder-venv"
        require(command("create-builder", [args.builder_python, "-m", "venv", builder])["exit"] == 0,
                "Fresh builder venv creation failed")
        builder_python = builder / "bin/python"
        build_inputs = {name: expected for name, expected in before.items()
                        if name.startswith(toolkit.name + "/src/") or
                        name in {toolkit.name + "/" + part for part in
                                 ("pyproject.toml", "README.md", "COPYING", "COPYING.LESSER")}}
        build_reference = output / "build-reference"
        summary["build_reference"] = copy_reference(repository, build_reference, build_inputs)
        build_toolkit = build_reference / toolkit.name
        assert_quiet(package_files(toolkit / "src/cbus_toolkit", allow_source_caches=True),
                     package_files(build_toolkit / "src/cbus_toolkit"))
        dist = output / "dist"
        require(command("build-wheel", [builder_python, "-m", "pip", "wheel", "--no-deps",
                                         "--wheel-dir", dist, build_toolkit])["exit"] == 0,
                "Fresh wheel build failed")
        wheels = list(dist.glob("cbus_toolkit_cli-*.whl"))
        require(len(wheels) == 1, "Expected one freshly built Toolkit wheel")
        wheel = wheels[0]
        venv = output / "venv"
        require(command("create-installed", [args.builder_python, "-m", "venv", venv])["exit"] == 0,
                "Fresh installed venv creation failed")
        python = venv / "bin/python"
        require(command("install-wheel", [python, "-m", "pip", "install", "--no-compile",
                   str(wheel) + "[test,research,serial,usb,firmware,network]"])["exit"] == 0,
                "Wheel/all-supported-extras installation failed")
        sites = list((venv / "lib").glob("python*/site-packages"))
        require(len(sites) == 1, "Fresh venv site-packages is ambiguous")
        site = sites[0]
        installed = site / "cbus_toolkit"
        package = package_identity(toolkit / "src/cbus_toolkit", wheel, installed)
        summary["package_before"] = package
        write_json(output / "package-before.json", package)
        guard = Path(__file__).with_name("installed_interop_guard.py")
        guard_pin = pin(guard)
        auditor_path = toolkit / "research/ci_test_results.py"
        summary["runner_inputs"] = {"runner": pin(__file__), "guard": guard_pin,
                                    "auditor": pin(auditor_path)}
        auditor = load_auditor(auditor_path)
        base_env = clean_environment()
        base_env.update(CBUS_CGATE_MOCK_BIN=str(args.mock_bin.absolute()),
                        CBUS_CMQTTD_BIN=str(args.cmqttd_bin.absolute()),
                        PATH=str(python.parent) + os.pathsep + base_env.get("PATH", ""),
                        PYTHONPATH=str(stage_toolkit) + os.pathsep + str(stage_toolkit / "tests"))
        temporary = output / "tmp"
        temporary.mkdir()
        base_env.update(TMPDIR=str(temporary), TMP=str(temporary), TEMP=str(temporary))
        hook = site / "zz_cbus_owned_interop_guard.pth"
        for backend, plan in chosen.items():
            phase = output / backend
            phase.mkdir()
            work = phase / "work"
            work.mkdir()
            config_path = phase / "collect-guard-config.json"
            config = {"format": "cbus-installed-interop-guard-v1", "python": str(python),
                      "installed_package": str(installed), "package_files": package["files"],
                      "origin_directory": str(phase / "collect-origins"),
                      "binary_resolved": [v["resolved"] for v in binary_before.values()]}
            if hook.exists():
                hook.unlink()  # Only this runner's fresh venv hook, never a shared environment.
            guard_inputs = install_guard(site, guard, config_path, config)
            phase_summary = {"guard_inputs": guard_inputs}
            summary["phases"][backend] = phase_summary
            collection_trace = phase / "collection-trace.json"
            common = [python, "-m", "pytest", "-p", "research.ci_test_results",
                      "--rootdir", stage_toolkit, "--basetemp", phase / "pytest-tmp",
                      "-o", "cache_dir=" + str(phase / "pytest-cache")]
            selectors = [str(stage_toolkit / s.split("::", 1)[0]) +
                         ("::" + s.split("::", 1)[1] if "::" in s else "") for s in plan["selectors"]]
            collect = command(backend + "-collect", [*common, "--collect-only", "-q",
                              "--cbus-ci-trace=" + str(collection_trace), *selectors],
                              cwd=work, env=base_env)
            phase_summary["collection"] = collect
            require(collect["exit"] == 0, "Declared selection collection failed")
            collection = json.loads(collection_trace.read_text())
            expected = collection["collected"]
            require(expected and len(expected) == len(set(expected)) and not collection["deselected"],
                    "Collection closure is empty/duplicate/deselected")
            require(set(plan["required_ids"]) <= set(expected) and all(
                n in plan["required_ids"] or n.split("::", 1)[0] in plan["whole_modules"] for n in expected),
                    "Collection is outside exact declared selectors")
            collect_records, collect_launches = read_guard(config["origin_directory"])
            collect_origins = audit_origins(collect_records, collect_launches, collect["pid"], python,
                                           installed, package["files"],
                                           expected_config_sha256=guard_inputs["config"]["sha256"])
            config["origin_directory"] = str(phase / "origins")
            config_path = phase / "pytest-guard-config.json"
            hook.unlink()
            pytest_guard = install_guard(site, guard, config_path, config)
            config_pin = pin(config_path)
            trace, junit = phase / "trace.json", phase / "junit.xml"
            executed = command(backend + "-pytest", [*common, "-q", "-ra",
                                "--cbus-ci-trace=" + str(trace), "--junitxml=" + str(junit),
                                *selectors], cwd=work, env=base_env)
            phase_summary["pytest"] = executed
            maintained = add_skip_reasons(auditor.audit(junit, trace, plan["required_modules"]), junit)
            write_json(phase / "audit-receipt.json", maintained)
            phase_summary["actual_parent_counts"] = dict(Counter(c["outcome"] for c in maintained["cases"]))
            phase_summary["unitemized_subtests"] = maintained["unitemized_subtests"]
            # Every core case in the actual collection must pass, except exactly two census skips.
            required = sorted(set(expected) - (set(OPTIONAL_SKIPS) - set(plan["required_ids"])))
            selected = audit_selection(maintained, required, plan["required_modules"], OPTIONAL_SKIPS,
                                       expected_collected=expected)
            require(executed["exit"] == 0 and not executed["timed_out"], "Pytest process did not pass")
            records, launches = read_guard(config["origin_directory"])
            origins = audit_origins(records, launches, executed["pid"], python, installed,
                                    package["files"], expected_config_sha256=config_pin["sha256"])
            require(pin(guard) == guard_pin and pin(config_path) == config_pin and
                    pin(hook) == pytest_guard["hook"], "Owned guard inputs changed")
            phase_summary.update({"selection": selected, "origins": origins,
                "pytest_guard_inputs": pytest_guard,
                "collection_origins": collect_origins, "pytest": executed,
                "collection": collect, "collection_trace": pin(collection_trace),
                "junit": pin(junit), "trace": pin(trace), "maintained_audit": pin(phase / "audit-receipt.json")})
            phase_summary["guard_data_files"] = {
                p.relative_to(phase).as_posix(): pin(p) for p in phase.rglob("*.jsonl")}
        # One installed console smoke is separate from declared test-body counts.
        smoke = output / "console-origins"
        config["origin_directory"] = str(smoke)
        config_path = output / "console-guard-config.json"
        hook.unlink()
        summary["console_guard_inputs"] = install_guard(site, guard, config_path, config)
        console_env = {k: v for k, v in base_env.items() if k != "PYTHONPATH"}
        console = command("installed-console-help", [venv / "bin/cbus-toolkit", "--help"], env=console_env)
        require(console["exit"] == 0, "Installed console help failed")
        records, launches = read_guard(smoke)
        summary["console"] = {"command": console, "origins": audit_origins(records, launches,
            console["pid"], python, installed, package["files"], expected_config_sha256=pin(config_path)["sha256"])}
        summary["package_after"] = package_identity(toolkit / "src/cbus_toolkit", wheel, installed)
        assert_quiet(package, summary["package_after"])
        assert_quiet(before, source_inputs(repository))
        assert_quiet(before, copied_inputs(stage, before, stage_extras))
        summary["binaries_after"] = {"mock": binary_identity(args.mock_bin), "daemon": binary_identity(args.cmqttd_bin)}
        assert_quiet(binary_before, summary["binaries_after"])
        summary.update(passed=True, source_quiet=True, copied_reference_quiet=True, binaries_quiet=True)
    except Exception as error:
        summary["error"] = {"type": type(error).__name__, "message": str(error)}
    finally:
        if before is not None:
            try:
                after = source_inputs(repository)
                write_json(output / "source-after.json", after)
                summary["source_quiet"] = after == before
                if not summary["source_quiet"]:
                    summary["passed"] = False
                    summary["terminal_input_error"] = "Frozen source map changed"
            except Exception as error:
                summary["source_quiet"] = False
                summary["passed"] = False
                summary["terminal_input_error"] = type(error).__name__
        write_json(output / "summary.json", summary)
    print(json.dumps({"format": FORMAT, "passed": summary["passed"], "scope": summary.get("scope"),
                      "error": summary.get("error"), "output": str(output)}, sort_keys=True))
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
