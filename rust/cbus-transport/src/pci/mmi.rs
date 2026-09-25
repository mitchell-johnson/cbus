//! Complete, coverage-checked installation MMI over the shared PCI.

use super::*;
use std::io::{Error, ErrorKind, Result};
use std::sync::atomic::Ordering;

const MMI_TIMEOUT: Duration = Duration::from_secs(10);

fn append_block(states: &mut Vec<u8>, block_start: u8, block: Vec<u8>) -> Result<bool> {
    if block.is_empty() {
        return Err(Error::new(
            ErrorKind::InvalidData,
            "MMI block carries no coverage",
        ));
    }
    if usize::from(block_start) != states.len() {
        return Err(Error::new(
            ErrorKind::InvalidData,
            "MMI block is repeated, overlapping, or noncontiguous",
        ));
    }
    if states.len() + block.len() > 256 {
        return Err(Error::new(
            ErrorKind::InvalidData,
            "MMI coverage extends beyond address 255",
        ));
    }
    states.extend(block);
    Ok(states.len() == 256)
}

struct MmiTransaction<'a> {
    client: &'a PciClient,
    complete: bool,
}

impl Drop for MmiTransaction<'_> {
    fn drop(&mut self) {
        self.client.mmi_collecting.store(false, Ordering::Release);
        if !self.complete {
            self.client.mmi_fault.store(true, Ordering::Release);
        }
    }
}

impl PciClient {
    /// Request the complete 256-address installation MMI.
    ///
    /// Blocks must cover addresses contiguously from zero and finish at 256.
    /// Some CNIs forward the first blocks before reporting the request's
    /// delivery confirmation, so those blocks are buffered but never accepted
    /// as a complete observation without a positive confirmation. After any
    /// partial or failed observation, reconnect before another MMI so late
    /// untagged blocks cannot be attributed to a later request.
    pub async fn install_mmi(&self) -> Result<Vec<u8>> {
        let _lane = self.mmi_lane.lock().await;
        self.install_mmi_inner().await
    }

    // Caller holds mmi_lane, either for this request or a whole observation.
    pub(super) async fn install_mmi_inner(&self) -> Result<Vec<u8>> {
        if self.mmi_fault.load(Ordering::Acquire) {
            return Err(Error::other(
                "MMI stream needs reconnect after an incomplete observation",
            ));
        }
        let mut replies = self.packets.subscribe();
        if !self.is_connected() {
            return Err(Error::new(ErrorKind::BrokenPipe, "PCI disconnected"));
        }
        self.mmi_collecting.store(true, Ordering::Release);
        let mut transaction = MmiTransaction {
            client: self,
            complete: false,
        };
        let packet = Packet::PointToMultipoint {
            // cmqttd enables SRCHK during PCI initialization, so this shared
            // session must include the command checksum. Native C-Gate's
            // checksumless capture comes from a session where SRCHK is off.
            meta: Meta::new(true, 0),
            application: 0xff,
            sals: vec![Sal::InstallMmiRequest],
        };
        let confirmation = self.send_guarded(&packet).await?;
        let code = confirmation.code;
        let result = tokio::time::timeout(MMI_TIMEOUT, async {
            let mut confirmed = false;
            let mut states = Vec::with_capacity(256);
            loop {
                match replies.recv().await {
                    Ok(Some(Packet::Confirmation { code: got, success })) if got == code => {
                        if !success {
                            return Err(Error::other("PCI rejected installation MMI"));
                        }
                        confirmed = true;
                        if states.len() == 256 {
                            return Ok(states);
                        }
                    }
                    Ok(Some(Packet::StandardStatus {
                        application: 0xff,
                        block_start,
                        states: block,
                    })) => {
                        if append_block(&mut states, block_start, block)? && confirmed {
                            return Ok(states);
                        }
                    }
                    Ok(Some(Packet::PointToPoint { cals, .. })) => {
                        for cal in cals {
                            let Cal::ExtendedStatus {
                                child_application: 0xff,
                                block_start,
                                report: StatusReport::Binary(block),
                                ..
                            } = cal
                            else {
                                continue;
                            };
                            if append_block(&mut states, block_start, block)? && confirmed {
                                return Ok(states);
                            }
                        }
                    }
                    Ok(Some(_)) => {}
                    Ok(None) | Err(_) => {
                        return Err(Error::new(
                            ErrorKind::BrokenPipe,
                            "PCI response stream lost during MMI",
                        ))
                    }
                }
            }
        })
        .await
        .unwrap_or_else(|_| {
            Err(Error::new(
                ErrorKind::TimedOut,
                "installation MMI coverage timed out",
            ))
        });
        if result.is_ok() {
            transaction.complete = true;
        }
        result
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};

