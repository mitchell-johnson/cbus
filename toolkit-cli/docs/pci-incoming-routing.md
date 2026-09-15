# Incoming CAL route inspection

`inspect_received_cal_route` inspects a deliberately narrow received addressed CAL format without opening a connection:

```python
from cbus_toolkit.pci_routing import inspect_received_cal_route

reply = inspect_received_cal_route(b"860410008104E1\r")
assert reply.outer_source_byte == 4
assert reply.destination_byte == 16
assert reply.address_path == (4,)
assert reply.route_count == 0
```

The input must be exact ASCII hex pairs followed by one CR, with header06 or86, an incoming route count0..6, the complete route, exactly one supported CAL and a correct original checksum. Bytes, bytearray and memoryview are accepted; size is checked before copying. The limit is87bytes: four header bytes, up to six route bytes, up to32bytes for one CAL and one checksum, represented as hex plusCR. This is the limit of this single-CAL profile, not a universal original receiver packet limit.

The result retains the original input bytes, header, `outer_source_byte`, `destination_byte`, `route_entries`, CAL and `checksum_byte`. `address_path` joins the outer address and literal route entries. Its final byte is not promoted to a logical source. A terminalzero, repeated route byte or route entry255 stays literal; no programming mode or physical network topology is inferred. `as_dict()` returns detached JSON-compatible values and explicitly reports that network identity, programming mode and device origin are unverified. Checksum success is arithmetic integrity, not sender authentication.

The inspector rejects a leading backslash, tags, embedded controls, whitespace, LF/CRLF endings, odd hex, other headers, route counts7..255, incomplete routes, missing/bad checksums, unsupported CALs and trailing bytes. It never retries a malformed addressed header86 as bare CAL, even though86 also occurs as a bare reply opcode. The existing `decode_frame`, `PCIClient`, outgoing routing API, MMI, commissioning and simulator behavior are unchanged.

The original evidence is [the frozen constructor/cache/CRC vectors](../research/fixtures/pci-incoming-original-vectors.json), produced by [the original-method probe](../research/NativeIncomingRouteProbe.java). It executes unchanged `cj` constructors and checksum methods using explicit cached objects. Original network/unit fixture constructors are bypassed; original final cache-array and bridge-link getters remain unchanged. No receiver, sender, broadcast dispatch, shared C-Gate, VM or physical interface is invoked.

The1,142 original cases cover every unsigned route byte under06/86/46/C6,84 cached-object compositions and formatting/checksum boundaries. They show why the strict inspector remains separate from original contextual handling:

* Original06/86 parsing uses the incoming count directly. The other two tested headers do not enter that constructor branch; counts7..255 remain stored without a supported route projection.
* Original bridge and `dl`-marked unit caches can rewrite text and change the network object. A later missing bridge can retain a previously reached context; repeated `dl` handling can remove a payload byte. Those contextual rewrites are not wire bytes and are excluded here.
* Original construction does not validate CAL payloads. Its checksum functions also admit some signed/Unicode/odd-tail forms excluded by this strict profile. Bad-checksum cases use the unchanged private validator to avoid original error-logging paths; valid-domain public checksum calls are separately recorded.

Fresh-original tests require the existing explicit `CBUS_CGATE_JAVA`, `CBUS_CGATE_JAVAC` and `CBUS_LOCAL_CGATE_VENDOR` paths on macOS. They use the pinned JAR and observed Java11 runtime, an isolated process with network denied, and a new owned output directory. `CBUS_PCI_INCOMING_REPORT_DIR` optionally chooses the report parent; it is an output override, not a device/backend selector. Other platforms need separately evidenced original-process isolation before a native parity claim.

The offline CLI is `cbus-toolkit pci-route receive WIRE_HEX`, where `WIRE_HEX` encodes the complete ASCII frame, including its checksum and CR. For example, `3836313431303032313530343831303442360D` encodes the captured original frame `8614100215048104B6\r`. There is no checksum toggle or transport option. The [routing usage guide](pci-routing.md#received-addressed-frames) explains its output and exit codes.

[Focused acceptance](../research/fixtures/pci-incoming-acceptance.json) records 45 tests per interpreter: 11 strict incoming tests, one fresh 1,142-case original process, 11 existing outgoing codec tests, five outgoing CLI tests, five incoming CLI tests and 12 existing CAL/frame tests. This is current-source focused acceptance on macOS, separate from installed-wheel or physical transport acceptance. The full original contextual behavior and the public strict subset remain distinct.
