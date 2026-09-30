"""Corrected bounded quick-zone core fixture with the programmable Advanced UI.

Fresh-model provenance corrections: TAdvancedUIService uses its actual VMT and
original HookEvents/UnhookEvents; UIAllocatedZones has no inherited after-change
callback. UsedZones is explicitly zero before the action, matching its recovered
constructor default while initial Templates binding suppresses its recomputation.
This executes selected original routines over an owned prepared graph. It does
not execute constructors, initial GUI binding, a whole form, PP load/save/reload,
project/group operations, or native Windows notifications.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

import thermostat_quick_zone_original as base

BASE_SHA256 = 'ad112c8653471232598251c98ab1726973539a52075db1c2f8c1e3e5225b5a1d'
ADV = 'CIS_TThermostat.TAdvancedUIService.'
HOOK, UNHOOK = ADV + 'HookEvents', ADV + 'UnhookEvents'
ADV_CLASS = 'CIS_TThermostat..TAdvancedUIService'
UI_HANDLER = 'CIS_TThermostat.TUIService.HandleZoneAfterChange'
SOURCES = (
    ADV + 'InternalCreate', HOOK, UNHOOK,
    'CIS_TThermostat.TProgrammableThermostat.AfterConstruction',
    'CIS_TThermostat.TUIService.AfterConstruction',
    'CIS_TThermostatCommon.TZones.InternalCreate',
    'CIS_TcdThermostatTemplates.TcdThermostatTemplates.Initialise',
    'CIS_TcdThermostatTemplates.UpdateFlashZoneVariables',
    'CIS_TBooleanAttribute.TBooleanAttribute.InternalCreate',
    'CIS_TThermostat.TThermostat.AfterConstruction',
)


def source_routes(exe, map_path):
    original, symbols = exe.read_bytes(), map_path.read_bytes()
    base.require((base.sha(original), base.sha(symbols)) == (base.EXE_SHA256, base.MAP_SHA256), 'Pinned original source')
    base.require(base.sha(Path(base.__file__).read_bytes()) == BASE_SHA256, 'Immutable inherited core probe')
    image = base._Image(original, symbols)
    walker = base._Walker(image)
    listings = {name: walker.listing(name) for name in SOURCES}
    def at(name, address, mnemonic, operands):
        return any((a, m, o) == (address, mnemonic, operands) for a, m, o, _ in listings[name][0])
    def calls(name):
        return [n for _, m, _, n in listings[name][0] if m == 'call']
    vmt = walker.dword(image.by_name[ADV_CLASS])
    checks = {
        'advanced_class_pointer': image.by_name[ADV_CLASS] == 0xfd8ce0 and vmt == 0xfd8d38,
        'actual_virtual_hook': walker.dword(vmt + 0x7c) == image.by_name[HOOK],
        'actual_virtual_unhook': walker.dword(vmt + 0x80) == image.by_name[UNHOOK],
        'advanced_internal_create_calls_base_then_two_flags': calls(ADV + 'InternalCreate') == [
            'CIS_TThermostat.TUIService.InternalCreate',
            'CIS_TCustomFlashObject.TFlashAttribute.Create',
            'CIS_TCustomFlashObject.TFlashAttribute.Create'],
        'evap_boolean_at_b8': at(ADV + 'InternalCreate', 0xfdd0f6, 'mov', 'eax, dword ptr [0x7f426c]')
            and at(ADV + 'InternalCreate', 0xfdd103, 'mov', 'dword ptr [edx + 0xb8], eax'),
        'non_evap_boolean_at_bc': at(ADV + 'InternalCreate', 0xfdd11c, 'mov', 'eax, dword ptr [0x7f426c]')
            and at(ADV + 'InternalCreate', 0xfdd129, 'mov', 'dword ptr [edx + 0xbc], eax'),
        'hook_has_no_inherited_call': calls(HOOK) == [],
        'unhook_has_no_inherited_call': calls(UNHOOK) == [],
        'hook_only_targets_two_flags': [o for _, m, o, _ in listings[HOOK][0]
            if m == 'mov' and o.startswith('eax, dword ptr [eax +')] == [
                'eax, dword ptr [eax + 0xb8]', 'eax, dword ptr [eax + 0xbc]'],
        'hook_installs_flag_handler_twice': sum(m == 'mov' and o == 'dword ptr [eax + 0x60], 0xfdd2a0'
            for _, m, o, _ in listings[HOOK][0]) == 2,
        'unhook_only_targets_two_flags': [o for _, m, o, _ in listings[UNHOOK][0]
            if m == 'mov' and o.startswith('eax, dword ptr [eax +')] == [
                'eax, dword ptr [eax + 0xb8]', 'eax, dword ptr [eax + 0xbc]'],
        'programmable_constructs_advanced_ui': at(SOURCES[3], 0xfecfe7, 'mov', 'eax, dword ptr [0xfd8ce0]')
            and at(SOURCES[3], 0xfecff6, 'mov', 'eax, dword ptr [eax + 0x1e4]'),
        'programmable_retains_ui_zone_event_endpoint': at(SOURCES[3], 0xfed039, 'mov',
            'dword ptr [eax + 0xb0], 0xfea7b0'),
        'programmable_sets_flag_event_endpoint': at(SOURCES[3], 0xfed01e, 'mov',
            'dword ptr [eax + 0xc8], 0xfed134'),
        'zone_boolean_value_explicitly_starts_false': at(SOURCES[8], 0x7f4511, 'mov',
            'byte ptr [eax + 0x70], 0'),
        'thermostat_assigns_new_used_zones': at(SOURCES[9], 0xfea5bc, 'mov',
            'eax, dword ptr [eax + 0x1d8]') and at(SOURCES[9], 0xfea5c4, 'call',
            'dword ptr [ecx + 0xa8]'),
    }
    base.require(all(checks.values()), 'Advanced UI source routes: ' + str([n for n, value in checks.items() if not value]))
    methods = []
    for name in SOURCES:
        start = image.by_name[name]
        end = next(a for a in image.starts if a > start)
        methods.append({'name': name, 'start': hex(start), 'end': hex(end), 'sha256': listings[name][2]})
    return {'checks': checks, 'methods': methods, 'advanced_ui_vmt': hex(vmt),
            'base_probe_sha256': BASE_SHA256}


class AdvancedProbe(base.Probe):
    def __init__(self, exe, map_path, sources):
        self.sources = sources
        super().__init__(exe, map_path)
        # Any accidentally inherited UI zone handler is outside this fixture's
        # declared original execution set, rather than a harmless empty stub.
        self.ranges = [(a, b, n) for a, b, n in self.ranges if n != UI_HANDLER]
        self.by_entry.pop(self.addr(UI_HANDLER))
        for name in (HOOK, UNHOOK):
            start = self.addr(name)
            end = next(a for a in self.image.starts if a > start)
            self.ranges.append((start, end, name))
            self.by_entry[start] = name

    def custom(self, name, cls):
        return super().custom(name, ADV_CLASS if name == 'ui' else cls)

    def seed(self):
        super().seed()
        ui = self.services['ui']
        self.ui_zone_attribute = self.word(ui + 0x98)
        # Replace the older fixture's explicitly injected base-UI callback
        # before any original instructions execute. The Advanced override does
        # not install it in the recovered constructor path.
        self.put(self.ui_zone_attribute + 0x60, 0)
        self.put(self.ui_zone_attribute + 0x64, 0)
        self.put(ui + 0xc8, self.addr('CIS_TThermostat.TProgrammableThermostat.HandleEvapProgramEnableChange'))
        self.put(ui + 0xcc, self.thermostat)
        self.flags = {}
        for name, field in (('EvapProgramEnabled', 0xb8), ('NonEvapProgramEnabled', 0xbc)):
            attribute = self.attribute(name, ui, 'CIS_TBooleanAttribute..TBooleanAttribute')
            self.put(ui + field, attribute)
            self.byte(attribute + 0x70, 0)
            self.flags[name] = attribute
        self.byte(self.boolean_attributes['UsedZones', 0] + 0x70, 0)

    def hook_state(self):
        def event(attribute):
            return {'code': hex(self.word(attribute + 0x60)), 'owner_is_ui': self.word(attribute + 0x64) == self.services['ui'],
                    'owner_is_nil': self.word(attribute + 0x64) == 0}
        return {'UIAllocatedZones': event(self.ui_zone_attribute),
                **{name: event(attribute) for name, attribute in self.flags.items()}}

    def run(self):
        before = self.masks()
        expected_before = {name: 1 for name in self.zones}
        expected_before.update(UsedZones=0, InstalledZones=3, ControlledZones=3)
        base.require(before == expected_before, 'Exact source-prepared input vector')
        self.phase = 'actual_advanced_ui_hook'
        self.call(HOOK, self.services['ui'])
        hooked = self.hook_state()
        base.require(hooked['UIAllocatedZones']['code'] == '0x0' and hooked['UIAllocatedZones']['owner_is_nil'],
                     'Original advanced hook leaves inherited zone callback nil')
        base.require(all(hooked[name]['code'] == '0xfdd2a0' and hooked[name]['owner_is_ui'] for name in self.flags),
                     'Original advanced hook installs both flag callbacks')
        self.phase = 'original_boolean_reads'
        for attribute in [*self.boolean_attributes.values(), *self.flags.values()]:
            self.call('CIS_TBooleanAttribute.TBooleanAttribute.AsBoolean', attribute)
        self.phase = 'include_zone_1'
        self.call('CIS_TcdThermostatTemplates.IncludeZone', 1, args=(self.parent_frame,))
        after = self.masks()
        expected = dict(before)
        expected.update(UsedZones=2, UIAllocatedZones=3, InternalPlantZones=3, MeasuredZones=3, ScheduleControlledZones=3)
        base.require(after == expected, 'Exact corrected output vector')
        base.require(self.hook_state() == hooked, 'Action preserves actual advanced hook state')
        callbacks = [e for e in self.trace if e['method'].endswith('HandleZoneAfterChange')]
        base.require([e['object'] for e in callbacks] == ['plant', 'measurement', 'schedule'], 'Three actual callbacks only')
        base.require(self.entries[UI_HANDLER] == 0, 'No inherited UI zone callback executed')
        base.require(self.entries['CIS_TcdThermostatTemplates.TcdThermostatTemplates.UpdateQuickOptions'] == 3,
                     'Three original guarded quick refreshes')
        setters = [e['object'] for e in self.trace if e['method'].endswith('SetAsBoolean')]
        base.require(setters == [n + '.bit1' for n in ('UsedZones', 'UIAllocatedZones', 'InternalPlantZones',
                     'MeasuredZones', 'ScheduleControlledZones', 'InstalledZones', 'ControlledZones')], 'Seven ordered setters')
        self.phase = 'actual_advanced_ui_unhook'
        self.call(UNHOOK, self.services['ui'])
        unhooked = self.hook_state()
        base.require(all(event['code'] == '0x0' and event['owner_is_nil'] for event in unhooked.values()),
                     'Original advanced unhook clears both flags and leaves zone callback nil')
        base.require(all(self.u.mem_read(a + 0x70, 1) == b'\0' for a in self.flags.values()), 'Both flags preserved false')
        base.require(all(self.word(p + 0x10) == 0 for p in self.managed), 'Managed counters balanced')
        base.require(all(self.word(p + 0x10) == 0 for n, (p, _) in self.objects.items() if n.endswith('.manager')),
                     'Attribute-manager counters balanced')
        base.require(all(self.word(self.objects[n][0] + 0x70) == 0 for n in
                     ('master_slave', 'heating_type', 'cooling_type', 'venting_type')), 'Master and types unchanged')
        base.require(self.u.mem_read(self.templates + 0x28, 1) == b'\1', 'Templates outer guard retained')
        base.require(self.u.mem_read(self.thermostat + 0x1c0, 1) == b'\0' and
                     self.u.mem_read(self.services['plant'] + 0x15c, 1) == b'\0', 'Model guards restored')
        base.require(bytes(self.u.mem_read(self.base, self.image_size)) == self.frozen_image, 'Immutable image after runtime slot seed')
        base.require({base.sha(p.read_bytes()) for p in self.library_paths} == base.LIBRARIES, 'Engine libraries unchanged')
        methods = [{'name': n, 'start': hex(a), 'end': hex(b), 'entries': self.entries[n],
                    'sha256': base.sha(self.image.pe.get_data(a - self.base, b - a))} for a, b, n in self.ranges]
        return {'schema': 'cbus-thermostat-quick-zone-advanced-ui-core-original-v1', 'passed': True,
                'scope': __doc__, 'probe_sha256': base.sha(Path(__file__).read_bytes()), 'source_routes': self.sources,
                'source_exe_sha256': base.EXE_SHA256, 'source_map_sha256': base.MAP_SHA256,
                'corrections_from_prior_synthetic_fixture': ['Actual TAdvancedUIService VMT and virtual hook overrides.',
                    'UIAllocatedZones after-change callback nil; only three dedicated model zone events.',
                    'UsedZones initial0 instead of retained1; isolated include produces2 rather than3.'],
                'input': {'action': 'IncludeZone(1)', 'before_masks': before, 'plant_types': [0, 0, 0], 'master_slave': 0,
                          'EvapProgramEnabled': False, 'NonEvapProgramEnabled': False, 'templates_action_guard': True},
                'after_masks': after, 'expected_masks': expected, 'hooked': hooked, 'unhooked': unhooked,
                'callback_trace': self.trace, 'methods': methods, 'instruction_count': self.total,
                'original_instruction_events': self.total - sum(self.adapter_calls.values()),
                'unique_original_instruction_count': len(self.instructions), 'instruction_budget': base.BUDGET,
                'abi_adapter_calls': dict(self.adapter_calls), 'abi_adapter_semantics': {
                    'VariantClear0x627b14': 'Owned stack VT_EMPTY/VT_BOOL only; clear type word, preserve inactive payload, return S_OK; original OleAut32 excluded.',
                    'Enter/LeaveCriticalSection0x60e35c/0x60e6c8': 'Owned reference-list locks only; balanced single-thread recursive depth; stdcall one pointer.'},
                'runtime_data_initialization': {'slot': '0x13a1010', 'target': '0x629f1c',
                    'source': 'Original Variants.Variants0x13691f0..0x13691fb via [0x13c2f58].'},
                'actual_instruction_engine_sha256': sorted(base.LIBRARIES),
                'writes': dict(self.writes), 'adapter_stack_type_word_writes': self.adapter_calls['variant_clear_empty_or_bool'],
                'writes_outside_owned_state': 0, 'original_image_unchanged_after_runtime_data_seed': True,
                'original_instruction_bytes_verified_at_every_execution': True,
                'full_original_form_executed': False, 'constructors_executed': False,
                'pp_load_save_reload_executed': False, 'public_action_accepted': False,
                'omissions': ['Full constructors and initialized form provenance', 'GUI publishers/expression consumers',
                    'workspace', 'parent EnableDisableZone callback', 'unrelated model attributes', 'project/group metadata',
                    'original AfterLoad/BeforeSave/save/reload', 'outer click/confirmation', 'native Windows message queue']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--map', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--static-only', action='store_true')
    parser.add_argument('--confined-child', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.static_only:
        print(json.dumps(source_routes(args.exe, args.map), indent=2, sort_keys=True))
        return
    if not args.confined_child:
        base.require(sys.platform == 'darwin' and Path('/usr/bin/sandbox-exec').is_file(), 'macOS network confinement required')
        command = ['/usr/bin/sandbox-exec', '-p', '(version 1)(allow default)(deny network*)', sys.executable,
                   '-B', str(Path(__file__).resolve()), '--confined-child', '--exe', str(args.exe.resolve(strict=True)),
                   '--map', str(args.map.resolve(strict=True)), '--output', str(args.output.resolve())]
        result = subprocess.run(command, capture_output=True, text=True, timeout=90, check=False)
        base.require(result.returncode == 0 and not result.stderr, 'Confined child failed: ' + result.stderr[-5000:])
        report = json.loads(result.stdout)
        report.update(network_denied_by_macos_sandbox=True, child_exit_code=0)
        with args.output.open('x') as stream:
            json.dump(report, stream, indent=2, sort_keys=True)
            stream.write('\n')
        print(json.dumps({'passed': True, 'original_instruction_events': report['original_instruction_events']}))
        return
    sys.addaudithook(base.deny_external)
    sources = source_routes(args.exe, args.map)
    probe = AdvancedProbe(args.exe, args.map, sources)
    report = probe.run()
    base.require(args.exe.read_bytes() == probe.exe_raw and args.map.read_bytes() == probe.map_raw, 'Source inputs unchanged')
    base.require(base.sha(Path(base.__file__).read_bytes()) == BASE_SHA256, 'Base checker unchanged')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
