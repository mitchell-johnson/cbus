# C-Gate transport cleanup

The synchronous client preserves the original operation failure when socket
cleanup also fails or is interrupted. This applies to connection establishment,
command send/read, event reads and an exception leaving the client context.
The socket reference and buffered data are cleared before closing the socket;
the invalidated stream cannot be reused to receive a late response or replay a
command.

The first exception retains `cgate_cleanup_errors`. Existing sanitized messages
for operating-system transport failures remain unchanged. The CLI reports up to
16 cleanup errors, with each message bounded to 1,024 characters, and identifies
truncation. When the operation succeeded but closing fails, the close failure
still propagates. The label-clear CLI additionally retains the classified native
reply in that case; cleanup failure does not erase evidence of an attempted
request.

An independent fake socket reproduced the original failure before the correction:
a `RuntimeError` in the context body was replaced by `KeyboardInterrupt` from
`socket.close`. The correction passes 36 focused tests on Python 3.13.14 and
3.10.20, including existing framing, interruption and verified TLS tests and
eight new cleanup regressions. The tests cover all four cleanup entry points,
secondary cancellation, context success, sanitized transport errors, one send
without replay, invalidated buffers and CLI output. The final combined run adds
six clear-label CLI regressions:42 tests passed on each Python version with
unchanged input hashes; see [the focused acceptance record](../research/fixtures/cgate-cleanup-acceptance.json).

This correction is newer than both the audited 1,094-test checkpoint and the
subsequent frozen settings/commissioning wheel. It requires the next full native
wheel acceptance. It does not establish physical-device outcomes or reclaim
remote programming locks whose acknowledgement was lost.
