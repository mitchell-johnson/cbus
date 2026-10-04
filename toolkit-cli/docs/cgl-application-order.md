# CGL Application creation order

`cbus-toolkit cgate cgl` exchanges a bounded CGL 1.1 label graph with a
selected C-Gate endpoint. Both `cgate-mock` and cmqttd now keep a durable
Application creation roster per Network. The CLI preserves the received array.

The retained C-Gate 3.4.0.2001 fixture creates Applications 72, 0, 71, 255
and 66. Some arrive in the successful prefix of a later 408 refusal. Its
export returns **72, 0, 71, 66**, excluding 255. Previously numeric sorting
returned 0, 66, 71, 72, and the replay comparator hid that difference.

## Operator workflow

Use the known host, port, project and Network; the following placeholders must
be replaced with actual endpoint details. Export creates a new local file.

```sh
cbus-toolkit cgate --host HOST --port PORT cgl export PROJECT labels.json \
  --network NETWORK
cbus-toolkit cgate --host HOST --port PORT cgl import PROJECT labels.json
```

The normal typed import validates the entire document before transmission and
creates its documented project backup unless `--no-backup` is selected. This
stricter Python admission differs from native malformed-document imports that
can retain a successful prefix. Raw document transport tests cover those
captured prefixes separately; they are not typed CLI import acceptance.
If a terminal reply is lost, inspect the resulting database before deciding on
manual recovery. An uncertain receipt never authorizes automatic replay,
inverse deletion or a project reload.

## Durable behavior and compatibility boundary

| Operation | Application order |
| --- | --- |
| CGL import or typed database creation | A new actual Application appends once; existing objects retain position. CGL import preserves existing names; typed setters retain their own rename contracts |
| Rename or complete Application replacement | Retains the existing position |
| Admitted same-session raw `DBSET !ApplicationOID/Address` readdress | Moves the address in the retained position; ordinary SAFE Address setters remain open |
| Delete then recreate | Removes the old slot; the recreated object appends |
| Complete Network replacement | Retains surviving identities and appends new Applications in submitted document order |
| Admitted cross-project Network `DBCOPY` | Creates destination children in the source's available order; new object identities remain separate |
| Project copy, save/load, cmqttd restart, internal `cmqttd:KEY` archive | Retains the durable roster and unknown-history marker |
| Older JSON with no order field, or foreign XML/SQLite archive | Explicitly unknown historical prefix uses numeric order; later known creations append |

An unknown prefix is a compatibility disposition, not recovered native history.
Foreign archive formats have no private chronology extension. Internal snapshots
retain metadata because they preserve the cmqttd model. Array order and database
OIDs are separate facts; renaming and readdressing preserve the owned identity
where its database contract requires it.

cmqttd advertises:

```json
{
  "cgl_application_export_order": "tracked-creation-with-unknown-legacy-prefix",
  "cgl_group_level_export_order": "address-order-native-order-unverified",
  "cgl_pci_traffic": false,
  "cgl_controller_side_effects": false
}
```

Group/Level native creation order is still unproven by a discriminating retained
case. Their existing address-order normalization remains explicit. Nameless new
objects still refuse rather than reproduce native unsaveable project state;
Jackson exception detail, broader native identity acceptance and project
acceptance remain open in [issue 25](https://github.com/mitchell-johnson/cbus/issues/25).
Ordinary numeric whole-Application `DBCOPYSAFE` remains an opaque-success gap,
tracked separately in [issue 124](https://github.com/mitchell-johnson/cbus/issues/124).
A passing Network/project copy test does not establish that typed copy workflow.
Ordinary Application SAFE Address setters can still store an opaque field without
moving the canonical object; [issue 125](https://github.com/mitchell-johnson/cbus/issues/125)
tracks the typed `database set` workflow. A raw `cgate run` readdress test does not
establish SAFE setter parity.
This feature closes the narrower scope of
[issue 123](https://github.com/mitchell-johnson/cbus/issues/123) after its recorded
validation succeeds. It does not establish controller programming, private
Schneider archive interoperability, original GUI execution or full Toolkit parity.

## Evidence and validation

The original fixture remains byte-for-byte unchanged:
`rust/testdata/fixtures/native_cgate_cgl_routes.json`, SHA-256
`3a818506368c6eb6311125cb7f5a1272b5de6526b653d67b7ae197e043369490`.
The historical capture script retains its original provenance.
`research/cgl_application_order_vectors.py` derives the successor vectors
without re-executing native software. Exactly one of the existing 158 vector
rows changes: `cgl-validation-23`, only its Application array order.
The full capture has 163 structured rows; source replay selects 161, excluding
two original network-open/close rows. The 158-vector projection omits these existing five rows:

| Scenario / zero-based row | Retained command | Disposition |
| --- | --- | --- |
| `chain_setup / 33` | `NET OPEN` | Original network lifecycle excluded |
| `runtime_layer / 2` | `NET CLOSE` | Original network lifecycle excluded |
| `validation / 24` | `DBGETXML` for Application 255 | Native XML identity/readback scope remains open |
| `nameless / 6` | `DBGETXML` | Native nameless/readback scope remains open |
| `nameless / 7` | `PROJECT SAVE` | Maintained model refuses the native unsaveable state |

Source replay also retains its explicit XML-scope comparison exclusion and all
nine nameless rows outside native equality. New private-store assertions for
retained labels, including 255, do not establish a native scalar/XML getter.
These are separate scopes, not interchangeable acceptance counts.

Rust tests bind the complete captured export and reject a numerically sorted
actual response. The existing Python vector consumer uses the successor
comparator, with an independent sorted-output rejection regression. New public
CLI cases exercise both owned backends, database lifecycles, graph isolation,
raw prefix imports, typed preflight refusal, and an actual upstream 200 dropped
before the caller. Daemon-only cases restart a fresh owned process from the
recorded repository and an old missing-field shape, including internal archives.
They use synthetic closed networks and a no-contact trap; no house lights,
original Toolkit, native server or physical bus is used.
The new order-specific archive journeys exercise foreign XML and internal JSON;
they do not establish Schneider SQLite order acceptance.

Source and fresh installed-wheel execution are distinct gates. Exact case IDs,
CLI commands, tagged document framing, process cleanup, binary/package pins,
skips and input stability belong in the release report; registration alone is
not a test pass. The final report records those outcomes once execution finishes.
