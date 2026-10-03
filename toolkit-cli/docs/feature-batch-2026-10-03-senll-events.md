# Ordered SENLL controls and Lighting event filters

This batch adds explicit application/group histories for SENLL ST7
2.0.01..2.4.99 and opt-in application, group and source selectors for the live
Lighting event stream. It integrates with DIN save PR81 and main83b49d10.

The sensor history models ascending eight-block load/collision callbacks,
hidden PEC/SingleJoin/Corridor clearing, and separate DualJoin/PIR getter facts.
It preserves the zero runtime InputKeys profile and performs the existing
forced save last. Legacy flat plans keep their previous behavior. The inventory
is bounded: missing objects, creation decisions and objects established only by
AreaGroupAddress or SceneTable refuse before staging. Read
[sensor controls](senll-application-controls.md) for causal positions and limits.

The event selectors preserve raw records, timestamps, literal source zero,
duplicates and order. Matching rows count toward `--count`; overflow always
survives filtering and returns nonzero. No selector retains the old output
shape. Read [event filters](application-event-filters.md) for the admitted
native Lighting grammar and remaining Application Log work.

The frozen source and a fresh installed wheel at `0bade16d91c4e7fb9a4ee7eb7879d371bafac7eb`
each passed **144 parent tests and 1,014 separate subtests**, with five skips and
zero failures/errors. Both ran all **22 public sensor cases** on owned
`cgate-mock` and `cmqttd`: 16 positive cases, two lost successful-save replies
without replay, and four read-only refusals. All 378 package files match
source/ZIP/installed bytes; 3,595 frozen inputs and both binaries remained
unchanged. Independent static review checked all 26 method pins and the final
getter/callback boundaries. No original instructions or hardware executed.

The exact ten-module selection, artifact hashes and skip IDs are in the
[release receipt](../research/fixtures/senll-events-owned-release-20261003.json).
The five skips require the original Toolkit source-receipt inputs, native
SENLL acceptance, two native sensor CLI workflows and native event acceptance.
Historical preflight failures and successful pre-review scopes are retained
separately rather than counted as final acceptance.

Six modeled compatibility receipts cover 64 primary comparisons plus four
combined checks. The final Makefile update required refreshing only the four
tagged/Unit receipts, comprising 46 primary comparisons and four combined
checks; two unchanged SESSION receipts retain their exact source bindings.
Maintained sanitization, inventory/register and skip-census checks pass. The
native selection remains 259 required/selected tests across 728 test modules.

Full suites were deferred per the user's speed instruction. `coverage
--require-complete` remains nonzero. Issues41 and54 remain open for additional
sensor inventories/profiles, original GUI/native lifecycle, Application Log
controls, routed event/MQTT coexistence and physical acceptance. Outcome
annotations follow frozen executions; publication-head CI is separate.
