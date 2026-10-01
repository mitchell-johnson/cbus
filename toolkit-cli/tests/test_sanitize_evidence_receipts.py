"""Offline publication seam: preserve evidence, reject unreviewed coordinates."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import stat
import tempfile

import pytest

from research import build_parity_register as builder
from research import sanitize_evidence_receipts as sanitizer
from cbus_toolkit import parity


ROOT = Path(__file__).resolve().parents[1]
CASES = [
    ("session", "cgate-session-differential-fixed.json"),
    ("session", "cgate-session-differential-cmqttd.json"),
    ("tagged", "cgate-tagged-session-differential-cgate-mock.json"),
    ("tagged", "cgate-tagged-session-differential-cmqttd.json"),
    ("unit", "cgate-dbsetxml-unit-differential-mock.json"),
    ("unit", "cgate-dbsetxml-unit-differential-cmqttd.json"),
]


def fixture(name):
    return raw_test_input(ROOT / "research/fixtures" / name)


def encode(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()


def raw_test_input(path):
    """Also work after publication, using synthetic invocation coordinates.

    Reconstructed test metadata is never a retained raw execution receipt.
    Technical fields come from the validated committed fixture unchanged.
    """
    raw = path.read_bytes()
    value = json.loads(raw)
    if sanitizer.MARKER not in value:
        return raw
    value.pop(sanitizer.MARKER)
    roles = {
        "CBUS_EVIDENCE_PYTHON": "/tmp/cbus-private-evidence/bin/python",
        "CBUS_ACCEPTANCE_PYTHONPATH": "/tmp/cbus-private-evidence/pythonpath",
        "CBUS_CGATE_MOCK_BIN": "/tmp/cbus-private-evidence/bin/cgate-mock",
        "CBUS_CMQTTD_BIN": "/tmp/cbus-private-evidence/bin/cmqttd",
        "CBUS_DIFFERENTIAL_OUTPUT_DIR": "/tmp/cbus-private-evidence/output",
        "CBUS_TEST_ROOT": "/tmp/cbus-private-evidence/tests",
    }

    def invocation(command):
        for role, coordinate in roles.items():
            command = command.replace("${" + role + "}", coordinate)
        return command

    if "receipts" in value:
        for receipt in value["receipts"]:
            for record in receipt["integration"]["commands"]:
                record["command"] = invocation(record["command"])
    else:
        key = "binary" if "binary" in value else "rust_artifact"
        value[key].pop("name")
        value[key]["path"] = "/tmp/cbus-private-evidence/bin/" + value["product"]
        value["command"] = invocation(value["command"])
    return encode(value)


def check_archive(raw, derivative, archive, kind):
    marker = derivative[sanitizer.MARKER]
    digest = sha256(raw).hexdigest()
    assert marker["raw_file_sha256"] == digest
    saved = archive / f"{kind}-{digest}.json"
    assert saved.read_bytes() == raw
    assert stat.S_IMODE(saved.stat().st_mode) == 0o600
    assert stat.S_IMODE(archive.stat().st_mode) == 0o700
    assert marker["raw_retained_privately"] is True
    assert marker["technical_payload_preserved"] is True
    assert marker["new_execution_claimed_by_sanitization"] is False
    assert not sanitizer.local_coordinate_fields(derivative)


@pytest.mark.parametrize(("kind", "name"), CASES)
def test_all_six_receipts_preserve_every_noncoordinate_field(kind, name, tmp_path):
    raw = fixture(name)
    original = json.loads(raw)
    archive = tmp_path / "private"
    output = sanitizer.sanitize(raw, kind=kind, private_raw_dir=archive)
    derivative = json.loads(output)
    check_archive(raw, derivative, archive, kind)
    artifact = "binary" if kind == "unit" else "rust_artifact"
    expected = deepcopy(original)
    expected[artifact].pop("path")
    expected[artifact]["name"] = original["product"]
    expected["command"] = derivative["command"]
    payload = {key: value for key, value in derivative.items() if key != sanitizer.MARKER}
    # A boolean comparison avoids including raw coordinates in assertion output.
    assert payload == expected, "a technical field changed"
    assert derivative["command"].strip()
    assert "${CBUS_" in derivative["command"]
    assert derivative[artifact]["sha256"] == original[artifact]["sha256"]
    assert {row["json_pointer"] for row in derivative[sanitizer.MARKER]["field_mapping"]} == {
        f"/{artifact}/path", "/command",
    }
    sanitizer._validator(kind)(derivative)
    assert sanitizer.sanitize(raw, kind=kind, private_raw_dir=archive) == output


def test_closure_changes_only_three_commands_and_keeps_strict_nested_schema(tmp_path):
    raw = raw_test_input(builder.CLOSURE_RECEIPTS_PATH)
    original = json.loads(raw)
    archive = tmp_path / "private"
    derivative = json.loads(sanitizer.sanitize(raw, kind="closure", private_raw_dir=archive))
    check_archive(raw, derivative, archive, "closure")
    expected = deepcopy(original)
    mappings = derivative[sanitizer.MARKER]["field_mapping"]
    assert len(mappings) == 3
    for mapping in mappings:
        keys = mapping["json_pointer"].strip("/").split("/")
        index, command_index = int(keys[1]), int(keys[4])
        new_command = derivative["receipts"][index]["integration"]["commands"][command_index]["command"]
        expected["receipts"][index]["integration"]["commands"][command_index]["command"] = new_command
        assert new_command.strip() and "${CBUS_" in new_command
    payload = {key: value for key, value in derivative.items() if key != sanitizer.MARKER}
    assert payload == expected, "closure claims, counts or source bindings changed"
    for receipt in derivative["receipts"]:
        assert set(receipt) == parity.CLOSURE_RECEIPT_KEYS
        assert sanitizer.MARKER not in receipt["integration"]


@pytest.mark.parametrize(("kind", "name"), [*CASES, ("closure", None)])
def test_future_published_fixtures_support_synthetic_metadata_tests(kind, name, tmp_path):
    raw = fixture(name) if name else raw_test_input(builder.CLOSURE_RECEIPTS_PATH)
    published = sanitizer.sanitize(raw, kind=kind, private_raw_dir=tmp_path / "private")
    path = tmp_path / "published.json"
    path.write_bytes(published)
    reconstructed = raw_test_input(path)
    value = json.loads(reconstructed)
    assert sanitizer.MARKER not in value
    repeated = json.loads(sanitizer.sanitize(reconstructed, kind=kind,
                                             private_raw_dir=tmp_path / "private"))
    first = json.loads(published)
    if kind != "closure":
        assert repeated["source_fingerprint"] == first["source_fingerprint"]
        artifact = "binary" if kind == "unit" else "rust_artifact"
        assert repeated[artifact]["sha256"] == first[artifact]["sha256"]
    else:
        assert repeated["receipts"] == first["receipts"], "closure technical metadata changed"


def test_actual_offline_generator_accepts_derivatives_and_binds_their_bytes(tmp_path, monkeypatch):
    # Only sanitized temporary inputs live under the trusted artifact root. Raw
    # originals are outside Git; no tracked output or source fingerprint changes.
    with tempfile.TemporaryDirectory(prefix="publication-proof-", dir=ROOT / "research") as folder:
        temporary = Path(folder)
        inputs = [
            ("session", builder.SESSION_DIFFERENTIAL_PATH, "SESSION_DIFFERENTIAL_PATH"),
            ("tagged", builder.TAGGED_SESSION_DIFFERENTIAL_PATH, "TAGGED_SESSION_DIFFERENTIAL_PATH"),
            ("closure", builder.CLOSURE_RECEIPTS_PATH, "CLOSURE_RECEIPTS_PATH"),
        ]
        for kind, source, constant in inputs:
            output = temporary / source.name
            output.write_bytes(sanitizer.sanitize(raw_test_input(source), kind=kind,
                                                 private_raw_dir=tmp_path / "private"))
            monkeypatch.setattr(builder, constant, output)
        register, evidence = builder.build()
        assert not sanitizer.local_coordinate_fields(register)
        assert not sanitizer.local_coordinate_fields(evidence)
        for record, constant in zip(evidence["records"][:2],
                                    ("SESSION_DIFFERENTIAL_PATH", "TAGGED_SESSION_DIFFERENTIAL_PATH")):
            report_path = getattr(builder, constant)
            assert record["command"] == json.loads(report_path.read_bytes())["command"]
            assert record["report_verification"]["path"] == report_path.relative_to(ROOT).as_posix()
            assert any(row["sha256"] == sha256(report_path.read_bytes()).hexdigest()
                       for row in record["artifacts"])
        evidence_raw = builder.render(evidence).encode()
        ledger_raw = builder.LEDGER_PATH.read_bytes()
        contracts_raw = builder.CGATE_CONTRACT_PATH.read_bytes()
        parity.validate_register(
            register, evidence, json.loads(ledger_raw), evidence_raw=evidence_raw,
            ledger_raw=ledger_raw, cgate_contract_inventory=json.loads(contracts_raw),
            cgate_contract_raw=contracts_raw, artifact_root=ROOT, source_root=ROOT.parent,
        )
        assert register["census_complete"] is False


@pytest.mark.parametrize("mutation", ["wire", "source", "unknown_path"])
def test_invalid_or_unmapped_evidence_is_refused_before_archiving(mutation, tmp_path):
    original = json.loads(fixture(CASES[0][1]))
    if mutation == "wire":
        original["result"] = "failed"
    elif mutation == "source":
        original["source_fingerprint"][next(iter(original["source_fingerprint"]))] = "0" * 64
    else:
        original["unreviewed_metadata"] = "/tmp/cbus-private-evidence/unmapped.json"
    archive = tmp_path / "private"
    with pytest.raises(ValueError):
        sanitizer.sanitize(encode(original), kind="session", private_raw_dir=archive)
    assert not archive.exists()


@pytest.mark.parametrize("raw", [b'{"a":1,"a":2}', b'{"a":NaN}', b'[]'])
def test_ambiguous_or_nonfinite_json_is_refused(raw):
    with pytest.raises(ValueError):
        sanitizer.parse(raw)


def test_no_resanitization_or_wrong_family(tmp_path):
    raw = fixture(CASES[0][1])
    output = sanitizer.sanitize(raw, kind="session", private_raw_dir=tmp_path / "private")
    with pytest.raises(ValueError):
        sanitizer.sanitize(output, kind="session", private_raw_dir=tmp_path / "private")
    with pytest.raises(ValueError):
        sanitizer.sanitize(raw, kind="unit", private_raw_dir=tmp_path / "private")


def test_raw_archive_cannot_be_inside_git(tmp_path):
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (checkout / ".git").write_text("gitdir: synthetic")
    with pytest.raises(ValueError, match="outside every Git checkout"):
        sanitizer._private_archive(b"raw", checkout / "private", "session")
    assert not (checkout / "private").exists()


def test_raw_archive_refuses_conflicts_and_symlinks(tmp_path):
    raw = b"raw"
    target = tmp_path / f"session-{sha256(raw).hexdigest()}.json"
    target.write_bytes(b"wrong")
    with pytest.raises(ValueError):
        sanitizer._private_archive(raw, tmp_path, "session")
    target.unlink()
    other = tmp_path / "other"
    other.write_bytes(raw)
    target.symlink_to(other)
    with pytest.raises(OSError):
        sanitizer._private_archive(raw, tmp_path, "session")


def test_command_roles_keep_test_selection_and_order():
    command = ("PYTHONPATH=/tmp/cbus-private-evidence/source "
               "/tmp/cbus-private-evidence/bin/python -m pytest -q "
               "/tmp/cbus-private-evidence/tests/test_one.py "
               "/tmp/cbus-private-evidence/tests/test_two.py")
    normalized, roles = sanitizer._template(command)
    assert normalized == ('PYTHONPATH="${CBUS_ACCEPTANCE_PYTHONPATH}" '
                          '"${CBUS_EVIDENCE_PYTHON}" -m pytest -q '
                          '"${CBUS_TEST_ROOT}/test_one.py" "${CBUS_TEST_ROOT}/test_two.py"')
    assert roles == ["acceptance_pythonpath", "acceptance_test_file", "python_interpreter"]


@pytest.mark.parametrize("command", [
    "python /tmp/cbus-private-evidence/unknown.py",
    "python /tmp/cbus-private-evidence/unknown.py && echo ok",
    "python research/script.py",
])
def test_unknown_roles_and_compound_commands_require_review(command):
    with pytest.raises(ValueError):
        sanitizer._template(command)


def test_scan_preserves_synthetic_loopback_and_public_provenance():
    synthetic = {"wire": "origin=/127.0.0.1:50000", "source": "rust/cbus-cgate/src/lib.rs",
                 "provenance": "https://example.invalid/original/binary", "sha256": "a" * 64}
    assert not sanitizer.local_coordinate_fields(synthetic)
    for value in ("~/private.json", "/srv/private.json", "C:\\Users\\synthetic\\private.json"):
        assert sanitizer.local_coordinate_fields({"metadata": value}) == ["/metadata"]
    assert sanitizer.local_coordinate_fields({"/tmp/private-key": "/tmp/private-value"}) == [
        "/<private-key>", "/<private-key>",
    ]


@pytest.mark.parametrize("residue", [
    "${CBUS_HOST_TEMP_ROOT}/ab/private_bucket/T/owned-scratch",
    "${CBUS_HOST_TEMP_ROOT}/ab/private_bucket/C/cache",
    "${CBUS_HOST_TEMP_ROOT}/pytest-of-synthetic/pytest-1/test_one/state.json",
    "${CBUS_TEST_ROOT}/pytest-of-synthetic/pytest-1/test_one/state.json",
])
def test_scan_rejects_account_coordinates_left_below_a_role(residue):
    assert sanitizer.local_coordinate_fields({"metadata": [residue]}) == ["/metadata/0"]
    assert sanitizer.local_coordinate_fields({residue: "public"}) == ["/<private-key>"]


def test_scan_accepts_complete_temporary_directory_roles():
    assert not sanitizer.local_coordinate_fields({
        "scratch": "${CBUS_NATIVE_WORK_ROOT}/tmp",
        "fixture": "${CBUS_TEST_WORK_ROOT}/test_one/state.json",
        "host_temp": "${CBUS_HOST_TEMP_ROOT}/owned-scratch",
    })
