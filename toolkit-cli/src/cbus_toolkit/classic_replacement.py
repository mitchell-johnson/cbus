"""Staged classic database-unit replacement with recoverable XML promotion.

C-Gate owns the project database. A source unit is not replaced until a copied
staging unit has passed parameter and metadata checks. No physical network is
opened or programmed. Learned-flag policy is a required, explicit input.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from typing import Any
from uuid import UUID, uuid4
from xml.dom import Node, minidom
from xml.parsers import expat

from .cgate import CGateError
from .native import NativeDatabase, NativeProjects, _project, _tail, _token
from .offline_conversion import OfflineConversion
from .programming import Programmer, xml_text
from .unitspec import UnitSpec, version_matches


class ReplacementError(RuntimeError):
    def __init__(self, message, *, backup_project=None, rollback_errors=(), staging_path=None):
        self.details = {"backup_project": backup_project, "rollback_errors": list(rollback_errors),
                        "staging_path": staging_path}
        super().__init__(message)


@dataclass(frozen=True)
class LearnedHistory:
    current: bool
    original: bool

    def __post_init__(self):
        if type(self.current) is not bool or type(self.original) is not bool:
            raise ValueError("Learned history current/original must be booleans")

    def as_dict(self):
        return {"current": self.current, "original": self.original}


def learned_flag(policy, source, target_default, history=None):
    """Exact classic frontend branch, or an explicitly selected alternative.

    BeforeUnitConversionSave copies the aligned attribute only if the target
    current learned state is false and its original learned state was true.
    Supported classic specs all start at learning-capable firmware 1.2.63.
    """
    if source not in (0, 1) or target_default not in (0, 1):
        raise ValueError("LearnedFlag must be 0 or 1")
    if policy == "frontend":
        if not isinstance(history, LearnedHistory):
            raise ValueError("Frontend learned policy requires explicit current/original LearnedHistory")
        return source if not history.current and history.original else target_default
    if history is not None:
        raise ValueError("LearnedHistory is only valid with frontend policy")
    if policy == "preserve_source": return source
    if policy == "target_default": return target_default
    raise ValueError("learned_policy must be frontend, preserve_source or target_default")


def _path(value):
    match = re.fullmatch(r"//([A-Za-z0-9_]{1,8})/([0-9]{1,3})/p/([0-9]{1,3})", str(value))
    if not match or int(match[2]) > 255 or int(match[3]) > 255:
        raise ValueError("Use a database unit path such as //PROJECT/254/p/20")
    project, network, unit = match.groups()
    return f"//{project}/{int(network)}/p/{int(unit)}", project, int(network), int(unit)


def _document(text):
    if not isinstance(text, str) or len(text.encode("utf-8")) > 8 * 1024 * 1024:
        raise ValueError("Unit XML is not text or exceeds 8 MiB")
    checker = expat.ParserCreate()
    def reject(*_args): raise ValueError("XML declarations with DTD/entities are unsupported")
    checker.StartDoctypeDeclHandler = reject
    checker.Parse(text, True)
    result = minidom.parseString(text)
    if result.documentElement.tagName != "Unit":
        raise ValueError("Expected one native Unit XML element")
    return result


def _children(node, name):
    return [c for c in node.childNodes if c.nodeType == Node.ELEMENT_NODE and c.tagName == name]


def _field(document, name):
    nodes = _children(document.documentElement, name)
    if len(nodes) > 1: raise ValueError("Duplicate native unit field: " + name)
    return "".join(c.data for c in nodes[0].childNodes if c.nodeType in (Node.TEXT_NODE, Node.CDATA_SECTION_NODE)) if nodes else ""


def _set(document, name, value):
    nodes = _children(document.documentElement, name)
    if len(nodes) > 1: raise ValueError("Duplicate native unit field: " + name)
    node = nodes[0] if nodes else document.createElement(name)
    if not nodes: document.documentElement.appendChild(node)
    for child in list(node.childNodes): node.removeChild(child)
    node.appendChild(document.createTextNode(str(value)))


def _shape(node):
    if node.nodeType == Node.ELEMENT_NODE:
        attrs = tuple(sorted((node.attributes.item(i).name, node.attributes.item(i).value)
                             for i in range(node.attributes.length)))
        children = tuple(_shape(c) for c in node.childNodes if not (c.nodeType == Node.TEXT_NODE and not c.data.strip()))
        return ("element", node.tagName, attrs, children)
    if node.nodeType in (Node.TEXT_NODE, Node.CDATA_SECTION_NODE): return ("text", node.data)
    if node.nodeType == Node.COMMENT_NODE: return ("comment", node.data)
    if node.nodeType == Node.PROCESSING_INSTRUCTION_NODE: return ("instruction", node.target, node.data)
    raise ValueError("Unsupported XML node in native unit")


def _canonical(text, exclude=()):
    root = _document(text).documentElement
    fields = [_shape(c) for c in root.childNodes
              if not (c.nodeType == Node.TEXT_NODE and not c.data.strip())
              and not (c.nodeType == Node.ELEMENT_NODE and c.tagName in exclude)]
    # Native fields/PP entries have unordered storage; nested opaque XML retains
    # its child ordering, attributes, namespace prefixes and text.
    attrs = tuple(sorted((root.attributes.item(i).name, root.attributes.item(i).value) for i in range(root.attributes.length)))
    return (root.tagName, attrs, tuple(sorted(fields, key=repr)))


def _digest(text):
    return hashlib.sha256(repr(_canonical(text)).encode("utf-8")).hexdigest()


_METADATA_CHANGED = ("OID", "Address", "TagName", "UnitType", "FirmwareVersion", "CatalogNumber", "SerialNumber", "PP")


@dataclass(frozen=True)
class ReplacementPlan:
    source: str
    source_xml: str
    source_hash: str
    source_parameters: tuple[tuple[str, str], ...]
    target_type: str
    target_firmware: str
    target_catalog: str
    target_serial: str
    learned_policy: str
    learned_history: LearnedHistory | None
    learned_value: int
    parameters: tuple[tuple[str, Any], ...]
    alignment: Any

    def as_dict(self):
        return {"format": "cbus-classic-replacement-plan-v1", "source": self.source,
                "source_hash": self.source_hash, "target_type": self.target_type,
                "target_firmware": self.target_firmware, "target_catalog": self.target_catalog,
                "target_serial": self.target_serial, "learned_policy": self.learned_policy,
                "learned_history": self.learned_history.as_dict() if self.learned_history else None,
                "learned_value": self.learned_value, "alignment": self.alignment.as_dict(),
                "source_address_retained": True, "source_metadata_retained": True,
                "serial_policy": "explicit target serial; blank means unassigned",
                "replaced": False, "hardware_programmed": False}


class ClassicReplacement:
    def __init__(self, client, source_spec: UnitSpec, target_spec: UnitSpec):
        self.client = client
        self.source_spec, self.target_spec = source_spec, target_spec
        self.alignment = OfflineConversion(source_spec, target_spec)
        self.database, self.projects, self.programmer = NativeDatabase(client), NativeProjects(client), Programmer(client)

    def _xml(self, path):
        result = xml_text(self.database.get(path, xml=True))
        _document(result)
        return result

    def _snapshot(self, path, spec):
        with self.programmer.load(path.rsplit("/p/", 1)[0], "/db" + path) as session:
            self.alignment._verify_session(session, spec)
            return session.values()

    def plan(self, source, *, target_firmware, target_catalog, learned_policy,
             learned_history=None, target_serial=""):
        source, project, _network, address = _path(source)
        target_firmware = _token(target_firmware, "target firmware")
        target_catalog = _token(target_catalog, "target catalogue")
        target_serial = _tail(target_serial)
        if not version_matches(target_firmware, self.target_spec.metadata.get("MinVersion", ""), self.target_spec.metadata.get("MaxVersion", "")):
            raise ValueError("Target firmware is outside the supplied specification range")
        # Validate policy/history before connecting or creating a PP session.
        learned_flag(learned_policy, 0, 1, learned_history)
        self.projects.operation("use", project)
        catalog_reply = self.programmer.list_catalog_numbers(self.target_spec.unit_type, target_firmware)
        catalogs = {m[1] for line in catalog_reply.lines
                    if (m := re.match(r"133[- ]catalogNumber=(\S+)(?: |$)", line))}
        if target_catalog not in catalogs:
            raise ValueError("Target catalogue is not supported by this native unit type/firmware")
        source_xml = self._xml(source)
        document = _document(source_xml)
        if _field(document, "UnitType") != self.source_spec.unit_type:
            raise ValueError("Source database type differs from its supplied specification")
        source_oid = _field(document, "OID")
        try: UUID(source_oid)
        except (ValueError, AttributeError) as error:
            raise ValueError("Source unit must have a valid native OID") from error
        seen_parameters = set()
        for parameter in _children(document.documentElement, "PP"):
            name = parameter.getAttribute("Name")
            attrs = {parameter.attributes.item(i).name for i in range(parameter.attributes.length)}
            if name in seen_parameters or name not in self.source_spec.parameters:
                raise ValueError("Source XML contains a duplicate or unmodeled PP parameter: " + name)
            if attrs != {"Name", "Value"} or any(c.nodeType != Node.TEXT_NODE or c.data.strip() for c in parameter.childNodes):
                raise ValueError("Source PP metadata cannot be preserved by the supported backend workflow: " + name)
            seen_parameters.add(name)
        # An unknown OID reference cannot be rewritten by guessing its meaning.
        project_document = minidom.parseString(xml_text(self.database.get("//" + project, xml=True)))
        def check_references(node):
            if node.nodeType == Node.ELEMENT_NODE and node.tagName == "Unit":
                ids = _children(node, "OID")
                if ids and ids[0].firstChild and ids[0].firstChild.nodeValue == source_oid:
                    for child in node.childNodes:
                        if child not in ids and source_oid and source_oid in child.toxml():
                            raise ValueError("Source unit contains an unmodeled reference to its OID")
                    return
            if node.nodeType in (Node.TEXT_NODE, Node.CDATA_SECTION_NODE) and source_oid and source_oid in node.data:
                raise ValueError("Project contains an unmodeled reference to the source unit OID")
            if node.nodeType == Node.ELEMENT_NODE:
                for i in range(node.attributes.length):
                    if source_oid and source_oid in node.attributes.item(i).value:
                        raise ValueError("Project contains an unmodeled attribute reference to the source unit OID")
            for child in node.childNodes: check_references(child)
        check_references(project_document.documentElement)
        source_parameters = self._snapshot(source, self.source_spec)
        with self.programmer.new(source.rsplit("/p/", 1)[0], self.target_spec.unit_type, target_firmware,
                                 catalog_number=target_catalog) as session:
            self.alignment._verify_session(session, self.target_spec)
            self._identity(session, source_parameters, address)
            alignment = self.alignment.plan(source_parameters, session.values())
        values = dict(alignment.expected); values.update(alignment.changes)
        flag = learned_flag(learned_policy, int(source_parameters["LearnedFlag"], 0), int(values["LearnedFlag"]), learned_history)
        values["LearnedFlag"] = flag
        return ReplacementPlan(source, source_xml, _digest(source_xml), tuple(source_parameters.items()),
                               self.target_spec.unit_type, target_firmware, target_catalog, target_serial,
                               learned_policy, learned_history, flag, tuple(values.items()), alignment)

    def _identity(self, session, values, address):
        session.set("UnitAddress", str(address))
        session.set("Project", values["Project"])
        session.set("NetworkAddress", values["NetworkAddress"])

    def _matches(self, path, expected, spec):
        actual = self.alignment._snapshot(spec, self._snapshot(path, spec), spec.parameters)
        if actual != dict(expected): raise ReplacementError("Persisted replacement parameters differ from the validated plan")

    def _free_address(self, network):
        root = minidom.parseString(xml_text(self.database.get(network, xml=True))).documentElement
        used = {int(_field(_document(c.toxml()), "Address")) for c in root.childNodes
                if c.nodeType == Node.ELEMENT_NODE and c.tagName == "Unit"}
        free = next((i for i in range(255, -1, -1) if i not in used), None)
        if free is None: raise ReplacementError("The network needs one unused database unit address for staging")
        return free

    def apply(self, plan: ReplacementPlan, *, backup_project=None):
        source, project, _number, address = _path(plan.source)
        if plan.target_type != self.target_spec.unit_type or plan.alignment.source_type != self.source_spec.unit_type:
            raise ValueError("Replacement plan types differ from this converter")
        if _digest(plan.source_xml) != plan.source_hash:
            raise ValueError("Replacement source XML hash differs from the plan")
        # Reject altered policies/parameters and re-derive target defaults from
        # the native backend before any durable database mutation.
        rebuilt = self.plan(source, target_firmware=plan.target_firmware, target_catalog=plan.target_catalog,
                            target_serial=plan.target_serial, learned_policy=plan.learned_policy, learned_history=plan.learned_history)
        if rebuilt.source_hash != plan.source_hash or dict(rebuilt.source_parameters) != dict(plan.source_parameters):
            raise ReplacementError("Source changed since this replacement was planned")
        if (dict(rebuilt.parameters) != dict(plan.parameters) or rebuilt.learned_value != plan.learned_value
                or rebuilt.alignment.as_dict() != plan.alignment.as_dict()):
            raise ValueError("Replacement parameter plan differs from the supported workflow")
        backup = _project(backup_project) if backup_project is not None else "B" + uuid4().hex[:7].upper()
        if backup.upper() == project.upper(): raise ValueError("Backup project must differ from the source")
        network = source.rsplit("/p/", 1)[0]
        stage_address = self._free_address(network)
        stage = network + "/p/" + str(stage_address)
        try:
            self.projects.operation("save", project)
            self.projects.operation("copy", project, backup)
        except Exception as error:
            raise ReplacementError("Backup preparation failed before staging: " + str(error), backup_project=backup) from error
        original = _document(plan.source_xml)
        tag_name = _field(original, "TagName")
        stage_oid = None
        stage_attempted = False
        stage_tag = "REPLACE_" + uuid4().hex[:12]
        promotion_attempted = False
        try:
            stage_attempted = True
            self.database.copy(source, network, stage_address, stage_tag)
            staged_xml = self._xml(stage)
            stage_oid = _field(_document(staged_xml), "OID")
            if _canonical(staged_xml, _METADATA_CHANGED) != _canonical(plan.source_xml, _METADATA_CHANGED):
                raise ReplacementError("Staging lost or changed source metadata")
            for field, value in (("UnitType", plan.target_type), ("FirmwareVersion", plan.target_firmware),
                                 ("CatalogNumber", plan.target_catalog)):
                self.database.set(stage + "/" + field, value)
            serial_document = _document(self._xml(stage))
            _set(serial_document, "SerialNumber", plan.target_serial)
            self.client.command_document("DBSETXML " + stage, serial_document.toxml())
            with self.programmer.load(network, "/db" + stage) as target:
                target.reset_defaults()
                self._identity(target, dict(plan.source_parameters), address)
                actual_plan = self.alignment.plan(dict(plan.source_parameters), target.values())
                if dict(actual_plan.expected) != dict(plan.alignment.expected):
                    raise ReplacementError("Staged native defaults differ from the plan")
                self.alignment.apply(target, actual_plan)
                target.set("LearnedFlag", str(plan.learned_value))
                target.save_to_source()
            self._matches(stage, plan.parameters, self.target_spec)
            candidate = _document(self._xml(stage))
            _set(candidate, "Address", address); _set(candidate, "TagName", tag_name)
            # A promoted replacement must not duplicate the still-existing staged
            # object's identity. C-Gate accepts and persists explicit UUID OIDs.
            _set(candidate, "OID", str(uuid4()))
            candidate_xml = candidate.toxml()
            if _canonical(candidate_xml, _METADATA_CHANGED) != _canonical(plan.source_xml, _METADATA_CHANGED):
                raise ReplacementError("Prepared replacement lost or changed source metadata")
            if _digest(self._xml(source)) != plan.source_hash or self._snapshot(source, self.source_spec) != dict(plan.source_parameters):
                raise ReplacementError("Source changed during replacement preparation")
            promotion_attempted = True
            self.client.command_document("DBSETXML " + source, candidate_xml)
            if _canonical(self._xml(source)) != _canonical(candidate_xml):
                raise ReplacementError("Promoted unit XML differs from the validated replacement")
            self._matches(source, plan.parameters, self.target_spec)
            self.database.delete(stage)
            stage_oid = None
            self.projects.operation("save", project)
            self._matches(source, plan.parameters, self.target_spec)
            return {**plan.as_dict(), "replaced": True, "project_saved": True, "backup_project": backup,
                    "old_oid": _field(original, "OID"), "new_oid": _field(candidate, "OID"),
                    "metadata_verified": True, "parameters_verified": True, "staging_removed": True}
        except Exception as error:
            rollback_errors = []
            if promotion_attempted:
                try:
                    self.client.command_document("DBSETXML " + source, plan.source_xml)
                    if _canonical(self._xml(source)) != _canonical(plan.source_xml):
                        raise ReplacementError("Original source XML could not be verified after restoration")
                    self._matches(source, self.alignment._snapshot(self.source_spec, dict(plan.source_parameters), self.source_spec.parameters).items(), self.source_spec)
                except Exception as rollback: rollback_errors.append(str(rollback))
            if stage_attempted:
                try:
                    remaining = _document(self._xml(stage))
                    if ((stage_oid and _field(remaining, "OID") == stage_oid)
                            or (stage_oid is None and _field(remaining, "TagName") == stage_tag)):
                        self.database.delete(stage)
                    else: rollback_errors.append("Staging identity changed; staged address was retained")
                except CGateError as cleanup:
                    if cleanup.response.code != 401: rollback_errors.append(str(cleanup))
                except Exception as cleanup: rollback_errors.append(str(cleanup))
            try: self.projects.operation("save", project)
            except Exception as save_error: rollback_errors.append(str(save_error))
            raise ReplacementError("Classic replacement failed: " + str(error), backup_project=backup,
                                   rollback_errors=rollback_errors, staging_path=stage if rollback_errors else None) from error

    def replace(self, source, *, target_firmware, target_catalog, learned_policy,
                learned_history=None, target_serial="", backup_project=None):
        plan = self.plan(source, target_firmware=target_firmware, target_catalog=target_catalog,
                         learned_policy=learned_policy, learned_history=learned_history, target_serial=target_serial)
        return self.apply(plan, backup_project=backup_project)
