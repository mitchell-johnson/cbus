"""Pin constructor/load provenance for the fresh programmable quick-zone seed.

Read-only EXE/MAP inspection. No original instructions, GUI, native service,
production planner, or instruction emulator are executed/imported here.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from topology_generator_static import EXE_SHA256, MAP_SHA256, _Image
from thermostat_post_load_static import _Walker
from thermostat_settings_temperature_static import original_vectors

MODEL = 'CIS_TThermostat.'
AGENT = 'CIS_TCBusThermostatCGateAgent.TCBusThermostatCGateAgent.'
PROGRAM = 'CIS_TCBusThermostatCGateAgent.TCBusProgrammableThermostatCGateAgent.'
CLASSES = ('TThermostat', 'TProgrammableThermostat', 'TCBusParameters',
           'TZoneManagerService', 'TPlantControlService',
           'TTemperatureMeasurementService', 'TUIService', 'TAdvancedUIService',
           'TTimeService', 'TScheduleService', 'TThermostatInstallations')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def inspect(exe, map_path, seed_path):
    raw, map_raw, seed_raw = exe.read_bytes(), map_path.read_bytes(), seed_path.read_bytes()
    if (sha(raw), sha(map_raw)) != (EXE_SHA256, MAP_SHA256):
        raise ValueError('Pinned original source mismatch')
    seed = json.loads(seed_raw)
    image = _Image(raw, map_raw)
    walker, methods, checks = _Walker(image), {}, {}

    def rows(name):
        if name not in methods:
            methods[name] = walker.listing(name)
        return methods[name][0]

    def at(method, address, mnemonic, operands):
        checks[method + '@' + hex(address)] = any(a == address and m == mnemonic and op == operands
                                                for a, m, op, _ in rows(method))

    def calls(method):
        return [note for _a, m, _op, note in rows(method) if m == 'call' and note]

    # Inventory declarations, not inferred production field definitions. A
    # literal-name constructor must immediately store its result into Self.
    def inventory(method):
        result = []
        listing = rows(method)
        for index, (address, mnemonic, _operands, note) in enumerate(listing):
            if mnemonic != 'call' or not note.endswith('.Create'):
                continue
            previous = listing[max(0, index - 12):index]
            names = [(a, image.literal(int(op, 16))) for a, m, op, _ in previous
                     if m == 'push' and re.fullmatch(r'0x[0-9a-f]+', op)]
            names = [(a, name) for a, name in names if name is not None]
            classes = [n for _a, m, _op, n in previous if m == 'mov' and '..' in n]
            stores = [(a, re.fullmatch(r'dword ptr \[edx \+ (0x[0-9a-f]+)\], eax', op))
                      for a, m, op, _ in listing[index + 1:index + 4] if m == 'mov']
            stores = [(a, match) for a, match in stores if match]
            if names and classes and len(stores) == 1:
                result.append({'name': names[-1][1], 'class': classes[-1],
                               'slot': stores[0][1].group(1), 'constructor': note,
                               'callsite': hex(address), 'store': hex(stores[0][0])})
        return result

    declarations = {cls: inventory(MODEL + cls + '.InternalCreate') for cls in CLASSES}
    declarations['TZones'] = inventory('CIS_TThermostatCommon.TZones.InternalCreate')
    for cls in CLASSES:
        for suffix in ('AfterConstruction', 'HookEvents', 'UnhookEvents', 'UnHookEvents'):
            name = MODEL + cls + '.' + suffix
            if name in image.by_name:
                rows(name)

    allocations = {}
    for cls in CLASSES:
        method = MODEL + cls + '.AfterConstruction'
        if method not in image.by_name:
            continue
        output = []
        listing = rows(method)
        for i, (address, m, _op, note) in enumerate(listing):
            if m != 'call' or note != 'CIS_TCustomFlashObject.TCustomFlashObject.CreateInWorkSpace':
                continue
            class_names = [n for _a, mn, _o, n in listing[max(0, i - 4):i] if mn == 'mov' and '..' in n]
            field = [re.fullmatch(r'eax, dword ptr \[eax \+ (0x[0-9a-f]+)\]', op)
                     for _a, mn, op, _n in listing[i + 1:i + 6] if mn == 'mov']
            field = [f.group(1) for f in field if f]
            if len(class_names) != 1 or len(field) != 1:
                raise ValueError('Ambiguous constructor allocation')
            output.append({'class': class_names[0], 'object_attribute_slot': field[0], 'callsite': hex(address)})
        allocations[cls] = output
    checks['base_constructs_six_owned_children'] = len(allocations['TThermostat']) == 6
    checks['programmable_constructs_advanced_ui_time_schedule'] = [x['class'] for x in allocations['TProgrammableThermostat']] == [MODEL + '.' + c for c in ('TAdvancedUIService', 'TTimeService', 'TScheduleService')]

    hooks = {}
    for cls in CLASSES:
        method = MODEL + cls + '.HookEvents'
        if method not in image.by_name:
            continue
        output, attr = [], None
        for address, m, op, note in rows(method):
            slot = re.fullmatch(r'eax, dword ptr \[eax \+ (0x[0-9a-f]+)\]', op)
            if m == 'mov' and slot:
                attr = slot.group(1)
            if m == 'mov' and op.startswith('dword ptr [eax + 0x60], 0x'):
                output.append({'attribute_slot': attr, 'handler': note, 'callsite': hex(address)})
        hooks[cls] = output
    checks['advanced_ui_hooks_only_two_flags'] = [x['attribute_slot'] for x in hooks['TAdvancedUIService']] == ['0xb8', '0xbc']
    checks['advanced_ui_hook_does_not_call_base_hook'] = not calls(MODEL + 'TAdvancedUIService.HookEvents')
    advanced_vmt = walker.dword(image.by_name[MODEL + '.TAdvancedUIService'])
    checks['advanced_ui_hook_vmt'] = walker.dword(advanced_vmt + 0x7c) == image.by_name[MODEL + 'TAdvancedUIService.HookEvents']
    checks['advanced_ui_unhook_vmt'] = walker.dword(advanced_vmt + 0x80) == image.by_name[MODEL + 'TAdvancedUIService.UnhookEvents']
    checks['advanced_ui_declarations_only_flags'] = [x['name'] for x in declarations['TAdvancedUIService']] == ['EvapProgramEnabled', 'NonEvapProgramEnabled']
    at('CIS_TBooleanAttribute.TBooleanAttribute.InternalCreate', 0x7f4511, 'mov', 'byte ptr [eax + 0x70], 0')
    checks['zones_construct_five_boolean_attributes'] = len(declarations['TZones']) == 5 and all(
        x['class'] == 'CIS_TBooleanAttribute..TBooleanAttribute' for x in declarations['TZones'])
    at(MODEL + 'TThermostat.AfterConstruction', 0xfea5b2, 'call', '0x7ea6ac')
    at(MODEL + 'TThermostat.AfterConstruction', 0xfea5bc, 'mov', 'eax, dword ptr [eax + 0x1d8]')
    at(MODEL + 'TThermostat.AfterConstruction', 0xfea5c4, 'call', 'dword ptr [ecx + 0xa8]')
    callback_wiring = {}
    for cls in CLASSES:
        name = MODEL + cls + '.AfterConstruction'
        if name not in image.by_name:
            continue
        callback_wiring[cls] = [
            {'store': hex(a), 'instruction': op, 'handler': n}
            for a, m, op, n in rows(name)
            if m == 'mov' and n.startswith(MODEL) and '..' not in n]

    # A direct-call scan supplements, rather than replaces, the exact virtual
    # dispatch pin above. This does not rule out arbitrary indirect callbacks.
    direct_base_ui_hook_sites = []
    targets = {image.by_name[MODEL + 'TUIService.' + n] for n in ('HookEvents', 'UnhookEvents')}
    for section in image.pe.sections:
        if not section.Characteristics & 0x20000000:
            continue
        data, start = section.get_data(), image.base + section.VirtualAddress
        cursor = 0
        while (cursor := data.find(b'\xe8', cursor)) >= 0:
            if cursor + 5 <= len(data):
                destination = (start + cursor + 5 + struct.unpack_from('<i', data, cursor + 1)[0]) & 0xffffffff
                if destination in targets:
                    direct_base_ui_hook_sites.append(hex(start + cursor))
            cursor += 1
    checks['no_direct_base_ui_hook_call_in_executable_code_sections'] = not direct_base_ui_hook_sites

    load, derived = AGENT + 'AfterLoadProgrammingInformation', PROGRAM + 'AfterLoadProgrammingInformation'
    load_windows = [
        ('CBus', 0x128e0aa, 0xfdb9f0, 0x128e4eb, 0xfdb9d0),
        ('ZoneManager', 0x128e539, 0xfde154, 0x128ec8c, 0xfde088),
        ('Plant', 0x128eca6, 0xfe16b0, 0x128f81e, 0xfe1664),
        ('Measurement', 0x128f830, 0xfdc038, 0x128f8f7, 0xfdc018),
        ('Schedule', 0x1299b22, 0xfea094, 0x1299b63, 0xfea074)]
    for service, begin, unhook, end, hook in load_windows:
        method = derived if service == 'Schedule' else load
        at(method, begin, 'call', hex(unhook))
        at(method, end, 'call', hex(hook))
    at(derived, 0x12994f5, 'call', '0x128e06c')
    at(derived, 0x129953a, 'call', 'dword ptr [edx + 0x80]')
    at(derived, 0x1299abe, 'call', 'dword ptr [edx + 0x7c]')
    at(load, 0x128e527, 'call', '0xf30014')
    for name in ('CreateInWorkSpace', 'Create', 'CreateComplete', 'GetWorkSpace', 'SetWorkSpace'):
        rows('CIS_TCustomFlashObject.TCustomFlashObject.' + name)
    for name in ('Create', 'AfterConstruction', 'CreateComplete'):
        rows('CIS_TManagedFlashObject.TManagedFlashObject.' + name)
    rows(MODEL + 'TPlantControlService.HandleVentPlantTypeChange')

    pp = seed['pp']
    expected = {'ApplicationNumber': 56, 'RemoteScheduleEnable': 0,
                'DisplayBacklightActiveBrightness': 201, 'KeyBacklightActiveBrightness': 201,
                'EvapProgramEnabled': 0, 'NonEvapProgramEnabled': 0,
                'InstalledZones': 3, 'ControlledZones': 3,
                'HeatingPlantType': 0, 'CoolingPlantType': 0, 'VentingPlantType': 0}
    checks['corrected_native_seed'] = all(int(pp[k], 0) == v for k, v in expected.items())
    vectors, temperatures = original_vectors(), {}
    for field, profile in vectors['fields'].items():
        raw_value = int(pp[field], 0)
        row = next(row for row in vectors['profiles'][profile]['rows'] if row[:2] == [False, raw_value])
        temperatures[field] = {'raw': raw_value, 'model': row[2], 'saved': row[4]}
    checks['fifteen_temperature_fixed_points'] = len(temperatures) == 15 and all(x['raw'] == x['saved'] for x in temperatures.values())
    if failures := [k for k, passed in checks.items() if not passed]:
        raise ValueError('Source check failed: ' + ', '.join(failures))
    return {
        'format': 'cbus-thermostat-quick-zone-constructor-static-v1',
        'original_exe_sha256': EXE_SHA256, 'original_map_sha256': MAP_SHA256,
        'native_seed_sha256': sha(seed_raw), 'checks': checks, 'check_count': len(checks),
        'model_attribute_declarations': declarations, 'owned_child_allocations': allocations,
        'service_attribute_hooks': hooks, 'constructor_callback_wiring': callback_wiring,
        'direct_base_ui_hook_calls': direct_base_ui_hook_sites,
        'fresh_used_zones_constructor_mask': 0,
        'after_load_event_suppression': [{'service': n, 'unhook_call': hex(a), 'hook_call': hex(b)}
                                       for n, a, _u, b, _h in load_windows],
        'temperature_fixed_points': temperatures,
        'methods': {name: {'address': hex(image.by_name[name]), 'sha256': data[2]}
                    for name, data in sorted(methods.items())},
        'original_executed': False, 'constructors_executed': False,
        'complete_initialization_closed': False, 'public_action_admission': False,
        'runtime_bridge': {
            'smallest_next_boundary': 'Original AdvancedUI Unhook/Hook on two zero flag attributes, actual AdvancedUI VMT, no injected base UIAllocatedZones callback; then bounded IncludeZone with fresh constructor UsedZones0, subject to separately verified pre-click initialization.',
            'full_after_load_prerequisites': [
                'All declared inherited and service attributes, object-reference graph and type-correct integer/string/enum PP agents.',
                'Explicit workspace, allocator, object registration and CreateInWorkSpace constructors, or retain an explicit source-shaped synthetic-graph boundary.',
                'Existing network254, output application56/group255, AC172/group255, Enable203/group255 and actuator115/116 with non-bare tags.',
                'Preserve original unhook/load/hook order; Plant VentPlantType2 under active hooks can change VentingPlantType0 and fan state.',
                'Installation-list construction and source-exact InstallationCode0 selection.',
                'Global Celsius preference unchanged; integer/string/variant and enum collection callbacks beyond current Boolean-only ABI closure.'],
            'remaining_gui_boundary': 'Initial binding, whether any event changes constructor UsedZones0 before the click, queued Plant type message0x423 and combo/native notification ordering; a scalar fixed point is not complete form preservation.'},
        'limits': [
            'Attribute inventory is explicit declarations of listed classes, not complete inherited CBus/network/workspace object layout.',
            'No whole-form execution, original PP load/save/reload or constructor execution is established.',
            'Prior four-callback core fixture manually used TUIService. It is not evidence for fresh programmable AdvancedUI callback wiring.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('exe', 'map', 'seed', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    report = inspect(args.exe, args.map, args.seed)
    report['checker_sha256'] = sha(Path(__file__).read_bytes())
    with args.output.open('x') as output:
        json.dump(report, output, indent=2, sort_keys=True)
        output.write('\n')
    print(json.dumps({'checks': report['check_count'], 'methods': len(report['methods']),
                      'attribute_declarations': sum(map(len, report['model_attribute_declarations'].values()))}))


if __name__ == '__main__':
    main()
