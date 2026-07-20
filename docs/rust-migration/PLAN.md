# C-Bus Python → Rust Migration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reimplement the `cbus` Python library, the `cmqttd` MQTT bridge daemon, and supporting CLIs in Rust, with bit-for-bit wire/MQTT parity proven by `rust-migration-harness/run.sh` exiting 0.

**Architecture:** A Cargo workspace at `rust/` with three library crates (`cbus-protocol` for the wire codec, `cbus-mqtt` for topic/discovery/CBZ logic, `cbus-transport` for the async PCI client state machine) and four binary crates (`cmqttd`, `cbus-vector-check`, `cbus-simulator`, `cbus-tools`). The committed golden vectors (3,201) and the behavioral suite (17 assertions) in `rust-migration-harness/` are the oracle — the Python working tree defines correct behaviour, bugs included.

**Tech Stack:** Rust 2021, tokio, rumqttc (MQTT 3.1.1), tokio-serial, clap v4, serde/serde_json, chrono, roxmltree + zip, tracing, thiserror.

---

## 0. Ground rules

1. **The harness is the spec.** `rust-migration-harness/README.md` documents the exact JSON schema, binary contracts and behavioral assertions. When this plan and the harness disagree, the harness wins. When the harness and your intuition disagree, the harness wins — it was generated from the Python ground truth, deliberately including Python's quirks.
2. **Do not modify** anything under `cbus/`, `tests/`, `rust-migration-harness/vectors/`, or `rust-migration-harness/fixtures/`. All Rust work lives under `rust/`. (Exception: adding `rust/` and `rust-migration-harness/logs/` to `.gitignore` patterns as needed for `target/`.)
3. Work on a branch: `git checkout -b rust-migration`. Commit after every task.
4. Verification loop for protocol work:
   `cd rust && cargo build --workspace && ./target/debug/cbus-vector-check ../rust-migration-harness/vectors`
   Full check: `./rust-migration-harness/run.sh` (from repo root).
5. Python references in this plan are `path:line` into the working tree — read them before porting. Port behaviour, not style.

## 1. Scope decision

### Migrating to Rust (in this plan)

| Python | Reason |
|---|---|
| `cbus/common.py`, `cbus/constants.py` | protocol constants/checksums — core |
| `cbus/protocol/**` (packets, CALs, SALs, applications, `packet.py` decoder) | core library |
| `cbus/protocol/pciprotocol.py` (confirmation mgmt, retry, timesync, reset) | required by cmqttd |
| `cbus/protocol/buffered_protocol.py`, `cbus_protocol.py` | framing layer |
| `cbus/transport/{base,tcp,serial}.py` | connectivity + reconnect |
| `cbus/daemon/**` (cmqttd, mqtt_gateway, topics, cli) | the main product |
| `cbus/toolkit/cbz.py` + `cbus/toolkit/dump_labels.py` | needed for `-P` labels; XML is stdlib `xml.etree` in Python already (lxml dep is vestigial), so Rust `roxmltree`+`zip` covers it; `cbz_dump_labels` JSON CLI comes almost free |
| `cbus/toolkit/periodic.py` | the 0.2 s command throttler — behaviourally load-bearing |
| `cbus/tools/decode_packet.py` | trivial CLI over the decoder; great debugging tool |
| `cbus/protocol/pciserverprotocol.py` → `cbus-simulator` bin | scripted fake PCI for end users/tests |
| `cbus/protocol/interrogator.py` | small, self-contained unit-interrogation client; port as `cbus-tools interrogate` |
| `cbus/esp32/connection.py` (WiFi=TCP / serial modes) | thin config wrapper over TCP/serial transports; port the `--esp32-wifi/--esp32-serial` CLI paths |

### Explicitly OUT of scope (stays as-is, in Python or C)

| Component | Decision & why |
|---|---|
| `esp32-firmware/` | **Out of scope.** It is C firmware for the ESP32, not Python. Nothing to migrate. |
| `cbus/toolkit/graph.py` (`pydot`) | **Dropped.** Niche DOT-graph generator, heavy dep, no tests depend on it. Python file remains for anyone who wants it. |
| `cbus/tools/fetch_protocol_docs.py` | **Dropped.** One-off PDF downloader (`requests`); not worth porting. |
| `cbus/web/` (aiohttp UI) | **Deferred.** Optional extra (`pip install .[web]`); no harness coverage; revisit after cutover (axum would be the natural choice). |
| `cbus/esp32/discovery.py` (zeroconf mDNS) | **Deferred.** Optional extra; `--esp32-discover` is convenience only. If wanted later: `mdns-sd` crate behind a cargo feature. Harness never uses it. |
| `cbus/esp32/emulator/`, `cbus/esp32/ha_discovery.py` | **Not migrated.** Test/ops tooling for the Python tree; the harness's own fake PCI + the Rust simulator supersede the emulator. `ha_discovery.py` is a one-shot ops script. |
| `cbus-proxy/` | **Deferred.** Debug proxy; `cbus-tools decode` covers analysis. Keep Python version for ad-hoc use. |
| `cbus-simulator/` (Python package) | **Superseded**, not ported line-by-line. The Rust `cbus-simulator` bin ports `pciserverprotocol.py` semantics (which is what cmqttd-facing tests need), not the regex-driven `cbus-simulator/simulator/protocol.py` (which parses a legacy text dialect nothing in the harness exercises). |
| `experiments/`, `wiser-swf-de/`, `scripts/` | Out of scope. |
| Python `tests/` | Superseded by the harness + Rust unit tests. Python tree stays in place until cutover (see Phase 8). |

## 2. Target layout

```
rust/
├── Cargo.toml                  # [workspace] members = [crates below], resolver = "2"
├── cbus-protocol/              # lib: pure wire codec, no async, no I/O
│   └── src/
│       ├── lib.rs
│       ├── common.rs           # <- cbus/common.py (enums, checksum, ramp)
│       ├── consts.rs           # <- cbus/constants.py (timings, thresholds)
│       ├── report.rs           # <- cbus/protocol/cal/report.py (manchester)
│       ├── cal.rs              # <- cbus/protocol/cal/{identify,recall,reply,extended,standard}.py
│       ├── sal/
│       │   ├── mod.rs          # SAL enum + dispatch <- application/__init__.py, sal.py
│       │   ├── lighting.rs     # <- application/lighting.py
│       │   ├── clock.rs        # <- application/clock.py
│       │   ├── temperature.rs  # <- application/temperature.py
│       │   ├── enable.rs       # <- application/enable.py
│       │   └── status_request.rs # <- application/status_request.py
│       ├── packet.rs           # Packet enum + per-type encode <- base/pm/pp/dm/confirm/error/po/reset/scs *_packet.py
│       ├── decode.rs           # decode_packet() <- cbus/protocol/packet.py
│       └── json.rs             # canonical JSON <-> Packet (serde), mirrors harness lib/pyjson.py
├── cbus-mqtt/                  # lib: cmqttd's pure logic (no network)
│   └── src/
│       ├── lib.rs
│       ├── topics.rs           # <- cbus/daemon/topics.py
│       ├── discovery.rs        # HA discovery payload builders <- mqtt_gateway.publish_light/publish_all_lights
│       └── cbz.rs              # <- cbus/toolkit/cbz.py + cmqttd.read_cbz_labels
├── cbus-transport/             # lib: async framing + PCI client state machine
│   └── src/
│       ├── lib.rs
│       ├── framing.rs          # buffered decode loop <- buffered_protocol.py + cbus_protocol.py
│       ├── pci.rs              # PciClient <- pciprotocol.py (confirmations, retry, reset, timesync)
│       └── conn.rs             # tcp/serial connect + reconnect <- transport/{base,tcp,serial}.py, esp32/connection.py
├── cmqttd/                     # bin: the daemon
│   └── src/
│       ├── main.rs             # <- cbus/daemon/cmqttd.py
│       ├── cli.rs              # <- cbus/daemon/cli.py
│       ├── gateway.rs          # <- cbus/daemon/mqtt_gateway.py (CBusHandler+MqttClient)
│       └── throttle.rs         # <- cbus/toolkit/periodic.py
├── cbus-vector-check/          # bin: golden-vector runner (contract in harness README §1)
│   └── src/main.rs
├── cbus-simulator/             # bin: fake PCI TCP server <- pciserverprotocol.py
│   └── src/main.rs
└── cbus-tools/                 # bin: `cbus-tools decode|dump-labels|interrogate`
    └── src/main.rs
```

