# Live eDLT label acceptance baseline

`cbus-toolkit cgate edlt-label-audit` turns the existing physical eDLT label
inventory into a deterministic acceptance receipt. It joins each stable,
serial-bound 9,216-byte KEYGL5 5.5.00 memory read with the 44-byte physical
`WidgetGroups` mapping populated by the same initial network synchronization.
It can create an immutable baseline or compare a later fresh read with one.

Create a baseline only after reviewing a complete read:

```sh
cbus-toolkit cgate --host 127.0.0.1 --timeout 120 \
  edlt-label-audit //PROJECT/254 \
  --write-baseline grenache-edlt-labels.json
```

The file is opened exclusively and is never replaced. An incomplete identity,
memory, observation or `WidgetGroups` read produces the partial audit on stdout,
returns nonzero and does not create a baseline. Re-run with a different output
path after resolving the failure; do not erase prior acceptance evidence.

Compare a later read with the saved state:

```sh
cbus-toolkit cgate --host 127.0.0.1 --timeout 120 \
  edlt-label-audit //PROJECT/254 \
  --baseline grenache-edlt-labels.json --mode configuration
```

The command returns zero only when the fresh acquisition is complete and the
selected comparison matches. Its `changed_units` rows retain every detected
change and separately mark whether the selected mode requires that change to
fail acceptance. Added or removed units always fail.

## Comparison modes

| Mode | Required stable state | Intended use |
| --- | --- | --- |
| `exact` | Physical serial/type/firmware, SHA-256 of all 9,216 physical bytes and `WidgetGroups` | Byte-for-byte readback after programming or firmware-controlled regression. |
| `configuration` | Identity, decoded label-bearing widget/scene/navigation/static-text records and `WidgetGroups` | Default label-configuration acceptance while tolerating changes in bytes outside the decoded label domain. |
| `labels` | Identity, label text/references/placement and `WidgetGroups` | Human-facing label drift checks that do not fail on unrelated decoded widget settings. |

Every baseline stores the source projections beside their SHA-256 values.
Loading recomputes the three fingerprints and rejects tampered or malformed
files before any C-Gate connection is used. The document is limited to 8 MiB,
256 units, 64 decoded static strings per unit through the underlying decoder,
and exactly 44 unsigned `WidgetGroups` bytes per unit.

## Physical and consistency guards

The audit uses one `NET SYNC ... fast` and one `NET CHECKUNIT` through the
fresh serial-inventory workflow. It does not run a second sync for
`WidgetGroups`; each `GET ... WidgetGroups` consumes the volatile cache produced
by that initial synchronization. Every successful memory image is bracketed by
physical IDENTIFY4 reads. Both serials must equal the fresh inventory serial,
the first 16 memory bytes must remain stable before and after the complete read,
and the static-text CRC must verify. A complete C-Gate rejection for one
`WidgetGroups` getter leaves the connection synchronized so later units can
still be reported. A timeout, malformed/incomplete transport reply or connection
loss prevents later getters from running.

Physical device snapshots remain sequential, so neither the inventory nor the
baseline is an atomic network image. `NET SYNC` leaves persistent configuration
unchanged, but cmqttd's KEYGL5 metadata sequence writes a volatile OEM selector;
the audit reports `physical_device_volatile_state_modified: true` and
`physical_device_modified: false`.

## Dynamic-label boundary

The audit preserves the inventory's single network-wide `CMQTT LABELS`
observation document as diagnostic evidence. It excludes those observations
from every fingerprint because they are a bounded ring of traffic seen during
the current cmqttd connection, are recipient-unverified, and do not read an
eDLT's current dynamic-label cache. A successful audit therefore verifies
static label configuration and the physical static mapping. It does not verify
dynamic-cache contents, display rendering, persistent flash after a later power
cycle, an atomic multi-device snapshot or physical button behavior.

Thirteen focused tests cover deterministic capture, one-sync ordering, exact versus
decoded drift, text and mapping drift, identity and membership changes,
incomplete reads, tamper detection, exclusive file creation, parser shape and
CLI exit status. The broader cmqtt label and WidgetGroups suites retain their
independent response, CRC, serial and malformed-input coverage.
