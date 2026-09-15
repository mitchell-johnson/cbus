"""Bounded original Toolkit registry persistence with explicit backend effects.

No registry backend is selected implicitly. The caller provides all forty current
preference values; these are retained model values, never inferred startup defaults.
"""
from __future__ import annotations
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping, Protocol
import re
import struct

from .toolkit_numeric import (
    ToolkitNumericConversionError, UnsupportedToolkitNumericInput,
    parse_toolkit_integer,
)

HKCU = 0x80000001
HKLM = 0x80000002
REG_SZ = 1
REG_DWORD = 4
TOOLKIT_KEY = r"Software\Clipsal Integrated Systems\C-Bus Installation Software\3.0"
CGATE_KEY = r"Software\Schneider Electric\C-Gate\CurrentVersion"
DISPLAY_KEY = r"Software\Clipsal Integrated Systems\Global\Preferences"
# Relative Windows paths: the original literals additionally have leading/trailing
# backslashes; JCL RelativeKey removes the leading separator.

@dataclass(frozen=True)
class PreferenceDefinition:
    name: str
    kind: str
    machine_first: bool
    skip_save: bool
    alternate_key: bool
    boolean_default: bool | None

    @property
    def key(self) -> str:
        return CGATE_KEY if self.alternate_key else TOOLKIT_KEY


PREFERENCE_DEFINITIONS = (
    PreferenceDefinition('LoadChangePortDisable', 'boolean', False, False, False, False),
    PreferenceDefinition('ApplicationLogDisable', 'boolean', False, False, False, False),
    PreferenceDefinition('TemperatureUnit', 'integer', False, False, False, None),
    PreferenceDefinition('DoNotPauseEventsWhileLoadingProject', 'boolean', False, False, False, False),
    PreferenceDefinition('ShowProjectManager', 'boolean', False, False, False, True),
    PreferenceDefinition('RememberProjectManagerVisibleState', 'boolean', False, False, False, False),
    PreferenceDefinition('Default Site', 'string', False, False, False, None),
    PreferenceDefinition('Default COM Port', 'string', False, False, False, None),
    PreferenceDefinition('Default Interface Type', 'string', False, False, False, None),
    PreferenceDefinition('Default CNI Address', 'string', False, False, False, None),
    PreferenceDefinition('AutoInvokeMacroFunctionDialog', 'boolean', False, False, False, False),
    PreferenceDefinition('AutoInvokeDatabaseUnitDialog', 'boolean', False, False, False, False),
    PreferenceDefinition('SynchroniseFilters', 'boolean', False, False, False, True),
    PreferenceDefinition('CGateShutdownOnExit', 'boolean', False, False, False, False),
    PreferenceDefinition('CGateShutdownOnExitAsk', 'boolean', False, False, False, False),
    PreferenceDefinition('CloseProjectsOnExit', 'boolean', False, False, False, False),
    PreferenceDefinition('CGateShutdownDecision', 'integer', False, False, False, None),
    PreferenceDefinition('UnitDialogOverride', 'boolean', False, False, False, False),
    PreferenceDefinition('UnitDialogModeAdvanced', 'boolean', False, False, False, False),
    PreferenceDefinition('UnitDialogAlwaysClassic', 'boolean', False, False, False, False),
    PreferenceDefinition('FeedbackLog', 'boolean', False, False, False, False),
    PreferenceDefinition('FeedbackLogFile', 'string', True, True, False, None),
    PreferenceDefinition('FeedbackLogSize', 'integer', True, False, False, None),
    PreferenceDefinition('JavaHeapMin', 'integer', False, False, True, None),
    PreferenceDefinition('JavaHeapMax', 'integer', False, False, True, None),
    PreferenceDefinition('IlluminanceMeasurementUnit', 'integer', True, True, False, None),
    PreferenceDefinition('ClipsalWebsiteURL', 'string', True, True, False, None),
    PreferenceDefinition('CISDownloadsURL', 'string', True, True, False, None),
    PreferenceDefinition('AllowLegacyApplicationCreation', 'boolean', False, False, False, False),
    PreferenceDefinition('AllowUserDefinedApplicationCreation', 'boolean', False, False, False, False),
    PreferenceDefinition('LegacyDuplicateUnitsDetection', 'boolean', False, False, False, True),
    PreferenceDefinition('ShowDatabaseLabelsOption', 'boolean', False, True, False, False),
    PreferenceDefinition('Default Language 1', 'integer', False, False, False, None),
    PreferenceDefinition('Default Language 2', 'integer', False, False, False, None),
    PreferenceDefinition('Default Language 3', 'integer', False, False, False, None),
    PreferenceDefinition('Default Language 4', 'integer', False, False, False, None),
    PreferenceDefinition('Default Language 5', 'integer', False, False, False, None),
    PreferenceDefinition('Default Language 6', 'integer', False, False, False, None),
    PreferenceDefinition('Default Language 7', 'integer', False, False, False, None),
    PreferenceDefinition('Default Language 8', 'integer', False, False, False, None),
)

