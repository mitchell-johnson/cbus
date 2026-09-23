# eDLT USB inspection

`usb_inspection.py` inspects one explicitly selected eDLT USB device using standard device-recipient IN requests. It lists cached metadata, reads the device and configuration descriptors, binds the active configuration by its value, and strictly decodes the advertised manufacturer, product and serial strings. It never claims an interface or sends an OUT request. This is a separate inspection API; it cannot be supplied to `DFUClient` to flash a device.

The focused acceptance uses real PyUSB 1.3.1 core with an independent fake backend. It passes 21 module tests and 5 CLI tests. No test enumerates, opens or changes a physical USB device. Fourteen representative module outcomes retain 106 backend request records, including negative cases, in `research/runtime/usb-inspection-acceptance.json`. The compact source/count evidence is [usb-inspection-acceptance-summary.json](usb-inspection-acceptance-summary.json).

## API and commands

```python
from cbus_toolkit.usb_inspection import list_edlt_devices, inspect_edlt_device

devices = list_edlt_devices()  # Cached VID166A/PID0501 metadata only.
result = inspect_edlt_device(bus=1, address=7,
                            expected_serial="ABC123", timeout=5.0)
print(result.as_dict())
```

The numeric selectors and serial above are synthetic examples. `list_edlt_devices(*, backend=None, max_devices=64)` returns `USBDeviceList`. `inspect_edlt_device(*, bus, address, expected_serial=None, timeout=5.0, backend=None)` returns `USBInspection`. The optional backend parameter supports explicitly injected test services. In normal use the module selects only the libusb1 backend; it does not fall back to another backend or install drivers.

```sh
cbus-toolkit firmware usb-list
cbus-toolkit firmware usb-inspect --bus 1 --address 7 --expected-serial ABC123 --timeout 5
```

