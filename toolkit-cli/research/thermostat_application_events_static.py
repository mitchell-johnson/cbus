"""Pin thermostat application notifications using static PE/MAP reads only.

This verifier never calls, emulates or executes original instructions. The
successful initialized existing-application path has one model callback per
changed selector assignment. The migration flag therefore alternates; an
unchanged selection does not reset it. Posted frame/list behavior is joined
with the separate selector verifier, not inferred from control names.
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

METHODS = (
    'System.TObject.InitInstance',
    'CIS_TCommonCBus.TCBUSUnit.InternalCreate',
    'CIS_TCommonCBus.TCBUSUnit.ApplicationChanged',
    'CIS_TCommonCBus.TCBUSUnit.SetApplicationObject',
    'CIS_TCommonCBus.TCBUSApplicationManager.ApplicationByAddress',
    'CIS_TThermostat.TThermostat.InternalCreate',
    'CIS_TThermostat.TThermostat.ApplicationChanged',
    'CIS_TThermostat.TThermostat.RefreshThermostatGroups',
    'CIS_TThermostat.TCBusParameters.HookEvents',
    'CIS_TThermostat.TCBusParameters.UnhookEvents',
    'CIS_TddThermostat.TddThermostat.Initialise',
    'CIS_TddThermostat.TddThermostat.InitialiseForm',
    'CIS_TddThermostat.TddThermostat.InitialiseSubForms',
    'CIS_TddThermostat.TddThermostat.UpdateZoneCheckboxes',
    'CIS_TddThermostat.TddThermostat.Destroy',
    'CIS_TddThermostat.TddThermostat.HandleBeforeLoadTemplate',
    'CIS_TddThermostat.TddThermostat.HandleLoadTemplate',
    'CIS_TddThermostat.TddThermostat.HandleLightingApplicationChange',
    'CIS_TddCBusUnit.TddCBusUnit.Initialise',
    'CIS_TddCBusUnit.OpenUnitForProgramming',
    'CIS_TddCBusUnit.LoadPP',
    'CIS_TddCBusUnit.TddCBusUnit.SaveProgramming',
    'CIS_TddCBusUnit.TddCBusUnit.SaveTemplate',
    'CIS_TCBusUnitCGateAgent.TCBusUnitCGateAgent.LoadProgrammingInformation',
    'CIS_TCBusThermostatCGateAgent.TCBusThermostatCGateAgent.AfterLoadProgrammingInformation',
    'CIS_TCBusThermostatCGateAgent.TCBusBasicThermostatCGateAgent.AfterLoadProgrammingInformation',
    'CIS_TCBusThermostatCGateAgent.TCBusProgrammableThermostatCGateAgent.AfterLoadProgrammingInformation',
    'CIS_TObjectReferenceAttribute.TObjectReferenceAttribute.Create',
    'CIS_TObjectReferenceAttribute.TObjectReferenceAttribute.InternalCreate',
    'CIS_TObjectReferenceAttribute.TObjectReferenceAttribute.MakeInitialised',
    'CIS_TObjectReferenceAttribute.TObjectReferenceAttribute.SetFromElement',
    'CIS_TObjectReferenceAttribute.TObjectReferenceAttribute.SetFlashObject',
    'CIS_TObjectReferenceAttribute.TObjectReferenceAttribute.GetFlashObject',
    'CIS_TObjectReferenceAttribute.TObjectReferenceAttribute.ReferenceChanged',
    'CIS_TObjectReferenceAttribute.TObjectReferenceAttribute.ReferenceReset',
    'CIS_TObjectReferenceAttribute.TObjectReferenceAttribute.ObjectChanged',
    'CIS_TCustomObjectAttribute.TCustomObjectAttribute.InternalCreate',
    'CIS_TCustomFlashObject.TFlashAttribute.Create',
    'CIS_TCustomFlashObject.TFlashAttribute.CanDoChange',
    'CIS_TCustomFlashObject.TFlashAttribute.Changed',
    'CIS_TCustomFlashObject.TCISAttribute.BeginUpdate',
    'CIS_TCustomFlashObject.TCISAttribute.EndUpdate',
    'CIS_TCustomFlashObject.TCISAttribute.Changed',
    'CIS_TCustomFlashObject.TAttributeManager.BeginUpdate',
    'CIS_TCustomFlashObject.TAttributeManager.EndUpdate',
    'CIS_TCustomFlashObject.TCustomFlashObject.Changed',
    'CIS_TCustomFlashObject.TFlashObjectReference.SetFlashObject',
    'CIS_TCustomFlashObject.TFlashObjectReference.ResolveReference',
    'CIS_TCustomFlashObject.TFlashObjectReference.ObjectChanged',
    'CIS_TCustomFlashObject.TFlashObject.UnSubscribeReference',
    'CIS_TCustomFlashObject.TFlashObjectReferenceList.Remove',
    'CIS_TManagedFlashObject.TManagedFlashObject.Changed',
    'CIS_TManagedFlashObject.TFlashElementStatePublisher.Changed',
    'CIS_TManagedFlashObject.TFlashElementStateSubscriber.ObservedObjectChanged',
    'CIS_TBaseObject.TBASEObject.EndUpdate',
    'CIS_Handles.TFlashExpressionController.Create',
    'CIS_Handles.TFlashElementController.SetAsElement',
    'CIS_Handles.TFlashElementController.Apply',
    'CIS_Handles.TFlashExpressionController.Apply',
    'CIS_Handles.TFlashExpressionController.SetFromElement',
    'CIS_Handles.TFlashExpressionController.HandleIsReference',
    'CIS_Handles.TFlashExpressionController.DoFlashHandleChanged',
    'CIS_Handles.TFlashExpressionController.FlashHandleValueChanged',
    'CIS_Handles.TFlashTrackedHandle.Create',
    'CIS_Handles.TFlashTrackedHandle.Update',
    'CIS_Handles.TFlashTrackedHandle.GetCurrentElement',
    'CIS_Handles.TFlashTrackedHandle.RootElementChanged',
    'CIS_Handles.TFlashTrackedHandle.DoRootElementChanged',
    'CIS_Handles.TFlashTrackedHandle.CurrentElementChanged',
    'CIS_Handles.TFlashTrackedHandle.DoCurrentElementChanged',
    'CIS_TFlashCxComboBox.TFlashCxComboBox.Create',
    'CIS_TFlashCxComboBox.TFlashCxComboBox.DoIndexChange',
    'CIS_TFlashCxComboBox.TFlashCxComboBox.DoCloseUp',
    'CIS_TFlashCxComboBox.TFlashCxComboBox.DoExit',
    'CIS_TfrmUnitIDBase.TfrmUnitIDBase.SetupFlashComponents',
    'CIS_TfrmUnitIDBase.TfrmUnitIDBase.SetCBusUnit',
    'CIS_TfrmUnitIDBase.TfrmUnitIDBase.HandleApplicationChange',
    'CIS_TfrmUnitIDBase.TfrmUnitIDBase.HandleAfterComboChange',
    'CIS_FlashGUI.PrepareFlashCxApplicationComboBox',
    'CIS_TcdThermostatPlant.TcdThermostatPlant.UpdateApplicationLink',
    'CIS_TcdThermostatZoneManagement.TcdThermostatZoneManagement.UpdateApplicationLink',
)

POINTS = {
    0x1132fd8: ('mov', 'byte ptr [eax + 0x1e0], 1'),
    0x113301c: ('mov', 'byte ptr [eax + 0x1e0], 0'),
    0xd9167e: ('mov', 'byte ptr [eax + 0x2fc], 1'),
    0xd917ef: ('mov', 'byte ptr [eax + 0x2fc], 0'),
    0xd919c4: ('mov', 'dword ptr [eax + 0x40], 0xd91130'),
    0x84d4d5: ('mov', 'dword ptr [eax + 0x28], 0x84dc5c'),
    0x84e4a1: ('mov', 'dword ptr [eax + 0x30], 0x84eb7c'),
    0x84e4e1: ('mov', 'dword ptr [eax + 0x30], 0x84e590'),
    0x84d8f7: ('call', '0x84dd64'),
    0x84d90d: ('mov', 'byte ptr [eax + 5], 0'),
    0x84d9cd: ('call', 'dword ptr [ebx + 0x40]'),
    0x84da34: ('call', '0x84e008'),
    0x7ed742: ('cmp', 'dword ptr [ebp - 8], 0'),
    0x7ed746: ('je', '0x7ed830'),
    0x7ed824: ('call', 'dword ptr [ebx + 0x28]'),
    0x7ed82e: ('jmp', '0x7ed838'),
    0x7ed833: ('call', '0x7edcbc'),
    0x128e4f3: ('mov', 'eax, dword ptr [eax + 0xf8]'),
    0x128e4fb: ('call', 'dword ptr [edx + 0x94]'),
    0x128e50a: ('call', '0xf2fff8'),
    0x128e50f: ('mov', 'eax, dword ptr [eax + 0xb0]'),
    0x128e515: ('mov', 'cl, 1'),
    0xf26527: ('cmp', 'dword ptr [ebp - 8], 0x100'),
    0xf2652e: ('jl', '0xf26567'),
    0xf2656f: ('call', '0xf26878'),
    0xf2657b: ('jne', '0xf2661e'),
    0xf26581: ('cmp', 'byte ptr [ebp - 9], 1'),
    0xf265b6: ('call', '0xf26410'),
    0xf265c4: ('call', '0xf47d64'),
    0xf265d6: ('call', '0x85adc4'),
    0x606217: ('xor', 'eax, eax'),
    0x60621e: ('rep stosd', 'dword ptr es:[edi], eax'),
    0x606224: ('rep stosb', 'byte ptr es:[edi], al'),
    0xf2ef7c: ('mov', 'dword ptr [edx + 0xbc], eax'),
    0xf2ef8e: ('mov', 'dword ptr [eax + 0x64], edx'),
    0xf2ef99: ('mov', 'dword ptr [eax + 0x60], edx'),
    0xfeb472: ('call', '0xf340c4'),
    0xfeb47a: ('cmp', 'word ptr [eax + 0x1ca], 0'),
    0xfeb487: ('cmp', 'byte ptr [eax + 0x1e3], 0'),
    0xfeb495: ('call', 'dword ptr [edx]'),
    0xfeb4a8: ('call', '0xfec798'),
    0xfeb4bf: ('call', 'dword ptr [edx + 8]'),
    0xfeb4c5: ('mov', 'byte ptr [eax + 0x1e3], 1'),
    0xfeb4d7: ('mov', 'byte ptr [eax + 0x1e3], 0'),
    0xfec7a7: ('cmp', 'byte ptr [eax + 0x1e0], 0'),
    0xfec7b7: ('cmp', 'byte ptr [eax + 0xdf], 0'),
    0xfec80e: ('call', 'dword ptr [ebx + 0x1d0]'),
    0x1131060: ('call', '0xec6b40'),
    0x1131202: ('mov', 'dword ptr [eax + 0x1c8], edx'),
    0x1131219: ('mov', 'dword ptr [eax + 0x1d0], 0x1132f9c'),
    0x113124d: ('call', '0x1132c74'),
    0x1131927: ('mov', 'dword ptr [eax + 0x1d0], edx'),
    0x113193d: ('mov', 'dword ptr [eax + 0x1c8], edx'),
    0x128e4eb: ('call', '0xfdb9d0'),
    0x128e518: ('call', '0xf264fc'),
    0x128e527: ('call', '0xf30014'),
    0x129775c: ('call', '0x128e06c'),
    0x12994f5: ('call', '0x128e06c'),
    0xec6bb9: ('call', '0xec6a3c'),
    0xec6bf3: ('call', '0xec632c'),
    0xec6c13: ('call', '0xec632c'),
    0xec64b9: ('call', '0xec6124'),
    0xec64d0: ('call', '0xec6124'),
    0xcbca5d: ('call', 'dword ptr [edx + 0xa4]'),
    0xec79ee: ('mov', 'byte ptr [eax + 0xdf], 1'),
    0xec8073: ('mov', 'byte ptr [eax + 0xdf], 0'),
    0xec96aa: ('mov', 'byte ptr [eax + 0xdf], 1'),
    0xec97b7: ('mov', 'byte ptr [eax + 0xdf], 0'),
    0x7ddae9: ('mov', 'dword ptr [eax + 0x30], 0x7ddbdc'),
    0x7ddafc: ('mov', 'dword ptr [eax + 0x28], 0x7ddbb8'),
    0x7ddb0f: ('mov', 'dword ptr [eax + 0x20], 0x7ddb94'),
    0x7ec54c: ('mov', 'edx, dword ptr [ebp + 0x14]'),
    0x7ec56b: ('call', '0x7ecd54'),
    0x7ec576: ('mov', 'byte ptr [eax + 0x58], dl'),
    0x7ec586: ('mov', 'byte ptr [eax + 0x6c], dl'),
    0x7ddc06: ('call', 'dword ptr [edx + 0xa0]'),
    0x7ddc19: ('call', 'dword ptr [edx]'),
    0x7ddc34: ('cmp', 'eax, dword ptr [ebp - 8]'),
    0x7ddc37: ('setne', 'byte ptr [ebp - 9]'),
    0x7ddc4d: ('cmp', 'word ptr [eax + 0x92], 0'),
    0x7ddc7e: ('cmp', 'byte ptr [ebp - 9], 0'),
    0x7ddc82: ('je', '0x7ddc92'),
    0x7ddc8d: ('call', '0x7ed6d4'),
    0x7ddca4: ('call', 'dword ptr [edx + 8]'),
    0x7ddbc7: ('call', '0x7682c8'),
    0x7ddbce: ('jne', '0x7ddbd8'),
    0x7ddbd5: ('call', 'dword ptr [edx + 4]'),
    0x7ddba3: ('cmp', 'byte ptr [eax + 0x70], 0'),
    0x7ddba7: ('je', '0x7ddbb1'),
    0x7ec680: ('call', '0x7682c8'),
    0x7ec685: ('xor', 'al, 1'),
    0x7ec64b: ('call', '0x7eca04'),
    0x7ec653: ('cmp', 'byte ptr [eax + 0x1c], 1'),
    0x7ec65c: ('cmp', 'word ptr [eax + 0x62], 0'),
    0x7ec66c: ('call', 'dword ptr [ebx + 0x60]'),
    0x7ece61: ('call', '0x768268'),
    0x7ece76: ('call', '0x7682a4'),
    0x7ece8c: ('call', 'dword ptr [edx + 8]'),
    0x7682ae: ('dec', 'dword ptr [eax + 0x10]'),
    0x7682b4: ('cmp', 'dword ptr [eax + 0x10], 0'),
    0x7682bf: ('call', 'dword ptr [edx + 4]'),
    0x7e7e28: ('call', 'dword ptr [edx]'),
    0x7e7e2d: ('call', '0x768268'),
    0x7e7e82: ('call', '0x7682a4'),
    0x7e7e98: ('call', 'dword ptr [edx + 8]'),
    0x7eca0e: ('call', '0x76a3cc'),
    0x7eca39: ('call', 'dword ptr [edx + 4]'),
    0x76a3d6: ('call', '0x7682c8'),
    0x76a3eb: ('cmp', 'byte ptr [eax + 0x1c], 1'),
    0x76a3f4: ('cmp', 'byte ptr [eax + 0x1d], 0'),
    0x76a407: ('call', '0x76a7c8'),
    0x84f53c: ('call', 'dword ptr [edx + 0x10]'),
    0x84f53f: ('cmp', 'eax, dword ptr [ebp - 8]'),
    0x84f547: ('cmp', 'byte ptr [eax + 0x64], 0'),
    0x84f54b: ('je', '0x84f577'),
    0x84f550: ('cmp', 'byte ptr [eax + 0x4c], 0'),
    0x84f569: ('cmp', 'byte ptr [eax + 0x58], 1'),
    0x84f574: ('call', 'dword ptr [edx + 0x10]'),
    0x84e8c2: ('mov', 'eax, dword ptr [eax + 0x3c]'),
    0x84eeab: ('mov', 'eax, dword ptr [ebp - 4]'),
    0x84eed5: ('mov', 'dword ptr [edx + 0x3c], eax'),
    0xd91158: ('cmp', 'byte ptr [eax + 0x2fd], 0'),
    0xd91164: ('cmp', 'byte ptr [eax + 0x2fc], 0'),
    0xd91180: ('cmp', 'eax, dword ptr [edx + 0x300]'),
    0xd9118c: ('push', '0x486'),
    0xd9119a: ('call', '0x60f418'),
    0xd911b2: ('mov', 'dword ptr [edx + 0x300], eax'),
    0xd911eb: ('cmp', 'byte ptr [eax + 0x2fd], 0'),
    0xd911fb: ('cmp', 'byte ptr [eax + 0x2fc], 0'),
    0xd9120b: ('mov', 'byte ptr [eax + 0x2fd], 1'),
    0xd9124b: ('call', '0xd8e9fc'),
    0xd9126a: ('call', '0x71f038'),
    0xd9127f: ('mov', 'byte ptr [eax + 0x2fd], 0'),
    0xbbbfc1: ('call', '0x84f528'),
    0xbbbfd2: ('push', '0x426'),
}

VIRTUALS = {
    'CIS_TObjectReferenceAttribute..TObjectReferenceAttribute': {
        0: 'CIS_TCustomFlashObject.TCISAttribute.BeginUpdate',
        4: 'CIS_TCustomFlashObject.TFlashAttribute.Changed',
        8: 'CIS_TCustomFlashObject.TCISAttribute.EndUpdate',
        0x3c: 'CIS_TObjectReferenceAttribute.TObjectReferenceAttribute.SetFromElement',
        0xa0: 'CIS_TCustomFlashObject.TFlashAttribute.CanDoChange',
        0xa4: 'CIS_TObjectReferenceAttribute.TObjectReferenceAttribute.GetFlashObject',
        0xa8: 'CIS_TObjectReferenceAttribute.TObjectReferenceAttribute.SetFlashObject',
    },
    'CIS_Handles..TFlashTrackedHandle': {
        0x10: 'CIS_Handles.TFlashTrackedHandle.GetCurrentElement',
    },
    'CIS_TCBusThermostatCGateAgent..TCBusBasicThermostatCGateAgent': {
        0xa4: 'CIS_TCBusThermostatCGateAgent.TCBusBasicThermostatCGateAgent.AfterLoadProgrammingInformation',
    },
    'CIS_TCBusThermostatCGateAgent..TCBusProgrammableThermostatCGateAgent': {
        0xa4: 'CIS_TCBusThermostatCGateAgent.TCBusProgrammableThermostatCGateAgent.AfterLoadProgrammingInformation',
    },
}
for _name in ('TThermostat', 'TPC_TSA', 'TPC_TSA5', 'TPC_TSB', 'TPC_TSB5'):
    VIRTUALS['CIS_TThermostat..' + _name] = {
        0xb8: 'CIS_TThermostat.TThermostat.ApplicationChanged',
    }


def inspect(exe: Path, map_path: Path):
    """Return sanitized source facts; no original instructions are executed."""
    digest = lambda value: hashlib.sha256(value).hexdigest()
    raw, mapping = exe.read_bytes(), map_path.read_bytes()
    if (digest(raw), digest(mapping)) != (EXE_SHA256, MAP_SHA256):
        raise ValueError('Expected the pinned Toolkit executable and map')
    image = _Image(raw, mapping)
    walker = _Walker(image)
    spans, listings, instructions = {}, {}, {}
    for name in METHODS:
        rows, _tables, span_digest = walker.listing(name)
        start = image.by_name[name]
        end = next(address for address in image.starts if address > start)
        spans[name] = {'start': hex(start), 'end': hex(end), 'sha256': span_digest}
        listings[name] = rows
        instructions.update({address: (mnemonic, operand)
                             for address, mnemonic, operand, _ in rows})
    checks = {hex(address): instructions.get(address) == expected
              for address, expected in POINTS.items()}
    virtuals = {}
    for cls, slots in VIRTUALS.items():
        base = image.by_name[cls] + 0x58
        for offset, target in slots.items():
            actual = walker.dword(base + offset)
            key = cls + '+' + hex(offset)
            checks[key] = actual == image.by_name[target]
            virtuals[key] = {'slot': hex(base + offset), 'target': hex(actual), 'method': target}

    def calls(name):
        return [(address, operand, note) for address, mnemonic, operand, note in listings[name]
                if mnemonic == 'call']

    def no_operand_write(name, offset):
        return not any(mnemonic in ('mov', 'inc', 'dec', 'and', 'or', 'xor')
                       and offset in operand.split(',', 1)[0]
                       for _, mnemonic, operand, _ in listings[name])

    attr = 'CIS_TObjectReferenceAttribute.TObjectReferenceAttribute.'
    base = 'CIS_TCustomFlashObject.'
    control = 'CIS_Handles.TFlashElementController.'
    parent = 'CIS_TddThermostat.TddThermostat.'
    checks['one_outer_attribute_begin'] = sum(p == 'dword ptr [edx]'
        for _, p, _ in calls(attr + 'SetFlashObject')) == 1
    checks['one_outer_attribute_end_in_finally'] = sum(p == 'dword ptr [edx + 8]'
        for _, p, _ in calls(attr + 'SetFlashObject')) == 1
    checks['one_inner_reference_assignment'] = sum(
        n == base + 'TFlashObjectReference.SetFlashObject'
        for _, _, n in calls(attr + 'SetFlashObject')) == 1
    checks['inner_reference_callback_once'] = sum(p == 'dword ptr [ebx + 0x28]'
        for _, p, _ in calls(base + 'TFlashObjectReference.SetFlashObject')) == 1
    checks['reset_only_nil_branch'] = instructions[0x7ed746] == ('je', '0x7ed830') and any(
        a == 0x7ed833 and n == base + 'TFlashObjectReference.Reset'
        for a, _, n in calls(base + 'TFlashObjectReference.SetFlashObject'))
    checks['old_reference_unsubscribe_does_not_reset'] = not any('Reset' in n
        for name in (base + 'TFlashObject.UnSubscribeReference', base + 'TFlashObjectReferenceList.Remove')
        for _, _, n in calls(name))
    checks['one_after_change_callback'] = sum(p == 'dword ptr [ebx + 0x60]'
        for _, p, _ in calls(base + 'TFlashAttribute.Changed')) == 1
    checks['publication_precedes_after_change_callback'] = next(a for a, _, n in calls(
        base + 'TFlashAttribute.Changed') if n == base + 'TCISAttribute.Changed') < next(
            a for a, p, _ in calls(base + 'TFlashAttribute.Changed') if p == 'dword ptr [ebx + 0x60]')
    checks['manager_end_updates_owner_not_each_attribute'] = [n for _, _, n in calls(
        base + 'TAttributeManager.EndUpdate') if n] == ['CIS_TBaseObject.TBASEObject.EndUpdate']
    checks['reference_forwarding_default_zero'] = all(no_operand_write(name, '+ 0x70]') for name in (
        attr + 'Create', attr + 'InternalCreate', 'CIS_TCustomObjectAttribute.TCustomObjectAttribute.InternalCreate',
        base + 'TFlashAttribute.Create'))
    checks['application_attribute_no_forwarding_or_changing_override'] = not any(
        mnemonic == 'mov' and any(offset in operand.split(',', 1)[0] for offset in ('+ 0x70]', '+ 0x90]'))
        for address, mnemonic, operand, _ in listings['CIS_TCommonCBus.TCBUSUnit.InternalCreate']
        if 0xf2ef7c <= address < 0xf2efa0)
    checks['controller_force_same_default_zero'] = all(no_operand_write(name, '+ 0x64]') for name in (
        'CIS_Handles.TFlashExpressionController.Create',
        'CIS_FlashGUI.PrepareFlashCxApplicationComboBox'))
    checks['no_application_second_setter_in_parent_initialise'] = not any(
        n.endswith('.SetApplicationObject') for _, _, n in calls(parent + 'Initialise'))
    checks['parent_post_install_tail_only_status_zones_and_delay'] = not any(
        'Application' in n and not n.endswith('.GetWorkSpace')
        for a, _, n in calls(parent + 'Initialise') if a > 0x1131219)
    checks['cbus_parameter_hook_only_installed_zones'] = [operand for _, mnemonic, operand, _ in
        listings['CIS_TThermostat.TCBusParameters.HookEvents'] if mnemonic == 'mov'
        and operand.startswith('dword ptr [eax + 0x60],')] == ['dword ptr [eax + 0x60], 0xfdbb0c']
    checks['initial_raw_application_path_has_no_selector_or_lighting_filter'] = [note
        for address, mnemonic, _, note in listings[
            'CIS_TCBusThermostatCGateAgent.TCBusThermostatCGateAgent.AfterLoadProgrammingInformation']
        if 0x128e4f0 <= address <= 0x128e527 and mnemonic == 'call' and note] == [
            'CIS_TCBusThermostatCGateAgent.TCBusThermostatCGateAgent.GetCBusUnit',
            'CIS_TCommonCBus.TCBUSUnit.GetNetwork',
            'CIS_TCommonCBus.TCBUSApplicationManager.ApplicationByAddress',
            'CIS_TCBusThermostatCGateAgent.TCBusThermostatCGateAgent.GetCBusUnit',
            'CIS_TCommonCBus.TCBUSUnit.SetApplicationObject']
    checks['base_application_changed_no_calls'] = not calls('CIS_TCommonCBus.TCBUSUnit.ApplicationChanged')
    checks['posted_handler_no_direct_application_assignment_or_link_rebind'] = not any(
        'SetApplicationObject' in n or 'UpdateApplicationLink' in n or 'SetAsElement' in n
        for name in ('CIS_TfrmUnitIDBase.TfrmUnitIDBase.HandleApplicationChange',
                     'CIS_TfrmUnitIDBase.TfrmUnitIDBase.HandleAfterComboChange')
        for _, _, n in calls(name))
    checks['parent_link_rebind_order_zone_then_plant'] = [n for _, _, n in calls(
        parent + 'HandleLightingApplicationChange') if n.endswith('.UpdateApplicationLink')] == [
            'CIS_TcdThermostatZoneManagement.TcdThermostatZoneManagement.UpdateApplicationLink',
            'CIS_TcdThermostatPlant.TcdThermostatPlant.UpdateApplicationLink']
    checks['no_synchronous_message_pump_in_model_or_posting_handlers'] = not any(
        'ProcessMessages' in n or 'ShowModal' in n or 'SendMessage' in n
        for name in ('CIS_TThermostat.TThermostat.ApplicationChanged',
                     'CIS_TThermostat.TThermostat.RefreshThermostatGroups',
                     'CIS_TfrmUnitIDBase.TfrmUnitIDBase.HandleApplicationChange')
        for _, _, n in calls(name))
    checks['same_item_does_not_reach_apply'] = instructions[0x84f54b] == ('je', '0x84f577')
    checks['closeup_only_one_commit_entry'] = sum(n.endswith('.DoIndexChange')
        for _, _, n in calls('CIS_TFlashCxComboBox.TFlashCxComboBox.DoCloseUp')) == 1
    checks['exit_does_not_commit_again'] = not any(n.endswith('.DoIndexChange')
        for _, _, n in calls('CIS_TFlashCxComboBox.TFlashCxComboBox.DoExit'))
    checks['direct_toggle_accesses_in_consumed_methods_only_application_changed'] = all(
        name == 'CIS_TThermostat.TThermostat.ApplicationChanged'
        for name, rows in listings.items() for _, _, operand, _ in rows if '+ 0x1e3]' in operand)
    if not all(checks.values()):
        raise ValueError('Application event source differs: ' + ', '.join(
            key for key, value in checks.items() if not value))
    if (digest(exe.read_bytes()), digest(map_path.read_bytes())) != (EXE_SHA256, MAP_SHA256):
        raise ValueError('Original source inputs changed during inspection')
    return {
        'format': 'cbus-thermostat-application-events-static-v1',
        'original_exe_sha256': EXE_SHA256, 'original_map_sha256': MAP_SHA256,
        'original_executed': False, 'native_vendor_executed': False, 'physical_io': False,
        'checks': dict(sorted(checks.items())), 'method_spans': spans, 'virtual_slots': virtuals,
        'initialized_profile': {
            'entry': 'Successful ordinary programming load followed by thermostat parent initialization.',
            'decision_callback_installed_after_load': True,
            'initial_application_changed_flag': False,
            'initial_template_guard': False,
            'initial_save_guard': False,
            'initial_application': 'Raw ApplicationNumber byte 0..255, including 115 and 255; lookup/create directly, without selector or lighting filtering.',
            'reopen': 'Destroy clears callbacks; ordinary AfterLoad calls the reference setter even for the same object.',
            'not_an_operator_supplied_state': True,
        },
        'event_rules': {
            'changed_existing_application_callback_count': 1,
            'same_current_application_callback_count': 0,
            'same_selection_preserves_flag': True,
            'changed_selection_with_flag_false': 'Refresh references and bound lists, then set flag true.',
            'changed_selection_with_flag_true': 'Clear flag; do not refresh references or bound lists.',
            'object_reference_internal_notification': 'Suppressed while the attribute update is active.',
            'attribute_publication': 'Synchronous handle update and parent refresh post precede ApplicationChanged.',
            'parent_refresh_message': 0x486,
            'combo_changed_message': 0x426,
            'posted_parent_refresh': 'Frame refresh and focus restoration; no direct model or link assignment.',
            'save_guard': 'SaveProgramming and SaveTemplate set +0xdf only within their save/cleanup paths.',
            'template_guard': 'Separate +0x1e0 load-template scope, not public readiness.',
            'application_identity_axes': ['current model Application', 'Plant/Zone list-bound Application',
                                          'actual Application of each retained Group reference'],
        },
        'boundary': {
            'original_gui_executed': False,
            'host_scheduling_executed': False,
            'exception_or_template_history_admitted': False,
            'selector_filter_and_no_posted_rebind_proof': 'thermostat_application_selector_static.py',
            'normal_storage_message_pump_and_collection_sort_proof': 'Separate manager/order source receipt.',
            'add_edit_focus_and_cached_index': 'Separate selector callback proof; not inferred from model notifications.',
        },
        'literal_event_cases': [
            {'history': ['A'], 'initial_current': 'A', 'model_callbacks': 0,
             'migration_passes': 0, 'current': 'A', 'list_binding': 'A', 'flag': False},
            {'history': ['B'], 'initial_current': 'A', 'model_callbacks': 1,
             'migration_passes': 1, 'current': 'B', 'list_binding': 'B', 'flag': True},
            {'history': ['B', 'B'], 'initial_current': 'A', 'model_callbacks': 1,
             'migration_passes': 1, 'current': 'B', 'list_binding': 'B', 'flag': True},
            {'history': ['B', 'C'], 'initial_current': 'A', 'model_callbacks': 2,
             'migration_passes': 1, 'current': 'C', 'list_binding': 'B', 'flag': False},
            {'history': ['B', 'C', 'D'], 'initial_current': 'A', 'model_callbacks': 3,
             'migration_passes': 2, 'current': 'D', 'list_binding': 'D', 'flag': True},
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