Binary name note: the package `cbus-vector-check` must produce the binary
`rust/target/debug/cbus-vector-check`, and `cmqttd` must produce
`rust/target/debug/cmqttd` — `run.sh` hardcodes both paths.

### Module-by-module mapping (every Python module accounted for)

| Python module | Rust home | Notes |
|---|---|---|
| cbus/common.py | cbus-protocol/src/common.rs | full port |
| cbus/constants.py | cbus-protocol/src/consts.rs | constants only |
| cbus/logging_config.py | cmqttd main (tracing-subscriber init) | behaviour: `-v LEVEL` sets filter |
| cbus/protocol/base_packet.py | packet.rs (`flags()` helper, Packet enum) | InvalidPacket → `Packet::Invalid` |
| cbus/protocol/packet.py | decode.rs | the big one; see traps |
| cbus/protocol/{pm,pp,dm,confirm,error,po,reset,scs}_packet.py | packet.rs | encode + decode helpers |
| cbus/protocol/cal/*.py | cal.rs, report.rs | StandardCAL encode only (simulator uses it) |
| cbus/protocol/application/*.py | sal/ | app registry = match on app byte |
| cbus/protocol/buffered_protocol.py | framing.rs | 256-byte buffer cap, overflow clears |
| cbus/protocol/cbus_protocol.py | framing.rs | decode loop + echo hook |
| cbus/protocol/pciprotocol.py | pci.rs | confirmation allocator/retry/timesync/reset |
| cbus/protocol/pciserverprotocol.py | cbus-simulator | server mode |
| cbus/protocol/interrogator.py | cbus-tools interrogate | uses raw TCP like Python |
| cbus/transport/{base,tcp,serial}.py | conn.rs | reconnect loop semantics |
| cbus/esp32/connection.py | conn.rs + cli.rs | `--esp32-wifi` = TCP, `--esp32-serial` = serial |
| cbus/esp32/discovery.py | deferred | cargo feature stub returning error |
| cbus/esp32/emulator/*, cbus/esp32/ha_discovery.py | not migrated | see scope |
| cbus/daemon/cli.py | cmqttd/src/cli.rs | clap, same flags |
| cbus/daemon/cmqttd.py | cmqttd/src/main.rs | wiring |
| cbus/daemon/mqtt_gateway.py | cmqttd/src/gateway.rs + cbus-mqtt | pure parts in cbus-mqtt |
| cbus/daemon/topics.py | cbus-mqtt/src/topics.rs | vector-checked |
| cbus/toolkit/cbz.py | cbus-mqtt/src/cbz.rs | roxmltree+zip |
| cbus/toolkit/dump_labels.py | cbus-tools dump-labels | JSON output parity is best-effort (no vectors) |
| cbus/toolkit/periodic.py | cmqttd/src/throttle.rs | 0.2 s mpsc drain |
| cbus/toolkit/graph.py, cbus/tools/fetch_protocol_docs.py | dropped | |
| cbus/tools/decode_packet.py | cbus-tools decode | |
| cbus/web/* | deferred | |

## 3. Dependency choices (rust/Cargo.toml workspace deps)

| Crate | Version | Why this one |
|---|---|---|
| tokio (features: full) | 1.x | the async runtime; timers (`sleep`, `interval`), TCP, mpsc — direct analogue of asyncio usage |
| rumqttc | 0.24+ | mature pure-Rust MQTT client; **use `MqttOptions` default v4 (3.1.1)** — the harness broker rejects v5. Alternatives rejected: paho-mqtt (C bindings, build pain), mqtt-async-client (unmaintained) |
| tokio-serial | 5.x | serial for tokio (mio-serial); 9600 8N1 like pyserial-asyncio |
| clap (derive) | 4.x | CLI parity with argparse incl. `-b/-p/-t/-T/-C/-P/-N/-v` short flags |
| serde, serde_json | 1.x | canonical packet JSON, vectors, HA discovery payloads |
| chrono | 0.4 | clock SALs; `weekday().num_days_from_monday()` == Python `date.weekday()` |
| roxmltree | 0.20 | read-only XML DOM — 1:1 port of the `xml.etree` walk in cbz.py (NB: Python no longer uses lxml). Rejected quick-xml/serde: CBZ mixes attributes and case-insensitive tags, easier hand-walked |
| zip | 2.x | .cbz is a 1-file zip of the XML |
| tracing, tracing-subscriber | 0.1/0.3 | logging; `-v DEBUG` → EnvFilter level |
| thiserror | 1.x | error enums in the libs |
| hex | 0.4 | vector wire_hex handling |
| (deferred, feature "mdns") mdns-sd | — | only if `--esp32-discover` is ever ported |

No async-trait needed if `PciClient` is a struct with event channel (recommended, see Task 5.2).

## 4. Semantics traps — read before writing any code

Each trap cites the Python source and, where applicable, the vector ids that pin it (grep the id prefix in `rust-migration-harness/vectors/`).

### Wire format & checksums
1. **Checksum** = two's complement of the byte sum: `((!sum & 0xff) + 1) & 0xff` (`cbus/common.py:371`). Empty input → 0. In Rust use `u32` accumulate + mask, or `wrapping` ops — no panics on overflow. Vectors: `checksum.jsonl` (265, includes empty + 256-byte input).
2. **Base16 is UPPERCASE-only.** Decoder must reject lowercase hex (`packet.py:173-176` checks against `HEX_CHARS = b'0123456789ABCDEF'`) → `Invalid`. Vector `fp-*-lowercase-hex-input`. Encoder must emit uppercase.
3. **Framing:** client commands end `\r`; PCI responses end `\r\n`; confirmation replies (`h.`/`h#`) have **no** terminator and are matched by *first byte ∈ codes* + second byte `.`/`#`, consuming exactly 2 (`packet.py:98-101`). `+` and `!` consume exactly 1 even with trailing bytes (`fp-*-power-on-double`).
4. **flags byte** = `dat | ((rc & 0x02) << 3) | (dp?0x20:0) | (priority << 6)` — note the Python masks `rc` with `0x02` not `0x03` (`base_packet.py:53-57`). Keep bug-for-bug.
5. **Priority defaults differ:** most packets CLASS_4 (0), DeviceManagement CLASS_2 (2) → DM flags byte `0xA3` (`dm_packet.py:28`).
6. **DM packets** encode `[flags, param, 0x00, value]`; decode requires byte1==0 and length exactly 3 after source strip (`dm_packet.py:42-63`).
7. **PM packets** encode `[flags, app, 0x00, sals..., ck?]`; decode raises on routing byte ≠ 0 (vector `fp-*-pm-nonzero-routing` → invalid).
8. **PP packets**: `[flags, unit, 0x00, cals...]` or bridged `[flags, bridge, bridge_len_code, hops..., unit, cals...]` with `BRIDGE_LENGTHS = {0x09:0, 0x12:1, 0x1B:2, 0x24:3, 0x2D:4, 0x36:5}` (`common.py:333`). Bridged packets **decode** but their encode raises in Python → decode-only in Rust too (vectors `fp-*-pp-bridged-*` have `expect_reencode: null`).
9. **from_pci frames carry a source address** byte right after flags; client frames don't. On decode from_pci, `source_address` is set **only if truthy** — source 0 leaves confirmation as-is (`packet.py:267-272`; don't overthink: match vectors).

### The decoder state machine (`packet.py` — port decode.rs from this exactly)
10. **Client-side prefixes:** `~` reset (consume 1); `|`+CR / `||`+CR smart-connect; literal `null` consumed silently (4 bytes); data before `?` (when `?` precedes CR) discarded up to and incl. `?`; `@` = once-off basic mode → forces `checksum=false` AND marks the frame as "device-management CAL" style; frames with no `\` and no `@` are *also* device-management CAL style (`packet.py:145-154`).
11. **Confirmation char detection (to-PCI):** if the last byte of the CR-stripped command isn't an uppercase hex char it's a confirmation code; if it's outside `g..z` → strict: Invalid, lenient: warn + accept (`packet.py:156-171`; vectors `tp-*-bad-conf-code-*`).
12. **Direct CAL replies (working-tree specialty):** for from-PCI frames where `flags & 0x07 ∈ {0,1,2,4,7}` **and** dp bit clear, the *entire* payload (including the flags byte!) is parsed as a CAL stream and wrapped in a PointToPoint packet with `unit_address: 0`, `source_address: null` (`packet.py:209-228`). This is how CNI interrogation replies (`89...`, `82...`, `87...`) decode. Corollary: a REPLY CAL whose header low-3-bits are 3, 5 or 6 does NOT take this path (it aliases an addressed packet type) — the vectors only contain non-aliasing lengths; do not "fix" this.
13. **EXSTAT/standard-status never hit the direct-CAL path at top level:** `0xE0..0xFF` headers have the dp bit (0x20) set → they fall through to the DM branch and typically decode as Invalid; real EXSTAT arrives *inside* PP packets (`86 <src> <unit> 00 F9 ...`). Standard status (`0xC0..0xDF` first byte) hits the direct path but `decode_cal` raises NotImplemented → Invalid.
14. **Bare-CAL returns:** the "device-management CAL" client path returns a *bare CAL* (not a packet): JSON `{"type":"cal", ...}` — but only when the dp bit of the flags byte is clear; `A3...` frames have dp set and decode as DM packets first (`packet.py:240-247`).
15. **CAL stream lengths:** REPLY header `0x80|(len(data)+1)`; total CAL size = low-5-bits + 1. EXSTAT header `0xE0|(3+len(report))`; total = low-5-bits + 1. Reply data is capped at 0x1E bytes on encode (`reply.py:55-57`, vector `en-*-pp-reply-clipped`).
16. **Checksum failure:** strict → Invalid; lenient → warn, still *strip* the checksum byte and decode (vectors `fp-*-bad-checksum-*`).

### Applications / SALs
17. **Application registry** covers ONLY: 0xFF status-request, 0xDF clock, 0xCB enable, 0x30–0x5F lighting, 0x19 temperature (`application/__init__.py:30-36`). Anything else (e.g. 0xCA trigger/hvac) → KeyError → Invalid (vector `fp-*-pm-unregistered-app-ca`).
18. **Lighting decode is *forgiving*:** unknown command code → warn + stop, returning SALs parsed so far; 1 stray byte → warn + stop; ramp missing its level byte → warn + drop that SAL (`lighting.py:79-104`). A PM packet with zero SALs is still a valid packet.
19. **Ramp rates:** duration→code snaps *up* through the ordered table (0,4,8,12,20,30,40,60,90,120,180,300,420,600,900,1020 s ↔ codes 0x02,0x0A,0x12,0x1A,0x22,0x2A,0x32,0x3A,0x42,0x4A,0x52,0x5A,0x62,0x6A,0x72,0x7A); durations >1020 s snap to 0x7A (`common.py:338-352`). `ramp_rates.jsonl` is exhaustive 0..1024. The SAL keeps the *original* duration in JSON; snapping happens at encode.
20. **Temperature:** value = `byte / 4.0` as f64; encode = `(temp * 4) as u8` (truncation, not rounding); encode validates 0.0..=63.75 (`temperature.py:139-153`).
21. **Clock:** time SAL = `[0x0D, 0x01, h, m, s, 0xFF]` (DST byte always 0xFF on encode, ignored on decode); date SAL = `[0x0E, 0x02, year_be_u16, month, day, weekday]` with weekday Monday=0 (Python `date.weekday()`; chrono `num_days_from_monday`). Decode ignores weekday. `clock_update_sal(datetime)` yields **date SAL then time SAL** in one PM packet (`clock.py:260-278`). Unknown clock variable: Python double-skips the buffer (a bug — `clock.py:175` returns `data[data_length:]` *after* already advancing) — keep it.
22. **Status request:** three wire forms — `0x7A app block` (binary), `0xFA app block` (deprecated, decode-only, re-encodes as 0x7A), `0x73 0x07 app block` (level). `block & 0x1F != 0` → ValueError → Invalid. Encode masks block with `0xE0` (`status_request.py:42-99`). Status requests ride in PM packets with application byte 0xFF.
23. **Enable/temperature length nibble check:** `(command_code & 0x07) != 2` → warn + stop (`enable.py:77`, `temperature.py:88`).

### Status reports
24. **Binary report:** 4 group-states per byte, 2 bits each, LSB-first; encode pads with MISSING(0) to a multiple of 4 (`report.py:96-127`).
25. **Manchester (level report):** nibble table `[0xA, 0x9, 0x6, 0x5]` encodes 2 bits each, LSB-first across the 4 nibbles of 2 bytes; ANY invalid nibble → level `None`; `None` encodes as `0x0000` (`report.py:34-64`). Level report decode requires even byte count. `encode.jsonl` has all 256 levels.

### PCI client behaviour (pci.rs / cmqttd)
26. **Confirmation codes:** the pool is the byte string `hijklmnopqrstuvwxyzg` — *this order*, h first, g last (`common.py:327`). Allocation is round-robin from `next_index` skipping in-use codes; on exhaustion force-release the oldest; codes time out after 30 s; when >90% in use, force-release the oldest 25% (`pciprotocol.py:557-633`, `constants.py`). The harness asserts only: valid codes, distinct within the init sequence, and identical bytes on retransmit.
27. **Retry:** unconfirmed packets are retransmitted **byte-identical** (same confirmation char) every 1 s, max 3 total attempts, then abandoned + code released (`pciprotocol.py:297-372`; behavioral `retry-unconfirmed-frame`).
28. **Send pacing:** every transport write is preceded by a 0.1 s sleep (`PACKET_SEND_DELAY_SECONDS`, `pciprotocol.py:698-700`).
29. **PCI init sequence** (exact, in order): 3× `~\r`; `|\r`; then four basic-mode (no `\`, no checksum) DM commands `A32100FF`, `A32200FF`, `A342000E`, `A3300079`, each + confirmation char + `\r` (`pciprotocol.py:731-791`). Note the init DM frames go through the confirmation/retry machinery like any other command.
30. **Timesync:** every `-T` seconds send one PM packet holding date+time SALs; `-T 0` disables. On receiving a clock request SAL, reply with the same (unless `-C`).
31. **Buffer cap:** receive buffer > 256 bytes → drop the whole buffer (log, don't crash) (`buffered_protocol.py:80-93` + `MAX_BUFFER_SIZE`).
32. **handle_data consumption loop:** decode returns (packet, consumed); consumed>0 → loop again; 0 → wait for more data (`cbus_protocol.py:57-82`).

### cmqttd / MQTT
33. **Topic IDs** (recent-commit-sensitive!): default lighting app 56 → topics use the bare GA (`cbus_10`), display strings use 3-digit (`010`); any other app → `cbus_<app:03d>_<ga:03d>` in *both* topics and display (`daemon/topics.py:32-42`). Pinned exhaustively by `mqtt_topics.jsonl` and behaviorally by the `cbus_048_011` command test.
34. **Discovery payloads:** exact JSON in `ha_discovery.jsonl`, including abbreviated keys (`cmd_t`, `stat_t`), `unique_id` formats `cbus_light_<id>` / `cbus_bin_sensor_<id>`, device blocks, `sw_version` string `"cmqttd https://github.com/mitchell-johnson/cbus"`. Config+state publishes: qos 1, retain true. Set-topic subscription qos 2.
35. **Startup MQTT sequence:** subscribe `homeassistant/light/#`; publish the `cbus_cmqttd` meta binary-sensor config; publish configs for every labelled group from `-P`; enqueue 8 level status requests (blocks 0..224) for **each** lighting app 0x30..0x5F → 384 throttled commands at 0.2 s (`mqtt_gateway.py:156-179, 269-271`).
36. **Command handling:** only topics `homeassistant/light/cbus_*/set`; JSON body; `state` required (case-insensitive "ON"); `brightness` default 255 clamped 0..255 (int cast); `transition` default 0 clamped ≥0; ON+255+0 → group_on, else ramp; OFF → group_off; after the C-Bus send, echo the state back to MQTT with `cbus_source_addr: null` (`mqtt_gateway.py:206-284`).
37. **Level report → MQTT:** per level: 0→off, 255→on, else ramp(duration 0); null skipped; the group counter advances for *every* slot including nulls; events use source_addr 0; unpublished groups get a lazy discovery config first (`mqtt_gateway.py:115-129, 366-368`).
38. **Throttler:** single queue, one action per 0.2 s, max 1000 queued, drop+warn when full (`toolkit/periodic.py`). MQTT set-commands share the queue with status requests — commands drain *behind* them; the harness depends on this ordering (only with generous timeouts).
39. **MQTT version:** 3.1.1 (level 4). rumqttc: `MqttOptions::new(client_id, host, port)` is v4 by default — do not use the `v5` module.

### Misc
40. **bytes↔str:** all wire I/O is bytes; base16 bodies are ASCII; JSON payloads UTF-8. Never lossy-convert wire bytes through String.
41. **Temperature JSON floats:** quarters are exact in IEEE754; serialize as f64 (serde_json default) — `25.0` round-trips.
42. **CBZ:** accept both a 1-file zip and bare XML; tag/attr matching is case-insensitive with `_` stripped and trailing `s` trimmed (`cbz.py:42-45`); labels output = `{app_addr: (app_name, {ga: label})}`; `-N` selects a network by TagName, default = first network (`cmqttd.py:46-87`).

## 5. Phased task breakdown

Phases are ordered so `run.sh` becomes progressively greener:
vectors (checksum/ramp → protocol → mqtt) → transports/PCI → daemon behavioral → tools/simulator → cutover.

---

### Phase 0 — Workspace scaffolding

#### Task 0.1: Create the Cargo workspace

**Files:** Create `rust/Cargo.toml`, `rust/.gitignore`, and empty lib crates.

**Step 1:** Create `rust/Cargo.toml`:

```toml
[workspace]
resolver = "2"
members = [
    "cbus-protocol",
    "cbus-mqtt",
    "cbus-transport",
    "cmqttd",
    "cbus-vector-check",
    "cbus-simulator",
    "cbus-tools",
]

