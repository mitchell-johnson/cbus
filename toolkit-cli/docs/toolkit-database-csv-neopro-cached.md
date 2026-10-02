# NeoPro cached CSV identity

`toolkit-database-csv --cached-projection` accepts KEYB2, KEYB4 and KEYB6 at
exactly firmware `2.5.00` using
`cbus-toolkit-database-cached-projection-v2`. The detached JSON binds primary
and secondary Application identities, their complete retained Group membership
and the byte `SecondApplicationBlocks` mask. Display tags, Group address 255 and
cache traversal order cannot establish Application ownership by themselves.

```sh
cbus-toolkit toolkit-database-csv cached-neopro.json \
  --cached-projection --output new-report.csv
```

The command validates the whole input and completes the modeled projection
before creating a new file. Existing outputs are preserved. It performs no
provider/database/network reads or writes; the caller supplies the cache and
provider outcomes. These identities are authoritative within that input, not
a claim that a live project was freshly inspected.

## Exact v2 schema

The root retains `unit`, `group_cache`, `area_observations` and `group_save`
from v1, and adds `application_context`. The following complete synthetic
input deliberately places the secondary Group first and selects secondary
Application for all eight blocks. Area still resolves to `primary-255`.

```json
{
  "format": "cbus-toolkit-database-cached-projection-v2",
  "unit": {
    "identity": "owned-unit",
    "address": 21,
    "part_name": "Owned NeoPro",
    "tag_name": "Owned keypad",
    "unit_type": "KEYB2",
    "catalog": "OWNED",
    "serial": "",
    "firmware": "2.5.00",
    "primary": "Lighting",
    "secondary": "Secondary",
    "group_identities": [
      "secondary-255", "secondary-255", "secondary-255", "secondary-255",
      "secondary-255", "secondary-255", "secondary-255", "secondary-255"
    ]
  },
  "group_cache": [
    {"identity": "secondary-255", "address": 255, "tag": "Secondary Area",
     "oid": "OID-secondary-255", "references": []},
    {"identity": "primary-255", "address": 255, "tag": "Primary Area",
     "oid": "OID-primary-255", "references": []}
  ],
  "area_observations": [
    {"raw": "255", "completed": true},
    {"raw": "255", "completed": true}
  ],
  "group_save": null,
  "application_context": {
    "primary_identity": "primary-app",
    "secondary_identity": "secondary-app",
    "secondary_mask": 255,
    "applications": [
      {"identity": "secondary-app", "address": 57, "tag": "Secondary",
       "group_identities": ["secondary-255"]},
      {"identity": "primary-app", "address": 56, "tag": "Lighting",
       "group_identities": ["primary-255"]}
    ]
  }
}
```

Every object has exactly its documented fields. Application addresses and
identities are unique; Application identities cannot collide with Unit/Group
identities or Group OID tokens. The cache contains exactly the named primary
and configured secondary Applications. Each cached Group belongs to exactly
one Application, with unique addresses within that Application. Unit display
tags must match the named Application records. All eight ordered Unit Group
identities must resolve through the Application chosen by their mask bit.
Repeated Unit associations are retained; repeated membership declarations are
refused. A secondary identity of `null` requires an empty secondary tag and
mask zero. Address 255 denotes that unused secondary, rather than a configured
secondary record. Primary and secondary may explicitly name the same record.

The cache is bounded to 256 Groups, identities/text to the existing 256 UTF-16
unit bound and source JSON to 8 MiB. Duplicate JSON keys, excessive nesting,
extra fields, unknown identities, conflicting membership or routes, ambiguous
Area addresses and inconsistent tags/masks fail before output creation.
Existing families continue to accept exactly their v1 inputs and return v1
results; v2 is the bounded NeoPro contract. NeoPro v1 remains refused.

## Provider and Area outcomes

The retained finite provider domain has exactly two ordered observations:
`raw` is `12`, `13`, `255` or `invalid`, and `completed` is Boolean. Both Area
getters run even when the Area column is omitted. Every completed getter looks
up its address in the **primary** Application; `invalid` falls back to 255.
A first or second load refusal returns a partial result with
`area_load_failed`, no CSV report and no output file. A second refusal retains
the first completed reference state. A 12→13 transition removes the Unit's
Area reference from 12 and adds it to 13 while preserving unrelated references.

Missing Group 255 may be created in the detached model only when its lookup is
actually required and the caller supplies `group_save: {"completed": true}`
or `false`. Creation appends the existing modeled identity `created-255` to
the primary membership and retains the ordered create/save/reference events.
A declared save refusal stops with `group_save_failed`, retaining the created
record without a Unit reference. No database save is sent. Missing other Area
addresses, missing save outcomes, capacity exhaustion and created identity
collisions are refused. A completed projection refuses an unconsumed save
outcome; an earlier provider stop returns its partial state before later
outcomes are consumed. A distinct secondary Group 255
never substitutes for a missing primary Group 255.

CSV preserves all eight block positions for each key count, including repeated
associations, and marks Groups 9–16 `<N/A>`. Column order, comma-triggered quoting,
Unicode UTF-8 and CRLF serialization use the existing report serializer.
Results retain explicit Application context, ordered provider events and
terminal Group/reference state. Native XML continues to require its existing
Area 255; it derives Application identities from emitted OIDs or canonical
Application paths and passes membership/mask explicitly to the same projector.

## Evidence boundary

The [exact cached vector](../../rust/testdata/vectors/toolkit_database_csv_neopro_cached_v2.json)
contains all 256 mask row cases, secondary-first caches with separate Areas,
literal provider event/row outcomes and pinned earlier source facts. The new
`tests/test_toolkit_database_csv_neopro_cached.py` exercises all three families,
strict identity refusals, provider stops/reference movement/creation and
public offline subprocesses runnable against source or an installed wheel.

This composes retained original NeoPro loader/Area method rules with the
existing finite cached provider contract. It adds no original execution or
fresh original NeoPro provider capture. GUI/report-manager/locale behavior,
cold native acceptance, other profiles and whole-project parity remain in
[#56](https://github.com/mitchell-johnson/cbus/issues/56). The current registry
still admits 35 types; no factory/admission fact changes in this extension.
