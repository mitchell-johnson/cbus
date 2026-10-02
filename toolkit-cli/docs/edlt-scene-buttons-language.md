# SceneManager buttons and Language ownership

The native KEYGL5 / 5055EDL firmware 5.5.00 profile admits explicit
`scene-button-control` operations in a retained SceneManager sequence. Use the
same offline `--project-xml FILE --unit //PROJECT/network/p/unit` or database
`--auto-metadata --exclusive-project` path as
[selector callbacks](edlt-scene-selector-control.md). The owner derives control
facts from the exact project and ordered history; exported cache or control
JSON cannot supply those facts.

## Explicit Add clicks

```json
[
  {"op":"scene-selector-control","scene":1,"events":[
    {"event":"scene-current-changed","current":true},
    {"event":"trigger-selected","value":42,"choice_index":0,
     "choice_identity":"trigger:202/42"}
  ]},
  {"op":"scene-button-control","scene":1,"button":"add-action-selector",
   "dialog":{"cancel":false,"name":"New action"}},
  {"op":"get-selector-view","scene":1}
]
```

Read a selector view first and replace the example's trigger identity, ordinal
and value with the exact returned row. `button` is `add-trigger-group`,
`add-action-selector` or `new-lighting-group`. `dialog` supplies an explicit
accepted or cancelled outcome; an accepted `name` is optional. The Lighting
button additionally requires `selected_scenes`, an array of distinct scene
numbers from 1 through 8. Zero or multiple selected rows take the source early
return and create nothing. Cancellation skips the dialog's accepted OnOK name
and address validation; setup still requires a free provisional address.
Accepted creation uses the existing component name rules
and the first free address from 0 through 254.

These clicks retain several observable source behaviors:

- Action Add consumes the retained selected Trigger object, which may differ
  from the raw scene Trigger value after a direct edit. It does not infer a new
  selection or property write when the returned action is absent from the old
  bound Items collection.
- Trigger Add can explicitly select and write a returned row in the refreshed
  Trigger list. Later getter reservations remain separate creations.
- Lighting Add requests the scene's resolved primary or secondary application,
  then compares the returned **group address** with the application-choice
  values. In this profile, a returned address 0 or 1 can therefore select the
  corresponding application selector; a returned address 2 does not match.
  The handler does not insert a scene item.

Inspect `scene_button_control` in the nested operation result: `request`,
`callbacks`, `selected_item`, `early_return` and the no-inferred-callback facts.
`planned_creations` records the objects to materialize. Complete returned
Items, identities and values remain in the selector views. A successful
creation alone does not establish that a retained control selected it.

## Language changes in an ordered parent transaction

An earlier text-only `add-language-dialog` may now precede the single
SceneManager sequence in `edlt parent-transaction-plan` or database
`edlt-parent-transaction`. For example, choose an existing language as default,
then explicitly refresh a retained selector:

```json
[
  {"op":"add-language-dialog","selected_ids":[1],
   "preferences":"registered-defaults"},
  {"op":"scene-manager","operations":[
    {"op":"get-selector-view","scene":1},
    {"op":"set-action","scene":1,"action":7},
    {"op":"get-selector-view","scene":1}
  ]}
]
```

Language IDs and scene/action values must exist in the selected profile.
Selection order chooses the default according to the
[Language dialog rules](edlt-static-language-add.md). No host registry is
inferred. The sealed initializer independently replays the original public
Language prefix and verifies its exact XML projection. It admits the final
text-only Language boundary, including cancellation and semantic no-ops.
Image, FONT, opaque DLTP, ambiguous Language/default rows and unrelated XML
changes cannot grant this initializer capability.

Every initial scene retains its original DynamicAll label object and
generation. An already valid getter therefore still shows the old labels
after the Language boundary; an explicit ActionSelector setter or
trigger-current refresh obtains the current text labels. A scene-current
callback alone does not refresh DynamicAll. A Language change later in the parent history cannot enter an
earlier SceneManager view. Operation-1 Reset starts a fresh initializer.
Language refresh counts describe the modeled final XML boundary, not an
observed number of COM notifications or native per-row refreshes.

## Save and acceptance boundaries

The parent owns one PP save, with separate backup and target-project saves.
Known failures before PP save can restore the source. Lost successful PP or
project-save responses remain uncertain and are never replayed automatically.
Read [inventory timelines](edlt-scene-inventory-timeline.md) and
[native metadata/save rules](edlt-scene-selector-metadata.md).

The implementations use source-derived control behavior, synthetic literal
vectors and owned cmqttd/cgate-mock CLI journeys. They do not execute the
original modal form, Framework binding machinery or a physical eDLT. Automatic
currency selection, notification cascades, async dispatch, broader lexical
address profiles, original GUI acceptance and physical rendering remain open.
The owned-journey structural XML comparator preserves whitespace-only leaf
text. It drops whitespace-only text on elements with children and all
whitespace-only tails; it does not consult `xml:space`. These checks do not
claim byte-exact XML preservation.
