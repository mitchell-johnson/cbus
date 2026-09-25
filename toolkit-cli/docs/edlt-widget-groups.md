# Live eDLT WidgetGroups mapping

`cbus-toolkit cgate edlt-widget-groups` consumes the physical KEYGL5
`WidgetGroups` mapping exposed by cmqttd's embedded C-Gate service:

```sh
cbus-toolkit cgate --host 127.0.0.1 --timeout 120 \
  edlt-widget-groups //PROJECT/254/p/5
```

The unit must be a fully qualified `//PROJECT/NETWORK/p/UNIT` path. The command
uses the existing C-Gate connection and performs exactly these operations, with
no retry:

1. `NET SYNC //PROJECT/NETWORK`
2. `GET //PROJECT/NETWORK/p/UNIT WidgetGroups`

The first operation performs the native OEM `09 00` parameter-`0xFA` recall
and must finish with status 200. The getter must be exactly one final
status-300 line with the requested canonical path and exact
`WidgetGroups` attribute. Its value must contain exactly 44 canonical unsigned
decimal bytes, separated by commas without whitespace. Missing, extra,
negative, signed, non-decimal, or values outside 0..255 fail the command before
any result is printed.

The JSON format is `cbus-edlt-widget-groups-v1`. It preserves the 44 opaque
bytes as `widget_groups` and their exact native spelling as
`native_decimal_csv`. `source: physical-synchronized-cache` means the
network-wide physical `NET SYNC` populated cmqttd's volatile cache and the GET
read consumed that cache. `widget_groups_device_readback: true` refers to that
physical synchronization; GET is not a second direct device read.

cmqttd only populates this property when the synchronized address has MMI state
one, exactly one known IDENTIFY4 serial, and matching configured and fresh
KEYGL5 types. State two, state three, zero-serial, and multi-serial addresses
receive no source-address-only metadata read; their property getter returns 404
and this command emits no success document. A reconnect or transport loss
during synchronization returns 408 rather than committing the old snapshot.

Network synchronization does not change persistent device configuration, but
the KEYGL5 metadata sequence writes a volatile OEM address-16 selector before
reading `Application` and `Application2`. The JSON records both facts as
`persistent_configuration_read_only: true` and
`volatile_oem_selector_write: true`; at the document level it reports
`persistent_device_configuration_modified: false` and
`physical_device_volatile_state_modified: true`. Synchronization observes the
entire network sequentially. The report therefore keeps
`network_snapshot_atomic: false` and `physical_observations_sequential: true`.
It also reports `dynamic_label_cache_readback`, `rendering_verified`, and
`persistence_verified` as false. WidgetGroups is a static opaque mapping, not a
query of an eDLT's existing dynamic-label cache, proof of display rendering, or
proof of persistent storage. The command never opens a direct PCI/CNI
connection and does not update the project database.

Use `CMQTT CAPABILITIES` to confirm `edlt_widget_groups: true` before depending
on this service extension. A missing property, unsupported device, failed
synchronization, non-success response, or malformed response is an error; the
CLI emits error JSON on stderr and no success document on stdout.
