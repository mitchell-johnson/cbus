"""Field-specific thermostat temperature load and save boundaries.

These pure codecs distinguish a raw PP snapshot from the live integer model.
They do not initialize controls, dispatch callbacks or authorize a native save.
The explicit Toolkit process preference is independent of TemperatureUnits PP.
"""
from __future__ import annotations

from collections.abc import Mapping

from .thermostat_post_load import TEMPERATURE_SAVE_RULES
from .thermostat_temperature import convert_temperature


class TemperatureModelError(ValueError):
    """Temperature data cannot be represented by this model/PP boundary."""


# Capture the existing source-pinned rules; no second conversion table is kept.
_FIELD_RULES = tuple(TEMPERATURE_SAVE_RULES.items())
TEMPERATURE_FIELDS = tuple(name for name, _rule in _FIELD_RULES)


def _preference(value: str) -> str:
    if type(value) is not str or value not in ('celsius', 'fahrenheit'):
        raise TemperatureModelError('Temperature preference must be celsius or fahrenheit')
    return value


def _values(values: Mapping[str, int], *, raw: bool) -> dict[str, int]:
    if not isinstance(values, Mapping):
        raise TemperatureModelError('Temperature fields require a mapping')
    result = {}
    for name in TEMPERATURE_FIELDS:
        if name not in values:
            raise TemperatureModelError('Missing temperature field: ' + name)
        value = values[name]
        lower, upper = (0, 255) if raw else (-(1 << 31), (1 << 31) - 1)
        if type(value) is not int or not lower <= value <= upper:
            domain = 'one-byte integer' if raw else 'signed 32-bit model integer'
            raise TemperatureModelError(name + ' must be a ' + domain)
        result[name] = value
    return result


def decode_temperature_fields(
    raw_snapshot: Mapping[str, int], *, temperature_preference: str,
) -> dict[str, int]:
    """Load all 15 raw bytes once into the source model's integer units.

    Validate every consumed field before conversion. Unrelated snapshot keys
    are neither consumed nor changed. The returned mapping contains only the
    fifteen temperature fields; it is data, not a control or save receipt.
    """
    preference = _preference(temperature_preference)
    raw = _values(raw_snapshot, raw=True)
    result = {}
    for name, (load_method, _save_method, signed, _upper_clamp) in _FIELD_RULES:
        value = raw[name]
        if signed and value >= 128:
            value -= 256
        result[name] = convert_temperature(load_method, value, units=preference)
    return result


def encode_temperature_fields(
    live_model: Mapping[str, int], *, temperature_preference: str,
) -> dict[str, int]:
    """Save final live model integers once, without another raw-byte load.

    Signed fields use the evidenced low-byte store. Only the two upper guard
    fields have an additional 127 cap. Plain unsigned stores refuse results
    outside 0..255; they are never wrapped to make a native PP write fit.
    """
    preference = _preference(temperature_preference)
    model = _values(live_model, raw=False)
    result = {}
    for name, (_load_method, save_method, signed, upper_clamp) in _FIELD_RULES:
        value = convert_temperature(save_method, model[name], units=preference)
        if upper_clamp is not None:
            value = min(value, upper_clamp)
        if signed:
            value &= 255
        elif not 0 <= value <= 255:
            raise TemperatureModelError(
                name + ' save result cannot be represented by one PP byte: ' + str(value))
        result[name] = value
    return result
