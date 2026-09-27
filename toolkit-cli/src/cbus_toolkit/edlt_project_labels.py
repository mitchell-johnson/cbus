"""Read saved group DLT tags from one bounded C-Gate network XML snapshot.

These are project database records. They are not the KEYGL5's static strings,
observed SAL traffic, or a readback of its pre-existing dynamic-label cache.
"""
from __future__ import annotations

import hashlib

from .addressing import _container
from .toolkit_database_csv_native import (_byte, _children, _field,
                                          native_xml_reply_text)


MAX_XML_BYTES = 4 * 1024 * 1024
MAX_OBJECTS = 4096
MAX_TAGS = 8192


def project_group_labels(client, network):
    """Enumerate network Group/TagsDLT/TagDLT from exactly one DBGETXML read."""
    from .cmqtt import _network

    network = _network(network)
    address = int(network.rsplit('/', 1)[1])
    command = f'DBGETXML {network}'
    response = client.command(command)
    if response.status not in (200, 344):
        raise ValueError('C-Gate network XML did not complete successfully')
    # Native C-Gate ends DBGETXML with 344. cmqttd uses 200, and old builds
    # could emit a parseable but incomplete network tree after dropping the
    # imported TagsDLT records. Require its explicit preservation capability.
    if response.status == 200:
        from .cmqtt import _object
        capabilities = _object(client, 'CMQTT CAPABILITIES')
        requested_project = network[2:].split('/', 1)[0]
        if (capabilities.get('service') != 'cmqttd'
                or capabilities.get('project') != requested_project
                or capabilities.get('saved_project_group_dlt_labels') is not True):
            raise ValueError('cmqttd has not confirmed saved project Group/TagsDLT preservation for the requested project')
    xml = native_xml_reply_text(response, completion_codes=(200, 344))
    size = len(xml.encode('utf-8'))
    if size > MAX_XML_BYTES:
        raise ValueError('C-Gate network XML exceeds the 4 MiB label enumeration limit')
    root = _container(xml, 'Network').documentElement
    if _byte(_field(root, 'Address'), 'Network address') != address:
        raise ValueError('C-Gate network XML does not match the requested network')
    applications = _children(root, 'Application')
    if len(applications) > 256:
        raise ValueError('C-Gate network XML has too many applications')
    rows = []
    seen_applications = set()
    group_count = 0
    for application in applications:
        app = _byte(_field(application, 'Address'), 'Application address')
        if app in seen_applications:
            raise ValueError('C-Gate network XML contains duplicate applications')
        seen_applications.add(app)
        application_name = _field(application, 'TagName')
        groups = _children(application, 'Group')
        if len(groups) > 256:
            raise ValueError('C-Gate network XML has too many groups in an application')
        seen_groups = set()
        for group in groups:
            group_count += 1
            if group_count > MAX_OBJECTS:
                raise ValueError('C-Gate network XML exceeds the group enumeration limit')
            address_number = _byte(_field(group, 'Address'), 'Group address')
            if address_number in seen_groups:
                raise ValueError('C-Gate network XML contains duplicate groups')
            seen_groups.add(address_number)
            group_name = _field(group, 'TagName')
            collections = _children(group, 'TagsDLT')
            if len(collections) > 1:
                raise ValueError('C-Gate Group contains duplicate TagsDLT collections')
            for tag in _children(collections[0], 'TagDLT') if collections else ():
                if len(rows) >= MAX_TAGS:
                    raise ValueError('C-Gate network XML exceeds the DLT tag enumeration limit')
                language = _byte(_field(tag, 'LanguageID'), 'DLT language')
                flavour = _byte(_field(tag, 'FlavourID'), 'DLT flavour')
                if not 1 <= flavour <= 4:
                    raise ValueError('C-Gate DLT flavour must be 1..4')
                kind = _field(tag, 'TagType')
                value = _field(tag, 'TagValue')
                if len(kind) > 64 or len(value) > 1024:
                    raise ValueError('C-Gate DLT tag exceeds the supported field length')
                rows.append({
                    'path': f'{network}/{app}/{address_number}',
                    'application': app,
                    'application_name': application_name,
                    'group': address_number,
                    'group_name': group_name,
                    'language_id': language,
                    'flavour_id': flavour,
                    'tag_type': kind,
                    'tag_value': value,
                })
    rows.sort(key=lambda row: (row['application'], row['group'], row['language_id'],
                               row['flavour_id'], row['tag_type'], row['tag_value']))
    return {
        'format': 'cbus-saved-project-group-dlt-labels-v1',
        'source': 'cgate-dbgetxml-saved-project',
        'scope': 'network-group-tagsdlt',
        'network': network,
        'command': command,
        'project_snapshot_complete': True,
        'completeness_scope': 'returned-saved-project-group-tagsdlt',
        'device_readback': False,
        'physical_device_verified': False,
        'device_label_inventory_complete': False,
        'cmqttd_import_capability_verified': response.status == 200,
        'application_count': len(applications),
        'group_count': group_count,
        'label_count': len(rows),
        'labels': rows,
        'xml_bytes': size,
        'xml_sha256': hashlib.sha256(xml.encode('utf-8')).hexdigest(),
    }
