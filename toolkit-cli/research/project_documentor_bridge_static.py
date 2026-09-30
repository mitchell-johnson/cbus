"""Pin the original bridge report and PP adapter without running vendor code."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from project_documentor_static import _Toolkit, EXE_SHA256, MAP_SHA256, UNIT_FACTORY

PREFIX = 'CIS_TCBusBridgeCGateAgent.TCBusBridgeCGateAgent.'
BASE_AGENT = 'CIS_TCBusUnitCGateAgent.TCBusUnitCGateAgent.'
BASE_UNIT = 'CIS_TCommonCBus.TCBUSUnit.'
METHODS = (
    'CIS_TBridgeDocumentor.TBridgeDocumentor.DocumentHTML',
    'CIS_TBridge.TBridge.LoadApplicationLists',
    'CIS_TBridge.TBridge.HasApplication1',
    PREFIX + 'InternalCreate', PREFIX + 'AfterLoadProgrammingInformation',
    PREFIX + 'GetApplication1', PREFIX + 'GetApplication2',
    BASE_AGENT + 'GetApplicationObject', BASE_AGENT + 'GetApplication2Object',
    BASE_AGENT + 'AfterLoadProgrammingInformation',
    BASE_UNIT + 'GetApplicationObject', BASE_UNIT + 'GetApplication2Object',
    'CIS_TStandardCBusApplications.TStandardCBusApplications.GetApplicationName',
    'CIS_TDocumentorCommon.DisplayHTMLApplication',
    'CIS_TProjectDocumentor.TUnitTypeDocumentor.DocumentHTML',
)


def inspect(exe: Path, map_file: Path):
    original, symbols = exe.read_bytes(), map_file.read_bytes()
    if hashlib.sha256(original).hexdigest() != EXE_SHA256 or hashlib.sha256(symbols).hexdigest() != MAP_SHA256:
        raise ValueError('Original Toolkit EXE/MAP hash mismatch')
    image = _Toolkit(original, symbols)
    methods = {name: image.method(name) for name in METHODS}
    instructions = lambda name: [(m, op) for _, m, op in methods[name]['instructions']]
    after = instructions(PREFIX + 'AfterLoadProgrammingInformation')
    bindings = methods[PREFIX + 'InternalCreate']['literals']

    def exact(name, address, mnemonic, operands):
        return (address, mnemonic, operands) in methods[name]['instructions']

    secondary = BASE_AGENT + 'GetApplication2Object'
    base_after = BASE_AGENT + 'AfterLoadProgrammingInformation'
    app_name = 'CIS_TStandardCBusApplications.TStandardCBusApplications.GetApplicationName'
    common_display = 'CIS_TDocumentorCommon.DisplayHTMLApplication'
    base_documentor = 'CIS_TProjectDocumentor.TUnitTypeDocumentor.DocumentHTML'

    registrations = [row for row in image.registrations(UNIT_FACTORY)[0]
                     if row[0] in ('BRIDGE1N', 'BRIDGE1F', 'BRIDGE2N', 'BRIDGE2F',
                                   'GATEWLS', 'GATEWLSN', 'GATEWLSF')]
    checks = {
        'forwarding_pp_names': bindings == ['ApplicationConnectEnabled', 'BridgeCount', 'BridgeAddress',
                                            'Burden', 'ClockGenEnable'],
        'has_application1_true': ('mov', 'byte ptr [ebp - 5], 1') in instructions(
            'CIS_TBridge.TBridge.HasApplication1'),
        'all_seven_bridge_types_have_application1': len(registrations) == 7 and all(
            image.slot(row[1], 0xf0) == 'CIS_TBridge.TBridge.HasApplication1' for row in registrations),
        'bridge_count_positive_enables_remote': ('test', 'eax, eax') in after and ('setg', 'al') in after,
        'seven_route_slots': after.count(('cmp', 'dword ptr [ebp - 8], 7')) == 2,
        'route_default_unused': ('mov', 'ecx, 0xff') in after,
        'stop_at_first_unused': ('cmp', 'eax, 0xff') in after and ('je', '0x1256ca5') in after,
        'stop_at_first_unknown_network': ('test', 'eax, eax') in after and after.count(('je', '0x1256ca5')) == 2,
        'destination_initially_unused': ('mov', 'dword ptr [ebp - 0xc], 0xff') in after,
        'destination_is_last_resolved_prefix_entry': ('mov', 'dword ptr [ebp - 0xc], eax') in after,
        'primary_application_first': ('mov', 'eax, dword ptr [eax]') in instructions(PREFIX + 'GetApplication1'),
        'secondary_application_second': ('mov', 'eax, dword ptr [eax + 4]') in instructions(PREFIX + 'GetApplication2'),
        'base_application255_default_name': (
            exact(app_name, 0x85add3, 'cmp', 'dword ptr [ebp - 8], 0xff')
            and methods[app_name]['literal_at'].get(0x85addf) == '<Unused>'),
        'display_application255_raw_name': (
            exact(common_display, 0xca582e, 'cmp', 'eax, 0xff')
            and exact(common_display, 0xca5833, 'je', '0xca588d')
            and exact(common_display, 0xca5893, 'mov', 'eax, dword ptr [eax + 0x9c]')
            and exact(common_display, 0xca589b, 'call', 'dword ptr [ecx + 0x2c]')),
        'secondary_application255_is_not_omitted': (
            exact(secondary, 0xcb8332, 'cmp', 'dword ptr [ebp - 0x10], 0xff')
            and exact(secondary, 0xcb8339, 'jg', '0xcb835b')
            and exact(secondary, 0xcb834e, 'mov', 'cl, 1')
            and exact(secondary, 0xcb8353, 'call', hex(image.by_name[
                'CIS_TCommonCBus.TCBUSApplicationManager.ApplicationByAddress']))),
        'secondary_loaded_unconditionally': (
            exact(base_after, 0xcbe6bb, 'call', 'dword ptr [edx + 0xe8]')
            and exact(base_after, 0xcbe6cb, 'call', hex(image.by_name[BASE_UNIT + 'SetApplication2Object']))),
        'base_documentor_displays_nonnull_secondary': (
            exact(base_documentor, 0xf060da, 'call', 'dword ptr [edx + 0xb4]')
            and exact(base_documentor, 0xf060e0, 'test', 'eax, eax')
            and exact(base_documentor, 0xf060e2, 'je', '0xf0611c')
            and exact(base_documentor, 0xf060f7, 'call', hex(image.by_name[common_display]))),
        'bridge_base_applications_use_network_objects': all(
            image.slot(row[1], slot) == BASE_UNIT + method
            for row in registrations for slot, method in ((0xb0, 'GetApplicationObject'),
                                                         (0xb4, 'GetApplication2Object'))),
        'bridge_agent_inherits_base_application_loaders': all(
            image.slot('CIS_TCBusBridgeCGateAgent..TCBusBridgeCGateAgent', slot) == BASE_AGENT + method
            for slot, method in ((0xe4, 'GetApplicationObject'), (0xe8, 'GetApplication2Object'))),
        'private_application_255_names': [image.resource(image.dword(p)) for p in (0x13c218c, 0x13c1d38)]
            == ['All Applications', '<Unused>'],
    }
    if not all(checks.values()):
        raise ValueError('Bridge source checks failed: ' + ', '.join(k for k, v in checks.items() if not v))
    return {
        'format': 'cbus-project-documentor-bridge-static-v1',
        'original_exe_sha256': EXE_SHA256, 'original_map_sha256': MAP_SHA256,
        'original_executed': False,
        'checks': checks,
        'method_spans': {name: {'start': hex(method['start']), 'sha256': method['sha256'],
                                'bytes': method['end'] - method['start']} for name, method in methods.items()},
        'bridge_registrations': registrations,
        'limit': 'Static PP-to-report branch recovery; no original generated-page or visual comparison.',
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--map', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(inspect(args.exe, args.map), sort_keys=True, indent=2))


if __name__ == '__main__':
    main()
