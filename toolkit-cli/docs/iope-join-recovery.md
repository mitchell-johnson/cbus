# IOPE Join Mode Recovery

`cbus_toolkit.iope_join_recovery.IopeJoinRecovery` implements the four
Join Mode Recovery choices from Toolkit 1.18's IOPE Power Failure form.
It admits IOPE1R1 (5752PP/1R), IOPE2R2 (5752PP/2R), and IOPE2C4
(5752PP/2R/2D), with exact UnitSpec layouts and firmware 1.0.00 through
1.2.99. A supplied catalogue number must match the model.

The editor exposes `show`, `plan`, `apply`, and `configure`. A plan requires
an explicit `recovery` value, identity, and positive same-network group
object evidence:

```python
from cbus_toolkit.iope_join_recovery import IopeJoinRecovery

editor = IopeJoinRecovery(spec)
cache = {
    "format": "cbus-iope-environment-groups-v1",
    "source": "owned disposable project snapshot",
    "applications": [
        {"address": 56, "groups": [20, 21]},
        {"address": 203, "groups": [40, 41]},
    ],
}
plan = editor.plan(current, identity=("IOPE2R2", "1.2.00", "5752PP/2R"),
                   group_cache=cache, recovery="quad-join")
```

The source string identifies evidence; it does not prove freshness. The
standalone IOPE workflow CLI independently checks this cache against the
closed native database before applying and saving. `show` requires no cache
and reports raw dependencies with unresolved group eligibility.

## Radio eligibility and bounded admission

The original form enables the recovery control through
`CIS_IJoinMode.IsJoinActive`. For these three IOPE classes, that predicate
requires `IsJoinModeSupported` and a non-unused first Join group object.
The second Join alone does not enable the control. The receipt pins the
first interface, its group/support thunks, and all inherited interface tables
through `TObject`. The helper's alternate interface is absent from that
ancestry. The inherited `QueryInterface` and `GetInterfaceEntry` dispatch
are also pinned.

A non-255 group address is not sufficient evidence of an existing group
object. Every assigned first or second Join must be present in the caller's
cache under its actual application. The primary application must be Lighting
48..95 and appear in the cache. Enable Control uses application 203.

The original loader selects each Join's non-255 Enable Control field before
its primary field. Full `SaveJoinModeAttributes`, however, saves both groups
under the **first** Join's application. This bounded recovery editor refuses
mixed effective applications and any Join with both its primary and Enable
Control fields populated. Those states require the full group workflow to
resolve their otherwise hidden group normalization. It also refuses a missing
first Join. A first-only assignment admits all four original radio choices.

## Load and save behavior

Loading gives the store bit priority. Otherwise the loader treats each
Join's primary and Enable Control startup flags as an OR: both Join flags
select Quad Join, only the second selects Second Join, and all remaining
combinations select First Join.

Every edit clears all four startup flags and the store bit, then applies:

| `recovery` | First startup | Second startup | Store |
| --- | ---: | ---: | ---: |
| `first-join` | 1 | 0 | 0 |
| `second-join` | 0 | 1 | 0 |
| `quad-join` | 1 | 1 | 0 |
| `restore` | 0 | 0 | 1 |

Only the startup pair for the first Join's application is set. The other
application's startup pair stays clear. The five writable parameters are
`PrimJoin1EnabledStartup`, `PrimJoin2EnabledStartup`,
`ControlJoin1EnabledStartup`, `ControlJoin2EnabledStartup`, and
`JoinEnableStateStoreEnabled`. Their masks are 0x3C at address 0x1C and
0x80 at address 0x3E; neighboring bits are preserved.

Both application bytes and all four Join group fields are read-only stale
check dependencies. Group/application editing, scene selectors, allocation
arrays, and other whole-dialog save normalizations are excluded. In
particular, this API does not run complete `SaveJoinModeAttributes`, which
rewrites group fields and allocation data beyond the radio's five bits.

Saved plans carry canonical options. Application regenerates a plan from its
expected snapshot and rejects forged changes, altered evidence, and
noncanonical JSON values. It checks session identity and schema, rejects
stale dependencies, verifies PP readback, and restores attempted staged
fields after an error. This editor stages changes without saving. The
standalone CLI owns the separate PP/project save and fresh-session reload;
uncertain saves must not be retried automatically.

## Evidence and limits

`research/fixtures/iope-join-recovery-source-review.json` pins the owned
Toolkit EXE/MAP, exact UnitSpecs, Power Failure form resource, 14 method
ranges, string literals, and inherited interface/VMT byte ranges. Fresh
private disassembly is retained outside the distributable source tree.

`tests/test_iope_join_recovery.py` covers all 32 original load states and
256 save vectors (both application branches, 32 prior bit states, four
choices), neighboring-bit preservation, first-only eligibility, mixed/dual
refusal, profile/schema checks, canonical replay, stale plans, rollback, and
unrelated scene/allocation preservation. Its optional owned-source test
verifies hashes and independently traverses each admitted class ancestry.
Native C-Gate save/reload evidence is recorded separately by the isolated
IOPE workflow test. These checks do not establish original GUI execution,
physical controller behavior, or real-unit acceptance.
