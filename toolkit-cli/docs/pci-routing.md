# Offline CAL routing codecs

`RoutedCALCommand` encodes one point-to-point CAL command through explicitly supplied routing bytes. It performs no connection, configuration or transmission. `PCIClient`, MMI, commissioning and simulator behavior are unchanged.

```python
from cbus_toolkit.pci import IdentifyCAL
from cbus_toolkit.pci_routing import RoutedCALCommand, inspect_routed_cal_command

command = RoutedCALCommand(4, IdentifyCAL(4), bridges=(30, 20))
raw = command.encode(confirmation=b"g", checksum=True)
assert raw == b"\\461E12140421044Dg\r"
wire = inspect_routed_cal_command(raw, checksum=True)
assert wire.address_path == (30, 20, 4)
```

Bridge bytes are ordered nearest the attached PCI first. Unit and bridge values must be integers in0..255; Booleans and out-of-range values are rejected. Repeated addresses are retained as bytes, without claiming they form usable topology. An empty bridge tuple is supported.

## CLI

```sh
cbus-toolkit pci-route encode --unit 4 --cal 2104 \
  --bridge 30 --bridge 20 --confirmation g --checksum
cbus-toolkit pci-route inspect 5C34363145313231343034323130343444670D --checksum
```

Both commands operate offline. `encode` accepts exactly one supported CAL as
hexadecimal bytes, with bridge options in nearest-first order. Addresses use
decimal or `0x` hexadecimal notation. `inspect` accepts the complete ASCII
command encoded as hexadecimal bytes, including its backslash and terminating
CR. It accepts at most 87 bytes and never infers unit identity or programming
mode. Whitespace, incomplete hex pairs, extra CALs and trailing input are
rejected.

JSON includes `wire_text`, `raw_hex`, the literal `address_path`, and explicit
`command_sent=false` and `io_performed=false` fields. Encoding also records the
caller's `requested` unit, bridges and addressing mode; inspection has no such
inferred intent. Exit 0 means successful encoding or inspection, 1 means a
semantic or checksum error, and 2 means invalid CLI arguments. Five CLI tests
passed on both Python versions in the separate combined metadata/routing CLI
checkpoint; the original codec has its own 24-test acceptance below.

The routing byte is9 times the number of following address entries. At most six entries are accepted. `addressing="programming"` appends the captured `00` programming entry, so it permits at most five additional bridge bytes. Adding a seventh entry is rejected without returning a partially modified command. The command and copied bridge tuple are immutable.

`cal` is one exact existing `IdentifyCAL`, `RecallCAL`, `WriteCAL`, `AcknowledgeCAL` or `ReplyCAL` value. The codec preserves these byte forms; it does not assign a new operational meaning to them. Existing CAL payload limits apply. The longest supported encoding is87 bytes: six routing entries,30 data bytes, optional checksum, confirmation and terminating CR. Byte-level encoding does not establish that every such combination is accepted by physical devices.

`confirmation` is `None` or one byte in `g..z`. `checksum` must be an explicit Boolean; true appends the two's-complement checksum used by original `aW.f(String)`. False is the default. The codec neither discovers nor changes the PCI's SRCHK setting.

## Inspection preserves ambiguity

`inspect_routed_cal_command(raw, *, checksum=False)` accepts a single outgoing header46 command, exactly one supported CAL and one terminating CR. It rejects malformed/reserved route bytes, more than six entries, truncated routes, additional CALs, bad checksums and trailing input. Checksummed and unchecksummed input modes are explicit. Received frames, bare CAL responses and broadcast headers05/03 are outside this parser's scope.

The returned frozen `RoutedCALWireCommand` contains `address_path`, `cal`, `confirmation`, `checksum_included` and detached `raw` bytes. Its `route_count` and `as_dict()` expose the literal fields. It does not return an inferred source, logical network or programming mode.

