# C-Gate and Toolkit compatibility reference

## Physical service in cmqttd

Use cmqttd's embedded listener for supported real-network operations. It shares
the CNI with MQTT; do not open a competing direct PCI connection or fall back to
Windows for live eDLT static-label reads. Read `docs/cmqttd-cgate.md` for the
current supported operations and remaining C-Gate replacement work. Query
`CMQTT CAPABILITIES` before assuming an operation is implemented. Physical reads:

```sh
cbus-toolkit cgate --host 127.0.0.1 --timeout 120 edlt-labels --network //PROJECT/254
cbus-toolkit cgate --host 127.0.0.1 --timeout 30 edlt-labels //PROJECT/254/p/UNIT
```

Treat the shared PCI generation as the ownership boundary for volatile C-Gate
results. Guarded physical commands capture the generation and client before
I/O, then hold the generation commit guard through their cache mutation,
invalidation, or success event. If reconnect wins after confirmation but before
that commit, the command returns 408 and leaves replacement-generation physical,
level, application, and dynamic-label observations unchanged. This applies to
lighting and scene invalidation, Trigger/Enable/clock/temperature echoes,
dynamic-label append and clear, FactoryDefault label invalidation,
project-identity changes, discovery, and the final UNRAVELUNIT snapshot/events.

Use the configured endpoint and project address. The network form runs one
whole-network serial refresh (`NET SYNC` plus `NET CHECKUNIT`), reports every
fresh record and reads exact KEYGL5 5.5.00 devices in numeric address order.
Unsupported firmware, unknown or ambiguous identities and per-device failures
remain in the JSON beside successful reads. The physical configurations are
sequential rather than an atomic network snapshot. Physical IDENTIFY4 reads
bracket each selected memory snapshot. The fresh inventory identity is attached
only when both physical serials match it; a mismatch remains a per-unit error
without stale identity attachment. An incomplete report is still emitted and
the command exits nonzero.
Treat a wildcard MMI candidate with a `No units detected` CHECKUNIT result as
an unresolved identity, not proof of physical absence. The network inventory
must remain incomplete while preserving successful eDLT snapshots.

Each successful device read returns physical identity, all 64 static strings
and their widget, page and scene references, a stable-header check and CRC
evidence. The network form then requests `CMQTT LABELS` exactly once at network
scope. Its bounded current-connection SAL observations remain top-level,
network-wide, transient and recipient-unverified; they are never assigned to a
device. A unit-shaped `CMQTT LABELS` request is only a compatibility alias for
the same network ring. The nested observation document's `complete: false` and
`device_readback: false` distinguish it from an inventory of a display's
pre-existing cache. `CMQTT LABELS`, `UNIT READMEM` and `UNIT IDENTIFY` are
cmqttd extensions.
A 502 response is a missing backend or failed device operation; never replace
it with saved project data and describe that as a live result.

### PORT discovery and probe commands

cmqttd implements every maintained C-Gate 3.4 `PORT` path:

```text
PORT
PORT LIST
PORT IFLIST
PORT CNISCAN [DESTINATION] [FAST]
PORT CNISCAN2 [INTERFACE] [DESTINATION] [FAST]
PORT PROBE serial|socket|cni|wiser|etherlite ADDRESS
PORT REFRESH
```

Use `PORT LIST` for host serial devices and `PORT IFLIST` for non-loopback
host addresses. `CNISCAN` sends native legacy discovery from UDP 30718 for
three seconds. Without `FAST`, it also attempts a three-second connection to
each advertised port. `CNISCAN2` first performs that legacy scan, then sends
the C-Gate 3.4 CCP read query from UDP 20050 and listens for five seconds. It
reports type, connected status, MAC, padded serial and C-Bus unit address.
Allow at least 10 seconds in a CLI timeout. C-Gate consumes one optional token
after the destination even when it is not `FAST`; a matched `FAST` also
consumes and ignores one following token. cmqttd preserves those parser quirks.

`PORT PROBE` never borrows the shared MQTT PCI. It refuses the configured
cmqttd endpoint with 431, opens a temporary transport, sends DC1+CR, drains,
then requires the six-byte `@2104` echo and returns the filtered serial reply
available after 500 ms. A serial probe configures 9600 8N1, software flow
control, DTR/RTS and performs the retained six-rate PCI baud-detection sequence.
EtherLite first establishes and configures the FAS serial channel. A 230 proves
the native exchange completed; 408 covers
address, type, connection, no-echo, or local port-library failure. Native build
2001 returns 408 for `PORT REFRESH` because serial enumeration is automatically
updated; that is the implemented behavior, despite the older manual's 200
success text.

With `--cgate-auth-file`, `CNISCAN`, `CNISCAN2`, `PROBE`, and `REFRESH` require
LOGIN. Help, LIST, and IFLIST remain open. Discovery can emit broadcast and
probe opens the named endpoint, so use explicit destinations when operating in
an environment where broadcast is inappropriate. Exact evidence is in
`rust/testdata/fixtures/native_cgate_port.json` and
`rust/testdata/vectors/cni_discovery.jsonl`.

### CONFIG commands

cmqttd implements all nine maintained C-Gate 3.4 CONFIG paths. Use the exact
parent command to inspect native-shaped help:

```text
CONFIG
CONFIG GET NAME|*
CONFIG INFO NAME|*
CONFIG SET NAME [VALUE]
CONFIG OBGET OBJECT NAME|*
CONFIG OBSET OBJECT NAME [VALUE]
CONFIG OBRESET OBJECT [NAME]
CONFIG LOAD global|project|all [FILENAME]
CONFIG SAVE global|project|all [FILENAME]
```

The catalogue has 148 registered names. INFO exposes metadata for 142; six
`secure.*` registrations are obsolete and return 408. `GET *` returns the 122
native-listed entries in retained order. Verbs are case-insensitive and
parameter names are case-sensitive. SET and OBSET preserve the dequoted
remaining value, including blank and multiword values. GET and INFO ignore
trailing words, matching the retained server.

Legacy GET/SET resolve global defaults and the selected project's overrides.
Object forms accept literal lowercase `global`, the selected `project`, a
project path, or a network path. Project and network values inherit upward;
resetting a project parameter also removes descendant network overrides.
`OBGET` for a parameter unavailable at that object is a deliberate cmqttd
liveness repair: native 3.4 accepts the command and never sends a response,
while cmqttd returns 408 so clients do not hang.

CONFIG state is command compatibility data in cmqttd's atomic JSON repository.
`LOAD` and `SAVE` retain native response ordering but use bounded internal
snapshots; a supplied filename is only an identity and is never opened on the
host. These values do not reconfigure cmqttd's listener, PCI, MQTT, loggers, or
other runtime settings. With the optional LOGIN gate armed, SET, LOAD, SAVE,
OBSET and OBRESET require authentication; help, GET, INFO and OBGET remain
open. CONFIG performs no PCI I/O and must not be described as physical C-Bus
state.

`CMQTT CAPABILITIES` publishes the exact command list, catalogue/wildcard
counts, `config_persistence="cmqttd-json"`,
`config_runtime_reconfiguration=false`, and the OBGET repair flag. Ground
native claims in
[`native_cgate_config.json`](../../../../rust/testdata/fixtures/native_cgate_config.json).
The real-daemon `system_cgate_config.rs` regression checks TCP framing, LOGIN,
scope/snapshot durability across restart, zero CONFIG PCI frames and MQTT
continuity. The fixture's oracle was the pinned C-Gate 3.4.0.2001 jar in a
disposable loopback-only Java container with no C-Bus endpoint.

