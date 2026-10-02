"""Reviewed Toolkit tweaker creation, with no source removal or project save."""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import tempfile
import unicodedata
import uuid
from xml.dom import Node

from .barcode_database import _snapshot, _shape, _unit_identity
from .cgate import CGateError
from .native import NativeDatabase, _tail, _token
from .programming import Programmer, ProgrammingCommandError, xml_text, _rows
from .project import ProjectDocument, _elements, _field, _xml_string
from . import toolkit_conversion_tweakers as tweakers
from .unitspec import UnitSpecStore, MAX_SPEC_BYTES, _read_xml, _children


FORMAT = "cbus-toolkit-tweaker-workflow-v1"
_UNIT = re.compile(r"//([A-Za-z0-9_]{1,8})/(0|[1-9][0-9]{0,2})/p/(0|[1-9][0-9]{0,2})")


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True).encode()).hexdigest()


def _spec(directory, filename):
    """Parse immutable copies of precisely the consumed include graph."""
    store = UnitSpecStore(directory)
    pins = {}
    with tempfile.TemporaryDirectory(prefix="cbus-tweaker-spec-") as temporary:
        target = Path(temporary)

        def copy(name):
            if name in pins:
                return
            if len(pins) >= 128:
                raise ValueError("Specification include limit exceeded")
            path = store._path(name)
            data = _snapshot(path, MAX_SPEC_BYTES)
            pins[name] = hashlib.sha256(data).hexdigest()
            local = target / name
            local.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            local.write_bytes(data)
            local.chmod(0o600)
            root = _read_xml(local)
            for container in _children(root, "Includes"):
                for include in _children(container, "Include"):
                    copy((include.text or "").strip())

        copy(filename)
        spec = UnitSpecStore(target).load(filename)
    return spec, pins


@dataclass(frozen=True)
class Prepared:
    source: str
    project: str
    network: str
    address: int
    source_type: str
    target_type: str
    source_spec: object
    target_spec: object
    spec_directory: Path
    spec_pins: dict
    firmware: str
    catalog: str
    tag_name: str
    apply: bool
    expected_plan: str | None
    auth_token: str | None
    metadata: dict | None = None
    plan_context: dict | None = None


def prepare(args):
    match = _UNIT.fullmatch(args.source)
    if match is None or any(int(match[i]) > 255 for i in (2, 3)):
        raise ValueError("Use a canonical //PROJECT/NETWORK/p/UNIT path in 0..255")
    if args.target_address == int(match[3]):
        raise ValueError("Replacement address must differ from the source")
    if args.apply and (not args.exclusive_project or args.expect_plan_sha256 is None):
        raise ValueError("--apply requires --exclusive-project and --expect-plan-sha256")
    if args.spec_dir is None:
        raise ValueError("Use --spec-dir or CBUS_UNITSPEC_DIR")
    source_type, target_type = args.source_type.upper(), args.target_type.upper()
    tweakers.admitted(source_type, target_type)
    source_spec, source_pins = _spec(args.spec_dir, args.source_spec)
    target_spec, target_pins = _spec(args.spec_dir, args.target_spec)
    for name in source_pins.keys() & target_pins.keys():
        if source_pins[name] != target_pins[name]:
            raise ValueError("Shared specification changed during input capture")
    # Existing profile/schema validation remains the authority for all pairs.
    converter = tweakers.ToolkitTweakerConversion(None, source_type, source_spec, target_type, target_spec)
    if not target_spec.supports_version(args.firmware):
        raise ValueError("Target firmware is outside the supplied specification")
    if converter.tweaker == tweakers.KEY_TWEAKER:
        validate = (tweakers.coupler.require_target_firmware
                    if source_type in tweakers.coupler.COUPLER_SOURCE_TYPES else tweakers.require_target_firmware)
        validate(args.firmware)
    elif converter.tweaker == tweakers.input_unit.INPUT_TWEAKER:
        tweakers.input_unit.require_target_firmware(args.firmware)
    elif converter.tweaker in tweakers.dlt.TWEAKERS:
        tweakers.dlt.require_target_firmware(args.firmware)
    elif converter.tweaker not in tweakers.RELAY_TWEAKERS:
        # F catalogue variants may use their base DIMDN specification. The
        # actual database and PP type must still match the requested type.
        def dimmer_type(actual, wanted):
            return actual.upper() in {wanted, wanted[:-1] if wanted.endswith("F") else wanted}
        if not dimmer_type(source_spec.unit_type, source_type) or not dimmer_type(target_spec.unit_type, target_type):
            raise ValueError("Dimmer specifications must match their requested source/target types")
    for label, value in (("firmware", args.firmware), ("catalogue", args.catalog_number),
                         ("TagName", args.tag_name or f"Tweaked{args.target_address}")):
        _tail(value)
        _xml_string(value)
        if not value or value != value.strip() or "#" in value or any(unicodedata.category(c) == "Cc" for c in value):
            raise ValueError(label + " must be nonempty trimmed text without controls or SAFE's # delimiter")
    _token(args.firmware, "firmware")
    _token(args.catalog_number, "catalogue for the temporary native default session")
    token = None
    if args.auth_token_file is not None:
        token = _snapshot(args.auth_token_file, 2048).decode().rstrip("\r\n")
        _token(token, "authentication token")
    return Prepared(args.source, match[1], args.source.rsplit("/p/", 1)[0], args.target_address,
                    source_type, target_type, source_spec, target_spec, Path(args.spec_dir).resolve(),
                    source_pins | target_pins, args.firmware, args.catalog_number,
                    args.tag_name or f"Tweaked{args.target_address}", args.apply,
                    args.expect_plan_sha256, token)


