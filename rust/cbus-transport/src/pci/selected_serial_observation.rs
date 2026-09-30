//! Strict Reply Network observations for selected-serial commissioning.
//!
//! The general packet projection omits the attached PCI destination in a
//! routed reply. Keep the reader's original frame alongside that projection
//! and reuse the protocol capture parsers to check the complete envelope.
//! Completion also requires an intact, empty shared framing buffer. This is
//! still frame-level correlation, not a complete raw transport receipt.

use super::*;
use cbus_protocol::common::cbus_checksum;
use cbus_protocol::pci_observation::{
    parse_routed_capture, parse_routed_mmi_capture, MmiEvent, PciEvent,
};
use std::io::{Error, ErrorKind, Result};
use std::sync::atomic::Ordering;

const OBSERVATION_TIMEOUT: Duration = Duration::from_secs(10);
const IDENTIFY_QUIET: Duration = Duration::from_secs(2);
const IDENTIFY_MAX_REPLIES: usize = 7;

// Both commissioning lanes are held by CommissioningObservation. Any failed
// read makes untagged later replies unsafe for either kind of observation.
struct ObservationTransaction<'a> {
    client: &'a PciClient,
    mmi: bool,
    complete: bool,
}

impl Drop for ObservationTransaction<'_> {
    fn drop(&mut self) {
        if self.mmi {
            self.client.mmi_collecting.store(false, Ordering::Release);
        }
        if !self.complete {
            self.client.mmi_fault.store(true, Ordering::Release);
            self.client.programming_fault.store(true, Ordering::Release);
            self.client.request_shutdown();
        }
    }
}

fn invalid(message: impl Into<String>) -> Error {
    Error::new(ErrorKind::InvalidData, message.into())
}

// Ordinary SAL traffic remains outside the commissioning lanes. Its replies
// cannot contribute evidence, but interleaving it must not break a read.
fn application_traffic(packet: &Packet) -> bool {
    matches!(
        packet,
        Packet::PointToMultipoint { application, .. }
            | Packet::PointToPointToMultipoint { application, .. }
            | Packet::StandardStatus { application, .. }
            if *application != 0xff
    )
}

// Capture parsers require checksums. In an SRCHK-off session FrameBuffer has
// already validated a bare frame, or accepted a checksummed fallback and set
// meta.checksum accordingly. Add a checksum only to that validated bare copy;
// never re-encode the Packet because that would lose the local destination.
pub(super) fn parser_capture(packet: &Packet, raw: &[u8]) -> Result<Vec<u8>> {
    match packet {
        Packet::Confirmation { .. } => Ok(raw.to_vec()),
        Packet::PointToPoint { meta, cals, .. } => {
            let end = raw
                .iter()
                .position(|byte| matches!(byte, b'\r' | b'\n'))
                .ok_or_else(|| invalid("routed observation frame has no terminator"))?;
            if raw[end..].iter().any(|byte| !matches!(byte, b'\r' | b'\n')) {
                return Err(invalid("routed observation frame has trailing input"));
            }
            let mut line = raw[..end].to_vec();
            if !meta.checksum {
                let payload = hex::decode(&line)
                    .map_err(|_| invalid("routed observation frame is not hexadecimal"))?;
                // The legacy bare-IDENTIFY4 decoder strips a valid checksum
                // itself in checksum-off mode, leaving meta.checksum false.
                let bare: Vec<u8> = cals.iter().flat_map(Cal::encode).collect();
                let bare_checksum = meta.source_address.is_none()
                    && payload.len() == bare.len() + 1
                    && payload[..bare.len()] == bare
                    && payload[bare.len()] == cbus_checksum(&bare);
                if !bare_checksum {
                    line.extend_from_slice(hex::encode_upper([cbus_checksum(&payload)]).as_bytes());
                }
            }
            line.extend_from_slice(b"\r\n");
            Ok(line)
        }
        _ => Err(invalid("unexpected traffic during routed observation")),
    }
}

pub(super) struct FrameCapture {
    value: serde_json::Value,
}

impl FrameCapture {
    pub(super) fn new(request: &[u8], confirmation: u8) -> Result<Self> {
        if request.len() > 4096 {
            return Err(invalid("selected-serial request exceeds capture limit"));
        }
        Ok(Self {
            value: serde_json::json!({
                "format": "cbus-selected-serial-frame-capture-v1",
                "source": "cbus-transport-strict-selected-serial",
                "request_hex": hex::encode(request),
                "confirmation": char::from(confirmation).to_string(),
                "raw_frames_hex": [], "parser_frames_hex": [], "ignored_frames_hex": [],
                "complete": false, "stream_complete": false, "termination": "response_window_elapsed"
            }),
        })
    }

