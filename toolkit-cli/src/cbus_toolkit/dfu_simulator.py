"""Independent memory-only peer for the bounded eDLT DFU research harness.

The byte decoder deliberately does not import the host's dfu record parser.
It models observable bytes, errors and interrupted writes. It is not a USB
adapter, hardware emulator or guarantee about a device bootloader's timing.
"""
from __future__ import annotations
import hashlib
import struct


class DFUStall(RuntimeError):
    """A memory peer rejected the control request."""


class DFUSimulator:
    def __init__(self, *, flash_size=262144, application_start=8192,
                 external_size=131072, transfer_size=1024):
        for name,value,minimum,maximum in (
            ('flash_size',flash_size,1024,8388608),
            ('application_start',application_start,0,flash_size-1),
            ('external_size',external_size,65536,8388608),
            ('transfer_size',transfer_size,11,1024)):
            if type(value) is not int or not minimum <= value <= maximum:
                raise ValueError(f'{name} is outside the bounded simulator range')
        if flash_size%1024 or application_start%1024 or external_size%65536:
            raise ValueError('Flash ranges must align to their erase blocks')
        self.internal=bytearray(b'\xff')*flash_size
        self.external=bytearray(b'\xff')*external_size
        self.application_start=application_start
        self.transfer_size=transfer_size
        self.state=2; self.status=0; self.next_block=0
        self.binary={False:False,True:False}
        self._program=None; self._upload=b''; self._busy_next=None
        self.transfers=0; self.programmed_bytes=0; self.completed_programs=0
        self.detached=False

    def _error(self, status):
        self.status=status; self.state=10; self._busy_next=None

    def _busy(self, final=5):
        self.state=4; self._busy_next=final

    def _range(self, external, address, length, *, modifying=False):
        memory=self.external if external else self.internal
        minimum=0 if external else self.application_start
        if length <= 0 or address < 0 or address+length > len(memory):
            self._error(8); return None
        if modifying and address<minimum:
            self._error(8); return None
        return memory

    def _download(self, data):
        if self.state not in (2,5): raise DFUStall('DNLOAD requires idle or download-idle state')
        if self._program is not None:
            external,address,length,written=self._program
            if not data:
                if written != length: self._error(9); return
                self._program=None; self.completed_programs+=1; self._busy(final=2); return
            if written+len(data)>length: self._error(8); return
            memory=self.external if external else self.internal
            offset=address+written
            if any((a&b)!=b for a,b in zip(memory[offset:offset+len(data)],data)):
                self._error(6); return
            memory[offset:offset+len(data)]=data
            self.programmed_bytes+=len(data)
            self._program=(external,address,length,written+len(data))
            self._busy(); return
        if not data: self._busy(final=2); return
        opcode=data[0]; external=opcode>=8; operation=opcode-7 if external else opcode
        if opcode not in range(1,14): self._error(15); return
        if operation==6:
            if len(data)!=11 or data[1] not in (0,1) or any(data[2:]): self._error(15); return
            self.binary[external]=bool(data[1]); self._busy(); return
        if len(data)!=8 or data[1]: self._error(15); return
        field=data[2]|data[3]<<8; size=int.from_bytes(data[4:8],'little')
        if operation in (1,2,3):
            # Only external address zero has unambiguous bounded device evidence.
            if external and field: self._error(15); return
            address=field*1024
            memory=self._range(external,address,size,modifying=operation==1)
            if memory is None: return
            if operation==1:
                self._program=(external,address,size,0)
            elif operation==2:
                if not self.binary[external]: self._error(15); return
                self._upload=bytes(memory[address:address+size])
            else:
                if size%4: self._error(8); return
                if any(value!=255 for value in memory[address:address+size]): self._error(5); return
            self._busy(); return
        if operation==4:
            if data[6:]!=b'\0\0': self._error(15); return
            block=65536 if external else 1024
            if external and field: self._error(15); return
            address=field*block; size=int.from_bytes(data[4:6],'little')*block
            memory=self._range(external,address,size,modifying=True)
            if memory is None: return
            memory[address:address+size]=b'\xff'*size
            self._busy(); return
        if any(data[1:]): self._error(15); return
        if operation==5:
            memory=self.external if external else self.internal
            self._upload=struct.pack('<IHIIII',65536 if external else 1024,
                self.transfer_size,0,0,len(memory),0 if external else self.application_start)
            self._busy(); return
        # RESET is a known TI command, but eDLT reset behavior is not accepted.
        self._error(15)

    def control(self, bm_request_type, request, value, index, *, data=b'', length=0):
        """Process a synthetic Endpoint0 request; return IN bytes or b'' for OUT.

        Block numbers are one shared, monotonic modulo65536 counter, matching
        the observed DLL. CLRSTATUS and ABORT do not silently rewind it.
        """
        if self.detached: raise DFUStall('The isolated peer is detached')
        if any(type(v) is not int for v in (bm_request_type,request,value,index,length)):
            raise ValueError('Control request fields must be integers')
        if not isinstance(data,bytes) or index!=0 or not 0<=value<=65535 or not 0<=length<=self.transfer_size:
            raise DFUStall('Invalid control request fields')
        if (bm_request_type==0x21 and length!=len(data)) or (bm_request_type==0xA1 and data):
            raise DFUStall('Control payload length or direction is inconsistent')
        self.transfers+=1
        if bm_request_type==0xA1 and request==0x42 and value==0x23 and length==4:
            return b'\x4d\x4c\x01\x00'
        if bm_request_type==0xA1 and request==3 and value==0 and length==6:
            reply=bytes((self.status,1 if self._busy_next is not None else 0,0,0,self.state,0))
            if self._busy_next is not None:
                self.state=self._busy_next; self._busy_next=None
            return reply
        if bm_request_type==0x21 and request in (0,4,6) and value==0 and not data and length==0:
            if request==0: self.detached=True
            elif request==4:
                if self.state!=10: raise DFUStall('CLRSTATUS requires an error state')
                self.state=2; self.status=0; self._program=None; self._upload=b''; self._busy_next=None
            else:
                self.state=2; self.status=0; self._program=None; self._upload=b''; self._busy_next=None
            return b''
        if (bm_request_type,request) not in ((0x21,1),(0xA1,2)):
            raise DFUStall('Unsupported control request')
        if value!=self.next_block: raise DFUStall('Unexpected DFU block sequence')
        self.next_block=(self.next_block+1)&65535
        if request==1:
            self._download(data); return b''
        if self.state not in (2,5,9) or len(self._upload)<length:
            raise DFUStall('UPLOAD exceeds the explicitly selected readable bytes')
        reply=self._upload[:length]; self._upload=self._upload[length:]
        self.state=9 if self._upload else 2
        return reply

    def snapshot(self):
        return {'schema':1,'scope':'Memory-only DFU peer; no physical-device acceptance',
            'flash_size':len(self.internal),'application_start':self.application_start,
            'external_size':len(self.external),'transfer_size':self.transfer_size,
            'state':self.state,'status':self.status,'next_block':self.next_block,
            'programmed_bytes':self.programmed_bytes,'completed_programs':self.completed_programs,
            'partial_program':self._program is not None,'detached':self.detached,
            'internal_sha256':hashlib.sha256(self.internal).hexdigest(),
            'external_sha256':hashlib.sha256(self.external).hexdigest(),'transfers':self.transfers}
