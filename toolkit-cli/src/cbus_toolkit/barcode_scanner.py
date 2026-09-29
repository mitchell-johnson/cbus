"""Toolkit 1.18.0.2754 barcode-scanner rules recovered from the original executable.

Toolkit has no barcode protocol of its own. The scanner is a USB keyboard wedge
(help 4595): ``TfrmBarcode`` appends every WM_CHAR except carriage return to a
buffer and closes itself 75 ms after the last keystroke. Two consumers then
interpret the text:

* **Units view, F10** (``TfrmKipperMain.ProcessBarCode``): a text of at least 28
  characters is a *software configuration* code. Characters 1..16, trimmed, are
  the catalogue field and characters 17.. , trimmed, are the serial. Separately,
  a text starting with ``0`` is looked up as an existing serial.
* **Unit dialog, F10** (``CIS_TfrmSoftwareLabel.IsSerialNumber``): a 12
  character text is a serial; a 28 character text contributes characters 17..
  as the serial and 1..16 as the catalogue number. Texts longer than 28, or
  longer than 10 and starting with the retail ``93`` prefix, are wrong barcodes.

The exact branch constants, messages and emulated vectors are pinned by
``research/barcode_scanner_original.py`` and
``research/fixtures/barcode-scanner-original-vectors.json``. Delphi strings are
UTF-16; this model rejects non-BMP characters instead of guessing code-unit
behavior. See docs/barcode.md for proven and unresolved scope.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable
import xml.etree.ElementTree as ET

# TfrmBarcode (DFM Timer1.Interval, Timer1Timer ``cmp eax, 0x4b; jbe``).
SCAN_IDLE_MS = 75
CARRIAGE_RETURN = "\r"
# TfrmKipperMain.ProcessBarCode / AddUnitByCatalogCode.
SOFTWARE_CONFIG_MIN_LENGTH = 28
CATALOG_FIELD_LENGTH = 16
SERIAL_FIELD_START = 17
SERIAL_LOOKUP_PREFIX = "0"
# AddUnitByCatalogCode rewrites U+00BC before splitting (keyboard-layout artifact).
COMMA_SUBSTITUTE = "¼"
CATALOG_TRUNCATORS = ("-", ",", " ")
# CIS_TfrmSoftwareLabel.IsSerialNumber.
DIALOG_SERIAL_LENGTH = 12
DIALOG_CONFIG_LENGTH = 28
RETAIL_PREFIX = "93"
RETAIL_PREFIX_MIN_EXCLUSIVE = 10
# CIS_CBus.GetDisplayableSerialNumber / FormatSerialNumber.
NO_SERIAL = "No serial #"
UNIDENTIFIED_SERIALS = ("000000000000", "010485754095")
# TfrmKipperMain.AddUnit, TCBUSUnitManager.GetNextAvailableAddress/GetMaximumPossibleAddress.
MAX_DATABASE_UNITS = 255
RECOMMENDED_MAX_UNITS = 100
FIRST_AUTOMATIC_ADDRESS = 1
MAX_POSSIBLE_ADDRESS = 255
# TfrmGetTagName.FormActivate lists every free address 0..254.
DIALOG_ADDRESSES = range(0, 255)
DEFAULT_NAME = "NEWUNIT"
DEFAULT_FIRMWARE = "1.00"
NEW_UNIT_STATE = "New"

# CIS_TKipperErrors registrations (error id -> resource text) used by the paths above.
MESSAGES = {
    2066: "Cannot add a new Unit as there are already 255 Units in the Database.",
    2096: "Unit not found in this Project. Add the unit or select the correct Project and try again.",
    2098: "Unable to add a Unit, Network not selected, please select a Network within a Project",
    2099: "Scanned Unit Type not known",
    2150: "Serial Number was successfully scanned",
    2271: "Cannot create a new Unit.  All available addresses are in use.",
    2300: "Barcode scanning is supported only on the Units node",
    45141: 'The Network "{network}" has more than the recommended maximum of 100 Units. '
           "C-Bus Network errors are likely to occur.",
    45151: "Cannot add Wired Unit to the Wireless C-Bus Network",
    45152: "Cannot add Wireless Unit to the Wired C-Bus Network",
}
WRONG_BARCODE_TEXT = ("To enter the Serial Number using scanner, please locate and scan the barcode "
                      "pictured below. If the box does not have this barcode, please enter the Serial "
                      "Number manually.")
# Registered but referenced by no 1.18.0.2754 code path (see docs/barcode.md).
UNREFERENCED_MESSAGES = {
    2095: "Unable to add or select a Unit, no Project selected",
    2097: 'Wrong barcode scanned, please scan the "Software Config Code"',
}


class BarcodeError(ValueError):
    """Invalid scanner input, catalogue or project state for a barcode workflow."""

    def __init__(self, message: str, *, code: str, message_id: int | None = None, **details: Any) -> None:
        super().__init__(message)
        self.details = {"code": code, **({"toolkit_message_id": message_id} if message_id is not None else {}), **details}


def _delphi_trim(text: str) -> str:
    """SysUtils.Trim: remove every code unit <= U+0020 from both ends."""
    start, end = 0, len(text)
    while start < end and text[start] <= " ":
        start += 1
    while end > start and text[end - 1] <= " ":
        end -= 1
    return text[start:end]


_ASCII_UPPER = {code: code - 32 for code in range(ord("a"), ord("z") + 1)}


def _ascii_upper(text: str) -> str:
    """SysUtils.UpperCase / CompareText fold only ASCII letters."""
    return text.translate(_ASCII_UPPER)


def _check_text(value: Any) -> str:
    if not isinstance(value, str):
        raise TypeError(f"scanner text must be str, got {type(value).__name__}")
    if any(ord(char) > 0xFFFF for char in value):
        raise BarcodeError("Scanner text contains a character outside the Basic Multilingual Plane",
                           code="non_bmp_input")
    return value


def wedge_lines(stream: str) -> list[str]:
    """Split keyboard-wedge text into scans.

    TfrmBarcode drops every carriage return and ends a scan on a 75 ms idle gap,
    which a CLI cannot observe. One line is therefore one scan: LF separates
    scans, CR is removed anywhere, and a line that is empty after that is not a
    scan (the original never completes with an empty buffer).
    """
    _check_text(stream)
    return [line for line in (raw.replace(CARRIAGE_RETURN, "") for raw in stream.split("\n")) if line]


def acquire(events: Iterable[tuple[str, Any, int]]) -> dict[str, Any]:
    """Replay TfrmBarcode keystroke and timer events.

    ``events`` are ``("key", char, tick_ms)``, ``("timer", None, tick_ms)`` or
    ``("escape", None, tick_ms)``. Every key updates the idle tick; CR is not
    buffered. A timer tick closes with mrOk when the buffer is nonempty and more
    than 75 ms elapsed. Escape activates the Cancel button (mrCancel), which
    makes AcquireBarCode return an empty string.
    """
    buffer, last = "", 0
    for kind, value, tick in events:
        if type(tick) is not int or not 0 <= tick <= 0xFFFFFFFF:
            raise BarcodeError("Event tick must be an unsigned 32-bit millisecond count", code="invalid_event")
        if kind == "key":
            if not isinstance(value, str) or len(value) != 1:
                raise BarcodeError("Key events carry exactly one character", code="invalid_event")
            _check_text(value)
            if value != CARRIAGE_RETURN:
                buffer += value
            last = tick
        elif kind == "timer":
            if buffer and ((tick - last) & 0xFFFFFFFF) > SCAN_IDLE_MS:
                return {"completed": True, "modal_result": 1, "barcode": buffer}
        elif kind == "escape":
            return {"completed": False, "modal_result": 2, "barcode": ""}
        else:
            raise BarcodeError(f"Unknown event kind {kind!r}", code="invalid_event")
    return {"completed": False, "modal_result": 0, "barcode": buffer}


def format_serial(text: str, *, dotted: bool) -> str:
    """CIS_CBus.FormatSerialNumber: keep digits and dots, then pad to 8.4 digits."""
    kept = "".join(char for char in _check_text(text) if char == "." or "0" <= char <= "9")
    if "." in kept:
        left, right = kept.split(".", 1)
        left, right = left.rjust(8, "0"), right.rjust(4, "0")
        return f"{left}.{right}" if dotted else left + right
    kept = kept.rjust(12, "0")
    return f"{kept[:-4]}.{kept[-4:]}" if dotted else kept


def displayable_serial(text: str) -> str:
    """CIS_CBus.GetDisplayableSerialNumber (undotted comparison form)."""
    value = format_serial(text, dotted=False)
    return NO_SERIAL if value in UNIDENTIFIED_SERIALS else value


def stored_serial(text: str) -> str:
    """TCBUSUnit.SetSerialNumber: dotted 8.4 form only for a nonempty dotless value."""
    _check_text(text)
    return format_serial(text, dotted=True) if text and "." not in text else text


def serials_match(scanned: str, existing: str) -> bool:
    """TCBUSUnitManager.UnitBySerialNumber equality; unidentified scans never match."""
    wanted = displayable_serial(scanned)
    return wanted != NO_SERIAL and displayable_serial(existing) == wanted


@dataclass(frozen=True)
class SoftwareConfig:
    """AddUnitByCatalogCode's split of a >=28 character software configuration code."""
    barcode: str
    catalog_field: str
    catalog_lookup: str
    serial: str

    def as_dict(self) -> dict[str, str]:
        return {"barcode": self.barcode, "catalog_field": self.catalog_field,
                "catalog_lookup": self.catalog_lookup, "serial": self.serial}


