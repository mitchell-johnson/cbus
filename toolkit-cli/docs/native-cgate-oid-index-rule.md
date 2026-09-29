# Original C-Gate shared-OID index rule

C-Gate 3.4.0 build 2001 does not reject duplicate OIDs. The earlier captures
([duplicate OIDs](native-cgate-dbsetxml-duplicate-oids.md),
[cross-kind](native-cgate-cross-kind-oid-mutations.md),
[five/six](native-cgate-five-plus-unit-oid-mutations.md),
[large/cross-Network](native-cgate-large-cross-network-oid.md) and
[nine/ten](native-cgate-nine-ten-unit-oid-mutations.md)) pinned bounded
shapes one at a time. This note records the general rule and the seeded probe
that validates it.

## Rule

The rule comes from a read-only review of the case-sensitive decompiled tag
database. No decompiled source is committed.

- Each project has one hashtable index from OID to object. A later `put`
  replaces an earlier one, so the object registered last wins.
- A full rebuild walks each Network in the project's list order, which is
  creation order. DBSETXML replaces a Network at its existing position.
- Within each Network, the walk registers the Network, then its Interface,
  then each Application in submission order with its Groups, Levels, TagDLTs
  and NetVars, and then each Unit in submission order. A Unit therefore beats
  any Application or descendant in the same Network. An object in a
  later-created Network beats everything in earlier Networks.
- The index is rebuilt after DBSET, DBSETSAFE, DBSETXML, DBCOPY, DBCOPYSAFE,
  DBCREATENET, PROJECT SAVE and project load.
- DBDELETE removes only the deleted object's own key and does not rebuild.
  The OID then returns 401 until the next rebuild. Keys of the deleted
  object's descendants stay behind, stale. A later DBDELETE through such a
  key returns 200 but changes nothing in the live tree.
- The earlier cross-Network captures created Network 254 before 253, so
  "Network 253 wins" was really "the later-created Network wins".

## Seeded probe

[`cgate_oid_index_probe.py`](../research/cgate_oid_index_probe.py) runs 12
seeds per profile against owned native C-Gate (`LocalCGate`, six verified
loopback listeners, unopened CNI `127.0.0.1:1`, cleanup confirmed) and
against both Rust servers. For three shared OIDs it records `DBGETXML !OID`:

1. after submission;
2. after SAVE/CLOSE/LOAD;
3. after an OID-targeted DBDELETE of each;
4. after an unrelated DBSET;
5. after another SAVE/CLOSE/LOAD.

| Profile | Fixture SHA-256 | Shape |
|---|---|---|
| [`mixed`](../../rust/testdata/fixtures/native_cgate_oid_index_probe_mixed.json) | `82c1169fb06d3807b8b65ea7f9b19cfc5077aac855bb5ec32f243061c13b8781` | 2–3 Networks in random creation/submission order; Applications with Group/Level descendants and Units share OIDs across Networks and kinds |
| [`units`](../../rust/testdata/fixtures/native_cgate_oid_index_probe_units.json) | `a63ba52e3a57067ee2da7f326c2021ec2f78cdac0a5c554fcec0a9e01c722734` | One Network; 2–16 Units and at most one leaf Application |
| [`cross`](../../rust/testdata/fixtures/native_cgate_oid_index_probe_cross.json) | `7a2149b2f23c5b9c3964333b234a9c65005f10390e5308b0dc02125e06482a91` | Two of Networks 250–254 created in random order, each holding one Unit or leaf Application per shared OID |

[`test_native_cgate_oid_index_probe.py`](../tests/test_native_cgate_oid_index_probe.py)
applies the rule above to each native plan. It predicts all 144 native
selections in every profile (12 seeds × 4 non-delete queries × 3 OIDs),
including stale descendant keys after an Application delete.

## Rust disposition

Both Rust servers now apply the rule where their model can represent the
shape:

- **Same-Network Units:** the count guards (`2..=10` for selection, 10 or 8
  Units at DBSETXML admission) are removed. Any number of same-OID Units in
  one Network, optionally with one leaf Application, select the final
  submitted Unit.
- **Cross-Network pairs:** Networks record a `created_seq` list position.
  DBCREATENET, `NEW`/`DBADDSAFE` Network creation and first import assign
  it, and DBSETXML replacement keeps it. For two Networks that each hold
  one Unit or leaf Application per shared OID, the later-created Network
  wins. The rest of each Network document may carry unrelated objects.
  Repositories without a recorded order keep the captured lower-address
  winner.
- **Rebuild:** a successful DBSET, DBSETSAFE, DBSETXML, DBCOPY, DBCOPYSAFE,
  DBCREATENET or PROJECT SAVE clears deleted-OID invalidation, as does
  project load. A deleted OID stays 401 even when one survivor remains.
- **OID-targeted Units:** DBDELETE and DBSETXML accept a Unit selected by a
  unique OID. DBDELETE of an absent OID returns 401.

`oid_index_probe.rs` replays the `units` and `cross` fixtures in-process with
exact step equality. `cross_network_oid_winner_follows_creation_order_through_restart`
checks that cmqttd keeps the creation order across a repository restart. The
probe itself was run against the `cgate-mock` and `cmqttd` binaries built from
this branch:

| Profile | cgate-mock | cmqttd |
|---|---:|---:|
| `units` | 180/180 | 180/180 |
| `cross` | 180/180 | 180/180 |
| `mixed` | 68/180 | 68/180 |

In `mixed`, both servers still refuse 17 of 29 Network submissions with 409,
without mutation. Those submissions contain Group/Level descendant OID
collisions, Application/Application collisions across Networks, or more than
one Application sharing an OID with Units. Because the refused Networks
never exist, later answers differ from native. For every accepted Network,
each Rust selection after submission and after reload equals the native
rule's prediction for that accepted subset (72/72). No selection was wrong.

Remaining gaps:

- Descendant collisions need an OID-indexed model for Group, Level and TagDLT
  identities before they can be admitted.
- Same-address Units in different Networks remain refused because their
  metadata keys would collide.
- Stale-descendant DBDELETE no-ops are not modeled; Rust refuses those
  shapes before they can arise.
