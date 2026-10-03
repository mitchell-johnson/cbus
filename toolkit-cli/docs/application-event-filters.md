# Lighting event filters

`cbus-toolkit cgate events` accepts client-side `--application 48..95`,
`--group 0..255` and `--source-unit 0..255` selectors. Combine selectors to
require all of them. With a filter, `--count` counts emitted matching records;
`--follow` continues until interrupted and the existing `--timeout` bounds
each idle read. The server subscription remains the supplied `--mode`; these
filters do not change server-side delivery or reduce its event queue.

```sh
cbus-toolkit cgate --host HOST events --application 56 --group 7 \
  --source-unit 4 --count 2
```

Filtered event JSON retains `raw`, `text`, `category`, `timestamp` and `code`,
and adds a `lighting` projection with the exact address, project/network
spelling, application, group, kind, literal source byte, level, ramp seconds,
OID and optional command context. Native timestamps are retained without
inventing a timezone; status rows with no timestamp keep `timestamp: null`.
The summary's `received` counts emitted rows; `observed` counts all read rows
and `filtered` counts omitted rows. No filter preserves the existing output
shape and passes opaque event records through.

The admitted profile is the native `730` Lighting level-change or terminated
ramp row, and `#s# lighting on/off/ramp/terminateramp` rows from the retained
[original capture](../../rust/testdata/fixtures/native_cgate_lighting_events.json).
Each separate event/status row stays in its received order. Repeated commands
are retained: the captured repeated OFF emits both rows again. This profile
admits only Lighting applications 48–95; other applications and unknown or
malformed grammars cannot satisfy a typed selector. cmqttd's own untimed
Lighting command and status-report rows remain opaque because they lack the
native source facts.

Explicit `sourceunit=0` stays zero as a recorded source byte; it does not prove
an originating unit. A missing source never becomes zero. An overflow marker
always bypasses selectors, appears with `lighting: null`, marks
`events_lost: true` and exits nonzero. A failed/disconnected read retains the
client's existing connection closure and nonzero error behavior; it does not
reconnect or replay.

The tests replay the retained original rows and exercise the public CLI
against a scripted loopback peer. They execute no original Toolkit/C-Gate
runtime and no hardware. Original Application Log pause/resume, Clear/filter
interaction, saved content/encoding and contextual editor behavior remain
unimplemented and unassessed under [issue #16](https://github.com/mitchell-johnson/cbus/issues/16).
Native transport/order/source and physical/MQTT acceptance remain separate
under [issue #54](https://github.com/mitchell-johnson/cbus/issues/54).

Focused source validation on 2026-10-03 used Python 3.13.14 with the required
extras installed and passed 48 test parents, zero failures and zero skips:

```sh
PYTHONPATH=src:tests:research python -m unittest -v \
  test_application_events test_events.EventTests test_event_stream \
  test_cgate.CGateTests test_cgate.CGateTLSVerificationTests
```

Run from `toolkit-cli/` with its Python environment. The new tests include
23 retained native capture cases, exact source/time/order preservation,
repeated OFF rows, literal zero, malformed/oversized integers, unchanged
default JSON, filtered count behavior, overflow with a false client flag,
selector rejection before connection and disconnect without command replay.
Native provisioning cases are outside this focused selection; no fresh
original GUI, native-runtime or hardware acceptance is claimed.
