"""Source-pinned eDLT object display and list-order preferences.

The eDLT ``CBusLogicModel`` reads five DWORDs from
``HKCU\\Software\\Clipsal Integrated Systems\\Global\\Preferences\\`` in
``GlobalSoftwareParameters.UpdateValues``.  Each flag is true only when the
value exists and its ``(int)`` DWORD is greater than zero.  An absent key
leaves the static defaults, which are all false.

``CBusBaseObject.ReadXmlData`` then builds ``FormattedDisplay`` from the
address and ``TagName``.  ``CBusNetwork``, ``CBusApplication`` and
``CBusGroup`` sort their application, group and level lists either by
``AddressAsInt`` or with ``CompareTo`` (``TagName`` under
``StringComparison.OrdinalIgnoreCase``).  ``List<T>.Sort`` is unstable, so the
original order of case-insensitively equal names is not pinned by the source;
this model keeps their input (DBGETXML) order and reports that choice.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable, Mapping

from .edlt import EdltError, _int
from .edlt_application_cache import ApplicationCache, CachedDisplay, CachedGroupList

FORMAT = 'cbus-edlt-display-preferences-v1'
REGISTRY_KEY = 'Software\\Clipsal Integrated Systems\\Global\\Preferences\\'
REGISTRY_NAMES = ('DisplayHexAddress', 'DisplayAddressValue',
                  'SortModeApplications', 'SortModeGroups', 'SortModeLevels')
# Toolkit preference-store display keys, in the same order as REGISTRY_NAMES.
TOOLKIT_DISPLAY_NAMES = ('tag_hex', 'tag_override', 'sort_applications',
                         'sort_groups', 'sort_levels')
UNUSED = '<Unused>'
TIE_ORDER = ('input order; original List.Sort is unstable and does not pin '
             'the order of case-insensitively equal names')
_WHITE = ' \t\n\v\f\r'
_INTEGER = re.compile('[' + _WHITE + ']*([+-]?[0-9]+)[' + _WHITE + ']*')


def _dword(value, name):
    """Return the C# ``(int)`` view of one REG_DWORD registry value."""
    if type(value) is not int or not -(2**31) <= value <= 0xffffffff:
        raise EdltError(f'{name} must be one REG_DWORD integer')
    return value - 2**32 if value >= 2**31 else value


@dataclass(frozen=True)
class EdltDisplayPreferences:
    display_hex: bool = False
    display_address_value: bool = False
    sort_applications_by_address: bool = False
    sort_groups_by_address: bool = False
    sort_levels_by_address: bool = False

    def __post_init__(self):
        if any(type(value) is not bool for value in self._flags()):
            raise EdltError('Display preferences must be booleans')

    def _flags(self):
        return (self.display_hex, self.display_address_value,
                self.sort_applications_by_address,
                self.sort_groups_by_address, self.sort_levels_by_address)

    @classmethod
    def from_registry(cls, values=None, *, key_present=True):
        """Apply ``UpdateValues`` to raw DWORDs; absent values are false."""
        if type(key_present) is not bool:
            raise EdltError('Registry key presence must be boolean')
        values = {} if values is None else values
        if not isinstance(values, Mapping) or not set(values) <= set(REGISTRY_NAMES):
            raise EdltError('Display registry values must use the five eDLT names')
        if not key_present and values:
            raise EdltError('An absent Preferences key cannot supply values')
        return cls(*(name in values and _dword(values[name], name) > 0
                     for name in REGISTRY_NAMES))

    @classmethod
    def from_toolkit_display_values(cls, values):
        """Adapt ``ToolkitPreferencesStore`` display values (booleans or bytes)."""
        if not isinstance(values, Mapping) or set(values) != set(TOOLKIT_DISPLAY_NAMES):
            raise EdltError('Toolkit display values must contain the five display names')
        flags = []
        for name in TOOLKIT_DISPLAY_NAMES:
            value = values[name]
            if type(value) not in (bool, int) or not 0 <= value <= 255:
                raise EdltError(f'{name} must be a boolean or byte integer')
            flags.append(value > 0)
        return cls(*flags)

    @classmethod
    def from_dict(cls, document):
        if (not isinstance(document, Mapping)
                or set(document) != {'format', 'registry_key_present', 'values'}
                or document['format'] != FORMAT):
            raise EdltError('Invalid eDLT display preference format or fields')
        return cls.from_registry(document['values'],
                                 key_present=document['registry_key_present'])

    def as_dict(self):
        return {'format': FORMAT, 'registry_key_present': True,
                'values': {name: int(flag)
                           for name, flag in zip(REGISTRY_NAMES, self._flags())}}

    def sort_by_address(self, kind):
        try:
            return {'application': self.sort_applications_by_address,
                    'group': self.sort_groups_by_address,
                    'level': self.sort_levels_by_address}[kind]
        except (KeyError, TypeError):
            raise EdltError('List kind must be application, group or level') from None


