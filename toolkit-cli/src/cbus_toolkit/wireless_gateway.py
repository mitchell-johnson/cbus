"""Toolkit Wireless to wired gateway (2.x) Remote Switch mode remote mapping.

This edits an existing native PP session for the one admitted profile,
WGATE5F firmware 2.2.90..2.4.99 (``WGATE5X_2.xml``). Toolkit 1.18 registers
only that identity with ``TCBusWirelessGatewayAdvancedUnit``, whose
``TCBusWirelessGatewayAdvancedCGateAgent`` loads and saves the Remotes tab.
The editor reproduces the Mode radio group, the eight Remote Control pages
and their Key Function / Key Assignment / application-switch controls, and
the agent's save encoding for those controls. It does not create project
remote-control units, groups or scenes, and it never touches the radio link.
See docs/wireless.md.
"""
from dataclasses import dataclass, replace
import re
from types import MappingProxyType
import xml.etree.ElementTree as ET

from .macros import _numbers
from .memory import MemoryCodec
from .programming import xml_text
from .unitspec import version_matches


class WirelessGatewayError(ValueError):
    pass


class WirelessGatewayApplyError(RuntimeError):
    def __init__(self, cause, attempted):
        self.cause, self.attempted = cause, tuple(attempted)
        self.details = {'attempted_parameters': list(self.attempted), 'saved': False, 'device_verified': False}
        super().__init__('Wireless gateway remote mapping stopped; PP changes may be partial and were not saved: '
                         + str(cause))


PLAN_FORMAT = 'cbus-wireless-gateway-remotes-plan-v1'
VIEW_FORMAT = 'cbus-wireless-gateway-remotes-v1'
SPEC_FILENAME = 'WGATE5X_2.xml'
UNIT_TYPE = 'WGATE5F'
# TUnitTypeFactory.RegisterUnitType('WGATE5F', '2.2.90', '2.4.99',
# TCBusWirelessGatewayAdvancedUnit); every other WGATE5N/WGATE5F range uses
# TCBusWirelessGatewayUnit, which has no Remote Switch mode or Remotes tab.
FIRMWARE_RANGE = ('2.2.90', '2.4.99')
REFUSED = MappingProxyType({
    'WGATE5N': ('Toolkit registers WGATE5N at every firmware with TCBusWirelessGatewayUnit; its dialog has no '
                'Remote Switch mode or Remotes tab even though WGATE5X_2.xml declares the parameters'),
})
REMOTES = 8
SLOTS = 16
DIALOG_KEYS = 10   # TWTXU.GetKeyCount
NO_REMOTE = 0xFFFFFFFF
NO_GROUP = 0xFF
# CIS_TWTXU.cWTXUKeyMap: TWTXU.GetRemoteKeyMap maps dialog key index k to a PP
# slot. Save and load use it only while a remote unit is selected; without a
# remote both use the identity map.
WTXU_KEY_MAP = (4, 3, 2, 1, 0, 12, 11, 10, 9, 8, 7, 6, 5, 15, 14, 13)
# TCBusWirelessGatewayAdvancedUnit.RegisterEnumerations order.
KEY_FUNCTIONS = ('group', 'scene-set', 'scene-toggle')
KEY_FUNCTION_LABELS = MappingProxyType({'group': 'Group Dimmer', 'scene-set': 'Scene Set',
                                        'scene-toggle': 'Scene Toggle'})
# EncodeScene: (scene << 4) + (1 for Scene Set, else 6).
SCENE_COMMANDS = MappingProxyType({'scene-set': 1, 'scene-toggle': 6})
MODES = ('network-gateway', 'remote-switch')   # rgMode item order; MapWirelessRemotes = ItemIndex

