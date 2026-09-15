"""C-Gate-backed unit programming workflows.

The native backend performs device-specific decoding, defaults and validation.
Database addresses (``/db//PROJECT/254/p/20``) keep load/save operations offline;
live addresses can communicate with hardware and must be chosen explicitly.
Context managers acquire a lock and session, then attempt to end and unlock on
exit while the connection remains usable. Interrupted cleanup retains the
original failure and uncertain resources; it never reconnects or saves edits.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any, Iterable, Mapping, Protocol
from uuid import uuid4


class CommandClient(Protocol):
    def command(self, command: str) -> Any: ...


class ProgrammingError(RuntimeError):
    """Invalid workflow, malformed response or failed native programming operation."""


class NativeCommandLimitation(ProgrammingError):
    """The vendor's command grammar cannot represent a catalogue field."""


class ProgrammingCommandError(ProgrammingError):
    def __init__(self, reply: Any, errors: list[tuple[int, str]]) -> None:
        self.reply = reply
        self.errors = errors
        super().__init__("; ".join(f"{code}: {message}" for code, message in errors))


class ProgrammingCleanupError(ProgrammingError):
    def __init__(self, errors: list[BaseException]) -> None:
        self.errors = errors
        super().__init__("Unable to clean up programming resources: " + "; ".join(str(error) for error in errors))


def _token(value: Any, label: str = "argument") -> str:
    if not isinstance(value, str) or not value or any(character.isspace() or ord(character) < 32 or character in '"\x7f' for character in value):
        raise ProgrammingError(f"{label} must be one nonempty C-Gate token without whitespace or quotes")
    return value


def _parameter_name(value: Any) -> str:
    if not isinstance(value, str) or not value or any(ord(character) < 32 or character in '\"\x7f' for character in value):
        raise ProgrammingError("Parameter name must be nonempty text without control characters or quotes")
    return value


def _integer_value(value: str) -> int:
    if not isinstance(value, str) or not re.fullmatch(r"[+-]?(?:0[xX][0-9A-Fa-f]+|\$[0-9A-Fa-f]+|[0-9]+)", value):
        raise ProgrammingError("Expected one integer parameter value")
    sign = -1 if value.startswith("-") else 1
    text = value.lstrip("+-")
    return sign * int(text[1:] if text.startswith("$") else text,
                      16 if text.startswith("$") or text.lower().startswith("0x") else 10)


def _xml_parameters(reply: Any) -> list[ET.Element]:
    document = xml_text(reply)
    if "<!DOCTYPE" in document or "<!ENTITY" in document:
        raise ProgrammingError("Native parameter XML contains unsupported declarations")
    try:
        root = ET.fromstring(document)
    except ET.ParseError as error:
        raise ProgrammingError("Malformed native parameter XML") from error
    return [element for element in root.iter() if element.tag == "Param"]


def quote_value(value: str) -> str:
    """Quote the PP SET tail using C-Gate mK's documented dequoting escapes.

    Escaped spaces survive C-Gate's whitespace tokenizer, including repeated
    internal spaces. Leading/trailing whitespace can still be normalized by the
    backend's parameter implementation, and responses retain its actual result.
    """
    if not isinstance(value, str) or any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ProgrammingError("Parameter text must be a string without control characters")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace(" ", "\\ ") + '"'


def database_address(address: str) -> str:
    """Turn an explicit C-Gate unit/database path into its offline PP address."""
    address = _token(address, "database address")
    if address.lower().startswith("/db/"):
        return address
    return "/db/" + (address[1:] if address.startswith("//") else address)


def _rows(reply: Any) -> list[tuple[int, str]]:
    """Accept CGateReply lines and simple string-based transports for embedding."""
    lines = getattr(reply, "lines", None)
    if lines is None:
        lines = reply.splitlines() if isinstance(reply, str) else []
    rows = []
    for line in lines:
        if isinstance(line, str):
            match = re.match(r"(?:\[[^\]]+\]\s*)?(\d{3})[- ](.*)", line)
            if match:
                rows.append((int(match.group(1)), match.group(2)))
        elif hasattr(line, "code"):
            rows.append((int(line.code), str(getattr(line, "text", getattr(line, "message", "")))))
    return rows


