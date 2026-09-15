"""Bounded eDLT DFU client for an injected Endpoint0 service.

No USB adapter is provided. A service must honor its per-call timeout and
report exact transfer lengths. The included adapter targets memory peers only.
"""
from __future__ import annotations
from dataclasses import asdict, dataclass, field
import hashlib
import math
import struct
import time
from typing import Protocol

from .dfu import MAX_IMAGE_SIZE, parse_status, plan_binary


@dataclass(frozen=True)
class DFUInterface:
    vendor_id: int
    product_id: int
    device_version: int
    interface: int
    attributes: int
    detach_timeout_ms: int
    transfer_size: int
    dfu_version: int
    manufacturer_index: int
    product_index: int
    serial_index: int
    device_descriptor: bytes = field(repr=False)
    configuration_descriptor: bytes = field(repr=False)

    def as_dict(self):
        return {key:value for key,value in asdict(self).items() if not key.endswith('_descriptor')}


def parse_descriptors(device: bytes, configuration: bytes) -> DFUInterface:
    """Validate the bounded eDLT DFU-mode descriptor profile before any I/O.

    Exact VID166A/PID0501, interface0/alternate0/classFE/subclass1/protocol2,
    one associated functional descriptor, DFU1.0, download+upload capability.
    Other interfaces may exist, but a second DFU interface is ambiguous.
    """
    if not isinstance(device,bytes) or len(device)!=18 or device[:2]!=b'\x12\x01':
        raise ValueError('Device descriptor must contain exactly eighteen bytes with the correct header')
    if not isinstance(configuration,bytes) or not 9<=len(configuration)<=65535:
        raise ValueError('Configuration descriptor length must be between nine and65535 bytes')
    if configuration[:2]!=b'\x09\x02' or int.from_bytes(configuration[2:4],'little')!=len(configuration):
        raise ValueError('Configuration header or declared total length is inconsistent')
    if device[7] not in (8,16,32,64) or device[17]==0:
        raise ValueError('Invalid device Endpoint0 packet size or configuration count')
    if configuration[5]==0 or configuration[7]&0x9f!=0x80:
        raise ValueError('Invalid configuration value or reserved attribute bits')
    vendor,product,version=struct.unpack_from('<HHH',device,8)
    if (vendor,product)!=(0x166a,0x0501):
        raise ValueError('Only the original eDLT166A/0501 interface is supported')
    interfaces=[]; current=None; offset=9
    while offset<len(configuration):
        if len(configuration)-offset<2: raise ValueError('Truncated descriptor header')
        size,kind=configuration[offset:offset+2]
        if size<2 or offset+size>len(configuration):
            raise ValueError('Descriptor length is zero, too short or beyond the configuration')
        value=configuration[offset:offset+size]
        if kind==4:
            if size!=9: raise ValueError('Interface descriptor must contain nine bytes')
            current={'bytes':value,'functional':[]};interfaces.append(current)
        elif kind==0x21:
            if current is None: raise ValueError('Functional descriptor has no owning interface')
            current['functional'].append(value)
        offset+=size
    if len({(entry['bytes'][2],entry['bytes'][3]) for entry in interfaces})!=len(interfaces):
        raise ValueError('Duplicate interface/alternate descriptor')
    if len({entry['bytes'][2] for entry in interfaces})!=configuration[4]:
        raise ValueError('Interface count differs from the configuration header')
    candidates=[entry for entry in interfaces if entry['bytes'][5:7]==b'\xfe\x01']
    if len(candidates)!=1: raise ValueError('Exactly one unambiguous DFU interface is required')
    selected=candidates[0];interface=selected['bytes']
    if interface[2:4]!=b'\0\0' or interface[7]!=2:
        raise ValueError('Only eDLT interface0/alternate0 already in DFU mode is supported')
    if len(selected['functional'])!=1 or len(selected['functional'][0])!=9:
        raise ValueError('One complete nine-byte DFU functional descriptor is required')
    functional=selected['functional'][0]
    attributes=functional[2]
    detach,transfer,dfu_version=struct.unpack_from('<HHH',functional,3)
    if attributes&3!=3: raise ValueError('DFU download and upload capabilities are required for readback verification')
    if attributes&0xf0: raise ValueError('Unknown DFU functional attribute bits')
    if not 22<=transfer<=1024: raise ValueError('Supported DFU transfer size is twenty-two through1024 bytes')
    if dfu_version!=0x100: raise ValueError('Only the DFU1.0 descriptor profile is accepted')
    return DFUInterface(vendor,product,version,interface[2],attributes,detach,transfer,dfu_version,
                        device[14],device[15],device[16],device,configuration)