DISPLAY_DEFINITIONS = (
    ("tag_hex", "DisplayHexAddress"),
    ("tag_override", "DisplayAddressValue"),
    ("sort_applications", "SortModeApplications"),
    ("sort_groups", "SortModeGroups"),
    ("sort_levels", "SortModeLevels"),
)

class UnsupportedPreferenceEncoding(ValueError):
    """A stored encoding lies outside this bounded original-compatible decoder."""


def _text(value: object, name: str) -> str:
    if type(value) is not str or len(value) > 4096 or "\0" in value:
        raise ValueError(f"{name} must be a string of at most 4096 characters without NUL")
    try:
        value.encode("utf-16-le")
    except UnicodeError as error:
        raise ValueError(f"{name} must contain valid Unicode") from error
    return value


def validate_values(values: Mapping[str, object]) -> dict[str, bool | int | str]:
    """Validate and detach exactly the full forty typed current values."""
    if not isinstance(values, Mapping):
        raise TypeError("preference values must be a mapping")
    expected = {spec.name for spec in PREFERENCE_DEFINITIONS}
    if set(values) != expected:
        raise ValueError("preference values must contain exactly all forty registered names")
    result = {}
    for spec in PREFERENCE_DEFINITIONS:
        value = values[spec.name]
        if spec.kind == "boolean":
            if type(value) is not bool:
                raise ValueError(f"{spec.name} must be a boolean")
        elif spec.kind == "integer":
            if type(value) is not int or not -(2**31) <= value < 2**31:
                raise ValueError(f"{spec.name} must be a signed 32-bit integer")
        else:
            value = _text(value, spec.name)
        result[spec.name] = value
    return result


def validate_display_values(values: Mapping[str, object]) -> dict[str, int | bool]:
    if not isinstance(values, Mapping) or set(values) != {key for key, _ in DISPLAY_DEFINITIONS}:
        raise ValueError("display values must contain exactly the five display names")
    result = dict(values)
    for name, value in result.items():
        if type(value) not in (int, bool) or not 0 <= value <= 255:
            raise ValueError(f"{name} must be a boolean or byte integer")
    return result


@dataclass(frozen=True)
class RegistryValue:
    win32_type: int
    data: bytes

    def __post_init__(self):
        if type(self.win32_type) is not int or not 0 <= self.win32_type <= 0xffffffff:
            raise ValueError("registry type must be an unsigned 32-bit integer")
        if type(self.data) is not bytes or len(self.data) > 65536:
            raise ValueError("registry data must be bytes of at most 65536 bytes")


class PreferenceRegistry(Protocol):
    """Explicit storage boundary; adapters own necessary key/handle operations.

    Reads raise FileNotFoundError for absent values and OSError for access errors.
    Named writes must create the requested key if needed, return None on success,
    and raise on failure. They must not change unrelated values. Default writes
    model legacy RegSetValue: they create a key as needed and return a Win32 code.
    No implementation is selected implicitly and no host registry is accessed here.
    """
    def read_value(self, hive: int, key: str, name: str) -> RegistryValue: ...
    def write_value(self, hive: int, key: str, name: str, value: RegistryValue) -> None: ...
    def write_default_string(self, hive: int, key: str, value: str) -> int: ...


def _string_value(text: str) -> RegistryValue:
    return RegistryValue(REG_SZ, (text + "\0").encode("utf-16-le"))


def _registry_string(value: RegistryValue, name: str) -> str:
    if type(value) is not RegistryValue or value.win32_type != REG_SZ:
        raise UnsupportedPreferenceEncoding(f"{name} requires REG_SZ")
    if len(value.data) < 2 or len(value.data) % 2 or not value.data.endswith(b"\0\0"):
        raise UnsupportedPreferenceEncoding(f"{name} requires terminated UTF-16LE")
    try:
        text = value.data[:-2].decode("utf-16-le")
        _text(text, name)
    except (UnicodeError, ValueError) as error:
        raise UnsupportedPreferenceEncoding(f"{name} contains unsupported string data") from error
    return text


def validate_numeric_locale(value):
    """Validate explicit numeric decoding options without registry access."""
    if value is None:
        return None
    if type(value) is not tuple or len(value) != 2 or any(type(item) is not str for item in value) or value not in ((".", ","), (",", ".")):
        raise ValueError("numeric_locale must be None or the tuple ('.', ',') or (',', '.')")
    return value


