"""Source-established Toolkit replacement with explicit operator backup/reopen.

Original exception cleanup attempts deletion of the target. This workflow keeps
an uncertain scaffold and a durable journal instead; read-only recovery never
replays or restores a mutation. Full GUI/physical replacement parity is open.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, replace
import hashlib
import json
from pathlib import Path
import re
import stat
import unicodedata
from xml.dom import Node

from . import toolkit_tweaker_workflow as creation
from .native import NativeDatabase, NativeProjects, _project, _tail
from .pci_selected_serial import _Journal, _unique_pairs
from .programming import Programmer
from .project import ProjectDocument, _elements, _field
from .barcode_database import _snapshot, _shape as _legacy_shape
from .conversion_xml_preservation import comparison_policy, contextual_unit, shape as _shape, unit_shape as _unit_shape, xml_space

FORMAT = "cbus-toolkit-tweaker-lifecycle-v1"
XML_PRESERVATION_PROFILE = "conversion-semantic-xml-v1"
LEGACY_XML_COMPARISON = {
    "whitespace_only_text_around_element_children_compared": False,
    "xml_space_preserve_override_enforced": False,
}
SOURCE_RULES = {
    "convert": "TCBusUnitConversion.Convert@0xcaeaf0..0xcaf4ec",
    "exe_sha256": "9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab",
    "map_sha256": "f96f05cef7c2bdf0f295397d97249b50c45db013f3fcaa2c502f76e2c10dd1eb",
    "method_bytes_sha256": "2161e9fb86f6781a52e117b2c1822f2cedd64f07cbaccbdad5a6221bbd07d9a4",
}
PHASES = {"prepared", "backup", "creation", "source_verify", "delete", "readdress",
          "save", "close", "load", "readback", "complete", "creation_incomplete"}


def _initial():
    return {"format": FORMAT, "phase": "connection", "plan": None, "plan_sha256": None,
            "commands": [], "mutation_journal": [], "outcome_uncertain": False,
            "created": False, "source_deleted": False, "readdressed": False,
            "project_saved": False, "reopened": False, "accepted": False,
            "backup_verified": False, "read_only_recovery_only": True,
            "automatic_retries": 0, "rollback_performed": False, "hardware_programmed": False,
            "original_exception_cleanup_reproduced": False, "full_replacement_parity": False,
            "xml_comparison": comparison_policy(),
            "creation": creation._initial()}


def _attach(error, state):
    error.details = {**getattr(error, "details", {}), "toolkit_tweaker_lifecycle_evidence": deepcopy(state)}


@contextmanager
def connection_guard(args):
    if args.action != "conversion" or args.remote_action not in ("tweak-replace", "tweak-recover"):
        yield
        return
    state = args._toolkit_tweaker_lifecycle_evidence = _initial()
    try:
        yield
    except BaseException as error:
        state["failure_phase"] = "connection_cleanup" if state["phase"] == "complete" else state["phase"]
        _attach(error, state)
        raise


def record_output_error(args, error):
    state = getattr(args, "_toolkit_tweaker_lifecycle_evidence", None)
    if state is not None:
        state["failure_phase"] = "output"
        _attach(error, state)


@dataclass(frozen=True)
class PreparedLifecycle:
    creation: creation.Prepared
    backup: str
    journal: Path | None


def _journal_path(value):
    path = Path(value).absolute()
    if path.exists() or path.is_symlink():
        raise ValueError("Existing lifecycle journal refuses reapply; use tweak-recover")
    if not path.parent.is_dir() or any(p.is_symlink() for p in (path.parent, *path.parent.parents)):
        raise ValueError("Journal requires an existing directory without symbolic links")
    return path


def prepare(args):
    backup = _project(args.backup_project)
    values = vars(args).copy()
    match = creation._UNIT.fullmatch(args.source)
    if match is None:
        raise ValueError("Use a canonical //PROJECT/NETWORK/p/UNIT path")
    if backup.casefold() == match[1].casefold():
        raise ValueError("Backup project must be distinct")
    # The actual stage address and metadata are derived from a fresh snapshot.
    values.update(target_address=1 if int(match[3]) != 1 else 2, tag_name="NEWUNIT")
    from argparse import Namespace
    prepared = creation.prepare(Namespace(**values))
    journal = _journal_path(args.journal) if getattr(args, "journal", None) is not None else None
    if prepared.apply and journal is None:
        raise ValueError("--apply requires a new --journal")
    return PreparedLifecycle(prepared, backup, journal)


def legal_part_name(tag):
    """Recovered CharIsCBusName + uppercase/filter/first-eight rule.

    ASCII output avoids Python/Delphi non-ASCII uppercase differences; their
    non-ASCII expansions are outside this portable fallback-name admission.
    """
    if not tag.isascii():
        raise ValueError("Blank UnitName fallback requires an ASCII TagName")
    return "".join(c for c in tag.upper() if 0x21 <= ord(c) <= 0x60 and c not in "<>")[:8]


def metadata(source, target_catalog):
    tag = _field(source, "TagName") or "NEWUNIT"
    name = _field(source, "UnitName") or legal_part_name(tag)
    result = {"TagName": tag, "UnitName": name, "Description": _field(source, "Description"),
              "SerialNumber": _field(source, "SerialNumber"), "CatalogNumber": target_catalog}
    for key, value in result.items():
        _tail(value)
        if value != " ".join(value.split()) or any(unicodedata.category(c) == "Cc" for c in value):
            raise ValueError(key + " cannot be represented exactly by native scalar commands")
        if key in ("TagName", "UnitName", "CatalogNumber") and (not value or "#" in value):
            raise ValueError(key + " requires a nonempty SAFE-representable value")
    return result


def stage_address(network):
    occupied = set()
    for unit in _elements(network, "Unit"):
        text = _field(unit, "Address")
        if not re.fullmatch(r"[+]?[0-9]+", text) or not 0 <= int(text) <= 255:
            raise ValueError("Existing Unit has an unrepresentable byte Address")
        if int(text) in occupied:
            raise ValueError("Ambiguous existing Unit address aliases")
        occupied.add(int(text))
    try:
        return next(address for address in range(1, 256) if address not in occupied)
    except StopIteration as error:
        raise ValueError("No free staging Unit address in 1..255") from error


def _set_field(node, name, value):
    rows = _elements(node, name)
    if len(rows) != 1:
        raise ValueError("Expected exactly one project " + name)
    row = rows[0]
    for child in list(row.childNodes):
        row.removeChild(child)
    row.appendChild(node.ownerDocument.createTextNode(value))


def _backup_absent(client, name):
    rows = NativeProjects(client).directory().lines
    if re.search(r"(?i)(?<![A-Za-z0-9_])" + re.escape(name) + r"(?![A-Za-z0-9_])", "\n".join(rows)):
        raise ValueError("Backup project already exists; no replacement attempted")


def _backup_matches(raw, before, backup):
    copied = ProjectDocument.from_bytes(raw)
    if _field(copied.project, "Address") != backup:
        raise RuntimeError("Backup project identity differs")
    original = ProjectDocument.from_bytes(before)
    for key in ("Address", "TagName"):
        if _elements(original.project, key):
            _set_field(copied.project, key, _field(original.project, key))
        elif _elements(copied.project, key):
            raise RuntimeError("Backup introduced an unexpected project " + key)
    if _shape(copied.document.documentElement) != _shape(original.document.documentElement):
        raise RuntimeError("Backup project does not preserve the complete original tree")


def _journal_xml_preserved(value):
    """Prove new completed journals without upgrading historical comparisons.

    The detached staged Unit inherits the parent scope from the hash-bound
    before project. Its recorded actual scope must match that derived scope;
    final and backup documents independently preserve the remaining tree.
    """
    if value.get("xml_preservation_profile") != XML_PRESERVATION_PROFILE or value["phase"] != "complete":
        return False
    if value.get("xml_comparison") != comparison_policy():
        raise ValueError("Journal XML comparison policy differs")
    for name in ("staged_unit_xml", "staged_unit_parent_xml_space", "expected_final_project_xml", "backup_xml"):
        if not isinstance(value.get(name), str):
            raise ValueError("Journal lacks semantic XML closure: " + name)
    plan = value["plan"]
    source, target = creation._UNIT.fullmatch(plan["source"]), creation._UNIT.fullmatch(plan["target"])
    before = ProjectDocument.from_bytes(plan["lifecycle"]["before_project_xml"].encode())
    parent = before.resolve("/network/" + source[2])
    scope = xml_space(parent)
    if value["staged_unit_parent_xml_space"] != scope:
        raise ValueError("Journal staged Unit ancestor scope differs")
    original_source = before.resolve("/network/" + source[2] + "/unit/" + source[3])
    staged = _unit_shape(value["staged_unit_xml"].encode(), context_node=original_source, inherited_xml_space=scope)
    expected = ProjectDocument.from_bytes(value["expected_final_project_xml"].encode())
    final = expected.resolve("/network/" + source[2] + "/unit/" + source[3])
    if _field(final, "OID") != value["destination_oid"]:
        raise ValueError("Journal replacement XML identity differs")
    comparison = final.cloneNode(deep=True)
    _set_field(comparison, "Address", target[3])
    if _shape(comparison, inherited_xml_space=xml_space(final.parentNode)) != staged:
        raise ValueError("Journal staged/final Unit XML differs")
    final.parentNode.removeChild(final)
    original = before.resolve("/network/" + source[2] + "/unit/" + source[3])
    original.parentNode.removeChild(original)
    if _shape(expected.document.documentElement) != _shape(before.document.documentElement):
        raise ValueError("Journal final unrelated XML differs")
    try:
        _backup_matches(value["backup_xml"].encode(), plan["lifecycle"]["before_project_xml"].encode(),
                        plan["lifecycle"]["backup_project"])
    except RuntimeError as error:
        raise ValueError("Journal backup semantic XML differs") from error
    return True


def _validate_journal(value):
    if (not isinstance(value, dict) or value.get("format") != FORMAT
            or value.get("phase") not in PHASES or value.get("read_only_recovery_only") is not True):
        raise ValueError("Malformed tweaker lifecycle journal")
    plan = value.get("plan")
    if not isinstance(plan, dict) or creation._digest(plan) != value.get("plan_sha256"):
        raise ValueError("Lifecycle journal plan digest differs")
    required = {"endpoint", "source", "target", "source_type", "target_type", "target_firmware",
                "target_catalog", "tag_name", "project_sha256", "specifications", "source_pp",
                "target_defaults", "tweaker", "assignments", "expected_parameters", "metadata", "lifecycle"}
    if set(plan) != required:
        raise ValueError("Malformed lifecycle plan fields")
    for name in ("source", "target", "source_type", "target_type", "target_firmware", "target_catalog", "tag_name", "project_sha256"):
        if not isinstance(plan[name], str) or not plan[name]:
            raise ValueError("Malformed lifecycle plan " + name)
    for name in ("specifications", "source_pp", "target_defaults", "tweaker", "expected_parameters", "metadata"):
        if not isinstance(plan[name], dict):
            raise ValueError("Malformed lifecycle plan " + name)
    if not isinstance(plan["assignments"], list):
        raise ValueError("Malformed lifecycle assignments")
    context = plan.get("lifecycle")
    if (not isinstance(context, dict) or context.get("format") != FORMAT or set(context) != {
            "format", "backup_project", "before_project_xml", "source_oid", "source_xml", "source_rules",
            "catalogue_boundary", "backup_reopen_boundary", "exception_cleanup_boundary", "endpoint_tls"}):
        raise ValueError("Missing lifecycle plan context")
    if (any(not isinstance(context[name], str) for name in context.keys() - {"source_rules", "endpoint_tls"})
            or context["source_rules"] != SOURCE_RULES or type(context["endpoint_tls"]) is not bool):
        raise ValueError("Malformed lifecycle context values")
    source = creation._UNIT.fullmatch(plan.get("source", ""))
    target = creation._UNIT.fullmatch(plan.get("target", ""))
    if (source is None or target is None or (source[1], source[2]) != (target[1], target[2])
            or source[3] == target[3] or max(int(source[2]), int(source[3]), int(target[3])) > 255):
        raise ValueError("Malformed lifecycle Unit paths")
    if _project(context["backup_project"]).casefold() == source[1].casefold():
        raise ValueError("Invalid lifecycle backup identity")
    endpoint = plan.get("endpoint")
    if (not isinstance(endpoint, dict) or set(endpoint) != {"host", "port"}
            or not isinstance(endpoint["host"], str) or not endpoint["host"]
            or type(endpoint["port"]) is not int or not 1 <= endpoint["port"] <= 65535):
        raise ValueError("Malformed lifecycle endpoint")
    before = context["before_project_xml"].encode()
    if hashlib.sha256(before).hexdigest() != plan["project_sha256"]:
        raise ValueError("Journal source snapshot digest differs")
    document = ProjectDocument.from_bytes(before)
    legacy = value.get("xml_comparison") == LEGACY_XML_COMPARISON
    if not legacy:
        _shape(document.document.documentElement)
    node = document.resolve("/network/" + source[2] + "/unit/" + source[3])
    if _field(node, "OID") != context["source_oid"]:
        raise ValueError("Journal source identity differs")
    # Historical journals remain inspectable under their declared policy. This
    # admission is read-only and cannot supply new semantic persistence credit.
    source_matches = (_legacy_shape(contextual_unit(context["source_xml"].encode(), node)) == _legacy_shape(node)) if legacy else (
        _unit_shape(context["source_xml"].encode(), context_node=node) == _shape(node))
    if not source_matches:
        raise ValueError("Journal source metadata differs")
    for name in ("created", "source_deleted", "readdressed", "reopened", "accepted", "backup_verified", "outcome_uncertain"):
        if type(value.get(name)) is not bool:
            raise ValueError("Malformed lifecycle state " + name)
    if value.get("project_saved") is not None and type(value.get("project_saved")) is not bool:
        raise ValueError("Malformed lifecycle save state")
    rows = value.get("mutation_journal")
    if not isinstance(rows, list) or len(rows) > 100000:
        raise ValueError("Malformed lifecycle send journal")
    for row in rows:
        if (not isinstance(row, dict) or set(row) not in ({"command", "attempted", "confirmed", "persistent"},
                {"command", "attempted", "confirmed", "persistent", "status"})
                or not isinstance(row["command"], str) or row["attempted"] is not True
                or type(row["confirmed"]) is not bool or type(row["persistent"]) is not bool
                or row["confirmed"] and (type(row.get("status")) is not int or not 100 <= row["status"] < 400)):
            raise ValueError("Malformed lifecycle possible-send record")
    if value["phase"] == "complete":
        created = value.get("creation")
        if (not all(value.get(k) is True for k in ("created", "source_deleted", "readdressed", "reopened", "accepted",
                "backup_verified", "project_saved", "fresh_project_verified", "fresh_pp_verified"))
                or value["outcome_uncertain"] or not rows or not all(row["confirmed"] for row in rows)
                or not isinstance(value.get("expected_final_project_xml"), str)
                or not isinstance(value.get("backup_xml"), str)
                or not isinstance(value.get("verified_final_pp"), dict)
                or any(not isinstance(k, str) or not isinstance(v, str) for k, v in value["verified_final_pp"].items())
                or not isinstance(created, dict) or created.get("plan") != plan
                or created.get("accepted") is not True or not isinstance(created.get("oid"), str)
                or created.get("oid") != value.get("destination_oid")):
            raise ValueError("Completed journal lacks confirmed save/reopen evidence")
        required_commands = ["PROJECT COPY " + source[1] + " " + context["backup_project"],
            "DBDELETE " + plan["source"], "DBSET " + plan["target"] + "/Address " + source[3],
            "PROJECT SAVE " + source[1], "PROJECT CLOSE " + source[1], "PROJECT LOAD " + source[1]]
        commands = [row["command"] for row in rows]
        if any(commands.count(command) != 1 for command in required_commands):
            raise ValueError("Completed journal lacks exact-once lifecycle sends")
        positions = [commands.index(command) for command in required_commands]
        if positions != sorted(positions):
            raise ValueError("Completed journal lifecycle ordering differs")
        if any(rows[position]["status"] != 200 for position in positions):
            raise ValueError("Completed journal lacks exact 200 lifecycle receipts")
        adds = [row for row in rows if row["command"].startswith("DBADDSAFE ")]
        if len(adds) != 1 or adds[0]["status"] != 301:
            raise ValueError("Completed journal lacks one exact 301 Unit ADD receipt")
        _journal_xml_preserved(value)
    return value


def _parse_journal(raw):
    def reject(value):
        raise ValueError("Nonfinite lifecycle JSON: " + value)
    return _validate_journal(json.loads(raw,
                            object_pairs_hook=_unique_pairs, parse_constant=reject))


def _read_journal(path):
    return _parse_journal(_Journal(path)._read_current())


def prepare_recovery(args):
    raw = _Journal(args.journal)._read_current()
    value = _parse_journal(raw)
    tls = bool(getattr(args, "tls", False))
    if (value["plan"]["endpoint"] != {"host": args.host, "port": args.port or (20123 if tls else 20023)}
            or value["plan"]["lifecycle"]["endpoint_tls"] != tls):
        raise ValueError("Recovery endpoint differs from the bound journal")
    token = None
    if getattr(args, "auth_token_file", None) is not None:
        token = _snapshot(args.auth_token_file, 2048).decode().rstrip("\r\n")
        from .native import _token
        _token(token, "authentication token")
    args._toolkit_tweaker_recovery = (value, hashlib.sha256(raw).hexdigest(), token)
    return value


class _Client:
    def __init__(self, client, state):
        self.client, self.state, self.writer = client, state, None
        self.marker = None
        self.selected = None

    def __getattr__(self, name):
        return getattr(self.client, name)

    def checkpoint(self):
        if self.writer is not None:
            self.writer.write(self.state)
            self.marker.write(self.state)

    def command(self, command):
        if command.startswith("PROJECT USE ") and self.selected == command:
            return self.selected_response
        return self._request(command)

    def command_document(self, command, document):
        return self._request(command, document)

    def _request(self, command, document=None):
        self.state["commands"].append("LOGIN <redacted>" if command.startswith("LOGIN ") else command)
        persistent = command.startswith(("DBADD", "DBSET", "DBDELETE ", "PP SAVE ", "PP SAVE_TO_SOURCE ",
                                         "PROJECT COPY ", "PROJECT SAVE ", "PROJECT CLOSE ", "PROJECT LOAD "))
        staging = command.startswith(("PP SET ", "PP RESET_TO_DEFAULTS ", "PP NEW "))
        previous = self.state["outcome_uncertain"]
        row = None
        if persistent or staging:
            row = {"command": command, "attempted": True, "confirmed": False,
                   "persistent": persistent}
            self.state["mutation_journal"].append(row)
            self.state["outcome_uncertain"] = True
            self.checkpoint()  # Durable possible-send marker before invoking transport.
        response = self.client.command(command) if document is None else self.client.command_document(command, document)
        if row is not None:
            row.update(confirmed=True, status=response.code)
            expected = 301 if command.startswith("DBADDSAFE ") else 200
            self.state["outcome_uncertain"] = previous or response.code != expected
            self.checkpoint()
            if response.code != expected:
                raise RuntimeError("Native send did not return the required " + str(expected) + " receipt")
        if command.startswith("PROJECT USE "):
            self.selected, self.selected_response = command, response
        return response


def _new_attempt(client, path, state):
    if path is None:
        raise ValueError("Missing apply journal")
    _journal_path(path)
    entries = list(path.parent.iterdir())
    if len(entries) > 4096:
        raise ValueError("Journal directory scan exceeds its bound")
    for entry in entries:
        info = entry.lstat()
        if not entry.name.endswith(".toolkit-tweaker.json"):
            continue
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("Lifecycle attempt marker is not a regular file")
        if info.st_size > 16 * 1024 * 1024:
            raise ValueError("Journal directory contains an oversized file")
        raw = _Journal(entry)._read_current()
        if FORMAT.encode() not in raw:
            continue
        prior = _read_journal(entry)
        if (prior["plan_sha256"] == state["plan_sha256"] or
                prior["plan"]["source"].split("/")[2] == state["plan"]["source"].split("/")[2]
                and prior["phase"] != "complete"):
            raise ValueError("A prior lifecycle attempt prevents replay; recover read-only")
    client.writer = _Journal(path)
    client.marker = _Journal(path.with_name(path.name + ".toolkit-tweaker.json"))
    state["journal_scan_scope"] = "same directory; *.toolkit-tweaker.json dedicated attempt markers only"
    client.checkpoint()


def _pp(client, prepared, path):
    with Programmer(client).load(prepared.network, "/db" + path) as session:
        if (session.unit_type, session.firmware, session.catalog_number) != (
                prepared.target_type, prepared.firmware, prepared.catalog):
            raise RuntimeError("Fresh target PP identity differs from the reviewed plan")
        raw = session.values()
        return raw, {name: creation.tweakers.normalized(prepared.target_spec.parameters[name], value)
                     for name, value in raw.items()}


def _verified_project(client, prepared, state, before, staged_shape):
    raw, document = creation._document(client, prepared.project)
    net = prepared.network.rsplit("/", 1)[1]
    final = document.resolve("/network/" + net + "/unit/" + prepared.source.rsplit("/", 1)[1])
    if _field(final, "OID") != state["creation"]["oid"]:
        raise RuntimeError("Replacement identity differs at the original source address")
    comparison = final.cloneNode(deep=True)
    _set_field(comparison, "Address", str(prepared.address))
    if _shape(comparison, inherited_xml_space=xml_space(final.parentNode)) != staged_shape:
        raise RuntimeError("Readdress altered replacement metadata, PP or opaque Unit content")
    final.parentNode.removeChild(final)
    baseline = ProjectDocument.from_bytes(before)
    source = baseline.resolve("/network/" + net + "/unit/" + prepared.source.rsplit("/", 1)[1])
    source.parentNode.removeChild(source)
    if _shape(document.document.documentElement) != _shape(baseline.document.documentElement):
        raise RuntimeError("Replacement altered unrelated project XML")
    raw_pp, normalized = _pp(client, prepared, prepared.source)
    if normalized != state["creation"]["verified_expected_parameters"]:
        raise RuntimeError("Fresh replacement PP differs after readdress/reopen")
    state["verified_final_pp"] = raw_pp
    return raw


def execute(prepared, raw_client, state):
    client = _Client(raw_client, state)
    p = prepared.creation
    if p.auth_token is not None:
        from .cgate import CGateError
        try:
            if client.command("LOGIN " + p.auth_token).code != 200:
                raise RuntimeError("Authentication did not return the required 200 receipt")
        except CGateError as error:
            raise RuntimeError("Authentication refused before replacement") from error
    client.command("PROJECT USE " + p.project)
    before, baseline = creation._document(client, p.project)
    creation._closed(client, baseline, p.project)
    network = baseline.resolve("/network/" + p.network.rsplit("/", 1)[1])
    source = baseline.resolve("/network/" + p.network.rsplit("/", 1)[1] + "/unit/" + p.source.rsplit("/", 1)[1])
    source_oid = _field(source, "OID")
    if not source_oid:
        raise ValueError("Source Unit requires an exact database OID")
    metadata_values = metadata(source, p.catalog)
    context = {"format": FORMAT, "backup_project": prepared.backup,
               "before_project_xml": before.decode(), "source_oid": source_oid,
               "source_xml": source.toxml(), "source_rules": SOURCE_RULES,
               "endpoint_tls": raw_client.ssl_context is not None,
               "catalogue_boundary": "explicit target default; original catalogue lookup not reproduced",
               "backup_reopen_boundary": "explicit operator protection, not original GUI ordering",
               "exception_cleanup_boundary": "no automatic target deletion or rollback; original cleanup remains open"}
    _backup_absent(client, prepared.backup)
    p = replace(p, address=stage_address(network), tag_name=metadata_values["TagName"],
                auth_token=None, metadata=metadata_values, plan_context=context)

    def before_add(inner, binding, fresh, document):
        state.update(plan=deepcopy(binding), plan_sha256=creation._digest(binding), phase="prepared")
        _new_attempt(client, prepared.journal, state)
        _backup_absent(client, prepared.backup)
        state["phase"] = "backup"
        NativeProjects(client).operation("copy", p.project, prepared.backup)
        backup_raw, _ = creation._document(client, prepared.backup)
        _backup_matches(backup_raw, before, prepared.backup)
        state.update(backup_verified=True, backup_xml=backup_raw.decode(), phase="creation")
        client.checkpoint()
        # Backup must not have altered selection, project or source PP.
        creation._closed(client, document, p.project)
        if creation._document(client, p.project)[0] != fresh:
            raise RuntimeError("Original project changed while creating backup")

    try:
        result, code = creation.execute(p, client, state["creation"], before_add=before_add)
        state.update(plan=deepcopy(result["plan"]), plan_sha256=result["plan_sha256"], created=result["created"])
        if not p.apply:
            state["phase"] = "preview_complete"
            return state, 0
        state["created"] = result["created"]
        if code or not result["accepted"]:
            state.update(phase="creation_incomplete", outcome_uncertain=result["outcome_uncertain"])
            client.checkpoint()
            return state, 1
        state["phase"] = "source_verify"
        current_raw, current = creation._document(client, p.project)
        creation._closed(client, current, p.project)
        target = result["plan"]["target"]
        target_node = current.resolve("/network/" + p.network.rsplit("/", 1)[1] + "/unit/" + str(p.address))
        staged_shape = _shape(target_node)
        state["staged_unit_xml"] = target_node.toxml()
        state["staged_unit_parent_xml_space"] = xml_space(target_node.parentNode)
        state["xml_preservation_profile"] = XML_PRESERVATION_PROFILE
        with Programmer(client).load(p.network, "/db" + p.source) as session:
            if session.values() != result["plan"]["source_pp"]:
                raise RuntimeError("Source PP changed before deletion")
        target_node.parentNode.removeChild(target_node)
        if _shape(current.document.documentElement) != _shape(baseline.document.documentElement):
            raise RuntimeError("Source/unrelated project changed before deletion")
        state["phase"] = "delete"
        if NativeDatabase(client).delete(p.source).code != 200:
            raise RuntimeError("Source deletion did not return the required 200 receipt")
        state["source_deleted"] = True
        state["phase"] = "readdress"
        if client.command("DBSET " + target + "/Address " + p.source.rsplit("/", 1)[1]).code != 200:
            raise RuntimeError("Readdress did not return the required 200 receipt")
        state["readdressed"] = True
        state["phase"] = "readback"
        after = _verified_project(client, p, state, before, staged_shape)
        state["expected_final_project_xml"] = after.decode()
        state["phase"] = "save"
        state["project_saved"] = None
        NativeProjects(client).operation("save", p.project)
        state["project_saved"] = True
        state["phase"] = "close"
        NativeProjects(client).operation("close", p.project)
        state["phase"] = "load"
        NativeProjects(client).operation("load", p.project)
        state["reopened"] = True
        state["phase"] = "readback"
        _verified_project(client, p, state, before, staged_shape)
        backup_raw, _ = creation._document(client, prepared.backup)
        _backup_matches(backup_raw, before, prepared.backup)
        if _shape(ProjectDocument.from_bytes(backup_raw).document.documentElement) != _shape(
                ProjectDocument.from_bytes(state["backup_xml"].encode()).document.documentElement):
            raise RuntimeError("Backup changed after replacement")
        state.update(phase="complete", accepted=True, outcome_uncertain=False,
                     fresh_project_verified=True, fresh_pp_verified=True, unrelated_project_preserved=True,
                     source_path_replaced=True, source_oid_absent_at_original_path=True,
                     destination_oid=result["oid"])
        client.checkpoint()
        return state, 0
    except BaseException as error:
        state["outcome_uncertain"] |= state["creation"]["outcome_uncertain"]
        state["created"] |= state["creation"]["created"]
        if state["created"] or state["source_deleted"] or state["readdressed"]:
            state["outcome_uncertain"] = True
        state["failure_phase"] = state["phase"]
        state["error"] = {"type": type(error).__name__, "message": str(error)}
        if client.writer is not None and not client.writer.failed:
            client.checkpoint()
        _attach(error, state)
        raise


def recover(args, raw_client):
    prepared = getattr(args, "_toolkit_tweaker_recovery", None)
    if prepared is None:
        prepare_recovery(args)
        prepared = args._toolkit_tweaker_recovery
    state, raw_hash, token = prepared
    if hashlib.sha256(_Journal(args.journal)._read_current()).hexdigest() != raw_hash:
        raise ValueError("Recovery journal changed after preconnection validation")
    evidence = _initial()
    client = _Client(raw_client, evidence)
    if token is not None:
        if client.command("LOGIN " + token).code != 200:
            raise RuntimeError("Authentication did not return the required 200 receipt")
    plan, context = state["plan"], state["plan"]["lifecycle"]
    result = {"format": FORMAT, "journal_phase": state["phase"], "read_only_recovery_only": True,
              "replay_authorized": False, "project_saved": None, "persistence_verified": False,
              "outcome_uncertain": state["outcome_uncertain"], "disposition": "read_unavailable",
              "backup_verified_fresh": False, "fresh_pp_verified": False, "commands": evidence["commands"],
              "journal_xml_preservation_verified": _journal_xml_preserved(state),
              "hardware_programmed": False, "automatic_retries": 0, "rollback_performed": False}
    project = plan["source"].split("/")[2]
    try:
        raw, document = creation._document(client, project)
        current_shape = _shape(document.document.documentElement)
        before_shape = _shape(ProjectDocument.from_bytes(context["before_project_xml"].encode()).document.documentElement)
        expected = state.get("expected_final_project_xml")
        final_matches = expected is not None and current_shape == _shape(
            ProjectDocument.from_bytes(expected.encode()).document.documentElement)
        result["disposition"] = "observed_replaced" if final_matches else "observed_before" if current_shape == before_shape else "conflict"
        if final_matches:
            result["destination_oid"] = state["creation"]["oid"]
            with Programmer(client).load(plan["source"].rsplit("/p/", 1)[0], "/db" + plan["source"]) as session:
                if (session.unit_type, session.firmware, session.catalog_number) != (
                        plan["target_type"], plan["target_firmware"], plan["target_catalog"]):
                    raise RuntimeError("Fresh recovery PP identity differs from the reviewed plan")
                fresh_pp_matches = session.values() == state.get("verified_final_pp")
            result["fresh_pp_verified"] = fresh_pp_matches
            if not result["fresh_pp_verified"]:
                result["disposition"] = "conflict"
    except (ValueError, RuntimeError, OSError) as error:
        result.update(fresh_pp_verified=False, disposition="read_unavailable")
        result["read_error"] = {"type": type(error).__name__, "message": str(error)}
    try:
        backup, _ = creation._document(client, context["backup_project"])
        _backup_matches(backup, context["before_project_xml"].encode(), context["backup_project"])
        retained = state.get("backup_xml")
        if retained is not None and _shape(ProjectDocument.from_bytes(backup).document.documentElement) != _shape(
                ProjectDocument.from_bytes(retained.encode()).document.documentElement):
            raise RuntimeError("Backup differs from the retained verified snapshot")
        result["backup_verified_fresh"] = True
    except (ValueError, RuntimeError, OSError) as error:
        result["backup_error"] = {"type": type(error).__name__, "message": str(error)}
    if (state["phase"] == "complete" and result["disposition"] == "observed_replaced"
            and result["backup_verified_fresh"] and result["fresh_pp_verified"]
            and result["journal_xml_preservation_verified"]):
        result.update(project_saved=True, persistence_verified=True, outcome_uncertain=False)
    return result