    async fn setup() -> (Arc<PciClient>, BufReader<tokio::io::DuplexStream>) {
        let (client, remote) = tokio::io::duplex(8192);
        let (rd, wr) = tokio::io::split(client);
        let (tx, _) = mpsc::unbounded_channel();
        let pci = PciClient::new(Box::new(rd), Box::new(wr), tx);
        pci.pci_reset().await.unwrap();
        let mut remote = BufReader::new(remote);
        for _ in 0..8 {
            let mut frame = Vec::new();
            remote.read_until(b'\r', &mut frame).await.unwrap();
        }
        (pci, remote)
    }

    fn block(start: u8, count: usize, present: &[usize]) -> Vec<u8> {
        let mut states = vec![0; count];
        for address in present {
            states[*address - usize::from(start)] = 1;
        }
        let wire = Packet::StandardStatus {
            application: 0xff,
            block_start: start,
            states,
        }
        .encode_packet()
        .unwrap();
        let mut line = wire;
        line.extend_from_slice(b"\r\n");
        line
    }

    fn addressed_block(start: u8, count: usize, present: &[usize]) -> Vec<u8> {
        let mut states = vec![0; count];
        for address in present {
            states[*address - usize::from(start)] = 1;
        }
        let wire = Packet::PointToPoint {
            meta: Meta {
                checksum: true,
                priority_class: 2,
                source_address: Some(16),
                confirmation: None,
            },
            unit_address: 16,
            bridged: false,
            hops: vec![],
            cals: vec![Cal::ExtendedStatus {
                externally_initiated: false,
                child_application: 0xff,
                block_start: start,
                report: StatusReport::Binary(states),
            }],
        }
        .encode_packet()
        .unwrap();
        let mut line = wire;
        line.extend_from_slice(b"\r\n");
        line
    }

    #[tokio::test]
    async fn complete_contiguous_mmi_returns_all_states() {
        let (pci, mut remote) = setup().await;
        let running = tokio::spawn({
            let pci = pci.clone();
            async move { pci.install_mmi().await }
        });
        let mut request = Vec::new();
        remote.read_until(b'\r', &mut request).await.unwrap();
        assert!(request.starts_with(b"\\05FF00FAFF0003"));
        let code = request[request.len() - 2];
        remote.write_all(&[code, b'.']).await.unwrap();
        remote
            .write_all(&addressed_block(0, 88, &[16]))
            .await
            .unwrap();
        remote
            .write_all(&addressed_block(88, 88, &[]))
            .await
            .unwrap();
        remote
            .write_all(&addressed_block(176, 80, &[255]))
            .await
            .unwrap();
        let states = running.await.unwrap().unwrap();
        assert_eq!(states.len(), 256);
        assert_eq!(states[16], 1);
        assert_eq!(states[255], 1);
        assert_eq!(states.iter().filter(|state| **state != 0).count(), 2);
    }

    #[tokio::test]
    async fn buffers_blocks_that_precede_positive_confirmation() {
        let (pci, mut remote) = setup().await;
        let running = tokio::spawn({
            let pci = pci.clone();
            async move { pci.install_mmi().await }
        });
        let mut request = Vec::new();
        remote.read_until(b'\r', &mut request).await.unwrap();
        let code = request[request.len() - 2];
        remote
            .write_all(&addressed_block(0, 88, &[16]))
            .await
            .unwrap();
        remote
            .write_all(&addressed_block(88, 88, &[]))
            .await
            .unwrap();
        remote
            .write_all(&addressed_block(176, 80, &[255]))
            .await
            .unwrap();
        assert!(!running.is_finished());
        remote.write_all(&[code, b'.']).await.unwrap();
        let states = running.await.unwrap().unwrap();
        assert_eq!(states.len(), 256);
        assert_eq!(states[16], 1);
        assert_eq!(states[255], 1);
    }

    #[tokio::test]
    async fn coverage_gap_faults_future_mmi_until_reconnect() {
        let (pci, mut remote) = setup().await;
        let running = tokio::spawn({
            let pci = pci.clone();
            async move { pci.install_mmi().await }
        });
        let mut request = Vec::new();
        remote.read_until(b'\r', &mut request).await.unwrap();
        let code = request[request.len() - 2];
        remote.write_all(&[code, b'.']).await.unwrap();
        remote.write_all(&block(88, 88, &[])).await.unwrap();
        assert!(running
            .await
            .unwrap()
            .unwrap_err()
            .to_string()
            .contains("noncontiguous"));
        assert!(pci
            .install_mmi()
            .await
            .unwrap_err()
            .to_string()
            .contains("needs reconnect"));
    }