def parameter_values(reply: Any) -> dict[str, str]:
    values = {}
    for code, message in _rows(reply):
        if code != 315:
            continue
        name, separator, value = message.partition("=")
        if not separator or not name:
            raise ProgrammingError("Malformed native parameter response")
        if name in values:
            raise ProgrammingError(f"Native response contains duplicate parameter {name!r}")
        values[name] = value
    return values


def xml_text(reply: Any) -> str:
    lines = [message for code, message in _rows(reply) if code == 347]
    if not lines:
        raise ProgrammingError("Native response does not contain an XML snippet")
    return "\n".join(lines)


class Programmer:
    def __init__(self, client: CommandClient) -> None:
        self.client = client

    def _run(self, command: str) -> Any:
        reply = self.client.command(command)
        errors = [(code, message) for code, message in _rows(reply) if code >= 400]
        if errors:
            raise ProgrammingCommandError(reply, errors)
        if getattr(reply, "code", 200) >= 400:
            raise ProgrammingCommandError(reply, [(reply.code, "Native operation failed")])
        return reply

    def session(self, lock_address: str, *, name: str | None = None, lock_name: str | None = None) -> ProgrammingSession:
        return ProgrammingSession(self, _token(lock_address, "lock address"), name=name, lock_name=lock_name)

    def new(self, lock_address: str, unit_type: str, firmware: str, *, catalog_number: str | None = None, name: str | None = None, lock_name: str | None = None) -> ProgrammingSession:
        session = self.session(lock_address, name=name, lock_name=lock_name)
        session._initialize = ("new", (unit_type, firmware), {"catalog_number": catalog_number})
        return session

    def load(self, lock_address: str, source: str, *, tags: Iterable[str] = (), name: str | None = None, lock_name: str | None = None) -> ProgrammingSession:
        session = self.session(lock_address, name=name, lock_name=lock_name)
        session._initialize = ("load", (source,), {"tags": tuple(tags)})
        return session

    def lock(self, name: str, address: str) -> Any:
        return self._run(f"PP LOCK {_token(name, 'lock name')} {_token(address, 'lock address')}")

    def unlock(self, name: str) -> Any:
        return self._run(f"PP UNLOCK {_token(name, 'lock name')}")

    def cancel_lock(self, address: str) -> Any:
        """Explicitly cancel a lock by address (does not imply ownership)."""
        return self._run(f"PP CANCEL_LOCK {_token(address, 'lock address')}")

    def list_locks(self) -> Any:
        return self._run("PP LIST_LOCK")

    def units(self) -> Any:
        return self._run("PP UNITS")

    def get_unit_spec(self, filename: str) -> Any:
        return self._run(f"PP GET_UNIT_SPEC {_token(filename, 'unit specification filename')}")

    def get_unit_catalog(self) -> Any:
        return self._run("PP GET_UNIT_CATALOG")

    def reload_catalog(self) -> Any:
        return self._run("PP RELOAD_CATALOG")

    def catalog_info(self) -> Any:
        return self._run("PP CATALOG_INFO")

    def list_catalog_numbers(self, unit_type: str, firmware: str) -> Any:
        return self._run(f"PP LIST_CATALOG_NUMBERS {_token(unit_type, 'unit type')} {_token(firmware, 'firmware')}")

    def patch_version(self, *, debug: bool = False) -> Any:
        return self._run("PP PATCH_VERSION" + (" debug" if debug else ""))

    def write_patch(self, address: str, version: int, *, simulate: bool = False) -> Any:
        """Request the backend's patch operation; the caller chooses its target."""
        if isinstance(version, bool) or not isinstance(version, int) or not 0 <= version <= 255:
            raise ProgrammingError("Patch version must be an integer from 0 to 255")
        return self._run(f"PP WRITE_PATCH {_token(address, 'unit address')} {version:02x}" + (" simulate" if simulate else ""))

    def quickget(self, database_unit: str, parameter: str = "*") -> Any:
        return self._run(f"PP QUICKGET {_token(database_unit, 'database unit')} {_token(parameter, 'parameter')}")

    def copy(self, lock_name: str, source: str, destination: str, *, tags: Iterable[str] = ()) -> Any:
        return self._run(f"PP COPY {_token(lock_name, 'lock name')} {_token(source, 'source')} {_token(destination, 'destination')}" + _tags(tags))


