# Native MMI coverage and physical address guards

The exact C-Gate 3.4 `NET CHECKUNIT` implementation can classify an occupied
address as absent when its MMI response contains a missing range replaced by
a repeated valid block. Explicitly selecting the address does not compensate:
the native checker schedules an IDENTIFY serial read only for addresses found
in its MMI map. Network synchronization uses the same discovery reader.

The current physical readdressing and serial commissioning helpers require a
separate successful `NET PINGU` immediately before the address write and during
verification. That command uses a different native reader with full coverage
validation. Raw commands and the existing read-only `NativeSerials.refresh`
report preserve native behavior; their successful completion alone does not
prove independently validated full MMI coverage.

## Exact reader distinction

The original case-sensitive class hashes and method offsets are in
[mmi-coverage-source-evidence.json](mmi-coverage-source-evidence.json).

| Native operation | Reader and behavior |
| --- | --- |
| CHECKUNIT, including selected addresses | `r` → `dw` → `cY/cs` → `dx`; checks at least three valid lines, but missing states remain zero without a coverage mask. |
| Network sync discovery | `nb` → `CBusBaseNetwork.a` → `r/dw`; another sync path also directly uses `dw`. |
| PINGU | `kO` → `dk/cs` → `dn`; rejects unexpected offsets and missing lines, then requires every address to have been filled. |
| CHECK_UNRAVEL | Obsolete command; returns 400 without running its older implementation. |

The request is `\05FF00FAFF00` followed by the PCI confirmation character and
CR. The conventional standard response consists of D8FF00, D8FF58 and D6FFB0
frames covering addresses 0–87, 88–175 and 176–255 respectively. Each payload byte
contains four states, starting with its least significant two bits. State 0 is
absent, states 1 and 2 are present, and state 3 carries the native error flag.
The distinct meanings of 1 and 2 have not been established by this audit.

There is no separate final marker: the block offset and length establish the
end of coverage. Whole-frame checksums use eight-bit two's complement. Native
MMI timeout is the network's ResponseDelay value, observed as 5500ms in the
oracle. It is configurable; the Java field's initial 3000ms is not a fixed
operational timeout. PINGU explicitly requests zero command retries.

## Reproduced failures and mitigation

Read-only native probes produced these results with the network healthy and
Retries=0 read back after startup:

| Injected MMI response | CHECKUNIT result | PINGU result |
| --- | --- | --- |
| Complete three blocks | Present and duplicate addresses found | Full address list |
| First block repeated instead of middle | Accepted; missing range treated as zero | 408 unexpected block offset |
| Middle repeated instead of final | Occupied 255 omitted; explicit 255 classified absent with no IDENTIFY | 408 unexpected block offset |
| Complete all-zero blocks | 200 with no units | 302 Units=null plus 200 |
| PCI confirmation only | 408 after response timeout | 408, insufficient response lines |

The [typed guard regression](native-mmi-address-guard-acceptance.json) uses a
move within the supported bounds: source 4 and an explicitly identified occupied
target 100. After initial native discovery, the fixture adds the target and
supplies three literal, valid-checksum MMI frames with the middle range omitted.
CHECKUNIT 4,100 reports target 100 absent without sending IDENTIFY to 100. The
helper subsequently reaches PINGU, which rejects the range gap. No scalar SET,
address unlock or address STORE is attempted; complete fixture state and
database XML remain unchanged.

The typed guard requires exactly `302-Units=<ascending unique decimal list>`
followed by `200 OK.`. The nonempty list must equal every address in the healthy
cached identity fingerprint; the source must be present and target absent.
This also rejects a complete all-zero response in the nonempty address workflow.
The local PCI is covered when it is present in that healthy fingerprint; the
guard does not independently bind a local hardware identity beyond the existing
interface and cached-identity checks. A failed coverage observation after a
write produces an uncertain outcome and never causes a replay.

This establishes coverage of the protocol response and agreement between the
native readers. It does not establish atomicity against another bus controller
or guarantee that every physical device will answer an MMI request. Earlier
wheel checkpoints that predate the PINGU guard retain the reproduced
missing-range limitation. They are not retroactively validated by newer tests.