def address_as_int(address):
    """``CBusBaseObject.AddressAsInt``: ``int.TryParse`` or zero."""
    if type(address) is int:
        return address if -(2**31) <= address < 2**31 else 0
    if not isinstance(address, str):
        raise EdltError('Object address must be text or an integer')
    match = _INTEGER.fullmatch(address)
    if match is None:
        return 0
    value = int(match[1])
    return value if -(2**31) <= value < 2**31 else 0


def formatted_display(address, tag_name, preferences):
    """``CBusBaseObject.ReadXmlData`` FormattedDisplay under explicit flags."""
    if type(preferences) is not EdltDisplayPreferences:
        raise EdltError('Explicit eDLT display preferences are required')
    if not isinstance(tag_name, str):
        raise EdltError('TagName must be text')
    text = str(address) if type(address) is int else address
    if not isinstance(text, str):
        raise EdltError('Object address must be text or an integer')
    prefix = ''
    if preferences.display_address_value:
        prefix += text.rjust(3, '0')
    if preferences.display_hex:
        prefix += ' (' + format(address_as_int(text) & 0xffffffff, 'X').rjust(2, '0') + 'h)'
    if prefix:
        prefix = prefix.strip() + ' - '
    return prefix + tag_name


def ordinal_ignore_case_key(value):
    """UTF-16 code units compared like ``StringComparison.OrdinalIgnoreCase``.

    ASCII is exact.  Other BMP characters use Python's one-character upper
    mapping; supplementary characters stay as their unchanged surrogates.
    """
    if not isinstance(value, str):
        raise EdltError('Compared names must be text')
    units = []
    for char in value:
        code = ord(char)
        if code > 0xffff:
            code -= 0x10000
            units.extend((0xd800 + (code >> 10), 0xdc00 + (code & 0x3ff)))
            continue
        upper = char.upper()
        units.append(ord(upper) if len(upper) == 1 and ord(upper) <= 0xffff else code)
    return tuple(units)


def order(rows, *, by_address, address=lambda row: row.address,
          name=lambda row: row.name):
    """Return the eDLT list order; ties keep their input order."""
    rows = tuple(rows)
    if type(by_address) is not bool:
        raise EdltError('Sort mode must be boolean')
    if by_address:
        return tuple(sorted(rows, key=lambda row: address_as_int(address(row))))
    return tuple(sorted(rows, key=lambda row: ordinal_ignore_case_key(name(row))))


def name_ties(rows, *, name=lambda row: row.name):
    """Groups of input positions whose names compare equal ignoring case."""
    buckets = {}
    for index, row in enumerate(rows):
        buckets.setdefault(ordinal_ignore_case_key(name(row)), []).append(index)
    return tuple(tuple(indexes) for indexes in buckets.values() if len(indexes) > 1)


def display_list(kind, rows: Iterable[CachedDisplay], preferences):
    """Format and order one application, group or level list.

    Rows carry the exact address and ``TagName`` in ``name``.  A group list's
    address-255 row is the in-memory ``<Unused>`` object: the original adds it
    first after sorting and never passes it through ``ReadXmlData``.
    """
    if type(preferences) is not EdltDisplayPreferences:
        raise EdltError('Explicit eDLT display preferences are required')
    rows = tuple(rows)
    if any(type(row) is not CachedDisplay for row in rows):
        raise EdltError('Display rows must be CachedDisplay records')
    unused = tuple(row for row in rows if kind == 'group' and row.address == 255)
    listed = tuple(row for row in rows if kind != 'group' or row.address != 255)
    ordered = order(listed, by_address=preferences.sort_by_address(kind))
    formatted = tuple(CachedDisplay(row.address, row.name,
                                    formatted_display(row.address, row.name, preferences))
                      for row in ordered)
    return tuple(CachedDisplay(255, row.name, row.name) for row in unused) + formatted


