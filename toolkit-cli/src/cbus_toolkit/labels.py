"""Typed C-Gate dynamic labels and native-compatible SAL payload encoding.

These commands send application messages. A successful C-Gate response means
the server accepted the command, not that a physical display applied it.
"""
from __future__ import annotations

from .native import _token


class LabelError(ValueError):
    """Invalid label input or a payload the native sender cannot preserve."""


def _integer(value, name, minimum=0, maximum=255):
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise LabelError(f"{name} must be an integer in {minimum}..{maximum}")
    return value


def _target(group, language, action_selector, variant):
    _integer(group, "Group")
    _integer(language, "Language")
    if action_selector is not None:
        _integer(action_selector, "Action selector")
    _integer(variant, "Variant", maximum=3)


def _bytes(value, maximum=None):
    if not isinstance(value, (bytes, bytearray, memoryview)):
        raise LabelError("Label data must be bytes")
    data = bytes(value)
    if maximum is not None and len(data) > maximum:
        raise LabelError(f"Label data exceeds {maximum} bytes")
    return data


def encode_label(group, language, options, data, *, action_selector=None, variant=0):
    """Encode one SAL label payload, excluding PCI/application framing."""
    _target(group, language, action_selector, variant)
    _integer(options, "Options")
    data = _bytes(data, 14)
    selected = action_selector is not None
    return bytes((0xA0 | (len(data) + 3 + selected), group,
                  options | selected | (variant << 5))) + (bytes((action_selector,)) if selected else b"") + bytes((language,)) + data


def encode_unicode_label(group, language, data, *, action_selector=None, variant=0, sequence=0):
    """Encode native Unicode fragments with a caller-selected sequence nibble.

    Native C-Gate chooses a random starting nibble. More than eighteen fragments
    overwrite earlier entries in its internal ordered map, so reject that input.
    UTF-8 characters may span fragments and must be decoded after reassembly.
    """
    _target(group, language, action_selector, variant)
    _integer(sequence, "Sequence", maximum=15)
    selected = action_selector is not None
    size = 12 if selected else 13
    data = _bytes(data, size * 18)
    try:
        data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise LabelError("Unicode label data must be valid UTF-8") from error
    chunks = [data[offset:offset + size] for offset in range(0, len(data), size)] or [b""]
    packets = []
    for index, chunk in enumerate(chunks):
        control = 12 if len(chunks) == 1 else 0 if index == 0 else 8 if index == len(chunks) - 1 else 4
        control |= ((sequence + index) & 15) << 4 | (3 if selected else 2)
        packet = bytes((0xC0 | (len(chunk) + 4 + selected), group, control,
                        (128 if selected else 0) | variant))
        packets.append(packet + (bytes((action_selector,)) if selected else b"") + bytes((language,)) + chunk)
    return tuple(packets)


def _bitmap(icon, width, height, vertical_offset, data):
    _integer(icon, "Icon selector", maximum=65535)
    _integer(width, "Icon width", 1, 240)
    _integer(height, "Icon height", 1, 60)
    _integer(vertical_offset, "Vertical offset")
    data = _bytes(data, 1800)
    if len(data) != (width * height + 7) // 8:
        raise LabelError("Bitmap byte count must equal ceil(width * height / 8)")
    return data


def encode_dynamic_icon(group, language, icon, width, height, data, *, vertical_offset=0, action_selector=None, variant=0):
    """Encode start, metadata, six-byte chunks and commit for a dynamic icon."""
    _target(group, language, action_selector, variant)
    data = _bitmap(icon, width, height, vertical_offset, data)
    kwargs = dict(action_selector=action_selector, variant=variant)
    packets = [encode_label(group, 0, 8, b"\x20", **kwargs),
               encode_label(group, language, 4, icon.to_bytes(2, "big") + bytes((width, height, vertical_offset)), **kwargs)]
    for offset in range(0, len(data), 6):
        chunk = data[offset:offset + 6]
        packets.append(encode_label(group, 0, 8, b"\x21", **kwargs))
        packets.append(bytes((0xA0 | (len(chunk) + 2 + (action_selector is not None)), group,
                              4 | (action_selector is not None) | (variant << 5)))
                       + (bytes((action_selector,)) if action_selector is not None else b"") + chunk)
    packets.append(encode_label(group, 0, 8, b"\x22", **kwargs))
    return tuple(packets)


