"""Persistent late light-form lists and synchronous source handlers.

Every predicate reads the actual retained attribute at its native position.
List population never adopts the detached choices from a final graph. This is
the fresh no-HWND control slice; the full director, scalar binding, show and
Apply schedule is still owned by the complete workflow.
"""
from .senlla_control_primitives import (
    NativeText, ProgrammaticCollection, ProgrammaticCombo, SourceDisplayPreferences)
from .senlla_late_unit import SENLLALateUnit
from .sensors import SensorError


class SENLLALateForms:
    def __init__(self, late_unit, *, text=None):
        if not isinstance(late_unit, SENLLALateUnit):
            raise SensorError('Late forms require the SAME concrete late Unit owner')
        if not late_unit.loaded_surface:
            raise SensorError('Late form handlers require completed ST7 and Surface loading')
        if text is not None and not isinstance(text, NativeText):
            raise SensorError('Late form comparison requires its concrete native text authority')
        self.late, self.runtime = late_unit, late_unit.runtime
        self.bridge = late_unit.inherited.bridge
        self.text = text or NativeText()
        self.maintenance_combo = ProgrammaticCombo('maintenance', self.text)
        self.broadcast_combo = ProgrammaticCombo('broadcast', self.text)
        self.broadcast_collection = ProgrammaticCollection('light.broadcast.blocks')
        # Flash list Changed marks dirty and updates enable state; it does not
        # synchronously run PopulateList, DoIndexChange or deferred messages.
        self.broadcast_collection.publisher.subscribe(self._broadcast_list_changed)
        self.maintenance_checked_control = self.broadcast_checked_control = False
        self.maintenance_panel_enabled = self.broadcast_panel_enabled = True
        self.pec_logic_enabled = self.pir_logic_enabled = True
        self.events = []

    def _event(self, operation, **facts):
        self.events.append(dict(operation=operation, **facts))

    def _get(self, name, source):
        self._event('unit_getter', field=name, source=source)
        return self.late.attribute(name).value

    def _set(self, name, value, source):
        return self.late.set(name, value, source=source)

    def _group(self, actual):
        if actual is None or self.runtime.groups.get(actual.identity) is not actual:
            raise SensorError('Native late form dereferences a nil or unavailable group')
        return actual

    def _unused(self, actual):
        return self._group(actual).identity[1] == 255

    def _block_index(self, actual):
        if actual not in self.runtime._block_indices:
            raise SensorError('Late form requires the SAME nonnil block object')
        return self.runtime._block_indices[actual]

    def _block_text(self, index, source):
        block = self.runtime.blocks[index]
        group = block.group.value
        if group is None:
            label = ''
        else:
            self._group(group)
            label = self.bridge.display_text(self.runtime, group, source=source)
            group.resolve_change()
        text = SourceDisplayPreferences.block_text(index, label)
        block.object.resolve_change()
        return text

    def _is_scene(self, key):
        current = self.runtime.keys[key].template.value
        return current is not None and current.identity in (23, 24, 25)

    def _has_block(self, key, actual):
        return actual is not None and self._block_index(actual) in self.runtime.keys[key].refs

    def _blocks(self, source):
        self.runtime.block_collection.resolve_change()
        self._event('block_collection_count', source=source, count=len(self.runtime.blocks))
        return self.runtime.blocks

    def _broadcast_list_changed(self, _):
        self.broadcast_combo.dirty = True
        self._event('broadcast_list_dirty', count=len(self.broadcast_collection.items))

    def _groups(self, secondary):
        application = self.runtime.application_object(secondary)
        if application is None:
            raise SensorError('Native maintenance list dereferences a nil application')
        return self.bridge.group_items(self.runtime, application)

    def populate_maintenance(self):
        return self.runtime._run(self._populate_maintenance)

    def _populate_maintenance(self):
        combo = self.maintenance_combo
        free = False
        combo.begin_items()
        try:
            combo.clear_items()
            for index, block in enumerate(self._blocks('0xfa8271')):
                if (self._get('LightLevelBroadcastActive', '0xfa8290')
                        and self._get('LightLevelMaintActive', '0xfa829f')
                        and block.object is self._get('LightLevelBroadcastBlock', '0xfa82c2')):
                    continue
                if self.late.live_banks.banks[index].active.value:
                    continue
                combo.add_item(block.object, self._block_text(index, '0xfa8309'))
                if (not free and self._unused(block.group.value)
                        and not self._is_scene(index)):
                    free = True
            if free:
                self._append_groups(False)
                secondary = self.runtime.application_object(True)
                if secondary is None:
                    raise SensorError('Native maintenance list dereferences nil App2 address')
                if secondary.identity != 255:
                    self._append_groups(True)
        finally:
            combo.end_items()

    def _append_groups(self, secondary):
        count = len(self._groups(secondary))
        for ordinal in range(count):
            rows = self._groups(secondary)
            if ordinal >= len(rows):
                raise SensorError('Native maintenance manager index became unavailable')
            group = rows[ordinal]
            if self._unused(group):
                continue
            if any(block.group.value is group for block in self._blocks(
                    '0xfa8557' if secondary else '0xfa840f')):
                continue
            record = self.bridge.current_record(self.runtime, group)
            app = self.runtime.apps[group.identity[0]]
            application_record = self.bridge.current_record(self.runtime, app)
            label = record['tag_name'] + ' (' + application_record['tag_name'] + ')'
            self.maintenance_combo.add_item(group, label)

    def populate_broadcast(self):
        return self.runtime._run(self._populate_broadcast)

    def _populate_broadcast(self):
        combo = self.broadcast_combo
        combo.begin_items()
        try:
            self.broadcast_collection.clear()
            for index, block in enumerate(self._blocks('0xfa8075')):
                if (self._get('LightLevelMaintActive', '0xfa8096')
                        and self._get('LightLevelBroadcastActive', '0xfa80a5')
                        and block.object is self._get('LightLevelMaintBlock', '0xfa80ca')):
                    continue
                include = True
                for key in range(len(self.runtime.keys)):
                    if self._has_block(key, block.object) and (
                            self._is_scene(key) or any(self.runtime.current_occupancy_flags(key))):
                        include = False
                        break
                if include:
                    self.broadcast_collection.append(block.object)
        finally:
            combo.end_items()

    def pec_enable_changed(self):
        return self.runtime._run(self._pec_enable_changed)

    def _pec_enable_changed(self):
        unused = self._unused(self._get('LightLevelMaintEnableGroup', '0xfa7876'))
        if unused:
            self._set('LightLevelMaintEnableGroupOff', False, '0xfa7891')
            self.pec_logic_enabled = False
        else:
            self.pec_logic_enabled = self._get('LightLevelMaintActive', '0xfa78c1')

    def pir_enable_changed(self):
        def execute():
            unused = self._unused(self._get('OccupancyEnableGroup', '0xfaf7ae'))
            if unused:
                self._set('OccupancyEnableGroupOff', False, '0xfaf7c9')
            self.pir_logic_enabled = not unused
        return self.runtime._run(execute)

    def maintenance_checked(self):
        return self.runtime._run(self._maintenance_checked)

    def _maintenance_checked(self):
        if not self._unused(self._get('LightLevelMaintEnableGroup', '0xfa740f')):
            collision = False
            for name, pec_source, other_source in (
                    ('JoinGroup', '0xfa7427', '0xfa7434'),
                    ('DualJoinGroup', '0xfa7447', '0xfa7454'),
                    ('OccupancyEnableGroup', '0xfa7463', '0xfa7470')):
                if self._get('LightLevelMaintEnableGroup', pec_source) is self._get(name, other_source):
                    collision = True
                    break
            if not collision:
                collision = (self._get('LightLevelMaintEnableGroup', '0xfa747f')
                    is self._get('CorridorLinkGroup', '0xfa748c')
                    and self._get('CorridorLinkActive', '0xfa749b'))
            if not collision:
                group = self._get('LightLevelMaintEnableGroup', '0xfa74aa')
                collision = any(block.group.value is group for block in self._blocks('0xd10480'))
            if collision:
                app = self.runtime.application_object()
                if app is None:
                    raise SensorError('PEC collision dereferences CURRENT nil primary application')
                group = self.runtime.get_source_group(app, 255, create=False, source='0xfa74e1')
                self._set('LightLevelMaintEnableGroup', group, '0xfa74ee')
        if (self._get('LightLevelBroadcastActive', '0xfa74f9')
                and self._get('LightLevelMaintActive', '0xfa7508')
                and self._get('LightLevelBroadcastBlock', '0xfa7517')
                is self._get('LightLevelMaintBlock', '0xfa7524')):
            self._populate_maintenance()
            self.maintenance_combo.set_index(0)
        self.maintenance_panel_enabled = self.maintenance_checked_control
        self._pec_enable_changed()
        self._populate_broadcast()

    def broadcast_checked(self):
        return self.runtime._run(self._broadcast_checked)

    def _broadcast_checked(self):
        self.broadcast_panel_enabled = self.broadcast_checked_control
        if self._get('LightLevelBroadcastActive', '0xfa725a'):
            for key in range(len(self.runtime.keys)):
                if self._has_block(key, self._get('LightLevelBroadcastBlock', '0xfa72a7')):
                    for flag, source in enumerate(('0xfa72d2', '0xfa72ed', '0xfa7308', '0xfa7323')):
                        self._event('occupancy_setter', key=key, flag=flag, value=False, source=source)
                        self.runtime._set_flag(key, flag, False)
                    if self._is_scene(key):
                        self.runtime.set_template(key, 16)
            if (self._get('LightLevelMaintActive', '0xfa7380')
                    and self._get('LightLevelBroadcastBlock', '0xfa738f')
                    is self._get('LightLevelMaintBlock', '0xfa739c')):
                self._populate_broadcast()
                if not self.broadcast_collection.items:
                    raise SensorError('Native broadcast fallback indexes an empty candidate collection')
                self._set('LightLevelBroadcastBlock', self.broadcast_collection.items[0], '0xfa73d1')
        # The normal fresh owner has no external form callback installed.
        self._populate_maintenance()

    def install_maintenance_change(self):
        self.maintenance_combo.property_on_change = lambda _: self.maintenance_combo_changed()
        self._event('properties_on_change_installed', source='0xfa8c54')

    def setup_maintenance_selection(self):
        def execute():
            self.install_maintenance_change()
            block = self._get('LightLevelMaintBlock', '0xfa8c61')
            label = self._block_text(self._block_index(block), '0xfa8c6b')
            index = self.text.index_of([text for _, text in self.maintenance_combo.items], label)
            self.maintenance_combo.set_index(index)
        return self.runtime._run(execute)

    def maintenance_combo_changed(self):
        def execute():
            combo = self.maintenance_combo
            index = combo.item_index
            if not 0 <= index < len(combo.items):
                return
            current = combo.items[index][0]
            if current in self.runtime._block_indices:
                self._set('LightLevelMaintBlock', current, '0xfa77f3')
            elif getattr(current, 'kind', None) == 'group':
                self._set_maintenance_group(self._group(current))
        return self.runtime._run(execute)

    def _set_maintenance_group(self, group):
        for index, block in enumerate(self._blocks('0xfa86ab')):
            if self._unused(block.group.value) and not self._is_scene(index):
                secondary = self.runtime.application_object(True)
                block.secondary.set(self.runtime.apps[group.identity[0]] is secondary)
                block.group.set(group)
                self._set('LightLevelMaintBlock', block.object, '0xfa8775')
                return

    def maintenance_block_changed(self, expression_text):
        def execute():
            if not isinstance(expression_text, str):
                raise SensorError('Maintenance expression callback requires CURRENT display text')
            if (self._get('LightLevelMaintActive', '0xfa76f4')
                    and self._get('LightLevelBroadcastActive', '0xfa7703')
                    and self._get('LightLevelMaintBlock', '0xfa7712')
                    is self._get('LightLevelBroadcastBlock', '0xfa771f')):
                self._populate_maintenance()
                self.maintenance_combo.set_index(0)
            else:
                index = self.text.index_of([text for _, text in self.maintenance_combo.items], expression_text)
                self.maintenance_combo.set_index(index)
                self._populate_broadcast()
        return self.runtime._run(execute)


__all__ = ['SENLLALateForms']