def _initial():
    return {"format": FORMAT, "phase": "connection", "plan": None, "plan_sha256": None,
            "created": False, "applied": False, "accepted": False, "oid": None,
            "project_saved": False, "source_deleted": False, "readdressed": False,
            "hardware_programmed": False, "automatic_retries": 0, "rollback_performed": False,
            "outcome_uncertain": False, "staging_uncertain": False, "commands": [], "writes": [],
            "staging_writes": [], "assignments": [], "failed_writes": {},
            "xml_comparison": {"whitespace_only_text_around_element_children_compared": False,
                               "xml_space_preserve_override_enforced": False}}


def _attach(error, state):
    error.details = {**getattr(error, "details", {}), "toolkit_tweaker_evidence": deepcopy(state)}


@contextmanager
def connection_guard(args):
    if args.action != "conversion" or args.remote_action != "tweak":
        yield
        return
    state = args._toolkit_tweaker_evidence = _initial()
    try:
        yield
    except BaseException as error:
        state["failure_phase"] = "connection_cleanup" if state["phase"] == "complete" else state["phase"]
        _attach(error, state)
        raise


def record_output_error(args, error):
    state = getattr(args, "_toolkit_tweaker_evidence", None)
    if state is not None:
        state["failure_phase"] = "output"
        _attach(error, state)


class _Client:
    def __init__(self, client, state, project):
        self.client, self.state, self.project = client, state, project
        self.selected = None

    def __getattr__(self, name):
        return getattr(self.client, name)

    def command(self, command):
        return self._request(command)

    def command_document(self, command, document):
        return self._request(command, document)

    def _request(self, command, document=None):
        if command == "PROJECT USE " + self.project and self.selected is not None:
            return self.selected
        self.state["commands"].append("LOGIN <redacted>" if command.startswith("LOGIN ") else command)
        persistent = command.startswith(("DBADDSAFE ", "DBSET ", "DBSETSAFE ", "DBSETXML ",
                                         "PP SAVE ", "PP SAVE_TO_SOURCE "))
        staging = command.startswith(("PP SET ", "PP RESET_TO_DEFAULTS ", "PP NEW "))
        previous_staging, previous_outcome = self.state["staging_uncertain"], self.state["outcome_uncertain"]
        row = None
        if persistent or staging:
            row = {"command": command, "attempted": True, "confirmed": False}
            if document is not None:
                row["document_sha256"] = hashlib.sha256(document.encode()).hexdigest()
            self.state["writes" if persistent else "staging_writes"].append(row)
            self.state["outcome_uncertain"] = True
            if staging:
                self.state["staging_uncertain"] = True
        try:
            response = (self.client.command(command) if document is None
                        else self.client.command_document(command, document))
        except CGateError as error:
            # These ADD refusals have an atomic no-allocation contract. A
            # rejected SAVE or other write is not proof that nothing happened.
            if command.startswith("DBADDSAFE ") and error.response.code in (401, 408, 420):
                self.state["outcome_uncertain"] = self.state["staging_uncertain"]
            if staging:
                row["refusal_code"] = error.response.code
            raise
        if persistent or staging:
            row["confirmed"] = True
            if staging:
                self.state["staging_uncertain"] = previous_staging
                self.state["outcome_uncertain"] = previous_outcome
            else:
                self.state["outcome_uncertain"] = self.state["staging_uncertain"]
        if command == "PROJECT USE " + self.project:
            self.selected = response
        return response