[workspace.package]
edition = "2021"
license = "LGPL-3.0-or-later"

[workspace.dependencies]
tokio = { version = "1", features = ["full"] }
rumqttc = "0.24"
tokio-serial = "5"
clap = { version = "4", features = ["derive"] }
serde = { version = "1", features = ["derive"] }
serde_json = "1"
chrono = "0.4"
roxmltree = "0.20"
zip = { version = "2", default-features = false, features = ["deflate"] }
tracing = "0.1"
tracing-subscriber = { version = "0.3", features = ["env-filter"] }
thiserror = "1"
hex = "0.4"
```

**Step 2:** `cargo new --lib rust/cbus-protocol` etc. for all 7 members (`--bin` for cmqttd, cbus-vector-check, cbus-simulator, cbus-tools). Each member `Cargo.toml` uses `edition.workspace = true` and pulls needed `workspace = true` deps.

**Step 3:** `echo 'target/' > rust/.gitignore`.

**Step 4:** Verify: `cd rust && cargo build --workspace` → compiles (empty crates).

**Step 5:** Commit: `git add rust && git commit -m "rust: workspace scaffolding"`.

---

### Phase 1 — cbus-protocol core (vector-driven TDD)

Work loop for every task in this phase: implement → add a focused Rust unit test from the cited Python test/vector → `cargo test -p cbus-protocol` → commit. Full vector validation lands in Phase 2.

#### Task 1.1: common.rs — constants, checksum, ramp rates

**Files:** Create `rust/cbus-protocol/src/common.rs`; wire into `lib.rs`.

**Step 1:** Port from `cbus/common.py`:

```rust
pub const HEX_CHARS: &[u8] = b"0123456789ABCDEF";
pub const END_COMMAND: &[u8] = b"\r";
pub const END_RESPONSE: &[u8] = b"\r\n";
pub const MIN_MESSAGE_SIZE: usize = 2;
pub const MAX_BUFFER_SIZE: usize = 256;
pub const CONFIRMATION_CODES: &[u8] = b"hijklmnopqrstuvwxyzg";
pub const MIN_GROUP_ADDR: u8 = 0;
pub const MAX_GROUP_ADDR: u8 = 255;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DestinationAddressType { /* Unset=0, PointToPointShort=1, ... per common.py:44 */ }

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PriorityClass { Class4 = 0, Class3 = 1, Class2 = 2, Class1 = 3 }

