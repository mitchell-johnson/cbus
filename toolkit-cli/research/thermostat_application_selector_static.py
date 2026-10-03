"""Static thermostat application-selector and rebound-list source evidence.

Reads pinned PE/MAP bytes only. No original instruction or Windows execution.
The callback receipt does not turn an incomplete mouse/focus history into an
application-migration API; explicit boundaries remain in the returned contract.
"""
from __future__ import annotations

import argparse
import bisect
import hashlib
import json
from pathlib import Path
import re
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from topology_generator_static import _Image, EXE_SHA256, MAP_SHA256
from thermostat_post_load_static import _Walker
from thermostat_quick_zone_initialization_static import dfm_properties
from thermostat_quick_zone_gui_binding_static import dynamic_methods

METHODS = ('CIS_Handles.TFlashElementController.SetAsElement',
 'CIS_Handles.TFlashExpressionController.Changed',
 'CIS_Handles.TFlashExpressionController.Create',
 'CIS_Handles.TFlashExpressionController.DoFlashHandleChanged',
 'CIS_Handles.TFlashExpressionController.ExpressionElementChanged',
 'CIS_Handles.TFlashExpressionController.FlashHandleListItemIndexChanged',
 'CIS_Handles.TFlashExpressionController.SetActive',
 'CIS_Handles.TFlashExpressionController.UpdateCachedValue',
 'CIS_Handles.TFlashObjectLink.SetFlashObject',
 'CIS_Handles.TFlashTrackedHandle.GetCurrentElement',
 'CIS_Handles.TFlashTrackedHandle.GetItems',
 'CIS_Handles.TFlashTrackedHandle.SetItemIndex',
 'CIS_Handles.TFlashTrackedHandle.Update',
 'CIS_IRefreshFrameSupport.RefreshTabs',
 'CIS_TCommonCBus.TCBUSApplication.GetCanAddGroups',
 'CIS_TFlashCxActionComboBox.TCustomFlashCxActionComboBox.Create',
 'CIS_TFlashCxActionComboBox.TCustomFlashCxActionComboBox.HandleButtonAddClick',
 'CIS_TFlashCxActionComboBox.TCustomFlashCxActionComboBox.HandleButtonClick',
 'CIS_TFlashCxActionComboBox.TCustomFlashCxActionComboBox.HandleButtonEditClick',
 'CIS_TFlashCxApplicationComboBox.TFlashCxApplicationComboBox.AllowChangingToNil',
 'CIS_TFlashCxApplicationComboBox.TFlashCxApplicationComboBox.Create',
 'CIS_TFlashCxApplicationComboBox.TFlashCxApplicationComboBox.IsItemValid',
 'CIS_TFlashCxApplicationComboBox.TFlashCxApplicationComboBox.RenderedValueChange',
 'CIS_TFlashCxApplicationComboBox.TFlashCxApplicationComboBox.UpdateEnableState',
 'CIS_TFlashCxComboBox.TFlashCxComboBox.AllowChangingToNil',
 'CIS_TFlashCxComboBox.TFlashCxComboBox.ControllerExpressionChanged',
 'CIS_TFlashCxComboBox.TFlashCxComboBox.Create',
 'CIS_TFlashCxComboBox.TFlashCxComboBox.DoCloseUp',
 'CIS_TFlashCxComboBox.TFlashCxComboBox.DoEditKeyPress',
 'CIS_TFlashCxComboBox.TFlashCxComboBox.DoEnter',
 'CIS_TFlashCxComboBox.TFlashCxComboBox.DoExit',
 'CIS_TFlashCxComboBox.TFlashCxComboBox.DoIndexChange',
 'CIS_TFlashCxComboBox.TFlashCxComboBox.DoInitPopup',
 'CIS_TFlashCxComboBox.TFlashCxComboBox.DoOnCanChangeElement',
 'CIS_TFlashCxComboBox.TFlashCxComboBox.FlashHandleListChanged',
 'CIS_TFlashCxComboBox.TFlashCxComboBox.FlashHandleListRootChanged',
 'CIS_TFlashCxComboBox.TFlashCxComboBox.HandleComboChange',
 'CIS_TFlashCxComboBox.TFlashCxComboBox.IsItemValid',
 'CIS_TFlashCxComboBox.TFlashCxComboBox.PopulateList',
 'CIS_TFlashCxComboBox.TFlashCxComboBox.RenderDisplay',
 'CIS_TFlashCxComboBox.TFlashCxComboBox.RenderedValueChange',
 'CIS_TFlashCxComboBox.TFlashCxComboBox.UpdateEnableState',
 'CIS_TFlashCxGroupComboBox.TFlashCxGroupComboBox.ComboGetGroup',
 'CIS_TFlashCxGroupComboBox.TFlashCxGroupComboBox.DoButtonAddClick',
 'CIS_TFlashCxGroupComboBox.TFlashCxGroupComboBox.DoButtonEditClick',
 'CIS_TFlashCxGroupComboBox.TFlashCxGroupComboBox.GetCBusApplication',
 'CIS_TFlashCxGroupComboBox.TFlashCxGroupComboBox.UpdateEnableState',
 'CIS_TFlashObjectExpressionLink.TFlashObjectExpressionLink.SetActive',
 'CIS_TFlashObjectExpressionLink.TFlashObjectExpressionLink.SetExpression',
 'CIS_TFlashObjectExpressionLink.TFlashObjectExpressionLink.SetFlashObject',
 'CIS_TStandardCBusApplications.CIS_TStandardCBusApplications',
 'CIS_TStandardCBusApplications.TStandardCBusApplication.Create',
 'CIS_TStandardCBusApplications.TStandardCBusApplication.SetAllowGroups',
 'CIS_TStandardCBusApplications.TStandardCBusApplications.GetStandardCBusApplication',
 'CIS_TStandardCBusApplications.TStandardCBusApplications.RegisterApplication',
 'CIS_TThermostat.TThermostat.AllowApplication1',
 'CIS_TcdThermostatCBus.TcdThermostatCBus.CreateSubForm',
 'CIS_TcdThermostatPlant.TcdThermostatPlant.UpdateApplicationLink',
 'CIS_TcdThermostatZoneManagement.TcdThermostatZoneManagement.UpdateApplicationLink',
 'CIS_TddCBusUnit.TddCBusUnit.AllowApplication1',
 'CIS_TddCBusUnit.TddCBusUnit.AllowApplication1Address',
 'CIS_TddCBusUnit.TddCBusUnit.HandleApplication1ComboIncludeItem',
 'CIS_TddCBusUnit.TddCBusUnit.SetupForm',
 'CIS_TddThermostat.TddThermostat.GetApplication1AddressCustomRangeEnd',
 'CIS_TddThermostat.TddThermostat.GetApplication1AddressCustomRangeStart',
 'CIS_TddThermostat.TddThermostat.HandleLightingApplicationChange',
 'CIS_TddThermostat.TddThermostat.InitialiseSubForms',
 'CIS_TddThermostat.TddThermostat.UpdateApplicationLink',
 'CIS_TfrmGroupAssign.TfrmGroupAssign.actOKExecute',
 'CIS_TfrmThermostatCoolingGroups.TfrmCoolingGroups.cmbGroupChange',
 'CIS_TfrmThermostatDamperGroups.TfrmDamperGroups.cmbGroupChange',
 'CIS_TfrmThermostatHeatingGroups.TfrmHeatingGroups.cmbGroupChange',
 'CIS_TfrmUnitGlobalCBusStatus.TfrmUnitGlobalCBusStatus.Refresh',
 'CIS_TfrmUnitGlobalCBusStatus.TfrmUnitGlobalCBusStatus.SetCBusUnit',
 'CIS_TfrmUnitGlobalCBusStatus.TfrmUnitGlobalCBusStatus.chkClockGenEnableClick',
 'CIS_TfrmUnitIDBase.TfrmUnitIDBase.HandleAfterComboChange',
 'CIS_TfrmUnitIDBase.TfrmUnitIDBase.HandleApplication1ComboIncludeItem',
 'CIS_TfrmUnitIDBase.TfrmUnitIDBase.HandleApplicationChange',
 'CIS_TfrmUnitIDBase.TfrmUnitIDBase.SetupFlashComponents',
 'Controls.TControl.Click',
 'Controls.TWinControl.CMEnter',
 'Controls.TWinControl.SetFocus',
 'Controls.TWinControl.WMSetFocus',
 'Forms.RestoreFocusState',
 'Forms.SaveFocusState',
 'Forms.TCustomForm.FocusControl',
 'Forms.TCustomForm.SetActive',
 'Forms.TCustomForm.SetActiveControl',
 'Forms.TCustomForm.SetFocusedControl',
 'Forms.TCustomForm.SetWindowFocus',
 'Forms.TCustomForm.ShowModal',
 'Forms.TCustomForm.WMActivate',
 'System.TObject.InitInstance',
 'cxContainer.TcxContainer.MouseDown',
 'cxContainer.TcxContainer.MouseUp',
 'cxContainer.TcxContainer.RefreshContainer',
 'cxContainer.TcxContainer.SetFocus',
 'cxContainer.TcxContainer.WMSetFocus',
 'cxControls.TcxControl.CanFocusOnClick',
 'cxControls.TcxControl.CanFocusOnClick@0x8ef0f8',
 'cxControls.TcxControl.MouseDown',
 'cxDropDownEdit.TcxCustomDropDownEdit.DoRefreshContainer',
 'cxDropDownEdit.TcxCustomDropDownEdit.EditButtonClick',
 'cxDropDownEdit.TcxCustomDropDownEdit.MouseDown',
 'cxEdit.TcxCustomEdit.Click',
 'cxEdit.TcxCustomEdit.DoButtonClick',
 'cxEdit.TcxCustomEdit.DoChange',
 'cxEdit.TcxCustomEdit.DoEditValueChanged',
 'cxEdit.TcxCustomEdit.DoOnChange',
 'cxEdit.TcxCustomEdit.DoOnEditValueChanged',
 'cxEdit.TcxCustomEdit.DoRefreshContainer',
 'cxEdit.TcxCustomEdit.MouseDown',
 'cxEdit.TcxCustomEdit.SetEditValue',
 'cxEdit.TcxCustomEdit.SetInternalEditValue',
 'cxMaskEdit.TcxCustomMaskEdit.MouseDown',
 'cxTextEdit.TcxCustomTextEdit.ChangeHandler',
 'cxTextEdit.TcxCustomTextEdit.DoEditValueChanged',
 'cxTextEdit.TcxCustomTextEdit.DoRefreshContainer',
 'cxTextEdit.TcxCustomTextEdit.DoTextChanged',
 'cxTextEdit.TcxCustomTextEdit.SetItemIndex',
 'cxTextEdit.TcxCustomTextEdit.WMSetFocus')

