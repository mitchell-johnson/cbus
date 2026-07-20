//! Buffered decode loop. Port of `buffered_protocol.py` (256-byte cap,
//! overflow clears the buffer) + `cbus_protocol.py` (decode loop).

use cbus_protocol::common::MAX_BUFFER_SIZE;
use cbus_protocol::decode::decode_packet;
use cbus_protocol::packet::Packet;

/// One decoded frame; `raw` holds the consumed wire bytes (used for the
/// server-mode local echo).
#[derive(Debug)]
pub struct FrameEvent {
    pub packet: Option<Packet>,
    pub raw: Vec<u8>,
}

pub struct FrameBuffer {
    buf: Vec<u8>,
    from_pci: bool,
    checksum: bool,
}

impl FrameBuffer {
    /// Client side: parse PCI->client traffic, checksums required.
    pub fn new_client() -> Self {
        FrameBuffer {
            buf: Vec::new(),
            from_pci: true,
            checksum: true,
        }
    }

    /// Server (PCI emulation) side: parse client->PCI traffic, no checksums
    /// until SRCHK is enabled.
    pub fn new_server() -> Self {
        FrameBuffer {
            buf: Vec::new(),
            from_pci: false,
            checksum: false,
        }
    }

    pub fn set_checksum(&mut self, on: bool) {
        self.checksum = on;
    }

    pub fn clear(&mut self) {
        self.buf.clear();
    }

    /// Feed rx bytes; return every decoded frame. Overflow (>256 bytes)
    /// drops the whole buffer (log, don't crash) like
    /// `buffered_protocol.py:80-93`.
    pub fn feed(&mut self, data: &[u8]) -> Vec<FrameEvent> {
        let mut out = Vec::new();
        if data.len() > MAX_BUFFER_SIZE || self.buf.len() + data.len() > MAX_BUFFER_SIZE {
            tracing::error!(
                "receive buffer would exceed {} bytes; dropping buffer",
                MAX_BUFFER_SIZE
            );
            self.buf.clear();
            return out;
        }
        self.buf.extend_from_slice(data);
        loop {
            if self.buf.is_empty() {
                break;
            }
            let (packet, consumed) = decode_packet(&self.buf, self.checksum, true, self.from_pci);
            if consumed > 0 {
                let raw = self.buf[..consumed.min(self.buf.len())].to_vec();
                self.buf.drain(..consumed.min(self.buf.len()));
                out.push(FrameEvent { packet, raw });
            } else {
                // consumed == 0: wait for more data
                break;
            }
        }
        out
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn split_confirmation_across_feeds() {
        let mut fb = FrameBuffer::new_client();
        assert!(fb.feed(b"h").is_empty());
        let evs = fb.feed(b".");
        assert_eq!(evs.len(), 1);
        assert_eq!(
            evs[0].packet,
            Some(Packet::Confirmation {
                code: b'h',
                success: true
            })
        );
    }

    #[test]
    fn multiple_frames_one_feed() {
        let mut fb = FrameBuffer::new_client();
        let evs = fb.feed(b"+h.i#");
        assert_eq!(evs.len(), 3);
    }

    #[test]
    fn overflow_clears() {
        let mut fb = FrameBuffer::new_client();
        fb.feed(&[b'0'; 200]);
        // this would exceed 256: whole buffer dropped
        assert!(fb.feed(&[b'0'; 100]).is_empty());
        // buffer is now empty again
        let evs = fb.feed(b"h.");
        assert_eq!(evs.len(), 1);
    }
}