pub fn cbus_checksum(data: &[u8]) -> u8 {
    let sum: u32 = data.iter().map(|&b| b as u32).sum();
    (((!sum & 0xff) + 1) & 0xff) as u8
}
pub fn add_cbus_checksum(data: &[u8]) -> Vec<u8> { /* append */ }
pub fn validate_cbus_checksum(data: &[u8]) -> bool { /* last byte check; empty→false */ }

pub const LIGHT_RAMP_RATES: &[(u8, u32)] = &[
    (0x02, 0), (0x0A, 4), (0x12, 8), (0x1A, 12), (0x22, 20), (0x2A, 30),
    (0x32, 40), (0x3A, 60), (0x42, 90), (0x4A, 120), (0x52, 180),
    (0x5A, 300), (0x62, 420), (0x6A, 600), (0x72, 900), (0x7A, 1020),
];
pub fn duration_to_ramp_rate(seconds: u32) -> u8 { /* first entry with seconds <= d, else 0x7A */ }
pub fn ramp_rate_to_duration(code: u8) -> Option<u32> { /* exact lookup */ }
```

Also port the `LightCommand` values (ON=0x79, OFF=0x01, TERMINATE_RAMP=0x09), `CAL` command constants (RESET 0x08, RECALL 0x1A, IDENTIFY 0x21, GET_STATUS 0x2A, ACK 0x32, REPLY 0x80, STANDARD_STATUS 0xC0, EXTENDED_STATUS 0xE0), `GroupState`, `ExtendedCALType`, `BRIDGE_LENGTHS`, `Application` bounds (LIGHTING_FIRST 0x30, LIGHTING 0x38, LIGHTING_LAST 0x5F, TEMPERATURE 0x19, CLOCK 0xDF, ENABLE 0xCB, STATUS_REQUEST 0xFF).

**Step 2:** Unit tests (from `tests/test_protocol_exhaustive.py:35-70` and `checksum.jsonl` samples): checksum of `05 38 00 79 01` sums to 0 after append; all-zero → 0; empty → 0; `duration_to_ramp_rate(0)==0x02`, `(1)==0x0A`, `(1021)==0x7A`.

**Step 3:** `cargo test -p cbus-protocol` → PASS. Commit.

#### Task 1.2: report.rs — manchester + status reports

**Files:** Create `rust/cbus-protocol/src/report.rs`.

**Step 1:** Port `cbus/protocol/cal/report.py` exactly:

```rust
const MANCHESTER_NIBBLES: [u8; 4] = [0b1010, 0b1001, 0b0110, 0b0101];

