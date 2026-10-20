"""Wave-14 offline pins for DIN relay/dimmer guard semantics (P5.03 #40).

Narrow scope: plan-time guards in cbus_toolkit.din_output_settings only,
using a synthetic spec (no session I/O, hardware, or save path). Each pinned
guard phrase has zero prior references in tests/.
"""

import pytest

from cbus_toolkit.din_output_settings import (
    FIRMWARE,
    LAYOUTS,
    PROFILES,
    DinOutputEditor,
    DinSettingsError,
)
from cbus_toolkit.unitspec import ParameterSpec, UnitSpec


def fixture(unit_type):
    """Synthetic spec with the admitted layout plus two unrelated parameters."""
    profile = PROFILES[unit_type]
    rows = dict(LAYOUTS[profile.spec_filename])
    count = rows['LevelStoreEnable'][1]
    defaults = {'InterLockingChannel': [0], 'LogicLevelStoreEnable': [1] * 4, 'RestrikeDelay': [60],
                'GroupAddress': [255] * 16, 'LightLevel': [0] * 16, 'LevelStoreEnable': [1] * count,
                'PowerUpDelay': [5] * count, 'MinDimmingLevel': [0] * count,
                'MaxDimmingLevel': [255] * rows['MaxDimmingLevel'][1]}
    parameters = {}
    for name, (address, size, bits, bit, skip, kind) in rows.items():
        fields = {'Name': name, 'Type': kind, 'Address': str(address), 'ArraySize': str(size),
                  'BitAddress': str(bit), 'ArraySkip': str(skip),
                  'DefaultValue': ' '.join(map(str, defaults.get(name, [0] * size)))}
        if kind == 'int':
            fields.update(BitSize=str(bits), MinValue='0', MaxValue='1' if bits == 1 else '255')
        parameters[name] = ParameterSpec(name, kind, 'literal-din-fixture.xml', fields)
    for name, address, value in (('UnitAddress', 32, '255'), ('AreaGroupAddress', 67, '255')):
        parameters[name] = ParameterSpec(name, 'int', 'literal-din-fixture.xml', {
            'Name': name, 'Type': 'int', 'Address': str(address), 'DefaultValue': value})
    return UnitSpec(profile.spec_filename, {'Type': unit_type}, ('literal-din-fixture.xml',), parameters)


def test_wave14_channel_logic_group_association_guards():
    editor = DinOutputEditor(fixture('RELDN4'), 'RELDN4')
    current = fixture('RELDN4').defaults()
    with pytest.raises(DinSettingsError, match='Logic groups must be a collection of 1..4'):
        editor.plan(current, channel=1, logic_groups=5)
    with pytest.raises(DinSettingsError, match='Logic group association must be an integer in 1..4'):
        editor.plan(current, channel=1, logic_groups=[0])
    with pytest.raises(DinSettingsError, match='Logic group association must be an integer in 1..4'):
        editor.plan(current, channel=1, logic_groups=[5])


def test_wave14_logic_group_selector_and_auto_store_guards():
    editor = DinOutputEditor(fixture('DIMDN4'), 'DIMDN4')
    current = fixture('DIMDN4').defaults()
    with pytest.raises(DinSettingsError, match='disables a logic group selector'):
        editor.plan(current, logic_group=2, logic_group_address=40)
    associated = fixture('DIMDN4').defaults()
    groups = [255] * 16
    groups[13] = 40
    associated['GroupAddress'] = ' '.join(map(str, groups))
    associated['LogicGA14Associations'] = '0 0 1 0'
    with pytest.raises(DinSettingsError, match='Logic Auto Level Store is enabled'):
        editor.plan(associated, logic_group=2, logic_recovery_level=9)


def test_wave14_relay_logic_function_names():
    relay = DinOutputEditor(fixture('RELDN4'), 'RELDN4')
    with pytest.raises(DinSettingsError, match='Logic function must be and or or'):
        relay.plan(fixture('RELDN4').defaults(), channel=1, logic_function='max')
    dimmer = DinOutputEditor(fixture('DIMDN4'), 'DIMDN4')
    with pytest.raises(DinSettingsError, match='Logic function must be min or max'):
        dimmer.plan(fixture('DIMDN4').defaults(), channel=1, logic_function='or')


def test_wave14_restrike_and_interlock_type_guards():
    editor = DinOutputEditor(fixture('RELDN4'), 'RELDN4')
    current = fixture('RELDN4').defaults()
    with pytest.raises(DinSettingsError, match='Restrike must be boolean'):
        editor.plan(current, channel=1, restrike='yes')
    with pytest.raises(DinSettingsError, match=r'Interlock channel count must be 0 or 2\.\.4'):
        editor.plan(current, interlock=True)
    with pytest.raises(DinSettingsError, match=r'Interlock channel count must be 0 or 2\.\.4'):
        editor.plan(current, interlock=1)
    assert FIRMWARE == '2.7.00'