CHECKPOINTS = {'0x1132fa8': {'method': 'CIS_TddThermostat.TddThermostat.HandleLightingApplicationChange',
               'mnemonic': 'mov',
               'operand': 'eax, dword ptr [ebp - 4]'},
 '0x117a88c': {'method': 'CIS_TfrmUnitGlobalCBusStatus.TfrmUnitGlobalCBusStatus.Refresh',
               'mnemonic': 'call',
               'operand': '0x117a7d4'},
 '0x60621e': {'method': 'System.TObject.InitInstance',
              'mnemonic': 'rep stosd',
              'operand': 'dword ptr es:[edi], eax'},
 '0x606224': {'method': 'System.TObject.InitInstance',
              'mnemonic': 'rep stosb',
              'operand': 'byte ptr es:[edi], al'},
 '0x71f0c2': {'method': 'Forms.TCustomForm.SetActiveControl', 'mnemonic': 'call', 'operand': '0x71f470'},
 '0x71f321': {'method': 'Forms.TCustomForm.SetFocusedControl',
              'mnemonic': 'cmp',
              'operand': 'eax, dword ptr [ebp - 4]'},
 '0x71f324': {'method': 'Forms.TCustomForm.SetFocusedControl', 'mnemonic': 'je', 'operand': '0x71f423'},
 '0x84edae': {'method': 'CIS_Handles.TFlashTrackedHandle.Update',
              'mnemonic': 'mov',
              'operand': 'dword ptr [edx + 0x4c], eax'},
 '0x84edbf': {'method': 'CIS_Handles.TFlashTrackedHandle.Update',
              'mnemonic': 'mov',
              'operand': 'dword ptr [eax + 0x4c], 0xffffffff'},
 '0x84ee63': {'method': 'CIS_Handles.TFlashTrackedHandle.Update',
              'mnemonic': 'mov',
              'operand': 'dword ptr [eax + 0x3c], edx'},
 '0x85af20': {'method': 'CIS_TStandardCBusApplications.TStandardCBusApplication.Create',
              'mnemonic': 'mov',
              'operand': 'byte ptr [eax + 0x3a], 1'},
 '0x8ee411': {'method': 'cxControls.TcxControl.MouseDown',
              'mnemonic': 'call',
              'operand': 'dword ptr [edx + 0xe8]'},
 '0xbbbe41': {'method': 'CIS_TFlashCxComboBox.TFlashCxComboBox.DoEnter',
              'mnemonic': 'mov',
              'operand': 'dword ptr [edx + 0x504], eax'},
 '0xbbbe52': {'method': 'CIS_TFlashCxComboBox.TFlashCxComboBox.DoEnter',
              'mnemonic': 'call',
              'operand': '0xbbc2f8'},
 '0xbbbed1': {'method': 'CIS_TFlashCxComboBox.TFlashCxComboBox.DoEditKeyPress',
              'mnemonic': 'mov',
              'operand': 'dword ptr [edx + 0x504], eax'},
 '0xbbbf35': {'method': 'CIS_TFlashCxComboBox.TFlashCxComboBox.DoIndexChange',
              'mnemonic': 'mov',
              'operand': 'eax, dword ptr [eax + 0x504]'},
 '0xbbbf75': {'method': 'CIS_TFlashCxComboBox.TFlashCxComboBox.DoIndexChange',
              'mnemonic': 'call',
              'operand': 'dword ptr [ecx + 0x20]'},
 '0xbbbfc1': {'method': 'CIS_TFlashCxComboBox.TFlashCxComboBox.DoIndexChange',
              'mnemonic': 'call',
              'operand': '0x84f528'},
 '0xbbc38b': {'method': 'CIS_TFlashCxComboBox.TFlashCxComboBox.PopulateList',
              'mnemonic': 'call',
              'operand': 'dword ptr [ecx + 0x49c]'},
 '0xbbc4b9': {'method': 'CIS_TFlashCxComboBox.TFlashCxComboBox.PopulateList',
              'mnemonic': 'call',
              'operand': 'dword ptr [ebx + 0x4d8]'},
 '0xbbc4e0': {'method': 'CIS_TFlashCxComboBox.TFlashCxComboBox.PopulateList',
              'mnemonic': 'call',
              'operand': 'dword ptr [ecx + 0x50c]'},
 '0xbbc55e': {'method': 'CIS_TFlashCxComboBox.TFlashCxComboBox.PopulateList',
              'mnemonic': 'cmp',
              'operand': 'ebx, eax'},
 '0xbbc57c': {'method': 'CIS_TFlashCxComboBox.TFlashCxComboBox.PopulateList',
              'mnemonic': 'call',
              'operand': 'dword ptr [ecx + 0x49c]'},
 '0xbbc5bc': {'method': 'CIS_TFlashCxComboBox.TFlashCxComboBox.PopulateList',
              'mnemonic': 'call',
              'operand': '0x6f62d8'},
 '0xbbc5da': {'method': 'CIS_TFlashCxComboBox.TFlashCxComboBox.PopulateList',
              'mnemonic': 'call',
              'operand': '0x6f62d8'},
 '0xbbc7a0': {'method': 'CIS_TFlashCxComboBox.TFlashCxComboBox.RenderedValueChange',
              'mnemonic': 'call',
              'operand': '0xbbc2f8'},
 '0xbbc7b0': {'method': 'CIS_TFlashCxComboBox.TFlashCxComboBox.RenderedValueChange',
              'mnemonic': 'call',
              'operand': '0xbbc648'},
 '0xbbefde': {'method': 'CIS_TFlashCxApplicationComboBox.TFlashCxApplicationComboBox.Create',
              'mnemonic': 'mov',
              'operand': 'byte ptr [eax + 0x581], 0'},
 '0xbbefe8': {'method': 'CIS_TFlashCxApplicationComboBox.TFlashCxApplicationComboBox.Create',
              'mnemonic': 'mov',
              'operand': 'byte ptr [eax + 0x582], 1'},
 '0xbc0053': {'method': 'CIS_TFlashCxApplicationComboBox.TFlashCxApplicationComboBox.IsItemValid',
              'mnemonic': 'call',
              'operand': '0xf26108'},
 '0xbc005f': {'method': 'CIS_TFlashCxApplicationComboBox.TFlashCxApplicationComboBox.IsItemValid',
              'mnemonic': 'cmp',
              'operand': 'byte ptr [eax + 0x582], 0'},
 '0xbc0070': {'method': 'CIS_TFlashCxApplicationComboBox.TFlashCxApplicationComboBox.IsItemValid',
              'mnemonic': 'cmp',
              'operand': 'eax, 0xff'},
 '0xbc007a': {'method': 'CIS_TFlashCxApplicationComboBox.TFlashCxApplicationComboBox.IsItemValid',
              'mnemonic': 'cmp',
              'operand': 'byte ptr [eax + 0x581], 0'},
 '0xbc0083': {'method': 'CIS_TFlashCxApplicationComboBox.TFlashCxApplicationComboBox.IsItemValid',
              'mnemonic': 'mov',
              'operand': 'byte ptr [ebp - 9], 1'},
 '0xbc5b83': {'method': 'CIS_TFlashCxGroupComboBox.TFlashCxGroupComboBox.DoButtonAddClick',
              'mnemonic': 'call',
              'operand': 'dword ptr [ecx + 0xa8]'},
 '0xbc5b8c': {'method': 'CIS_TFlashCxGroupComboBox.TFlashCxGroupComboBox.DoButtonAddClick',
              'mnemonic': 'call',
              'operand': '0xbbc2f8'},
 '0xbc5b94': {'method': 'CIS_TFlashCxGroupComboBox.TFlashCxGroupComboBox.DoButtonAddClick',
              'mnemonic': 'call',
              'operand': '0xbbbee8'},
 '0xbc5ec7': {'method': 'CIS_TFlashCxGroupComboBox.TFlashCxGroupComboBox.DoButtonEditClick',
              'mnemonic': 'call',
              'operand': '0xbbc2f8'},
 '0xbc5ecf': {'method': 'CIS_TFlashCxGroupComboBox.TFlashCxGroupComboBox.DoButtonEditClick',
              'mnemonic': 'call',
              'operand': '0xbbbee8'},
 '0xbc5f83': {'method': 'CIS_TFlashCxGroupComboBox.TFlashCxGroupComboBox.GetCBusApplication',
              'mnemonic': 'call',
              'operand': '0xf27efc'},
 '0xf26132': {'method': 'CIS_TCommonCBus.TCBUSApplication.GetCanAddGroups',
              'mnemonic': 'cmp',
              'operand': 'eax, 0xff'},
 '0xf26137': {'method': 'CIS_TCommonCBus.TCBUSApplication.GetCanAddGroups',
              'mnemonic': 'je',
              'operand': '0xf26162'},
 '0xf26139': {'method': 'CIS_TCommonCBus.TCBUSApplication.GetCanAddGroups',
              'mnemonic': 'cmp',
              'operand': 'dword ptr [ebp - 0xc], 0'},
 '0xf2613d': {'method': 'CIS_TCommonCBus.TCBUSApplication.GetCanAddGroups',
              'mnemonic': 'je',
              'operand': '0xf26166'},
 '0xf26148': {'method': 'CIS_TCommonCBus.TCBUSApplication.GetCanAddGroups',
              'mnemonic': 'cmp',
              'operand': 'byte ptr [eax + 0x3a], 0'},
 '0xf2614c': {'method': 'CIS_TCommonCBus.TCBUSApplication.GetCanAddGroups',
              'mnemonic': 'jne',
              'operand': '0xf26166'},
 '0xf26156': {'method': 'CIS_TCommonCBus.TCBUSApplication.GetCanAddGroups',
              'mnemonic': 'sub',
              'operand': 'eax, 0x19'},
 '0xf26159': {'method': 'CIS_TCommonCBus.TCBUSApplication.GetCanAddGroups',
              'mnemonic': 'je',
              'operand': '0xf26166'},
 '0xf2615b': {'method': 'CIS_TCommonCBus.TCBUSApplication.GetCanAddGroups',
              'mnemonic': 'sub',
              'operand': 'eax, 0x93'},
 '0xf26160': {'method': 'CIS_TCommonCBus.TCBUSApplication.GetCanAddGroups',
              'mnemonic': 'je',
              'operand': '0xf26166'},
 '0xfeb44c': {'method': 'CIS_TThermostat.TThermostat.AllowApplication1',
              'mnemonic': 'cmp',
              'operand': 'dword ptr [ebp - 8], 0x80'},
 '0xfeb453': {'method': 'CIS_TThermostat.TThermostat.AllowApplication1',
              'mnemonic': 'setle',
              'operand': 'byte ptr [ebp - 9]'}}