pub fn manchester_decode(b: [u8; 2]) -> Option<u8> { /* any nibble not in table -> None */ }
pub fn manchester_encode(value: Option<u8>) -> [u8; 2] { /* None -> [0,0] */ }

#[derive(Debug, Clone, PartialEq)]
pub enum StatusReport {
    Binary(Vec<u8>),        // group states 0..=3
    Level(Vec<Option<u8>>),
}
impl StatusReport {
    pub fn block_type(&self) -> u8 { /* Binary=0, Level=7 */ }
    pub fn encode(&self) -> Vec<u8> { /* binary: pack 4/byte LSB-first, pad w/ 0 */ }
    pub fn decode_binary(data: &[u8]) -> Self { /* 4 states per byte */ }
    pub fn decode_level(data: &[u8]) -> Result<Self, DecodeError> { /* odd len -> Err */ }
}
```

**Step 2:** Unit tests from `tests/test_cal.py:81-90`: `manchester_decode([0xaa,0xaa])==Some(0)`, `([0x00,0x00])==None`, `([0x95,0x99])==Some(0x57)`, `([0x55,0x55])==Some(0xff)`; encode inverses. Commit.

#### Task 1.3: cal.rs — CAL types

**Files:** Create `rust/cbus-protocol/src/cal.rs`.

**Step 1:** Port identify/recall/reply/extended (+ StandardCAL encode for the simulator):

```rust
#[derive(Debug, Clone, PartialEq)]
pub enum Cal {
    Identify { attribute: u8 },
    Recall { param: u8, count: u8 },
    Reply { parameter: u8, data: Vec<u8> },
    ExtendedStatus { externally_initiated: bool, child_application: u8,
                     block_start: u8, report: StatusReport },
}
impl Cal {
    pub fn encode(&self) -> Vec<u8> { /* per cal/*.py; Reply clips data to 0x1E */ }
    /// One CAL from the front of `data`; returns (cal, consumed).
    pub fn decode_one(data: &[u8]) -> Result<(Cal, usize), DecodeError> {
        /* port pp_packet.py:82-112: REPLY 0x80.. len=low5+1;
           STANDARD_STATUS 0xC0.. -> Err(NotImplemented);
           EXTENDED_STATUS 0xE0.. len=low5+1, coding byte splits binary/level;
           else: 0x21 -> Identify (consumes 2), 0x1A -> Recall (consumes 3),
           unknown -> Err */
    }
}
```

**Step 2:** Unit tests: identify encode `21 02`; recall `1A FA 2C`; reply header math; EXSTAT round trip with both report kinds; truncated reply → Err. Use bytes from vectors `fp-*-pp-identify-*`, `fp-*-pp-reply-len*`. Commit.

#### Task 1.4: sal/ — all five applications

**Files:** Create `rust/cbus-protocol/src/sal/{mod,lighting,clock,temperature,enable,status_request}.rs`.

**Step 1:** Model:

```rust
#[derive(Debug, Clone, PartialEq)]
pub enum Sal {
    LightingOn { application: u8, group_address: u8 },
    LightingOff { application: u8, group_address: u8 },
    LightingTerminateRamp { application: u8, group_address: u8 },
    LightingRamp { application: u8, group_address: u8, duration: u32, level: u8 },
    ClockUpdateTime { hour: u8, minute: u8, second: u8 },
    ClockUpdateDate { year: u16, month: u8, day: u8 },
    ClockRequest,
    TemperatureBroadcast { group_address: u8, temperature: f64 },
    EnableSetNetworkVariable { variable: u8, value: u8 },
    StatusRequest { level_request: bool, group_address: u8, child_application: u8 },
}
impl Sal {
    pub fn application(&self) -> u8 { /* clock 0xDF, enable 0xCB, temp 0x19,
        status 0xFF, lighting = stored application */ }
    pub fn encode(&self) -> Vec<u8>;
}
/// Application dispatch: decode the SAL payload of a PM packet.
/// Returns Ok(sals) even when trailing garbage forced an early stop (trap 18).
/// Returns Err only where Python raises (unregistered app: caller side;
/// status-request bad block / unknown status type).
pub fn decode_sals(app: u8, data: &[u8]) -> Result<Vec<Sal>, DecodeError>;
```

`decode_sals` matches on app byte: 0x30..=0x5F lighting, 0xDF clock, 0xCB enable, 0x19 temperature, 0xFF status-request, else `Err(UnregisteredApplication)`.

**Step 2:** Port each application decoder, matching the warn-and-stop semantics in traps 18–23 exactly. Clock encode: DST byte 0xFF; date weekday `chrono::NaiveDate::from_ymd_opt(y,m,d).unwrap().weekday().num_days_from_monday() as u8`.

**Step 3:** Unit tests per app using bytes from `tests/test_lighting.py`, `tests/test_clock.py`, `tests/test_temperature.py`, `tests/test_enable.py` (read them; e.g. lighting: `38 00 79 08` payload decodes to on(8)). Commit after each sub-module.

#### Task 1.5: packet.rs — packet model + encoders

**Files:** Create `rust/cbus-protocol/src/packet.rs`.

**Step 1:**

```rust
#[derive(Debug, Clone, PartialEq)]
pub enum Packet {
    // specials
    PowerOn, PciError, Reset, SmartConnect,
    Confirmation { code: u8, success: bool },
    Invalid,                       // payload/exception not modelled
    BareCal(Cal),                  // client DM-CAL path (trap 14)
    DeviceManagement { meta: Meta, parameter: u8, value: u8 },
    PointToMultipoint { meta: Meta, application: u8, sals: Vec<Sal> },
    PointToPoint { meta: Meta, unit_address: u8, bridged: bool,
                   hops: Vec<u8>, cals: Vec<Cal> },
}
#[derive(Debug, Clone, PartialEq)]
pub struct Meta {
    pub checksum: bool,
    pub priority_class: u8,          // 0..3
    pub source_address: Option<u8>,
    pub confirmation: Option<u8>,    // the confirmation *char*
}
impl Packet {
    /// base16-ASCII body (BasePacket.encode_packet) or raw token for specials.
    pub fn encode_packet(&self) -> Result<Vec<u8>, EncodeError>;
    /// raw binary (BasePacket.encode) incl. checksum when meta.checksum.
    pub fn encode(&self) -> Result<Vec<u8>, EncodeError>;
    fn flags(&self) -> u8 { /* trap 4 & 5 */ }
}
```

Encode rules per packet type from the Python `encode()` methods; source_address included in the flags-header when `Some` (`base_packet.py:59-65`). Specials: Reset→`~`, SmartConnect→`|`, PowerOn→`++`, PciError→`!`, Confirmation→`h.`/`h#`; their `encode_packet` == `encode`. Bridged PP encode → `Err(NotImplemented)`.

