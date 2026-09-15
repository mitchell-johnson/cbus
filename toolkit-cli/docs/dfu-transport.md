# Injected Endpoint0 DFU client

`dfu_transport.py` implements a bounded Python client for a supplied Endpoint0 transport. It fetches and validates the active peer's USB descriptors, checks its status and extension response, compares reported flash geometry with explicit bounds, and performs one program or erase operation with independent byte-for-byte readback. This module includes an adapter for the memory simulator. The separate [claimed PyUSB session](usb-dfu.md) now provides a logical Endpoint0 lease with fake-backend acceptance; its physical interface release is an explicit outer lifecycle step. There is no hardware acceptance claim. The read-only [USB inspection API](usb-inspection.md) cannot serve as this client's Endpoint0.

The client builds on [DFU protocol evidence](dfu-protocol.md). Its focused suite passes 29 tests, including 12 executions of the original vendor `DeviceOpen` implementation with fake USB descriptors. Fifteen representative Python client outcomes are retained alongside peer-memory hashes in the local full report. The compact report is [dfu-transport-acceptance-summary.json](dfu-transport-acceptance-summary.json).

## API and ownership

```python
from cbus_toolkit.dfu_transport import (
    parse_descriptors, DFUClient, DFUOperationError, MemoryEndpoint0,
)
from cbus_toolkit.dfu_simulator import DFUSimulator

# Explicit synthetic descriptor fixture; these bytes do not identify hardware.
device = bytes.fromhex("12010002000000406a160105341201020301")
configuration = bytes.fromhex(
    "09021b0001010080320904000000fe010200092107e80300040001"
)
descriptor = parse_descriptors(device, configuration)
peer = DFUSimulator(flash_size=262144, application_start=8192)
endpoint = MemoryEndpoint0(peer, descriptor)
client = DFUClient(endpoint, descriptor,
                   flash_size=262144, application_start=8192)
result = client.program(bytes(range(256)), address=8192)
assert result.complete
assert result.as_dict()["peer_verified"]
assert bytes(peer.internal[8192:8448]) == bytes(range(256))
```

The public operations are `inspect()`, `program(data, address=...)` and `erase(address=..., length=...)`. Constructor options include explicit `flash_size`, `application_start`, `external`, an overall `timeout`, and a per-command `poll_limit`. Clock and sleep functions may be injected for deterministic tests.

`DFUClient.preflight(descriptor, *, operation, flash_size, application_start, external=False, timeout=30, poll_limit=256, data=None, address=None, length=None)` validates the entire requested operation before a transport is acquired. It uses pure constructor validation and the same program/erase planning methods as execution, including sequence limits. It returns compact geometry/operation/chunk metadata and an optional payload hash, without any Endpoint0 call. Acquisition or device compatibility is not implied by that result.

A client and its exclusively owned Endpoint0 session can be consumed once. Every outcome closes that service. Reusing the client raises before any I/O. A new logical session does not establish physical-device ownership, clear a delayed USB request or prove a resumable flash state. Reconnection and continuation of a physical device are outside this implementation. The example uses a fresh, explicitly configured memory peer.

Program does not erase automatically. Erase requires explicit aligned address and length. It encodes the exact requested block count; it does not reproduce the original DLL's `length/(block_size-1)` arithmetic defect. The 2 MiB regression reads back all 2097152 requested bytes and proves that the following 2048 bytes remain unchanged. External operations are restricted to address zero because other external address semantics remain unresolved in the vendor evidence.

## Endpoint0 contract

The supplied service implements:

```python
control(bm_request_type, request, value, index,
        *, data: bytes, length: int, timeout: float) -> ControlReply
close() -> None
```

`ControlReply(success, transferred, data=b"")` preserves both transport success and the actual byte count. OUT responses must have no returned data and must acknowledge exactly the supplied payload length. IN responses must provide both the exact count and exactly that many bytes. Failed, short, malformed or inconsistent results invalidate the operation. The host never interprets a failed transfer as successful merely because its reported length matches.

The service must honor the supplied timeout and must never replay a request internally. Python cannot enforce a deadline on arbitrary injected code that blocks indefinitely; no worker-thread cancellation or hidden USB backend is supplied. The client checks its deadline before and after each call, bounds status polling independently, and stops without further control requests on a timeout. `close()` must release the service without performing unrequested recovery or mutation.

The memory adapter provides explicitly supplied descriptor bytes for synthetic GET_DESCRIPTOR requests and delegates DFU requests to the independent `DFUSimulator`. That simulator's decoder does not import the host parser or encoder. The original x86 DLL was separately exercised against it in the protocol acceptance suite.

## Descriptor and geometry checks

`parse_descriptors(device, configuration)` returns a canonical `DFUInterface`. A client revalidates that object, then fetches device and configuration descriptors through its active Endpoint0 service and compares the actual parsed result with the expected object. Supplying a valid descriptor object cannot conceal a short transfer or different peer identity.

The bounded profile requires:

- An exact 18-byte device descriptor and a consistent configuration total length of 9..65535 bytes.
- VID`166A`, PID`0501`, a valid Endpoint0 packet size and at least one configuration.
- Consistent interface counts, no duplicate interface/alternate pair, and no zero/truncated descriptor lengths.
- Exactly one DFU interface: interface 0, alternate 0, class`FE`, subclass 1, protocol 2. Runtime protocol 1 is not automatically detached or recovered.
- Exactly one complete nine-byte functional descriptor associated with that interface; download and upload capabilities; supported attribute bits; DFU1.0.
- Transfer size 22..1024 bytes. The 22-byte minimum is needed for the native INFO response; the separate offline binary-plan helper can describe smaller packet sizes without claiming client support.

