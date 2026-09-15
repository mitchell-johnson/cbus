# Bounded PCI simulator and native C-Gate acceptance

The simulator has three explicit profiles. `raw` is an arbitrary persistent
parameter-block peer. `captured` adds the programming memory transport observed
for KEYGL5. `synthetic` is the SIMTEST fixture: captured types/firmware plus
deliberately chosen state at independently verified locations. None claims full
EEPROM, firmware flashing, bridge or Toolkit parity. A separate explicit KEY4
fixture exercises native PP field transfers with the limitations below.

The independent socket peer never imports `pci` codecs. Unknown operations,
unmapped memory, truncated requests and invalid checksums receive failure;
writes never create unknown memory implicitly. A failed persistence operation
rolls back the memory bytes and selector. The selector is volatile; EEPROM bytes
are persisted atomically. Generic block semantics remain separate from the OEM
programming address space.

## Evidence

Java references below are exact case-sensitive members of
`vendor/cgate-decompiled.tar`, derived from the supplied C-Gate 3.4.0 JAR. On a
case-insensitive filesystem, use `tarfile.extractfile('./name.java')`: extracting
all members overwrites unrelated Java classes with names differing only by case.

* `cc.h` issues `@1A2001` and reads a one-byte BASIC REPLY for parameter0x20.
  The observed attached-unit16 reply is `8220104E`. Fresh TCP does not prove
  the PCI's retained destination; PCIClient discovers locally, then explicitly
  addresses every `unit=None` operation. Monitored addressed traffic cannot
  establish this local identity.
* `cl` removes a repeated transmit header. The peer retains the exact direct or
  programming routing header for compressed commands. `@` bypasses that context.
* `aV.a` selects an OEM address with WRITE parameter0, tag0x41, and 2..4
  little-endian address bytes. `aU`/`bj` RECALL parameter1; `bD` assembles
  repeated-parameter replies to the exact requested byte count. `lP` maps OEM
  logical offsets at or above256 to physical offset `logical-256`; the legacy
  path below256 is separate.
* Proxy packets7044–7046 show selection of physical16 followed by RECALL2 and
  bytes38FF. Programming ACKs are `8605100100320041F1` and
  `8605100100320142EF`. ParameterFA returns44bytes in16/16/12 fragments;
  parameterFB returns `01.05.00` and a NUL. Tests preserve literal frames.
* `cs`, `dk` and `dn` implement standard MMI: D8/D8/D6 blocks at offsets0/88/176
  carry256 two-bit states, least significant pair first. Install applicationFF
  uses positive state for presence. Captured units4/5/16 have states2/2/1.
* `CBusLightingApplication` parses the same standard MMI for application38;
  state2 maps a known group to OFF. The SIMTEST groups12/24/25/27/33 come from
  unit4's captured group block and the eDLT's captured FA widget/application
  pairs. This fixture chooses all five OFF, with zero for other groups.
* KEYE.xml and KEYGL5.xml specify Project and UnitName as sixbit strings at
  0x23 and0x2A. SIMTEST uses `memory.encode_sixbit` for projectSIMTEST and
  namesSIMKEY1/SIMEDLT. `CBus2InputUnit.s` reads IDENTIFY8 terminal levels;
  native KEYE1 scan requests nine groups, and the fixture chooses nine OFF
  levels. `CBusUnit.g` polls its configured change byte, initially0xF2; the
  fixture chooses FF, matching the native initial value. No checksum algorithm
  or checksum meaning is inferred from that byte.
* `ch` and `aW` recognize `g#` as failed confirmation. `g!` is unsuitable:
  native C-Gate assumes the code was confirmed and parses `!` as PCI busy.
  Simulator negative confirmations therefore use `#`; rejection reasons are
  recorded independently in its wire log.