### ACCESS and LOGIN commands

cmqttd implements all five maintained C-Gate 3.4 ACCESS paths and native
session-level authentication:

```text
LOGIN
LOGIN USERNAME PASSWORD
LOGOUT
ACCESS
ACCESS ADD user USERNAME PASSWORD LEVEL
ACCESS ADD interface ADDRESS LEVEL
ACCESS ADD remote ADDRESS LEVEL
ACCESS LIST
ACCESS DELETE LINE
ACCESS SAVE [SNAPSHOT]
ACCESS LOAD [SNAPSHOT]
```

`LOGIN` reports status 210. A matching user row returns status 211 and the
row's ordered level; credentials and usernames are case-sensitive, duplicate
rows are allowed, and the first matching user wins. `LOGOUT` re-evaluates the
connection's interface/remote rows. The ACCESS family itself requires Clipsal
or Max. LIST emits status-135 rows in insertion order, filters out rows above
the current level, and DELETE uses the resulting 1-based visible line number.

Native C-Gate exposes passwords in LIST and its saved file. cmqttd stores only
a one-way digest and renders `user NAME <redacted> LEVEL`; do not expect to
recover a credential. SAVE/LOAD operate on named snapshots in the atomic
`cmqttd-json` repository. Names with separators, traversal, `~`, or `:` are
rejected, and a missing snapshot returns 408 without replacing the active
list. This differs intentionally from native C-Gate, whose missing LOAD resets
the list and whose LOAD accepts traversal. cmqttd validates hostnames before
insertion, so the native unresolved-address row/connection-poisoning defect is
not reproduced. Fresh and pre-ACCESS repositories admit non-loopback peers at
Clipsal so Docker-published Toolkit connections remain compatible. Adding,
deleting, or loading interface/remote policy makes address admission explicit;
an unmatched non-loopback peer then receives native 421. When the independent
recovery token is configured, that peer instead receives a restricted session:
`LOGIN` can report None and `LOGIN TOKEN` can unlock it, while every command
other than `LOGOUT` returns 420. A loopback Clipsal recovery path remains available.
The ACCESS family's Clipsal/Max boundary is enforced, but the exact native
per-handler level table for unrelated commands is not. Check
`access_global_command_level_matrix=false` before relying on role separation
outside ACCESS and the optional mutation gate.

When `--cgate-auth-file` is configured, `LOGIN TOKEN` remains the operator
recovery form and returns 200. ADD, DELETE, LOAD and SAVE require that token or
a Clipsal/Max ACCESS-user login; LIST remains available to a Clipsal/Max
session. In this mode LOGOUT retains
the established 200 response. Never put a site password or recovery token in
logs, documentation, issue text, or test fixtures.

`CMQTT CAPABILITIES` publishes the five `access_commands`,
`access_persistence="cmqttd-json"`, `access_host_filesystem=false`, and flags
for password redaction, connection admission, unresolved-address repair,
loopback recovery, compatibility-bootstrap/explicit admission, token-only
recovery admission, and the global command-level boundary.
Ground native behavior and the deliberate differences in
[`native_cgate_access.json`](../../../../rust/testdata/fixtures/native_cgate_access.json).
The real-daemon `system_cgate_access.rs` regression covers authentication,
role filtering, durable snapshot/restart behavior, redaction, path/missing
errors, a healthy second connection after failed resolution, and zero PCI
traffic.

### FILE commands

cmqttd implements all seven maintained C-Gate 3.4 FILE paths over a durable,
sandboxed virtual root:

```text
FILE
FILE DIR [DIRECTORY]
FILE LS [DIRECTORY]
FILE MKDIR DIRECTORY
FILE DELETE PATH
FILE SHA256 PATH [PATH ...]
FILE DOWNLOAD PATH
FILE UPLOAD PATH << DELIMITER
BASE64 DATA
DELIMITER
```

`FILE` returns the exact nine-line native help. DIR and LS are aliases: a
directory header is status 304 and each child row is status 305. SHA256 accepts
multiple files and emits one status-302 digest row per path. DOWNLOAD uses the
native status-345 start, status-347 base64 rows and status-346 completion
envelope, with 76 base64 characters per data row. UPLOAD consumes a native
here-document and rejects missing or invalid base64 without desynchronizing the
connection. Replacing a file preserves the previous bytes as `PATH.0`, replacing
any older backup. MKDIR creates parent directories; DELETE removes files and
empty directories and rejects non-empty directories.

Ordinary paths are relative and reject leading `/` or `\\`, `~`, `..`, and `:`.
Contents, directories and modification times persist atomically in
`--cgate-state`; they never open an arbitrary host path. `%PROJECT%/...`
accepts its separator after a known project token and addresses a separate
virtual project namespace; it does not denote a Schneider project or archive
file.
With LOGIN armed, UPLOAD, DELETE and MKDIR require authentication; FILE help,
DIR/LS, SHA256 and DOWNLOAD remain open. FILE performs no PCI I/O.

`CMQTT CAPABILITIES` publishes the seven `file_commands`,
`file_storage="cmqttd-json"`,
`file_binary_transfer="base64-here-document-and-345-347-346-envelope"`, and
`file_host_filesystem=false`. Ground native behavior in
[`native_cgate_file.json`](../../../../rust/testdata/fixtures/native_cgate_file.json).
The real-daemon `system_cgate_file.rs` regression covers TCP framing, binary
round-trip, SHA256, listings, replacement backup, path/base64 errors, LOGIN,
restart durability, zero PCI traffic and MQTT continuity. The native oracle
was a disposable loopback-only C-Gate 3.4.0.2001 process with no C-Bus endpoint.

### AIRCON/HVAC commands

cmqttd implements every AIRCON subcommand registered by C-Gate 3.4 for its
configured direct network. Inspect native-shaped help with `AIRCON ?`. The
application target must resolve to application 172 (`$AC`), using either
`NETWORK/APPLICATION` or `//PROJECT/NETWORK/APPLICATION` form:

```text
AIRCON REFRESH APP WARD
AIRCON SET_WARD_OFF APP WARD
AIRCON SET_WARD_ON APP WARD
AIRCON SET_ZONE_HVAC_MODE APP WARD ZONES MODE RAW SETBACK GUARD USE_AUX TYPE LEVEL AUX_LEVEL
AIRCON SET_ZONE_HUMIDITY_MODE APP WARD ZONES MODE RAW SETBACK GUARD USE_AUX TYPE LEVEL AUX_LEVEL
AIRCON SET_HVAC_UPPER_GUARD_LIMIT APP WARD ZONES LIMIT MODE RAW
AIRCON SET_HVAC_LOWER_GUARD_LIMIT APP WARD ZONES LIMIT MODE RAW
AIRCON SET_HVAC_SETBACK_LIMIT APP WARD ZONES LIMIT MODE RAW
AIRCON SET_HUMIDITY_UPPER_GUARD_LIMIT APP WARD ZONES LIMIT MODE RAW
AIRCON SET_HUMIDITY_LOWER_GUARD_LIMIT APP WARD ZONES LIMIT MODE RAW
AIRCON SET_HUMIDITY_SETBACK_LIMIT APP WARD ZONES LIMIT MODE RAW
```

