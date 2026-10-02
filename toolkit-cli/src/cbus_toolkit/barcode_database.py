"""Barcode add/select against one loaded C-Gate project, without PP or save."""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import stat
import unicodedata
from xml.dom import Node
from xml.dom import minidom
from xml.parsers import expat
import xml.etree.ElementTree as ET

from .barcode_scanner import BarcodeCatalog, BarcodeError, plan_native_add_unit, units_view_actions, wedge_lines
from .cgate import CGateError
from .native import NativeDatabase, NativeProjects, _project, _tail, _token
from .programming import _rows, xml_text
from .project import ProjectDocument, _elements, _field, _xml_string

FORMAT = "cbus-cgate-barcode-add-v1"
MAX_CATALOG_BYTES = 16 * 1024 * 1024
MAX_SCAN_CHARS = 4 * 1024 * 1024
_OID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")
_UNIT_FIELDS = ("UnitType", "UnitName", "SerialNumber", "FirmwareVersion", "CatalogNumber")


def _snapshot(path: Path, limit: int) -> bytes:
    # A FIFO must not block before its type can be checked. O_NONBLOCK has no
    # effect on regular files; Windows lacks it and does not use POSIX FIFOs.
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
    with os.fdopen(descriptor, "rb") as source:
        opened = os.fstat(source.fileno())
        if not stat.S_ISREG(opened.st_mode) or opened.st_size > limit:
            raise ValueError("Input must be a regular file within its size limit")
        raw = source.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("Input exceeds its size limit")
    return raw


@dataclass(frozen=True)
class PreparedScan:
    project: str
    network: str
    barcode: str
    catalog_path: Path
    catalog: BarcodeCatalog
    address: int | None
    tag_name: str | None
    apply: bool
    expected_project_sha256: str | None
    auth_token: str | None


def prepare(args) -> PreparedScan:
    """Validate local input before connecting; catalogue hash covers parsed bytes."""
    project = _project(args.project)
    network = _token(args.network, "network")
    parts = network.split("/")
    if (len(parts) != 4 or parts[:2] != ["", ""] or parts[2] != project
            or not parts[3] or any(c in network for c in "<>#")):
        raise ValueError("Use an exact //PROJECT/NETWORK path in the selected project")
    if args.apply and not args.exclusive_project:
        raise ValueError("--apply requires --exclusive-project")
    if args.catalog is None:
        raise ValueError("Use --catalog or CBUS_UNIT_CATALOG")
    raw = _snapshot(Path(args.catalog), MAX_CATALOG_BYTES)
    catalog = BarcodeCatalog.from_snapshot(raw)
    if args.expect_catalog_sha256 is not None and catalog.sha256 != args.expect_catalog_sha256:
        raise ValueError("Catalogue SHA-256 differs from --expect-catalog-sha256")
    if args.barcode == "-":
        import sys
        barcode = sys.stdin.read(MAX_SCAN_CHARS + 1)
    else:
        barcode = args.barcode
    if len(barcode) > MAX_SCAN_CHARS:
        raise ValueError("Scanner input exceeds the 4 MiB character limit")
    scans = wedge_lines(barcode)
    if len(scans) != 1:
        raise BarcodeError("Supply exactly one nonempty scan", code="invalid_input", scans=len(scans))
    if not units_view_actions(scans[0]):
        raise BarcodeError("Toolkit ignores this scan in the Units view", code="wrong_barcode")
    if args.tag_name is not None:
        _tail(args.tag_name)
        _xml_string(args.tag_name)
        if not args.tag_name or args.tag_name != args.tag_name.strip():
            raise ValueError("TagName must be nonempty trimmed text")
        if any(unicodedata.category(character) == "Cc" for character in args.tag_name):
            raise ValueError("TagName cannot contain control characters")
    token = None
    if args.auth_token_file is not None:
        token = _snapshot(args.auth_token_file, 2048).decode("utf-8").rstrip("\r\n")
        _token(token, "authentication token")
    return PreparedScan(project, network, scans[0], Path(args.catalog), catalog,
                        args.address, args.tag_name, args.apply,
                        args.expect_project_sha256, token)


