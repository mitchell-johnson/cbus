"""Bounded selected-serial commissioning with durable, read-only recovery.

The independently tested device profile is a synthetic two-node KEYE1 fixture.
Serial inventories do not verify firmware/type compatibility of physical nodes.
The caller must exclusively own the PCI and all commissioning activity. Neither
a socket nor matching MMI bookends can prove that prerequisite or atomicity.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import stat
import tempfile
import threading
import time

from .pci import Confirmation, Frame, FrameStream, IdentifyCAL, ReplyCAL, RecallCAL, encode_command
from .pci_full_inventory import PCIInventoryCollector
from .pci_inventory import MMIBlock, _MMIStream
from .pci_local_options import PCILocalOptionsReader, parse_local_options
from .pci_serial_address import _selected_serial, encode_serial_address
from .pci_serial_address_transport import PCISerialAddressTransport
from .pci_serials import PCISerialCollector


MAX_PLAN_BYTES = 4 * 1024 * 1024
MAX_JOURNAL_BYTES = 16 * 1024 * 1024


def _json(value, limit=MAX_PLAN_BYTES):
    try: encoded = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)
    except (ValueError, TypeError, RecursionError) as error:
        raise ValueError('Recovery evidence must be finite JSON data') from error
    if len(encoded.encode('utf-8')) > limit: raise ValueError('Recovery evidence exceeds its size bound')
    return encoded


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result: raise ValueError('Duplicate JSON field: ' + key)
        result[key] = value
    return result


def _load(path, limit):
    with Path(path).open('rb') as handle: raw = handle.read(limit + 1)
    if len(raw) > limit: raise ValueError('Recovery file exceeds its size bound')
    return json.loads(raw, object_pairs_hook=_unique_pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Nonfinite JSON value')))


def _keys(value, expected, name):
    if type(value) is not dict or set(value) != set(expected):
        raise ValueError(name + ' has unsupported or missing fields')


def _hex(value, limit=65536):
    if not isinstance(value, str) or len(value) > limit*2 or len(value)%2 or any(x not in '0123456789abcdef' for x in value):
        raise ValueError('Expected bounded canonical hexadecimal evidence')
    return bytes.fromhex(value)


def _same(actual, expected, name):
    # JSON canonical comparison distinguishes booleans from integer fields.
    if _json(actual) != _json(expected): raise ValueError(name + ' is inconsistent with its evidence')


def _capture(document, expected_request):
    if not isinstance(document, dict): raise ValueError('Missing complete observation')
    for key in ('complete', 'connection_closed'):
        if document.get(key) is not True: raise ValueError('Observation is incomplete or unclosed')
    if document.get('errors') != [] or document.get('unrelated') != []:
        raise ValueError('Commissioning requires an observation without errors or unrelated traffic')
    _same(document.get('request_hex'), expected_request.hex(), 'Observation request')
    raw = _hex(document.get('received_hex'))
    _same(document.get('bytes_received'), len(raw), 'Captured byte count')
    return raw


def _raw_mmi(document, local, checksum):
    raw = _capture(document, b'\\05FF00FAFF00'+(b'03' if checksum else b'')+b'g\r')
    if document.get('format') != 'cbus-pci-mmi-observation-v1' or document.get('termination') != 'coverage_complete':
        raise ValueError('Unsupported MMI observation')
    stream, events = _MMIStream(), []
    for byte in raw: events.extend(stream.feed_byte(byte))
    if stream.buffer or not events or events[0] != Confirmation(b'g', '.'):
        raise ValueError('MMI confirmation/framing is incomplete')
    states, blocks = [], []
    for item in events[1:]:
        if not isinstance(item, MMIBlock) or item.application != 255 or item.start != len(states):
            raise ValueError('MMI blocks must independently cover the whole range without gaps or overlap')
        states.extend(item.states); blocks.append(item.as_dict())
    if len(states) != 256 or states[local] == 0 or 3 in states:
        raise ValueError('MMI coverage, known local presence or healthy states are missing')
    _same(document.get('local_unit'), local, 'MMI local address')
    _same(document.get('states'), states, 'MMI state vector')
    _same(document.get('blocks'), blocks, 'MMI blocks')
    _same(document.get('confirmation'), '.', 'MMI confirmation')
    return states


def _raw_serials(document, local, checksum):
    address = document.get('address') if isinstance(document, dict) else None
    if type(address) is not int or not 0 <= address <= 255: raise ValueError('Invalid inventory address')
    request = encode_command(address, IdentifyCAL(4), confirmation=b'g', checksum=checksum)
    raw = _capture(document, request)
    if document.get('format') != 'cbus-pci-serial-observation-v1' or document.get('termination') != 'quiet':
        raise ValueError('Serial collection did not complete its quiet window')
    _same(document.get('local_unit'), local, 'Serial local address')
    stream, events = FrameStream(), []
    for byte in raw: events.extend(stream.feed(bytes([byte])))
    if stream.buffer or not events or events[0] != Confirmation(b'g', '.'):
        raise ValueError('Serial confirmation/framing is incomplete')
    found, replies = {}, []
    for frame in events[1:]:
        if not isinstance(frame, Frame) or len(frame.cals) != 1:
            raise ValueError('Unexpected serial capture event')
        if any(byte not in b'0123456789abcdefABCDEF' for byte in frame.raw):
            raise ValueError('Unexpected serial frame prefix')
        if frame.bare:
            if address != local: raise ValueError('Remote bare serial cannot be attributed')
        elif frame.source != address or frame.destination != local or frame.route != b'\x00':
            raise ValueError('Serial frame source/destination/route mismatch')
        cal = frame.cals[0]
        if not isinstance(cal, ReplyCAL) or cal.parameter != 4 or len(cal.data) != 12:
            raise ValueError('IDENTIFY4 must contain twelve bytes')
        packed = int.from_bytes(cal.data[5:9], 'big')
        canonical, _ = _selected_serial(f'{packed >> 12}.{packed & 4095}')
        if canonical in found and found[canonical] != cal.data:
            raise ValueError('The same serial has conflicting identity blocks')
        found[canonical] = cal.data
        replies.append((frame, canonical))
    serials = sorted(found, key=lambda s: tuple(map(int, s.split('.'))))
    if not serials: raise ValueError('A present address has no known serial')
    _same(document.get('serials'), serials, 'Serial list')
    _same(document.get('confirmation'), '.', 'Serial confirmation')
    recorded = document.get('replies')
    if not isinstance(recorded, list) or len(recorded) != len(replies):
        raise ValueError('Serial reply evidence differs from the capture')
    for actual, (frame, serial) in zip(recorded, replies):
        _keys(actual, ('source','destination','serial','known','data_hex','raw_hex','received_after_seconds'), 'Serial reply')
        expected = {'source':frame.source, 'destination':frame.destination, 'serial':serial, 'known':True,
                    'data_hex':frame.cals[0].data.hex(), 'raw_hex':frame.raw.hex(),
                    'received_after_seconds':actual['received_after_seconds']}
        _same(actual, expected, 'Serial reply')
        elapsed = actual['received_after_seconds']
        if isinstance(elapsed,bool) or not isinstance(elapsed,(int,float)) or not math.isfinite(elapsed) or elapsed < 0:
            raise ValueError('Invalid serial arrival time')
    return address, serials


def _inventory_proof(document, endpoint, local, checksum):
    """Reparse all captured protocol bytes; summaries cannot supply absence."""
    _json(document)
    if document.get('format') != 'cbus-pci-inventory-observation-v1': raise ValueError('Unsupported inventory format')
    _same(document.get('endpoint'), endpoint, 'Inventory endpoint')
    _same(document.get('local_unit'), local, 'Inventory local address')
    for key in ('complete','collection_complete','consistent','membership_unchanged','connection_closed','mmi_healthy'):
        if document.get(key) is not True: raise ValueError('Full consistent healthy inventory is required')
    if document.get('termination') != 'sequence_complete' or document.get('errors') != []:
        raise ValueError('Inventory collection did not complete')
    first = _raw_mmi(document.get('initial_mmi'), local, checksum)
    last = _raw_mmi(document.get('final_mmi'), local, checksum)
    _same(first, last, 'Full MMI bookends')
    if not isinstance(document.get('serial_observations'), list): raise ValueError('Missing serial observations')
    identities = [_raw_serials(item, local, checksum) for item in document['serial_observations']]
    addresses = [address for address, state in enumerate(first) if state]
    _same([address for address, _ in identities], addresses, 'Serial coverage')
    _same(document.get('planned_addresses'), addresses, 'Planned coverage')
    _same(document.get('unattempted_addresses'), [], 'Unattempted addresses')
    seen = set()
    for _, serials in identities:
        if seen.intersection(serials): raise ValueError('A serial appears at multiple addresses')
        seen.update(serials)
    duplicates = [address for address, serials in identities if len(serials)>1]
    _same(document.get('duplicate_addresses'), duplicates, 'Duplicate-address summary')
    for key in ('serial_conflicts','missing_serial_addresses','changed_states','error_addresses'):
        _same(document.get(key), [], key)
    return {'states':first, 'identities':[{'address':a,'serials':s} for a,s in identities]}


def _options_proof(document, local, checksum):
    _keys(document, ('format','local_unit','request_hex','received_hex','value','send_attempted','capture_complete',
                    'complete','termination','connection_closed','errors','timing','bare_reply_attribution',
                    'identity_verified','options_changed','automatic_retries'), 'Local options observation')
    expected = encode_command(local, RecallCAL(66,1), confirmation=b'g', checksum=checksum)
    _same(document['request_hex'], expected.hex(), 'Local options request')
    _same(document['local_unit'],local,'Options local address')
    if (document['format'] != 'cbus-pci-local-options-observation-v1' or
            any(document[key] is not True for key in ('complete','capture_complete','send_attempted','connection_closed')) or
            document['errors'] != [] or document['termination'] != 'response_window_elapsed'):
        raise ValueError('A complete fresh local options observation is required')
    value = parse_local_options(_hex(document['received_hex'],4096),local_unit=local)
    _same(document['value'],value,'Local options value')
    if value != 5: raise ValueError('The bounded coordinator requires freshly observed local option byte 05')


def _expected(before, serial, destination, local_serial, local):
    identities = {row['address']:list(row['serials']) for row in before['identities']}
    if identities.get(local) != [local_serial]: raise ValueError('Pinned local PCI serial does not match')
    if len(identities.get(255, [])) != 2 or serial not in identities[255]:
        raise ValueError('Source 255 must contain exactly two distinct serials including the selected serial')
    if any(len(values)!=1 for address,values in identities.items() if address != 255):
        raise ValueError('Other duplicate addresses are outside the supported scope')
    if destination == local or destination in identities or before['states'][destination] != 0:
        raise ValueError('Destination must be independently empty and nonlocal')
    if before['states'][255] != 2:
        raise ValueError('The supported source fixture must have MMI state 2')
    identities[255].remove(serial); identities[destination] = [serial]
    states = list(before['states']); states[destination] = states[255]
    return {'states':states, 'identities':[{'address':a,'serials':s} for a,s in sorted(identities.items())]}


@dataclass(frozen=True)
class SelectedSerialPlan:
    _document: str

    def as_dict(self): return json.loads(self._document)

    @classmethod
    def from_dict(cls, value):
        value = json.loads(_json(value))
        _keys(value, ('format','endpoint','local_unit','expected_local_serial','source','serial','destination',
                      'settings','before','local_identity','local_options','expected_after','request_hex',
                      'scope','atomic_observation','firmware_persistence_verified','exclusive_ownership_required'), 'Plan')
        if value['format'] != 'cbus-selected-serial-plan-v1': raise ValueError('Unsupported selected-serial plan')
        _keys(value['endpoint'], ('host','port'), 'Endpoint')
        _keys(value['settings'], ('overall_timeout','observation_timeout','confirmation_timeout','mmi_response_timeout',
            'quiet_period','options_response_timeout','address_response_timeout','max_mmi_frames','max_serial_frames',
            'max_unrelated','max_bytes','command_checksum'), 'Settings')
        # Constructors validate settings/endpoint without I/O.
        coordinator = SelectedSerialCoordinator(**value['endpoint'],local_unit=value['local_unit'],
            expected_local_serial=value['expected_local_serial'],**value['settings'])
        serial, _ = _selected_serial(value['serial'])
        if serial != value['serial'] or coordinator.expected_local_serial != value['expected_local_serial']:
            raise ValueError('Plan serials must be canonical')
        if type(value['source']) is not int or value['source'] != 255: raise ValueError('Only source 255 is supported')
        request = encode_serial_address(serial,value['destination'],command_checksum=coordinator.command_checksum)
        _same(value['request_hex'],request.hex(),'Address request')
        proof = _inventory_proof(value['before'],value['endpoint'],value['local_unit'],coordinator.command_checksum)
        local, observed = _raw_serials(value['local_identity'],value['local_unit'],coordinator.command_checksum)
        if local != value['local_unit'] or observed != [value['expected_local_serial']]:
            raise ValueError('Fresh local identity does not match the pinned serial')
        _options_proof(value['local_options'],value['local_unit'],coordinator.command_checksum)
        expected = _expected(proof,serial,value['destination'],value['expected_local_serial'],value['local_unit'])
        _same(value['expected_after'],expected,'Expected selected-serial change')
        _same(value['scope'],'two_known_serials_at_255_explicit_empty_destination','Scope')
        _same(value['atomic_observation'],False,'Atomicity')
        _same(value['firmware_persistence_verified'],False,'Persistence')
        _same(value['exclusive_ownership_required'],True,'Ownership prerequisite')
        return cls(_json(value))

    @classmethod
    def load(cls,path): return cls.from_dict(_load(path,MAX_PLAN_BYTES))


class SelectedSerialError(RuntimeError):
    """Preconditions failed; best evidence is attached as selected_serial_evidence."""


class SelectedSerialUncertain(SelectedSerialError):
    """An attempt was recorded; do not replay. Use independent read-only verify."""


@dataclass(frozen=True)
class SelectedSerialResult:
    _document: str

    def as_dict(self): return json.loads(self._document)

    @property
    def outcome(self): return self.as_dict()['outcome']

    @property
    def observed_expected_change(self): return self.outcome == 'observed_expected_change'


class _Journal:
    """Exclusive new file followed by checked atomic replacements and fsync.

    A failed directory sync can leave the new record visible without proving
    crash durability. Record that distinction and stop before any bus request.
    """
    def __init__(self,path):
        self.path = Path(path).absolute()
        self.expected = None
        self.failed = False
        self.last_update = {}

    def _sync_directory(self):
        descriptor = os.open(self.path.parent,os.O_RDONLY)
        try: os.fsync(descriptor)
        except BaseException:
            try: os.close(descriptor)
            except BaseException as error:
                self.last_update.setdefault('cleanup_errors',[]).append({'type':type(error).__name__,'message':str(error)})
            raise
        else: os.close(descriptor)

    def _read_current(self):
        # Bounds apply even if an external writer replaces our journal. Refuse
        # symlinks/nonregular files and avoid blocking on a substituted FIFO.
        descriptor=os.open(self.path,os.O_RDONLY|getattr(os,'O_NONBLOCK',0)|getattr(os,'O_NOFOLLOW',0))
        handle=None
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode): raise ValueError('Recovery journal is not a regular file')
            handle=os.fdopen(descriptor,'rb')
            raw=handle.read(MAX_JOURNAL_BYTES+1)
            if len(raw)>MAX_JOURNAL_BYTES: raise ValueError('Recovery journal exceeds its size bound')
        except BaseException:
            try:
                if handle is None: os.close(descriptor)
                else: handle.close()
            except BaseException as error:
                self.last_update.setdefault('cleanup_errors',[]).append({'type':type(error).__name__,'message':str(error)})
            raise
        else:
            handle.close()
            return raw

    def _write_descriptor(self,descriptor,raw):
        handle=None
        try:
            handle=os.fdopen(descriptor,'wb')
            handle.write(raw);handle.flush();os.fsync(handle.fileno())
            self.last_update['file_synced']=True
        except BaseException:
            try:
                if handle is None: os.close(descriptor)
                else: handle.close()
            except BaseException as error:
                self.last_update.setdefault('cleanup_errors',[]).append({'type':type(error).__name__,'message':str(error)})
            raise
        else: handle.close()

    def write(self, value):
        raw = (_json(value,MAX_JOURNAL_BYTES)+'\n').encode('utf-8')
        initial = self.expected is None
        state = {'initial_creation':initial,'file_synced':False,'replacement_attempted':False,
                 'replacement_completed':False,'directory_synced':False,'disk_matches_proposed':None}
        self.last_update = state
        temporary = None
        try:
            if initial:
                descriptor = os.open(self.path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                self._write_descriptor(descriptor,raw)
            else:
                if self._read_current() != self.expected:
                    raise RuntimeError('Recovery journal changed outside this exclusive writer')
                descriptor, temporary = tempfile.mkstemp(prefix='.'+self.path.name+'.',dir=self.path.parent)
                self._write_descriptor(descriptor,raw)
                state['replacement_attempted']=True
                os.replace(temporary,self.path);state['replacement_completed']=True;temporary=None
            self._sync_directory();state['directory_synced']=True
            self.expected=raw;state['disk_matches_proposed']=True
        except BaseException:
            self.failed=True
            try: state['disk_matches_proposed']=self._read_current()==raw
            except FileNotFoundError: state['disk_matches_proposed']=False
            except BaseException as error:
                state['disk_matches_proposed']=None
                state['probe_error']={'type':type(error).__name__,'message':str(error)}
            raise
        finally:
            if temporary is not None:
                try: os.unlink(temporary)
                except BaseException as error:
                    state.setdefault('cleanup_errors',[]).append({'type':type(error).__name__,'message':str(error)})


class SelectedSerialCoordinator:
    """Exactly one selected-serial attempt, preceded/followed by full observations.

    This is an opt-in fixture/observation workflow, not a device compatibility
    detector. The caller must hold exclusive endpoint and commissioning access.
    No retries, option writes, fallback destination or automatic rollback exist.
    overall_timeout starts after pure input/plan validation and lock admission;
    it bounds the admitted transaction, not waiting to acquire this process lock.
    """
    def __init__(self,host,port=10001,*,local_unit,expected_local_serial,overall_timeout=600.,
                 observation_timeout=10.,confirmation_timeout=2.,mmi_response_timeout=5.5,quiet_period=2.,
                 options_response_timeout=2.,address_response_timeout=2.,max_mmi_frames=7,max_serial_frames=7,
                 max_unrelated=64,max_bytes=65536,command_checksum=False):
        inventory=PCIInventoryCollector(host,port,local_unit=local_unit,overall_timeout=overall_timeout,
            observation_timeout=observation_timeout,confirmation_timeout=confirmation_timeout,
            response_timeout=mmi_response_timeout,quiet_period=quiet_period,max_mmi_frames=max_mmi_frames,
            max_serial_frames=max_serial_frames,max_unrelated=max_unrelated,max_bytes=max_bytes,
            command_checksum=command_checksum)
        options=PCILocalOptionsReader(host,port,local_unit=local_unit,response_timeout=options_response_timeout,
            overall_timeout=observation_timeout,command_checksum=command_checksum)
        transport=PCISerialAddressTransport(host,port,local_unit=local_unit,response_timeout=address_response_timeout,
            overall_timeout=observation_timeout,command_checksum=command_checksum)
        self.host,self.port,self.local_unit=inventory.host,inventory.port,local_unit
        self.expected_local_serial=_selected_serial(expected_local_serial)[0]
        self.command_checksum=command_checksum
        self.settings={'overall_timeout':inventory.overall_timeout,'observation_timeout':inventory.observation_timeout,
            'confirmation_timeout':inventory.confirmation_timeout,'mmi_response_timeout':inventory.response_timeout,
            'quiet_period':inventory.quiet_period,'options_response_timeout':options.response_timeout,
            'address_response_timeout':transport.response_timeout,'max_mmi_frames':max_mmi_frames,
            'max_serial_frames':max_serial_frames,'max_unrelated':max_unrelated,'max_bytes':max_bytes,
            'command_checksum':command_checksum}
        self._lock=threading.Lock();self._apply_used=False
        self.last_result=None;self.last_evidence=None

    def _inventory(self):
        s=self.settings
        return PCIInventoryCollector(self.host,self.port,local_unit=self.local_unit,
            overall_timeout=s['overall_timeout'],observation_timeout=s['observation_timeout'],
            confirmation_timeout=s['confirmation_timeout'],response_timeout=s['mmi_response_timeout'],
            quiet_period=s['quiet_period'],max_mmi_frames=s['max_mmi_frames'],max_serial_frames=s['max_serial_frames'],
            max_unrelated=s['max_unrelated'],max_bytes=s['max_bytes'],command_checksum=self.command_checksum)

    def _local_identity(self):
        s=self.settings
        return PCISerialCollector(self.host,self.port,local_unit=self.local_unit,overall_timeout=s['observation_timeout'],
            confirmation_timeout=s['confirmation_timeout'],quiet_period=s['quiet_period'],
            max_frames=s['max_serial_frames'],max_unrelated=s['max_unrelated'],max_bytes=s['max_bytes'],
            command_checksum=self.command_checksum)

    def _options(self):
        return PCILocalOptionsReader(self.host,self.port,local_unit=self.local_unit,
            response_timeout=self.settings['options_response_timeout'],overall_timeout=self.settings['observation_timeout'],
            command_checksum=self.command_checksum)

    def _transport(self):
        return PCISerialAddressTransport(self.host,self.port,local_unit=self.local_unit,
            response_timeout=self.settings['address_response_timeout'],overall_timeout=self.settings['observation_timeout'],
            command_checksum=self.command_checksum)

    def _new_journal(self,path): return _Journal(path)

    def _phase(self,evidence,key,child,method,deadline,*args):
        if time.monotonic() >= deadline: raise TimeoutError('Overall deadline reached before '+key)
        child._absolute_deadline=deadline
        result=None;first=None
        try:
            if key=='exchange':
                evidence['transport_invoked']=True
                evidence['send_attempted']=None  # Unknown until the child records its actual sendall boundary.
            result=getattr(child,method)(*args)
        except BaseException as error:
            first=error
            raise
        finally:
            try:
                saved=getattr(child,'last_observation',None) or getattr(child,'last_exchange',None) or result
                if saved is not None: evidence[key]=saved.as_dict()
            except BaseException as error:
                if first is None: raise
                evidence['errors'].append({'phase':key+'_evidence','type':type(error).__name__,'message':str(error)})
        if time.monotonic() >= deadline: raise TimeoutError('Overall deadline reached during '+key)
        return result

    def _before(self,evidence,deadline):
        self._phase(evidence,'before',self._inventory(),'collect_inventory',deadline)
        proof=_inventory_proof(evidence['before'],{'host':self.host,'port':self.port},self.local_unit,self.command_checksum)
        self._phase(evidence,'local_identity',self._local_identity(),'collect_serials',deadline,self.local_unit)
        local,serials=_raw_serials(evidence['local_identity'],self.local_unit,self.command_checksum)
        if local!=self.local_unit or serials!=[self.expected_local_serial]:
            raise ValueError('Pinned local PCI serial changed before transmission')
        self._phase(evidence,'local_options',self._options(),'read_options',deadline)
        _options_proof(evidence['local_options'],self.local_unit,self.command_checksum)
        return proof

    def _base(self,operation,plan=None):
        return {'format':'cbus-selected-serial-result-v1','operation':operation,'state':'validated',
            'outcome':'uncertain','plan':None if plan is None else plan.as_dict(),
            'before':None,'local_identity':None,'local_options':None,'exchange':None,'after':None,
            'attempt_recorded':False,'attempt_durability_verified':False,'transport_invoked':False,
            'send_attempted':False,'receipt_matches_request':None,
            'after_collection_complete':False,'expected_identity_change':False,'unexpected_changes':[],
            'errors':[],'journal':None,'atomic_observation':False,'firmware_persistence_verified':False,
            'physical_compatibility_verified':False,'exclusive_ownership_required':True,
            'automatic_retries':0,'automatic_rollback':False,'database_updated':False,
            'deadline_scope':'transaction_after_validation_and_lock'}

    def _error(self,error,evidence,journal=None):
        exchange=evidence.get('exchange')
        if exchange is not None: evidence['send_attempted']=exchange['send_attempted']
        evidence['outcome']='uncertain' if evidence['attempt_recorded'] or evidence['operation']=='verify' else 'preconditions_failed'
        evidence['errors'].append({'type':type(error).__name__,'message':str(error)})
        if journal is not None:
            if not journal.failed:
                try: journal.write(evidence)
                except BaseException as secondary:
                    evidence['errors'].append({'phase':'recovery_update','type':type(secondary).__name__,'message':str(secondary)})
            evidence['journal']={'path':str(journal.path),'last_update':dict(journal.last_update),'failed':journal.failed}
        try: self.last_evidence=json.loads(_json(evidence,MAX_JOURNAL_BYTES))
        except BaseException as secondary:
            evidence['errors'].append({'phase':'evidence_copy','type':type(secondary).__name__,'message':str(secondary)})
            self.last_evidence=evidence
        error.selected_serial_evidence=self.last_evidence
        return error

    def plan(self,serial,destination,*,source=255):
        serial,_=_selected_serial(serial)
        request=encode_serial_address(serial,destination,command_checksum=self.command_checksum)
        if type(source) is not int or source!=255: raise ValueError('Only source address 255 is supported')
        if destination==self.local_unit: raise ValueError('Local PCI relocation is unsupported')
        with self._lock:
            evidence=self._base('plan')
            try:
                deadline=time.monotonic()+self.settings['overall_timeout']
                before=self._before(evidence,deadline)
                expected=_expected(before,serial,destination,self.expected_local_serial,self.local_unit)
                value={'format':'cbus-selected-serial-plan-v1','endpoint':{'host':self.host,'port':self.port},
                    'local_unit':self.local_unit,'expected_local_serial':self.expected_local_serial,'source':source,
                    'serial':serial,'destination':destination,'settings':dict(self.settings),
                    'before':evidence['before'],'local_identity':evidence['local_identity'],
                    'local_options':evidence['local_options'],'expected_after':expected,'request_hex':request.hex(),
                    'scope':'two_known_serials_at_255_explicit_empty_destination','atomic_observation':False,
                    'firmware_persistence_verified':False,'exclusive_ownership_required':True}
                result=SelectedSerialPlan.from_dict(value)
                if time.monotonic()>=deadline: raise TimeoutError('Overall deadline reached during plan finalization')
                self.last_evidence=value
                return result
            except BaseException as error:
                self._error(error,evidence)
                raise

    def _validated_plan(self,plan):
        if not isinstance(plan,SelectedSerialPlan): raise TypeError('Expected a validated SelectedSerialPlan')
        plan=SelectedSerialPlan.from_dict(plan.as_dict());value=plan.as_dict()
        _same(value['endpoint'],{'host':self.host,'port':self.port},'Coordinator endpoint')
        _same(value['local_unit'],self.local_unit,'Coordinator local address')
        _same(value['expected_local_serial'],self.expected_local_serial,'Coordinator local serial')
        _same(value['settings'],self.settings,'Coordinator settings')
        return plan,value

    def _classify(self,evidence,value):
        after=evidence['after']
        evidence['after_collection_complete']=bool(after and after.get('collection_complete'))
        try: observed=_inventory_proof(after,value['endpoint'],self.local_unit,self.command_checksum)
        except (ValueError,TypeError,AttributeError) as error:
            evidence['errors'].append({'phase':'after_validation','type':type(error).__name__,'message':str(error)})
            return
        before=_inventory_proof(value['before'],value['endpoint'],self.local_unit,self.command_checksum)
        expected=value['expected_after']
        if observed==expected:
            evidence['outcome']='observed_expected_change';evidence['expected_identity_change']=True
        elif observed==before: evidence['outcome']='observed_unchanged'
        else: evidence['outcome']='observed_unexpected_change'
        actual={x['address']:x['serials'] for x in observed['identities']}
        wanted={x['address']:x['serials'] for x in expected['identities']}
        evidence['unexpected_changes']=[{'address':a,'expected_serials':wanted.get(a,[]),'observed_serials':actual.get(a,[]),
            'expected_state':expected['states'][a],'observed_state':observed['states'][a]}
            for a in range(256) if wanted.get(a,[])!=actual.get(a,[]) or expected['states'][a]!=observed['states'][a]]

    def apply(self,plan,*,recovery_path):
        plan,value=self._validated_plan(plan)
        with self._lock:
            if self._apply_used: raise RuntimeError('A coordinator cannot apply twice; use read-only verify after an attempt')
            self._apply_used=True
            evidence=self._base('apply',plan);journal=None
            try:
                deadline=time.monotonic()+self.settings['overall_timeout']
                before=self._before(evidence,deadline)
                original=_inventory_proof(value['before'],value['endpoint'],self.local_unit,self.command_checksum)
                _same(before,original,'Fresh complete inventory')
                _expected(before,value['serial'],value['destination'],self.expected_local_serial,self.local_unit)
                # Prepare the pure child before durably marking a possible send.
                transport=self._transport()
                if time.monotonic()>=deadline: raise TimeoutError('Overall deadline reached before journal creation')
                evidence['state']='preconditions_checked';journal=self._new_journal(recovery_path)
                evidence['journal']={'path':str(journal.path)};journal.write(evidence)
                evidence['state']='write_attempted';evidence['attempt_recorded']=True
                journal.write(evidence)  # If durable attempt marking fails, no co is invoked.
                evidence['attempt_durability_verified']=True
                self._phase(evidence,'exchange',transport,'send_serial_address',deadline,value['serial'],value['destination'])
                exchange=evidence['exchange'];evidence['send_attempted']=exchange['send_attempted']
                evidence['receipt_matches_request']=exchange['retained_receipt_matches_request']
                evidence['state']='receipt_collected'
                if (exchange['errors'] or not exchange['capture_complete'] or not exchange['connection_closed'] or
                        exchange['receipt']['errors'] or exchange['receipt']['pending_hex']):
                    raise SelectedSerialUncertain('Address request outcome is uncertain; no replay or follow-up I/O was attempted')
                journal.write(evidence)
                self._phase(evidence,'after',self._inventory(),'collect_inventory',deadline)
                evidence['state']='after_observed';self._classify(evidence,value)
                journal.write(evidence)
                evidence['journal']={'path':str(journal.path),'last_update':dict(journal.last_update),'failed':False}
                result=SelectedSerialResult(_json(evidence,MAX_JOURNAL_BYTES))
                final_evidence=result.as_dict()
                if time.monotonic()>=deadline: raise TimeoutError('Overall deadline reached during recovery journal/result finalization')
                self.last_result=result;self.last_evidence=final_evidence
                return result
            except BaseException as error:
                self._error(error,evidence,journal)
                raise

    def verify(self,plan):
        """Gather a fresh full inventory only. Never construct/use address transport."""
        plan,value=self._validated_plan(plan)
        with self._lock:
            evidence=self._base('verify',plan)
            try:
                deadline=time.monotonic()+self.settings['overall_timeout']
                self._phase(evidence,'after',self._inventory(),'collect_inventory',deadline)
                evidence['state']='after_observed';self._classify(evidence,value)
                result=SelectedSerialResult(_json(evidence,MAX_JOURNAL_BYTES))
                final_evidence=result.as_dict()
                if time.monotonic()>=deadline: raise TimeoutError('Overall deadline reached during verification finalization')
                self.last_result=result;self.last_evidence=final_evidence
                return result
            except BaseException as error:
                self._error(error,evidence)
                raise

    @staticmethod
    def load_recovery(path):
        """Load only the strictly validated plan from a bounded journal.

        Historical outcome fields are not authenticated. Recovery always obtains
        a new read-only observation; this function never authorizes replay.
        """
        value=_load(path,MAX_JOURNAL_BYTES)
        if not isinstance(value,dict) or value.get('format')!='cbus-selected-serial-result-v1':
            raise ValueError('Unsupported selected-serial recovery journal')
        plan=SelectedSerialPlan.from_dict(value.get('plan'));document=plan.as_dict()
        validator=SelectedSerialCoordinator(**document['endpoint'],local_unit=document['local_unit'],
            expected_local_serial=document['expected_local_serial'],**document['settings'])
        _keys(value,validator._base('apply'),'Recovery journal')
        if value['operation']!='apply': raise ValueError('Recovery requires an apply journal')
        return plan
