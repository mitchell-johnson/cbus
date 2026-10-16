"""Configured installed package/console paths must fail instead of skipping."""
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
