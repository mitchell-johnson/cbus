# Classic DLT unit-label lifecycle planning

`dlt unit-delivery plan` composes the source-backed classic label sequence from
explicit resolved key and language state. `assess` checks supplied operation
outcomes against that plan. Both commands are offline and have no execution or
automatic recovery option.

```sh
cbus-toolkit dlt unit-delivery plan --input unit-labels.json > delivery-plan.json
cbus-toolkit dlt unit-delivery assess --plan delivery-plan.json \
  --outcomes operation-outcomes.json
```

A minimal synthetic request that plans a clear for one missing primary group:

```json
{
  "format": "cbus-classic-dlt-unit-delivery-request-v1",
  "project": "LAB", "network": 254,
  "unit_application": 56, "unit_address": 10, "default_language": 1,
  "save_labels": true, "transfer": false, "block_dynamic_updates": true,
  "kfi_enabled": false, "reblock_session_open": false,
  "keys": [{"key": 1, "kfi": 0, "role": "ordinary",
            "target_state": "missing", "flavour": null}]
}
```

For a present selected flavour, `flavour` contains the complete
`cbus-classic-dlt-broadcast-request-v1` object described by the
[broadcast workflow](classic-dlt-broadcast.md). Its project, network and language
must match the unit request. Roles are `ordinary`, `scene` and `scene_modify`;
target states are `present`, `missing` and `unused` (scene levels exclude
`unused`). Use `present` with a null flavour when the target exists but the
selected flavour is absent.
Group 255 is unused for ordinary and scene-modify keys, so those roles cannot
declare it present. The scene-level branch has no group-unused check.

This is a model of the label lifecycle around a network save, not a complete PP
program serializer. The initial operation represents the inherited programming
save through its PP save, project save and status-loading effects, up to entry
into `AfterSaveProgrammingInformation`. Its required dynamic-label setting is
enabled. A caller-supplied successful outcome for that operation does not prove
hardware programming or project persistence.

## Explicit dependencies

The request names the project, network, unit address, unit application, resolved
network default language, Save DLT Labels, transfer and Block Dynamic Updates
states. The resolved default language must be an explicit integer in 1–255;
no default language is inferred or created. Save DLT Labels is independent of
Block Dynamic Updates. The transfer
flag separately allows the per-key label loop.

Keys are the original collection's ordered entries, numbered 1–8. The request
supplies each key's role, target presence and selected flavour. It must already
resolve primary groups, scene-modify control groups, scene trigger levels,
language and variant selection. The planner does not infer those objects from
PP variant slots, database XML or physical button/page positions. It requires
an initialized language/cache snapshot and does not recreate Toolkit's missing
language initialization or prior process state.

KFI values are explicit integers in 0–15. The original command contains eight
values; fewer supplied key entries are padded with zero. This portable input
bound does not establish original behavior for malformed KFI state.

KFI and key-clear command text uses the original relative network/application
form. A future executor would have to establish the exact selected project
context before using those commands. The application-label broadcasts retain
their separately compiled project-qualified targets. These different target
forms must not be silently interchanged.

## Ordering and failure boundaries

The lifecycle distinguishes the inherited programming save, optional KFI,
per-key label operations and a final reblock save. KFI precedes the label gate.
Scene-modify keys with absent/unused control groups and scene keys with no level
are skipped. Ordinary keys with absent/unused primary groups clear their unit
key. Missing flavours, blank or exact `<Default>` tags, and image flavours
without usable bitmap data also clear the unit key. The bounded planner accepts
that last case for scene and scene-modify labels. When label delivery is enabled,
it refuses ordinary DYNAMIC/FONT keys without a prepared bitmap because their
original bitmap-load
step can change the subsequent decision or fail outside the local handler.

A retained flavour's broadcast mark is reset before every key's dispatch.
Two keys using the same label can therefore emit the same application label
twice; the planner never deduplicates them. A retained clear marks the flavour
only after its save action returns. DYNAMIC/FONT broadcasts set the mark after
their first command and before their following ICON command, as in the separate
[per-flavour compiler](classic-dlt-broadcast.md).

The original local handler catches the `ECGateCommand` family only. Such a
failure during retained-flavour dispatch is collected, skips the rest of that
key and allows later keys. Other exceptions abort the sequence. Missing-flavour
and missing-primary-group clears, KFI and bitmap loading are outside that local
handler and their failures also abort. A final reblock save is reachable only
after the preceding sequence returns.

The final reblock sets `EnableDynamicLabels=0` and performs a separate save.
An existing session is reused. An owned session adds lock, start and load, then
end and unlock cleanup. Those internal operations are distinct from the initial
save; a failed or uncertain aggregate outcome cannot prove cleanup or reblocking.

## Supplied outcomes and evidence

Every supplied operation result must match the plan's exact operation identifier
and digest in the currently reachable order. A result reports `returned`,
`raised` with a `cgate_command` or `other` category, or `uncertain`. These are
caller-supplied operation observations, not authenticated C-Gate responses.
The assessment does not apply the per-flavour response parser to KFI or clears.

The outcome envelope uses format
`cbus-classic-dlt-unit-delivery-outcomes-v1`, the exact `plan_sha256` and an
`operations` array. Each entry carries an operation's `id` and
`operation_sha256`. A returned entry adds only `"outcome": "returned"`. A raised
entry adds `"outcome": "raised"`, `error_class` and a bounded `message`. An
uncertain entry adds `"outcome": "uncertain"` and a `reason` of `timeout`,
`connection_lost` or `unknown`. An empty array reports the first outstanding
operation without asserting any progress.

Uncertainty stops assessment and requires manual reconciliation. The tool never
resends a command, resumes a partial save, rolls back a device or treats a
broadcast cache mark as delivery evidence. It rejects outcomes for operations
that became unreachable after a failure. Initial save and final reblock
results remain separate.

The [retained delivery evidence](classic-dlt-delivery-original.md) contains
original branch observations from earlier bounded execution. The added
[static source receipt](../research/fixtures/classic-dlt-unit-delivery-source.json)
pins the orchestration and exception boundaries without a new
CPU replay. Portable tests compare retained decisions and exercise failure
paths; they do not execute the complete original dialog or establish physical
delivery, rendering or nonvolatile persistence.

The integration check passed 164 focused tests across the model, independent
review, public CLI and both source-receipt modules, with no skips. It included
fresh read-only inspection of 27 orchestration methods and 41 FONT methods.
No original CPU instructions, native service, GUI or household endpoint ran.

The [FONT preparation source report](classic-dlt-font-source.md) records the
remaining bitmap dependency. The original Windows
renderer uses installed font metrics and rasterization; project saving couples
the bitmap with an ANSI-codepage-encoded descriptor. An arbitrary host renderer
or locale cannot supply an equivalent prepared bitmap or metadata record.
