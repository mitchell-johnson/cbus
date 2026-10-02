"""Reconcile an explicitly declared source surface with functional obligations.

This offline diagnostic does not replace the packaged parity evaluator. Its
denominator counts declared source/profile/variant mappings, not undocumented
Toolkit functions. A caller's ``source_inventory_complete`` flag cannot verify
the original census or close full Toolkit parity.

The v1 bundle has ``format``, ``source_inventory_complete``, ``sources``,
``obligations``, ``bindings``, ``receipts`` and ``current_artifacts``. Sources
come from :func:`collect_source_records`; an independent review must supply
their explicit ``profile_variants`` and any resolved ``handler_id``. Obligations
declare profiles, variants and required dimensions. Bindings name an exact
source hash and one obligation/profile/variant, or a reviewed nonfunctional
disposition. There is no title, filename, generic forwarding or status heuristic.

Receipt records have an exact source-pin and case-observation matrix. Their
artifact bytes must equal the canonical evidence document (the record without
its ``artifact`` field). Original/physical observations additionally need an
owner-issued :class:`VerifiedGate` from retained manifest/trace/JUnit/receipt
bytes. This verifies retained evidence, never executes a gate or a vendor.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from functools import wraps
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping
import xml.etree.ElementTree as ET


BUNDLE_FORMAT = "cbus-toolkit-obligation-reconciliation-bundle-v1"
EVIDENCE_FORMAT = "cbus-toolkit-obligation-reconciliation-evidence-v1"
REPORT_FORMAT = "cbus-toolkit-obligation-reconciliation-report-v1"
SCOPE = "declared-modeled-input-surface-only"
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_PRIVATE = re.compile(r"(?:/(?:Users|Volumes|private|home|tmp|var)/|(?<![A-Za-z0-9_])[A-Za-z]:[\\/]|\\\\)")
_DIMENSIONS = frozenset({"nominal", "error", "invalid_input", "profile_variation",
                         "original_differential", "physical", "persistence_recovery",
                         "static_analysis", "scope_disposition"})
_RESULTS = frozenset({"passed", "failed", "skipped", "unassessed"})
_KINDS = frozenset({"modeled", "static", "original", "hardware", "declarative",
                   "generic_forwarding", "test_inventory"})
_SCALAR_COLOR = frozenset({"tledstatusindicator", "tflashledstatusindicator"})
_ISSUER = object()
_ANCHORS = frozenset({"resource_sha256", "root_class", "root_name", "class", "name",
                      "component_class", "form_class", "property", "value", "handler",
                      "page_sha256", "heading_sha256", "topic_id", "syntax_sha256",
                      "assembly", "symbol", "body_sha256", "declaration_sha256", "event", "owner"})
_SOURCE_KINDS = frozenset({"executable_form", "executable_control", "executable_property",
                          "executable_event", "topic", "heading", "anchor", "dialog", "macro_leaf",
                          "unindexed_html", "public_command", "managed_method", "native_method",
                          "managed_declaration", "managed_api", "managed_control", "managed_event"})


class ReconciliationError(ValueError):
    """A bundle has ambiguous, malformed or unsafe declarations."""


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value: Any) -> str:
    return sha256(canonical_bytes(value)).hexdigest()


def artifact_pin(raw: bytes) -> dict[str, Any]:
    return {"sha256": sha256(raw).hexdigest(), "bytes": len(raw)}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ReconciliationError(message)


def _text(value: Any, context: str) -> str:
    _require(isinstance(value, str) and bool(value),
             f"{context} needs a nonempty exact string")
    _require(not _PRIVATE.search(value) and not any(ord(c) < 32 for c in value),
             f"{context} contains a private coordinate or control character")
    return value


def _pin(value: Any, context: str) -> dict[str, Any]:
    _require(isinstance(value, dict) and set(value) == {"sha256", "bytes"},
             f"{context} needs SHA256 and byte length")
    _require(isinstance(value["sha256"], str) and bool(_SHA.fullmatch(value["sha256"]))
             and type(value["bytes"]) is int and value["bytes"] >= 0,
             f"{context} has an invalid artifact pin")
    return value


def _safe(value: Any, context: str) -> None:
    if isinstance(value, str):
        _require(not _PRIVATE.search(value) and not any(ord(c) < 32 for c in value),
                 f"{context} contains a private coordinate or control character")
    elif isinstance(value, dict):
        for key, item in value.items():
            _text(key, context)
            _safe(item, context)
    elif isinstance(value, list):
        for item in value:
            _safe(item, context)
    else:
        _require(value is None or type(value) in (bool, int),
                 f"{context} contains unsupported metadata")


def _unique_rows(rows: Any, context: str, key: str = "id") -> dict[str, dict]:
    _require(isinstance(rows, list), f"{context} needs a list")
    result: dict[str, dict] = {}
    for row in rows:
        _require(isinstance(row, dict), f"{context} row needs an object")
        name = _text(row.get(key), context)
        _require(name not in result, f"duplicate {context} ID: {name}")
        result[name] = row
    return result


def _pairs(rows: Any, context: str) -> set[tuple[str, str]]:
    _require(isinstance(rows, list), f"{context} needs explicit profile_variants")
    pairs: set[tuple[str, str]] = set()
    for row in rows:
        _require(isinstance(row, dict) and set(row) == {"profile", "variant"},
                 f"{context} needs exact profile/variant pairs")
        pair = (_text(row["profile"], context), _text(row["variant"], context))
        _require(pair not in pairs, f"duplicate {context} profile/variant")
        pairs.add(pair)
    return pairs


def _source_hash(row: dict) -> str:
    return digest({key: row[key] for key in ("kind", "source_id", "anchor", "artifacts")})


def _schema_errors(function):
    @wraps(function)
    def checked(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except ReconciliationError:
            raise
        except (KeyError, TypeError, AttributeError, OverflowError) as exc:
            raise ReconciliationError(f"invalid {function.__name__} declaration structure") from exc
    return checked


@_schema_errors
def collect_source_records(
    executable_surface: dict | None,
    help_surface: dict | None,
    managed_annexes: Iterable[tuple[str, dict]] = (),
    *,
    artifact_pins: Mapping[str, dict] | None = None,
) -> list[dict]:
    """Collect sanitized, stable IDs; never infer workflows or profile rosters.

    Artifact IDs are ``toolkit-executable-surface``, ``toolkit-help-surface`` and
    each explicit managed-annex ID. If raw file pins are omitted, their pins
    describe canonical JSON bytes instead. To verify them, pass those same
    bytes to ``reconcile``. A managed annex may contain ``managed_method_spans``,
    ``native_method_spans``, ``decompiled_source_symbols``,
    ``framework_api_declarations`` and explicit ``managed_controls``. Metadata
    enumeration is not a new event; only explicit event rows become events.
    Duplicate identities refuse even when their content is identical.
    """
    pins = dict(artifact_pins or {})
    records: dict[str, dict] = {}
    parent_pins: dict[str, dict] = {}

    def add(kind: str, source_id: str, anchor: dict, artifact_id: str,
            document: dict, handler_id: str | None = None) -> None:
        _text(source_id, "source identity")
        _safe(anchor, "source anchor")
        for key, value in anchor.items():
            if key.endswith("_sha256"):
                _require(isinstance(value, str) and bool(_SHA.fullmatch(value)), "invalid source anchor digest")
        identity = f"scope:{kind.replace('_', '-')}:{sha256(source_id.encode()).hexdigest()[:20]}"
        # Match the historical form's shorter resource-name digest.
        if kind == "executable_form":
            identity = f"scope:executable-form:{sha256(source_id.encode()).hexdigest()[:16]}"
        _require(identity not in records, f"duplicate source identity: {source_id}")
        if artifact_id not in parent_pins:
            parent_pins[artifact_id] = _pin(pins[artifact_id] if artifact_id in pins
                                            else artifact_pin(canonical_bytes(document)), artifact_id)
        pin = parent_pins[artifact_id]
        row = {"id": identity, "kind": kind, "source_id": source_id, "anchor": anchor,
               "artifacts": [{"id": artifact_id, **pin}], "profile_variants": [],
               "handler_id": handler_id}
        row["source_sha256"] = _source_hash(row)
        records[identity] = row

    if executable_surface is not None:
        doc = executable_surface
        _require(doc.get("schema_version") == 1 and isinstance(doc.get("resources"), list),
                 "unsupported executable surface")
        counts = doc.get("counts", {})
        resources = doc["resources"]
        _require(counts.get("parse_errors") == 0, "executable parse errors remain unresolved")
        for key, count in (("parsed_form_resources", len(resources)),
                           ("components", sum(len(r["components"]) for r in resources)),
                           ("event_bindings", sum(len(r["event_bindings"]) for r in resources))):
            _require(counts.get(key) == count, f"executable {key} count mismatch")
        for resource in resources:
            name = _text(resource["resource_name"], "resource name")
            _require(bool(_SHA.fullmatch(resource["resource_sha256"])), "resource hash invalid")
            add("executable_form", name,
                {"resource_sha256": resource["resource_sha256"],
                 "root_class": resource["root_class"], "root_name": resource["root_name"]},
                "toolkit-executable-surface", doc)
            components = _unique_rows(resource["components"], f"{name} component", "path")
            for path, component in components.items():
                add("executable_control", f"{name}/{path}",
                    {"class": component["class"], "name": component["name"],
                     "resource_sha256": resource["resource_sha256"]},
                    "toolkit-executable-surface", doc)
            for event in resource["event_bindings"]:
                path = event["component_path"]
                _require(path in components, "event refers to an unknown component")
                prop = _text(event["property"], "event property")
                handler = _text(event["handler"], "event handler")
                scalar = (components[path]["class"].casefold() in _SCALAR_COLOR
                          and prop.casefold() == "oncolor")
                source_id = f"{name}/{path}#{prop}" + ("" if scalar else f"={handler}")
                add("executable_property" if scalar else "executable_event", source_id,
                    {"component_class": components[path]["class"], "property": prop,
                     "form_class": resource["root_class"],
                     "value" if scalar else "handler": handler,
                     "resource_sha256": resource["resource_sha256"]},
                    "toolkit-executable-surface", doc)

    if help_surface is not None:
        doc = help_surface
        topics = _unique_rows(doc.get("topics"), "help topic")
        _require(doc.get("counts", {}).get("indexed_topics") == len(topics),
                 "help indexed topic count mismatch")
        for topic_id, topic in topics.items():
            add("topic", topic_id, {"page_sha256": topic["page"]["sha256"]},
                "toolkit-help-surface", doc)
            for ordinal, heading in enumerate(topic["page"].get("headings", [])):
                add("heading", f"{topic_id}#heading-{ordinal}",
                    {"heading_sha256": heading["sha256"]}, "toolkit-help-surface", doc)
            for ordinal, anchor in enumerate(topic["page"].get("anchors", [])):
                add("anchor", f"{topic_id}#anchor-{ordinal}",
                    {"name": anchor["name"], "page_sha256": topic["page"]["sha256"]},
                    "toolkit-help-surface", doc)
        for dialog in doc.get("device_dialog_candidates", []):
            _require(dialog["topic_id"] in topics, "dialog has no current help topic")
            add("dialog", dialog["id"], {"topic_id": dialog["topic_id"],
                "page_sha256": topics[dialog["topic_id"]]["page"]["sha256"]},
                "toolkit-help-surface", doc)
        for topic_id in doc.get("macro_reference", {}).get("leaf_topic_ids", []):
            _require(topic_id in topics, "macro has no current help topic")
            add("macro_leaf", topic_id, {"page_sha256": topics[topic_id]["page"]["sha256"]},
                "toolkit-help-surface", doc)
        for row in doc.get("unindexed_html", []):
            add("unindexed_html", row["id"], {"page_sha256": row["sha256"]},
                "toolkit-help-surface", doc)
        for command in doc.get("public_commands", []):
            add("public_command", command["id"],
                {"syntax_sha256": command["source"]["syntax_sha256"]},
                "toolkit-help-surface", doc)

    annex_ids: set[str] = set()
    for artifact_id, doc in managed_annexes:
        _text(artifact_id, "managed artifact ID")
        _require(artifact_id not in annex_ids, "duplicate managed annex ID")
        annex_ids.add(artifact_id)
        for key, kind in (("managed_method_spans", "managed_method"),
                          ("native_method_spans", "native_method")):
            for span in doc.get(key, []):
                assembly = span.get("assembly", span.get("module", "toolkit-executable"))
                add(kind, f"{assembly}:{span['symbol']}",
                    {"assembly": assembly, "symbol": span["symbol"],
                     "body_sha256": span.get("body_sha256", span.get("sha256"))}, artifact_id, doc)
        for row in doc.get("decompiled_source_symbols", []):
            add("managed_declaration", f"{row['path']}:{row['symbol']}",
                {"declaration_sha256": row["sha256"]}, artifact_id, doc)
        for row in doc.get("framework_api_declarations", []):
            add("managed_api", f"{row['path']}:{row['member']}",
                {"declaration_sha256": row["sha256"]}, artifact_id, doc)
        for row in doc.get("managed_controls", []):
            control_id = f"{row['owner']}/{row['path']}"
            add("managed_control", control_id, {"class": row["class"]}, artifact_id, doc)
            for event in row.get("events", []):
                add("managed_event", f"{control_id}#{event['event']}={event['handler']}",
                    {"event": event["event"], "handler": event["handler"], "owner": row["owner"]}, artifact_id, doc,
                    handler_id=event.get("handler_id"))
    return [records[key] for key in sorted(records)]


@dataclass(frozen=True)
class _GateIssuance:
    authority: object
    payload_sha256: str


def _gate_payload_sha256(gate: VerifiedGate) -> str:
    return digest({"gate_id": gate.gate_id, "kind": gate.kind,
                   "case_ids": gate.case_ids, "artifact_pins": gate.artifact_pins,
                   "source_snapshot_sha256": gate.source_snapshot_sha256})


@dataclass(frozen=True)
class VerifiedGate:
    """Retained-gate verification with an owner-issued exact content seal.

    Copying the dataclass does not permit changing the verified kind, cases,
    artifacts or source snapshot. This is internal Python provenance, not an
    authenticity attestation for externally supplied original/hardware data.
    """

    gate_id: str
    kind: str
    case_ids: tuple[str, ...]
    artifact_pins: tuple[tuple[str, str, int], ...]
    source_snapshot_sha256: str
    _issuer: object


@_schema_errors
def verify_gate_receipt(
    *, gate_id: str, receipt_raw: bytes, manifest_raw: bytes, trace_raw: bytes,
    junit_raw: bytes, artifact_ids: Mapping[str, str], current_artifacts: Mapping[str, dict],
    current_source_files: Mapping[str, bytes], current_provision: list[dict],
) -> VerifiedGate:
    """Verify retained native/hardware gate artifacts without running any code.

    Current source bytes and independently recomputed provision metadata are
    explicit caller inputs. The manifest must have actual provisioning rules;
    receipt ``passed`` alone is insufficient. This does not attest the physical
    effect or authenticity of supplied observations beyond their retained pins.
    """
    _text(gate_id, "gate ID")
    _require(set(artifact_ids) == {"receipt", "manifest", "trace", "junit"},
             "gate needs all four artifact IDs")
    raw = {"receipt": receipt_raw, "manifest": manifest_raw,
           "trace": trace_raw, "junit": junit_raw}
    refs = []
    for role, content in raw.items():
        name = _text(artifact_ids[role], "gate artifact ID")
        expected = current_artifacts.get(name)
        _require(expected == artifact_pin(content), f"gate {role} artifact is not current")
        refs.append((name, expected["sha256"], expected["bytes"]))
    receipt, manifest, trace = (parse_json(raw[k]) for k in ("receipt", "manifest", "trace"))
    kind = receipt.get("gate")
    _require(kind in {"native", "hardware"} and manifest.get("gate") == kind,
             "gate kind must match native/hardware manifest")
    _require(receipt.get("format") == manifest.get("format") == "cbus-provisioned-release-gate-v1",
             "unsupported retained gate format")
    _require(receipt.get("passed") is True and receipt.get("pytest_exit") == 0,
             "gate did not pass")
    rules = manifest.get("required_environment")
    _require(isinstance(rules, dict) and bool(rules), "gate has no provisioning rules")
    _require(current_provision == receipt.get("verified_provision"), "gate provision is stale")
    provision = _unique_rows(current_provision, "gate provision", "name")
    _require(set(provision) == set(rules), "gate provision roster mismatch")
    for name, rule in rules.items():
        entry = provision[name]
        _require(entry.get("present") is True and entry.get("kind") == rule.get("kind"),
                 "gate provision absent or wrong kind")
        if rule.get("sha256") is not None:
            _require(entry.get("sha256") == rule["sha256"] and entry.get("pinned") is True,
                     "gate original provision digest mismatch")
        if rule.get("kind") in {"file", "directory", "executable"}:
            _require(bool(_SHA.fullmatch(entry.get("sha256", "")))
                     and type(entry.get("bytes")) is int and entry["bytes"] > 0,
                     "gate file provision has no content pin")
    if kind == "hardware":
        _require(rules.get("CBUS_HARDWARE_ACCEPTANCE", {}).get("kind") == "flag",
                 "hardware gate lacks explicit hardware provision")
    else:
        _require(any(rule.get("kind") in {"file", "directory", "executable"}
                     for rule in rules.values()), "native gate lacks original file provision")
    _require(receipt.get("manifest_sha256") == sha256(manifest_raw).hexdigest()
             and receipt.get("trace_sha256") == sha256(trace_raw).hexdigest()
             and receipt.get("junit_sha256") == sha256(junit_raw).hexdigest(),
             "gate artifact binding mismatch")
    selections = manifest.get("tests")
    _require(isinstance(selections, list) and selections and len(selections) == len(set(selections)),
             "gate selection is empty or duplicated")
    for item in selections:
        _text(item, "gate selected case")
    _require(receipt.get("selection_sha256") == sha256(json.dumps(selections, separators=(",", ":")).encode()).hexdigest()
             and receipt.get("selected_test_count") == len(selections), "gate selection binding mismatch")
    _require(trace.get("format") == "cbus-release-gate-pytest-trace-v1"
             and trace.get("session_exitstatus") == 0 and trace.get("deselected") == [],
             "gate trace is incomplete")
    collected, executed = trace.get("collected"), trace.get("executed")
    _require(isinstance(collected, list) and collected and len(collected) == len(set(collected))
             and isinstance(executed, list) and Counter(executed) == Counter(collected),
             "gate cases did not execute exactly once")
    def selected(node: str, selector: str) -> bool:
        return node == selector or node.startswith(selector + "::") or node.startswith(selector + "[")
    _require(all(any(selected(node, s) for s in selections) for node in collected)
             and all(any(selected(node, s) for node in collected) for s in selections),
             "gate collected selection mismatch")
    try:
        xml = ET.fromstring(junit_raw)
        suites = [xml] if xml.tag == "testsuite" else list(xml.findall("testsuite"))
        counts = {k: sum(int(s.attrib.get(k, 0)) for s in suites)
                  for k in ("tests", "failures", "errors", "skipped")}
        cases = list(xml.iter("testcase"))
    except (ET.ParseError, ValueError, TypeError) as exc:
        raise ReconciliationError("invalid gate JUnit") from exc
    _require(xml.tag in {"testsuite", "testsuites"} and suites and cases
             and counts["failures"] == counts["errors"] == counts["skipped"] == 0,
             "gate JUnit failed or skipped")
    nodeids = []
    for case in cases:
        _require(not any(case.find(k) is not None for k in ("failure", "error", "skipped")),
                 "gate JUnit case failed or skipped")
        ids = [p.attrib.get("value") for p in case.findall("properties/property")
               if p.attrib.get("name") == "cbus_release_gate_nodeid"]
        _require(len(ids) == 1 and isinstance(ids[0], str), "gate JUnit lacks exact case IDs")
        nodeids.extend(ids)
    _require(Counter(nodeids) == Counter(collected), "gate JUnit/trace case mismatch")
    subtests = trace.get("subtests", {"passed": 0, "failed": 0, "skipped": 0})
    _require(isinstance(subtests, dict) and set(subtests) == {"passed", "failed", "skipped"}
             and all(type(n) is int and n >= 0 for n in subtests.values())
             and subtests["failed"] == subtests["skipped"] == 0
             and counts["tests"] == len(cases) + subtests["passed"], "gate subtest mismatch")
    result = {**counts, "passed": counts["tests"]}
    if subtests["passed"]:
        result["unitemized_subtests"] = {"reported": subtests["passed"], "passed": subtests["passed"],
                                        "failures": 0, "errors": 0, "skipped": 0}
    execution = {"collected": len(collected), "executed": len(executed), "deselected": 0}
    if subtests["passed"]:
        execution["subtests"] = subtests
    _require(receipt.get("result") == result and receipt.get("execution") == execution,
             "gate aggregate counters mismatch")
    _require(bool(current_source_files), "current gate source snapshot is empty")
    source_rows = []
    for name, content in sorted(current_source_files.items()):
        _text(name, "gate source ID")
        _require(not name.startswith("/") and ".." not in name.split("/"), "unsafe gate source ID")
        source_rows.append((name, len(content), sha256(content).hexdigest()))
    snapshot = {"sha256": sha256(json.dumps(source_rows, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest(),
                "files": len(source_rows), "bytes": sum(row[1] for row in source_rows)}
    _require(receipt.get("source_inputs") == snapshot, "gate source snapshot is stale")
    gate = VerifiedGate(gate_id, kind, tuple(sorted(collected)), tuple(sorted(refs)), snapshot["sha256"], None)
    return VerifiedGate(gate.gate_id, gate.kind, gate.case_ids, gate.artifact_pins,
                        gate.source_snapshot_sha256, _GateIssuance(_ISSUER, _gate_payload_sha256(gate)))


def parse_json(raw: bytes | str) -> dict:
    """Reject duplicate object keys, nonfinite numbers and nonobject roots."""
    def pairs(values: list[tuple[str, Any]]) -> dict:
        out: dict = {}
        for key, value in values:
            _require(key not in out, f"duplicate JSON key: {key}")
            out[key] = value
        return out
    def constant(_: str) -> None:
        raise ReconciliationError("nonfinite JSON number")
    try:
        out = json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, UnicodeError) as exc:
        if isinstance(exc, ReconciliationError):
            raise
        raise ReconciliationError("invalid reconciliation JSON") from exc
    _require(isinstance(out, dict), "reconciliation document must be an object")
    return out


def reconcile_bundle_file(bundle_path: Path, *, artifact_root: Path | None = None) -> dict:
    """Read one explicit bundle and optional contained artifacts, then reconcile.

    Artifact IDs are relative files, with no parent traversal, absolute paths or
    links escaping the explicit root. Bytes are read once and pinned before JSON
    parsing. The report contains pins and source identities, never local paths.
    This entry point intentionally cannot issue original/hardware gate tokens.
    """
    try:
        raw = bundle_path.read_bytes()
        bundle = parse_json(raw)
        payloads = None
        if artifact_root is not None:
            root = artifact_root.resolve(strict=True)
            _require(root.is_dir(), "reconciliation artifact root must be a directory")
            payloads = {}
            current = bundle.get("current_artifacts")
            _require(isinstance(current, dict), "current_artifacts needs an object")
            for name in current:
                _text(name, "artifact ID")
                path = Path(name)
                _require(not path.is_absolute() and ".." not in path.parts,
                         "artifact ID must be a contained relative file")
                candidate = (root / path).resolve(strict=True)
                _require(candidate.is_relative_to(root) and candidate.is_file(),
                         "artifact ID escapes the trusted artifact root")
                content = candidate.read_bytes()
                _require((root / path).resolve(strict=True) == candidate,
                         "artifact link changed while reading")
                payloads[name] = content
        report = reconcile(bundle, artifact_bytes=payloads)
        report["bundle_artifact"] = artifact_pin(raw)
        return report
    except OSError as exc:
        raise ReconciliationError("reconciliation artifact read failed") from exc


@_schema_errors
def reconcile(bundle: dict, *, artifact_bytes: Mapping[str, bytes] | None = None,
              verified_gates: Iterable[VerifiedGate] = ()) -> dict:
    """Join exact current source/profile mappings and evidence; return no globals.

    Without artifact bytes, pins remain declarations and completeness is false.
    No supplied JSON can issue a VerifiedGate. Gate tokens must still match this
    bundle's current artifact pins. A skipped required gate stays unsatisfied.
    """
    _require(isinstance(bundle, dict) and set(bundle) == {"format", "source_inventory_complete",
             "sources", "obligations", "bindings", "receipts", "current_artifacts"},
             "bundle needs exact v1 fields")
    _require(bundle["format"] == BUNDLE_FORMAT and type(bundle["source_inventory_complete"]) is bool,
             "unsupported reconciliation bundle")
    _safe(bundle, "bundle")
    current = bundle["current_artifacts"]
    _require(isinstance(current, dict), "current_artifacts needs an object")
    for name, pin in current.items():
        _text(name, "current artifact ID"); _pin(pin, name)
    payloads = dict(artifact_bytes or {})
    _require(all(isinstance(v, bytes) for v in payloads.values()), "artifact payload must be bytes")
    verified = {name for name, raw in payloads.items() if current.get(name) == artifact_pin(raw)}
    gate_map: dict[str, VerifiedGate] = {}
    for gate in verified_gates:
        _require(isinstance(gate, VerifiedGate) and isinstance(gate._issuer, _GateIssuance)
                 and gate._issuer.authority is _ISSUER
                 and gate._issuer.payload_sha256 == _gate_payload_sha256(gate),
                 "gate must be issued by retained-artifact verification")
        _require(gate.gate_id not in gate_map, "duplicate verified gate ID")
        gate_map[gate.gate_id] = gate
    sources = _unique_rows(bundle["sources"], "source")
    obligations = _unique_rows(bundle["obligations"], "obligation")
    bindings = _unique_rows(bundle["bindings"], "binding")
    receipts = _unique_rows(bundle["receipts"], "receipt")
    issues: list[dict] = []; issue_keys: set[tuple] = set()
    def issue(code: str, *, source: str | None = None, binding: str | None = None,
              obligation: str | None = None, receipt: str | None = None, artifact: str | None = None) -> None:
        row = {"code": code}
        for key, value in (("source_id", source), ("binding_id", binding),
                           ("obligation_id", obligation), ("receipt_id", receipt), ("artifact_id", artifact)):
            if value is not None:
                row[key] = value
        key = tuple(sorted(row.items()))
        if key not in issue_keys:
            issue_keys.add(key)
            issues.append(row)
    # Prove each source anchor is actually a member of its supplied inventory.
    # A file hash alone cannot turn an arbitrary file or invented source row into
    # a control/method/workflow surface. Cache this once per parent artifact.
    members: dict[str, dict[str, dict] | None] = {}
    for name in verified:
        try:
            doc = parse_json(payloads[name])
            if name == "toolkit-executable-surface":
                rows = collect_source_records(doc, None, artifact_pins={name: current[name]})
            elif name == "toolkit-help-surface":
                rows = collect_source_records(None, doc, artifact_pins={name: current[name]})
            elif any(key in doc for key in ("managed_method_spans", "native_method_spans", "decompiled_source_symbols",
                                           "framework_api_declarations", "managed_controls")):
                rows = collect_source_records(None, None, [(name, doc)], artifact_pins={name: current[name]})
            else:
                members[name] = None
                continue
            members[name] = {row["id"]: row for row in rows}
        except (ReconciliationError, KeyError, TypeError):
            members[name] = None
    discovered: dict[str, dict] = {}; duplicate_members: set[str] = set()
    inventory_report = []
    for name, rows in sorted(members.items()):
        if rows is None:
            continue  # Receipt/gate files are not source inventories.
        omitted = []
        for sid, row in sorted(rows.items()):
            if sid in discovered:
                duplicate_members.add(sid)
                issue("inventory_duplicate_source_identity", source=sid, artifact=name)
            discovered[sid] = row
            if sid not in sources:
                omitted.append({key: row[key] for key in ("id", "source_id", "kind", "source_sha256")})
                issue("inventory_source_omitted", source=sid, artifact=name)
        inventory_report.append({"artifact_id": name, "discovered_source_records": len(rows),
                                 "omitted_sources": omitted})
    omitted_members = set(discovered) - set(sources)
    source_pairs: dict[str, set] = {}; source_valid: dict[str, bool] = {}; source_fresh: dict[str, bool] = {}
    for sid, source in sources.items():
        _require(set(source) == {"id", "kind", "source_id", "anchor", "artifacts",
                 "profile_variants", "handler_id", "source_sha256"}, "source needs exact fields")
        _require(source["kind"] in _SOURCE_KINDS, "unknown source kind")
        _text(source["source_id"], "source identity")
        _require(isinstance(source["anchor"], dict) and set(source["anchor"]) <= _ANCHORS
                 and isinstance(source["source_sha256"], str) and bool(_SHA.fullmatch(source["source_sha256"])),
                 "invalid source anchor or hash")
        refs = source["artifacts"]
        _require(isinstance(refs, list) and len(refs) == 1, "source needs one exact parent inventory artifact")
        names = set()
        valid = source["source_sha256"] == _source_hash(source)
        if not valid:
            issue("source_record_hash_mismatch", source=sid)
        for ref in refs:
            _require(isinstance(ref, dict) and set(ref) == {"id", "sha256", "bytes"}, "invalid source artifact")
            name = _text(ref["id"], "source artifact ID")
            _require(name not in names, "duplicate source artifact")
            names.add(name)
            pin = _pin({k: ref[k] for k in ("sha256", "bytes")}, name)
            if current.get(name) != pin:
                valid = False; issue("source_artifact_stale", source=sid)
            elif name not in verified:
                valid = False; issue("source_artifact_unverified", source=sid)
            elif (members.get(name) is None or sid not in members[name]
                  or members[name][sid]["source_sha256"] != source["source_sha256"]):
                valid = False; issue("source_not_in_current_inventory", source=sid)
        source_fresh[sid] = valid
        pairs = _pairs(source["profile_variants"], sid)
        source_pairs[sid] = pairs
        if not pairs:
            valid = False; issue("source_profile_roster_missing", source=sid)
        handler_id = source["handler_id"]
        _require(handler_id is None or isinstance(handler_id, str), "handler ID must be a string or null")
        if source["kind"] in {"executable_event", "managed_event"}:
            if (handler_id not in sources or sources[handler_id]["kind"] not in {"managed_method", "native_method"}):
                valid = False; issue("event_handler_unresolved", source=sid)
            else:
                anchor = source["anchor"]
                symbol = sources[handler_id]["anchor"].get("symbol")
                handler = anchor["handler"]
                owner = anchor.get("form_class", anchor.get("owner"))
                if symbol not in {handler, f"{owner}::{handler}", f"{owner}.{handler}"}:
                    valid = False; issue("event_handler_identity_mismatch", source=sid)
        elif handler_id is not None:
            raise ReconciliationError("non-event source must not declare a handler")
        source_valid[sid] = valid
    profile_map: dict[tuple[str, str, str], list[str]] = {}
    definition_valid: dict[str, bool] = {}
    for oid, obligation in obligations.items():
        _require(set(obligation) == {"id", "definition_status", "implementation_status",
                 "implementation_basis", "profiles"}, "obligation needs exact fields")
        _require(obligation["definition_status"] in {"defined", "provisional"}
                 and obligation["implementation_status"] in {"implemented", "in_progress", "pending"}
                 and obligation["implementation_basis"] in {"typed_workflow", "generic_forwarding", "test_filename", "unresolved"},
                 "invalid obligation status")
        profiles = _unique_rows(obligation["profiles"], f"{oid} profile")
        valid = obligation["definition_status"] == "defined" and bool(profiles)
        if not valid:
            issue("obligation_definition_unresolved", obligation=oid)
        for pid, profile in profiles.items():
            _require(set(profile) == {"id", "variants", "required_dimensions"}, "profile needs exact fields")
            variants, dimensions = profile["variants"], profile["required_dimensions"]
            _require(isinstance(variants, list) and variants and len(variants) == len(set(variants))
                     and isinstance(dimensions, list) and dimensions and len(dimensions) == len(set(dimensions))
                     and set(dimensions) <= _DIMENSIONS, "profile needs unique variants and required dimensions")
            for variant in variants:
                _text(variant, "variant")
                profile_map[(oid, pid, variant)] = sorted(dimensions)
        definition_valid[oid] = valid
    joined: dict[tuple[str, str, str], list[str]] = {}
    mapped_pairs: dict[str, set] = {sid: set() for sid in sources}
    binding_valid: dict[str, bool] = {}; nonfunctional: list[dict] = []
    seen_bindings = set(); dispositions_by_pair: dict[tuple, set] = {}
    for bid, binding in bindings.items():
        _require(set(binding) == {"id", "source_id", "source_sha256", "obligation_id",
                 "profile", "variant", "disposition"}, "binding needs exact fields")
        sid, oid = binding["source_id"], binding["obligation_id"]
        _text(sid, "binding source ID")
        _require(oid is None or isinstance(oid, str), "binding obligation ID must be a string or null")
        _require(isinstance(binding["source_sha256"], str) and bool(_SHA.fullmatch(binding["source_sha256"])),
                 "binding needs a source digest")
        profile, variant = _text(binding["profile"], "binding profile"), _text(binding["variant"], "binding variant")
        _require(binding["disposition"] in {"workflow", "nonfunctional", "unresolved"}, "invalid binding disposition")
        identity = (sid, oid, profile, variant, binding["disposition"])
        _require(identity not in seen_bindings, "duplicate source/obligation/profile/variant binding")
        seen_bindings.add(identity)
        pair_key = (sid, profile, variant)
        disposition_set = dispositions_by_pair.setdefault(pair_key, set())
        disposition_set.add(binding["disposition"])
        _require(not ("nonfunctional" in disposition_set and len(disposition_set) > 1),
                 "conflicting functional/nonfunctional disposition")
        valid = sid in sources
        if not valid:
            issue("binding_source_unknown", binding=bid)
        elif binding["source_sha256"] != sources[sid]["source_sha256"]:
            valid = False; issue("binding_source_stale", source=sid, binding=bid)
        if valid and (profile, variant) not in source_pairs[sid]:
            valid = False; issue("binding_source_variant_undeclared", source=sid, binding=bid)
        if binding["disposition"] == "workflow":
            if (oid, profile, variant) not in profile_map:
                valid = False; issue("binding_obligation_variant_unknown", binding=bid)
            elif not definition_valid[oid]:
                valid = False; issue("binding_obligation_provisional", binding=bid, obligation=oid)
            if valid:
                joined.setdefault((oid, profile, variant), []).append(sid)
        elif binding["disposition"] == "nonfunctional":
            _require(oid is None, "nonfunctional binding must not name an obligation")
            if valid:
                nonfunctional.append(binding)
        else:
            valid = False; issue("binding_explicitly_unresolved", binding=bid)
        binding_valid[bid] = valid
        if valid:
            mapped_pairs[sid].add((profile, variant))
    for sid in sources:
        if source_pairs[sid] - mapped_pairs[sid]:
            issue("source_variants_unmapped", source=sid)
    observations: list[tuple[str, dict, bool]] = []
    receipt_report = []
    for rid, receipt in receipts.items():
        _require(set(receipt) == {"format", "id", "artifact", "source_pins", "execution_kind",
                 "result", "case_ids", "observations", "gate_id"}
                 and receipt["format"] == EVIDENCE_FORMAT, "receipt needs exact evidence fields")
        kind = receipt["execution_kind"]
        _require(kind in _KINDS and receipt["result"] in _RESULTS, "invalid receipt kind/result")
        ref = receipt["artifact"]
        _require(isinstance(ref, dict) and set(ref) == {"id", "sha256", "bytes"}, "invalid receipt artifact")
        name = _text(ref["id"], "receipt artifact ID")
        pin = _pin({k: ref[k] for k in ("sha256", "bytes")}, name)
        valid = current.get(name) == pin and name in verified
        if not valid:
            issue("receipt_artifact_stale_or_unverified", receipt=rid)
        elif parse_json(payloads[name]) != {k: v for k, v in receipt.items() if k != "artifact"}:
            valid = False; issue("receipt_document_mismatch", receipt=rid)
        source_pins = receipt["source_pins"]
        _require(isinstance(source_pins, dict) and source_pins, "receipt needs exact source pins")
        for sid, source_hash in source_pins.items():
            if sid not in sources or source_hash != sources[sid]["source_sha256"] or not source_valid[sid]:
                valid = False; issue("receipt_source_stale_or_unresolved", receipt=rid)
        cases = receipt["case_ids"]
        _require(isinstance(cases, list) and len(cases) == len(set(cases)), "duplicate receipt case ID")
        for case in cases:
            _text(case, "receipt case ID")
        if not cases or kind in {"declarative", "generic_forwarding", "test_inventory"}:
            valid = False; issue("receipt_has_no_workflow_execution", receipt=rid)
        gate = gate_map.get(receipt["gate_id"])
        if kind in {"original", "hardware"}:
            expected = "native" if kind == "original" else "hardware"
            gate_current = (gate is not None and gate.kind == expected
                            and all(current.get(n) == {"sha256": h, "bytes": b}
                                    and n in verified for n, h, b in gate.artifact_pins)
                            and set(cases) <= set(gate.case_ids))
            if not gate_current:
                valid = False; issue("required_gate_provenance_unverified", receipt=rid)
        else:
            _require(receipt["gate_id"] is None, "modeled/static receipt cannot claim a release gate")
        seen_observations = set()
        _require(isinstance(receipt["observations"], list), "receipt observations need a list")
        for obs in receipt["observations"]:
            _require(isinstance(obs, dict) and set(obs) == {"obligation_id", "profile", "variant",
                     "dimension", "result", "case_id", "source_ids"}, "observation needs exact fields")
            _require(obs["dimension"] in _DIMENSIONS and obs["result"] in _RESULTS
                     and obs["case_id"] in cases, "invalid observation dimension/result/case")
            ids = obs["source_ids"]
            _require(isinstance(ids, list) and ids and len(ids) == len(set(ids))
                     and set(ids) <= set(source_pins), "observation needs unique pinned sources")
            identity = (obs["obligation_id"], obs["profile"], obs["variant"], obs["dimension"], obs["case_id"], tuple(sorted(ids)))
            _require(identity not in seen_observations, "duplicate receipt observation")
            seen_observations.add(identity)
            eligible = valid and receipt["result"] == obs["result"] == "passed"
            if (obs["obligation_id"] is not None and
                    (obs["obligation_id"], obs["profile"], obs["variant"]) not in profile_map):
                eligible = False; issue("observation_obligation_variant_unknown", receipt=rid)
            if obs["dimension"] == "original_differential" and kind != "original":
                eligible = False; issue("observation_execution_kind_ineligible", receipt=rid)
            if obs["dimension"] == "physical" and kind != "hardware":
                eligible = False; issue("observation_execution_kind_ineligible", receipt=rid)
            if kind == "static" and obs["dimension"] not in {"static_analysis", "scope_disposition"}:
                eligible = False; issue("observation_execution_kind_ineligible", receipt=rid)
            observations.append((rid, obs, eligible))
        receipt_report.append({"id": rid, "execution_kind": kind, "recorded_result": receipt["result"],
                               "current_and_eligible_provenance": valid,
                               "case_count": len(cases), "observation_count": len(receipt["observations"])})
    def evidence(oid: str | None, profile: str, variant: str, dimension: str, sid: str) -> list[str]:
        return sorted({rid for rid, obs, eligible in observations if eligible
                       and (obs["obligation_id"], obs["profile"], obs["variant"], obs["dimension"])
                       == (oid, profile, variant, dimension) and sid in obs["source_ids"]})
    nonfunctional_ok: dict[str, bool] = {}
    for binding in nonfunctional:
        ok = bool(evidence(None, binding["profile"], binding["variant"], "scope_disposition", binding["source_id"]))
        nonfunctional_ok[binding["id"]] = ok
        if not ok:
            issue("nonfunctional_disposition_unproved", source=binding["source_id"], binding=binding["id"])
    gates = []
    for (oid, profile, variant), dimensions in sorted(profile_map.items()):
        required_sources = sorted(set(joined.get((oid, profile, variant), [])))
        for dimension in dimensions:
            links = {sid: evidence(oid, profile, variant, dimension, sid) for sid in required_sources}
            satisfied = bool(required_sources) and all(links.values())
            if not satisfied:
                issue("required_variant_dimension_unsatisfied", obligation=oid)
            gates.append({"obligation_id": oid, "profile": profile, "variant": variant,
                          "dimension": dimension, "required_source_ids": required_sources,
                          "evidence_by_source": links, "satisfied": satisfied})
    source_report = []
    for sid, source in sorted(sources.items()):
        mapped = source_valid[sid] and bool(source_pairs[sid]) and source_pairs[sid] <= mapped_pairs[sid]
        dispositions = [b for b in nonfunctional if b["source_id"] == sid]
        if dispositions and not all(nonfunctional_ok[b["id"]] for b in dispositions):
            mapped = False
        source_report.append({"id": sid, "source_id": source["source_id"], "kind": source["kind"],
                              "source_sha256": source["source_sha256"], "source_current": source_fresh[sid],
                              "profile_variants": sorted(source_pairs[sid]), "mapping_resolved": mapped})
    denominator_ready = (bundle["source_inventory_complete"] and bool(sources) and bool(obligations)
                         and all(s["mapping_resolved"] for s in source_report)
                         and all(definition_valid.values()) and all(binding_valid.values())
                         and all(joined.get(k) for k in profile_map)
                         and not omitted_members and not duplicate_members)
    implementation_ready = all(o["implementation_status"] == "implemented"
                               and o["implementation_basis"] == "typed_workflow" for o in obligations.values())
    for oid, obligation in obligations.items():
        if obligation["implementation_basis"] != "typed_workflow":
            issue("workflow_implementation_basis_unproved", obligation=oid)
        elif obligation["implementation_status"] != "implemented":
            issue("workflow_implementation_incomplete", obligation=oid)
    if not bundle["source_inventory_complete"]:
        issue("declared_source_inventory_incomplete")
    complete = bool(denominator_ready and implementation_ready and gates
                    and all(g["satisfied"] for g in gates) and all(nonfunctional_ok.values())
                    and not issues)
    return {"format": REPORT_FORMAT, "scope": SCOPE,
            "full_toolkit_parity": False, "census_completeness_verified": False,
            "complete_for_declared_surface": complete, "denominator_ready": bool(denominator_ready),
            "input_sha256": digest(bundle), "counts": {
                "source_records": len(sources), "source_profiles": sum(map(len, source_pairs.values())),
                "discovered_source_records": len(discovered), "omitted_source_records": len(omitted_members),
                "source_kinds": dict(sorted(Counter(s["kind"] for s in sources.values()).items())),
                "mapping_resolved_sources": sum(s["mapping_resolved"] for s in source_report),
                "obligations": len(obligations), "obligation_profile_variants": len(profile_map),
                "required_variant_gates": len(gates), "satisfied_variant_gates": sum(g["satisfied"] for g in gates),
                "receipt_records": len(receipts), "verified_artifacts": len(verified)},
            "sources": source_report, "variant_gates": gates,
            "inventory_membership": inventory_report,
            "receipts": sorted(receipt_report, key=lambda r: r["id"]),
            "unresolved": sorted(issues, key=canonical_bytes),
            "limits": ["Supplied inventories do not establish undocumented original completeness.",
                       "Retained gate verification is artifact verification, not new original or hardware execution.",
                       "Test filenames and generic command forwarding are not workflow evidence."]}