class NativeLabels:
    """Validated LIGHTING, TRIGGER or ENABLE label commands; no automatic retry."""
    def __init__(self, client, family="lighting"):
        if not isinstance(family, str) or family.lower() not in ("lighting", "trigger", "enable"):
            raise LabelError("Label family must be lighting, trigger or enable")
        self.client = client
        self.family = family.upper()

    def _prefix(self, application, group, language, action_selector, variant, unicode=False):
        _target(group, language, action_selector, variant)
        application = _token(application, "application address")
        action = "-" if action_selector is None else str(action_selector)
        return f"{self.family} {'UNICODELABEL' if unicode else 'LABEL'} {application} {language} {group} {action} F{variant}"

    def raw(self, application, group, options, data, *, language=0, action_selector=None, variant=0):
        prefix = self._prefix(application, group, language, action_selector, variant)
        _integer(options, "Options")
        data = _bytes(data, 14)
        return self.client.command(f"{prefix} {options}" + (" " + data.hex() if data else ""))

    def text(self, application, group, text, *, language=0, action_selector=None, variant=0):
        if not isinstance(text, str):
            raise LabelError("Text label must be a string")
        try:
            data = text.encode("ascii")
        except UnicodeEncodeError as error:
            raise LabelError("ASCII label contains Unicode; use unicode()") from error
        if any(value < 32 or value == 127 for value in data):
            raise LabelError("ASCII labels cannot contain control characters")
        # RAW options0 preserves all spaces and punctuation without depending on
        # C-Gate's dequoting rules. Empty native TEXT is encoded as a NUL byte.
        return self.raw(application, group, 0, data or b"\0", language=language, action_selector=action_selector, variant=variant)

    def icon(self, application, group, icon, *, language=0, action_selector=None, variant=0):
        prefix = self._prefix(application, group, language, action_selector, variant)
        _integer(icon, "Icon selector", maximum=65535)
        return self.client.command(f"{prefix} ICON {icon}")

    def dynamic(self, application, group, icon, width, height, data, *, language=0, vertical_offset=0, action_selector=None, variant=0):
        prefix = self._prefix(application, group, language, action_selector, variant)
        data = _bitmap(icon, width, height, vertical_offset, data)
        return self.client.command(f"{prefix} DYNAMIC {icon} {width} {height} {vertical_offset} {data.hex()}")

    def set_language(self, application, group, language, *, action_selector=None):
        prefix = self._prefix(application, group, language, action_selector, 0)
        return self.client.command(prefix + " SET_LANGUAGE")

    def unicode_raw(self, application, group, data, *, language=0, action_selector=None, variant=0):
        if self.family == "ENABLE":
            raise LabelError("C-Gate 3.4 ENABLE has no UNICODELABEL command")
        prefix = self._prefix(application, group, language, action_selector, variant, unicode=True)
        data = _bytes(data)
        encode_unicode_label(group, language, data, action_selector=action_selector, variant=variant)
        return self.client.command(prefix + " RAW" + (" " + data.hex() if data else ""))

    def unicode(self, application, group, text, *, language=0, action_selector=None, variant=0):
        if not isinstance(text, str):
            raise LabelError("Unicode label must be a string")
        try:
            data = text.encode("utf-8", errors="strict")
        except UnicodeEncodeError as error:
            raise LabelError("Unicode label contains an unpaired surrogate") from error
        return self.unicode_raw(application, group, data, language=language, action_selector=action_selector, variant=variant)
