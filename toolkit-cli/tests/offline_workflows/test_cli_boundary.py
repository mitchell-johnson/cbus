"""Independent subprocess checks for the bounded offline CLI file boundary."""
from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile

import pytest

SOURCE_ROOT = Path(__file__).resolve().parents[2] / "src"
PACKAGE_ROOT = SOURCE_ROOT / "cbus_toolkit" / "offline_workflows"
WORKFLOWS = ("copy-paste", "neo-editor", "catalogue-groups", "discovery-session", "transfer-restore")
MAX_INPUT_BYTES = 4 * 1024 * 1024


@pytest.fixture
def tmp_path(tmp_path_factory):
    # macOS /var and /tmp aliases are symlinks; use a canonical fixture parent.
    return tmp_path_factory.mktemp("offline-cli-boundary").resolve()


def cli_environment(package_path=SOURCE_ROOT):
    environment = dict(os.environ)
    # -S excludes editable .pth files; every run has one explicit package origin.
    environment["PYTHONPATH"] = str(package_path)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONNOUSERSITE"] = "1"
    environment.pop("PYTHONSTARTUP", None)
    return environment


def run_cli(args, *, cwd, package_path=SOURCE_ROOT, stdin=None, timeout=5):
    return subprocess.run([sys.executable, "-S", "-m", "cbus_toolkit.offline_workflows", "--compact", *args],
        cwd=cwd, env=cli_environment(package_path), input=stdin, capture_output=True,
        timeout=timeout, check=False)


def input_args(path, *, workflow="copy-paste", action="inspect", output=None):
    args = [workflow, action, "--input", str(path)]
    if output is not None:
        args += ["--output", str(output)]
    return args


def assert_json_error(process, expected):
    assert process.returncode == expected, (process.stdout, process.stderr)
    assert process.stdout == b""
    document = json.loads(process.stderr)
    assert isinstance(document, dict) and document
    assert document["format"] == "cbus-offline-workflows-cli-v1"
    assert document["preparation_only"] is True
    for flag in ("execution_enabled", "native_execution_enabled", "original_compatibility_verified", "external_persistence_verified"):
        assert document[flag] is False
    assert isinstance(document["error"]["code"], str)
    assert isinstance(document["error"]["message"], str)
    assert b"Traceback" not in process.stderr
    return document


@pytest.mark.parametrize("payload", [
    b'{"format":"first","format":"duplicate"}',
    b'{"outer":{"value":1,"value":2}}',
    b'{"value":NaN}', b'{"value":Infinity}', b'{"value":-Infinity}',
    b'{"value":1e9999}', b'{} {}', b'{} trailing', b'\xff',
    b'\xef\xbb\xbf{}', b'', b'null', b'[]', b'"scalar"',
])
def test_bad_json_and_nonobject_input_have_stable_json_errors(tmp_path, payload):
    source = tmp_path / "input.json"
    source.write_bytes(payload)
    before = source.read_bytes()
    process = run_cli(input_args(source), cwd=tmp_path)
    assert_json_error(process, 2)
    assert source.read_bytes() == before
    assert sorted(path.name for path in tmp_path.iterdir()) == ["input.json"]


@pytest.mark.parametrize("payload", [
    b'{"nested":' + b'[' * 160 + b'0' + b']' * 160 + b'}',
    b'{"nodes":[' + b'0,' * 100_000 + b'0]}',
    b' ' * (MAX_INPUT_BYTES + 1),
], ids=["depth", "nodes", "bytes"])
def test_resource_bounds_refuse_before_dispatch_and_create_no_output(tmp_path, payload):
    source = tmp_path / "input.json"
    source.write_bytes(payload)
    process = run_cli(input_args(source), cwd=tmp_path)
    assert_json_error(process, 2)
    assert source.stat().st_size == len(payload)
    assert sorted(path.name for path in tmp_path.iterdir()) == ["input.json"]