Wards are 0–255. `ZONES` is a comma-separated list of indices 0–6; duplicates
collapse and empty comma-delimited tokens are ignored, so a comma-only value
encodes an empty bitmap. HVAC modes are 0–4 and humidity modes 0–3. Boolean
flags are exactly `0` or `1`; levels and limits are 0–65535; auxiliary level is
0–255. C-Gate accepts a nonnegative signed-32-bit plant type and maps values
above 255 to byte `FF`; cmqttd retains that behavior. Every valid command is
sent as one application-`0xAC` broadcast
and waits for its correlated PCI confirmation. A 200 proves confirmed delivery
to the interface only. It does not prove HVAC-controller acceptance, resulting
mode/temperature/humidity, or persistence. Do not infer state from the command
response, and do not claim bridged-network support. When the optional LOGIN
gate is armed, authenticate before the ten state-changing AIRCON subcommands;
`REFRESH` and help stay open.

Incoming HVAC/humidity schedule entries, plant status and level reports, and
zone temperature/humidity reports are decoded as application-172 events and
fanned out to clients with `EVENT ON`. A report received while `REFRESH` is
pending remains an event; only the correlated PCI confirmation completes the
command. cmqttd does not invent an MQTT HVAC entity or state schema for these
reports.

`CMQTT CAPABILITIES` advertises `aircon_control: true`,
`aircon_application: 172`, `aircon_delivery_semantics:
"pci-confirmed-broadcast"`, the exact `aircon_commands` and `aircon_reports`
lists, `aircon_event_fanout: true`, and `aircon_mqtt_state: false`. Ground byte
claims in `rust/testdata/fixtures/native_cgate_aircon.json` and
`rust/testdata/vectors/aircon.jsonl`. The real-daemon fake-PCI test validates
all eleven commands, native parser boundaries, report fanout, NAK recovery,
authentication, pre-I/O rejection, and MQTT continuity. A transport regression
pins that a report does not consume the pending command confirmation. No live
HVAC acceptance has been performed.

### Audio commands

cmqttd implements every maintained C-Gate 3.4 `AUDIO` subcommand for Audio
application 205 (`$CD`) on its configured direct network. Start with `AUDIO ?`
to retrieve the native-shaped command list. Use `APP` as either
`NETWORK/205` or `//PROJECT/NETWORK/205`:

```text
AUDIO CURRENT_FEED APP MUX ZONE FEED GAIN
AUDIO DYNAMIC_1 APP MUX ZONE
AUDIO DYNAMIC_2 APP MUX ZONE
AUDIO HIGH_PRIORITY APP MUX LEVEL FEED
AUDIO MUTE APP MUX ZONE MODE
AUDIO NEXT_FEED APP MUX ZONE
AUDIO NEXT_LANGUAGE APP MUX ZONE
AUDIO OFF APP MUX ZONE FUNCTION
AUDIO ON APP MUX ZONE FUNCTION
AUDIO OUTPUT_COMMON_CONTROL APP [CONTROL]
AUDIO OUTPUT_DEVICE_STATUS_REQUEST APP [PARAMETER]
AUDIO OUTPUT_ERROR_CODE APP MUX ZONE ERROR
AUDIO PREVIOUS_FEED APP MUX ZONE
AUDIO RAMP APP MUX ZONE FUNCTION LEVEL RATE
AUDIO REQUEST_CURRENT_FEED APP MUX ZONE
AUDIO SET_FEED APP MUX ZONE FEED OPTION
AUDIO TERMINATERAMP APP MUX ZONE FUNCTION
AUDIO ZONE_DESCRIPTOR_REQUEST APP MUX ZONE
AUDIO ZONE_FEED_LABEL_REQUEST APP MUX ZONE
```

Except for `HIGH_PRIORITY`, `OUTPUT_COMMON_CONTROL`,
`OUTPUT_DEVICE_STATUS_REQUEST`, and `OUTPUT_ERROR_CODE`, replace the address
columns with `Z FUNCTION` to use native Z addressing. `MUX` is 0–2, `ZONE`
and feed/function/error values are 0–7, gain is 0–4, level is 0–255, ramp rate
is 0–15 and set-feed option is 0–1. All numeric fields accept decimal or
`$`-prefixed hexadecimal. The encoder preserves native low-bit masking for
dynamic/feed/language, mute and request operations. Z ramp values at or above
192 can collide with other native Audio opcodes on decode; command acceptance
does not imply round-trip identity.

Native 3.4 accepts mute modes 0–7 and 255. Modes 8–254 are also transmitted
but produce the native mixed 400 continuation followed by final 200; `-1` and
256 fail before I/O. An omitted or `-1` output-common-control or
output-device-status parameter encodes `FF`; only explicit zero is otherwise
accepted. Output error codes span 0–7 despite the older manual's narrower
description. Preserve these cases when generating commands or interpreting
responses.

All valid commands wait for the correlated PCI confirmation on the active
connection generation. A 200 proves interface delivery only, not
audio-controller acceptance or resulting state. Routed Audio writes fail
closed. When LOGIN is armed, authenticate for the thirteen state-changing
forms; current-feed, output status/error, request-current-feed and the two zone
metadata requests remain open.

Incoming Audio command SAL is decoded and fanned out to `EVENT ON` clients.
cmqttd also decodes evidenced A0 label/load-icon fields as an explicit repair:
the maintained native C-Gate advertises these events but suppresses every valid
frame because of an impossible byte-length versus hex-character-length check.
Do not describe that repair as native event parity. There is no Audio MQTT
state contract. `CMQTT CAPABILITIES` exposes `audio_commands`, `audio_events`,
confirmed-broadcast delivery, event fanout and `audio_mqtt_state: false`.
Ground wire behavior in `rust/testdata/fixtures/native_cgate_audio.json` and
`rust/testdata/vectors/audio.jsonl`; the real-daemon
`system_cgate_audio.rs` test covers all commands, grammar, authentication,
confirmation recovery, event fanout and MQTT continuity with fake PCI. A
service regression also replaces the PCI while an Audio confirmation is
pending and rejects the retired generation's eventual success.

### Security commands

cmqttd implements the complete maintained C-Gate 3.4 SECURITY family for
application 208 (`$D0`) on its configured direct network. Inspect native help
with `SECURITY ?`:

```text
SECURITY STATUS_REQUEST APP 1|2
SECURITY ARM APP away|night|day|vacation|highest
SECURITY TAMPER APP raise|drop
SECURITY RAISE_ALARM APP
SECURITY EMULATE_KEYPAD APP KEY
SECURITY DISPLAY_MESSAGE APP [MESSAGE]
SECURITY REQUEST_ZONE_NAME APP ZONE
```

`APP` accepts `NETWORK/APPLICATION` or `//PROJECT/NETWORK/APPLICATION` and
must resolve to 208. `KEY` uses C-Gate's signed-32-bit parser, including `$`
hex; values outside 0–255 encode as `FF`, matching native behavior. The
display command accepts zero or one whitespace token, decodes `\\`, `\xHH`,
`\n`, `\r`, and `\t`, and permits at most 17 encoded bytes. Encode spaces as
`\x20`. `ZONE` is 1–127. Native 3.4 crashes internally for some out-of-range
zone indices; cmqttd rejects them before I/O.

Every admitted command is one application-`0xD0` broadcast and completes only
after a positive correlated confirmation from the active shared PCI
generation. A 200 is interface-delivery evidence, not alarm-panel acceptance,
state change or persistence. With LOGIN armed, `STATUS_REQUEST` and
`REQUEST_ZONE_NAME` remain open; the five control forms require authentication.
Incoming commands and native events `0x80`–`0x98`, including fixed zone names
and the 32-/48-zone packed reports, fan out to `EVENT ON` clients. cmqttd has
no MQTT Security entity/state schema. Bridged Security routing remains
unsupported.

