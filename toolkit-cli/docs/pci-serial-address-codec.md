# Selected-serial address wire codec

`pci_serial_address` encodes the original CAL serial-address broadcast and
classifies captured receipts. These are pure functions: they do not open files,
connect to a PCI/CNI, send bytes, update a database, or change an address.

```python
from cbus_toolkit.pci_serial_address import (
    encode_serial_address, decode_serial_address_receipt,
)

wire = encode_serial_address("101136.1558", 6)
assert wire == b"\\05FF000F0018B106160615g\r"

receipt = decode_serial_address_receipt(
    b"g.86061000870018B106160000F8\r\n",
    serial="101136.1558", destination=6, local_unit=16,
)
assert receipt.matched
assert not receipt.movement_verified
print(receipt.as_dict())
```

The offline CLI returns JSON:

```sh
cbus-toolkit serial-address encode 101136.1558 6
cbus-toolkit serial-address encode 101136.1558 6 --checksum
cbus-toolkit serial-address receipt capture.bin --serial 101136.1558 --destination 6 --local-unit 16
```

`encode` returns `wire_text` and `wire_hex`; it never sends them. `receipt`
reads a raw capture file up to 4096 bytes and retains it in the result. Both
commands accept `--confirmation g` through `z`. Receipt exit status 0 means
the packet matched the request; every other classification returns 1. Neither
status establishes physical movement or persistence. The commands have no
host, port or connection option.

## Request encoding

The native serial comprises a 20-bit decimal first component and a 12-bit
decimal second component. The codec accepts decimal-dot strings, normalizes
leading zeroes, checks both ranges, and packs `(first << 12) | second` into four
big-endian bytes. Zero and FFFFFFFF are unsupported unknown serial values. The
destination must be an integer in the conservative supported range 2..254.
This range is a codec restriction, not a claim about every device's allowable
addresses. Source-location, occupancy, local-PCI relocation and device-family
preconditions require a separate physical workflow.

The binary packet is `05 FF 00 0F 00`, four serial bytes, one destination byte,
and an inner checksum. Original `co.a(cn,int)` computes that checksum over only
the `00` immediately after opcode 0F, the serial and destination. It makes that
body's sum zero modulo 256. The packet contains **no source address**: generating
these bytes does not constrain which physical address currently holds the serial.

The outgoing text begins with a backslash and ends with a confirmation byte
from `g` through `z`, followed by CR. `confirmation` defaults to `b"g"`.
`command_checksum=True` adds a separate SRCHK checksum over the whole binary
packet. It does not replace the inner checksum. For this packet shape the outer
checksum is ED because the fixed header sums to 13 hex and the inner body sums
to zero.

Original native vectors and their SRCHK forms:

```text
101136.1558 -> 6: \05FF000F0018B106160615g\r
with SRCHK:      \05FF000F0018B106160615EDg\r
101136.1559 -> 7: \05FF000F0018B106170713g\r
with SRCHK:      \05FF000F0018B106170713EDg\r
```

Input type, serial, destination, confirmation and Boolean checksum errors raise
before any bytes are returned. Nothing transmits the result.

## Receipt classification

`decode_serial_address_receipt(data, *, serial, destination, local_unit,
confirmation=b"g")` accepts at most 4096 captured bytes. It parses the entire
capture, including any PCI confirmation and trailing data, and retains the raw
capture plus valid parsed prefixes. Bad API arguments raise; bad wire data
returns a classified result. Hexadecimal case, CR/LF separators and PCI XON/XOFF
flow-control bytes are handled without changing the retained raw capture.

Only one expected successful confirmation **before** one exact direct routed
receipt can be `matched`. The supported routed header is 86, with source equal
to the requested destination, destination equal to `local_unit`, and route 00.
The frame must contain exactly one CAL: opcode 87, prefix/parameter 00, the
four selected serial bytes, and two opaque bytes, with a valid whole-frame
checksum. An echoed outgoing backslash prefix is not a receipt.

| Status | Meaning |
| --- | --- |
| `matched` | The whole capture satisfies this strict packet-correlation contract. |
| `unverified` | A complete frame lacks confirmation or fails correlation, attribution or the supported receipt shape. |
| `incomplete` | No full receipt arrived, or trailing input is truncated. |
| `invalid` | Framing, checksum or unsupported incoming-prefix validation failed. |
| `ambiguous` | Multiple/foreign/reordered confirmations, multiple frames/CALs, unsolicited notifications, or contradictory receipt-after-rejection data occurred. |
| `rejected` | One matching negative PCI confirmation arrived without a conflicting frame. |

Invalid framing takes precedence over ambiguity, then truncation, rejection,
missing receipt and remaining correlation issues. The full issue list remains
available. A valid prefix never hides a later malformed, partial or conflicting
receipt. Missing confirmation is distinct from structural receipt validity:
the serial and packet fields remain available but the result is `unverified`.

The original native receipt for serial 101136.1558 at address 6 is:

```text
g.86061000870018B106160000F8\r\n
```

Original C-Gate also accepted this opaque-tail variant:

```text
g.86061000870018B10616FACE30\r\n
```

The parser retains `0000` or `FACE` as `opaque_tail_hex`, with
`opaque_tail_interpreted=false`. These bytes are not assigned a success,
EEPROM-checksum or persistence meaning. The native bare variant
`870018B10616000094` is decoded for evidence but is unattributed and cannot match.
Other routed headers supported by the generic PCI decoder remain unverified;
they have not been accepted into this bounded receipt contract.

`SerialAddressReceipt.as_dict()` identifies
`cbus-pci-serial-address-receipt-v1` and includes `status`,
`receipt_matches_request`, expected fields, raw capture, confirmations, parsed
replies/frames, notifications, pending bytes, issues and parsing errors. Every
result has `movement_verified=false`, `persistence_verified=false`,
`requires_independent_verification=true` and `io_performed=false`. There is no
`complete` or physical-success property to confuse packet validity with an
address change.

## Evidence and limits

[serial-address-codec-evidence.json](serial-address-codec-evidence.json) pins the
original C-Gate JAR/class/member hashes, method offsets, native transmissions and
receipt faults. Tests use the literal original request/receipt bytes independently
of this encoder. Separate boundary vectors verify the 20/12-bit packing and both
checksums. Tests cover malformed framing, serial/destination bounds, correlation,
unknown serials, opaque tails, ordering, multiple messages, trailing fragments,
byte limits and absence of I/O.

The [native fault report](native-duplicate-unravel-research.json) includes a
matching-looking receipt that did not move the unit, a wrong-source receipt
despite movement, and movement with no receipt. A matching packet therefore
does not verify the physical result. The exact source/bytecode and further
full-inventory probes remain under
`research/runtime/selected-serial-contract/`; the earlier
[research note](selected-serial-addressing-research.md) describes the broader
native fallback and Local SAL investigation.

No selected-serial transport, retry policy, transaction, Local SAL change,
physical inventory guard, rollback, or reboot persistence is implemented by
this module. Native MATCHDB fallback is not invoked. Any physical workflow using
this codec must establish independent before/after identity and address evidence
and explicitly handle uncertain outcomes. The bounded implementation is
documented in [Selected-serial commissioning](pci-selected-serial.md).

```sh
PYTHONPATH=src .venv/bin/python -m unittest tests.test_pci_serial_address
```