In particular, a direct command to unit0 through byte4 and a programming command to unit4 both encode `\\460409002104\r` for IDENTIFY4. Inspection retains `(4, 0)` and reports `programming_mode_inferred=false`; it cannot distinguish those intentions from the bytes.

## Original evidence and limits

[Original vectors](../research/fixtures/pci-routing-original-vectors.json) record358 inputs and493 route-prepend steps from unchanged C-Gate3.4.0 build2001 `aW.k(int)`. Actual `cq`/`aW` constructors, their command setter/getter and checksum utility were invoked. Source and bytecode inspection established that these selected initialization paths only set fields and allocate arrays. Every step checked that all original instance fields except the command string retained their original value/reference. No sender or network method was invoked.

The matrix covers all256 address bytes, direct/programming route depths, zero and maximum routes, overflow/refused mutation,11 literal CAL forms, malformed routing fields and the separately excluded broadcast branch. Original integer formatting maps negative and above255 values toFF; the public API deliberately rejects those values instead. Original overflow returns false and leaves the command unchanged. The native bridge-network caller discards that Boolean; this codec exposes a bounded rejection rather than adopting that caller's continuation behavior.

The original Java process ran under a deny-all-network macOS sandbox. A connection attempt to an owned listening loopback witness was denied, and the listener accepted no connection. The first pilot failed at that witness before original construction because its expected error text omitted Java's `(connect failed)` suffix; both that failure and the corrected successful pilot are preserved. Large archives and fresh reports are stored in a separately owned external research directory, mapped from `research/runtime/pci-routed-cal-static/external-mapping.json`.

[Focused acceptance](../research/fixtures/pci-routing-acceptance.json) records both supported Python versions, including a fresh original358/493 matrix under the pinned owned macOS JDK. That optional test uses `CBUS_CGATE_JAVA`, `CBUS_CGATE_JAVAC` and `CBUS_LOCAL_CGATE_VENDOR`; its platform/permission boundary is explicit. `CBUS_PCI_ROUTING_REPORT_DIR` may select an owned report root, with a fresh subdirectory per execution. Other platforms require a separately established original-process isolation backend.

This outgoing evidence does not cover received route normalization, cached bridge/programming object resolution, routed MMI, physical network identity, hardware delivery, checksummed interface configuration, routed commissioning or firmware persistence.

## Received addressed frames

`inspect_received_cal_route(raw)` provides separate, strict inspection of a received addressed frame. It checks the checksum over the original bytes and accepts exactly one CAL, header `06` or `86`, an incoming route count from 0 through 6, and one terminating CR. Unlike the outgoing route field, the incoming count is used directly. The maximum is 87 bytes for this single-CAL profile.

```python
from cbus_toolkit.pci_routing import inspect_received_cal_route

frame = inspect_received_cal_route(b"8614100215048104B6\r")
assert frame.outer_source_byte == 20
assert frame.destination_byte == 16
assert frame.address_path == (20, 21, 4)
```

```sh
cbus-toolkit pci-route receive 3836313431303032313530343831303442360D
```

The CLI argument is the complete ASCII frame encoded as hexadecimal bytes, including its checksum and CR. Checksum validation is mandatory; there is no `--checksum` option. Exit codes are 0 for successful inspection, 1 for a semantic/checksum error and 2 for invalid arguments. The command performs no I/O. Output retains the original `wire_text`, `raw_hex`, outer address, destination, route entries and CAL. A route ending in zero stays literal; the command does not resolve a logical network, infer programming mode, authenticate a source or correlate a reply. Invalid addressed input is never retried as bare CAL.

[Incoming scope and original evidence](pci-incoming-routing.md) describes the 1,142 original constructor/cache/checksum cases, the stricter public grammar and the deliberately excluded contextual rewrites. [Incoming focused acceptance](../research/fixtures/pci-incoming-acceptance.json) records the separate 45-test run on each supported Python version, including fresh original execution and the existing outgoing codec/CLI and CAL/frame guards. The outgoing 24-test checkpoint above remains historical evidence with its own exact inputs.