RESOURCES = ('TFRMCOOLINGGROUPS',
 'TFRMDAMPERGROUPS',
 'TFRMHEATINGGROUPS',
 'TFRMTHERMOSTAT',
 'TFRMTHERMOSTATBACKLIGHT',
 'TFRMTHERMOSTATCBUS',
 'TFRMTHERMOSTATEVAPCONFORTCONTROL',
 'TFRMTHERMOSTATEXTERNALRELAYS',
 'TFRMTHERMOSTATGROUPS',
 'TFRMTHERMOSTATLOADTEMPLATES',
 'TFRMTHERMOSTATPIDFACTORS',
 'TFRMTHERMOSTATPLANT',
 'TFRMTHERMOSTATSCHEDULING',
 'TFRMTHERMOSTATTEMPCONTROL',
 'TFRMTHERMOSTATTEMPLATES',
 'TFRMTHERMOSTATTEMPOFFSET',
 'TFRMTHERMOSTATUI',
 'TFRMTHERMOSTATZONEMANAGEMENT',
 'TFRMUNITGLOBALCBUSSTATUS',
 'TFRMUNITIDAREA',
 'TFRMUNITIDAREAAPP2',
 'TFRMUNITIDAREAFW2',
 'TFRMUNITIDAREAFW2APP2',
 'TFRMUNITIDBASE',
 'TFRMUNITIDENTIFICATION')