    pub(super) fn record(&mut self, packet: &Packet, raw: &[u8], ignored: bool) -> Result<()> {
        // Unsupported packet projections remain original bytes. A consumer
        // must reject any frame its strict parser cannot independently admit.
        let parser = parser_capture(packet, raw).unwrap_or_else(|_| raw.to_vec());
        self.value["raw_frames_hex"]
            .as_array_mut()
            .unwrap()
            .push(hex::encode(raw).into());
        self.value["parser_frames_hex"]
            .as_array_mut()
            .unwrap()
            .push(hex::encode(parser).into());
        if ignored {
            self.value["ignored_frames_hex"]
                .as_array_mut()
                .unwrap()
                .push(hex::encode(raw).into());
        }
        if serde_json::to_vec(&self.value)
            .map_err(|error| invalid(error.to_string()))?
            .len()
            > 65536
        {
            return Err(invalid("selected-serial frame capture exceeds 64 KiB"));
        }
        Ok(())
    }

    pub(super) fn finish(mut self, termination: &str) -> serde_json::Value {
        self.value["complete"] = true.into();
        self.value["stream_complete"] = true.into();
        self.value["termination"] = termination.into();
        self.value
    }
}

impl PciClient {
    fn selected_serial_observation_ready(&self, bridges: &[u8], direct: bool) -> Result<()> {
        if !((1..=6).contains(&bridges.len()) || direct && bridges.is_empty()) {
            return Err(Error::new(
                ErrorKind::InvalidInput,
                "routed observation requires one to six bridges",
            ));
        }
        if self.mmi_fault.load(Ordering::Acquire) || self.programming_fault.load(Ordering::Acquire)
        {
            return Err(Error::other("commissioning stream needs reconnect"));
        }
        if !self.is_connected() {
            return Err(Error::new(ErrorKind::BrokenPipe, "PCI disconnected"));
        }
        Ok(())
    }

    // Caller holds both commissioning lanes for all inventory bookends.
    pub(super) async fn selected_serial_mmi_routed(
        &self,
        bridges: &[u8],
        local: u8,
    ) -> Result<Vec<u8>> {
        self.selected_serial_mmi_routed_captured(bridges, local)
            .await
            .map(|(value, _)| value)
    }

    pub(super) async fn selected_serial_mmi_routed_captured(
        &self,
        bridges: &[u8],
        local: u8,
    ) -> Result<(Vec<u8>, serde_json::Value)> {
        self.selected_serial_observation_ready(bridges, false)?;
        let mut replies = self.programming_frames.subscribe();
        self.mmi_collecting.store(true, Ordering::Release);
        let mut transaction = ObservationTransaction {
            client: self,
            mmi: true,
            complete: false,
        };
        let packet = Packet::PointToPointToMultipoint {
            meta: Meta::new(self.command_checksum(), 0),
            bridges: bridges.to_vec(),
            application: 0xff,
            sals: vec![Sal::InstallMmiRequest],
        };
        let result = tokio::time::timeout(OBSERVATION_TIMEOUT, async {
            // Routed native NET PINGU is exact-once: a missing confirmation
            // cannot justify replaying an untagged stream of MMI blocks.
            let (confirmation, request) = self.send_guarded_once_captured(&packet).await?;
            let mut evidence = FrameCapture::new(&request, confirmation.code)?;
            let mut confirmed = false;
            let mut states = Vec::with_capacity(256);
            loop {
                let next = if states.len() == 256 {
                    // Consume anything already emitted in the same read before
                    // accepting coverage, including a repeated final block.
                    match replies.try_recv() {
                        Ok(next) => next,
                        Err(broadcast::error::TryRecvError::Empty) => {
                            if !self.selected_serial_framing_complete() {
                                return Err(invalid("routed MMI ended with incomplete or lost framing"));
                            }
                            // The framing check waits for an in-flight reader
                            // batch; drain frames it published after our first
                            // empty check before accepting complete coverage.
                            match replies.try_recv() {
                                Ok(next) => next,
                                Err(broadcast::error::TryRecvError::Empty) => return Ok((states, evidence.finish("coverage_complete"))),
                                Err(_) => {
                                    return Err(Error::new(
                                        ErrorKind::BrokenPipe,
                                        "PCI response stream lost during routed MMI",
                                    ))
                                }
                            }
                        }
                        Err(_) => {
                            return Err(Error::new(
                                ErrorKind::BrokenPipe,
                                "PCI response stream lost during routed MMI",
                            ))
                        }
                    }
                } else {
                    replies.recv().await.map_err(|_| {
                        Error::new(ErrorKind::BrokenPipe, "PCI response stream lost during routed MMI")
                    })?
                };
                let (packet, raw) = next.ok_or_else(|| {
                    Error::new(ErrorKind::BrokenPipe, "PCI disconnected during routed MMI")
                })?;
                let ignored = application_traffic(&packet)
                    || matches!(&packet, Packet::Confirmation { code, .. } if *code != confirmation.code);
                evidence.record(&packet, &raw, ignored)?;
                if ignored {
                    continue;
                }
                let capture = parser_capture(&packet, &raw)?;
                let (events, pending) = parse_routed_mmi_capture(&capture, bridges, local)
                    .map_err(invalid)?;
                if !pending.is_empty() || events.len() != 1 {
                    return Err(invalid("routed MMI framing is incomplete or ambiguous"));
                }
                match events.into_iter().next().unwrap() {
                    MmiEvent::Confirmation(code, '.') if code == confirmation.code && !confirmed => {
                        confirmed = true;
                    }
                    MmiEvent::Confirmation(..) => {
                        return Err(invalid("routed MMI confirmation was rejected or repeated"));
                    }
                    MmiEvent::Block(block) => {
                        if !confirmed {
                            return Err(invalid("routed MMI block arrived before confirmation"));
                        }
                        if block.states.is_empty()
                            || usize::from(block.start) != states.len()
                            || states.len() + block.states.len() > 256
                        {
                            return Err(invalid(
                                "routed MMI block is empty, repeated, overlapping, or noncontiguous",
                            ));
                        }
                        states.extend(block.states);
                    }
                    _ => return Err(invalid("routed MMI source/destination/route mismatch")),
                }
            }
        })
        .await
        .unwrap_or_else(|_| Err(Error::new(ErrorKind::TimedOut, "routed MMI observation timed out")));
        transaction.complete = result.is_ok();
        result
    }

