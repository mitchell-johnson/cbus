# Original classic DLT delivery sequence

`research/classic_dlt_delivery_original.py` retains source-backed sequencing and
executes 58 original branch cases with synthetic state. The receipt is
`research/fixtures/classic-dlt-delivery-original.json`. This research adds no
physical programming API.

The separate [broadcast compiler and assessment](classic-dlt-broadcast.md)
implements the bounded per-flavour command/cache sequence with prepared bitmap
inputs. It performs no I/O and does not implement the whole-unit save below.

The ordinary Toolkit save has this order:

1. Save unit programming with dynamic labels temporarily enabled.
2. Run `AfterSaveProgrammingInformation`: optionally send key-function
   indicators, reset collected label errors and initialize missing network
   language metadata.
3. Process labels in key order when the unit's **Save DLT Labels** state or the
   agent's transfer flag permits it.
4. If **Block Dynamic Updates** is selected, separately set
   `EnableDynamicLabels=0` and save again.

The delivery gate is more than the inverse of Block Dynamic Updates.
`unit+0x16E` is also writable by the Save DLT Labels checkbox. `agent+0xDA` is
true for `TransferNetworkToDatabase` and `TransferDatabaseToNetwork`, and false
for ordinary saves. Database saves take the language-finalization branch rather
than the per-key physical delivery branch.

A scene-modify key uses its control-application group; a scene key uses its
trigger level; other keys use their primary DLT group. The label comes from the
network default language and selected flavour. Empty tags, `<Default>`, missing
flavours and missing DYNAMIC/FONT bitmap data clear the relevant key label.
A usable retained flavour dispatches `SaveDLTLabel`. Ordinary primary-group
DYNAMIC/FONT labels first attempt bitmap loading when their cache is empty.

The emulator exercises eight delivery-gate cases and fifty key decisions,
including keys 1 and 8, missing flavours, blank/default tags and both bitmap
states. It runs the original branch instructions but supplies object lookups,
strings and callback targets. It does not send C-Gate commands.

The original retains nuanced failure behavior: exceptions within the
retained-flavour dispatch region are collected while later keys continue;
fallback missing-flavour clears lie outside that local handler. The form keeps
at most ten displayed errors. The separate SaveFlavours path stages the two
flavour arrays without committing an already-open session; it saves and closes
only a session that it opened itself.

The same receipt statically verifies 23 original command-builder methods.
Application labels use project-qualified object identifiers where available,
network language identifiers and `F0..F3` flavour tokens. The original text path
encodes at most fourteen UTF-16 code units as hexadecimal bytes and suppresses
the command if any code unit in the complete source string exceeds 255. That
suppressed path still marks the flavour as broadcast. DYNAMIC/FONT delivery
sends DYNAMIC followed by ICON; the broadcast mark is set before the second
command. These original cache rules need deliberate handling in any future
executor and are not independent evidence of successful delivery.

A complete executor still needs source-backed key-function-indicator state,
image/font preparation, command and cache state, whole-form failure handling,
and independent physical acceptance. Successful synthetic branch execution or
C-Gate command acceptance does not establish label rendering or persistence.
