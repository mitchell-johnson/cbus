"""The scoped native differential is strict about source and wire framing."""
from __future__ import annotations

from copy import deepcopy
import importlib.util
import io
import json
from pathlib import Path
import re

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "research/cgate_session_differential.py"
spec = importlib.util.spec_from_file_location("cgate_session_differential", SCRIPT)
differential = importlib.util.module_from_spec(spec)
spec.loader.exec_module(differential)


def test_native_capture_preserves_three_internal_console_rows():
    native = differential.validate_native()
    canonical, console_rows = differential.canonicalize(native["cases"][:9])
    assert len(canonical) == 9
    assert len(console_rows) == 3
    assert canonical[2] == [
        "300-sessionID=<internal-console> origin=internal from=<time-console> tag=Console",
        "300-sessionID=<a> origin=/127.0.0.1:<port-a> from=<time-a>",
        "300 sessionID=<b> origin=/127.0.0.1:<port-b> from=<time-b>",
    ]
    assert canonical[5] == ["408 Operation failed: tag name has already been set"]


def test_unexpected_internal_row_is_not_filtered():
    cases = deepcopy(differential.validate_native()["cases"][:9])
    cases[2]["reply"][0] = cases[2]["reply"][0].replace("tag=Console", "tag=Other")
    with pytest.raises(ValueError, match="unexpected external row"):
        differential.canonicalize(cases)


def test_missing_rust_console_row_fails_complete_comparison():
    cases = deepcopy(differential.validate_native()["cases"][:9])
    cases[2]["reply"].pop(0)
    with pytest.raises(ValueError, match="exactly three internal Console rows"):
        differential.canonicalize(cases)


def test_inconsistent_rust_console_timestamp_is_rejected():
    cases = deepcopy(differential.validate_native()["cases"][:9])
    cases[4]["reply"][0] = cases[4]["reply"][0].replace(
        "from=20260925-211912", "from=20260925-211913"
    )
    with pytest.raises(ValueError, match="Console connection time changed"):
        differential.canonicalize(cases)


def test_client_tag_echo_must_match_exactly():
    stream = io.BytesIO(b"[wrong] 300 sessionID=cmd3\r\n")
    with pytest.raises(ValueError, match="did not echo client-assigned tag"):
        differential.read_reply(stream, "requested")


def test_rust_reply_must_use_native_crlf():
    stream = io.BytesIO(b"[requested] 300 sessionID=cmd3\n")
    with pytest.raises(ValueError, match="native CRLF framing"):
        differential.read_reply(stream, "requested")


def test_connected_server_with_wrong_greeting_is_behavior_failure(tmp_path, monkeypatch):
    binary = tmp_path / "mock"
    binary.write_bytes(b"binary")
    binary.chmod(0o755)

    def bad_greeting(_binary):
        raise differential.ProbeGreetingError("Rust greeting does not use native CRLF framing")

    monkeypatch.setattr(differential, "probe", bad_greeting)
    receipt, code = differential.run(binary, "current-build")
    assert code == 1
    assert receipt["result"] == "failed"
    assert receipt["greeting_result"] == "failed"
    assert receipt["executed"] == 0
    assert receipt["skipped"] == 9


def test_stale_native_capture_fails_before_probe(tmp_path, monkeypatch):
    altered = tmp_path / "native.json"
    altered.write_bytes(differential.NATIVE.read_bytes() + b"\n")
    monkeypatch.setattr(differential, "NATIVE", altered)
    with pytest.raises(ValueError, match="native capture hash changed"):
        differential.validate_native()


def test_passed_receipt_rejects_missing_or_stale_source_binding():
    receipt_path = SCRIPT.parent / "fixtures/cgate-session-differential-fixed.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    differential.validate_passed_receipt(receipt)
    stale = deepcopy(receipt)
    stale["source_fingerprint"]["rust/cbus-cgate/src/main.rs"] = "0" * 64
    with pytest.raises(ValueError, match="source fingerprint is stale"):
        differential.validate_passed_receipt(stale)
    partial = deepcopy(receipt)
    partial["skipped"] = 1
    with pytest.raises(ValueError, match="did not pass all nine"):
        differential.validate_passed_receipt(partial)


@pytest.mark.parametrize(
    ("product", "source_name"),
    [
        ("cgate-mock", "rust/cbus-protocol/src/lib.rs"),
        ("cgate-mock", "rust/cbus-transport/src/lib.rs"),
        ("cmqttd", "rust/cbus-protocol/src/lib.rs"),
        ("cmqttd", "rust/cbus-transport/src/lib.rs"),
        ("cmqttd", "rust/cbus-mqtt/src/lib.rs"),
        ("cmqttd", "rust/cbus-test-support/src/lib.rs"),
        ("cmqttd", "rust/cbus-mqtt/Cargo.toml"),
        ("cgate-mock", "rust/testdata/fixtures/native_cgate_dali_help.json"),
    ],
)
def test_transitive_workspace_change_invalidates_passed_receipt(
    product, source_name, monkeypatch
):
    fixture = ("cgate-session-differential-cmqttd.json" if product == "cmqttd"
               else "cgate-session-differential-fixed.json")
    receipt = json.loads((SCRIPT.parent / "fixtures" / fixture).read_text(encoding="utf-8"))
    daemon = product == "cmqttd"
    receipt["source_fingerprint"] = differential.source_fingerprint(daemon=daemon)
    source = differential.ROOT / source_name
    key = source.relative_to(differential.ROOT).as_posix()
    assert key in receipt["source_fingerprint"]
    differential.validate_passed_receipt(receipt)

    original_digest = differential.digest
    monkeypatch.setattr(
        differential, "digest",
        lambda path: "0" * 64 if path == source else original_digest(path),
    )
    with pytest.raises(ValueError, match="source fingerprint is stale"):
        differential.validate_passed_receipt(receipt)


