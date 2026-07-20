# rust-migration-harness

The **sole arbiter of success** for the Python → Rust migration of this
repository. `./run.sh` exits `0` only when the Rust implementation passes
every suite; anything else is a non-zero exit with a per-suite scoreboard.

The golden vectors in `vectors/` were generated from the **working-tree
Python implementation** (which is the migration ground truth) and are
**committed**, so the vector suites keep working even after the Python
code is deleted. The Python-based *self-check* suites additionally prove
the harness itself is sound; they are skipped automatically if the Python
package is no longer importable.

```
rust-migration-harness/
├── run.sh                      # single entry point (see below)
├── generate_vectors.py         # regenerates vectors/ + fixtures (needs .venv python)
├── vectors/                    # committed golden vectors (JSONL, 3200+)
│   ├── decode_from_pci.jsonl   # PCI->client wire bytes -> packet JSON (419)
│   ├── decode_to_pci.jsonl     # client->PCI wire bytes -> packet JSON (98)
│   ├── encode.jsonl            # packet JSON -> wire bytes (516)
│   ├── checksum.jsonl          # checksum function vectors (265)
│   ├── ramp_rates.jsonl        # lighting ramp duration<->code vectors (1044)
│   ├── mqtt_topics.jsonl       # cmqttd topic format/parse vectors (596)
│   └── ha_discovery.jsonl      # exact HA discovery JSON payloads (263)
├── fixtures/
│   ├── project.xml             # C-Bus Toolkit project (CBZ XML) used by -P
│   └── behavioral_expectations.json  # exact bytes/payloads for behavioral suite
├── lib/                        # harness internals
│   ├── pyjson.py               # canonical packet<->JSON codec (needs cbus pkg)
│   ├── wire.py                 # stdlib-only framing helpers
│   ├── fake_pci.py             # stdlib-only scripted PCI TCP server
│   └── mini_broker.py          # stdlib-only MQTT 3.1.1 broker
├── suites/
│   ├── verify_vectors.py       # python self-check of committed vectors
│   └── behavioral.py           # end-to-end cmqttd parity suite
└── logs/                       # cmqttd logs from behavioral runs (gitignored ok)
```

## Running

```sh
./rust-migration-harness/run.sh
```

Suites, in order:

| suite               | what it does                                                    |
|---------------------|-----------------------------------------------------------------|
| selfcheck-vectors   | replays every committed vector against the *Python* tree        |
| selfcheck-behavioral| runs the *Python* cmqttd against the fake PCI + mini broker     |
| rust-build          | `cargo build --workspace` in `rust/`                            |
| protocol-vectors    | runs `rust/target/debug/cbus-vector-check vectors/`             |
| rust-unit-tests     | `cargo test --workspace` in `rust/`                             |
| behavioral-cmqttd   | runs the *Rust* cmqttd against the fake PCI + mini broker       |

Environment knobs: `SKIP_SELFCHECK=1` (skip python self-checks),
`SKIP_SLOW=1` (skip the two ~2-minute throttle-drain assertions),
`RUST_DIR=<path>` (default `<repo>/rust`).

To regenerate vectors after intentionally changing Python behaviour:

```sh
.venv/bin/python rust-migration-harness/generate_vectors.py
.venv/bin/python rust-migration-harness/suites/verify_vectors.py
```

---

# Contract for the Rust implementation

## 1. `cbus-vector-check` binary

The Rust workspace MUST provide a binary crate/target named
`cbus-vector-check` (so it lands at `rust/target/debug/cbus-vector-check`).

Invocation: `cbus-vector-check <vectors-dir>`

It must read every `*.jsonl` file in the directory (one JSON object per
line) and evaluate each vector according to its file (formats below). It
prints anything it likes to stdout, but the **last line** must be:

```
protocol-vectors: <passed>/<total> PASS|FAIL
```

and the exit code must be `0` iff `passed == total`. On failure, print one
line per failing vector id with a short reason (first 50 failures is fine).

## 2. Rust `cmqttd` binary

Must land at `rust/target/debug/cmqttd` and accept at least these CLI
options (argparse-compatible subset of the Python daemon):

```
-b <host>              MQTT broker address (required)
-p <port>              MQTT broker port (0 = auto: 8883 TLS / 1883 plain)
--broker-disable-tls   plain TCP to the broker
-t <host:port>         TCP connection to CNI/PCI
-T <seconds>           timesync interval; 0 disables timesync
-C                     do not answer clock requests
-P <file>              C-Bus Toolkit project file (CBZ zip or bare XML)
-N <name...>           network name within the project file
-v <LEVEL>             log verbosity (accept and honour or ignore)
--broker-keepalive <s> MQTT keepalive (default 60)
```

The behavioral suite always passes `-b`, `-p`, `--broker-disable-tls`,
`-t`, `-T 0`, `-P`, `-v DEBUG`.

**MQTT protocol version MUST be 3.1.1 (protocol level 4).** The harness
broker rejects anything else with a clear error.

## 3. Behavioral assertions (what the Rust cmqttd must do)