def _tags(tags: Iterable[str]) -> str:
    if isinstance(tags, str):
        raise ProgrammingError("Tags must be a sequence of strings, not one string")
    values = [quote_value(tag) for tag in tags]
    return " " + " ".join(values) if values else ""


class ProgrammingSession:
    def __init__(self, programmer: Programmer, lock_address: str, *, name: str | None = None, lock_name: str | None = None) -> None:
        self.programmer = programmer
        self.lock_address = lock_address
        identifier = uuid4().hex[:16]
        self.name = _token(name or "cbus_cli_" + identifier, "session name")
        self.lock_name = _token(lock_name or self.name + "_lock", "lock name")
        self._locked = False
        self._started = False
        self._initialize: tuple[str, tuple, dict] | None = None
        self.cleanup_errors: list[BaseException] = []
        self.source: str | None = None
        self.unit_type: str | None = None
        self.firmware: str | None = None
        self.catalog_number: str | None = None

    def __enter__(self) -> ProgrammingSession:
        self.open()
        return self

    def __exit__(self, exception_type, exception, traceback) -> bool:
        errors = self._cleanup()
        if errors and exception is None:
            self._raise_cleanup(errors)
        if errors and exception is not None:
            # Keep the operation/body failure primary while making leaked-resource
            # details available on Python 3.10 as well as newer runtimes.
            try:
                exception.programming_cleanup_errors = errors
            except Exception:
                pass
        return False

    def open(self) -> ProgrammingSession:
        if self._locked or self._started:
            raise ProgrammingError("Programming session is already open")
        # C-Gate associates some native operations with the command connection's
        # current project even when the lock uses a fully qualified address.
        project_match = re.match(r"^//([^/]+)/", self.lock_address)
        if project_match:
            self.programmer._run("PROJECT USE " + _token(project_match.group(1), "project name"))
        self.programmer.lock(self.lock_name, self.lock_address)
        self._locked = True
        try:
            self.programmer._run(f"PP START {self.name} {self.lock_name}")
            self._started = True
            if self._initialize is not None:
                method, args, kwargs = self._initialize
                getattr(self, method)(*args, **kwargs)
        except BaseException as error:
            cleanup_errors = self._cleanup()
            if cleanup_errors:
                try:
                    error.programming_cleanup_errors = cleanup_errors
                except Exception:
                    pass
            raise
        return self

    @staticmethod
    def _raise_cleanup(errors: list[BaseException]) -> None:
        # Cancellation during cleanup remains cancellation when there is no
        # earlier body/initialization failure to preserve.
        interrupted = next((error for error in errors if not isinstance(error, Exception)), None)
        if interrupted is not None:
            interrupted.programming_cleanup_errors = errors
            raise interrupted
        raise ProgrammingCleanupError(errors)

    def _cleanup(self) -> list[BaseException]:
        errors = []
        for attribute, command in (("_started", f"PP END {self.name}"),
                                   ("_locked", f"PP UNLOCK {self.lock_name}")):
            if not getattr(self, attribute):
                continue
            if not getattr(self.programmer.client, "connected", True):
                errors.append(ProgrammingError("Connection lost; programming cleanup stopped without I/O; session or lock state is uncertain"))
                break
            try:
                if attribute == "_locked":
                    self.programmer.unlock(self.lock_name)
                else:
                    self.programmer._run(command)
                setattr(self, attribute, False)
            except BaseException as error:
                errors.append(error)
                if not isinstance(error, Exception):
                    break
        self.cleanup_errors = errors
        return errors

    def close(self) -> None:
        errors = self._cleanup()
        if errors:
            self._raise_cleanup(errors)

    end = close

    def _run(self, operation: str, tail: str = "") -> Any:
        if not self._started:
            raise ProgrammingError("Programming session is not open")
        return self.programmer._run(f"PP {operation} {self.name}" + (" " + tail if tail else ""))

    def new(self, unit_type: str, firmware: str, *, catalog_number: str | None = None) -> Any:
        if isinstance(unit_type, str) and " " in unit_type and all(ord(character) >= 32 and character not in '\"\x7f' for character in unit_type):
            raise NativeCommandLimitation("C-Gate PP NEW cannot represent a UnitType containing spaces: " + repr(unit_type))
        tail = _token(unit_type, "unit type") + " " + _token(firmware, "firmware")
        if catalog_number is not None:
            tail += " " + _token(catalog_number, "catalog number")
        reply = self._run("NEW", tail)
        self.unit_type, self.firmware, self.catalog_number = unit_type, firmware, catalog_number
        self.source = None
        return reply

    def load(self, source: str, *, tags: Iterable[str] = ()) -> Any:
        reply = self._run("LOAD", _token(source, "source") + _tags(tags))
        self.source = source
        self.unit_type = self.firmware = self.catalog_number = None
        if source.lower().startswith("/db/"):
            path = source[4:]
            if path.startswith("/"):
                path = "/" + path
            fields = {}
            for code, message in _rows(self.programmer._run("DBGET " + _token(path, "database source"))):
                if code != 342:
                    continue
                name, separator, value = message.partition("=")
                name = name.rsplit("/", 1)[-1]
                if separator and name in ("UnitType", "FirmwareVersion", "CatalogNumber"):
                    if name in fields:
                        raise ProgrammingError("Database source returned duplicate unit identity fields")
                    fields[name] = None if value == "null" else value
            if not fields.get("UnitType") or not fields.get("FirmwareVersion"):
                raise ProgrammingError("Database source did not provide unit type and firmware identity")
            self.unit_type, self.firmware = fields["UnitType"], fields["FirmwareVersion"]
            self.catalog_number = fields.get("CatalogNumber") or None
        return reply

    def load_from_file(self, filename: str) -> Any:
        """Load defaults from a server-side unit-spec file, not a saved session."""
        reply = self._run("LOAD_FROM_FILE", _token(filename, "unit specification filename"))
        self.source = self.unit_type = self.firmware = self.catalog_number = None
        return reply

    def save(self, destination: str, *, tags: Iterable[str] = ()) -> Any:
        destination = _token(destination, "destination")
        suffix = _tags(tags)
        if not self._started:
            raise ProgrammingError("Programming session is not open")
        if self.source is None:
            self._bind_new_database_destination(destination)
        return self._run("SAVE", destination + suffix)

    def _bind_new_database_destination(self, destination: str) -> None:
        """Work around the native NEW -> SAVE null-source defect without SQL edits.

        C-Gate database SAVE serializes named PP values. Preserve those native
        values (including raw edits reflected in parameters), bind the existing
        database unit, and restore them before saving. Unmapped memory is not a
        database PP and is not part of this operation's serialized output.
        """
        if not destination.lower().startswith("/db/"):
            raise ProgrammingError("A new session must first save to a database destination; load a live unit before programming hardware")
        if self.unit_type is None or self.firmware is None:
            raise ProgrammingError("A session loaded only from a specification file has no unit type/firmware; use new or load before saving")
        path = destination[4:]
        if path.startswith("/"):
            path = "/" + path
        # PP LOAD would replace the schema, so check compatibility first rather
        # than letting a destination silently choose another unit definition.
        for field, expected in (("UnitType", self.unit_type), ("FirmwareVersion", self.firmware)):
            reply = self.programmer._run(f"DBGET {_token(path, 'database destination')}/{field}")
            fields = [message.partition("=") for code, message in _rows(reply) if code == 342]
            if len(fields) != 1 or not fields[0][1] or fields[0][2] != expected:
                raise ProgrammingError(f"Destination {field} does not match the new programming session")
        if self.catalog_number is not None:
            reply = self.programmer._run(f"DBGET {_token(path, 'database destination')}/CatalogNumber")
            values = [message.partition("=")[2] for code, message in _rows(reply) if code == 342 and "=" in message]
            if len(values) != 1:
                raise ProgrammingError("Destination CatalogNumber could not be determined")
            if values[0] not in ("", "null", self.catalog_number):
                raise ProgrammingError("Destination CatalogNumber does not match the new programming session")
        snapshot = self.export_parameters()
        self.load(destination)
        self.import_parameters(snapshot)
        self.unit_type = snapshot["unit_type"]
        self.firmware = snapshot["firmware"]
        self.catalog_number = snapshot["catalog_number"]

    def save_to_source(self, *, tags: Iterable[str] = ()) -> Any:
        if self.source is None:
            raise ProgrammingError("This programming session has no loaded source; save to an explicit database destination first")
        return self._run("SAVE_TO_SOURCE", _tags(tags).lstrip())

    def set(self, parameter: str, value: str) -> Any:
        parameter = _parameter_name(parameter)
        quoted = quote_value(value)
        if any(character.isspace() for character in parameter):
            return self._set_spaced_parameter(parameter, value)
        return self._run("SET", _token(parameter, "parameter") + " " + quoted)

    def _spaced_parameter_data(self, parameter: str, value: str) -> tuple[int, bytes]:
        # C-Gate 3.4 PP SET tokenizes names without unescaping. Its own catalogue
        # contains "EEPROM Checksum", which only GET */INFO * can name. Use the
        # native spec to stage a full byte without guessing or touching neighbors.
        matches = [element for element in _xml_parameters(self._run("INFO", "*"))
                   if element.findtext("Name") == parameter]
        if len(matches) != 1:
            raise ProgrammingError("Native schema does not identify exactly one parameter named " + repr(parameter))
        fields = {element.tag: element.text or "" for element in matches[0]}
        if (fields.get("Type") != "int" or _integer_value(fields.get("BitSize") or "8") != 8
                or _integer_value(fields.get("ArraySize") or "1") != 1
                or _integer_value(fields.get("BitAddress") or "0") != 0):
            raise ProgrammingError("Spaced parameter names currently require a scalar 8-bit integer in the native schema")
        if "Address" not in fields:
            raise ProgrammingError("Native parameter schema has no memory address")
        address = _integer_value(fields["Address"])
        number = _integer_value(value)
        minimum = max(0, _integer_value(fields.get("MinValue") or "0"))
        maximum = min(255, _integer_value(fields.get("MaxValue") or "255"))
        if address < 0 or not minimum <= number <= maximum:
            raise ProgrammingError("Spaced parameter value or address is outside its native schema range")
        return address, bytes([number])

    def _set_spaced_parameter(self, parameter: str, value: str) -> Any:
        address, data = self._spaced_parameter_data(parameter, value)
        reply = self.set_raw_data(address, data)
        actual = self.values(parameter)[parameter]
        if _integer_value(actual) != data[0]:
            raise ProgrammingError("Native parameter readback differed after staging the requested byte")
        return reply

    def get(self, parameter: str = "*") -> Any:
        parameter = _parameter_name(parameter)
        if any(character.isspace() for character in parameter):
            from .cgate import CGateResponse
            values = parameter_values(self._run("GET", "*"))
            if parameter not in values:
                raise ProgrammingError("Native unit has no parameter named " + repr(parameter))
            line = "315 " + parameter + "=" + values[parameter]
            return CGateResponse((line,), line, 315)
        return self._run("GET", _token(parameter, "parameter"))

    def values(self, parameter: str = "*") -> dict[str, str]:
        return parameter_values(self.get(parameter))

    def info(self, parameter: str = "*") -> Any:
        parameter = _parameter_name(parameter)
        if any(character.isspace() for character in parameter):
            from .cgate import CGateResponse
            matches = [element for element in _xml_parameters(self._run("INFO", "*"))
                       if element.findtext("Name") == parameter]
            if len(matches) != 1:
                raise ProgrammingError("Native unit has no unique parameter named " + repr(parameter))
            container = ET.Element("Parameters")
            container.append(matches[0])
            lines = ("343-Begin XML snippet", "347-" + ET.tostring(container, encoding="unicode"), "344 End XML snippet")
            return CGateResponse(lines, lines[-1], 344)
        return self._run("INFO", _token(parameter, "parameter"))

    def reset_defaults(self) -> Any:
        return self._run("RESET_TO_DEFAULTS")

    reset_to_defaults = reset_defaults

    def debug_memory(self, start: int = 0) -> Any:
        _positive_integer(start, "Start address", allow_zero=True)
        if not self._started:
            raise ProgrammingError("Programming session is not open")
        return self.programmer._run(f"PP DEBUG mem {self.name} {start:x}")

    def get_raw_data(self, start: int, count: int) -> Any:
        _positive_integer(start, "Start address", allow_zero=True)
        _positive_integer(count, "Byte count")
        return self._run("GET_RAW_DATA", f"{start} {count}")

    def set_raw_data(self, start: int, data: str | bytes) -> Any:
        _positive_integer(start, "Start address", allow_zero=True)
        text = data.hex() if isinstance(data, bytes) else data
        if not isinstance(text, str) or not text or len(text) % 2 or re.fullmatch(r"[0-9A-Fa-f]+", text) is None:
            raise ProgrammingError("Raw data must contain complete hexadecimal byte pairs")
        return self._run("SET_RAW_DATA", f"{start} {text}")

    def copy(self, source: str, destination: str, *, tags: Iterable[str] = ()) -> Any:
        if not self._started:
            raise ProgrammingError("Programming session is not open")
        return self.programmer.copy(self.lock_name, source, destination, tags=tags)

    def export_parameters(self) -> dict[str, Any]:
        """Export named native values; this is a CLI format, not a Toolkit backup."""
        return {"format": "cbus-cli-parameters-v1", "unit_type": self.unit_type, "firmware": self.firmware, "catalog_number": self.catalog_number, "parameters": self.values()}

    def import_parameters(self, snapshot: Mapping[str, Any]) -> list[Any]:
        """Stage named values into the current session; caller explicitly saves.

        The backend may normalize values. A native failure can leave earlier
        parameters staged, so the caller can inspect or discard this session.
        """
        if not isinstance(snapshot, Mapping) or snapshot.get("format") != "cbus-cli-parameters-v1":
            raise ProgrammingError("Unsupported parameter snapshot format")
        parameters = snapshot.get("parameters")
        if not isinstance(parameters, Mapping):
            raise ProgrammingError("Parameter snapshot requires a parameters mapping")
        for key in ("unit_type", "firmware", "catalog_number"):
            known, incoming = getattr(self, key), snapshot.get(key)
            if known and incoming and known != incoming:
                raise ProgrammingError(f"Snapshot {key} differs from this session")
        # Validate all command fields before staging any parameter.
        commands = [(_parameter_name(name), quote_value(value)) for name, value in parameters.items()]
        # Resolve special names and validate their ranges before staging any
        # parameter. Normal names retain the vendor's own value validation.
        raw_writes = {name: self._spaced_parameter_data(name, parameters[name])
                      for name, _quoted in commands if any(character.isspace() for character in name)}
        replies = []
        for name, value in commands:
            if name in raw_writes:
                address, data = raw_writes[name]
                replies.append(self.set_raw_data(address, data))
                if _integer_value(self.values(name)[name]) != data[0]:
                    raise ProgrammingError("Native parameter readback differed after importing " + repr(name))
            else:
                replies.append(self._run("SET", name + " " + value))
        return replies


def _positive_integer(value: int, label: str, *, allow_zero: bool = False) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < (0 if allow_zero else 1):
        raise ProgrammingError(f"{label} must be {'a nonnegative' if allow_zero else 'a positive'} integer")