_REMOTE_ROWS = {}
for _r in range(REMOTES):
    _REMOTE_ROWS[f'RemoteIdentity{_r + 1}'] = (0x70 + 4 * _r, 4, 8, 0, 0, 'int')
    _REMOTE_ROWS[f'KeySceneMask{_r + 1}'] = (0x90 + 2 * _r, SLOTS, 1, 0, 0, 'bit')
    _REMOTE_ROWS[f'ApplicationSeconday{_r + 1}'] = (0xA0 + 2 * _r, SLOTS, 1, 0, 0, 'bit')
    _REMOTE_ROWS[f'GroupAddress{_r + 1}'] = (0xB0 + 16 * _r, SLOTS, 8, 0, 0, 'int')
# Address, count, bit size, bit offset, array skip, type.
OWNED = MappingProxyType({'MapWirelessRemotes': (0x41, 1, 1, 3, 0, 'bit'), **_REMOTE_ROWS})
# Read-only dependencies checked by the Toolkit controls and stale-checked.
DEPENDENCIES = MappingProxyType({
    'Application': (0x21, 2, 8, 0, 0, 'int'),
    'SceneTriggerGroup': (0x130, 8, 8, 0, 0, 'int'),
    'SceneVectorOffset': (0x150, 8, 8, 0, 0, 'int'),
})
LAYOUT = MappingProxyType({**OWNED, **DEPENDENCIES})
FIELDS = tuple(LAYOUT)


