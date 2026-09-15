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
also has client-side conversion code for key inputs and sensors. The CLI does
not claim that the native command implements those additional rules.

Acceptance in `tests/test_conversion.py` uses the actual supplied C-Gate jar
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
