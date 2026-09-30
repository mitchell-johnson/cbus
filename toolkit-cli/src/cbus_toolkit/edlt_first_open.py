"""Original eDLT first-open initialization for the direct database helpers.

The Toolkit never edits stored eDLT PP values directly. ``FrmBaseUnit`` opens
the unit through ``EDLTUnit.AfterLoadPPData``, the user edits the loaded
model, and ``BeforeSavePPData`` plus the five CRCs run on save. The direct
widget and settings helpers reproduce the edit and the save-stage projection
for a unit the eDLT model has already opened and saved. They do not reproduce
the load normalization of a unit the model has never opened.

``EDLTUnit.AfterLoadPPData`` changes ``ConfigVersionMajor``/``Minor`` from 255
to 1/0. Every later Toolkit save stores 1/0 (database) or the firmware
version (network), so 255 in either byte identifies a unit whose PP data the
original eDLT model has never saved. For such a unit the native CLI stages the
complete ``EdltLifecycle`` load/before-save/CRC cycle first, then the helper's
edit, then one database save. The complete original workflow capture shows
that this sequence equals the original's single save for Page Control.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

from .edlt import EdltError, _numbers

FORMAT = 'cbus-edlt-first-open-v1'

# Mutating native unit workflows that edit stored PP values without running
# the retained eDLT model lifecycle. Workflows that take lifecycle metadata
# (lifecycle, blank, parent form/transaction, restore levels, applications,
# corridor, reset, scene manager/capture) already load the unit through it.
DIRECT_ACTIONS = (
    'edlt-lighting', 'edlt-enable', 'edlt-shutter', 'edlt-timer', 'edlt-fan', 'edlt-multilevel',
    'edlt-room-courtesy', 'edlt-measurement', 'edlt-time-date', 'edlt-hvac', 'edlt-display',
    'edlt-mra', 'edlt-mra-globals', 'edlt-general', 'edlt-standby', 'edlt-colours',
    'edlt-navigation', 'edlt-quick-status', 'edlt-activation', 'edlt-page-control',
    'edlt-scene', 'edlt-scenes')

GUIDANCE = ('Run "cbus-toolkit edlt lifecycle-requirements" on an export, then supply the cache with '
            '--first-open-metadata, or run edlt-lifecycle first')


class FirstOpenRequired(EdltError):
    """A never-opened unit needs the original first-open facts before a direct edit."""
    def __init__(self, message, details):
        self.details = {'first_open': details}
        super().__init__(message + '. ' + GUIDANCE)


def detect(values):
    """Return the stored configuration version and whether the model never saved it."""
    try:
        major, minor = _numbers(values['ConfigVersionMajor']), _numbers(values['ConfigVersionMinor'])
    except KeyError as error:
        raise EdltError('A complete PP snapshot matching the unit specification is required') from error
    return {'config_version': [list(major), list(minor)],
            'never_initialized': major == (255,) or minor == (255,)}


def network_path(unit):
    """``/db//PROJECT/254/p/20`` -> ``//PROJECT/254`` for the unit's database network."""
    parts = unit.split('/') if isinstance(unit, str) else []
    if (len(parts) != 7 or [parts[0], parts[1].lower(), parts[2]] != ['', 'db', ''] or not parts[3] or not parts[4].isdigit()
            or parts[5].lower() != 'p' or not parts[6].isdigit()):
        raise EdltError('First-open metadata needs a /db//PROJECT/network/p/unit database unit')
    return '//' + parts[3] + '/' + parts[4]


def database_cache(requirements, xml):
    """Lifecycle cache facts read from one exact native network ``DBGETXML`` document.

    Only application presence and group existence are database facts. Each
    application object contains the virtual unused group 255. Dynamic image
    and scene level facts are not derived; requiring them fails closed.
    """
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as error:
        raise EdltError('Native network XML could not be parsed') from error
    if root.tag != 'Network':
        raise EdltError('Native network XML must be one Network document')
    present = {}
    for application in root.findall('Application'):
        try:
            address = int(application.findtext('Address'))
            groups = {int(group.findtext('Address')) for group in application.findall('Group')}
        except (TypeError, ValueError) as error:
            raise EdltError('Native network XML has a malformed application or group address') from error
        if address in present:
            raise EdltError('Native network XML repeats application ' + str(address))
        present[address] = groups
    applications = sorted(entry['application'] for entry in requirements['applications'])
    missing = [address for address in applications if address not in present]
    if missing:
        raise FirstOpenRequired('The original first open needs database applications that are absent: '
                                + ', '.join(map(str, missing)), {'missing_applications': missing})
    groups = []
    for entry in requirements['groups']:
        unsupported = sorted(set(entry['facts']) - {'exists'})
        if unsupported:
            raise FirstOpenRequired('The original first open needs cache facts that the database does not '
                                    'establish (' + ', '.join(unsupported) + ')',
                                    {'application': entry['application'], 'group': entry['group'],
                                     'unsupported_facts': unsupported})
        application, group = entry['application'], entry['group']
        groups.append({'application': application, 'group': group,
                       'exists': group == 255 or group in present[application]})
    return {'format': 'cbus-edlt-lifecycle-cache-v1', 'applications': applications, 'groups': groups}


def prepare(session, client, spec, *, unit, metadata=None, skip=False):
    """Stage the original first-open cycle on a never-opened unit; return evidence or ``None``.

    An already-initialized unit issues no additional command and returns
    ``None``, so its direct edit is unchanged. ``metadata`` is a caller
    ``LifecycleCache``; otherwise facts come from the unit's network
    ``DBGETXML``. The staged cycle is saved only with the following edit.
    """
    state = detect(session.values())
    if not state['never_initialized']:
        return None
    evidence = {'format': FORMAT, **state, 'required': True}
    if skip:
        return {**evidence, 'applied': False, 'skipped_by_request': True}
    from .edlt_lifecycle import EdltLifecycle, LifecycleCache
    lifecycle = EdltLifecycle(spec)
    requirements = lifecycle.requirements(session.values()).as_dict()
    if metadata is not None:
        cache, provenance = LifecycleCache.from_dict(
            metadata.as_dict() if isinstance(metadata, LifecycleCache) else metadata), 'caller-supplied-cache'
    else:
        from .programming import xml_text
        network = network_path(unit)
        reply = client.command('DBGETXML ' + network)
        if getattr(reply, 'code', 344) != 344:
            raise EdltError('Native network XML response did not complete')
        cache = LifecycleCache.from_dict(database_cache(requirements, xml_text(reply)))
        provenance = 'native-database-network-xml'
    result = lifecycle.configure(session, metadata=cache)
    return {**evidence, 'applied': True, 'skipped_by_request': False, 'metadata_provenance': provenance,
            'metadata': cache.as_dict(), 'lifecycle_changes': result['changes'],
            'phases': result['phases'], 'verified': result['verified'], 'saved_separately': False}
