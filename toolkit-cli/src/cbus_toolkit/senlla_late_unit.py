"""Live late SENLLA Unit attributes and ordered ST7/surface PP loading.

The inherited owner, Unit manager, key/block objects and current PP journal
are retained. Bank and occupancy transitions use the existing owning graph
at each setter position. Persistent form initialization and complete ordered
save orchestration are separate callers.
"""
from .senlla_inherited_owner import SENLLAInheritedOwner, UnitEnumAttribute
from .senlla_lifecycle import (
    BooleanAttribute, IntegerAttribute, ObjectReferenceAttribute)
from .senlla_live_banks import SENLLALiveBanks
from .senlla_surface import margin_percent
from .sensors import SensorError


class _CommittedBoolean(BooleanAttribute):
    def __init__(self, *args, committed, **kwargs):
        self._committed = committed
        super().__init__(*args, **kwargs)

    def _record(self, operation):
        if operation == 'assign':
            self._committed()
        super()._record(operation)


class _CommittedReference(ObjectReferenceAttribute):
    def __init__(self, *args, committed, **kwargs):
        self._committed = committed
        super().__init__(*args, **kwargs)

    def _record(self, operation):
        if operation == 'assign':
            self._committed()
        super()._record(operation)


class SENLLALateUnit:
    """Register the late attributes before PP load; execute explicit phases.

    ``journal`` must be the owner's actual current PP storage with read and
    capture methods. It is consulted again after every preceding callback.
    Missing source objects are resolved by the inherited owner's bridge.
    """
    def __init__(self, inherited_owner, journal):
        from .senlla_owner import SENLLAParameterJournal
        if not isinstance(inherited_owner, SENLLAInheritedOwner):
            raise SensorError('Late Unit requires the same concrete inherited owner')
        if (not isinstance(journal, SENLLAParameterJournal)
                or journal.snapshot.identity != inherited_owner.snapshot.identity
                or journal.snapshot.expected != inherited_owner.snapshot.expected):
            raise SensorError('Late Unit requires current owning PP storage')
        if inherited_owner.runtime.context is not None:
            raise SensorError('Late attributes must be registered before the owning PP load')
        self.inherited = inherited_owner
        self.runtime = inherited_owner.runtime
        self.journal = journal
        self.attributes = {}
        self.loaded_st7 = self.loaded_surface = False
        manager, trace = self.runtime.unit_manager, self.runtime._trace

        # These constructor refs are nil. The complete owner loads their
        # values in the earlier NeoPro phase, before ST7/surface loading.
        references = ('JoinApplication', 'JoinGroup', 'DualJoinGroup',
                      'KeyDisableGroup', 'CorridorLinkGroup',
                      'InfraredKeyOffset', 'InfraredLightLevelKey', 'InfraredOccupancyKey',
                      'LightLevelMaintEnableGroup', 'OccupancyEnableGroup',
                      'PotentiometerABlock', 'PotentiometerBBlock',
                      'LightLevelTargetGroup', 'LightLevelMarginGroup',
                      'BankSwitchLowGroup', 'BankSwitchHighGroup')
        for name in references:
            self._register(name, ObjectReferenceAttribute(manager, name='unit.' + name, trace=trace))
        for name in ('Nightlight', 'KeyDisableGroupInvert', 'InfraredLightLevelActive', 'InfraredOccupancyActive',
                     'LightLevelMaintEnableGroupOff', 'OccupancyEnableGroupOff',
                     'IsUsingLightLevelTargetGroup', 'IsUsingLightLevelMarginGroup'):
            self._register(name, BooleanAttribute(manager, False, name='unit.' + name, trace=trace))
        for name in ('LightLevelTargetLux', 'LightLevelMarginPerc', 'LightLevelScale',
                     'PowerUpTargetGroupPresetLevel', 'PowerUpMarginGroupPresetLevel',
                     'PowerUpBankSwitchGroupPresetLevel'):
            self._register(name, IntegerAttribute(manager, 0, name='unit.' + name, trace=trace))
        for name, maximum in (('IndicatorControl', 3), ('PotentiometerAFunction', 3),
                              ('PotentiometerBFunction', 3), ('PowerUpLightLevelState', 2),
                              ('PowerUpOccupancyState', 2), ('PowerUpTargetGroupState', 1),
                              ('PowerUpMarginGroupState', 1), ('PowerUpBankSwitchGroupState', 1)):
            self._register(name, UnitEnumAttribute(manager, maximum=maximum,
                                                   name='unit.' + name, trace=trace))

        # These fields have no native dedicated AfterChange callback. Commit
        # their current graph facts before managed subscribers run, without
        # inventing a bank Allowed refresh at assignment.
        self._register('LightLevelMaintActive', _CommittedBoolean(manager, False,
            name='unit.LightLevelMaintActive', trace=trace, committed=self._maintenance_committed))
        self._register('LightLevelMaintBlock', _CommittedReference(manager,
            name='unit.LightLevelMaintBlock', trace=trace, committed=self._maintenance_committed))
        self._register('LightLevelBroadcastActive', self.runtime.broadcast_active)
        self._register('LightLevelBroadcastBlock', self.runtime.broadcast_block)
        self.live_banks = SENLLALiveBanks(self.runtime,
            maintenance_active=self.attribute('LightLevelMaintActive'),
            maintenance_block=self.attribute('LightLevelMaintBlock'))
        self.bank_objects = tuple(bank.object for bank in self.live_banks.banks)
        self.bank_managers = tuple(bank.manager for bank in self.live_banks.banks)
        self.use_low = tuple(bank.use_low for bank in self.live_banks.banks)
        self.use_high = tuple(bank.use_high for bank in self.live_banks.banks)

        self._register('CorridorLinkActive', BooleanAttribute(manager, False,
            name='unit.CorridorLinkActive', trace=trace,
            after_change=lambda _: self._corridor_active_changed()))
        for name in ('CorridorLinkCorridorBlock', 'CorridorLinkOfficeBlock'):
            self._register(name, ObjectReferenceAttribute(manager, name='unit.' + name, trace=trace,
                before_change=lambda attr, _, name=name: self._corridor_before(name),
                after_change=lambda _, name=name: self._corridor_refresh(name)))
        self.timer_minimum = []
        for index, block in enumerate(self.runtime.blocks):
            minimum = IntegerAttribute(block.manager, 0, name=f'block:{index}.timer_minimum', trace=trace,
                                       after_change=lambda _, index=index: self._timer_changed(index))
            self.timer_minimum.append(minimum)
            block.timer_minimum = minimum
            if block.timer.after_change is not None:
                raise SensorError('Timer callback already has another owning implementation')
            block.timer.after_change = lambda _, index=index: self._timer_changed(index)
        self.runtime.protected_group_attributes = (self.attributes['LightLevelMaintEnableGroup'],
            self.attributes['JoinGroup'], self.attributes['CorridorLinkGroup'])

    def _register(self, name, attribute):
        self.attributes[name] = self.inherited.register_unit_attribute(name, attribute)

    def attribute(self, name):
        if name not in self.attributes:
            raise SensorError('Late Unit field has no source-registered attribute: ' + str(name))
        return self.attributes[name]

    def set(self, name, value, *, source):
        def execute():
            if not isinstance(source, str) or not source:
                raise SensorError('Late Unit setter requires its actual source position')
            self.runtime._event('late_unit_setter', field=name, source=source,
                                value=getattr(value, 'identity', getattr(value, 'name', value)))
            self.attribute(name).set(value)
        return self.runtime._run(execute)

    def _read(self, name, index=0):
        value = self.journal.read(name)
        if not isinstance(value, (list, tuple)) or not 0 <= index < len(value):
            raise SensorError('Current PP indexed value is unavailable: ' + name)
        return value[index]

    def _block_index(self, actual):
        for index, block in enumerate(self.runtime.blocks):
            if block.object is actual:
                return index
        raise SensorError('Late block reference requires its SAME owning block object')

    def _maintenance_committed(self):
        active = self.attributes['LightLevelMaintActive']._value
        block = self.attributes['LightLevelMaintBlock']._value
        self.runtime.graph = self.runtime.graph.with_maintenance(
            active=active, block=None if block is None else self._block_index(block))

    def _timer_changed(self, index):
        block = self.runtime.blocks[index]
        if block.timer.value < self.timer_minimum[index].value:
            block.timer.set(self.timer_minimum[index].value)

    def _corridor_before(self, name):
        if self.attribute(name).value is not None:
            current = self.attribute(name).value
            self.timer_minimum[self._block_index(current)].set(0)

    def _corridor_active_changed(self):
        self._corridor_refresh('CorridorLinkCorridorBlock')
        self._corridor_refresh('CorridorLinkOfficeBlock')

    def _corridor_refresh(self, name):
        if self.attribute(name).value is None:
            return
        if self.attribute('CorridorLinkActive').value:
            current = self.attribute(name).value
            if self.runtime.blocks[self._block_index(current)].timer.value < 60:
                current = self.attribute(name).value
                self.runtime.blocks[self._block_index(current)].timer.set(300)
            current = self.attribute(name).value
            self.timer_minimum[self._block_index(current)].set(60)
        else:
            current = self.attribute(name).value
            self.timer_minimum[self._block_index(current)].set(0)

    def _group(self, address, source):
        application = self.runtime.application_object()
        if application is None:
            raise SensorError('Native late group getter dereferences CURRENT nil application')
        return self.runtime.get_source_group(application, address, create=True, source=source)

    def _used(self, name):
        current = self.attribute(name).value
        if current is None:
            raise SensorError('Native IsUnused dereferences a nil group')
        if self.runtime.groups.get(current.identity) is not current:
            raise SensorError('Late group reference requires its actual canonical object')
        return current.identity[1] != 255

    def _bank(self, index, field, value, source):
        self.runtime._event('late_bank_setter', bank=index, field=field, value=value, source=source)
        attribute = {'active': 'active', 'off': 'off', 'low': 'low_lux'}.get(field)
        if attribute is None:
            raise SensorError('Unknown source bank setter')
        getattr(self.live_banks.banks[index], attribute).set(value)

    def load_st7(self):
        def execute():
            if self.loaded_st7 or self.runtime.context is None:
                raise SensorError('ST7 late load requires one completed key-block handoff')
            for name, parameter, kind, source in (
                ('InfraredKeyOffset', 'IRBankKeyOffset', 'key', '0xcf48d2'),
                ('InfraredLightLevelActive', 'PECFunctionIRActive', 'bool', '0xcf48f2'),
                ('InfraredLightLevelKey', 'PECFunctionIRKey', 'key', '0xcf4928'),
                ('InfraredOccupancyActive', 'PIRFunctionIRActive', 'bool', '0xcf4948'),
                ('InfraredOccupancyKey', 'PIRFunctionIRKey', 'key', '0xcf497e'),
                ('IndicatorControl', 'IndicatorControl', 'enum', '0xcf49a3')):
                value = self._read(parameter)
                if kind == 'key':
                    value = self.runtime.keys[value].object
                elif kind == 'bool':
                    value = bool(value)
                self.set(name, value, source=source)
            self.set('LightLevelTargetLux', self._read('PECTargetLux'), source='0xcf49c3')
            target_present = bool(self._read('PECTargetLux'))
            if target_present:
                margin_value = self._read('PECMarginLux')
                margin = margin_percent(self._read('PECTargetLux'), margin_value)
            else:
                margin = 0
            self.set('LightLevelMarginPerc', margin, source='0xcf4a29' if target_present else '0xcf4a3a')
            for index in range(8):
                self._bank(index, 'active', bool(self._read('BlockBankSwitchActive', index)), '0xcf456e')
                self._bank(index, 'off', bool(self._read('BlockGroupLogic', index)), '0xcf458e')
            self.set('LightLevelScale', self._read('PECScaleFactor'), source='0xcf4a61')
            self.set('LightLevelMaintActive', bool(self._read('PECFunctionActive')), source='0xcf4a81')
            self.set('LightLevelMaintBlock', self.runtime.blocks[self._read('PECFunctionBlock')].object,
                     source='0xcf4ab6')
            self.set('LightLevelMaintEnableGroup', self._group(self._read('PECEnablerGroup'), '0xcf4ae6'),
                     source='0xcf4af5')
            self.set('LightLevelMaintEnableGroupOff', bool(self._read('PECEnablerGroupLogic')), source='0xcf4b15')
            self.set('LightLevelBroadcastActive', self._read('BroadcastActive') > 0
                     and self._read('BroadcastActive') < 7, source='0xcf4b55')
            self.set('LightLevelBroadcastBlock', self.runtime.blocks[self._read('BroadcastBlock')].object,
                     source='0xcf4b8a')
            for index in range(8):
                bit = 1 << index
                if self._read('PIRLightMovement') & bit and self._read('PIRDarkMovement') & bit:
                    self.runtime._set_flag(index, 2, True)
                else:
                    self.runtime._set_flag(index, 0, bool(self._read('PIRLightMovement') & bit))
                    self.runtime._set_flag(index, 1, bool(self._read('PIRDarkMovement') & bit))
                    self.runtime._set_flag(index, 2, False)
                self.runtime._set_flag(index, 3, bool(self._read('PIRDark') & bit))
            self.set('OccupancyEnableGroup', self._group(self._read('PIREnablerGroup'), '0xcf4bc1'),
                     source='0xcf4bd0')
            self.set('OccupancyEnableGroupOff', bool(self._read('PIREnablerGroupLogic')), source='0xcf4bf0')
            for name, index, logic, store, sources in (
                ('LightLevel', 9, 'PECEnablerGroupLogic', 'PECLevelStore',
                 ('0xcf471c', '0xcf476a', '0xcf477e', '0xcf47aa', '0xcf47be')),
                ('Occupancy', 8, 'PIREnablerGroupLogic', 'PIRLevelStore',
                 ('0xcf47e8', '0xcf4833', '0xcf4847', '0xcf4873', '0xcf4887'))):
                if self._read(store):
                    state, source = 2, sources[0]
                elif self._read('LightLevel', index) == 255:
                    state, source = (0, sources[1]) if self._read(logic) else (1, sources[2])
                else:
                    state, source = (1, sources[3]) if self._read(logic) else (0, sources[4])
                self.set('PowerUp' + name + 'State', state, source=source)
            for letter, source in (('A', '0xcf4c1c'), ('B', '0xcf4c41')):
                self.set('Potentiometer' + letter + 'Function', self._read('Potentiometer' + letter + 'Function'),
                         source=source)
            for letter, source in (('A', '0xcf4c76'), ('B', '0xcf4cab')):
                self.set('Potentiometer' + letter + 'Block',
                         self.runtime.blocks[self._read('Potentiometer' + letter + 'TimerBlock')].object,
                         source=source)
            self.loaded_st7 = True
        return self.runtime._run(execute)

    def load_surface(self):
        def execute():
            if not self.loaded_st7 or self.loaded_surface:
                raise SensorError('Surface late load follows its ST7 parent once')
            for name, group, store, source in (
                ('Target', 'LightLevelTargetGroup', 'LightLevelTargetGroupLevelStore', '0x12175cc'),
                ('Margin', 'LightLevelMarginGroup', 'LightLevelMarginGroupLevelStore', '0x121763c'),
                ('BankSwitch', 'BankSwitchThresholdGroup', 'BankSwitchGroupLevelStore', '0x12176ac')):
                self.set('PowerUp' + name + 'GroupState', int(bool(self._read(store)) or self._read(group) == 255),
                         source=source)
            for name, source in (('Target', '0x12176e6'), ('Margin', '0x121770c'), ('BankSwitch', '0x1217732')):
                self.set('PowerUp' + name + 'GroupPresetLevel', self._read('PowerUp' + name + 'GroupLevel'),
                         source=source)
            self.set('LightLevelTargetGroup', self._group(self._read('LightLevelTargetGroup'), '0x12177bf'),
                     source='0x12177ce')
            self.set('IsUsingLightLevelTargetGroup', self._used('LightLevelTargetGroup'), source='0x12177f1')
            if self.attribute('IsUsingLightLevelTargetGroup').value:
                self.set('LightLevelTargetLux', 45, source='0x1217814')
                self.journal.capture('LightLevelMarginGroup', [255], source='0x1217836')
            self.set('LightLevelMarginGroup', self._group(self._read('LightLevelMarginGroup'), '0x1217864'),
                     source='0x1217873')
            self.set('IsUsingLightLevelMarginGroup', self._used('LightLevelMarginGroup'), source='0x1217896')
            if self.attribute('IsUsingLightLevelMarginGroup').value:
                self.set('LightLevelMarginPerc', 9, source='0x12178b9')
            if self._read('BankSwitchThresholdBehaviour') == 1:
                self.set('BankSwitchLowGroup', self._group(self._read('BankSwitchThresholdGroup'), '0x1217920'),
                         source='0x121792f')
                self.set('BankSwitchHighGroup', self._group(255, '0x1217951'), source='0x1217960')
            else:
                self.set('BankSwitchHighGroup', self._group(self._read('BankSwitchThresholdGroup'), '0x121799a'),
                         source='0x12179a9')
                self.set('BankSwitchLowGroup', self._group(255, '0x12179cb'), source='0x12179da')
            for index in range(8):
                value = bool(self._read('BankSwitchGroupUsed', index)) and self._used('BankSwitchLowGroup')
                self.runtime._event('late_surface_bank_use', bank=index, field='low', value=value,
                                    source='0x1217a4f')
                self.use_low[index].set(value)
                value = bool(self._read('BankSwitchGroupUsed', index)) and self._used('BankSwitchHighGroup')
                self.runtime._event('late_surface_bank_use', bank=index, field='high', value=value,
                                    source='0x1217a9e')
                self.use_high[index].set(value)
                if self.use_low[index].value:
                    self._bank(index, 'low', 0, '0x1217ad8')
            self.loaded_surface = True
        return self.runtime._run(execute)


__all__ = ['SENLLALateUnit']