    /// Issue #10 Phase 3: a negative delivery confirmation rejects the
    /// observation and faults the lane until reconnect, exactly like a gap.
    #[tokio::test]
    async fn negative_confirmation_rejects_and_faults_lane() {
        let (pci, mut remote) = setup().await;
        let running = tokio::spawn({
            let pci = pci.clone();
            async move { pci.install_mmi().await }
        });
        let mut request = Vec::new();
        remote.read_until(b'\r', &mut request).await.unwrap();
        let code = request[request.len() - 2];
        remote.write_all(&[code, b'#']).await.unwrap();
        assert!(running
            .await
            .unwrap()
            .unwrap_err()
            .to_string()
            .contains("rejected"));
        assert!(pci
            .install_mmi()
            .await
            .unwrap_err()
            .to_string()
            .contains("needs reconnect"));
    }

    /// Issue #10 Phase 3: broadcast multipoint blocks correlate with routed
    /// addressed blocks into one contiguous 0..255 observation.
    #[tokio::test]
    async fn broadcast_and_addressed_blocks_correlate_into_full_coverage() {
        let (pci, mut remote) = setup().await;
        let running = tokio::spawn({
            let pci = pci.clone();
            async move { pci.install_mmi().await }
        });
        let mut request = Vec::new();
        remote.read_until(b'\r', &mut request).await.unwrap();
        let code = request[request.len() - 2];
        remote.write_all(&[code, b'.']).await.unwrap();
        // Broadcast multipoint and routed addressed blocks share the
        // canonical 88/88/80 boundaries and correlate into one observation.
        remote.write_all(&block(0, 88, &[16])).await.unwrap();
        remote
            .write_all(&addressed_block(88, 88, &[100]))
            .await
            .unwrap();
        remote.write_all(&block(176, 80, &[255])).await.unwrap();
        let states = running.await.unwrap().unwrap();
        assert_eq!(states.len(), 256);
        assert_eq!(states[16], 1);
        assert_eq!(states[100], 1);
        assert_eq!(states[255], 1);
        assert_eq!(states.iter().filter(|state| **state != 0).count(), 3);
    }

    /// Issue #10 Phase 3: bridged routed replies carry the same 0xff status
    /// blocks and correlate like local ones. The encoder never emits
    /// bridged PTP, so the frame is re-addressed on the decoded wire with a
    /// fresh checksum instead.
    #[tokio::test]
    async fn bridged_addressed_blocks_accepted() {
        use cbus_protocol::common::add_cbus_checksum;

        let (pci, mut remote) = setup().await;
        let running = tokio::spawn({
            let pci = pci.clone();
            async move { pci.install_mmi().await }
        });
        let mut request = Vec::new();
        remote.read_until(b'\r', &mut request).await.unwrap();
        let code = request[request.len() - 2];
        remote.write_all(&[code, b'.']).await.unwrap();
        // Wire form is uppercase hex ASCII: [flags, source, unit, 0x00,
        // CAL..., checksum]. Route the unit block through bridge 0x20 with
        // a zero-hop length code and recompute the checksum.
        let plain = addressed_block(0, 88, &[16]);
        let binary = hex::decode(&plain[..plain.len() - 2]).unwrap();
        assert_eq!(binary[1], 0x10, "source address");
        assert_eq!(binary[2], 0x10, "unit address");
        assert_eq!(binary[3], 0x00, "local route marker");
        let mut routed = Vec::with_capacity(binary.len() + 1);
        routed.extend_from_slice(&binary[..2]);
        routed.extend_from_slice(&[0x20, 0x09, 0x10]);
        routed.extend_from_slice(&binary[4..binary.len() - 1]);
        let mut line = hex::encode_upper(add_cbus_checksum(&routed)).into_bytes();
        line.extend_from_slice(b"\r\n");
        remote.write_all(&line).await.unwrap();
        remote
            .write_all(&addressed_block(88, 88, &[]))
            .await
            .unwrap();
        remote
            .write_all(&addressed_block(176, 80, &[255]))
            .await
            .unwrap();
        let states = running.await.unwrap().unwrap();
        assert_eq!(states.len(), 256);
        assert_eq!(states[16], 1);
        assert_eq!(states[255], 1);
    }