def test_missing_input_file_and_directory_are_io_errors(tmp_path):
    missing = tmp_path / "missing.json"
    assert_json_error(run_cli(input_args(missing), cwd=tmp_path), 4)
    directory = tmp_path / "directory"
    directory.mkdir()
    assert_json_error(run_cli(input_args(directory), cwd=tmp_path), 4)


def test_input_symlink_is_never_followed(tmp_path):
    target = tmp_path / "real.json"
    target.write_bytes(b'{}')
    link = tmp_path / "input.json"
    link.symlink_to(target)
    assert_json_error(run_cli(input_args(link), cwd=tmp_path), 4)
    assert target.read_bytes() == b'{}'
    assert link.is_symlink()


def test_fifo_input_refuses_promptly_without_waiting_for_a_writer(tmp_path):
    source = tmp_path / "input.fifo"
    os.mkfifo(source)
    assert_json_error(run_cli(input_args(source), cwd=tmp_path, timeout=3), 4)


def test_unix_socket_input_refuses_as_a_special_file(tmp_path):
    with tempfile.TemporaryDirectory(prefix="cb-offline-", dir="/private/tmp") as folder:
        source = Path(folder) / "i.sock"
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as special:
            special.bind(str(source))
            assert_json_error(run_cli(input_args(source), cwd=tmp_path), 4)


def test_device_input_and_implicit_stdin_are_refused(tmp_path):
    assert_json_error(run_cli(input_args(Path('/dev/null')), cwd=tmp_path), 4)
    assert_json_error(run_cli(["copy-paste", "inspect"], cwd=tmp_path, stdin=b'{}'), 2)
    assert_json_error(run_cli(input_args("-"), cwd=tmp_path, stdin=b'{}'), 4)


@pytest.mark.parametrize("arguments", [
    [], ["unknown", "inspect"], ["copy-paste", "unknown"],
    ["copy-paste", "inspect", "--input"], ["copy-paste", "inspect", "--apply"],
    ["copy-paste", "inspect", "--execute"], ["copy-paste", "inspect", "--host", "fake"],
])
def test_usage_errors_are_json_and_never_expose_an_execution_adapter(tmp_path, arguments):
    assert_json_error(run_cli(arguments, cwd=tmp_path), 2)


def test_help_is_available_without_files_and_documents_only_offline_actions(tmp_path):
    process = run_cli(["--help"], cwd=tmp_path)
    assert process.returncode == 0
    assert process.stderr == b""
    text = process.stdout.decode()
    assert "copy-paste" in text and "transfer-restore" in text
    assert "--host" not in text and "--apply" not in text


def copy_example(tmp_path):
    source = tmp_path / "input.json"
    source.write_bytes((PACKAGE_ROOT / "examples" / "copy-paste.json").read_bytes())
    return source


def assert_report(process, expected=0):
    assert process.returncode == expected, (process.stdout, process.stderr)
    assert process.stderr == b""
    report = json.loads(process.stdout)
    assert report["format"] == "cbus-offline-workflows-cli-v1"
    assert report["preparation_only"] is True
    for flag in ("execution_enabled", "native_execution_enabled", "original_compatibility_verified", "external_persistence_verified"):
        assert report[flag] is False
    return report


def test_safe_output_is_exclusive_private_and_matches_stdout_exactly(tmp_path):
    source = copy_example(tmp_path)
    original = source.read_bytes()
    output = tmp_path / "new.json"
    process = run_cli(input_args(source, action="plan", output=output), cwd=tmp_path)
    report = assert_report(process)
    assert report["workflow"] == "copy-paste"
    assert report["operation"] == "plan"
    assert output.read_bytes() == process.stdout
    assert output.stat().st_mode & 0o777 == 0o600
    assert source.read_bytes() == original
    assert sorted(path.name for path in tmp_path.iterdir()) == ["input.json", "new.json"]
    assert_json_error(run_cli(input_args(source, action="plan", output=output), cwd=tmp_path), 4)
    assert output.read_bytes() == process.stdout
    assert source.read_bytes() == original
    assert sorted(path.name for path in tmp_path.iterdir()) == ["input.json", "new.json"]


