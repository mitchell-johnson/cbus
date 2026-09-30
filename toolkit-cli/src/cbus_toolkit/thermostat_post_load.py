"""Toolkit 1.18 thermostat Load Template post-load model replay.

After ``PP LOAD_FROM_FILE`` the original TcdThermostatTemplates dialog
reloads its object model (AfterLoadProgrammingInformation), reassigns the
plant output and relay groups (TPlantControlService.UpdateParametersForPlantType
and UpdateFanSpeedsForPlantType), clears the programmable Evap program flags
and relies on the later form save (BeforeSaveProgrammingInformation) to write
the model back.  This module replays that pipeline for the fields it touches,
from the post-overlay PP values and the unit's output-application group
inventory.  The tables are pinned against the original EXE by
``research/thermostat_template_static.py``.

The replay is exact only inside a stated precondition and fails closed
outside it: no group of the output application may already carry this
thermostat's ``[CGnn]`` prefix, and no group-selection step may reach the
original's order-dependent ``GetNewGroup`` search.  Generic AfterLoad and
BeforeSave normalization of fields the pipeline does not touch is not
replayed.  See docs/thermostat-templates.md.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


class ThermostatPostLoadError(ValueError):
    """The original post-load outcome is outside the replayed precondition."""


UNUSED = ('unused',)
UNUSED_TAG = '<Unused>'
# TCBusThermostatCGateAgent.LoadThermostatInstallations resource strings;
# the current installation after Load Template is the selected number.
INSTALLATION_NAMES = {
    1: 'Basic Reverse Cycle System', 2: 'Zoned Reverse Cycle System',
    3: 'Zoned 2 Stage Reverse Cycle System', 4: 'Basic Hydronic System',
    5: 'Basic Evaporative Cooling System', 6: 'Basic Fan Coil Cooling System',
    7: 'Evaporative Cooling and Gas Heating System',
    8: 'Conventional Single Stage Heat/Cool USA System',
    9: 'Conventional 2 Stage Heat/Cool USA System',
}
# AfterLoad order of the plant output group attributes.
OUTPUTS = ('CoolActivation', 'CoolStage1', 'CoolStage2', 'CoolStage3', 'CoolFanLow',
           'CoolFanMedium', 'CoolFanHigh', 'HeatActivation', 'HeatStage1', 'HeatStage2',
           'HeatStage3', 'HeatFanLow', 'HeatFanMedium', 'HeatFanHigh')
DAMPERS = ('DamperZone1', 'DamperZone2', 'DamperZone3', 'DamperZone4')
RELAYS = ('InternalRelay1', 'InternalRelay2', 'InternalRelay3', 'InternalRelay4', 'InternalRelay5')
# GroupUsedExcludingAttribute inspects model fields 0xf4..0x138.
USAGE_CHECKED = OUTPUTS + DAMPERS
# IntUnitPlantTypeToVirtualPlantType: unit type 8 is virtual 11 unless all
# of these outputs are 255.
VIRTUAL_11_OUTPUTS = ('CoolActivation', 'CoolStage1', 'CoolStage2', 'CoolStage3', 'CoolFanLow',
                      'CoolFanMedium', 'CoolFanHigh', 'HeatFanLow', 'HeatFanMedium', 'HeatFanHigh')
FAN_FIELDS = ('SpeedControlEnable', 'Speeds', 'DefaultSpeed', 'OnDelay', 'OffDelay', 'Enable')


def pp_name(attribute):
    if attribute in RELAYS:
        return attribute + 'GroupNumber'
    return attribute + 'Output'


UPDATE_TABLE = {
    0: {
        None: (('CoolActivation', UNUSED),
            ('CoolStage1', UNUSED),
            ('CoolStage2', UNUSED),
            ('CoolStage3', UNUSED),
            ('CoolFanLow', UNUSED),
            ('CoolFanMedium', UNUSED),
            ('CoolFanHigh', UNUSED),
            ('HeatActivation', UNUSED),
            ('HeatStage1', UNUSED),
            ('HeatStage2', UNUSED),
            ('HeatStage3', UNUSED),
            ('HeatFanLow', UNUSED),
            ('HeatFanMedium', UNUSED),
            ('HeatFanHigh', UNUSED),
            ('InternalRelay1', UNUSED),
            ('InternalRelay2', UNUSED),
            ('InternalRelay3', UNUSED),
            ('InternalRelay4', UNUSED),
            ('InternalRelay5', UNUSED),
            ('DamperZone1', UNUSED),
            ('DamperZone2', UNUSED),
            ('DamperZone3', UNUSED),
            ('DamperZone4', UNUSED)),
    },
    1: {
        None: (('CoolActivation', UNUSED),
            ('CoolStage1', UNUSED),
            ('CoolStage2', UNUSED),
            ('CoolStage3', UNUSED),
            ('CoolFanLow', UNUSED),
            ('CoolFanMedium', UNUSED),
            ('CoolFanHigh', UNUSED),
            ('HeatActivation', UNUSED),
            ('HeatStage1', ('group', 5, 'W (heat)', 'HeatStage1')),
            ('HeatStage2', UNUSED),
            ('HeatStage3', UNUSED),
            ('HeatFanLow', ('group', 3, 'G (heat fan)', 'HeatFanLow')),
            ('HeatFanMedium', UNUSED),
            ('HeatFanHigh', UNUSED),
            ('InternalRelay1', UNUSED),
            ('InternalRelay2', UNUSED),
            ('InternalRelay3', ('ref', 'HeatFanLow')),
            ('InternalRelay4', UNUSED),
            ('InternalRelay5', ('ref', 'HeatStage1'))),
    },
    2: {
        None: (('CoolActivation', UNUSED),
            ('CoolStage1', ('group', 1, 'pump', 'CoolStage1')),
            ('CoolStage2', UNUSED),
            ('CoolStage3', ('group', 2, 'fill', 'CoolStage3')),
            ('CoolFanLow', ('group', 3, 'cool fan speed 1', 'CoolFanLow')),
            ('CoolFanMedium', ('group', 4, 'cool fan speed 2', 'CoolFanMedium')),
            ('CoolFanHigh', UNUSED),
            ('HeatActivation', UNUSED),
            ('HeatStage1', UNUSED),
            ('HeatStage2', UNUSED),
            ('HeatStage3', UNUSED),
            ('HeatFanLow', UNUSED),
            ('HeatFanMedium', UNUSED),
            ('HeatFanHigh', UNUSED),
            ('InternalRelay1', ('ref', 'CoolStage1')),
            ('InternalRelay2', ('ref', 'CoolStage3')),
            ('InternalRelay3', ('ref', 'CoolFanLow')),
            ('InternalRelay4', ('ref', 'CoolFanMedium')),
            ('InternalRelay5', UNUSED)),
    },
    3: {
        None: (('CoolActivation', ('group', 2, 'B (cool activation)', 'CoolActivation')),
            ('CoolStage1', ('group', 1, 'Y (heat/cool)', 'CoolStage1')),
            ('CoolStage2', UNUSED),
            ('CoolStage3', UNUSED),
            ('CoolFanLow', ('group', 3, 'G (fan)', 'CoolFanLow')),
            ('CoolFanMedium', UNUSED),
            ('CoolFanHigh', UNUSED),
            ('HeatActivation', ('group', 4, 'B (heat activation)', 'HeatActivation')),
            ('HeatStage1', ('ref', 'CoolStage1')),
            ('HeatStage2', UNUSED),
            ('HeatStage3', UNUSED),
            ('HeatFanLow', ('ref', 'CoolFanLow')),
            ('HeatFanMedium', UNUSED),
            ('HeatFanHigh', UNUSED),
            ('InternalRelay1', ('ref', 'CoolStage1')),
            ('InternalRelay2', ('ref', 'CoolActivation')),
            ('InternalRelay3', ('ref', 'CoolFanLow')),
            ('InternalRelay4', ('ref', 'HeatActivation')),
            ('InternalRelay5', UNUSED)),
        'Zoned 2 Stage Reverse Cycle System': (('CoolActivation', UNUSED),
            ('CoolStage1', ('group', 1, 'Y1 (cool/heat)', 'CoolStage1')),
            ('CoolStage2', ('group', 2, 'Y2 (cool/heat)', 'CoolStage2')),
            ('CoolStage3', UNUSED),
            ('CoolFanLow', ('group', 3, 'G (fan)', 'CoolFanLow')),
            ('CoolFanMedium', ('group', 5, 'Heat/cool fan speed', 'CoolFanMedium')),
            ('CoolFanHigh', UNUSED),
            ('HeatActivation', ('group', 4, 'B (heat activation)', 'HeatActivation')),
            ('HeatStage1', ('ref', 'CoolStage1')),
            ('HeatStage2', ('ref', 'CoolStage2')),
            ('HeatStage3', UNUSED),
            ('HeatFanLow', ('ref', 'CoolFanLow')),
            ('HeatFanMedium', ('ref', 'CoolFanMedium')),
            ('HeatFanHigh', UNUSED),
            ('InternalRelay1', ('ref', 'CoolStage1')),
            ('InternalRelay2', ('ref', 'CoolStage2')),
            ('InternalRelay3', ('ref', 'CoolFanLow')),
            ('InternalRelay4', ('ref', 'HeatActivation')),
            ('InternalRelay5', ('ref', 'CoolFanMedium'))),
    },
    4: {
        None: (('CoolActivation', UNUSED),
            ('CoolStage1', UNUSED),
            ('CoolStage2', UNUSED),
            ('CoolStage3', UNUSED),
            ('CoolFanLow', UNUSED),
            ('CoolFanMedium', UNUSED),
            ('CoolFanHigh', UNUSED),
            ('HeatActivation', UNUSED),
            ('HeatStage1', ('group', 1, 'W (heat)', 'HeatStage1')),
            ('HeatStage2', UNUSED),
            ('HeatStage3', UNUSED),
            ('HeatFanLow', ('group', 3, 'G (heat fan)', 'HeatFanLow')),
            ('HeatFanMedium', UNUSED),
            ('HeatFanHigh', UNUSED),
            ('InternalRelay1', ('ref', 'HeatStage1')),
            ('InternalRelay2', UNUSED),
            ('InternalRelay3', ('ref', 'HeatFanLow')),
            ('InternalRelay4', UNUSED),
            ('InternalRelay5', UNUSED)),
    },
    5: {
        None: (('CoolActivation', UNUSED),
            ('CoolStage1', ('group', 1, 'Y (cool)', 'CoolStage1')),
            ('CoolStage2', UNUSED),
            ('CoolStage3', UNUSED),
            ('CoolFanLow', ('group', 3, 'G (cool fan)', 'CoolFanLow')),
            ('CoolFanMedium', UNUSED),
            ('CoolFanHigh', UNUSED),
            ('HeatActivation', UNUSED),
            ('HeatStage1', UNUSED),
            ('HeatStage2', UNUSED),
            ('HeatStage3', UNUSED),
            ('HeatFanLow', UNUSED),
            ('HeatFanMedium', UNUSED),
            ('HeatFanHigh', UNUSED),
            ('InternalRelay1', ('ref', 'CoolStage1')),
            ('InternalRelay2', UNUSED),
            ('InternalRelay3', ('ref', 'CoolFanLow')),
            ('InternalRelay4', UNUSED),
            ('InternalRelay5', UNUSED)),
    },
    6: {
        None: (('CoolActivation', UNUSED),
            ('CoolStage1', ('group', 10, 'pump', 'CoolStage1')),
            ('CoolStage2', ('group', 11, 'dump', 'CoolStage2')),
            ('CoolStage3', UNUSED),
            ('CoolFanLow', ('group', 12, 'cool fan speed 1', 'CoolFanLow')),
            ('CoolFanMedium', ('group', 13, 'cool fan speed 2', 'CoolFanMedium')),
            ('CoolFanHigh', ('group', 14, 'cool fan speed 3', 'CoolFanHigh')),
            ('HeatActivation', UNUSED),
            ('HeatStage1', ('group', 5, 'W (heat)', 'HeatStage1')),
            ('HeatStage2', UNUSED),
            ('HeatStage3', UNUSED),
            ('HeatFanLow', ('group', 3, 'G1 (heat fan speed 1)', 'HeatFanLow')),
            ('HeatFanMedium', ('group', 4, 'G2 (heat fan speed 2)', 'HeatFanMedium')),
            ('HeatFanHigh', UNUSED),
            ('InternalRelay1', UNUSED),
            ('InternalRelay2', UNUSED),
            ('InternalRelay3', ('ref', 'HeatFanLow')),
            ('InternalRelay4', ('ref', 'HeatFanMedium')),
            ('InternalRelay5', ('ref', 'HeatStage1'))),
    },
    7: {
        None: (('CoolActivation', UNUSED),
            ('CoolStage1', ('group', 1, 'Y (cool)', 'CoolStage1')),
            ('CoolStage2', UNUSED),
            ('CoolStage3', UNUSED),
            ('CoolFanLow', ('group', 3, 'G (cool fan)', 'CoolFanLow')),
            ('CoolFanMedium', UNUSED),
            ('CoolFanHigh', UNUSED),
            ('HeatActivation', UNUSED),
            ('HeatStage1', ('group', 5, 'W (heat)', 'HeatStage1')),
            ('HeatStage2', UNUSED),
            ('HeatStage3', UNUSED),
            ('HeatFanLow', ('group', 4, 'G (heat fan)', 'HeatFanLow')),
            ('HeatFanMedium', UNUSED),
            ('HeatFanHigh', UNUSED),
            ('InternalRelay1', ('ref', 'CoolStage1')),
            ('InternalRelay2', UNUSED),
            ('InternalRelay3', ('ref', 'CoolFanLow')),
            ('InternalRelay4', ('ref', 'HeatFanLow')),
            ('InternalRelay5', ('ref', 'HeatStage1'))),
    },
    8: {
        None: (('CoolActivation', UNUSED),
            ('CoolStage1', UNUSED),
            ('CoolStage2', UNUSED),
            ('CoolStage3', UNUSED),
            ('CoolFanLow', UNUSED),
            ('CoolFanMedium', UNUSED),
            ('CoolFanHigh', UNUSED),
            ('HeatActivation', UNUSED),
            ('HeatStage1', ('group', 5, 'W (heat)', 'HeatStage1')),
            ('HeatStage2', UNUSED),
            ('HeatStage3', UNUSED),
            ('HeatFanLow', UNUSED),
            ('HeatFanMedium', UNUSED),
            ('HeatFanHigh', UNUSED),
            ('InternalRelay1', UNUSED),
            ('InternalRelay2', UNUSED),
            ('InternalRelay3', UNUSED),
            ('InternalRelay4', UNUSED),
            ('InternalRelay5', ('ref', 'HeatStage1')),
            ('DamperZone1', UNUSED),
            ('DamperZone2', UNUSED),
            ('DamperZone3', UNUSED),
            ('DamperZone4', UNUSED)),
    },
    9: {
        None: (('CoolActivation', UNUSED),
            ('CoolStage1', ('group', 1, 'Y (cool)', 'CoolStage1')),
            ('CoolStage2', UNUSED),
            ('CoolStage3', UNUSED),
            ('CoolFanLow', ('group', 3, 'G (fan)', 'CoolFanLow')),
            ('CoolFanMedium', UNUSED),
            ('CoolFanHigh', UNUSED),
            ('HeatActivation', UNUSED),
            ('HeatStage1', ('group', 5, 'W (heat)', 'HeatStage1')),
            ('HeatStage2', UNUSED),
            ('HeatStage3', UNUSED),
            ('HeatFanLow', UNUSED),
            ('HeatFanMedium', UNUSED),
            ('HeatFanHigh', UNUSED),
            ('InternalRelay1', ('ref', 'CoolStage1')),
            ('InternalRelay2', UNUSED),
            ('InternalRelay3', ('ref', 'CoolFanLow')),
            ('InternalRelay4', UNUSED),
            ('InternalRelay5', ('ref', 'HeatStage1'))),
        'Conventional Single Stage Heat/Cool USA System': (('CoolActivation', UNUSED),
            ('CoolStage1', ('group', 1, 'Y (cool)', 'CoolStage1')),
            ('CoolStage2', UNUSED),
            ('CoolStage3', UNUSED),
            ('CoolFanLow', ('group', 3, 'G (fan)', 'CoolFanLow')),
            ('CoolFanMedium', UNUSED),
            ('CoolFanHigh', UNUSED),
            ('HeatActivation', UNUSED),
            ('HeatStage1', ('group', 5, 'W (heat)', 'HeatStage1')),
            ('HeatStage2', UNUSED),
            ('HeatStage3', UNUSED),
            ('HeatFanLow', ('ref', 'CoolFanLow')),
            ('HeatFanMedium', UNUSED),
            ('HeatFanHigh', UNUSED),
            ('InternalRelay1', ('ref', 'CoolStage1')),
            ('InternalRelay2', UNUSED),
            ('InternalRelay3', ('ref', 'CoolFanLow')),
            ('InternalRelay4', UNUSED),
            ('InternalRelay5', ('ref', 'HeatStage1'))),
        'Conventional 2 Stage Heat/Cool USA System': (('CoolActivation', UNUSED),
            ('CoolStage1', ('group', 1, 'Y (cool)', 'CoolStage1')),
            ('CoolStage2', ('group', 2, 'Y2 (cool)', 'CoolStage2')),
            ('CoolStage3', UNUSED),
            ('CoolFanLow', ('group', 3, 'G (fan)', 'CoolFanLow')),
            ('CoolFanMedium', UNUSED),
            ('CoolFanHigh', UNUSED),
            ('HeatActivation', UNUSED),
            ('HeatStage1', ('group', 4, 'W (heat)', 'HeatStage1')),
            ('HeatStage2', ('group', 5, 'W2 (heat)', 'CoolStage2')),
            ('HeatStage3', UNUSED),
            ('HeatFanLow', ('ref', 'CoolFanLow')),
            ('HeatFanMedium', UNUSED),
            ('HeatFanHigh', UNUSED),
            ('InternalRelay1', ('ref', 'CoolStage1')),
            ('InternalRelay2', ('ref', 'CoolStage2')),
            ('InternalRelay3', ('ref', 'CoolFanLow')),
            ('InternalRelay4', ('ref', 'HeatStage1')),
            ('InternalRelay5', ('ref', 'HeatStage2'))),
    },
    10: {
        None: (('CoolActivation', UNUSED),
            ('CoolStage1', ('group', 1, 'pump', 'CoolStage1')),
            ('CoolStage2', UNUSED),
            ('CoolStage3', ('group', 2, 'fill', 'CoolStage3')),
            ('CoolFanLow', ('group', 3, 'cool fan speed 1', 'CoolFanLow')),
            ('CoolFanMedium', ('group', 4, 'cool fan speed 2', 'CoolFanMedium')),
            ('CoolFanHigh', UNUSED),
            ('HeatActivation', UNUSED),
            ('HeatStage1', ('group', 5, 'W (heat)', 'HeatStage1')),
            ('HeatStage2', UNUSED),
            ('HeatStage3', UNUSED),
            ('HeatFanLow', UNUSED),
            ('HeatFanMedium', UNUSED),
            ('HeatFanHigh', UNUSED),
            ('InternalRelay1', ('ref', 'CoolStage1')),
            ('InternalRelay2', ('ref', 'CoolStage3')),
            ('InternalRelay3', ('ref', 'CoolFanLow')),
            ('InternalRelay4', ('ref', 'CoolFanMedium')),
            ('InternalRelay5', ('ref', 'HeatStage1'))),
    },
    11: {
        None: (('CoolActivation', UNUSED),
            ('CoolStage1', ('group', 1, 'Y (cool)', 'CoolStage1')),
            ('CoolStage2', ('group', 2, 'Open', 'CoolStage2')),
            ('CoolStage3', ('group', 5, 'Close', 'CoolStage3')),
            ('CoolFanLow', ('group', 3, 'G1 (fan speed 1)', 'CoolFanLow')),
            ('CoolFanMedium', ('group', 4, 'G2 (fan speed 2)', 'CoolFanMedium')),
            ('CoolFanHigh', UNUSED),
            ('HeatActivation', UNUSED),
            ('HeatStage1', UNUSED),
            ('HeatStage2', UNUSED),
            ('HeatStage3', UNUSED),
            ('HeatFanLow', UNUSED),
            ('HeatFanMedium', UNUSED),
            ('HeatFanHigh', UNUSED),
            ('InternalRelay1', ('ref', 'CoolStage1')),
            ('InternalRelay2', ('ref', 'CoolStage2')),
            ('InternalRelay3', ('ref', 'CoolFanLow')),
            ('InternalRelay4', ('ref', 'CoolFanMedium')),
            ('InternalRelay5', ('ref', 'CoolStage3'))),
    },
}
FAN_TABLE = {
    0: {
        None: (('CoolingPlantFanEnable', 0), ('HeatingPlantFanEnable', 0)),
    },
    1: {
        None: (('CoolingPlantFanSpeedControlEnable', 0), ('CoolingPlantFanSpeeds', 1), ('CoolingPlantFanDefaultSpeed', 1), ('CoolingPlantFanEnable', 0), ('HeatingPlantFanSpeedControlEnable', 1), ('HeatingPlantFanSpeeds', 1), ('HeatingPlantFanDefaultSpeed', 1), ('HeatingPlantFanEnable', 1)),
    },
    2: {
        None: (('CoolingPlantFanSpeedControlEnable', 1), ('CoolingPlantFanSpeeds', 2), ('CoolingPlantFanDefaultSpeed', 1), ('CoolingPlantFanEnable', 1), ('HeatingPlantFanSpeedControlEnable', 0), ('HeatingPlantFanSpeeds', 2), ('HeatingPlantFanDefaultSpeed', 1), ('HeatingPlantFanEnable', 0)),
    },
    3: {
        None: (('CoolingPlantFanSpeedControlEnable', 0), ('CoolingPlantFanSpeeds', 1), ('CoolingPlantFanDefaultSpeed', 1), ('CoolingPlantFanEnable', 1), ('HeatingPlantFanSpeedControlEnable', 0), ('HeatingPlantFanSpeeds', 1), ('HeatingPlantFanDefaultSpeed', 1), ('HeatingPlantFanEnable', 1)),
        'Zoned 2 Stage Reverse Cycle System': (('CoolingPlantFanSpeedControlEnable', 1), ('CoolingPlantFanSpeeds', 2), ('CoolingPlantFanDefaultSpeed', 1), ('CoolingPlantFanEnable', 1), ('HeatingPlantFanSpeedControlEnable', 1), ('HeatingPlantFanSpeeds', 2), ('HeatingPlantFanDefaultSpeed', 1), ('HeatingPlantFanEnable', 1)),
    },
    4: {
        None: (('CoolingPlantFanSpeedControlEnable', 0), ('CoolingPlantFanSpeeds', 1), ('CoolingPlantFanDefaultSpeed', 1), ('CoolingPlantFanEnable', 0), ('HeatingPlantFanSpeedControlEnable', 1), ('HeatingPlantFanSpeeds', 1), ('HeatingPlantFanDefaultSpeed', 1), ('HeatingPlantFanEnable', 1)),
    },
    5: {
        None: (('CoolingPlantFanSpeedControlEnable', 1), ('CoolingPlantFanSpeeds', 1), ('CoolingPlantFanDefaultSpeed', 1), ('CoolingPlantFanEnable', 1), ('HeatingPlantFanSpeedControlEnable', 0), ('HeatingPlantFanSpeeds', 1), ('HeatingPlantFanDefaultSpeed', 1), ('HeatingPlantFanEnable', 0)),
    },
    6: {
        None: (('CoolingPlantFanSpeedControlEnable', 1), ('CoolingPlantFanSpeeds', 3), ('CoolingPlantFanDefaultSpeed', 1), ('CoolingPlantFanEnable', 1), ('HeatingPlantFanSpeedControlEnable', 1), ('HeatingPlantFanSpeeds', 2), ('HeatingPlantFanDefaultSpeed', 1), ('HeatingPlantFanEnable', 1)),
    },
    7: {
        None: (('CoolingPlantFanSpeedControlEnable', 1), ('CoolingPlantFanSpeeds', 1), ('CoolingPlantFanDefaultSpeed', 1), ('CoolingPlantFanEnable', 1), ('HeatingPlantFanSpeedControlEnable', 1), ('HeatingPlantFanSpeeds', 1), ('HeatingPlantFanDefaultSpeed', 1), ('HeatingPlantFanEnable', 1)),
    },
    8: {
        None: (('CoolingPlantFanSpeedControlEnable', 0), ('CoolingPlantFanSpeeds', 1), ('CoolingPlantFanDefaultSpeed', 1), ('CoolingPlantFanEnable', 0), ('HeatingPlantFanSpeedControlEnable', 0), ('HeatingPlantFanSpeeds', 1), ('HeatingPlantFanDefaultSpeed', 1), ('HeatingPlantFanEnable', 1)),
    },
    9: {
        'Conventional 2 Stage Heat/Cool USA System': (('CoolingPlantFanSpeedControlEnable', 1), ('CoolingPlantFanSpeeds', 1), ('CoolingPlantFanDefaultSpeed', 1), ('CoolingPlantFanEnable', 1), ('HeatingPlantFanSpeedControlEnable', 1), ('HeatingPlantFanSpeeds', 1), ('HeatingPlantFanDefaultSpeed', 1), ('HeatingPlantFanEnable', 1)),
        None: (('CoolingPlantFanSpeedControlEnable', 1), ('CoolingPlantFanSpeeds', 1), ('CoolingPlantFanDefaultSpeed', 1), ('CoolingPlantFanEnable', 1), ('HeatingPlantFanSpeedControlEnable', 0), ('HeatingPlantFanSpeeds', 1), ('HeatingPlantFanDefaultSpeed', 1), ('HeatingPlantFanEnable', 0)),
        'Conventional Single Stage Heat/Cool USA System': (('CoolingPlantFanSpeedControlEnable', 1), ('CoolingPlantFanSpeeds', 1), ('CoolingPlantFanDefaultSpeed', 1), ('CoolingPlantFanEnable', 1), ('HeatingPlantFanSpeedControlEnable', 1), ('HeatingPlantFanSpeeds', 1), ('HeatingPlantFanDefaultSpeed', 1), ('HeatingPlantFanEnable', 1)),
    },
    10: {
        None: (('CoolingPlantFanSpeedControlEnable', 1), ('CoolingPlantFanSpeeds', 2), ('CoolingPlantFanDefaultSpeed', 1), ('CoolingPlantFanEnable', 1), ('HeatingPlantFanSpeedControlEnable', 0), ('HeatingPlantFanSpeeds', 2), ('HeatingPlantFanDefaultSpeed', 1), ('HeatingPlantFanEnable', 0)),
    },
    11: {
        None: (('CoolingPlantFanSpeedControlEnable', 1), ('CoolingPlantFanSpeeds', 2), ('CoolingPlantFanDefaultSpeed', 1), ('CoolingPlantFanEnable', 1), ('HeatingPlantFanSpeedControlEnable', 0), ('HeatingPlantFanSpeeds', 2), ('HeatingPlantFanDefaultSpeed', 1), ('HeatingPlantFanEnable', 0)),
    },
}
DEFAULT_NAMES = {
    'CoolActivation': {3: 'B (cool activation)'},
    'CoolFanHigh': {6: 'cool fan speed 3'},
    'CoolFanLow': {2: 'cool fan speed 1', 3: 'G (fan)', 5: 'G (cool fan)', 6: 'cool fan speed 1', 7: 'G (cool fan)', 9: 'G (fan)', 10: 'cool fan speed 1', 11: 'G1 (fan speed 1)'},
    'CoolFanMedium': {2: 'cool fan speed 2', 3: {None: None, 'Zoned 2 Stage Reverse Cycle System': 'Heat/cool fan speed'}, 6: 'cool fan speed 2', 10: 'cool fan speed 2', 11: 'G2 (fan speed 2)'},
    'CoolStage1': {2: 'pump', 3: {None: 'Y (heat/cool)', 'Zoned 2 Stage Reverse Cycle System': 'Y1 (cool/heat)'}, 5: 'Y (cool)', 6: 'pump', 7: 'Y (cool)', 9: 'Y (cool)', 10: 'pump', 11: 'Y (cool)'},
    'CoolStage2': {3: {None: None, 'Zoned 2 Stage Reverse Cycle System': 'Y2 (cool/heat)'}, 6: 'dump', 11: 'Open'},
    'CoolStage3': {2: 'fill', 10: 'fill', 11: 'Close'},
    'HeatActivation': {3: 'B (heat activation)'},
    'HeatFanHigh': {},
    'HeatFanLow': {1: 'G (heat fan)', 3: 'G (fan)', 4: 'G (heat fan)', 6: 'G1 (heat fan speed 1)', 7: 'G (heat fan)'},
    'HeatFanMedium': {3: {None: None, 'Zoned 2 Stage Reverse Cycle System': 'Heat/cool fan speed'}, 6: 'G2 (heat fan speed 2)'},
    'HeatStage1': {1: 'W (heat)', 3: {None: 'Y (heat/cool)', 'Zoned 2 Stage Reverse Cycle System': 'Y1 (cool/heat)'}, 4: 'W (heat)', 6: 'W (heat)', 7: 'W (heat)', 8: 'W (heat)', 9: 'W (heat)', 10: 'W (heat)'},
    'HeatStage2': {3: {None: None, 'Zoned 2 Stage Reverse Cycle System': 'Y2 (cool/heat)'}},
    'HeatStage3': {},
}

DAMPER_NAMES = {name: 'Damper Zone ' + name[-1] for name in DAMPERS}
# BeforeSave DamperModulationEnable multiplier per virtual plant type.
DAMPER_MODULATION_FACTOR = {0: 0, 2: 2, 6: 3, 10: 3}


def virtual_plant_type(values):
    unit = values['InternalPlantType']
    if unit == 8 and any(values[pp_name(name)] != 255 for name in VIRTUAL_11_OUTPUTS):
        return 11
    return unit


def _default_name(attribute, plant, installation):
    entry = DEFAULT_NAMES[attribute].get(plant)
    if isinstance(entry, dict):
        return entry.get(installation, entry[None])
    return entry


def _round_half_even(value):
    return round(value)


def _fan_save(model, side, other, own_mode, modes, own_enabled, other_enabled, slave):
    """BeforeSave fan block for one side ('Heating' or 'Cooling')."""
    result = {}
    source = other if (other_enabled and not own_enabled and not slave) else side
    if other_enabled and not own_enabled and not slave:
        keep = bool(modes & 0x10)
    else:
        keep = bool(modes & 0x10) or slave
    if keep:
        result['SpeedControlEnable'] = int(model[source]['SpeedControlEnable'])
        speeds = model[source]['Speeds']
        result['Speeds'] = 1 if speeds == 0 and modes & own_mode else speeds
    else:
        result['SpeedControlEnable'] = 0
        result['Speeds'] = 0
    result['DefaultSpeed'] = model[source]['DefaultSpeed']
    result['OnDelay'] = model[side]['OnDelay'] * 6
    result['OffDelay'] = model[side]['OffDelay'] * 6
    result['Enable'] = int(model[side]['Enable'])
    return {side + 'PlantFan' + key: value for key, value in result.items()}


def form_save_fans(values, *, slave=None):
    """Fan parameters written by the original form save for a loaded PP state."""
    if slave is None:
        slave = values['ControlledZones'] <= 0
    model = {}
    for side in ('Heating', 'Cooling'):
        prefix = side + 'PlantFan'
        model[side] = {'SpeedControlEnable': values[prefix + 'SpeedControlEnable'] != 0,
                       'Speeds': values[prefix + 'Speeds'],
                       'DefaultSpeed': values[prefix + 'DefaultSpeed'],
                       'OnDelay': _round_half_even(values[prefix + 'OnDelay'] / 6),
                       'OffDelay': _round_half_even(values[prefix + 'OffDelay'] / 6),
                       'Enable': values[prefix + 'Enable'] != 0}
    return _save_fan_model(model, values, slave)


def _save_fan_model(model, values, slave):
    modes, vent = values['InternalPlantModes'], values['VentPlantType']
    cooling = bool(modes & 4 or modes & 8 or vent == 2)
    heating = bool(modes & 2 or modes & 8 or vent == 1)
    result = _fan_save(model, 'Heating', 'Cooling', 2, modes, heating, cooling, slave)
    result.update(_fan_save(model, 'Cooling', 'Heating', 4, modes, cooling, heating, slave))
    return result


def damper_modulation_save(value, plant):
    enabled = int(value != 0)
    return DAMPER_MODULATION_FACTOR.get(plant, 1) * enabled


@dataclass(frozen=True)
class GroupOperation:
    action: str  # 'create' or 'rename'
    address: int
    tag: str
    previous_tag: str | None = None

    def as_dict(self):
        return {'action': self.action, 'address': self.address, 'tag': self.tag,
                'previous_tag': self.previous_tag}


@dataclass(frozen=True)
class PostLoadReplay:
    installation: int
    installation_name: str
    virtual_plant_type: int
    prefix: str
    master: bool
    parameters: tuple[tuple[str, int], ...]
    group_operations: tuple[GroupOperation, ...]

    @property
    def expected(self):
        return dict(self.parameters)

    def as_dict(self):
        return {'installation': self.installation, 'installation_name': self.installation_name,
                'virtual_plant_type': self.virtual_plant_type, 'group_prefix': self.prefix,
                'zone_manager_master': self.master, 'parameters': dict(self.parameters),
                'group_operations': [op.as_dict() for op in self.group_operations]}


class _Groups:
    def __init__(self, groups, prefix):
        self.tags = dict(groups)
        self.prefix = prefix
        self.operations = []

    def find(self, tag):
        found = [address for address, text in self.tags.items() if text.lower() == tag.lower()]
        if len(found) > 1:
            raise ThermostatPostLoadError('Several output groups share tag ' + repr(tag)
                                          + '; the original match depends on group order')
        return found[0] if found else None

    def create(self, address, tag):
        self.tags[address] = tag
        self.operations.append(GroupOperation('create', address, tag))
        return address

    def rename(self, address, tag):
        self.operations.append(GroupOperation('rename', address, tag, self.tags[address]))
        self.tags[address] = tag

    def unused(self):
        if 255 not in self.tags:
            self.create(255, UNUSED_TAG)
        return 255

    def prefixed(self, address):
        return self.tags[address].startswith(self.prefix)


def replay_post_load(values: Mapping[str, int], family: str, installation: int,
                     groups: Mapping[int, str]) -> PostLoadReplay:
    """Replay the original post-load pipeline for one loaded template.

    ``values`` is the complete post-overlay PP state as integers and
    ``groups`` maps each existing output-application group address to its tag.
    """
    if family not in ('programmable', 'basic'):
        raise ThermostatPostLoadError('Unknown thermostat family')
    if installation not in INSTALLATION_NAMES:
        raise ThermostatPostLoadError('Installation must be 1..9')
    if any(type(a) is not int or not 0 <= a <= 255 or type(t) is not str for a, t in groups.items()):
        raise ThermostatPostLoadError('Groups must map byte addresses to tag text')
    name = INSTALLATION_NAMES[installation]
    plant = virtual_plant_type(values)
    if plant > 11:
        raise ThermostatPostLoadError('Internal plant type is outside the original table')
    zone = values['ZoneGroup']
    prefix = '[CG' + format(zone, '02d') + ']'
    if any(tag.startswith(prefix) for tag in groups.values()):
        raise ThermostatPostLoadError('The output application already has ' + prefix
                                      + ' groups; original renaming then depends on unrecovered state')
    state = _Groups(groups, prefix)
    master = values['ControlledZones'] > 0
    model = {}

    def create_and_rename(label, address):
        tag = prefix + ' ' + label
        if address in state.tags:
            found = state.find(tag)
            if found is not None and found != address:
                raise ThermostatPostLoadError('AfterLoad group selection depends on an unrecovered flag')
            if found is None:
                state.rename(address, tag)
            return address
        found = state.find(tag)
        return found if found is not None else state.create(address, tag)

    # AfterLoadProgrammingInformation: output group references.
    for attribute in OUTPUTS:
        address = values[pp_name(attribute)]
        if address == 255:
            model[attribute] = state.unused()
            continue
        if address in state.tags and not state.prefixed(address):
            model[attribute] = address
            continue
        label = _default_name(attribute, plant, name)
        if label is None:
            model[attribute] = address if address in state.tags else state.unused()
        else:
            model[attribute] = create_and_rename(label, address)
    for attribute in DAMPERS:
        address = values[pp_name(attribute)]
        if family == 'basic':
            model[attribute] = 255 if 255 in state.tags else None
        elif address == 255:
            model[attribute] = state.unused()
        elif address in state.tags and not state.prefixed(address):
            model[attribute] = address
        else:
            model[attribute] = create_and_rename(DAMPER_NAMES[attribute], address)
    for attribute in RELAYS:
        address = values[pp_name(attribute)]
        if address == 255:
            model[attribute] = state.unused()
        elif address in state.tags:
            model[attribute] = address
        else:
            raise ThermostatPostLoadError('Relay group ' + str(address) + ' would be created with an'
                                          ' unrecovered application default tag')

    def used_by_other(address, excluded):
        return any(model.get(a) == address for a in USAGE_CHECKED if a != excluded)

    def get_group(address, label, excluded):
        tag = prefix + ' ' + label
        found = state.find(tag)
        if found is not None:
            return found
        if address not in state.tags:
            return state.create(address, tag)
        if state.prefixed(address) and not used_by_other(address, excluded):
            if state.tags[address].lower() != tag.lower():
                state.rename(address, tag)
            return address
        raise ThermostatPostLoadError('Group ' + str(address) + ' is taken; the original GetNewGroup'
                                      ' search order is not replayed')

    # TPlantControlService.UpdateParametersForPlantType.
    table = UPDATE_TABLE[plant]
    for attribute, source in table.get(name, table[None]):
        if source == UNUSED:
            model[attribute] = state.unused()
        elif source[0] == 'ref':
            model[attribute] = model[source[1]]
        else:
            model[attribute] = get_group(source[1], source[2], source[3])
    # UpdateFanSpeedsForPlantType on the AfterLoad fan model.
    fans = {}
    for side in ('Heating', 'Cooling'):
        prefix_name = side + 'PlantFan'
        fans[side] = {'SpeedControlEnable': values[prefix_name + 'SpeedControlEnable'] != 0,
                      'Speeds': values[prefix_name + 'Speeds'],
                      'DefaultSpeed': values[prefix_name + 'DefaultSpeed'],
                      'OnDelay': _round_half_even(values[prefix_name + 'OnDelay'] / 6),
                      'OffDelay': _round_half_even(values[prefix_name + 'OffDelay'] / 6),
                      'Enable': values[prefix_name + 'Enable'] != 0}
    table = FAN_TABLE[plant]
    for setter, value in table.get(name, table[None]):
        side = 'Heating' if setter.startswith('Heating') else 'Cooling'
        key = setter[len(side) + len('PlantFan'):]
        fans[side][key] = bool(value) if key in ('SpeedControlEnable', 'Enable') else value

    # BeforeSaveProgrammingInformation for the replayed fields.
    result = {}
    for attribute in OUTPUTS + RELAYS:
        result[pp_name(attribute)] = model[attribute]
    for attribute in DAMPERS:
        result[pp_name(attribute)] = 255 if model[attribute] is None or not master else model[attribute]
    result.update(_save_fan_model(fans, values, not master))
    result['DamperModulationEnable'] = damper_modulation_save(values['DamperModulationEnable'], plant)
    if master:
        result['InternalPlantType'] = 8 if plant == 11 else plant
    else:
        result['InternalPlantType'] = 0
        result['InternalPlantZones'] = 0
    result['EnableHVACRelayDrive'] = 0
    result['InstallationCode'] = installation
    if family == 'programmable':
        # UpdateEvapProgramParameters after AfterLoad normalization (>1 -> 1).
        result['EvapProgramEnabled'] = 0
        nonevap = 1 if values['NonEvapProgramEnabled'] > 1 else values['NonEvapProgramEnabled']
        result['NonEvapProgramEnabled'] = 0 if plant in (0, 2) else nonevap
    return PostLoadReplay(installation, name, plant, prefix, master, tuple(sorted(result.items())),
                          tuple(state.operations))
