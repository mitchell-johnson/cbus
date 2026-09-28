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
import math
from pathlib import Path
import re
from typing import Any


REGISTER_RESOURCE = "parity-obligations.json"
EVIDENCE_RESOURCE = "parity-evidence.json"
CGATE_CONTRACT_RESOURCE = "cgate-contract-inventory.json"
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
REPORT_FORMATS = {"cbus-parity-test-report-v1", "cgate-session-differential-v2"}
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
CGATE_CONTRACT_AXIS_SCHEMA = {
    "selector_grammar": ("command_path", "argument_arity", "value_domains"),
    "session_states": ("connection", "recovery_mode", "selection_and_locks"),
    "target_forms": ("address_shape", "route_shape"),
    "authorization": ("connection_policy", "programming_gate", "handler_roles"),
    "response_event_envelopes": (
        "tag_and_completion_framing",
        "command_envelope",
        "event_fanout",
    ),
    "effects_routing": ("routing_class", "physical_io_boundary", "state_effect"),
    "implementation_acceptance": (
        "endpoint_route",
        "native_obsolescence",
        "functional_acceptance",
    ),
}
CGATE_SESSION_PILOT_IDS = {
    "SESSION_ID": "cgate-function:session-id-query",
    "SESSION_ID ALL": "cgate-function:session-id-all",
    "SESSION_ID TAG": "cgate-function:session-id-tag",
}
CGATE_SESSION_CASES = (
    ("session-query-a", "a", "SESSION_ID", "cgate-function:session-id-query"),
    ("session-query-b", "b", "SESSION_ID", "cgate-function:session-id-query"),
    ("session-all-initial", "a", "SESSION_ID ALL", "cgate-function:session-id-all"),
    ("session-tag-initial", "a", "SESSION_ID TAG C-Bus   Toolkit test", "cgate-function:session-id-tag"),
    ("session-all-tagged", "b", "SESSION_ID ALL", "cgate-function:session-id-all"),
    ("session-tag-reassign", "a", "SESSION_ID TAG replacement", "cgate-function:session-id-tag"),
    ("session-tag-missing", "a", "SESSION_ID TAG", "cgate-function:session-id-tag"),
    ("session-query-invalid", "a", "SESSION_ID bogus", "cgate-function:session-id-query"),
    ("session-all-trailing", "a", "SESSION_ID ALL ignored-by-native", "cgate-function:session-id-all"),
)


def cgate_path_obligation_id(path: str) -> str:
    """Stable, version-independent identity for one maintained command path."""
    return f"cgate-path:{sha256(path.encode('utf-8')).hexdigest()[:16]}"


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_nonfinite_constant(value: str) -> Any:
    raise ValueError(f"Non-finite JSON number is forbidden: {value}")


def _parse_finite_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"Non-finite JSON number is forbidden: {value}")
    return parsed


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
            parse_float=_parse_finite_float,
        )
    except json.JSONDecodeError as exc:
        raise ValueError(f"{context} is not valid JSON: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{context} must be a JSON object")
    return value


