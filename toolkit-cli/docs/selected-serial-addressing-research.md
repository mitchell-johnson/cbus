# Selected-serial addressing: protocol research and proposed API

The CAL serial-address broadcast can select one serial and an explicit target.
The native `NET UNRAVELUNIT` command cannot constrain an operation to that pair:
it selects and processes serials itself, and can fall back to a different free
address. No production selected-serial mutation API is enabled by this research.
The production duplicate simulator remains read-only.

## Exact native paths

Original `co.class`, method `a(cn,int)`, builds:

```text
05 FF 00 0F 00 <four-byte packed serial> <destination> <inner checksum>
```

The serial is `(first_decimal_part << 12) | second_decimal_part`, in big-endian
byte order. The inner checksum makes the sum from the `00` immediately after
`0F` through the checksum zero modulo256. The native SMART PCI request has a
leading backslash and trailing confirmation letter; SRCHK, if explicitly
enabled, requires a separate outer packet checksum.

For serial101136.1558 and target6, the native request is
`\05FF000F0018B106160615`. For serial101136.1559 and target7, it is
`\05FF000F0018B106170713`. Both were emitted by the original C-Gate against an
isolated duplicate-address fixture.

`co.a(String)` requires CAL opcode87 and the matching `00` plus four serial
bytes. With an incoming86 header, it records the reply's source address. It
does not require that source to equal the requested destination. With a bare
CAL reply, the source is unknown and Unraveller assumes the requested target.
The two remaining CAL data bytes are not checked. Both `0000` and `FACE`
fixture tails were accepted; their hardware meanings remain unknown.

`CBusNetworkUnraveller.a(UnitUnravelStack,bP,...)` chooses the `co` branch when
the source has multiple known serials. The normal singleton branch uses
`dc/dd/cu` unlock and protected STORE. After a successful `co`, its private
`a(int,int)` updates the runtime model; it does not issue an address STORE.
The complete successful split trace confirms that distinction.

Before each database target is used, the native code probes it with
`\46<target>001120`; an empty fixture target returns only PCI confirmation.
Native also disables then restores local PCI Local SAL around broadcasts:
`A3429705` and `A3429707`, acknowledged by `324297`. Exact
`CBus2PCILocalable.a(aX,boolean)` chooses parameter66 values5/7;
`CBusBaseUnit.c(aX,int,int)` uses STORE tag151. These are local interface
setting writes, separate from the selected unit's address.

`kY.class` accepts source addresses and optional MATCHDB, with no serial or
destination argument. Source search finds `co` instantiated inside Unraveller,
with no independent command route. Wired `co` uses one command attempt with
zero command retries; its caller performs an independent destination serial
read after a missing/unmatched response. Later Unraveller fallback can still
issue a different protected address write.

## Native fault observations

The [durable report](native-duplicate-unravel-research.json) contains exact
class hashes, native replies, literal wire exchanges, post-refresh records,
fixture states and raw-artifact hashes for nine unique disposable projects.
Each uses AutoUnravel=no, AutoUpdate=no and Retries=0. A is serial101136.1558,
whose database target is6; B is serial101136.1559, whose target is7. B was
processed first in these runs. The order is native enumeration, not a promised
API ordering.

| Case | Native result concerning A | Observed A address | Address STORE |
| --- | --- | --- | --- |
| Normal MATCHDB | Reports6 | 6 | None |
| Move, omit co reply | Reads destination serial, reports6 | 6 | None |
| Move, reply contains another serial | Reads destination serial, reports6 | 6 | None |
| Move to6, reply source is9 | Reports9 despite no unit at9 | 6 | None |
| Reply says6, no move | Reports6 despite no unit at6 | 255 | None |
| Bare matching reply, no move | Assumes6 despite no unit at6 | 255 | None |
| No move and no reply | Falls back to a free address | 2 | `A3204E025A` from255 |
| UNRAVELUNIT without MATCHDB | Selects free addresses itself | 3, with B at2 | None |
| Matching reply with opaque tailFACE | Reports6 | 6 | None |

Every native command returned200. Each case sent one `co` per serial;
the failed-move case then sent one additional protected STORE. Database XML
and unrelated node fields remained unchanged, and final traces contained no
unsupported simulator commands. Passing research checks means the recorded
behavior was observed; it does not mean the requested target was reached.

