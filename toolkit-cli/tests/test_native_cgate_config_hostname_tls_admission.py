"""Historical native admission outcomes with exact helper source applicability.

The fresh hostname recapture failed; this guard preserves the original capture
and proves only that the PKI helpers it imported remain byte-identical.
"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "rust/testdata/fixtures/native_cgate_config_hostname_tls_admission.json"
HELPER_PROOF = ROOT / "toolkit-cli/research/fixtures/native-cgate-hostname-tls-helper-applicability.json"
HELPER_SNAPSHOT = ROOT / "toolkit-cli/research/fixtures/native-cgate-hostname-tls-verify-tls-capture-source.txt"
FAILED_RECAPTURE = ROOT / "toolkit-cli/research/fixtures/native-cgate-hostname-tls-failed-recapture.json"
PKI_HELPER = "toolkit-cli/research/verify_tls.py"


def assert_historical_helper_source_applicability(expected: str) -> None:
    proof = json.loads(HELPER_PROOF.read_bytes())
    assert proof["format"] == "cbus-native-cgate-hostname-tls-helper-applicability-v1"
    assert proof["fresh_native_acceptance"] is False
    assert proof["historical_capture"]["path"] == str(FIXTURE.relative_to(ROOT))
    assert proof["historical_capture"]["sha256"] == hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
    captured = HELPER_SNAPSHOT.read_bytes()
    assert hashlib.sha256(captured).hexdigest() == expected
    assert proof["captured_helper_source"]["sha256"] == expected
    assert proof["captured_helper_source"]["original_repository_path"] == PKI_HELPER
    assert proof["captured_helper_source"]["path"] == str(HELPER_SNAPSHOT.relative_to(ROOT))
    applicability = proof["current_source_applicability"]
    assert applicability["repository_path"] == PKI_HELPER
    assert applicability["imported_helpers"] == ["STORE_PASSWORD", "run", "generate_pki"]
    current = (ROOT / PKI_HELPER).read_bytes()
    captured_prefix = captured.split(b"\ndef verify(", 1)[0]
    assert current.split(b"\ndef verify(", 1)[0] == captured_prefix
    assert applicability["exact_prefix_bytes"] == len(captured_prefix)
    assert applicability["exact_prefix_sha256"] == hashlib.sha256(captured_prefix).hexdigest()
    # Nothing outside the retained prefix may override its imported helpers or
    # globals when the module is imported. Only the uncalled verify/main
    # functions and an exact __main__ guard may follow it.
    signatures = []
    for source in (captured, current):
        remainder = ast.parse(source).body
        verify_index, = [index for index, node in enumerate(remainder)
                        if isinstance(node, ast.FunctionDef) and node.name == "verify"]
        tail = remainder[verify_index:]
        assert len(tail) == 3 and isinstance(tail[2], ast.If)
        assert [node.name for node in tail[:2] if isinstance(node, ast.FunctionDef)] == ["verify", "main"]
        signatures.append([(ast.dump(node.args), [ast.dump(item) for item in node.decorator_list],
                            None if node.returns is None else ast.dump(node.returns))
                           for node in tail[:2]])
        assert ast.dump(tail[2].test) == ast.dump(ast.parse('__name__ == "__main__"', mode="eval").body)
        assert tail[2].orelse == []
    assert signatures[0] == signatures[1]


def receipt() -> dict:
    return json.loads(FIXTURE.read_text())


def test_hostname_tls_receipt_is_owned_and_source_bound() -> None:
    report = receipt()
    assert report["schema"] == "native-cgate-config-hostname-tls-admission-v1"
    oracle = report["oracle"]
    assert oracle["jar_sha256"] == "3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630"
    assert oracle["java_sha256"] == "94e156397958bb83fda31ee16200580fd083b0fc0ed4a9ce795cfa44ff8e72f4"
    assert oracle["physical_endpoint"] is False
    assert "no IPv6 peer" in report["scope"]
    assert len(report["cases"]) == 12
    assert len(report["tls_cases"]) == 7
    for name, expected in oracle["source_hashes"].items():
        if name == PKI_HELPER:
            assert_historical_helper_source_applicability(expected)
        else:
            assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected
    assert oracle["source_hashes_after"] == oracle["source_hashes"]
    for row in report["cases"]:
        assert all(row["cleanup"].values())
        assert row["set"] == "[set] 200 OK."
        assert row["get"] == f"[get] 303 accept-connections-from={row['value']}"
        assert row["existing_noop"] == "[old] 200 OK."
        assert row["restore"] == "[restore] 200 OK."
    assert all(oracle["tls_cleanup"].values())


def test_native_hostname_ipv4_mapped_and_tls_outcomes() -> None:
    report = receipt()
    outcomes = {row["value"]: (row["plain"], row["restored_plain"])
                for row in report["cases"]}
    assert outcomes == {
        "LOCALHOST": ("greeting", "greeting"),
        "localhost.": ("greeting", "greeting"),
        "127.0.0.1.nip.io": ("greeting", "greeting"),
        "192.0.2.55.nip.io": ("connected-silent", "greeting"),
        "localhost 192.0.2.55": ("greeting", "greeting"),
        "192.0.2.55 localhost": ("greeting", "greeting"),
        "::1": ("connected-silent", "greeting"),
        "ip6-localhost": ("connected-silent", "connected-silent"),
        "::ffff:127.0.0.1": ("greeting", "greeting"),
        "127.0.0.1/8": ("connected-silent", "connected-silent"),
        "unresolved.invalid": ("connected-silent", "connected-silent"),
        "ALL": ("greeting", "greeting"),
    }
    assert report["baseline"] == {
        "plain": "greeting", "tls": {"outcome": "greeting", "tls_version": "TLSv1.3"}
    }
    assert [(row["value"], row["plain"], row["tls"]["outcome"])
            for row in report["tls_cases"]] == [
        ("LOCALHOST", "greeting", "greeting"),
        ("localhost.", "greeting", "greeting"),
        ("127.0.0.1.nip.io", "greeting", "greeting"),
        ("192.0.2.55.nip.io", "connected-silent", "handshake-timeout"),
        ("all", "greeting", "greeting"),
        ("::1", "connected-silent", "handshake-timeout"),
        ("all", "greeting", "greeting"),
    ]


def test_failed_fresh_hostname_revalidation_does_not_replace_historical_acceptance() -> None:
    failed = json.loads(FAILED_RECAPTURE.read_bytes())
    assert failed["format"] == "cbus-native-cgate-hostname-tls-failed-recapture-v1"
    assert failed["captured_utc"].startswith("2026-09-30T")
    assert failed["outcome"] == {"result": "failed", "error_type": "ConnectionRefusedError"}
    assert failed["historical_fixture_overwritten"] is False
    assert failed["physical_endpoint"] is False
    assert "not successful fresh native hostname/TLS acceptance" in failed["scope"]
    assert hashlib.sha256(failed["diagnostic_source"].encode()).hexdigest() == failed["diagnostic_source_sha256"]
    assert failed["oracle"]["source_hashes_after"] == failed["oracle"]["source_hashes"]
    assert failed["oracle"]["jar_sha256"] == receipt()["oracle"]["jar_sha256"]
    assert failed["oracle"]["java_sha256"] == receipt()["oracle"]["java_sha256"]
    assert failed["last_commands"][0] == {
        "tag": "set", "body": "CONFIG SET accept-connections-from ip6-localhost"
    }
    assert failed["last_commands"][-1] == {
        "tag": "restore", "body": "CONFIG SET accept-connections-from all"
    }
    observation, = failed["readiness_observations"]
    assert observation["outcome"] == "unavailable"
    assert 3 <= observation["elapsed_seconds"] < 4
    assert set(observation["errors"]) == {"ConnectionResetError", "ConnectionRefusedError"}
    assert len(observation["errors"]) > 2
    assert len(failed["owned_cleanup"]) == 8
    for cleanup in failed["owned_cleanup"]:
        assert cleanup == {
            "listener_ownership_verified": True,
            "process_exit_confirmed": True,
            "cleanup_complete": True,
            "work_removed": True,
        }