EXPECTED_CALLERS = {'DoEnter': [],
 'DoIndexChange': [{'address': '0xbbbe22',
                    'sha256': '5214b88aeab33a9d8048f390994863d573fd0591757175426396c9556b7fd99f',
                    'start': '0xbbbe10',
                    'symbol': 'CIS_TFlashCxComboBox.TFlashCxComboBox.DoCloseUp'},
                   {'address': '0xbbc06b',
                    'sha256': '4e53feed8dffea6b7c8f19ca00a70dafcd7ad022c94e666beedf950fd67af2f7',
                    'start': '0xbbc010',
                    'symbol': 'CIS_TFlashCxComboBox.TFlashCxComboBox.DoMouseWheel'},
                   {'address': '0xbbc1eb',
                    'sha256': 'c42456240467f508561f5d96f5d54e8cf1a64089e0ebe5b5dff44ca5e8375459',
                    'start': '0xbbc1c0',
                    'symbol': 'CIS_TFlashCxComboBox.TFlashCxComboBox.KeyDown'},
                   {'address': '0xbbc280',
                    'sha256': 'c6d80974b8e4a6fcdd3de2ae74d59669d86314ef5dbd516f1654a21deb3edd30',
                    'start': '0xbbc1f4',
                    'symbol': 'CIS_TFlashCxComboBox.TFlashCxComboBox.KeyPress'},
                   {'address': '0xbbfc6a',
                    'sha256': 'c1c71a34381a5bd9c06881339cc8b018ee8009b61a2eb716313bc1cdc45bcaaa',
                    'start': '0xbbfa40',
                    'symbol': 'CIS_TFlashCxApplicationComboBox.TFlashCxApplicationComboBox.DoButtonAddClick'},
                   {'address': '0xbbfe8d',
                    'sha256': 'e9e98707e4bafd9286e2a4b214cc10b55a38646ddbf5612890c4c388fac0d089',
                    'start': '0xbbfde0',
                    'symbol': 'CIS_TFlashCxApplicationComboBox.TFlashCxApplicationComboBox.DoButtonEditClick'},
                   {'address': '0xbc5b94',
                    'sha256': 'd842ba913d134e130229eb168f48116f9e8b8f578993f5732749e88d491143e5',
                    'start': '0xbc58e8',
                    'symbol': 'CIS_TFlashCxGroupComboBox.TFlashCxGroupComboBox.DoButtonAddClick'},
                   {'address': '0xbc5ecf',
                    'sha256': 'ff886b850b655ebe967ebaec16f19449c0caf6cb29488730b4390c476160e86b',
                    'start': '0xbc5d90',
                    'symbol': 'CIS_TFlashCxGroupComboBox.TFlashCxGroupComboBox.DoButtonEditClick'},
                   {'address': '0xbc8ee6',
                    'sha256': 'fcb676c72c7de53f53e585aa46953c0cc5bad68c87866732be1cd44ec1c37946',
                    'start': '0xbc8c6c',
                    'symbol': 'CIS_TFlashCxLevelComboBox.TFlashCxLevelComboBox.DoButtonAddClick'},
                   {'address': '0xbc927b',
                    'sha256': '895b51ab10fe60908a815be13e06923f1585956eb4bd172047432dbb28ba46b2',
                    'start': '0xbc9128',
                    'symbol': 'CIS_TFlashCxLevelComboBox.TFlashCxLevelComboBox.DoButtonEditClick'}],
 'HandleButtonClick': [],
 'PopulateList': [{'address': '0xbbbe52',
                   'sha256': 'bdb65f8615741261670076d13858980ae4748017b54d0bb57b03ca77b8de687f',
                   'start': '0xbbbe2c',
                   'symbol': 'CIS_TFlashCxComboBox.TFlashCxComboBox.DoEnter'},
                  {'address': '0xbbc006',
                   'sha256': '8c8bcc66118270c9d29ba291f7d4e293a8722b70173502e9c2255b1169a1c61f',
                   'start': '0xbbbff4',
                   'symbol': 'CIS_TFlashCxComboBox.TFlashCxComboBox.DoInitPopup'},
                  {'address': '0xbbc039',
                   'sha256': '4e53feed8dffea6b7c8f19ca00a70dafcd7ad022c94e666beedf950fd67af2f7',
                   'start': '0xbbc010',
                   'symbol': 'CIS_TFlashCxComboBox.TFlashCxComboBox.DoMouseWheel'},
                  {'address': '0xbbc232',
                   'sha256': 'c6d80974b8e4a6fcdd3de2ae74d59669d86314ef5dbd516f1654a21deb3edd30',
                   'start': '0xbbc1f4',
                   'symbol': 'CIS_TFlashCxComboBox.TFlashCxComboBox.KeyPress'},
                  {'address': '0xbbc7a0',
                   'sha256': '0b4c731958a6111a7e9ddb939e799c9fb39616cfcca4adbcc5f474355b1fda96',
                   'start': '0xbbc754',
                   'symbol': 'CIS_TFlashCxComboBox.TFlashCxComboBox.RenderedValueChange'},
                  {'address': '0xbbfc62',
                   'sha256': 'c1c71a34381a5bd9c06881339cc8b018ee8009b61a2eb716313bc1cdc45bcaaa',
                   'start': '0xbbfa40',
                   'symbol': 'CIS_TFlashCxApplicationComboBox.TFlashCxApplicationComboBox.DoButtonAddClick'},
                  {'address': '0xbbfe85',
                   'sha256': 'e9e98707e4bafd9286e2a4b214cc10b55a38646ddbf5612890c4c388fac0d089',
                   'start': '0xbbfde0',
                   'symbol': 'CIS_TFlashCxApplicationComboBox.TFlashCxApplicationComboBox.DoButtonEditClick'},
                  {'address': '0xbc5b8c',
                   'sha256': 'd842ba913d134e130229eb168f48116f9e8b8f578993f5732749e88d491143e5',
                   'start': '0xbc58e8',
                   'symbol': 'CIS_TFlashCxGroupComboBox.TFlashCxGroupComboBox.DoButtonAddClick'},
                  {'address': '0xbc5ec7',
                   'sha256': 'ff886b850b655ebe967ebaec16f19449c0caf6cb29488730b4390c476160e86b',
                   'start': '0xbc5d90',
                   'symbol': 'CIS_TFlashCxGroupComboBox.TFlashCxGroupComboBox.DoButtonEditClick'},
                  {'address': '0xbc8ede',
                   'sha256': 'fcb676c72c7de53f53e585aa46953c0cc5bad68c87866732be1cd44ec1c37946',
                   'start': '0xbc8c6c',
                   'symbol': 'CIS_TFlashCxLevelComboBox.TFlashCxLevelComboBox.DoButtonAddClick'},
                  {'address': '0xbc9273',
                   'sha256': '895b51ab10fe60908a815be13e06923f1585956eb4bd172047432dbb28ba46b2',
                   'start': '0xbc9128',
                   'symbol': 'CIS_TFlashCxLevelComboBox.TFlashCxLevelComboBox.DoButtonEditClick'}]}

