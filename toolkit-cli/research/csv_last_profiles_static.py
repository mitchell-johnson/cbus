"""Read-only source proof for the final Toolkit database CSV profiles.

Reads the digest-pinned original PE/MAP; it never loads or executes vendor
instructions. The exported proof contains method hashes, symbols, callsites
and derived report facts, without vendor code or unit specifications.
"""
from __future__ import annotations

import argparse
import bisect
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from cbus_toolkit.toolkit_database_csv_last_profiles import LAST_CLASSES, last_profile
from research.csv_factory_registry_static import EXE_SHA256, MAP_SHA256, _Image


SUPPORT = (
    'TCBUSUnit.InternalCreate', 'TCBUSUnit.Init', 'TCBusUnitCGateAgent.LoadGroups',
    'TCBusUnitCGateAgent.FormatCgApplication',
    'TSENLLCGateAgent.InternalCreate', 'TSENLLCGateAgent.LoadDBParametersForLoadGroups',
    'TSENTEMPCGateAgent.InternalCreate', 'TSENTEMPCGateAgent.LoadDBParametersForLoadGroups',
    'TSENTEMPProCGateAgent.InternalCreate', 'TSENTEMPProCGateAgent.LoadDBParametersForLoadGroups',
    'TIOPECGateAgent.InternalCreate', 'TIOPECGateAgent.LoadInputBlocks',
    'TIOPECGateAgent.LoadInputBlockApplications', 'TIOPECGateAgent.LoadInputs',
    'TIOPEUnit.GetMaximumInputBlockCount', 'TIOPEUnit.GetMaximumOutputCount',
    'TIOPE2R2.GetMaximumOutputCount', 'TIOPE2C4.GetMaximumOutputCount',
    'TIOPEOutputModule.GetMaxChannels',
    'TCBusWirelessInputUnitCGateAgent.SetKeyAndChannelCounts',
    'TCBusWirelessInputUnitCGateAgent.LoadChannelGroups',
    'TCBusWirelessFanControllerCGateAgent.LoadDBParametersForLoadGroups',
    'TCBusWirelessFanControllerCGateAgent.LoadFanParametersFromMaster',
    'TCBusThermostatCGateAgent.LoadGuardEnableAndCommGroup',
    'TDIMPR12.GetMaxChannels', 'TBytecraftUnit.CreateChannels',
)


