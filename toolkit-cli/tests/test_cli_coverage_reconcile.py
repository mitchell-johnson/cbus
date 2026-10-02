from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys

import pytest

from cbus_toolkit.toolkit_obligation_reconcile import ReconciliationError, reconcile_bundle_file


ROOT = Path(__file__).resolve().parents[1]
VECTOR = ROOT / "research/fixtures/toolkit-obligation-reconcile-vectors.json"


def raw(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


def files(tmp_path: Path) -> tuple[Path, Path, dict]:
    vector = json.loads(VECTOR.read_bytes())
    root = tmp_path / "artifacts"
    root.mkdir()
    for name, doc in vector["artifact_documents"].items():
        (root / name).write_bytes(raw(doc))
    bundle_path = tmp_path / "bundle.json"
    bundle_path.write_bytes(raw(vector["bundle"]))
    return bundle_path, root, vector


def cli(*args: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-m", "cbus_toolkit", "--compact", "coverage",
                           *map(str, args)], capture_output=True, text=True, check=False, timeout=30)


def test_public_coverage_default_preserves_global_evaluator_without_reconciliation() -> None:
    result = cli("--require-complete")
    assert result.returncode == 1, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["complete"] is False and report["progress"]["complete"] is False
    assert "reconciliation" not in report


def test_public_complete_declared_bundle_cannot_promote_global_parity(tmp_path: Path) -> None:
    bundle, artifacts, vector = files(tmp_path)
    result = cli("--reconciliation-bundle", bundle, "--reconciliation-artifact-root", artifacts,
                 "--require-complete")
    assert result.returncode == 1, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["complete"] is False and report["progress"]["complete"] is False
    scoped = report["reconciliation"]
    assert scoped["counts"] == vector["expected_counts"]
    assert scoped["complete_for_declared_surface"] is True
    assert scoped["scope"] == "declared-modeled-input-surface-only"
    assert scoped["full_toolkit_parity"] is False and scoped["census_completeness_verified"] is False
    assert scoped["bundle_artifact"] == {"sha256": sha256(bundle.read_bytes()).hexdigest(),
                                         "bytes": len(bundle.read_bytes())}
    # No publication coordinate, document bodies or receipt instructions enter the report.
    assert str(tmp_path) not in result.stdout and "artifact_documents" not in scoped


def test_public_json_only_leaves_artifact_and_gate_evidence_unverified(tmp_path: Path) -> None:
    bundle, _, _ = files(tmp_path)
    result = cli("--reconciliation-bundle", bundle)
    assert result.returncode == 0, result.stdout + result.stderr
    scoped = json.loads(result.stdout)["reconciliation"]
    assert not scoped["complete_for_declared_surface"] and not scoped["denominator_ready"]
    assert scoped["counts"]["verified_artifacts"] == 0


def test_artifact_root_option_requires_explicit_bundle(tmp_path: Path) -> None:
    result = cli("--reconciliation-artifact-root", tmp_path)
    assert result.returncode == 1 and result.stdout == ""
    assert json.loads(result.stderr)["error"] == "--reconciliation-artifact-root requires --reconciliation-bundle"


@pytest.mark.parametrize("fault", ["missing", "duplicate-key", "wrong-format", "private-coordinate"])
def test_public_invalid_bundle_is_atomic_and_has_no_partial_coverage_output(tmp_path: Path, fault: str) -> None:
    bundle, _, vector = files(tmp_path)
    if fault == "missing":
        bundle.unlink()
    elif fault == "duplicate-key":
        bundle.write_text('{"format":"one","format":"two"}')
    else:
        bad = deepcopy(vector["bundle"])
        if fault == "wrong-format":
            bad["format"] = "unknown"
        else:
            bad["sources"][0]["source_id"] = "/Users/synthetic/private-project.xml"
        bundle.write_bytes(raw(bad))
    result = cli("--reconciliation-bundle", bundle)
    assert result.returncode == 1 and result.stdout == ""
    error = json.loads(result.stderr)
    assert "complete" not in error and str(tmp_path) not in result.stderr
    assert "/Users/synthetic" not in result.stderr


@pytest.mark.parametrize("escape", ["absolute", "parent", "linked-file", "linked-parent"])
def test_artifact_resolution_refuses_outside_file_before_read(tmp_path: Path, escape: str) -> None:
    bundle_path, root, vector = files(tmp_path)
    outside = tmp_path / "outside.json"
    outside.write_text('secret marker must never be emitted')
    bundle = deepcopy(vector["bundle"])
    if escape == "absolute":
        name = str(outside)
    elif escape == "parent":
        name = "../outside.json"
    elif escape == "linked-file":
        name = "linked-file.json"
        (root / name).symlink_to(outside)
    else:
        name = "linked-parent/outside.json"
        (root / "linked-parent").symlink_to(tmp_path, target_is_directory=True)
    bundle["current_artifacts"] = {name: {"sha256": "f" * 64, "bytes": 1}}
    bundle_path.write_bytes(raw(bundle))
    with pytest.raises(ReconciliationError, match="coordinate|relative|escapes"):
        reconcile_bundle_file(bundle_path, artifact_root=root)
    result = cli("--reconciliation-bundle", bundle_path, "--reconciliation-artifact-root", root)
    assert result.returncode == 1 and result.stdout == ""
    assert "secret marker" not in result.stderr and str(tmp_path) not in result.stderr


def test_current_artifact_byte_change_is_reported_without_granting_credit(tmp_path: Path) -> None:
    bundle, artifacts, _ = files(tmp_path)
    (artifacts / "synthetic-evidence.json").write_text('{"result":"passed"}')
    result = cli("--reconciliation-bundle", bundle, "--reconciliation-artifact-root", artifacts)
    assert result.returncode == 0
    scoped = json.loads(result.stdout)["reconciliation"]
    assert scoped["denominator_ready"] is True and scoped["complete_for_declared_surface"] is False
    assert any(row["code"] == "receipt_artifact_stale_or_unverified" for row in scoped["unresolved"])
