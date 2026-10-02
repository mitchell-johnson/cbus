# eDLT Application Add and Reset/Add histories

The KEYGL5 / 5055EDL firmware 5.5.00 automatic parent workflow supports accepted,
cancelled and repeated Application Add alongside the existing Group and Action
Add operations. It also supports operation-1 Reset followed by these Adds,
Applications, Corridor, supported widgets and one SceneManager. This is a
source-derived database workflow; original forms and physical devices are not
executed.

Use the existing `edlt parent-transaction-plan` command with `--project-xml`
and `--unit` for offline preview, or `cgate unit ... edlt-parent-transaction`
with `--auto-metadata --exclusive-project`. The live preview uses `--dry-run`;
apply requires the reviewed backup via `--backup-project`. The concrete command
and display-preference setup are in [the parent Add guide](edlt-parent-add-dialog.md).

An Application Add operation looks like this:

```json
{
  "op": "add-application-dialog",
  "field": "primary",
  "creation_preferences": {
    "allow_user_defined": false,
    "allow_legacy": false
  },
  "name": "New lighting application",
  "description": "Owned database application"
}
```

`field` is `primary` or `secondary`. Both creation preferences are required
boolean snapshots. The original fresh defaults are false; this command does
not read or attest a Toolkit registry. Optional `address` selects a listed free
address, `name` supplies an editable native name, and `description` defaults to
empty. `cancel: true` records the provisional dialog but allocates nothing and
writes no SelectedValue binding.

The ordinary eDLT creation list is 48–95, 112–114 and 136. Either enabled
preference expands it to 48–127 and 136. Existing application-combo choices and
creation choices are separate rules. Allocation selects the first ascending
free address in the selected Network, after initial getters and all earlier
accepted metadata operations. An occupied address, 255 or an address outside
the selected list refuses locally. A full list cannot open an admitted Add.

The source standard names are fixed: 56 `Lighting`, 95 `DALI`, 113 `Irrigation
Control`, 114 `Pool, Spa, Pond Control`, and 136 `Heating (Legacy)`. Those names
are not editable. Other listed addresses have an initially blank editable name
and need an explicit name for acceptance. Names and descriptions trim on
acceptance. Errors run in native order: blank name 2241; exact Project.TagName
match 2247; selected-Network ASCII case duplicate 2242; reserved-address
confirmation 3171; project-wide same name at another address 2244; then another
Network's same address with a different exact name 2245. Addresses 96–127 require
`confirm_reserved: true`. An identical address and exact name in another Network
is allowed. The complete native Project snapshot supplies these inventories;
partial caches cannot authorize creation.

The current metadata-name transport retains its 128-character, trimmed,
control-free name boundary and refuses `#`, repeated/non-ASCII whitespace and
XML-forbidden scalars. Descriptions must also be exactly representable by the
native line/XML transport and fit its bounded line. These are software transport
limits, narrower than the recovered interactive form. Nonempty Application
Description is assigned and checked as the exact issued-OID scalar property
before PP staging and after SAVE/CLOSE/LOAD. The current service omits that
property from Application XML, so the XML graph proof does not establish native
Description XML/export fidelity. Empty descriptions make no assignment and
claim no scalar null readback. The modeled host is a
standalone eDLT parent: the unrelated special branch for a simultaneously open
DIMDD4/DIMDD8 editor is not modeled.

For Reset followed by a fresh Application and Group, use this ordered history:

```json
[
  {"op": "reset", "active_tab": "widgets", "binding_variant": "audited-local-wiring"},
  {
    "op": "add-application-dialog", "field": "primary",
    "creation_preferences": {"allow_user_defined": false, "allow_legacy": false},
    "name": "Fresh primary"
  },
  {"op": "add-dialog", "field": "QuickStatusGroup", "name": "Fresh status"}
]
```

Reset requires the existing exact 874-parameter schema with original default
fields and one supported binding variant. It resets the database PP model,
retains the established identity exclusions, creates 21 fresh widgets and eight
fresh scene models, refreshes the controls, then inserts Time/Date in widget 10.
The source's initial scene/action getters run before Reset and their metadata
remains in the Project; Reset replaces the scene models without deleting that
metadata. Subsequent Add, widget getters and SceneManager use fresh defaults and
only the metadata visible at that operation. Contiguous Blank operations may
follow Reset. A later Add cannot make an earlier Corridor selection present.
Earlier Standby/Activation operations may enable a subsequent Action Add.

The parent manager rejects issued OIDs already observed in the original or
fresh pre-Add Project XML, including unrelated Units, Networks, Interfaces and
nested unnamespaced OID fields. This is an observed XML collision fence, not a
proof of the server's opaque identity index. It admits each creation receipt
before initialization; a collision stops before a
Level OID read, Value initialization or cleanup delete, and before any
Application description initialization. Ordinary native add callers retain
their existing behavior.
It creates objects in dependency order, initializes a nonempty Application description,
and stages one parent PP save. It verifies the complete resulting PP and native
Project through SAVE/CLOSE/LOAD. Source and unrelated metadata retain the existing
structural preservation checks. All whitespace-only XML text, including opaque
and `xml:space` content, is outside that comparison. It is not XML byte equality.
Backend serialization can enrich a minimal Level with empty TagsDLT; the existing
preservation guard detects it. This feature does not widen that backend contract.

Apply requires all Project Networks closed and idle and explicit exclusive
ownership. The reviewed backup is created once. Metadata creation, PP SAVE and
PROJECT SAVE are separate mutations; a lost save receipt remains uncertain.
The existing pre-PP-save rollback boundary is retained, and an apply attempt
cannot replay automatically. Keep the evidence and inspect fresh state after
an uncertain outcome.

The sanitized source proof is
[`edlt-application-reset-add-source-evidence.json`](../research/fixtures/edlt-application-reset-add-source-evidence.json).
It preserves the overload correction and original method/managed-source hashes
without vendor bytes. Literal policy cases are in
`rust/testdata/vectors/edlt_application_add_dialog.json`. Static-text/language
Add, unmodeled concurrent original editor history, original GUI acceptance and
physical controller behavior remain open. Deferred associated-Level COPY/LOAD
and selector work is unchanged.