def recover(exe, map_file, registry):
    exe_bytes, map_bytes = Path(exe).read_bytes(), Path(map_file).read_bytes()
    sha = lambda value: hashlib.sha256(value).hexdigest()
    if sha(exe_bytes) != EXE_SHA256 or sha(map_bytes) != MAP_SHA256:
        raise ValueError('CSV final recovery requires the pinned Toolkit EXE/MAP')
    image = _Image(exe_bytes, map_bytes)

    def symbol(short):
        names = [name for name in image.by_name if name.endswith('.' + short)]
        if len(names) != 1:
            raise ValueError('Expected one exact source method: ' + short)
        return names[0]

    todo, classes = set(), {}
    for row in registry['registrations']:
        profile = last_profile(row['class'], row['agent'])
        if profile is None:
            continue
        klass, agent = row['class'], row['agent']
        unit_ref, agent_ref = image.address(symbol('.' + klass)), image.address(symbol('.' + agent))
        unit_vmt, agent_vmt = image.pointer(unit_ref), image.pointer(agent_ref)
        selected = {'unit_init': image.name(image.pointer(unit_vmt + 0xe4)),
                    'unit_internal_create': image.name(image.pointer(unit_vmt + 0x0c)),
                    'agent_load': image.name(image.pointer(agent_vmt + 0x94)),
                    'load_groups': image.name(image.pointer(agent_vmt + 0xd4)),
                    'format_application': image.name(image.pointer(agent_vmt + 0x100)),
                    'primary_provider': image.name(image.pointer(agent_vmt + 0xe4)),
                    'secondary_provider': image.name(image.pointer(agent_vmt + 0xe8)),
                    'area_provider': image.name(image.pointer(unit_vmt + 0xec)),
                    'interaction_predicate': image.name(image.pointer(unit_vmt + 0x10c))}
        if any(value is None for value in selected.values()):
            raise ValueError('Final CSV profile has an unknown virtual binding')
        if selected['load_groups'] != symbol(profile['loader']):
            raise ValueError('Final CSV loader binding changed')
        classes[klass] = {'agent': agent, 'profile': profile, 'virtual_bindings': selected}
        todo.update(selected.values())
    todo.update(symbol(short) for short in SUPPORT)
    methods = {}
    while todo:
        name = todo.pop()
        if name in methods:
            continue
        start = image.address(name)
        end = image.starts[bisect.bisect_right(image.starts, start)]
        data = image.raw(start, end - start)
        calls, accesses = [], []
        for ins in image.disassembler.disasm(data, start):
            if ins.mnemonic == 'call' and ins.op_str.startswith('0x'):
                target = image.name(int(ins.op_str, 16))
                if target:
                    calls.append({'callsite': hex(ins.address), 'symbol': target})
                    if target.startswith('CIS_') and (target.endswith(('.InternalCreate', '.Init'))
                            or any(word in target for word in ('CreateChannels', 'CreateDimmer'))):
                        todo.add(target)
            if '[eax + 0xd0]' in ins.op_str or '[edx + 0xd0]' in ins.op_str:
                accesses.append(hex(ins.address))
        methods[name] = {'start': hex(start), 'end': hex(end), 'sha256': sha(data),
                         'direct_calls': calls, 'group_manager_offset_accesses': accesses}
    return {'format': 'cbus-toolkit-csv-last-profiles-source-v1',
            'original_execution': False, 'original_inputs': registry['original_inputs'],
            'registry_sha256': sha(json.dumps(registry, ensure_ascii=False, indent=2).encode() + b'\n'),
            'classes': dict(sorted(classes.items())), 'methods': dict(sorted(methods.items())),
            'findings': {
                'empty_managers': 'Fresh base manager created at Unit+0xd0; reviewed constructor paths and base/gateway loaders do not append report associations.',
                'application_defaults': 'Base defaults56/255; exact bridge, wireless gateway and wireless PCI overrides default255/255.',
                'old_light_level_order': ['LevelGroupAddress', 'OnOffGroupAddress', 'EnableGroupAddress'],
                'old_temperature_order': ['ControlGroupAddress', 'EnableGroupAddress', 'OffsetGroupAddress'],
                'pro_temperature_modes': {'25': ['TemperatureGroup'], '172': ['GroupAddress'],
                                          '228': [], 'other': ['GroupAddress', 'EconomyGroup', 'ControlledGroup']},
                'iope_order': 'Eight primary InputGroupAddress associations followed by one/two/four primary OutputGroupAddress associations; secondary input-block lookups precede primary report reload.',
                'wireless_fan_order': 'OutputGroup only, in installed-channel order, using each OutputGroupSecondary Boolean; initialized input blocks are omitted.',
                'wireless_fan_master_dispatch': 'AgentLoad invokes LoadFanParametersFromMaster only for LoadParamsFromMaster or LoadMasterFanTrigger verbs; the database LoadGroups verb does not enter that separate projection.',
                'late_dimpr12': 'Initialized twelve-channel Bytecraft collection uses inherited TDIMPR12CGateAgent.LoadGroups.',
                'scope': 'Resolved report associations and Area projection; auxiliary object graphs, full original loaders, GUI, VM and physical acceptance remain separate.'}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--map', type=Path, required=True)
    parser.add_argument('--registry', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    registry = json.loads(args.registry.read_text())
    result = recover(args.exe, args.map, registry)
    # Bind the exact file bytes, independently of JSON serialization.
    result['registry_sha256'] = hashlib.sha256(args.registry.read_bytes()).hexdigest()
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
