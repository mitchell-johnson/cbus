"""Source-owned damper panel callbacks in one fresh settings-model history.

This private model is created after ordinary load. It is not a transferable
continuation: native plans seal/replay the complete source snapshot and graph.
Direct InstalledZones property writes expose notification intents; callers
explicitly request UpdateDamperGroups. No host subscriber dispatch is inferred.
"""
from __future__ import annotations

from collections.abc import Mapping

from .edlt_add_dialog import _upper
from .thermostat_post_load import DAMPERS, DAMPER_NAMES, OUTPUTS, RELAYS, damper_modulation_save, pp_name
from .thermostat_templates import ThermostatTemplateError

DAMPER_READ_FIELDS = ('InstalledZones', 'DamperModulationEnable')
OPS = frozenset(('damper-form-show', 'damper-after-show', 'damper-group-change',
    'damper-modulation-binding', 'damper-modulation-click', 'damper-zone-update',
    'damper-installed-zones'))


def normalize_damper_operation(row):
    """Validate request syntax only; no owner/model decisions occur here."""
    op = row.get('op') if isinstance(row, Mapping) else None
    if type(op) is not str:
        raise ThermostatTemplateError('Output operation name must be a string')
    if op not in OPS:
        return None
    expected = {'op'}
    if op == 'damper-group-change':
        expected.add('zone')
    elif op in ('damper-modulation-binding', 'damper-modulation-click'):
        expected.add('checked')
    elif op == 'damper-installed-zones':
        expected.add('value')
    if set(row) != expected:
        raise ThermostatTemplateError(op + ' requires exactly ' + ', '.join(sorted(expected)))
    result = {'op': op}
    if 'zone' in expected:
        if type(row['zone']) is not int or not 1 <= row['zone'] <= 4:
            raise ThermostatTemplateError('Damper callback zone must be an integer in 1..4')
        result['zone'] = row['zone']
    if 'checked' in expected:
        if type(row['checked']) is not bool:
            raise ThermostatTemplateError('Damper checked state must be Boolean')
        result['checked'] = row['checked']
    if 'value' in expected:
        if type(row['value']) is not int or not 0 <= row['value'] <= 31:
            raise ThermostatTemplateError('Damper InstalledZones must be an integer mask in 0..31')
        result['value'] = row['value']
    return result


