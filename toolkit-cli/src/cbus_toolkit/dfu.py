"""Offline eDLT USB DFU records. This module has no USB or flash-write adapter."""
from __future__ import annotations
from dataclasses import asdict, dataclass
import struct
import zlib

MAX_IMAGE_SIZE = 64 * 1024 * 1024
STATE_NAMES = ('appIDLE', 'appDETACH', 'dfuIDLE', 'dfuDNLOAD_SYNC', 'dfuDNBUSY',
               'dfuDNLOAD_IDLE', 'dfuMANIFEST_SYNC', 'dfuMANIFEST',
               'dfuMANIFEST_WAIT_RESET', 'dfuUPLOAD_IDLE', 'dfuERROR')
STATUS_NAMES = ('OK', 'errTARGET', 'errFILE', 'errWRITE', 'errERASE', 'errCHECK_ERASED',
                'errPROG', 'errVERIFY', 'errADDRESS', 'errNOTDONE', 'errFIRMWARE',
                'errVENDOR', 'errUSBR', 'errPOR', 'errUNKNOWN', 'errSTALLEDPKT')
_NATIVE_ERRORS = (0, -5, -5, -12, -12, -12, -12, -12, -7, -12, -4, -4, -4, -4, -4, -11)


def _integer(name, value, lower, upper):
    if isinstance(value, bool) or not isinstance(value, int) or not lower <= value <= upper:
        raise ValueError(f'{name} must be an integer from {lower} through {upper}')
    return value


def _bytes(data, maximum):
    if not isinstance(data, bytes) or len(data) > maximum:
        raise ValueError(f'Expected bytes with length at most {maximum}')
    return data


@dataclass(frozen=True)
class DFUStatus:
    status: int
    poll_timeout_ms: int
    state: int
    string_index: int

    @property
    def native_error(self): return _NATIVE_ERRORS[self.status]

    def as_dict(self):
        return {**asdict(self), 'status_name': STATUS_NAMES[self.status],
                'state_name': STATE_NAMES[self.state], 'native_error': self.native_error,
                'device_verified': False}


def parse_status(data: bytes) -> DFUStatus:
    """Parse the complete six-byte USB DFU GETSTATUS reply, strictly."""
    _bytes(data, 6)
    if len(data) != 6: raise ValueError('DFU status must contain exactly six bytes')
    if data[0] > 15: raise ValueError('Unknown DFU status code')
    if data[4] > 10: raise ValueError('Unknown DFU state code')
    return DFUStatus(data[0], int.from_bytes(data[1:4], 'little'), data[4], data[5])


@dataclass(frozen=True)
class DFUCommand:
    opcode: int
    operation: str
    external: bool
    address: int | None = None
    length: int | None = None
    binary: bool | None = None
    supported: bool = True
    limitation: str | None = None

    def as_dict(self):
        return {**asdict(self), 'device_verified': False,
                'scope': 'Idle-state vendor header decoding; no device execution'}


def parse_command(data: bytes) -> DFUCommand:
    """Decode an idle-state vendor command, not a firmware data packet.

    Nonzero external CHECK is decoded as ambiguous, because BlankCheck and
    Erase(verify=True) encode its address in different units in the same DLL.
    """
    _bytes(data, 11)
    if not data: raise ValueError('Empty DNLOAD terminates a stream; it is not a command')
    opcode = data[0]
    if opcode not in range(1, 14): raise ValueError('Unknown eDLT DFU command')
    external = opcode >= 8
    operation = opcode - 7 if external else opcode
    if operation == 6:
        if len(data) != 11 or any(data[5:]) or int.from_bytes(data[1:5], 'little') not in (0, 1):
            raise ValueError('Native binary-mode command requires eleven bytes and a boolean value')
        return DFUCommand(opcode, 'binary', external, binary=bool(data[1]))
    if len(data) != 8 or data[1] != 0:
        raise ValueError('Native DFU command requires an eight-byte header with zero reserved byte')
    field = int.from_bytes(data[2:4], 'little')
    length = int.from_bytes(data[4:8], 'little')
    if operation in (1, 2, 3):
        name = ('program', 'read', 'check')[operation-1]
        if external and operation == 3 and field:
            return DFUCommand(opcode, name, True, length=length, supported=False,
                limitation='Nonzero external CHECK address uses conflicting 1024/65536-byte units in original DLL wrappers')
        return DFUCommand(opcode, name, external, address=field*1024, length=length)
    if operation == 4:
        if data[6:] != b'\0\0': raise ValueError('Erase command reserved bytes must be zero')
        block = 65536 if external else 1024
        return DFUCommand(opcode, 'erase', external, address=field*block,
                          length=int.from_bytes(data[4:6], 'little')*block)
    if any(data[1:]): raise ValueError('Info/reset command reserved bytes must be zero')
    return DFUCommand(opcode, 'info' if operation == 5 else 'reset', external)