@pytest.mark.parametrize(
    ("include", "error"),
    [
        ('include_str!("missing.json")', "include is missing"),
        ('include_str!(concat!("data", ".json"))', "nonliteral include"),
    ],
)
def test_untracked_rust_include_fails_closed(tmp_path, monkeypatch, include, error):
    workspace = tmp_path / "rust"
    crate = workspace / "cbus-cgate"
    (crate / "src").mkdir(parents=True)
    (workspace / "Cargo.toml").write_text("[workspace]\n", encoding="utf-8")
    (crate / "Cargo.toml").write_text("[package]\nname = 'cbus-cgate'\n", encoding="utf-8")
    (crate / "src/main.rs").write_text(include, encoding="utf-8")
    monkeypatch.setattr(differential, "ROOT", tmp_path)
    with pytest.raises(ValueError, match=error):
        differential.rust_source_paths()


def test_literal_rust_include_inside_repository_but_outside_workspace_is_fingerprinted(
    tmp_path, monkeypatch
):
    workspace = tmp_path / "rust"
    crate = workspace / "cbus-cgate"
    source_dir = crate / "src"
    source_dir.mkdir(parents=True)
    (workspace / "Cargo.toml").write_text("[workspace]\n", encoding="utf-8")
    (crate / "Cargo.toml").write_text("[package]\nname = 'cbus-cgate'\n", encoding="utf-8")
    asset = tmp_path / "toolkit-cli/research/local_cgate.py"
    asset.parent.mkdir(parents=True)
    asset.write_text("# bounded fixture\n", encoding="utf-8")
    (source_dir / "lib.rs").write_text(
        'const HARNESS: &[u8] = include_bytes!("../../../toolkit-cli/research/local_cgate.py");\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(differential, "ROOT", tmp_path)
    assert asset.resolve() in differential.rust_source_paths()


def test_literal_rust_include_outside_repository_fails_closed(tmp_path, monkeypatch):
    workspace = tmp_path / "rust"
    crate = workspace / "cbus-cgate"
    source_dir = crate / "src"
    source_dir.mkdir(parents=True)
    (workspace / "Cargo.toml").write_text("[workspace]\n", encoding="utf-8")
    (crate / "Cargo.toml").write_text("[package]\nname = 'cbus-cgate'\n", encoding="utf-8")
    outside = tmp_path.parent / f"{tmp_path.name}-outside.txt"
    outside.write_text("outside\n", encoding="utf-8")
    (source_dir / "lib.rs").write_text(
        f'const OUTSIDE: &str = include_str!("../../../../{outside.name}");\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(differential, "ROOT", tmp_path)
    with pytest.raises(ValueError, match="include escapes the repository"):
        differential.rust_source_paths()


def test_rust_source_resolving_outside_workspace_fails_closed(tmp_path, monkeypatch):
    workspace = tmp_path / "rust"
    crate = workspace / "cbus-cgate"
    (crate / "src").mkdir(parents=True)
    (workspace / "Cargo.toml").write_text("[workspace]\n", encoding="utf-8")
    (crate / "Cargo.toml").write_text("[package]\nname = 'cbus-cgate'\n", encoding="utf-8")
    external = tmp_path / "external.rs"
    external.write_text("fn external() {}\n", encoding="utf-8")
    source = crate / "src/lib.rs"
    source.write_text("fn source() {}\n", encoding="utf-8")
    original_resolve = Path.resolve
    monkeypatch.setattr(
        Path, "resolve",
        lambda path, *args, **kwargs: external if path == source
        else original_resolve(path, *args, **kwargs),
    )
    monkeypatch.setattr(differential, "ROOT", tmp_path)
    with pytest.raises(ValueError, match="source escapes the workspace"):
        differential.rust_source_paths()


def test_cmqttd_receipt_is_separate_and_fully_executed():
    receipt_path = SCRIPT.parent / "fixtures/cgate-session-differential-cmqttd.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["product"] == "cmqttd"
    assert re.fullmatch(r"[0-9a-f]{64}", receipt["rust_artifact"]["sha256"])
    differential.validate_passed_receipt(receipt)


def test_broken_tagged_reply_is_a_red_executed_case_not_a_blocked_skip(tmp_path, monkeypatch):
    binary = tmp_path / "mock"
    binary.write_bytes(b"binary")
    binary.chmod(0o755)

    def broken_probe(_binary):
        raise differential.ProbeBehaviorError([], "session-query-a", ValueError("wrong tag"))

    monkeypatch.setattr(differential, "probe", broken_probe)
    receipt, code = differential.run(binary, "current-build")
    assert code == 1
    assert (receipt["result"], receipt["executed"], receipt["failed"], receipt["skipped"]) == (
        "failed", 1, 1, 8
    )


def test_pre_fix_receipt_is_red_without_skipped_cases():
    receipt_path = SCRIPT.parent / "fixtures/cgate-session-differential-pre-fix.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["rust_artifact"]["sha256"] == (
        "1dbc9c1c041da90993e407c68131c49748dd3435cacd8b6d9dcecfe78c1fb242"
    )
    assert (receipt["result"], receipt["executed"], receipt["passed"],
            receipt["failed"], receipt["skipped"]) == ("failed", 9, 0, 9, 0)
    with pytest.raises(ValueError, match="receipt format changed"):
        differential.validate_passed_receipt(receipt)
    receipt["format"] = "cgate-session-differential-v2"
    receipt["source_fingerprint"] = differential.source_fingerprint()
    receipt["pilot_manifest"]["sha256"] = differential.digest(differential.PILOT)
    with pytest.raises(ValueError, match="lacks exact current Rust artifact hash"):
        differential.validate_passed_receipt(receipt)