**Step 2:** Unit tests against `encode.jsonl` samples (hand-pick ~10 lines incl. `en-*-pm-ramp-snap-1021`, `en-*-dm-30-79-cs0`, `en-*-pp-reply-clipped`). Commit.

#### Task 1.6: decode.rs — the decoder

**Files:** Create `rust/cbus-protocol/src/decode.rs`.

**Step 1:**

```rust
pub struct DecodeResult { pub packet: Option<Packet>, pub consumed: usize }
pub fn decode_packet(data: &[u8], checksum: bool, strict: bool,
                     from_pci: bool) -> DecodeResult;
```

Port `cbus/protocol/packet.py:41-276` **line by line** — every branch is
pinned by a vector. Order of checks matters (traps 3, 10–16). Any error
inside the body maps to `Packet::Invalid` with the same `consumed` as
Python (consumed is computed *before* body parsing — it's the framing
position, not a parse position).

**Step 2:** Unit tests: the golden literals from `tests/test_interrogator.py:31-84` (direct CAL replies + PP EXSTAT) and `tests/test_cal.py:47-79`. Commit.

#### Task 1.7: json.rs — canonical JSON codec

**Files:** Create `rust/cbus-protocol/src/json.rs` (feature-gate not needed; serde is cheap).

**Step 1:** Implement `packet_to_json(&Option<Packet>) -> serde_json::Value` and `packet_from_json(&Value) -> Result<PacketOrSalOrCalOrReport>` following **exactly** the schema in `rust-migration-harness/README.md §5` (which mirrors `rust-migration-harness/lib/pyjson.py` — read both). Notes:
- key names/spellings matter (`externally_initiated` correct spelling in JSON).
- `confirmation` is a 1-char string; `data_hex` lowercase hex.
- `temperature` must serialize as a JSON number equal to Python's (f64).
- `packet_from_json` also accepts `{"type":"sal"|"cal"|"binary_report"|"level_report"}` for standalone encode vectors.

**Step 2:** Unit test: parse a handful of `expect_packet` values from the vector files (include one of each type), round-trip to_json(from_json(v)) == v. Commit.

---

### Phase 2 — cbus-vector-check (protocol vectors green)

#### Task 2.1: implement the checker for the 5 protocol files

**Files:** Create `rust/cbus-vector-check/src/main.rs` (deps: cbus-protocol, cbus-mqtt later, serde_json, hex).

**Step 1:** Implement per the contract (harness README §1 + §4): read every `*.jsonl` in `argv[1]`; dispatch by filename; for files not yet supported, count every vector as FAILED with reason "unimplemented suite" (never skip silently). Support an optional `--file <name>` filter for development. Print failures (id + reason, cap 50) and the final line `protocol-vectors: <passed>/<total> PASS|FAIL`; exit 0 iff all pass.

Checks per file:
- `decode_from_pci.jsonl` / `decode_to_pci.jsonl`: run `decode_packet`, compare consumed, `packet_to_json`, and (when non-null) `expect_reencode` vs `encode_packet()` interpreted as latin-1 string.
- `encode.jsonl`: `packet_from_json` → `encode()` hex, and `encode_packet()` when the field is present.
- `checksum.jsonl`, `ramp_rates.jsonl`: direct function calls.
- `mqtt_topics.jsonl`, `ha_discovery.jsonl`: fail with "unimplemented suite" until Phase 3.

**Step 2:** Verify progressively:
```sh
cd rust && cargo build --workspace
./target/debug/cbus-vector-check ../rust-migration-harness/vectors --file checksum.jsonl
./target/debug/cbus-vector-check ../rust-migration-harness/vectors --file ramp_rates.jsonl
./target/debug/cbus-vector-check ../rust-migration-harness/vectors --file encode.jsonl
./target/debug/cbus-vector-check ../rust-migration-harness/vectors --file decode_from_pci.jsonl
./target/debug/cbus-vector-check ../rust-migration-harness/vectors --file decode_to_pci.jsonl
```
Iterate on cbus-protocol until each reports full PASS. Expect the decode files to flush out a dozen edge-case mismatches — fix in the library, never by special-casing the checker.

**Step 3:** Commit: "rust: cbus-protocol passes all decode/encode/checksum/ramp vectors (2342/2342 of protocol suites)".

---

### Phase 3 — cbus-mqtt (topics, discovery, CBZ) → ALL vectors green

#### Task 3.1: topics.rs

**Files:** Create `rust/cbus-mqtt/src/topics.rs`.

**Step 1:** Port `cbus/daemon/topics.py` exactly (trap 33):