@dataclass(frozen=True)
class ControlReply:
    success: bool
    transferred: int
    data: bytes = b''


class Endpoint0(Protocol):
    def control(self, bm_request_type: int, request: int, value: int, index: int, *,
                data: bytes, length: int, timeout: float) -> ControlReply:
        """Return within timeout, preserving actual success/length; never replay."""
        ...
    def close(self) -> None: ...


class MemoryEndpoint0:
    """Adapter for the independent DFUSimulator. It performs no USB access."""
    def __init__(self, peer, descriptor: DFUInterface):
        if not isinstance(descriptor,DFUInterface) or parse_descriptors(descriptor.device_descriptor,descriptor.configuration_descriptor)!=descriptor:
            raise ValueError('Memory Endpoint0 requires an explicit validated descriptor fixture')
        self.peer=peer;self.descriptor=descriptor;self.closed=False
    def control(self,bm_request_type,request,value,index,*,data=b'',length=0,timeout):
        if self.closed: raise RuntimeError('Memory Endpoint0 service is closed')
        if not math.isfinite(timeout) or timeout<=0: raise TimeoutError('Endpoint0 deadline expired')
        if bm_request_type==0x80 and request==6 and index==0 and not data:
            fixture={0x100:self.descriptor.device_descriptor,0x200:self.descriptor.configuration_descriptor}.get(value)
            if fixture is None or type(length) is not int or length<0:
                raise ValueError('Unscripted descriptor request')
            reply=fixture[:length]
        else:
            reply=self.peer.control(bm_request_type,request,value,index,data=data,length=length)
        return ControlReply(True,length if bm_request_type==0x21 else len(reply),reply)
    def close(self): self.closed=True


@dataclass(frozen=True)
class DFUOutcome:
    operation: str
    complete: bool
    external: bool
    address: int | None
    length: int | None
    payload_transferred: int
    readback_bytes: int
    first_mismatch: int | None
    expected_sha256: str | None
    readback_sha256: str | None
    stage: str
    error: str | None
    outcome_known: bool
    elapsed_seconds: float
    trace: tuple[dict, ...]
    info: dict | None
    close_error: str | None = None

    def as_dict(self):
        readback_verified=(self.operation in ('program','erase') and self.length is not None
            and self.readback_bytes==self.length and self.first_mismatch is None
            and self.expected_sha256 is not None and self.expected_sha256==self.readback_sha256)
        return {**asdict(self),'trace':list(self.trace),'peer_verified':readback_verified,
                'physical_device_verified':False,'scope':'Injected Endpoint0 operation; no physical USB adapter supplied'}


class DFUOperationError(RuntimeError):
    def __init__(self,outcome):
        super().__init__(outcome.error or 'DFU operation failed')
        self.outcome=outcome
        self.details=outcome.as_dict()


class _OperationFailure(Exception):
    def __init__(self,message,*,known=False):super().__init__(message);self.known=known


