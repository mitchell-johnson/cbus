---
name: cbus
description: Use when inspecting or reprogramming Mitchell's live C-Bus network (Grenache Way) - finding which unit/key/group controls a light, or changing key-unit programming with the toolkit-cli.
---

# C-Bus (Grenache Way) programming

## Where things run

- CNI: PC_CNIED, unit 16, `192.168.1.21:10001`. It accepts **one** TCP client;
  a second connection gets `*** Connection already in use` and is closed.
- The Mac mini `unifi` (192.168.1.243, `ssh 192.168.1.243`, docker at
  `/usr/local/bin` or `/opt/homebrew/bin`) runs the `cbus` container
  (Rust cmqttd + C-Gate-compatible server, compose in `~/source/cbus`,
  `restart: always`). It holds the CNI permanently.
  - Its C-Gate listens on the Mac mini's `127.0.0.1:20023`; reach it with
    `ssh -f -N -L 20023:127.0.0.1:20023 192.168.1.243`. It handles TREE, DBGET,
    lighting, etc. but **cannot read or write unit parameters**
    (`GET //GRENACHE/254/p/31 GroupAddress` -> 402 parameter not found).
  - For parameter programming: `docker stop cbus`, use the CNI directly, then
    `docker start cbus`. Keep the window short; Home Assistant/HomeKit lose
    C-Bus control while it is stopped. The user has OK'd stopping it.
- MQTT (emqx) on 192.168.1.243:1883, topics `homeassistant/light/cbus_<group>/state`
  and `/set`. HomeKit names come from Home Assistant, not C-Bus labels, so to
  find "which group is X in HomeKit", subscribe to `homeassistant/light/+/state`
  (paho is in the repo `.venv`) and ask the user to toggle X.
- Vendor unit specs (280 XML) are inside the container at
  `/etc/cmqttd/unitspec/`. Copy them to the scratchpad (never into the repo):
  `ssh 192.168.1.243 'docker exec cbus tar -C /etc/cmqttd/unitspec -cf - .' | tar -C <dir> -xf -`
  then use `cbus-toolkit memory --spec-dir <dir> layout KEYE.xml <Param>`.
- House documentation: `~/source/cbus/cmqttd_config/GRENACHE-HOUSE-OPERATIONS.md`
  on the Mac mini has the unit/group/channel/key binding tables.

## Toolkit CLI against the CNI

Run from `toolkit-cli/` without installing:

```sh
PYTHONPATH=src python3 -m cbus_toolkit --compact pci --host 192.168.1.21 --local-unit 16 recall 31 0x36 8
PYTHONPATH=src python3 -m cbus_toolkit --compact pci --host 192.168.1.21 --local-unit 16 write 31 0x37 0a
```

- Each CLI call opens a fresh TCP session, and the CNI starts every session in
  basic mode: it echoes the command (without CR) and sends occasional `++`
  power-up notifications. The client discards the echo; before that fix this
  showed up as `Frame must contain an even number of hexadecimal characters`.
  Interface options set with `A3300019` do not survive to the next session.
- Do not pass `--checksum`; replies already carry a checksum the client checks.
- `recall`/`write` are raw parameter access. Read before and after every write.

## Groups worth knowing

| Group | Label | Output | Key input |
|---|---|---|---|
| 5 | outside wall light rear | Relay 1 (unit 0) ch 6 | unit 31 key 2 |
| 6 | outside wall light side | Relay 1 ch 7 | unit 31 key 3 |
| 7-11 | prov 1-5 (HomeKit names them) | Relay 1 ch 8-12 | none originally |

## Key units (KEYE1/2/3, 5031NMML, fw 2.5.00, spec `KEYE.xml`)

Downstairs 3-gangs: unit 23 Lounge (24, 33, 27), 25 Bottom of Stairs
(38, 27, 25), 31 Dining (Ranch Slider) (33, 5, 6). Values are GroupAddress
blocks 0..2. The user calls unit 31's rear-light key the "bottom" button even
though it is key 2 of 3; identify a key by the group it sends, not by position.

Memory layout (confirmed against vendor `KEYE.xml`):

| Param | Address | Notes |
|---|---|---|
| Application | 0x21 x2 | 38 ff = lighting |
| BlockAllocation | 0x36 x8 | per-key bitmask of blocks it drives |
| SecondApplicationBlocks | 0x45 | |
| GroupAddress | 0x50 x9 | group per block, ff = unused |
| IndicatorBlockAssignment | 0x60 x8 | low 3 bits; IndicatorFunction bits 4-5 |
| JP/SR, LP/LR commands | 0x68.. | two bytes per key, nibbles |
| EEPROMCheckSumActive / EEPROM Checksum | 0x1E / 0x1F | checksum active only if 0x1E has odd parity |

To make one key control two groups: put the second group in a free block
(GroupAddress ff) and OR that block's bit into the key's BlockAllocation. The
indicator keeps following the original block, and other keys are unaffected.
