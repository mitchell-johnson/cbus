"""eDLT USB inspection using standard device-recipient IN requests only.

No interface is claimed. This module is deliberately not a DFU Endpoint0
adapter: it cannot detach, reset, change configuration, or issue class requests.
Timeouts apply to each control transfer, not enumeration, opening or closing.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math
import struct

from .dfu_transport import parse_descriptors

VENDOR_ID = 0x166A
PRODUCT_ID = 0x0501
MAX_CONFIGURATIONS = 8


@dataclass(frozen=True)
class USBDeviceList:
    complete: bool
    devices: tuple[dict, ...]
    error: str | None = None
    close_error: str | None = None

    def as_dict(self):
        return {**asdict(self), 'devices': list(self.devices),
                'scope': 'Cached eDLT USB enumeration metadata; no strings or control requests',
                'exclusive_ownership': False}


@dataclass(frozen=True)
class USBInspection:
    complete: bool
    selector: dict
    device: dict | None = None
    device_descriptor: str | None = None
    active_configuration: int | None = None
    configurations: tuple[dict, ...] = ()
    language_ids: tuple[int, ...] = ()
    selected_language_id: int | None = None
    strings: dict = field(default_factory=dict)
    expected_serial_matches: bool | None = None
    dfu_interface: dict | None = None
    unsupported_reason: str | None = None
    trace: tuple[dict, ...] = ()
    stage: str = 'enumeration'
    error: str | None = None
    close_error: str | None = None
    resources_closed: bool = True

    def as_dict(self):
        return {**asdict(self), 'configurations': list(self.configurations),
                'language_ids': list(self.language_ids), 'trace': list(self.trace),
                'dfu_profile_supported': self.dfu_interface is not None,
                'usable_usb_serial': bool(self.strings.get('serial')) and '\0' not in self.strings['serial'],
                'exclusive_ownership': False, 'active_alternate_setting_verified': False,
                'timeout_scope': 'Each control transfer only; enumeration, open and close are not deadline bounded',
                'scope': 'Standard device-recipient USB IN inspection; no DFU status or flash operations'}


def _modules(backend):
    try:
        import usb
        import usb.core
        import usb.backend.libusb1
    except ImportError as error:
        raise RuntimeError('USB inspection requires the optional usb extra (pyusb==1.3.1)') from error
    if usb.__version__ != '1.3.1':
        raise RuntimeError('USB inspection is validated with pyusb==1.3.1; install the pinned usb extra')
    if backend is None:
        backend = usb.backend.libusb1.get_backend()
        if backend is None:
            raise RuntimeError('The libusb1 native backend is unavailable; USB inspection cannot continue')
    return usb.core, backend


def _bound(value, name, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f'{name} must be an integer between {minimum} and {maximum}')
    return value


def _metadata(device):
    # These Device attributes come from the backend's cached descriptor. Never
    # use serial_number/manufacturer/product properties or str(Device) here.
    return {'bus': device.bus, 'address': device.address,
            'port_numbers': list(device.port_numbers) if device.port_numbers is not None else None,
            'vendor_id': device.idVendor, 'product_id': device.idProduct,
            'device_version': device.bcdDevice, 'usb_version': device.bcdUSB,
            'configuration_count': device.bNumConfigurations,
            'manufacturer_index': device.iManufacturer, 'product_index': device.iProduct,
            'serial_index': device.iSerialNumber,
            'selectable': (type(device.bus) is int and 0 <= device.bus <= 255 and
                           type(device.address) is int and 1 <= device.address <= 127)}


def _cached_descriptor(device):
    return struct.pack('<BBHBBBBHHHBBBB', device.bLength, device.bDescriptorType,
        device.bcdUSB, device.bDeviceClass, device.bDeviceSubClass, device.bDeviceProtocol,
        device.bMaxPacketSize0, device.idVendor, device.idProduct, device.bcdDevice,
        device.iManufacturer, device.iProduct, device.iSerialNumber, device.bNumConfigurations)


def _find(core, backend, devices, limit):
    for device in core.find(find_all=True, backend=backend, idVendor=VENDOR_ID, idProduct=PRODUCT_ID):
        devices.append(device)
        if len(devices) > limit:
            raise RuntimeError(f'More than {limit} matching USB devices; enumeration is incomplete')


def _close(devices):
    errors = []
    for device in devices:
        try:
            # Public PyUSB finalization consumes the finalizer even when close
            # raises. dispose_resources alone allows a later implicit retry.
            # These Device objects are private, fresh, and never claim anything.
            device.finalize()
        except Exception as error:
            errors.append(str(error) or type(error).__name__)
    return '; '.join(errors) if errors else None


def list_edlt_devices(*, backend=None, max_devices=64) -> USBDeviceList:
    """List cached VID166A/PID0501 metadata, without opening any device handle."""
    _bound(max_devices, 'max_devices', 1, 256)
    core, backend = _modules(backend)
    devices = []; rows = []; error = None
    try:
        _find(core, backend, devices, max_devices)
        rows = [_metadata(device) for device in devices]
    except Exception as exc:
        error = str(exc) or type(exc).__name__
        for device in devices[:max_devices]:
            try: rows.append(_metadata(device))
            except Exception: break
    finally:
        close_error = _close(devices)
    return USBDeviceList(error is None and close_error is None, tuple(rows), error, close_error)


def _configuration(data):
    if len(data) < 9 or data[:2] != b'\x09\x02' or int.from_bytes(data[2:4], 'little') != len(data):
        raise ValueError('Configuration descriptor header/total length is inconsistent')
    if data[5] == 0 or data[7] & 0x9f != 0x80:
        raise ValueError('Configuration value or reserved attribute bits are invalid')
    offset = 9; interfaces = {}; current = None
    while offset < len(data):
        if len(data) - offset < 2:
            raise ValueError('Truncated configuration child descriptor')
        size, kind = data[offset:offset+2]
        if size < 2 or offset + size > len(data):
            raise ValueError('Configuration child descriptor has an invalid length')
        value = data[offset:offset+size]
        if kind in (1, 2):
            raise ValueError('Nested device/configuration descriptor is invalid')
        if kind == 4:
            if size != 9: raise ValueError('Interface descriptor must contain nine bytes')
            current = (value[2], value[3])
            if current in interfaces: raise ValueError('Duplicate interface/alternate descriptor')
            interfaces[current] = {'expected': value[4], 'endpoints': set()}
        elif kind == 5:
            if current is None or size not in (7, 9):
                raise ValueError('Endpoint descriptor has no interface or an invalid length')
            address = value[2]
            if address & 0x70 or not address & 0x0f or address in interfaces[current]['endpoints']:
                raise ValueError('Endpoint address is invalid or duplicated')
            interfaces[current]['endpoints'].add(address)
        offset += size
    if len({number for number, _ in interfaces}) != data[4]:
        raise ValueError('Configuration interface count is inconsistent')
    if any(row['expected'] != len(row['endpoints']) for row in interfaces.values()):
        raise ValueError('Interface endpoint count is inconsistent')
    return {'value': data[5], 'interface_count': data[4], 'attributes': data[7],
            'max_power_units': data[8], 'raw': data.hex()}


class _Reader:
    def __init__(self, device, timeout, trace):
        self.device = device; self.timeout = max(1, math.ceil(timeout * 1000)); self.trace = trace

    def read(self, request, value, index, length):
        # Narrow allow-list, deliberately no public general-purpose Endpoint0.
        descriptor = request == 6 and value >> 8 in (1, 2, 3)
        configuration = request == 8 and value == index == 0 and length == 1
        if not (descriptor or configuration) or not 1 <= length <= 65535:
            raise ValueError('Only standard device-recipient IN descriptor/configuration reads are allowed')
        row = {'bmRequestType': 0x80, 'bRequest': request, 'wValue': value,
               'wIndex': index, 'wLength': length, 'timeout_ms': self.timeout}
        self.trace.append(row)
        try:
            response = self.device.ctrl_transfer(0x80, request, value, index, length, timeout=self.timeout)
            # Integer input length gives a byte array, never an OUT byte count.
            import array
            if not isinstance(response, array.array) or response.typecode != 'B':
                raise ValueError('PyUSB returned an invalid IN response type')
            data = response.tobytes()
            row.update(transferred=len(data), data=data.hex())
            if len(data) != length:
                raise ValueError(f'Incomplete USB control response: requested {length}, received {len(data)} bytes')
            return data
        except Exception as error:
            row['error'] = str(error)
            if getattr(error, 'backend_error_code', None) is not None:
                row['backend_error_code'] = error.backend_error_code
            raise

    def string_descriptor(self, index, language):
        header = self.read(6, 0x300 | index, language, 2)
        if header[1] != 3 or not 2 <= header[0] <= 254 or header[0] % 2:
            raise ValueError('String descriptor has an invalid type or even length')
        data = self.read(6, 0x300 | index, language, header[0])
        if data[:2] != header: raise ValueError('String descriptor changed between header and full read')
        return data


def inspect_edlt_device(*, bus, address, expected_serial=None, timeout=5.0,
                        backend=None) -> USBInspection:
    """Inspect one exact bus/address locator. No device is claimed or modified.

    USB bus/address is a transient enumeration locator, not permanent identity.
    expected_serial compares the chosen device's strictly decoded USB string;
    it is not assumed to equal the firmware diagnostic serial number.
    """
    _bound(bus, 'bus', 0, 255); _bound(address, 'address', 1, 127)
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 3600:
        raise ValueError('timeout must be finite, positive and at most 3600 seconds per control transfer')
    if expected_serial is not None:
        if not isinstance(expected_serial, str) or not expected_serial or '\0' in expected_serial:
            raise ValueError('expected_serial must be a nonempty string without NUL')
        try: encoded = expected_serial.encode('utf-16-le')
        except UnicodeEncodeError as error: raise ValueError('expected_serial must be valid Unicode') from error
        if len(encoded) > 252: raise ValueError('expected_serial exceeds the USB string descriptor limit')
    core, backend = _modules(backend)
    devices = []; trace = []; configs = []; strings = {}; langs = (); lang = None
    metadata = raw = active = match = dfu = unsupported = error = None
    stage = 'enumeration'; selector = {'bus': bus, 'address': address, 'expected_serial': expected_serial}
    try:
        _find(core, backend, devices, 64)
        candidates = [device for device in devices if device.bus == bus and device.address == address]
        if len(candidates) != 1:
            raise ValueError(f'Exact USB selector matched {len(candidates)} eDLT devices; exactly one is required')
        device = candidates[0]; metadata = _metadata(device); reader = _Reader(device, timeout, trace)
        stage = 'device_descriptor'; data = reader.read(6, 0x100, 0, 18); raw = data.hex()
        if data[:2] != b'\x12\x01' or data[7] not in (8, 16, 32, 64):
            raise ValueError('Invalid eighteen-byte device descriptor or Endpoint0 packet size')
        if data != _cached_descriptor(device):
            raise ValueError('Device descriptor changed since enumeration; identity is not consistent')
        if not 1 <= data[17] <= MAX_CONFIGURATIONS:
            raise ValueError(f'Only one through {MAX_CONFIGURATIONS} configurations are supported')
        stage = 'active_configuration'; active = reader.read(8, 0, 0, 1)[0]
        stage = 'configuration_descriptors'
        for index in range(data[17]):
            header = reader.read(6, 0x200 | index, 0, 9)
            total = int.from_bytes(header[2:4], 'little')
            if header[:2] != b'\x09\x02' or not 9 <= total <= 65535:
                raise ValueError('Configuration header has an invalid type/length')
            config = reader.read(6, 0x200 | index, 0, total)
            if config[:9] != header: raise ValueError('Configuration changed between header and full read')
            row = _configuration(config)
            if any(previous['value'] == row['value'] for previous in configs):
                raise ValueError('Duplicate configuration value')
            configs.append({'index': index, **row})
        selected = next((row for row in configs if row['value'] == active), None)
        if active and selected is None: raise ValueError('Active configuration value has no matching descriptor')
        if selected is None:
            unsupported = 'Device is unconfigured; inspection does not set a configuration'
        else:
            try: dfu = parse_descriptors(data, bytes.fromhex(selected['raw'])).as_dict()
            except ValueError as exc: unsupported = str(exc)
        stage = 'string_descriptors'
        indices = dict(zip(('manufacturer', 'product', 'serial'), data[14:17]))
        if any(indices.values()):
            language_data = reader.string_descriptor(0, 0)
            langs = tuple(int.from_bytes(language_data[i:i+2], 'little') for i in range(2, len(language_data), 2))
            if not langs or 0 in langs or len(set(langs)) != len(langs):
                raise ValueError('Language descriptor must contain unique nonzero language identifiers')
            lang = langs[0]
        cache = {}
        for name, index in indices.items():
            if index == 0:
                strings[name] = None
            else:
                if index not in cache:
                    value = reader.string_descriptor(index, lang)
                    try: cache[index] = value[2:].decode('utf-16-le', errors='strict')
                    except UnicodeDecodeError as exc: raise ValueError('String descriptor contains invalid UTF-16LE') from exc
                strings[name] = cache[index]
        if expected_serial is not None:
            match = strings['serial'] == expected_serial
            if not match: raise ValueError('USB serial does not match expected_serial')
        stage = 'configuration_recheck'
        if reader.read(8, 0, 0, 1)[0] != active:
            raise ValueError('Active USB configuration changed during inspection')
        stage = 'complete'
    except Exception as exc:
        error = str(exc) or type(exc).__name__
    finally:
        close_error = _close(devices)
    if close_error is not None and error is None: error = 'USB resource closure failed'
    return USBInspection(error is None and close_error is None, selector, metadata, raw, active,
        tuple(configs), langs, lang, strings, match, dfu, unsupported, tuple(trace), stage,
        error, close_error, close_error is None)
