"""Independent public CLI registration, bounded I/O, and installed-console proof.

Only explicit local JSON files and newly published review reports are exercised.
Set CBUS_OFFLINE_INSTALLED_TARGET to a freshly installed task wheel for the real
pip-generated console-script cases. CBUS_OFFLINE_INSTALLED_CONSOLE may explicitly
name the wheel virtualenv console; source examples remain caller-supplied files.
"""
from __future__ import annotations

import builtins
import hashlib
import importlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys

import pytest

SOURCE_ROOT = Path(__file__).resolve().parents[2] / "src"
EXAMPLES = SOURCE_ROOT / "cbus_toolkit/offline_workflows/examples"
WORKFLOWS = ("copy-paste", "neo-editor", "catalogue-groups", "discovery-session", "transfer-restore")
OPERATIONS = ("inspect", "validate", "plan")
FALSE_AUTHORITY = ("execution_enabled", "native_execution_enabled", "original_compatibility_verified", "external_persistence_verified")


@pytest.fixture
def tmp_path(tmp_path_factory):
    return tmp_path_factory.mktemp("public-offline-cli").resolve()


def installed_console(target):
    declared = os.environ.get("CBUS_OFFLINE_INSTALLED_CONSOLE")
    if declared == "":
        pytest.fail("Configured installed console must be a nonempty script path")
    console = Path(declared).resolve() if declared is not None else (target / "bin/cbus-toolkit").resolve()
    if not console.is_file():
        pytest.fail("Configured installed console script is missing: " + str(console))
    return console


@pytest.fixture(scope="module")
def installed_target():
    declared = os.environ.get("CBUS_OFFLINE_INSTALLED_TARGET")
    if declared is None:
        if os.environ.get("CBUS_OFFLINE_INSTALLED_CONSOLE") is not None:
            pytest.fail("Configured installed console requires CBUS_OFFLINE_INSTALLED_TARGET")
        pytest.skip("Requires the freshly built task wheel installed in an explicit isolated target")
    if not declared:
        pytest.fail("Configured installed target must be a nonempty directory path")
    target = Path(declared).resolve()
    if not target.is_dir():
        pytest.fail("Configured installed target directory is missing: " + str(target))
    if target == SOURCE_ROOT.resolve() or not (target / "cbus_toolkit/cli.py").is_file():
        pytest.fail("Configured installed target package is missing or points to source: " + str(target))
    installed_console(target)
    return target


def environment(cwd, package_root=SOURCE_ROOT):
    result = dict(os.environ)
    result.update(PYTHONPATH=str(package_root), PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1", PYTHONSAFEPATH="1",
                  TMPDIR=str(cwd), TEMP=str(cwd), TMP=str(cwd))
    result.pop("PYTHONSTARTUP", None)
    return result


def invoke_public(arguments, cwd, target=None, *, stdin=None, timeout=10, extra_environment=None):
    command = ([str(installed_console(target))] if target is not None
               else [sys.executable, "-S", "-m", "cbus_toolkit"])
    settings = environment(cwd, target if target is not None else SOURCE_ROOT)
    settings.update(extra_environment or {})
    return subprocess.run([*command, *map(str, arguments)], cwd=cwd, env=settings, input=stdin,
                          capture_output=True, check=False, timeout=timeout)


def workflow_arguments(source, workflow="copy-paste", operation="inspect", output=None):
    result = ["offline-workflows", workflow, operation, "--input", str(source), "--compact"]
    if output is not None:
        result += ["--output", str(output)]
    return result


def assert_envelope(process, status=0, *, error=False):
    assert process.returncode == status, (process.stdout, process.stderr)
    raw = process.stderr if error else process.stdout
    assert (process.stdout if error else process.stderr) == b""
    result = json.loads(raw)
    assert result["format"] == "cbus-offline-workflows-cli-v1"
    assert result["preparation_only"] is True
    assert all(result[field] is False for field in FALSE_AUTHORITY)
    if error:
        assert type(result["error"]["code"]) is str
        assert type(result["error"]["message"]) is str
    assert b"Traceback" not in raw
    return result


