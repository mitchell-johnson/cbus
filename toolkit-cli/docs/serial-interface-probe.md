# Serial PCI probe and setup

`cbus-toolkit interface probe-serial PORT [--baud 9600] [--timeout 5] [--setup]`
opens one explicitly named serial device with pyserial (`serial` extra) and
classifies what is attached. It never scans or guesses ports.

```sh
cbus-toolkit interface probe-serial /dev/ttyUSB0
cbus-toolkit interface probe-serial /dev/ttyUSB0 --setup
```

## Wire sequence

Every frame is taken from an existing transport; none is new protocol:

1. Exclusive open at 8N1 (pyserial `exclusive=True`, an advisory `flock` on
   POSIX; Windows ports are always exclusive). `--baud` accepts the six native
   PCI rates 9600, 4800, 2400, 1200, 600 and 300. Stale input is discarded.
2. Three `~\r` resets and the `|\r` SMART/CONNECT shortcut, each after the
   100 ms delay used by cmqttd's `PciClient::pci_reset`, then a 200 ms settle
   window. Those bytes (basic-mode echo, power-up notices) are retained but
   only checked for the printable-ASCII PCI repertoire.
3. BASIC `@1A2001` local-address discovery, IDENTIFY attributes 1 (type) and
   2 (firmware), and RECALL of parameters 0x30 and 0x42 (one byte each) and
   0x21 (two application-address bytes), using `PCIClient`'s correlation.
4. Only with `--setup` and a `present` result: the four device-management
   frames `A32100FF`, `A32200FF`, `A342000E`, `A3300079` that `pci_reset`
   sends without confirmation, then the same RECALLs with command checksums
   (0x79 enables SRCHK). `setup.verified` is true only when the readback is
   `0x79`, `0x0E` and `FFFF`. A Python test pins these frames against the
   Rust `init_sequence_bytes` string.

Without `--setup` no A3 frame is sent (`configuration_writes: 0`). The reset
and SMART/CONNECT still change the PCI's volatile session mode, exactly as
every cmqttd connection does. Nothing is retried.

## Outcomes

| `outcome` | Meaning |
| --- | --- |
| `present` | Local address, identity and option bytes were read back |
| `absent` | The port opened, but no byte arrived before the deadline |
| `timeout` | Bytes arrived but the exchange did not complete; partial identity is kept |
| `busy` | The open failed because the port is locked, in use or not permitted (`EBUSY`, `EAGAIN`, `EACCES`, `EPERM`, Windows access denied) |
| `malformed` | Bytes outside the ASCII repertoire, undecodable frames, or a loopback echo of the probe's own command |
| `not_found` | No such device, or a path that is not a terminal (`ENOENT`, `ENODEV`, `ENXIO`, `ENOTTY`) |
| `rejected` | The PCI answered with a refusal (`!` or an unsuccessful confirmation) |
| `error` | Another I/O failure after opening |

The exit status is 0 only for `present`, and with `--setup` only when
verified. The JSON retains every sent frame with its phase and offset and up
to 64 KiB of received bytes. Identity is attributed only to the PCI on the
explicit port; `absent` does not prove that no interface is attached (for
example, a PCI at another rate).

## cmqttd

`cmqttd --serial DEVICE` opens its PCI exclusively (TIOCEXCL and `flock`), so
a concurrent `probe-serial` of the same device reports `busy`. C-Gate
`PORT LIST` always reports cmqttd's selected serial endpoint `inuse`, adding
it when the host port library does not enumerate it (a pseudo-terminal), and
`PORT PROBE serial` of that endpoint returns `431` without opening it. On
macOS a pseudo-terminal rejects the line-rate ioctl with ENOTTY; only that
failure is retried once without a rate.

## Evidence and limits

`tests/test_pci_serial_probe.py` drives the probe through real pseudo-
terminals. Its serial peer wraps the independent `PCISimulator` decoder with
reset, SMART/CONNECT, basic echo and A3 option handling, and covers every
outcome, exclusive-lock contention, setup verification and mismatch, and the
CLI. A TIOCEXCL-holder case skips on platforms whose pty driver does not
enforce TIOCEXCL (macOS). `rust/cmqttd/tests/system_serial_pty.rs` runs
cmqttd on a pty relayed to the scripted fake PCI and checks the init frames,
`PORT LIST`, the `431` refusal and live MQTT control.

These are simulator and pseudo-terminal results only. No physical PCI, USB
serial adapter, native C-Gate/Toolkit serial differential, alternate-rate
detection, power-up option (0x41) handling or Windows COM acceptance has been
performed.