Install the optional `usb` extra to obtain the pinned `pyusb==1.3.1` dependency. A compatible native libusb1 library must separately be available. PyUSB 1.3.1 supports Python 3.9 and later; the CLI itself requires Python 3.10 and later. The module reports a missing dependency or backend without trying to repair the host. [PyUSB release metadata](https://pypi.org/project/pyusb/1.3.1/)

## Exact selection and inspection scope

Enumeration uses `find_all=True`, filters only cached VID/PID fields, and retains at most the requested number of matching candidates (default 64, maximum 256). Exceeding the limit is an incomplete result, not a successful truncated list. Inspection independently caps matching candidates at 64. No string property is used while finding candidates.

Inspection requires exactly one match for bus 0..255 and address 1..127. A missing or ambiguous match fails before a handle is opened. Platforms without usable bus/address metadata can list a device but cannot select it through this API. Bus/address denotes a current enumeration location, not permanent identity. Only the selected device is opened. Its complete 18-byte descriptor must match the cached descriptor before more reads proceed.

The result records descriptor hex, configuration indices and values, active configuration, strings, language IDs, selected language, optional serial match, and the actual request/response trace. Empty or NUL-containing USB serials are not usable serial identities. `expected_serial` must be a nonempty, valid Unicode string fitting a USB string descriptor and containing no NUL. This comparison uses the USB serial string; it does not assume equality with the firmware diagnostic serial.

Every configuration is fetched by descriptor index using a nine-byte header followed by its declared complete length. The bounded implementation accepts at most eight configurations, each at most 65535 bytes. It rejects changing headers, duplicate configuration values, inconsistent interface/endpoint counts, duplicate interface/alternate or endpoint identifiers, and malformed child lengths. The active configuration comes from a real `GET_CONFIGURATION` request and must match a descriptor's `bConfigurationValue`; index zero is not assumed active. A final `GET_CONFIGURATION` must return the same value.

For nonzero string indices, the reader fetches descriptor zero, validates unique nonzero language IDs, and uses the first advertised language. It reads each distinct string index once in that language, with separate header/full reads. Descriptor type, even length 2..254, unchanged header and strict UTF-16LE are required. Absent indices are `null`; an empty serial remains empty. A malformed or unavailable string stops inspection and retains earlier results.

`complete=true` means these inspection reads and resource closure completed. It does not mean that DFU is ready or that exclusive ownership was acquired. A valid unconfigured or runtime device can have `complete=true` and `dfu_profile_supported=false`. The result explains this through `unsupported_reason`. For an active configuration matching the narrow, separately tested eDLT descriptor profile, `dfu_interface` contains parsed metadata. The active alternate setting, actual DFU state, flash capacity, firmware compatibility and physical-device behavior remain unverified.

## Request and resource contract

The only control requests are:

| bmRequestType | bRequest | Meaning |
|---:|---:|---|
| `80` | `06` | Device, configuration or string GET_DESCRIPTOR |
| `80` | `08` | GET_CONFIGURATION |

No interface claim, release, GET_INTERFACE, SET_CONFIGURATION, SET_INTERFACE, reset, kernel-driver operation, DFU GETSTATUS, extension INFO or OUT transfer is issued. There is no device lock or exclusive ownership claim. Concurrent changes may invalidate inspection; the descriptor and configuration checks cannot turn separate USB reads into an atomic snapshot.

This separation matters because PyUSB automatically claims an interface for non-vendor interface-recipient requests. Its general descriptor/string conveniences also differ from this reader's strict length and language handling. The adapter uses the integer-length form of `Device.ctrl_transfer`, which returns the received byte array, and checks the exact length before proceeding. [PyUSB core 1.3.1](https://github.com/pyusb/pyusb/blob/v1.3.1/usb/core.py), [PyUSB string helpers](https://github.com/pyusb/pyusb/blob/v1.3.1/usb/util.py)

The official libusb contract says releasing a claimed interface can block and sends SET_INTERFACE to restore the first alternate setting. A future claimed DFU adapter therefore needs a separate mutation and cleanup contract; its release cannot be described as a read-only close. This inspection creates private Device objects and never claims an interface, so finalization has no claimed interface to release. [libusb device handling](https://libusb.sourceforge.io/api-1.0/group__libusb__dev.html)

Each private Device is finalized once on success, failure or interruption. The pinned PyUSB public `finalize()` marks the finalizer consumed before cleanup, unlike merely disposing resources. A failed close is retained as `close_error` with `resources_closed=false`; it neither replaces the original inspection error nor triggers an implicit garbage-collector retry. The fake backend explicitly checks that close is attempted once after a scripted close failure. [PyUSB finalizer implementation](https://github.com/pyusb/pyusb/blob/v1.3.1/usb/_objfinalizer.py)

`timeout` applies separately to each control transfer. It must be finite and positive, up to 3600 seconds; conversion to milliseconds rounds up, with a minimum of one millisecond. Zero is never passed, since libusb treats zero as unlimited. Enumeration, opening and closing have no supplied deadline, and there is no end-to-end timeout claim. A timeout or short result stops further control I/O without retry. PyUSB's synchronous error path does not expose partial control data on a thrown USB timeout; such data is not invented in the report. [libusb synchronous I/O](https://libusb.sourceforge.io/api-1.0/group__libusb__syncio.html), [PyUSB libusb1 transfer adapter](https://github.com/pyusb/pyusb/blob/v1.3.1/usb/backend/libusb1.py)

## Acceptance and remaining work

```sh
CBUS_USB_INSPECTION_REPORT=research/runtime/usb-inspection-acceptance.json \
.venv/bin/python -m unittest tests.test_usb_inspection tests.test_cli_usb_inspection -v
```

The independent backend in `tests/test_usb_inspection.py` supplies literal descriptors and handles only the two allowed standard request types. Its claim, release, configuration, alternate-setting, reset and kernel-driver methods fail if invoked. Tests run PyUSB's actual enumeration, Device construction, control transfer, byte-array handling and finalization. CLI tests patch only `libusb1.get_backend`, preserving argument parsing through to this same request path.

Coverage includes multiple candidates, absent locators, mismatched cached identity, active configuration at a nonzero index, unconfigured/runtime inspection, invalid configuration records, multilingual/surrogate-pair strings, malformed Unicode/languages, serial mismatch, partial reads, USB timeout, opening failure, interruption and close failure. A full valid fixture performs exactly 13 standard IN requests and one open/close pair. The focused run records Python 3.13.14 and PyUSB 1.3.1; release wheel reports track other Python versions separately.

This evidence establishes the bounded host inspection behavior against a fake backend. Physical USB/driver acceptance, claimed DFU ownership, status/configuration transitions, re-enumeration, recovery and live firmware installation remain separate work. The original vendor DeviceOpen negative fixtures are documented in [dfu-transport.md](dfu-transport.md); its permissive success return is not used to declare this inspection or any flash operation complete.
