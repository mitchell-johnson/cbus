"""Pure-stdlib C-Bus serial framing helpers for the behavioral harness.

Deliberately does NOT import the `cbus` package: the behavioral suite must
keep working against the Rust implementation after the Python package is
removed. This is an independent, minimal re-implementation used only to
*inspect* traffic; the golden vectors are the authority on full parsing.
"""
from typing import Optional

HEX_CHARS = b'0123456789ABCDEF'
CONFIRMATION_CODES = b'hijklmnopqrstuvwxyzg'


def cbus_checksum(data: bytes) -> int:
    return ((~sum(data) & 0xff) + 1) & 0xff


def add_cbus_checksum(data: bytes) -> bytes:
    return data + bytes([cbus_checksum(data)])


def validate_cbus_checksum(data: bytes) -> bool:
    return len(data) >= 1 and data[-1] == cbus_checksum(data[:-1])


class ClientFrame:
    """One CR-terminated command received from a C-Bus client."""

    def __init__(self, raw: bytes):
        self.raw = raw
        self.is_reset = raw == b'~'
        self.is_smart_connect = raw in (b'|', b'||')
        self.basic = not raw.startswith(b'\\')
        self.conf: Optional[bytes] = None
        body = raw[1:] if raw.startswith(b'\\') else raw
        if body.startswith(b'@'):
            body = body[1:]
        if body and not self.is_reset and not self.is_smart_connect \
                and body[-1:] not in (b'',) and body[-1] not in HEX_CHARS:
            self.conf = body[-1:]
            body = body[:-1]
        self.payload = body.decode('latin-1')  # base16 command text

    def payload_bytes(self) -> Optional[bytes]:
        try:
            return bytes.fromhex(self.payload)
        except ValueError:
            return None

    def __repr__(self):
        return (f'ClientFrame(payload={self.payload!r}, conf={self.conf!r}, '
                f'reset={self.is_reset}, smart={self.is_smart_connect})')


def split_client_frames(buf: bytearray):
    """Consumes complete CR-terminated frames (and bare ~ / | tokens) from
    buf, yielding ClientFrame objects. Leaves incomplete data in buf.
    """
    frames = []
    while True:
        # bare reset tokens are not CR-terminated by all clients; the
        # python client sends '~\r' so a plain split on CR handles it.
        idx = buf.find(b'\r')
        if idx == -1:
            # handle a bare '~' with nothing else pending
            if buf == b'~':
                frames.append(ClientFrame(b'~'))
                del buf[:]
            break
        chunk = bytes(buf[:idx])
        del buf[:idx + 1]
        if chunk == b'':
            continue
        # a chunk may contain multiple bare '~' before a command
        while chunk.startswith(b'~'):
            frames.append(ClientFrame(b'~'))
            chunk = chunk[1:]
        if chunk:
            frames.append(ClientFrame(chunk))
    return frames