def _decode(spec: PreferenceDefinition, value: RegistryValue, numeric_locale=None) -> bool | int | str:
    text = _registry_string(value, spec.name)
    if spec.kind == "boolean":
        if not text.isascii():
            raise UnsupportedPreferenceEncoding(f"{spec.name} supports ASCII boolean storage only")
        return text.lower() == "true"
    if spec.kind == "integer":
        if numeric_locale is not None:
            try:
                return parse_toolkit_integer(text, decimal_separator=numeric_locale[0],
                                             thousands_separator=numeric_locale[1]).value
            except UnsupportedToolkitNumericInput as error:
                raise UnsupportedPreferenceEncoding(f"{spec.name} contains unsupported numeric storage: {error}") from error
        if re.fullmatch(r"(?:0|-[1-9][0-9]*|[1-9][0-9]*)", text) is None or len(text) > 11:
            raise UnsupportedPreferenceEncoding(f"{spec.name} supports canonical signed decimal storage only")
        number = int(text)
        if not -(2**31) <= number < 2**31:
            raise UnsupportedPreferenceEncoding(f"{spec.name} is outside signed 32-bit storage")
        return number
    return text


def _encode(value: bool | int | str) -> RegistryValue:
    return _string_value("True" if value is True else "False" if value is False else str(value))


def _error(error: BaseException) -> dict[str, str]:
    try:
        message = str(error)
    except BaseException:
        message = "exception message unavailable"
    return {"type": type(error).__name__, "message": message}


@dataclass(frozen=True)
class StoreOutcome:
    operation: str
    complete: bool
    algorithm_completed: bool
    values: Mapping[str, bool | int | str]
    display_values: Mapping[str, int | bool]
    operations: tuple[Mapping[str, object], ...]
    issues: tuple[str, ...]
    error: Mapping[str, str] | None
    fully_observed: bool
    numeric_locale: tuple[str, str] | None = None

    def as_dict(self) -> dict:
        result = {"operation": self.operation, "complete": self.complete,
                "algorithm_completed": self.algorithm_completed,
                "values": dict(self.values), "display_values": dict(self.display_values),
                "operations": [dict(row) for row in self.operations],
                "issues": list(self.issues), "error": dict(self.error) if self.error else None,
                "fully_observed": self.fully_observed,
                "default_writes": [dict(row) for row in self.operations if row["action"] in ("write-default", "write-preference-default")],
                "transactional": False, "runtime_effects_applied": False,
                "actual_registry_backend_verified": False}
        if self.numeric_locale is not None:
            result["numeric_locale"] = list(self.numeric_locale)
        return result


