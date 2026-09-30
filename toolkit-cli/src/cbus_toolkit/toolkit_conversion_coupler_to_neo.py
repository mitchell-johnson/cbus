"""Original Toolkit coupler-to-Neo conversion at the native default revisions.

The selected sources use the classic key agent, but the target is the distinct
CouplerPro agent. Its constructor inherits CoreNeoPro directly and its final
conversion hook disables brightness after the inherited NeoPro hook runs.
"""
from __future__ import annotations

from .toolkit_conversion_key_to_neo import NEOPRO_ATTRIBUTES, apply_key_hooks
from .unitspec import UnitSpec


COUPLER_SOURCE_TYPES = ('KEYBC2', 'KEYBC4', 'DINAUX4')
COUPLER_TARGET_TYPES = ('BCN2B', 'BCN4B', 'BCI4A')
SOURCE_FIRMWARE = '1.2.67'
TARGET_FIRMWARE = '2.2.00'
# CoreNeoPro's 62 attributes, then CoreBusCoupler's two constructor additions.
# Unlike TCBusNeoProInputCGateAgent, this class never adds NightlightColour.
COUPLER_ATTRIBUTES = NEOPRO_ATTRIBUTES[:-1] + (
    ('BistableSwitchBlock', True), ('GroupAssertOnPowerup', True),
)


def require_target_firmware(firmware):
    if firmware != TARGET_FIRMWARE:
        raise ValueError('Coupler-to-Neo conversion requires the fresh-target firmware 2.2.00 profile')


def apply_coupler_hooks(values, mutable, origin, not_written):
    """Run the inherited tweaker/Learn/CoreKey/NeoPro chain, then CouplerPro."""
    # The coupler model's LearnModePropertiesEnabled override is constant true.
    # It therefore selects the same enabled Learn flags as the classic profile.
    apply_key_hooks(values, mutable, origin, not_written)
    mutable['IndicatorBrightness'] = False
    not_written['IndicatorBrightness'] = 'CouplerPro conversion hook makes brightness immutable'


def validate_coupler_spec(unit_type, spec, *, source):
    allowed = COUPLER_SOURCE_TYPES if source else COUPLER_TARGET_TYPES
    firmware = SOURCE_FIRMWARE if source else TARGET_FIRMWARE
    # This exact alias is in the native catalogue; no other cross-type alias is inferred.
    expected_type = 'BCN4B' if unit_type == 'BCI4A' and not source else unit_type
    if (unit_type not in allowed or not isinstance(spec, UnitSpec) or spec.unit_type != expected_type
            or spec.filename != expected_type + '.xml' or not spec.supports_version(firmware)):
        raise ValueError('Coupler-to-Neo conversion requires the matching 1.2.67 source / 2.2.00 target specifications')
    shapes = {
        'Application': ('int', 2, 8),
        'GroupAddress': ('int', 8 if source else 9, 8),
        'IndicatorFunction': ('int', 4 if source else 8, 2),
        'LearnAnyApp': ('bit', 1, 8), 'LearnMode': ('bit', 1, 8), 'LearnedFlag': ('bit', 1, 8),
    }
    if not source:
        shapes.update({name: ('int', 1, 8) for name in
                       ('IndicatorBrightness', 'BistableSwitchBlock', 'GroupAssertOnPowerup')})
    for name, expected in shapes.items():
        parameter = spec.parameters.get(name)
        if parameter is None or (parameter.type, parameter.array_size, parameter.bit_size) != expected:
            raise ValueError(f'Unsupported coupler-to-Neo PP shape for {name}')
