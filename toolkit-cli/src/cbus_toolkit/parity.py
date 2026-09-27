"""Strict, evidence-derived Toolkit and C-Gate parity accounting.

The broad feature ledger is retained for historical reporting.  Release
completion is derived from the finer parity register and its evidence bundle.
The committed register is deliberately provisional while the executable
surface census remains incomplete, so functional percentages are unavailable
rather than inferred from unlike categories or documentation counts.
"""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
from importlib.resources import files
import json
from pathlib import Path
import re
from typing import Any


REGISTER_RESOURCE = "parity-obligations.json"
EVIDENCE_RESOURCE = "parity-evidence.json"
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
REVISION_RE = re.compile(r"[0-9a-f]{40}\Z")
IMPLEMENTATION_STATES = {"pending", "in_progress", "implemented"}
DEFINITION_STATES = {"provisional", "defined"}
APPLICABILITY_STATES = {"unresolved", "resolved"}
ACCEPTANCE_STATES = {"unassessed", "blocked", "accepted", "not_applicable"}
EVIDENCE_RESULTS = {"passed", "failed", "blocked", "skipped"}
EVIDENCE_ENVIRONMENTS = {
    "offline",
    "installed_wheel",
    "interop",
    "native_original",
    "physical",
}
ARTIFACT_ROLES = {"input", "output", "executable", "report"}
SCOPE_DISPOSITIONS = {
    "pending_analysis",
    "provisional_obligation",
    "functional_obligation",
    "nonfunctional_with_evidence",
}
SCOPE_EXCLUSION_DECISION = "exclude_nonfunctional"
WORK_ITEM_IDS = frozenset(
    {
        "P0.01",
        "P0.02",
        "P0.03",
        "P0.04",
        "P0.05",
        "P1.01",
        "P1.02",
        "P1.03",
        "P1.04",
        "P1.05",
        "P2.01",
        "P2.02",
        "P2.03",
        "P2.04",
        "P2.05",
        "P3.01",
        "P3.02",
        "P3.03",
        "P3.04",
        "P3.05",
        "P4.01",
        "P4.02",
        "P4.03",
        "P4.04",
        "P4.05",
        "P5.01",
        "P5.02",
        "P5.03",
        "P5.04",
        "P5.05",
        "P5.06",
        "P5.07",
        "P6.01",
        "P6.02",
        "P6.03",
        "P6.04",
        "P6.05",
        "P6.06",
        "P7.01",
        "P7.02",
        "P7.03",
        "P7.04",
        "P8.01",
        "P8.02",
        "P8.03",
        "P8.04",
        "P8.05",
        "P9.01",
        "P9.02",
        "P9.03",
        "P9.04",
        "P10.01",
        "P10.02",
        "P10.03",
        "P10.04",
        "P11.01",
        "P11.02",
        "P11.03",
        "P11.04",
    }
)
REQUIRED_DIMENSIONS = (
    "nominal",
    "error",
    "invalid_input",
    "profile_variation",
    "original_differential",
    "physical",
    "persistence_recovery",
)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_nonfinite_constant(value: str) -> Any:
    raise ValueError(f"Non-finite JSON number is forbidden: {value}")


def parse_json_document(raw: str | bytes, *, context: str) -> dict[str, Any]:
    """Parse one bounded JSON object and reject duplicate keys."""
    if isinstance(raw, bytes):
        if len(raw) > 32 * 1024 * 1024:
            raise ValueError(f"{context} exceeds the 32 MiB limit")
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"{context} is not UTF-8") from exc
    elif isinstance(raw, str):
        if len(raw.encode("utf-8")) > 32 * 1024 * 1024:
            raise ValueError(f"{context} exceeds the 32 MiB limit")
        text = raw
    else:
        raise ValueError(f"{context} must be text or bytes")
    try:
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite_constant,
        )
    except json.JSONDecodeError as exc:
        raise ValueError(f"{context} is not valid JSON: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{context} must be a JSON object")
    return value


def _strings(value: Any, *, field: str, nonempty: bool = False) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{field} must be an array of strings")
    if nonempty and not value:
        raise ValueError(f"{field} must not be empty")
    if len(value) != len(set(value)):
        raise ValueError(f"{field} contains duplicates")
    return value