class DamperControlModel:
    """Private fresh PlantControlService plus explicitly entered panel events.

    Cache initialization relies on source allocation/AfterLoad before hooks.
    Opening or reopening the panel never reinitializes these four caches.
    """

    def __init__(self, owner):
        from .thermostat_output_groups import OutputGroupModel
        if type(owner) is not OutputGroupModel or set(owner.loaded) != set(OUTPUTS + DAMPERS + RELAYS) or set(owner.references) != set(owner.loaded):
            raise ThermostatTemplateError('Damper controls require this fresh loaded output owner')
        self._owner = owner
        self.cache = [None] * 4
        self.warnings = [False] * 4
        self.shown = False
        self.after_show_installed = False
        self.help_bound = False
        self.checked = False
        self.modulation = owner.values['DamperModulationEnable'] != 0
        self.installed_zones = owner.values['InstalledZones'] & 31
        self.overrides = {}
        self.operations = []
        self.alerts = []

    def _live(self, value):
        if value is None:
            return None
        live = self._owner.resolver.current(value)
        if live is None or live.identity != value.identity:
            raise ThermostatTemplateError('Damper retained object identity no longer belongs to its owner')
        return live

    def _group(self, value):
        value = self._live(value)
        return None if value is None else {'application': value.application,
            'address': value.address, 'identity': value.identity, 'name': value.name}

    def _state(self):
        return {'model_references': [self._group(self._owner.references[role]) for role in DAMPERS],
            'caches': [self._group(value) for value in self.cache], 'warnings': list(self.warnings),
            'checked': self.checked, 'model_modulation': self.modulation,
            'installed_zones': self.installed_zones, 'shown': self.shown,
            'after_show_installed': self.after_show_installed, 'help_bound': self.help_bound}

    def _group_change(self, zone, bound_value):
        # The tracked handle's RootElement is an ObjectReferenceAttribute;
        # GetFlashObject reads its value, rather than ComboBox.SelectedItem.
        from .thermostat_remote_references import RemoteGroup
        row = {'callback': 'cmbGroupChange', 'zone': zone,
               'controller_identity': None, 'cache_written': False, 'warning_written': False}
        if type(bound_value) is not RemoteGroup:
            row['branch'] = 'nil-or-non-group'
            return row
        selected = self._live(bound_value)
        row['controller_identity'] = selected.identity
        relay_ids = {group.identity for role in RELAYS
                     if (group := self._owner.references[role]) is not None}
        internal = self._owner.unit_type in ('PC_TSA5', 'PC_TSB5') and selected.identity in relay_ids
        self.warnings[zone - 1] = selected.address != 255 and not internal
        row.update(warning_written=True, warning=self.warnings[zone - 1],
                   internal_relay=internal, branch='unused' if selected.address == 255 else 'group')
        if selected.address != 255:
            # Deliberately read the model getter independently of the bound
            # controller result. Pure source tests can demonstrate stale roots.
            current = self._owner.references[DAMPERS[zone - 1]]
            self.cache[zone - 1] = current
            row.update(cache_written=True, cached_identity=current.identity if current else None)
        return row

    def _find_or_create(self, zone):
        owner = self._owner
        role = DAMPERS[zone - 1]
        tag = owner.prefix + ' ' + DAMPER_NAMES[role]
        inventory = [group for (app, _), group in owner.resolver.live.items() if app == owner.application]
        matches = [group for group in inventory if _upper(group.name) == _upper(tag)]
        if len(matches) > 1:
            raise ThermostatTemplateError('Generated damper group name is ambiguous without original manager order: ' + tag)
        found = matches[0] if matches else None
        owner.resolver.getters.append({'getter': 'FindExistingGroup', 'role': 'damper_zone_update:' + str(zone),
            'application': owner.application, 'name': tag, 'identity': found.identity if found else None})
        owner.references[role] = found
        if found is None and owner.master:
            addresses = {group.address for group in inventory}
            free = next((address for address in range(255) if address not in addresses), None)
            if free is None:
                raise ThermostatTemplateError('Group capacity prevents creating a missing installed damper group')
            owner.resolver.getters.append({'getter': 'GetNextAvailableAddress', 'role': role,
                'application': owner.application, 'address': free})
            # Source GroupByAddress(create=True) followed by ChangeTagName.
            created = owner.resolver.group(owner.application, free, True,
                'damper_zone_update:' + str(zone), enable_application=False)
            owner.references[role] = owner.resolver.rename(created, tag, 'damper_zone_update:' + str(zone))
        return owner.references[role]

    def _update(self):
        rows = []
        for zone, role in enumerate(DAMPERS, 1):
            current = self._live(self._owner.references[role])
            installed = bool(self.installed_zones & (1 << zone))
            row = {'zone': zone, 'installed': installed,
                   'before_identity': current.identity if current else None,
                   'cache_written': False, 'cache_restored': False, 'default_lookup': False}
            if installed:
                if current is None or current.address == 255:
                    current = self._live(self.cache[zone - 1])
                    self._owner.references[role] = current
                    row['cache_restored'] = True
                if current is None or current.address == 255:
                    current = self._find_or_create(zone)
                    row['default_lookup'] = True
            else:
                if self.cache[zone - 1] is None and current is not None and current.address != 255:
                    self.cache[zone - 1] = current
                    row['cache_written'] = True
                current = self._owner._unused('damper_zone_update:' + str(zone))
                self._owner.references[role] = current
            row['after_identity'] = current.identity if current else None
            rows.append(row)
        return rows

    def process(self, row, position):
        row = normalize_damper_operation(row)
        if row is None:
            raise ThermostatTemplateError('Expected a normalized damper control operation')
        op = row['op']
        if op not in ('damper-form-show', 'damper-zone-update', 'damper-installed-zones') and not self.shown:
            raise ThermostatTemplateError('Damper panel callback requires preceding damper-form-show')
        before = self._state()
        receipt = {'position': position, **row, 'before': before, 'source_calls': []}
        if op == 'damper-form-show':
            self.shown = True
            self.checked = self.modulation
            receipt['source_calls'].append('SetupFlashComponents')
            receipt['checkbox_setup_click_suppressed'] = True
            for zone, role in enumerate(DAMPERS, 1):
                receipt['source_calls'].append(self._group_change(zone, self._owner.references[role]))
            self.after_show_installed = True
            receipt['source_calls'].extend(('InstallHandleAfterShow', 'ExternalRelays.Initialise'))
            receipt['external_relay_view_only'] = True
            receipt['external_relay_rendering_reproduced'] = False
        elif op == 'damper-after-show':
            self.help_bound = True
            receipt['source_calls'].append('HandleAfterShow:bind-help')
        elif op == 'damper-group-change':
            zone = row['zone']
            receipt['source_calls'].append(self._group_change(zone, self._owner.references[DAMPERS[zone - 1]]))
        elif op == 'damper-modulation-binding':
            self.checked = row['checked']
            self.modulation = self.checked
            self.overrides['DamperModulationEnable'] = int(self.modulation)
            receipt['source_calls'].extend(('TFlashCheckBox.Change', 'TFlashBooleanController.SetAsBoolean',
                                           'UpdateEnableState'))
        elif op == 'damper-modulation-click':
            self.checked = row['checked']
            receipt['source_calls'].append('TCustomCheckBox.GetChecked')
            if self.checked:
                alert = {'position': position, 'code': 7323, 'context': 'WHITE', 'result_consumed': False,
                         'modal_rendering_reproduced': False}
                self.alerts.append(alert)
                receipt['source_calls'].append({'CISError': 7323, 'context': 'WHITE', 'result_consumed': False})
        elif op == 'damper-installed-zones':
            previous = self.installed_zones
            target = row['value']
            writes = []
            partial = previous
            for bit in range(5):
                enabled = bool(target & (1 << bit))
                changed = enabled != bool(partial & (1 << bit))
                partial = (partial | (1 << bit)) if enabled else (partial & ~(1 << bit))
                writes.append({'zone': bit, 'value': enabled, 'changed': changed,
                    'notification_intent': changed, 'intermediate_mask': partial})
            self.installed_zones = target
            self.overrides['InstalledZones'] = target
            receipt.update(source_calls=['TZones.SetZones'], boolean_writes=writes,
                           automatic_subscriber_dispatch_reproduced=False)
        else:
            receipt['source_calls'].append('UpdateDamperGroups')
            receipt['zone_updates'] = self._update()
        receipt['after'] = self._state()
        receipt['changed_model_or_panel_state'] = receipt['after'] != before
        self.operations.append(receipt)
        return receipt

    @property
    def model_overrides(self):
        return dict(self.overrides)

    @property
    def expected(self):
        result = {}
        if 'InstalledZones' in self.overrides:
            result['InstalledZones'] = self.installed_zones
            result['ControlledZones'] = self.installed_zones if self._owner.master else 0
        if 'DamperModulationEnable' in self.overrides:
            result['DamperModulationEnable'] = damper_modulation_save(self.modulation, self._owner.plant)
        return result

    def as_dict(self):
        return {'profile': 'fresh-ordinary-model-explicit-damper-callbacks-v1',
            'initial_cache_provenance': 'fresh-zero-initialized-plant-before-hooked-ordinary-load',
            **self._state(), 'operations': self.operations, 'alerts': self.alerts,
            'model_overrides': self.model_overrides, 'expected': self.expected,
            'same_owner_only': True, 'detached_receipt_continuation_admitted': False,
            'automatic_subscriber_dispatch_reproduced': False,
            'quick_zone_gui_reproduced': False, 'application_migration_reproduced': False,
            'complete_form_lifecycle_reproduced': False, 'physical_device_programmed': False}