def _initial(mode):
    return {"format": FORMAT, "mode": mode, "phase": "preconditions", "plan": None,
            "applied": False, "created": False, "accepted": False,
            "project_saved": False, "hardware_programmed": False,
            "automatic_retries": 0, "rollback_performed": False,
            "commands": [], "database_write": {
                "add_attempted": False, "add_confirmed": False,
                "document_attempted": False, "document_confirmed": False,
                "outcome_uncertain": False, "oid": None, "path": None},
            "readback": {"unit_verified": False, "scalars_verified": False,
                         "unrelated_project_preserved": False}}


def _attach(error, evidence):
    try:
        error.details = {**getattr(error, "details", {}),
                         "barcode_database_evidence": deepcopy(evidence)}
    except BaseException:
        pass


@contextmanager
def connection_guard(args):
    if args.action != "database" or args.remote_action != "barcode-add":
        yield
        return
    state = args._barcode_database_evidence = _initial("apply" if args.apply else "preview")
    try:
        yield
    except BaseException as error:
        state["failure_phase"] = "connection_cleanup" if state["phase"] == "complete" else state["phase"]
        _attach(error, state)
        raise


def record_output_error(args, error):
    state = getattr(args, "_barcode_database_evidence", None)
    if state is not None:
        state["failure_phase"] = "output"
        _attach(error, state)


def _shape(node):
    """Compare opaque project data while ignoring container indentation only."""
    if node.nodeType == Node.ELEMENT_NODE:
        has_elements = any(c.nodeType == Node.ELEMENT_NODE for c in node.childNodes)
        children = tuple(_shape(c) for c in node.childNodes
                         if not (has_elements and c.nodeType == Node.TEXT_NODE and not c.data.strip()))
        return (node.namespaceURI, node.tagName, tuple(sorted(node.attributes.items())), children)
    if node.nodeType in (Node.TEXT_NODE, Node.CDATA_SECTION_NODE):
        return (node.nodeType, node.data)
    return (node.nodeType, getattr(node, "target", None), getattr(node, "data", None))


def _new_unit_xml(plan, oid):
    root = ET.Element("Unit")
    fields = {"OID": oid, "TagName": plan["tag_name"], "Address": str(plan["address"]),
              **plan["fields"]}
    for name in ("OID", "TagName", "Address", *_UNIT_FIELDS):
        ET.SubElement(root, name).text = fields[name]
    return ET.tostring(root, encoding="unicode", short_empty_elements=True)


def _unit_document(raw):
    """Parse Unit readback without expanding a DTD or discarding markup."""
    if len(raw) > 4 * 1024 * 1024:
        raise ValueError("Unit XML exceeds the database document limit")
    parser = expat.ParserCreate()

    def reject_doctype(*_args):
        raise ValueError("DTD and entity declarations are not supported")

    parser.StartDoctypeDeclHandler = reject_doctype
    try:
        parser.Parse(raw, True)
        root = minidom.parseString(raw).documentElement
        if root.tagName != "Unit" or root.namespaceURI:
            raise ValueError("Expected an unnamespaced Unit readback")
        return root
    except (expat.ExpatError, UnicodeError) as error:
        raise ValueError("Unit readback is not a valid XML document") from error


def _unit_shape(raw):
    return _shape(_unit_document(raw))


def _unit_identity(raw):
    root = _unit_document(raw)
    identities = _elements(root, "OID")
    if (len(identities) != 1 or identities[0].tagName != "OID"
            or identities[0].namespaceURI or identities[0].attributes.length
            or any(node.nodeType != Node.TEXT_NODE for node in identities[0].childNodes)):
        raise RuntimeError("Created Unit readback must contain one plain OID")
    value = _field(root, "OID")
    if not isinstance(value, str) or _OID.fullmatch(value) is None:
        raise RuntimeError("Created Unit readback contains an invalid OID")
    return value