@pytest.mark.parametrize("workflow", WORKFLOWS)
@pytest.mark.parametrize("operation", OPERATIONS)
def test_public_source_dispatch_matches_standalone_bytes_and_input_digest(tmp_path, workflow, operation):
    source = (EXAMPLES / (workflow + ".json")).resolve()
    raw = source.read_bytes()
    arguments = workflow_arguments(source, workflow, operation)
    public = invoke_public(arguments, tmp_path)
    standalone = subprocess.run([sys.executable, "-S", "-m", "cbus_toolkit.offline_workflows", *arguments[1:]],
                                cwd=tmp_path, env=environment(tmp_path), capture_output=True, check=False, timeout=10)
    report = assert_envelope(public)
    assert (public.returncode, public.stdout, public.stderr) == (standalone.returncode, standalone.stdout, standalone.stderr)
    assert report["workflow"] == workflow
    assert report["operation"] == operation
    assert report["input_sha256"] == hashlib.sha256(raw).hexdigest()
    assert report["report"]["outcome"] == ("inspected" if operation == "inspect" else
        "prepared" if workflow in ("copy-paste", "catalogue-groups") else "cancelled")
    assert source.read_bytes() == raw


@pytest.mark.parametrize("arguments", [
    ["offline-workflows"],
    ["offline-workflows", "unknown", "plan"],
    ["offline-workflows", "copy-paste", "execute"],
    ["offline-workflows", "copy-paste", "plan"],
    ["offline-workflows", "copy-paste", "plan", "--input", "missing.json", "--backend", "native"],
])
def test_public_offline_argument_errors_keep_typed_json_exit_two(tmp_path, arguments):
    assert_envelope(invoke_public(arguments, tmp_path), 2, error=True)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("payload", [b'{"format":"x","format":"duplicate"}', b'{"value":NaN}',
                                     b'{"value":1e9999}', b'{"value":"\\ud800"}', b'\xff',
                                     b' ' * (4 * 1024 * 1024 + 1)],
                         ids=['duplicate-key', 'nonfinite', 'overflow', 'surrogate', 'utf8', 'bytes-limit'])
def test_public_route_retains_strict_decode_and_size_errors(tmp_path, payload):
    source = tmp_path / "input.json"
    output = tmp_path / "output.json"
    source.write_bytes(payload)
    assert_envelope(invoke_public(workflow_arguments(source, output=output), tmp_path), 2, error=True)
    assert source.read_bytes() == payload
    assert not output.exists()


@pytest.mark.parametrize("kind", ["missing", "directory", "symlink", "fifo", "stdin"])
def test_public_route_refuses_nonregular_input_without_waiting_or_output(tmp_path, kind):
    source = tmp_path / "input.json"
    sentinel = tmp_path / "sentinel.json"
    if kind == "directory":
        source.mkdir()
    elif kind == "symlink":
        sentinel.write_bytes(b"foreign sentinel")
        source.symlink_to(sentinel)
    elif kind == "fifo":
        os.mkfifo(source)
    elif kind == "stdin":
        source = "-"
    output = tmp_path / "output.json"
    assert_envelope(invoke_public(workflow_arguments(source, output=output), tmp_path, stdin=b'{}', timeout=3), 4, error=True)
    assert not output.exists()
    if kind == "symlink":
        assert sentinel.read_bytes() == b"foreign sentinel"
        assert source.is_symlink()


def test_public_report_output_is_private_complete_exclusive_and_preserves_input(tmp_path):
    source = tmp_path / "input.json"
    raw = (EXAMPLES / "copy-paste.json").read_bytes()
    source.write_bytes(raw)
    output = tmp_path / "output.json"
    arguments = workflow_arguments(source, operation="plan", output=output)
    process = invoke_public(arguments, tmp_path)
    assert_envelope(process)
    assert output.read_bytes() == process.stdout
    assert output.stat().st_mode & 0o777 == 0o600
    assert_envelope(invoke_public(arguments, tmp_path), 4, error=True)
    assert output.read_bytes() == process.stdout
    assert_envelope(invoke_public(workflow_arguments(source, output=source), tmp_path), 4, error=True)
    assert source.read_bytes() == raw
    assert sorted(path.name for path in tmp_path.iterdir()) == ["input.json", "output.json"]


def test_public_unknown_profile_stays_unsupported_stdout_three_and_can_publish_review(tmp_path):
    source = tmp_path / "input.json"
    document = json.loads((EXAMPLES / "copy-paste.json").read_bytes())
    document["profile"]["mode"] = "original-native-unverified"
    source.write_text(json.dumps(document), encoding="utf-8")
    output = tmp_path / "unsupported.json"
    process = invoke_public(workflow_arguments(source, operation="plan", output=output), tmp_path)
    report = assert_envelope(process, 3)
    assert report["report"]["outcome"] == "unsupported"
    assert report["report"]["component"]["commands"] == []
    assert output.read_bytes() == process.stdout


