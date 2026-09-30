"""Pin why resolving a cached thermostat group inventory does not sort it.

This reads the pinned original EXE/MAP without executing vendor code. The
counterexamples are source-derived control-flow projections with successful,
side-effect-free reference resolution, not an original GUI lifecycle receipt.
No database XML order is promoted to an original manager-order guarantee.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from topology_generator_static import EXE_SHA256, MAP_SHA256, _Image  # noqa: E402
from thermostat_post_load_static import _Walker  # noqa: E402

FLASH = 'CIS_TCustomFlashObject.'
REF = FLASH + 'TFlashObjectReference.'
COLLECTION = FLASH + 'TFlashObjectReferenceCollection.'
MANAGER = 'CIS_TCBusObject.TCGateObjectManager.'
UNIT = 'CIS_TCommonCBus.TCBUSUnit.'
AGENT = 'CIS_TCBusThermostatCGateAgent.TCBusThermostatCGateAgent.'
PLANT = 'CIS_TThermostat.TPlantControlService.'
METHODS = (
    COLLECTION + 'AddReference', COLLECTION + 'GetCount', COLLECTION + 'GetItem',
    COLLECTION + 'ResolveAllReferences', COLLECTION + 'ResolveChange',
    COLLECTION + 'OnReferencedObjectChange', COLLECTION + 'DoFullSort',
    FLASH + 'TFlashObjectCollection.AddSessionID',
    REF + 'SetAsString', REF + 'SetFlashObjectSource', REF + 'ResolveReference',
    REF + 'SetFlashObject', REF + 'GetFlashObject',
    'CIS_TManagedFlashObject.TManagedFlashObject.ResolveChange',
    FLASH + 'TFlashEntityManager.ResolveChange',
    FLASH + 'TFlashObject.FinishedLoading', FLASH + 'TFlashObject.AfterLoad',
    'CIS_XMLLoader.TFlashCachedObject.LoadIntoFlashObject',
    'CIS_XMLLoader.SetCompositeCollectionItem',
    'CIS_XMLLoader.SetAggregateCollectionItem',
    'CIS_TCommonCBus.TCBusGroupManager.GetItem',
    MANAGER + 'LoadAndSort',
    'CIS_TFlashCxTreeViewDataProvider.AddNetworkChildNodes',
    UNIT + 'GetApplicationObject', UNIT + 'SetApplicationObject',
    AGENT + 'InternalCreate', AGENT + 'AfterLoadProgrammingInformation',
    'CIS_TThermostat.TCBusParameters.SetApplicationNumber',
    PLANT + 'GetUnusedGroup', PLANT + 'GetGroup', 'CIS_TThermostat.GetNewGroup',
)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _resolve_fixture(*, dirty: bool, get_count_first: bool) -> dict:
    """Project the pinned collection/reference branches, not object loading."""
    addresses = [5, 1, 7, 3]
    states = [2] * len(addresses)
    if get_count_first:
        dirty = False  # GetCount -> ResolveChange, not ResolveAllReferences.
    resolved_indices = list(reversed(range(len(states)))) if dirty else []
    for index in resolved_indices:
        states[index] = 3  # SetFlashObject skips the change callback for state 2.
    if states[0] in (1, 2):
        resolved_indices.append(0)
        states[0] = 3  # GetItem -> reference.GetFlashObject resolves this item.
    return {
        'get_count_first': get_count_first,
        'initial_addresses': addresses,
        'initial_reference_states': [2] * len(addresses),
        'resolved_indices': resolved_indices,
        'final_reference_states': states,
        'final_addresses': list(addresses),
        'sorted_by_address': addresses == sorted(addresses),
        'referenced_object_change_callbacks': 0,
    }


def inspect(exe: Path, map_path: Path) -> dict:
    exe_raw, map_raw = exe.read_bytes(), map_path.read_bytes()
    if (_sha(exe_raw), _sha(map_raw)) != (EXE_SHA256, MAP_SHA256):
        raise ValueError('Original Toolkit EXE/MAP hash mismatch')
    image = _Image(exe_raw, map_raw)
    walker = _Walker(image)
    methods = {name: walker.listing(name) for name in METHODS}
    rows = {name: {a: (m, op) for a, m, op, _note in data[0]}
            for name, data in methods.items()}
    checks = {}

    def at(name, address, mnemonic, operands):
        checks[hex(address)] = rows[name].get(address) == (mnemonic, operands)

    def markers(name, entries):
        for address, mnemonic, operands in entries:
            at(name, address, mnemonic, operands)

    markers(REF + 'ResolveReference', (
        (0x7ed43c, 'cmp', 'byte ptr [eax + 0x40], 1'),
        (0x7ed468, 'call', '0x7e4124'),
        (0x7ed472, 'call', '0x7ed6d4'),
        (0x7ed497, 'cmp', 'byte ptr [eax + 0x40], 2'),
        (0x7ed4e8, 'call', 'dword ptr [ebx + 0x50]'),
        (0x7ed4fe, 'call', '0x7ed6d4')))
    markers(REF + 'SetFlashObject', (
        (0x7ed7fb, 'cmp', 'byte ptr [eax + 0x40], 1'),
        (0x7ed7ff, 'je', '0x7ed827'),
        (0x7ed804, 'cmp', 'byte ptr [eax + 0x40], 2'),
        (0x7ed808, 'je', '0x7ed827'),
        (0x7ed80d, 'mov', 'byte ptr [eax + 0x40], 3'),
        (0x7ed814, 'cmp', 'word ptr [eax + 0x2a], 0'),
        (0x7ed824, 'call', 'dword ptr [ebx + 0x28]'),
        (0x7ed82a, 'mov', 'byte ptr [eax + 0x40], 3')))
    markers(COLLECTION + 'ResolveAllReferences', (
        (0x7e924c, 'cmp', 'byte ptr [eax + 0x1d], 0'),
        (0x7e9250, 'je', '0x7e9288'),
        (0x7e9272, 'call', '0x7ed41c'),
        (0x7e9277, 'dec', 'dword ptr [ebp - 8]'),
        (0x7e9285, 'call', 'dword ptr [edx + 0x24]')))
    markers(COLLECTION + 'GetItem', (
        (0x7e8f83, 'call', '0x7e9240'),
        (0x7e8f91, 'call', '0x64393c'),
        (0x7e8f96, 'call', '0x7ed3a0')))
    at(REF + 'GetFlashObject', 0x7ed3ac, 'call', '0x7ed41c')
    at('CIS_TCommonCBus.TCBusGroupManager.GetItem', 0xf28966, 'call', '0x7e8f74')
    markers(COLLECTION + 'GetCount', (
        (0x7e8f5e, 'call', 'dword ptr [edx + 0x24]'),
        (0x7e8f67, 'mov', 'eax, dword ptr [eax + 8]')))
    markers(COLLECTION + 'ResolveChange', (
        (0x7e9296, 'call', '0x76a444'),
        (0x7e92aa, 'call', '0x7ee114')))
    managed = 'CIS_TManagedFlashObject.TManagedFlashObject.ResolveChange'
    at(managed, 0x76a457, 'mov', 'byte ptr [eax + 0x1d], 0')
    checks['managed_resolve_change_has_no_calls'] = not any(
        m == 'call' for m, _op in rows[managed].values())
    checks['collection_resolve_change_only_inherited_and_entity_calls'] = {
        op for m, op in rows[COLLECTION + 'ResolveChange'].values() if m == 'call'
    } == {'0x76a444', '0x7ee114'}
    markers(COLLECTION + 'OnReferencedObjectChange', (
        (0x7e9b7f, 'cmp', 'byte ptr [eax + 0x59], 0'),
        (0x7e9b88, 'call', '0x7e99b0')))
    markers(COLLECTION + 'DoFullSort', (
        (0x7e99ba, 'cmp', 'byte ptr [eax + 0x68], 0'),
        (0x7e99be, 'jne', '0x7e9a06'),
        (0x7e99c3, 'mov', 'byte ptr [eax + 0x68], 1'),
        (0x7e99e5, 'call', '0x7e97c4')))

    add_session = FLASH + 'TFlashObjectCollection.AddSessionID'
    markers(add_session, (
        (0x7e9f89, 'mov', 'dword ptr [eax + 0x28], 0x7e9b70'),
        (0x7e9fb4, 'call', '0x7edd70'),
        (0x7e9fc2, 'call', '0x643784')))
    at(REF + 'SetFlashObjectSource', 0x7ede11, 'mov', 'byte ptr [eax + 0x40], 2')
    checks['set_source_no_change_callback'] = not any(
        m == 'call' and '+ 0x28]' in op
        for m, op in rows[REF + 'SetFlashObjectSource'].values())
    markers(COLLECTION + 'AddReference', (
        (0x7e8458, 'mov', 'dword ptr [eax + 0x28], 0x7e9b70'),
        (0x7e8475, 'call', '0x7ed68c'),
        (0x7e8483, 'call', '0x643784')))
    markers(REF + 'SetAsString', (
        (0x7ed6b2, 'mov', 'byte ptr [eax + 0x40], 1'),
        (0x7ed6c9, 'call', 'dword ptr [ebx + 0x28]')))
    loader = 'CIS_XMLLoader.TFlashCachedObject.LoadIntoFlashObject'
    markers(loader, (
        (0x7e37f6, 'call', '0x7e2fec'),
        (0x7e3846, 'call', '0x7e316c'),
        (0x7e3896, 'call', '0x7efa88')))
    at('CIS_XMLLoader.SetCompositeCollectionItem', 0x7e327c,
       'call', 'dword ptr [ebx + 0xb0]')
    at('CIS_XMLLoader.SetAggregateCollectionItem', 0x7e308c,
       'call', 'dword ptr [ecx + 0x98]')
    at(FLASH + 'TFlashObject.FinishedLoading', 0x7efa94,
       'call', 'dword ptr [edx + 0x74]')
    checks['base_after_load_no_calls'] = not any(
        m == 'call' for m, _op in rows[FLASH + 'TFlashObject.AfterLoad'].values())

    group_vmt = walker.dword(image.by_name['CIS_TCommonCBus..TCBusGroupManager'])
    group_slots = {hex(offset): walker.name(walker.dword(group_vmt + offset))
                   for offset in (0x24, 0x58, 0x5c, 0x98, 0xb0)}
    checks['group_manager_vmt_loading_and_getters'] = group_slots == {
        '0x24': COLLECTION + 'ResolveChange', '0x58': COLLECTION + 'GetCount',
        '0x5c': COLLECTION + 'GetItem', '0x98': COLLECTION + 'AddReference',
        '0xb0': add_session,
    }
    completion_slots = {}
    for class_name in ('TCBusGroup', 'TCBUSApplication'):
        vmt = walker.dword(image.by_name['CIS_TCommonCBus..' + class_name])
        completion_slots[class_name] = {
            hex(offset): walker.name(walker.dword(vmt + offset))
            for offset in (0x24, 0x74)
        }
        checks[class_name + '_base_resolve_and_after_load'] = completion_slots[class_name] == {
            '0x24': managed, '0x74': FLASH + 'TFlashObject.AfterLoad',
        }
    markers(MANAGER + 'LoadAndSort', (
        (0xf487a6, 'call', 'dword ptr [edx + 0x58]'),
        (0xf487c1, 'call', 'dword ptr [ecx + 0x5c]'),
        (0xf487d4, 'call', '0x7e99b0')))
    tree = 'CIS_TFlashCxTreeViewDataProvider.AddNetworkChildNodes'
    for address in (0xf0eb9c, 0xf0ebda, 0xf0ec30):
        at(tree, address, 'call', '0xf48798')

    # Thermostat AfterLoad explicitly replaces the unit's application object
    # using the ApplicationNumber PP attribute, before plant-group getters run.
    # The shared unit getter is not evidence that a generic Application byte is
    # the selected output application at this point in the lifecycle.
    markers(UNIT + 'GetApplicationObject', (
        (0xf2ebcc, 'mov', 'eax, dword ptr [eax + 0xbc]'),
        (0xf2ebd4, 'call', 'dword ptr [edx + 0xa4]')))
    markers(UNIT + 'SetApplicationObject', (
        (0xf30026, 'mov', 'eax, dword ptr [eax + 0xbc]'),
        (0xf3002e, 'call', 'dword ptr [ecx + 0xa8]')))
    markers(AGENT + 'InternalCreate', (
        (0x128b9ef, 'push', '0x128c870'),
        (0x128ba02, 'mov', 'eax, dword ptr [0xf42b48]'),
        (0x128ba07, 'call', '0x7ec504'),
        (0x128ba0f, 'mov', 'dword ptr [edx + 0xf8], eax')))
    name_address = 0x128c870
    name_length = walker.dword(name_address - 4)
    attribute_name = image.pe.get_data(name_address - image.base, name_length * 2).decode('utf-16le')
    checks['agent_f8_attribute_name'] = attribute_name == 'ApplicationNumber'
    markers(AGENT + 'AfterLoadProgrammingInformation', (
        (0x128e4bc, 'mov', 'eax, dword ptr [eax + 0xf8]'),
        (0x128e4c4, 'call', 'dword ptr [edx + 0x94]'),
        (0x128e4d3, 'call', '0xfea768'),
        (0x128e4d9, 'call', '0xfdbb7c'),
        (0x128e4f3, 'mov', 'eax, dword ptr [eax + 0xf8]'),
        (0x128e4fb, 'call', 'dword ptr [edx + 0x94]'),
        (0x128e50a, 'call', '0xf2fff8'),
        (0x128e50f, 'mov', 'eax, dword ptr [eax + 0xb0]'),
        (0x128e515, 'mov', 'cl, 1'),
        (0x128e517, 'pop', 'edx'),
        (0x128e518, 'call', '0xf264fc'),
        (0x128e527, 'call', '0xf30014')))
    markers('CIS_TThermostat.TCBusParameters.SetApplicationNumber', (
        (0xfdbbae, 'mov', 'eax, dword ptr [eax + 0x88]'),
        (0xfdbbb6, 'call', 'dword ptr [ecx + 0x7c]')))
    markers(PLANT + 'GetUnusedGroup', (
        (0xfe6014, 'mov', 'eax, dword ptr [eax + 0x158]'),
        (0xfe601c, 'call', 'dword ptr [edx + 0xb0]'),
        (0xfe6022, 'mov', 'eax, dword ptr [eax + 0xb4]'),
        (0xfe6028, 'mov', 'cl, 1'),
        (0xfe602a, 'mov', 'edx, 0xff'),
        (0xfe602f, 'call', '0xf28b68')))
    for address in (0xfe3318, 0xfe334a, 0xfe33c2):
        at(PLANT + 'GetGroup', address, 'call', 'dword ptr [edx + 0xb0]')
    for address in (0xfe2f97, 0xfe2fc3, 0xfe3032, 0xfe3062,
                    0xfe30e3, 0xfe314c, 0xfe317c, 0xfe31fd):
        at('CIS_TThermostat.GetNewGroup', address, 'call', 'dword ptr [edx + 0xb0]')
    thermostat_application_slots = {}
    for class_name in ('TThermostat', 'TBasicThermostat', 'TProgrammableThermostat'):
        vmt = walker.dword(image.by_name['CIS_TThermostat..' + class_name])
        target = walker.dword(vmt + 0xb0)
        thermostat_application_slots[class_name] = {
            'vmt': hex(vmt), 'slot': '0xb0', 'target': hex(target),
            'method': walker.name(target),
        }
        checks[class_name + '_application_getter'] = target == image.by_name[UNIT + 'GetApplicationObject']

    counterexamples = [_resolve_fixture(dirty=True, get_count_first=value)
                       for value in (False, True)]
    checks['first_getitem_no_sorted_invariant'] = all(
        not example['sorted_by_address'] and
        example['initial_addresses'] == example['final_addresses'] and
        example['referenced_object_change_callbacks'] == 0
        for example in counterexamples)
    checks['getcount_can_skip_eager_resolution'] = (
        counterexamples[0]['final_reference_states'] == [3, 3, 3, 3] and
        counterexamples[1]['final_reference_states'] == [3, 2, 2, 2])
    if not all(checks.values()):
        raise AssertionError([name for name, passed in checks.items() if not passed])
    return {
        'schema': 'cbus-thermostat-group-load-boundary-static-v1',
        'original_exe_sha256': EXE_SHA256,
        'original_map_sha256': MAP_SHA256,
        'original_vendor_code_executed': False,
        'production_allocator_enabled': False,
        'checks': checks,
        'check_count': len(checks),
        'methods': {name: {
            'start': hex(image.by_name[name]),
            'end_exclusive': hex(next(a for a in image.starts if a > image.by_name[name])),
            'sha256': data[2],
        } for name, data in methods.items()},
        'group_manager_vmt': group_slots,
        'group_and_application_completion_vmt': completion_slots,
        'thermostat_output_application_route': {
            'pp_attribute': attribute_name,
            'pp_attribute_agent_offset': '0xf8',
            'unit_application_object_offset': '0xbc',
            'after_load_application_lookup': '0x128e518',
            'after_load_application_lookup_create': True,
            'after_load_unit_application_assignment': '0x128e527',
            'thermostat_vmt_slots': thermostat_application_slots,
            'generic_application_first_byte_is_authoritative_here': False,
            'complete_application_side_effect_lifecycle_proved': False,
            'route_only_limitations': [
                'Earlier AfterLoad AC ZoneGroup creation can affect the same manager when ApplicationNumber is 172.',
                'Remote setback application 203 may overlap the selected output application.',
                'The route proof does not establish an empty manager or replay those overlapping lifecycle side effects.',
            ],
        },
        'accepted_source_facts': [
            'Composite cached loading dispatches AddSessionID, which appends a state-2 reference without sorting.',
            'Successful resolution of state 1 or 2 sets state 3 but skips the referenced-object-change callback.',
            'GetItem resolves references and obtains an item; it contains no unconditional sort.',
            'GetCount calls ResolveChange, which can clear the dirty flag before ResolveAllReferences runs.',
            'OID AddReference calls SetAsString and its change callback before appending the new reference; that pre-append sort does not establish final ordering.',
            'Group/application FinishedLoading dispatches their inherited empty AfterLoad method.',
            'LoadAndSort explicitly iterates items and calls DoFullSort; AddNetworkChildNodes contains a direct group-manager call.',
            'Thermostat AfterLoad reads the ApplicationNumber PP attribute at agent offset 0xf8, calls SetApplicationNumber, then rereads that same PP attribute for ApplicationByAddress(create=true) and SetApplicationObject.',
            'All three thermostat class VMTs use the inherited unit GetApplicationObject at slot 0xb0; its attribute at unit offset 0xbc is the same attribute written by SetApplicationObject.',
            'Plant GetUnusedGroup, GetGroup and GetNewGroup obtain their output application through that slot, so their AfterLoad route is ApplicationNumber, not a generic Application first-byte assumption.',
        ],
        'reference_resolution_counterexamples': counterexamples,
        'counterexample_assumptions': [
            'The resolver successfully returns stable objects for the synthetic addresses.',
            'No external callback changes manager membership or requests a separate sort during reference resolution.',
            'This is a source-derived local control-flow counterexample, not a native GUI project-load execution.',
        ],
        'remaining_requirements': [
            'Prove a completed LoadAndSort or equivalent sort for the target manager before the first allocator call in the actual thermostat lifecycle.',
            'Bind the process sort preference and any relevant pending timer or later address/tag mutations.',
            'Tag-name sorting also requires the original Windows user-locale collation and equal-key behavior.',
        ],
        'arbitrary_preloaded_inventory_admitted': False,
        'complete_original_gui_lifecycle_reproduced': False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--map', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(inspect(args.exe, args.map), indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