def _validate_execution_report(
    record: dict[str, Any], report: dict[str, Any], *, artifact_root: Path
) -> None:
    """Bind a passed evidence claim to the cases in its verified report bytes.

    The producer-side generator validates the full native differential and its
    current source closure. This independent packaged check prevents a wheel
    audit from accepting a changed report merely because its declaration and
    SHA-256 were changed together.
    """
    evidence_id = record["id"]
    verification = record["report_verification"]
    report_format = verification["format"]
    if report.get("format") != report_format:
        raise ValueError(f"{evidence_id} report format changed")
    if report.get("result") != record["result"]:
        raise ValueError(f"{evidence_id} report result differs from evidence")
    if report.get("source_revision") != record["source_revision"]:
        raise ValueError(f"{evidence_id} report source revision differs from evidence")
    if report.get("command") != record["command"]:
        raise ValueError(f"{evidence_id} report command differs from evidence")
    cases = report.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError(f"{evidence_id} report requires executed cases")
    if report_format == "cbus-parity-test-report-v1":
        if report.get("exit_code") != record["exit_code"]:
            raise ValueError(f"{evidence_id} report exit code differs from evidence")
        report_ids: set[str] = set()
        covered: set[tuple[str, str]] = set()
        reported_applicability: list[dict[str, Any]] = []
        reported_scope_dispositions: list[dict[str, Any]] = []
        for case in cases:
            if not isinstance(case, dict) or case.get("result") != "passed":
                raise ValueError(f"{evidence_id} report has a nonpassing case")
            test_id = case.get("id")
            if not isinstance(test_id, str) or not test_id or test_id in report_ids:
                raise ValueError(f"{evidence_id} report has an invalid case id")
            report_ids.add(test_id)
            obligation_ids = _strings(case.get("obligation_ids"), field=f"{evidence_id}.{test_id}.obligation_ids", nonempty=True)
            dimensions = _strings(case.get("dimensions"), field=f"{evidence_id}.{test_id}.dimensions")
            case_applicability = case.get("applicability_receipts", [])
            case_dispositions = case.get("scope_disposition_receipts", [])
            if not isinstance(case_applicability, list) or not isinstance(case_dispositions, list):
                raise ValueError(f"{evidence_id} report has invalid decision cases")
            if set(obligation_ids) - set(record["obligation_ids"]) or set(dimensions) - set(record["dimensions"]):
                raise ValueError(f"{evidence_id} report case exceeds its evidence scope")
            covered.update((obligation_id, dimension) for obligation_id in obligation_ids for dimension in dimensions)
            reported_applicability.extend(case_applicability)
            reported_scope_dispositions.extend(case_dispositions)
        required = {(obligation_id, dimension) for obligation_id in record["obligation_ids"] for dimension in record["dimensions"]}
        if report_ids != set(record["test_ids"]) or not required.issubset(covered):
            raise ValueError(f"{evidence_id} report cases do not cover declared tests and dimensions")
        if (
            reported_applicability != record.get("applicability_receipts", [])
            or reported_scope_dispositions != record["scope_disposition_receipts"]
        ):
            raise ValueError(f"{evidence_id} report decisions differ from evidence")
    elif report_format == "cgate-session-differential-v2":
        if "original_differential" not in record["dimensions"] or not isinstance(record.get("oracle"), dict):
            raise ValueError(f"{evidence_id} differential report requires an oracle")
        native_capture = report.get("native_capture")
        native_inputs = [
            artifact for artifact in record["artifacts"]
            if artifact["role"] == "input"
            and artifact["sha256"] == record["oracle"]["artifact_sha256"]
        ]
        if len(native_inputs) != 1:
            raise ValueError(f"{evidence_id} differential requires one native input")
        native = parse_json_document(
            (artifact_root / native_inputs[0]["path"]).read_bytes(),
            context=f"{evidence_id} native oracle",
        )
        native_cases = native.get("cases")
        if (
            report.get("product") != "cmqttd"
            or report.get("failed") != 0
            or report.get("skipped") != 0
            or report.get("errors") != []
            or report.get("normalization_errors") != []
            or report.get("executed") != len(cases)
            or report.get("passed") != len(cases)
            or len(cases) != len(CGATE_SESSION_CASES)
            or report.get("obligation_ids") != sorted(record["obligation_ids"])
            or not isinstance(native_capture, dict)
            or native_capture.get("sha256") != record["oracle"]["artifact_sha256"]
            or native_capture.get("path") != "toolkit-cli/" + native_inputs[0]["path"]
            or native.get("format") != "cbus-cgate-session-native-acceptance-v1"
            or native.get("passed") is not True
            or native.get("vendor_jar_sha256") != report.get("vendor_jar_sha256")
            or not isinstance(native_cases, list)
            or len(native_cases) < len(CGATE_SESSION_CASES)
        ):
            raise ValueError(f"{evidence_id} differential report is incomplete or mismatched")
        prefix = "research/cgate_session_differential.py::"
        report_ids: set[str] = set()
        covered_ids: set[str] = set()
        for index, (case, spec) in enumerate(zip(cases, CGATE_SESSION_CASES)):
            if not isinstance(case, dict):
                raise ValueError(f"{evidence_id} differential report has an invalid case")
            case_id = case.get("id")
            obligation_id = case.get("obligation_id")
            native_case = native_cases[index]
            reply = case.get("rust_reply")
            wire = case.get("rust_wire_reply")
            if (
                not isinstance(case_id, str) or not case_id
                or case_id in report_ids
                or obligation_id not in record["obligation_ids"]
                or (case_id, case.get("connection"), case.get("command"), obligation_id) != spec
                or not isinstance(native_case, dict)
                or native_case.get("connection") != spec[1]
                or native_case.get("command") != spec[2]
                or native_case.get("status") != case.get("native_status")
                or case.get("result") != "passed"
                or case.get("client_tag_echoed") is not True
                or case.get("native_status") != case.get("rust_status")
                or case.get("native_normalized") != case.get("rust_normalized")
                or not isinstance(reply, list) or not reply
                or not all(isinstance(row, str) for row in reply)
                or wire != [f"[d{index:02d}] {row}\r\n" for row in reply]
            ):
                raise ValueError(f"{evidence_id} differential case evidence changed")
            report_ids.add(case_id)
            covered_ids.add(obligation_id)
        if (
            {prefix + case_id for case_id in report_ids} != set(record["test_ids"])
            or covered_ids != set(record["obligation_ids"])
        ):
            raise ValueError(f"{evidence_id} differential cases do not cover declared tests")


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


def _canonical_object_digest(value: dict[str, Any]) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _validate_contract_axes(
    axes: Any, *, context: str
) -> tuple[dict[str, str], dict[str, str]]:
    if not isinstance(axes, dict) or set(axes) != set(CGATE_CONTRACT_AXIS_SCHEMA):
        raise ValueError(f"{context} must define the exact C-Gate contract axes")
    axis_status: dict[str, str] = {}
    subaxis_status: dict[str, str] = {}
    for axis_name, subaxis_names in CGATE_CONTRACT_AXIS_SCHEMA.items():
        axis = axes[axis_name]
        if not isinstance(axis, dict) or set(axis) != {"status", "subaxes"}:
            raise ValueError(f"{context}.{axis_name} has an invalid axis")
        subaxes = axis["subaxes"]
        if not isinstance(subaxes, dict) or tuple(subaxes) != subaxis_names:
            raise ValueError(f"{context}.{axis_name} has invalid subaxes")
        resolved_count = 0
        for subaxis_name, subaxis in subaxes.items():
            subaxis_context = f"{context}.{axis_name}.{subaxis_name}"
            if not isinstance(subaxis, dict) or subaxis.get("status") not in {
                "resolved",
                "unresolved",
            }:
                raise ValueError(f"{subaxis_context} has an invalid status")
            refs = _strings(
                subaxis.get("source_refs"),
                field=f"{subaxis_context}.source_refs",
                nonempty=True,
            )
            if any(not ref.strip() for ref in refs):
                raise ValueError(f"{subaxis_context} has an empty source reference")
            if subaxis["status"] == "resolved":
                resolved_count += 1
                if "value" not in subaxis or "reason" in subaxis:
                    raise ValueError(f"{subaxis_context} lacks a resolved value")
            elif (
                not isinstance(subaxis.get("reason"), str)
                or not subaxis["reason"].strip()
                or "value" in subaxis
            ):
                raise ValueError(f"{subaxis_context} lacks an unresolved reason")
            subaxis_status[f"{axis_name}.{subaxis_name}"] = subaxis["status"]
        expected_status = (
            "resolved"
            if resolved_count == len(subaxes)
            else "unresolved"
            if resolved_count == 0
            else "partial"
        )
        if axis.get("status") != expected_status:
            raise ValueError(f"{context}.{axis_name} aggregate status changed")
        axis_status[axis_name] = expected_status
    return axis_status, subaxis_status


