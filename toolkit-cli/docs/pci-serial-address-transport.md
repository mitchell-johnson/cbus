# One-request selected-serial transport

`PCISerialAddressTransport` sends one explicit selected-serial co broadcast and
captures its bounded reply window. It is a low-level library primitive, with no
CLI exposure, inventory coordinator, empty-target guard, database operation,
retry or rollback. It must only be used with exclusive endpoint ownership and
independently established authority/preconditions for the physical operation.
It never reports movement or persistence as verified.

```python
transport = PCISerialAddressTransport(
    host, port=10001, local_unit=16,
    response_timeout=2.0, overall_timeout=5.0,
    max_bytes=4096, confirmation=b"g", command_checksum=False,
)
exchange = transport.send_serial_address(serial, destination)
```

The constructor accepts a numeric IPv4/IPv6 address without DNS or scope suffix,
port 1..65535, explicit local address 0..255, finite timeouts in (0,60], a byte
limit 1..4096, one confirmation byte g..z and an exact Boolean checksum option.
Overall timeout must strictly exceed the response timeout. Pure encoding and
receipt preflight reject an unknown/out-of-range serial or destination outside
2..254 before creating a socket. This primitive does not independently establish
the local identity, source location, destination vacancy, unit compatibility or
Local SAL setting. The co packet has no source-address field.

The object is one-shot. It opens one fresh numeric-IP socket and makes at most
one `sendall` call. No SMART reset, command retransmission, address STORE,
interface configuration, inventory request or native MATCHDB fallback is sent.
`send_attempted` is recorded before entering `sendall`; `send_completed` only
means that call returned. A partial send can have an unknown bus result, so the
report does not invent a sent-byte count or replay the request.

## Capture and deadline contract

The fixed response window starts immediately after `sendall` returns. Its
default 2000 ms duration matches original wired co's configured response timeout;
it is not a sliding quiet interval. A confirmation, matched receipt, PCI
rejection, unknown frame or malformed prefix does not terminate the window.
The transport retains the whole bounded capture and invokes the pure strict
receipt parser after closing the connection.

An absolute total deadline covers admission, socket creation, connection,
transmission and receive operations. It is checked before/after blocking steps.
An internal parent deadline can shorten it. The transport reserves a complete
response window before transmitting, then checks again after transmission. A
late send or insufficient remaining budget starts no receive operation. The
parent deadline wins exact ties; a response window must end strictly before it.
Socket timeouts use remaining absolute budgets. Operating-system scheduling and
socket cleanup are not preemptible by Python; late returns are classified rather
than accepted as within-budget observations.

`capture_complete` means the complete configured response window elapsed before
the parent deadline without an earlier capture termination. It does not mean a
valid reply arrived, the bus has no later traffic, or the unit moved. An empty,
rejected, malformed or conflicting full capture may still be complete as a
capture. EOF, byte-limit overflow, late data, insufficient budget, I/O failure
or interruption during capture makes it incomplete. The entire retained prefix
is preserved even if the next byte exceeds the limit. An exact 4096-byte capture
can complete if no further byte arrives.

Closing happens on every outcome. A failed close is reported separately and
leaves `connection_closed: false`; a completed capture remains a completed
capture. Following I/O failure or interruption, the only remaining socket action
is cleanup. No new network request or automatic recovery observation occurs.

## Result and exception evidence

`SerialAddressExchange` exposes `request`, `received`, `send_attempted`,
`send_completed`, `bytes_received`, `receipt`, `termination`, `capture_complete`,
timing, limits, `connection_closed` and structured errors. `.as_dict()` uses
format `cbus-pci-serial-address-exchange-v1` and includes:

* `correlation_status` and `retained_receipt_matches_request`: the pure parser's
  classification of retained bytes. A matching prefix can exist inside an
  incomplete transport capture. Inspect both these fields and capture evidence.
* `receipt`: full pure-parser evidence, including framing, confirmations,
  serial/source/destination/route checks and any trailing partial input.
* `bytes_received` versus `retained_bytes`: overflow remains visible when only
  the bounded prefix can be stored. `sent_byte_count` is always null.
* `movement_verified: false`, `persistence_verified: false`,
  `requires_independent_verification: true`, `automatic_retries: 0` and
  `inventory_performed: false`.

Termination values are `response_window_elapsed`, `overall_timeout`,
`insufficient_response_budget`, `byte_limit`, `late_data`, `disconnected`,
`connection_error`, `send_error`, `receive_error` and `interrupted`. They describe
transport observation, not commissioning success. The original exception phase
is retained in `errors`, including cleanup/final-timing failures occurring after
a completed capture.

Ordinary socket errors return partial evidence. Interruptions and unexpected
exceptions propagate as the original object with `pci_serial_address_exchange`
attached. The same result remains in `last_exchange`; the first error remains
in `last_error`. A secondary close, parser or clock failure does not replace an
already selected original exception. Received bytes are saved before sampling
their arrival time, and a failed final clock sample retains the last recorded
time and all previously captured bytes. No recovery decision should infer
non-movement from an exception, missing reply, PCI rejection or unchanged
partial observation.

## Evidence and limits

The exact source/bytecode hashes, ordinary/SRCHK packet forms and receipt limits
are pinned in [serial-address-codec-evidence.json](serial-address-codec-evidence.json).
Original native co's weak receipt handling and MATCHDB fallback findings remain
in [selected-serial-addressing-research.md](selected-serial-addressing-research.md).
The new primitive uses the stricter pure parser and does not call native
Unraveller.

`tests/test_pci_serial_address_transport.py` uses an independent literal TCP
peer for the real default two-second window, ordinary/SRCHK bytes, fragmentation,
late conflicting/truncated/malformed input, rejection and EOF. Fake sockets and
clocks test partial-send uncertainty, parent deadline ties, delayed connection,
late transmission/receives, no DNS, close failures and original interruption
identity with secondary failures.

[serial-address-transport-acceptance.json](serial-address-transport-acceptance.json)
records the transport against the independent serial-keyed fixture. Normal,
missing-reply, forged-success/no-move and wrong-source cases each have exactly
one co request. Separate read-only full inventories determine topology before,
after and after loading a new fixture instance. These inventories are test
orchestration, not calls made by the transport. Short explicit synthetic timing
is recorded. This proves fixture behavior only, not real firmware persistence.

The bounded movement coordinator is implemented with independent preconditions,
a durable recovery format, and exact after-inventory checks; see
[Selected-serial commissioning with independent observations](pci-selected-serial.md).
The earlier [proposal](selected-serial-coordinator-proposal.md) is retained as
design history. Broader device and firmware evidence remains separate work.