@dataclass(frozen=True)
class DFUImage:
    size: int
    valid: bool
    supported: bool
    issues: tuple[str, ...]
    vendor_id: int | None = None
    product_id: int | None = None
    device_version: int | None = None
    dfu_version: int | None = None
    suffix_length: int | None = None
    crc_valid: bool = False
    has_ti_prefix: bool = False
    address: int | None = None
    payload_length: int | None = None

    def as_dict(self):
        return {**asdict(self), 'issues': list(self.issues), 'device_verified': False,
                'scope': 'Offline DFU container inspection; firmware payload compatibility is unverified'}


def inspect_image(data: bytes, *, vendor_id: int | None = None,
                  product_id: int | None = None) -> DFUImage:
    """Inspect a DFU suffix and native TI prefix without reading hardware.

    ``valid`` covers the suffix, CRC and optional expected VID/PID. ``supported``
    additionally requires the bounded 16-byte/DFU1.0/TI-prefix format. Neither
    value establishes that the opaque payload is suitable for a device.
    """
    _bytes(data, MAX_IMAGE_SIZE)
    for name, value in (('vendor_id', vendor_id), ('product_id', product_id)):
        if value is not None: _integer(name, value, 0, 65535)
    if len(data) < 16: return DFUImage(len(data), False, False, ('Missing sixteen-byte DFU suffix',))
    device, product, vendor, version, signature, suffix_length, crc = struct.unpack('<HHHH3sBI', data[-16:])
    issues = []
    if signature != b'UFD': issues.append('Invalid DFU suffix signature')
    if not 16 <= suffix_length <= len(data): issues.append('Invalid DFU suffix length')
    crc_valid = zlib.crc32(data) == 0xffffffff
    if not crc_valid: issues.append('DFU checksum mismatch')
    if vendor_id is not None and vendor != vendor_id: issues.append('Vendor ID mismatch')
    if product_id is not None and product != product_id: issues.append('Product ID mismatch')
    valid = not issues
    # Original IsValidImage checks byte0 and length, independently of suffix validity.
    prefix = len(data) >= 24 and data[0] == 1 and int.from_bytes(data[4:8], 'little') == len(data)-suffix_length-8
    address = int.from_bytes(data[2:4], 'little')*1024 if prefix else None
    length = int.from_bytes(data[4:8], 'little') if prefix else None
    if not prefix: issues.append('Missing native TI program prefix')
    if prefix and data[1] != 0: issues.append('Nonzero TI prefix reserved byte')
    if suffix_length != 16: issues.append('Only sixteen-byte DFU suffixes are supported')
    if version != 0x0100: issues.append('Only DFU1.0 image suffixes are supported')
    if prefix and length == 0: issues.append('Empty firmware payload is unsupported')
    return DFUImage(len(data), valid, not issues, tuple(issues), vendor, product, device,
                    version, suffix_length, crc_valid, prefix, address, length)


def plan_binary(length: int, *, address: int, flash_size: int, application_start: int,
                external: bool = False, transfer_size: int = 1024) -> dict:
    """Plan native program/chunk/read headers for a synthetic or supplied binary.

    This is a bounded offline record plan: it neither erases nor transfers data.
    External flash is restricted to address zero until its address semantics
    have independent device-side evidence.
    """
    if not isinstance(external, bool): raise ValueError('external must be boolean')
    _integer('length', length, 1, MAX_IMAGE_SIZE)
    _integer('flash_size', flash_size, 1024, MAX_IMAGE_SIZE)
    _integer('application_start', application_start, 0, flash_size-1)
    _integer('address', address, application_start, flash_size-1)
    _integer('transfer_size', transfer_size, 11, 1024)
    if external and (address != 0 or application_start != 0):
        raise ValueError('External flash plans currently support only address zero')
    if address % 1024: raise ValueError('Program address must be a multiple of 1024')
    if address+length > flash_size: raise ValueError('Program range exceeds the explicit flash capacity')
    opcode = 8 if external else 1
    header = struct.pack('<BBHI', opcode, 0, address//1024, length)
    read = struct.pack('<BBHI', opcode+1, 0, address//1024, length)
    count, remainder = divmod(length, transfer_size)
    if 2 * (count + bool(remainder)) + 5 >= 65536: raise ValueError('Transfer would wrap the native sixteen-bit block sequence')
    chunks = [transfer_size]*count + ([remainder] if remainder else [])
    return {'external':external,'address':address,'length':length,'flash_size':flash_size,
        'application_start':application_start,'transfer_size':transfer_size,
        'program_header_hex':header.hex(),'data_chunk_lengths':chunks,
        'terminal_dnload_length':0,'read_header_hex':read.hex(),
        'binary_enable_hex':bytes([opcode+5,1,0,0,0,0,0,0,0,0,0]).hex(),
        'binary_disable_hex':(bytes([opcode+5])+b'\0'*10).hex(),
        'device_verified':False,'scope':'Offline plan; no image payload validation, erase, USB access or firmware installation'}