def validate_cgate_contract_inventory(
    inventory: dict[str, Any], *, raw: bytes | None = None
) -> dict[str, dict[str, Any]]:
    if raw is not None:
        parsed = parse_json_document(raw, context=CGATE_CONTRACT_RESOURCE)
        if parsed != inventory:
            raise ValueError("Parsed C-Gate contract inventory differs from supplied inventory")
    if inventory.get("schema_version") != 1:
        raise ValueError("C-Gate contract inventory requires schema_version 1")
    if inventory.get("axis_schema") != {
        key: list(value) for key, value in CGATE_CONTRACT_AXIS_SCHEMA.items()
    }:
        raise ValueError("C-Gate contract inventory axis schema changed")
    if not isinstance(inventory.get("inventory_version"), str) or not inventory[
        "inventory_version"
    ]:
        raise ValueError("C-Gate contract inventory requires inventory_version")
    sources = inventory.get("sources")
    if not isinstance(sources, dict) or not sources:
        raise ValueError("C-Gate contract inventory requires sources")
    for source_name, source in sources.items():
        if (
            not isinstance(source_name, str)
            or not source_name
            or not isinstance(source, dict)
            or set(source) != {"sha256"}
            or not isinstance(source["sha256"], str)
            or not SHA256_RE.fullmatch(source["sha256"])
        ):
            raise ValueError(f"C-Gate contract source is invalid: {source_name!r}")
    if not {
        "native_session_selectors",
        "access_handler_registry", "native_initial_handler_roles", "native_handler_role_expansion",
        "native_programming_handler_roles",
        "native_media_handler_roles",
        "native_admin_handler_roles",
        "native_application_handler_roles",
            "native_dali_handler_selector_roles",
            "native_remaining_handler_roles",
            "native_unprobed_handler_roles",
            "native_final_handler_roles",
    } <= set(sources):
        raise ValueError("C-Gate contract native handler role sources are missing")
    contracts = inventory.get("contracts")
    if not isinstance(contracts, list) or len(contracts) != 442:
        raise ValueError("C-Gate contract inventory requires exactly 442 contracts")
    by_id: dict[str, dict[str, Any]] = {}
    paths: set[str] = set()
    inventory_counts: Counter[str] = Counter()
    axis_counts: dict[str, Counter[str]] = {
        axis_name: Counter() for axis_name in CGATE_CONTRACT_AXIS_SCHEMA
    }
    subaxis_counts: dict[str, Counter[str]] = {
        f"{axis_name}.{subaxis_name}": Counter()
        for axis_name, subaxis_names in CGATE_CONTRACT_AXIS_SCHEMA.items()
        for subaxis_name in subaxis_names
    }
    native_role_observations = 0
    for index, contract in enumerate(contracts):
        context = f"C-Gate contract {index}"
        if not isinstance(contract, dict):
            raise ValueError(f"{context} must be an object")
        contract_id = contract.get("id")
        path = contract.get("path")
        if not isinstance(contract_id, str) or not contract_id:
            raise ValueError(f"{context} requires an id")
        if contract_id in by_id:
            raise ValueError(f"Duplicate C-Gate contract id: {contract_id}")
        if not isinstance(path, str) or not path or path in paths:
            raise ValueError(f"{context} has an invalid or duplicate path")
        paths.add(path)
        inventory_kind = contract.get("inventory")
        if inventory_kind not in {"primary", "supplement"}:
            raise ValueError(f"{contract_id} has an invalid inventory kind")
        inventory_counts[inventory_kind] += 1
        if (
            not isinstance(contract.get("routing_evidence"), str)
            or not contract["routing_evidence"].strip()
        ):
            raise ValueError(f"{contract_id} requires routing evidence")
        axes = contract.get("axes")
        if contract.get("axes_sha256") != _canonical_object_digest(axes):
            raise ValueError(f"{contract_id} axes digest changed")
        unsigned = {
            key: value for key, value in contract.items() if key != "contract_sha256"
        }
        if contract.get("contract_sha256") != _canonical_object_digest(unsigned):
            raise ValueError(f"{contract_id} contract digest changed")
        statuses, substatuses = _validate_contract_axes(axes, context=contract_id)
        roles_axis = axes["authorization"]["subaxes"]["handler_roles"]
        roles_known = roles_axis.get("known", {})
        if not isinstance(roles_known, dict):
            raise ValueError(f"{contract_id} native handler known facts are invalid")
        observation = roles_known.get("native_handler_entry")
        if observation is not None:
            native_role_observations += 1
            matching_role_sources = [
                source_name
                for source_name, reference in (
                    ("native_initial_handler_roles", "rust/testdata/fixtures/native_cgate_authorization_probe.json"),
                    ("native_handler_role_expansion", "rust/testdata/fixtures/native_cgate_authorization_expansion_probe.json"),
                    ("native_programming_handler_roles", "rust/testdata/fixtures/native_cgate_programming_authorization_probe.json"),
                    ("native_media_handler_roles", "rust/testdata/fixtures/native_cgate_media_authorization_probe.json"),
                    ("native_admin_handler_roles", "rust/testdata/fixtures/native_cgate_admin_authorization_probe.json"),
                    ("native_application_handler_roles", "rust/testdata/fixtures/native_cgate_application_authorization_probe.json"),
                    ("native_dali_handler_selector_roles", "rust/testdata/fixtures/native_cgate_dali_authorization_probe.json"),
                    ("native_remaining_handler_roles", "rust/testdata/fixtures/native_cgate_remaining_authorization_probe.json"),
                    ("native_unprobed_handler_roles", "rust/testdata/fixtures/native_cgate_unprobed_authorization_probe.json"),
                    ("native_final_handler_roles", "rust/testdata/fixtures/native_cgate_final_authorization_probe.json"),
                )
                if isinstance(observation, dict)
                and observation.get("fixture_sha256") == sources[source_name]["sha256"]
                and reference in roles_axis["source_refs"]
            ]
            dali_role_source = matching_role_sources == [
                "native_dali_handler_selector_roles"
            ]
            expected_fields = {
                "invocation",
                "minimum_access_level_at_handler_entry",
                "lower_access_status",
                "at_floor_status",
                "observed_roles",
                "fixture_sha256",
                "scope",
            }
            if dali_role_source:
                expected_fields.add("selector_invocations")
            if (
                roles_axis["status"] != "unresolved"
                or len(matching_role_sources) != 1
                or not isinstance(observation, dict)
                or set(observation) != expected_fields
                or not isinstance(observation["invocation"], str)
                or not (
                    observation["invocation"] == path
                    or observation["invocation"].startswith(f"{path} ")
                )
                or observation["minimum_access_level_at_handler_entry"]
                not in {
                    "None", "Connect", "Monitor", "Operate", "Admin",
                    "Program", "Debug", "Clipsal", "Max",
                }
                or observation["lower_access_status"] != 420
                or type(observation["at_floor_status"]) is not int
                or not 100 <= observation["at_floor_status"] <= 699
                or observation["at_floor_status"] == 420
                or observation["observed_roles"] != 9
                or observation["scope"]
                != "exact_invocation_only; no_later_object_or_physical_success_claim"
            ):
                raise ValueError(f"{contract_id} native handler entry evidence changed")
            if dali_role_source:
                selectors = observation["selector_invocations"]
                if (
                    not isinstance(selectors, list)
                    or len(selectors) not in {1, 2}
                    or selectors[0] != {
                        "invocation": observation["invocation"],
                        "at_floor_status": observation["at_floor_status"],
                    }
                    or any(
                        not isinstance(item, dict)
                        or set(item) != {"invocation", "at_floor_status"}
                        or not isinstance(item["invocation"], str)
                        or not (
                            item["invocation"] == path
                            or item["invocation"].startswith(f"{path} ")
                        )
                        or type(item["at_floor_status"]) is not int
                        or not 100 <= item["at_floor_status"] <= 599
                        or item["at_floor_status"] == 420
                        for item in selectors
                    )
                    or (len(selectors) == 2 and not selectors[1]["invocation"].startswith(
                        f"{path} poll "
                    ))
                ):
                    raise ValueError(f"{contract_id} native DALI selector evidence changed")
        for name, status in statuses.items():
            axis_counts[name][status] += 1
        for name, status in substatuses.items():
            subaxis_counts[name][status] += 1
        by_id[contract_id] = contract
    counts = inventory.get("counts")
    expected_fixed = {
        "paths": 442,
        "primary_paths": 431,
        "supplement_paths": 11,
        "declarative_argument_arities": 70,
        "public_help_syntax_hashes": 209,
        "native_handler_role_observations": 431,
        "native_handler_role_unresolved": 431,
    }
    if not isinstance(counts, dict) or any(
        counts.get(key) != value for key, value in expected_fixed.items()
    ):
        raise ValueError("C-Gate contract inventory fixed counts changed")
    if inventory_counts != Counter({"primary": 431, "supplement": 11}):
        raise ValueError("C-Gate contract inventory path classes changed")
    if native_role_observations != counts["native_handler_role_observations"]:
        raise ValueError("C-Gate contract native handler observation count changed")
    expected_axis_counts = {
        key: dict(sorted(value.items())) for key, value in axis_counts.items()
    }
    expected_subaxis_counts = {
        key: dict(sorted(value.items())) for key, value in subaxis_counts.items()
    }
    if counts.get("axis_status") != expected_axis_counts:
        raise ValueError("C-Gate contract inventory axis counts changed")
    if counts.get("subaxis_status") != expected_subaxis_counts:
        raise ValueError("C-Gate contract inventory subaxis counts changed")
    return by_id


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
        if not isinstance(record.get("result"), str) or record["result"] not in EVIDENCE_RESULTS:
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
            record.get("dimensions"), field=f"{evidence_id}.dimensions"
        )
        unknown_dimensions = set(dimensions) - set(REQUIRED_DIMENSIONS)
        if unknown_dimensions:
            raise ValueError(
                f"{evidence_id} has unknown dimensions: {sorted(unknown_dimensions)}"
            )
        applicability_receipts = record.get("applicability_receipts", [])
        if not isinstance(applicability_receipts, list):
            raise ValueError(f"{evidence_id}.applicability_receipts must be an array")
        applicability_keys: set[tuple[str, str]] = set()
        for receipt_index, receipt in enumerate(applicability_receipts):
            receipt_context = f"{evidence_id}.applicability_receipts[{receipt_index}]"
            if not isinstance(receipt, dict) or set(receipt) != {
                "obligation_id", "dimension", "decision", "reason"
            }:
                raise ValueError(f"{receipt_context} has an invalid applicability receipt")
            obligation_id, dimension = receipt["obligation_id"], receipt["dimension"]
            if (
                not isinstance(obligation_id, str)
                or not isinstance(dimension, str)
                or obligation_id not in obligation_ids
                or dimension not in REQUIRED_DIMENSIONS
            ):
                raise ValueError(f"{receipt_context} is not bound to this evidence")
            if receipt["decision"] != "not_applicable":
                raise ValueError(f"{receipt_context} has an unknown applicability decision")
            if not isinstance(receipt["reason"], str) or not receipt["reason"].strip():
                raise ValueError(f"{receipt_context} requires a reason")
            key = (obligation_id, dimension)
            if key in applicability_keys:
                raise ValueError(f"{evidence_id} has duplicate applicability receipts")
            applicability_keys.add(key)
        if not dimensions and not applicability_receipts and not disposition_receipts:
            raise ValueError(f"{evidence_id} has no dimension or decision to evidence")
        test_ids = _strings(
            record.get("test_ids"), field=f"{evidence_id}.test_ids", nonempty=True
        )
        if any(not test_id.strip() for test_id in test_ids):
            raise ValueError(f"{evidence_id}.test_ids contains an empty identifier")
        environment = record.get("environment")
        if not isinstance(environment, dict):
            raise ValueError(f"{evidence_id} requires an environment")
        environment_kind = environment.get("kind")
        if not isinstance(environment_kind, str) or environment_kind not in EVIDENCE_ENVIRONMENTS:
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
        artifact_roles: set[str] = set()
        input_digests: set[str] = set()
        for artifact_index, artifact in enumerate(artifacts):
            if not isinstance(artifact, dict):
                raise ValueError(f"{evidence_id}.artifacts[{artifact_index}] must be an object")
            path = artifact.get("path")
            digest = artifact.get("sha256")
            if artifact.get("role") not in ARTIFACT_ROLES:
                raise ValueError(f"{evidence_id} artifact has an unknown role")
            artifact_roles.add(artifact["role"])
            if not isinstance(path, str) or not path or Path(path).is_absolute() or ".." in Path(path).parts:
                raise ValueError(f"{evidence_id} has an unsafe artifact path")
            if path in artifact_paths:
                raise ValueError(f"{evidence_id} has duplicate artifact paths")
            artifact_paths.add(path)
            if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
                raise ValueError(f"{evidence_id} artifact requires a lowercase SHA-256")
            if artifact["role"] == "input":
                input_digests.add(digest)
            if artifact_root is not None:
                candidate = (artifact_root / path).resolve()
                root = artifact_root.resolve()
                if root not in candidate.parents and candidate != root:
                    raise ValueError(f"{evidence_id} artifact escapes its root")
                if not candidate.is_file():
                    raise ValueError(f"{evidence_id} artifact is missing: {path}")
                if sha256(candidate.read_bytes()).hexdigest() != digest:
                    raise ValueError(f"{evidence_id} artifact digest changed: {path}")
        if record["result"] == "passed" and not artifact_roles.intersection({"output", "report"}):
            raise ValueError(f"{evidence_id} passed evidence requires an output or report artifact")
        if record["result"] == "passed":
            verification = record.get("report_verification")
            if (
                not isinstance(verification, dict)
                or set(verification) != {"format", "path"}
                or verification.get("format") not in REPORT_FORMATS
                or not isinstance(verification.get("path"), str)
                or verification["path"] not in artifact_paths
                or not any(
                    artifact["role"] == "report" and artifact["path"] == verification["path"]
                    for artifact in artifacts
                )
            ):
                raise ValueError(f"{evidence_id} requires a recognized report artifact")
            if artifact_root is not None:
                report_path = (artifact_root / verification["path"]).resolve()
                report = parse_json_document(
                    report_path.read_bytes(), context=f"{evidence_id} execution report"
                )
                _validate_execution_report(record, report, artifact_root=artifact_root)
        if "original_differential" in dimensions and oracle_digest not in input_digests:
            raise ValueError(f"{evidence_id} oracle digest requires a matching input artifact")
        skips = record.get("skips")
        if not isinstance(skips, list):
            raise ValueError(f"{evidence_id}.skips must be an array")
        skipped_cases: set[str] = set()
        for skip_index, skip in enumerate(skips):
            if not isinstance(skip, dict):
                raise ValueError(f"{evidence_id}.skips[{skip_index}] must be an object")
            if not isinstance(skip.get("case_id"), str) or not skip["case_id"]:
                raise ValueError(f"{evidence_id} has an unexplained skip without case_id")
            case_id = skip["case_id"]
            if case_id in skipped_cases:
                raise ValueError(f"{evidence_id} has duplicate skipped case IDs")
            if case_id in test_ids:
                raise ValueError(f"{evidence_id} claims a skipped test as executed")
            skipped_cases.add(case_id)
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
    cgate_contract_inventory: dict[str, Any] | None = None,
    cgate_contract_raw: bytes | None = None,
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
    cgate_contracts_by_id: dict[str, dict[str, Any]] | None = None
    if (
        "cgate_contract_inventory" in source_digests
        and cgate_contract_inventory is None
    ):
        raise ValueError("C-Gate contract inventory is required by this parity register")
    if cgate_contract_inventory is not None:
        cgate_contracts_by_id = validate_cgate_contract_inventory(
            cgate_contract_inventory, raw=cgate_contract_raw
        )
        if cgate_contract_raw is None:
            raise ValueError("C-Gate contract inventory bytes are required")
        if sha256(cgate_contract_raw).hexdigest() != source_digests.get(
            "cgate_contract_inventory"
        ):
            raise ValueError("Parity C-Gate contract inventory digest changed")
    elif cgate_contract_raw is not None:
        raise ValueError("C-Gate contract inventory object is required with its bytes")
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
    cgate_path_obligations: dict[str, dict[str, Any]] = {}
    cgate_function_obligations: dict[str, dict[str, Any]] = {}
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
        is_cgate_path = (
            obligation.get("kind") == "cgate_path"
            or obligation_id.startswith("cgate-path:")
        )
        is_cgate_function = (
            obligation.get("kind") == "cgate_function"
            or obligation_id.startswith("cgate-function:")
        )
        if is_cgate_path:
            if obligation.get("kind") != "cgate_path":
                raise ValueError(f"{obligation_id} requires cgate_path kind")
            if ledger_id != "cgate-command-transport":
                raise ValueError(f"{obligation_id} has an incorrect broad-ledger mapping")
            path = obligation.get("source_id")
            if not isinstance(path, str) or not path:
                raise ValueError(f"{obligation_id} requires a C-Gate source path")
            if obligation_id != cgate_path_obligation_id(path):
                raise ValueError(f"{obligation_id} has an unstable C-Gate path id")
            if not isinstance(obligation.get("source_scope_item_id"), str):
                raise ValueError(f"{obligation_id} requires a source scope item id")
            if obligation.get("contract_id") != f"cgate-contract:{obligation_id.removeprefix('cgate-path:')}":
                raise ValueError(f"{obligation_id} has an incorrect C-Gate contract id")
            if not isinstance(obligation.get("contract_sha256"), str) or not SHA256_RE.fullmatch(
                obligation["contract_sha256"]
            ):
                raise ValueError(f"{obligation_id} requires a C-Gate contract digest")
            if not isinstance(obligation.get("implementation_basis"), str) or not obligation[
                "implementation_basis"
            ].strip():
                raise ValueError(f"{obligation_id} requires an implementation basis")
            cgate_path_obligations[obligation_id] = obligation
        if is_cgate_function:
            path = obligation.get("source_id")
            if obligation.get("kind") != "cgate_function" or not isinstance(path, str):
                raise ValueError(f"{obligation_id} requires cgate_function kind and path")
            if obligation_id != CGATE_SESSION_PILOT_IDS.get(path):
                raise ValueError(f"{obligation_id} has an unstable functional pilot ID")
            if ledger_id != "cgate-command-transport":
                raise ValueError(f"{obligation_id} has an incorrect broad-ledger mapping")
            source_anchor = obligation.get("source_anchor")
            if not isinstance(source_anchor, dict) or set(source_anchor) != {
                "path", "line", "syntax_start_line", "syntax_end_line", "syntax_sha256",
            }:
                raise ValueError(f"{obligation_id} requires an exact public-help source anchor")
            if (
                source_anchor["path"] != "research/vendor/cgate/app/help/cmds.txt"
                or not isinstance(source_anchor["line"], int)
                or not isinstance(source_anchor["syntax_start_line"], int)
                or not isinstance(source_anchor["syntax_end_line"], int)
                or not isinstance(source_anchor["syntax_sha256"], str)
                or not SHA256_RE.fullmatch(source_anchor["syntax_sha256"])
            ):
                raise ValueError(f"{obligation_id} has an invalid public-help source anchor")
            if obligation.get("definition_status") != "defined":
                raise ValueError(f"{obligation_id} must be an explicitly defined function")
            if not isinstance(obligation.get("implementation_basis"), str) or not obligation[
                "implementation_basis"
            ].strip():
                raise ValueError(f"{obligation_id} requires an independent implementation basis")
            implementation = obligation.get("implementation")
            if not isinstance(implementation, dict) or set(implementation) != {
                "owner", "cli_entry_point", "test_ids"
            }:
                raise ValueError(f"{obligation_id} requires implementation ownership and tests")
            for key in ("owner", "cli_entry_point"):
                if not isinstance(implementation[key], str) or not implementation[key].strip():
                    raise ValueError(f"{obligation_id} requires implementation {key}")
            _strings(implementation["test_ids"], field=f"{obligation_id}.implementation.test_ids", nonempty=True)
            oracle = obligation.get("native_oracle")
            if not isinstance(oracle, dict) or set(oracle) != {
                "path", "sha256", "vendor_jar_sha256", "cases"
            }:
                raise ValueError(f"{obligation_id} requires an exact native oracle anchor")
            if oracle["path"] != (
                "research/experiments/2026-09-25/cgate-session-native-acceptance.json"
            ) or oracle["sha256"] != source_digests.get("cgate_session_native_acceptance"):
                raise ValueError(f"{obligation_id} native acceptance anchor is stale or missing")
            if not isinstance(oracle["vendor_jar_sha256"], str) or not SHA256_RE.fullmatch(
                oracle["vendor_jar_sha256"]
            ):
                raise ValueError(f"{obligation_id} requires a native C-Gate artifact digest")
            cases = oracle["cases"]
            if not isinstance(cases, list) or not cases or any(
                not isinstance(case, dict)
                or set(case) != {"command", "status"}
                or not isinstance(case["command"], str)
                or not case["command"]
                or isinstance(case["status"], bool)
                or not isinstance(case["status"], int)
                for case in cases
            ):
                raise ValueError(f"{obligation_id} requires native command/status cases")
            applicability = obligation.get("applicability")
            if not isinstance(applicability, dict) or set(applicability) != {
                "profile", "physical_candidate", "physical_candidate_reason",
                "unresolved_profiles",
            }:
                raise ValueError(f"{obligation_id} requires independent applicability fields")
            candidate = applicability["physical_candidate"]
            if candidate not in {"not_applicable_pending_receipt", "not_applicable_verified"}:
                raise ValueError(f"{obligation_id} has an unknown physical applicability decision")
            if obligation.get("applicability_status") != "unresolved":
                raise ValueError(f"{obligation_id} applicability remains unresolved until reviewed")
            for key in ("profile", "physical_candidate_reason"):
                if not isinstance(applicability[key], str) or not applicability[key].strip():
                    raise ValueError(f"{obligation_id} requires applicability {key}")
            _strings(
                applicability["unresolved_profiles"],
                field=f"{obligation_id}.applicability.unresolved_profiles",
                nonempty=True,
            )
            if not isinstance(obligation.get("differential_gap"), str) or not obligation[
                "differential_gap"
            ].strip():
                raise ValueError(f"{obligation_id} requires an original-differential gap")
            for key in ("preconditions", "preservation"):
                _strings(obligation.get(key), field=f"{obligation_id}.{key}", nonempty=True)
            cgate_function_obligations[obligation_id] = obligation
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
        if not (is_cgate_path or is_cgate_function) and obligation["implementation_status"] != ledger_by_id[ledger_id]["status"]:
            raise ValueError(f"{obligation_id} implementation status drifts from {ledger_id}")
        if (
            is_cgate_path
            and obligation["implementation_basis"] == "route_reachable_contract_incomplete"
            and obligation["implementation_status"] != "in_progress"
        ):
            raise ValueError(f"{obligation_id} overstates route-only implementation")
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
            if state == "accepted" and not any(
                evidence_by_id[evidence_id]["result"] == "passed"
                and dimension in evidence_by_id[evidence_id]["dimensions"]
                and obligation_id in evidence_by_id[evidence_id]["obligation_ids"]
                for evidence_id in evidence_ids
            ):
                raise ValueError(
                    f"{obligation_id}.{dimension} lacks matching passed evidence"
                )
            if state == "not_applicable" and not any(
                evidence_by_id[evidence_id]["result"] == "passed"
                and receipt["obligation_id"] == obligation_id
                and receipt["dimension"] == dimension
                for evidence_id in evidence_ids
                for receipt in evidence_by_id[evidence_id].get("applicability_receipts", [])
            ):
                raise ValueError(
                    f"{obligation_id}.{dimension} lacks a passed not-applicable decision"
                )
        if obligation.get("kind") == "cgate_function":
            candidate = obligation["applicability"]["physical_candidate"]
            physical = acceptance["physical"]
            if (candidate == "not_applicable_verified") != (physical == "not_applicable"):
                raise ValueError(
                    f"{obligation_id} physical applicability status differs from its receipt"
                )
        obligations_by_id[obligation_id] = obligation
    for evidence_id, record in evidence_by_id.items():
        for receipt in record.get("applicability_receipts", []):
            obligation_id, dimension = receipt["obligation_id"], receipt["dimension"]
            obligation = obligations_by_id.get(obligation_id)
            if obligation is None or evidence_id not in obligation["evidence_ids"]:
                raise ValueError(
                    f"{evidence_id} applicability receipt is not referenced by {obligation_id}"
                )
            if obligation["acceptance"][dimension] != "not_applicable":
                raise ValueError(
                    f"{evidence_id} applicability receipt differs from {obligation_id}.{dimension}"
                )
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
    cgate_contract_ids: set[str] = set()
    cgate_axis_counts: dict[str, Counter[str]] = {
        axis_name: Counter() for axis_name in CGATE_CONTRACT_AXIS_SCHEMA
    }
    cgate_subaxis_counts: dict[str, Counter[str]] = {
        f"{axis_name}.{subaxis_name}": Counter()
        for axis_name, subaxis_names in CGATE_CONTRACT_AXIS_SCHEMA.items()
        for subaxis_name in subaxis_names
    }
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
        if kind in {"cgate_primary_path", "cgate_supplement_path"}:
            contract_id = item.get("contract_id")
            if not isinstance(contract_id, str) or not contract_id:
                raise ValueError(f"{item_id} requires a C-Gate contract id")
            if contract_id in cgate_contract_ids:
                raise ValueError(f"Duplicate scoped C-Gate contract id: {contract_id}")
            cgate_contract_ids.add(contract_id)
            contract_digest = item.get("contract_sha256")
            axes_digest = item.get("contract_axes_sha256")
            if (
                not isinstance(contract_digest, str)
                or not SHA256_RE.fullmatch(contract_digest)
                or not isinstance(axes_digest, str)
                or not SHA256_RE.fullmatch(axes_digest)
            ):
                raise ValueError(f"{item_id} requires C-Gate contract digests")
            axes = item.get("contract_axes")
            if axes_digest != _canonical_object_digest(axes):
                raise ValueError(f"{item_id} C-Gate contract axes digest changed")
            statuses, substatuses = _validate_contract_axes(
                axes, context=f"{item_id}.contract_axes"
            )
            for name, status in statuses.items():
                cgate_axis_counts[name][status] += 1
            for name, status in substatuses.items():
                cgate_subaxis_counts[name][status] += 1
            routing_class = item.get("routing_class")
            if (
                axes["effects_routing"]["subaxes"]["routing_class"].get("value")
                != routing_class
            ):
                raise ValueError(f"{item_id} routing class differs from its contract")
            if cgate_contracts_by_id is not None:
                contract = cgate_contracts_by_id.get(contract_id)
                if contract is None:
                    raise ValueError(f"{item_id} names unknown C-Gate contract")
                expected_kind = (
                    "primary" if kind == "cgate_primary_path" else "supplement"
                )
                if (
                    contract["path"] != item["source_id"]
                    or contract["inventory"] != expected_kind
                    or contract["contract_sha256"] != contract_digest
                    or contract["axes_sha256"] != axes_digest
                    or contract["axes"] != axes
                ):
                    raise ValueError(
                        f"{item_id} differs from packaged C-Gate contract inventory"
                    )
        if item.get("disposition") not in SCOPE_DISPOSITIONS:
            raise ValueError(f"{item_id} has an unknown disposition")
        item_obligations = _strings(
            item.get("obligation_ids"), field=f"{item_id}.obligation_ids"
        )
        if set(item_obligations) - set(obligations_by_id):
            raise ValueError(f"{item_id} names an unknown obligation")
        if kind in {"cgate_primary_path", "cgate_supplement_path"}:
            expected_path_id = cgate_path_obligation_id(item["source_id"])
            scoped_path_ids = [
                obligation_id
                for obligation_id in item_obligations
                if obligation_id.startswith("cgate-path:")
            ]
            if scoped_path_ids != [expected_path_id]:
                raise ValueError(f"{item_id} requires exactly its own C-Gate path obligation")
            if "ledger:cgate-command-transport" not in item_obligations:
                raise ValueError(f"{item_id} lacks its broad-ledger mapping")
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

    if cgate_contracts_by_id is not None and cgate_contract_ids != set(
        cgate_contracts_by_id
    ):
        raise ValueError("Scoped C-Gate contracts differ from packaged inventory")
    if cgate_contracts_by_id is None and cgate_path_obligations:
        raise ValueError("C-Gate path obligations require a packaged contract inventory")
    if cgate_contracts_by_id is not None:
        expected_path_ids = {
            cgate_path_obligation_id(contract["path"])
            for contract in cgate_contracts_by_id.values()
        }
        if set(cgate_path_obligations) != expected_path_ids:
            raise ValueError("C-Gate path obligations differ from packaged contracts")
        for obligation_id, obligation in cgate_path_obligations.items():
            contract = cgate_contracts_by_id.get(obligation["contract_id"])
            if contract is None:
                raise ValueError(f"{obligation_id} names an unknown C-Gate contract")
            scope_kind = (
                "cgate_primary_path"
                if contract["inventory"] == "primary"
                else "cgate_supplement_path"
            )
            expected_scope_id = f"scope:{scope_kind}:{obligation_id.removeprefix('cgate-path:')}"
            scope = scope_by_id.get(expected_scope_id)
            if (
                obligation["source_id"] != contract["path"]
                or obligation["contract_sha256"] != contract["contract_sha256"]
                or obligation["source_scope_item_id"] != expected_scope_id
                or scope is None
                or obligation_id not in scope["obligation_ids"]
                or scope["contract_id"] != contract["id"]
            ):
                raise ValueError(f"{obligation_id} differs from its source-bound C-Gate scope")

    if "functional_obligation_pilot" in source_digests:
        if set(cgate_function_obligations) != set(CGATE_SESSION_PILOT_IDS.values()):
            raise ValueError("Functional pilot is missing a defined SESSION_ID obligation")
    elif cgate_function_obligations:
        raise ValueError("Functional pilot lacks its source manifest digest")
    for obligation_id, obligation in cgate_function_obligations.items():
        path = obligation["source_id"]
        expected_scopes = [
            f"scope:public-command:cgate:{path}",
            f"scope:cgate_primary_path:{sha256(path.encode('utf-8')).hexdigest()[:16]}",
        ]
        if obligation.get("source_scope_item_ids") != expected_scopes:
            raise ValueError(f"{obligation_id} has missing source scope anchors")
        public_scope = scope_by_id.get(expected_scopes[0])
        path_scope = scope_by_id.get(expected_scopes[1])
        if (
            public_scope is None
            or path_scope is None
            or obligation_id not in public_scope["obligation_ids"]
            or obligation_id not in path_scope["obligation_ids"]
            or public_scope.get("source_anchor") != obligation.get("source_anchor")
            or public_scope.get("source_sha256") != obligation["source_anchor"].get("syntax_sha256")
            or path_scope.get("contract_id") != obligation.get("contract_id")
            or path_scope.get("contract_sha256") != obligation.get("contract_sha256")
            or "ledger:cgate-command-transport" not in public_scope["obligation_ids"]
            or "ledger:cgate-command-transport" not in path_scope["obligation_ids"]
        ):
            raise ValueError(f"{obligation_id} differs from its source and broad-ledger anchors")

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
    expected_cgate_axis_counts = {
        key: dict(sorted(value.items())) for key, value in cgate_axis_counts.items()
    }
    expected_cgate_subaxis_counts = {
        key: dict(sorted(value.items())) for key, value in cgate_subaxis_counts.items()
    }
    domain_ids: set[str] = set()
    domain_scope_kinds: set[str] = set()
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
            if not isinstance(kind, str) or not kind:
                raise ValueError(f"{domain_id}.scope_kind must be a nonempty string")
            if kind in domain_scope_kinds:
                raise ValueError(f"Duplicate source inventory scope kind: {kind}")
            domain_scope_kinds.add(kind)
            if not isinstance(expected, int) or expected < 0:
                raise ValueError(f"{domain_id}.count must be a nonnegative integer")
            if scope_counts[kind] != expected:
                raise ValueError(
                    f"{domain_id} count mismatch: {scope_counts[kind]} != {expected}"
                )
        if domain_id == "cgate_selector_state_effect_contracts":
            if expected != len(cgate_contract_ids):
                raise ValueError("C-Gate contract domain count differs from scoped contracts")
            version = domain.get("contract_inventory_version")
            if not isinstance(version, str) or not version:
                raise ValueError("C-Gate contract domain requires an inventory version")
            if cgate_contract_inventory is not None and version != cgate_contract_inventory.get(
                "inventory_version"
            ):
                raise ValueError("C-Gate contract inventory version changed")
            if domain.get("axis_status") != expected_cgate_axis_counts:
                raise ValueError("C-Gate contract domain axis counts changed")
            if domain.get("subaxis_status") != expected_cgate_subaxis_counts:
                raise ValueError("C-Gate contract domain subaxis counts changed")
            if domain["resolved"] and any(
                states != {"resolved": expected}
                for states in expected_cgate_axis_counts.values()
            ):
                raise ValueError(
                    "C-Gate contract domain cannot resolve while contract axes remain partial or unresolved"
                )
        if not domain["resolved"]:
            unresolved_domains.append(domain_id)
    if domain_scope_kinds != set(scope_counts):
        missing = sorted(set(scope_counts) - domain_scope_kinds)
        extra = sorted(domain_scope_kinds - set(scope_counts))
        raise ValueError(
            "Source inventory scope kinds differ from scoped kinds "
            f"(missing={missing}, extra={extra})"
        )
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
        "cgate_contracts": {
            "paths": len(cgate_contract_ids),
            "axis_status": expected_cgate_axis_counts,
            "subaxis_status": expected_cgate_subaxis_counts,
        },
    }


