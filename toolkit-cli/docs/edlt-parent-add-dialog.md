# Corridor and Activation Add dialogs in one eDLT parent save

The automatic KEYGL5 / 5055EDL firmware 5.5.00 parent transaction accepts
Corridor Group Add, Activation Group Add and Activation Action Add histories.
It models accepted and cancelled dialog outcomes from pinned Toolkit 1.18.0
sources. It creates the accepted database metadata and stages all supported
parent controls through one PP SAVE and one target PROJECT SAVE.

Use a complete native project snapshot for an offline preview, or use the
existing database workflow with `--auto-metadata --exclusive-project`.
Caller-supplied partial caches cannot allocate an Add dialog object. The
selected Project must contain its explicit `TagName`: duplicate-name checks
use that scalar, independently of the project's command address.

For example, put this ordered history in `operations.json`:

```json
[
  {"op": "standby", "enabled": true},
  {"op": "activation", "wake_mode": "trigger-event", "group": 7},
  {"op": "add-activation-group-dialog", "name": "New wake trigger"},
  {"op": "add-activation-action-dialog", "name": "Wake action"},
  {"op": "add-corridor-dialog", "field": "link_group", "name": "Link"},
  {"op": "add-corridor-dialog", "field": "office_group", "cancel": true},
  {"op": "add-corridor-dialog", "field": "corridor_group", "name": "Corridor"},
  {"op": "corridor", "edits": [{"field": "seconds", "value": 300}]},
  {"op": "measurement", "page": 1, "position": 1, "device_id": 42, "channel": 1}
]
```

Corridor Add requires an explicit display-preference document. An explicit
all-false profile is a valid choice; it establishes name sorting rather than
inferring a preference from XML child order:

```json
{
  "format": "cbus-edlt-display-preferences-v1",
  "registry_key_present": true,
  "values": {
    "DisplayHexAddress": 0,
    "DisplayAddressValue": 0,
    "SortModeApplications": 0,
    "SortModeGroups": 0,
    "SortModeLevels": 0
  }
}
```

Preview without connecting:

```sh
cbus-toolkit edlt parent-transaction-plan snapshot.json \
  --project-xml project.xml --unit //PROJECT/254/p/20 \
  --operations operations.json --display-preferences preferences.json
```

Preview on an owned database, then remove `--dry-run` after reviewing the
returned plan, inventory and closed-network guards. For apply, remove
`--dry-run` and add `--backup-project BEFORE_ADD`:

```sh
cbus-toolkit cgate unit --lock-address //PROJECT/254 \
  --source /db//PROJECT/254/p/20 --dry-run edlt-parent-transaction \
  --auto-metadata --exclusive-project \
  --operations operations.json --display-preferences preferences.json
```

Each new operation accepts optional `address`, `name` and `cancel` fields.
Addresses are integers 0..254. Corridor requires `field` equal to
`link_group`, `office_group` or `corridor_group`. Activation uses separate
`add-activation-group-dialog` and `add-activation-action-dialog` operations.
An omitted address uses the first free address in the complete inventory at
that point in the history. Reserved 255, occupied explicit addresses and full
inventories refuse before database creation.

Group Add seeds the application-specific group noun and first-free address.
Accepted names trim before blank, exact Project.TagName and ASCII-insensitive
duplicate checks. Action Add seeds `Level N`; selecting a different address
retains that seed because it does not begin with the dialog's `Action
Selector` noun. Action duplicate checks use the entered untrimmed text before
storing the trimmed name. A new action has Address=Value. The current command
transport further requires a trimmed name of at most 128 characters without
controls, `#`, repeated/non-ASCII whitespace or XML-forbidden scalars. These
transport limits are narrower than the recovered interactive dialog.

A cancelled operation records its provisional seed and first-free address,
creates nothing and writes no selected-value binding. Repeated accepted Adds
retain every created object; each reply updates the owning control in order.
Office and Corridor Add are disabled while Link is 255. Activation Group Add
requires enabled standby and event mode 2 or 3. Action Add requires mode 3 and a
selected non-255 trigger. An earlier Standby or Activation operation can make
those controls available. A later operation cannot supply an earlier dialog's
state. Later explicit controls may change an earlier accepted binding while
its created object remains in the history. Duplicate ordinary operations for
the same owning panel remain refused.

New Adds can share a parent save with the existing generic `add-dialog`
fields, Applications and one SceneManager history. They share complete
inventories and exact getter/dialog creation receipts. Initial scene getter
creations occupy addresses before the first Add, including histories without
a SceneManager operation. Initial missing Corridor selections are cleared
from the initial complete inventory; a later-created group cannot make them
present retroactively. After an Application switch, each Corridor Show uses
the inventory at that operation, before any later Add. The plan retains
these absence facts for the guarded canonical replay. Inspect
`initial_dialog_show_normalizations` and `ordered_dialog_show_normalizations` in the
returned parent transaction plan. Objects created by an
earlier SceneManager operation occupy addresses for later parent dialogs;
preceding parent-created Levels occupy addresses for SceneManager Action Add.
Place SceneManager before every Scene widget, as required by the existing
parent transaction. The returned `resolved_operations` records each dialog's
pure `parent-add-binding` event at its original position. Those events do not
perform standalone saves.

The outer manager owns the reviewed backup, fresh source/cache checks,
issued-OID binding, metadata creation, PP staging, exact scalar/readback
verification and SAVE/CLOSE/LOAD sequence. All project Networks must be
closed and idle, and the caller must own the project exclusively. Native
metadata creation, PP SAVE and PROJECT SAVE remain separate operations.
Automatic rollback is limited to the existing pre-PP-save boundary. After an
uncertain save, retain the evidence and inspect fresh state; there is no
automatic replay or restoration.

The source fixture
[`edlt-parent-add-dialog-source-evidence.json`](../research/fixtures/edlt-parent-add-dialog-source-evidence.json)
contains source hashes, method ranges and recovered rules without vendor
code or executable bytes. The independent pure vector is
`rust/testdata/vectors/edlt_parent_add_dialog.json`. Software tests and owned
mock/daemon journeys do not execute the original forms, render their controls,
observe a physical wake event or establish full Toolkit parity.

Application Add remains unresolved because its native dialog maximum depends
on the hosting form pointer's low byte. Static-text/language Add and a
Reset-fresh Add binding history remain outside this new contract; retained
pre-Reset inventories cannot represent the fresh Reset graph. A previous
Toolkit process that declined auto-add is also unmodeled: exact getter
creation uses the source model's fresh `bAdd=true` default. Image-dependent
metadata still requires established project/DLTP facts.

The existing structural XML preservation comparison ignores all
whitespace-only text, including opaque or `xml:space` content. It compares
other text, attributes, comments, processing instructions and unrelated
objects. It is not byte-for-byte XML preservation. Existing backend Level
serialization can append an empty `TagsDLT` to a previously minimal Level
when a project is saved; the preservation check detects that change. Owned
positive fixtures use explicit complete blank label collections and do not
claim that minimal-Level round-trip limitation is repaired.
