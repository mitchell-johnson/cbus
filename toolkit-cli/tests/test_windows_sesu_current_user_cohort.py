"""The vendor-key observer must fail closed before touching HKCU."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from cbus_toolkit import windows_sesu_current_user_cohort as current


SID = "S-1-5-21-100-200-300-1001"
REG = SimpleNamespace(REG_SZ=1, REG_DWORD=4)


def test_retained_original_identity_and_native_probe_are_source_bound():
    root = Path(__file__).resolve().parents[1]
    fixture = json.loads((root / "research/fixtures/toolkit-update-rollout-original-registry-identity.json").read_text())
    assert fixture["original_assembly"]["sha256"] == current.ORIGINAL_SHA256
    assert fixture["original_assembly"]["size"] == current.ORIGINAL_SIZE
    assert fixture["identity"]["key"] == current.REGISTRY_KEY
    assert fixture["identity"]["entry"] == current.REGISTRY_ENTRY
    source = (root / "research/NativeSesuRegistryIdentityProbe.ps1").read_bytes()
    assert hashlib.sha256(source).hexdigest() == fixture["native_reflection"]["owned_probe_source_sha256"]
    assert fixture["native_reflection"]["field_values_match_static_derivation"] is True
    assert fixture["native_reflection"]["registry_write_attempted"] is False


def observe(state="present", value="41", kind=1):
    with patch.object(current, "_source_sha256", return_value=current.ORIGINAL_SHA256), \
         patch.object(current, "_current_process_sid", return_value=SID), \
         patch.object(current, "_read_hkcu_registry32", return_value=(state, value, kind)) as read, \
         patch.dict(sys.modules, {"winreg": REG}):
        result = current.observe_current_user_cohort(
            Path("original.dll"), expected_source_sha256=current.ORIGINAL_SHA256,
            expected_user_sid=SID,
        )
    read.assert_called_once_with()
    return result


def test_wrong_source_expectation_rejects_before_file_sid_or_registry():
    with patch.object(current, "_source_sha256") as source, \
         patch.object(current, "_current_process_sid") as sid, \
         patch.object(current, "_read_hkcu_registry32") as registry:
        with pytest.raises(ValueError, match="Expected source SHA-256"):
            current.observe_current_user_cohort(
                Path("not-opened.dll"), expected_source_sha256="0" * 64,
                expected_user_sid=SID,
            )
    source.assert_not_called(); sid.assert_not_called(); registry.assert_not_called()


def test_source_file_mismatch_and_link_reject_before_token_or_registry(tmp_path):
    source = tmp_path / "unrelated.dll"
    source.write_bytes(b"\x00" * current.ORIGINAL_SIZE)
    with patch.object(current, "_current_process_sid") as sid, \
         patch.object(current, "_read_hkcu_registry32") as registry:
        with pytest.raises(ValueError, match="hash differs"):
            current.observe_current_user_cohort(
                source, expected_source_sha256=current.ORIGINAL_SHA256,
                expected_user_sid=SID,
            )
        link = tmp_path / "link.dll"
        link.symlink_to(source)
        with pytest.raises(ValueError, match="ordinary pinned"):
            current._source_sha256(link)
    sid.assert_not_called(); registry.assert_not_called()


def test_wrong_process_user_rejects_before_registry_read():
    with patch.object(current, "_source_sha256", return_value=current.ORIGINAL_SHA256), \
         patch.object(current, "_current_process_sid", return_value="S-1-5-18"), \
         patch.object(current, "_read_hkcu_registry32") as registry:
        with pytest.raises(ValueError, match="differs"):
            current.observe_current_user_cohort(
                Path("original.dll"), expected_source_sha256=current.ORIGINAL_SHA256,
                expected_user_sid=SID,
            )
    registry.assert_not_called()


@pytest.mark.parametrize("state,value,kind,read_state,status,cohort", [
    ("present", "41", 1, "present", "observed", 41),
    ("present", 41, 4, "present", "observed", 41),
    ("key_absent", None, None, "key_absent", "unsupported", None),
    ("entry_absent", None, None, "entry_absent", "unsupported", None),
    ("present", "-1", 1, "sentinel", "unsupported", None),
    ("present", "+41", 1, "unsupported", "unsupported", None),
    ("present", "bad", 1, "unsupported", "unsupported", None),
    ("present", 0xffffffff, 4, "unsupported", "unsupported", None),
    ("present", b"secret", 3, "unsupported", "unsupported", None),
])
def test_observation_distinguishes_existing_cohort_from_original_write_branches(
    state, value, kind, read_state, status, cohort,
):
    result = observe(state, value, kind)
    assert (result.read_state, result.status, result.stored_cohort) == (read_state, status, cohort)
    report = result.as_dict()
    assert report["registry_write_attempted"] is False
    assert report["cohort_generated"] is False
    assert report["full_machine_applicability_evaluated"] is False
    assert report["install_permitted"] is False
    assert "secret" not in str(report)


def test_permission_failure_is_typed_and_never_claims_observed_cohort():
    with patch.object(current, "_source_sha256", return_value=current.ORIGINAL_SHA256), \
         patch.object(current, "_current_process_sid", return_value=SID), \
         patch.object(current, "_read_hkcu_registry32", side_effect=PermissionError("private")):
        result = current.observe_current_user_cohort(
            Path("original.dll"), expected_source_sha256=current.ORIGINAL_SHA256,
            expected_user_sid=SID,
        )
    assert result.status == "unsupported"
    assert result.registry_error_type == "PermissionError"
    assert result.as_dict()["stored_cohort"] is None


def test_winreg_access_is_query_only_and_uses_32bit_view():
    calls = []

    class Handle:
        def __enter__(self):
            return self

        def __exit__(self, *unused):
            return None

    fake = SimpleNamespace(
        HKEY_CURRENT_USER=object(), KEY_QUERY_VALUE=0x1, KEY_WOW64_32KEY=0x200,
        KEY_SET_VALUE=0x2, REG_SZ=1, REG_DWORD=4,
        OpenKey=lambda *args: calls.append(("open", args)) or Handle(),
        QueryValueEx=lambda *args: calls.append(("query", args)) or ("41", 1),
    )
    with patch.object(current.os, "name", "nt"), patch.dict(sys.modules, {"winreg": fake}):
        state, value, kind = current._read_hkcu_registry32()
    assert (state, value, kind) == ("present", "41", 1)
    assert calls[0] == ("open", (fake.HKEY_CURRENT_USER, current.REGISTRY_KEY, 0, 0x201))
    assert calls[1][0] == "query" and calls[1][1][1] == current.REGISTRY_ENTRY