def _validate_fields(plan):
    _tail(plan["tag_name"])
    for name, value in {"TagName": plan["tag_name"], **plan["fields"]}.items():
        _xml_string(value)
        if name in ("TagName", "UnitType", "FirmwareVersion") and (not value or value != value.strip()):
            raise ValueError(name + " must be nonempty trimmed text")
        if name in ("TagName", "UnitType", "FirmwareVersion") and any(
                unicodedata.category(character) == "Cc" for character in value):
            raise ValueError(name + " cannot contain control characters")
    # Refuse an initializer that the document transport cannot send before ADD
    # creates a scaffold. The real issued UUID has the same fixed width.
    if len(_new_unit_xml(plan, "00000000-0000-4000-8000-000000000000").encode("utf-8")) > 4 * 1024 * 1024:
        raise ValueError("Planned Unit XML exceeds the 4 MiB document limit")


def run(prepared: PreparedScan, client, state):
    """Issue at most one ADD and one Unit initializer; retain uncertain outcomes."""
    database = NativeDatabase(client)
    write = state["database_write"]

    def command(text):
        state["commands"].append(text)
        return client.command(text)

    def document(path):
        state["commands"].append("DBGETXML " + path)
        return xml_text(database.get(path, xml=True)).encode("utf-8")

    def scalar(path):
        response = command("DBGET " + path)
        rows = _rows(response)
        values = [value for code, value in rows if code == 342]
        # The replacement's numeric Unit fields have one continued342 row
        # and terminal200; named objects and OID reads terminate with342.
        codes = [code for code, _ in rows]
        if (codes not in ([342], [342, 200]) or response.code != codes[-1]
                or len(rows) != len(response.lines) or len(values) != 1
                or not values[0].startswith(path + "=")):
            raise RuntimeError("Expected one native database scalar reply")
        return values[0].split("=", 1)[1]

    try:
        if prepared.auth_token is not None:
            state["commands"].append("LOGIN <redacted>")
            try:
                authenticated = client.command("LOGIN " + prepared.auth_token)
                if authenticated.code != 200:
                    raise RuntimeError("LOGIN did not return200")
            except (ValueError, OSError, RuntimeError) as error:
                # An arbitrary server may echo a credential in its error reply.
                raise RuntimeError("Authentication did not complete") from error
        state["commands"].append("PROJECT USE " + prepared.project)
        NativeProjects(client).operation("use", prepared.project)
        project_path = "//" + prepared.project
        before = document(project_path)
        before_sha = hashlib.sha256(before).hexdigest()
        state["before_project_sha256"] = before_sha
        if prepared.expected_project_sha256 is not None and before_sha != prepared.expected_project_sha256:
            raise ValueError("Project SHA-256 differs from --expect-project-sha256")
        plan = plan_native_add_unit(before, prepared.network, prepared.barcode, prepared.catalog,
                                    address=prepared.address, tag_name=prepared.tag_name)
        state["plan"] = plan
        state["phase"] = "planned"
        if plan["action"] != "add":
            state["phase"] = plan["action"]
            state["accepted"] = plan["action"] == "selected_existing"
            return state, 0
        _validate_fields(plan)
        if not prepared.apply:
            return state, 0
        # This guards a caller-owned edit; C-Gate exposes no compare-and-swap.
        state["phase"] = "preconditions"
        current_catalog = _snapshot(prepared.catalog_path, MAX_CATALOG_BYTES)
        if hashlib.sha256(current_catalog).hexdigest() != prepared.catalog.sha256:
            raise ValueError("Catalogue changed after barcode planning")
        fresh = document(project_path)
        if fresh != before:
            raise ValueError("Project changed after barcode planning")
        state["phase"] = "refreshed"
        write["path"] = plan["unit"]
        state["phase"] = "add"
        write["add_attempted"] = True
        try:
            reply = command(f"DBADDSAFE {prepared.network} Unit {plan['address']} {plan['tag_name']}")
        except BaseException as error:
            write["outcome_uncertain"] = not isinstance(error, CGateError)
            raise
        if reply.code not in (200, 301):
            write["outcome_uncertain"] = True
            raise RuntimeError("Unit ADD did not return a supported creation receipt")
        write["add_confirmed"] = state["created"] = True
        # Creation acceptance does not establish which fresh object was issued.
        # Keep this unresolved until its identity is independently bound below.
        write["outcome_uncertain"] = True
        state["phase"] = "create_identity"
        if reply.code == 301:
            match = re.fullmatch(r"301 OID=(" + _OID.pattern + ")", reply.final)
            if match is None or len(reply.lines) != 1:
                raise RuntimeError("Unit ADD did not return one fresh OID")
            oid = match[1]
        else:
            oid = _unit_identity(document(plan["unit"]))
            state["legacy_numeric_add_receipt"] = "Replacement200; retained original SAFE Unit cases use301"
        if _OID.fullmatch(oid) is None:
            raise RuntimeError("Created Unit OID is invalid")
        baseline = ProjectDocument.from_bytes(before)
        if any((_field(node, "OID") or "").lower() == oid.lower()
               for node in [baseline.project, *baseline.project.getElementsByTagName("*")]):
            raise RuntimeError("Created Unit OID is already owned by the baseline project")
        write["oid"] = oid
        if reply.code == 301 and _unit_identity(document(plan["unit"])) != oid:
            raise RuntimeError("Created Unit OID did not resolve at its exact address")
        write["outcome_uncertain"] = False
        candidate = _new_unit_xml(plan, oid)
        expected_unit = _unit_shape(candidate.encode("utf-8"))
        state["unit_document_sha256"] = hashlib.sha256(candidate.encode("utf-8")).hexdigest()
        state["phase"] = "initialize"
        write["document_attempted"] = True
        state["commands"].append("DBSETXML " + plan["unit"])
        try:
            initialized = database.set_xml(plan["unit"], candidate)
        except BaseException as error:
            write["outcome_uncertain"] = not isinstance(error, CGateError)
            raise
        if initialized.code != 301 or initialized.final != "301 OID=" + oid or len(initialized.lines) != 1:
            write["outcome_uncertain"] = True
            raise RuntimeError("Unit initializer did not confirm the issued OID")
        write["document_confirmed"] = state["applied"] = True
        state["phase"] = "readback"
        unit_snapshot = document(plan["unit"])
        expected = {"OID": oid, "TagName": plan["tag_name"], "Address": str(plan["address"]), **plan["fields"]}
        if _unit_shape(unit_snapshot) != expected_unit:
            raise RuntimeError("New Unit XML differs from the barcode plan")
        state["readback"]["unit_verified"] = True
        for name, value in expected.items():
            path = "!" + oid + "/OID" if name == "OID" else plan["unit"] + "/" + name
            if scalar(path) != value:
                raise RuntimeError("New Unit scalar readback differs for " + name)
        state["readback"]["scalars_verified"] = True
        after = document(project_path)
        after_document = ProjectDocument.from_bytes(after)
        new_node = after_document.resolve("/network/" + prepared.network.rsplit("/", 1)[1]
                                           + "/unit/" + str(plan["address"]))
        if _shape(new_node) != expected_unit:
            raise RuntimeError("New Unit differs in whole-project readback")
        new_node.parentNode.removeChild(new_node)
        if _shape(after_document.document.documentElement) != _shape(baseline.document.documentElement):
            raise RuntimeError("Unrelated project data changed during barcode Unit creation")
        state["readback"]["unrelated_project_preserved"] = True
        state["after_project_sha256"] = hashlib.sha256(after).hexdigest()
        state["accepted"] = True
        state["phase"] = "complete"
        return state, 0
    except BaseException as error:
        state["failure_phase"] = state["phase"]
        _attach(error, state)
        raise
