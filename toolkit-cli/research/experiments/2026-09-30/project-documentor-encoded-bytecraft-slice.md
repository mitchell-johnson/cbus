# Encoded NeoProClassic and old Bytecraft output slice

This slice extends the previous ordinary KEYC/CIR projection with canonical
selector=1 / JP14 Scene24 keys. It also adds old DIMPR12 output dependencies,
without admitting its scene loader or body. Central DALI/SENLL projections,
CLI registration and capability ledgers are outside this slice.

## Recovered behavior

All five registered KEYC/CIR profiles retain eight key objects and their native
physical/virtual/IR counts. Scene24 controls display IndicatorBlockAssignment
plus one and the SR ramp. The template replaces the encoded four stages with
idle commands, which the Classic action consumer does not treat as recalls.
Its body has no Neo scene appendix or trigger link. Input dependencies still
scan loaded scene commands, and all eight actual key references determine
whether each scene is used. A physical Scene24 key remains active even though
its normalized commands are idle; KEYCIR1 has no physical key labels.

Canonical admission requires the scene key's own linear block, unused group
255 in the primary application, and no other key sharing that block. This
avoids projecting the original template event's relocation and removal of
shared references. Ordinary-key matching and stored-level/timer behavior use
the existing accepted projection.

Body, action and dependency consumers require only the fields they read. The
body does not require scene commands or trigger binding metadata. Only actual
Scene24 indicator slots are validated. Classic actions, secondary input queries
and empty primary scene scans omit scene indexes. Missing indexes for a
nonempty primary scene scan preserve block descriptions and a partial marker.
Missing or malformed scene commands remain partial independently of body
recovery. This field separation does not claim that the original whole loader
accepted absent PP fields.

Old DIMPR12 firmware 0 through 1.9.02 uses the exact TDIMPR12 and
TDIMPR12CGateAgent registration. Its output consumer visits twelve channel
objects in order, comparing primary application/group identity and preserving
repeated groups and group 255. It does not read presets, scene use or DMX
values. L1 firmware, other/input dependencies, actions and body remain outside
this adapter.

## Evidence and checks

The new encoded-key receipt has 15 exact static checks and six method spans.
It composes the accepted Neo scene-padding/template facts and five concrete
NeoClassic profiles. The old Bytecraft output receipt has 18 exact checks,
five method spans and exact class/agent registration evidence. Its retained
assessment records thirteen method spans and the packed scene/body prerequisites.
All artifacts use pinned original EXE/MAP hashes and sanitized relative paths.

An independent GPT-6.1-sol review found unnecessary indicator coupling to action
and empty/secondary input consumers. The correction initially exposed an empty
scene iteration error; both were fixed before final verification. The reviewer
found no remaining actionable runtime/source contradiction in the final scope.

The final configured targeted check covered encoded keys, Bytecraft output,
NeoClassic body/dependencies, core report dispatch/receipt, classic usage and
shared Neo regressions: **238 passed, 2 skipped**. Both skips require explicitly
enabled original instruction execution, which was disabled. Static receipts
reproduced, retained original Classic/Neo leaf vectors were compared without
rerunning vendor instructions, and all five encoded profiles matched the
accepted shared Neo software key/block graph and Classic body projection.
No full repository suite, build, installation, new CPU probe or hardware action
ran.

The source CLI smoke used seven synthetic units: five fully encoded KEYC/CIR
profiles and old/L1 DIMPR12 examples. It exited zero, recovered all five Scene24
bodies, rendered forty scene controls, reported old Bytecraft channels 1/3/12
in order and preserved L1/body/action gaps. UTF-8 BOM/CRLF and honest parity
metadata were checked. The intentionally incomplete snapshot retains 26
markers, including calculator/status and unsupported consumers. The companion
software-smoke receipt contains only the checked result fields. An additional
focused pytest case reproduces that receipt through the source CLI (one passed).

## Remaining prerequisites

Scene Modify assigns template25 only as an intermediate state. It attaches
Scene1, loads stages under a macro lock, unlocks and performs a subset-sensitive
macro refresh that can replace the template and trigger timer/block events.
The final indicator assignment changes an indicator block number, not the
extension scene. Those refresh/effects and noncanonical relocation/history are
still unprojected.

Bytecraft actions and bodies need exact packed PresetRec00..32 decoding,
constructor/default policy and Boolean/Variant normalization: the loader passes
masked EDX while setters consume DL, so channels 8..11 cannot be modeled by a
simple Python mask truth test. The body also needs DMX/channel-unused and
scene-zero restore semantics; the L1 class adds its own logic loader.
Architectural bodies remain a separate loader/documentor problem.

Original PP-loader execution, full generated-page capture, whole-page bytes,
visual comparison, collection ordering/locale preferences, retained GUI history
and printing remain unassessed. Source/retained leaf and software comparisons
do not establish those outcomes.

## Reproduction

Use an existing configured research environment with pinned source variables:

```sh
CBUS_RUN_DOCUMENTOR_ORIGINAL=0 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests \
  python -m pytest tests/test_project_documentation_neoclassic_scene_keys.py \
  tests/test_project_documentation_bytecraft_usage.py \
  tests/test_project_documentation_neoclassic.py \
  tests/test_project_documentation_neoclassic_usage.py \
  tests/test_project_documentation.py tests/test_project_documentation_usage.py \
  tests/test_project_documentation_neo.py tests/test_project_documentation_neo_usage.py \
  -q -p no:cacheprovider
```

Set CBUS_TOOLKIT_EXE and CBUS_TOOLKIT_MAP to the pinned original inputs before
that check. Regenerate the core supporting-module receipt after integration,
retaining the central module union and independent DALI/SENLL changes.
