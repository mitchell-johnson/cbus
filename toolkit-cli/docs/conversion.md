# Native unit conversion

`cgate conversion` exposes C-Gate 3.4's internal database conversion engine.
The command grammar comes from the supplied `pu` and `pv` classes; the
conversion rules and destination handling come from `dg` and
`ConvertUnitRulesUtility`. The vendor help only lists the command names.
These commands do not program a physical device or save the project to disk.

```sh
cbus-toolkit cgate conversion check-catalog //TEST/254/p/20 DIMDU4 L5504D2U
cbus-toolkit cgate conversion catalog //TEST/254/p/20 DIMDU4 L5504D2U
cbus-toolkit cgate conversion check-move //TEST/254/p/20 //TEST/254/p/21
cbus-toolkit cgate conversion move //TEST/254/p/20 //TEST/254/p/21
cbus-toolkit cgate project save TEST
```

`catalog` converts the existing unit in place using the catalogue's default
firmware. `move` transfers programming to an existing replacement unit and
**deletes the source database unit**. Both commands first save the project and
create a separately named backup by default. `--backup-project NAME` selects
the backup name; `--no-backup` explicitly disables it. Moves currently require
both units in the same project. The Python API accepts an explicit
`backup_project`; it does not create one when this argument is omitted.

The native engine supports a narrower set of conversions than Toolkit's GUI:
same-type firmware changes and selected DIN dimmer/relay transitions. Toolkit
does not use this command. It converts units client-side with 292 registered
tweakers; see [toolkit-conversion-tweakers.md](toolkit-conversion-tweakers.md)
for that registry and the admitted DIMDN/DIMDU4 subset.

## Admitted pairs and the mapping table

C-Gate class `dg` admits an unchanged type and exactly these 15 source-to-target
pairs; every other pair returns `301 no` from both `CHECK` and `CONVERT`:

| Source | Targets |
| --- | --- |
| DIMDU4 | DIMDN8, DIMDN8F, DIMDN4, DIMDN4F, DIMDD4 |
| DIMDN4 | DIMDU4, DIMDN8, DIMDD4 |
| DIMDN4F, DIMDN8F | DIMDU4 |
| DIMDN8 | DIMDU4, DIMDD8 |
| RELDN4, RELDN8, RELDN12 | RELDN4A, RELDN8A, RELDN16A respectively |

The private `ConvertUnitMappingTable.xml` has 15 entries for 14 of these pairs.
Its duplicate DIMDN4F-to-DIMDU4 entry is ignored because C-Gate uses the first
match. DIMDN4 to DIMDN8 has no entry. The table uses 17 rules, not only
`channelProperties`, `setDefaultValue` and `resetToZero`; the others split,
join, scale and invert values into the C-Bus 3 per-channel parameters.

`cbus_toolkit.conversion_mapping` models the rebuild from the table, unit
specifications and catalogue, independently of C-Gate output. For each target
parameter, in specification order, C-Gate uses:

1. the first matching table pair's rules, if the source has stored PP values;
2. otherwise the same-named source PP string, copied verbatim; or
3. otherwise the rendered target default.

Every rule sees the unchanged target default, and the last rule's result wins.
An empty result omits the parameter. A same-type conversion copies the source
PP list unchanged. Mode 1 keeps the source tag, name and address. It writes
serial `00000000.0000` and the catalogue's default firmware. Mode 2 keeps the
destination tag, name, address, serial, type, firmware and catalogue number.
C-Bus 3 DIN dimmer and relay targets get new `Channel1..n` output channels.

Native behaviors that users must expect:

- `channelProperties` and `resetToZero` return an empty value when source and
  target arrays have equal length. The PP is then omitted and reads back as
  the target default. For example, DIMDN4 to DIMDU4 loses nine configured
  channel settings.
- DIMDN4 to DIMDN8 copies four-element arrays into eight-element parameters.
  Some rules also produce a bare hex digit such as `b` or a one-token `0`.
  C-Gate stores those strings, but a later PP LOAD of the unit fails with `408`.
- `CHECK` admits an unchanged identity, while `CONVERT` refuses it. The same
  refusal applies to a mode-2 move between units with the same type and
  firmware.
- A source with no stored PP skips every rule and receives only defaults.

Owned native C-Gate 3.4.0.2001 acceptance
(`tests/test_conversion_pairs_native.py`) ran all 15 pairs in both modes. It
used generated non-default source values and, for moves, non-default
destination values. The model matched every stored PP list, including order,
and every rebuilt identity and output-channel set. PP GET readback matched,
including the seven predicted PP LOAD failures. Values survived project save,
close and load. Fifteen refusal cases were checked for exact codes and no
mutation: incompatible and reverse pairs, a missing source or destination, an
incompatible destination, an unknown catalogue number, an unchanged identity
and mode 4. The sanitized receipt
`research/fixtures/convertunit-pairs-native-receipt.json` records hashes of the
jar, mapping table, catalogue and specifications, never their contents.

cmqttd and `cgate-mock` implement the same admission, rules, identity and
move-deletion semantics. They need the mapping table in the directory given
to `--cgate-unitspec` or `--unitspec`. Without it, `CONVERT` refuses with
`301` instead of guessing. The same harness (`research/convertunit_pairs.py`)
matched native PP lists for all non-C-Bus-3 targets. Three differences remain:

- The Rust database field map cannot store the C-Bus 3 `UnitType` device
  parameter beside the unit type, so that PP is not stored.
- Rust does not regenerate C-Bus 3 output channels.
- Rust PP LOAD accepts stored values that native C-Gate rejects.

The original DIMDN4-to-DIMDU4 acceptance in `tests/test_conversion.py` uses
the actual supplied C-Gate jar
and independently checks changed identities, retained group assignments,
backup contents, project save/reload, destination metadata and source removal.
It also records two native behaviors that must remain visible:

- For an unchanged DIMDN4 identity, `CHECK` returns `200 yes`, while `CONVERT`
  returns `301 no`. The CLI checks both responses and treats refusal as failure.
- A move from address 20 to 21 can retain PP `UnitAddress=0x14` while the
  database address becomes 21. The result reports
  `parameter_address_matches_database: false` and includes the complete before
  and after parameter snapshots. No physical address change is inferred.

Native mode 1 resets the serial number; mode 2 retains the destination's name
and serial number while transferring source programming. C-Gate can omit other
metadata when rebuilding the unit, which is why the CLI defaults to a project
backup. No automatic retry or restore is attempted after an uncertain failure.
