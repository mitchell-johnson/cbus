# Classic DLT broadcast compilation and assessment

`dlt broadcast` compiles one retained classic label flavour into the original
Toolkit command sequence and assesses supplied outcomes. Both commands are
offline. They do not open a connection, send a label, save PP, change a Toolkit
cache or automatically retry a command.

```sh
cbus-toolkit dlt broadcast plan --input broadcast.json > broadcast-plan.json
cbus-toolkit dlt broadcast assess --plan broadcast-plan.json --outcomes outcomes.json
```

The request contains the selected model facts explicitly:

```json
{
  "format": "cbus-classic-dlt-broadcast-request-v1",
  "project": "EXAMPLE1",
  "network": 254,
  "application": 56,
  "application_oid": null,
  "group": 20,
  "level": null,
  "language": 1,
  "variant": 1,
  "tag_type": "TEXT",
  "tag_value": "Kitchen",
  "already_broadcast": false,
  "bitmap": null
}
```

Every field is required; unknown fields, Boolean numbers and ambiguous numeric
strings are refused. Application IDs are Lighting 48–95, Trigger 202 or Enable
203. An action `level` is admitted only for Trigger. The group can be null to
represent the original missing-group early return. `variant` is the Toolkit
1–4 selection and compiles to `F0`–`F3`.

When an application OID is supplied, the compiler uses the original qualified
`//PROJECT/!OID` target. Otherwise it uses the numeric project/network/application
path. The OID-to-application relationship is caller supplied; this offline
command cannot resolve or verify it. Network language selection, key/page
mapping and project label lookup are also upstream facts.

## Original dispatch behavior

| Input | Compiled behavior |
|---|---|
| Already broadcast, or missing group | No commands; retain the original cache mark |
| TEXT containing any UTF-16 unit above 255 | No command; original code marks the flavour broadcast |
| Empty TEXT or exact `<Default>` | Options `0`, data `10` |
| Other TEXT | Options `00`, first 14 Latin-1 bytes in uppercase hexadecimal |
| ICON | One `ICON` command with the decimal image ID |
| DYNAMIC or FONT with prepared data | `DYNAMIC`, then mark broadcast, then `ICON` |

The Unicode predicate scans the complete text, including characters beyond the
14-unit prefix. The dialog's separate 20-unit storage bound does not change this
delivery rule. `10` is the original literal byte, not a NUL clear. Native-to-peer
evidence preserves that byte and does not assign a display meaning to it.

ICON and DYNAMIC values must be canonical decimal image IDs in 0–65535. FONT
values must contain the original nine-comma form with a canonical image ID as
their first component. Its remaining components are retained as model context;
they are not interpreted as font rendering instructions.

DYNAMIC and FONT require `bitmap: {"width": N, "data_hex": "..."}` containing
prepared packed bytes. The source fixes height 16 and vertical offset 10; width
comes from the supplied model field (its original constructor default is 64).
The admitted native width is 1–240, and exactly `2 × width` bytes are required.
The compiler does not rasterize text, locate fonts or derive pixels from a tag.
Malformed original token combinations that produce invalid native commands
are retained in the source receipt and refused by the portable compiler.

## Outcome and recovery assessment

Plans expose ordered commands, their hashes, the original cache-mark event,
timeouts, the source request and a canonical plan hash. Assessment rederives the
plan before consuming any outcomes. Each supplied attempt must name the next
command index and matching command hash; duplicates, gaps, changed commands
and attempts after a terminal failure are refused.
The source command timeout is 20 seconds, overridden to 30 seconds for DYNAMIC.

Outcomes are a JSON object with format
`cbus-classic-dlt-broadcast-outcomes-v1`, the `plan_sha256`, and an `attempts`
array. A response entry contains `index`, `command_sha256`,
`"outcome": "response"` and `responses` (the response lines). An uncertain entry
instead contains `"outcome": "uncertain"` and a reason of `timeout`,
`connection_lost` or `send_error`. An empty attempts array records that no
command outcome has been supplied.

The original response parser can treat a `bad object` response as completion.
That does not establish native acceptance. Assessment reports original
completion and cache marking separately from conservative acceptance of the
supplied responses. It cannot authenticate those responses or determine device
state. First-command uncertainty leaves the original cache mark unknown; a
second-command failure leaves it marked because the original mark occurs
between the two commands. A simple replay with that mark retained would skip
the entire broadcast. The report therefore supplies a manual recovery
disposition and never generates a retry or resume command.

## Evidence and remaining scope

The original instruction replay and command-result source receipts are separate
from the native C-Gate acceptance fixture. The native fixture feeds compiled
commands into a fresh local C-Gate process connected only to an owned loopback
PCI simulator. The independent receiver observes both the uploaded bitmap
stage and its following ICON reference, and verifies saved synthetic state can
reload. It does not model the device's image cache, rendering or flash.
Label delivery is checked while the native network is open and may still be
synchronizing; a complete unit-discovery scan is not part of this acceptance.

The retained evidence is:

- [`classic-dlt-broadcast-original.json`](../research/fixtures/classic-dlt-broadcast-original.json):
  64 bounded replay cases, executing 22,127 original instructions across eight
  routines. Object getters, strings and command-call boundaries are synthetic;
  failure injection stops at the call boundary without Delphi exception unwinding.
- [`classic-dlt-broadcast-results-original.json`](../research/fixtures/classic-dlt-broadcast-results-original.json):
  25 parser cases, including sticky errors, prefix matching and `bad object`.
  Exception allocation/state storage and string primitives are hooked; no
  original socket processor or timeout runs.
- [`classic-dlt-broadcast-native.json`](../research/fixtures/classic-dlt-broadcast-native.json):
  11 compiled commands in nine delivery cases, three no-command cases, native
  responses, independent receiver stages and reload comparison from the owned
  native fixture. Command listings replace synthetic project/OID values with
  readable placeholders; assessment hashes bind the original generated inputs.

Run `test_dlt_broadcast.py`, `test_dlt_broadcast_review.py`,
`test_cli_dlt_broadcast.py`, `test_classic_dlt_broadcast_original.py`,
`test_classic_dlt_broadcast_results_original.py` and
`test_dlt_broadcast_native.py` with `PYTHONPATH=src:tests:.`. The source replay
uses the pinned `CBUS_TOOLKIT_EXE` and MAP; native acceptance requires the owned
local C-Gate settings used by the classic label tests.
`CBUS_DLT_BROADCAST_REPORT` selects the native receipt output path. A temporary
directory on a volume with sufficient free space avoids unrelated SQLite
failures when the system volume is full.

Full unit delivery still needs the key-function indicator inputs, key/group
selection, Save DLT Labels gate, two-phase PP save and whole-form error lifecycle
described in [the delivery source research](classic-dlt-delivery-original.md).
This compiler's complete scope is one explicitly supplied flavour and its
command/outcome sequence. Physical display and persistence acceptance remain
unestablished.