def _integer(value, label, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise WirelessGatewayError(f'{label} must be an integer in {minimum}..{maximum}')
    return value


def _version(value):
    return value if isinstance(value, str) and re.fullmatch(r'[0-9]{1,4}(\.[0-9]{1,4}){1,3}', value) else None


def profile_refusal(unit_type, firmware):
    """Return why a unit identity is outside the admitted profile, or None."""
    if unit_type != UNIT_TYPE:
        return REFUSED.get(unit_type, 'Only WGATE5F wireless gateways use the Remote Switch workflow')
    version = _version(firmware)
    if version is None or not version_matches(version, *FIRMWARE_RANGE):
        return (f'{UNIT_TYPE} firmware outside {FIRMWARE_RANGE[0]}..{FIRMWARE_RANGE[1]} uses '
                'TCBusWirelessGatewayUnit without the Remotes tab')
    return None


def check_profile(unit_type, firmware, catalog_number=None, *, subject='Unit identity'):
    reason = profile_refusal(unit_type, firmware)
    if reason is not None:
        raise WirelessGatewayError(f'{subject} must be an admitted {UNIT_TYPE} {FIRMWARE_RANGE[0]}..'
                                   f'{FIRMWARE_RANGE[1]} gateway: {reason}')
    return (unit_type, firmware, catalog_number)


def serial_from_bytes(values):
    """GetRemoteSerial: little-endian 32-bit identity; FFFFFFFF means no remote."""
    return sum(int(v) << (8 * i) for i, v in enumerate(values))


def serial_to_bytes(serial):
    return tuple((serial >> (8 * i)) & 0xFF for i in range(4))


def scene_count(offsets):
    """LoadScenes creates one scene per SceneVectorOffset entry != 255 with (v & 0x7F) < 100."""
    return sum(1 for value in offsets if value != 0xFF and (value & 0x7F) < 100)


def decode_slot(mask, secondary, value):
    """The Toolkit view of one PP key slot (LoadRemoteKeys)."""
    if mask:
        command = value & 0x0F
        # GetKeyFunction: command 1 is Scene Set; every other command loads as
        # Scene Toggle and a Toolkit save writes it back as command 6.
        function = 'scene-set' if command == 1 else 'scene-toggle'
        return {'function': function, 'label': KEY_FUNCTION_LABELS[function], 'scene': (value >> 4) + 1,
                'raw': {'mask': 1, 'secondary': secondary, 'value': value}}
    return {'function': 'group', 'label': KEY_FUNCTION_LABELS['group'],
            'application': 'secondary' if secondary else 'primary',
            'group': None if value == NO_GROUP else value,
            'raw': {'mask': 0, 'secondary': secondary, 'value': value}}


def parse_assignment(text):
    """Parse ``group:G[:secondary]``, ``group:none``, ``scene-set:N`` or ``scene-toggle:N``."""
    if not isinstance(text, str):
        raise WirelessGatewayError('Key assignment must be text')
    parts = text.strip().lower().split(':')
    function = parts[0]
    try:
        if function == 'group' and len(parts) in (2, 3):
            group = None if parts[1] == 'none' else int(parts[1], 0)
            application = parts[2] if len(parts) == 3 else 'primary'
            return {'function': 'group', 'group': group, 'application': application}
        if function in SCENE_COMMANDS and len(parts) == 2:
            return {'function': function, 'scene': int(parts[1], 10)}
    except ValueError as error:
        raise WirelessGatewayError('Key assignment numbers must be integers') from error
    raise WirelessGatewayError('Key assignment must be group:G[:primary|secondary], group:none, '
                               'scene-set:N or scene-toggle:N')


def verify_native_schema(session, spec, fields, error):
    """Require the native PP schema to match the decoded spec for ``fields``."""
    document = xml_text(session.info('*'))
    if '<!DOCTYPE' in document.upper() or '<!ENTITY' in document.upper():
        raise error('Unsupported native schema declarations')
    try:
        root = ET.fromstring(document)
    except ET.ParseError as parse_error:
        raise error('Invalid native parameter schema') from parse_error
    found = {}
    for param in root.iter():
        if param.tag.rsplit('}', 1)[-1] == 'Param':
            row = {child.tag.rsplit('}', 1)[-1]: child.text or '' for child in param}
            if row.get('Name') in found:
                raise error('Duplicate native parameter schema')
            found[row.get('Name')] = row
    for name in fields:
        native, local = found.get(name, {}), spec.get(name).fields
        if native.get('Type', '').lower() != local.get('Type', '').lower():
            raise error('Native parameter type mismatch: ' + name)
        for field, default in (('Address', None), ('ArraySize', '1'), ('BitAddress', '0'), ('ArraySkip', '0')):
            if _numbers(native.get(field, default)) != _numbers(local.get(field, default)):
                raise error(f'Native parameter layout mismatch: {name}/{field}')


@dataclass(frozen=True)
class WirelessGatewayPlan:
    expected: dict
    changes: dict
    remote: int | None = None
    raw_slot_edits: tuple = ()
    identity: tuple | None = None

    def __post_init__(self):
        for name in ('expected', 'changes'):
            object.__setattr__(self, name, MappingProxyType({k: tuple(v) for k, v in getattr(self, name).items()}))

    def as_dict(self):
        firmware, catalog_number = self.identity[1:] if self.identity else (None, None)
        return {'format': PLAN_FORMAT, 'unit_type': UNIT_TYPE, 'firmware': firmware,
                'catalog_number': catalog_number, 'firmware_admitted': list(FIRMWARE_RANGE),
                'spec_filename': SPEC_FILENAME, 'remote': self.remote,
                'raw_slot_edits': list(self.raw_slot_edits),
                'expected': {k: list(v) for k, v in self.expected.items()},
                'changes': {k: list(v) for k, v in self.changes.items()},
                'saved': False, 'device_verified': False}

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict) or data.get('format') != PLAN_FORMAT:
            raise WirelessGatewayError('Expected a ' + PLAN_FORMAT + ' document')
        if data.get('unit_type') != UNIT_TYPE:
            raise WirelessGatewayError('Plan unit type is not admitted')
        try:
            expected = {str(k): tuple(v) for k, v in data['expected'].items()}
            changes = {str(k): tuple(v) for k, v in data['changes'].items()}
        except (KeyError, AttributeError, TypeError) as error:
            raise WirelessGatewayError('Plan requires expected and changes mappings') from error
        firmware = data.get('firmware')
        identity = None if firmware is None else check_profile(UNIT_TYPE, firmware, data.get('catalog_number'))
        return cls(expected, changes, data.get('remote'), tuple(data.get('raw_slot_edits') or ()), identity)


