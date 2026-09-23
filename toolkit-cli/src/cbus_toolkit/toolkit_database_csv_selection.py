"""Toolkit 1.18 database-report column selection and registry persistence.

The original form stores a comma-terminated list of displayed column labels.
An absent value defaults to the literal ``SelectAll`` sentinel.  Matching is the
original case-sensitive substring test for ``label + ','``; unknown text is
ignored and persisted order does not affect the resulting ordinal mask.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Protocol

from .toolkit_database_csv import COLUMNS, COLUMN_LABELS, validate_columns
from .toolkit_preferences_store import HKCU, TOOLKIT_KEY


CSV_SELECTION_KEY = TOOLKIT_KEY + r"\Forms\frmCSVSelection"
CSV_SELECTION_VALUE = "CSVSelection"
SELECT_ALL_SENTINEL = "SelectAll"
ALL_COLUMNS_MASK = (1 << len(COLUMNS)) - 1
MAX_SELECTION_UTF16_UNITS = 32767


class CSVSelectionRegistry(Protocol):
    """Explicit string boundary for the original HKCU selection value."""

    def read_selection(self, hive: int, key: str, name: str) -> str: ...
    def write_selection(self, hive: int, key: str, name: str, value: str) -> None: ...


def _text(value: object) -> str:
    if type(value) is not str or "\0" in value:
        raise ValueError("CSV selection storage must be text without NUL")
    try:
        raw = value.encode("utf-16-le")
    except UnicodeError as error:
        raise ValueError("CSV selection storage must contain valid Unicode") from error
    if len(raw) // 2 > MAX_SELECTION_UTF16_UNITS:
        raise ValueError("CSV selection storage exceeds 32767 UTF-16 code units")
    return value


def columns_mask(columns: tuple[str, ...]) -> int:
    selected = validate_columns(columns)
    return sum(1 << index for index, name in enumerate(COLUMNS) if name in selected)


def encode_selection(columns: tuple[str, ...]) -> str:
    """Encode the text written by the original OK handler."""
    selected = validate_columns(columns)
    return "".join(COLUMN_LABELS[name] + "," for name in selected)


@dataclass(frozen=True)
class CSVSelection:
    columns: tuple[str, ...]
    mask: int
    stored_text: str
    default_used: bool

    def __post_init__(self):
        if type(self.columns) is not tuple:
            raise ValueError("CSV selection columns must be a tuple")
        if self.columns:
            if validate_columns(self.columns) != self.columns:
                raise ValueError("CSV selection columns must use original ordinal order")
        if type(self.mask) is not int or not 0 <= self.mask <= ALL_COLUMNS_MASK:
            raise ValueError("CSV selection mask is outside the 26-bit domain")
        if self.mask != sum(1 << index for index, name in enumerate(COLUMNS)
                            if name in self.columns):
            raise ValueError("CSV selection mask does not match its columns")
        _text(self.stored_text)
        if type(self.default_used) is not bool:
            raise ValueError("default_used must be Boolean")

    @property
    def ok_enabled(self) -> bool:
        return self.mask != 0

    def as_dict(self) -> dict:
        return {
            "format": "cbus-toolkit-database-csv-selection-v1",
            "columns": list(self.columns),
            "headers": [COLUMN_LABELS[name] for name in self.columns],
            "mask": self.mask,
            "mask_hex": f"0x{self.mask:08x}",
            "stored_text": self.stored_text,
            "default_used": self.default_used,
            "ok_enabled": self.ok_enabled,
        }


def decode_selection(value: str, *, default_used: bool = False) -> CSVSelection:
    """Decode one original registry string, including its substring behavior."""
    value = _text(value)
    if type(default_used) is not bool:
        raise ValueError("default_used must be Boolean")
    selected = tuple(
        name for name in COLUMNS
        if value == SELECT_ALL_SENTINEL or COLUMN_LABELS[name] + "," in value
    )
    mask = sum(1 << index for index, name in enumerate(COLUMNS) if name in selected)
    return CSVSelection(selected, mask, value, default_used)


class ToolkitDatabaseCSVSelectionStore:
    """Load or save the one original selection value with ordered evidence."""

    def __init__(self, registry: CSVSelectionRegistry):
        self.registry = registry
        self.last_evidence: dict | None = None
        self.last_error: BaseException | None = None

    def load(self) -> CSVSelection:
        evidence = {
            "operation": "load-toolkit-database-csv-selection",
            "complete": False,
            "hive": HKCU,
            "key": CSV_SELECTION_KEY,
            "name": CSV_SELECTION_VALUE,
            "read_attempted": True,
            "value_present": None,
            "default_used": False,
            "write_attempted": False,
            "selection": None,
        }
        self.last_error = None
        try:
            try:
                value = self.registry.read_selection(
                    HKCU, CSV_SELECTION_KEY, CSV_SELECTION_VALUE)
                evidence["value_present"] = True
            except FileNotFoundError:
                value = SELECT_ALL_SENTINEL
                evidence.update(value_present=False, default_used=True)
            selection = decode_selection(value, default_used=evidence["default_used"])
            evidence.update(complete=True, selection=selection.as_dict())
            self.last_evidence = copy.deepcopy(evidence)
            return selection
        except BaseException as error:
            self.last_error = error
            evidence["error"] = _error(error)
            self.last_evidence = copy.deepcopy(evidence)
            try:
                error.toolkit_database_csv_selection_evidence = evidence
            except BaseException:
                pass
            raise

    def save(self, columns: tuple[str, ...]) -> CSVSelection:
        text = encode_selection(columns)
        selection = decode_selection(text)
        evidence = {
            "operation": "save-toolkit-database-csv-selection",
            "complete": False,
            "hive": HKCU,
            "key": CSV_SELECTION_KEY,
            "name": CSV_SELECTION_VALUE,
            "read_attempted": False,
            "write_attempted": True,
            "stored_text": text,
            "selection": selection.as_dict(),
        }
        self.last_error = None
        try:
            self.registry.write_selection(
                HKCU, CSV_SELECTION_KEY, CSV_SELECTION_VALUE, text)
            evidence["complete"] = True
            self.last_evidence = copy.deepcopy(evidence)
            return selection
        except BaseException as error:
            self.last_error = error
            evidence["error"] = _error(error)
            self.last_evidence = copy.deepcopy(evidence)
            try:
                error.toolkit_database_csv_selection_evidence = evidence
            except BaseException:
                pass
            raise


def _error(error: BaseException) -> dict[str, str]:
    try:
        message = str(error)
    except BaseException:
        message = "exception message unavailable"
    return {"type": type(error).__name__, "message": message[:4096]}
