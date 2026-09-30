"""Pin a conservative fresh programmable thermostat initialization candidate.

This reads the original image and joins prior captured arithmetic observations.
It does not execute a form, prove generic dispatch, or admit a public action.
The synthetic seed describes explicit existing graph objects, never hardware.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import extract_toolkit_executable_surface as dfm  # noqa: E402
from topology_generator_static import EXE_SHA256, MAP_SHA256, _Image  # noqa: E402
from thermostat_post_load_static import _Walker  # noqa: E402
from thermostat_settings_temperature_static import original_vectors, _attribute_definitions  # noqa: E402

AGENT = 'CIS_TCBusThermostatCGateAgent.TCBusThermostatCGateAgent.'
PROGRAM = 'CIS_TCBusThermostatCGateAgent.TCBusProgrammableThermostatCGateAgent.'
PARENT = 'CIS_TddThermostat.TddThermostat.'
PLANT = 'CIS_TThermostat.TPlantControlService.'
NETWORK = 'CIS_TCommonCBus.TCBusNetwork.'
APPS = 'CIS_TCommonCBus.TCBUSApplicationManager.'
GROUPS = 'CIS_TCommonCBus.TCBusGroupManager.'
TEMPCONTROL = 'CIS_TcdThermostatTempControl.TcdThermostatTempControl.'
ZONE_PANEL = 'CIS_TcdThermostatZoneManagement.TcdThermostatZoneManagement.'
TEMPERATURE_SEED = {
    'MaximumSetTemperature': (32, 32), 'MinimumSetTemperature': (15, 15),
    'GuardUpperTemperature': (80, 40), 'GuardMaximumUpperTemperature': (100, 45),
    'GuardMinimumUpperTemperature': (52, 33), 'GuardLowerTemperature': (196, 5),
    'GuardMaximumLowerTemperature': (216, 10), 'GuardMinimumLowerTemperature': (176, 0),
    'SetbackLevel': (196, 5), 'TemperatureSendDifferential': (32, 8),
}
BOUNDS = {
    'trkMaximumSetTemp': (10, 37), 'trkMinimumSetTemp': (-10, 30),
    'trkGuardMaximumLowerTemp': (-6, 20), 'trkGuardMinimumLowerTemp': (-11, 15),
    'trkGuardLowerTemp': (-11, 20), 'trkGuardUpperTemp': (25, 51),
    'trkGuardMaximumUpperTemp': (30, 51), 'trkGuardMinimumUpperTemp': (25, 46),
}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def dfm_properties(image, resource_name):
    for entry in image.pe.DIRECTORY_ENTRY_RESOURCE.entries:
        if entry.id != 10:
            continue
        for resource in entry.directory.entries:
            if dfm._entry_name(resource) != resource_name:
                continue
            leaf = dfm._resource_leaves(resource)[0]
            raw = image.pe.get_data(leaf.data.struct.OffsetToData, leaf.data.struct.Size)
            cursor, result = dfm.Cursor(raw, 4), {}

            def component(depth):
                cls, name = dfm._read_component_header(cursor, version=raw[3] - ord('0'))
                props = {}
                while cursor.peek_u8() != 0:
                    key = dfm._text(cursor.short_bytes())
                    props[key] = dfm._read_value(cursor, depth=depth + 1)
                cursor.u8()
                result[name] = {'class': cls, 'properties': props}
                while cursor.peek_u8() != 0:
                    component(depth + 1)
                cursor.u8()

            component(0)
            if cursor.remaining:
                raise ValueError('Unparsed DFM data')
            return raw, result
    raise ValueError('Missing DFM resource: ' + resource_name)


def inspect(exe, map_path):
    raw, map_raw = exe.read_bytes(), map_path.read_bytes()
    if (sha(raw), sha(map_raw)) != (EXE_SHA256, MAP_SHA256):
        raise ValueError('Original EXE/MAP hashes differ')
    image = _Image(raw, map_raw)
    walker, methods, checks = _Walker(image), {}, {}

    def method(name):
        if name not in methods:
            methods[name] = walker.listing(name)
        return methods[name][0]

    def at(name, address, mnemonic, operand):
        checks[hex(address)] = any(a == address and m == mnemonic and op == operand
                                  for a, m, op, _n in method(name))

    def calls(name):
        return [n for _a, m, _op, n in method(name) if m == 'call' and n]

    load = AGENT + 'AfterLoadProgrammingInformation'
    programmable_load = PROGRAM + 'AfterLoadProgrammingInformation'
    special = AGENT + 'CreateSpecialApplications'
    for address, mnemonic, operand in (
        (0x128dfca, 'mov', 'edx, 0xac'), (0x128dfdb, 'jne', '0x128e030'),
        (0x128e03b, 'call', '0xfecc78')):
        at(special, address, mnemonic, operand)
    for address, mnemonic, operand in (
        (0x128e1d0, 'mov', 'edx, 0x73'), (0x128e1dc, 'jne', '0x128e299'),
        (0x128e2d9, 'jne', '0x128e33a'), (0x128e34f, 'mov', 'edx, 0x74'),
        (0x128e35b, 'jne', '0x128e418'), (0x128e458, 'jne', '0x128e4b9'),
        (0x128e942, 'jne', '0x128e9d9'), (0x128e9ec, 'jne', '0x128ea7c'),
        (0x128ea89, 'xor', 'edx, edx'), (0x128ea9d, 'xor', 'edx, edx'),
        (0x128ebca, 'je', '0x128ebfe'), (0x128ec36, 'je', '0x128ec6a'),
        (0x128f654, 'jne', '0x128f7ae')):
        at(load, address, mnemonic, operand)
    at(AGENT + 'LoadThermostatInstallations', 0x1292e37, 'mov', 'dword ptr [eax + 0x88], edx')
    at(AGENT + 'LoadThermostatInstallations', 0x129367d, 'je', '0x129397a')
    checks['custom_installation_resource'] = image.resource(0x128b208) == '<Custom>'
    checks['legacy_actuator_tag_literals'] = (image.literal(0x128f980), image.literal(0x128f994)) == ('115', '116')
    checks['actuator_tag_resources'] = tuple(image.resource(walker.dword(p)) for p in
                                            (0x13c3cc4, 0x13c3e48)) == ('HVAC Actuator 1', 'HVAC Actuator 2')
    at(APPS + 'ApplicationByAddress', 0xf2657b, 'jne', '0xf2661e')
    at(GROUPS + 'GroupByAddress', 0xf28ba8, 'jne', '0xf28c91')
    at(NETWORK + 'GetEnableControlApplication', 0xf2b13d, 'mov', 'edx, 0xcb')
    checks['find_or_create_application_uses_existing_address_lookup'] = calls(
        NETWORK + 'FindOrCreateApplicationByAddress') == [APPS + 'CheckAndCreate', APPS + 'FindApplicationByAddress']
    for name in ('CheckAndCreate', 'FindApplicationByAddress'):
        method(APPS + name)
    at(programmable_load, 0x1299912, 'je', '0x12999ef')
    for address in (0x1299a07, 0x1299a3f, 0x1299a77):
        at(programmable_load, address, 'xor', 'ecx, ecx')
    checks['disabled_schedule_resolves_three_unused_objects_without_add'] = [n for a, m, _op, n in
        method(programmable_load) if 0x12999ef <= a < 0x1299a97 and m == 'call'].count(GROUPS + 'GroupByAddress') == 3
    # Disabled model groups and their saved raw defaults differ: loading nil
    # or the unused sentinel is not evidence that BeforeSave writes 255.
    save = AGENT + 'BeforeSaveProgrammingInformation'
    for address, mnemonic, operand in (
        (0x1294d80, 'jle', '0x1294df8'), (0x1294dfe, 'mov', 'edx, 0x1e'),
        (0x1294e24, 'mov', 'edx, 0x1f'), (0x1294ffc, 'call', '0xf47a10')):
        at(save, address, mnemonic, operand)
    for address, mnemonic, operand in (
        (0x1299fea, 'je', '0x129a0c9'), (0x129a0cf, 'xor', 'edx, edx'),
        (0x129a0f2, 'mov', 'edx, 0x20'), (0x129a118, 'mov', 'edx, 0x21'),
        (0x129a13e, 'mov', 'edx, 0x22')):
        at(PROGRAM + 'BeforeSaveProgrammingInformation', address, mnemonic, operand)
    at(AGENT + 'GetMasterUnitNetwork', 0x128fa6b, 'call', '0xf29558')

    getter_names = [n for n in calls(load) if n.startswith(PLANT + 'GetDefault') and 'OutputGroup' in n]
    checks['eighteen_output_and_damper_getters'] = len(getter_names) == len(set(getter_names)) == 18
    for name in getter_names:
        rows = method(name)
        index = next(i for i, (_a, m, op, _n) in enumerate(rows)
                     if m == 'cmp' and op == 'dword ptr [ebp - 8], 0xff')
        window = rows[index:index + 7]
        checks[name + '_255_short_circuit'] = (window[1][1] == 'jne'
            and window[3][3] == PLANT + 'GetUnusedGroup' and window[5][1] == 'jmp')
    at(PLANT + 'GetUnusedGroup', 0xfe6028, 'mov', 'cl, 1')
    at(PLANT + 'GetUnusedGroup', 0xfe602a, 'mov', 'edx, 0xff')
    # Database-only single-network inventory avoids refreshing any other unit.
    for address, mnemonic, operand in ((0xff192e, 'cmp', 'byte ptr [eax + 0xdd], 0'),
        (0xff1935, 'je', '0xff1948'), (0xff194e, 'mov', 'eax, dword ptr [eax + 0xd8]'),
        (0xff19d7, 'je', '0xff1afb')):
        at(ZONE_PANEL + 'LoadMasterUnits', address, mnemonic, operand)
    method(ZONE_PANEL + 'LoadMasterUnitNetworks')
    derived = 'CIS_TddThermostat.TddProgrammableThermostat.InitialiseSubForms'
    checks['programmable_initializes_scheduling_after_base'] = calls(derived).index(PARENT + 'InitialiseSubForms') < calls(
        derived).index('CIS_TcdThermostatScheduling.TcdThermostatScheduling.Create')
    for panel in ('CBus', 'UI', 'ZoneManagement', 'Plant', 'TempControl', 'Templates', 'Scheduling'):
        for action in ('Initialise', 'SetupFlashComponents'):
            method('CIS_TcdThermostat' + panel + '.TcdThermostat' + panel + '.' + action)
    for name in (PARENT + 'InitialiseSubForms', PARENT + 'UpdateZoneCheckboxes',
                 TEMPCONTROL + 'SetGuardTemperatureLimits', TEMPCONTROL + 'SetMinMaxTemperatureLimits_GuardEnabled',
                 TEMPCONTROL + 'UpdateSliderTemperatureUnit'):
        method(name)
    for panel, callback in (('CBus', 'HandleHeartbeatTimeChange'), ('CBus', 'HandleSystemRefreshTimeChange'),
                            ('Plant', 'HandlePlantMinimumTimeChange'), ('Plant', 'HandlePlantCycleTimeChange')):
        method('CIS_TcdThermostat' + panel + '.TcdThermostat' + panel + '.' + callback)
    at(TEMPCONTROL + 'Initialise', 0x112daf4, 'call', '0x112e9b4')
    at(TEMPCONTROL + 'Initialise', 0x112db1b, 'call', '0x112e888')
    checks['empty_guard_mask_literal'] = image.pe.get_data(0x112db2c - image.base, 1) == b'\0'
    at(TEMPCONTROL + 'SetMinMaxTemperatureLimits_GuardEnabled', 0x112e8f9, 'call', '0xfdfda8')
    at(TEMPCONTROL + 'SetMinMaxTemperatureLimits_GuardEnabled', 0x112e96a, 'call', '0xfdfd48')

    resources = {}
    for name in ('TFRMTHERMOSTATTEMPCONTROL', 'TFRMTHERMOSTATCBUS', 'TFRMTHERMOSTATPLANT'):
        resource, controls = dfm_properties(image, name)
        resources[name] = {'bytes': len(resource), 'sha256': sha(resource)}
        if name == 'TFRMTHERMOSTATTEMPCONTROL':
            for control, bounds in BOUNDS.items():
                properties = controls[control]['properties']
                checks[control + '_dfm_bounds'] = tuple(properties['BarProperties.' + key]
                                                      for key in ('Min', 'Max')) == bounds
        elif name == 'TFRMTHERMOSTATCBUS':
            for control, bounds in (('trkSystemRefreshTime', (3, 60)), ('trkHeartbeatTime', (1, 255))):
                checks[control + '_dfm_bounds'] = tuple(controls[control]['properties']['BarProperties.' + key]
                                                       for key in ('Min', 'Max')) == bounds
        else:
            for control, offset in (('cmbPlantMinimumOnTime', 0), ('cmbPlantMinimumOffTime', 0),
                                     ('cmbPlantCycleTime', -5)):
                properties = controls[control]['properties']
                checks[control + '_index_offset'] = properties['UseIndex'] is True and properties['IndexOffset'] == offset
    pp = _attribute_definitions(image, method(AGENT + 'InternalCreate'))
    checks['guard_enable_pp_name'] = pp['GuardEnable']['slot'] == 0x134
    checks['master_sentinel_slots'] = (pp['MasterAddress']['slot'], pp['MasterNetworkAddress']['slot']) == (0x180, 0x184)
    vectors, temperature = original_vectors(), {}
    for field, (raw_byte, model) in TEMPERATURE_SEED.items():
        profile = vectors['profiles'][vectors['fields'][field]]
        row = next(row for row in profile['rows'] if row[:2] == [False, raw_byte])
        checks[field + '_captured_fixed_point'] = row[2] == model and row[4] == raw_byte
        temperature[field] = {'raw_pp_byte': raw_byte, 'loaded_model_integer': model, 'saved_pp_byte': row[4]}
    if failures := [name for name, ok in checks.items() if not ok]:
        raise ValueError('Initialization source differs: ' + ', '.join(failures))
    if (sha(exe.read_bytes()), sha(map_path.read_bytes())) != (EXE_SHA256, MAP_SHA256):
        raise ValueError('Source changed during inspection')
    return {
        'format': 'cbus-thermostat-quick-zone-initialization-static-v1',
        'original_exe_sha256': EXE_SHA256, 'original_map_sha256': MAP_SHA256,
        'original_executed': False, 'hardware_accessed': False,
        'complete_initialization_closed': False, 'public_action_admission': False,
        'checks': checks, 'method_count': len(methods), 'check_count': len(checks),
        'methods': {name: {'address': hex(image.by_name[name]), 'sha256': data[2]}
                    for name, data in sorted(methods.items())},
        'resources': resources, 'celsius_temperature_fixed_point_seed': temperature,
        'candidate_zone_context': {
            'InstalledZones': 3, 'ControlledZones': 3,
            'seven_used_source_masks': {name: 1 for name in ('UIAllocatedZones', 'InternalPlantZones',
                'MeasuredZones', 'ScheduleControlledZones', 'HeatingPlantInstalledZones',
                'CoolingPlantInstalledZones', 'VentingPlantInstalledZones')},
            'HeatingPlantType': 0, 'CoolingPlantType': 0, 'VentingPlantType': 0,
            'action': 'IncludeZone1 (bit1); original click and nested notification evidence are separate',
        },
        'conservative_additional_scalar_seed': {
            'SystemRefreshTime': 3, 'HeartbeatTime': 3,
            'PlantMinimumOnTime': 1, 'PlantMinimumOffTime': 1, 'PlantCycleTime': 5,
            'HeatingPlantStages': 0, 'CoolingPlantStages': 0, 'FanOperationMode': 0,
            'TemperatureUnits': 0, 'TimeUnits': 0, 'BeepEnable': 0, 'EnableHVACRelayDrive': 0,
        },
        'graph_seed': {
            'inventory': 'One database-only network containing only this programmable thermostat; fresh model/cache.',
            'applications': {'172': 'existing; preserve its tag', '115': 'existing, tag must not be bare 115',
                             '116': 'existing, tag must not be bare 116', '203': 'existing Enable application',
                             'A': 'existing application selected by ApplicationNumber'},
            'groups': ['172/ZoneGroup (255 in candidate)', '203/255', 'A/255'],
            'no_address_duplicates': True,
            'all_14_plant_outputs_4_dampers_5_relays': 255,
            'MasterAddress': 255, 'MasterNetworkAddress': 'N (the existing current network address)',
            'RemoteSetbackControlSource': 0, 'RemoteSetbackOnGroup': 30, 'RemoteSetbackOffGroup': 31,
            'EvapProgramEnabled': 0, 'NonEvapProgramEnabled': 0,
            'RemoteScheduleEnable': 0,
            'RemoteScheduleOnGroup': 32, 'RemoteScheduleOffGroup': 33, 'RemoteScheduleOverrideGroup': 34,
            'GuardEnable': 0, 'toolkit_process_temperature_preference': 'celsius',
            'InstallationCode': 0,
        },
        'save_normalization_traps': {
            'disabled_remote_setback': 'Load resolves nil; save writes raw group bytes 30 and 31.',
            'disabled_remote_schedule': 'Load resolves Enable/255; save writes enable0 and raw groups32/33/34.',
            'MasterNetworkAddress255': 'Load resolves current network object; save writes its actual network address.',
        },
        'limits': [
            'Existing graph lookup paths and selected initialization guards are pinned, not full form execution.',
            'The numeric graph seed excludes application/group allocation and special actuator rename branches.',
            'Temperature seed uses unchanged Celsius preference and prior original arithmetic captures, not production output.',
            'Controller refresh locking, checkbox callbacks, complete model notifications, inherited unit initialization, '
            'installation callbacks and all non-temperature control bounds need their separately scoped evidence.',
            'Do not apply absent-guard or retained-session generalizations; fresh caches and one accepted action are essential.',
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--map', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(inspect(args.exe, args.map), indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
