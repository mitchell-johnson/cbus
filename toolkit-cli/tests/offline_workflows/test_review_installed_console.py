"""Configured installed package/console paths must fail instead of skipping."""
from pathlib import Path
import os
import shlex
import subprocess

import pytest

import test_public_cli_integration as public


@pytest.fixture
def tmp_path(tmp_path_factory):
    return tmp_path_factory.mktemp("review-installed-console").resolve()


@pytest.fixture(autouse=True)
def clean_installed_environment(monkeypatch):
    monkeypatch.delenv("CBUS_OFFLINE_INSTALLED_TARGET", raising=False)
    monkeypatch.delenv("CBUS_OFFLINE_INSTALLED_CONSOLE", raising=False)


def target_fixture(tmp_path):
    target = tmp_path / "site-packages"
    package = target / "cbus_toolkit"
    package.mkdir(parents=True)
    (package / "cli.py").write_text("# Path-shape fixture only; never imported or installed.\n")
    return target


def console_fixture(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# Console-path fixture only; never executed.\n")
    return path.resolve()


def test_unconfigured_installed_check_can_skip():
    with pytest.raises(pytest.skip.Exception):
        public.installed_target.__wrapped__()


def test_explicit_console_outside_package_root_is_used_for_invocation(tmp_path, monkeypatch):
    target = target_fixture(tmp_path)
    console = console_fixture(tmp_path / "wheel-venv/bin/cbus-toolkit")
    monkeypatch.setenv("CBUS_OFFLINE_INSTALLED_TARGET", str(target))
    monkeypatch.setenv("CBUS_OFFLINE_INSTALLED_CONSOLE", str(console))
    assert not (target / "bin/cbus-toolkit").exists()
    assert public.installed_target.__wrapped__() == target
    assert public.installed_console(target) == console
    calls = []
    sentinel = object()
    def capture(command, **settings):
        calls.append((command, settings))
        return sentinel
    monkeypatch.setattr(public.subprocess, "run", capture)
    assert public.invoke_public(["--help"], tmp_path, target) is sentinel
    command, settings = calls[0]
    assert command == [str(console), "--help"]
    assert settings["env"]["PYTHONPATH"] == str(target)


def test_target_install_console_remains_local_fallback(tmp_path, monkeypatch):
    target = target_fixture(tmp_path)
    console = console_fixture(target / "bin/cbus-toolkit")
    monkeypatch.setenv("CBUS_OFFLINE_INSTALLED_TARGET", str(target))
    assert public.installed_target.__wrapped__() == target
    assert public.installed_console(target) == console


@pytest.mark.parametrize("missing", ("target", "package", "console", "console-only"))
def test_any_configured_missing_installed_path_fails_instead_of_skipping(tmp_path, monkeypatch, missing):
    target = tmp_path / "missing-target" if missing == "target" else target_fixture(tmp_path)
    console = tmp_path / "missing-console" if missing == "console" else console_fixture(tmp_path / "wheel-venv/bin/cbus-toolkit")
    if missing == "package":
        (target / "cbus_toolkit/cli.py").unlink()
    if missing != "console-only":
        monkeypatch.setenv("CBUS_OFFLINE_INSTALLED_TARGET", str(target))
    monkeypatch.setenv("CBUS_OFFLINE_INSTALLED_CONSOLE", str(console))
    with pytest.raises(pytest.fail.Exception, match="Configured installed"):
        public.installed_target.__wrapped__()


def test_configured_target_without_any_console_fails_instead_of_skipping(tmp_path, monkeypatch):
    target = target_fixture(tmp_path)
    monkeypatch.setenv("CBUS_OFFLINE_INSTALLED_TARGET", str(target))
    with pytest.raises(pytest.fail.Exception, match="Configured installed console"):
        public.installed_target.__wrapped__()


def test_configured_empty_target_refuses_package_in_working_directory(tmp_path, monkeypatch):
    target = target_fixture(tmp_path)
    console = console_fixture(tmp_path / "wheel-venv/bin/cbus-toolkit")
    monkeypatch.chdir(target)
    monkeypatch.setenv("CBUS_OFFLINE_INSTALLED_TARGET", "")
    monkeypatch.setenv("CBUS_OFFLINE_INSTALLED_CONSOLE", str(console))
    with pytest.raises(pytest.fail.Exception, match="nonempty directory path"):
        public.installed_target.__wrapped__()


def test_configured_empty_console_fails_instead_of_resolving_working_directory(tmp_path, monkeypatch):
    target = target_fixture(tmp_path)
    monkeypatch.chdir(target)
    monkeypatch.setenv("CBUS_OFFLINE_INSTALLED_TARGET", str(target))
    monkeypatch.setenv("CBUS_OFFLINE_INSTALLED_CONSOLE", "")
    with pytest.raises(pytest.fail.Exception, match="nonempty script path"):
        public.installed_target.__wrapped__()


# These checks exercise audit configuration only, without a package build or CLI run.
_TOOLKIT = Path(__file__).resolve().parents[2]
_AUDIT_ARGS_TARGET = "print-offline-workflow-audit-args"
_AUDIT_STEPS = ("Audit Toolkit offline execution and skips",
                "Audit installed-wheel execution and skips")


def audit_step_command(step):
    workflow = (_TOOLKIT.parent / ".github/workflows/ci.yml").read_text()
    body = workflow.split("      - name: " + step + "\n", 1)[1].split("\n      - name:", 1)[0]
    return " ".join(line.strip() for line in body.split("        run: >-\n", 1)[1].splitlines())


def make_audit_arguments(directory, *, environment=None):
    return subprocess.run(
        ["make", "--no-print-directory", "-s", "-f", str(_TOOLKIT / "Makefile"), _AUDIT_ARGS_TARGET],
        cwd=directory, env=environment, capture_output=True, text=True, timeout=10, check=False,
    )


def required_module_tokens(process):
    assert process.returncode == 0, process.stderr
    tokens = shlex.split(process.stdout)
    assert tokens and len(tokens) % 2 == 0
    assert tokens[::2] == ["--require-module"] * (len(tokens) // 2)
    return tokens[1::2]


def test_make_audit_helper_requires_every_current_recursive_offline_module():
    actual = required_module_tokens(make_audit_arguments(_TOOLKIT))
    expected = sorted(path.relative_to(_TOOLKIT).as_posix()
                      for path in (_TOOLKIT / "tests/offline_workflows").rglob("test_*.py")
                      if path.is_file())
    assert actual == expected
    assert len(actual) == len(set(actual))
    assert "tests/offline_workflows/test_cli_installed.py" in actual
    assert "tests/offline_workflows/test_review_copy_history.py" in actual


def test_make_audit_helper_discovers_nested_future_modules_without_roster_edits(tmp_path):
    root = tmp_path / "tests/offline_workflows"
    nested = root / "future/deeper"
    nested.mkdir(parents=True)
    (root / "test_root.py").write_text("# configuration path fixture only\n")
    (nested / "test_nested.py").write_text("# configuration path fixture only\n")
    (nested / "support.py").write_text("# not a test module\n")
    assert required_module_tokens(make_audit_arguments(tmp_path)) == [
        "tests/offline_workflows/future/deeper/test_nested.py",
        "tests/offline_workflows/test_root.py",
    ]


@pytest.mark.parametrize("shape", ("absent", "empty", "dangling"))
def test_make_audit_helper_refuses_missing_or_empty_roster(tmp_path, shape):
    root = tmp_path / "tests/offline_workflows"
    if shape == "empty":
        root.mkdir(parents=True)
    elif shape == "dangling":
        root.parent.mkdir()
        root.symlink_to(tmp_path / "missing-directory", target_is_directory=True)
    process = make_audit_arguments(tmp_path)
    assert process.returncode != 0
    assert process.stdout == ""


def test_make_audit_helper_propagates_find_failure(tmp_path):
    (tmp_path / "tests/offline_workflows").mkdir(parents=True)
    commands = tmp_path / "commands"
    commands.mkdir()
    find = commands / "find"
    find.write_text("#!/bin/sh\nexit 7\n")
    find.chmod(0o700)
    environment = dict(os.environ, PATH=str(commands) + os.pathsep + os.environ["PATH"])
    process = make_audit_arguments(tmp_path, environment=environment)
    assert process.returncode != 0
    assert process.stdout == ""


@pytest.mark.parametrize("step", _AUDIT_STEPS)
def test_both_ci_audits_require_recursive_roster_with_fail_closed_discovery(step):
    command = audit_step_command(step)
    discovery = ("offline_workflow_audit_args=$(make --no-print-directory -s "
                 + _AUDIT_ARGS_TARGET + ") && ")
    assert command.startswith(discovery)
    assert command.count("$offline_workflow_audit_args") == 1
    assert "--require-module" in command
    if step == _AUDIT_STEPS[0]:
        assert "--allow-unconfigured-installed-module" in command
        assert "--require-installed-configuration" not in command
    else:
        assert "--allow-unconfigured-installed-module" not in command
        assert "--require-installed-configuration" in command
        assert "--require-module tests/offline_workflows/test_cli_installed.py" in command
        assert "--require-module tests/offline_workflows/test_public_cli_integration.py" in command
        assert "--require-passing-prefix tests/offline_workflows/test_cli_installed.py:: 18" in command
        assert ("--require-passing-prefix tests/offline_workflows/"
                "test_public_cli_integration.py::test_actual_installed 17") in command


@pytest.mark.parametrize("step", _AUDIT_STEPS)
def test_ci_audit_does_not_execute_python_after_discovery_failure(tmp_path, step):
    commands = tmp_path / "commands"
    commands.mkdir()
    make = commands / "make"
    make.write_text("#!/bin/sh\nexit 7\n")
    make.chmod(0o700)
    marker = tmp_path / "python-was-executed"
    for python in (commands / "python", tmp_path / ".venv/bin/python"):
        python.parent.mkdir(parents=True, exist_ok=True)
        python.write_text("#!/bin/sh\n: > \"$AUDIT_EXECUTION_MARKER\"\nexit 0\n")
        python.chmod(0o700)
    environment = dict(os.environ, PATH=str(commands) + os.pathsep + os.environ["PATH"],
                       AUDIT_EXECUTION_MARKER=str(marker), RUNNER_TEMP=str(tmp_path),
                       GITHUB_STEP_SUMMARY=str(tmp_path / "summary"))
    process = subprocess.run(["/bin/sh", "-c", audit_step_command(step)], cwd=tmp_path,
                             env=environment, capture_output=True, text=True, timeout=10, check=False)
    assert process.returncode == 7
    assert not marker.exists()


def test_wheel_description_qualifies_parent_installed_origins_and_source_comparisons():
    make = (_TOOLKIT / "Makefile").read_text()
    header = make.split("#   make check-wheel", 1)[1].split("#   make check-parity-register", 1)[0]
    assert "installed origins in the parent process" in header
    assert "explicit source-comparison subprocesses are separate" in header
    assert "without importing from src/" not in header