def evaluate(
    register: dict[str, Any],
    evidence: dict[str, Any],
    ledger: dict[str, Any],
    *,
    evidence_raw: bytes | None = None,
    ledger_raw: bytes | None = None,
    cgate_contract_inventory: dict[str, Any] | None = None,
    cgate_contract_raw: bytes | None = None,
    artifact_root: Path | None = None,
) -> dict[str, Any]:
    validated = validate_register(
        register,
        evidence,
        ledger,
        evidence_raw=evidence_raw,
        ledger_raw=ledger_raw,
        cgate_contract_inventory=cgate_contract_inventory,
        cgate_contract_raw=cgate_contract_raw,
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

    # The register binds declared hashes, but only a caller with a trusted
    # artifact root can verify that the recorded inputs and reports exist and
    # still have those bytes. A wheel's embedded declarations alone cannot
    # establish a completed release.
    evidence_artifacts_verified = artifact_root is not None

    def percent(count: int, total: int) -> float | None:
        if not denominator_ready or not evidence_artifacts_verified or not total:
            return None
        return round(count * 100.0 / total, 2)

    complete = (
        denominator_ready
        and evidence_artifacts_verified
        and len(accepted) == len(obligations)
    )
    status_counts = Counter(feature["status"] for feature in ledger["features"])
    ledger_total = len(ledger["features"])
    acceptance_by_dimension = {}
    for dimension in REQUIRED_DIMENSIONS:
        states = Counter(item["acceptance"][dimension] for item in obligations)
        required = len(obligations) - states["not_applicable"]
        dimension_percent = None
        if denominator_ready and evidence_artifacts_verified:
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
    if not evidence_artifacts_verified:
        blockers.append("evidence artifacts have not been verified against a trusted root")
    return {
        "schema_version": register["schema_version"],
        "denominator_version": register["denominator_version"],
        "census_complete": register["census_complete"],
        "denominator_ready": denominator_ready,
        "functional_percent_available": denominator_ready and evidence_artifacts_verified,
        "evidence_artifacts_verified": evidence_artifacts_verified,
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
        "cgate_contracts": validated["cgate_contracts"],
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


def load_packaged_documents() -> tuple[
    dict[str, Any], dict[str, Any], bytes, dict[str, Any], bytes
]:
    package = files("cbus_toolkit")
    register_raw = package.joinpath(REGISTER_RESOURCE).read_bytes()
    evidence_raw = package.joinpath(EVIDENCE_RESOURCE).read_bytes()
    cgate_contract_raw = package.joinpath(CGATE_CONTRACT_RESOURCE).read_bytes()
    return (
        parse_json_document(register_raw, context=REGISTER_RESOURCE),
        parse_json_document(evidence_raw, context=EVIDENCE_RESOURCE),
        evidence_raw,
        parse_json_document(cgate_contract_raw, context=CGATE_CONTRACT_RESOURCE),
        cgate_contract_raw,
    )


def evaluate_packaged(
    ledger: dict[str, Any], *, artifact_root: Path | None = None
) -> dict[str, Any]:
    (
        register,
        evidence,
        evidence_raw,
        cgate_contract_inventory,
        cgate_contract_raw,
    ) = load_packaged_documents()
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
        cgate_contract_inventory=cgate_contract_inventory,
        cgate_contract_raw=cgate_contract_raw,
        artifact_root=artifact_root,
    )
