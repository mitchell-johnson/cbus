# Enable Control

The `cgate enable` commands set Enable variables and read their native cached
state. They accept bytes, integer percentages, hex/binary numbers and exact
database level tags, including names containing spaces. The shared native
percentage rule truncates: `50%` sends 127. Tag resolution reads the native
Group/NetVar XML and rejects missing, ambiguous or invalid values before sending.

```sh
cbus-toolkit cgate enable set //TEST/254/203/1 50%
cbus-toolkit cgate enable set //TEST/254/203/1 'Sensor enabled' --force
cbus-toolkit cgate enable level //TEST/254/203/1
cbus-toolkit cgate enable state //TEST/254/203/1
cbus-toolkit cgate enable groups //TEST/254/203
cbus-toolkit cgate enable get //TEST/254/203/1
cbus-toolkit cgate enable remove //TEST/254/203/1
```

SET reports native queue acceptance separately from physical verification.
`--force` explicitly requests transmission regardless of network state. The
client never retries an uncertain operation automatically. The Python API also
provides `encode_enable_set` and `parse_enable_event`; a native outgoing 702
event can contain this session's command ID and does not prove receipt.

The exact vendor `CBusEnableSetCommand` encodes application 203 with SAL bytes
`02 variable value`. An independent receiver decodes complete command chains,
tracks repeated SET operations and persists values atomically. It imports no
client encoder. Socket tests cover omitted repeated headers and rollback when
the state file cannot be saved.

Native acceptance sends five SET operations (0, 255, 50%, and two named-level
operations). The independent receiver observes values 0, 255, 127, 123, 123;
native GET and events agree. A fresh simulator instance loads the same values
and operation counts from disk. The run contains zero unsupported packets and
cleans up its own disposable native project.

There is a native REMOVE limitation. Public command help promises removal of
the variable and its saved value, but build 2001 calls `File.delete()` and
ignores its return value. Native acceptance confirms that its live Level and
Groups remain unchanged after status 200; database tags and the independent
receiver also remain unchanged. Therefore the CLI reports `accepted: true`
and `effect_verified: false`, without claiming the cache or disk value was
removed. These native semantics are preserved explicitly.

```sh
CBUS_CGATE_TEST_HOST=127.0.0.1 \
  CBUS_ENABLE_REPORT=toolkit-cli/research/runtime/enable-acceptance.json \
  toolkit-cli/.venv/bin/python -m unittest discover \
  -s toolkit-cli/tests -p test_enable.py -v
```

Seven tests cover encoding, events, cache parsing, native commands, malformed
state, persistence, CLI error reporting and the real-server workflow. Native
acceptance is opt-in. See [the compact report](enable-acceptance-summary.json)
for source/report hashes and scope. Neither simulator agreement nor native
cache reads establish physical sensor execution.