COMBO_PREFIXES = (
    'CIS_TFlashCxComboBox.TFlashCxComboBox.',
    'CIS_TFlashCxActionComboBox.TCustomFlashCxActionComboBox.',
    'CIS_TFlashCxGroupComboBox.TFlashCxGroupComboBox.',
    'CIS_TFlashCxApplicationComboBox.TFlashCxApplicationComboBox.',
)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def inspect(exe: Path, map_path: Path) -> dict:
    raw, mapping = exe.read_bytes(), map_path.read_bytes()
    if (sha(raw), sha(mapping)) != (EXE_SHA256, MAP_SHA256):
        raise ValueError('Pinned original EXE/MAP hashes differ')
    image, checks = _Image(raw, mapping), {}
    for name in METHODS:
        if '@0x' in name:
            base, address = name.rsplit('@', 1)
            address = int(address, 16)
            if base not in image.symbols[address]:
                raise ValueError('Exact overloaded MAP symbol missing: ' + name)
            image.by_name[name] = address
    walker = _Walker(image)
    scan_names = sorted(n for n in image.by_name if n.startswith(COMBO_PREFIXES))
    methods, listings = {}, {}

    def read(name):
        if name not in listings:
            rows, _tables, digest = walker.listing(name)
            start = image.by_name[name]
            listings[name] = rows
            methods[name] = {'address': hex(start),
                             'end': hex(next(a for a in image.starts if a > start)),
                             'sha256': digest}
        return listings[name]

    for name in dict.fromkeys((*METHODS, *scan_names)):
        read(name)
    for address, row in CHECKPOINTS.items():
        actual = {hex(a): (mn, op) for a, mn, op, _n in read(row['method'])}
        checks['instruction.' + address] = actual.get(address) == (row['mnemonic'], row['operand'])

    # Both filters run in order. GetCanAddGroups defaults true for an unknown
    # catalogue address; the only flagged-off address below 129 is explicitly
    # reenabled by the getter (25).
    app, false_flags, catalogue = None, [], {}
    last_name, previous = None, None
    for _a, mn, op, note in read('CIS_TStandardCBusApplications.CIS_TStandardCBusApplications'):
        match = re.fullmatch(r'edx, (0x[0-9a-f]+)', op)
        if mn == 'mov' and match:
            app = int(match[1], 16)
        if mn == 'call' and note == 'System.LoadResString':
            prior_mn, prior_op = previous
            direct = re.fullmatch(r'eax, (0x[0-9a-f]+)', prior_op)
            indirect = re.fullmatch(r'eax, dword ptr \[(0x[0-9a-f]+)\]', prior_op)
            if prior_mn != 'mov' or not (direct or indirect):
                raise ValueError('Unexpected catalogue resource load')
            address = int((direct or indirect)[1], 16)
            last_name = image.resource(address if direct else walker.dword(address))
        if note.endswith('.TStandardCBusApplications.RegisterApplication') and mn == 'call':
            catalogue[app] = last_name
        if (mn, op) == ('mov', 'byte ptr [eax + 0x3a], 0'):
            false_flags.append(app)
        previous = mn, op
    checks['catalogue.false_flags'] = sorted(false_flags) == [25, 172, 192, 205, 206, 208, 223, 224, 228, 255]
    checks['catalogue.indirect_titles'] = [catalogue[a] for a in (113, 114, 115, 116)] == ['Irrigation Control', 'Pool, Spa, Pond Control', 'HVAC Actuator 1', 'HVAC Actuator 2']
    checks['include.unrelated_unit_exceptions'] = [image.literal(a) for a in (0xecae70, 0xecae8c)] == ['DIMDD8', 'DIMDD4']

    classes = ['CIS_TThermostat..T' + n for n in ('PC_TSA', 'PC_TSA5', 'PC_TSB', 'PC_TSB5')]
    classes += ['CIS_TFlashCxApplicationComboBox..TFlashCxApplicationComboBox',
                'CIS_TFlashCxGroupComboBox..TFlashCxGroupComboBox',
                'CIS_TfrmUnitIDBase..TfrmUnitIDBase']
    bindings = {}
    for name in classes:
        vmt = walker.dword(image.by_name[name])
        offsets = ((0xb0, 0xb8, 0xf8) if name.startswith('CIS_TThermostat..') else
                   (() if 'TfrmUnitIDBase' in name else
                    (0xe8, 0x12c, 0x428, 0x468, 0x49c, 0x504, 0x508, 0x50c, 0x510)))
        slots = {hex(o): {'address': hex(vmt + o), 'target': hex(walker.dword(vmt + o)),
                          'symbol': walker.name(walker.dword(vmt + o))} for o in offsets}
        dynamic = {hex(k): {'target': hex(v), 'symbol': walker.name(v)}
                   for k, v in dynamic_methods(walker, name).items()
                   if k in (0xffec, 0x426, 0x486)}
        bindings[name] = {'vmt': hex(vmt), 'slots': slots, 'dynamic': dynamic}
        if name.startswith('CIS_TThermostat..'):
            checks[name + '.virtuals'] = [int(slots[hex(o)]['target'], 16) for o in offsets] == [0xf2ebc0, 0xfeb460, 0xfeb440]
    checks['group.nil_allowed'] = walker.dword(0xbc46c4) == 0xbbbb0c
    checks['application.nil_refused'] = walker.dword(0xbbec58) == 0xbbffb0

    resources, controls, frame_classes = {}, {}, set()
    for resource in RESOURCES:
        data, parsed = dfm_properties(image, resource)
        resources[resource] = {'sha256': sha(data), 'bytes': len(data)}
        controls[resource] = {}
        for name, item in parsed.items():
            if item['class'].startswith('Tfrm'):
                frame_classes.add(item['class'])
            if item['class'] in ('TFlashCxApplicationComboBox', 'TFlashCxGroupComboBox'):
                properties = item['properties']
                controls[resource][name] = {k: v for k, v in properties.items()
                    if k.startswith('On') or '.On' in k or k in (
                        'Action', 'FlashController.UpdateMode', 'FlashController.Sort',
                        'FlashListController.UpdateMode', 'FlashListController.Sort',
                        'ShowAllApplications', 'IncludeUnusedApplication')}
                checks[resource + '.' + name + '.no_click_assignment'] = all(k not in properties for k in ('OnClick', 'Properties.OnEditValueChanged', 'Action'))
    app_control = controls['TFRMUNITIDBASE']['cmbApplication']
    checks['application.update_mode'] = app_control['FlashController.UpdateMode'] == 'umChange'

    guid = image.pe.get_data(0xd8eae0 - image.base, 16)
    checks['refresh.guid'] = guid.hex() == 'deb32ff6f5f4e94caa443c9951bd7d17'
    interface_inventory = {}
    for name, pointer in sorted(image.by_name.items()):
        if '..' not in name:
            continue
        cls = name.rsplit('..', 1)[-1]
        if not (name.startswith(('CIS_TfrmThermostat', 'CIS_TfrmUnitID', 'CIS_TFlashCx')) or cls in frame_classes):
            continue
        vmt = walker.dword(pointer)
        v, chain, found = vmt, [], []
        while v:
            table = walker.dword(v - 84)
            count = walker.dword(table) if table else 0
            if count > 50:
                raise ValueError('Unexpected interface count')
            chain.append({'vmt': hex(v), 'interface_table': hex(table), 'interface_count': count})
            for i in range(count):
                entry = table + 4 + i * 28
                if image.pe.get_data(entry - image.base, 16) == guid:
                    vt = walker.dword(entry + 16)
                    target = walker.dword(vt + 12)
                    found.append({'entry': hex(entry), 'interface_vmt': hex(vt),
                                  'target': hex(target), 'symbol': walker.name(target)})
            parent = walker.dword(v - 48)
            v = walker.dword(parent) if parent else 0
        interface_inventory[name] = {'vmt': hex(vmt), 'chain': chain, 'refresh_implementations': found}
    implementations = {n: v['refresh_implementations'] for n, v in interface_inventory.items() if v['refresh_implementations']}
    checks['refresh.no_matching_thermostat_frames'] = not implementations

    writes = []
    for name in scan_names:
        for a, mn, op, _n in read(name):
            if mn in ('mov', 'xor', 'and', 'or', 'add', 'sub', 'inc', 'dec') and '0x504]' in op.split(',')[0]:
                writes.append({'method': name, 'address': hex(a), 'mnemonic': mn, 'operand': op})
    checks['cache.only_enter_and_keypress_writers'] = {r['address'] for r in writes} == {'0xbbbed1', '0xbbbe41'}
    checks['cache.scan_method_count'] = len(scan_names) == 100

    # Find E8 candidates in executable sections, then require decoded instruction
    # alignment in a MAP-pinned method. This is static call-site inspection.
    wanted = {0xbbc2f8: 'PopulateList', 0xbbbee8: 'DoIndexChange',
              0xbbe5fc: 'HandleButtonClick', 0xbbbe2c: 'DoEnter'}
    callers = {n: [] for n in wanted.values()}
    for section in image.pe.sections:
        if not section.Characteristics & 0x20000000:
            continue
        section_raw, base, p = section.get_data(), image.base + section.VirtualAddress, -1
        while True:
            p = section_raw.find(b'\xe8', p + 1)
            if p < 0 or p + 5 > len(section_raw):
                break
            target = base + p + 5 + struct.unpack_from('<i', section_raw, p + 1)[0]
            if target not in wanted:
                continue
            start = image.starts[bisect.bisect_right(image.starts, base + p) - 1]
            name = next((n for n in image.symbols[start] if image.by_name.get(n) == start), None)
            if name and any(a == base + p and mn == 'call' and op == hex(target) for a, mn, op, _n in read(name)):
                callers[wanted[target]].append({'address': hex(base + p), 'symbol': name,
                    'start': hex(start), 'sha256': methods[name]['sha256']})
    checks['direct_callers.exact'] = callers == EXPECTED_CALLERS
    if not all(checks.values()):
        raise ValueError('Application selector source differs: ' + ', '.join(k for k, v in checks.items() if not v))
    if (sha(exe.read_bytes()), sha(map_path.read_bytes())) != (EXE_SHA256, MAP_SHA256):
        raise ValueError('Original inputs changed during static read')
    return {
        'format': 'cbus-thermostat-application-selector-static-v1',
        'original_exe_sha256': EXE_SHA256, 'original_map_sha256': MAP_SHA256,
        'original_executed': False, 'physical_io': False,
        'checks': {k: True for k in sorted(checks)},
        'method_spans': dict(sorted(methods.items())), 'resources': resources,
        'class_bindings': bindings, 'control_bindings': controls,
        'refresh_interface_inventory': interface_inventory,
        'focus_cache_writer_scan': {'method_names': scan_names, 'writes': writes},
        'direct_callers': callers,
        'catalogue': {'registered_names': {str(k): v for k, v in sorted(catalogue.items())},
                      'flag_3a_false': sorted(false_flags), 'get_can_add_groups_exceptions': [25, 172]},
        'contract': CONTRACT,
    }


