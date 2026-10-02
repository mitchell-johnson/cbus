"""Final CSV factory profiles, recovered from the pinned Toolkit EXE/MAP.

Only report associations are represented here. Auxiliary parameter graphs,
native GUI lifecycle and physical programming are separate contracts.
"""
from __future__ import annotations


def _empty(agent, *, area=False, application_default=56, formatter=None):
    return {'agent': agent, 'blocks': 0, 'has_area': area,
            'group_parameter': None, 'generic': True,
            'application_default': application_default,
            'formatter': formatter or 'TCBusUnitCGateAgent.FormatCgApplication',
            'loader': 'TCBusUnitCGateAgent.LoadGroups'}


LAST_CLASSES = {
    'TPCSHAC': _empty('TPCSHACCGateAgent'),
    'TPC_GIM': _empty('TPC_GIMCGateAgent', area=True),
    **{name: _empty('TCBusBridgeCGateAgent', application_default=255,
                   formatter='TCBusBridgeCGateAgent.FormatCgApplication')
       for name in ('TBridge1', 'TBridge2', 'TWGWiresSide')},
    **{name: {**_empty(agent, application_default=255,
                      formatter='TCBusWirelessGatewayCGateAgent.FormatCgApplication'),
              'loader': 'TCBusWirelessGatewayCGateAgent.LoadGroups'}
       for name, agent in (
           ('TCBusWGUnitNoSynchroniseToWired', 'TCBusWirelessGatewayCGateAgent'),
           ('TCBusWGUnitNoRepeatSALTransmission', 'TCBusWirelessGatewayCGateAgent'),
           ('TCBusWirelessGatewayUnit', 'TCBusWirelessGatewayCGateAgent'),
           ('TCBusWirelessGatewayAdvancedUnit', 'TCBusWirelessGatewayAdvancedCGateAgent'))},
    'TWTXU': _empty('TCBusRemoteControlCGateAgent'),
    'TWTXUP': _empty('TCBusRemoteControlCGateAgent'),
    **{name: _empty(agent) for name, agent in (
        ('TPC_TSA', 'TCBusProgrammableThermostatCGateAgent'),
        ('TPC_TSA5', 'TCBusProgrammableThermostatCGateAgent'),
        ('TPC_TSB', 'TCBusBasicThermostatCGateAgent'),
        ('TPC_TSB5', 'TCBusBasicThermostatCGateAgent'))},
    'TSENCT4': _empty('TSENCT4CGateAgent', area=True),
    'TKEYSCEN4': _empty('TCustomSceneKeyCGateAgent', area=True),
    'TSCNCTL5': _empty('TCustomSceneControllerCGateAgent', area=True),
    'TPC_DAL2B': _empty('TCBusPC_DAL2BCGateAgent'),
    'TPC_DAL2C': _empty('TCBusPC_DAL2BCGateAgent'),
    **{name: _empty('TCBusPC_WHAACGateAgent')
       for name in ('TPC_WHAD', 'TPC_WHAR', 'TPC_WHARB')},
    'TCBusWirelessPCIUnit': _empty('TCBusWirelessPCICGateAgent', application_default=255,
                                 formatter='TCBusWirelessPCICGateAgent.FormatCgApplication'),
    'TDMXDO12': _empty('TCBusDMXGatewayCGateAgent', area=True),
    'TPC_RDTS': _empty('TCBusDigitalTemperatureSensorCGateAgent'),
    'TSENLL': {'agent': 'TSENLLCGateAgent', 'blocks': 3, 'has_area': True,
              'group_parameter': ('LevelGroupAddress', 'OnOffGroupAddress', 'EnableGroupAddress'),
              'loader': 'TSENLLCGateAgent.LoadGroups'},
    'TSENTEMP': {'agent': 'TSENTEMPCGateAgent', 'blocks': 3, 'has_area': True,
                'group_parameter': ('ControlGroupAddress', 'EnableGroupAddress', 'OffsetGroupAddress'),
                'loader': 'TSENTEMPCGateAgent.LoadGroups'},
    'TSENTEMPPro': {'agent': 'TSENTEMPProCGateAgent', 'blocks': 3, 'has_area': True,
                   'group_parameter': 'temperature_mode', 'dynamic_blocks': 'temperature_mode',
                   'loader': 'TSENTEMPProCGateAgent.LoadGroups'},
    **{name: {'agent': 'TIOPECGateAgent', 'blocks': 8 + channels, 'has_area': True,
              'group_parameter': 'iope', 'output_channels': channels,
              'loader': 'TIOPECGateAgent.LoadGroups'}
       for name, channels in (('TIOPE1R1', 1), ('TIOPE2R2', 2), ('TIOPE2C4', 4))},
    'TDIMPR12L1': {'agent': 'TDIMPR12L1CGateAgent', 'blocks': 12, 'has_area': True,
                   'group_parameter': 'GroupAddress', 'loader': 'TDIMPR12CGateAgent.LoadGroups'},
    'TWRD4F1': {'agent': 'TCBusWirelessFanControllerCGateAgent', 'blocks': 16,
               'has_area': False, 'secondary_blocks': True,
               'group_parameter': 'wireless_channels', 'dynamic_blocks': 'wireless_channels',
               'loader': 'TCBusWirelessFanControllerCGateAgent.LoadGroups'},
}


def last_profile(klass, agent):
    """Require the exact registered class/agent pair."""
    profile = LAST_CLASSES.get(klass)
    if profile is None or profile['agent'] != agent:
        return None
    return {'class': klass, 'wireless': False, 'source_model': True,
            'last_source_model': True, 'secondary_blocks': False,
            'application_default': 56, **profile}


def temperature_group_count(primary_address):
    return 1 if primary_address in (25, 172) else 0 if primary_address == 228 else 3
