# Thermostat owner CI regression repair

[Issue 118](https://github.com/mitchell-johnson/cbus/issues/118) tracks the concrete
regressions in [PR 117](https://github.com/mitchell-johnson/cbus/pull/117).
The earlier [CI run](https://github.com/mitchell-johnson/cbus/actions/runs/37173737354)
failed. Its installed-wheel selection reported 32 failures: 17 stale receipt
and derivative guards, 14 changed malformed-operation diagnostics, and one
outdated exact backend roster. Source offline testing stopped at the parity
register gate; separately audited Rust and both client/backend jobs passed.
Native and physical jobs were skipped.

The repair routes the established operation-name validation before the new
quick-zone family. Nonstring names again return the exact structured error
`Output operation name must be a string` before client construction. The roster
guard preserves every earlier identity and digest and separately requires all
19 quick-zone owner cases for each backend, plus their CI body requirements.
The full explicit roster now contains 945 unique identities.

The maintained differential producers actually executed again. Each owned
loopback server passed 11 tagged-session cases, 12 Unit XML cases and two
combined Network readbacks. Existing debug binaries were reused against the
unchanged Rust source closure. The original capture bytes stayed fixed; no
original application, VM, house network or physical device was used. Validated
public derivatives preserve every non-coordinate field and bind their new raw
archives. The parity register was regenerated and both generator checks passed.
This is fresh execution, not replacement of old fingerprints.

| Focused validation | Actual result |
| --- | --- |
| Source seven-module selection | 253 parent passes and 559 passing subtest events; one filesystem permission failure. |
| Source generator retry | The one blocked case passed with access to its disposable snapshot directory. |
| Fresh installed wheel, same seven modules | 254 parent passes and 559 passing subtest events; no failures or skips. |
| Earlier schema/roster selection | 48 passes; overlaps the selections above. |

All 32 previously failed CI identities occur as passing parent cases in the
fresh installed-wheel result. These counts overlap and must not be added.
No unified all-passing source epoch is claimed. The permission failure and its
successful targeted retry remain separate records. All 394 package files match
source, wheel ZIP and installation; the wheel SHA-256 is
`22e6eba22dce21f96bf40595e0cd0fc8b1e6929a497726decc6ab39f6331cd77`.
A separate interpreter check observed five correct installed module origins;
it does not establish continuous pytest or subprocess import tracing.

The [public receipt](../research/fixtures/thermostat-owner-ci-repair-release-20261004.json)
pins changed files, actual result artifacts and every prior failed identity.
No full local suite ran. The previous failed CI run stays failed; subsequent
publication CI must be evaluated separately. The category ledger remains
18/42, its functional denominator is incomplete, and broader thermostat work
in issue 42, original form scheduling and hardware acceptance remain open.
