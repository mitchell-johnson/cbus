"""Journaled eDLT firmware update through an explicit DFU device, with explicit resume.

A supported ``cbus-edlt-firmware-update-plan-v1`` plan is executed as ordered
stages that each start at a safe boundary: erase the stage's whole range, then
program the image and read it back. The font stage erases the plan's original
external range; the main stage erases the image range rounded up to 1024-byte
blocks. That explicit main erase departs from the original updater, which
relies on the bootloader, so an interrupted stage can always be restarted.

Before any destructive request the device is freshly enumerated and inspected
(identity, descriptors and the reported memory geometry). The reported
application start is the only variant observable in DFU mode: 0x2000 means
Stellaris, 0x4000 means Tiva, and Tiva/PCI versus Tiva/NCC is not separable.

A durable journal is exclusively created and fsynced before the first erase.
Each later phase is an atomic, checked replacement written *before* the
request it describes. The journal never authorizes a replay. A failure stops
the run; nothing is retried. ``resume_update`` re-enumerates, re-inspects,
requires the journal's exact identity and geometry, re-reads every stage the
journal records as verified, and restarts the first unverified stage from its
erase. It never continues a partial write.

The mode switch, target reset and NCC serial post-check are not sent. The
device must already be in DFU mode. Memory-peer and fake-backend runs are
development evidence; physical acceptance needs the hardware gate runbook.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import time
from typing import Any, Callable

from .dfu_simulator import DFUDisconnect
from .dfu_transport import DFUClient, DFUInterface, DFUOperationError, MemoryEndpoint0
from .firmware_update_plan import _outcome, _vector_table
from .pci_selected_serial import _Journal, _unique_pairs
from .physical_pp_journal import attempt_id, now

JOURNAL_FORMAT = 'cbus-edlt-firmware-update-journal-v1'
RESULT_FORMAT = 'cbus-edlt-firmware-update-run-v1'
PLAN_FORMAT = 'cbus-edlt-firmware-update-plan-v1'
PHASES = ('pending', 'erase-sent', 'erased', 'write-sent', 'verified')
STATUSES = ('in-progress', 'interrupted', 'failed', 'complete')
EVENTS = ('journal-created', 'erase-sent', 'erase-result', 'erased', 'write-sent', 'write-result', 'verified',
          'run-stopped',
          'run-complete', 'resume-started', 'resume-refused', 'reverify-result', 'stage-restart')
# INFO application start reported by the bootloader -> variants it can hold.
APPLICATION_START_VARIANTS = {0x2000: ('StellarisPCI',), 0x4000: ('TivaPCI', 'TivaNCC')}
STAGE_STATES = {
    'pending': 'untouched by this journal',
    'erase-sent': 'unknown: erase may be partial',
    'erased': 'erased and read back as blank',
    'write-sent': 'unknown: image may be partial or unverified',
    'verified': 'image read back byte-for-byte',
}
_DOCUMENT_KEYS = frozenset({'format', 'attempt_id', 'binding', 'send_may_have_occurred',
                            'replay_authorized', 'status', 'stages', 'history', 'runs'})
_BINDING_KEYS = frozenset({'plan_format', 'package', 'variant', 'force_font', 'main_address',
                           'flash_size', 'external_size', 'stages', 'identity', 'geometry'})
_STAGE_KEYS = frozenset({'name', 'external', 'erase_address', 'erase_length', 'address',
                         'entry', 'bytes', 'sha256'})
_EVENT_KEYS = frozenset({'seq', 'at', 'event', 'stage', 'detail'})


class UpdateJournalError(ValueError):
    """The journal is missing, malformed or does not bind this update."""


class DeviceUnavailable(RuntimeError):
    """The selected device could not be enumerated, identified or claimed."""
    def __init__(self, message, details=None):
        super().__init__(message)
        self.details = details


class _Refusal(Exception):
    def __init__(self, kind, message, detail=None):
        super().__init__(message)
        self.kind = kind; self.detail = detail or {}


@dataclass
class DeviceSession:
    endpoint: Any
    descriptor: DFUInterface
    identity: dict
    _release: Callable[[], dict | None] | None = None

    def release(self):
        return self._release() if self._release is not None else None


def descriptor_identity(descriptor, serial):
    return {'usb_serial': serial,
            'device_descriptor_sha256': hashlib.sha256(descriptor.device_descriptor).hexdigest(),
            'configuration_descriptor_sha256': hashlib.sha256(descriptor.configuration_descriptor).hexdigest()}


class MemoryDeviceOpener:
    """Open a fresh host session on a memory peer, as each dfuprog process does."""
    def __init__(self, peer, descriptor, *, serial):
        self.peer = peer; self.descriptor = descriptor; self.serial = serial; self.opens = 0

    def open(self):
        self.opens += 1
        try:
            self.peer.new_host_session()
        except DFUDisconnect as error:
            raise DeviceUnavailable(f'Memory peer is not enumerated: {error}') from error
        return DeviceSession(MemoryEndpoint0(self.peer, self.descriptor), self.descriptor,
                             descriptor_identity(self.descriptor, self.serial))


class USBDeviceOpener:
    """Enumerate and claim the explicitly selected eDLT for every operation."""
    def __init__(self, *, bus, address, expected_serial, descriptor, release_policy,
                 inspection_timeout=5.0, backend=None):
        self.options = dict(bus=bus, address=address, expected_serial=expected_serial,
                            descriptor=descriptor, release_policy=release_policy,
                            inspection_timeout=inspection_timeout, backend=backend)
        self.descriptor = descriptor; self.opens = 0

    def open(self):
        from .usb_dfu import ClaimedUSBSession, USBAcquisitionError
        self.opens += 1
        try:
            session = ClaimedUSBSession.acquire(**self.options)
        except USBAcquisitionError as error:
            raise DeviceUnavailable(str(error), error.details) from error
        try:
            lease = session.endpoint()
        except BaseException:
            session.release(); raise

        def release():
            try:
                return session.release().as_dict()
            except Exception as error:
                return {'complete': False, 'error': str(error) or type(error).__name__}
        return DeviceSession(lease, self.descriptor,
                             descriptor_identity(self.descriptor, session.acquisition.serial), release)


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def plan_stages(plan, images, *, flash_size, external_size):
    """Derive the safe-boundary stages and refuse unusable inputs before any I/O."""
    if not isinstance(plan, dict) or plan.get('format') != PLAN_FORMAT:
        raise _Refusal('plan', 'A cbus-edlt-firmware-update-plan-v1 plan is required')
    if not plan['supported']:
        raise _Refusal('plan', 'Only a supported plan can be executed', {'issues': plan['issues']})
    steps = {step['step']: step for step in plan['dfuprog_steps']}
    address = int(plan['main_address'], 16)
    stages = []
    if 'font-write' in steps:
        font = steps['font-write']
        if external_size is None:
            raise _Refusal('geometry', 'The font stage requires an explicit external flash size')
        stages.append({'name': 'font', 'external': True, 'erase_address': 0,
                       'erase_length': steps['font-erase']['length'], 'address': 0,
                       'entry': font['entry'], 'bytes': font['bytes']})
    main = steps['main-write']
    stages.append({'name': 'main', 'external': False, 'erase_address': address,
                   'erase_length': -(-main['bytes'] // 1024) * 1024, 'address': address,
                   'entry': main['entry'], 'bytes': main['bytes']})
    for stage in stages:
        data = images.get(stage['entry'])
        if not isinstance(data, bytes) or len(data) != stage['bytes']:
            raise _Refusal('image', f'Image {stage["entry"]!r} is missing or differs from the plan size')
        stage['sha256'] = hashlib.sha256(data).hexdigest()
        external = stage['external']
        geometry = dict(flash_size=external_size if external else flash_size,
                        application_start=0 if external else address, external=external)
        try:
            DFUClient.preflight(_preflight_descriptor(), operation='erase', address=stage['erase_address'],
                                length=stage['erase_length'], **geometry)
            DFUClient.preflight(_preflight_descriptor(), operation='program', address=stage['address'],
                                data=data, **geometry)
        except ValueError as error:
            raise _Refusal('geometry', f'Stage {stage["name"]} does not fit the explicit flash bounds: {error}') from error
    table = _vector_table(images[main['entry']], address)
    if table is None or not table['reset_handler_in_image']:
        raise _Refusal('variant-mismatch', 'The main image reset vector does not lie inside the image at the '
                       f'{plan["variant"]} address {plan["main_address"]}', {'vector_table': table})
    return stages


def _preflight_descriptor():
    from .firmware_update_plan import SIMULATOR_CONFIGURATION_DESCRIPTOR, SIMULATOR_DEVICE_DESCRIPTOR
    from .dfu_transport import parse_descriptors
    return parse_descriptors(SIMULATOR_DEVICE_DESCRIPTOR, SIMULATOR_CONFIGURATION_DESCRIPTOR)


class _Update:
    def __init__(self, plan, images, stages, *, opener, flash_size, external_size, timeout,
                 poll_limit, clock, sleep, journal_path):
        self.plan = plan; self.images = images; self.stages = stages; self.opener = opener
        self.flash_size = flash_size; self.external_size = external_size
        self.timeout = timeout; self.poll_limit = poll_limit; self.clock = clock; self.sleep = sleep
        self.address = int(plan['main_address'], 16)
        self.journal_path = journal_path; self.writer = None; self.doc = None
        self.operations = []; self.releases = []

    # -- device operations -------------------------------------------------
    def operation(self, kind, stage=None, *, external=False):
        """One fresh session and one DFU operation. Never repeated here."""
        external = stage['external'] if stage is not None else external
        session = self.opener.open()
        outcome = None
        try:
            client = DFUClient(session.endpoint, session.descriptor,
                               flash_size=self.external_size if external else self.flash_size,
                               application_start=0 if external else self.address, external=external,
                               timeout=self.timeout, poll_limit=self.poll_limit,
                               clock=self.clock, sleep=self.sleep)
            try:
                if kind == 'inspect':
                    outcome = client.inspect()
                elif kind == 'erase':
                    outcome = client.erase(address=stage['erase_address'], length=stage['erase_length'])
                elif kind == 'program':
                    outcome = client.program(self.images[stage['entry']], address=stage['address'])
                else:
                    outcome = client.verify(self.images[stage['entry']], address=stage['address'])
            except DFUOperationError as error:
                outcome = error.outcome
        finally:
            release = session.release()
            if release is not None:
                self.releases.append(release)
        summary = {**_outcome(outcome), 'operation': kind, 'stage': stage['name'] if stage else None,
                   'dfu_stage': outcome.stage, 'outcome_known': outcome.outcome_known, 'info': outcome.info}
        self.operations.append(summary)
        return outcome, summary, session.identity

    def inspect_device(self):
        identity = None; geometry = {}
        for external in ([False, True] if any(stage['external'] for stage in self.stages) else [False]):
            try:
                outcome, summary, found = self.operation('inspect', external=external)
            except DeviceUnavailable as error:
                raise _Refusal('device-unavailable', str(error), {'details': error.details}) from error
            if identity is not None and found != identity:
                raise _Refusal('identity-changed', 'Device identity changed between inspections')
            identity = found
            if not outcome.complete:
                info = outcome.info
                if not external and info is not None and info['application_start'] != self.address:
                    raise _Refusal('variant-mismatch',
                        f'Device reports application start 0x{info["application_start"]:x}, which holds '
                        f'{"/".join(APPLICATION_START_VARIANTS.get(info["application_start"], ("an unknown variant",)))}; '
                        f'the plan is for {self.plan["variant"]} at {self.plan["main_address"]}',
                        {'reported': info})
                raise _Refusal('inspection-failed', outcome.error or 'Device inspection failed',
                               {'reported': info, 'stage': outcome.stage})
            geometry['external' if external else 'internal'] = outcome.info
        geometry.setdefault('external', None)
        return identity, geometry

    # -- journal -----------------------------------------------------------
    def event(self, event, stage=None, **detail):
        self.doc['history'].append({'seq': len(self.doc['history']), 'at': now(), 'event': event,
                                    'stage': stage, 'detail': detail})

    def persist(self):
        self.writer.write(self.doc)

    def phase(self, stage, phase, event, **detail):
        self.doc['stages'][stage['name']] = phase
        self.event(event, stage['name'], **detail)
        self.persist()

    def stop(self, stage, summary, *, known):
        self.doc['status'] = 'failed' if known else 'interrupted'
        self.event('run-stopped', stage['name'], phase=self.doc['stages'][stage['name']],
                   error=summary.get('error'), outcome_known=known)
        self.persist()

    def execute(self):
        """Run every unverified stage from its erase; stop at the first failure."""
        for stage in self.stages:
            if self.doc['stages'][stage['name']] == 'verified':
                continue
            for kind, sent, done in (('erase', 'erase-sent', 'erased'), ('program', 'write-sent', 'verified')):
                self.phase(stage, sent, sent)
                try:
                    outcome, summary, _ = self.operation(kind, stage)
                except DeviceUnavailable as error:
                    summary = {'operation': kind, 'stage': stage['name'], 'error': str(error),
                               'device_unavailable': error.details}
                    self.operations.append(summary)
                    self.stop(stage, summary, known=False)
                    return stage, summary
                self.event('erase-result' if kind == 'erase' else 'write-result', stage['name'],
                           complete=outcome.complete, error=outcome.error, outcome_known=outcome.outcome_known,
                           payload_transferred=outcome.payload_transferred,
                           readback_bytes=outcome.readback_bytes, first_mismatch=outcome.first_mismatch)
                if not outcome.complete:
                    self.stop(stage, summary, known=outcome.outcome_known)
                    return stage, summary
                self.phase(stage, done, done)
        self.doc['status'] = 'complete'
        self.event('run-complete')
        self.persist()
        return None, None

    def result(self, operation, *, refused=None, failed=None, created=False, extra=None):
        failed_stage, summary = failed or (None, None)
        doc = self.doc
        complete = doc is not None and doc['status'] == 'complete' and refused is None
        stages = dict(doc['stages']) if doc else {stage['name']: 'pending' for stage in self.stages}
        error = refused.args[0] if refused is not None else (summary or {}).get('error')
        resumable = doc is not None and doc['status'] != 'complete'
        return {'format': RESULT_FORMAT, 'operation': operation, 'complete': complete,
                'refused': refused is not None, 'refusal_kind': refused.kind if refused else None,
                'refusal_detail': refused.detail if refused else None, 'error': error,
                'journal': str(self.journal_path) if self.journal_path else None,
                'journal_created': created, 'attempt_id': doc['attempt_id'] if doc else None,
                'status': doc['status'] if doc else None,
                'failed_stage': failed_stage['name'] if failed_stage else None,
                'failed_phase': stages[failed_stage['name']] if failed_stage else None,
                'stages': stages, 'stage_states': {name: STAGE_STATES[phase] for name, phase in stages.items()},
                'operations': self.operations, 'releases': self.releases, **(extra or {}),
                'retried': False, 'resume_required': resumable,
                'next_action': ('cbus-toolkit firmware update-resume --journal <journal> '
                                '(fresh re-inspection; restarts the first unverified stage from erase)')
                               if resumable else None,
                'mode_switch': 'not sent: the device must already be in DFU mode',
                'target_reset': 'not sent', 'post_check': 'not executed',
                'physical_device_verified': False,
                'scope': 'Journaled stage execution over an explicit DFU device; hardware acceptance is not established'}


def _binding(plan, stages, *, flash_size, external_size, identity, geometry):
    return {'plan_format': PLAN_FORMAT,
            'package': {key: plan['package'][key] for key in ('name', 'sha256', 'version')},
            'variant': plan['variant'], 'force_font': plan['font_install']['forced'],
            'main_address': plan['main_address'], 'flash_size': flash_size,
            'external_size': external_size, 'stages': stages, 'identity': identity, 'geometry': geometry}


def run_update(plan, images, *, opener, journal_path, flash_size, external_size=None, timeout=30,
               poll_limit=256, clock=time.monotonic, sleep=time.sleep):
    """Inspect, create the journal, then run every stage once. Never retries."""
    try:
        stages = plan_stages(plan, images, flash_size=flash_size, external_size=external_size)
    except _Refusal as refusal:
        update = _Update(plan if isinstance(plan, dict) else {}, images, [], opener=opener,
                         flash_size=flash_size, external_size=external_size, timeout=timeout,
                         poll_limit=poll_limit, clock=clock, sleep=sleep, journal_path=None)
        return update.result('run', refused=refusal)
    update = _Update(plan, images, stages, opener=opener, flash_size=flash_size, external_size=external_size,
                     timeout=timeout, poll_limit=poll_limit, clock=clock, sleep=sleep, journal_path=journal_path)
    try:
        identity, geometry = update.inspect_device()
    except _Refusal as refusal:
        return update.result('run', refused=refusal)
    binding = _binding(plan, stages, flash_size=flash_size, external_size=external_size,
                       identity=identity, geometry=geometry)
    update.doc = {'format': JOURNAL_FORMAT, 'attempt_id': attempt_id(binding), 'binding': binding,
                  'send_may_have_occurred': True, 'replay_authorized': False, 'status': 'in-progress',
                  'stages': {stage['name']: 'pending' for stage in stages}, 'history': [], 'runs': 1}
    update.event('journal-created', identity=identity)
    update.writer = _Journal(journal_path)
    try:
        update.persist()
    except Exception as error:
        update.doc = None
        return update.result('run', refused=_Refusal(
            'journal', f'Journal could not be created before the first erase; nothing was written: {error}'))
    failed = update.execute()
    return update.result('run', failed=failed if failed[0] else None, created=True)


def load_journal(path):
    """Read and strictly validate a journal. Returns (document, raw bytes)."""
    writer = _Journal(path)
    try:
        raw = writer._read_current()
    except (OSError, ValueError) as error:
        raise UpdateJournalError(f'Cannot read update journal: {error}') from error
    try:
        doc = json.loads(raw.decode('utf-8'), object_pairs_hook=_unique_pairs,
                         parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite JSON value')))
    except (UnicodeDecodeError, ValueError) as error:
        raise UpdateJournalError(f'Update journal is not valid JSON: {error}') from error

    def require(condition, message):
        if not condition:
            raise UpdateJournalError(message)
    require(type(doc) is dict and set(doc) == _DOCUMENT_KEYS, 'Update journal has unsupported or missing fields')
    require(doc['format'] == JOURNAL_FORMAT, 'Unsupported update journal format')
    binding = doc['binding']
    require(type(binding) is dict and set(binding) == _BINDING_KEYS, 'Journal binding is malformed')
    require(doc['attempt_id'] == attempt_id(binding), 'Journal binding does not match its attempt_id')
    require(doc['send_may_have_occurred'] is True and doc['replay_authorized'] is False,
            'Journal envelope must record a possible send and no replay authority')
    require(doc['status'] in STATUSES, 'Unknown journal status')
    stages = binding['stages']
    require(type(stages) is list and stages and all(type(stage) is dict and set(stage) == _STAGE_KEYS
                                                    for stage in stages), 'Journal stages are malformed')
    require(type(doc['stages']) is dict and list(doc['stages']) == [stage['name'] for stage in stages]
            and all(phase in PHASES for phase in doc['stages'].values()), 'Journal stage phases are malformed')
    history = doc['history']
    require(type(history) is list and history, 'Journal history is empty')
    for position, entry in enumerate(history):
        require(type(entry) is dict and set(entry) == _EVENT_KEYS, f'Journal event {position} is malformed')
        require(entry['seq'] == position, f'Journal event {position} breaks sequence continuity')
        require(entry['event'] in EVENTS, f'Journal event {position} is unknown')
    require(type(doc['runs']) is int and doc['runs'] >= 1, 'Journal run count is malformed')
    return doc, raw


def journal_plan_options(doc):
    """The plan selection a resume must reproduce from the same package."""
    binding = doc['binding']
    return {'variant': binding['variant'], 'force_font': binding['force_font'],
            'flash_size': binding['flash_size'], 'external_size': binding['external_size'],
            'identity': binding['identity']}


def resume_update(journal_path, plan, images, *, opener, timeout=30, poll_limit=256,
                  clock=time.monotonic, sleep=time.sleep):
    """Re-inspect, re-verify, then restart the first unverified stage from erase."""
    doc, raw = load_journal(journal_path)
    binding = doc['binding']
    update = _Update(plan, images, binding['stages'], opener=opener, flash_size=binding['flash_size'],
                     external_size=binding['external_size'], timeout=timeout, poll_limit=poll_limit,
                     clock=clock, sleep=sleep, journal_path=journal_path)
    update.doc = doc
    update.writer = _Journal(journal_path); update.writer.expected = raw
    if doc['status'] == 'complete':
        return update.result('resume', refused=_Refusal('journal-complete',
                             'The journal records a completed update; there is nothing to resume'))
    try:
        stages = plan_stages(plan, images, flash_size=binding['flash_size'],
                             external_size=binding['external_size'])
    except _Refusal as refusal:
        return update.result('resume', refused=refusal)
    fresh = _binding(plan, stages, flash_size=binding['flash_size'], external_size=binding['external_size'],
                     identity=binding['identity'], geometry=binding['geometry'])
    if _canonical(fresh) != _canonical(binding):
        return update.result('resume', refused=_Refusal('journal-binding-mismatch',
                             'The supplied package, variant or images differ from the journal binding'))
    doc['runs'] += 1
    update.event('resume-started', run=doc['runs'], prior_status=doc['status'], stages=dict(doc['stages']))
    update.persist()

    def refuse(refusal):
        update.event('resume-refused', kind=refusal.kind, error=refusal.args[0])
        update.persist()
        return update.result('resume', refused=refusal)
    try:
        identity, geometry = update.inspect_device()
    except _Refusal as refusal:
        return refuse(refusal)
    if identity != binding['identity']:
        changed = sorted(key for key in identity if identity[key] != binding['identity'].get(key))
        return refuse(_Refusal('identity-changed', 'The device identity differs from the journal: '
                               + ', '.join(changed), {'changed': changed}))
    if geometry != binding['geometry']:
        return refuse(_Refusal('geometry-changed', 'The device memory geometry differs from the journal'))
    reverify = []
    for stage in update.stages:
        if doc['stages'][stage['name']] != 'verified':
            continue
        try:
            outcome, summary, _ = update.operation('verify', stage)
        except DeviceUnavailable as error:
            return refuse(_Refusal('device-unavailable', str(error)))
        reverify.append({'stage': stage['name'], 'complete': outcome.complete, 'first_mismatch': outcome.first_mismatch})
        update.event('reverify-result', stage['name'], complete=outcome.complete, error=outcome.error,
                     first_mismatch=outcome.first_mismatch)
        if not outcome.complete:
            if outcome.first_mismatch is None:
                return refuse(_Refusal('reverify-failed', outcome.error or 'Re-verification did not complete'))
            doc['stages'][stage['name']] = 'pending'
            update.event('stage-restart', stage['name'], from_phase='verified', reason='readback mismatch')
    restarted = None
    for stage in update.stages:
        phase = doc['stages'][stage['name']]
        if phase == 'verified':
            continue
        restarted = restarted or stage['name']
        if phase != 'pending':
            doc['stages'][stage['name']] = 'pending'
            update.event('stage-restart', stage['name'], from_phase=phase, reason='restart from erase')
    doc['status'] = 'in-progress'
    update.persist()
    failed = update.execute()
    return update.result('resume', failed=failed if failed[0] else None,
                         extra={'reverify': reverify, 'restarted_stage': restarted, 'run': doc['runs']})


def verify_device(plan, images, *, opener, flash_size, external_size=None, timeout=30, poll_limit=256,
                  clock=time.monotonic, sleep=time.sleep):
    """Read-only: freshly inspect the device and read back every stage image."""
    try:
        stages = plan_stages(plan, images, flash_size=flash_size, external_size=external_size)
    except _Refusal as refusal:
        return {'complete': False, 'refusal_kind': refusal.kind, 'error': refusal.args[0], 'stages': []}
    update = _Update(plan, images, stages, opener=opener, flash_size=flash_size, external_size=external_size,
                     timeout=timeout, poll_limit=poll_limit, clock=clock, sleep=sleep, journal_path=None)
    try:
        identity, geometry = update.inspect_device()
    except _Refusal as refusal:
        return {'complete': False, 'refusal_kind': refusal.kind, 'error': refusal.args[0], 'stages': []}
    rows = []
    for stage in stages:
        try:
            outcome, _, _ = update.operation('verify', stage)
        except DeviceUnavailable as error:
            rows.append({'stage': stage['name'], 'complete': False, 'error': str(error), 'first_mismatch': None})
            break
        rows.append({'stage': stage['name'], 'complete': outcome.complete, 'error': outcome.error,
                     'first_mismatch': outcome.first_mismatch, 'readback_sha256': outcome.readback_sha256})
    return {'complete': len(rows) == len(stages) and all(row['complete'] for row in rows),
            'identity': identity, 'geometry': geometry, 'stages': rows, 'operations': update.operations,
            'read_only': True, 'physical_device_verified': False}
