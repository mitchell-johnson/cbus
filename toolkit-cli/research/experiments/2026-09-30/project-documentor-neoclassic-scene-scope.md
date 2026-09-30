# Encoded KEYC/CIR Scene24 scope

The exact KEYC1/2/4 and KEYCIR1/4 classes admitted by the existing NeoClassic
receipt share the core Neo loader. Its selector branch does not consult the
false ScenesEnabled getter. Selector 1 with JPCommand 14 assigns global
Scene template 24 directly. The assignment is not gated by the key macro
subset: the primary NEOPRO_CLASSIC subset includes Scene24, while the
secondary NEOPRO_S subset equals KEY, but neither is consulted at this branch.

The bounded projection can reuse the Neo canonical guard: the key's allocation
is precisely its linear block, that block is unused group 255 in the primary
application, and no other key refers to it. Native template events remove all
references, may relocate block data and remove other keys' shared references,
then add the linear block and force primary application/unused group. These
conditions avoid those omitted relocation/history effects. Template24 assigns
the all-idle microfunction group; raw JP/SR/LP/LR are encoded extension values,
not the final action commands. IndicatorBlockAssignment supplies Scene number
plus one, SR supplies ramp, and LP/LR supply the trigger byte.

The Classic documentor renders Scene number/ramp controls and has no Neo scene
appendix or trigger link. Its body projection therefore need not consume
SceneTable, SceneTablePointer or ControlAppGroupAddress. The shared source
scene loader pads the collection to eight, so canonical indicator 0..7 has
an existing scene object independent of command contents. Omitting those PP
fields from a consumer projection does not assert that the original loader
executed successfully with missing programming information. Input dependencies
must separately decode actual canonical scene tables and select the scene
indexes used by encoded keys (ordinary keys use Scene1). Classic action usage
consumes normalized idle commands without the Neo trigger pass.

Consumer field requirements remain independent. Only actual Scene24 indicator
slots are validated; ordinary slots are unconsumed even in a mixed snapshot.
Classic actions never need those indexes. Secondary input queries and primary
queries with no scene commands also skip the scene-reference scan. Missing
indexes on a nonempty primary scene scan preserve the known block descriptions
and mark the result partial without inventing scene-use labels. This distinction
was found in the independent source review and is covered by focused cases.

Scene Modify was initially left partial because the final macro/template refresh
and events required independent inspection. The later
`project-documentor-neoclassic-scene-modify-scope.md` closes that canonical path
and corrects the ordinary-branch inference. It first attaches Scene1, locks the
macro pin, loads four raw stages, unlocks and refreshes the macro. The special
SceneModify branch assigns a separate extension ramp template under its lock;
key template25 and raw stages remain. The final indicator-plus-one assignment
calls SetBlockNumber and changes neither the extension scene nor its fresh
Instant ramp. Noncanonical relocation/history remains outside the projection.

`project_documentor_neoclassic_scene_static.py` generated the companion JSON
receipt with 15 exact source checks against pinned EXE/MAP hashes, including
modify ordering and canonical block assignment effects. Existing Neo and
NeoClassic receipts supply scene padding, template group and concrete class
facts. This evidence executes no original CPU instructions, PP loader, GUI,
network or hardware and does not establish original generated-page acceptance.
