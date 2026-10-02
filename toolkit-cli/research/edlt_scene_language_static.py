#!/usr/bin/env python3
"""Read exact Language/scene refresh spans; never execute vendor instructions."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from research.edlt_scene_name_static import ManagedImage, require_order
from research.edlt_scene_selector_static import VENDOR_PINS, declaration_span
from research.edlt_scene_inventory_static import recover as recover_inventory

NET = 'CBusLogicModel.CBusNetwork::'
LEVEL = 'CBusLogicModel.CBusObjects.CBusLevel::'
GROUP = 'CBusLogicModel.CBusObjects.CBusGroup::'
SCENE = 'CBusLogicModel.Units.EDLT.EDLTScene::'
UNIT = 'CBusLogicModel.Units.EDLT.EDLTUnit::'
METHODS = (
    NET+'get_DefaultLanguage', NET+'set_DefaultLanguage', NET+'ReadXmlData',
    NET+'RefreshData', LEVEL+'ReadXmlData', LEVEL+'PopulateDynamicAll',
    GROUP+'InitialiseGroup', GROUP+'ReadXmlData', UNIT+'LoadScenes',
    SCENE+'get_ActionSelector', SCENE+'set_ActionSelector', SCENE+'RefreshDynamicLables',
)
SOURCE = {
    'edlt-decompiled/CBusLogicModel/CBusLogicModel/CBusNetwork.cs': (
        (NET+'DefaultLanguage', 'public int DefaultLanguage'),
        (NET+'ReadXmlData', 'public override XmlDocument ReadXmlData('),
        (NET+'RefreshData', 'public void RefreshData(')),
    'edlt-decompiled/CBusLogicModel/CBusLogicModel.CBusObjects/CBusLevel.cs': (
        (LEVEL+'ReadXmlData', 'public override XmlDocument ReadXmlData('),
        (LEVEL+'PopulateDynamicAll', 'public void PopulateDynamicAll(')),
    'edlt-decompiled/CBusLogicModel/CBusLogicModel.Units.EDLT/EDLTScene.cs': (
        (SCENE+'ActionSelector', 'public int ActionSelector'),
        (SCENE+'RefreshDynamicLables', 'public void RefreshDynamicLables(')),
    'edlt-decompiled/CBusLogicModel/CBusLogicModel.Units.EDLT/EDLTUnit.cs': (
        (UNIT+'LoadScenes', 'public void LoadScenes('),),
}


def recover(vendor_root, original_app):
    assembly = vendor_root/'toolkit/app/CBusLogicModel.dll'
    raw = assembly.read_bytes()
    if hashlib.sha256(raw).hexdigest() != VENDOR_PINS['toolkit/app/CBusLogicModel.dll']:
        raise ValueError('Pinned CBusLogicModel assembly differs')
    image = ManagedImage(raw)
    if image.runtime != 'v4.0.30319':
        raise ValueError('Managed metadata runtime differs')
    decoded = {name: image.instructions(name) for name in METHODS}
    spans = [image.method(name) for name in METHODS]
    declarations = []
    inputs = [{'name': 'CBusLogicModel.dll', 'sha256': hashlib.sha256(raw).hexdigest(),
               'bytes': len(raw), 'role': 'original-managed-static-input'}]
    for name, symbols in SOURCE.items():
        data = (vendor_root/name).read_bytes()
        if hashlib.sha256(data).hexdigest() != VENDOR_PINS[name]:
            raise ValueError('Pinned declaration differs: '+Path(name).name)
        inputs.append({'name': Path(name).name, 'sha256': hashlib.sha256(data).hexdigest(),
                       'bytes': len(data), 'role': 'pinned-decompiled-static-input'})
        declarations.extend(declaration_span(data, symbol, anchor) for symbol, anchor in symbols)
    checks = []
    def order(name, calls, label):
        require_order([row['symbol'] for row in decoded[name]['calls']], calls, label)
        checks.append({'id': label, 'symbol': name, 'ordered_calls': calls, 'passed': True})
    order(NET+'ReadXmlData', ['get_Languages', 'set_RaiseListChangedEvents',
        'ReadXmlData', 'SelectNodes', 'ReadXmlData', 'get_AddressAsInt',
        'TryParse', 'set_DefaultLanguage', 'GetApplicationByAddress', 'ReadXmlData'],
        'default-import-precedes-application-reload-with-language-events-suppressed')
    order(LEVEL+'ReadXmlData', ['ReadXmlData', 'InitialiseLevel', 'get_TagsDLTAll',
        'Add', 'get_DefaultLanguage', 'ToString', 'set_Item', 'PopulateDynamicAll'],
        'default-language-selects-tags-before-new-dynamic-all')
    order(LEVEL+'PopulateDynamicAll', ['get_DynamicAll', 'set_DynamicAll',
        'set_RaiseListChangedEvents', 'get_DynamicAll', 'Clear', 'get_TagsDLT',
        '.ctor', 'Add', 'NotifyPropertyChanged'], 'dynamic-all-repopulates-current-level-objects')
    order(UNIT+'LoadScenes', ['GetGroupByAddress', 'GetLevelByAddress',
        'set_ActionSelector', 'set_NameIndex', 'Add'], 'initial-scenes-capture-labels-one-slot-at-a-time')
    order(SCENE+'set_ActionSelector', ['GetLevelByAddress', 'RefreshDynamicLables'],
        'explicit-setter-adopts-current-level-labels')
    if any(row['symbol'].endswith('::RefreshDynamicLables')
           for row in decoded[SCENE+'get_ActionSelector']['calls']):
        raise ValueError('Existing valid ActionSelector getter unexpectedly refreshes labels')
    checks.append({'id': 'valid-getter-no-unconditional-label-refresh',
                   'symbol': SCENE+'get_ActionSelector', 'passed': True,
                   'qualification': 'Missing/negative getter can invoke the setter; valid existing getter does not.'})
    # Revalidate the pinned native registration and whole-network bridge chain.
    # This is static evidence of the callback bodies, never their host schedule.
    prior = recover_inventory(vendor_root, original_app)
    bridge_ids = {'bridge-binds-network-refresh-and-add-delegates',
                  'native-embedded-form-registers-project-xml-callback',
                  'native-project-xml-callback-dispatches-managed-update',
                  'managed-update-uses-retained-network-refresh-event',
                  'group-initializer-replaces-levels'}
    bridge = [row for row in prior['static_checks'] if row['id'] in bridge_ids]
    if len(bridge) != len(bridge_ids):
        raise ValueError('Retained bridge checks are incomplete')
    return {'format': 'cbus-edlt-scene-language-static-v1', 'inputs': inputs,
            'managed_method_spans': spans, 'decompiled_declarations': declarations,
            'static_checks': checks, 'retained_refresh_bridge_checks': bridge,
            'retained_bridge_inputs': [{'name': Path(row['path']).name,
                'sha256': row['sha256'], 'bytes': row['bytes'], 'role': row['role']}
                for row in prior['original_inputs']],
            'contract': {
                'admitted_refresh': 'Explicit final text-only Language XML refresh after independently reprojected typed mutations.',
                'default_before_labels': True,
                'old_scene_dynamic_all_retained': True,
                'current_labels_adopted_by': ['explicit ActionSelector setter', 'explicit RefreshDynamicLables'],
                'valid_existing_getter_keeps_old_labels': True,
                'whole_network_collections_replaced': True,
                'language_events_suppressed_during_xml_default_import': True,
                'cancel_or_semantic_noop_refresh_count': 0,
                'changed_final_language_xml_refresh_count': 1,
                'original_per_row_saves_reproduced': False,
                'implicit_callback_schedule_verified': False,
                'framework_instructions_executed': False,
                'original_instructions_executed': False},
            'limits': ['Text-only native labels; no Image/FONT/DYNAMIC/ICON/DLTP admission.',
                       'Unique canonical Languages IDs and one valid default marker.',
                       'Original GUI notifications, scheduling and per-row saves remain unexecuted.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vendor-root', type=Path, required=True)
    parser.add_argument('--original-app', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    result = recover(args.vendor_root, args.original_app)
    raw = (json.dumps(result, indent=2, ensure_ascii=True)+'\n').encode('ascii')
    if args.check:
        if args.output.read_bytes() != raw:
            raise SystemExit('Static Language fixture differs')
    else:
        args.output.write_bytes(raw)
    print(json.dumps({'managed_methods': len(result['managed_method_spans']),
        'declarations': len(result['decompiled_declarations']),
        'checks': len(result['static_checks'])+len(result['retained_refresh_bridge_checks']),
        'sha256': hashlib.sha256(raw).hexdigest(), 'original_execution': False}))


if __name__ == '__main__':
    main()