    // IDENTIFY4 deliberately preserves duplicate replies.
    pub(super) async fn selected_serial_identify_routed(
        &self,
        bridges: &[u8],
        local: u8,
        unit: u8,
    ) -> Result<Vec<Vec<u8>>> {
        self.selected_serial_identify_routed_captured(bridges, local, unit)
            .await
            .map(|(value, _)| value)
    }
    pub(super) async fn selected_serial_identify_routed_captured(
        &self,
        bridges: &[u8],
        local: u8,
        unit: u8,
    ) -> Result<(Vec<Vec<u8>>, serde_json::Value)> {
        self.selected_serial_observation_ready(bridges, false)?;
        self.selected_serial_collect_for_route(
            bridges,
            local,
            unit,
            Cal::Identify { attribute: 4 },
            (4, 12, false),
        )
        .await
    }
    #[cfg(test)]
    pub(super) async fn selected_serial_local_identity(&self, local: u8) -> Result<Vec<Vec<u8>>> {
        self.selected_serial_local_identity_captured(local)
            .await
            .map(|(value, _)| value)
    }
    pub(super) async fn selected_serial_local_identity_captured(
        &self,
        local: u8,
    ) -> Result<(Vec<Vec<u8>>, serde_json::Value)> {
        self.selected_serial_observation_ready(&[], true)?;
        self.selected_serial_collect_for_route(
            &[],
            local,
            local,
            Cal::Identify { attribute: 4 },
            (4, 12, false),
        )
        .await
    }
    #[cfg(test)]
    pub(super) async fn selected_serial_local_options(&self, local: u8) -> Result<Vec<u8>> {
        self.selected_serial_local_options_captured(local)
            .await
            .map(|(value, _)| value)
    }
    pub(super) async fn selected_serial_local_options_captured(
        &self,
        local: u8,
    ) -> Result<(Vec<u8>, serde_json::Value)> {
        self.selected_serial_observation_ready(&[], true)?;
        let (mut replies, capture) = self
            .selected_serial_collect_for_route(
                &[],
                local,
                local,
                Cal::Recall {
                    param: 66,
                    count: 1,
                },
                (66, 1, true),
            )
            .await?;
        Ok((replies.remove(0), capture))
    }