All expected byte strings / payloads live in
`fixtures/behavioral_expectations.json` (generated from Python — do not
hand-edit). Assertions, in order:

1. `pci-connect` — connect to the PCI TCP endpoint on startup.
2. `pci-init-reset-x3` — send three `~` resets (each followed by CR is
   fine; the Python client sends `~\r`).
3. `pci-init-smart-connect` — send the `|` smart+connect shortcut.
4. `pci-init-dm-sequence` — then send, in order, basic-mode device
   management commands with payloads `A32100FF`, `A32200FF`, `A342000E`,
   `A3300079`, each followed by a **confirmation character** from the set
   `hijklmnopqrstuvwxyzg` (4 distinct codes) and CR. No `\` prefix, no
   checksum.
5. `mqtt-connect` — connect to the broker (MQTT 3.1.1).
6. `mqtt-subscribe-wildcard` — subscribe to `homeassistant/light/#`.
7. `meta-config-publish` — publish the exact retained JSON config for
   `homeassistant/binary_sensor/cbus_cmqttd/config` (qos 1, retain true).
8. `label-configs-publish` — for each group in the `-P` project file,
   publish the exact discovery config (see `label_configs` in the
   fixtures; unique_id `cbus_light_<id>`, abbreviated keys `cmd_t`,
   `stat_t`, etc.).
9. `status-requests-valid` — start streaming level status requests
   (`\05FF0073 07 <app> <block> <ck><conf>\r`), one per 0.2 s, for every
   lighting application 0x30..0x5F and block starts 0,32,...,224. Every
   frame must byte-match an entry in `status_requests` in the fixtures.
10. `retry-unconfirmed-frame` — the harness withholds the confirmation for
    the first status request: the same frame (identical payload AND
    confirmation char) must be retransmitted (Python: after 1 s, up to 3
    attempts total, then the code is abandoned/released).
11. `pci-event-on-to-mqtt` / `pci-event-ramp-to-mqtt` — when the PCI
    sends a lighting SAL, publish the exact state JSON to
    `homeassistant/light/cbus_<ga>/state` (`{"state","brightness",
    "transition","cbus_source_addr"}`) and `ON`/`OFF` to
    `homeassistant/binary_sensor/cbus_<ga>/state` (qos 1, retained).
12. `level-report-to-mqtt` — when the PCI sends a point-to-point extended
    status (level report) frame, publish per-group states: level 0 → OFF,
    255 → ON/255, other → ON with that brightness, transition 0,
    `cbus_source_addr: 0`; null (missing) levels are skipped but still
    advance the group counter.
13. `lazy-discovery-config` — the first state publish for a group that
    was not in the project file must be preceded by publishing its
    discovery config with the default name (`C-Bus Light NNN`).
14. `clock-request-response` — when the PCI sends a clock request SAL,
    reply with a clock update packet (PM frame, application 0xDF,
    date SAL then time SAL; time DST byte 0xFF).
15. `mqtt-cmd-off-to-pci` / `mqtt-cmd-alt-app-to-pci` — a JSON publish on
    `homeassistant/light/cbus_10/set` / `homeassistant/light/cbus_048_011/set`
    must produce the exact PM frame on the PCI (see
    `mqtt_cmd_*.expect_pci_payload`) **and** an MQTT state echo. These
    drain behind the 0.2 s throttle queue (up to ~2.5 min) — that timing
    is part of parity.

## 4. Vector file formats

Bytes are lowercase hex strings unless stated. `null` in JSON means
Python `None`.

### decode_from_pci.jsonl / decode_to_pci.jsonl

```jsonc
{
  "id": "fp-0001-power-on",
  "wire_hex": "2b",          // exact bytes given to the decoder
  "checksum": true,           // decoder flag: require+verify checksum
  "strict": true,             // decoder flag: errors -> invalid packet
  "from_pci": true,           // true: parse as PCI->client; false: client->PCI
  "expect_consumed": 1,       // bytes consumed from the buffer
  "expect_packet": { ... },   // canonical packet JSON, or null
  "expect_reencode": "...",   // re-serialised packet (see below), or null
  "note": "free text"
}
```

