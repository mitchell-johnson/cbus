//! Buffered decode loop with a 256-byte cap and overflow recovery.

use cbus_protocol::common::MAX_BUFFER_SIZE;
use cbus_protocol::decode::{decode_packet, decode_packet_install_mmi};
use cbus_protocol::packet::Packet;

/// One decoded frame; `raw` holds the consumed wire bytes (used for the
/// server-mode local echo).
#[derive(Debug)]
pub struct FrameEvent {
    /// The decoded packet; `None` for consume-and-ignore frames.
    pub packet: Option<Packet>,
    /// The raw wire bytes this frame consumed.
    pub raw: Vec<u8>,
}

/// Reassembles a byte stream into C-Bus frames.
/// buffered protocol behavior.
pub struct FrameBuffer {
    buf: Vec<u8>,
    from_pci: bool,
    checksum: bool,
    install_mmi: bool,
    discarded_input: bool,
}

impl FrameBuffer {
    /// Client side: parse PCI->client traffic, checksums required.
    pub fn new_client() -> Self {
        FrameBuffer {
            buf: Vec::new(),
            from_pci: true,
            checksum: true,
            install_mmi: false,
            discarded_input: false,
        }
    }

    /// Server (PCI emulation) side: parse client->PCI traffic, no checksums
    /// until SRCHK is enabled.
    pub fn new_server() -> Self {
        FrameBuffer {
            buf: Vec::new(),
            from_pci: false,
            checksum: false,
            install_mmi: false,
            discarded_input: false,
        }
    }

    /// Toggle checksum verification (the simulator flips this when the
    /// client sets/clears SRCHK).
    pub fn set_checksum(&mut self, on: bool) {
        self.checksum = on;
    }

    /// Select the context-sensitive installation MMI decoder.
    pub fn set_install_mmi(&mut self, on: bool) {
        self.install_mmi = on;
    }

    /// Drop any buffered partial frame.
    pub fn clear(&mut self) {
        self.buf.clear();
    }

    pub(crate) fn selected_serial_complete(&self) -> bool {
        self.buf.is_empty() && !self.discarded_input
    }

    /// Feed rx bytes; return every decoded frame. The 256-byte bound applies
    /// to an incomplete frame, not to a read containing many complete frames.
    /// An overflowing incomplete frame drops the buffer and the rest of this
    /// read, preserving the existing overflow recovery boundary.
    pub fn feed(&mut self, mut data: &[u8]) -> Vec<FrameEvent> {
        let mut out = Vec::new();
        loop {
            if !data.is_empty() {
                let available = MAX_BUFFER_SIZE - self.buf.len();
                if available == 0 {
                    self.discarded_input = true;
                    tracing::error!(
                        "receive buffer would exceed {} bytes; dropping buffer",
                        MAX_BUFFER_SIZE
                    );
                    self.buf.clear();
                    break;
                }
                let take = available.min(data.len());
                self.buf.extend_from_slice(&data[..take]);
                data = &data[take..];
            }
            if self.buf.is_empty() {
                break;
            }
            let decode = if self.install_mmi {
                decode_packet_install_mmi
            } else {
                decode_packet
            };
            let (mut packet, mut consumed) = decode(&self.buf, self.checksum, true, self.from_pci);
            // Units emit checksummed replies even into a checksum-off
            // session. When a bare from-PCI decode fails, retry once as
            // checksummed and keep it only if it parses; a frame invalid in
            // both modes stays Invalid. Checksummed sessions (cmqttd) stay
            // strict: a frame failing its checksum is never reinterpreted
            // as bare. Server-side parsing stays strict as well.
            if self.from_pci
                && !self.checksum
                && matches!(packet, Some(Packet::Invalid))
                && consumed > 0
            {
                let (fallback_packet, fallback_consumed) =
                    decode(&self.buf, true, true, self.from_pci);
                if !matches!(fallback_packet, Some(Packet::Invalid)) && fallback_consumed > 0 {
                    packet = fallback_packet;
                    consumed = fallback_consumed;
                }
            }
            if consumed > 0 {
                // The public decoder retains legacy bare-CAL accounting that
                // adds the CAL length to the already consumed line. Never let
                // that compatibility quirk eat bytes from the next frame.
                if !self.from_pci && matches!(packet, Some(Packet::BareCal(_))) {
                    if let Some(end) = self.buf.iter().position(|&byte| byte == b'\r') {
                        consumed = consumed.min(end + 1);
                    }
                }
                let raw = self.buf[..consumed.min(self.buf.len())].to_vec();
                self.buf.drain(..consumed.min(self.buf.len()));
                out.push(FrameEvent { packet, raw });
            } else if data.is_empty() {
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
    fn basic_mode_echo_does_not_hold_later_confirmations() {
        // The init sequence echoed CR-only by a basic-mode PCI, then the
        // confirmation of the first confirmed command.
        let mut fb = FrameBuffer::new_client();
        let evs = fb.feed(b"~\r~\r~\r|\r");
        // The last CR waits for the next byte in case it starts a CRLF.
        assert_eq!(evs.len(), 3);
        assert!(evs
            .iter()
            .all(|ev| ev.packet == Some(Packet::Invalid) && ev.raw.len() == 2));
        let evs = fb.feed(b"h.");
        assert_eq!(evs.len(), 2);
        assert_eq!(evs[0].raw, b"|\r");
        assert_eq!(
            evs[1].packet,
            Some(Packet::Confirmation {
                code: b'h',
                success: true
            })
        );
    }

    #[test]
    fn crlf_split_between_reads_is_one_terminator() {
        let mut fb = FrameBuffer::new_client();
        assert!(fb.feed(b"05013000790051\r").is_empty());
        let evs = fb.feed(b"\nh.");
        assert_eq!(evs.len(), 2);
        assert_eq!(evs[0].raw, b"05013000790051\r\n");
        assert!(matches!(
            evs[0].packet,
            Some(Packet::PointToMultipoint { .. })
        ));
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