def _split_fields(text: str) -> SoftwareConfig:
    """AddUnitByCatalogCode's field split; the original itself does not check the length."""
    replaced = text.replace(COMMA_SUBSTITUTE, ",")
    field_value = _delphi_trim(replaced[:CATALOG_FIELD_LENGTH])
    lookup = field_value
    for separator in CATALOG_TRUNCATORS:
        if separator in lookup:
            lookup = lookup.split(separator, 1)[0]
    return SoftwareConfig(text, field_value, lookup, _delphi_trim(replaced[SERIAL_FIELD_START - 1:]))


def split_software_config(barcode: str) -> SoftwareConfig:
    text = _check_text(barcode)
    if len(text) < SOFTWARE_CONFIG_MIN_LENGTH:
        raise BarcodeError(f"A software configuration code has at least {SOFTWARE_CONFIG_MIN_LENGTH} characters",
                           code="wrong_barcode")
    return _split_fields(text)


def units_view_actions(barcode: str) -> list[dict[str, Any]]:
    """TfrmKipperMain.ProcessBarCode: both independent branches, in original order."""
    text = _check_text(barcode)
    actions: list[dict[str, Any]] = []
    if len(text) >= SOFTWARE_CONFIG_MIN_LENGTH:
        actions.append({"action": "add_by_catalog_code", **split_software_config(text).as_dict()})
    if text[:1] == SERIAL_LOOKUP_PREFIX:
        actions.append({"action": "find_by_serial", "serial": text, "report_missing": True})
    return actions