CONTRACT = {'application_selector': {'actual_existing_address_inventory': [0,
                                                                1,
                                                                2,
                                                                3,
                                                                4,
                                                                5,
                                                                6,
                                                                7,
                                                                8,
                                                                9,
                                                                10,
                                                                11,
                                                                12,
                                                                13,
                                                                14,
                                                                15,
                                                                16,
                                                                17,
                                                                18,
                                                                19,
                                                                20,
                                                                21,
                                                                22,
                                                                23,
                                                                24,
                                                                25,
                                                                26,
                                                                27,
                                                                28,
                                                                29,
                                                                30,
                                                                31,
                                                                32,
                                                                33,
                                                                34,
                                                                35,
                                                                36,
                                                                37,
                                                                38,
                                                                39,
                                                                40,
                                                                41,
                                                                42,
                                                                43,
                                                                44,
                                                                45,
                                                                46,
                                                                47,
                                                                48,
                                                                49,
                                                                50,
                                                                51,
                                                                52,
                                                                53,
                                                                54,
                                                                55,
                                                                56,
                                                                57,
                                                                58,
                                                                59,
                                                                60,
                                                                61,
                                                                62,
                                                                63,
                                                                64,
                                                                65,
                                                                66,
                                                                67,
                                                                68,
                                                                69,
                                                                70,
                                                                71,
                                                                72,
                                                                73,
                                                                74,
                                                                75,
                                                                76,
                                                                77,
                                                                78,
                                                                79,
                                                                80,
                                                                81,
                                                                82,
                                                                83,
                                                                84,
                                                                85,
                                                                86,
                                                                87,
                                                                88,
                                                                89,
                                                                90,
                                                                91,
                                                                92,
                                                                93,
                                                                94,
                                                                95,
                                                                96,
                                                                97,
                                                                98,
                                                                99,
                                                                100,
                                                                101,
                                                                102,
                                                                103,
                                                                104,
                                                                105,
                                                                106,
                                                                107,
                                                                108,
                                                                109,
                                                                110,
                                                                111,
                                                                112,
                                                                113,
                                                                114,
                                                                115,
                                                                116,
                                                                117,
                                                                118,
                                                                119,
                                                                120,
                                                                121,
                                                                122,
                                                                123,
                                                                124,
                                                                125,
                                                                126,
                                                                127,
                                                                128],
                          'add_application': 'Separate Add dialog/custom range 0..128. Not part of '
                                             'existing selector workflow.',
                          'catalogue_flag_false': [25, 172, 192, 205, 206, 208, 223, 224, 228, 255],
                          'catalogue_get_can_add_groups': 'reject255; permit unregistered; registered '
                                                          'flag+0x3a or explicit25/172',
                          'current_excluded': 'Object is not appended. PopulateList explicitly sets '
                                              'ItemIndex -1 before rebuilding, does not select the '
                                              'absent identity, and restores prior text if resulting '
                                              'text is empty. Framework text-to-lookup-index effects '
                                              'require the separate caption-rematching trace.',
                          'default_IncludeUnused': True,
                          'default_ShowAll': False,
                          'include_order': ['parent IncludeItem', 'application IsItemValid'],
                          'kind': 'existing Application objects belonging to selected network; no '
                                  'implicit creation',
                          'parent255_result': False,
                          'parent_predicate': 'signed address <= 128, with actual byte addresses 0..255',
                          'same_item': 'SetAsElement suppresses identical object when controller '
                                       'force+0x64=false; original fresh controller leaves false',
                          'unrelated_include_exceptions': ['DIMDD8', 'DIMDD4']},
 'cross_application_dialog': {'Add': 'Uses actual selected group application for free address, name, '
                                     'dialog, insert/save; direct attribute virtual+a8 sets newly '
                                     'created object after CanChangeElement. Then PopulateList and '
                                     'DoIndexChange.',
                              'Edit': 'Uses actual selected group application and identity; validation '
                                      'excludes same object in that application; after either modal '
                                      'outcome PopulateList and DoIndexChange.',
                              'clamp': 'TrackedHandle.Update clamps above Count-1 to last and below -1 '
                                       'to -1; negative collection index resolves nil.',
                              'focus_cache': 'Fresh zero; only DoEnter and nonnegative DoEditKeyPress '
                                             'assign +0x504. Embedded mouse-down requests focus before '
                                             'button callback. DoEnter caches displayed index before '
                                             'PopulateList. Explicit focus/list event history must '
                                             'derive indices; no caller-supplied raw index.',
                              'group_nil': 'Group combo inherits AllowChangingToNil=true; application '
                                           'combo override=false.',
                              'index_fallback': 'DoIndexChange uses visible item stored manager index '
                                                'if ItemIndex>=0, otherwise cached +0x504 from DoEnter. '
                                                'Fallback is used directly as unfiltered manager index.',
                              'remaining': 'This source receipt pins callback mechanics, not a complete '
                                           'event-history API. List display, bound manager, current '
                                           'model application and actual role object applications must '
                                           'remain distinct; next implementation must compose '
                                           'deterministic focus/list histories.'},
 'no_claims': ['native GUI execution',
               'vendor C-Gate acceptance',
               'physical behavior',
               'full application migration event multiplicity (separate event lane)'],
 'rebinding': {'list_callbacks': 'List change and root change only mark dirty+0x4d0 and update enable '
                                 'state; no DoIndexChange',
               'posted_refresh': 'All thermostat/UnitID/FlashCx and embedded-frame class chains lack '
                                 'IRefreshFrameSupport; no refresh method or application setter is '
                                 'dispatched by this traversal. Adjacent GUID0x117ab5c belongs to '
                                 'unrelated TfrmIOPEGlobal.',
               'property_callbacks': 'Cooling/heating update visibility; dampers additionally update '
                                     'non-255 cached group identities. No output reference setter.',
               'render_callbacks': 'PopulateList/RenderDisplay can assign display ItemIndex/text only. '
                                   'SetItemIndex dispatches Click, not DoIndexChange. No OnClick or '
                                   'OnEditValueChanged assigned in relevant thermostat/application DFM '
                                   'controls.',
               'standalone_relay': 'Old selected object reference survives list rebinding itself; '
                                   'GetCBusApplication prioritizes selected actual object application '
                                   'over explicit or list root.'}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--map', type=Path, required=True, dest='map_path')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = json.dumps(inspect(args.exe, args.map_path), indent=2, sort_keys=True) + '\n'
    if args.output:
        args.output.write_text(result)
    else:
        print(result, end='')


if __name__ == '__main__':
    main()