def present_application_cache(cache, preferences):
    """Recompute displays and list order from each exact address/name pair."""
    if type(cache) is not ApplicationCache:
        raise EdltError('An ApplicationCache is required')
    return ApplicationCache(
        cache.lifecycle, cache.applications_complete,
        display_list('application', cache.applications, preferences),
        tuple(CachedGroupList(row.application, row.complete,
                              display_list('group', row.groups, preferences))
              for row in cache.group_lists))


def evidence(preferences, cache=None):
    """Plan evidence for one explicit or omitted preference set."""
    if preferences is None:
        return {'toolkit_display_preferences_supplied': False,
                'display_projection': 'exact TagName database view',
                'inventory_order_source': 'DBGETXML Application/Group XML child order'}
    if type(preferences) is not EdltDisplayPreferences:
        raise EdltError('Explicit eDLT display preferences are required')
    result = {'toolkit_display_preferences_supplied': True,
              'toolkit_display_preferences': preferences.as_dict(),
              'display_projection': 'eDLT CBusBaseObject FormattedDisplay',
              'inventory_order_source': 'eDLT List.Sort under SortMode preferences',
              'equal_name_tie_order': TIE_ORDER}
    if cache is not None:
        lists = [('application', None, cache.applications)] + [
            ('group', row.application, row.groups) for row in cache.group_lists]
        result['case_insensitive_name_ties'] = [
            {'kind': kind, 'application': application,
             'addresses': [rows[index].address for index in tie]}
            for kind, application, rows in lists
            if not preferences.sort_by_address(kind)
            for tie in name_ties([row for row in rows
                                  if not (kind == 'group' and row.address == 255)])]
    return result


def native_display_lists(text, network, preferences):
    """Application/group/level lists from one DBGETXML network, read-only."""
    from .addressing import _container
    from .toolkit_database_csv_native import _byte, _children, _field

    _int(network, 'Network address')
    if type(preferences) is not EdltDisplayPreferences:
        raise EdltError('Explicit eDLT display preferences are required')
    root = _container(text, 'Installation').documentElement
    projects = _children(root, 'Project')
    if len(projects) != 1:
        raise ValueError('Native XML must contain exactly one project')
    networks = [row for row in _children(projects[0], 'Network')
                if _byte(_field(row, 'Address'), 'Network address') == network]
    if len(networks) != 1:
        raise ValueError('Native project must contain exactly the selected network')

    def record(node, label):
        return CachedDisplay(_byte(_field(node, 'Address'), label),
                             _field(node, 'TagName'), _field(node, 'TagName'))

    def unique(rows, label):
        if len({row.address for row in rows}) != len(rows):
            raise ValueError(f'Native {label} list contains duplicate addresses')
        return rows

    applications, group_lists, level_lists, count = [], [], [], 0
    for node in _children(networks[0], 'Application'):
        application = record(node, 'Application address')
        if application.address == 255:
            continue  # CBusNetwork admits only application addresses 0..254.
        applications.append(application)
        groups = []
        for child in node.childNodes:
            if getattr(child, 'tagName', None) not in ('Group', 'NetVar'):
                continue
            group = record(child, 'Group address')
            if group.address == 255:
                continue  # CBusApplication recreates its virtual <Unused>.
            groups.append(group)
            levels = unique([record(level, 'Level address')
                             for level in _children(child, 'Level')], 'level')
            level_lists.append((application.address, group.address, levels))
            count += 1 + len(levels)
        group_lists.append((application.address, unique(groups, 'group')))
        count += 1
        if count > 4096:
            raise ValueError('Native display inventory exceeds 4096 objects')
    unique(applications, 'application')

    def rows(items):
        return [row.as_dict() for row in items]
    return {
        'format': 'cbus-edlt-display-lists-v1',
        'network': network,
        **evidence(preferences),
        'applications': rows(display_list('application', applications, preferences)),
        'groups': [
            {'application': application,
             'groups': rows(display_list(
                 'group', (CachedDisplay(255, UNUSED, UNUSED), *groups), preferences))}
            for application, groups in group_lists],
        'levels': [
            {'application': application, 'group': group,
             'levels': rows(display_list('level', levels, preferences))}
            for application, group, levels in level_lists],
        'project_xml_read_only': True,
        'toolkit_registry_read': False,
    }
