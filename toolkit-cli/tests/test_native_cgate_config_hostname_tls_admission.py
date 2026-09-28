"""Source-bound original C-Gate hostname and secure-listener admission receipt."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "rust/testdata/fixtures/native_cgate_config_hostname_tls_admission.json"


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
