"""Pin thermostat allocator manager order without assuming database XML order.

No vendor executable is run. This is evidence for a possible future opt-in
address-sorted, initially empty application slice, not a production admission.
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
REF = FLASH + 'TFlashObjectReferenceCollection.'
MANAGER = 'CIS_TCBusObject.TCGateObjectManager.'
GROUP = 'CIS_TCommonCBus.TCBusGroupManager.'
METHODS = (
    'CIS_TCommonCBus.TCBUSApplication.InternalCreate',
    'CIS_GlobalSoftwareParameters.SortModeGroupsUseAddress',
    MANAGER + 'SetSortStyleCustomAddressAsc', MANAGER + 'SetSortStyleCustomTagNameAsc',
    MANAGER + 'CustomSortAddressAsc', MANAGER + 'CustomSortTagNameAsc',
    REF + 'SetSortStyle', REF + 'Compare', REF + 'AddObject',
    FLASH + 'TFlashObjectCollection.Append', REF + 'Append',
    REF + 'GetSortedInsertLocation', FLASH + 'QuickInsert',
    REF + 'AddReference', REF + 'GetItem', REF + 'ResolveAllReferences',
    MANAGER + 'LoadAndSort', MANAGER + 'SetAfterChangeTimerEnabled',
    MANAGER + 'HandleAfterChangeTimerTrigger', REF + 'OnReferencedObjectChange',
    'CIS_TCommonCBus.TCBusInstallation.SortAll',
    'CIS_TThermostat.TPlantControlService.CreateAndRenameGroup',
    'CIS_TThermostat.TPlantControlService.GetGroup', 'CIS_TThermostat.GetNewGroup',
)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _compare_address(left, right):
    """Recovered custom comparator, including the unused-address override."""
    if left == right:
        return 0
    if left == 255:
        return -1
    if right == 255:
        return 1
    return left - right


def _quick_insert(items, value, low=0, high=None):
    """Independent projection of original binary QuickInsert branch choices."""
    if not items:
        return 0
    if high is None:
        high = len(items) - 1
    middle = (low + high) // 2
    comparison = _compare_address(value, items[middle])
    if comparison == 0:
        return middle
    if comparison > 0:
        return high + 1 if middle == high else _quick_insert(items, value, middle + 1, high)
    return low if middle == low else _quick_insert(items, value, low, middle - 1)


def _allocate(ordered_addresses, prefixed_addresses):
    occupied = set(ordered_addresses)
    for address in reversed(ordered_addresses):
        if address not in prefixed_addresses:
            continue
        for candidate in range(address + 1, 255):
            if candidate not in occupied:
                return candidate
    return next((candidate for candidate in range(255) if candidate not in occupied), None)


def inspect(exe: Path, map_path: Path) -> dict:
    exe_raw, map_raw = exe.read_bytes(), map_path.read_bytes()
    if (_sha(exe_raw), _sha(map_raw)) != (EXE_SHA256, MAP_SHA256):
        raise ValueError('Original Toolkit EXE/MAP hash mismatch')
    image = _Image(exe_raw, map_raw)
    walker = _Walker(image)
    methods = {name: walker.listing(name) for name in METHODS}
    rows = {name: {a: (m, op) for a, m, op, _note in data[0]} for name, data in methods.items()}
    checks = {}

    def at(name, address, mnemonic, operands):
        checks[hex(address)] = rows[name].get(address) == (mnemonic, operands)

    app = 'CIS_TCommonCBus.TCBUSApplication.InternalCreate'
    at(app, 0xf257ad, 'call', '0x85b428')
    at(app, 0xf257b4, 'je', '0xf257c7')
    at(app, 0xf257bf, 'call', '0xf48850')
    at(app, 0xf257d0, 'call', '0xf48874')
    at('CIS_GlobalSoftwareParameters.SortModeGroupsUseAddress', 0x85b42c,
       'mov', 'al, byte ptr [0x144df26]')
    at(MANAGER + 'SetSortStyleCustomAddressAsc', 0xf48860,
       'mov', 'dword ptr [edx + 0x60], 0xf4825c')
    at(MANAGER + 'SetSortStyleCustomAddressAsc', 0xf48867, 'mov', 'dl, 3')
    at(MANAGER + 'SetSortStyleCustomAddressAsc', 0xf4886c, 'call', '0x7e9978')
    at(MANAGER + 'SetSortStyleCustomTagNameAsc', 0xf48884,
       'mov', 'dword ptr [edx + 0x60], 0xf48488')
    at(MANAGER + 'SetSortStyleCustomTagNameAsc', 0xf4888b, 'mov', 'dl, 3')
    at(REF + 'SetSortStyle', 0x7e998a, 'mov', 'byte ptr [edx + 0x59], al')
    at(REF + 'SetSortStyle', 0x7e99a5, 'call', '0x7e99b0')
    at(REF + 'Compare', 0x7e9910, 'cmp', 'byte ptr [eax + 0x59], 3')
    at(REF + 'Compare', 0x7e9930, 'call', 'dword ptr [ebx + 0x60]')
    for address, mnemonic, operands in (
        (0xf482a7, 'call', '0xf47a10'), (0xf482b1, 'call', '0xf47a10'),
        (0xf482b6, 'sub', 'ebx, eax'), (0xf48307, 'cmp', 'eax, 0xff'),
        (0xf48311, 'mov', 'dword ptr [eax], 0xffffffff'),
        (0xf48355, 'cmp', 'eax, 0xff'), (0xf4835f, 'mov', 'dword ptr [eax], 1')):
        at(MANAGER + 'CustomSortAddressAsc', address, mnemonic, operands)
    at(MANAGER + 'CustomSortTagNameAsc', 0xf48510, 'call', '0x618cb0')
    at(REF + 'AddObject', 0x7e83f0, 'call', 'dword ptr [ecx + 0x68]')
    at(FLASH + 'TFlashObjectCollection.Append', 0x7e9ff2, 'call', '0x7e84ac')
    for address, mnemonic, operands in (
        (0x7e859e, 'cmp', 'byte ptr [eax + 0x59], 0'),
        (0x7e85aa, 'call', '0x7e9b30'), (0x7e85be, 'call', '0x6439e4'),
        (0x7e85ce, 'call', '0x643784')):
        at(REF + 'Append', address, mnemonic, operands)
    at(REF + 'GetSortedInsertLocation', 0x7e9b59, 'call', '0x7e9a84')
    for address, mnemonic, operands in (
        (0x7e9a99, 'shr', 'eax, 1'), (0x7e9abb, 'call', '0x7e98f8'),
        (0x7e9ad5, 'jle', '0x7e9b01'), (0x7e9af6, 'call', '0x7e9a84'),
        (0x7e9b1f, 'call', '0x7e9a84')):
        at(FLASH + 'QuickInsert', address, mnemonic, operands)
    at(REF + 'AddReference', 0x7e8483, 'call', '0x643784')
    at(REF + 'GetItem', 0x7e8f83, 'call', '0x7e9240')
    at(REF + 'GetItem', 0x7e8f91, 'call', '0x64393c')
    at(MANAGER + 'LoadAndSort', 0xf487d4, 'call', '0x7e99b0')
    at(MANAGER + 'SetAfterChangeTimerEnabled', 0xf4880f, 'mov', 'edx, 1')
    at(MANAGER + 'SetAfterChangeTimerEnabled', 0xf4881d, 'call', '0x697290')
    at(MANAGER + 'HandleAfterChangeTimerTrigger', 0xf4875b, 'call', '0x7e99b0')
    at(REF + 'OnReferencedObjectChange', 0x7e9b88, 'call', '0x7e99b0')
    # Template group creators assign Address and TagName before inserting the
    # object into the manager. Therefore the custom comparator sees the final
    # address during each newly generated prefix group's binary insertion.
    creator = 'CIS_TThermostat.TPlantControlService.CreateAndRenameGroup'
    at(creator, 0xfe2935, 'mov', 'eax, dword ptr [eax + 0x80]')
    at(creator, 0xfe293d, 'call', 'dword ptr [ecx + 0x7c]')
    at(creator, 0xfe2976, 'mov', 'eax, dword ptr [eax + 0x9c]')
    at(creator, 0xfe297e, 'call', 'dword ptr [ecx + 0x7c]')
    at(creator, 0xfe299f, 'call', 'dword ptr [ecx + 0x64]')
    creator = 'CIS_TThermostat.TPlantControlService.GetGroup'
    at(creator, 0xfe3382, 'mov', 'eax, dword ptr [eax + 0x80]')
    at(creator, 0xfe338a, 'call', 'dword ptr [ecx + 0x7c]')
    at(creator, 0xfe33ac, 'mov', 'eax, dword ptr [eax + 0x9c]')
    at(creator, 0xfe33b4, 'call', 'dword ptr [ecx + 0x7c]')
    at(creator, 0xfe33d3, 'call', 'dword ptr [ecx + 0x64]')
    group_vmt = walker.dword(image.by_name['CIS_TCommonCBus..TCBusGroupManager'])
    vmt = {hex(offset): walker.name(walker.dword(group_vmt + offset))
           for offset in (0x58, 0x5c, 0x64, 0x68)}
    checks['group_manager_vmt_insert_chain'] = vmt == {
        '0x58': REF + 'GetCount', '0x5c': REF + 'GetItem', '0x64': REF + 'AddObject',
        '0x68': FLASH + 'TFlashObjectCollection.Append'}
    # These five creations are the independent installation-9 phase sequence
    # from the earlier post-load receipt: unused, Y, fan, W, then Y2.
    insertions, items = [], []
    for address in (255, 5, 3, 6, 2):
        position = _quick_insert(items, address)
        items.insert(position, address)
        insertions.append({'created_address': address, 'insert_position': position,
                           'resulting_addresses': list(items)})
    checks['fresh_template9_address_sort'] = items == [255, 2, 3, 5, 6]
    allocated = _allocate(items, {2, 3, 5, 6})
    checks['fresh_template9_allocates7'] = allocated == 7
    # A concrete counterexample demonstrates why merely assuming insertion
    # will repair an arbitrary, incompletely loaded initial manager is wrong.
    unsorted = [5, 1, 7, 3]
    for address in (6, 4, 2):
        unsorted.insert(_quick_insert(unsorted, address), address)
    checks['unsorted_initial_list_is_not_repaired_by_insert'] = unsorted == [4, 5, 1, 2, 6, 7, 3]
    failures = sorted(name for name, ok in checks.items() if not ok)
    if failures:
        raise ValueError('Original group-order contract differs: ' + ', '.join(failures))
    if (_sha(exe.read_bytes()), _sha(map_path.read_bytes())) != (EXE_SHA256, MAP_SHA256):
        raise ValueError('Original files changed during inspection')
    return {
        'format': 'cbus-toolkit-thermostat-group-order-static-v1',
        'original_exe_sha256': EXE_SHA256, 'original_map_sha256': MAP_SHA256,
        'original_executed': False, 'production_allocator_enabled': False,
        'supporting_receipts': ['thermostat-post-load-static.json',
                                'thermostat-group-allocation-static.json'],
        'method_spans': {name: {'start': hex(image.by_name[name]),
                                'end': hex(next(a for a in image.starts if a > image.by_name[name])),
                                'sha256': data[2]} for name, data in methods.items()},
        'checks': {name: True for name in sorted(checks)}, 'group_manager_vmt': vmt,
        'source_rules': {
            'initialization': 'Application InternalCreate reads the process group sort preference; '
                              'it installs custom address-ascending or tag-name-ascending sortstyle3.',
            'address_compare': 'Numeric address difference for ordinary groups; address255 sorts first.',
            'tag_compare': 'SysUtils.AnsiCompareText, with address255 first; locale-sensitive comparison '
                           'is not projected by this receipt.',
            'insertion': 'AddObject dispatches through GroupManager VMT to collection Append, which '
                         'uses QuickInsert plus TList.Insert while sorted. It does not append at the end.',
            'scope': 'An initially empty manager is trivially sorted. Under an explicitly selected '
                     'address sort, sorted insertion preserves exact numeric order for newly created '
                     'unique-address groups. This proves the fresh application slice without using '
                     'database XML child order.'},
        'proposed_optional_slice': {
            'required_context': ['explicit address-ascending original preference',
                                 'initial output application group inventory is empty'],
            'unchanged_refusals': ['omitted or other sort context when GetNewGroup is needed',
                                  'initially nonempty application when GetNewGroup is needed',
                                  'preexisting thermostat-prefix groups'],
            'template9_insertion_trace': insertions,
            'template9_W2_address': allocated,
            'template9_final_relay_addresses': [5, 2, 3, 6, 7],
            'implementation_status': 'Evidence only; no production path or admission added.'},
        'general_existing_manager_blockers': [
            'TFlashObjectReferenceCollection.AddReference (0x7e83f8) directly TList.Adds at '
            '0x7e8483, without the sorted insertion path.',
            'TCGateObjectManager.LoadAndSort (0xf48798) explicitly resolves objects and then sorts; '
            'the full cached/native application-load path to that completion is not established here.',
            'Address/tag changes can schedule a 1ms sort through SetAfterChangeTimerEnabled '
            '(0xf487e0) and HandleAfterChangeTimerTrigger (0xf48708); pending GUI event state is absent '
            'from a PP snapshot and DBGETXML.',
            'OnReferencedObjectChange (0x7e9b70) can synchronously sort, but this does not prove '
            'every initial reference has completed its loading/change notifications.',
            'Known sort preference alone is insufficient for arbitrary existing manager load state; '
            'new sorted insertions do not generally repair an unsorted initial collection.'],
        'unsorted_initial_counterexample': {'initial': [5, 1, 7, 3], 'inserted': [6, 4, 2],
                                           'result': unsorted, 'inserted_subsequence': [4, 2, 6]},
        'limit': 'Static source evidence and independent branch projections only. No original GUI, '
                 'native application-load ordering, or physical thermostat execution occurred.',
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--map', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(inspect(args.exe, args.map), indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
