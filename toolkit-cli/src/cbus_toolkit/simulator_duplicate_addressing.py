"""Opt-in serial-keyed duplicate assignment fixture, never hardware firmware.

The caller chooses whether co also updates parameter32. Both policies persist
the fixture's bus topology; neither establishes real-device EEPROM behavior.
Only co changes nodes. Generic writes, unlocks and application commands reject.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile

from .serials import parse_native_serial
from .simulator import PCISimulator, UnitState
from .simulator_duplicates import _clone, _serial


@dataclass(frozen=True)
class SerialAddressFault:
    move: bool = True
    reply: bool = True
    bare: bool = False
    reported_source: int | None = None
    reported_serial: str | None = None

    def __post_init__(self):
        if any(type(value) is not bool for value in (self.move,self.reply,self.bare)):
            raise ValueError("Fault move/reply/bare values must be Boolean")
        if self.reported_source is not None and (type(self.reported_source) is not int or not 0 <= self.reported_source <= 255):
            raise ValueError("Fault source must be an explicit address byte")
        if self.reported_serial is not None:
            if parse_native_serial(self.reported_serial).canonical != self.reported_serial:
                raise ValueError("Fault serial must use canonical decimal-dot spelling")
        if not self.reply and (self.bare or self.reported_source is not None or self.reported_serial is not None):
            raise ValueError("No-reply fault cannot specify receipt overrides")
        if self.bare and self.reported_source is not None:
            raise ValueError("Bare receipt cannot specify a source")


def _unit_document(unit):
    return {"address":unit.address,"mmi_state":unit.mmi_state,
            "attributes":{str(key):value.hex() for key,value in sorted(unit.attributes.items())},
            "parameters":{str(key):value.hex() for key,value in sorted(unit.parameters.items())}}


def _unit_from_document(value):
    if not isinstance(value,dict) or set(value)!={"address","mmi_state","attributes","parameters"}:
        raise ValueError("Invalid serial fixture unit fields")
    def blocks(name):
        if not isinstance(value[name],dict):raise ValueError("Unit blocks must be mappings")
        result={}
        for key,data in value[name].items():
            if not isinstance(key,str) or not key.isascii() or not key.isdecimal() or str(int(key))!=key:
                raise ValueError("Unit block keys must be canonical decimal bytes")
            if not isinstance(data,str) or len(data)%2 or any(char not in '0123456789abcdefABCDEF' for char in data):
                raise ValueError("Unit block values must be hexadecimal bytes")
            result[int(key)]=bytes.fromhex(data)
        return result
    return UnitState(value['address'],blocks('attributes'),blocks('parameters'),{},value['mmi_state'])


class SerialAddressFixture(PCISimulator):
    """Two explicit KEYE1 nodes plus a PCI, with serial-keyed persistent state.

    ``allowed_destinations`` is a fixture scope allowlist, never a firmware
    claim about occupied-target rejection. The operation checks actual fixture
    occupancy each time. Node order persists separately from JSON key order.
    """
    FORMAT="cbus-serial-address-fixture-v1"

    def __init__(self,nodes,pci,*,allowed_destinations,address_memory_policy,reply_tails,
                 faults=None,state_path=None,command_checksum=False,fragment_sizes=(),
                 wire_log_path=None,response_delay=0):
        if not isinstance(nodes,(tuple,list)) or len(nodes)!=2:
            raise ValueError("Exactly two explicit physical nodes are required")
        nodes=[_clone(node) for node in nodes];pci=_clone(pci)
        if address_memory_policy not in ('bus_only','parameter32'):
            raise ValueError("Choose explicit bus_only or parameter32 address memory policy")
        if (not 1 <= pci.address <= 254 or pci.attributes.get(1)!=b'PC_CNIED' or
                pci.attributes.get(2)!=b'5.5.00  ' or pci.parameters.get(32)!=bytes([pci.address]) or
                pci.parameters.get(66) not in (b'\x05',b'\x07') or pci.write_tags or pci.mmi_state!=1):
            raise ValueError("PCI requires explicit PC_CNIED 5.5.00 identity, address, options05/07 and read-only blocks")
        for node in nodes:
            if (not 2 <= node.address <= 255 or node.address==pci.address or
                    node.attributes.get(1)!=b'KEYE1   ' or node.attributes.get(2)!=b'2.5.00  ' or
                    len(node.parameters.get(32,b''))!=1 or node.write_tags or node.mmi_state!=2):
                raise ValueError("Nodes require explicit read-only KEYE1 2.5.00 blocks and MMI state2")
            if address_memory_policy=='parameter32' and node.parameters[32]!=bytes([node.address]):
                raise ValueError("parameter32 policy requires matching bus and parameter addresses")
        if nodes[0].address==nodes[1].address and nodes[0].address!=255:
            raise ValueError("Duplicate fixture occupancy is supported only at address255")
        for field,exclude in (('attributes',4),('parameters',32)):
            if ({key:value for key,value in getattr(nodes[0],field).items() if key!=exclude} !=
                    {key:value for key,value in getattr(nodes[1],field).items() if key!=exclude}):
                raise ValueError("Source profiles must match apart from serial and UnitAddress")
        serials=[_serial(node) for node in nodes];pci_serial=_serial(pci)
        if len(set(serials+[pci_serial]))!=3:raise ValueError("All physical serial identities must be distinct and known")
        if not isinstance(allowed_destinations,(tuple,list,set,frozenset)) or not allowed_destinations:
            raise ValueError("Explicit allowed destinations must be a nonempty sequence")
        if (any(type(address) is not int or not 2 <= address <= 254 or address==pci.address for address in allowed_destinations)
                or len(set(allowed_destinations))!=len(allowed_destinations)):
            raise ValueError("Allowed destinations must be distinct nonlocal addresses in2..254")
        if (not isinstance(reply_tails,dict) or set(reply_tails)!=set(serials) or
                any(not isinstance(tail,bytes) or len(tail)!=2 for tail in reply_tails.values())):
            raise ValueError("Every physical serial needs exactly two explicit opaque reply bytes")
        faults={} if faults is None else faults
        if not isinstance(faults,dict) or not set(faults)<=set(serials) or any(not isinstance(fault,SerialAddressFault) for fault in faults.values()):
            raise ValueError("Faults must map configured serials to SerialAddressFault values")
        if state_path is not None and Path(state_path).exists():
            raise ValueError("Existing fixture state must be loaded explicitly with from_state")
        self._nodes=dict(zip(serials,nodes));self._node_order=tuple(serials);self._pci=pci
        self.allowed_destinations=frozenset(allowed_destinations)
        self.address_memory_policy=address_memory_policy
        self.reply_tails=dict(reply_tails);self.faults={serial:faults.get(serial,SerialAddressFault()) for serial in serials}
        self.revision=0;self.co_operations=[];self._expected_file_bytes=None
        representatives={pci.address:pci}
        for node in nodes:representatives.setdefault(node.address,node)
        super().__init__(list(representatives.values()),local_unit=pci.address,profile='synthetic',physical_memory={},
                         lighting_groups=[],command_checksum=command_checksum,fragment_sizes=fragment_sizes,
                         wire_log_path=wire_log_path,response_delay=response_delay)
        self._rebuild()
        self.state_path=Path(state_path) if state_path is not None else None
        self._persist()

    def _rebuild(self):
        self.units={self.local_unit:self._pci}
        for serial in self._node_order:
            node=self._nodes[serial];self.units.setdefault(node.address,node)

    @property
    def nodes(self):
        with self._lock:return {serial:_clone(self._nodes[serial]) for serial in self._node_order}

    def _document(self):
        return {'format':self.FORMAT,'fixture_only':True,'firmware_persistence_verified':False,
                'address_memory_policy':self.address_memory_policy,'revision':self.revision,
                'response_order':list(self._node_order),'physical_nodes':{serial:_unit_document(self._nodes[serial]) for serial in self._node_order},
                'pci':_unit_document(self._pci),'allowed_destinations':sorted(self.allowed_destinations),
                'reply_tails':{serial:self.reply_tails[serial].hex() for serial in self._node_order},
                'faults':{serial:asdict(self.faults[serial]) for serial in self._node_order}}

    @staticmethod
    def _bytes(document):return (json.dumps(document,sort_keys=True,indent=2)+'\n').encode('utf-8')

    def _persist(self):
        if self.state_path is None:return
        current=self.state_path.read_bytes() if self.state_path.exists() else None
        if current!=self._expected_file_bytes:raise ValueError("Fixture state changed externally; refusing to overwrite it")
        payload=self._bytes(self._document());self.state_path.parent.mkdir(parents=True,exist_ok=True)
        descriptor,temporary=tempfile.mkstemp(prefix='.serial-fixture-',dir=self.state_path.parent)
        pending=None
        try:
            with os.fdopen(descriptor,'wb') as handle:
                handle.write(payload);handle.flush();os.fsync(handle.fileno())
            os.replace(temporary,self.state_path)
            self._expected_file_bytes=payload
        except BaseException as error:pending=error
        try:
            if os.path.exists(temporary):os.unlink(temporary)
        except BaseException as error:
            if pending is None:pending=error
            elif isinstance(pending,Exception) and not isinstance(error,Exception):
                error.fixture_persistence_prior_error=type(pending).__name__+': '+str(pending)
                pending=error
            else:pending.fixture_persistence_cleanup_error=type(error).__name__+': '+str(error)
        if pending is not None:raise pending

    @classmethod
    def from_state(cls,path,**transport):
        permitted={'command_checksum','fragment_sizes','wire_log_path','response_delay'}
        if not set(transport)<=permitted:raise ValueError("State loading accepts only transport options")
        path=Path(path)
        with path.open('rb') as handle:raw=handle.read(1048577)
        if len(raw)>1048576:raise ValueError("Serial fixture state exceeds1MiB")
        def unique(pairs):
            result={}
            for key,value in pairs:
                if key in result:raise ValueError("Duplicate JSON state key")
                result[key]=value
            return result
        try:
            document=json.loads(raw,object_pairs_hook=unique)
            required={'format','fixture_only','firmware_persistence_verified','address_memory_policy','revision',
                      'response_order','physical_nodes','pci','allowed_destinations','reply_tails','faults'}
            if (not isinstance(document,dict) or set(document)!=required or document['format']!=cls.FORMAT or
                    document['fixture_only'] is not True or document['firmware_persistence_verified'] is not False):
                raise ValueError("Unsupported serial fixture state format")
            order=document['response_order'];physical=document['physical_nodes']
            if (not isinstance(order,list) or len(order)!=2 or any(not isinstance(serial,str) for serial in order) or
                    len(set(order))!=2 or not isinstance(physical,dict) or set(order)!=set(physical)):
                raise ValueError("Invalid serial response order/topology")
            if type(document['revision']) is not int or not 0 <= document['revision'] < 2**63:
                raise ValueError("Invalid fixture revision")
            nodes=[_unit_from_document(physical[serial]) for serial in order]
            if any(_serial(node)!=serial for node,serial in zip(nodes,order)):
                raise ValueError("Stored serial key does not match physical IDENTIFY4")
            if not isinstance(document['reply_tails'],dict) or not isinstance(document['faults'],dict):
                raise ValueError("Invalid receipt/fault maps")
            if set(document['faults'])!=set(order):raise ValueError("Every stored physical serial needs a fault policy")
            tails={}
            for serial,value in document['reply_tails'].items():
                if not isinstance(value,str) or len(value)!=4 or any(c not in '0123456789abcdefABCDEF' for c in value):
                    raise ValueError("Opaque receipt tails must contain two hexadecimal bytes")
                tails[serial]=bytes.fromhex(value)
            fields={'move','reply','bare','reported_source','reported_serial'}
            if any(not isinstance(value,dict) or set(value)!=fields for value in document['faults'].values()):
                raise ValueError("Invalid stored fault policy fields")
            result=cls(nodes,_unit_from_document(document['pci']),allowed_destinations=document['allowed_destinations'],
                       address_memory_policy=document['address_memory_policy'],reply_tails=tails,
                       faults={serial:SerialAddressFault(**value) for serial,value in document['faults'].items()},**transport)
            result.revision=document['revision'];result.state_path=path;result._expected_file_bytes=raw
            return result
        except (KeyError,TypeError,AttributeError,UnicodeError) as error:
            raise ValueError("Invalid serial fixture state") from error

    def _co(self,payload):
        if len(payload)!=11 or payload[:5]!=b'\x05\xff\x00\x0f\x00' or sum(payload[4:])&255:
            raise ValueError("Invalid serial assignment shape or inner checksum")
        packed=int.from_bytes(payload[5:9],'big');serial=f'{packed>>12}.{packed&4095}';target=payload[9]
        record={'serial':serial,'requested_destination':target,'payload_hex':payload.hex(),'old_address':None,
                'new_address':None,'persistence':'not_changed'}
        self.co_operations.append(record)
        node=self._nodes.get(serial)
        if node is None:
            record['outcome']='no_matching_serial';return b''
        record['old_address']=record['new_address']=node.address
        if target not in self.allowed_destinations or target in self.units:
            record['outcome']='outside_empty_destination_scope'
            raise ValueError("Serial fixture requires an explicitly allowed, currently empty destination")
        fault=self.faults[serial];record['fault']=asdict(fault)
        if fault.move:
            if self.revision == 2**63-1:
                record['outcome']='revision_exhausted'
                raise ValueError("Fixture revision is exhausted")
            old,old_parameter,revision=node.address,node.parameters[32],self.revision
            previous_units=dict(self.units);prospective=None;persistence_attempted=False
            try:
                node.address=target
                if self.address_memory_policy=='parameter32':node.parameters[32]=bytes([target])
                self.revision+=1;self._rebuild()
                prospective=self._bytes(self._document())
                persistence_attempted=True
                self._persist()
            except BaseException as error:
                # An injected failure can occur after replace committed. Read
                # exact expected bytes instead of falsely claiming rollback.
                probe_error=None
                record['persistence_attempted']=persistence_attempted
                try:committed=(persistence_attempted and self.state_path is not None
                               and self.state_path.read_bytes()==prospective)
                except BaseException as observed:
                    committed=None;probe_error=observed
                    record['persistence_probe_error']=type(observed).__name__+': '+str(observed)
                record['disk_matches_proposed_state']=committed
                if committed:
                    self._expected_file_bytes=prospective
                    record['new_address']=target;record['persistence']='committed_despite_error'
                else:
                    node.address=old;node.parameters[32]=old_parameter;self.revision=revision
                    self.units=previous_units
                    record['persistence']='not_confirmed_memory_restored'
                record['outcome']='persistence_error';record['error']=type(error).__name__+': '+str(error)
                if hasattr(error,'fixture_persistence_cleanup_error'):
                    record['persistence_cleanup_error']=error.fixture_persistence_cleanup_error
                if hasattr(error,'fixture_persistence_prior_error'):
                    record['persistence_prior_error']=error.fixture_persistence_prior_error
                interruption=error if not isinstance(error,Exception) else probe_error
                if interruption is not None and not isinstance(interruption,Exception):
                    interruption.serial_address_fixture_operation=deepcopy(record)
                    raise interruption
                raise ValueError("Fixture persistence failed; inspect operation evidence") from error
            record['new_address']=target;record['persistence']='memory_only' if self.state_path is None else 'committed'
        record['outcome']='moved' if fault.move else 'not_moved_by_fault'
        if not fault.reply:
            record['reply_hex']=None;return b''
        reported=parse_native_serial(fault.reported_serial or serial)
        response=b'\x87\x00'+((reported.first<<12)|reported.second).to_bytes(4,'big')+self.reply_tails[serial]
        if not fault.bare:response=bytes([0x86,target if fault.reported_source is None else fault.reported_source,self.local_unit,0])+response
        record['reply_hex']=response.hex();return response

    def _command(self,line,context):
        code=line[-1:] if line and ord('g')<=line[-1]<=ord('z') else b''
        text=line[:-1] if code else line;explicit,basic=text.startswith(b'\\'),text.startswith(b'@')
        if explicit or basic:text=text[1:]
        def reject(reason,status=b'#'):return (code+status if code else b'!'),reason
        if not text or len(text)%2 or any(c not in b'0123456789abcdefABCDEF' for c in text):return reject('Malformed hexadecimal command')
        payload=bytes.fromhex(text.decode('ascii'))
        if self.command_checksum and not basic:
            if len(payload)<2 or sum(payload)&255:return reject('Invalid C-Bus checksum',b'$')
            payload=payload[:-1]
        addressed=explicit
        if not explicit and not basic and context['header'] is not None:
            payload=context['header']+payload;addressed=True
        ack=code+b'.' if code else b''
        with self._lock:
            if explicit and payload[:4]==b'\x05\xff\x00\x0f':
                try:response=self._co(payload)
                except ValueError as error:return reject(str(error))
                context['header']=payload[:3]
                return ack+(self._reply(response) if response else b''),None
            if basic:
                if payload!=b'\x1a\x20\x01' or code:return reject('Unsupported BASIC command')
                return super()._command(line,context)
            if addressed and payload==b'\x05\xff\x00\xfa\xff\x00':return super()._command(line,context)
            address=self.local_unit
            if addressed:
                if len(payload)<4 or payload[0]!=0x46 or payload[2]!=0:return reject('Unsupported fixture route or application')
                address,payload=payload[1],payload[3:]
            if not payload:return reject('Missing read CAL')
            remaining=payload
            while remaining:
                size=2 if remaining[0]==0x21 else 3 if remaining[0] in (0x1a,0x2a) else 0
                if not size or len(remaining)<size:return reject('Fixture rejects generic writes, unlocks and unsupported CAL')
                remaining=remaining[size:]
            if address==self.local_unit:return super()._command(line,context)
            matches=[self._nodes[serial] for serial in self._node_order if self._nodes[serial].address==address]
            if not matches:
                if explicit:context['header']=bytes([0x46,address,0])
                return ack,None  # No other physical nodes exist in this explicit fixture.
            replies=[];updated_context=dict(context)
            try:
                for node in matches:
                    self.units[address]=node;updated_context=dict(context)
                    response,reason=super()._command(line,updated_context)
                    if reason:return response,reason
                    replies.append(response[len(ack):])
            finally:self._rebuild()
            context.update(updated_context)
            return ack+b''.join(replies),None