Ground exact behavior in `rust/testdata/fixtures/native_cgate_security.json`,
`rust/testdata/vectors/security.jsonl`, and
`rust/cmqttd/tests/system_cgate_security.rs`. A `cbus-transport` regression
also pins that an incoming Security event cannot satisfy a pending request
confirmation.

### Measurement data

cmqttd implements the complete maintained C-Gate 3.4 Measurement family on
the configured direct network:

```text
MEASUREMENT DATA NETWORK/228/DEVICE/CHANNEL VALUE MULTIPLIER UNITS
```

`VALUE` is signed 16-bit, `MULTIPLIER` is signed 8-bit, and units, device and
channel are bytes. Scalar integers accept C-Gate `$` hexadecimal notation.
The exact SAL order is `0E device channel units multiplier value-msb
value-lsb`. A 200 proves only correlated PCI confirmation. With the optional
LOGIN gate armed, authenticate before DATA. Do not claim bridged write support
or physical sensor acceptance.

Incoming application-228 samples appear on `EVENT ON` as
`#e# measurement data //PROJECT/NETWORK/228/DEVICE/CHANNEL VALUE MULTIPLIER UNITS sourceUnit=SOURCE`.
They lazily create native-shaped dynamic objects. Query application
`State`/`Devices`, device `State`/`Channels`, and channel `State`/`Data` with
`GET`; Data is `value,multiplier,units,age-ms`. An existing channel without a
sample returns `0,0,0,-1`. cmqttd defines no MQTT Measurement state. Ground
behavior in `native_cgate_measurement.json`, `measurement.jsonl`, and
`system_cgate_measurement.rs`.

### Media Transport commands

cmqttd implements the complete maintained C-Gate 3.4 `MEDIATRANSPORT` family
for application 192 (`$C0`) on its configured direct network. Use
`MEDIATRANSPORT ?` for the captured native help. The grammar is:

```text
MEDIATRANSPORT STOP|PLAY|STATUS_REQUEST APP GROUP
MEDIATRANSPORT PAUSE|SHUFFLE|REPEAT|NEXT_CATEGORY|NEXT_SELECTION|NEXT_TRACK APP GROUP OPERATION
MEDIATRANSPORT FORWARD|REWIND|SOURCE_POWER APP GROUP OPERATION
MEDIATRANSPORT SET_CATEGORY APP GROUP CATEGORY
MEDIATRANSPORT SET_SELECTION APP GROUP SELECTION
MEDIATRANSPORT SET_TRACK|TOTAL_TRACKS APP GROUP VALUE
MEDIATRANSPORT ENUMERATE APP GROUP TYPE START
MEDIATRANSPORT ENUMERATION_SIZE APP GROUP TYPE START SIZE
MEDIATRANSPORT TRACK_NAME|SELECTION_NAME|CATEGORY_NAME APP GROUP WNI TOTAL INDEX [TEXT]
```

`GROUP`, byte operations and `START` are 0–255. Pause and shuffle operations
are 0 or 255; forward/rewind rates are 0, 2, 4, 6, 8, 10 or 12. Category is
0–127, selection is 0–32767, and track/count values are 0–2147483647.
Enumeration type is 0–2 and size is 0–15. WNI accepts 0, 1, 2, 5, 6 or 7;
`TOTAL` and `INDEX` are 0–3; name text is optional and at most 11 UTF-8 bytes.
Decimal, case-insensitive `0b` binary, case-insensitive `0x` hexadecimal, and
`$` hexadecimal integers use the native signed-32-bit parser. A name beginning
with a quote uses native dequoting: the last quote is removed and escaped
spaces, quotes, and backslashes are unescaped before the byte-length check.
Native C-Gate corrupts every non-ASCII UTF-8 byte in an outbound name to
`FF`; the command boundary preserves that captured quirk, while inbound SAL
and typed JSON retain the raw bytes losslessly. Inbound decoding also preserves
WNI 3 and 4 because native C-Gate accepts every packed three-bit WNI on the bus
even though its outbound command parser reserves those two values.

`STATUS_REQUEST` and `ENUMERATE` remain open when the optional LOGIN gate is
armed. Controls and bus-report injection require LOGIN. Every admitted command is sent exactly once and
waits for a positive correlated confirmation from the active shared PCI
generation. A 200 proves interface delivery only, not media-device acceptance
or resulting state. Incoming commands/reports fan out as `#e# mediatransport`
events. cmqttd exposes no MQTT Media Transport entity or state. Bridged routing
remains unsupported. Ground exact behavior in
`rust/testdata/fixtures/native_cgate_mediatransport.json`,
`rust/testdata/vectors/mediatransport.jsonl`, and
`rust/cmqttd/tests/system_cgate_mediatransport.rs`. `CMQTT CAPABILITIES` advertises application 192, `pci-confirmed-broadcast`, `exactly-once-no-replay`, all 21 message names, event fanout, and `mediatransport_mqtt_state: false`.

### Telephony commands

cmqttd implements the complete maintained C-Gate 3.4 `TELEPHONY` family for
application 224 (`$E0`) on its configured direct network. Inspect the exact
native help with `TELEPHONY ?`:

```text
TELEPHONY CLEAR_DIVERSION APP
TELEPHONY DIVERT APP NUMBER
TELEPHONY ISOLATE_SECONDARY_OUTLET APP normal|isolate
TELEPHONY RECALL_LAST_NUMBER_REQUEST APP in|out
TELEPHONY REJECT_INCOMING_CALL APP
```

`APP` accepts `NETWORK/224` or `//PROJECT/NETWORK/224`. Keep it on the
configured direct network; foreign, absent and routed paths fail closed.
Modes and directions are case-insensitive. `NUMBER` is exactly one literal
whitespace-delimited token with Java UTF-16 length 1–16. Do not shell-decode
quotes or backslashes: `\q` sends the two bytes `5C 71`, and `""` sends two
quote bytes. Native 3.4 has an evidenced non-ASCII defect: it counts Java
characters for the SAL prefix, converts each signed UTF-8 byte to `FF`, and
can therefore emit an undeclared trailing byte. cmqttd intentionally retains
that exact command output; do not normalize it when compatibility is required.

Every admitted command is one application-`0xE0` broadcast and completes only
after a correlated positive confirmation from the active shared PCI
generation. A 200 proves interface delivery, not telephone-unit acceptance,
call state, diversion persistence or readback. With LOGIN armed,
`RECALL_LAST_NUMBER_REQUEST` stays open; clear/divert/isolate/reject require
authentication. Incoming commands and `line_on_hook`, `line_off_hook`,
`dial_out_failure`, `dial_in_failure`, `ringing`, `last_number`, and
`internet_connection_request_made` events fan out to `EVENT ON` clients.
The retained decoder has a formatting quirk for line-off-hook and last-number
events: it inserts a separator before a number only when that number is longer
than one byte, so single-byte values appear as `out data1` or `in1`. Preserve
that spelling when parsing native-compatible event text. These events create
no MQTT entity or state.

Ground behavior in `rust/testdata/fixtures/native_cgate_telephony.json`,
`rust/testdata/vectors/telephony.jsonl`, and
`rust/cmqttd/tests/system_cgate_telephony.rs`. A transport regression proves
that an incoming Telephony event cannot satisfy a pending send confirmation,
and a service regression rejects a confirmation from a retired PCI generation.

### DALI commands

cmqttd routes all 128 maintained DALI paths: 103 physical leaves and 25
local/help paths. Physical coverage includes all 48 retained core commands, all
14 commands below `DALI EMERGENCY`, and 41 specialized gateway,
error-reporting, measurement, or session leaves. The six group roots and 19
specialized catalogue/session/gateway-view leaves are local. Start with the
native help catalogue and address the gateway unit itself:

