"""Inspect typed thermostat output Add source statically; never execute originals.

Pins accepted/cancelled paths, dialog name/address rules, controller preparation,
constructor defaults and absence of thermostat-specific Add/veto handlers.
No original instructions, vendor services, native GUI or hardware are executed.
The output contains source identities, bounded checkpoints and derived facts,
never vendor instruction bytes, full listings or private input coordinates.
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
from topology_generator_static import EXE_SHA256, MAP_SHA256, _Image  # noqa: E402
from thermostat_post_load_static import _Walker  # noqa: E402
from thermostat_quick_zone_initialization_static import dfm_properties  # noqa: E402
from thermostat_quick_zone_gui_binding_static import dynamic_methods  # noqa: E402

METHODS = ('CIS_TFlashCxGroupComboBox.TFlashCxGroupComboBox.DoButtonAddClick',
 'CIS_TFlashCxGroupComboBox.TFlashCxGroupComboBox.GetCBusApplication',
 'CIS_TddThermostat.TddThermostat.HandleLightingApplicationChange',
 'CIS_TFlashCxGroupComboBox.TFlashCxGroupComboBox.UpdateEnableState',
 'CIS_TFlashCxComboBox.TFlashCxComboBox.DoOnCanChangeElement',
 'CIS_TFlashCxComboBox.TFlashCxComboBox.DoOnBeforeChange',
 'CIS_TFlashCxActionComboBox.TCustomFlashCxActionComboBox.UpdateActionButtons',
 'CIS_TCommonCBus.TCBUSApplication.GetCanAddGroups',
 'CIS_TCommonCBus.TCBusGroupManager.GetNextAvailableAddress',
 'CIS_TfrmGroupAssign.TfrmGroupAssign.SetValues',
 'CIS_TfrmGroupAssign.TfrmGroupAssign.cmbGroupAddressChange',
 'CIS_TCommonCBus.TCBusGroupManager.GetMaximumPossibleAddress',
 'CIS_TfrmGroupAssign.TfrmGroupAssign.actOKExecute',
 'CIS_TFlashCxGroupComboBox.TFlashCxGroupComboBox.Create',
 'CIS_TFlashCxActionComboBox.TCustomFlashCxActionComboBox.Create',
 'CIS_TFlashCxComboBox.TFlashCxComboBox.Create',
 'CIS_TFlashCxComboBox.TFlashCxComboBox.UpdateEnableState',
 'CIS_FlashGUI.PrepareFlashCxGroupComboBox',
 'CIS_TfrmGroupAssign.TfrmGroupAssign.actOKUpdate',
 'CIS_TfrmGroupAssign.TfrmGroupAssign.SelectedAddress',
 'CIS_TfrmGroupAssign.TfrmGroupAssign.IsSiteOpen',
 'CIS_TCommonCBus.TCBusGroupManager.GroupByTagNameExclude',
 'CIS_Handles.TFlashExpressionController.SetActive',
 'CIS_Handles.TFlashExpressionController.GetActive',
 'SysUtils.UpperCase',
 'CIS_TcdThermostatPlant.TcdThermostatPlant.Create',
 'CIS_TcdThermostatPlant.TcdThermostatPlant.SetupComponents',
 'CIS_TcdThermostatPlant.TcdThermostatPlant.SetupFlashComponents',
 'CIS_TfrmThermostatCoolingGroups.TfrmCoolingGroups.FormShow',
 'CIS_TfrmThermostatCoolingGroups.TfrmCoolingGroups.SetupComponents',
 'CIS_TfrmThermostatCoolingGroups.TfrmCoolingGroups.SetupFlashComponents',
 'CIS_TfrmThermostatDamperGroups.TfrmDamperGroups.FormShow',
 'CIS_TfrmThermostatDamperGroups.TfrmDamperGroups.SetupFlashComponents',
 'CIS_TfrmThermostatHeatingGroups.TfrmHeatingGroups.FormShow',
 'CIS_TfrmThermostatHeatingGroups.TfrmHeatingGroups.SetupComponents',
 'CIS_TfrmThermostatHeatingGroups.TfrmHeatingGroups.SetupFlashComponents',
 'System.TObject.InitInstance',
 'CIS_TFlashCxActionComboBox.TCustomFlashCxActionComboBox.HandleButtonAddClick',
 'CIS_TFlashCxActionComboBox.TCustomFlashCxActionComboBox.DoButtonAddClick',
 'CIS_TFlashCxComboBox.TFlashCxComboBox.DoIndexChange',
 'CIS_TFlashCxComboBox.TFlashCxComboBox.HandleComboChange',
 'CIS_TFlashCxComboBox.TFlashCxComboBox.Loaded',
 'SysUtils.Trim',
 'CIS_TCBusObject.TCGateObject.InternalCreate',
 'CIS_TCommonCBus.TProject.InternalCreate',
 'StdCtrls.TCustomEdit.SetMaxLength',
 'StdCtrls.TCustomEdit.CreateWnd',
 'StdCtrls.TCustomEdit.DoSetMaxLength',
 'CIS_TCommonCBus.TCBUSApplication.GetDefaultGroupName',
 'CIS_TCommonCBus.TCBUSApplication.GetHasReservedGroupAddress255',
 'CIS_TCommonCBus.TCBusGroupManager.GroupByAddressExclude',
 'CIS_TStandardCBusApplications.TStandardCBusApplications.GetGroupName',
 'CIS_TStandardCBusApplications.CIS_TStandardCBusApplications')

CHECKPOINTS = {'0x6186fe': {'method': 'SysUtils.UpperCase', 'mnemonic': 'cmp', 'operand': 'ax, 2'},
 '0x618702': {'method': 'SysUtils.UpperCase', 'mnemonic': 'je', 'operand': '0x618713'},
 '0x618736': {'method': 'SysUtils.UpperCase', 'mnemonic': 'movzx', 'operand': 'eax, word ptr [ebx]'},
 '0x61873b': {'method': 'SysUtils.UpperCase', 'mnemonic': 'add', 'operand': 'esi, -0x61'},
 '0x61873e': {'method': 'SysUtils.UpperCase', 'mnemonic': 'sub', 'operand': 'si, 0x1a'},
 '0x618742': {'method': 'SysUtils.UpperCase', 'mnemonic': 'jae', 'operand': '0x618748'},
 '0x618744': {'method': 'SysUtils.UpperCase', 'mnemonic': 'xor', 'operand': 'ax, 0x20'},
 '0x618748': {'method': 'SysUtils.UpperCase', 'mnemonic': 'mov', 'operand': 'word ptr [ecx], ax'},
 '0x61874b': {'method': 'SysUtils.UpperCase', 'mnemonic': 'add', 'operand': 'ecx, 2'},
 '0x61874e': {'method': 'SysUtils.UpperCase', 'mnemonic': 'add', 'operand': 'ebx, 2'},
 '0x618ffc': {'method': 'SysUtils.Trim', 'mnemonic': 'cmp', 'operand': 'word ptr [eax + ebx*2 - 2], 0x20'},
 '0x619002': {'method': 'SysUtils.Trim', 'mnemonic': 'jbe', 'operand': '0x618fef'},
 '0x61901d': {'method': 'SysUtils.Trim', 'mnemonic': 'cmp', 'operand': 'word ptr [eax + esi*2 - 2], 0x20'},
 '0x619023': {'method': 'SysUtils.Trim', 'mnemonic': 'jbe', 'operand': '0x619014'},
 '0x6852f9': {'method': 'StdCtrls.TCustomEdit.DoSetMaxLength', 'mnemonic': 'push', 'operand': '0xc5'},
 '0x685306': {'method': 'StdCtrls.TCustomEdit.DoSetMaxLength', 'mnemonic': 'call', 'operand': '0x60f4c4'},
 '0x68541a': {'method': 'StdCtrls.TCustomEdit.SetMaxLength',
              'mnemonic': 'mov',
              'operand': 'dword ptr [ebx + 0x274], esi'},
 '0x685431': {'method': 'StdCtrls.TCustomEdit.SetMaxLength',
              'mnemonic': 'call',
              'operand': 'dword ptr [ecx + 0xec]'},
 '0xbbbfd2': {'method': 'CIS_TFlashCxComboBox.TFlashCxComboBox.DoIndexChange',
              'mnemonic': 'push',
              'operand': '0x426'},
 '0xbbbfe0': {'method': 'CIS_TFlashCxComboBox.TFlashCxComboBox.DoIndexChange',
              'mnemonic': 'call',
              'operand': '0x60f418'},
 '0xbbc2de': {'method': 'CIS_TFlashCxComboBox.TFlashCxComboBox.Loaded',
              'mnemonic': 'call',
              'operand': '0x84de00'},
 '0xbbc2ee': {'method': 'CIS_TFlashCxComboBox.TFlashCxComboBox.Loaded',
              'mnemonic': 'call',
              'operand': '0x84de00'},
 '0xbbda62': {'method': 'CIS_TFlashCxActionComboBox.TCustomFlashCxActionComboBox.Create',
              'mnemonic': 'mov',
              'operand': 'byte ptr [eax + 0x518], dl'},
 '0xbc2e4e': {'method': 'CIS_TfrmGroupAssign.TfrmGroupAssign.actOKExecute',
              'mnemonic': 'call',
              'operand': '0x618f9c'},
 '0xbc2e53': {'method': 'CIS_TfrmGroupAssign.TfrmGroupAssign.actOKExecute',
              'mnemonic': 'cmp',
              'operand': 'dword ptr [ebp - 0x14], 0'},
 '0xbc2e57': {'method': 'CIS_TfrmGroupAssign.TfrmGroupAssign.actOKExecute',
              'mnemonic': 'jne',
              'operand': '0xbc2e87'},
 '0xbc2e9e': {'method': 'CIS_TfrmGroupAssign.TfrmGroupAssign.actOKExecute',
              'mnemonic': 'call',
              'operand': '0x618f9c'},
 '0xbc2eb0': {'method': 'CIS_TfrmGroupAssign.TfrmGroupAssign.actOKExecute',
              'mnemonic': 'call',
              'operand': '0xf260b4'},
 '0xbc2eb5': {'method': 'CIS_TfrmGroupAssign.TfrmGroupAssign.actOKExecute',
              'mnemonic': 'call',
              'operand': '0xf2b260'},
 '0xbc2eba': {'method': 'CIS_TfrmGroupAssign.TfrmGroupAssign.actOKExecute',
              'mnemonic': 'mov',
              'operand': 'eax, dword ptr [eax + 0x9c]'},
 '0xbc2ec5': {'method': 'CIS_TfrmGroupAssign.TfrmGroupAssign.actOKExecute',
              'mnemonic': 'call',
              'operand': 'dword ptr [ecx + 0x2c]'},
 '0xbc2ecc': {'method': 'CIS_TfrmGroupAssign.TfrmGroupAssign.actOKExecute',
              'mnemonic': 'call',
              'operand': '0x6090ac'},
 '0xbc2ed1': {'method': 'CIS_TfrmGroupAssign.TfrmGroupAssign.actOKExecute',
              'mnemonic': 'jne',
              'operand': '0xbc2f01'},
 '0xbc2ef2': {'method': 'CIS_TfrmGroupAssign.TfrmGroupAssign.actOKExecute',
              'mnemonic': 'mov',
              'operand': 'edx, 0x89c'},
 '0xbc2f28': {'method': 'CIS_TfrmGroupAssign.TfrmGroupAssign.actOKExecute',
              'mnemonic': 'call',
              'operand': '0xf28d10'},
 '0xbc2f2f': {'method': 'CIS_TfrmGroupAssign.TfrmGroupAssign.actOKExecute',
              'mnemonic': 'jne',
              'operand': '0xbc3071'},
 '0xbc2f4c': {'method': 'CIS_TfrmGroupAssign.TfrmGroupAssign.actOKExecute',
              'mnemonic': 'call',
              'operand': '0x618f9c'},
 '0xbc2f6c': {'method': 'CIS_TfrmGroupAssign.TfrmGroupAssign.actOKExecute',
              'mnemonic': 'call',
              'operand': '0xf28e28'},
 '0xbc2f73': {'method': 'CIS_TfrmGroupAssign.TfrmGroupAssign.actOKExecute',
              'mnemonic': 'jne',
              'operand': '0xbc302f'},
 '0xbc2f85': {'method': 'CIS_TfrmGroupAssign.TfrmGroupAssign.actOKExecute',
              'mnemonic': 'call',
              'operand': '0xf47d64'},
 '0xbc2fa1': {'method': 'CIS_TfrmGroupAssign.TfrmGroupAssign.actOKExecute',
              'mnemonic': 'call',
              'operand': '0x618f9c'},
 '0xbc2fc5': {'method': 'CIS_TfrmGroupAssign.TfrmGroupAssign.actOKExecute',
              'mnemonic': 'call',
              'operand': 'dword ptr [ecx + 0x7c]'},
 '0xbc2fd2': {'method': 'CIS_TfrmGroupAssign.TfrmGroupAssign.actOKExecute',
              'mnemonic': 'jne',
              'operand': '0xbc3020'},
 '0xbc3023': {'method': 'CIS_TfrmGroupAssign.TfrmGroupAssign.actOKExecute',
              'mnemonic': 'mov',
              'operand': 'dword ptr [eax + 0x2b8], 1'},
 '0xbc3065': {'method': 'CIS_TfrmGroupAssign.TfrmGroupAssign.actOKExecute',
              'mnemonic': 'mov',
              'operand': 'edx, 0x89b'},
 '0xbc30a3': {'method': 'CIS_TfrmGroupAssign.TfrmGroupAssign.actOKExecute',
              'mnemonic': 'mov',
              'operand': 'edx, 0x899'},
 '0xbc3291': {'method': 'CIS_TfrmGroupAssign.TfrmGroupAssign.cmbGroupAddressChange',
              'mnemonic': 'call',
              'operand': '0x609114'},
 '0xbc329c': {'method': 'CIS_TfrmGroupAssign.TfrmGroupAssign.cmbGroupAddressChange',
              'mnemonic': 'call',
              'operand': '0x6186e4'},
 '0xbc32b1': {'method': 'CIS_TfrmGroupAssign.TfrmGroupAssign.cmbGroupAddressChange',
              'mnemonic': 'call',
              'operand': '0x6186e4'},
 '0xbc32ba': {'method': 'CIS_TfrmGroupAssign.TfrmGroupAssign.cmbGroupAddressChange',
              'mnemonic': 'call',
              'operand': '0x6090ac'},
 '0xbc32c5': {'method': 'CIS_TfrmGroupAssign.TfrmGroupAssign.cmbGroupAddressChange',
              'mnemonic': 'jmp',
              'operand': '0xbc32e0'},
 '0xbc32dc': {'method': 'CIS_TfrmGroupAssign.TfrmGroupAssign.cmbGroupAddressChange',
              'mnemonic': 'sete',
              'operand': 'byte ptr [ebp - 0xd]'},
 '0xbc32e4': {'method': 'CIS_TfrmGroupAssign.TfrmGroupAssign.cmbGroupAddressChange',
              'mnemonic': 'je',
              'operand': '0xbc3325'},
 '0xbc32f7': {'method': 'CIS_TfrmGroupAssign.TfrmGroupAssign.cmbGroupAddressChange',
              'mnemonic': 'call',
              'operand': '0xbc34b0'},
 '0xbc3649': {'method': 'CIS_TfrmGroupAssign.TfrmGroupAssign.SetValues',
              'mnemonic': 'cmp',
              'operand': 'byte ptr [eax + 0x411], 0'},
 '0xbc3655': {'method': 'CIS_TfrmGroupAssign.TfrmGroupAssign.SetValues',
              'mnemonic': 'mov',
              'operand': 'byte ptr [eax + 0x411], 0xfe'},
 '0xbc5913': {'method': 'CIS_TFlashCxGroupComboBox.TFlashCxGroupComboBox.DoButtonAddClick',
              'mnemonic': 'call',
              'operand': '0xbbe45c'},
 '0xbc5922': {'method': 'CIS_TFlashCxGroupComboBox.TFlashCxGroupComboBox.DoButtonAddClick',
              'mnemonic': 'je',
              'operand': '0xbc5c21'},
 '0xbc5954': {'method': 'CIS_TFlashCxGroupComboBox.TFlashCxGroupComboBox.DoButtonAddClick',
              'mnemonic': 'call',
              'operand': '0xf289fc'},
 '0xbc595c': {'method': 'CIS_TFlashCxGroupComboBox.TFlashCxGroupComboBox.DoButtonAddClick',
              'mnemonic': 'cmp',
              'operand': 'dword ptr [ebp - 0x10], -1'},
 '0xbc5960': {'method': 'CIS_TFlashCxGroupComboBox.TFlashCxGroupComboBox.DoButtonAddClick',
              'mnemonic': 'je',
              'operand': '0xbc5bda'},
 '0xbc5980': {'method': 'CIS_TFlashCxGroupComboBox.TFlashCxGroupComboBox.DoButtonAddClick',
              'mnemonic': 'call',
              'operand': '0x7ea6ac'},
 '0xbc59be': {'method': 'CIS_TFlashCxGroupComboBox.TFlashCxGroupComboBox.DoButtonAddClick',
              'mnemonic': 'call',
              'operand': '0xf254a4'},
 '0xbc59ef': {'method': 'CIS_TFlashCxGroupComboBox.TFlashCxGroupComboBox.DoButtonAddClick',
              'mnemonic': 'call',
              'operand': '0x61b6e8'},
 '0xbc5a2f': {'method': 'CIS_TFlashCxGroupComboBox.TFlashCxGroupComboBox.DoButtonAddClick',
              'mnemonic': 'mov',
              'operand': 'dword ptr [edx + 0x3f4], eax'},
 '0xbc5a3e': {'method': 'CIS_TFlashCxGroupComboBox.TFlashCxGroupComboBox.DoButtonAddClick',
              'mnemonic': 'mov',
              'operand': 'byte ptr [eax + 0x404], 1'},
 '0xbc5a55': {'method': 'CIS_TFlashCxGroupComboBox.TFlashCxGroupComboBox.DoButtonAddClick',
              'mnemonic': 'call',
              'operand': '0x608924'},
 '0xbc5a79': {'method': 'CIS_TFlashCxGroupComboBox.TFlashCxGroupComboBox.DoButtonAddClick',
              'mnemonic': 'call',
              'operand': '0x85b2c4'},
 '0xbc5aa0': {'method': 'CIS_TFlashCxGroupComboBox.TFlashCxGroupComboBox.DoButtonAddClick',
              'mnemonic': 'mov',
              'operand': 'dword ptr [eax + 0x3f8], edx'},
 '0xbc5aa9': {'method': 'CIS_TFlashCxGroupComboBox.TFlashCxGroupComboBox.DoButtonAddClick',
              'mnemonic': 'mov',
              'operand': 'al, byte ptr [eax + 0x51a]'},
 '0xbc5ab8': {'method': 'CIS_TFlashCxGroupComboBox.TFlashCxGroupComboBox.DoButtonAddClick',
              'mnemonic': 'mov',
              'operand': 'byte ptr [edx + 0x410], al'},
 '0xbc5ac1': {'method': 'CIS_TFlashCxGroupComboBox.TFlashCxGroupComboBox.DoButtonAddClick',
              'mnemonic': 'mov',
              'operand': 'al, byte ptr [eax + 0x519]'},
 '0xbc5ad0': {'method': 'CIS_TFlashCxGroupComboBox.TFlashCxGroupComboBox.DoButtonAddClick',
              'mnemonic': 'mov',
              'operand': 'byte ptr [edx + 0x411], al'},
 '0xbc5adf': {'method': 'CIS_TFlashCxGroupComboBox.TFlashCxGroupComboBox.DoButtonAddClick',
              'mnemonic': 'call',
              'operand': '0xbc356c'},
 '0xbc5b1b': {'method': 'CIS_TFlashCxGroupComboBox.TFlashCxGroupComboBox.DoButtonAddClick',
              'mnemonic': 'cmp',
              'operand': 'word ptr [ebp - 0x12], 1'},
 '0xbc5b20': {'method': 'CIS_TFlashCxGroupComboBox.TFlashCxGroupComboBox.DoButtonAddClick',
              'mnemonic': 'jne',
              'operand': '0xbc5b9b'},
 '0xbc5b25': {'method': 'CIS_TFlashCxGroupComboBox.TFlashCxGroupComboBox.DoButtonAddClick',
              'mnemonic': 'call',
              'operand': '0xbbc080'},
 '0xbc5b3d': {'method': 'CIS_TFlashCxGroupComboBox.TFlashCxGroupComboBox.DoButtonAddClick',
              'mnemonic': 'call',
              'operand': 'dword ptr [ecx + 0x64]'},
 '0xbc5b52': {'method': 'CIS_TFlashCxGroupComboBox.TFlashCxGroupComboBox.DoButtonAddClick',
              'mnemonic': 'call',
              'operand': 'dword ptr [ebx + 0x80]'},
 '0xbc5b5e': {'method': 'CIS_TFlashCxGroupComboBox.TFlashCxGroupComboBox.DoButtonAddClick',
              'mnemonic': 'call',
              'operand': '0xbbc0ac'},
 '0xbc5b83': {'method': 'CIS_TFlashCxGroupComboBox.TFlashCxGroupComboBox.DoButtonAddClick',
              'mnemonic': 'call',
              'operand': 'dword ptr [ecx + 0xa8]'},
 '0xbc5b8c': {'method': 'CIS_TFlashCxGroupComboBox.TFlashCxGroupComboBox.DoButtonAddClick',
              'mnemonic': 'call',
              'operand': '0xbbc2f8'},
 '0xbc5b94': {'method': 'CIS_TFlashCxGroupComboBox.TFlashCxGroupComboBox.DoButtonAddClick',
              'mnemonic': 'call',
              'operand': '0xbbbee8'},
 '0xbc5b9e': {'method': 'CIS_TFlashCxGroupComboBox.TFlashCxGroupComboBox.DoButtonAddClick',
              'mnemonic': 'call',
              'operand': '0x606200'},
 '0xbc5c17': {'method': 'CIS_TFlashCxGroupComboBox.TFlashCxGroupComboBox.DoButtonAddClick',
              'mnemonic': 'mov',
              'operand': 'edx, 0x8df'},
 '0xc104aa': {'method': 'CIS_FlashGUI.PrepareFlashCxGroupComboBox',
              'mnemonic': 'call',
              'operand': '0x84de00'},
 '0xc104ba': {'method': 'CIS_FlashGUI.PrepareFlashCxGroupComboBox',
              'mnemonic': 'call',
              'operand': '0x84de00'},
 '0xf2d20a': {'method': 'CIS_TCommonCBus.TProject.InternalCreate', 'mnemonic': 'call', 'operand': '0xf47718'},
 '0xf47734': {'method': 'CIS_TCBusObject.TCGateObject.InternalCreate',
              'mnemonic': 'push',
              'operand': '0xf47830'},
 '0xf47754': {'method': 'CIS_TCBusObject.TCGateObject.InternalCreate',
              'mnemonic': 'mov',
              'operand': 'dword ptr [edx + 0x9c], eax'},
 '0xf47763': {'method': 'CIS_TCBusObject.TCGateObject.InternalCreate',
              'mnemonic': 'mov',
              'operand': 'dword ptr [eax + 0x50], 0x20'}}

PUBLISHED_PROPERTIES = {'CIS_TFlashCxActionComboBox..TCustomFlashCxActionComboBox': {},
 'CIS_TFlashCxComboBox..TFlashCxComboBox': {'OnBeforeChange': {'address': '0xbbba8d',
                                                               'default': 2147483648,
                                                               'get': '0xff0004e0',
                                                               'set': '0xff0004e0'},
                                            'OnCanChangeElement': {'address': '0xbbbad9',
                                                                   'default': 2147483648,
                                                                   'get': '0xff000508',
                                                                   'set': '0xff000508'},
                                            'OnChange': {'address': '0xbbbab6',
                                                         'default': 2147483648,
                                                         'get': '0xff0004e8',
                                                         'set': '0xff0004e8'}},
 'CIS_TFlashCxGroupComboBox..TFlashCxGroupComboBox': {'ActionButtons': {'address': '0xbc4741',
                                                                        'default': 3,
                                                                        'get': '0xff000518',
                                                                        'set': '0xbbde68'},
                                                      'AllowIfControllerInactive': {'address': '0xbc478d',
                                                                                    'default': 1,
                                                                                    'get': '0xff000581',
                                                                                    'set': '0xff000581'},
                                                      'OnAfterButtonAddClick': {'address': '0xbc488b',
                                                                                'default': 2147483648,
                                                                                'get': '0xff000560',
                                                                                'set': '0xff000560'},
                                                      'OnBeforeButtonAddClick': {'address': '0xbc47c1',
                                                                                 'default': 2147483648,
                                                                                 'get': '0xff000540',
                                                                                 'set': '0xff000540'}}}

WIRE_METHODS = (
    'CIS_TCBusGroupCGateAgent.TCBusGroupCGateAgent.AgentSave',
    'CIS_TCBusGroupCGateAgent.TCBusGroupCGateAgent.CreateGroup',
    'CIS_TCGateAgent.TCGateAgent.AgentSave',
    'CIS_TCGateAgent.TCGateAgent.CGateAdd',
    'CIS_TCGateAgent.TCGateAgent.CommandDBAdd',
    'CIS_TCGateAgent.TCGateAgent.UpdateTag',
    'CIS_TCGateAgent.TCGateAgent.UpdateCGateValue',
    'CIS_TCGateAgent.TCGateAgent.CommandDBSet',
    'CIS_TcgcDBAdd.TcgcDBAdd.GenerateCommandText',
    'CIS_TcgcDBSet.TcgcDBSet.GenerateCommandText',
    'CIS_Strings.TagStringToCgateString',
)
SCAN_PREFIXES = (
    'CIS_TfrmThermostatCoolingGroups.TfrmCoolingGroups.',
    'CIS_TfrmThermostatHeatingGroups.TfrmHeatingGroups.',
    'CIS_TfrmThermostatDamperGroups.TfrmDamperGroups.',
    'CIS_TcdThermostatPlant.TcdThermostatPlant.',
)
HANDLER_FIELDS = (0x4e0, 0x4e4, 0x4e8, 0x4ec, 0x508, 0x50c, 0x530,
                  0x534, 0x540, 0x544, 0x560, 0x564, 0x519, 0x51a)
OPTIONAL_EVENTS = ('OnBeforeChange', 'OnChange', 'OnCanChangeElement',
                   'OnGetButtonEnabled', 'OnBeforeButtonAddClick', 'OnAfterButtonAddClick')
G = 'CIS_TFlashCxGroupComboBox.TFlashCxGroupComboBox.'
D = 'CIS_TfrmGroupAssign.TfrmGroupAssign.'
M = 'CIS_TCommonCBus.TCBusGroupManager.'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def inspect(exe: Path, map_path: Path) -> dict:
    raw, mapping = exe.read_bytes(), map_path.read_bytes()
    if (sha(raw), sha(mapping)) != (EXE_SHA256, MAP_SHA256):
        raise ValueError('Pinned original EXE/MAP hashes differ')
    image, checks, methods = _Image(raw, mapping), {}, {}
    walker = _Walker(image)
    scan_names = sorted(name for name in image.by_name if name.startswith(SCAN_PREFIXES))
    for name in dict.fromkeys((*METHODS, *WIRE_METHODS, *scan_names)):
        rows, _tables, digest = walker.listing(name)
        start = image.by_name[name]
        methods[name] = {'address': hex(start), 'end': hex(next(a for a in image.starts if a > start)),
                         'sha256': digest, 'rows': rows}
    def rows(name):
        return methods[name]['rows']
    def calls(name):
        return [note for _a, m, _op, note in rows(name) if m == 'call' and note]
    def has(name, mnemonic, operand):
        return any((m, op) == (mnemonic, operand) for _a, m, op, _n in rows(name))
    for address, expected in CHECKPOINTS.items():
        actual = {hex(a): (m, op) for a, m, op, _n in rows(expected['method'])}
        checks[address] = actual.get(address) == (expected['mnemonic'], expected['operand'])

    # Published-property records identify handler slots; a field-only store scan
    # is deliberately syntactic, with DFM absence and fresh construction separate.
    properties = {}
    for class_name, expected_properties in PUBLISHED_PROPERTIES.items():
        properties[class_name] = {}
        for name, expected in expected_properties.items():
            start = int(expected['address'], 16)
            header = image.pe.get_data(start-image.base, 27)
            length = header[26]
            record = image.pe.get_data(start-image.base, 27+length)
            actual_name = record[27:].decode('ascii')
            get, set_ = struct.unpack_from('<II', record, 4)
            default = struct.unpack_from('<I', record, 20)[0]
            actual = {'address': hex(start), 'get': hex(get), 'set': hex(set_), 'default': default}
            checks[class_name+'.'+name] = actual_name == name and actual == expected
            properties[class_name][name] = {**actual, 'bytes': len(record), 'sha256': sha(record)}
    writes = []
    for name in scan_names:
        for at, mnemonic, operand, _note in rows(name):
            if mnemonic not in ('mov', 'xor', 'and', 'or', 'add', 'sub', 'inc', 'dec'):
                continue
            destination = operand.split(', ', 1)[0]
            if any(re.search(r'\+ '+hex(field)+r'\]', destination) for field in HANDLER_FIELDS):
                writes.append({'method': name, 'address': hex(at), 'destination': destination})
    checks['all_67_thermostat_panel_methods_scanned'] = len(scan_names) == 67
    checks['no_direct_optional_handler_or_address_limit_writes'] = not writes
    checks['fresh_instance_zero_fill'] = any('stosd' in m for _a, m, _o, _n in rows('System.TObject.InitInstance'))
    checks['constructor_action_buttons_add_edit'] = image.pe.get_data(0xbbdcdc-image.base, 1) == b'\x03'
    checks['inherited_add_virtual_empty'] = not calls(
        'CIS_TFlashCxActionComboBox.TCustomFlashCxActionComboBox.DoButtonAddClick')

    resources, controls = {}, {}
    for resource in ('TFRMGROUPASSIGN', 'TFRMCOOLINGGROUPS', 'TFRMHEATINGGROUPS',
                     'TFRMDAMPERGROUPS', 'TFRMTHERMOSTATPLANT'):
        resource_raw, all_controls = dfm_properties(image, resource)
        resources[resource] = {'sha256': sha(resource_raw), 'bytes': len(resource_raw)}
        if resource == 'TFRMGROUPASSIGN':
            controls[resource] = {name: {key: c['properties'][key] for key in
                ('MaxLength', 'ModalResult', 'OnExecute', 'OnUpdate', 'OnChange') if key in c['properties']}
                for name, c in all_controls.items() if name in ('edtGroupName', 'btnCancel', 'actOK', 'cmbGroupAddress')}
            checks['group_name_unicode_edit_maximum32'] = (
                all_controls['edtGroupName']['class'] == 'TEdit'
                and all_controls['edtGroupName']['properties']['MaxLength'] == 32)
            checks['cancel_modal_result2'] = all_controls['btnCancel']['properties']['ModalResult'] == 2
            checks['ok_execute_update_bindings'] = all_controls['actOK']['properties'].get('OnExecute') == 'actOKExecute' and all_controls['actOK']['properties'].get('OnUpdate') == 'actOKUpdate'
        else:
            combos = {n: c for n, c in all_controls.items() if c['class'] == 'TFlashCxGroupComboBox'}
            controls[resource] = {name: {k: v for k, v in c['properties'].items() if k in (
                *OPTIONAL_EVENTS, 'Properties.OnChange', 'FlashController.UpdateMode',
                'AllowIfControllerInactive', 'ActionButtons', 'MinAddress', 'MaxAddress')}
                for name, c in combos.items()}
            checks[resource+'.group_combo_count'] = len(combos) == {
                'TFRMCOOLINGGROUPS': 7, 'TFRMHEATINGGROUPS': 7,
                'TFRMDAMPERGROUPS': 4, 'TFRMTHERMOSTATPLANT': 5}[resource]
            for name, c in combos.items():
                checks[resource+'.'+name+'.no_custom_handlers'] = not any(k in c['properties'] for k in OPTIONAL_EVENTS)
                checks[resource+'.'+name+'.no_address_limit_override'] = not any(k in c['properties'] for k in ('MinAddress', 'MaxAddress'))
                checks[resource+'.'+name+'.default_action_buttons'] = 'ActionButtons' not in c['properties']
    dispatch = dynamic_methods(walker, 'CIS_TFlashCxComboBox..TFlashCxComboBox')
    checks['queued_change_dispatch'] = dispatch[0x426] == image.by_name['CIS_TFlashCxComboBox.TFlashCxComboBox.HandleComboChange']

    checks['numeric_first_free_starts_zero'] = has(M+'GetNextAvailableAddress', 'xor', 'eax, eax')
    checks['numeric_first_free_capacity'] = has(M+'GetNextAvailableAddress', 'cmp', 'eax, 0x100')
    checks['numeric_first_free_address_lookup'] = M+'IndexOfGroupByAddress' in calls(M+'GetNextAvailableAddress')
    checks['numeric_first_free_bound'] = M+'GetMaximumPossibleAddress' in calls(M+'GetNextAvailableAddress')
    checks['maximum254_when_reserved'] = has(M+'GetMaximumPossibleAddress', 'mov', 'dword ptr [ebp - 8], 0xfe')
    checks['application_reserves255'] = has('CIS_TCommonCBus.TCBUSApplication.GetHasReservedGroupAddress255', 'mov', 'byte ptr [ebp - 5], 1')
    checks['bound_group_creation_kind'] = has(G+'DoButtonAddClick', 'mov', 'eax, dword ptr [0xf23cd4]')
    checks['active_flag_and_not_loading'] = (has('CIS_Handles.TFlashExpressionController.GetActive', 'cmp', 'byte ptr [eax + 4], 0')
        and has('CIS_Handles.TFlashExpressionController.GetActive', 'test', 'byte ptr [eax + 0x1c], 8'))
    checks['app_add_capability_gate'] = 'CIS_TCommonCBus.TCBUSApplication.GetCanAddGroups' in calls(G+'UpdateEnableState')
    checks['ok_connected_workspace_gate'] = calls(D+'IsSiteOpen')[-1] == 'CIS_TCGateCommunicator.TCGateCommunicator.GetConnected'
    checks['cancel_initialization_has_no_direct_project_tag_read'] = not any('TProject' in n or 'TCBusNetwork.Project' in n
        for n in calls(D+'SetValues')+calls(G+'DoButtonAddClick'))
    checks['project_inherits_tag_attribute'] = calls('CIS_TCommonCBus.TProject.InternalCreate')[0] == 'CIS_TCBusObject.TCGateObject.InternalCreate'
    checks['tag_attribute_name'] = image.literal(0xf47830) == 'TagName'
    checks['group_assignment_seed_format'] = image.literal(0xbc5c7c) == ' %d'
    checks['address_change_name_separator'] = image.literal(0xbc339c) == ' '
    checks['duplicate_uses_ascii_uppercase'] = calls(M+'GroupByTagNameExclude').count('SysUtils.UpperCase') == 2
    default_names = {'48..95': image.resource(0xf210dc),
                     '203': image.resource(walker.dword(0x13c2c88))}
    checks['default_group_name_literals'] = default_names == {'48..95': 'Group', '203': 'Enable Network Variable'}

    agent = 'CIS_TCGateAgent.TCGateAgent.'
    group_agent = 'CIS_TCBusGroupCGateAgent.TCBusGroupCGateAgent.'
    create_calls = calls(group_agent+'CreateGroup')
    checks['wire_group_create_then_address'] = create_calls.index(agent+'CGateAdd') < create_calls.index(agent+'UpdateCGateValue')
    checks['wire_group_then_generic_tag_save'] = calls(group_agent+'AgentSave').index(group_agent+'CreateGroup') < calls(group_agent+'AgentSave').index(agent+'AgentSave')
    checks['wire_generic_tag_update'] = agent+'UpdateTag' in calls(agent+'AgentSave')
    checks['wire_tag_update_oid_path'] = has(agent+'UpdateCGateValue', 'call', '0x7ec4e8') and image.literal(0xcac610) == '!'
    checks['wire_tag_field_exact'] = image.literal(0xcac688) == 'TagName'
    checks['wire_group_address_fields'] = (image.literal(0x1210fe8), image.literal(0x1211000)) == ('Group', 'Address')
    checks['wire_group_project_save_verbs'] = (image.literal(0x1210e2c), image.literal(0x1210eac)) == ('GroupSave', 'ProjectSave')
    checks['wire_add_is_dbadd_not_dbaddsafe'] = image.literal(0xcab9b4) == 'DBAdd '
    checks['wire_dbset_exact_prefix'] = image.literal(0xcab26c) == 'dbset '
    checks['wire_dbset_escapes_tag'] = 'CIS_Strings.TagStringToCgateString' in calls('CIS_TcgcDBSet.TcgcDBSet.GenerateCommandText')
    escape_bitmap = image.pe.get_data(0x7b8ec8-image.base, 32)
    escape_code_units = [n for n in range(256) if escape_bitmap[n//8] & (1 << (n % 8))]
    checks['wire_escape_quote_backslash_only'] = escape_code_units == [34, 92]
    checks['wire_quote_slash_double_space_literals'] = tuple(image.literal(a) for a in (0x7b8ef4, 0x7b8f04, 0x7b8f18)) == ('\\', '  ', '"')
    checks['wire_unicode_code_unit_iteration'] = has('CIS_Strings.TagStringToCgateString', 'cmp', 'word ptr [eax + edx*2 - 2], 0x100')
    checks['wire_only_ascii_space_second_pass'] = has('CIS_Strings.TagStringToCgateString', 'cmp', 'word ptr [eax + edx*2 - 2], 0x20')

    # Source helpers are UTF-16 based. These literal vectors document the
    # projection boundary; they are not calls into an original instruction.
    name_rules = {
        'maximum_utf16_code_units_before_trim': 32,
        'trim_code_units_inclusive': [0, 32],
        'uppercase_transform': {'from_inclusive': [97, 122], 'xor': 32},
        'project_tag_comparison': 'exact UTF-16 string equality after Trim; accept-only dependency',
        'duplicate_name_comparison': 'ASCII-only UpperCase on proposed trimmed name and each existing TagName',
        'distinct_examples': [['é', 'É'], ['straße', 'STRASSE'], ['\u00a0name\u00a0', 'name']],
        'utf16_length_examples': [{'text': '😀'*16, 'units': 32}, {'text': '😀'*17, 'units': 34}],
        'other_reserved_names': 'No independent reserved label test; address255 is reserved, and existing labels can collide.',
    }
    if not all(checks.values()):
        raise ValueError('Output Add source checkpoints differ: '+', '.join(k for k, ok in checks.items() if not ok))
    if (sha(exe.read_bytes()), sha(map_path.read_bytes())) != (EXE_SHA256, MAP_SHA256):
        raise ValueError('Original inputs changed during static inspection')
    return {
        'format': 'cbus-thermostat-output-add-static-v1',
        'original_exe_sha256': EXE_SHA256, 'original_map_sha256': MAP_SHA256,
        'original_executed': False, 'native_vendor_executed': False, 'physical_io': False,
        'checks': {k: True for k in sorted(checks)},
        'method_spans': {n: {k: v for k, v in item.items() if k != 'rows'} for n, item in sorted(methods.items())},
        'handler_scan': {'method_names': scan_names, 'field_offsets': [hex(f) for f in HANDLER_FIELDS],
                         'direct_writes': writes, 'scope': 'syntactic direct writes, composed with fresh zero-fill and DFM absence'},
        'resources': resources, 'dialog_and_output_controls': controls,
        'published_properties': properties, 'queued_change_message': {'id': '0x426', 'target': hex(dispatch[0x426])},
        'default_name_nouns': default_names, 'name_rules': name_rules,
        'original_wire_projection': {
            'commands': ['DBAdd parent-application-OID Group', 'dbset new-group-OID/Address address',
                         'dbset new-group-OID/TagName encoded-name', 'ProjectSave'],
            'tag_encoding': {'escape_code_units': escape_code_units, 'escape_character': '\\',
                'conditional_second_pass': 'if escaped string contains two consecutive ASCII spaces, prefix every ASCII space with backslash',
                'always_wrap': 'double quotes', 'other_unicode': 'unchanged UTF-16 code units, including NBSP'},
            'boundary': 'static original command generation; owned adapter may compose graph staging and one owner save, with fresh identity and exact-name verification',
        },
        'contract': {
            'history': 'complete ordinary load then ordered select-output-group/add-output-group operations',
            'accepted_inputs': ['op', 'parameter', 'outcome=accept', 'optional integer address0..254', 'optional final shown name'],
            'cancelled_inputs': ['op', 'parameter', 'outcome=cancel'],
            'input_order': 'initial first-free address/name; optional address selection with default-name rewrite; optional final name edit',
            'initial_capacity': 'first free numeric0..254; no capacity refuses before modal, including direct cancel',
            'accept_order': ['OK validation', 'provisional Address/TagName assignment', 'manager Add', 'Group save', 'bound reference assignment', 'list refresh', 'queued change'],
            'cancel_order': ['nonaccept modal result', 'free provisional group'],
            'address_change_rewrite': 'empty current name or ASCII-insensitive prefix equal to catalogue noun rewrites noun + space + selected decimal address',
            'source_selection': 'clicked combo bound reference; no thermostat Add/veto/custom OnChange handler',
            'control_gate': 'existing role gate plus prepared active controller, bound non255 application and GetCanAddGroups',
            'ok_gate': 'project installation workspace communicator connected; no physical network-open prerequisite',
            'storage_projection': 'complete owned preflight, ordered graph materialization and one owning settings save; does not emulate original partial failure prefixes',
            'bounds': ['direct cancel only; no cancelled text-entry histories', 'integer address outcome; no raw text coercion',
                       'native command/XML name admission is an additional product boundary',
                       'no application migration, output Edit/Delete, zone history, whole original GUI or physical acceptance'],
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--map', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(inspect(args.exe, args.map), indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
