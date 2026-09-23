"""Independent bounded SAL label receiver for synthetic PCI fixtures.

Uses native wire captures and separately decoded protocol fields; it must not
import the client label encoder. It models completed payload state, not display
rendering, flash behavior, or all model-specific label capacities.
"""
from __future__ import annotations

from copy import deepcopy


class LabelPacketError(ValueError):
    pass


def _byte(value):
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 255


class LabelState:
    MAX_LABELS = 1024
    MAX_PENDING = 32

    def __init__(self):
        self.labels = {}
        self.languages = {}
        self._unicode = {}
        self._dynamic = {}

    def _store(self, key, record):
        if key not in self.labels and len(self.labels) >= self.MAX_LABELS:
            raise LabelPacketError("Synthetic label capacity exceeded")
        self.labels[key] = record
        return True

    def receive(self, application, payload):
        """Validate one complete SAL payload; return True only after a commit."""
        if not _byte(application) or not (48 <= application <= 95 or application in (202, 203)):
            raise LabelPacketError("Unsupported synthetic label application")
        if not isinstance(payload, bytes) or len(payload) < 3 or (payload[0] & 31) + 1 != len(payload):
            raise LabelPacketError("Incorrect SAL label length")
        family = payload[0] & 224
        if family == 192:
            return self._receive_unicode(application, payload)
        if family != 160:
            raise LabelPacketError("Unsupported SAL label opcode")
        group, options = payload[1:3]
        if options & 128:
            raise LabelPacketError("Unsupported reserved label options")
        variant = options >> 5 & 3
        selected = bool(options & 1)
        offset = 4 if selected else 3
        if len(payload) < offset:
            raise LabelPacketError("Missing label action selector")
        action = payload[3] if selected else None
        slot = (application, group, action, variant)
        kind = options & 30
        tail = payload[offset:]
        pending = self._dynamic.get(slot)
        if kind == 4 and pending is not None and pending["phase"] == "chunk":
            if not 1 <= len(tail) <= 6 or len(pending["data"]) + len(tail) > pending["size"]:
                raise LabelPacketError("Invalid or overflowing dynamic icon chunk")
            pending["data"] += tail
            pending["phase"] = "append"
            return False
        if not tail:
            raise LabelPacketError("Missing label language")
        language, data = tail[0], tail[1:]
        key = (application, group, action, language, variant)
        if len(data) > 14:
            raise LabelPacketError("Label payload exceeds fourteen bytes")
        if kind == 8:
            if language != 0 or len(data) != 1 or data[0] not in (32, 33, 34):
                raise LabelPacketError("Unsupported dynamic icon control")
            if data[0] == 32:
                if slot not in self._dynamic and len(self._dynamic) >= self.MAX_PENDING:
                    raise LabelPacketError("Too many pending dynamic icons")
                self._dynamic[slot] = {"phase": "header"}
                return False
            if pending is None or pending["phase"] != "append":
                raise LabelPacketError("Dynamic icon control without a complete preceding stage")
            if data[0] == 33:
                if len(pending["data"]) >= pending["size"]:
                    raise LabelPacketError("Dynamic icon already has all bytes")
                pending["phase"] = "chunk"
                return False
            if len(pending["data"]) != pending["size"]:
                raise LabelPacketError("Cannot commit an incomplete dynamic icon")
            record = {"kind": "dynamic", "icon": pending["icon"], "width": pending["width"],
                      "height": pending["height"], "vertical_offset": pending["vertical_offset"], "data_hex": pending["data"].hex()}
            self._store((application, group, action, pending["language"], variant), record)
            del self._dynamic[slot]
            return True
        if kind == 4:
            if pending is None or pending["phase"] != "header" or len(data) != 5:
                raise LabelPacketError("Dynamic icon header without a start marker")
            icon = int.from_bytes(data[:2], "big")
            width, height, vertical_offset = data[2:]
            if not 1 <= width <= 240 or not 1 <= height <= 60:
                raise LabelPacketError("Invalid dynamic icon dimensions")
            self._dynamic[slot] = dict(phase="append", icon=icon, width=width, height=height,
                                       vertical_offset=vertical_offset, language=language,
                                       size=(width * height + 7) // 8, data=b"")
            return False
        if kind == 6:
            if data:
                raise LabelPacketError("Language selection must not contain data")
            target = (application, group, action)
            if target not in self.languages and len(self.languages) >= self.MAX_LABELS:
                raise LabelPacketError("Synthetic language selection capacity exceeded")
            self.languages[target] = language
            return True
        if kind == 2:
            if len(data) != 3 or data[0] != 1:
                raise LabelPacketError("Unsupported icon reference")
            return self._store(key, {"kind": "icon", "icon": int.from_bytes(data[1:], "big"), "data_hex": data.hex()})
        if kind != 0:
            raise LabelPacketError("Unsupported synthetic label option")
        previous = self.labels.get(key)
        if previous and previous["kind"] == "unicode" and previous["data_hex"]:
            # Native help specifies Unicode labels take precedence until cleared.
            return False
        try:
            text = "" if data == b"\0" else data.decode("ascii")
        except UnicodeDecodeError:
            text = None
        return self._store(key, {"kind": "text", "text": text, "data_hex": data.hex()})

    def _receive_unicode(self, application, payload):
        if len(payload) < 5:
            raise LabelPacketError("Truncated Unicode label")
        group, control, options = payload[1:4]
        if options & 124:
            raise LabelPacketError("Reserved Unicode label options")
        selected = bool(options & 128)
        if (control & 3) != (3 if selected else 2):
            raise LabelPacketError("Unicode header/action-selector mismatch")
        offset = 5 if selected else 4
        if len(payload) <= offset:
            raise LabelPacketError("Missing Unicode label language")
        action = payload[4] if selected else None
        language = payload[offset]
        data = payload[offset + 1:]
        if len(data) > (12 if selected else 13):
            raise LabelPacketError("Unicode fragment is too long")
        key = (application, group, action, language, options & 3)
        phase, sequence = control & 12, control >> 4
        if phase == 12:
            complete = data
            self._unicode.pop(key, None)
        elif phase == 0:
            if not data:
                raise LabelPacketError("Empty initial Unicode fragment")
            if key not in self._unicode and len(self._unicode) >= self.MAX_PENDING:
                raise LabelPacketError("Too many pending Unicode labels")
            self._unicode[key] = {"sequence": sequence, "data": data, "fragments": 1}
            return False
        else:
            pending = self._unicode.get(key)
            if pending is None or sequence != (pending["sequence"] + 1) % 16:
                self._unicode.pop(key, None)
                raise LabelPacketError("Missing or out-of-order Unicode fragment")
            if not data or pending["fragments"] >= 18:
                self._unicode.pop(key, None)
                raise LabelPacketError("Invalid Unicode fragment count")
            complete = pending["data"] + data
            if phase == 4:
                self._unicode[key] = {"sequence": sequence, "data": complete, "fragments": pending["fragments"] + 1}
                return False
            del self._unicode[key]
        try:
            text = complete.decode("utf-8", errors="strict")
        except UnicodeDecodeError as error:
            raise LabelPacketError("Completed Unicode label is invalid UTF-8") from error
        return self._store(key, {"kind": "unicode", "text": text, "data_hex": complete.hex()})

    def snapshot(self):
        """Committed state only: partial uploads are never persisted as labels."""
        return {"format": "cbus-synthetic-labels-v1",
                "labels": [{"key": list(key), **deepcopy(value)} for key, value in self.labels.items()],
                "languages": [{"key": list(key), "language": value} for key, value in self.languages.items()]}

    @classmethod
    def from_snapshot(cls, value):
        state = cls()
        if not isinstance(value, dict) or value.get("format") != "cbus-synthetic-labels-v1":
            raise LabelPacketError("Unsupported synthetic label snapshot")
        labels, languages = value.get("labels"), value.get("languages")
        if not isinstance(labels, list) or not isinstance(languages, list) or len(labels) > state.MAX_LABELS or len(languages) > state.MAX_LABELS:
            raise LabelPacketError("Invalid synthetic label snapshot size")
        for rows, width, target in ((labels, 5, state.labels), (languages, 3, state.languages)):
            for row in rows:
                if not isinstance(row, dict):
                    raise LabelPacketError("Invalid synthetic label snapshot row")
                key = row.get("key")
                if not isinstance(key, list) or len(key) != width or any(not _byte(part) for index, part in enumerate(key) if index != 2) or (key[2] is not None and not _byte(key[2])) or (width == 5 and key[4] > 3):
                    raise LabelPacketError("Invalid synthetic label snapshot key")
                key = tuple(key)
                if not (48 <= key[0] <= 95 or key[0] in (202, 203)):
                    raise LabelPacketError("Unsupported synthetic snapshot application")
                if key in target:
                    raise LabelPacketError("Duplicate synthetic label snapshot key")
                if width == 3:
                    if not _byte(row.get("language")):
                        raise LabelPacketError("Invalid synthetic label language")
                    target[key] = row["language"]
                    continue
                record = {name: deepcopy(value) for name, value in row.items() if name != "key"}
                if record.get("kind") not in ("text", "unicode", "icon", "dynamic"):
                    raise LabelPacketError("Invalid synthetic label kind")
                try:
                    data = bytes.fromhex(record["data_hex"])
                except (KeyError, TypeError, ValueError) as error:
                    raise LabelPacketError("Invalid synthetic label data") from error
                if len(data) > 1800:
                    raise LabelPacketError("Synthetic label data exceeds bounds")
                kind = record["kind"]
                fields = {"kind", "data_hex"} | ({"text"} if kind in ("text", "unicode") else {"icon"})
                if kind == "dynamic":
                    fields |= {"width", "height", "vertical_offset"}
                if set(record) != fields:
                    raise LabelPacketError("Unexpected synthetic label fields")
                if kind in ("text", "unicode"):
                    if len(data) > (14 if kind == "text" else 216 if key[2] is not None else 234):
                        raise LabelPacketError("Synthetic text label exceeds bounds")
                    try:
                        expected_text = "" if kind == "text" and data == b"\0" else data.decode("ascii" if kind == "text" else "utf-8")
                    except UnicodeDecodeError as error:
                        if kind == "unicode":
                            raise LabelPacketError("Invalid persisted Unicode label") from error
                        expected_text = None
                    if record["text"] != expected_text:
                        raise LabelPacketError("Persisted label text does not match its bytes")
                else:
                    icon = record["icon"]
                    if isinstance(icon, bool) or not isinstance(icon, int) or not 0 <= icon <= 65535:
                        raise LabelPacketError("Invalid persisted icon selector")
                    if kind == "icon" and data != bytes((1, icon >> 8, icon & 255)):
                        raise LabelPacketError("Persisted icon does not match its bytes")
                    if kind == "dynamic":
                        bitmap_width, bitmap_height, offset = (record[field] for field in ("width", "height", "vertical_offset"))
                        if not all(_byte(number) for number in (bitmap_width, bitmap_height, offset)) or not 1 <= bitmap_width <= 240 or not 1 <= bitmap_height <= 60 or len(data) != (bitmap_width * bitmap_height + 7) // 8:
                            raise LabelPacketError("Invalid persisted dynamic icon")
                target[key] = record
        return state
