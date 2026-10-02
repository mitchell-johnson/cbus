"""Exact blank-address eDLT Application Add policy, without I/O.

The parent calls the owner/eDLT overload, not the distinct MinMax overload.
Explicit preferences model the original registry switches; they are not read
from this computer. A result is a proposed metadata object and combo binding.
"""
from .edlt import EdltError
from .edlt_add_dialog import _trim, _upper

STANDARD_NAMES = {56: 'Lighting', 95: 'DALI', 113: 'Irrigation Control',
                  114: 'Pool, Spa, Pond Control', 136: 'Heating (Legacy)'}


def preferences(value):
    if (type(value) is not dict or set(value) != {'allow_user_defined', 'allow_legacy'}
            or any(type(v) is not bool for v in value.values())):
        raise EdltError('Application Add requires explicit boolean creation_preferences allow_user_defined and allow_legacy')
    return dict(value)


def candidates(applications, settings):
    settings = preferences(settings)
    allowed = (set(range(48, 128)) | {136} if any(settings.values()) else
               set(range(48, 96)) | set(range(112, 115)) | {136})
    return tuple(address for address in sorted(allowed) if address not in applications)


def normalize(value):
    allowed = {'op', 'field', 'address', 'name', 'description', 'cancel',
               'creation_preferences', 'confirm_reserved'}
    if (set(value) - allowed or value.get('field') not in ('primary', 'secondary')):
        raise EdltError('add-application-dialog requires primary or secondary field and admitted options')
    preferences(value.get('creation_preferences'))
    if 'address' in value and (type(value['address']) is not int or not 0 <= value['address'] <= 254):
        raise EdltError('Application Add address must be a byte in 0..254')
    for name in ('name', 'description'):
        if name in value and type(value[name]) is not str:
            raise EdltError('Application Add ' + name + ' must be text')
    for name in ('cancel', 'confirm_reserved'):
        if name in value and type(value[name]) is not bool:
            raise EdltError('Application Add ' + name + ' must be boolean')
    return {key: (dict(value[key]) if key == 'creation_preferences' else value[key])
            for key in ('op', 'field', 'address', 'name', 'description', 'cancel',
                        'creation_preferences', 'confirm_reserved') if key in value}


def resolve(value, applications, project_name, other_networks=()):
    value = normalize(value)
    free = candidates(applications, value['creation_preferences'])
    if not free:
        raise EdltError('Application Add has no listed free address')
    first = free[0]
    address = first if value.get('cancel') else value.get('address', first)
    if address not in free:
        raise EdltError('Application Add address is not in the permitted free list')
    standard = STANDARD_NAMES.get(address)
    shown = standard or ''
    result = dict(operation=value, kind='Application', field=value['field'],
                  first_free_address=first, candidate_addresses=list(free),
                  address=address, shown_name=shown, name_editable=standard is None,
                  creation_preferences=value['creation_preferences'],
                  original_dialog_executed=False)
    if value.get('cancel'):
        return {**result, 'outcome': 'cancelled'}
    # A registered standard name disables the Name edit. Supplying the same
    # value is harmless; a conflicting edit is not a native reachable state.
    if standard is not None and 'name' in value and _trim(value['name']) != standard:
        raise EdltError('Application Add standard name is not editable')
    name = _trim(value.get('name', shown))
    if not name:
        raise EdltError('Application Add error 2241: Application name cannot be blank')
    if name == project_name:
        raise EdltError('Application Add error 2247: name cannot equal the Project TagName')
    if any(_upper(name) == _upper(tag) for tag in applications.values()):
        raise EdltError('Application Add error 2242: Application name already exists')
    warning = not (48 <= address <= 95 or 112 <= address <= 114 or address == 136)
    if warning and not value.get('confirm_reserved', False):
        raise EdltError('Application Add confirmation 3171 is required for this reserved address')
    for _network, rows in other_networks:
        if any(_upper(name) == _upper(tag) and number != address for number, tag in rows.items()):
            raise EdltError('Application Add error 2244: same name has a different address in this project')
    for _network, rows in other_networks:
        if address in rows and rows[address] != name:
            raise EdltError('Application Add error 2245: same address has a different name in another network')
    return {**result, 'outcome': 'accepted', 'name': name,
            'description': _trim(value.get('description', '')),
            'reserved_confirmation': warning,
            'operator_address': 'address' in value, 'operator_name': 'name' in value}