    /// Issue #10 Phase 3: block assembly accepts only contiguous coverage
    /// from zero that ends exactly at 256.
    #[test]
    fn append_block_pins_contiguity_and_bounds() {
        let mut states = Vec::new();
        assert!(!append_block(&mut states, 0, vec![0; 128]).unwrap());
        assert!(append_block(&mut states, 128, vec![0; 128]).unwrap());
        // Repeated start.
        let mut repeated = vec![0; 4];
        assert!(append_block(&mut repeated, 0, vec![0; 4]).is_err());
        // Overlapping start.
        let mut overlapping = vec![0; 8];
        assert!(append_block(&mut overlapping, 4, vec![0; 4]).is_err());
        // Gap.
        let mut gapped = vec![0; 8];
        assert!(append_block(&mut gapped, 16, vec![0; 8]).is_err());
        // Coverage past address 255.
        let mut full = vec![0; 255];
        assert!(append_block(&mut full, 255, vec![0; 2]).is_err());
        // Empty blocks carry no coverage and fast-fault instead of stalling.
        let mut empty = Vec::new();
        assert!(append_block(&mut empty, 0, Vec::new()).is_err());
        // Exactly-256 completion.
        let mut exact = vec![0; 255];
        assert!(append_block(&mut exact, 255, vec![0; 1]).unwrap());
    }

    /// Reverse cross-family order: addressed blocks before broadcast ones
    /// correlate the same way.
    #[tokio::test]
    async fn addressed_before_broadcast_correlates() {
        let (pci, mut remote) = setup().await;
        let running = tokio::spawn({
            let pci = pci.clone();
            async move { pci.install_mmi().await }
        });
        let mut request = Vec::new();
        remote.read_until(b'\r', &mut request).await.unwrap();
        let code = request[request.len() - 2];
        remote.write_all(&[code, b'.']).await.unwrap();
        remote
            .write_all(&addressed_block(0, 88, &[16]))
            .await
            .unwrap();
        remote.write_all(&block(88, 88, &[100])).await.unwrap();
        remote
            .write_all(&addressed_block(176, 80, &[255]))
            .await
            .unwrap();
        let states = running.await.unwrap().unwrap();
        assert_eq!(states.len(), 256);
        assert_eq!(states[16], 1);
        assert_eq!(states[100], 1);
        assert_eq!(states[255], 1);
    }

    /// Non-canonical wire fragmentation within the encoder limits
    /// (multiples of 4, at most 116 states) assembles all the same.
    #[tokio::test]
    async fn non_canonical_broadcast_sizes_assemble() {
        let (pci, mut remote) = setup().await;
        let running = tokio::spawn({
            let pci = pci.clone();
            async move { pci.install_mmi().await }
        });
        let mut request = Vec::new();
        remote.read_until(b'\r', &mut request).await.unwrap();
        let code = request[request.len() - 2];
        remote.write_all(&[code, b'.']).await.unwrap();
        remote.write_all(&block(0, 116, &[16])).await.unwrap();
        remote.write_all(&block(116, 116, &[])).await.unwrap();
        remote.write_all(&block(232, 24, &[255])).await.unwrap();
        let states = running.await.unwrap().unwrap();
        assert_eq!(states.len(), 256);
        assert_eq!(states[16], 1);
        assert_eq!(states[255], 1);
        assert_eq!(states.iter().filter(|state| **state != 0).count(), 2);
    }

    /// Single-hop bridged replies route through the hop byte to the unit.
    #[tokio::test]
    async fn single_hop_bridged_block_accepted() {
        use cbus_protocol::common::add_cbus_checksum;

        let (pci, mut remote) = setup().await;
        let running = tokio::spawn({
            let pci = pci.clone();
            async move { pci.install_mmi().await }
        });
        let mut request = Vec::new();
        remote.read_until(b'\r', &mut request).await.unwrap();
        let code = request[request.len() - 2];
        remote.write_all(&[code, b'.']).await.unwrap();
        let plain = addressed_block(0, 88, &[16]);
        let binary = hex::decode(&plain[..plain.len() - 2]).unwrap();
        assert_eq!(binary[1], 0x10, "source address");
        assert_eq!(binary[2], 0x10, "unit address");
        assert_eq!(binary[3], 0x00, "local route marker");
        let mut routed = Vec::with_capacity(binary.len() + 2);
        routed.extend_from_slice(&binary[..2]);
        routed.extend_from_slice(&[0x20, 0x12, 0x05, 0x10]);
        routed.extend_from_slice(&binary[4..binary.len() - 1]);
        let mut line = hex::encode_upper(add_cbus_checksum(&routed)).into_bytes();
        line.extend_from_slice(b"\r\n");
        remote.write_all(&line).await.unwrap();
        remote
            .write_all(&addressed_block(88, 88, &[]))
            .await
            .unwrap();
        remote
            .write_all(&addressed_block(176, 80, &[255]))
            .await
            .unwrap();
        let states = running.await.unwrap().unwrap();
        assert_eq!(states.len(), 256);
        assert_eq!(states[16], 1);
        assert_eq!(states[255], 1);
    }
}
