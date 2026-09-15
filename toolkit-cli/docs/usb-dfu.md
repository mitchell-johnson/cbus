# Claimed eDLT USB session and DFU lease

`usb_dfu.py` supplies an explicit physical-resource owner and one logical Endpoint0 lease. It validates the selected USB identity, configuration and alternate, manually claims interface0, and transports the existing DFU client's bounded request set. The owner separately releases the interface and closes the handle. Release may change interface state and has no supplied deadline.

The accepted implementation has 25 focused tests using real PyUSB1.3.1 with an independent fake backend and the separately implemented `DFUSimulator`. Tests exercise complete inspection, programming, erase and byte-for-byte readback, plus acquisition, transfer, interruption and cleanup failures. No physical USB device was enumerated or accessed. The compact evidence is [usb-dfu-acceptance-summary.json](usb-dfu-acceptance-summary.json); the local full report is `research/runtime/usb-dfu-acceptance.json`.

## API and ownership

```python
from cbus_toolkit.dfu_transport import DFUClient
from cbus_toolkit.usb_dfu import ClaimedUSBSession

# descriptor and backend are explicit validated/fake fixtures in acceptance.
preflight = DFUClient.preflight(
    descriptor, operation="program", flash_size=262144,
    application_start=8192, data=payload, address=8192,
)
session = ClaimedUSBSession.acquire(
    bus=1, address=7, expected_serial="ABC123", descriptor=descriptor,
    release_policy="reset-first-alternate", backend=backend,
)
try:
    client = DFUClient(session.endpoint(), descriptor,
                       flash_size=262144, application_start=8192)
    result = client.program(payload, address=8192)
finally:
    release = session.release()
```

These selectors are synthetic examples. The public acquisition signature is:

```python
ClaimedUSBSession.acquire(*, bus, address, expected_serial, descriptor,
    release_policy, inspection_timeout=5.0, backend=None)
```

There is no default release policy: the caller must explicitly provide `reset-first-alternate`. The normal backend selection uses only libusb1 through the optional `usb` extra (`pyusb==1.3.1`). A missing backend is an acquisition error. This adapter does not install/change a driver.

`session.endpoint()` returns exactly one `USBEndpoint0Lease`. Its `control(bm_request_type, request, value, index, *, data=b"", length=0, timeout=...)` returns the existing `ControlReply`. Its `close()` invalidates that logical service only. The physical handle and claim remain owned by the session until `session.release()` runs. Direct public construction of a lease is rejected.

The coordinator must release in an outer `finally` covering all work after acquisition, including construction of the DFU client. `DFUOutcome.complete` alone does not mean the USB lifecycle completed. Acquisition, DFU operation and release must all complete for a complete overall result. A successful full readback can coexist with a failed interface release or handle close; both facts remain visible.

`DFUClient.preflight` validates constructor geometry/options plus the same program/erase planners used during execution, without any Endpoint0 access. Use it before acquisition. Its compact result records bounds, operation, address/length, chunk count and optional payload hash. Inspect accepts no data/address/length; program derives length from its bytes; erase accepts address/length and no payload. This check does not establish device or firmware compatibility.

## Acquisition checks

Acquisition requires exact bus0..255/address1..127, a nonempty expected USB serial, and a canonical `DFUInterface` returned by `parse_descriptors`. The expected device must have one configuration at descriptor index0 and a serial-string index. A bounded enumeration must match exactly one eDLT VID166A/PID0501 device. Only that device is opened.

On the same private Device/handle, acquisition checks the actual device descriptor against both cached and explicitly expected bytes, compares the complete configuration descriptor, reads actual active configuration, and strictly reads the USB serial in the first advertised language. Invalid language descriptors, malformed UTF-16LE, partial reads, mismatched serials, or a different/unconfigured active value fail before claim.

The owner then manually claims interface0. It sends actual `GET_INTERFACE` (`81/0A`, index0, length1), requires alternate0, and rechecks active configuration. It never selects a configuration or alternate. Current `DFUClient` fetches descriptor index0 directly, so the adapter does not accept a different active descriptor index or rewrite a request.