* The official [Clipsal CBUS-QS issue 2.0, section 4.2](https://ckm-content.se.com/ckmContent/sfc/servlet.shepherd/document/download/0698V00000kHfpkQAC)
  distinguishes `#` (retries exhausted), `$` (corrupt command checksum), and
  `%` (lost network clock). The PCI decoder recognizes all three and closes a
  failed request without retrying. The simulator emits `$` for an invalid
  checksum when outgoing checksums are configured. These are wire checksums;
  this guide does not establish the device EEPROM checksum algorithm.

## Reproducible acceptance

Run from the repository root with the isolated `cbus-toolkit-oracle` Docker
container listening on loopback20023:

```sh
PYTHONPATH=toolkit-cli/src python3 toolkit-cli/research/verify_network.py --duration 25
```

The runner verifies the disposable container's exact research-state mount and
loopback port. It creates one uniquely marked8-character project and a CNI
network pointing only to its short-lived simulator via `host.docker.internal`.
It never adopts or opens other projects or hardware networks. It closes and
deletes the disposable project and writes a JSON report plus exact wire log.

The native run PCIC87D1 on2026-09-14 returned `State=ok`,
`InterfaceState=running`, and unit4 KEYE1, unit5 KEYGL5 and unit16 PC_CNIED all
`state=ok`, with129 wire records and no unsupported requests. The extended
runner closed the native fixture network and verified a PCIClient
programming WRITE against immediate RECALL and a second server loaded from
disk (38FF → 39FF), then restored the original38FF. That test is explicitly raw PCI
programming transport; it is not native PP SAVE or a hardware flash test.

`acceptance_status=passed` requires the healthy network, all three expected
units stateok, successful write/read/reload/restore, no unsupported requests
and clean project cleanup. Otherwise the runner reports `incomplete` and exits
nonzero. This status covers only the stated fixture workflow.

## Native KEY4 field transfer and outstanding checksum behavior

```sh
PYTHONPATH=toolkit-cli/src python3 toolkit-cli/research/verify_network.py --fixture key4 --duration 10
```

`fixtures/key4-synthetic.json` contains only explicitly selected, schema-backed
legacy memory bytes. Unmapped addresses stay absent. The runner adds a chosen
change byte and explicit status blocks, and supplies a writable-address list;
that list is a fixture constraint, not an emulation of device protection.
Native `bp` supplies the READ-status opcode `2A`; it reads these status blocks
separately from EEPROM. Native `ct` supplies tagged direct STORE, and the peer
echoes the parameter and transaction tag in ACK. It never changes reserved
bytes or invents a checksum update to make SAVE succeed.

Run PCIA6480 on 2026-09-14 reached network `State=ok`, interface `running`, and
unit4 KEY4/unit16 PC_CNIED `state=ok`, with 87 wire records and no unsupported
requests. Real C-Gate PP LOAD/GET/SET/SAVE_TO_SOURCE changed UnitName from the
chosen fixture name to PPWRITE. An independent PCI RECALL returned the literal
six-bit vector `BEFDB1A3391E`, a fresh PP LOAD read the changed name, and a
second SAVE restored the original. Independent socket read and a new server
loaded from disk both confirmed restoration.

The runner separately reads EEPROMChecksumActive/EEPROMChecksum at 0x1E/0x1F
before and after. Both remain the explicit fixture value FFFF. It reports
`checksum_mutation_verified=false` and `acceptance_status=incomplete`, with a
nonzero exit status, because this does not prove device firmware behavior.

The bounded checksum/protection investigation established:

* I_KEY.xml declares checksum-active at 0x1E with protection `none`, checksum
  at 0x1F with protection `checksum`, and UnitAddress at 0x20 as `special`.
* Exact `lP.java` lines 1180–1229 route protection `none` and `checksum`
  through the same `ct` STORE. The tag is a transaction index, not a checksum.
  Protection `lock` first issues `dd` UNLOCK (`11` plus parameter), expecting
  a one-byte REPLY, then STORE. Factory/special fields are skipped by the normal
  native save path. Unlock expiry, allowed memory ranges and firmware checksum
  mutation are not established; the simulator rejects unsupported unlocks.
* The native UnitName SAVE sends the field STORE and waits for its ACK; it
  does not send an EEPROM checksum update. No exact 0x1E/0x1F RECALL or STORE
  was found in the 950 parsed packets in the repository proxy capture.
* Toolkit's MAP-backed base `GetCRCParameterName` at image address 0xCBD5B8
  returns an empty string; `ExcludeParameterFromCRC` tests OID, SerialNo and
  FirmwareVersion. The MAP lists overrides for other unit families, not KEY4.
  Those methods therefore do not establish a KEY4 EEPROM checksum algorithm.

The next requirement is independent device firmware/protocol evidence for
the EEPROM checksum algorithm and protected-write lifecycle. The simulator
does not claim complete PP programming until that requirement is met.

## Independent application receiver

Synthetic SAL dispatch supports the independent label receiver for
applications 56, 202 and 203. Literal native packets establish text, Unicode,
icon and dynamic bitmap uploads. Incomplete Unicode or dynamic uploads do not
become labels; failed persistence rolls back committed state. No incoming echo
or physical display behavior is invented. Socket tests additionally exercise
compressed routing headers, fragmented confirmations, malformed packets and
state reload after restart.

Native label run LBLC6336 recorded 67 command records and 183 wire records,
with nine committed labels, one language selection, matching persisted state
and no rejected wire commands. Native C-Gate can return 200 even when its PCI
peer rejects a label packet, so this acceptance checks receiver state and disk
reload as well as native responses. The oracle rejected ENABLE_UNICODE with
400; that separate operation remains an explicit native limitation.

Trigger Control uses the separate independent TriggerState receiver for
EVENT (`02 group selector`), INDICATORKILL (`09 group`), MIN (`01 group`) and
MAX (`79 group`). The whole chain validates before mutation; every accepted
event persists separately, including repeated identical selectors. This
receiver is restricted to application 202 in the synthetic profile. Native
receive/echo behavior and physical actuation require their own evidence.

## Lighting control and deterministic timing

The independent `lighting_state.py` receiver supports ON79, OFF01, the 16
RAMP codes and TERMINATERAMP09. Public [CBUS-QS sections 6–8](https://ckm-content.se.com/ckmContent/sfc/servlet.shepherd/document/download/0698V00000kHfpkQAC)
establish the command bytes, full-scale ramp durations and binary MMI states.
Native `CBusLightingApplication` additionally parses opcode09 as ramp
termination. The state interpolates continuously, with duration proportional
to the level difference; a replacement ramp starts from the current level.
It does not reproduce a particular dimmer's PWM quantization. The clock is
injectable, so tests cover every rate and exact intermediate/stop behavior
without waiting up to 17 minutes.

Only explicitly configured application/group pairs accept commands. Default
SIMTEST membership remains groups12/24/25/27/33, initialized OFF. MMI now
reports state1 for nonzero modeled levels and state2 for zero. Entire SAL
chains validate before mutation, and failed persistence rolls back state.
Snapshots store current level, target and remaining duration; a loaded
snapshot resumes from saved progress. That paused-time convention belongs
to the simulator and does not claim hardware power-loss semantics.

```sh
CBUS_CGATE_TEST_HOST=127.0.0.1 CBUS_CGATE_TEST_PORT=20023 \
  PYTHONPATH=toolkit-cli/src python3 -m unittest discover \
  -s toolkit-cli/tests -p test_lighting_native.py -q
```

Native run LGT74A56 on 2026-09-14 passed six CLI operations: ON, OFF, instant
level127, OFF, full-scale4-second ramp, then TERMINATERAMP. The independent
peer observed exact native payloads, retained a nonterminal stopped level,
and restored that level from disk in a fresh peer. C-Gate's cached GET
eventually reflected ON; its command response can precede that update.
The native transcript contains121 wire records, zero unsupported requests
and clean project cleanup. Only the first SAL includes the routing header;
the remaining five use C-Gate's compressed form. No fabricated incoming echo
was needed. Extended status, learn mode and physical dimmer behavior are
outside this acceptance.

The same test module also persists nonzero levels through real socket SAL
commands, restarts the simulator, then opens an entirely new native project.
Synthetic KEYE1 uses two explicitly configured group slots12/24 at 0x50/0x51.
Exact `CBus2InputUnit.s` maps IDENTIFY8 index to the corresponding configured
group; the synthetic KEY4/KEYE1 responder now derives those bytes from saved
lighting state. Missing legacy slots preserve their indices. The continuous
test level is truncated for this byte-valued protocol response, without a
claim about hardware PWM quantization.

Fresh native scan LGR4B799 recovered levels127/64 with network `state=ok`,
109 wire records, no unsupported requests and clean cleanup. Both native
lighting tests passed together after this change. The eDLT-only variant of
the probe exposed a native limitation: C-Gate requested only binary FA MMI,
which reports presence/ON/OFF, and did not query the exact nonzero level.
That variant's exact level remained0 in the native cache. No unsolicited
response or guessed extended-status behavior was added to conceal it.