def test_output_equal_to_input_never_clobbers_input(tmp_path):
    source = copy_example(tmp_path)
    original = source.read_bytes()
    assert_json_error(run_cli(input_args(source, output=source), cwd=tmp_path), 4)
    assert source.read_bytes() == original


@pytest.mark.parametrize("special_kind", ["symlink", "directory", "fifo"])
def test_output_existing_special_objects_and_link_targets_are_preserved(tmp_path, special_kind):
    source = copy_example(tmp_path)
    output = tmp_path / "output"
    sentinel = tmp_path / "sentinel.json"
    sentinel.write_bytes(b"existing private sentinel")
    if special_kind == "symlink":
        output.symlink_to(sentinel)
    elif special_kind == "directory":
        output.mkdir()
    else:
        os.mkfifo(output)
    assert_json_error(run_cli(input_args(source, output=output), cwd=tmp_path, timeout=3), 4)
    assert sentinel.read_bytes() == b"existing private sentinel"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["input.json", "output", "sentinel.json"]
    if special_kind == "symlink":
        assert output.is_symlink()


def test_input_and_output_symlink_ancestors_are_not_traversed(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    source = copy_example(real)
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)
    assert_json_error(run_cli(input_args(alias / "input.json"), cwd=tmp_path), 4)
    assert_json_error(run_cli(input_args(source, output=alias / "output.json"), cwd=tmp_path), 4)
    assert list(real.iterdir()) == [source]
    assert alias.is_symlink()


def test_parallel_publish_has_one_winner_and_one_clean_refusal(tmp_path):
    source = copy_example(tmp_path)
    output = tmp_path / "output.json"
    command = [sys.executable, "-S", "-m", "cbus_toolkit.offline_workflows", "--compact",
               *input_args(source, action="plan", output=output)]
    children = [subprocess.Popen(command, cwd=tmp_path, env=cli_environment(), stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE) for _ in range(2)]
    captures = [child.communicate(timeout=10) for child in children]
    assert sorted(child.returncode for child in children) == [0, 4]
    winner = next(index for index, child in enumerate(children) if child.returncode == 0)
    loser = 1 - winner
    assert captures[winner][1] == b""
    assert captures[loser][0] == b""
    assert json.loads(captures[loser][1])["error"]
    assert output.read_bytes() == captures[winner][0]
    assert output.stat().st_mode & 0o777 == 0o600
    assert sorted(path.name for path in tmp_path.iterdir()) == ["input.json", "output.json"]


def test_unsupported_report_is_stdout_exit_three_and_can_be_saved_as_review_material(tmp_path):
    source = copy_example(tmp_path)
    value = json.loads(source.read_bytes())
    value["profile"]["mode"] = "original-native-unverified"
    source.write_text(json.dumps(value), encoding="utf-8")
    output = tmp_path / "unsupported.json"
    process = run_cli(input_args(source, action="plan", output=output), cwd=tmp_path)
    report = assert_report(process, 3)
    assert report["report"]["outcome"] == "unsupported"
    assert output.read_bytes() == process.stdout
    assert report["report"]["component"]["commands"] == []


@pytest.mark.parametrize("field", ["execution_enabled", "native_execution_enabled", "original_compatibility_verified", "external_persistence_verified"])
def test_caller_cannot_inject_execution_or_acceptance_authority(tmp_path, field):
    source = copy_example(tmp_path)
    value = json.loads(source.read_bytes())
    value[field] = True
    source.write_text(json.dumps(value), encoding="utf-8")
    assert_json_error(run_cli(input_args(source, action="plan"), cwd=tmp_path), 2)
    assert sorted(path.name for path in tmp_path.iterdir()) == ["input.json"]