def unit_dialog_serial(barcode: str) -> dict[str, Any]:
    """CIS_TfrmSoftwareLabel.IsSerialNumber plus the unit-dialog field updates."""
    text = _check_text(barcode)
    if len(text) > DIALOG_CONFIG_LENGTH or (len(text) > RETAIL_PREFIX_MIN_EXCLUSIVE and text[:2] == RETAIL_PREFIX):
        return {"accepted": False, "reason": "wrong_barcode", "message": WRONG_BARCODE_TEXT}
    serial = text if len(text) == DIALOG_SERIAL_LENGTH else text[SERIAL_FIELD_START - 1:] if len(text) == DIALOG_CONFIG_LENGTH else ""
    if not serial:
        return {"accepted": False, "reason": "wrong_barcode", "message": WRONG_BARCODE_TEXT}
    serial = serial.replace(" ", "")
    result: dict[str, Any] = {"accepted": True, "serial": serial, "stored_serial": stored_serial(serial),
                              "message_id": 2150, "message": MESSAGES[2150]}
    if len(text) == DIALOG_CONFIG_LENGTH:
        result["catalog_number"] = _delphi_trim(text[:CATALOG_FIELD_LENGTH])
    return result


def parse(barcode: str) -> dict[str, Any]:
    """Classify one scan for both original consumers without touching a project."""
    text = _check_text(barcode)
    actions = units_view_actions(text)
    return {"barcode": text, "length": len(text),
            "units_view": {"actions": actions, "ignored": not actions},
            "unit_dialog": unit_dialog_serial(text)}