@pytest.mark.parametrize("flag", FALSE_AUTHORITY)
def test_public_caller_cannot_forge_native_or_persistence_authority(tmp_path, flag):
    source = tmp_path / "input.json"
    document = json.loads((EXAMPLES / "copy-paste.json").read_bytes())
    document[flag] = True
    source.write_text(json.dumps(document), encoding="utf-8")
    assert_envelope(invoke_public(workflow_arguments(source, operation="plan"), tmp_path), 2, error=True)


def test_public_help_discovers_workflows_and_retains_existing_command_groups(tmp_path):
    public = invoke_public(["--help"], tmp_path)
    assert public.returncode == 0
    assert public.stderr == b""
    for command in (b"offline-workflows", b"project", b"cgate", b"memory"):
        assert command in public.stdout
    offline = invoke_public(["offline-workflows", "--help"], tmp_path)
    assert offline.returncode == 0
    assert offline.stderr == b""
    assert b"cbus-toolkit offline-workflows" in offline.stdout
    for keyword in (*map(str.encode, WORKFLOWS), b"inspect", b"validate", b"plan", b"--input", b"--output", b"--compact"):
        assert keyword in offline.stdout


@pytest.mark.parametrize("workflow", WORKFLOWS)
@pytest.mark.parametrize("operation", OPERATIONS)
def test_public_dispatch_invokes_no_backend_process_or_transport_and_only_explicit_file_boundary(tmp_path, monkeypatch, capsys, workflow, operation):
    root = importlib.import_module("cbus_toolkit.cli")
    offline = importlib.import_module("cbus_toolkit.offline_workflows.cli")
    definitions = [(importlib.import_module(name), classes) for name, classes in (
        ("cbus_toolkit.cgate", ("CGateClient",)), ("cbus_toolkit.native", ("NativeProjects", "NativeDatabase")),
        ("cbus_toolkit.programming", ("Programmer", "ProgrammingSession")), ("cbus_toolkit.unitspec", ("UnitSpecStore",)))]
    source = (EXAMPLES / (workflow + ".json")).resolve()
    output = tmp_path / "output.json"
    original_read, original_write = offline.read_regular_input, offline.write_new_output
    active_boundary = False
    calls = []
    attempts = []

    def denied(*arguments, **keywords):
        attempts.append("external work")
        raise AssertionError("Public offline dispatch attempted an external adapter or unapproved I/O")

    def read(path):
        nonlocal active_boundary
        assert Path(path) == source
        calls.append("input")
        active_boundary = True
        try:
            return original_read(path)
        finally:
            active_boundary = False

    def write(path, payload):
        nonlocal active_boundary
        assert Path(path) == output
        calls.append("output")
        active_boundary = True
        try:
            return original_write(path, payload)
        finally:
            active_boundary = False

    def boundary_only(function):
        def guarded(*arguments, **keywords):
            if not active_boundary:
                return denied(*arguments, **keywords)
            return function(*arguments, **keywords)
        return guarded

    with monkeypatch.context() as guarded:
        guarded.setattr(offline, "read_regular_input", read)
        guarded.setattr(offline, "write_new_output", write)
        guarded.setattr(builtins, "open", denied)
        for name in ("open", "write", "unlink", "remove", "rename", "replace", "mkdir", "makedirs", "rmdir"):
            guarded.setattr(os, name, boundary_only(getattr(os, name)))
        for name in ("open", "read_bytes", "read_text", "write_bytes", "write_text", "rename", "replace", "mkdir", "unlink", "rmdir", "touch"):
            guarded.setattr(Path, name, denied)
        for name in ("__init__", "connect", "connect_ex", "bind", "send", "sendall", "sendto", "listen", "accept"):
            guarded.setattr(socket.socket, name, denied)
        guarded.setattr(socket, "create_connection", denied)
        guarded.setattr(os, "system", denied)
        for name in ("Popen", "run", "call", "check_call", "check_output"):
            guarded.setattr(subprocess, name, denied)
        for module, classes in definitions:
            for name in classes:
                guarded.setattr(getattr(module, name), "__init__", denied)
        status = root.main(workflow_arguments(source, workflow, operation, output))
    captured = capsys.readouterr()
    assert status == 0
    assert captured.err == ""
    assert json.loads(captured.out)["workflow"] == workflow
    assert calls == ["input", "output"]
    assert attempts == []
    assert output.read_bytes() == captured.out.encode("ascii")


