"""Independent installed-wheel runner tests with tiny package/process fixtures.

No Rust binary, original/vendor software, C-Gate service or hardware is executed.
Required fixture IDs and the maintained ef677 roster digests are literal.
"""
from __future__ import annotations
import base64
import copy
import csv
import hashlib
import importlib.util
import io
import json
import marshal
import os
from pathlib import Path
import stat
import struct
import subprocess
import sys
import venv
import zipfile
import xml.etree.ElementTree as ET
import pytest

REQUIRED_IDS = (
    "tests/test_fixture_owned.py::test_alpha[mock]",
    "tests/test_fixture_owned.py::test_beta[daemon]",
)
REQUIRED_MODULE = "tests/test_fixture_owned.py"
PACKAGE_BYTES = {
    "cbus_toolkit/__init__.py": b"MARKER = 'fixture-installed'\n",
    "cbus_toolkit/probe.py": b"MARKER = 'fixture-probe'\n",
    "cbus_toolkit/cli.py": (
        b"import json\nfrom . import probe\n"
        b"def main():\n    print(json.dumps({'probe': probe.MARKER}))\n    return 0\n"
    ),
    "cbus_toolkit/__main__.py": b"from .cli import main\nraise SystemExit(main())\n",
}


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def write_json(path: Path, value) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    return path