# ---------------------------------------------------------------------------
# Catalogue lookup (TUnitTypeManager.FindUnitByCatalogCode and helpers)

@dataclass
class CatalogType:
    catalog_number: str
    alternatives: str
    unit_title: str
    revisions: list[dict[str, str]]
    subunits: list[CatalogType] = field(default_factory=list)
    clone: bool = False

    @property
    def unit_code(self) -> str:
        # CalcCategoryAndFamilyName: UnitCode := first FirmwareRevision.UnitType.
        return self.revisions[0].get("UnitType", "") if self.revisions else ""

    @property
    def family(self) -> str:
        return _title_value(self.unit_title, "Family=")


def _title_value(title: str, key: str) -> str:
    index = title.upper().find(key.upper())
    if index < 0:
        return ""
    value = title[index + len(key):]
    return _delphi_trim(value.split(";", 1)[0])


def _own_match(catalog_number: str, code: str) -> bool:
    number = _ascii_upper(catalog_number)
    if "," in number:
        number = number.split(",", 1)[0]
    elif "-" in number:
        number = number.split("-", 1)[0]
    elif "*" in number:
        number = number.split("*", 1)[0]
        if number and code.startswith(number):
            return True
    return number == code


def _alternates_match(alternatives: str, code: str) -> bool:
    """TUnitType.HasCatalogNumberInAlternates, including its original quirks."""
    if not alternatives:
        return False
    if "*" in alternatives:
        prefix = alternatives.split("*", 1)[0]
        while "," in prefix:
            prefix = prefix[prefix.index(",") + 1:]
        if prefix and code.startswith(prefix):
            return True
    if not code or code not in alternatives:
        return False
    pieces, start = [], 1
    for index in range(1, len(alternatives) + 1):
        if index == len(alternatives) or alternatives[index - 1] == ";":
            # The final piece is copied with length len-start, dropping its last character.
            piece = alternatives[start - 1:start - 1 + index - start]
            if piece[:1] == ";":
                piece = piece[1:256]
            if "," in piece:
                piece = piece.split(",", 1)[0]
            pieces.append(piece)
            start = index
    for piece in pieces:
        if _ascii_upper(piece) == _ascii_upper(code):
            return True
        if "*" in piece:
            piece = piece.split("*", 1)[0]
            if piece and code.startswith(piece):
                return True
    return False