def test_shared_decoder_bounds_are_actual_parse_bounds_not_schema_refusals():
    from cbus_toolkit.offline_workflows.cli_support import InputError, decode_json, json_bytes
    for raw, code in ((b'{"a":1,"a":2}', "duplicate_json_key"),
                      (b'{"a":1e9999}', "invalid_json"),
                      (b'{"a":' + b'[' * 65 + b'0' + b']' * 65 + b'}', "json_limit"),
                      (b'{"a":[' + b'0,' * 100_000 + b'0]}', "json_limit"),
                      (b' ' * (MAX_INPUT_BYTES + 1), "input_too_large")):
        with pytest.raises(InputError) as error:
            decode_json(raw)
        assert error.value.code == code
    exact_nodes = b'{"a":[' + b'0,' * 99_997 + b'0]}'
    assert len(decode_json(exact_nodes)["a"]) == 99_998
    with pytest.raises(InputError) as error:
        json_bytes({"large": "x" * 500}, max_bytes=128)
    assert error.value.code == "output_too_large"


def test_symlink_parent_followed_by_dotdot_cannot_be_normalized_away(tmp_path):
    main = tmp_path / "main"
    main.mkdir()
    source = copy_example(main)
    outside = tmp_path / "outside"
    outside.mkdir()
    child = outside / "child"
    child.mkdir()
    outside_input = outside / "input.json"
    outside_input.write_bytes(b"outside selection sentinel")
    alias = main / "alias"
    alias.symlink_to(child, target_is_directory=True)
    ambiguous_input = str(alias) + "/../input.json"
    ambiguous_output = str(alias) + "/../output.json"
    assert_json_error(run_cli(input_args(ambiguous_input), cwd=tmp_path), 4)
    assert_json_error(run_cli(input_args(source, output=ambiguous_output), cwd=tmp_path), 4)
    assert outside_input.read_bytes() == b"outside selection sentinel"
    assert not (outside / "output.json").exists()
    assert not (main / "output.json").exists()


@pytest.mark.parametrize("raw", [b'{"x":"\\ud800"}', b'{"x":"\\udfff"}', b'{"\\ud800":1}'])
def test_escaped_unpaired_surrogate_scalar_refuses_before_workflow_processing(tmp_path, raw):
    source = tmp_path / "input.json"
    source.write_bytes(raw)
    report = assert_json_error(run_cli(input_args(source), cwd=tmp_path), 2)
    assert report["error"]["code"] == "invalid_json"


@pytest.mark.parametrize("replacement", [False, True], ids=["grows-during-read", "pathname-replaced"])
def test_input_snapshot_metadata_and_named_inode_are_bracketed(tmp_path, monkeypatch, replacement):
    from cbus_toolkit.offline_workflows import cli
    source = copy_example(tmp_path)
    initial = source.read_bytes()
    original_read = cli.os.read
    changed = False

    def changing_read(descriptor, count):
        nonlocal changed
        chunk = original_read(descriptor, count)
        if chunk and not changed:
            changed = True
            if replacement:
                source.rename(tmp_path / "old-input.json")
                source.write_bytes(initial)
            else:
                source.write_bytes(initial + b" changed")
        return chunk

    monkeypatch.setattr(cli.os, "read", changing_read)
    with pytest.raises(cli.FileBoundaryError) as error:
        cli.read_regular_input(source)
    assert error.value.code == "input_changed"
    assert changed