@pytest.mark.parametrize("workflow", WORKFLOWS)
@pytest.mark.parametrize("operation", OPERATIONS)
def test_actual_installed_console_matches_public_source_for_all_modes(installed_target, tmp_path, workflow, operation):
    source = (EXAMPLES / (workflow + ".json")).resolve()
    raw = source.read_bytes()
    arguments = workflow_arguments(source, workflow, operation)
    installed = invoke_public(arguments, tmp_path, installed_target)
    public = invoke_public(arguments, tmp_path)
    assert_envelope(installed)
    assert (installed.returncode, installed.stdout, installed.stderr) == (public.returncode, public.stdout, public.stderr)
    assert json.loads(installed.stdout)["input_sha256"] == hashlib.sha256(raw).hexdigest()
    assert source.read_bytes() == raw


def _console_origin_probe_source():
    return r"""import atexit,hashlib,json,os,stat,sys
from importlib.machinery import SourceFileLoader
from pathlib import Path
_probe_main_module=sys.modules['__main__']
def record():
    import importlib.metadata
    loader=_probe_main_module.__loader__
    if type(loader) is not SourceFileLoader:
        raise TypeError('Console origin requires an actual SourceFileLoader')
    loaded_filename=loader.get_filename('__main__')
    if type(loaded_filename) is not str:
        raise TypeError('Console loader filename must be a string')
    loaded_path=Path(loaded_filename).resolve(strict=True)
    if '__file__' in vars(_probe_main_module):
        main_file=_probe_main_module.__file__
        if type(main_file) is not str:
            raise TypeError('Console __main__.__file__ must be a string')
        entry_path=Path(main_file).resolve(strict=True)
        if entry_path!=loaded_path:
            raise ValueError('Console file and loader origins disagree')
        entry_origin='__main__.__file__'
    else:
        entry_path=loaded_path
        entry_origin='SourceFileLoader.get_filename'
    if not stat.S_ISREG(entry_path.stat().st_mode):
        raise ValueError('Console origin must be a regular file')
    origins={name:module.__file__ for name,module in sys.modules.items() if name=='cbus_toolkit' or name.startswith('cbus_toolkit.')}
    entries=[{'name':entry.name,'value':entry.value} for entry in importlib.metadata.distribution('cbus-toolkit-cli').entry_points if entry.group=='console_scripts']
    Path(os.environ['CBUS_PUBLIC_ORIGIN_RECEIPT']).write_text(json.dumps({'origins':origins,'paths':sys.path,'entry_script':str(entry_path),'entry_script_sha256':hashlib.sha256(entry_path.read_bytes()).hexdigest(),'entry_script_loader':type(loader).__name__,'entry_script_origin':entry_origin,'entries':entries})+'\n', encoding='utf-8')
atexit.register(record)
"""


def test_console_origin_probe_retains_actual_loader_when_main_file_removed_at_exit(installed_target, tmp_path):
    script = tmp_path / "actual-probe-script.py"
    receipt = tmp_path / "loader-origin.json"
    script.write_text(_console_origin_probe_source() + """
import cbus_toolkit
def remove_main_file():
    main=sys.modules['__main__']
    main.__file__=main.__loader__.get_filename('__main__')
    del main.__file__
atexit.register(remove_main_file)
""", encoding="utf-8")
    settings = environment(tmp_path, installed_target)
    settings["CBUS_PUBLIC_ORIGIN_RECEIPT"] = str(receipt)
    process = subprocess.run([sys.executable, "-S", str(script)], cwd=tmp_path, env=settings,
                             capture_output=True, check=False, timeout=10)
    assert process.returncode == 0, (process.stdout, process.stderr)
    assert process.stdout == process.stderr == b""
    captured = json.loads(receipt.read_bytes())
    assert Path(captured["entry_script"]) == script
    assert captured["entry_script_sha256"] == hashlib.sha256(script.read_bytes()).hexdigest()
    assert captured["entry_script_loader"] == "SourceFileLoader"
    assert captured["entry_script_origin"] == "SourceFileLoader.get_filename"
    assert Path(captured["origins"]["cbus_toolkit"]).is_relative_to(installed_target)


