# SENLLA ordinary eight-key lifecycle component

`cbus_toolkit.senlla_ordinary_keys.load_ordinary_keys` projects the ordinary
eight-key loader and fresh recall hooks from explicit unit-state inputs.
It preserves all four raw nibbles through the locked template selection,
defaults zero timer/expiry values for retained timer templates, and models the
fresh form's ordered resets of incompatible recall categories sharing one
primary-group object. Group comparison uses object identity, including nil.
Zero and multiple block references have no primary group; singleton references
require the owning loader's object, including its per-application unused group.
The optional `block_references` argument preserves explicit ordered rows after
application collision transfers. The first retained reference supplies timer
and recall-store values, even when it is not the lowest set bit in the saved
mask. The default remains direct raw ascending order. Reference rows must match
their mask without duplicates. The
[ordered-reference source handoff](../research/fixtures/senlla-key-references-source.json)
records the native append-before-extract transfer and its literal reference
order; the component consumes that declared state without replaying callbacks.

The component covers all 65,536 valid four-nibble combinations. The full
source-derived registry contains 126 groups and 59 ordered templates; only 50
four-nibble combinations match, and the remaining 65,486 retain their raw
commands under the custom template. Masks preserve all eight block bits and
select the first reference for timer/level operations. Timer serialization uses
ordinary unsigned 16-bit seconds. Returned parameter arrays are detached.

The [source handoff](../research/fixtures/senlla-ordinary-key-source.json)
records 75 method pins and nine literal before/after vectors. The independent
[full numeric registry](../research/fixtures/senlla-ordinary-key-registry-source.json)
supports exhaustive comparison with the packaged reduced lookup. Focused
component and retained surface tests pass 33 parents and 247 separate subtests;
the exhaustive loop is one parent test, not 65,536 additional test IDs.
Two static-source reviewers agree with the component's defaults and callback
order. No original instructions or forms execute in these checks.

This is an internal building block for the complete owning SENLLA lifecycle.
It introduces no public CLI save action. Scene selectors, group creation and
application rebinding, inherited sensor normalization, fresh scalar controls,
the complete 93-parameter save and native/hardware acceptance remain separate
integration work. Existing read-only surface views retain their original scope.