    async fn selected_serial_collect_for_route(
        &self,
        bridges: &[u8],
        local: u8,
        unit: u8,
        request: Cal,
        expected_reply: (u8, usize, bool),
    ) -> Result<(Vec<Vec<u8>>, serde_json::Value)> {
        let (parameter, length, exactly_one) = expected_reply;
        let mut replies = self.programming_frames.subscribe();
        let mut transaction = ObservationTransaction {
            client: self,
            mmi: false,
            complete: false,
        };
        let packet = Packet::PointToPoint {
            meta: Meta::new(self.command_checksum(), 1),
            unit_address: unit,
            bridged: !bridges.is_empty(),
            hops: bridges.to_vec(),
            cals: vec![request],
        };
        let result = tokio::time::timeout(OBSERVATION_TIMEOUT, async {
            let (confirmation, request) = self.send_guarded_once_captured(&packet).await?;
            let mut evidence = FrameCapture::new(&request, confirmation.code)?;
            let mut confirmed = false;
            let mut collected = Vec::new();
            let mut quiet_deadline = None;
            let mut expected_route = vec![bridges.len() as u8];
            if !bridges.is_empty() {
                expected_route.extend_from_slice(&bridges[1..]);
                expected_route.push(unit);
            }
            loop {
                let next = match quiet_deadline {
                    Some(deadline) => match tokio::time::timeout_at(deadline, replies.recv()).await {
                        Ok(next) => next,
                        Err(_) => {
                            if !self.selected_serial_framing_complete() {
                                return Err(invalid("selected-serial read ended with incomplete or lost framing"));
                            }
                            // A dispatch batch can finish while the quiet
                            // deadline fires. Its queued frames still belong
                            // to this observation and must be checked.
                            match replies.try_recv() {
                                Ok(next) => Ok(next),
                                Err(broadcast::error::TryRecvError::Empty) => {
                                    if exactly_one && collected.len() != 1 {
                                        return Err(invalid("local options require exactly one confirmed reply"));
                                    }
                                    return Ok((collected, evidence.finish("quiet_window_elapsed")));
                                }
                                Err(_) => return Err(Error::new(ErrorKind::BrokenPipe, "PCI response stream lost during selected-serial read")),
                            }
                        }
                    },
                    None => replies.recv().await,
                }
                .map_err(|_| Error::new(ErrorKind::BrokenPipe, "PCI response stream lost during selected-serial read"))?
                .ok_or_else(|| Error::new(ErrorKind::BrokenPipe, "PCI disconnected during selected-serial read"))?;
                let (packet, raw) = next;
                let ignored = application_traffic(&packet)
                    || matches!(&packet, Packet::Confirmation { code, .. } if *code != confirmation.code);
                evidence.record(&packet, &raw, ignored)?;
                if ignored {
                    continue;
                }
                let capture = parser_capture(&packet, &raw)?;
                let (events, pending) = parse_routed_capture(&capture).map_err(invalid)?;
                if !pending.is_empty() || events.len() != 1 {
                    return Err(invalid("selected-serial read framing is incomplete or ambiguous"));
                }
                match events.into_iter().next().unwrap() {
                    PciEvent::Confirmation(code, '.') if code == confirmation.code && !confirmed => {
                        confirmed = true;
                        quiet_deadline = Some(Instant::now() + IDENTIFY_QUIET);
                    }
                    PciEvent::Confirmation(..) => {
                        return Err(invalid("selected-serial read confirmation was rejected or repeated"));
                    }
                    PciEvent::Frame(frame) => {
                        if !confirmed {
                            return Err(invalid("selected-serial read reply arrived before confirmation"));
                        }
                        let envelope_matches = if bridges.is_empty() {
                            if frame.bare() {
                                unit == local && self.local_unit.load(Ordering::Acquire) == u16::from(local)
                            } else {
                                frame.source == Some(local)
                                    && frame.destination == Some(local)
                                    && matches!(frame.route.as_slice(), [0] | [1, 0])
                            }
                        } else {
                            frame.source == bridges.first().copied()
                                && frame.destination == Some(local)
                                && frame.route == expected_route
                        };
                        if !envelope_matches {
                            return Err(invalid("selected-serial read source/destination/route mismatch"));
                        }
                        let [Cal::Reply { parameter: got, data }] = frame.cals.as_slice() else {
                            return Err(invalid("selected-serial read reply has an unexpected or ambiguous CAL"));
                        };
                        if *got != parameter || data.len() != length {
                            return Err(invalid(format!("selected-serial parameter {parameter} reply must contain exactly {length} bytes")));
                        }
                        collected.push(data.clone());
                        if exactly_one && collected.len() > 1 {
                            return Err(invalid("local options require exactly one confirmed reply"));
                        }
                        if collected.len() >= IDENTIFY_MAX_REPLIES {
                            return Err(invalid("selected-serial read response count reached the collection limit"));
                        }
                        quiet_deadline = Some(Instant::now() + IDENTIFY_QUIET);
                    }
                    _ => return Err(invalid("unexpected selected-serial read notification")),
                }
            }
        })
        .await
        .unwrap_or_else(|_| Err(Error::new(ErrorKind::TimedOut, "selected-serial read observation timed out")));
        transaction.complete = result.is_ok();
        result
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use cbus_protocol::pci_observation::{
        routed_identify_request, routed_installation_mmi_request,
    };
    use tokio::io::{AsyncBufReadExt, BufReader};

    type Peer = BufReader<tokio::io::DuplexStream>;

    async fn setup() -> (Arc<PciClient>, Peer) {
        let (client, remote) = tokio::io::duplex(8192);
        let (read, write) = tokio::io::split(client);
        let (events, _) = mpsc::unbounded_channel();
        let pci = PciClient::new(Box::new(read), Box::new(write), events);
        pci.pci_reset().await.unwrap();
        let mut remote = BufReader::new(remote);
        for _ in 0..8 {
            request(&mut remote).await;
        }
        (pci, remote)
    }

    async fn request(remote: &mut Peer) -> Vec<u8> {
        let mut bytes = Vec::new();
        remote.read_until(b'\r', &mut bytes).await.unwrap();
        bytes
    }

    fn line(mut bytes: Vec<u8>, checksum: bool) -> Vec<u8> {
        if checksum {
            bytes.push(cbus_checksum(&bytes));
        }
        let mut line = hex::encode_upper(bytes).into_bytes();
        line.extend_from_slice(b"\r\n");
        line
    }

    fn reply(bridges: &[u8], local: u8, unit: u8, cal: Vec<u8>, checksum: bool) -> Vec<u8> {
        let mut bytes = vec![0x86, bridges[0], local, bridges.len() as u8];
        bytes.extend_from_slice(&bridges[1..]);
        bytes.push(unit);
        bytes.extend(cal);
        line(bytes, checksum)
    }

    fn mmi(bridges: &[u8], local: u8, start: u8, count: usize, checksum: bool) -> Vec<u8> {
        let mut cal = vec![0xe0 | (3 + count / 4) as u8, 0x00, 0xff, start];
        cal.resize(4 + count / 4, 0);
        if start == 0 {
            cal[5] = 1 << 4; // Unit 6 is present.
        }
        reply(bridges, local, 1, cal, checksum)
    }

    fn serial() -> Vec<u8> {
        vec![
            0x38, 0xff, 0xff, 0xff, 0xff, 0x18, 0xb1, 0x06, 0x16, 0xa2, 0, 5,
        ]
    }

    fn identify(bridges: &[u8], local: u8, unit: u8, checksum: bool) -> Vec<u8> {
        reply(
            bridges,
            local,
            unit,
            Cal::Reply {
                parameter: 4,
                data: serial(),
            }
            .encode(),
            checksum,
        )
    }

    fn assert_request(actual: &[u8], mut expected: Vec<u8>) -> u8 {
        let code = actual[actual.len() - 2];
        let index = expected.len() - 2;
        expected[index] = code;
        assert_eq!(actual, expected);
        code
    }

    fn assert_retired(pci: &PciClient) {
        assert!(pci.mmi_fault.load(Ordering::Acquire));
        assert!(pci.programming_fault.load(Ordering::Acquire));
        assert!(!pci.is_connected());
        assert!(!pci.mmi_collecting.load(Ordering::Acquire));
    }

    #[test]
    fn frame_capture_preserves_confirmation_bytes_and_bounds_ignored_traffic() {
        let request = b"\\4606040020g\r";
        let mut capture = FrameCapture::new(request, b'g').unwrap();
        let raw = b"g.";
        capture
            .record(
                &Packet::Confirmation {
                    code: b'g',
                    success: true,
                },
                raw,
                false,
            )
            .unwrap();
        let value = capture.finish("quiet_window_elapsed");
        assert_eq!(value["request_hex"], hex::encode(request));
        assert_eq!(value["raw_frames_hex"][0], hex::encode(raw));
        assert_eq!(value["parser_frames_hex"][0], hex::encode(raw));
        assert_eq!(value["confirmation"], "g");
        assert_eq!(value["complete"], true);
        assert_eq!(value["stream_complete"], true);
        assert!(FrameCapture::new(&vec![0; 4097], b'g').is_err());
        let mut capture = FrameCapture::new(request, b'g').unwrap();
        let raw = vec![b'0'; 256];
        let foreign = Packet::Confirmation {
            code: b'h',
            success: true,
        };
        let mut count = 0;
        while capture.record(&foreign, &raw, true).is_ok() {
            count += 1;
            assert!(count < 100);
        }
        assert!(count > 0);
    }

    #[tokio::test(start_paused = true)]
    async fn captured_identify_records_actual_request_original_frames_and_ignored_confirmation() {
        let (pci, mut remote) = setup().await;
        pci.set_command_checksum(false);
        let worker = tokio::spawn({
            let pci = pci.clone();
            async move {
                pci.selected_serial_identify_routed_captured(&[0x20], 16, 6)
                    .await
            }
        });
        let sent = request(&mut remote).await;
        let code = sent[sent.len() - 2];
        let foreign = if code == b'g' { b'h' } else { b'g' };
        let raw = identify(&[0x20], 16, 6, false);
        let mut response = vec![foreign, b'.', code, b'.'];
        response.extend_from_slice(&raw);
        remote.write_all(&response).await.unwrap();
        let (values, evidence) = worker.await.unwrap().unwrap();
        assert_eq!(values, vec![serial()]);
        assert_eq!(evidence["request_hex"], hex::encode(sent));
        assert_eq!(evidence["confirmation"], char::from(code).to_string());
        assert_eq!(evidence["raw_frames_hex"][2], hex::encode(&raw));
        assert_eq!(
            evidence["parser_frames_hex"][2],
            hex::encode(identify(&[0x20], 16, 6, true))
        );
        assert_eq!(
            evidence["ignored_frames_hex"][0],
            hex::encode([foreign, b'.'])
        );
        assert_eq!(evidence["termination"], "quiet_window_elapsed");
        pci.shutdown().await;
    }

    #[tokio::test(start_paused = true)]
    async fn strict_routed_observations_cover_one_two_and_six_bridges_and_both_checksum_modes() {
        for bridges in [vec![0x20], vec![0xfd, 0xfc], vec![1, 2, 3, 4, 5, 6]] {
            for checksum in [true, false] {
                let (pci, mut remote) = setup().await;
                pci.set_command_checksum(checksum);
                let worker = tokio::spawn({
                    let pci = pci.clone();
                    let bridges = bridges.clone();
                    async move { pci.selected_serial_mmi_routed(&bridges, 16).await }
                });
                let code = assert_request(
                    &request(&mut remote).await,
                    routed_installation_mmi_request(&bridges, checksum),
                );
                let mut response = vec![code, b'.'];
                for (start, count) in [(0, 88), (88, 88), (176, 80)] {
                    // A checksum-off peer may mix bare and checksummed replies.
                    response.extend(mmi(&bridges, 16, start, count, checksum || start == 88));
                }
                remote.write_all(&response).await.unwrap();
                let states = worker.await.unwrap().unwrap();
                assert_eq!(states.len(), 256);
                assert_eq!(states[6], 1);

                let worker = tokio::spawn({
                    let pci = pci.clone();
                    let bridges = bridges.clone();
                    async move { pci.selected_serial_identify_routed(&bridges, 16, 6).await }
                });
                let code = assert_request(
                    &request(&mut remote).await,
                    routed_identify_request(&bridges, 6, 4, checksum),
                );
                let mut response = vec![code, b'.'];
                response.extend(identify(&bridges, 16, 6, checksum));
                response.extend(identify(&bridges, 16, 6, true));
                remote.write_all(&response).await.unwrap();
                assert_eq!(worker.await.unwrap().unwrap(), vec![serial(), serial()]);
                assert!(pci.is_connected());
                pci.shutdown().await;
            }
        }
    }

    #[tokio::test(start_paused = true)]
    async fn strict_mmi_rejects_wrong_envelopes_reordered_or_duplicate_blocks_and_confirmations() {
        for variant in 0..8 {
            let bridges = [0xfd, 0xfc];
            let (pci, mut remote) = setup().await;
            let worker = tokio::spawn({
                let pci = pci.clone();
                async move { pci.selected_serial_mmi_routed(&bridges, 16).await }
            });
            let sent = request(&mut remote).await;
            let code = sent[sent.len() - 2];
            let mut response = vec![code, b'.'];
            match variant {
                0 => response.extend(mmi(&bridges, 17, 0, 88, true)),
                1 => response.extend(mmi(&[0xfe, 0xfc], 16, 0, 88, true)),
                2 => response.extend(mmi(&[0xfd, 0xfb], 16, 0, 88, true)),
                3 => response.extend(mmi(&bridges, 16, 88, 88, true)),
                4 => {
                    response.extend(mmi(&bridges, 16, 0, 88, true));
                    response.extend(mmi(&bridges, 16, 0, 88, true));
                }
                5 => {
                    response = mmi(&bridges, 16, 0, 88, true);
                    response.extend_from_slice(&[code, b'.']);
                }
                6 => response.extend_from_slice(&[code, b'.']),
                7 => response = vec![code, b'#'],
                _ => unreachable!(),
            }
            remote.write_all(&response).await.unwrap();
            assert!(worker.await.unwrap().is_err(), "variant {variant}");
            assert_retired(&pci);
            pci.shutdown().await;
        }
    }

    #[tokio::test(start_paused = true)]
    async fn strict_identify_rejects_wrong_envelope_and_ambiguous_cal_even_after_matching_reply() {
        for variant in 0..6 {
            let bridges = [0xfd, 0xfc];
            let (pci, mut remote) = setup().await;
            let worker = tokio::spawn({
                let pci = pci.clone();
                async move { pci.selected_serial_identify_routed(&bridges, 16, 6).await }
            });
            let sent = request(&mut remote).await;
            let code = sent[sent.len() - 2];
            let mut response = vec![code, b'.'];
            response.extend(identify(&bridges, 16, 6, true));
            let bad_reply = match variant {
                0 => identify(&bridges, 17, 6, true),
                1 => identify(&[0xfd, 0xfb], 16, 6, true),
                2 => identify(&bridges, 16, 7, true),
                3 => reply(&bridges, 16, 6, vec![0x85, 4, 1, 2, 3, 4], true),
                4 => {
                    let mut cal = Cal::Reply {
                        parameter: 4,
                        data: serial(),
                    }
                    .encode();
                    cal.extend(
                        Cal::Reply {
                            parameter: 4,
                            data: serial(),
                        }
                        .encode(),
                    );
                    reply(&bridges, 16, 6, cal, true)
                }
                5 => vec![code, b'.'],
                _ => unreachable!(),
            };
            response.extend(bad_reply);
            remote.write_all(&response).await.unwrap();
            assert!(worker.await.unwrap().is_err(), "variant {variant}");
            assert_retired(&pci);
            pci.shutdown().await;
        }
    }

    #[tokio::test(start_paused = true)]
    async fn strict_identify_allows_interleaved_application_traffic_without_extending_quiet_window()
    {
        let (pci, mut remote) = setup().await;
        let worker = tokio::spawn({
            let pci = pci.clone();
            async move { pci.selected_serial_identify_routed(&[0x20], 16, 6).await }
        });
        let sent = request(&mut remote).await;
        let code = sent[sent.len() - 2];
        let mut response = vec![code, b'.'];
        // Ordinary Lighting off traffic from unit 1, application 56.
        response.extend(line(vec![0x05, 0x01, 0x38, 0, 0x01, 1], true));
        response.extend(identify(&[0x20], 16, 6, true));
        remote.write_all(&response).await.unwrap();
        assert_eq!(worker.await.unwrap().unwrap(), vec![serial()]);
        assert!(pci.is_connected());
        pci.shutdown().await;
    }

    #[tokio::test(start_paused = true)]
    async fn strict_observation_deadline_and_cancellation_retire_client_without_replay() {
        for cancel in [false, true] {
            let (pci, mut remote) = setup().await;
            let worker = tokio::spawn({
                let pci = pci.clone();
                async move { pci.selected_serial_identify_routed(&[0x20], 16, 6).await }
            });
            assert!(!request(&mut remote).await.is_empty());
            if cancel {
                worker.abort();
                assert!(worker.await.unwrap_err().is_cancelled());
            } else {
                assert_eq!(
                    worker.await.unwrap().unwrap_err().kind(),
                    ErrorKind::TimedOut
                );
            }
            assert_retired(&pci);
            pci.shutdown().await;
            assert!(request(&mut remote).await.is_empty(), "read was replayed");
        }
    }

    #[tokio::test(start_paused = true)]
    async fn invalid_routes_refuse_before_io_without_faulting_client() {
        let (pci, mut remote) = setup().await;
        for bridges in [vec![], vec![1, 2, 3, 4, 5, 6, 7]] {
            assert_eq!(
                pci.selected_serial_mmi_routed(&bridges, 16)
                    .await
                    .unwrap_err()
                    .kind(),
                ErrorKind::InvalidInput,
            );
            assert_eq!(
                pci.selected_serial_identify_routed(&bridges, 16, 6)
                    .await
                    .unwrap_err()
                    .kind(),
                ErrorKind::InvalidInput,
            );
        }
        assert!(pci.is_connected());
        assert!(!pci.programming_fault.load(Ordering::Acquire));
        assert!(!pci.mmi_fault.load(Ordering::Acquire));
        pci.shutdown().await;
        assert!(request(&mut remote).await.is_empty());
    }

    #[tokio::test(start_paused = true)]
    async fn strict_local_identity_accepts_only_exact_addressed_or_hinted_bare_reply() {
        for checksum in [true, false] {
            for form in 0..3 {
                let (pci, mut remote) = setup().await;
                pci.set_command_checksum(checksum);
                pci.set_local_unit_hint(16).unwrap();
                let worker = tokio::spawn({
                    let pci = pci.clone();
                    async move { pci.selected_serial_local_identity(16).await }
                });
                let code = assert_request(
                    &request(&mut remote).await,
                    cbus_protocol::pci_observation::identify_request(16, 4, checksum),
                );
                let mut response = vec![code, b'.'];
                let cal = Cal::Reply {
                    parameter: 4,
                    data: serial(),
                }
                .encode();
                let payload = match form {
                    0 => cal,
                    _ => {
                        let mut payload = vec![0x86, 16, 16];
                        payload.extend(if form == 1 { vec![0] } else { vec![1, 0] });
                        payload.extend(cal);
                        payload
                    }
                };
                // Include the bare-checksummed/checksum-off decoder case.
                response.extend(line(payload, checksum || form == 0));
                remote.write_all(&response).await.unwrap();
                assert_eq!(worker.await.unwrap().unwrap(), vec![serial()]);
                pci.shutdown().await;
            }
        }
    }

    #[tokio::test(start_paused = true)]
    async fn strict_local_identity_rejects_wrong_destination_and_unhinted_bare_reply() {
        for bare in [false, true] {
            let (pci, mut remote) = setup().await;
            let worker = tokio::spawn({
                let pci = pci.clone();
                async move { pci.selected_serial_local_identity(16).await }
            });
            let sent = request(&mut remote).await;
            let mut response = vec![sent[sent.len() - 2], b'.'];
            let mut payload = if bare { vec![] } else { vec![0x86, 16, 17, 0] };
            payload.extend(
                Cal::Reply {
                    parameter: 4,
                    data: serial(),
                }
                .encode(),
            );
            response.extend(line(payload, true));
            remote.write_all(&response).await.unwrap();
            assert!(worker.await.unwrap().is_err());
            assert_retired(&pci);
            pci.shutdown().await;
        }
    }

    #[tokio::test(start_paused = true)]
    async fn completed_observations_refuse_trailing_partial_input_or_overflow() {
        for identify_read in [false, true] {
            for overflow in [false, true] {
                let (pci, mut remote) = setup().await;
                let worker = tokio::spawn({
                    let pci = pci.clone();
                    async move {
                        if identify_read {
                            pci.selected_serial_identify_routed(&[0x20], 16, 6)
                                .await
                                .map(|_| ())
                        } else {
                            pci.selected_serial_mmi_routed(&[0x20], 16)
                                .await
                                .map(|_| ())
                        }
                    }
                });
                let sent = request(&mut remote).await;
                let mut response = vec![sent[sent.len() - 2], b'.'];
                if identify_read {
                    response.extend(identify(&[0x20], 16, 6, true));
                } else {
                    for (start, count) in [(0, 88), (88, 88), (176, 80)] {
                        response.extend(mmi(&[0x20], 16, start, count, true));
                    }
                }
                if overflow {
                    response.extend_from_slice(&[b'0'; 300]);
                } else {
                    response.extend_from_slice(b"86201001068D04");
                }
                remote.write_all(&response).await.unwrap();
                assert!(
                    worker.await.unwrap().is_err(),
                    "identify={identify_read}, overflow={overflow}"
                );
                assert_retired(&pci);
                pci.shutdown().await;
            }
        }
    }

    #[tokio::test(start_paused = true)]
    async fn strict_local_options_require_positive_confirmation_and_exact_single_reply() {
        for bare in [false, true] {
            for checksum in [true, false] {
                let (pci, mut remote) = setup().await;
                pci.set_command_checksum(checksum);
                pci.set_local_unit_hint(16).unwrap();
                let worker = tokio::spawn({
                    let pci = pci.clone();
                    async move { pci.selected_serial_local_options(16).await }
                });
                let code = assert_request(
                    &request(&mut remote).await,
                    cbus_protocol::pci_observation::recall_request(16, 66, 1, checksum),
                );
                let mut response = vec![code, b'.'];
                let mut payload = if bare { vec![] } else { vec![0x86, 16, 16, 0] };
                payload.extend(
                    Cal::Reply {
                        parameter: 66,
                        data: vec![5],
                    }
                    .encode(),
                );
                response.extend(line(payload, checksum));
                remote.write_all(&response).await.unwrap();
                assert_eq!(worker.await.unwrap().unwrap(), vec![5]);
                pci.shutdown().await;
            }
        }
    }

    #[tokio::test(start_paused = true)]
    async fn strict_local_options_reject_wrong_destination_duplicate_and_unconfirmed_reply() {
        for variant in 0..6 {
            let (pci, mut remote) = setup().await;
            let worker = tokio::spawn({
                let pci = pci.clone();
                async move { pci.selected_serial_local_options(16).await }
            });
            let sent = request(&mut remote).await;
            let code = sent[sent.len() - 2];
            let mut response = if variant == 2 {
                vec![]
            } else {
                vec![code, b'.']
            };
            let mut payload = vec![0x86, 16, if variant == 0 { 17 } else { 16 }, 0];
            payload.extend(
                Cal::Reply {
                    parameter: 66,
                    data: vec![5],
                }
                .encode(),
            );
            let reply = line(payload, true);
            if variant != 5 {
                response.extend_from_slice(&reply);
            }
            match variant {
                1 => response.extend(reply),
                2 => response.extend_from_slice(&[code, b'.']),
                3 => response.extend_from_slice(b"861010008242"),
                4 => response.extend_from_slice(&[code, b'#']),
                _ => {}
            }
            remote.write_all(&response).await.unwrap();
            assert!(worker.await.unwrap().is_err(), "variant {variant}");
            assert_retired(&pci);
            pci.shutdown().await;
        }
    }
}
