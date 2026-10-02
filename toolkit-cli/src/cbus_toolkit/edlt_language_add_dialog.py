"""Native KEYGL5 selected-language list and FinaliseLanguages projection.

This models a fresh native network cache with explicitly supplied preference
slots. It does not infer the retained Toolkit process cache from project XML.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import re

from .edlt import EdltError

REGISTERED_DEFAULTS = (1, -1, -1, -1, -1, -1, -1, -1)
LANGUAGE_NAMES = {
    0: '<None>', 1: 'English', 2: 'English (Australia)',
    3: 'English (Belize)', 4: 'English (Canada)', 5: 'English (Carribean)',
    6: 'English (Ireland)', 7: 'English (Jamaica)', 8: 'English (New Zealand)',
    9: 'English (Philippines)', 10: 'English (South Africa)',
    11: 'English (Trinidad)', 12: 'English (UK)', 13: 'English (USA)',
    14: 'English (Zimbabwe)', 64: 'Afrikaans', 65: 'Basque', 66: 'Catalan',
    67: 'Danish', 68: 'Dutch (Belgium)', 69: 'Dutch (Netherlands)',
    70: 'Faeroese', 71: 'Finnish', 72: 'French (Belgium)',
    73: 'French (Canada)', 74: 'French', 75: 'French (Luxembourg)',
    76: 'French (Monaco)', 77: 'French (Switzerland)', 78: 'Galician',
    79: 'German (Austria)', 80: 'German', 81: 'German (Liechtenstein)',
    82: 'German (Luxembourg)', 83: 'German (Switzerland)', 84: 'Icelandic',
    85: 'Indonesian', 86: 'Italian', 87: 'Italian (Switzerland)',
    88: 'Malay (Brunei)', 89: 'Malay', 90: 'Norwegian',
    91: 'Norwegian (Nynorsk)', 92: 'Portuguese (Brazil)', 93: 'Portuguese',
    94: 'Spanish (Argentina)', 95: 'Spanish (Bolivia)', 96: 'Spanish (Chile)',
    97: 'Spanish (Columbia)', 98: 'Spanish (Costa Rica)',
    99: 'Spanish (Dominican Republic)', 100: 'Spanish (Ecuador)',
    101: 'Spanish (El Salvador)', 102: 'Spanish (Guatemala)',
    103: 'Spanish (Honduras)', 104: 'Spanish', 105: 'Spanish (Mexico)',
    106: 'Spanish (Nicaragua)', 107: 'Spanish (Panama)',
    108: 'Spanish (Paraguay)', 109: 'Spanish (Peru)',
    110: 'Spanish (Puerto Rico)', 111: 'Spanish (Traditional)',
    112: 'Spanish (Uruguay)', 113: 'Spanish (Venezuela)', 114: 'Swahili',
    115: 'Swedish', 116: 'Swedish (Finland)', 202: 'Chinese',
}


def _preferences(value):
    if value == 'registered-defaults':
        return REGISTERED_DEFAULTS
    if (not isinstance(value, (tuple, list)) or len(value) != 8
            or any(type(v) is not int or not -(2**31) <= v < 2**31 for v in value)):
        raise EdltError('Language Add requires eight explicit integer preferences or registered-defaults')
    if any(v > 0 and v not in LANGUAGE_NAMES for v in value):
        raise EdltError('Language preference does not resolve in the pinned factory')
    return tuple(value)


def normalize(operation):
    if (not isinstance(operation, Mapping)
            or operation.get('op') != 'add-language-dialog'
            or set(operation) - {'op', 'selected_ids', 'cancel', 'preferences'}
            or type(operation.get('cancel', False)) is not bool
            or 'preferences' not in operation):
        raise EdltError('Invalid add-language-dialog operation; explicit preferences are required')
    _preferences(operation['preferences'])
    selected = operation.get('selected_ids', [])
    if (not isinstance(selected, (tuple, list))
            or any(type(v) is not int or v == 0 or v not in LANGUAGE_NAMES for v in selected)
            or len(set(selected)) != len(selected)):
        raise EdltError('Language selection must contain distinct nonzero pinned factory IDs')
    if not operation.get('cancel', False) and not 1 <= len(selected) <= 8:
        raise EdltError('Accepted Language Add requires 1..8 selected languages')
    return {'op': 'add-language-dialog', 'selected_ids': list(selected),
            'cancel': operation.get('cancel', False),
            'preferences': (operation['preferences'] if isinstance(operation['preferences'], str)
                            else list(operation['preferences']))}


@dataclass(frozen=True)
class LanguageRow:
    identifier: int
    name: str
    oid: str | None

    def as_dict(self):
        return {'id': self.identifier, 'tag_value': self.name, 'oid': self.oid}


@dataclass(frozen=True)
class LanguageState:
    rows: tuple[LanguageRow, ...]
    cache: tuple[int, ...]
    default: int


def _native_default_id(value):
    """Pinned SysUtils.StrToIntDef/System.@ValLong grammar, fallback zero."""
    if type(value) is not str:
        return 0
    text = value.split('\0', 1)[0].lstrip(' ')
    match = re.fullmatch(r'([+-]?)(?:(?:\$|0[xX]|[xX])([0-9a-fA-F]+)|([0-9]+))', text)
    if match is None:
        return 0
    sign, hexadecimal, decimal = match.groups()
    if hexadecimal is not None:
        hexadecimal = hexadecimal.lstrip('0') or '0'
        if len(hexadecimal) > 8:
            return 0
        number = int(hexadecimal, 16)
        if number > 0xffffffff:
            return 0
        if sign == '-':
            number = (-number) & 0xffffffff
        return number if number < 0x80000000 else number - 0x100000000
    decimal = decimal.lstrip('0') or '0'
    if len(decimal) > 10:
        return 0
    number = int(decimal)
    if sign == '-':
        number = -number
    return number if -(2**31) <= number < 2**31 else 0


def initialise(rows, preferences, *, cache=(), default=None):
    """Native ordered XML import, then preference slots; no cache clearing."""
    selected = list(cache)
    if (len(set(selected)) != len(selected)
            or any(type(v) is not int or v not in LANGUAGE_NAMES or v == 0 for v in selected)
            or (default is not None and default not in LANGUAGE_NAMES)):
        raise EdltError('Language Add requires a complete valid prior cache or a fresh empty cache')
    for row in rows:
        if row.identifier == 0:
            identifier = _native_default_id(row.name)
            default = identifier if identifier in LANGUAGE_NAMES else None
        elif row.identifier in LANGUAGE_NAMES and row.identifier not in selected:
            selected.append(row.identifier)
    for index, value in enumerate(_preferences(preferences)):
        candidate = value if value > 0 else REGISTERED_DEFAULTS[index]
        if candidate > 0 and len(selected) < 8 and candidate not in selected:
            selected.append(candidate)
    return LanguageState(tuple(rows), tuple(selected), 1 if default is None else default)


def project(state, operation):
    """Accept/cancel selected order, reconcile row identities and default."""
    operation = normalize(operation)
    before = state
    # The dialog receives the current selected collection. Initialisation
    # imports XML/preferences once; opening it is not a new cache import.
    selected = tuple(operation['selected_ids'])
    receipt = {'format': 'cbus-edlt-language-add-dialog-operation-v1',
        'cache_before': list(state.cache), 'default_before': state.default,
        'available_ids_factory_order': [i for i in LANGUAGE_NAMES
            if i and i not in state.cache],
        'available_gui_sorted': True,
        'selected_gui_sorted': False,
        'selected_order': list(state.cache if operation['cancel'] else selected),
        'out_result': '0' if operation['cancel'] else '1',
        'cancelled': operation['cancel'], 'native_dialog_executed': False,
        'fresh_cache_profile': True, 'gui_collation_verified': False,
        'original_callback_storage_save_count_reproduced': False,
        'default_changed': False, 'default_chooses_first': False,
        'deleted_rows': [], 'created_rows': [], 'marker_updated': False}
    if operation['cancel']:
        receipt.update(default_after=state.default, rows_after=[r.as_dict() for r in state.rows])
        return state, receipt
    if 1 in state.cache and 1 not in selected:
        raise EdltError('Original Language Add cannot unselect English identifier1')
    # Reverse sweep: retain the last default marker and all surviving real
    # rows, including duplicate IDs and their existing descriptions.
    retained_marker = next((r for r in reversed(state.rows) if r.identifier == 0), None)
    rows, deleted = [], []
    marker_seen = False
    for row in reversed(state.rows):
        keep = row.identifier in selected
        if row.identifier == 0:
            keep = not marker_seen
            marker_seen = True
        if keep:
            rows.insert(0, row)
        else:
            deleted.append(row)
    created = []
    for identifier in selected:
        if not any(r.identifier == identifier for r in rows):
            row = LanguageRow(identifier, LANGUAGE_NAMES[identifier], None)
            rows.append(row)
            created.append(row)
    default = state.default if state.default in selected else selected[0]
    # Native Add finalises once with the old default, repairs membership,
    # then finalises again. The composed transaction retains final bytes;
    # its receipt makes that source sequence explicit.
    marker = LanguageRow(0, str(default), None if retained_marker is None else retained_marker.oid)
    if retained_marker is None:
        rows.append(marker)
        created.append(marker)
    else:
        rows = [marker if r is retained_marker else r for r in rows]
    receipt.update(default_after=default, default_changed=default != state.default,
        default_chooses_first=state.default not in selected,
        original_finalise_calls=2 if state.default not in selected else 1,
        deleted_rows=[r.as_dict() for r in deleted],
        created_rows=[r.as_dict() for r in created], marker_updated=True,
        rows_after=[r.as_dict() for r in rows],
        xml_changed=tuple(rows) != before.rows)
    return LanguageState(tuple(rows), selected, default), receipt


def native_inventory(text, unit_path):
    """Read complete ordered native rows; never promote a partial cache."""
    from .edlt_parent_metadata import (
        _container, _children, _field, _oid, _one_by_address, _unit_path,
    )
    _unit, _project, address, _unit_address = _unit_path(unit_path)
    document = _container(text, 'Installation')
    project_node = _children(document.documentElement, 'Project')[0]
    network = _one_by_address(project_node, 'Network', address)
    network_oid = _oid(_field(network, 'OID'))
    collections = _children(network, 'Languages')
    if len(collections) > 1:
        raise EdltError('Language Add requires one complete Languages collection')
    collection_oid, rows = None, []
    if collections:
        collection_oid = _oid(_field(collections[0], 'OID'))
        for node in _children(collections[0], 'Language'):
            raw_id = _field(node, 'ID')
            if not re.fullmatch(r'[+-]?[0-9]+', raw_id):
                raise EdltError('Language ID must be a signed decimal integer')
            unsigned_id = raw_id.lstrip('+-').lstrip('0') or '0'
            if len(unsigned_id) > 10:
                raise EdltError('Language ID must fit the native signed integer')
            identifier = int(('-' if raw_id.startswith('-') else '') + unsigned_id)
            if not -(2**31) <= identifier < 2**31:
                raise EdltError('Language ID must fit the native signed integer')
            identity = _oid(_field(node, 'OID'))
            rows.append(LanguageRow(identifier, _field(node, 'TagValue'), identity))
    identities = [r.oid for r in rows]
    if len(set(identities)) != len(identities):
        raise EdltError('Language Add requires distinct observed row identities')
    return network_oid, collection_oid, tuple(rows)


def replace_native_rows(text, unit_path, rows, *, collection_oid, identities=None):
    """Project only the collection and row fields owned by language history.

    Existing row markup and descriptions survive. New identities are explicit
    plan keys until actual issued OIDs have been admitted.
    """
    from .edlt_parent_metadata import _container, _children, _field, _one_by_address, _unit_path
    _unit, _project, address, _unit_address = _unit_path(unit_path)
    document = _container(text, 'Installation')
    project_node = _children(document.documentElement, 'Project')[0]
    network = _one_by_address(project_node, 'Network', address)
    collections = _children(network, 'Languages')
    collection = collections[0] if collections else document.createElement('Languages')
    if not collections:
        network.appendChild(collection)
        node = document.createElement('OID')
        node.appendChild(document.createTextNode(collection_oid))
        collection.appendChild(node)
    prior = {_field(node, 'OID'): node for node in _children(collection, 'Language')}
    wanted = {(identities or {}).get(row.oid, row.oid) for row in rows}
    for identity, node in prior.items():
        if identity not in wanted:
            collection.removeChild(node)
    for row in rows:
        identity = (identities or {}).get(row.oid, row.oid)
        node = prior.get(identity)
        if node is None:
            node = document.createElement('Language')
            for name, value in (('OID', identity), ('ID', str(row.identifier)), ('TagValue', row.name)):
                field = document.createElement(name)
                field.appendChild(document.createTextNode(value))
                node.appendChild(field)
            collection.appendChild(node)
        else:
            for name, value in (('ID', str(row.identifier)), ('TagValue', row.name)):
                fields = _children(node, name)
                if len(fields) != 1:
                    raise EdltError('Language row requires exact ID and TagValue fields')
                field = fields[0]
                # Finalise never rewrites retained real rows. Keep their
                # signed decimal spelling; only ID0 is deliberately set0.
                if name == 'ID' and row.identifier != 0:
                    continue
                if name == 'TagValue' and _field(node, name) == value:
                    continue
                for child in list(field.childNodes): field.removeChild(child)
                field.appendChild(document.createTextNode(value))
    return document.toxml()