def _document(client, project):
    raw = xml_text(NativeDatabase(client).get("//" + project, xml=True)).encode()
    if len(raw) > 4 * 1024 * 1024:
        raise ValueError("Project XML exceeds the database document limit")
    document = ProjectDocument.from_bytes(raw)
    if _field(document.project, "Address") != project:
        raise ValueError("Project readback differs from the selected project")
    return raw, document


def _closed(client, document, project):
    addresses = set()
    for node in _elements(document.project, "Network"):
        address = _field(node, "Address")
        _token(address, "Network Address")
        if address in addresses or any(c in address for c in "/#<>"):
            raise ValueError("Ambiguous project Network Address")
        addresses.add(address)
        path = "//" + project + "/" + address
        response = client.command("GET " + path + " *")
        values = {}
        for code, message in _rows(response):
            match = re.fullmatch(re.escape(path) + r": ([^=]+)=(.*)", message)
            if code != 300 or match is None or match[1] in values:
                raise ValueError("Malformed Network state readback")
            values[match[1]] = match[2]
        if any(values.get(k) != v for k, v in (("InterfaceState", "closed"),
                ("TargetInterfaceState", "closed"), ("SyncState", "idle"))):
            raise ValueError("Every project Network must be closed and idle")


def execute(prepared, client, state, *, before_add=None):
    p = prepared
    client = _Client(client, state, p.project)
    database, programmer = NativeDatabase(client), Programmer(client)
    if p.auth_token is not None:
        try:
            if client.command("LOGIN " + p.auth_token).code != 200:
                raise RuntimeError("Authentication did not return the required 200 receipt")
        except CGateError as error:
            raise RuntimeError("Authentication was refused before the tweaker workflow") from error
    client.command("PROJECT USE " + p.project)
    state["phase"] = "preview"
    before, baseline = _document(client, p.project)
    _closed(client, baseline, p.project)
    network_address = p.network.rsplit("/", 1)[1]
    network = baseline.resolve("/network/" + network_address)
    source_node = baseline.resolve("/network/" + network_address + "/unit/" + p.source.rsplit("/", 1)[1])
    for unit in _elements(network, "Unit"):
        address = _field(unit, "Address")
        try:
            numeric = int(address, 10)
        except ValueError as error:
            raise ValueError("Ambiguous existing Unit address") from error
        if numeric == p.address:
            raise ValueError("Replacement address is occupied, including numeric aliases")
    source_firmware = _field(source_node, "FirmwareVersion")
    if _field(source_node, "UnitType").upper() != p.source_type or not p.source_spec.supports_version(source_firmware):
        raise ValueError("Source type/firmware differs from the supplied profile")
    if (tweakers.lookup(p.source_type, p.target_type) in (tweakers.KEY_TWEAKER, tweakers.input_unit.INPUT_TWEAKER)
            and source_firmware != "1.2.67"):
        raise ValueError("This tweaker requires source firmware 1.2.67")
    if (tweakers.lookup(p.source_type, p.target_type) in tweakers.dlt.TWEAKERS
            and source_firmware != tweakers.dlt.source_firmware(p.source_type)):
        raise ValueError("DLT source firmware differs from the recovered profile")
    with programmer.load(p.network, "/db" + p.source) as session:
        source_values = session.values()
        if session.unit_type.upper() != p.source_type or session.firmware != source_firmware:
            raise ValueError("Source PP identity differs from project XML")
    plan = tweakers.plan_writes(p.source_type, p.target_type, source_values,
                               set(p.target_spec.parameters), target_firmware=p.firmware)
    with programmer.new(p.network, p.target_type, p.firmware, catalog_number=p.catalog) as session:
        defaults = session.values()
    if set(defaults) != set(p.target_spec.parameters):
        raise ValueError("Native target PP schema differs from the supplied specification")
    # NativeDatabase.create_unit's initial target context, without persisting it.
    for name, value in (("UnitAddress", str(p.address)), ("Project", p.project)):
        if name in defaults:
            normalized = tweakers.staged(p.target_spec.parameters[name], defaults[name], value)
            defaults[name] = normalized if isinstance(normalized, str) else " ".join(map(str, normalized))
    expected = tweakers.expected_values(p.target_spec, defaults, plan)
    staged_values, assignments = dict(defaults), []
    for name, value, origin in plan.writes:
        staged = tweakers.staged(p.target_spec.parameters[name], staged_values[name], value)
        submitted = staged if isinstance(staged, str) else " ".join(map(str, staged))
        assignments.append({"parameter": name, "planned_value": value, "submitted_value": submitted, "origin": origin})
        staged_values[name] = submitted
    binding = {"endpoint": {"host": client.host, "port": client.port},
               "source": p.source, "target": p.network + "/p/" + str(p.address),
               "source_type": p.source_type, "target_type": p.target_type,
               "target_firmware": p.firmware, "target_catalog": p.catalog, "tag_name": p.tag_name,
               "project_sha256": hashlib.sha256(before).hexdigest(), "specifications": p.spec_pins,
               "source_pp": source_values, "target_defaults": defaults, "tweaker": plan.as_dict(),
               "assignments": assignments, "expected_parameters": deepcopy(expected)}
    if p.metadata is not None:
        binding["metadata"] = deepcopy(p.metadata)
    if p.plan_context is not None:
        binding["lifecycle"] = deepcopy(p.plan_context)
    state["plan"], state["plan_sha256"] = binding, _digest(binding)
    if _document(client, p.project)[0] != before:
        raise ValueError("Project changed during preview")
    if not p.apply:
        state["phase"] = "preview_complete"
        return state, 0
    if state["plan_sha256"] != p.expected_plan:
        raise ValueError("Fresh plan differs from --expect-plan-sha256; no database edit attempted")
    for name, digest in p.spec_pins.items():
        if hashlib.sha256(_snapshot(p.spec_directory / name, MAX_SPEC_BYTES)).hexdigest() != digest:
            raise ValueError("Specification changed after planning")
    _closed(client, baseline, p.project)
    if _document(client, p.project)[0] != before:
        raise ValueError("Project changed before Unit ADD")
    if before_add is not None:
        before_add(client, binding, before, baseline)
    state["phase"] = "add"
    response = database.add(p.network, "unit", p.address, p.tag_name)
    state["created"] = True
    state["outcome_uncertain"] = True
    match = re.fullmatch(r"301 OID=([0-9a-fA-F-]{36})", response.final)
    if response.code != 301 or match is None:
        raise RuntimeError("Unit ADD did not bind a native creation OID")
    oid = match[1]
    try:
        if str(uuid.UUID(oid)) != oid.lower():
            raise ValueError("noncanonical UUID")
    except ValueError as error:
        raise RuntimeError("Unit ADD returned an invalid UUID") from error
    existing = {"".join(c.data for c in node.childNodes if c.nodeType == Node.TEXT_NODE).casefold()
                for node in baseline.document.getElementsByTagName("*") if node.localName == "OID"}
    existing.update(value.casefold() for node in baseline.document.getElementsByTagName("*")
                    for name, value in node.attributes.items() if name.rsplit(":", 1)[-1].casefold() == "oid")
    target = binding["target"]
    if oid.casefold() in existing or _unit_identity(xml_text(database.get(target, xml=True)).encode()) != oid:
        raise RuntimeError("New Unit OID is reused or did not resolve at its exact address")
    state["oid"] = oid
    state["outcome_uncertain"] = False
    state["phase"] = "initialize"
    fields = (("OID", oid), ("TagName", p.tag_name), ("Address", str(p.address)),
              ("UnitType", p.target_type), ("UnitName", p.target_type), ("SerialNumber", ""),
              ("FirmwareVersion", p.firmware), ("CatalogNumber", p.catalog))
    if p.metadata is not None:
        fields = tuple((name, p.metadata.get(name, value)) for name, value in fields)
        fields += tuple((name, value) for name, value in p.metadata.items() if name not in dict(fields))
    # Scalar initialization does not re-admit a whole numeric Network, which
    # could reject or normalize a retained raw/opaque sibling. Set TagName
    # last: legacy UnitName projection can otherwise replace the ADD label.
    for name, value in (("UnitType", p.target_type), ("UnitName", p.target_type),
                        ("FirmwareVersion", p.firmware), ("CatalogNumber", p.catalog), ("TagName", p.tag_name)):
        if p.metadata is not None:
            value = p.metadata.get(name, value)
        if database.set(target + "/" + name, value).code != 200:
            state["outcome_uncertain"] = True
            raise RuntimeError("Unexpected database initializer receipt")
    if p.metadata is not None:
        for name in ("SerialNumber", "Description"):
            value = p.metadata.get(name, "")
            # The recovered agent uses DBSET, including empty metadata tails.
            if client.command("DBSET " + target + "/" + name + (" " + _tail(value) if value else "")).code != 200:
                state["outcome_uncertain"] = True
                raise RuntimeError("Unexpected metadata initializer receipt")
    with programmer.load(p.network, "/db" + target) as session:
        session.reset_defaults()
        native_defaults = session.values()
        for name, value in (("UnitAddress", str(p.address)), ("Project", p.project)):
            if name in native_defaults:
                session.set(name, value)
        native_defaults = session.values()
        if {n: tweakers.normalized(p.target_spec.parameters[n], v) for n, v in native_defaults.items()} != {
                n: tweakers.normalized(p.target_spec.parameters[n], v) for n, v in defaults.items()}:
            raise ValueError("Created Unit defaults differ from the reviewed plan")
        for planned in binding["assignments"]:
            # The original hook values remain in the immutable plan. Submit
            # their exact native schema effect, including bounded arrays and
            # retained partial-array tails, rather than relying on a sparse
            # modeled server to perform the same normalization on PP SET.
            name, submitted = planned["parameter"], planned["submitted_value"]
            assignment = planned | {"confirmed": False}
            state["assignments"].append(assignment)
            try:
                session.set(name, submitted)
            except (CGateError, ProgrammingCommandError) as error:
                if ((isinstance(error, CGateError) and error.response.code >= 500)
                        or (isinstance(error, ProgrammingCommandError) and any(code >= 500 for code, _ in error.errors))):
                    state["outcome_uncertain"] = True
                    state["staging_uncertain"] = True
                    raise
                state["failed_writes"][name] = str(error)
                expected[name] = tweakers.normalized(p.target_spec.parameters[name], native_defaults[name])
            else:
                assignment["confirmed"] = True
                native_defaults[name] = submitted
        state["phase"] = "pp_save"
        if session.save_to_source().code != 200:
            state["outcome_uncertain"] = True
            raise RuntimeError("Unexpected PP save receipt")
        state["applied"] = True
    state["phase"] = "readback"
    with programmer.load(p.network, "/db" + target) as session:
        readback = {n: tweakers.normalized(p.target_spec.parameters[n], v) for n, v in session.values().items()}
    if readback != expected:
        raise RuntimeError("Fresh target PP readback differs from the tweaker plan")
    state["staging_uncertain"] = state["outcome_uncertain"] = False
    after, final = _document(client, p.project)
    new = final.resolve("/network/" + network_address + "/unit/" + str(p.address))
    if any(_field(new, name) != value for name, value in fields):
        raise RuntimeError("Replacement database identity differs from the reviewed creation")
    new.parentNode.removeChild(new)
    if _shape(final.document.documentElement) != _shape(baseline.document.documentElement):
        raise RuntimeError("Source or unrelated project data changed")
    complete = not state["failed_writes"]
    state.update(accepted=complete, phase="complete", verified_parameters=len(expected),
                 planned_assignments_complete=complete, verified_expected_parameters=expected,
                 unrelated_project_preserved=True, after_project_sha256=hashlib.sha256(after).hexdigest())
    if _digest(state["plan"]) != state["plan_sha256"]:
        raise RuntimeError("Reviewed plan changed during execution")
    return state, int(not complete)