A separate, exclusively owned TCP fixture exchange sent only A's broadcast,
then independently read A at6 and B still at255. It restored the original
local PCI setting. This proves selected delivery within the explicit fixture,
without supplying a production transport or a hardware safety claim.

The research fork deliberately changes only its bus address for `co`, leaving
parameter32 unchanged, to reveal whether native C-Gate sends a later address
STORE. Thus the absence of a later STORE **does not establish EEPROM
persistence**: real firmware could persist the address inside `co`. No
power-cycle, persistent duplicate-node loader, or firmware-level persistence
behavior has been verified.

## Proposed separate collector and transport API

The first implementation should add read-only collection before enabling the
write transaction. Existing `PCIClient.identify()` stops at its first matching
reply and cannot establish duplicate absence.

Proposed names, not current exports:

```python
with SerialPCITransport(exclusively_owned_transport, expected_local_pci=...) as transport:
    observation = transport.collect_serials(address=255)
    inventory = transport.discover_serials()

# A later, separately validated layer:
plan = SelectedSerialAddressing(transport).plan(
    source=255, serial="101136.1558", destination=6)
attempt = SelectedSerialAddressing(transport).apply(plan)
result = SelectedSerialAddressing(transport).verify(plan)
```

`SerialObservation` should retain address, request/confirmation, every matched
raw frame, canonical known serials, malformed/unknown/conflicting records,
start/end times, response counts and why collection ended. Inventory must
retain multiple physical identities at one address. Unknown or mixed unit
profiles must remain ambiguous rather than pairing a serial with guessed
type/firmware metadata.

The native timing model is a **quiet interval**, not simply two seconds from
request transmission. `cT` sets timeout2000ms and requests up to the base
response limit7. Original `aW.a(cj,boolean)` updates response timestampN after
each accepted reply; `aW.K()` measures elapsed time from N, or send timestampE
if no reply has arrived. Original bytecode confirms these assignments and
comparisons.

The collector proposal is therefore:

1. One outstanding request under a transport lock; no request replay. Require
   a valid matching PCI confirmation and fully framed checksummed replies.
2. Collect all matching IDENTIFY4 responses for a two-second quiet interval
   after the last matching response. Correlate source, local PCI destination,
   normal route and attribute4. Retain unrelated traffic separately.
3. Add a hard total deadline, proposed10s, and a bounded frame count. Reaching
   either bound reports an incomplete observation, never complete absence.
   Repeated identical responses count toward the bound even when serials are
   deduplicated in the result. Truncated framing, transport loss, malformed
   serial data or conflicting identities prevents mutation.
4. Discover all three install-MMI blocks and all observed addresses, including
   duplicates at255. Recheck the address set before planning and application.
   Collection completion describes the documented observation window; it is
   not proof against arbitrarily late or missing physical bus responses.

Acceptance must include delayed second serials, fragmented/interleaved input,
matching frames around the quiet-window boundary, missing/rejected PCI
confirmation, pre-confirmation/late frames, repeated-frame saturation,
checksum failures, partial CALs and disconnects. Late traffic must not be
silently attributed to the next request.

The future write plan must bind the exact selected known serial at255, all
other discovered serials/addresses, a separately observed empty destination,
the supported homogeneous source profile, the local interface identity and
settings, and explicit transport ownership. C-Gate and other software must
not share that PCI stream. An advisory process lock alone cannot establish
exclusive physical interface ownership.

A later `apply` should refresh and compare that full plan, preserve or
explicitly manage native-required Local SAL settings, send exactly one `co`
for the selected serial/target, and record the acknowledgement as evidence
only. Independent discovery must then show the selected serial solely at the
target, the unselected duplicate still at255, unchanged identities elsewhere,
and the original local interface settings. Any lost/contradictory reply,
incomplete discovery or settings-restoration failure produces an uncertain
result and a recoverable evidence document, without replay or automatic
fallback. `verify` only observes through a newly valid exclusive transport.

The collector timing model, interface-ownership lifecycle, Local SAL recovery,
complete before/after comparison, and durable per-serial simulator topology
must be accepted and tested before this mutation path is enabled.
