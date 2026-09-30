"""Bounded, offline interpretation of the original eDLT download dispatcher.

The pinned dfuprog 0x401B50 dispatcher strips a valid DFU suffix for binary
download. A valid TI prefix selects LMDFUDownload, which transmits the prefix
and payload without the suffix; the prefix replaces the command-line address.
The wrapper at 0x402400 has no external-flash argument: opcode 1 in that prefix
still names internal flash even when dfuprog was given -z.

These helpers expose normalized bytes only in memory and hashes in receipts.
They are not a hardware adapter or a firmware authenticity/bootability check.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import struct

from .dfu import DFUImage, MAX_IMAGE_SIZE, inspect_image, plan_binary


DFUPROG_SHA256 = 'fb3f46f81fd1878cba2cde47f72dceaa9e1b4ac1be0e083c33901a34d130aa0e'
DFU_DLL_SHA256 = 'eb90a4b4abec88e1607a7462f85028e8b0fc064d83a8b765047d89d0909a647a'


def _integer(name, value, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f'{name} must be an integer from {minimum} through {maximum}')
    return value


@dataclass(frozen=True)
class FirmwarePayload:
    """One in-memory dispatch result; ``as_dict`` never includes payload bytes."""

    payload: bytes = field(repr=False)
    input_bytes: int
    input_sha256: str
    requested_address: int
    effective_address: int
    requested_external: bool
    effective_external: bool
    native_download_path: str
    payload_offset: int
    suffix_bytes: int
    supported: bool
    issues: tuple[str, ...]
    container: DFUImage

    @property
    def payload_sha256(self):
        return hashlib.sha256(self.payload).hexdigest()

    def as_dict(self):
        return {
            'format': 'cbus-edlt-download-payload-v1',
            'input_bytes': self.input_bytes, 'input_sha256': self.input_sha256,
            'payload_bytes': len(self.payload), 'payload_sha256': self.payload_sha256,
            'requested_address': self.requested_address, 'effective_address': self.effective_address,
            'requested_external': self.requested_external, 'effective_external': self.effective_external,
            'native_download_path': self.native_download_path,
            'payload_offset': self.payload_offset, 'suffix_bytes': self.suffix_bytes,
            'supported': self.supported, 'issues': list(self.issues),
            'container': self.container.as_dict(),
            'source': {'dfuprog_sha256': DFUPROG_SHA256, 'dfu_dll_sha256': DFU_DLL_SHA256,
                       'dispatcher': '0x401B50', 'prefixed_wrapper': '0x402400',
                       'image_reader': '0x1000E940', 'prefixed_download': '0x10010280'},
            'physical_execution_supported': False, 'authenticity_verified': False,
            'device_verified': False, 'firmware_written': False,
            'scope': 'Offline payload interpretation; ranges require an explicit capacity and application boundary',
        }


def resolve_download_payload(data, *, address, external=False, vendor_id=0x166A, product_id=0x0501):
    """Resolve native raw/suffix/prefix selection without permitting execution.

    Native malformed-container fallback is reported but intentionally refused
    for recognizable damaged containers. This is a conservative boundary, not
    an assertion that the original would refuse that raw fallback. Valid but
    unsupported suffix versions/lengths and reserved prefixes are also refused.
    Exact VID/PID matching follows the native reader; no wildcard or -d bypass
    is admitted. Device BCD is deliberately not used as a compatibility gate.
    """
    if not isinstance(data, bytes) or len(data) > MAX_IMAGE_SIZE:
        raise ValueError(f'Expected bytes with length at most {MAX_IMAGE_SIZE}')
    _integer('address', address, 0, 0xFFFFFFFF)
    _integer('vendor_id', vendor_id, 0, 65535)
    _integer('product_id', product_id, 0, 65535)
    if not isinstance(external, bool):
        raise ValueError('external must be boolean')
    container = inspect_image(data)
    payload, effective, effective_external = data, address, external
    path, offset, suffix = 'raw binary at -a', 0, 0
    issues = []
    if container.valid:
        suffix = container.suffix_length
        end = len(data) - suffix
        if container.has_ti_prefix:
            path, offset, effective = 'dfu-prefixed: the prefix address replaces -a', 8, container.address
            effective_external = False
            if external:
                issues.append('A TI prefix selects internal flash even when the requested role is external')
            if data[1] != 0:
                issues.append('Nonzero TI prefix reserved byte is unsupported')
        else:
            path = 'dfu-suffix-stripped binary at -a'
        payload = data[offset:end]
        if container.vendor_id != vendor_id or container.product_id != product_id:
            issues.append('DFU vendor or product ID mismatch; the native dispatcher stops without -d')
        if suffix != 16:
            issues.append('Only sixteen-byte DFU suffixes are supported')
        if container.dfu_version != 0x0100:
            issues.append('Only DFU1.0 image suffixes are supported')
    elif container.has_ti_prefix or len(data) >= 16 and data[-8:-5] == b'UFD':
        issues.append('Recognizable invalid DFU container: native raw-binary fallback is refused')
    if not payload:
        issues.append('Empty firmware payload is unsupported')
    if effective % 1024:
        issues.append('Program address must be a multiple of 1024')
    if effective // 1024 > 65535:
        issues.append('Program address exceeds the native sixteen-bit address field')
    if effective_external and effective != 0:
        issues.append('Nonzero external addresses remain unsupported by the simulator and physical client')
    return FirmwarePayload(payload, len(data), hashlib.sha256(data).hexdigest(), address, effective,
                           external, effective_external, path, offset, suffix, not issues,
                           tuple(issues), container)


def plan_download_payload(payload, *, flash_size, application_start, transfer_size=1024):
    """Build a bounded offline plan for resolved bytes; no transport is opened."""
    if not isinstance(payload, FirmwarePayload):
        raise ValueError('A resolved FirmwarePayload is required')
    if not payload.supported:
        raise ValueError('Unsupported firmware payload: ' + '; '.join(payload.issues))
    plan = plan_binary(len(payload.payload), address=payload.effective_address, flash_size=flash_size,
                       application_start=application_start, external=payload.effective_external,
                       transfer_size=transfer_size)
    return {'format': 'cbus-edlt-download-payload-plan-v1', 'payload': payload.as_dict(),
            'transfer': plan, 'physical_execution_supported': False, 'firmware_written': False,
            'scope': 'Normalized binary transfer plan; TI-prefixed native packet grouping is not reproduced'}


def describe_external_check_addresses(*, address, length):
    """Describe the two conflicting native CHECK encodings, without choosing one.

    Original LMDFUBlankCheck uses address/65536; LMDFUErase verification uses
    address/1024. Neither this description nor native host success establishes
    the device's interpretation, so nonzero execution remains unsupported.
    """
    _integer('address', address, 0, 65535 * 1024)
    _integer('length', length, 1, MAX_IMAGE_SIZE)
    if address % 1024:
        raise ValueError('External address must be a multiple of 1024')
    return {'format': 'cbus-edlt-external-check-address-v1', 'address': address, 'length': length,
            'blank_check_header_hex': struct.pack('<BBHI', 10, 0, address // 65536, length).hex(),
            'erase_verify_check_header_hex': struct.pack('<BBHI', 10, 0, address // 1024, length).hex(),
            'ambiguous': address != 0, 'physical_execution_supported': False, 'device_verified': False,
            'source': {'dfu_dll_sha256': DFU_DLL_SHA256, 'blank_check': '0x1000F8C0', 'erase': '0x1000F9C0'},
            'scope': 'Original host-side encodings only; no device-side address interpretation is established'}