def test_output_temporary_name_collision_does_not_delete_a_foreign_file(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from cbus_toolkit.offline_workflows import cli
    fixed = "0" * 32
    foreign = tmp_path / (".cbus-offline-" + fixed + ".tmp")
    foreign.write_bytes(b"foreign temporary sentinel")
    monkeypatch.setattr(cli.uuid, "uuid4", lambda: SimpleNamespace(hex=fixed))
    output = tmp_path / "output.json"
    with pytest.raises(cli.FileBoundaryError):
        cli.write_new_output(output, b'{"complete":true}\n')
    assert foreign.read_bytes() == b"foreign temporary sentinel"
    assert not output.exists()


def test_output_target_created_after_precheck_is_retained_and_owned_temp_cleaned(tmp_path, monkeypatch):
    from cbus_toolkit.offline_workflows import cli
    output = tmp_path / "output.json"
    original_link = cli.os.link

    def collide(source, destination, **arguments):
        output.write_bytes(b"competing output sentinel")
        return original_link(source, destination, **arguments)

    monkeypatch.setattr(cli.os, "link", collide)
    with pytest.raises(cli.FileBoundaryError) as error:
        cli.write_new_output(output, b'{"complete":true}\n')
    assert error.value.code == "output_exists"
    assert output.read_bytes() == b"competing output sentinel"
    assert list(tmp_path.iterdir()) == [output]


@pytest.mark.parametrize("fail_on", [1, 2], ids=["before-publication", "after-publication"])
def test_output_sync_failures_distinguish_unpublished_and_published_unconfirmed(tmp_path, monkeypatch, fail_on):
    from cbus_toolkit.offline_workflows import cli
    output = tmp_path / "output.json"
    payload = b'{"complete":true,"execution_enabled":false}\n'
    original_sync = cli.os.fsync
    calls = 0

    def fault(descriptor):
        nonlocal calls
        calls += 1
        if calls == fail_on:
            raise OSError("synthetic sync failure")
        return original_sync(descriptor)

    monkeypatch.setattr(cli.os, "fsync", fault)
    with pytest.raises(cli.FileBoundaryError) as error:
        cli.write_new_output(output, payload)
    if fail_on == 1:
        assert error.value.code == "output_file_error"
        assert not output.exists()
        assert list(tmp_path.iterdir()) == []
    else:
        assert error.value.code == "output_published_unconfirmed"
        assert output.read_bytes() == payload
        assert list(tmp_path.iterdir()) == [output]
        with pytest.raises(cli.FileBoundaryError) as repeated:
            cli.write_new_output(output, payload)
        assert repeated.value.code == "output_exists"
        assert output.read_bytes() == payload


@pytest.mark.parametrize("replacement_kind", ["symlink", "regular"])
@pytest.mark.parametrize("phase", ["before-link", "during-link"])
def test_output_temporary_path_replacement_never_claims_success_or_deletes_foreign_file(tmp_path, monkeypatch, replacement_kind, phase):
    from cbus_toolkit.offline_workflows import cli
    output = tmp_path / "output.json"
    retained_owned = tmp_path / "retained-owned.json"
    sentinel = tmp_path / "foreign.json"
    foreign_bytes = b"foreign replacement sentinel"
    sentinel.write_bytes(foreign_bytes)
    payload = b'{"complete":true,"execution_enabled":false}\n'
    original_sync = cli.os.fsync
    original_link = cli.os.link
    replaced = None

    def replace_temporary():
        nonlocal replaced
        candidates = list(tmp_path.glob(".cbus-offline-*.tmp"))
        assert len(candidates) == 1
        replaced = candidates[0]
        replaced.rename(retained_owned)
        if replacement_kind == "symlink":
            replaced.symlink_to(sentinel)
        else:
            replaced.write_bytes(foreign_bytes)

    def sync_then_replace(descriptor):
        result = original_sync(descriptor)
        if replaced is None:
            replace_temporary()
        return result

    def replace_then_link(source, destination, **arguments):
        replace_temporary()
        return original_link(source, destination, **arguments)

    if phase == "before-link":
        monkeypatch.setattr(cli.os, "fsync", sync_then_replace)
    else:
        monkeypatch.setattr(cli.os, "link", replace_then_link)
    with pytest.raises(cli.FileBoundaryError) as error:
        cli.write_new_output(output, payload)
    assert error.value.code == ("output_changed" if phase == "before-link" else "output_published_unconfirmed")
    assert retained_owned.read_bytes() == payload
    assert sentinel.read_bytes() == foreign_bytes
    assert replaced is not None
    assert replaced.read_bytes() == foreign_bytes
    assert replaced.is_symlink() is (replacement_kind == "symlink")
    if phase == "before-link":
        assert not output.exists()
    else:
        assert output.read_bytes() == foreign_bytes
        assert output.is_symlink() is (replacement_kind == "symlink")
