"""Inspect ordinary thermostat output groups statically; never execute originals.

Reproduces method bounds/hashes, instruction checkpoints, DFM bindings and
plant-specific default labels. No vendor bytes or private input paths are emitted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from topology_generator_static import EXE_SHA256, MAP_SHA256, _Image  # noqa: E402
from thermostat_post_load_static import _Walker, _case_table, _default_names  # noqa: E402
from thermostat_settings_form_static import _fields  # noqa: E402
from thermostat_quick_zone_initialization_static import dfm_properties  # noqa: E402

A = 'CIS_TCBusThermostatCGateAgent.TCBusThermostatCGateAgent.'
P = 'CIS_TThermostat.TPlantControlService.'
OUTPUTS = ('CoolActivation', 'CoolStage1', 'CoolStage2', 'CoolStage3',
           'CoolFanLow', 'CoolFanMedium', 'CoolFanHigh', 'HeatActivation',
           'HeatStage1', 'HeatStage2', 'HeatStage3', 'HeatFanLow', 'HeatFanMedium', 'HeatFanHigh')
DAMPERS = ('DamperZone1', 'DamperZone2', 'DamperZone3', 'DamperZone4')
RELAYS = ('InternalRelay1', 'InternalRelay2', 'InternalRelay3', 'InternalRelay4', 'InternalRelay5')
METHODS = ('CIS_TCBusThermostatCGateAgent.TCBusThermostatCGateAgent.AfterLoadProgrammingInformation',
 'CIS_TCBusThermostatCGateAgent.TCBusThermostatCGateAgent.BeforeSaveProgrammingInformation',
 'CIS_TCBusThermostatCGateAgent.TCBusThermostatCGateAgent.InternalCreate',
 'CIS_TThermostat.TPlantControlService.InternalCreate',
 'CIS_TThermostat.TPlantControlService.GetUnusedGroup',
 'CIS_TThermostat.TPlantControlService.FindExistingGroup',
 'CIS_TThermostat.TPlantControlService.CreateAndRenameGroup',
 'CIS_TThermostat.TPlantControlService.GetCoolActivationOutputGroup',
 'CIS_TThermostat.TPlantControlService.SetCoolActivationOutputGroup',
 'CIS_TThermostat.TPlantControlService.GetInternalRelay1Group',
 'CIS_TThermostat.TPlantControlService.SetInternalRelay1Group',
 'CIS_TddThermostat.TddThermostat.BeforeSaveProgramming',
 'CIS_TddThermostat.TddThermostat.ValidateProgramming',
 'CIS_TddThermostat.TddThermostat.SameGroups',
 'CIS_TddThermostat.TddThermostat.ValidateCoolingGroups',
 'CIS_TddThermostat.TddThermostat.ValidateHeatingGroups',
 'CIS_TddThermostat.TddThermostat.ValidateDamperGroups',
 'CIS_TddThermostat.TddThermostat.ValidateFanOnDelay',
 'CIS_TddThermostat.TddThermostat.ValidateFanOffDelay',
 'CIS_TfrmThermostatCoolingGroups.TfrmCoolingGroups.cmbGroupChange',
 'CIS_TfrmThermostatCoolingGroups.TfrmCoolingGroups.FormShow',
 'CIS_TfrmThermostatCoolingGroups.TfrmCoolingGroups.HandleFanHighGroupIncludeItem',
 'CIS_TfrmThermostatCoolingGroups.TfrmCoolingGroups.HandleFanLowGroupIncludeItem',
 'CIS_TfrmThermostatCoolingGroups.TfrmCoolingGroups.HandleFanMediumGroupIncludeItem',
 'CIS_TfrmThermostatCoolingGroups.TfrmCoolingGroups.SetupComponents',
 'CIS_TfrmThermostatCoolingGroups.TfrmCoolingGroups.SetupFlashComponents',
 'CIS_TfrmThermostatHeatingGroups.TfrmHeatingGroups.cmbGroupChange',
 'CIS_TfrmThermostatHeatingGroups.TfrmHeatingGroups.EnableDisableCombos',
 'CIS_TfrmThermostatHeatingGroups.TfrmHeatingGroups.FormShow',
 'CIS_TfrmThermostatHeatingGroups.TfrmHeatingGroups.HandleFanHighGroupIncludeItem',
 'CIS_TfrmThermostatHeatingGroups.TfrmHeatingGroups.HandleFanLowGroupIncludeItem',
 'CIS_TfrmThermostatHeatingGroups.TfrmHeatingGroups.HandleFanMediumGroupIncludeItem',
 'CIS_TfrmThermostatHeatingGroups.TfrmHeatingGroups.SetupComponents',
 'CIS_TfrmThermostatHeatingGroups.TfrmHeatingGroups.SetupFlashComponents',
 'CIS_TfrmThermostatDamperGroups.TfrmDamperGroups.cmbGroupChange',
 'CIS_TfrmThermostatDamperGroups.TfrmDamperGroups.FormShow',
 'CIS_TfrmThermostatDamperGroups.TfrmDamperGroups.SetupFlashComponents',
 'CIS_TThermostat.TPlantControlService.GetDefaultCoolActivationOutputGroupForPlantType',
 'CIS_TThermostat.TPlantControlService.GetDefaultCoolActivationOutputGroupName',
 'CIS_TThermostat.TPlantControlService.GetDefaultCoolFanHighOutputGroupForPlantType',
 'CIS_TThermostat.TPlantControlService.GetDefaultCoolFanHighOutputGroupName',
 'CIS_TThermostat.TPlantControlService.GetDefaultCoolFanLowOutputGroupForPlantType',
 'CIS_TThermostat.TPlantControlService.GetDefaultCoolFanLowOutputGroupName',
 'CIS_TThermostat.TPlantControlService.GetDefaultCoolFanMediumOutputGroupForPlantType',
 'CIS_TThermostat.TPlantControlService.GetDefaultCoolFanMediumOutputGroupName',
 'CIS_TThermostat.TPlantControlService.GetDefaultCoolStage1OutputGroupForPlantType',
 'CIS_TThermostat.TPlantControlService.GetDefaultCoolStage1OutputGroupName',
 'CIS_TThermostat.TPlantControlService.GetDefaultCoolStage2OutputGroupForPlantType',
 'CIS_TThermostat.TPlantControlService.GetDefaultCoolStage2OutputGroupName',
 'CIS_TThermostat.TPlantControlService.GetDefaultCoolStage3OutputGroupForPlantType',
 'CIS_TThermostat.TPlantControlService.GetDefaultCoolStage3OutputGroupName',
 'CIS_TThermostat.TPlantControlService.GetDefaultDamper1OutputGroup',
 'CIS_TThermostat.TPlantControlService.GetDefaultDamper1OutputGroupName',
 'CIS_TThermostat.TPlantControlService.GetDefaultDamper2OutputGroup',
 'CIS_TThermostat.TPlantControlService.GetDefaultDamper2OutputGroupName',
 'CIS_TThermostat.TPlantControlService.GetDefaultDamper3OutputGroup',
 'CIS_TThermostat.TPlantControlService.GetDefaultDamper3OutputGroupName',
 'CIS_TThermostat.TPlantControlService.GetDefaultDamper4OutputGroup',
 'CIS_TThermostat.TPlantControlService.GetDefaultDamper4OutputGroupName',
 'CIS_TThermostat.TPlantControlService.GetDefaultHeatActivationOutputGroupForPlantType',
 'CIS_TThermostat.TPlantControlService.GetDefaultHeatActivationOutputGroupName',
 'CIS_TThermostat.TPlantControlService.GetDefaultHeatFanHighOutputGroupForPlantType',
 'CIS_TThermostat.TPlantControlService.GetDefaultHeatFanHighOutputGroupName',
 'CIS_TThermostat.TPlantControlService.GetDefaultHeatFanLowOutputGroupForPlantType',
 'CIS_TThermostat.TPlantControlService.GetDefaultHeatFanLowOutputGroupName',
 'CIS_TThermostat.TPlantControlService.GetDefaultHeatFanMediumOutputGroupForPlantType',
 'CIS_TThermostat.TPlantControlService.GetDefaultHeatFanMediumOutputGroupName',
 'CIS_TThermostat.TPlantControlService.GetDefaultHeatStage1OutputGroupForPlantType',
 'CIS_TThermostat.TPlantControlService.GetDefaultHeatStage1OutputGroupName',
 'CIS_TThermostat.TPlantControlService.GetDefaultHeatStage2OutputGroupForPlantType',
 'CIS_TThermostat.TPlantControlService.GetDefaultHeatStage2OutputGroupName',
 'CIS_TThermostat.TPlantControlService.GetDefaultHeatStage3OutputGroupForPlantType',
 'CIS_TThermostat.TPlantControlService.GetDefaultHeatStage3OutputGroupName',
 'CIS_TThermostat.UpdateInternalRelayGroup',
 'CIS_TThermostat.TThermostat.InternalCreate',
 'CIS_TThermostat.TPlantControlService.AutogeneratedPrefix',
 'CIS_TThermostat.TPlantControlService.AutogeneratedGroupName',
 'CIS_TcdThermostatPlant.TcdThermostatPlant.EnableControlsForMasterDisableForSlave',
 'CIS_TcdThermostatPlant.TcdThermostatPlant.SetupComponents',
 'CIS_TcdThermostatPlant.TcdThermostatPlant.SetupFlashComponents',
 'CIS_TcdThermostatPlant.TcdThermostatPlant.HandleCoolingGroupsUpdate',
 'CIS_TcdThermostatPlant.TcdThermostatPlant.HandleHeatingGroupsUpdate',
 'CIS_TcdThermostatPlant.TcdThermostatPlant.HandleDamperGroupsUpdate',
 'CIS_TcdThermostatPlant.TcdThermostatPlant.UpdateApplicationLink',
 'CIS_TObjectReferenceAttribute.TObjectReferenceAttribute.SetFlashObject',
 'CIS_TThermostat.TThermostat.GetUnitHasRelays',
 'CIS_TThermostat.TPC_TSA5.GetUnitHasRelays',
 'CIS_TThermostat.TPC_TSB5.GetUnitHasRelays',
 'CIS_TcdThermostatPlant.TcdThermostatPlant.EnableDisableZone',
 'CIS_TThermostat.TThermostat.GetUsedZones',
 'CIS_TThermostat.TPlantControlService.HookEvents',
 'CIS_TThermostat.TPlantControlService.UnhookEvents',
 'CIS_TCBusThermostatCGateAgent.TCBusThermostatCGateAgent.LoadThermostatInstallations',
 'CIS_TCBusThermostatCGateAgent.TCBusThermostatCGateAgent.CreateSpecialApplications',
 'CIS_TCommonCBus.TCBUSApplicationManager.ApplicationByAddress',
 'CIS_TCommonCBus.TCBusGroupManager.GroupByAddress',
 'CIS_TThermostat.TThermostat.GetACApplicationObject')
CHECKPOINTS = {'0x128e098': {'method': 'CIS_TCBusThermostatCGateAgent.TCBusThermostatCGateAgent.AfterLoadProgrammingInformation',
               'mnemonic': 'call',
               'operand': '0x128df98'},
 '0x128e0fc': {'method': 'CIS_TCBusThermostatCGateAgent.TCBusThermostatCGateAgent.AfterLoadProgrammingInformation',
               'mnemonic': 'mov',
               'operand': 'cl, 1'},
 '0x128e0ff': {'method': 'CIS_TCBusThermostatCGateAgent.TCBusThermostatCGateAgent.AfterLoadProgrammingInformation',
               'mnemonic': 'call',
               'operand': '0xf28b68'},
 '0x128e518': {'method': 'CIS_TCBusThermostatCGateAgent.TCBusThermostatCGateAgent.AfterLoadProgrammingInformation',
               'mnemonic': 'call',
               'operand': '0xf264fc'},
 '0x128eb86': {'method': 'CIS_TCBusThermostatCGateAgent.TCBusThermostatCGateAgent.AfterLoadProgrammingInformation',
               'mnemonic': 'test',
               'operand': 'eax, eax'},
 '0x128eb88': {'method': 'CIS_TCBusThermostatCGateAgent.TCBusThermostatCGateAgent.AfterLoadProgrammingInformation',
               'mnemonic': 'jle',
               'operand': '0x128eba0'},
 '0x128eb97': {'method': 'CIS_TCBusThermostatCGateAgent.TCBusThermostatCGateAgent.AfterLoadProgrammingInformation',
               'mnemonic': 'xor',
               'operand': 'edx, edx'},
 '0x128ebad': {'method': 'CIS_TCBusThermostatCGateAgent.TCBusThermostatCGateAgent.AfterLoadProgrammingInformation',
               'mnemonic': 'mov',
               'operand': 'dl, 1'},
 '0x128f43f': {'method': 'CIS_TCBusThermostatCGateAgent.TCBusThermostatCGateAgent.AfterLoadProgrammingInformation',
               'mnemonic': 'mov',
               'operand': 'edx, dword ptr [0xfd9ae4]'},
 '0x128f44c': {'method': 'CIS_TCBusThermostatCGateAgent.TCBusThermostatCGateAgent.AfterLoadProgrammingInformation',
               'mnemonic': 'je',
               'operand': '0x128f543'},
 '0x128f654': {'method': 'CIS_TCBusThermostatCGateAgent.TCBusThermostatCGateAgent.AfterLoadProgrammingInformation',
               'mnemonic': 'jne',
               'operand': '0x128f7ae'},
 '0xfe6028': {'method': 'CIS_TThermostat.TPlantControlService.GetUnusedGroup',
              'mnemonic': 'mov',
              'operand': 'cl, 1'},
 '0xfe602a': {'method': 'CIS_TThermostat.TPlantControlService.GetUnusedGroup',
              'mnemonic': 'mov',
              'operand': 'edx, 0xff'},
 '0xfe2b8b': {'method': 'CIS_TThermostat.TPlantControlService.FindExistingGroup',
              'mnemonic': 'call',
              'operand': '0x6187ac'},
 '0xfe2b9a': {'method': 'CIS_TThermostat.TPlantControlService.FindExistingGroup',
              'mnemonic': 'call',
              'operand': '0x6187ac'},
 '0xfe2ba3': {'method': 'CIS_TThermostat.TPlantControlService.FindExistingGroup',
              'mnemonic': 'call',
              'operand': '0x6090ac'},
 '0xfe2865': {'method': 'CIS_TThermostat.TPlantControlService.CreateAndRenameGroup',
              'mnemonic': 'cmp',
              'operand': 'byte ptr [eax + 0x1e0], 0'},
 '0xfe286c': {'method': 'CIS_TThermostat.TPlantControlService.CreateAndRenameGroup',
              'mnemonic': 'je',
              'operand': '0xfe28a8'},
 '0xfe28ae': {'method': 'CIS_TThermostat.TPlantControlService.CreateAndRenameGroup',
              'mnemonic': 'jne',
              'operand': '0xfe29be'},
 '0xfe28dd': {'method': 'CIS_TThermostat.TPlantControlService.CreateAndRenameGroup',
              'mnemonic': 'call',
              'operand': '0xfe2afc'},
 '0xfe28ed': {'method': 'CIS_TThermostat.TPlantControlService.CreateAndRenameGroup',
              'mnemonic': 'jne',
              'operand': '0xfe29ee'},
 '0xfe29e9': {'method': 'CIS_TThermostat.TPlantControlService.CreateAndRenameGroup',
              'mnemonic': 'call',
              'operand': '0xf47880'},
 '0xfe1e66': {'method': 'CIS_TThermostat.TPlantControlService.SetCoolActivationOutputGroup',
              'mnemonic': 'call',
              'operand': 'dword ptr [ecx + 0xa8]'},
 '0x1131b33': {'method': 'CIS_TddThermostat.TddThermostat.SameGroups',
               'mnemonic': 'cmp',
               'operand': 'eax, dword ptr [edx + ecx*4]'},
 '0x1131b46': {'method': 'CIS_TddThermostat.TddThermostat.SameGroups',
               'mnemonic': 'cmp',
               'operand': 'eax, 0xff'},
 '0x1131b4b': {'method': 'CIS_TddThermostat.TddThermostat.SameGroups',
               'mnemonic': 'je',
               'operand': '0x1131b53'},
 '0x1125a5c': {'method': 'CIS_TfrmThermostatHeatingGroups.TfrmHeatingGroups.EnableDisableCombos',
               'mnemonic': 'test',
               'operand': 'al, al'},
 '0x1125a5e': {'method': 'CIS_TfrmThermostatHeatingGroups.TfrmHeatingGroups.EnableDisableCombos',
               'mnemonic': 'je',
               'operand': '0x1125a68'},
 '0x1125a60': {'method': 'CIS_TfrmThermostatHeatingGroups.TfrmHeatingGroups.EnableDisableCombos',
               'mnemonic': 'sub',
               'operand': 'al, 8'},
 '0x1125a62': {'method': 'CIS_TfrmThermostatHeatingGroups.TfrmHeatingGroups.EnableDisableCombos',
               'mnemonic': 'je',
               'operand': '0x1125a68'},
 '0x11292b5': {'method': 'CIS_TcdThermostatPlant.TcdThermostatPlant.EnableControlsForMasterDisableForSlave',
               'mnemonic': 'mov',
               'operand': 'eax, dword ptr [eax + 0x44c]'},
 '0x11292c9': {'method': 'CIS_TcdThermostatPlant.TcdThermostatPlant.EnableControlsForMasterDisableForSlave',
               'mnemonic': 'mov',
               'operand': 'eax, dword ptr [eax + 0x450]'},
 '0x11292dd': {'method': 'CIS_TcdThermostatPlant.TcdThermostatPlant.EnableControlsForMasterDisableForSlave',
               'mnemonic': 'mov',
               'operand': 'eax, dword ptr [eax + 0x454]'},
 '0x11292f1': {'method': 'CIS_TcdThermostatPlant.TcdThermostatPlant.EnableControlsForMasterDisableForSlave',
               'mnemonic': 'mov',
               'operand': 'eax, dword ptr [eax + 0x458]'},
 '0x1129305': {'method': 'CIS_TcdThermostatPlant.TcdThermostatPlant.EnableControlsForMasterDisableForSlave',
               'mnemonic': 'mov',
               'operand': 'eax, dword ptr [eax + 0x45c]'},
 '0x1128d90': {'method': 'CIS_TcdThermostatPlant.TcdThermostatPlant.HandleCoolingGroupsUpdate',
               'mnemonic': 'sub',
               'operand': 'al, 2'},
 '0x1128d92': {'method': 'CIS_TcdThermostatPlant.TcdThermostatPlant.HandleCoolingGroupsUpdate',
               'mnemonic': 'jb',
               'operand': '0x1128da0'},
 '0x1128d94': {'method': 'CIS_TcdThermostatPlant.TcdThermostatPlant.HandleCoolingGroupsUpdate',
               'mnemonic': 'sub',
               'operand': 'al, 2'},
 '0x1128d96': {'method': 'CIS_TcdThermostatPlant.TcdThermostatPlant.HandleCoolingGroupsUpdate',
               'mnemonic': 'je',
               'operand': '0x1128da0'},
 '0x1128d98': {'method': 'CIS_TcdThermostatPlant.TcdThermostatPlant.HandleCoolingGroupsUpdate',
               'mnemonic': 'sub',
               'operand': 'al, 4'},
 '0x1128d9a': {'method': 'CIS_TcdThermostatPlant.TcdThermostatPlant.HandleCoolingGroupsUpdate',
               'mnemonic': 'je',
               'operand': '0x1128da0'},
 '0x1128e08': {'method': 'CIS_TcdThermostatPlant.TcdThermostatPlant.HandleHeatingGroupsUpdate',
               'mnemonic': 'test',
               'operand': 'al, al'},
 '0x1128e0a': {'method': 'CIS_TcdThermostatPlant.TcdThermostatPlant.HandleHeatingGroupsUpdate',
               'mnemonic': 'je',
               'operand': '0x1128e18'},
 '0x1128e0c': {'method': 'CIS_TcdThermostatPlant.TcdThermostatPlant.HandleHeatingGroupsUpdate',
               'mnemonic': 'sub',
               'operand': 'al, 2'},
 '0x1128e0e': {'method': 'CIS_TcdThermostatPlant.TcdThermostatPlant.HandleHeatingGroupsUpdate',
               'mnemonic': 'je',
               'operand': '0x1128e18'},
 '0x1128e10': {'method': 'CIS_TcdThermostatPlant.TcdThermostatPlant.HandleHeatingGroupsUpdate',
               'mnemonic': 'sub',
               'operand': 'al, 3'},
 '0x1128e12': {'method': 'CIS_TcdThermostatPlant.TcdThermostatPlant.HandleHeatingGroupsUpdate',
               'mnemonic': 'je',
               'operand': '0x1128e18'},
 '0x1129982': {'method': 'CIS_TcdThermostatPlant.TcdThermostatPlant.HandleDamperGroupsUpdate',
               'mnemonic': 'mov',
               'operand': 'eax, dword ptr [eax + 0x394]'},
 '0x1129997': {'method': 'CIS_TcdThermostatPlant.TcdThermostatPlant.HandleDamperGroupsUpdate',
               'mnemonic': 'mov',
               'operand': 'eax, dword ptr [eax + 0x398]'},
 '0x11299ac': {'method': 'CIS_TcdThermostatPlant.TcdThermostatPlant.HandleDamperGroupsUpdate',
               'mnemonic': 'mov',
               'operand': 'eax, dword ptr [eax + 0x39c]'},
 '0x11299c1': {'method': 'CIS_TcdThermostatPlant.TcdThermostatPlant.HandleDamperGroupsUpdate',
               'mnemonic': 'mov',
               'operand': 'eax, dword ptr [eax + 0x3a0]'},
 '0x11299e0': {'method': 'CIS_TcdThermostatPlant.TcdThermostatPlant.HandleDamperGroupsUpdate',
               'mnemonic': 'test',
               'operand': 'al, al'},
 '0x11299e2': {'method': 'CIS_TcdThermostatPlant.TcdThermostatPlant.HandleDamperGroupsUpdate',
               'mnemonic': 'jne',
               'operand': '0x11299e8'},
 '0x7ddc34': {'method': 'CIS_TObjectReferenceAttribute.TObjectReferenceAttribute.SetFlashObject',
              'mnemonic': 'cmp',
              'operand': 'eax, dword ptr [ebp - 8]'},
 '0x7ddc82': {'method': 'CIS_TObjectReferenceAttribute.TObjectReferenceAttribute.SetFlashObject',
              'mnemonic': 'je',
              'operand': '0x7ddc92'},
 '0x7ddc8d': {'method': 'CIS_TObjectReferenceAttribute.TObjectReferenceAttribute.SetFlashObject',
              'mnemonic': 'call',
              'operand': '0x7ed6d4'},
 '0xfecca5': {'method': 'CIS_TThermostat.TThermostat.GetUnitHasRelays',
              'mnemonic': 'mov',
              'operand': 'byte ptr [ebp - 5], 0'},
 '0xfeda65': {'method': 'CIS_TThermostat.TPC_TSA5.GetUnitHasRelays',
              'mnemonic': 'mov',
              'operand': 'byte ptr [ebp - 5], 1'},
 '0xfeda51': {'method': 'CIS_TThermostat.TPC_TSB5.GetUnitHasRelays',
              'mnemonic': 'mov',
              'operand': 'byte ptr [ebp - 5], 1'},
 '0x1126f36': {'method': 'CIS_TcdThermostatPlant.TcdThermostatPlant.EnableDisableZone',
               'mnemonic': 'call',
               'operand': '0xfdeb50'},
 '0x1126f44': {'method': 'CIS_TcdThermostatPlant.TcdThermostatPlant.EnableDisableZone',
               'mnemonic': 'and',
               'operand': 'al, byte ptr [ebp - 7]'},
 '0xfe167a': {'method': 'CIS_TThermostat.TPlantControlService.HookEvents',
              'mnemonic': 'mov',
              'operand': 'dword ptr [eax + 0x60], 0xfe1de4'},
 '0xfe1690': {'method': 'CIS_TThermostat.TPlantControlService.HookEvents',
              'mnemonic': 'mov',
              'operand': 'dword ptr [eax + 0x60], 0xfe1de4'},
 '0xfe16a6': {'method': 'CIS_TThermostat.TPlantControlService.HookEvents',
              'mnemonic': 'mov',
              'operand': 'dword ptr [eax + 0x60], 0xfe1d20'},
 '0x129367d': {'method': 'CIS_TCBusThermostatCGateAgent.TCBusThermostatCGateAgent.LoadThermostatInstallations',
               'mnemonic': 'je',
               'operand': '0x129397a'},
 '0x1293694': {'method': 'CIS_TCBusThermostatCGateAgent.TCBusThermostatCGateAgent.LoadThermostatInstallations',
               'mnemonic': 'cmp',
               'operand': 'eax, 9'},
 '0x1293697': {'method': 'CIS_TCBusThermostatCGateAgent.TCBusThermostatCGateAgent.LoadThermostatInstallations',
               'mnemonic': 'ja',
               'operand': '0x1293939'},
 '0x128dfca': {'method': 'CIS_TCBusThermostatCGateAgent.TCBusThermostatCGateAgent.CreateSpecialApplications',
               'mnemonic': 'mov',
               'operand': 'edx, 0xac'},
 '0x128dfdb': {'method': 'CIS_TCBusThermostatCGateAgent.TCBusThermostatCGateAgent.CreateSpecialApplications',
               'mnemonic': 'jne',
               'operand': '0x128e030'},
 '0x128dff0': {'method': 'CIS_TCBusThermostatCGateAgent.TCBusThermostatCGateAgent.CreateSpecialApplications',
               'mnemonic': 'mov',
               'operand': 'cl, 1'},
 '0x128e002': {'method': 'CIS_TCBusThermostatCGateAgent.TCBusThermostatCGateAgent.CreateSpecialApplications',
               'mnemonic': 'mov',
               'operand': 'eax, 0x128b218'},
 '0x128e02d': {'method': 'CIS_TCBusThermostatCGateAgent.TCBusThermostatCGateAgent.CreateSpecialApplications',
               'mnemonic': 'call',
               'operand': 'dword ptr [edx + 0x7c]'},
 '0x128f559': {'method': 'CIS_TCBusThermostatCGateAgent.TCBusThermostatCGateAgent.AfterLoadProgrammingInformation',
               'mnemonic': 'xor',
               'operand': 'ecx, ecx'},
 '0x128f55b': {'method': 'CIS_TCBusThermostatCGateAgent.TCBusThermostatCGateAgent.AfterLoadProgrammingInformation',
               'mnemonic': 'mov',
               'operand': 'edx, 0xff'},
 '0x128f58f': {'method': 'CIS_TCBusThermostatCGateAgent.TCBusThermostatCGateAgent.AfterLoadProgrammingInformation',
               'mnemonic': 'xor',
               'operand': 'ecx, ecx'},
 '0x128f591': {'method': 'CIS_TCBusThermostatCGateAgent.TCBusThermostatCGateAgent.AfterLoadProgrammingInformation',
               'mnemonic': 'mov',
               'operand': 'edx, 0xff'},
 '0x128f5c5': {'method': 'CIS_TCBusThermostatCGateAgent.TCBusThermostatCGateAgent.AfterLoadProgrammingInformation',
               'mnemonic': 'xor',
               'operand': 'ecx, ecx'},
 '0x128f5c7': {'method': 'CIS_TCBusThermostatCGateAgent.TCBusThermostatCGateAgent.AfterLoadProgrammingInformation',
               'mnemonic': 'mov',
               'operand': 'edx, 0xff'},
 '0x128f5fb': {'method': 'CIS_TCBusThermostatCGateAgent.TCBusThermostatCGateAgent.AfterLoadProgrammingInformation',
               'mnemonic': 'xor',
               'operand': 'ecx, ecx'},
 '0x128f5fd': {'method': 'CIS_TCBusThermostatCGateAgent.TCBusThermostatCGateAgent.AfterLoadProgrammingInformation',
               'mnemonic': 'mov',
               'operand': 'edx, 0xff'},
 '0x129604c': {'method': 'CIS_TCBusThermostatCGateAgent.TCBusThermostatCGateAgent.BeforeSaveProgrammingInformation',
               'mnemonic': 'je',
               'operand': '0x12960a0'},
 '0x1296062': {'method': 'CIS_TCBusThermostatCGateAgent.TCBusThermostatCGateAgent.BeforeSaveProgrammingInformation',
               'mnemonic': 'jne',
               'operand': '0x12960a0'},
 '0x12960a6': {'method': 'CIS_TCBusThermostatCGateAgent.TCBusThermostatCGateAgent.BeforeSaveProgrammingInformation',
               'mnemonic': 'mov',
               'operand': 'edx, 0xff'},
 '0x1296134': {'method': 'CIS_TCBusThermostatCGateAgent.TCBusThermostatCGateAgent.BeforeSaveProgrammingInformation',
               'mnemonic': 'mov',
               'operand': 'edx, 0xff'},
 '0x12961c2': {'method': 'CIS_TCBusThermostatCGateAgent.TCBusThermostatCGateAgent.BeforeSaveProgrammingInformation',
               'mnemonic': 'mov',
               'operand': 'edx, 0xff'},
 '0x1296250': {'method': 'CIS_TCBusThermostatCGateAgent.TCBusThermostatCGateAgent.BeforeSaveProgrammingInformation',
               'mnemonic': 'mov',
               'operand': 'edx, 0xff'},
 '0x1128b25': {'method': 'CIS_TcdThermostatPlant.TcdThermostatPlant.SetupComponents',
               'mnemonic': 'call',
               'operand': 'dword ptr [edx + 0x178]'},
 '0x1128b55': {'method': 'CIS_TcdThermostatPlant.TcdThermostatPlant.SetupComponents',
               'mnemonic': 'je',
               'operand': '0x1128b9d'},
 '0x1128b65': {'method': 'CIS_TcdThermostatPlant.TcdThermostatPlant.SetupComponents',
               'mnemonic': 'call',
               'operand': '0x6f61c0'},
 '0x1128b98': {'method': 'CIS_TcdThermostatPlant.TcdThermostatPlant.SetupComponents',
               'mnemonic': 'call',
               'operand': '0x6f61c0'}}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def inspect(exe: Path, map_path: Path) -> dict:
    raw, mapping = exe.read_bytes(), map_path.read_bytes()
    if (sha(raw), sha(mapping)) != (EXE_SHA256, MAP_SHA256):
        raise ValueError('Pinned original EXE/MAP hashes differ')
    image = _Image(raw, mapping)
    walker = _Walker(image)
    names = list(METHODS) + [A+'IntUnitPlantTypeToVirtualPlantType']
    names += [P+'Set'+role+('Group' if role in RELAYS else 'OutputGroup')
              for role in OUTPUTS+DAMPERS+RELAYS]
    names += ['CIS_TCBusThermostatCGateAgent.TCBusProgrammableThermostatCGateAgent.AfterLoadProgrammingInformation',
              'CIS_TStandardCBusApplications.CIS_TStandardCBusApplications',
              'CIS_TStandardCBusApplications.TStandardCBusApplications.GetApplicationName']
    methods = {}
    for name in dict.fromkeys(names):
        rows, tables, digest = walker.listing(name)
        start = image.by_name[name]
        methods[name] = {'address': hex(start), 'end': hex(next(x for x in image.starts if x > start)),
                         'sha256': digest, 'rows': rows, 'tables': tables}
    checks = {}
    for address, expected in CHECKPOINTS.items():
        rows = {hex(a): (m, op) for a, m, op, _ in methods[expected['method']]['rows']}
        checks[address] = rows.get(address) == (expected['mnemonic'], expected['operand'])
    def rows(name):
        return methods[name]['rows']
    def calls(name):
        return [note for _a, m, _op, note in rows(name) if m == 'call' and note]
    defaults = {}
    for role in OUTPUTS:
        name = P+'GetDefault'+role+'OutputGroupForPlantType'
        table, _digest, _rows = _case_table(walker, name, _default_names)
        defaults[role] = {str(plant): [{'installation': installation, 'label': actions[0] if actions else None}
                                     for installation, actions in branches.items()]
                          for plant, branches in table.items()}
        rs = rows(name)
        checks[role+'_unused_first'] = next(note for _a, m, _op, note in rs if m == 'call') == P+'GetUnusedGroup'
        checks[role+'_does_not_allocate'] = not any('GetNewGroup' in note or 'NewGroupWithAddress' in note
                                                  for _a, _m, _op, note in rs)
    load_calls = calls(A+'AfterLoadProgrammingInformation')
    defaults_order = [n for n in load_calls if n.startswith(P+'GetDefault') and 'OutputGroup' in n]
    checks['ordinary_getter_order'] = defaults_order == [P+'GetDefault'+r+'OutputGroupForPlantType' for r in OUTPUTS] + [
        P+'GetDefaultDamper'+str(i)+'OutputGroup' for i in range(1, 5)]
    save_calls = calls(A+'BeforeSaveProgrammingInformation')
    expected_saved = [P+'Get'+r+('Group' if r in RELAYS else 'OutputGroup') for r in RELAYS+OUTPUTS+DAMPERS]
    actual_saved = list(dict.fromkeys(n for n in save_calls if n in expected_saved))
    checks['save_role_order'] = actual_saved == expected_saved
    for index in range(1, 5):
        name = P+'GetDefaultDamper'+str(index)+'OutputGroup'
        checks['damper'+str(index)+'_no_prefix_test'] = not any('System.Pos' == n for n in calls(name))
    load_rows = rows(A+'AfterLoadProgrammingInformation')
    for index, (_a, mnemonic, _operand, note) in enumerate(load_rows):
        if mnemonic == 'call' and note in defaults_order:
            checks[note+'_ordinary_false_flag'] = [(m, op) for _b, m, op, _n in load_rows[index-2:index]] == [
                ('xor', 'ecx, ecx'), ('pop', 'edx')]
    virtual_rows = rows(A+'IntUnitPlantTypeToVirtualPlantType')
    virtual_fields = dict(zip(range(0x204, 0x23c, 4), OUTPUTS))
    virtual_offsets = [int(match[1], 16) for _a, mn, op, _n in virtual_rows
        for match in [re.fullmatch(r'eax, dword ptr \[eax \+ (0x[0-9a-f]+)\]', op)] if mn == 'mov' and match]
    checks['raw8_virtual11_complete_dependencies'] = tuple(virtual_fields[o] for o in virtual_offsets) == (
        'CoolActivation', 'CoolStage1', 'CoolStage2', 'CoolStage3', 'CoolFanLow', 'CoolFanMedium',
        'CoolFanHigh', 'HeatFanLow', 'HeatFanMedium', 'HeatFanHigh')
    checks['raw8_virtual11_branch'] = (any(op == 'byte ptr [ebp - 8], 8' for _a, _m, op, _n in virtual_rows)
        and any(op == 'dword ptr [ebp - 0xc], 0xb' for _a, _m, op, _n in virtual_rows))
    damper_labels = {str(i): image.literal(0xfe9580+(i-1)*0x100) for i in range(1, 5)}
    checks['exact_damper_labels'] = damper_labels == {str(i): 'Damper Zone '+str(i) for i in range(1, 5)}
    for role in OUTPUTS+DAMPERS+RELAYS:
        name = P+'Set'+role+('Group' if role in RELAYS else 'OutputGroup')
        checks[role+'_reference_setter'] = [(m, op) for _a, m, op, _n in rows(name) if m == 'call'] == [
            ('call', 'dword ptr [ecx + 0xa8]')]
    checks['prefix_literal'] = (image.literal(0xfe2ad4), image.literal(0xfe2ae8)) == ('CG', '[%s%2.2d]')
    checks['ac_application_name'] = image.resource(0x128b218) == 'Air Conditioning'
    checks['unused_name'] = image.resource(walker.dword(0x13c1ca8)) == '<Unused>'
    app, resource, overrides = None, None, {}
    for _a, mn, op, note in rows('CIS_TStandardCBusApplications.CIS_TStandardCBusApplications'):
        match = re.fullmatch(r'edx, (0x[0-9a-f]+)', op)
        if mn == 'mov' and match:
            app = int(match[1], 16)
        if note.startswith('RES:'):
            resource = note[4:]
        if mn == 'call' and note.endswith('.TStandardCBusApplication.SetGroupName'):
            overrides[app] = resource
    checks['ac_group_name'] = overrides[172] == 'Communication Group'
    checks['catalogue_selected_application_names'] = tuple(image.resource(a) for a in
        (0x85a9d8, 0x85aa90, 0x85a9f8)) == ('Lighting', 'DALI', 'Enable Control')
    app_name_rows = {a: (mn, op) for a, mn, op, _ in rows(
        'CIS_TStandardCBusApplications.TStandardCBusApplications.GetApplicationName')}
    checks['unregistered_application_name_is_decimal'] = app_name_rows[0x85adf1] == ('call', '0x6198ac')
    checks['catalogue_name_uses_address_equality'] = app_name_rows[0x85ae1c] == ('cmp', 'eax, dword ptr [ebp - 8]')
    resources, fields, bindings = {}, {}, {}
    for module, cls, resource in (
        ('CoolingGroups', 'CoolingGroups', 'TFRMCOOLINGGROUPS'),
        ('HeatingGroups', 'HeatingGroups', 'TFRMHEATINGGROUPS'),
        ('DamperGroups', 'DamperGroups', 'TFRMDAMPERGROUPS'),
        ('Plant', 'ThermostatPlant', 'TFRMTHERMOSTATPLANT')):
        raw_dfm, controls = dfm_properties(image, resource)
        resources[resource] = {'sha256': sha(raw_dfm), 'bytes': len(raw_dfm)}
        fields[resource] = {hex(k): v for k, v in _fields(walker, 'CIS_TfrmThermostat'+module+'..Tfrm'+cls).items()}
        bindings[resource] = {name: {k: v for k, v in c['properties'].items()
                                    if k in ('FlashController.UpdateMode', 'Properties.OnChange',
                                             'Properties.DropDownListStyle', 'Properties.ImmediatePost')}
                              for name, c in controls.items()
                              if 'ComboBox' in c['class'] and ('Group' in name)}
        for name, properties in bindings[resource].items():
            checks[resource+'.'+name+'.update'] = properties.get('FlashController.UpdateMode') == 'umChange'
            checks[resource+'.'+name+'.callback'] = properties.get('Properties.OnChange') == (
                None if module == 'Plant' else 'cmbGroupChange')
    if not all(checks.values()):
        raise ValueError('Output source checkpoints differ: '+', '.join(k for k, ok in checks.items() if not ok))
    if (sha(exe.read_bytes()), sha(map_path.read_bytes())) != (EXE_SHA256, MAP_SHA256):
        raise ValueError('Original inputs changed during static inspection')
    return {
        'format': 'cbus-thermostat-output-groups-static-v1',
        'original_exe_sha256': EXE_SHA256, 'original_map_sha256': MAP_SHA256,
        'original_executed': False, 'physical_io': False,
        'checks': {k: True for k in sorted(checks)},
        'method_spans': {n: {k: v for k, v in item.items() if k not in ('rows', 'tables')}
                         for n, item in sorted(methods.items())},
        'resources': resources, 'published_control_fields': fields, 'selector_bindings': bindings,
        'default_labels': defaults, 'damper_labels': damper_labels,
        'contract': {
            'ordinary_model': 'fresh model, template event flag false; no template or application-change callbacks',
            'load_order': ['AC application172', 'ZoneGroup in172', 'ApplicationNumber binding',
                           'setback references', *OUTPUTS, *DAMPERS, *RELAYS, 'schedule references'],
            'new_selected_application_names': {'56': 'Lighting', '95': 'DALI', '203': 'Enable Control',
                                               'other_admitted48_94': 'decimal address'},
            'post_load_selection': 'ordered parameter/address selections from existing bound-application group identities',
            'cooling_enabled_virtual_types': [2, 3, 5, 6, 7, 9, 10, 11],
            'heating_disabled_virtual_types': [0, 2, 5], 'heating_fans_disabled_virtual_types': [0, 8],
            'damper_selector_gate': 'programmable; virtual plant nonzero; InternalPlantZones & 30 nonzero',
            'relay_selector_gate': 'TSA5 or TSB5; loaded ControlledZones > 0',
            'fan_filter': 'unused always included; other two same-side fan identities excluded at each step',
            'save': 'all fourteen outputs and five relays store selected address; dampers store255 for slave or nil',
            'validation': 'duplicate non255 identities refused independently within cooling7, heating7 and damper4',
            'selection_callbacks': 'cool/heat warning only; damper also caches last non255 object; no automatic relay reassignment',
            'graph_preservation': 'ordinary-load create/reuse/rename effects retained even if later selection chooses elsewhere',
            'bounds': ['no typed Add dialog', 'no template allocator', 'no ZoneGroup/application-change history',
                       'no future zone callback history', 'no original GUI, vendor execution or physical acceptance'],
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