def test_console_origin_probe_preserves_missing_module_file_error(installed_target, tmp_path):
    script = tmp_path / "missing-module-origin.py"
    receipt = tmp_path / "invalid-origin.json"
    script.write_text(_console_origin_probe_source() + """
import cbus_toolkit,types
name='cbus_toolkit.probe_missing_origin'
sys.modules[name]=types.ModuleType(name)
""", encoding="utf-8")
    settings = environment(tmp_path, installed_target)
    settings["CBUS_PUBLIC_ORIGIN_RECEIPT"] = str(receipt)
    process = subprocess.run([sys.executable, "-S", str(script)], cwd=tmp_path, env=settings,
                             capture_output=True, check=False, timeout=10)
    assert process.returncode == 0
    assert process.stdout == b""
    assert b"AttributeError" in process.stderr
    assert b"cbus_toolkit.probe_missing_origin" in process.stderr and b"__file__" in process.stderr
    assert not receipt.exists()


def test_actual_installed_console_metadata_and_runtime_origins_are_bound_to_target(installed_target, tmp_path):
    probe = tmp_path / "probe"
    probe.mkdir()
    receipt = tmp_path / "actual-console-origins.json"
    (probe / "sitecustomize.py").write_text(_console_origin_probe_source(), encoding="utf-8")
    source = (EXAMPLES / "neo-editor.json").resolve()
    process = invoke_public(workflow_arguments(source, "neo-editor", "plan"), tmp_path, installed_target,
                            extra_environment={"PYTHONPATH": str(probe) + os.pathsep + str(installed_target), "CBUS_PUBLIC_ORIGIN_RECEIPT": str(receipt)})
    assert_envelope(process)
    captured = json.loads(receipt.read_bytes())
    assert Path(captured["entry_script"]).resolve() == installed_console(installed_target)
    assert captured["entry_script_sha256"] == hashlib.sha256(installed_console(installed_target).read_bytes()).hexdigest()
    assert captured["entry_script_loader"] == "SourceFileLoader"
    assert captured["entry_script_origin"] in ("__main__.__file__", "SourceFileLoader.get_filename")
    assert {"name": "cbus-toolkit", "value": "cbus_toolkit.cli:main"} in captured["entries"]
    assert {"cbus_toolkit", "cbus_toolkit.cli", "cbus_toolkit.offline_workflows.cli", "cbus_toolkit.offline_workflows.neo_editor_input"}.issubset(captured["origins"])
    for name, origin in captured["origins"].items():
        installed = Path(origin).resolve()
        assert installed.is_relative_to(installed_target), (name, origin)
        source_module = SOURCE_ROOT / installed.relative_to(installed_target)
        assert hashlib.sha256(installed.read_bytes()).digest() == hashlib.sha256(source_module.read_bytes()).digest(), name
    for entry in captured["paths"]:
        if entry:
            assert not Path(entry).resolve().is_relative_to(SOURCE_ROOT), entry


def test_actual_installed_console_keeps_typed_errors_and_nooverwrite(installed_target, tmp_path):
    source = tmp_path / "input.json"
    source.write_bytes(b'{"format":"x","format":"duplicate"}')
    assert_envelope(invoke_public(workflow_arguments(source), tmp_path, installed_target), 2, error=True)
    document = json.loads((EXAMPLES / "copy-paste.json").read_bytes())
    document["profile"]["mode"] = "original-native-unverified"
    source.write_text(json.dumps(document), encoding="utf-8")
    output = tmp_path / "report.json"
    arguments = workflow_arguments(source, operation="plan", output=output)
    process = invoke_public(arguments, tmp_path, installed_target)
    assert_envelope(process, 3)
    assert output.read_bytes() == process.stdout
    assert output.stat().st_mode & 0o777 == 0o600
    assert_envelope(invoke_public(arguments, tmp_path, installed_target), 4, error=True)
    assert output.read_bytes() == process.stdout


def test_public_global_and_local_compact_options_preserve_shared_parser_behavior(tmp_path):
    source = (EXAMPLES / "copy-paste.json").resolve()
    arguments = workflow_arguments(source)
    local = invoke_public(arguments, tmp_path)
    leading = invoke_public(["--compact", *arguments[:-1]], tmp_path)
    both = invoke_public(["--compact", *arguments], tmp_path)
    assert_envelope(local)
    assert (leading.returncode, leading.stdout, leading.stderr) == (local.returncode, local.stdout, local.stderr)
    assert (both.returncode, both.stdout, both.stderr) == (local.returncode, local.stdout, local.stderr)
    assert local.stdout.count(b"\n") == 1
    root = importlib.import_module("cbus_toolkit.cli")
    parsed = root.build_parser().parse_args(["--compact", *arguments[:-1]])
    assert parsed.area == "offline-workflows"
    assert parsed.compact is True
