"""Finite SESU applicability preflight against retained original method cases."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from cbus_toolkit.toolkit_update_applicability import inspect_update_applicability


FIXTURES = Path(__file__).resolve().parents[1] / "research" / "fixtures"
ORIGINAL = json.loads((FIXTURES / "toolkit-update-applicability-preflight-vectors.json").read_text())
CATALOGUE = json.loads((FIXTURES / "toolkit-update-metadata-vectors.json").read_text())
SOURCE = CATALOGUE["raw_catalogue_json"].encode()
BASE = json.loads(SOURCE)
AT = "2026-09-15T02:04:45Z"


def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()


def inspect(source=BASE, *, index=0, platform="windows_x86_64", at_utc=AT):
    node_id = source["data"][index]["nodeId"]
    return inspect_update_applicability(
        encode(source), node_id=node_id, platform=platform, at_utc=at_utc,
    )


def test_retained_original_empty_condition_100_percent_method_matrix():
    assert ORIGINAL["sesubrick_dad_sha256"] == "21a6b2fb74d9b308d22c740ca0a1d887d80a067cccc03f59e4dd1bbb6c9c4b0c"
    assert ORIGINAL["original_method_rva"] == "0x4f74"
    assert ORIGINAL["file_selection_method_rva"] == "0x3fc8"
    assert hashlib.sha256(SOURCE).hexdigest() == ORIGINAL["captured_catalogue_sha256"]
    assert ORIGINAL["native_windows_outcomes_match_mono"] is True
    assert ORIGINAL["native_windows_probe_x86_sha256"] == "892395fbb2d311827acaa39f7c6aa7c1c02b63d88657a2fda1289e8ac32c876d"
    assert len(ORIGINAL["cases"]) == 20
    for case in ORIGINAL["cases"]:
        assert (case["native_windows_accepted"], case["native_windows_error"]) == (
            case["accepted"], case["error"])
        source = copy.deepcopy(BASE)
        node = source["data"][case["node_index"]]
        variant = case["variant"]
        if variant == "future-start":
            node["data"]["startDate"] = "2099-01-01T00:00:00Z"
        elif variant == "expired":
            node["data"]["expireDate"] = "2000-01-01T00:00:00Z"
        elif variant == "missing-url":
            # Original probe nulled the selected URI after file selection.
            # An empty selected URL reaches the same field state in source IL.
            node["urls"][node["files"][0]["id"]]["url"] = ""
        elif variant == "unsupported-media":
            # Original probe forced enum Unknown=6 after selection. Missing
            # metadata also leaves that original default enum value.
            del node["files"][0]["metadata"]["mediatype"]
        elif variant == "null-conditions":
            node["data"]["clientConditionData"] = None
        elif variant == "empty-map-false-expression":
            node["data"]["clientConditionData"]["expression"] = "false"
        else:
            assert variant == "captured"
        report = inspect(source, index=case["node_index"],
                         platform=ORIGINAL["platform_values"][str(case["platform_value"])])
        assert report.applicable_under_supplied_context is case["accepted"]
        if case["error"]:
            assert case["error"] == "System.NullReferenceException"
            assert report.status == "unsupported"
        else:
            assert report.status == ("passed" if case["accepted"] else "failed")
        for key in ("metadata_signature_verified", "publisher_trust_evaluated",
                    "certificate_chain_evaluated", "complete_revocation_status_evaluated",
                    "package_applicability_evaluated", "version_comparison_performed",
                    "install_permitted", "downloaded", "installed", "registry_accessed"):
            assert report.as_dict()[key] is False
        if variant != "null-conditions":
            assert report.empty_conditions is True
            assert report.rollout_bypassed_visibility_100 is True
        else:
            assert report.empty_conditions is None
            assert report.rollout_bypassed_visibility_100 is None

def test_first_matching_url_key_wins_even_when_selected_url_is_empty():
    source = copy.deepcopy(BASE)
    node = source["data"][0]
    first = node["files"][0]["id"]
    later = copy.deepcopy(node["files"][0])
    later["id"] = "later-file"
    node["files"].append(later)
    node["urls"][first]["url"] = ""
    node["urls"][later["id"]] = {"url": "https://invalid.example/later.exe"}
    result = inspect(source)
    assert result.status == "failed"
    assert result.selected_file_id == first
    assert result.selected_uri_present is False
    del node["urls"][first]
    result = inspect(source)
    assert result.status == "passed"
    assert result.selected_file_id == later["id"]


def test_architecture_contains_is_case_sensitive_and_dates_use_explicit_context():
    source = copy.deepcopy(BASE)
    node = source["data"][0]
    node["files"][0]["metadata"]["architecture"] = "WINDOWS_X86_64"
    assert inspect(source).status == "failed"
    node["files"][0]["metadata"]["architecture"] = "prefix-windows_x86_64-suffix"
    assert inspect(source).status == "passed"
    node["data"]["startDate"] = AT
    node["data"]["expireDate"] = AT
    assert inspect(source).status == "passed"
    assert inspect(source, at_utc="2026-09-15T02:04:44.9999999Z").status == "failed"
    assert inspect(source, at_utc="2026-09-15T02:04:45.0000001Z").status == "failed"


def test_unproved_conditions_rollout_media_and_url_fail_closed():
    source = copy.deepcopy(BASE)
    node = source["data"][0]
    node["data"]["visibilityInPercent"] = 99
    result = inspect(source)
    assert result.status == "unsupported"
    assert result.empty_conditions is True
    assert result.rollout_bypassed_visibility_100 is None
    node["data"]["visibilityInPercent"] = 100
    node["data"]["clientConditionData"]["conditions"] = {"a": {"whatToCheck": "fileExists"}}
    result = inspect(source)
    assert result.status == "unsupported"
    assert result.empty_conditions is None
    node["data"]["clientConditionData"]["conditions"] = {}
    node["files"][0]["metadata"]["mediatype"] = "webUpdate"
    assert inspect(source).status == "unsupported"
    node["files"][0]["metadata"]["mediatype"] = "singleFileExecutable"
    node["urls"][node["files"][0]["id"]]["url"] = "http://invalid.example/package"
    assert inspect(source).status == "unsupported"
    node["urls"][node["files"][0]["id"]] = ["not an URL object"]
    assert inspect(source).status == "unsupported"
    node["urls"][node["files"][0]["id"]] = {"url": "https://exam\\ple.test/a"}
    assert inspect(source).status == "unsupported"


@pytest.mark.parametrize("url", [
    "https://bad^host.example/package",
    "https://host%2f.example/package",
    "https://host_name.example/package",
    "https://-host.example/package",
    "https://host..example/package",
    "https://999.999.999.999/package",
    "https://example.com:/package",
    "https://example.com:abc/package",
    "https://example.com:00000000000000000000000000/package",
    "https://example.com:65536/package",
    "https://example.com/package#",
])
def test_ambiguous_https_authority_and_fragment_are_outside_profile(url):
    source = copy.deepcopy(BASE)
    node = source["data"][0]
    node["urls"][node["files"][0]["id"]]["url"] = url
    result = inspect(source)
    assert result.status == "unsupported"
    assert result.selected_uri_present is None
    assert result.as_dict()["publisher_trust_evaluated"] is False
    assert result.as_dict()["install_permitted"] is False


@pytest.mark.parametrize("url", [
    "https://download.example.com:443/package",
    "https://192.0.2.1/package",
    "https://[2001:db8::1]:443/package",
])
def test_explicit_unambiguous_https_authority_remains_admitted(url):
    source = copy.deepcopy(BASE)
    node = source["data"][0]
    node["urls"][node["files"][0]["id"]]["url"] = url
    result = inspect(source)
    assert result.status == "passed"
    assert result.selected_uri_present is True


def test_same_id_changed_source_does_not_borrow_a_preflight_result():
    first = inspect()
    source = copy.deepcopy(BASE)
    source["data"][0]["data"]["expireDate"] = "2000-01-01T00:00:00Z"
    second = inspect(source)
    assert first.node_id == second.node_id
    assert first.status == "passed" and second.status == "failed"
    assert first.catalogue_source_sha256 != second.catalogue_source_sha256
    assert first.selected_node_sha256 != second.selected_node_sha256
    assert first.canonical_node_sha256 != second.canonical_node_sha256


def test_ambiguous_source_and_bad_response_rejected():
    source = copy.deepcopy(BASE)
    source["data"].append(copy.deepcopy(source["data"][0]))
    with pytest.raises(ValueError, match="exactly one"):
        inspect(source)
    source = copy.deepcopy(BASE)
    source["data"][0]["files"].append(copy.deepcopy(source["data"][0]["files"][0]))
    with pytest.raises(ValueError, match="unique"):
        inspect(source)
    source = copy.deepcopy(BASE)
    source["statusCode"] = True
    with pytest.raises(ValueError, match="statusCode"):
        inspect(source)
    with pytest.raises(ValueError, match="Duplicate JSON key"):
        inspect_update_applicability(
            b'{"success":true,"success":true,"data":[]}', node_id="x",
            platform="windows_x86_64", at_utc=AT,
        )
