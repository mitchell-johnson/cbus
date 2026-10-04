"""Narrow acceptance of the actual fresh installed task wheel, without source imports.

Set CBUS_OFFLINE_INSTALLED_TARGET to the pip-installed task wheel target. Source
JSON examples are explicit caller files; no example resource packaging is claimed.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from test_cli_boundary import PACKAGE_ROOT, SOURCE_ROOT, WORKFLOWS, assert_json_error, assert_report, cli_environment, input_args, run_cli


@pytest.fixture
def tmp_path(tmp_path_factory):
    return tmp_path_factory.mktemp("offline-cli-installed").resolve()


@pytest.fixture(scope="module")
def installed_target():
    declared = os.environ.get("CBUS_OFFLINE_INSTALLED_TARGET")
    if declared is None:
        if os.environ.get("CBUS_OFFLINE_INSTALLED_CONSOLE") is not None:
            pytest.fail("Configured installed console requires an explicit installed target")
        pytest.skip("Requires a freshly built task wheel installed in an explicit isolated target")
    if not declared:
        pytest.fail("Configured installed target must be a nonempty directory path")
    target = Path(declared).resolve()
    assert target.is_dir()
    assert target != SOURCE_ROOT.resolve()
    assert (target / "cbus_toolkit" / "offline_workflows" / "__main__.py").is_file()
    return target


def test_all_actual_import_origins_and_bytes_are_installed_and_match_final_source(installed_target, tmp_path):
    names = ("cbus_toolkit", "cbus_toolkit.offline_workflows", "cbus_toolkit.offline_workflows.__main__",
             "cbus_toolkit.offline_workflows.cli", "cbus_toolkit.offline_workflows.cli_support",
             "cbus_toolkit.offline_workflows.demo", *(
        "cbus_toolkit.offline_workflows." + suffix for suffix in (
            "copy_paste", "neo_editor", "catalogue_groups", "discovery_session", "transfer_restore",
            "copy_paste_input", "neo_editor_input", "catalogue_groups_input", "discovery_session_input", "transfer_restore_input")))
    script = '''import importlib,importlib.metadata,json,sys
names=json.loads(sys.argv[1])
for name in names: importlib.import_module(name)
origins={name:module.__file__ for name,module in sys.modules.items() if name=='cbus_toolkit' or name.startswith('cbus_toolkit.')}
print(json.dumps({'origins':origins,'paths':sys.path,'version':importlib.metadata.version('cbus-toolkit-cli')}))
'''
    process = subprocess.run([sys.executable, "-S", "-c", script, json.dumps(names)],
        cwd=tmp_path, env=cli_environment(installed_target), capture_output=True, check=False, timeout=10)
    assert process.returncode == 0, process.stderr
    assert process.stderr == b""
    evidence = json.loads(process.stdout)
    assert evidence["version"] == "0.1.0"
    assert set(names).issubset(evidence["origins"])
    for module, origin in evidence["origins"].items():
        assert Path(origin).resolve().is_relative_to(installed_target), (module, origin)
    for entry in evidence["paths"]:
        if entry:
            assert not Path(entry).resolve().is_relative_to(SOURCE_ROOT), entry
    for name in names:
        installed = Path(evidence["origins"][name]).resolve()
        relative = installed.relative_to(installed_target)
        source = SOURCE_ROOT / relative
        assert hashlib.sha256(installed.read_bytes()).digest() == hashlib.sha256(source.read_bytes()).digest(), name


@pytest.mark.parametrize("workflow", WORKFLOWS)
@pytest.mark.parametrize("operation", ("inspect", "validate", "plan"))
def test_every_source_file_example_runs_through_installed_entrypoint(installed_target, tmp_path, workflow, operation):
    source = (PACKAGE_ROOT / "examples" / (workflow + ".json")).resolve()
    raw = source.read_bytes()
    process = run_cli(input_args(source, workflow=workflow, action=operation), cwd=tmp_path, package_path=installed_target)
    report = assert_report(process)
    assert report["workflow"] == workflow
    assert report["operation"] == operation
    assert report["input_sha256"] == hashlib.sha256(raw).hexdigest()
    assert report["report"]["operation"] == operation
    if operation == "inspect":
        assert report["report"]["outcome"] == "inspected"
    else:
        assert report["report"]["outcome"] == ("prepared" if workflow in ("copy-paste", "catalogue-groups") else "cancelled")
    assert source.read_bytes() == raw


def test_installed_unknown_contract_exit_three_is_review_material_with_no_authority(installed_target, tmp_path):
    value = json.loads((PACKAGE_ROOT / "examples" / "copy-paste.json").read_bytes())
    value["profile"]["mode"] = "original-native-unverified"
    source = tmp_path / "input.json"
    source.write_text(json.dumps(value), encoding="utf-8")
    output = tmp_path / "unsupported.json"
    process = run_cli(input_args(source, action="plan", output=output), cwd=tmp_path, package_path=installed_target)
    report = assert_report(process, 3)
    assert report["report"]["outcome"] == "unsupported"
    assert report["report"]["component"]["commands"] == []
    assert output.read_bytes() == process.stdout
    assert output.stat().st_mode & 0o777 == 0o600
    refused = run_cli(input_args(source, action="plan", output=output), cwd=tmp_path, package_path=installed_target)
    assert_json_error(refused, 4)
    assert output.read_bytes() == process.stdout


def test_installed_entrypoint_rejects_duplicate_json_and_forged_authority(installed_target, tmp_path):
    source = tmp_path / "input.json"
    source.write_bytes(b'{"format":"x","format":"duplicate"}')
    error = assert_json_error(run_cli(input_args(source), cwd=tmp_path, package_path=installed_target), 2)
    assert error["error"]["code"] == "duplicate_json_key"
    value = json.loads((PACKAGE_ROOT / "examples" / "copy-paste.json").read_bytes())
    value["native_execution_enabled"] = True
    source.write_text(json.dumps(value), encoding="utf-8")
    assert_json_error(run_cli(input_args(source, action="plan"), cwd=tmp_path, package_path=installed_target), 2)
    assert sorted(path.name for path in tmp_path.iterdir()) == ["input.json"]
