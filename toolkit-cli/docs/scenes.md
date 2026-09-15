# Filesystem scenes

`SceneFile` reads and edits the native C-Gate scene text format. `SceneExecutor`
executes its actions through C-Gate lighting commands and records C-Gate's
cached group levels. These workflows are distinct from SQLite scene records,
device PP scene tables, and the legacy native `SCENE PLAY/RECORD` commands.

```sh
cbus-toolkit scene new evening.scene
cbus-toolkit scene add evening.scene //HOME/254/56/12 255
cbus-toolkit scene add evening.scene //HOME/254/56/24 127 --seconds 4
cbus-toolkit scene show evening.scene
cbus-toolkit cgate --host 127.0.0.1 scene execute evening.scene
cbus-toolkit cgate --host 127.0.0.1 scene record-file evening.scene recorded.scene
```

Playback sends actions in order. Zero-time levels 0 and 255 use OFF and ON;
other actions use RAMP. Ramp commands are queued without waiting for completion.
A failed command stops playback and reports its zero-based action index and
the number of earlier accepted commands. Commands are never retried implicitly.
The response reports `queued=true` and `device_verified=false` because command
acceptance does not prove a device reached its target level.

Recording reads every action's current cached level before constructing a new
scene. It resets ramp times to zero and preserves trigger metadata and comments.
The CLI publishes a new output file only after all reads succeed, and refuses
to overwrite an existing output. Cached levels are not physical verification.
During a ramp, the native GET Level property and native scene recorder both
sample the same integer method (`bq.k_()`); the independent simulator can have
a fractional interpolated level at that instant. Recording does not invent a
rounding rule for fractional or otherwise invalid server responses.

The file grammar is:

```text
# Optional comment
play //HOME/254/56/27
record //HOME/254/56/33
set //HOME/254/56/12 255
set //HOME/254/56/24 127 4
set //HOME/254/56/25 0 0
```

`play` and `record` lines describe native lighting-group trigger bindings. The
Python executor preserves them as metadata and does not install a persistent
trigger listener. Duplicate trigger declarations use the last value, matching
the native parser. Actions preserve their order. Untouched files round-trip
exactly; editing emits canonical text and retains comments. Inputs are bounded
to 1 MiB and 1024 actions. Levels are decimal bytes, ramp times are nonnegative
signed 32-bit decimal integers, and addresses must be single tokens without
the native `#` comment delimiter. Encoding defaults to UTF-8 and is explicit
when loading or saving.

## Native limitation and verification

C-Gate 3.4.0 build 2001 loads the pre-existing scene set when `use-scenes=yes`
and `scene-base` names its directory. The acceptance runner verifies that the
loaded scene-set object is readable through GET. Nevertheless, both native
`SCENE PLAY CLI_SCENE evening` and `SCENE RECORD CLI_SCENE evening` return 401.
Bytecode confirms that the command class `nJ` looks up the separate `BS` table,
while the scene loader `AY` registers its objects in `Bm`. The BS insertion
method is private and never called. The CLI preserves these native errors;
it does not fall back implicitly or count them as successful native workflows.
Persistent native scene-trigger operation remains unverified.

The separately named `execute` and `record-file` workflows pass against the
unmodified native C-Gate server and the independently implemented synthetic
lighting peer. Six checks cover native parser/serializer agreement, playback,
cached recording, recording during an active ramp, editing and reloading a
scene with a ramp, and persistence across a fresh peer instance. The Java
parser probe directly invokes the vendor AU parser and serializer with a
literal four-action fixture; it does not modify the jar or replace the server
entrypoint. The native SCENE failures remain separate failed results in the
same report.

```sh
CBUS_SCENE_NATIVE=1 toolkit-cli/.venv/bin/python -m unittest discover \
  -s toolkit-cli/tests -p test_scenes.py -v
# Equivalent explicit acceptance runner:
toolkit-cli/.venv/bin/python toolkit-cli/research/verify_scenes.py --port 20024
```

The runner creates a uniquely owned runtime directory and container named
`cbus-toolkit-scene-oracle`, uses pinned JRE/JDK images, publishes the command
port on loopback, and connects only to its fresh synthetic interface. It
refuses to adopt an existing scene container or use the shared oracle's port
20023. The container and its project are cleaned up; captured evidence remains
under `research/runtime`. [scene-acceptance-summary.json](scene-acceptance-summary.json)
contains the compact evidence and source hashes. The 16-test scene suite passes
with native acceptance enabled; its native test is explicitly skipped unless
requested.