```text
DALI ?
DALI KNOWN EXEC //PROJECT/254/p/20 A
DALI KNOWN POLL //PROJECT/254/p/20 A
DALI EMERGENCY STATUS EXEC //PROJECT/254/p/20 A 3
DALI ERROR_REPORTING STORE_OPTION //PROJECT/254/p/20
DALI GATEWAY PAGED_RECALL //PROJECT/254/p/20 521 1
DALI SESSION NEW commissioning
```

Each command accepts an optional mode before the gateway: AUTO is the default;
EXEC/EXECUTE, POLL and CANCEL use retained extended-CAL controls. The line is
`A` or `B`. EXEC payload grammar is command-specific; POLL and CANCEL carry no
payload. Native help also advertises STATUS, but retained C-Gate 3.4 never
supplies its mandatory selector and fails before I/O. Preserve cmqttd's
`400 dali cal status must be set` rather than inventing a selector.

DALI uses priority-zero direct point-to-point CAL and has no PCI confirmation
code. Treat the source-correlated extended reply from the addressed gateway as
the completion boundary. AUTO sends EXECUTE once, waits 1.5 seconds, and polls
at most ten times while status is IN_PROGRESS or FAIL_BUSY. It never repeats
the EXECUTE. A disconnect, lost gateway reply or PCI-generation change makes
the outcome uncertain and the operation is not replayed. Native-shaped replies
include DaliCommand, Line, Payload, SendCommand, Response, ResponseStatus and
ResponsePayload rows; a NAK maps to FAIL_CATASTROPHE with a null payload.

Specialized paged reads and stores use the shared programming lane. Stores are
limited to 12 bytes per page-bounded chunk, require the tagged device reply,
and read the range back before success. `GATEWAY SET_EXTENDED_PARAMETERS` and
`SESSION SET_EXT_PARAMS` stage local bytes; `GATEWAY WRITE_EXTENDED_PARAMETERS`
and `SESSION DEPLOY ... EXT_ONLY` perform the physical write. Catalogue JSON is
loaded from `%PROJECT%/dali_catalogue/devices/*.json` in the virtual FILE
repository. Active sessions are volatile; explicit SAVE/LOAD snapshots are
keyed by gateway OID in the atomic cmqttd JSON database.

When LOGIN is armed, mutation commands in AUTO/EXEC/CANCEL mode, specialized
setters, catalogue reload, gateway mutations, and session mutations require
authentication. Read-only operations stay open. The six group roots CATALOG,
EMERGENCY, ERROR_REPORTING, GATEWAY, MEASUREMENT and SESSION return exact
retained help locally. Inspect the boundary programmatically with
`CMQTT CAPABILITIES`:

```json
{
  "dali_physical_leaf_commands": 103,
  "dali_local_help_roots": 6,
  "dali_specialized_local_leaf_commands": 19,
  "dali_specialized_physical_leaf_commands": 41,
  "dali_specialized_commands_fail_closed": 0,
  "dali_full_compatibility": false,
  "dali_session_ext_only": true,
  "dali_session_typed_device_plans": "fail-closed-before-io",
  "dali_delivery_semantics": "source-correlated-exactly-once-no-replay"
}
```

`EXT_ONLY` session extraction and deployment have exact paged-memory physical
plans. Do not silently map `DALI_ONLY`, `FULL`, `COND_QUICK`, `COND_EXTENDED`,
`RESCAN_FAULT`, `REFRESH_STATUS_INFO`, or `RETRIEVE_RECONCILE` onto that plan.
C-Gate's retained classes make those typed-model workflows; cmqttd refuses
them before I/O until the full typed model codec is evidenced.

There is no MQTT DALI state contract. Ground syntax/help in
`rust/testdata/fixtures/native_cgate_dali_help.json`, specialized class hashes,
layouts, and the fail-before-I/O boundary in
`rust/testdata/fixtures/native_cgate_dali_specialized.json`, exact CAL/page
bytes in `rust/testdata/vectors/dali.jsonl`, and real-daemon fake-PCI/MQTT
behavior in `rust/cmqttd/tests/system_cgate_dali.rs` and
`rust/cmqttd/tests/system_cgate_dali_specialized.rs`. The complete operator
guide is `docs/cgate-dali.md`.

The physical service also implements lighting commands, C-Gate `DO` object
methods for lighting and direct/bridged read-only `SYNC`, Trigger Control,
Enable Control, clock date/time/refresh, Temperature Broadcast, `NET PINGU`, `NET SYNC`,
`NET CHECKUNIT`, physical `NET CLOCKS`, physical `PP LOAD`, and readback-verified physical `PP SAVE` for
`direct`, `edlt`, `paged`, `ncc`, `giu`, `sgiu`, `dali`, `goc`, `gocbyt`, and
`goc2` parameters using decoded unit specifications. Direct and page-aware
`lock` parameters use the captured unlock phase. A specification containing
`ProgramMethod=ncc` identifies the vendor C-Bus 3 families; after at least one
changed store, SAVE performs native group-0 operation-4 EXECUTE followed by
500 ms POLLs for up to 15 seconds and succeeds only on status zero. An unchanged
or tag-filtered save does not issue the NVM command.
`LIGHTING`, `TRIGGER`, and `ENABLE` label commands also use the physical bus.
They support the Toolkit CLI's raw/text, icon, language, segmented Unicode, and
dynamic bitmap forms. Enable Unicode is a native-invalid form. A 200 response
proves confirmed fragment delivery, not display rendering or persistence.
`SCENE RECORD set name` atomically persists currently observed lighting levels
from the configured network. `SCENE PLAY set name` sends confirmed zero-time
ramps and requests status readback; its success does not by itself prove the
loads reached those levels. These named server snapshots are separate from
device PP scene tables.
`LABEL CLEAREDLT //PROJECT/NETWORK/p/UNIT` is hardware-backed for KEYGL5. It
sends one native clear control and requires a correlated unit ACK. Report it as
accepted, never as verified erasure or persistence; there is no dynamic-label
cache readback operation.

Standard native cache clear is a separate operation:

```text
LABEL CLEAR //PROJECT/NETWORK/APPLICATION UNIT
LABEL CLEAR //PROJECT/NETWORK/APPLICATION UNIT KEY
```

Use `cbus-toolkit cgate label cache-clear APPLICATION UNIT [--key KEY]` for
the typed form. Applications are 48–95, 202 or 203, units are 0–255 and keys
are 1–8. The all-key form emits `A3 FF 00 27`; the keyed form emits
`A4 FF 00 66 KEY`. cmqttd sends one point-to-point frame with no replay and
waits only for its matching PCI confirmation. Native C-Gate considers both
`.` and `#` confirmation outcomes complete. There is no unit ACK or readback,
and the native handler publishes no label-specific success event. Optional
high-verbosity audit events remain generic command/response logging. Report
`native_accepted` and `pci_confirmation_received`, while keeping delivery
outcome, erasure and persistence unverified. This is also distinct from
`cgate label clear`, which sends an empty group-label SAL.

The native KFI commands are also hardware-backed on the configured direct
network:

```text
LABEL KFIGET //PROJECT/NETWORK/APPLICATION UNIT
LABEL KFISET //PROJECT/NETWORK/APPLICATION UNIT KFI1 KFI2 KFI3 KFI4 KFI5 KFI6 KFI7 KFI8
```