```rust
pub const LIGHT_TOPIC_PREFIX: &str = "homeassistant/light/cbus_";
pub const BINSENSOR_TOPIC_PREFIX: &str = "homeassistant/binary_sensor/cbus_";
pub fn ga_string(group: u8, app: u8, zeros: bool) -> String;
pub fn set_topic(group: u8, app: u8) -> String;      // + state/conf/bin variants
/// parse `homeassistant/light/cbus_.../set`-style topic → (group, app).
pub fn topic_group_address(topic: &str) -> Result<(u8, u8), TopicError>;
```
Parse rules: strip prefix; take the segment before the first `/`; split on `_`: one part → app=56, two parts → (app, ga); integer parse accepts leading zeros; group must be 0..=255 (parse into i64 then range-check so `999` errors like Python's `check_ga`).

**Step 2:** vector-check support for `mqtt_topics.jsonl` (both `format` and `parse` kinds) in cbus-vector-check. Verify: `--file mqtt_topics.jsonl` → 596/596. Commit.

#### Task 3.2: discovery.rs — HA discovery payload builders

**Files:** Create `rust/cbus-mqtt/src/discovery.rs`.

**Step 1:** Port the payload construction in `cbus/daemon/mqtt_gateway.py:286-345` into pure functions:

```rust
pub type AppLabels = BTreeMap<u8, (String, BTreeMap<u8, String>)>;
pub struct LightDiscovery {
    pub subscribe_topic: String,   // set topic, qos 2
    pub light_config_topic: String,
    pub light_config: serde_json::Value,
    pub sensor_config_topic: String,
    pub sensor_config: serde_json::Value,
}
pub fn light_discovery(group: u8, app: u8, labels: Option<&AppLabels>) -> LightDiscovery;
pub fn meta_discovery() -> (String, serde_json::Value);  // cbus_cmqttd root device
```
Copy field-for-field from `ha_discovery.jsonl` records — including `sw_version`, `via_device`, the `connections` nested arrays (strings, not ints) and the name fallback logic (`default_light_name` uses the *padded* ga_string).

**Step 2:** vector-check support for `ha_discovery.jsonl`: for each record build with the record's `labels` (or None) and compare topics + configs as `serde_json::Value` equality, plus subscribe topic/qos and qos/retain constants. Verify 263/263.

**Step 3:** Full run: `./target/debug/cbus-vector-check ../rust-migration-harness/vectors` → `protocol-vectors: 3201/3201 PASS`. Commit.

#### Task 3.3: cbz.rs — Toolkit project labels

**Files:** Create `rust/cbus-mqtt/src/cbz.rs`.

**Step 1:** Implement:

```rust
/// Read a .cbz (1-file zip) or bare XML Toolkit backup and extract
/// {app_addr: (app_name, {group: label})} for the named network
/// (None = first). Port of cmqttd.read_cbz_labels + toolkit/cbz.py.
pub fn read_cbz_labels(path: &Path, network: Option<&str>)
    -> Result<AppLabels, CbzError>;
```
Implementation: try `zip::ZipArchive` — expect exactly 1 file ending `.xml`; else parse the file directly with roxmltree. Walk: Installation → Project → Network (match `TagName` if `network` given) → Application* → Group*, reading `TagName`/`Address` as *children or attributes* case-insensitively (normalise names like `cbz.py:42-45`: lowercase, strip `_`, trim one trailing `s`).

**Step 2:** Unit test against the harness fixture:
```rust
let labels = read_cbz_labels(Path::new("../../rust-migration-harness/fixtures/project.xml"), None)?;
assert_eq!(labels[&56].0, "Lighting");
assert_eq!(labels[&56].1[&1], "Kitchen Bench");
assert_eq!(labels[&56].1[&10], "Lounge");
assert_eq!(labels[&48].1[&11], "Deck");
```
(Use a path helper via `env!("CARGO_MANIFEST_DIR")`.) Commit.

---

### Phase 4 — cbus-transport (framing, PCI client, connections)

#### Task 4.1: framing.rs

**Files:** Create `rust/cbus-transport/src/framing.rs`.

**Step 1:** Port `buffered_protocol.py` + `cbus_protocol.py` as a plain struct (no async):

```rust
pub struct FrameBuffer { buf: Vec<u8>, from_pci: bool, checksum: bool }
impl FrameBuffer {
    pub fn new_client() -> Self { /* from_pci=true, checksum=true */ }
    pub fn new_server() -> Self { /* from_pci=false, checksum=false */ }
    /// Feed rx bytes; return every decoded packet. Overflow (>256) clears
    /// the buffer and returns what was decodable before.
    pub fn feed(&mut self, data: &[u8]) -> Vec<Packet>;
}
```
Loop decode_packet until consumed==0 (trap 31, 32). Also expose the count of consumed bytes per iteration for the server-mode echo hook.

**Step 2:** Unit test: feed the PCI init reply fragments byte-by-byte (split a confirmation `h.` across two feeds) and assert reassembly. Commit.

#### Task 4.2: pci.rs — the PCI client state machine

**Files:** Create `rust/cbus-transport/src/pci.rs`.

This is the trickiest async port. Recommended shape — a task owning the
socket + state, with an mpsc command channel and a broadcast/mpsc event
channel (mirrors how `mqtt_gateway.CBusHandler` consumes `PCIProtocol`):

```rust
pub enum CBusEvent {
    Confirmation { code: u8, success: bool },
    LightingOn { source: u8, app: u8, group: u8 },
    LightingOff { source: u8, app: u8, group: u8 },
    LightingRamp { source: u8, app: u8, group: u8, duration: u32, level: u8 },
    LevelReport { app: u8, block_start: u8, levels: Vec<Option<u8>> },
    ClockRequest { source: u8 },
    PciError, PowerOn, ConnectionLost,
}
pub struct PciClient { /* cmd tx */ }
impl PciClient {
    pub async fn send_packet(&self, p: Packet, confirmation: bool, basic: bool) -> ...;
    pub async fn lighting_group_on(&self, groups: &[u8], app: u8) -> ...;   // ≤9 groups
    pub async fn lighting_group_off(...); pub async fn lighting_group_ramp(...);
    pub async fn request_status(&self, block: u8, app: u8) -> ...;
    pub async fn clock_datetime(&self, when: Option<DateTime<Local>>) -> ...;
    pub async fn pci_reset(&self) -> ...;
}
```

Port these behaviours exactly (traps 26–30):
1. `_prepare_packet` (`pciprotocol.py:635-684`): `\` prefix unless basic/special; append allocated confirmation char; append `\r`.
2. Confirmation allocator (`pciprotocol.py:557-633`): round-robin index over `CONFIRMATION_CODES`, in-use map with timestamps, 30 s timeout sweep, force-release oldest at >90% (release 25%), oldest-release on exhaustion.
3. Pending-confirmation retry task (`pciprotocol.py:297-372`): every 1 s, resend byte-identical prepared frames older than 1 s, attempts capped at 3, then release.
4. 0.1 s sleep before every write (`_send_packet`).
5. `connection_made` equivalent: on connect, clear state, run `pci_reset()` (3 resets, `|`, the four DM commands — trap 29), spawn timesync loop if `-T > 0`, spawn retry task.
6. Event dispatch from decoded packets (`handle_cbus_packet`, `pciprotocol.py:157-208`): confirmations release codes; PM lighting/clock SALs and PP ExtendedStatus level reports become events (binary reports are ignored — Python passes on them).

**Step 2:** Unit tests with a `tokio::io::duplex` transport: assert the exact init byte-sequence `~\r~\r~\r|\rA32100FF<c>\rA32200FF<c>\r...`; assert a withheld confirmation causes an identical resend after ~1 s. Commit.

#### Task 4.3: conn.rs — TCP/serial with reconnect

**Files:** Create `rust/cbus-transport/src/conn.rs`.

**Step 1:** Port `transport/base.py` semantics: connect timeout 10 s; on connection lost and `reconnect` enabled: sleep `reconnect_interval` (default 5 s) and retry, `max_reconnect_attempts` 0 = unlimited. Expose:

```rust
pub enum Endpoint { Tcp { host: String, port: u16 }, Serial { device: String, baud: u32 } }
pub async fn connect(ep: &Endpoint) -> io::Result<Box<dyn AsyncReadWrite>>; // trait alias
```
`--esp32-wifi HOST[:PORT]` maps to Tcp (default port 10001); `--esp32-serial DEV` to Serial (default 9600 baud).

**Step 2:** Unit test: TCP connect to a local `tokio` listener; reconnect after dropping it. Commit.

---

### Phase 5 — cmqttd daemon (behavioral suite green)

#### Task 5.1: cli.rs

**Files:** Create `rust/cmqttd/src/cli.rs`.

**Step 1:** clap derive struct mirroring `cbus/daemon/cli.py` — at minimum (harness contract, README §2): `-b/--broker-address` (required), `-p/--broker-port` (default 0), `--broker-keepalive` (60), `--broker-disable-tls`, `-A/--broker-auth`, `-c/--broker-ca`, `-k/-K` client cert/key, `-t/--tcp`, `--esp32-wifi`, `--esp32-serial`, `-T/--timesync` (default 300), `-C/--no-clock`, `-S/--status-resync` (parsed, unused — like Python), `-P/--project-file`, `-N/--cbus-network` (multi), `-l/--log-file`, `-v/--verbosity`. Exactly one of the connection options required.

**Step 2:** `cargo run -p cmqttd -- --help` shows all flags; `-b x -t y:1` parses. Commit.

#### Task 5.2: throttle.rs + gateway.rs

**Files:** Create `rust/cmqttd/src/throttle.rs`, `rust/cmqttd/src/gateway.rs`.

**Step 1 (throttle):** mpsc channel (cap 1000) + drain task: recv → run boxed future → `sleep(0.2s)` → next (order preserved; drop+warn when full). Port of `toolkit/periodic.py`.

**Step 2 (gateway):** port `mqtt_gateway.py` onto rumqttc:
- rumqttc `MqttOptions`: client id (any unique), host, port, keepalive 60; TLS only when `--broker-disable-tls` absent (harness always disables).
- On MQTT connect: subscribe `homeassistant/light/#` (qos ≤1); publish meta config; for each labelled group publish discovery (also subscribe its set topic qos 2 — rumqttc will cap per broker grant); then enqueue 384 status requests via the throttle (apps 0x30..=0x5F ascending, blocks 0,32..224 ascending — Python's iteration order; the harness accepts any coverage but match Python for determinism).
- groupDB (`HashMap<u8, HashMap<u8, bool>>`) + `check_published` lazy discovery.
- Incoming publishes: filter `/set` suffix + prefix; parse per trap 36; enqueue the C-Bus command on the throttle; after the send resolves, echo state + binary_sensor to MQTT (`cbus_source_addr: null`).
- CBus events → MQTT state/sensor publishes per traps 34/37 (qos 1 retain true).
- Clock request event → `clock_datetime()` (direct, not throttled) unless `-C`.

**Step 3:** `cargo build -p cmqttd`. Commit.

#### Task 5.3: main.rs — wiring + logging

**Files:** Create `rust/cmqttd/src/main.rs`.

**Step 1:** tracing-subscriber init from `-v` (and optional `-l` file); load labels via `cbus_mqtt::cbz::read_cbz_labels` when `-P` given (`-N` joins multiple args with spaces, like `cmqttd.py:123-127`); connect endpoint; start PciClient; start gateway; run until ctrl-c or connection loss (reconnect loop for esp32 modes).

**Step 2:** Manual smoke test against the harness pieces:
```sh
cd rust && cargo build --workspace
python3 ../rust-migration-harness/suites/behavioral.py --impl rust --skip-slow
```
Iterate until 15/15. Then the full run:
```sh
python3 ../rust-migration-harness/suites/behavioral.py --impl rust
```
→ `behavioral-rust: 17/17 PASS` (the two mqtt-cmd assertions take ~2 min by design — trap 38).

**Step 3:** Commit: "rust: cmqttd passes behavioral suite 17/17".

---

### Phase 6 — simulator + tools

#### Task 6.1: cbus-simulator

**Files:** Create `rust/cbus-simulator/src/main.rs`.

**Step 1:** Port `pciserverprotocol.py` semantics onto tokio TCP server (default `127.0.0.1:10001`, args `[address] [port]` like Python): server-mode FrameBuffer (from_pci=false, checksum off until SRCHK set); send `+` power-on on connect; local echo when in basic mode; handle reset (state to defaults), `|`/`||` smart+connect, DM interface options (0x30/0x41 bits: connect/srchk/smart/monitor/idmon — `pciserverprotocol.py:180-205`); confirm any command carrying a confirmation char (`<code>.`); respond to master-application binary status requests with StandardCAL blocks like `pciserverprotocol.py:310-335`. Skip the Python debug behaviour of firing random lighting events on clock updates (it's junk; note the divergence in the module doc comment).

**Step 2:** Verify interop: run the Rust simulator, then run the **Rust cmqttd** against it with a real or harness broker and observe init + confirmations in the logs. Also `cargo test -p cbus-simulator` for the DM options bit-parsing. Commit.

#### Task 6.2: cbus-tools (decode, dump-labels, interrogate)

**Files:** Create `rust/cbus-tools/src/main.rs` (clap subcommands).

**Step 1:** `decode <hex-or-ascii-frame> [--no-checksum] [--not-strict] [--client]` → decode_packet + `{:#?}` debug print (parity with `tools/decode_packet.py` is "prints something useful", not byte-identical).
**Step 2:** `dump-labels <file> [-o out] [-p spaces]` → walk the full CBZ (networks/applications/groups/units incl. `GroupAddress` PP channel parsing, `toolkit/dump_labels.py:89-105`) to JSON.
**Step 3:** `interrogate --tcp host:port [--unit N | --discover]` → port `protocol/interrogator.py` (raw TCP, `||` connect, `\46...` PP frames with rotating confirmation codes, 0x46 header — see vector `tp-*-pp-identify-interrogator-style`).
**Step 4:** Smoke: `cargo run -p cbus-tools -- decode 0538007901490D --client`. Commit.

---

### Phase 7 — full harness green + polish

#### Task 7.1: run the full harness

```sh
./rust-migration-harness/run.sh
```
Required end state — scoreboard all green:
```
selfcheck-vectors:      3201/3201 PASS
selfcheck-behavioral:   PASS
rust-build:             PASS
protocol-vectors:       protocol-vectors: 3201/3201 PASS
rust-unit-tests:        PASS
behavioral-cmqttd:      PASS
RESULT: FULL SUCCESS
```
Fix anything red. Commit.

#### Task 7.2: docs + release plumbing

- `rust/README.md`: build/run instructions, binary list, feature flags.
- Update the repo `Dockerfile` to a multi-stage rust build producing `cmqttd` (keep the Python one as `Dockerfile.python` until cutover).
- `cargo clippy --workspace -D warnings` and `cargo fmt --check` clean. Commit.

### Phase 8 — cutover (separate decision, not part of this plan's DoD)

When the team is ready: swap Docker entrypoint to the Rust cmqttd, run both side-by-side against the production CNI for a soak period, then archive the Python tree (`git mv cbus python-legacy/` or delete). The harness continues to work with `SKIP_SELFCHECK=1` after the Python tree is gone.

---

## 6. Definition of done

`./rust-migration-harness/run.sh` exits 0 with all six suites passing, on a checkout where the Rust engineer has touched nothing outside `rust/` (plus .gitignore). That single command is the acceptance test for this entire plan.
