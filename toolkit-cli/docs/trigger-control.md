# Trigger Control

```sh
cbus-toolkit cgate trigger event //TEST/254/202/1 123
cbus-toolkit cgate trigger event //TEST/254/202/1 50%
cbus-toolkit cgate trigger event //TEST/254/202/1 'Evening scene' --force
cbus-toolkit cgate trigger kill //TEST/254/202/1
cbus-toolkit cgate trigger get //TEST/254/202/1
cbus-toolkit cgate trigger state //TEST/254/202/1
cbus-toolkit cgate trigger groups //TEST/254/202
```

`NativeTrigger(client)` provides `event`, `indicator_kill`, `get`, `state`, and `groups`. Events accept a byte, numeric text, an integer percentage, or an exact database level-tag name. Percentages use the native integer conversion, so 50% is 127. Named selectors are resolved from native `DBGETXML` and sent numerically; this also supports names with spaces. Missing or ambiguous names and invalid `Value` fields fail before an event is sent. Numeric calls require no database lookup. `force=True` adds the explicit native `FORCE` option; there are no automatic retries.

This lookup avoids a verified C-Gate 3.4 failure: direct named `TRIGGER EVENT` calls returned 405 even with a correctly configured NetVar and Level. The typed workflow reads the authoritative saved `Value` and sends that byte. Native Trigger Control uses database `NetVar` records. The vendor numeric database resolver also fails on NetVar Level children; their supported OID path is `!UUID/Value`.

Trigger `get` and `state` read native cached object attributes. Native groups expose `EventLevel`, `Name`, and `State`. `EventLevel` is the logging level, not the last action selector. `GET ... Level` returns native 402 and is not emulated. A runtime trigger group may not exist until C-Gate has encountered it. Event/kill CLI output states `queued: true, device_verified: false`; physical scene execution is not inferred from queue acceptance or cached state.

`parse_trigger_event(line)` decodes native 702 event messages into a typed `TriggerEvent`, including kind, selector, source unit, timestamp, address, object ID and optional session/command correlation. Unrelated messages return `None`. An indicator-kill event has `selector=None`. Native command events can describe C-Gate's own outgoing message, so they do not independently prove device execution.

Fifteen tests pass: eight API/encoding/event parsing tests, six independent receiver/transport tests, and one native acceptance test. The native run verifies five events with selectors `[0, 255, 127, 123, 123]` followed by indicator kill, exact peer state and correlated C-Gate events, named-selector resolution, cached attributes, and disk reload. Repeated events are retained; kill clears the modeled indicator while preserving the last selector. Transport tests cover compressed headers, atomic rejection of malformed chains and persistence-failure rollback.

```sh
CBUS_CGATE_TEST_HOST=127.0.0.1 \
  CBUS_TRIGGER_REPORT=research/runtime/trigger-acceptance.json \
  .venv/bin/python -m unittest discover -s tests -p '*applications.py' -v
```

The run uses a unique disposable project and a newly created synthetic interface. No existing physical network is opened. The report from native C-Gate 3.4.0 build 2001 remains at `research/runtime/trigger-acceptance.json`, SHA-256 `dc91968ee9c9e095148fe5b01efd7b1345e8453ea8eb27a0cce8400e1d43e27b`. This establishes outgoing Trigger Control encoding and independent synthetic receipt/state persistence. It does not establish physical scene execution, every device's indicator behavior, or Toolkit parity.