class WirelessGatewayEditor:
    def __init__(self, spec):
        if spec.filename != SPEC_FILENAME:
            raise WirelessGatewayError(f'Use {SPEC_FILENAME} for {UNIT_TYPE} {FIRMWARE_RANGE[0]}..{FIRMWARE_RANGE[1]}')
        self.spec, self.codec = spec, MemoryCodec(spec)
        for name, expected in LAYOUT.items():
            try:
                layout = self.codec.layout(name)
            except Exception as error:  # noqa: BLE001 - any spec defect is a refusal
                raise WirelessGatewayError('Unsupported wireless gateway parameter layout: ' + name) from error
            actual = (layout.address, layout.array_size, layout.bit_size, layout.bit_address,
                      layout.array_skip, layout.parameter.type)
            if actual != expected:
                raise WirelessGatewayError('Unsupported wireless gateway parameter layout: ' + name)

    def snapshot(self, current):
        result = {}
        for name in FIELDS:
            if name not in current:
                raise WirelessGatewayError('Missing current wireless gateway parameter: ' + name)
            try:
                values = _numbers(current[name])
            except ValueError as error:
                raise WirelessGatewayError('Invalid current wireless gateway parameter: ' + name) from error
            if not self.spec.get(name).validate_value(list(values))['valid']:
                raise WirelessGatewayError('Invalid current wireless gateway parameter: ' + name)
            result[name] = values
        return result

    # ---- read model -------------------------------------------------
    def show(self, current):
        """Project the stored values the way the Toolkit Mode and Remotes controls load them."""
        values = self.snapshot(current)
        count = scene_count(values['SceneVectorOffset'])
        effects = []
        remotes = []
        for r in range(1, REMOTES + 1):
            serial = serial_from_bytes(values[f'RemoteIdentity{r}'])
            assigned = serial != NO_REMOTE
            slot_map = WTXU_KEY_MAP if assigned else tuple(range(SLOTS))
            keys = []
            for k, slot in enumerate(slot_map):
                row = decode_slot(values[f'KeySceneMask{r}'][slot], values[f'ApplicationSeconday{r}'][slot],
                                  values[f'GroupAddress{r}'][slot])
                row = {'key': k + 1 if assigned and k < DIALOG_KEYS else None, 'slot': slot + 1, **row}
                if row['function'] != 'group':
                    raw = row['raw']
                    if row['scene'] > count:
                        row['scene_missing'] = True
                        effects.append(f'remote {r} slot {slot + 1} references scene {row["scene"]} but only '
                                       f'{count} scenes are configured; Toolkit load asserts')
                    if raw['value'] & 0x0F not in (1, 6):
                        effects.append(f'remote {r} slot {slot + 1} scene command {raw["value"] & 0x0F} saves as 6')
                    if raw['secondary']:
                        effects.append(f'remote {r} slot {slot + 1} scene key ApplicationSeconday saves as 0')
                keys.append(row)
            remotes.append({'remote': r, 'serial': serial if assigned else None,
                            'serial_hex': f'{serial:08X}' if assigned else None,
                            'identity_bytes': list(values[f'RemoteIdentity{r}']),
                            'key_map': 'WTXU' if assigned else 'identity',
                            'keys': [row for row in keys if row['key'] is not None] if assigned else [],
                            'hidden_slots': [row for row in keys if row['key'] is None]})
        applications = values['Application']
        return {'format': VIEW_FORMAT, 'unit_type': UNIT_TYPE, 'spec_filename': SPEC_FILENAME,
                'mode': MODES[values['MapWirelessRemotes'][0]],
                'remotes_tab_visible': bool(values['MapWirelessRemotes'][0]),
                'applications': {'primary': None if applications[0] == 0xFF else applications[0],
                                 'secondary': None if applications[1] == 0xFF else applications[1]},
                'application_switch_enabled': applications[1] != 0xFF,
                'scenes': [{'scene': i + 1, 'trigger_group': None if values['SceneTriggerGroup'][i] == 0xFF
                            else values['SceneTriggerGroup'][i], 'vector_offset': values['SceneVectorOffset'][i]}
                           for i in range(count)],
                'remotes': remotes, 'toolkit_save_effects': effects}

    # ---- plan -------------------------------------------------------
    def plan(self, current, *, mode=None, remote=None, serial=..., keys=None, slots=None, identity=None):
        """Plan the Mode control and one Remote Control page.

        ``serial`` is a 32-bit remote identity, ``None`` to clear the remote,
        or omitted. ``keys`` maps dialog keys 1..10 and ``slots`` maps raw PP
        slots 1..16 to assignments from :func:`parse_assignment` (or text).
        """
        if identity is not None:
            if not isinstance(identity, tuple) or len(identity) != 3:
                raise WirelessGatewayError('Identity must be (unit_type, firmware, catalog_number)')
            identity = check_profile(*identity)
        keys, slots = dict(keys or {}), dict(slots or {})
        if mode is not None and mode not in MODES:
            raise WirelessGatewayError('Mode must be ' + ' or '.join(MODES))
        editing_remote = serial is not ... or keys or slots
        if editing_remote and remote is None:
            raise WirelessGatewayError('Remote, key and slot edits require a remote 1..8')
        if remote is not None:
            remote = _integer(remote, 'Remote', 1, REMOTES)
        original = self.snapshot(current)
        updates = {name: list(values) for name, values in original.items()}
        if mode is not None:
            enable = MODES.index(mode)
            if enable and not original['MapWirelessRemotes'][0] and original['Application'][0] == 0xFF:
                # HandleModeChange assigns the network's default Lighting (or
                # Heating) application to an unassigned Application 1; that
                # project-dependent cascade is not reproduced.
                raise WirelessGatewayError('Remote Switch mode with Application 1 unassigned makes Toolkit choose a '
                                           'network default application; assign Application 1 first')
            updates['MapWirelessRemotes'][0] = enable
        if remote is not None and not updates['MapWirelessRemotes'][0]:
            raise WirelessGatewayError('Toolkit shows the Remotes tab only in Remote Switch mode')
        raw_slots = []
        if remote is not None:
            r = remote
            if serial is not ...:
                if serial is None:
                    updates[f'RemoteIdentity{r}'] = list(serial_to_bytes(NO_REMOTE))
                else:
                    value = _integer(serial, 'Remote serial', 0, NO_REMOTE - 1)
                    updates[f'RemoteIdentity{r}'] = list(serial_to_bytes(value))
            assigned = serial_from_bytes(updates[f'RemoteIdentity{r}']) != NO_REMOTE
            targets = {}
            for key, assignment in keys.items():
                key = _integer(key, 'Key', 1, DIALOG_KEYS)
                if not assigned:
                    # EnableKeySelection disables every key panel until a remote is selected.
                    raise WirelessGatewayError('Toolkit disables the remote keys until a remote control is selected')
                targets[WTXU_KEY_MAP[key - 1]] = (f'key {key}', assignment)
            for slot, assignment in slots.items():
                slot = _integer(slot, 'Slot', 1, SLOTS)
                if slot - 1 in targets:
                    raise WirelessGatewayError(f'Slot {slot} is also selected by {targets[slot - 1][0]}')
                targets[slot - 1] = (f'slot {slot}', assignment)
                raw_slots.append(slot)
            for index, (label, assignment) in sorted(targets.items()):
                self._assign(updates, r, index, label, assignment)
        changes = {name: tuple(values) for name, values in updates.items() if tuple(values) != original[name]}
        if any(name not in OWNED for name in changes):
            raise WirelessGatewayError('Plan would change a read-only dependency')
        self.codec.encode_many(changes)
        return WirelessGatewayPlan(original, changes, remote, tuple(raw_slots), identity)

    def _assign(self, updates, r, index, label, assignment):
        if isinstance(assignment, str):
            assignment = parse_assignment(assignment)
        if not isinstance(assignment, dict) or assignment.get('function') not in KEY_FUNCTIONS:
            raise WirelessGatewayError(f'{label}: key function must be ' + ', '.join(KEY_FUNCTIONS))
        function = assignment['function']
        if function == 'group':
            group = assignment.get('group')
            group = NO_GROUP if group is None else _integer(group, f'{label} group', 0, 255)
            application = assignment.get('application', 'primary')
            if application not in ('primary', 'secondary'):
                raise WirelessGatewayError(f'{label}: application must be primary or secondary')
            if application == 'secondary' and updates['Application'][1] == 0xFF:
                # RefreshKeyApplicationSwitchEnable enables the switch only when
                # Application 2 is assigned.
                raise WirelessGatewayError(f'{label}: Toolkit disables the application switch while Application 2 '
                                           'is unassigned')
            # SaveRemotes group branch: mask 0, secondary = not primary, group or 255.
            mask, secondary, value = 0, int(application == 'secondary'), group
        else:
            count = scene_count(updates['SceneVectorOffset'])
            scene = _integer(assignment.get('scene'), f'{label} scene', 1, 15)
            if scene > count:
                raise WirelessGatewayError(f'{label}: scene {scene} is not configured ({count} scenes exist)')
            if updates['SceneTriggerGroup'][scene - 1] == 0xFF:
                # AllScenesHaveGroupsAssigned refuses the dialog save.
                raise WirelessGatewayError(f'{label}: scene {scene} has no trigger group')
            # SaveRemotes scene branch: mask 1, secondary 0, EncodeScene.
            mask, secondary, value = 1, 0, ((scene - 1) << 4) + SCENE_COMMANDS[function]
        updates[f'KeySceneMask{r}'][index] = mask
        updates[f'ApplicationSeconday{r}'][index] = secondary
        updates[f'GroupAddress{r}'][index] = value

    # ---- apply ------------------------------------------------------
    def _verify_profile(self, session):
        return check_profile(session.unit_type, session.firmware, getattr(session, 'catalog_number', None),
                             subject='Native session')

    def _verify_session(self, session):
        verify_native_schema(session, self.spec, FIELDS, WirelessGatewayError)

    def apply(self, session, plan):
        if (not isinstance(plan, WirelessGatewayPlan) or set(plan.expected) != set(FIELDS)
                or any(name not in OWNED for name in plan.changes)):
            raise WirelessGatewayError('Plan contains fields outside the wireless gateway remote workflow')
        self.codec.encode_many(plan.changes)
        identity = self._verify_profile(session)
        if plan.identity is not None and plan.identity[:2] != identity[:2]:
            raise WirelessGatewayError('Plan was created for another unit type or firmware')
        self._verify_session(session)
        if self.snapshot(session.values()) != dict(plan.expected):
            raise WirelessGatewayError('PP parameters changed since the wireless gateway plan was created')
        attempted = []
        try:
            for name in FIELDS:
                if name in plan.changes:
                    attempted.append(name)
                    session.set(name, ' '.join(map(str, plan.changes[name])))
            expected = dict(plan.expected)
            expected.update(plan.changes)
            if self.snapshot(session.values()) != expected:
                raise WirelessGatewayError('Native wireless gateway readback differs from the plan')
        except (RuntimeError, OSError, ValueError) as error:
            # Never issue recovery I/O after an uncertain or partial PP write.
            raise WirelessGatewayApplyError(error, attempted) from error
        return {**replace(plan, identity=identity).as_dict(), 'verified': True}

    def configure(self, session, **options):
        identity = self._verify_profile(session)
        return self.apply(session, self.plan(session.values(), identity=identity, **options))
