# Canonical NeoProClassic SceneModify closure

This source review corrects the SceneModify conclusion in the earlier
`project-documentor-neoclassic-scene-scope.md` and its static receipt. Their
instruction checks remain true, but the conclusion applied the ordinary
`RefreshTemplateFromMacroFunction` branch to a SceneModify key. The first
branch of that method tests the key's template ordinal25 and its Neo
extension. On the admitted fresh graph both tests succeed. It assigns the
resolved raw macro's template to the extension's separate ramp-template
reference under the extension lock and exits past the ordinary subset filter
and key-template setter. Template25 is therefore final, even when absent from
NEOPRO_CLASSIC's application subset.

Admission remains the exact existing KEYC1/2/4 and KEYCIR1/4 classes and
firmware registration, a fresh model, selector1 with JP other than14, and an
unshared linear primary block whose group is255. The initial template event
removes the key's block references, chooses its linear block, and restores the
linear primary unused reference. Because no other key refers to that block,
the relocation and other-key removal branches have no consumed effect. The
effective block-list and indicator callbacks on all five classes are the
base no-op methods. Noncanonical allocation, shared-reference and retained
GUI-history graphs remain outside this projection.

The exact admitted order is:

1. Raw JP is assigned as the extension's SceneRampFunction. JP14 selects
   Scene24; every other raw nibble selects template25.
2. Template25's event refreshes its block reference. It misses the timer
   default gate (template6 and templates29..35), skips template command
   copying, and establishes the initial Dimmer ramp template if the fresh
   extension's ramp template is absent or Unused. That early ramp event may
   copy commands, before the loader overwrites all four stages.
3. The loader assigns extension Scene1 and locks its macro pin. Each raw-stage
   setter takes the macro's own lock; that lock suppresses per-stage refresh.
   JP/SR/LP/LR finish as the four supplied raw nibbles.
4. It unlocks the pin, assigns the class subset name only if empty, and
   refreshes the raw macro from source type0. The accepted global registration
   order and existing sensor/AUX reconciliation produce the derived type;
   identical-macro refresh may select stored-level shutter aliases.
5. The special SceneModify refresh assigns that derived type's template to
   the extension ramp reference under its lock. The ramp-reference handler
   checks that lock and skips reverse copying. Neither the key template nor
   raw stages nor timer/block data change. No ordinary subset filter runs.
6. IndicatorBlockAssignment plus1 is stored as indicator block number. It
   does not assign extension Scene or SceneRampRate.

The Classic documentor reads the key template description `<Scene Modify>`.
Its microfunction subtable is only emitted for template26, so this key's raw
commands do not appear there. Its scene-controls branch uses the extension
scene object and SceneRampRate: Scene1 and Instant on this fresh path. The
inherited Neo input consumer identifies activity through the key template's
Unused predicate (25 is active), counts only physical keys in its block pass,
and includes every key's Scene1 pointer in its separate scene-use scan.
Classic action usage still reads the preserved raw commands, stored levels
and expiry data under its existing Address/Value gates.

`scene_modify_projection` exposes only these consumed fields and validates
the canonical block guard. It does not require or infer the final indicator
block, internal derived ramp-template ordinal, stored-level data, or scene
commands. Body and input consumers therefore do not gain action-only field
requirements. Scene24 alone consumes IndicatorBlockAssignment to choose its
extension scene. Omitting an unconsumed field from this projection does not
prove that the original loader could finish with missing PP data.

The companion `project-documentor-neoclassic-scene-modify-static.json` pins
the EXE/MAP hashes, narrow method hashes, special-branch and event checks, and
synthetic raw-vector/context transitions using the existing SourceMacroOracle
registrations. Internal ramp types are deliberately calculated without its
normal KEY subset filter. For example, Trigger1 under application255 and
stored1=255 resolves internal ramp template20 while key template25 remains;
the Sunset raw vector likewise retains internal template34. Neither ordinal
is substituted for the documentor's key template.

This closes the canonical software consumer projection. It executes no
original CPU instruction, programming loader or GUI and has no original
generated-page comparison. Native page acceptance, broader/history graphs,
hardware behavior and missing-PP loader completion remain separate blockers.