def wheel_fixture(root: Path) -> dict:
    """Construct a valid tiny wheel and its extracted install/source layouts.

    The install layout is a fixture unpacking, not evidence that a product
    installer or the product package was exercised. Actual interpreter/guard
    tests import these bytes and compare their distinct origins.
    """
    installed = root / ("environment/lib/python" + str(sys.version_info.major) + "." + str(sys.version_info.minor) + "/site-packages")
    source = root / "checkout/src"
    dist_info = "cbus_toolkit_cli-0.0.0.dist-info"
    entries = dict(PACKAGE_BYTES)
    entries[dist_info + "/METADATA"] = (
        b"Metadata-Version: 2.1\nName: cbus-toolkit-cli\nVersion: 0.0.0\n"
    )
    entries[dist_info + "/WHEEL"] = (
        b"Wheel-Version: 1.0\nGenerator: independent-fixture\n"
        b"Root-Is-Purelib: true\nTag: py3-none-any\n"
    )
    record_name = dist_info + "/RECORD"
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    for name, payload in sorted(entries.items()):
        encoded = base64.urlsafe_b64encode(hashlib.sha256(payload).digest()).rstrip(b"=").decode()
        writer.writerow((name, "sha256=" + encoded, str(len(payload))))
    writer.writerow((record_name, "", ""))
    entries[record_name] = stream.getvalue().encode()
    wheel = root / "cbus_toolkit_cli-0.0.0-py3-none-any.whl"
    wheel.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(wheel, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in sorted(entries.items()):
            archive.writestr(name, payload)
    for name, payload in entries.items():
        destination = installed / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
    for name, payload in PACKAGE_BYTES.items():
        destination = source / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
    return {
        "wheel": wheel,
        "installed": installed,
        "package": installed / "cbus_toolkit",
        "source": source,
        "record": installed / record_name,
        "package_hashes": {name: sha256(payload) for name, payload in PACKAGE_BYTES.items()},
    }


def pytest_evidence(root: Path, *, ids=REQUIRED_IDS, outcomes=None,
                    deselected=(), missing_calls=(), exitstatus=0,
                    reported_subtests=0) -> dict:
    """Literal JUnit/trace inputs, independent of the runner's receipt writer."""
    ids = tuple(ids)
    outcomes = outcomes or {}
    values = {nodeid: outcomes.get(nodeid, "passed") for nodeid in ids}
    counts = {"tests": len(ids) + reported_subtests, "errors": 0,
              "failures": sum(value == "failed" for value in values.values()),
              "skipped": sum(value == "skipped" for value in values.values())}
    suite = ET.Element("testsuite", {key: str(value) for key, value in counts.items()})
    suite.set("name", "independent-fixture")
    suite.set("time", "0.01")
    for nodeid in ids:
        case = ET.SubElement(suite, "testcase", {
            "classname": "test_fixture_owned", "name": nodeid.split("::", 1)[1],
            "time": "0.001",
        })
        props = ET.SubElement(case, "properties")
        ET.SubElement(props, "property", {"name": "cbus_ci_nodeid", "value": nodeid})
        if values[nodeid] == "failed":
            ET.SubElement(case, "failure", {"message": "literal failure"})
        elif values[nodeid] == "skipped":
            ET.SubElement(case, "skipped", {"type": "pytest.skip", "message": "literal skip"})
    junit = root / "junit.xml"
    root.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(suite).write(junit, encoding="utf-8", xml_declaration=True)
    calls = [{"id": nodeid, "outcome": values[nodeid]} for nodeid in ids
             if nodeid not in missing_calls]
    calls += [{"id": ids[0], "outcome": "passed"} for _ in range(reported_subtests)]
    trace = write_json(root / "trace.json", {
        "format": "cbus-ci-pytest-trace-v1", "collected": list(ids),
        "deselected": list(deselected), "started": list(ids),
        "call_events": calls, "session_exitstatus": exitstatus,
    })
    return {"junit": junit, "trace": trace, "ids": ids}


@pytest.fixture(scope="module")
def runner():
    default = Path(__file__).resolve().parents[1] / "research/installed_rust_interop.py"
    selected = Path(os.environ.get("CBUS_INSTALLED_INTEROP_HELPER", str(default)))
    spec = importlib.util.spec_from_file_location("independent_runner_under_test", selected)
    assert spec and spec.loader, "runner helper was not supplied"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MAKE_LITERAL = """check-cgate-interop: compile
\tCBUS_CGATE_MOCK_BIN=fixture python -m pytest \\
\t  'tests/test_fixture_owned.py::test_alpha[mock]' \\
\t  tests/test_core_mock.py -q

check-cmqtt-interop: compile
\tCBUS_CMQTTD_BIN=fixture python -m pytest \\
\t  'tests/test_fixture_owned.py::test_beta[daemon]' \\
\t  tests/test_core_daemon.py -q

"""


def good_receipt():
    return {
        "format": "cbus-ci-test-results-v1", "passed": True, "pytest_exit": 0,
        "collected": list(REQUIRED_IDS), "started": list(REQUIRED_IDS),
        "cases": [{"id": nodeid, "outcome": "passed"} for nodeid in REQUIRED_IDS],
        "call_events": [{"id": nodeid, "outcome": "passed", "ordinal": 1}
                        for nodeid in REQUIRED_IDS],
        "unitemized_subtests": {"reported": 0, "passed": 0, "skipped": 0,
                                "failures": 0, "errors": 0},
        "deselected": [],
    }


def test_declared_fixture_selectors_are_literal_and_include_whole_modules(runner):
    plans = runner.declared_selections(MAKE_LITERAL)
    assert plans["mock"]["selectors"] == [REQUIRED_IDS[0], "tests/test_core_mock.py"]
    assert plans["daemon"]["selectors"] == [REQUIRED_IDS[1], "tests/test_core_daemon.py"]
    assert plans["mock"]["required_ids"] == [REQUIRED_IDS[0]]
    assert plans["daemon"]["required_ids"] == [REQUIRED_IDS[1]]


def test_complete_baseline_preserves_991_explicit_ids_and_seven_modules(runner):
    make = Path(os.environ.get("CBUS_INSTALLED_INTEROP_BASE_MAKE",
        str(Path(__file__).resolve().parents[1] / "Makefile")))
    plans = runner.declared_selections(make.read_text())
    # Keep the exact inherited declaration digest; new CGL and SAFE IDs have their own roster guards.
    for plan in plans.values():
        for key in ("required_ids", "quoted_ids"):
            plan[key] = [n for n in plan[key] if not n.startswith((
                "tests/test_cgl_application_order_backends.py::",
                "tests/test_application_copy_safe_backends.py::",
                "tests/test_application_safe_set_backends.py::",
                "tests/test_ordinary_level_value_backends.py::",
                "tests/test_ordinary_level_value_followon_backends.py::"))]
    ids = sorted(n for p in plans.values() for n in p["required_ids"])
    quoted = sorted(n for p in plans.values() for n in p["quoted_ids"])
    assert len(ids) == 991 and len(quoted) == 985
    assert hashlib.sha256(("\n".join(ids) + "\n").encode()).hexdigest() == "539e4cf03c21396a01e34a0a37cc827ec8e472e4a4c62639611343f1ccc31e01"
    assert hashlib.sha256(("\n".join(quoted) + "\n").encode()).hexdigest() == "b273185b93de0e55afec47efffd84ae0fab671ad65e35bae1d233a2c89877003"
    assert sum(len(p["whole_modules"]) for p in plans.values()) == 7
    assert plans["mock"]["whole_modules"] == ["tests/test_rust_cgate_interop.py"]
    assert plans["daemon"]["whole_modules"] == [
        "tests/test_cmqtt_interop.py", "tests/test_cmqtt_programming_methods_interop.py",
        "tests/test_cmqtt_dali_commissioning_interop.py", "tests/test_cmqtt_network_new_cli.py",
        "tests/test_cmqtt_network_save_db_cli.py", "tests/test_cgate_file_upload.py",
    ]


@pytest.mark.parametrize("selects", [[], [REQUIRED_IDS[0], REQUIRED_IDS[0]],
                                    ["tests/test_unregistered.py"], [""], [None]])
def test_empty_duplicate_and_foreign_focus_refuse(runner, selects):
    with pytest.raises(runner.GateError):
        runner.choose_selections(runner.declared_selections(MAKE_LITERAL), selects)


def test_default_and_explicit_selection_keep_distinct_scope(runner):
    plans = runner.declared_selections(MAKE_LITERAL)
    chosen, scope = runner.choose_selections(plans)
    assert chosen == plans and scope == "full-maintained-declaration"
    chosen, scope = runner.choose_selections(plans, [REQUIRED_IDS[1]])
    assert scope == "focused-explicit-subset"
    assert set(chosen) == {"daemon"}
    assert chosen["daemon"]["selectors"] == [REQUIRED_IDS[1]]


def test_registered_core_module_is_an_admissible_focused_body(runner):
    chosen, scope = runner.choose_selections(
        runner.declared_selections(MAKE_LITERAL), ["tests/test_core_mock.py"])
    assert chosen["mock"]["required_ids"] == []
    assert scope == "focused-explicit-subset"
    nodeid = "tests/test_core_mock.py::test_literal_core_body"
    receipt = good_receipt()
    for key in ("collected", "started"):
        receipt[key] = [nodeid]
    receipt["cases"] = [{"id": nodeid, "outcome": "passed"}]
    receipt["call_events"] = [{"id": nodeid, "outcome": "passed", "ordinal": 1}]
    result = runner.audit_selection(receipt, [], ["tests/test_core_mock.py"])
    assert result["required_passed"] == 0 and result["parent_total"] == 1


def test_two_required_literal_bodies_pass(runner):
    result = runner.audit_selection(good_receipt(), list(REQUIRED_IDS), [REQUIRED_MODULE])
    assert result["required_passed"] == 2
    assert result["parent_counts"] == {"passed": 2}
    assert result["parent_total"] == 2


@pytest.mark.parametrize("mutation", ["missing", "empty", "duplicate", "call-missing",
                                      "call-skipped", "call-failed", "setup-skipped",
                                      "exit-nonzero", "identity-mismatch"])
def test_required_body_failure_cannot_hide_behind_other_passes(runner, mutation):
    r = good_receipt()
    if mutation == "missing":
        r["collected"].pop(); r["started"].pop(); r["cases"].pop(); r["call_events"].pop()
    elif mutation == "empty":
        for key in ("collected", "started", "cases", "call_events"):
            r[key] = []
    elif mutation == "duplicate":
        r["cases"].append(copy.deepcopy(r["cases"][0]))
    elif mutation == "call-missing":
        r["call_events"].pop()
    elif mutation == "call-skipped":
        r["call_events"][-1]["outcome"] = "skipped"
    elif mutation == "call-failed":
        r["call_events"][-1]["outcome"] = "failed"
    elif mutation == "setup-skipped":
        r["cases"][-1]["outcome"] = "skipped"; r["call_events"].pop()
    elif mutation == "exit-nonzero":
        r["pytest_exit"] = 1
    elif mutation == "identity-mismatch":
        r["started"][-1] = "tests/test_unrelated.py::test_passed"
    with pytest.raises(runner.GateError):
        runner.audit_selection(r, list(REQUIRED_IDS), [REQUIRED_MODULE])


def test_optional_skip_never_excuses_an_explicit_required_id(runner):
    r = good_receipt()
    r["cases"][-1]["outcome"] = "skipped"; r["call_events"].pop()
    with pytest.raises(runner.GateError):
        runner.audit_selection(r, list(REQUIRED_IDS), [REQUIRED_MODULE], [REQUIRED_IDS[1]])


def test_raw_deselection_refuses_at_maintained_auditor_boundary(tmp_path):
    path = Path(__file__).resolve().parents[1] / "research/ci_test_results.py"
    spec = importlib.util.spec_from_file_location("independent_raw_results_auditor", path)
    assert spec and spec.loader
    auditor = importlib.util.module_from_spec(spec); spec.loader.exec_module(auditor)
    evidence = pytest_evidence(tmp_path, deselected=["tests/test_fixture_owned.py::test_gamma"])
    with pytest.raises(auditor.AuditError, match="deselected"):
        auditor.audit(evidence["junit"], evidence["trace"], [REQUIRED_MODULE])


def test_subtest_occurrences_do_not_become_individual_parent_identities(runner):
    r = good_receipt()
    r["call_events"].append({"id": REQUIRED_IDS[0], "outcome": "passed", "ordinal": 2})
    r["unitemized_subtests"] = {"reported": 1, "passed": 1, "skipped": 0,
                               "failures": 0, "errors": 0}
    result = runner.audit_selection(r, list(REQUIRED_IDS), [REQUIRED_MODULE])
    assert result["parent_total"] == 2
    assert result["unitemized_subtests"]["passed"] == 1


def test_missing_nonexecutable_binary_is_preflight_refusal(runner, tmp_path):
    with pytest.raises(runner.GateError):
        runner.binary_identity(tmp_path / "missing-fixture")
    binary = tmp_path / "fixture-bin"; binary.write_bytes(b"fixture bytes only\n")
    binary.chmod(0o600)
    with pytest.raises(runner.GateError):
        runner.binary_identity(binary)


def test_binary_pin_change_fails_quietness(runner, tmp_path):
    binary = tmp_path / "fixture-bin"; binary.write_bytes(b"fixture version one\n")
    binary.chmod(0o700)
    before = runner.binary_identity(binary)
    binary.write_bytes(b"fixture version two\n")
    with pytest.raises(runner.GateError):
        runner.assert_quiet(before, runner.binary_identity(binary))


def test_fixture_package_wheel_install_record_are_equal(runner, tmp_path):
    f = wheel_fixture(tmp_path)
    result = runner.package_identity(f["source"] / "cbus_toolkit", f["wheel"], f["package"])
    assert result["file_count"] == 4
    assert result["record"]["entries"] == 7


@pytest.mark.parametrize("mutation", ["source-bytes", "installed-bytes", "extra-module",
                                      "missing-module", "record-hash", "record-missing",
                                      "duplicate-wheel", "wheel-bytes", "escaped-wheel"])
def test_package_record_and_roster_attacks_refuse(runner, tmp_path, mutation):
    f = wheel_fixture(tmp_path)
    if mutation == "source-bytes":
        (f["source"] / "cbus_toolkit/probe.py").write_bytes(b"changed source\n")
    elif mutation == "installed-bytes":
        (f["package"] / "probe.py").write_bytes(b"changed install\n")
    elif mutation == "extra-module":
        (f["package"] / "unrecorded.py").write_bytes(b"unrecorded\n")
    elif mutation == "missing-module":
        (f["package"] / "probe.py").unlink()
    elif mutation == "record-hash":
        f["record"].write_text(f["record"].read_text().replace("sha256=", "sha256=X", 1))
    elif mutation == "record-missing":
        f["record"].write_text("\n".join(line for line in f["record"].read_text().splitlines()
                                      if not line.startswith("cbus_toolkit/probe.py,")) + "\n")
    elif mutation == "duplicate-wheel":
        with zipfile.ZipFile(f["wheel"], "a") as z:
            z.writestr("cbus_toolkit/probe.py", b"duplicate\n")
    elif mutation == "wheel-bytes":
        replacement = tmp_path / "changed.whl"
        with zipfile.ZipFile(f["wheel"]) as before, zipfile.ZipFile(replacement, "w") as after:
            for name in before.namelist():
                after.writestr(name, b"changed\n" if name == "cbus_toolkit/probe.py" else before.read(name))
        f["wheel"] = replacement
    elif mutation == "escaped-wheel":
        with zipfile.ZipFile(f["wheel"], "a") as z:
            z.writestr("../outside.py", b"outside\n")
    with pytest.raises(runner.GateError):
        runner.package_identity(f["source"] / "cbus_toolkit", f["wheel"], f["package"])


def origins_fixture(runner, tmp_path):
    f = wheel_fixture(tmp_path)
    selected = tmp_path / "environment/bin/python"
    selected.parent.mkdir(parents=True); selected.symlink_to(sys.executable)
    files = runner.package_files(f["package"])
    config = "a" * 64
    modules = {"cbus_toolkit": {"path": str(f["package"] / "__init__.py"), **files["__init__.py"]}}
    records = [{"kind": kind, "pid": pid, "ppid": 0 if pid == 101 else 101, "config_sha256": config,
                "executable": str(selected), "prefix": str(selected.parent.parent),
                "modules": copy.deepcopy(modules), "guard_active": True}
               for pid in (101, 102) for kind in ("startup", "terminal")]
    launches = [{"pid": 102, "owner_pid": 101, "role": "python",
                 "product_cli": True, "returncode": 0}]
    return f, selected, files, config, records, launches


def test_actual_parent_and_cli_child_need_distinct_phase_pairs(runner, tmp_path):
    f, py, files, config, records, launches = origins_fixture(runner, tmp_path)
    result = runner.audit_origins(records, launches, 101, py, f["package"], files,
                                  expected_config_sha256=config)
    assert result["python_processes"] == 2 and result["origin_records"] == 4
    assert result["violations"] == 0


@pytest.mark.parametrize("mutation", ["source-same-bytes", "mixed-submodule", "child-no-record",
                                      "child-startup-only", "duplicate-terminal", "foreign-pid",
                                      "wrong-interpreter", "wrong-prefix", "foreign-config",
                                      "guard-disabled", "violation", "module-bytes",
                                      "unreaped-rust"])
def test_child_origin_or_cleanup_holes_refuse(runner, tmp_path, mutation):
    f, py, files, config, rows, launches = origins_fixture(runner, tmp_path)
    if mutation == "source-same-bytes":
        rows[-1]["modules"]["cbus_toolkit"]["path"] = str(f["source"] / "cbus_toolkit/__init__.py")
    elif mutation == "mixed-submodule":
        rows[-1]["modules"]["cbus_toolkit.probe"] = {
            "path": str(f["source"] / "cbus_toolkit/probe.py"), **files["probe.py"]}
    elif mutation == "child-no-record":
        rows = rows[:2]
    elif mutation == "child-startup-only":
        rows.pop()
    elif mutation == "duplicate-terminal":
        rows.append(copy.deepcopy(rows[-1]))
    elif mutation == "foreign-pid":
        rows[-1]["pid"] = 103
    elif mutation == "wrong-interpreter":
        wrong = tmp_path / "wrong-python"; wrong.write_bytes(b"not the selected interpreter\n")
        rows[-1]["executable"] = str(wrong)
    elif mutation == "wrong-prefix":
        rows[-1]["prefix"] = str(tmp_path / "wrong-venv")
    elif mutation == "foreign-config":
        rows[-1]["config_sha256"] = "b" * 64
    elif mutation == "guard-disabled":
        rows[-1]["guard_active"] = False
    elif mutation == "violation":
        rows.append({"pid": 102, "kind": "violation", "config_sha256": config})
    elif mutation == "module-bytes":
        rows[-1]["modules"]["cbus_toolkit"]["sha256"] = "b" * 64
    elif mutation == "unreaped-rust":
        launches.append({"pid": 201, "owner_pid": 101, "role": "owned-rust", "returncode": None})
    with pytest.raises(runner.GateError):
        runner.audit_origins(rows, launches, 101, py, f["package"], files,
                             expected_config_sha256=config)


def test_python_child_must_be_reaped_not_just_have_terminal_imports(runner, tmp_path):
    f, py, files, config, rows, launches = origins_fixture(runner, tmp_path)
    launches[0]["returncode"] = None
    with pytest.raises(runner.GateError):
        runner.audit_origins(rows, launches, 101, py, f["package"], files,
                             expected_config_sha256=config)


def test_launch_owner_must_be_an_observed_guarded_process(runner, tmp_path):
    f, py, files, config, rows, launches = origins_fixture(runner, tmp_path)
    launches[0]["owner_pid"] = 999
    with pytest.raises(runner.GateError):
        runner.audit_origins(rows, launches, 101, py, f["package"], files,
                             expected_config_sha256=config)


def test_terminal_before_startup_is_not_a_completed_process(runner, tmp_path):
    f, py, files, config, rows, launches = origins_fixture(runner, tmp_path)
    rows[-2:] = rows[-2:][::-1]
    with pytest.raises(runner.GateError):
        runner.audit_origins(rows, launches, 101, py, f["package"], files,
                             expected_config_sha256=config)


@pytest.mark.parametrize("mutation", ["dangling-symlink", "directory-symlink", "package-bytecache"])
def test_package_hidden_symlink_and_bytecache_refuse(runner, tmp_path, mutation):
    f = wheel_fixture(tmp_path)
    if mutation == "dangling-symlink":
        (f["package"] / "phantom.py").symlink_to(tmp_path / "missing.py")
    elif mutation == "directory-symlink":
        outside = tmp_path / "outside"; outside.mkdir()
        (outside / "probe.py").write_bytes(b"outside fixture only\n")
        (f["package"] / "unassessed").symlink_to(outside, target_is_directory=True)
    elif mutation == "package-bytecache":
        cache = f["package"] / "__pycache__"; cache.mkdir()
        (cache / "__init__.cpython-313.pyc").write_bytes(b"preexisting bytecode must refuse\n")
    with pytest.raises(runner.GateError):
        runner.package_identity(f["source"] / "cbus_toolkit", f["wheel"], f["package"])


@pytest.mark.parametrize("optional,reason", [
    ("tests/test_rust_cgate_interop.py::RustInteropTests::test_edlt_lighting_programming_round_trip",
     "vendor unitspec directory is absent"),
    ("tests/test_cmqtt_programming_methods_interop.py::test_protection_matrix_matches_a_fresh_derivation",
     "Set CBUS_UNITSPEC_DIR to re-derive the matrix from decoded specs"),
])
def test_optional_skip_has_exact_nonrequired_identity_and_reason(runner, optional, reason):
    r = good_receipt()
    module = optional.split("::", 1)[0]
    core_body = module + "::test_fixture_other_passing_body"
    r["collected"].append(core_body); r["started"].append(core_body)
    r["cases"].append({"id": core_body, "outcome": "passed"})
    r["call_events"].append({"id": core_body, "outcome": "passed", "ordinal": 1})
    r["collected"].append(optional); r["started"].append(optional)
    r["cases"].append({"id": optional, "outcome": "skipped", "skip_reason": reason})
    assert runner.OPTIONAL_SKIPS[optional]["reason"] == reason
    result = runner.audit_selection(r, list(REQUIRED_IDS), [REQUIRED_MODULE, module], runner.OPTIONAL_SKIPS)
    assert result["optional_skipped_ids"] == [optional]
    r["cases"][-1]["skip_reason"] = reason + " (different)"
    with pytest.raises(runner.GateError):
        runner.audit_selection(r, list(REQUIRED_IDS), [REQUIRED_MODULE, module], runner.OPTIONAL_SKIPS)
    r["cases"][-1]["skip_reason"] = reason
    with pytest.raises(runner.GateError):
        runner.audit_selection(r, list(REQUIRED_IDS) + [optional], [REQUIRED_MODULE, module], runner.OPTIONAL_SKIPS)


@pytest.mark.parametrize("artifact", ["junit", "trace"])
def test_truncated_raw_evidence_refuses(tmp_path, artifact):
    path = Path(__file__).resolve().parents[1] / "research/ci_test_results.py"
    spec = importlib.util.spec_from_file_location("independent_truncated_results_auditor", path)
    assert spec and spec.loader
    auditor = importlib.util.module_from_spec(spec); spec.loader.exec_module(auditor)
    evidence = pytest_evidence(tmp_path)
    damaged = evidence[artifact]
    damaged.write_bytes(damaged.read_bytes()[: max(1, damaged.stat().st_size // 2)])
    with pytest.raises((ValueError, __import__("xml.etree.ElementTree", fromlist=["ParseError"]).ParseError)):
        auditor.audit(evidence["junit"], evidence["trace"], [REQUIRED_MODULE])


@pytest.mark.parametrize("mutation", ["self-parent", "disconnected-cycle", "wrong-parent", "root-as-child"])
def test_child_lineage_is_rooted_in_actual_pytest_pid(runner,tmp_path,mutation):
    f,py,files,config,rows,launches=origins_fixture(runner,tmp_path)
    if mutation=="self-parent":
        launches[0]["owner_pid"]=102
        for row in rows:
            if row["pid"]==102: row["ppid"]=102
    elif mutation=="disconnected-cycle":
        third=[{**copy.deepcopy(row),"pid":103,"ppid":102} for row in rows if row["pid"]==102]
        rows.extend(third)
        launches[0]["owner_pid"]=103
        for row in rows:
            if row["pid"]==102: row["ppid"]=103
        launches.append({"pid":103,"owner_pid":102,"role":"python","product_cli":False,"returncode":0})
    elif mutation=="wrong-parent":
        for row in rows:
            if row["pid"]==102: row["ppid"]=999
    elif mutation=="root-as-child":
        launches.append({"pid":101,"owner_pid":102,"role":"python","product_cli":False,"returncode":0})
    with pytest.raises(runner.GateError):
        runner.audit_origins(rows,launches,101,py,f["package"],files,expected_config_sha256=config)


def test_unexpected_within_module_body_does_not_expand_exact_selected_roster(runner):
    r=good_receipt(); extra=REQUIRED_MODULE+"::test_unrequested"
    r["collected"].append(extra);r["started"].append(extra)
    r["cases"].append({"id":extra,"outcome":"passed"})
    r["call_events"].append({"id":extra,"outcome":"passed","ordinal":1})
    with pytest.raises(runner.GateError):
        runner.audit_selection(r,list(REQUIRED_IDS),[REQUIRED_MODULE],expected_collected=list(REQUIRED_IDS))


@pytest.mark.parametrize("mutation", ["truncated-last-line", "non-object", "wrong-pid-filename",
                                      "missing-launch-terminal", "changed-launch-identity"])
def test_guard_raw_jsonl_and_launch_pair_integrity_refuse(runner,tmp_path,mutation):
    origins=tmp_path/"origins-101.jsonl"
    origins.write_text(json.dumps({"pid":101,"kind":"startup"})+"\n")
    launch={"pid":102,"owner_pid":101,"event":"launch","role":"python",
            "product_cli":True,"returncode":None,"argv":["fixture-python"]}
    terminal={**launch,"event":"terminal","returncode":0}
    path=tmp_path/"launches-101.jsonl"
    path.write_text(json.dumps(launch)+"\n"+json.dumps(terminal)+"\n")
    if mutation=="truncated-last-line":
        origins.write_text('{"pid":101,"kind":"startup"}')
    elif mutation=="non-object":
        origins.write_text('[101,"startup"]\n')
    elif mutation=="wrong-pid-filename":
        origins.write_text(json.dumps({"pid":999,"kind":"startup"})+"\n")
    elif mutation=="missing-launch-terminal":
        path.write_text(json.dumps(launch)+"\n")
    elif mutation=="changed-launch-identity":
        terminal["owner_pid"]=999
        path.write_text(json.dumps(launch)+"\n"+json.dumps(terminal)+"\n")
    with pytest.raises(runner.GateError):
        runner.read_guard(tmp_path)


def test_installed_package_root_symlink_is_not_regular_authority(runner,tmp_path):
    f=wheel_fixture(tmp_path)
    alternate=tmp_path/"environment/alternate-package"
    f["package"].rename(alternate)
    f["package"].symlink_to(alternate,target_is_directory=True)
    with pytest.raises(runner.GateError):
        runner.package_identity(f["source"]/"cbus_toolkit",f["wheel"],f["package"])


def test_child_startup_ppid_is_mandatory(runner,tmp_path):
    f,py,files,config,rows,launches=origins_fixture(runner,tmp_path)
    del rows[2]["ppid"]
    with pytest.raises(runner.GateError):
        runner.audit_origins(rows,launches,101,py,f["package"],files,expected_config_sha256=config)


BASE = Path(__file__).resolve().parent

@pytest.fixture(scope="module")
def helper():
    path = Path(os.environ.get("CBUS_INSTALLED_INTEROP_HELPER", str(BASE.parent / "research/installed_rust_interop.py")))
    spec=importlib.util.spec_from_file_location("independent_guard_auditor",path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module

def guarded_fixture(tmp_path, helper):
    f=wheel_fixture(tmp_path)
    venv.EnvBuilder(with_pip=False,symlinks=True).create(tmp_path/"environment")
    py=tmp_path/"environment/bin/python"
    guard=Path(os.environ.get("CBUS_INSTALLED_INTEROP_GUARD",str(BASE.parent/"research/installed_interop_guard.py")))
    (f["installed"]/"fixture_guard.py").write_bytes(guard.read_bytes())
    origins=tmp_path/"origins"
    config={"installed_package":str(f["package"]),"origin_directory":str(origins),
            "package_files":helper.package_files(f["package"]),"python":str(py),"binary_resolved":[]}
    config_path=tmp_path/"guard-config.json"
    config_path.write_text(json.dumps(config,sort_keys=True)+"\n")
    (f["installed"]/"fixture_guard.pth").write_text("import fixture_guard; fixture_guard.activate("+repr(str(config_path))+")\n")
    return f,py,origins,hashlib.sha256(config_path.read_bytes()).hexdigest()

def actual_rows(root):
    origins=[];launch_events=[]
    for path in sorted(root.glob("origins-*.jsonl")):
        origins.extend(json.loads(line) for line in path.read_text().splitlines())
    for path in sorted(root.glob("launches-*.jsonl")):
        launch_events.extend(json.loads(line) for line in path.read_text().splitlines())
    launches=[]
    by={}
    for row in launch_events:
        by.setdefault((row["owner_pid"],row["pid"]),[]).append(row)
    for key,rows in by.items():
        assert [row["event"] for row in rows]==["launch","terminal"]
        assert rows[0]["returncode"] is None and type(rows[1]["returncode"]) is int
        assert {k:v for k,v in rows[0].items() if k not in ("event","returncode")}=={k:v for k,v in rows[1].items() if k not in ("event","returncode")}
        launches.append(rows[1])
    return origins,launches

def run_parent(py,code,*,cwd,values=None):
    env={**os.environ,"PYTHONNOUSERSITE":"1","PYTHONDONTWRITEBYTECODE":"1","PYTHONPATH":"",**(values or {})}
    process=subprocess.run([str(py),"-B","-c",code],cwd=cwd,env=env,text=True,capture_output=True,timeout=20)
    assert process.returncode==0, process.stderr
    return json.loads(process.stdout)

CHILD_IMPORT="import cbus_toolkit,os,json;print(json.dumps({'pid':os.getpid(),'file':cbus_toolkit.__file__}))"
PARENT="import cbus_toolkit,os,json,subprocess,sys;r=subprocess.run(json.loads(os.environ['CHILD_ARGV']),env=json.loads(os.environ['CHILD_ENV']),text=True,capture_output=True);print(json.dumps({'pid':os.getpid(),'child_exit':r.returncode,'stdout':r.stdout,'stderr':r.stderr}))"

def probe(tmp_path,helper,mode):
    f,py,origins,config=guarded_fixture(tmp_path,helper)
    env={**os.environ,"PYTHONNOUSERSITE":"1","PYTHONDONTWRITEBYTECODE":"1","PYTHONPATH":""}
    args=[str(py),"-B","-c",CHILD_IMPORT]
    if mode=="module-cli":
        args=[str(py),"-B","-m","cbus_toolkit"]
    elif mode=="packaged-resource":
        args=[str(py),"-B","-c","import cbus_toolkit,importlib.resources,json;print(json.dumps({'resource':importlib.resources.files('cbus_toolkit').joinpath('probe.py').read_text()}))"]
    elif mode=="console-cli":
        console=py.parent/"cbus-toolkit"
        console.write_text("#!"+str(py)+"\nfrom cbus_toolkit.cli import main\nraise SystemExit(main())\n")
        console.chmod(0o700)
        args=[str(console)]
    elif mode=="empty-env":
        env={}
    elif mode=="stripped-env":
        env={"PATH":os.environ.get("PATH",""),"PYTHONDONTWRITEBYTECODE":"1"}
    elif mode=="source-env":
        env["PYTHONPATH"]=str(f["source"])
    elif mode=="no-site":
        args=[str(py),"-S","-B","-c","import sys;sys.path.insert(0,"+repr(str(f["installed"]))+");"+CHILD_IMPORT]
    elif mode=="mixed-submodule":
        code="import cbus_toolkit;cbus_toolkit.__path__.insert(0,"+repr(str(f["source"]/"cbus_toolkit"))+");from cbus_toolkit import probe"
        args=[str(py),"-B","-c",code]
    elif mode=="late-tamper":
        code="import cbus_toolkit;from pathlib import Path;Path("+repr(str(f["package"]/"probe.py"))+").write_text('tampered=1\\n');from cbus_toolkit import probe"
        args=[str(py),"-B","-c",code]
    elif mode=="exit-without-terminal":
        args=[str(py),"-B","-c","import cbus_toolkit,os;os._exit(0)"]
    row=run_parent(py,PARENT,cwd=tmp_path,values={"CHILD_ARGV":json.dumps(args),"CHILD_ENV":json.dumps(env)})
    actual_origins,launches=actual_rows(origins)
    assert len(launches)==1 and launches[0]["owner_pid"]==row["pid"]
    assert launches[0]["returncode"]==row["child_exit"]
    return f,py,config,row,actual_origins,launches

@pytest.mark.parametrize("mode",["normal-child","module-cli","stripped-env","packaged-resource","console-cli","empty-env"])
def test_actual_guarded_parent_and_child_pass(helper,tmp_path,mode):
    f,py,config,row,records,launches=probe(tmp_path,helper,mode)
    assert row["child_exit"]==0,row["stderr"]
    if mode=="packaged-resource":
        assert json.loads(row["stdout"])["resource"]=="MARKER = 'fixture-probe'\n"
    elif mode in ("module-cli","console-cli"):
        assert json.loads(row["stdout"])=={"probe":"fixture-probe"}
    result=helper.audit_origins(records,launches,row["pid"],py,f["package"],helper.package_files(f["package"]),expected_config_sha256=config)
    assert result["python_processes"]==2 and result["violations"]==0

@pytest.mark.parametrize("mode",["source-env","no-site","mixed-submodule","late-tamper","exit-without-terminal"])
def test_actual_child_fallback_and_missing_guard_fail(helper,tmp_path,mode):
    f,py,config,row,records,launches=probe(tmp_path,helper,mode)
    assert any(r["pid"]==row["pid"] and r["kind"]=="terminal" for r in records)
    if mode in ("no-site","exit-without-terminal"):
        assert row["child_exit"]==0
        assert not any(r["pid"]==launches[0]["pid"] and r["kind"]=="terminal" for r in records)
    else:
        assert row["child_exit"]!=0
    with pytest.raises(helper.GateError):
        helper.audit_origins(records,launches,row["pid"],py,f["package"],helper.package_files(f["package"]),expected_config_sha256=config)


def test_actual_positional_executable_and_environment_are_bound(helper,tmp_path):
    f,py,origins,config=guarded_fixture(tmp_path,helper)
    # Keep a synthetic argv[0] inside the venv: a bare display name prevents
    # Linux CPython from locating pyvenv.cfg even with an explicit executable.
    # Popen still receives both executable and the empty env positionally.
    display = py.parent / "fixture-display-name"
    display.symlink_to(py.name)
    assert display.resolve() == py.resolve()
    code=("import cbus_toolkit,subprocess,os,json,sys;"
          f"p=subprocess.Popen([{str(display)!r},'-B','-c',os.environ['CHILD_CODE']],"
          "-1,sys.executable,None,subprocess.PIPE,subprocess.PIPE,None,True,False,None,{});"
          "out,err=p.communicate();print(json.dumps({'pid':os.getpid(),'child_exit':p.returncode,'stdout':out.decode(),'stderr':err.decode()}))")
    row=run_parent(py,code,cwd=tmp_path,values={"CHILD_CODE":CHILD_IMPORT})
    assert row["child_exit"]==0,row["stderr"]
    records,launches=actual_rows(origins)
    assert len(launches)==1 and launches[0]["owner_pid"]==row["pid"]
    result=helper.audit_origins(records,launches,row["pid"],py,f["package"],helper.package_files(f["package"]),expected_config_sha256=config)
    assert result["python_processes"]==2 and result["violations"]==0


def test_identical_guard_activation_is_idempotent(helper,tmp_path):
    f,py,origins,config=guarded_fixture(tmp_path,helper)
    code=("import fixture_guard,os,json;fixture_guard.activate("+repr(str(tmp_path/"guard-config.json"))+");"
          "import cbus_toolkit;print(json.dumps({'pid':os.getpid()}))")
    row=run_parent(py,code,cwd=tmp_path)
    records,launches=actual_rows(origins)
    assert launches==[]
    assert [r["kind"] for r in records].count("startup")==1
    assert [r["kind"] for r in records].count("terminal")==1
    result=helper.audit_origins(records,launches,row["pid"],py,f["package"],helper.package_files(f["package"]),expected_config_sha256=config)
    assert result["python_processes"]==1


def test_guard_cleanup_does_not_turn_unreaped_child_into_accepted_history(helper,tmp_path):
    f,py,origins,config=guarded_fixture(tmp_path,helper)
    ready=tmp_path/"child-ready.json"
    child=("import cbus_toolkit,os,json,time;from pathlib import Path;Path("+repr(str(ready))+").write_text(json.dumps({'pid':os.getpid()}));time.sleep(60)")
    code=("import cbus_toolkit,subprocess,os,json,sys,time;from pathlib import Path;"
          "p=subprocess.Popen([sys.executable,'-B','-c',os.environ['CHILD_CODE']],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);"
          "deadline=time.monotonic()+5;"
          "\nwhile not Path("+repr(str(ready))+").exists() and time.monotonic()<deadline: time.sleep(.01)"
          "\nassert Path("+repr(str(ready))+").exists();print(json.dumps({'pid':os.getpid(),'child_pid':p.pid}))")
    row=run_parent(py,code,cwd=tmp_path,values={"CHILD_CODE":child})
    records,launches=helper.read_guard(origins)
    assert len(launches)==1 and launches[0]["pid"]==row["child_pid"]
    assert launches[0]["returncode"] is None
    cleanup=helper.read_jsonl(origins/('cleanup-'+str(row["pid"])+'.jsonl'))
    assert len(cleanup)==1 and cleanup[0]["pid"]==row["child_pid"]
    assert cleanup[0]["original_returncode"] is None
    assert cleanup[0]["reaped"] is True and type(cleanup[0]["cleanup_returncode"]) is int
    with pytest.raises(ProcessLookupError):
        os.kill(row["child_pid"],0)
    with pytest.raises(helper.GateError):
        helper.audit_origins(records,launches,row["pid"],py,f["package"],helper.package_files(f["package"]),expected_config_sha256=config)


def test_timestamp_valid_bytecode_is_rejected_before_acceptance(helper,tmp_path):
    f,py,origins,config=guarded_fixture(tmp_path,helper)
    source=f["package"]/"__init__.py"
    cache=Path(importlib.util.cache_from_source(str(source)))
    cache.parent.mkdir(parents=True)
    wrong=compile("MARKER='fixture-substituted-bytecode'\n",str(source),"exec")
    cache.write_bytes(importlib.util.MAGIC_NUMBER+struct.pack('<III',0,int(source.stat().st_mtime),len(source.read_bytes()))+marshal.dumps(wrong))
    result=subprocess.run([str(py),'-B','-c',"import cbus_toolkit,os,json;print(json.dumps({'pid':os.getpid(),'marker':cbus_toolkit.MARKER}))"],cwd=tmp_path,
        env={**os.environ,'PYTHONPATH':'','PYTHONNOUSERSITE':'1','PYTHONDONTWRITEBYTECODE':'1'},text=True,capture_output=True,timeout=20)
    records,launches=helper.read_guard(origins)
    assert launches==[] and any(r['kind']=='violation' for r in records)
    # Python may ignore a .pth ImportError; acceptance still refuses the raw
    # violation and never infers trusted code from the unchanged .py hash.
    if result.returncode==0:
        assert json.loads(result.stdout)['marker']=='fixture-substituted-bytecode'
    with pytest.raises(helper.GateError):
        helper.audit_origins(records,launches,result.pid if hasattr(result,'pid') else records[0]['pid'],py,f['package'],
            {name: {'sha256':sha256(payload),'bytes':len(payload)} for name,payload in {
                '__init__.py':PACKAGE_BYTES['cbus_toolkit/__init__.py'],
                'probe.py':PACKAGE_BYTES['cbus_toolkit/probe.py'],
                'cli.py':PACKAGE_BYTES['cbus_toolkit/cli.py'],
                '__main__.py':PACKAGE_BYTES['cbus_toolkit/__main__.py'],
            }.items()},expected_config_sha256=config)


@pytest.mark.parametrize("suffix", [".pyc", ".pyo"])
def test_regular_source_cache_is_excluded_and_not_copied(runner,tmp_path,suffix):
    f=wheel_fixture(tmp_path)
    source=f["source"]/"cbus_toolkit"
    cache=source/"__pycache__";cache.mkdir()
    (cache/("probe.cpython-313"+suffix)).write_bytes(b"disposable fixture cache bytes\n")
    expected={name.removeprefix("cbus_toolkit/"):{"sha256":sha256(payload),"bytes":len(payload)}
              for name,payload in PACKAGE_BYTES.items()}
    assert runner.package_files(source,allow_source_caches=True)==expected
    with pytest.raises(runner.GateError):
        runner.package_files(source)
    identity=runner.package_identity(source,f["wheel"],f["package"])
    assert identity["files"]==expected and identity["file_count"]==4
    # The bounded reference input map includes only the four literal source
    # files. Git already excludes ordinary caches in the production runner.
    inputs={"src/cbus_toolkit/"+name:value for name,value in expected.items()}
    stage=tmp_path/"cache-free-reference"
    copied=runner.copy_reference(f["source"].parent,stage,inputs)
    assert copied["files"]==4 and copied["distinct_inodes"] is True
    assert runner.copied_inputs(stage,inputs)==inputs
    assert not (stage/"src/cbus_toolkit/__pycache__").exists()
    assert sorted(p.relative_to(stage).as_posix() for p in stage.rglob('*') if p.is_file())==sorted(inputs)


@pytest.mark.parametrize("kind", ["directory", "file", "dangling-file"])
def test_source_cache_symlink_never_uses_ignore_exception(runner,tmp_path,kind):
    f=wheel_fixture(tmp_path)
    source=f["source"]/"cbus_toolkit"
    cache=source/"__pycache__"
    if kind=="directory":
        outside=tmp_path/"outside-cache";outside.mkdir()
        (outside/"probe.cpython-313.pyc").write_bytes(b"cache fixture\n")
        cache.symlink_to(outside,target_is_directory=True)
    else:
        cache.mkdir()
        target=tmp_path/"outside.pyc"
        if kind=="file":target.write_bytes(b"cache fixture\n")
        (cache/"probe.cpython-313.pyc").symlink_to(target)
    with pytest.raises(runner.GateError):
        runner.package_files(source,allow_source_caches=True)
    with pytest.raises(runner.GateError):
        runner.package_identity(source,f["wheel"],f["package"])


@pytest.mark.parametrize("relative", ["__pycache__/unexpected.txt", "legacy.pyc"])
def test_source_cache_exception_is_only_regular_bytecode_beneath_cache(runner,tmp_path,relative):
    f=wheel_fixture(tmp_path)
    source=f["source"]/"cbus_toolkit"
    extra=source/relative;extra.parent.mkdir(parents=True,exist_ok=True)
    extra.write_bytes(b"not an admitted ordinary cache member\n")
    with pytest.raises(runner.GateError):
        runner.package_files(source,allow_source_caches=True)


def test_source_cache_exception_does_not_admit_installed_bytecode(runner,tmp_path):
    f=wheel_fixture(tmp_path)
    source=f["source"]/"cbus_toolkit"
    for package in (source,f["package"]):
        cache=package/"__pycache__";cache.mkdir()
        (cache/"probe.cpython-313.pyc").write_bytes(b"cache fixture\n")
    with pytest.raises(runner.GateError):
        runner.package_identity(source,f["wheel"],f["package"])


def test_source_cache_exception_does_not_admit_wheel_bytecode(runner,tmp_path):
    f=wheel_fixture(tmp_path)
    source=f["source"]/"cbus_toolkit"
    cache=source/"__pycache__";cache.mkdir()
    (cache/"probe.cpython-313.pyc").write_bytes(b"cache fixture\n")
    with zipfile.ZipFile(f["wheel"],"a") as archive:
        archive.writestr("cbus_toolkit/__pycache__/probe.cpython-313.pyc",b"cache fixture\n")
    with pytest.raises(runner.GateError):
        runner.package_identity(source,f["wheel"],f["package"])