The application must be one of the label-capable native IDs 48–95, 202 or 203;
the unit is 0–255 and KFISET requires exactly eight values from 0 through 15.
The application token is a native `LabelSupportingApplication` scope/class
gate; it is not encoded into KFIGET's fixed selector `0x1c`.
KFIGET returns eight ordered `300` KFI rows from exactly one source-correlated
native reply; zero or multiple replies return 524. KFISET sends four packed
parameter-`0xFF` writes and stops at the first failed confirmation or unit ACK.
Despite the GET name, KFIGET first sends three volatile parameter-`0xFF` selector
writes. It is a programming operation behind the optional LOGIN gate and should
not be run casually on live hardware. It does not read a dynamic-label cache,
does not require a modeled KEYGL5 unit type, and has scripted rather than live
hardware acceptance.

Every KFI parameter-`0xFF` write and the GET IDENTIFY request is a
generation-safe exact-once send and never enters automatic retry. A lost
confirmation faults the programming lane until reconnect, preventing a late
confirmation or identical untagged ACK from advancing a later selector and
preventing GET replay from manufacturing response multiplicity.

`DO //PROJECT/NETWORK/p/UNIT FactoryDefault` is also hardware-backed for
KEYGL5. Use `cbus-toolkit cgate edlt-factory-default plan|request` with the
expected native serial. cmqttd sends captured control `A4 FF 43 B2 B2` exactly
once and requires PCI confirmation plus the source-correlated unit ACK. A 202
proves acceptance only; reset values, reboot, retained address, rendering and
persistence require separate verification. When the optional LOGIN gate is
armed, this destructive method requires authentication.
It also implements guarded scalar `SET //PROJECT/NETWORK/p/UNIT Address DEST`
against the physical bus. That command proves one source and an empty
destination, uses the native parameter-`0x20` one-use challenge, sends the
special address STORE once, requires the destination ACK, and deliberately
leaves the database unit address unchanged for the Toolkit workflow to verify.
The bounded `NET UNRAVELUNIT //PROJECT/NETWORK 255 MATCHDB` path resolves
exactly two known serials colliding at 255 to two unique, independently empty
database destinations on a direct network. It requires local PCI parameter
66=`05`, sends each selected-serial broadcast once, verifies each destination,
and repeats the complete MMI and serial inventory before returning 200. Query
`CMQTT CAPABILITIES`; `net_unravelunit_matchdb_duplicate_255: true` denotes
this exact scope. Whole-network UNRAVEL, other source/subset forms, occupied
destinations, cycles, larger duplicate sets, and bridged networks remain 502.
`DBNETWORKPATH START END [OID|COMPACT]` resolves the imported Bridge
`InterfaceAddress` graph with the standard far-side address convention. It
requires a database bridge unit for every transition, returns each crossed
network excluding START and including END, and refuses paths longer than six.
OID results are network identities and resolve with `DBGET !oid/OID` in the
selected project, including native-style project copies that share the OID.
The final `/p/<interface-unit>` component may differ from the child network;
native 3.4 accepts that address but still requires and emits the far-side
network address under its standard bridge convention. Native 3.4 continues to
resolve the path after the distinct suffix unit is deleted, so do not require
that unit for `DBNETWORKPATH`. A zero-hop request whose START equals END returns
the exact native 408 no-path response in default, OID and COMPACT forms. Only
the literal optional `COMPACT` token selects compact output; another fourth
token uses the default OID form, and later tokens are ignored like native 3.4.
The retained [native topology acceptance](../../../../toolkit-cli/research/experiments/2026-09-26/cgate-bridged-topology-native-acceptance.json)
contains the disposable C-Gate 3.4 path results and exact missing-unit 408. Its
one-hop outbound PINGU frame is explicitly a separate C-Gate 2.11.11 capture,
consistent with the published serial interface guide; no selected-version or
physical bridge reply acceptance is inferred from it. The companion
[`DBNETWORKPATH` grammar acceptance](../../../../toolkit-cli/research/experiments/2026-09-26/cgate-dbnetworkpath-grammar-native-acceptance.json)
pins the selected-version zero-hop, mode, trailing-token and missing-address
behavior.
PINGU and whole-network checks send either the direct install-MMI request or a
native PPM source route through one to six bridge unit addresses. They buffer
blocks that arrive before confirmation but accept only positively confirmed,
contiguous coverage of addresses 0–255 from the exact Reply Network. SYNC uses
the configured direct interface-unit address as a routing hint, or BASIC
discovery when that hint is unavailable; fresh MMI and route-correlated
IDENTIFY replies physically validate the result. It probes
IDENTIFY1/2 and collects all IDENTIFY4 replies for every present address, then
atomically replaces the live identity cache. Silent legacy/error addresses stay
present with unknown identity fields. Native eDLT metadata requires non-error
present MMI state one or two, exactly one raw IDENTIFY4 reply carrying a known
serial, and both the configured database type and fresh IDENTIFY1 to be KEYGL5.
Repeated identical known replies and mixed known/unknown replies are ineligible,
while the live serial cache retains its distinct-known-serial representation.
Eligible units follow retained CBusEdlt
classfile order:
OEM-routed parameter `0xFB` length 9 becomes the NUL-terminated volatile
`FirmwareVersion`; an OEM address-16 selector plus parameter-1 length-2 recall
becomes decimal `Application` and `Application2`; OEM-routed parameter `0xFA`
length 44 becomes opaque decimal-CSV `WidgetGroups`. `Version` remains the separate
IDENTIFY2 value and the persistent database `FirmwareVersion` is unchanged.
Read the properties with `GET //PROJECT/NETWORK/p/UNIT PROPERTY`; these cached
`300` getters issue no bus I/O. Every request is exact-once and responses must
match source, selector tag or parameter, and total length. A failed optional
read leaves earlier values from the same sequence fresh, invalidates the failed
and all later unrefreshed values, and does not fail an otherwise valid identity
SYNC. The programming lane remains faulted until reconnect and no request is
replayed. `WidgetGroups` is static mapping, not dynamic-label cache readback.
State three and addresses with zero or multiple raw IDENTIFY4 replies receive no
source-address-only metadata traffic and expose no stale metadata. Multiple raw
replies include repeated identical known replies and mixed known/unknown
replies. Reconnect or transport loss invalidates an in-flight snapshot before
commit and returns 408 without a sync-ok event. Routed synchronization updates
only the addressed network's volatile cache and emits that network in sync and
duplicate events. Direct-network OEM KEYGL5 metadata reads have no proven
Reply Network form and are skipped on bridged networks.
CHECKUNIT actively collects direct or route-correlated IDENTIFY4
replies through the native two-second quiet interval; it does not infer duplicate count from the
two-bit MMI state. Use `GET //PROJECT/NETWORK Units` and unit `Type`, `Version`,
`SerialNumber`, `Address`, and `State` getters for the resulting live snapshot.
For Rust commissioning work that must preserve duplicates rather than populate
the service cache, use `cbus_transport::inventory::collect_full_inventory`. It
requires complete contiguous MMI coverage, retains raw IDENTIFY4 replies with
multiplicity, bounds each address and the full collection, and marks silent or
malformed identities partial. Its observations are sequential and are not an
atomic network snapshot.
`NET SYNCNEW //PROJECT/NETWORK [unit]` is hardware-backed for direct networks,
and its general form is hardware-backed through one to six bridges. It merges
five complete MMI passes. The direct optional targeted form rejects an
already-modeled address before bus I/O, runs native duplicate challenges
`0x80`, `0x81`, and `0x82`, then reads IDENTIFY1/2/4. General routed discovery
uses exact Reply Network correlation for IDENTIFY1/2/4 and commits its staged
cache and event changes only if the shared PCI generation is still current.
Routed targeted discovery returns 502 before PCI I/O because its duplicate
challenge completion has not been captured. Results update only the addressed
network's volatile physical cache and retain native progress/result codes
(`120`, `303`, `408`); they do not create persistent database units. See the
[retained C-Gate 3.4 classfile and routed-wire evidence](../../../../toolkit-cli/research/experiments/2026-09-26/cgate-bridged-syncnew-readonly-evidence.json).
`NET PROJECT_IDENTIFY TYPE@ADDRESS` is hardware-backed for the one interface
already shared with MQTT. It runs one complete MMI, counts every nonzero state,
skips address zero while scanning candidates, and returns the first readable
six-byte parameter-35 identity as native `305 Project=... UnitCount=...`. It
does not update the project cache. A different valid interface returns 502;
cmqttd never opens a second PCI/CNI for this command. See the retained
[C-Gate 3.4 native acceptance](../../../../toolkit-cli/research/experiments/2026-09-26/cgate-project-identify-native-acceptance.json)
for exact grammar, bytecode and scripted wire evidence.
`NET SET_PROJECT_IDENTIFY //PROJECT/NETWORK NAME` is also hardware-backed.
It packs the uppercased 1–8 character native six-bit identity, selects the
first unit in non-error present MMI state one or two with valid IDENTIFY1 data
and exactly one valid known IDENTIFY4 serial reply over the complete quiet
window, stores parameter 35,
and requires exact RECALL readback. A failed or uncertain write invalidates an
older cached `ProjectName`. The verified update or same-generation invalidation
commits only while the captured shared PCI generation and pointer remain
current and connected. A reconnect returns 408, and the old operation cannot
clear or repopulate the replacement generation's cache. The typed CLI
mK-quotes spaces, quotes and backslashes; the cached `ProjectName` is decoded
from verified bytes so the native `?`/space alias stays canonical. It updates
only the volatile physical snapshot and does not rename or persist a project.
This is distinct from the read-only interface discovery performed by
`NET PROJECT_IDENTIFY`.
Query `CMQTT CAPABILITIES`; `unit_readdress: true` denotes the readdress path and
`physical_pp_save_cbus3_nvm: true` denotes the NVM commit path,
`dynamic_labels: true` denotes the label sender,
`dynamic_label_observation: true` denotes the volatile network-wide observed
SAL ring (including unit-shaped compatibility aliases with no verified
recipient), while
`dynamic_label_device_readback: false` preserves the unsupported device-query boundary,
`edlt_label_clear: true` denotes the one-shot KEYGL5 clear control,
`label_clear: true` denotes the standard physical all-key/one-key cache-clear
command above,
`label_kfi: true` denotes the native physical KFIGET/KFISET sequences above,
`edlt_extended_firmware: true` denotes OEM-routed parameter-`0xFB` physical
firmware readback during KEYGL5 NET SYNC,
`edlt_applications: true` denotes the native OEM address-16
Application/Application2 readback,
`edlt_widget_groups: true` denotes the bounded KEYGL5 static mapping populated
by NET SYNC,
`cgate_auth: true` denotes the armed opt-in LOGIN gate (`false` dormant
default): with `--cgate-auth-file` configured, each connection needs
`LOGIN <token>` before programming verbs, AIRCON mutations, Security control
forms, Telephony clear/divert/isolate/reject, and `MEASUREMENT DATA` while
reads, the Telephony last-number request, and
other bus control stay open; failures answer `420 LOGIN required` / `420 LOGIN failed` (malformed
`LOGIN` with no token is 400 and also clears the flag), never `401`.
Not native `access.txt` parity; loopback-only first slice;
`named_scenes: true` denotes hardware-backed named-scene playback,
and `do_methods: ["factorydefault", "lighting", "sync"]` denotes the physical object-method aliases,
`network_clocks: true` denotes IDENTIFY16 inspection plus schema-backed target
count and gateway recovery,
`network_syncnew: true` denotes the five-pass direct backend,
`bridged_syncnew_general: true` denotes routed general discovery while the
optional routed targeted form remains unavailable,
`bridged_read_only_discovery: true` denotes `DBNETWORKPATH` plus routed
`NET PINGU`, `NET SYNC`, general `NET SYNCNEW`, `DO ... SYNC`, and
`NET CHECKUNIT`,
`bridged_network_max_hops: 6` is the proven source-route bound,
`network_set_project_identify: true` denotes the verified parameter-35 write,
`pp_reset_to_defaults: true` denotes specification-backed staged
`PP RESET_TO_DEFAULTS` behavior,
`document_framing: true` denotes bounded, synchronized here-document transport;
`file_commands`, `file_storage`, `file_binary_transfer`, and
`file_host_filesystem` describe the complete FILE family and its sandboxed
cmqttd repository boundary;
`database_documents: false` records that native DBSETXML replacement semantics
and its 301 OID receipt remain unavailable,
`project_archive_restore: "cmqttd-internal"` denotes durable snapshot keys in
the cmqttd JSON repository (never vendor archive files),
`project_rename_secondary: true` denotes rename support except for the running
hardware-bound project,
`project_copy: "cmqttd-internal"` denotes an OID-preserving durable copy inside
the loaded cmqttd JSON model, and
`project_delete_secondary: "cmqttd-internal"` denotes durable deletion of a
secondary project while protecting the configured hardware project,
`repository_list: true` and `repository_type: "cmqttd-json"` denote the one
read-only repository descriptor, and explicit `cgl_import: false` /
`cgl_export: false` preserve the vendor-format boundary,
while `full_cgate_compatibility` remains false until every remaining backend and
acceptance requirement is complete.

