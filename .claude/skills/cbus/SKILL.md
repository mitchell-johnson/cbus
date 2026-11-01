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
PYTHONPATH=src python3 -m cbus_toolkit --compact pci --host 192.168.1.21 --local-unit 16 \
  --checksum write --addressing direct 31 0x37 420a
```

Writes to classic units (KEYE etc.) need all three of these, or they silently do nothing:

- **`--addressing direct`**: `pci write` defaults to `programming` addressing
  (`\46<unit>0900...`), which KEYE units ignore. The result is a timeout.
- **`--checksum`**: the unit ACKs an unchecksummed STORE but does not apply it.
- **A tag byte first**: `hex_data` is `<tag><data...>` (legacy STORE). The ACK
  echoes the tag (`32 <param> <tag>`). `420a` writes one byte, 0x0a, with tag 0x42.
  Without a tag the data byte is taken as the tag and nothing is stored.

Writes take effect immediately (no save/NVM step for these 2.x units). Check
`EEPROMCheckSumActive` (0x1E) first: if it has odd parity, the EEPROM checksum at
0x1F would also need updating. On unit 31 it is 0x00, so the checksum is inactive.
Params with `Protection` of `lock` in the spec need the unlock CAL before the
STORE. `checksum` protection does not.

- Each CLI call opens a fresh TCP session, and the CNI starts every session in
  basic mode: it echoes the command (without CR) and sends occasional `++`
  power-up notifications. The client discards the echo; before that fix this
  showed up as `Frame must contain an even number of hexadecimal characters`.
  Interface options set with `A3300019` do not survive to the next session.
- `recall` works with or without `--checksum`; replies always carry a checksum.
- `recall`/`write` are raw parameter access. Read before and after every write.

## Groups worth knowing

| Group | Label | Output | Key input |
|---|---|---|---|
| 5 | outside wall light rear | Relay 1 (unit 0) ch 6 | unit 31 key 2 |
| 6 | outside wall light side | Relay 1 ch 7 | unit 31 key 3 |
| 7 | prov 1 = **Patio** in HomeKit | Relay 1 ch 8 | unit 31 key 2 (block 3, added 2026-11-01) |
| 8-11 | prov 2-5 | Relay 1 ch 9-12 | none |

Change log (live unit edits, so the next person can undo them):

- 2026-11-01, unit 31: GroupAddress[3] (0x53) ff -> 07, and BlockAllocation[1]
  (0x37) 02 -> 0a, so the rear-lights key also switches the patio. To undo, write
  `4202` to 0x37 and `41ff` to 0x53.

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