class BarcodeCatalog:
    """CBusUnits catalogue arranged as Toolkit's TUnitTypeManager.

    Toolkit loads the same catalogue through ``pp get_unit_catalog`` and then
    appends one clone per ``;``-separated alternative catalogue number of each
    top-level entry (AddAlternativeCatalogNumberUnits).
    """

    def __init__(self, types: list[CatalogType], sha256: str | None = None) -> None:
        self.types = types
        self.sha256 = sha256

    @classmethod
    def load(cls, path: str | Path) -> BarcodeCatalog:
        import hashlib
        raw = Path(path).read_bytes()
        try:
            root = ET.fromstring(raw)
        except ET.ParseError as exc:
            raise BarcodeError(f"Unit catalogue is not well-formed XML: {exc}", code="invalid_catalog") from exc
        if root.tag != "CBusUnits":
            raise BarcodeError("Expected a CBusUnits catalogue", code="invalid_catalog")

        def build(unit: ET.Element) -> CatalogType:
            return CatalogType(
                unit.findtext("CatalogNumber", "") or "",
                unit.findtext("AlternativeCatalogNumbers", "") or "",
                unit.findtext("UnitTitle", "") or "",
                [{child.tag: (child.text or "") for child in revision}
                 for revision in unit.findall("FirmwareRevisions/Revision")],
                [build(child) for child in unit.findall("SubUnits/Unit")])

        types = [build(unit) for unit in root.findall("Units/Unit")]
        clones = []
        for item in types:
            for alternative in item.alternatives.split(";"):
                if alternative:
                    clones.append(CatalogType(alternative, "", item.unit_title, item.revisions, item.subunits, True))
        return cls(types + clones, hashlib.sha256(raw).hexdigest())

    def find(self, catalog_code: str) -> CatalogType | None:
        code = _ascii_upper(catalog_code)

        def search(items: list[CatalogType]) -> CatalogType | None:
            for item in items:
                if _own_match(item.catalog_number, code) or _alternates_match(item.alternatives, code):
                    return item
                found = search(item.subunits)
                if found is not None:
                    return found
            return None

        return search(self.types)

    def default_firmware(self, unit_type: str) -> str:
        """GetDefaultFirmwareForType: the last IsDefault revision of matching top-level types."""
        wanted, result = _ascii_upper(unit_type), DEFAULT_FIRMWARE
        for item in self.types:
            if _ascii_upper(item.unit_code) != wanted:
                continue
            for revision in item.revisions:
                if revision.get("IsDefault", "").strip().lower() == "true":
                    result = revision.get("MinVersion", "")
        return result


# ---------------------------------------------------------------------------
# Offline project creation (TfrmKipperMain.AddUnitByCatalogCode / AddUnit)

def catalog_add_outcome(*, site_open: bool = True, serial_found: bool = False, type_known: bool = True,
                        units_node: bool = True, unit_count: int = 0, network_wireless: bool = False,
                        network_wired: bool = False, family: str = "") -> dict[str, Any]:
    """AddUnitByCatalogCode's branch order over explicit facts, before AddUnit."""
    if not site_open:
        return {"outcome": "ignored"}
    if serial_found:
        return {"outcome": "selected_existing"}
    if not type_known:
        return {"outcome": "error", "message_id": 2099}
    if not units_node:
        return {"outcome": "ignored"}
    if unit_count >= MAX_DATABASE_UNITS:
        return {"outcome": "error", "message_id": 2066}
    family_wireless = "wireless" in family.lower()
    if network_wireless and not network_wired and not family_wireless:
        return {"outcome": "error", "message_id": 45151}
    if network_wired and not network_wireless and family_wireless:
        return {"outcome": "error", "message_id": 45152}
    return {"outcome": "add"}


_ERROR_CODES = {2099: "unknown_unit_type", 2066: "database_full", 45151: "wired_unit_on_wireless_network",
                45152: "wireless_unit_on_wired_network"}


def _is_wireless_type(unit_type: str) -> bool:
    from .project_topology import is_wireless_unit_type
    return is_wireless_unit_type(unit_type)