For read-only local inventory, bare `PROJECT` returns the retained command
help and `PROJECT DIRFULL` returns native 123 project/description rows from the
atomic cmqttd repository. `DBGETJSON NAC_OBJECTS_LIST UNIT`,
`NAC_ROUTING_TABLE UNIT`, and `NAC_TAGMAP UNIT` require an existing durable
unit. cmqttd does not retain vendor NACObjectList definitions, so the first two
documents are explicitly empty; TAGMAP contains the modeled local network,
supported applications, groups and levels. Check
`database_json_nac_object_definitions` and `database_json_tagmap_scope` in
`CMQTT CAPABILITIES`; never describe these documents as physical discovery.

`EVENT_CHANNEL LIST` returns the four native deploy-queue channel types.
SUB/UNSUB is per command connection, returns native added/already/removed
status, and needs LOGIN when the optional gate is armed. Subscription state
does not prove that an unsupported queue operation can emit an event.
Advisory `LOCK OBJECT` and `UNLOCK OBJECT` are also connection-owned local
state. They resolve durable objects, conflict across sessions, and are released
on successful credential-changing LOGIN, LOGOUT, disconnect, or owning
UNLOCK. They are distinct from `PP LOCK` and never touch the C-Bus network.
Native evidence is in
`rust/testdata/fixtures/native_cgate_local_admin.json`.

For local project administration, `PROJECT ARCHIVE NAME cmqttd:KEY` stores a
database snapshot under an opaque key inside `--cgate-state`; it does not open
the key as a path. `PROJECT RESTORE NAME cmqttd:KEY` restores the modeled
project/network/unit records and unit fields without physical presence,
observed levels or network runtime state. Opaque auxiliary database maps are
outside this snapshot contract. `PROJECT RENAME OLD NEW`
atomically migrates a secondary project's path-keyed fields and follows that
connection's current selection. Renaming the configured PCI/MQTT project
returns 408 while cmqttd is running. All three use the retained native success
text `200 OK.`, are covered by the optional LOGIN gate, persist atomically and
roll memory back if the state-file commit fails.
Archive tokens outside the explicit `cmqttd:` namespace return 408, preserving
the unsupported Schneider ZIP/GZ/DB file-format boundary.