Semantics: run your equivalent of
`decode_packet(wire, checksum, strict, from_pci)`; it returns
`(packet-or-null, consumed)`. Compare `consumed`, the packet's canonical
JSON, and — when `expect_reencode` is non-null — the result of
re-serialising the decoded packet with `encode_packet()` (the base16
ASCII body **without** `\` prefix, confirmation char or CR/LF; for
"special" packets it is the raw token, e.g. `~`, `h.`, `++`, `!`).
`expect_reencode` is a latin-1 string, not hex.

A `null` `expect_packet` with `expect_consumed > 0` means "consume bytes,
emit nothing" (e.g. `null` toolkit junk, cancel-with-`?`). A `null`
packet with 0 consumed means "wait for more data".

### encode.jsonl

```jsonc
{
  "id": "en-0001-reset",
  "packet": { ... },              // canonical packet JSON (see schema)
  "expect_encode_hex": "7e",      // encode(): raw bytes incl. checksum if any
  "expect_encode_packet": "~"     // encode_packet(): base16 ASCII (BasePackets)
}                                  //   or raw token (specials); absent for
                                   //   bare SAL/CAL/report objects
```

`packet.type` may also be `sal`, `cal`, `binary_report` or `level_report`
to exercise those encoders standalone (then only `expect_encode_hex`).

### checksum.jsonl

`{"data_hex": "...", "expect_checksum": N}` where
`checksum = ((~sum(bytes) & 0xff) + 1) & 0xff` (empty input → 0).

### ramp_rates.jsonl

`{"kind": "duration_to_rate", "in": seconds, "expect": code}` — snap a
duration (s) to the smallest ramp-rate command code whose duration is
`>=` it (durations beyond 1020 s snap to 0x7A).
`{"kind": "rate_to_duration", "in": code, "expect": seconds}` — exact
lookup; only the 16 valid codes appear.

### mqtt_topics.jsonl

`kind: "format"` records give, for `(group_addr, app_addr)`, the expected
`ga_string` (padded + unpadded), set/state/config topics and binary-sensor
topics. Rules: default lighting app (0x38/56) uses the bare group number
in topics (`cbus_10`) and zero-padded 3-digit in display names (`010`);
any other app uses `cbus_<app:03d>_<ga:03d>` in **both**.
`kind: "parse"` records map a topic string to `(expect_group, expect_app)`
or `expect_error: true` (invalid prefix, out-of-range group, non-numeric).

### ha_discovery.jsonl

For `(group_addr, app_addr, labels?)`: the exact JSON payloads for the
light config topic and binary-sensor config topic, plus the set-topic
subscription (`expect_subscribe`, qos 2) and publish qos/retain (1/true).
Compare configs as parsed JSON objects (key order irrelevant), not
strings. The record with `"meta": true` is the `cbus_cmqttd` root device
config.

## 5. Canonical packet JSON schema

Common envelope fields for the three addressed packet types:
`checksum` (bool), `priority_class` (0..3), `source_address` (int|null),
`confirmation` (single-char string|null).

```jsonc
// specials
{"type": "power_on"}         // '+'         (PCI->client)
{"type": "pci_error"}        // '!'         (PCI->client)
{"type": "confirmation", "code": "h", "success": true}   // 'h.' / 'h#'
{"type": "reset"}            // '~'         (client->PCI)
{"type": "smart_connect"}    // '|'         (client->PCI)
{"type": "invalid"}          // decode error under strict rules
{"type": "cal", ...cal fields}  // bare CAL (client->PCI DM path)

{"type": "device_management", <envelope>, "parameter": 0x30, "value": 0x79}

{"type": "point_to_multipoint", <envelope>,
 "application": 56,           // the packet's application byte
 "sals": [ ... ]}

{"type": "point_to_point", <envelope>,
 "unit_address": 16, "bridged": false, "hops": [],
 "cals": [ ... ]}
```

SALs:

```jsonc
{"sal": "lighting_on",             "application": 56, "group_address": 1}
{"sal": "lighting_off",            "application": 56, "group_address": 1}
{"sal": "lighting_terminate_ramp", "application": 56, "group_address": 1}
{"sal": "lighting_ramp", "application": 56, "group_address": 1,
 "duration": 12, "level": 128}     // duration in seconds (pre-snap value)
{"sal": "clock_update_time", "hour": 1, "minute": 2, "second": 3}
{"sal": "clock_update_date", "year": 2026, "month": 7, "day": 20}
{"sal": "clock_request"}
{"sal": "temperature_broadcast", "group_address": 5, "temperature": 25.0}
{"sal": "enable_set_network_variable", "variable": 1, "value": 2}
{"sal": "status_request", "level_request": true, "group_address": 32,
 "child_application": 56}
```

CALs:

```jsonc
{"cal": "identify", "attribute": 1}
{"cal": "recall", "param": 250, "count": 44}
{"cal": "reply", "parameter": 1, "data_hex": "50435f434e494544"}
{"cal": "extended_status", "externally_initiated": false,
 "child_application": 56, "block_start": 0,
 "report": {"report": "binary", "group_states": [0,1,2,3]}}
// or {"report": "level", "levels": [255, 0, null, 128]}
```

Notes:
* `temperature` is a float (`byte / 4.0`, exact in binary FP).
* `group_states`: 0=missing, 1=on, 2=off, 3=error.
* `levels`: 0-255 or null (missing / undecodable manchester pair).
* the direct CAL reply frames (`wire` starting with a CAL header byte,
  e.g. `89...`, `82...`, `87...`) decode to a `point_to_point` packet
  with `unit_address: 0` and `source_address: null` — see the
  `direct-reply-*` vectors and PLAN.md "semantics traps".

## 6. Fixture project file

`fixtures/project.xml` is a bare-XML C-Bus Toolkit backup (the `.cbz`
format is the same XML in a 1-file zip). It defines application 56
("Lighting": group 1 "Kitchen Bench", group 10 "Lounge") and application
48 ("Lighting 48": group 11 "Deck"). The Rust `-P` loader must accept
both zip and bare XML.