def add_unit(document: Any, network: str, barcode: str, catalog: BarcodeCatalog, *,
             address: int | None = None, tag_name: str | None = None) -> dict[str, Any]:
    """Apply one Units-view scan to an offline legacy project.

    Mirrors the original branch order. A serial already present in any project
    network selects that unit and adds nothing. ``address`` replaces the Tag
    Name dialog's address choice; ``tag_name`` replaces its Tag field.
    """
    from .project import ProjectError, _address, _elements, _field, _is_entity, _name

    text = _check_text(barcode)
    actions = units_view_actions(text)
    if not actions:
        raise BarcodeError("Toolkit ignores this scan in the Units view: it is shorter than 28 characters "
                           "and does not start with 0", code="wrong_barcode", barcode=text)
    try:
        network_node = document.resolve(network)
    except ProjectError as exc:
        raise BarcodeError(MESSAGES[2098], code="network_not_selected", message_id=2098, network=network) from exc
    if _name(network_node) != "Network":
        raise BarcodeError(MESSAGES[2300], code="not_units_node", message_id=2300, network=network)

    def all_units() -> list[Any]:
        return [unit for net in _elements(document.project, "Network") if _is_entity(net)
                for unit in _elements(net, "Unit") if _is_entity(unit)]

    def lookup(serial: str) -> Any | None:
        return next((unit for unit in all_units() if serials_match(serial, _field(unit, "SerialNumber"))), None)

    result: dict[str, Any] = {"barcode": text, "network": document.path_of(network_node), "changed": False,
                              "catalog_sha256": catalog.sha256}
    warnings: list[dict[str, Any]] = []
    for action in actions:
        if action["action"] == "find_by_serial":
            found = lookup(action["serial"])
            result["serial_lookup"] = {"serial": action["serial"], "found": document.path_of(found) if found is not None else None}
            if found is None:
                warnings.append({"toolkit_message_id": 2096, "message": MESSAGES[2096]})
            elif "unit" not in result:
                result.update(action="selected_existing", unit=document.path_of(found))
            continue
        config = split_software_config(text)
        result["software_config"] = config.as_dict()
        existing = lookup(config.serial)
        if existing is not None:
            result.update(action="selected_existing", unit=document.path_of(existing), duplicate_serial=True)
            continue
        unit_type = catalog.find(config.catalog_lookup)
        if unit_type is None:
            raise BarcodeError(MESSAGES[2099], code="unknown_unit_type", message_id=2099,
                               catalog_lookup=config.catalog_lookup)
        if not unit_type.unit_code:
            # Toolkit would create a unit with an empty UnitType; refuse instead.
            raise BarcodeError("Catalogue entry has no firmware revision UnitType", code="catalog_entry_without_type",
                               catalog_lookup=config.catalog_lookup)
        units = [unit for unit in _elements(network_node, "Unit") if _is_entity(unit)]
        types = [_field(unit, "UnitType") for unit in units]
        outcome = catalog_add_outcome(unit_count=len(units), family=unit_type.family,
                                      network_wireless=any(_is_wireless_type(value) for value in types),
                                      network_wired=any(not _is_wireless_type(value) for value in types))
        if outcome["outcome"] == "error":
            identifier = outcome["message_id"]
            raise BarcodeError(MESSAGES[identifier], code=_ERROR_CODES[identifier], message_id=identifier)
        used = {_address(_field(unit, "Address")) for unit in units}
        automatic = next((value for value in range(FIRST_AUTOMATIC_ADDRESS, MAX_POSSIBLE_ADDRESS + 1)
                          if value not in used), None)
        if automatic is None:
            raise BarcodeError(MESSAGES[2271], code="no_free_address", message_id=2271)
        chosen = automatic if address is None else address
        if address is not None and address != automatic and (address not in DIALOG_ADDRESSES or address in used):
            raise BarcodeError("Address is not offered by the Tag Name dialog: it must be free and in 0..254, "
                               "or the automatic address", code="address_unavailable", address=address,
                               automatic_address=automatic)
        name = DEFAULT_NAME if tag_name is None else tag_name
        fields = {"UnitType": unit_type.unit_code, "SerialNumber": stored_serial(config.serial),
                  "CatalogNumber": config.catalog_field,
                  "FirmwareVersion": catalog.default_firmware(unit_type.unit_code),
                  "UnitName": DEFAULT_NAME, "State": NEW_UNIT_STATE}
        created = document.add("unit", document.path_of(network_node), address=chosen, name=name, fields=fields)
        result.update(action="added", changed=True, unit=created["path"], automatic_address=automatic,
                      address=chosen, tag_name=name, fields=fields,
                      catalog_entry={"catalog_number": unit_type.catalog_number, "clone": unit_type.clone,
                                     "family": unit_type.family})
        if len(units) + 1 > RECOMMENDED_MAX_UNITS:
            warnings.append({"toolkit_message_id": 45141,
                             "message": MESSAGES[45141].format(network=_field(network_node, "TagName"))})
    result["warnings"] = warnings
    return result