`PROJECT COPY SOURCE DESTINATION` preserves durable database OIDs, project
records, fields and level definitions, but clears copied physical presence,
observed levels and network runtime state. The source remains selected. The
destination must use the native evidenced maximum of eight ASCII project-name
characters. Copied OIDs resolve and mutate only when their source or destination
is the effective selected project; an unrelated selection returns 401 rather
than falling back to another loaded project. A cmqttd connection with no
explicit selection uses its configured hardware project. The command
`PROJECT DELETE NAME` is limited to secondary projects, removes only that
project's durable records and clears the deleting connection's selection.
Deleting the configured PCI/MQTT project returns 408. Both commands use the
`200 OK.` envelope, optional LOGIN gating, atomic persistence and failed-write
rollback. Native C-Gate keeps repository files separate from already loaded
projects; cmqttd has one loaded atomic model, so a copy is immediately
selectable and a delete is immediate. Do not infer Schneider file-repository
parity from these commands. Retained disposable-native evidence is in
`rust/testdata/fixtures/native_cgate_project_copy_delete.json`.

`REPOSITORY LIST` returns exactly one native-grammar 123 row for the configured
state file with type `cmqttd-json` and `current=yes`. Treat the type literally:
it is not Schneider SQLite, XML `file`, or `db` storage. Do not issue
`REPOSITORY USE`; its server-global selection semantics remain unimplemented.
`PROJECT REPAIR` also remains 502: the captured native SQLite repository says
it does not support the operation, and no repair transaction is established
for `cmqttd-json`.

cmqttd recognizes `[tag] COMMAND << DELIMITER`, followed by a body and the exact
delimiter on its own line. It limits individual lines to 1 MiB and the document
to 16 MiB, drains an oversized body before returning tagged 400, and closes
after a tagged 400 if EOF arrives before the delimiter. Completed `DBSETXML`
and `CGL IMPORT` documents return 502 unchanged. Native DBSETXML replaces a
typed object and the retained Toolkit workflows require a `301 OID=...`
receipt plus XML readback; the mock's opaque string store does not establish
that behavior. CGL format and transaction behavior also remain unimplemented.

Command connections also provide native-shaped `SESSION_ID`, `SESSION_ID ALL`
and one-shot `SESSION_ID TAG` state, including live TCP/TLS peer and connection
time fields. `EVENT` and its `EVENTS` alias default to `e0s0c0` on a new cmqttd
connection. `QUIT` and `EXIT` flush `204 Closing connection.` before closing the
stream. These operations are volatile and perform no PCI or persistent database
I/O.

`PP RESET_TO_DEFAULTS SESSION` replaces the loaded session values with exactly
the `DefaultValue` fields from its decoded unit specification. The change is
staged: it performs no PCI or database write until a later `PP SAVE` or
`PP SAVE_TO_SOURCE`. A missing or malformed exact specification returns 408
without changing the session.

Run `NET SYNC` before `NET CLOCKS`; clock operations use the synchronized
physical inventory. Query mode reports native `120-address=...` rows. A target
of 1..10 and recovery `R` change `ClockGenEnable` only when the live unit has a
decoded direct schema, preserving neighbouring bits and requiring physical
readback. Inspect the response lines because native behavior can report a
per-unit failure before final status 200.

`DO //PROJECT/NETWORK/APPLICATION/GROUP ON|OFF|RAMP|TERMINATERAMP` uses the
same confirmed SAL path as the corresponding lighting command. `DO
//PROJECT/NETWORK SYNC` runs the same physical identity-populating direct or
bridged read-only synchronization as `NET SYNC` and returns native `202 Done:
object` framing.
`DO ... UNRAVEL` returns 502; never describe the mock's in-memory result as
physical success or treat the bounded NET workflow as general unravel support.

## Mock service

The user-facing CLI is Python `cbus-toolkit cgate`; see [toolkit.md](toolkit.md) for installation, typed workflows, and JSON output. This reference describes its Rust test server. Connect the CLI with `--host 127.0.0.1 --port 20033` for the default mock listener; native plain TCP defaults to 20023.

## What is supported

The maintained registry combines 224 public headings from C-Gate manual section 4.5 with 268 registered bytecode command paths, producing 431 unique paths after overlap removal. Tests assert inventory sizes, uniqueness, help visibility, parser reachability, and dispatch reachability. Unknown commands return an error.

Core project, database, network, unit, group-level, label, lock, session, event, repository, and PP programming flows use shared in-memory state. Specialist application and hardware-facing commands have deterministic handlers so a client can exercise every registered path without Schneider services or physical equipment.

The Rust mock supports CLI clients and C-Gate command traffic. It does not provide persistent project storage, physical C-Bus access, firmware transfer, real port discovery, or exact device timing and side effects. The Python Toolkit CLI has its own native-server and physical-device workflows with separate limits and acceptance evidence. Full Toolkit parity remains unfinished.

## Start and connect

```sh
rust/target/release/cgate-mock --bind 127.0.0.1:0
```

Read the printed address, then connect with a line-oriented TCP client. For a fixed development port:

```sh
nc 127.0.0.1 20033
```

Commands may be untagged or tagged. A tag is written before the command:

```text
APIVER
[1] PROJECT LIST
[2] EVENT ON
```

Tagged replies retain the client tag. Multiline replies use a hyphen after the status/tag prefix for continuation lines and a space for the final line. Events may appear before a command's final response and can arrive asynchronously on subscribed clients, so clients must parse reply framing rather than assume one input line produces one output line.

## Addresses and stateful examples

C-Gate addresses use forms such as `//PROJECT/NETWORK/APPLICATION/GROUP`. The tests use examples like:

```text
[1] PROJECT LIST
[2] PROJECT USE TEST
[3] LIGHTING ON //TEST/254/56/1
[4] LIGHTING RAMP //TEST/254/56/1 128 20
[5] LIGHTING OFF //TEST/254/56/1
```

These commands require suitable model state; a fresh mock may return a not-found response for an address that has not been created. Use `HELP` and the repository command inventory for discovery, and construct a project/network/application/group before testing level changes.

Programming sessions are lock-gated:

```text
[10] PP LOCK L //TEST/254
[11] PP START S L
[12] PP NEW S KEY1 1.2.67
[13] PP SET S Example value
[14] PP GET S *
[15] PP END S
[16] PP UNLOCK L
```

Run with `--deny-programming` when testing access denial. Supply `--unitspec DIR` when catalogue-backed parameter schemas are required. Without vendor specifications, the model still supports the spec-free programming behavior allowed by the command.

## Sessions and events

The server model is shared across TCP connections. Each connection keeps its own selected project and event mode. `EVENT ON`, `EVENT OFF`, or a detailed `e[+0-9]s[01]c[01]` mode controls delivery. Subscribed clients receive cross-client events; the originating client receives eligible command events in order before its reply.

## Resource bounds

- Input line: 1 MiB maximum.
- Here-document body: 16 MiB maximum.
- Library event queue: 4,096 entries by default, with an overflow marker.
- TCP fanout: unbounded channels; a subscribed client that never reads can consume growing memory while writers continue.
- Unit-spec file: 8 MiB maximum; include traversal is capped at 128 files and checked for directory containment.

Use loopback and an ephemeral port in automated work. Stop the child process after the check. Do not expose the mock listener beyond the intended test environment.