def _canonical_record_digest(record: dict[str, Any]) -> str:
    content = {key: value for key, value in record.items() if key != "record_sha256"}
    encoded = json.dumps(
        content, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def validate_evidence_bundle(
    bundle: dict[str, Any], *, artifact_root: Path | None = None
) -> dict[str, dict[str, Any]]:
    if bundle.get("schema_version") != 1:
        raise ValueError("Evidence bundle requires schema_version 1")
    if not isinstance(bundle.get("target"), str) or not bundle["target"].strip():
        raise ValueError("Evidence bundle requires a target")
    records = bundle.get("records")
    if not isinstance(records, list):
        raise ValueError("Evidence bundle requires a records array")
    by_id: dict[str, dict[str, Any]] = {}
    for index, record in enumerate(records):
        context = f"evidence record {index}"
        if not isinstance(record, dict):
            raise ValueError(f"{context} must be an object")
        evidence_id = record.get("id")
        if not isinstance(evidence_id, str) or not evidence_id:
            raise ValueError(f"{context} requires a nonempty id")
        if evidence_id in by_id:
            raise ValueError(f"Duplicate evidence id: {evidence_id}")
        if record.get("result") not in EVIDENCE_RESULTS:
            raise ValueError(f"{evidence_id} has an unknown result")
        obligation_ids = _strings(
            record.get("obligation_ids"), field=f"{evidence_id}.obligation_ids"
        )
        disposition_receipts = record.get("scope_disposition_receipts")
        if not isinstance(disposition_receipts, list):
            raise ValueError(
                f"{evidence_id}.scope_disposition_receipts must be an array"
            )
        receipt_keys: set[tuple[str, str]] = set()
        for receipt_index, receipt in enumerate(disposition_receipts):
            receipt_context = (
                f"{evidence_id}.scope_disposition_receipts[{receipt_index}]"
            )
            if not isinstance(receipt, dict) or set(receipt) != {
                "scope_item_id",
                "decision",
            }:
                raise ValueError(
                    f"{receipt_context} must contain exactly scope_item_id and decision"
                )
            scope_item_id = receipt.get("scope_item_id")
            decision = receipt.get("decision")
            if not isinstance(scope_item_id, str) or not scope_item_id:
                raise ValueError(f"{receipt_context} requires a nonempty scope_item_id")
            if decision != SCOPE_EXCLUSION_DECISION:
                raise ValueError(f"{receipt_context} has an unknown exclusion decision")
            receipt_key = (scope_item_id, decision)
            if receipt_key in receipt_keys:
                raise ValueError(f"{evidence_id} has duplicate scope disposition receipts")
            receipt_keys.add(receipt_key)
        if not obligation_ids and not disposition_receipts:
            raise ValueError(
                f"{evidence_id} must bind an obligation or scope disposition"
            )
        dimensions = _strings(
            record.get("dimensions"), field=f"{evidence_id}.dimensions", nonempty=True
        )
        unknown_dimensions = set(dimensions) - set(REQUIRED_DIMENSIONS)
        if unknown_dimensions:
            raise ValueError(
                f"{evidence_id} has unknown dimensions: {sorted(unknown_dimensions)}"
            )
        test_ids = _strings(
            record.get("test_ids"), field=f"{evidence_id}.test_ids", nonempty=True
        )
        if any(not test_id.strip() for test_id in test_ids):
            raise ValueError(f"{evidence_id}.test_ids contains an empty identifier")
        environment = record.get("environment")
        if not isinstance(environment, dict):
            raise ValueError(f"{evidence_id} requires an environment")
        environment_kind = environment.get("kind")
        if environment_kind not in EVIDENCE_ENVIRONMENTS:
            raise ValueError(f"{evidence_id} has an unknown environment kind")
        if not isinstance(environment.get("identity"), str) or not environment["identity"].strip():
            raise ValueError(f"{evidence_id} requires an environment identity")
        if "physical" in dimensions:
            if environment_kind != "physical":
                raise ValueError(f"{evidence_id} physical evidence requires a physical environment")
            _strings(
                environment.get("hardware_refs"),
                field=f"{evidence_id}.environment.hardware_refs",
                nonempty=True,
            )
        if "original_differential" in dimensions:
            oracle = record.get("oracle")
            if not isinstance(oracle, dict):
                raise ValueError(f"{evidence_id} differential evidence requires an oracle")
            if not isinstance(oracle.get("target"), str) or not oracle["target"].strip():
                raise ValueError(f"{evidence_id} requires an oracle target")
            oracle_digest = oracle.get("artifact_sha256")
            if not isinstance(oracle_digest, str) or not SHA256_RE.fullmatch(oracle_digest):
                raise ValueError(f"{evidence_id} requires an oracle artifact SHA-256")
        revision = record.get("source_revision")
        if not isinstance(revision, str) or not REVISION_RE.fullmatch(revision):
            raise ValueError(f"{evidence_id} requires a 40-hex source_revision")
        command = record.get("command")
        if not isinstance(command, str) or not command.strip():
            raise ValueError(f"{evidence_id} requires the exact nonempty command")
        exit_code = record.get("exit_code")
        if isinstance(exit_code, bool) or not isinstance(exit_code, int):
            raise ValueError(f"{evidence_id} requires an integer exit_code")
        if record["result"] == "passed" and exit_code != 0:
            raise ValueError(f"{evidence_id} passed evidence requires exit_code 0")
        if record["result"] == "failed" and exit_code == 0:
            raise ValueError(f"{evidence_id} failed evidence requires a nonzero exit_code")
        artifacts = record.get("artifacts")
        if not isinstance(artifacts, list) or not artifacts:
            raise ValueError(f"{evidence_id} requires at least one artifact")
        artifact_paths: set[str] = set()
        for artifact_index, artifact in enumerate(artifacts):
            if not isinstance(artifact, dict):
                raise ValueError(f"{evidence_id}.artifacts[{artifact_index}] must be an object")
            path = artifact.get("path")
            digest = artifact.get("sha256")
            if artifact.get("role") not in ARTIFACT_ROLES:
                raise ValueError(f"{evidence_id} artifact has an unknown role")
            if not isinstance(path, str) or not path or Path(path).is_absolute() or ".." in Path(path).parts:
                raise ValueError(f"{evidence_id} has an unsafe artifact path")
            if path in artifact_paths:
                raise ValueError(f"{evidence_id} has duplicate artifact paths")
            artifact_paths.add(path)
            if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
                raise ValueError(f"{evidence_id} artifact requires a lowercase SHA-256")
            if artifact_root is not None:
                candidate = (artifact_root / path).resolve()
                root = artifact_root.resolve()
                if root not in candidate.parents and candidate != root:
                    raise ValueError(f"{evidence_id} artifact escapes its root")
                if not candidate.is_file():
                    raise ValueError(f"{evidence_id} artifact is missing: {path}")
                if sha256(candidate.read_bytes()).hexdigest() != digest:
                    raise ValueError(f"{evidence_id} artifact digest changed: {path}")
        skips = record.get("skips")
        if not isinstance(skips, list):
            raise ValueError(f"{evidence_id}.skips must be an array")
        for skip_index, skip in enumerate(skips):
            if not isinstance(skip, dict):
                raise ValueError(f"{evidence_id}.skips[{skip_index}] must be an object")
            if not isinstance(skip.get("case_id"), str) or not skip["case_id"]:
                raise ValueError(f"{evidence_id} has an unexplained skip without case_id")
            if not isinstance(skip.get("reason"), str) or not skip["reason"].strip():
                raise ValueError(f"{evidence_id} has an unexplained skip without reason")
            if skip.get("required") is not False:
                raise ValueError(f"{evidence_id} contains a required skipped case")
        digest = record.get("record_sha256")
        if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
            raise ValueError(f"{evidence_id} requires record_sha256")
        if digest != _canonical_record_digest(record):
            raise ValueError(f"{evidence_id} record digest changed")
        by_id[evidence_id] = record
    return by_id


def validate_register(
    register: dict[str, Any],
    evidence: dict[str, Any],
    ledger: dict[str, Any],
    *,
    evidence_raw: bytes | None = None,
    ledger_raw: bytes | None = None,
    artifact_root: Path | None = None,
) -> dict[str, Any]:
    if register.get("schema_version") != 1:
        raise ValueError("Parity register requires schema_version 1")
    if not isinstance(register.get("target"), str) or not register["target"]:
        raise ValueError("Parity register requires a target")
    if not isinstance(register.get("denominator_version"), str) or not register["denominator_version"]:
        raise ValueError("Parity register requires denominator_version")
    if not isinstance(register.get("census_complete"), bool):
        raise ValueError("Parity register census_complete must be boolean")
    source_digests = register.get("source_digests")
    if not isinstance(source_digests, dict) or not source_digests:
        raise ValueError("Parity register requires source_digests")
    for source_name, source_digest in source_digests.items():
        if not isinstance(source_name, str) or not source_name:
            raise ValueError("Parity register has an invalid source digest name")
        if not isinstance(source_digest, str) or not SHA256_RE.fullmatch(source_digest):
            raise ValueError(f"Parity source {source_name} requires a lowercase SHA-256")
    if ledger_raw is not None:
        parsed_ledger = parse_json_document(ledger_raw, context="feature ledger")
        if parsed_ledger != ledger:
            raise ValueError("Parsed feature ledger differs from supplied ledger")
        if sha256(ledger_raw).hexdigest() != source_digests.get("feature_ledger"):
            raise ValueError("Parity feature ledger digest changed")
    expected_bundle_digest = register.get("evidence_bundle_sha256")
    if not isinstance(expected_bundle_digest, str) or not SHA256_RE.fullmatch(expected_bundle_digest):
        raise ValueError("Parity register requires evidence_bundle_sha256")
    if evidence_raw is not None:
        parsed_evidence = parse_json_document(
            evidence_raw, context="parity evidence bundle"
        )
        if parsed_evidence != evidence:
            raise ValueError("Parsed parity evidence differs from supplied evidence")
        if sha256(evidence_raw).hexdigest() != expected_bundle_digest:
            raise ValueError("Parity evidence bundle digest changed")
    evidence_by_id = validate_evidence_bundle(evidence, artifact_root=artifact_root)
    if evidence["target"] != register["target"]:
        raise ValueError("Parity evidence target does not match register target")

    features = ledger.get("features")
    if ledger.get("target") != register["target"]:
        raise ValueError("Feature ledger target does not match parity register target")
    if not isinstance(features, list):
        raise ValueError("Feature ledger requires a features array")
    work_item_roster = _strings(
        register.get("work_item_ids"),
        field="Parity register work_item_ids",
        nonempty=True,
    )
    if set(work_item_roster) != WORK_ITEM_IDS:
        missing = sorted(WORK_ITEM_IDS - set(work_item_roster))
        unknown = sorted(set(work_item_roster) - WORK_ITEM_IDS)
        raise ValueError(
            "Parity register work_item_ids differs from the authoritative roster "
            f"(missing={missing}, unknown={unknown})"
        )
    ledger_by_id: dict[str, dict[str, Any]] = {}
    for feature in features:
        if not isinstance(feature, dict) or not isinstance(feature.get("id"), str):
            raise ValueError("Every feature ledger row requires a string id")
        feature_id = feature["id"]
        if feature_id in ledger_by_id:
            raise ValueError(f"Duplicate feature ledger id: {feature_id}")
        if feature.get("status") not in IMPLEMENTATION_STATES:
            raise ValueError(f"{feature_id} has an unknown feature status")
        ledger_by_id[feature_id] = feature

    obligations = register.get("obligations")
    if not isinstance(obligations, list) or not obligations:
        raise ValueError("Parity register requires a nonempty obligations array")
    obligations_by_id: dict[str, dict[str, Any]] = {}
    ledger_coverage: Counter[str] = Counter()
    for index, obligation in enumerate(obligations):
        context = f"obligation {index}"
        if not isinstance(obligation, dict):
            raise ValueError(f"{context} must be an object")
        obligation_id = obligation.get("id")
        if not isinstance(obligation_id, str) or not obligation_id:
            raise ValueError(f"{context} requires a nonempty id")
        if obligation_id in obligations_by_id:
            raise ValueError(f"Duplicate obligation id: {obligation_id}")
        ledger_id = obligation.get("ledger_id")
        if ledger_id not in ledger_by_id:
            raise ValueError(f"{obligation_id} names unknown ledger id: {ledger_id}")
        ledger_coverage[ledger_id] += 1
        work_items = _strings(
            obligation.get("work_item_ids"),
            field=f"{obligation_id}.work_item_ids",
            nonempty=True,
        )
        if any(not re.fullmatch(r"P(?:1[01]|[0-9])\.\d{2}", item) for item in work_items):
            raise ValueError(f"{obligation_id} has an invalid work item id")
        unknown_work_items = set(work_items) - set(work_item_roster)
        if unknown_work_items:
            raise ValueError(
                f"{obligation_id} names unknown work items: "
                f"{sorted(unknown_work_items)}"
            )
        if obligation.get("definition_status") not in DEFINITION_STATES:
            raise ValueError(f"{obligation_id} has an unknown definition_status")
        if obligation.get("implementation_status") not in IMPLEMENTATION_STATES:
            raise ValueError(f"{obligation_id} has an unknown implementation_status")
        if obligation["implementation_status"] != ledger_by_id[ledger_id]["status"]:
            raise ValueError(f"{obligation_id} implementation status drifts from {ledger_id}")
        if obligation.get("applicability_status") not in APPLICABILITY_STATES:
            raise ValueError(f"{obligation_id} has an unknown applicability_status")
        if not isinstance(obligation.get("outcome"), str) or not obligation["outcome"].strip():
            raise ValueError(f"{obligation_id} requires a user outcome")
        _strings(obligation.get("source_refs"), field=f"{obligation_id}.source_refs", nonempty=True)
        evidence_ids = _strings(
            obligation.get("evidence_ids"), field=f"{obligation_id}.evidence_ids"
        )
        unknown_evidence = set(evidence_ids) - set(evidence_by_id)
        if unknown_evidence:
            raise ValueError(
                f"{obligation_id} names unknown evidence: {sorted(unknown_evidence)}"
            )
        acceptance = obligation.get("acceptance")
        if not isinstance(acceptance, dict) or set(acceptance) != set(REQUIRED_DIMENSIONS):
            raise ValueError(
                f"{obligation_id} acceptance must define exactly {REQUIRED_DIMENSIONS}"
            )
        for dimension, state in acceptance.items():
            if state not in ACCEPTANCE_STATES:
                raise ValueError(f"{obligation_id}.{dimension} has an unknown state")
            if state in {"accepted", "not_applicable"} and not evidence_ids:
                raise ValueError(f"{obligation_id}.{dimension} requires evidence")
            if state in {"accepted", "not_applicable"} and not any(
                evidence_by_id[evidence_id]["result"] == "passed"
                and dimension in evidence_by_id[evidence_id]["dimensions"]
                and obligation_id in evidence_by_id[evidence_id]["obligation_ids"]
                for evidence_id in evidence_ids
            ):
                raise ValueError(
                    f"{obligation_id}.{dimension} lacks matching passed evidence"
                )
        obligations_by_id[obligation_id] = obligation
    missing_ledger = set(ledger_by_id) - set(ledger_coverage)
    if missing_ledger:
        raise ValueError(f"Ledger rows without obligations: {sorted(missing_ledger)}")
    for evidence_id, record in evidence_by_id.items():
        unknown_obligations = set(record["obligation_ids"]) - set(obligations_by_id)
        if unknown_obligations:
            raise ValueError(
                f"{evidence_id} names unknown obligations: {sorted(unknown_obligations)}"
            )

    scope_items = register.get("scope_items")
    if not isinstance(scope_items, list):
        raise ValueError("Parity register requires a scope_items array")
    scope_by_id: dict[str, dict[str, Any]] = {}
    scope_counts: Counter[str] = Counter()
    unresolved_scope = 0
    for index, item in enumerate(scope_items):
        if not isinstance(item, dict):
            raise ValueError(f"scope item {index} must be an object")
        item_id = item.get("id")
        kind = item.get("kind")
        if not isinstance(item_id, str) or not item_id:
            raise ValueError(f"scope item {index} requires a nonempty id")
        if item_id in scope_by_id:
            raise ValueError(f"Duplicate scope item id: {item_id}")
        scope_by_id[item_id] = item
        if not isinstance(kind, str) or not kind:
            raise ValueError(f"{item_id} requires a kind")
        if not isinstance(item.get("source_id"), str) or not item["source_id"]:
            raise ValueError(f"{item_id} requires a source_id")
        scope_counts[kind] += 1
        if item.get("disposition") not in SCOPE_DISPOSITIONS:
            raise ValueError(f"{item_id} has an unknown disposition")
        item_obligations = _strings(
            item.get("obligation_ids"), field=f"{item_id}.obligation_ids"
        )
        if set(item_obligations) - set(obligations_by_id):
            raise ValueError(f"{item_id} names an unknown obligation")
        if item["disposition"] != "nonfunctional_with_evidence" and not item_obligations:
            raise ValueError(f"{item_id} has no mapped obligation")
        item_evidence = _strings(
            item.get("evidence_ids", []), field=f"{item_id}.evidence_ids"
        )
        if set(item_evidence) - set(evidence_by_id):
            raise ValueError(f"{item_id} names unknown evidence")
        if item["disposition"] == "nonfunctional_with_evidence":
            has_passed_exclusion_receipt = any(
                evidence_by_id[evidence_id]["result"] == "passed"
                and {
                    "scope_item_id": item_id,
                    "decision": SCOPE_EXCLUSION_DECISION,
                }
                in evidence_by_id[evidence_id]["scope_disposition_receipts"]
                for evidence_id in item_evidence
            )
            if not has_passed_exclusion_receipt:
                raise ValueError(
                    f"{item_id} lacks matching passed evidence for its "
                    "nonfunctional disposition"
                )
        if item["disposition"] in {"pending_analysis", "provisional_obligation"}:
            unresolved_scope += 1

    for evidence_id, record in evidence_by_id.items():
        for receipt in record["scope_disposition_receipts"]:
            scope_item_id = receipt["scope_item_id"]
            scope_item = scope_by_id.get(scope_item_id)
            if scope_item is None:
                raise ValueError(
                    f"{evidence_id} names unknown scope item: {scope_item_id}"
                )
            if scope_item["disposition"] != "nonfunctional_with_evidence":
                raise ValueError(
                    f"{evidence_id} exclusion receipt does not match "
                    f"{scope_item_id}'s disposition"
                )
            if evidence_id not in scope_item.get("evidence_ids", []):
                raise ValueError(
                    f"{evidence_id} exclusion receipt is not referenced by "
                    f"{scope_item_id}"
                )

    source_inventory = register.get("source_inventory")
    if not isinstance(source_inventory, list) or not source_inventory:
        raise ValueError("Parity register requires source_inventory")
    domain_ids: set[str] = set()
    unresolved_domains: list[str] = []
    for domain in source_inventory:
        if not isinstance(domain, dict) or not isinstance(domain.get("id"), str):
            raise ValueError("Every source inventory domain requires an id")
        domain_id = domain["id"]
        if domain_id in domain_ids:
            raise ValueError(f"Duplicate source inventory id: {domain_id}")
        domain_ids.add(domain_id)
        if not isinstance(domain.get("resolved"), bool):
            raise ValueError(f"{domain_id}.resolved must be boolean")
        expected = domain.get("count")
        kind = domain.get("scope_kind")
        if expected is not None and (
            isinstance(expected, bool) or not isinstance(expected, int) or expected < 0
        ):
            raise ValueError(f"{domain_id}.count must be a nonnegative integer or null")
        if domain["resolved"] and expected is None:
            raise ValueError(f"{domain_id} cannot be resolved with an unknown count")
        if kind is not None:
            if not isinstance(expected, int) or expected < 0:
                raise ValueError(f"{domain_id}.count must be a nonnegative integer")
            if scope_counts[kind] != expected:
                raise ValueError(
                    f"{domain_id} count mismatch: {scope_counts[kind]} != {expected}"
                )
        if not domain["resolved"]:
            unresolved_domains.append(domain_id)
    if register["census_complete"] and (unresolved_scope or unresolved_domains):
        raise ValueError("census_complete cannot hide unresolved scope")

    return {
        "ledger_by_id": ledger_by_id,
        "obligations_by_id": obligations_by_id,
        "evidence_by_id": evidence_by_id,
        "scope_counts": dict(sorted(scope_counts.items())),
        "unresolved_scope_items": unresolved_scope,
        "unresolved_domains": unresolved_domains,
        "source_inventory": source_inventory,
    }


def evaluate(
    register: dict[str, Any],
    evidence: dict[str, Any],
    ledger: dict[str, Any],
    *,
    evidence_raw: bytes | None = None,
    ledger_raw: bytes | None = None,
    artifact_root: Path | None = None,
) -> dict[str, Any]:
    validated = validate_register(
        register,
        evidence,
        ledger,
        evidence_raw=evidence_raw,
        ledger_raw=ledger_raw,
        artifact_root=artifact_root,
    )
    obligations = list(validated["obligations_by_id"].values())
    defined = [item for item in obligations if item["definition_status"] == "defined"]
    implemented = [item for item in obligations if item["implementation_status"] == "implemented"]
    accepted = [
        item
        for item in obligations
        if item["definition_status"] == "defined"
        and item["applicability_status"] == "resolved"
        and item["implementation_status"] == "implemented"
        and all(
            state in {"accepted", "not_applicable"}
            for state in item["acceptance"].values()
        )
    ]
    denominator_ready = (
        register["census_complete"]
        and not validated["unresolved_scope_items"]
        and not validated["unresolved_domains"]
        and len(defined) == len(obligations)
    )

    def percent(count: int, total: int) -> float | None:
        if not denominator_ready or not total:
            return None
        return round(count * 100.0 / total, 2)

    complete = denominator_ready and len(accepted) == len(obligations)
    status_counts = Counter(feature["status"] for feature in ledger["features"])
    ledger_total = len(ledger["features"])
    acceptance_by_dimension = {}
    for dimension in REQUIRED_DIMENSIONS:
        states = Counter(item["acceptance"][dimension] for item in obligations)
        required = len(obligations) - states["not_applicable"]
        dimension_percent = None
        if denominator_ready:
            dimension_percent = (
                100.0
                if required == 0
                else round(states["accepted"] * 100.0 / required, 2)
            )
        acceptance_by_dimension[dimension] = {
            "required": required,
            "accepted": states["accepted"],
            "not_applicable": states["not_applicable"],
            "blocked": states["blocked"],
            "unassessed": states["unassessed"],
            "percent": dimension_percent,
        }
    blockers: list[str] = []
    if not register["census_complete"]:
        blockers.append("functional census is incomplete")
    if validated["unresolved_domains"]:
        blockers.append(
            f"{len(validated['unresolved_domains'])} source domains remain unresolved"
        )
    if validated["unresolved_scope_items"]:
        blockers.append(
            f"{validated['unresolved_scope_items']} source items require functional analysis"
        )
    if len(defined) != len(obligations):
        blockers.append(f"{len(obligations) - len(defined)} obligations remain provisional")
    if len(accepted) != len(obligations):
        blockers.append(f"{len(obligations) - len(accepted)} obligations are not fully accepted")
    return {
        "schema_version": register["schema_version"],
        "denominator_version": register["denominator_version"],
        "census_complete": register["census_complete"],
        "denominator_ready": denominator_ready,
        "functional_percent_available": denominator_ready,
        "obligations": {
            "total": len(obligations),
            "defined": len(defined),
            "implemented": len(implemented),
            "accepted": len(accepted),
            "implementation_percent": percent(len(implemented), len(obligations)),
            "accepted_percent": percent(len(accepted), len(obligations)),
        },
        "acceptance_by_dimension": acceptance_by_dimension,
        "physical_acceptance": acceptance_by_dimension["physical"],
        "legacy_category_summary": {
            "total": ledger_total,
            **{state: status_counts[state] for state in sorted(IMPLEMENTATION_STATES)},
            "implemented_percent": round(
                status_counts["implemented"] * 100.0 / ledger_total, 2
            )
            if ledger_total
            else 0.0,
            "functionality_estimate": False,
        },
        "scope_items": {
            "total": sum(validated["scope_counts"].values()),
            "by_kind": validated["scope_counts"],
            "unresolved": validated["unresolved_scope_items"],
        },
        "unresolved_domains": validated["unresolved_domains"],
        "source_inventory": {
            "total_domains": len(validated["source_inventory"]),
            "resolved_domains": sum(
                item["resolved"] for item in validated["source_inventory"]
            ),
            "records": validated["source_inventory"],
        },
        "evidence_records": len(validated["evidence_by_id"]),
        "blockers": blockers,
        "complete": complete,
    }


def load_packaged_documents() -> tuple[dict[str, Any], dict[str, Any], bytes]:
    package = files("cbus_toolkit")
    register_raw = package.joinpath(REGISTER_RESOURCE).read_bytes()
    evidence_raw = package.joinpath(EVIDENCE_RESOURCE).read_bytes()
    return (
        parse_json_document(register_raw, context=REGISTER_RESOURCE),
        parse_json_document(evidence_raw, context=EVIDENCE_RESOURCE),
        evidence_raw,
    )


def evaluate_packaged(ledger: dict[str, Any]) -> dict[str, Any]:
    register, evidence, evidence_raw = load_packaged_documents()
    ledger_raw = files("cbus_toolkit").joinpath("capabilities.json").read_bytes()
    packaged_ledger = parse_json_document(ledger_raw, context="capabilities.json")
    if packaged_ledger != ledger:
        raise ValueError("Caller feature ledger differs from packaged capabilities.json")
    return evaluate(
        register,
        evidence,
        ledger,
        evidence_raw=evidence_raw,
        ledger_raw=ledger_raw,
    )
