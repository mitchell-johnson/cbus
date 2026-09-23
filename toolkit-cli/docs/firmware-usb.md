# USB DFU operation coordinator

`run_usb_dfu` owns one USB acquisition, one DFU operation and the physical release. It returns separate acquisition, transfer and release evidence. Top-level `complete` is true only when all three succeed. A verified transfer followed by a failed release is an incomplete overall result, with its readback evidence retained.

The implementation supports the bounded eDLT profile accepted by `parse_descriptors` and `ClaimedUSBSession`: exact expected descriptor bytes, one configuration at index zero, an already active configuration, interface zero and alternate zero, and an exact nonempty USB serial string. It does not detach drivers, change the configuration or select an alternate during acquisition. Release may reset the interface to its first alternate, so the release policy is mandatory.

```python
from cbus_toolkit.dfu_transport import parse_descriptors
from cbus_toolkit.firmware_usb import run_usb_dfu

expected = parse_descriptors(device_descriptor_bytes, configuration_descriptor_bytes)
result = run_usb_dfu(
    "program", bus=1, address=7, expected_serial="EXPLICIT_DEVICE_SERIAL",
    descriptor=expected, release_policy="reset-first-alternate",
    flash_size=262144, application_start=8192,
    data=raw_firmware_bytes, address_offset=8192,
)
```

The example's location and geometry are illustrative. Callers must supply the intended device's exact expected descriptor, identity and geometry. `bus`/`address` identify a current USB enumeration location; `address_offset` identifies the flash offset. They are separate values.

## API

```text
run_usb_dfu(operation, *, bus, address, expected_serial, descriptor,
            release_policy, flash_size, application_start, external=False,
            timeout=30, inspection_timeout=5, poll_limit=256,
            data=None, address_offset=None, length=None, backend=None)
```

| Operation | Payload/range arguments | Verification |
|---|---|---|
| `inspect` | No `data`, `address_offset` or `length` | DFU state, diagnostic information and declared geometry |
| `program` | Raw `bytes` and explicit `address_offset`; no separate length | Read back and compare every programmed byte |
| `erase` | Explicit `address_offset` and `length`; no data | Read back every requested byte and verify erased contents |

`DFUClient.preflight` validates operation arguments, descriptor, geometry, range, alignment, payload and sequence limits before acquisition. It uses the same planners as execution. Invalid operation preflight raises before any USB access. Acquisition guards also validate the selector, serial, policy and inspection timeout before enumeration; acquisition failures return structured incomplete evidence.

Programming accepts raw bytes only. It does not strip or interpret firmware containers, erase automatically, reset, retry, resume, or replay requests after uncertain outcomes. The explicitly declared geometry is verified against the peer before modification. Current external-memory operations require address zero. See [DFU transport](dfu-transport.md) and [claimed USB ownership](usb-dfu.md) for the underlying bounds and protocol evidence.

The optional `backend` supplies a PyUSB backend. Tests always inject one; callers that omit it use the configured libusb1 backend. The installed `usb` extra pins `pyusb==1.3.1`.

## Result and interruptions

The JSON-compatible result uses format `cbus-usb-dfu-result-v1`:

| Field | Meaning |
|---|---|
| `preflight` | Pure validated operation plan; its `transport_acquired=False` describes preflight, not later execution |
| `acquisition` | Expected/observed identity, configuration, claim and alternate evidence, or `None` if no acquisition outcome exists |
| `transfer` | DFU operation outcome, including acknowledged payload, readback bytes/hashes, first mismatch, stage and trace; may be `None` |
| `release` | Claim release, handle close, timing errors and elapsed time; may be `None` if no owner was acquired |
| `complete` | True only if acquisition, operation and release all succeeded |
| `operation_invoked` | Whether the coordinator called a DFU operation; this does not itself prove that a modifying request was sent |
| `endpoint_trace` | Exact logical lease request evidence, including transfer lengths and data hashes |
| `error`, `errors` | Primary failure and separate staged failures; acquisition/transfer evidence is retained when cleanup also fails |
| `physical_device_verified` | Always false: backend success is not a hardware acceptance claim |

Ordinary operational failures return `complete=False`; the CLI exits 1. A short or lost response stops the operation without replay. Partial flash mutation may already have occurred, and transfer evidence reports uncertainty independently from cleanup success.

The coordinator releases its physical owner in an outer `finally`, including failures while obtaining the logical endpoint or constructing the DFU client. The client's endpoint close invalidates only the logical lease; it does not replace physical release. Release is called once per owner lifecycle; a failed acquisition's already recorded release is returned idempotently without another USB request.

`KeyboardInterrupt`, `SystemExit` and other interruptions propagate as the same exception object with a `usb_dfu_evidence` dictionary attached. If cleanup interrupts after an ordinary operation failure, that interruption propagates while the earlier failure remains in the evidence. An original interruption is not replaced by a later cleanup interruption. The CLI reports KeyboardInterrupt evidence and exits 130. `release_error`, `close_error` and `timing_error` remain separate; even a release-clock failure makes overall completion false while retaining actual release/close flags.

A successful program/erase `transfer.peer_verified` means the requested whole range matched readback. It does not establish firmware authenticity, hardware compatibility, successful boot, or real-device acceptance. Release may change interface state; `release.state_after_release_unknown` remains explicit. A readback result obtained before release is not evidence of the subsequent interface state.

## Timeouts and ownership

`timeout` is the DFU operation deadline, beginning after acquisition and client construction. Polling is additionally limited by `poll_limit`. `inspection_timeout` applies separately to each acquisition control transfer. USB enumeration, opening, claiming, release and close are not deadline bounded; neither option is an end-to-end lifecycle timeout.

The USB owner enforces the accepted request grammar and one logical lease. The coordinator never acquires a replacement owner or starts a second operation after failure. Neither claiming one interface nor checking its serial establishes exclusive ownership of the entire device.

## CLI and test evidence

The CLI exposes `firmware usb-dfu-inspect`, `firmware usb-dfu-program RAW_FILE`, and `firmware usb-dfu-erase`. It requires explicit bus/address, serial, descriptor files, geometry and `--release-policy reset-first-alternate`. `--address` is the USB address and `--offset` the flash offset. Program input is bounded raw file content; no container transformation occurs.

`tests/test_firmware_usb.py` drives actual PyUSB core through the independent `ClaimedBackend` and `DFUSimulator`. It verifies inspect/program/erase, internal and external bytes, whole-range readback, adjacent preservation, invalid input before acquisition, acquisition/constructor failures, partial writes and lost acknowledgements, readback mismatch, release/close/timing failures, interruption identity and failure evidence. `tests/test_cli_usb_dfu.py` exercises the public CLI through the same explicit backend and checks output and exit codes. No test enumerates the host USB bus.

Run the focused public workflow tests:

```sh
PYTHONPATH=src:. python3 -m unittest tests.test_firmware_usb tests.test_cli_usb_dfu -v
```

Related suites are `tests.test_usb_dfu`, `tests.test_usb_inspection` and `tests.test_dfu_transport`. The original DLL descriptor test also requires the research extras and `CBUS_DFU_DLL` pointing to the original x86 `lmdfu_edlt.dll`; its USB services are emulated. The full focused acceptance used Python 3.10.20 with PyUSB 1.3.1, pefile 2024.8.26 and Unicorn 2.1.4. Compact evidence and source hashes are in `research/fixtures/firmware-usb-acceptance.json`; full fake-backend traces remain under ignored runtime storage.
