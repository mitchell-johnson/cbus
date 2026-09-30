# PIR project documentor evidence

`project_documentation_pir.py` reconstructs the original `TPIRDocumentor` and
`TST7PIRSensorDocumentor` report bodies from explicit offline PP snapshots. It
uses the exact native unit class and agent registration selected by numeric
firmware. SENPIRSS 1.00–2.0.00 and SENPIROA/IA/IB 1.2.60–2.0.00 use the old
PIR model. SENPIROA/IA 2.0.01–9 and SENPIRIB 2.0.01–2.3.9 use ST7 PIR.
The surface multisensor selected for SENPIRIB from 2.4, other multisensors and
SENLL are excluded.

Both bodies render the inherited four-key/four-block ClassicKeyInput tables,
then the original enable/disable group line. Old `EnableGroupLogic == 0` means
Disable; ST7 `PIREnablerGroupLogic == 1` means Disable. The group is in the
primary application for both. Group 255 uses `PIR Enable/Disable Group:` and
does not read polarity. Named group/level display uses the existing documentor
helpers and requires explicit project metadata.

The fresh PP projection resolves the SENPIR macro subset (including Day Move,
Night Move, Any Move and Sunset), stored levels, timer expiry coercion and the
300-second zero-timer template event. ST7 secondary block membership and mixed
key application selection preserve application/group object identity. The
shared table renderer retains repeated groups and first-global-block lookup.
Both documentors inherit Classic ActionSelectorUse: only the primary application
pass runs, with the original stored-1 Address gate enclosing the stored-2 Value
branch. There is no Neo scene overwrite or second application action pass.

Input dependencies preserve block-major key order and unused blocks. ST7 also
reports active light-level maintenance on its selected block. Its scene usage
is recovered only for an explicit empty native scene table; other tables retain
known block uses with a partial marker. Other dependencies preserve native
ordering, both corridor labels, primary-application occupancy/maintenance groups,
the unused key-disable group in application 203, and the broadcast block group
even when broadcasting is disabled. Unsupported brightness and join properties
are omitted based on pinned virtual methods, not guessed PP defaults.

The adapter requires complete consumed arrays and ordinary ST7 keys
(`SceneKeySelector[0:4] == 0`). Encoded Scene/Scene Modify keys, nonempty ST7 scene
group dependencies, retained GUI state, out-of-range broadcast block references
and unresolved group metadata remain explicit gaps. A recovered body or usage
component is not full Toolkit parity.

## Verification

- `research/fixtures/project-documentor-pir-static.json`: 84 source checks of
  factory/VMT selection, method hashes, four-block/key topology, loader ancestry,
  disabled properties, inherited action method, exact labels and dependencies.
- `research/fixtures/project-documentor-pir-macro-source.json`: 983,040 comparisons
  across all 65,536 microfunction vectors in 15 application/stored-level contexts;
  independently decoded native registrations and subsets, zero mismatches.
  This is a source-derived comparison, not execution of the original refresh.
- `research/fixtures/project-documentor-pir-original.json`: 12 original appendix
  wrapper cases and 15 original Classic action cases executed under bounded
  x86 emulation. String routines, collection/attribute access, group display,
  class tests and the inherited body are synthetic hooks. The original PP loader,
  complete generated pages and GUI were not executed.
- `tests/test_project_documentation_pir.py`: focused complete/incomplete snapshots,
  native class bounds, macro/timer behavior, polarity, ordering, action identity,
  secondary application behavior and retained original instruction comparisons.

Regenerate static/source evidence with `research/project_documentor_pir_static.py
--executable ... --map-file ... --output ... --macros-output ...`. The separate
`project_documentor_pir_original.py` requires executable memory and an explicitly
approved offline probe environment. Neither helper connects to C-Gate or hardware.
Original generated-page acceptance remains **not obtained**.