Before any flash command, the peer must report status OK in DFU idle. The client does not abort an operation already in progress when it first connects. It then validates the exact extension response`4D4C0100` and reads the 22-byte INFO record. Block size, transfer size, flash capacity and application start must match the supplied descriptor and explicit memory geometry. Unmatched or missing geometry fails before a program or erase command.

The native `DeviceOpen` probe demonstrates why return0 is insufficient:

| Original fixture | Native result | Strict client treatment |
|---|---:|---|
| Valid DFU descriptors | 0 | Accepted, then status/extensions/geometry checked |
| Runtime interface | 0 | Rejected; no implicit mode switch |
| No matching enumerated device | -3 | Enumeration not implemented; a failed service cannot be used |
| Short/wrong device descriptor | -4 | Short transfer/header rejected |
| Short configuration descriptor | -4 | Short transfer rejected |
| Wrong interface class | -4 | Rejected |
| Missing functional descriptor | 0 | Rejected |
| Zero transfer size | 0 | Rejected |
| Failed initial status | 0 | Rejected; no subsequent control request |
| Missing extension response | 0 | Rejected before flash command |
| Zero-length interface descriptor | Native execution budget exhausted | Rejected immediately during bounded traversal |

The native helper can report extension support even when zero transfer size prevents its INFO exchange. Its image writer also does not gain device-version compatibility proof from descriptor success: the separately accepted native image-reader tests show that it does not compare the device BCD. Neither native permissiveness is used as authorization to program a peer.

## State, verification and failure outcomes

The host maintains one shared 16-bit block sequence across INFO, DNLOAD and UPLOAD requests. Preflight checks account for both program and readback blocks and reject a sequence that would wrap. Status polling accepts only known status/state values, honors the 24-bit delay, and applies an absolute operation deadline plus a per-command poll count. Zero advertised busy delay still yields a bounded polling interval.

After a complete program stream, a zero-length DNLOAD must return the peer to idle. For readback, the client enables binary mode, selects the exact range, receives every requested byte, disables binary mode and restores idle using only state transitions owned by the current transaction. A known byte mismatch still completes this bounded readback cleanup before reporting failure. An ambiguous transfer, malformed status, native error or polling deadline stops control I/O immediately; it does not retry or attempt recovery.

`DFUOutcome.as_dict()` records:

- `complete`: the whole requested operation, verification and closure completed.
- `payload_transferred`: program bytes whose OUT transfers were acknowledged completely. This is not a claim that those bytes were successfully programmed.
- `readback_bytes`, expected/readback SHA256 and `first_mismatch`: independent verification evidence.
- `peer_verified`: the complete requested range was read and matched, even if a later close failed. `physical_device_verified` remains false.
- `outcome_known`: success or a definite reported failure was observed. It does not assert that all flash contents are known after a native write error.
- `stage`, `error`, request/status trace, elapsed time, reported geometry and any separate `close_error`.

Failures raise `DFUOperationError`, preserving the structured result as `.outcome` and `.details`. A close error cannot replace the primary error or erase completed readback evidence. One lost-ACK fixture writes bytes into the peer before raising a timeout; the result remains uncertain, no termination is sent, and the payload is never replayed. A short-ACK fixture demonstrates the same boundary. These tests inspect peer memory independently of the host's exception.

`KeyboardInterrupt`, `SystemExit` and other interruptions also invalidate the one-operation client and attempt Endpoint0 closure exactly once. The original interruption is re-raised; `client.last_outcome` retains the partial operation, acknowledged bytes, trace and any separate close failure. A close failure does not replace an earlier interruption. No abort, program termination, recovery or readback request is added after an interrupted control transfer or polling sleep. Tests cover interruption after bytes reached peer memory but before acknowledgment, interruption during polling after acknowledgment, interrupted close after complete readback, and interruption while obtaining the starting clock. The earlier report is preserved as `research/runtime/dfu-transport-acceptance-before-interruption-fix.json`.

## Reproduction and limits

```sh
CBUS_DFU_DLL=research/vendor/toolkit/app/Firmware/eDLTFirmware/usb_drivers/i386/lmdfu_edlt.dll \
CBUS_DFU_TRANSPORT_REPORT=research/runtime/dfu-transport-acceptance.json \
.venv/bin/python -m unittest discover -s tests -p test_dfu_transport.py -v
```

The original descriptor probe lives in `research/native_dfu_descriptors.py` and uses the same isolated x86 execution services as `research/native_dfu_probe.py`. Its negative malformed-descriptor case ends at the emulator's instruction/time budget. pefile 2024.8.26 and Unicorn 2.1.4 are explicit research dependencies. The recorded run uses Python 3.13; broader installed-wheel/version results belong to the release acceptance reports.

The remaining work includes physical acceptance of the claimed transport/driver adapter, physical descriptor captures, verified device identity binding across an update, reset/re-enumeration, interrupted-update recovery, resumable sessions, real firmware payload/variant validation, nonzero external addresses, x64 native comparison and hardware acceptance. Standard inspection and the claimed-session adapter have separate fake-backend tests; these do not establish physical DFU behavior. This client is a tested injected-transport foundation; it does not establish complete Toolkit firmware-update functionality.