class ToolkitPreferencesStore:
    """Sequential manager persistence; completed prefixes are never rolled back."""
    def __init__(self, registry: PreferenceRegistry, *, numeric_locale=None):
        self._numeric_locale = validate_numeric_locale(numeric_locale)
        self.registry = registry
        self.last_outcome: StoreOutcome | None = None
        self.last_evidence: dict | None = None
        self.last_error: BaseException | None = None

    @property
    def numeric_locale(self):
        return self._numeric_locale

    def _reset(self, operation):
        self.last_outcome = self.last_evidence = self.last_error = None
        self._operation = operation
        self._values = {}
        self._display = {}
        self._operations = []
        self._issues = []
        self._observed = True

    def _call(self, action, hive, key, name, function, *args, value=None):
        row = {"sequence": len(self._operations) + 1, "action": action,
               "hive": hive, "key": key, "name": name, "completed": False}
        if value is not None:
            row.update(win32_type=value.win32_type, data_hex=value.data.hex())
        self._operations.append(row)
        try:
            result = function(*args)
        except BaseException as error:
            row["error_type"] = type(error).__name__
            raise
        row["completed"] = True
        if action == "read":
            if type(result) is not RegistryValue:
                raise TypeError("registry read returned an invalid value")
            row.update(win32_type=result.win32_type, data_hex=result.data.hex())
        elif action == "write-default":
            if type(result) is not int or not 0 <= result <= 0xffffffff:
                raise TypeError("default registry write must return a Win32 status")
            row["return_code"] = result
            row["write_succeeded"] = result == 0
            if result:
                self._issues.append(f"unnamed registry write returned {result}: {key}")
                self._observed = False
        elif result is not None:
            raise TypeError("named registry write must return None")
        return result

    def _read(self, hive, key, name):
        return self._call("read", hive, key, name, self.registry.read_value, hive, key, name)

    def _write(self, hive, key, name, value, action="write"):
        self._call(action, hive, key, name, self.registry.write_value, hive, key, name, value, value=value)

    def _default(self, hive, key):
        self._call("write-default", hive, key, "", self.registry.write_default_string,
                   hive, key, "", value=_string_value(""))

    def _finish(self, completed, error=None):
        self.last_error = error
        result = StoreOutcome(self._operation, completed and not self._issues and error is None,
                              completed, MappingProxyType(dict(self._values)), MappingProxyType(dict(self._display)),
                              tuple(MappingProxyType(dict(row)) for row in self._operations), tuple(self._issues),
                              MappingProxyType(_error(error)) if error is not None else None, self._observed and error is None,
                              self._numeric_locale)
        self.last_outcome = result
        try:
            self.last_evidence = result.as_dict()
        except BaseException:
            self.last_evidence = {"operation": self._operation, "complete": False,
                                  "evidence_export_failed": True,
                                  "attempted_operations": len(self._operations)}
        if error is not None:
            try:
                error.toolkit_preferences_evidence = self.last_evidence
            except BaseException:
                pass
        return result

    def load(self, initial_values: Mapping[str, object]) -> StoreOutcome:
        self._reset("load")
        self._values = validate_values(initial_values)
        self._display = dict.fromkeys((name for name, _ in DISPLAY_DEFINITIONS), False)
        try:
            self._default(HKCU, TOOLKIT_KEY)
            self._default(HKCU, CGATE_KEY)
            for spec in PREFERENCE_DEFINITIONS:
                first, second = (HKLM, HKCU) if spec.machine_first else (HKCU, HKLM)
                try:
                    raw = self._read(first, spec.key, spec.name)
                except OSError:
                    self._observed = False
                    try:
                        raw = self._read(second, spec.key, spec.name)
                    except OSError:
                        if spec.machine_first:
                            continue
                        raw = None
                    if not spec.machine_first:
                        # Decode before the original copy-write boundary. Unsupported
                        # encodings explicitly stop this bounded API without copying.
                        text = _registry_string(raw, spec.name) if raw is not None else ""
                        if text:
                            try:
                                decoded = _decode(spec, raw, self._numeric_locale)
                            except ToolkitNumericConversionError:
                                # The original copies before invoking numeric load.
                                # A proven parser error preserves that prefix; unknown
                                # encodings above remain explicit pre-copy rejections.
                                self._write(HKCU, spec.key, spec.name, raw, "write-preference-copy")
                                raise
                            self._write(HKCU, spec.key, spec.name, raw, "write-preference-copy")
                        else:
                            current = self._values[spec.name]
                            default = spec.boolean_default if spec.kind == "boolean" else current
                            self._write(HKCU, spec.key, spec.name, _encode(default), "write-preference-default")
                            # Original code reloads GetRegistryString(current), not its
                            # just-written boolean default, until a subsequent load.
                            decoded = current
                        self._values[spec.name] = decoded
                        continue
                self._values[spec.name] = _decode(spec, raw, self._numeric_locale)
            for name, registry_name in DISPLAY_DEFINITIONS:
                try:
                    value = self._read(HKCU, DISPLAY_KEY, registry_name)
                except FileNotFoundError:
                    self._observed = False
                    continue
                if value.win32_type != REG_DWORD or len(value.data) != 4:
                    raise UnsupportedPreferenceEncoding(f"{registry_name} requires one REG_DWORD")
                self._display[name] = bool(int.from_bytes(value.data, "little"))
        except (KeyboardInterrupt, SystemExit) as error:
            self._finish(False, error)
            raise
        except Exception as error:
            return self._finish(False, error)
        return self._finish(True)

    def save(self, values: Mapping[str, object], display_values: Mapping[str, object]) -> StoreOutcome:
        self._reset("save")
        self._values = validate_values(values)
        self._display = validate_display_values(display_values)
        try:
            for name, registry_name in DISPLAY_DEFINITIONS:
                value = RegistryValue(REG_DWORD, struct.pack("<I", int(self._display[name]) & 0x7f))
                self._write(HKCU, DISPLAY_KEY, registry_name, value)
            self._default(HKCU, TOOLKIT_KEY)
            self._default(HKCU, CGATE_KEY)
            machine_key_requested = False
            for spec in PREFERENCE_DEFINITIONS:
                if spec.skip_save:
                    continue
                value = _encode(self._values[spec.name])
                if spec.machine_first:
                    if not machine_key_requested:
                        self._default(HKLM, spec.key)
                        machine_key_requested = True
                    try:
                        self._write(HKLM, spec.key, spec.name, value)
                    except OSError:
                        self._observed = False
                        self._write(HKCU, spec.key, spec.name, value, "write-preference-fallback")
                else:
                    self._write(HKCU, spec.key, spec.name, value)
        except (KeyboardInterrupt, SystemExit) as error:
            self._finish(False, error)
            raise
        except Exception as error:
            return self._finish(False, error)
        return self._finish(True)