class DFUClient:
    """A one-operation session. Create a fresh client and peer state for reuse.

    Program never erases automatically. All modifying operations require full
    readback. Any failure invalidates/closes the injected service; no mutation
    or recovery command is retried. A transport must honor its timeout contract.
    """
    def __init__(self, endpoint: Endpoint0, descriptor: DFUInterface, *, flash_size: int,
                 application_start: int, external: bool=False, timeout: float=30,
                 poll_limit: int=256, clock=time.monotonic, sleep=time.sleep):
        if not isinstance(descriptor,DFUInterface) or parse_descriptors(descriptor.device_descriptor,descriptor.configuration_descriptor)!=descriptor:
            raise ValueError('Use a descriptor returned by parse_descriptors')
        if type(external) is not bool: raise ValueError('external must be boolean')
        block=65536 if external else 1024
        if type(flash_size) is not int or not block<=flash_size<=MAX_IMAGE_SIZE or flash_size%block:
            raise ValueError('Explicit flash size must align to its erase block and fit the bounded range')
        if type(application_start) is not int or not 0<=application_start<flash_size or application_start%block:
            raise ValueError('Explicit application start must be a valid erase-block boundary')
        if external and application_start: raise ValueError('External flash currently supports address zero only')
        if type(timeout) not in (int,float) or not math.isfinite(timeout) or not 0<timeout<=3600:
            raise ValueError('timeout must be finite, positive and at most3600 seconds')
        if type(poll_limit) is not int or not 1<=poll_limit<=4096:
            raise ValueError('poll_limit must be between one and4096')
        self.endpoint=endpoint;self.descriptor=descriptor
        self.flash_size=flash_size;self.application_start=application_start
        self.external=external;self.timeout=float(timeout);self.poll_limit=poll_limit
        self.clock=clock;self.sleep=sleep;self.used=False;self.closed=False
        self.sequence=0;self.trace=[];self.info=None;self.last_outcome=None

    def _remaining(self):
        value=self.deadline-self.clock()
        if not math.isfinite(value) or value<=0: raise _OperationFailure('DFU operation deadline expired')
        return value

    def _transfer(self,bm,request,value=0,*,data=b'',length=0):
        remaining=self._remaining()
        row={'bmRequestType':bm,'bRequest':request,'wValue':value,'wIndex':self.descriptor.interface,
             'wLength':length,'stage':self.stage}
        if data:row['out_sha256']=hashlib.sha256(data).hexdigest()
        self.trace.append(row)
        try:
            reply=self.endpoint.control(bm,request,value,self.descriptor.interface,
                data=data,length=length,timeout=remaining)
        except Exception as error:
            row['transport_error']=str(error)
            raise _OperationFailure(f'Endpoint0 transfer failed: {error}') from error
        if not isinstance(reply,ControlReply) or type(reply.success) is not bool or type(reply.transferred) is not int or not isinstance(reply.data,bytes):
            raise _OperationFailure('Endpoint0 returned an invalid transfer result')
        row.update(success=reply.success,transferred=reply.transferred)
        if reply.data:row['in_sha256']=hashlib.sha256(reply.data).hexdigest()
        if not reply.success or reply.transferred!=length or len(reply.data)!=(length if bm&0x80 else 0):
            raise _OperationFailure('Endpoint0 failed or returned an incomplete/inconsistent transfer')
        self._remaining()
        return reply.data

    def _status(self):
        value=self._transfer(0xa1,3,length=6)
        try:status=parse_status(value)
        except ValueError as error:raise _OperationFailure(str(error)) from error
        self.trace[-1]['status']=status.as_dict()
        if status.status:raise _OperationFailure(f'DFU peer reported {status.as_dict()["status_name"]}',known=True)
        return status

    def _poll(self,allowed=(2,5)):
        for _ in range(self.poll_limit):
            status=self._status()
            if status.state not in (3,4):
                if status.state not in allowed:
                    raise _OperationFailure(f'Unexpected DFU state {status.as_dict()["state_name"]}')
                return status
            delay=max(status.poll_timeout_ms/1000,0.001)
            self.sleep(min(delay,self._remaining()))
        raise _OperationFailure('DFU polling limit exhausted while the peer remained busy')

    def _block(self,bm,request,*,data=b'',length=0):
        if self.sequence>65535: raise _OperationFailure('DFU block sequence would wrap')
        value=self.sequence;self.sequence+=1
        return self._transfer(bm,request,value,data=data,length=length)

    def _download(self,data,*,allowed=(2,5)):
        self._block(0x21,1,data=data,length=len(data))
        self._poll(allowed)

    def _idle(self,*,owned=False):
        state=self._status().state
        if state==2:return
        if owned and state in (5,9):
            self._transfer(0x21,6)
            if self._status().state==2:return
        raise _OperationFailure('The peer must be in DFU idle; automatic recovery of an existing operation is not allowed')

    def _inspect(self):
        self.stage='inspect-device'
        device=self._transfer(0x80,6,0x100,length=18)
        self.stage='inspect-configuration'
        header=self._transfer(0x80,6,0x200,length=9)
        total=int.from_bytes(header[2:4],'little')
        if header[:2]!=b'\x09\x02' or not 9<=total<=65535:
            raise _OperationFailure('Invalid configuration header or declared descriptor length',known=True)
        configuration=self._transfer(0x80,6,0x200,length=total)
        try:actual=parse_descriptors(device,configuration)
        except ValueError as error:raise _OperationFailure(str(error),known=True) from error
        if actual!=self.descriptor:
            raise _OperationFailure('Active Endpoint0 descriptors differ from the explicit expected descriptor',known=True)
        self.stage='inspect-status';self._idle()
        self.stage='inspect-extensions'
        if self._transfer(0xa1,0x42,0x23,length=4)!=b'\x4d\x4c\x01\x00':
            raise _OperationFailure('The peer did not confirm the expected eDLT DFU extensions',known=True)
        self.stage='inspect-memory'
        self._download(bytes([12 if self.external else 5])+b'\0'*7)
        data=self._block(0xa1,2,length=22)
        block,transfer,part0,part1,size,start=struct.unpack('<IHIIII',data)
        self.info={'block_size':block,'transfer_size':transfer,'part0':part0,'part1':part1,
                   'flash_size':size,'application_start':start,'external':self.external}
        if (block,transfer,size,start)!=(65536 if self.external else 1024,self.descriptor.transfer_size,self.flash_size,self.application_start):
            raise _OperationFailure('Reported memory geometry differs from the explicit bounds/descriptor',known=True)
        self._idle(owned=True)

    def _readback(self,address,length,expected):
        self.stage='readback-enable'
        opcode=13 if self.external else 6
        self._download(bytes([opcode,1])+b'\0'*9)
        self.stage='readback-select'
        self._download(struct.pack('<BBHI',9 if self.external else 2,0,address//1024,length))
        digest=hashlib.sha256();expected_digest=hashlib.sha256()
        for offset in range(0,length,self.descriptor.transfer_size):
            count=min(self.descriptor.transfer_size,length-offset)
            self.stage='readback-data'
            data=self._block(0xa1,2,length=count)
            wanted=expected[offset:offset+count] if expected is not None else b'\xff'*count
            digest.update(data);expected_digest.update(wanted);self.readback_bytes+=count
            if self.first_mismatch is None and data!=wanted:
                self.first_mismatch=address+offset+next(i for i,(a,b) in enumerate(zip(data,wanted)) if a!=b)
        self.readback_sha=digest.hexdigest();self.expected_sha=expected_digest.hexdigest()
        self.stage='readback-disable'
        self._idle(owned=True)
        self._download(bytes([opcode])+b'\0'*10)
        self._idle(owned=True)
        self.stage='readback-compare'
        if self.first_mismatch is not None:
            raise _OperationFailure(f'Independent readback mismatch at address {self.first_mismatch}',known=True)

    def _run(self,operation,address,length,action):
        if self.used or self.closed:raise RuntimeError('DFUClient sessions allow exactly one operation; create a fresh session')
        self.used=True;self.stage='start';self.start=None
        self.payload_transferred=0;self.readback_bytes=0;self.first_mismatch=None
        self.expected_sha=None;self.readback_sha=None
        error=None;known=True;close_error=None;complete=False;interruption=None
        try:
            self.start=self.clock();self.deadline=self.start+self.timeout
            self._inspect()
            if action is not None:action()
            complete=True;self.stage='complete'
        except _OperationFailure as failure:error=str(failure);known=failure.known
        except Exception as failure:error=f'DFU operation failed: {failure}';known=False
        except BaseException as failure:
            interruption=failure;error=f'DFU operation interrupted: {type(failure).__name__}';known=False
        finally:
            # Invalidate before closure, even if the control service or close
            # itself is interrupted. Never replay or send recovery commands.
            self.closed=True
            try:self.endpoint.close()
            except BaseException as failure:
                close_error=str(failure) or type(failure).__name__
                if error is None:error=f'Endpoint0 close failed: {close_error}';self.stage='close'
                complete=False
                if not isinstance(failure,Exception) and interruption is None:interruption=failure
        elapsed=0.
        try:
            if self.start is not None:elapsed=max(0,self.clock()-self.start)
        except BaseException as failure:
            if error is None:error=f'DFU result timing failed: {type(failure).__name__}'
            complete=False
            if not isinstance(failure,Exception) and interruption is None:interruption=failure
        outcome=DFUOutcome(operation,complete,self.external,address,length,self.payload_transferred,
            self.readback_bytes,self.first_mismatch,self.expected_sha,self.readback_sha,self.stage,error,known,
            elapsed,tuple(dict(row) for row in self.trace),self.info,close_error)
        self.last_outcome=outcome
        if interruption is not None:raise interruption.with_traceback(interruption.__traceback__)
        if not complete:raise DFUOperationError(outcome)
        return outcome

    def inspect(self):
        return self._run('inspect',None,None,None)

    def _program_plan(self,data,address):
        if not isinstance(data,bytes):raise ValueError('Program data must be bytes')
        plan=plan_binary(len(data),address=address,flash_size=self.flash_size,application_start=self.application_start,
                    external=self.external,transfer_size=self.descriptor.transfer_size)
        # INFO uses two blocks before the program/readback sequence.
        count=(len(data)+self.descriptor.transfer_size-1)//self.descriptor.transfer_size
        if 2*count+7>=65536:raise ValueError('Program plus inspection/readback would wrap the block sequence')
        return plan

    def _erase_plan(self,address,length):
        plan=plan_binary(length,address=address,flash_size=self.flash_size,application_start=self.application_start,
                    external=self.external,transfer_size=self.descriptor.transfer_size)
        block=65536 if self.external else 1024
        if address%block or length%block or length//block>65535:
            raise ValueError('Erase range must align to the explicit block size and fit a sixteen-bit count')
        return plan

    @staticmethod
    def preflight(descriptor,*,operation,flash_size,application_start,external=False,
                  timeout=30,poll_limit=256,data=None,address=None,length=None):
        """Validate an entire operation before any transport is acquired.

        Constructor validation is pure; this temporary validation instance has
        no Endpoint0 and never calls _run. Execution reuses the same planners.
        """
        if operation not in ('inspect','program','erase'):
            raise ValueError('DFU operation must be inspect, program or erase')
        checked=DFUClient(None,descriptor,flash_size=flash_size,application_start=application_start,
                          external=external,timeout=timeout,poll_limit=poll_limit)
        if operation=='inspect':
            if data is not None or address is not None or length is not None:
                raise ValueError('DFU inspect does not accept data, address or length')
        elif operation=='program':
            if length is not None:raise ValueError('Program length is derived from its byte payload')
            checked._program_plan(data,address);length=len(data)
        else:
            if data is not None:raise ValueError('Erase does not accept a program payload')
            checked._erase_plan(address,length)
        return {'operation':operation,'flash_size':checked.flash_size,'application_start':checked.application_start,
                'external':checked.external,'timeout':checked.timeout,'poll_limit':checked.poll_limit,
                'address':address,'length':length,'transfer_size':descriptor.transfer_size,
                'data_chunks':(length+descriptor.transfer_size-1)//descriptor.transfer_size if length is not None else 0,
                'payload_sha256':hashlib.sha256(data).hexdigest() if data is not None else None,
                'transport_acquired':False,'device_verified':False}

    def program(self,data: bytes,*,address:int):
        self._program_plan(data,address)
        def action():
            self.stage='program-select'
            self._download(struct.pack('<BBHI',8 if self.external else 1,0,address//1024,len(data)))
            for offset in range(0,len(data),self.descriptor.transfer_size):
                self.stage='program-data';chunk=data[offset:offset+self.descriptor.transfer_size]
                self._block(0x21,1,data=chunk,length=len(chunk))
                self.payload_transferred+=len(chunk);self._poll()
            self.stage='program-terminate';self._download(b'',allowed=(2,))
            self._readback(address,len(data),data)
        return self._run('program',address,len(data),action)

    def erase(self,*,address:int,length:int):
        self._erase_plan(address,length)
        block=65536 if self.external else 1024
        def action():
            self.stage='erase'
            # Encode the requested block count exactly, avoiding the vendor's
            # length/(block_size-1) arithmetic defect for large internal ranges.
            self._download(struct.pack('<BBHHH',11 if self.external else 4,0,address//block,length//block,0))
            self._idle(owned=True)
            self._readback(address,length,None)
        return self._run('erase',address,length,action)