PyUSB automatically claims interfaces for non-vendor interface-recipient control calls, including GET_INTERFACE. An already manually claimed interface is not claimed again. This is why the claim precedes the alternate query. [PyUSB core1.3.1](https://github.com/pyusb/pyusb/blob/v1.3.1/usb/core.py)

An alternate mismatch can only be observed after that claim through this API. Failing acquisition then releases the interface; that release may reset it to the first alternate. The result records the observed alternate and separate cleanup result. A claim is ownership of interface0, not exclusive control of every device request or an atomic identity snapshot.

## Request restrictions

The lease allows the existing client's device/configuration GET_DESCRIPTOR, GETSTATUS, exact eDLT extension query, UPLOAD, DNLOAD and ABORT request shapes. It rejects other interface indices, descriptor indices, incorrect fixed lengths, inconsistent direction/payload lengths, oversized transfers and unknown request types before I/O. There is no DETACH, CLRSTATUS, SET_CONFIGURATION, SET_INTERFACE, device reset or driver operation exposed through the lease.

The shared upload/download sequence must advance once without replay or wrapping. For DNLOAD command headers, only INFO, PROGRAM, READ, ERASE and binary mode are accepted. Vendor RESET/CHECK headers, nonpositive/unbounded lengths and nonzero external addresses are rejected. Once PROGRAM declares its byte count, firmware payload bytes are opaque; the same bytes that would mean RESET as a command are accepted as program data. Premature termination, oversized data, upload or abort during a selected program stream are rejected. This distinction is verified against independent peer memory.

The lease is a transport guard, not a replacement for the DFU client's state, geometry and independent readback checks. A short result preserves the exact count and invalidates the lease. A USB error or interruption also invalidates it, records stage/native error details where available, and performs no further control request. It does not release automatically; the physical owner still requires its explicit final cleanup.

## Release and failures

`USBReleaseOutcome` records `release_attempted`, `release_succeeded`, `release_error`, `close_attempted`, `close_succeeded` and `close_error` separately. A release that was not needed has `release_attempted=false` and `release_succeeded=false`; it is not reported as a successful physical release. Completion means all required cleanup calls completed without an error. `close_attempted` reflects an open PyUSB handle presented for finalization.

Release timing failures are separate `timing_error` evidence and also prevent an overall complete result. Both starting and finishing timer reads are guarded: an interruption there cannot skip cleanup or erase `last_release`. If timing, interface release and handle closure encounter multiple interruptions, the original interruption is re-raised and later failures remain in their separate fields. Tests use distinct interruption objects to verify this ordering and prove that a repeated release performs no additional cleanup or clock call.

The owner invalidates itself before cleanup, explicitly calls `usb.util.release_interface`, retains any error, and finalizes every owned Device once. Repeated `release()` calls return the recorded outcome without any backend call. A release failure does not prevent a handle-close attempt. A close failure cannot erase an earlier release failure or trigger a later implicit garbage-collector retry. These behaviors depend on the pinned PyUSB explicit-release/finalization implementation and are exercised with injected faults. [PyUSB resource helpers](https://github.com/pyusb/pyusb/blob/v1.3.1/usb/util.py), [PyUSB finalizer](https://github.com/pyusb/pyusb/blob/v1.3.1/usb/_objfinalizer.py)

libusb documents release as blocking and describes a SET_INTERFACE request that restores the first alternate setting. Automatic kernel detach is disabled on a fresh handle by default; this implementation never enables it. Claim BUSY/ACCESS/unsupported errors are retained, without detach or retry. [libusb device handling](https://libusb.sourceforge.io/api-1.0/group__libusb__dev.html)

Failed acquisition automatically performs this explicit release/close before raising `USBAcquisitionError`, which retains `.session`, `.acquisition`, `.release` and JSON-compatible `.details`. Original interruptions are re-raised with `.usb_acquisition` and `.usb_release` attached. A later release interruption is recorded in `session.last_release` before being re-raised. A coordinator must retain that result alongside `client.last_outcome` when an operation was interrupted. State after any attempted claim/release remains explicitly unverified.

## Timeouts and acceptance limits

Acquisition's timeout applies to each control request. DFU control uses the remaining budget rounded down to positive whole milliseconds and rejects a submillisecond budget before I/O. Zero is never passed to libusb, where it would mean unlimited. Actual bytes/counts are preserved on returned results; no partial data is invented when PyUSB instead throws a transfer error. [libusb control transfers](https://libusb.sourceforge.io/api-1.0/group__libusb__syncio.html), [PyUSB libusb1 adapter](https://github.com/pyusb/pyusb/blob/v1.3.1/usb/backend/libusb1.py)

There is no end-to-end or hard real-time guarantee. Enumeration, opening, claiming, release and closing have no caller-supplied deadline; OS scheduling/FFI overhead can also delay a control return. DFUClient checks for late completion afterward. Concurrent application control/release entry is rejected without waiting for an application lock. A concurrent rejected release has not run and cannot be treated as resource disposal. No background cancellation, reconnect, reset or request replay is attempted.

Reproduce the focused tests with:

```sh
CBUS_USB_DFU_REPORT=research/runtime/usb-dfu-acceptance.json \
.venv/bin/python -m unittest tests.test_usb_dfu -v
```

`ClaimedBackend` in the test file drives real PyUSB Device/control/claim/release handling and delegates DFU byte requests to the independent memory peer. Literal fixtures cover manual claim count, alternate/configuration rejection, serial/language errors, BUSY, short/failed transfer, interrupted programming, explicit release errors and hidden-retry prevention. Backend methods for configuration changes, alternate selection, resets and kernel-driver operations fail if invoked. The modeled release side effect is documented behavior, not a physical USB capture.

The original unmodified vendor DLL's descriptor/protocol comparisons remain separate evidence in [dfu-transport.md](dfu-transport.md) and [dfu-protocol.md](dfu-protocol.md). This suite establishes Python/PyUSB integration against a fake backend, not physical bootloader acceptance. Real hardware/driver behavior, firmware payload/variant compatibility, reset/re-enumeration, recovery and live installation remain unverified.
