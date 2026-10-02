# Scene selector metadata and database saves

For KEYGL5 /5055EDL firmware 5.5.00, `get-selector-view` invokes the admitted
TriggerGroup then ActionSelector getters and returns the complete named
application, actual TriggerGroups, action and dynamic-label rows. It exposes
the observed action separately from `raw_action_selector`: trigger 255 returns
-1 without replacing an otherwise retained raw action. A valid getter preserves
the existing dynamic-label collection. The explicit trigger-current callback
performs the separate refresh.

Use the existing `edlt scene-manager-state` / `scene-manager-plan` commands with
`--project-xml FILE --unit //PROJECT/network/p/unit`, or the database
`cgate unit ... edlt-scene-manager --auto-metadata --exclusive-project` workflow.
The same nested operations work inside one `edlt-parent-transaction`. Read
[callback schemas](edlt-scene-selector-control.md) before preparing selections.

The manual optional `cbus-edlt-scene-manager-cache-v2` adds exact `trigger_list`
and `action_lists` to the unchanged v1 application and DynamicAll contracts.
Trigger rows are actual observed objects; the legacy lifecycle's synthetic
unused 255 row is not an actual selector choice. Each action list supplies its
group, completeness, and ordered `{address,name,formatted_display}` rows.
Names never establish identity. The normal primary/secondary values are 0/1;
they are distinct from the referenced application addresses.

Automatic metadata preserves the consumed DBGETXML child order and TagName
unless explicit display preferences apply. The owned Rust services normalize
their serialized database children by address; their tests use those observed
XML ordinals, separately from arbitrary-order declared-cache tests. A database
snapshot does not observe the operator's Toolkit registry or original currency
selection. Image facts must already be derivable under the existing native
metadata rules; this does not add pixels or invent an icon image.

For this new native selector profile, every listed Trigger Control action Level
must have matching numeric Address and Value. A conflicting pair refuses before
planning writes because the original reflection precedence between those fields
has not been established. This restriction applies to the new selector profile;
the existing v1/direct operation paths keep their historical admission rules.

Initial retained getter reservations precede the control history. Native selector
histories currently require existing post-load trigger/action objects and refuse
interleaved SceneManager Add dialogs. They do not borrow all later projected
objects from a final cache. Supporting source create-enabled getters and those
Add histories needs an exact per-callback creation timeline. Existing v1/direct
operation paths retain their historical creation behavior.

Earlier parent Add results enter the SceneManager's actual inventory at its
position. Its trigger/action lists stay separate from the final outer lifecycle
facts, so a later parent Add cannot influence its callbacks, validation or scene
save. Pending SceneName text remains pending across selector callbacks and
continues to prevent saving. When a direct Name binding is established, a
Name callback for a different scene refuses; explicitly rebind first. Shared
Name control text/read timing across scene switches remains unqualified. New owners and Reset start fresh control state;
caller JSON cannot inject it.

The native owner keeps the existing closed-project/exclusive ownership,
exact source-network lock, fresh stale checks, backup and full readback gates.
One owning PP save still crosses a separate project save. Before PP save, known
creation failures can use the existing rollback boundary. After an attempted
PP or project save, preserve uncertainty and never automatically replay.
Owned service save/reload does not establish original GUI, physical display,
device effects or power-cycle persistence. Issues 45,69 and deferred72–75 remain
open.
