//! Correlated programming transactions over the same PCI as lighting/MQTT.
//! Pointer selection is volatile; memory reads never issue a memory write.

use super::*;
use std::io::{Error, ErrorKind, Result};
use std::sync::atomic::{AtomicBool, Ordering};

const REPLY_TIMEOUT: Duration = Duration::from_secs(10);
const IDENTIFY_QUIET: Duration = Duration::from_secs(2);
const IDENTIFY_MAX_REPLIES: usize = 7;

// After a cancelled/failed transaction, late untagged CAL fragments cannot be
// distinguished from a future read. Require a fresh connection instead of
// ever returning a potentially misattributed memory image.
struct Transaction<'a> {
    fault: &'a AtomicBool,
    complete: bool,
}

impl Drop for Transaction<'_> {
    fn drop(&mut self) {
        if !self.complete {
            self.fault.store(true, Ordering::Release);
        }
    }
}

impl PciClient {
    /// Supply the configured local-interface address used to correlate bare
    /// CAL replies. A conflicting hint is rejected; this does not itself
    /// establish physical presence or identity.
    pub fn set_local_unit_hint(&self, unit: u8) -> Result<()> {
        match self.local_unit.compare_exchange(
            256,
            u16::from(unit),
            Ordering::AcqRel,
            Ordering::Acquire,
        ) {
            Ok(_) => Ok(()),
            Err(existing) if existing == u16::from(unit) => Ok(()),
            Err(_) => Err(Error::new(
                ErrorKind::InvalidInput,
                "local-interface address conflicts with the active PCI",
            )),
        }
    }

    /// Discover and cache the attached PCI's own C-Bus unit address through
    /// the read-only BASIC `@1A2001` query. Local IDENTIFY replies are bare
    /// CALs, so callers that inventory the full network must establish this
    /// address before correlating them.
    pub async fn discover_local_unit(&self) -> Result<u8> {
        let cached = self.local_unit.load(Ordering::Acquire);
        if cached <= u8::MAX.into() {
            return Ok(cached as u8);
        }
        let _lane = self.programming_lane.lock().await;
        let cached = self.local_unit.load(Ordering::Acquire);
        if cached <= u8::MAX.into() {
            return Ok(cached as u8);
        }
        if self.programming_fault.load(Ordering::Acquire) {
            return Err(Error::other(
                "programming stream needs reconnect after an incomplete transaction",
            ));
        }
        let mut transaction = Transaction {
            fault: &self.programming_fault,
            complete: false,
        };
        let mut replies = self.packets.subscribe();
        self.init_done
            .subscribe()
            .wait_for(|&done| done)
            .await
            .map_err(|_| Error::new(ErrorKind::BrokenPipe, "PCI initialization ended"))?;
        if !self.is_connected() {
            return Err(Error::new(ErrorKind::BrokenPipe, "PCI disconnected"));
        }
        self.flow
            .submit(
                b"@1A2001\r".to_vec(),
                Priority::Command,
                ResponseKind::Silent,
            )
            .await
            .map_err(|_| Error::new(ErrorKind::BrokenPipe, "PCI writer ended"))??;
        let unit = tokio::time::timeout(REPLY_TIMEOUT, async {
            loop {
                match replies.recv().await {
                    Ok(Some(Packet::BareCal(Cal::Reply {
                        parameter: 0x20,
                        data,
                    }))) => {
                        if data.len() != 1 {
                            return Err(Error::new(
                                ErrorKind::InvalidData,
                                "BASIC local-address reply must contain exactly one byte",
                            ));
                        }
                        return Ok(data[0]);
                    }
                    Ok(Some(Packet::PointToPoint { meta, cals, .. }))
                        if meta.source_address.is_none()
                            && cals.len() == 1
                            && matches!(
                                cals.first(),
                                Some(Cal::Reply {
                                    parameter: 0x20,
                                    ..
                                })
                            ) =>
                    {
                        let Cal::Reply { data, .. } = &cals[0] else {
                            unreachable!("reply checked above")
                        };
                        if data.len() != 1 {
                            return Err(Error::new(
                                ErrorKind::InvalidData,
                                "BASIC local-address reply must contain exactly one byte",
                            ));
                        }
                        return Ok(data[0]);
                    }
                    Ok(Some(Packet::PciError)) => {
                        return Err(Error::other("PCI rejected local-address discovery"))
                    }
                    Ok(Some(_)) => {}
                    Ok(None) | Err(_) => {
                        return Err(Error::new(
                            ErrorKind::BrokenPipe,
                            "PCI response stream lost",
                        ))
                    }
                }
            }
        })
        .await
        .unwrap_or_else(|_| {
            Err(Error::new(
                ErrorKind::TimedOut,
                "local-address discovery timed out",
            ))
        })?;
        self.local_unit.store(u16::from(unit), Ordering::Release);
        transaction.complete = true;
        Ok(unit)
    }

    /// Whether the reader has observed transport loss.
    pub fn is_connected(&self) -> bool {
        !self.disconnected.load(Ordering::Acquire)
    }

    /// Send a command and wait for its PCI delivery confirmation. A negative
    /// confirmation is an error, not a successful state transition.
    pub async fn send_confirmed(&self, packet: &Packet) -> Result<()> {
        let mut replies = self.packets.subscribe();
        if !self.is_connected() {
            return Err(Error::new(ErrorKind::BrokenPipe, "PCI disconnected"));
        }
        let code = self
            .send(packet, true, false)
            .await?
            .ok_or_else(|| Error::new(ErrorKind::InvalidInput, "command cannot be confirmed"))?;
        let result = tokio::time::timeout(Duration::from_secs(12), async {
            loop {
                match replies.recv().await {
                    Ok(Some(Packet::Confirmation { code: got, success })) if got == code => {
                        return if success {
                            Ok(())
                        } else {
                            Err(Error::other("PCI rejected command"))
                        };
                    }
                    Ok(Some(_)) => {}
                    Ok(None) | Err(_) => {
                        return Err(Error::new(
                            ErrorKind::BrokenPipe,
                            "PCI response stream lost",
                        ))
                    }
                }
            }
        })
        .await
        .unwrap_or_else(|_| {
            Err(Error::new(
                ErrorKind::TimedOut,
                "PCI delivery confirmation timed out",
            ))
        });
        if result.is_err() {
            let mut state = self.state.lock().unwrap();
            state.pending.remove(&code);
            state.codes_in_use.remove(&code);
        }
        result
    }

    async fn programming_exchange(
        &self,
        unit: u8,
        request: Cal,
        parameter: u8,
        count: usize,
        ack: Option<u8>,
        direct_route: bool,
    ) -> Result<Vec<u8>> {
        let mut replies = self.packets.subscribe();
        let bytes = if direct_route {
            let packet = Packet::PointToPoint {
                meta: Meta::new(true, 1),
                unit_address: unit,
                bridged: false,
                hops: vec![],
                cals: vec![request],
            };
            let mut bytes = vec![b'\\'];
            bytes.extend(
                packet
                    .encode_packet()
                    .map_err(|e| Error::new(ErrorKind::InvalidInput, e.0))?,
            );
            bytes.push(b'\r');
            bytes
        } else {
            cbus_protocol::packet::programming_request(unit, &request)
                .map_err(|e| Error::new(ErrorKind::InvalidInput, e.0))?
        };
        tokio::time::timeout(REPLY_TIMEOUT, async {
            self.init_done
                .subscribe()
                .wait_for(|&done| done)
                .await
                .map_err(|_| Error::new(ErrorKind::BrokenPipe, "PCI initialization ended"))?;
            if !self.is_connected() {
                return Err(Error::new(ErrorKind::BrokenPipe, "PCI disconnected"));
            }
            self.flow
                .submit(bytes, Priority::Command, ResponseKind::Silent)
                .await
                .map_err(|_| Error::new(ErrorKind::BrokenPipe, "PCI writer ended"))??;
            let mut result = Vec::with_capacity(count);
            loop {
                let cals = match replies.recv().await {
                    Ok(Some(Packet::PointToPoint { meta, cals, .. }))
                        if meta.source_address == Some(unit) =>
                    {
                        cals
                    }
                    Ok(Some(Packet::PointToPoint { meta, cals, .. }))
                        if meta.source_address.is_none()
                            && self.local_unit.load(Ordering::Acquire) == u16::from(unit) =>
                    {
                        cals
                    }
                    Ok(Some(Packet::BareCal(cal)))
                        if self.local_unit.load(Ordering::Acquire) == u16::from(unit) =>
                    {
                        vec![cal]
                    }
                    Ok(Some(_)) => continue,
                    Ok(None) | Err(_) => {
                        return Err(Error::new(
                            ErrorKind::BrokenPipe,
                            "PCI response stream lost",
                        ))
                    }
                };
                for cal in cals {
                    match cal {
                        Cal::Ack { parameter: p, data } if p == parameter && ack.is_some() => {
                            if data == [ack.unwrap()] {
                                return Ok(Vec::new());
                            }
                            return Err(Error::other("unit rejected programming selector"));
                        }
                        Cal::Reply { parameter: p, data } if p == parameter && ack.is_none() => {
                            if count == 0 {
                                return Ok(data);
                            }
                            result.extend(data);
                            if result.len() > count {
                                return Err(Error::new(
                                    ErrorKind::InvalidData,
                                    "unit returned excess memory bytes",
                                ));
                            }
                            if result.len() == count {
                                return Ok(result);
                            }
                        }
                        _ => {}
                    }
                }
            }
        })
        .await
        .unwrap_or_else(|_| {
            Err(Error::new(
                ErrorKind::TimedOut,
                "unit programming reply timed out",
            ))
        })
    }

    /// Read a bounded range of OEM physical memory. Each block explicitly
    /// selects its address; the only WRITE is the volatile 0x41 selector.
    /// Logical unit-spec addresses >=256 map to physical address = logical-256.
    pub async fn read_memory(&self, unit: u8, address: u32, length: usize) -> Result<Vec<u8>> {
        if length == 0 || length > 65536 || address.checked_add(length as u32).is_none() {
            return Err(Error::new(
                ErrorKind::InvalidInput,
                "memory read requires 1..65536 bytes without address overflow",
            ));
        }
        let _lane = self.programming_lane.lock().await;
        if self.programming_fault.load(Ordering::Acquire) {
            return Err(Error::other(
                "programming stream needs reconnect after an incomplete transaction",
            ));
        }
        let mut transaction = Transaction {
            fault: &self.programming_fault,
            complete: false,
        };
        let mut result = Vec::with_capacity(length);
        while result.len() < length {
            let offset = address + result.len() as u32;
            let mut selector = vec![0x41];
            selector
                .extend_from_slice(&offset.to_le_bytes()[..if offset <= 0xffff { 2 } else { 4 }]);
            self.programming_exchange(
                unit,
                Cal::Write {
                    parameter: 0,
                    data: selector,
                },
                0,
                0,
                Some(0x41),
                false,
            )
            .await?;
            let count = (length - result.len()).min(128) as u8;
            result.extend(
                self.programming_exchange(
                    unit,
                    Cal::Recall { param: 1, count },
                    1,
                    usize::from(count),
                    None,
                    false,
                )
                .await?,
            );
        }
        transaction.complete = true;
        Ok(result)
    }

    /// Recall one standard CAL programming parameter. This is the transport
    /// used by native PP for unit-spec logical addresses below 256; larger
    /// logical addresses use [`Self::read_memory`] with the 256-byte bias.
    pub async fn recall_parameter(
        &self,
        unit: u8,
        parameter: u8,
        length: usize,
    ) -> Result<Vec<u8>> {
        let count = u8::try_from(length).map_err(|_| {
            Error::new(
                ErrorKind::InvalidInput,
                "parameter recall requires 1..255 bytes",
            )
        })?;
        if count == 0 {
            return Err(Error::new(
                ErrorKind::InvalidInput,
                "parameter recall requires 1..255 bytes",
            ));
        }
        let _lane = self.programming_lane.lock().await;
        if self.programming_fault.load(Ordering::Acquire) {
            return Err(Error::other(
                "programming stream needs reconnect after an incomplete transaction",
            ));
        }
        let mut transaction = Transaction {
            fault: &self.programming_fault,
            complete: false,
        };
        let result = self
            .programming_exchange(
                unit,
                Cal::Recall {
                    param: parameter,
                    count,
                },
                parameter,
                length,
                None,
                true,
            )
            .await?;
        transaction.complete = true;
        Ok(result)
    }

    /// Store one contiguous standard CAL parameter range and verify it with
    /// an immediate direct RECALL. Each STORE carries an explicit transaction
    /// tag, and large ranges are split at the 29-data-byte CAL limit.
    pub async fn store_parameter_verified(
        &self,
        unit: u8,
        parameter: u8,
        data: &[u8],
    ) -> Result<()> {
        if data.is_empty()
            || data.len() > u8::MAX as usize
            || usize::from(parameter) + data.len() > 256
        {
            return Err(Error::new(
                ErrorKind::InvalidInput,
                "parameter store requires 1..255 bytes within the parameter address space",
            ));
        }
        let _lane = self.programming_lane.lock().await;
        if self.programming_fault.load(Ordering::Acquire) {
            return Err(Error::other(
                "programming stream needs reconnect after an incomplete transaction",
            ));
        }
        let mut transaction = Transaction {
            fault: &self.programming_fault,
            complete: false,
        };
        for (chunk_index, chunk) in data.chunks(29).enumerate() {
            let offset = chunk_index * 29;
            let target = parameter + offset as u8;
            let tag = chunk_index as u8;
            let mut tagged = Vec::with_capacity(chunk.len() + 1);
            tagged.push(tag);
            tagged.extend_from_slice(chunk);
            self.programming_exchange(
                unit,
                Cal::Write {
                    parameter: target,
                    data: tagged,
                },
                target,
                0,
                Some(tag),
                true,
            )
            .await?;
        }
        let count = data.len() as u8;
        let actual = self
            .programming_exchange(
                unit,
                Cal::Recall {
                    param: parameter,
                    count,
                },
                parameter,
                data.len(),
                None,
                true,
            )
            .await?;
        if actual != data {
            return Err(Error::other(
                "standard parameter readback did not match STORE",
            ));
        }
        transaction.complete = true;
        Ok(())
    }

    /// Store a bounded OEM physical-memory range through the captured 0x41
    /// pointer and tagged 0x42 data path, then reselect and read the entire
    /// range back before reporting success.
    pub async fn write_memory_verified(&self, unit: u8, address: u32, data: &[u8]) -> Result<()> {
        if data.is_empty()
            || data.len() > 65_536
            || address.checked_add(data.len() as u32).is_none()
        {
            return Err(Error::new(
                ErrorKind::InvalidInput,
                "memory store requires 1..65536 bytes without address overflow",
            ));
        }
        let _lane = self.programming_lane.lock().await;
        if self.programming_fault.load(Ordering::Acquire) {
            return Err(Error::other(
                "programming stream needs reconnect after an incomplete transaction",
            ));
        }
        let mut transaction = Transaction {
            fault: &self.programming_fault,
            complete: false,
        };
        for (chunk_index, chunk) in data.chunks(29).enumerate() {
            let offset = address + (chunk_index * 29) as u32;
            let mut selector = vec![0x41];
            selector
                .extend_from_slice(&offset.to_le_bytes()[..if offset <= 0xffff { 2 } else { 4 }]);
            self.programming_exchange(
                unit,
                Cal::Write {
                    parameter: 0,
                    data: selector,
                },
                0,
                0,
                Some(0x41),
                false,
            )
            .await?;
            let mut tagged = Vec::with_capacity(chunk.len() + 1);
            tagged.push(0x42);
            tagged.extend_from_slice(chunk);
            self.programming_exchange(
                unit,
                Cal::Write {
                    parameter: 1,
                    data: tagged,
                },
                1,
                0,
                Some(0x42),
                false,
            )
            .await?;
        }

        let mut actual = Vec::with_capacity(data.len());
        while actual.len() < data.len() {
            let offset = address + actual.len() as u32;
            let mut selector = vec![0x41];
            selector
                .extend_from_slice(&offset.to_le_bytes()[..if offset <= 0xffff { 2 } else { 4 }]);
            self.programming_exchange(
                unit,
                Cal::Write {
                    parameter: 0,
                    data: selector,
                },
                0,
                0,
                Some(0x41),
                false,
            )
            .await?;
            let count = (data.len() - actual.len()).min(128) as u8;
            actual.extend(
                self.programming_exchange(
                    unit,
                    Cal::Recall { param: 1, count },
                    1,
                    usize::from(count),
                    None,
                    false,
                )
                .await?,
            );
        }
        if actual != data {
            return Err(Error::other("physical memory readback did not match STORE"));
        }
        transaction.complete = true;
        Ok(())
    }

    /// Identify a real unit attribute, preserving its original reply bytes.
    pub async fn identify(&self, unit: u8, attribute: u8) -> Result<Vec<u8>> {
        let _lane = self.programming_lane.lock().await;
        if self.programming_fault.load(Ordering::Acquire) {
            return Err(Error::other(
                "programming stream needs reconnect after an incomplete transaction",
            ));
        }
        let mut transaction = Transaction {
            fault: &self.programming_fault,
            complete: false,
        };
        let result = self
            .programming_exchange(unit, Cal::Identify { attribute }, attribute, 0, None, true)
            .await?;
        transaction.complete = true;
        Ok(result)
    }

    /// Collect every reply to one IDENTIFY request through a two-second
    /// quiet interval. This is the native C-Gate duplicate-address probe used
    /// by `NET CHECKUNIT`: a first reply establishes presence, but cannot
    /// establish that only one unit owns the address.
    ///
    /// A positive PCI delivery confirmation is required before the observation
    /// can complete; real CNIs may deliver unit data first, so it is buffered
    /// until that confirmation arrives. Reaching the seven-frame native response bound is treated as
    /// incomplete rather than silently claiming that no further identity was
    /// present. As with memory reads, any incomplete observation poisons this
    /// programming lane until reconnect so a late untagged reply cannot be
    /// attributed to another request.
    pub async fn identify_all(&self, unit: u8, attribute: u8) -> Result<Vec<Vec<u8>>> {
        self.identify_collect(unit, attribute, false).await
    }

    /// Return the first confirmed matching IDENTIFY reply, or `None` when the
    /// unit remains silent for the bounded response window. This populates
    /// ordinary identity fields without claiming duplicate absence.
    pub async fn identify_first(&self, unit: u8, attribute: u8) -> Result<Option<Vec<u8>>> {
        Ok(self
            .identify_collect(unit, attribute, true)
            .await?
            .into_iter()
            .next())
    }

    async fn identify_collect(
        &self,
        unit: u8,
        attribute: u8,
        stop_after_first: bool,
    ) -> Result<Vec<Vec<u8>>> {
        let _lane = self.programming_lane.lock().await;
        if self.programming_fault.load(Ordering::Acquire) {
            return Err(Error::other(
                "programming stream needs reconnect after an incomplete transaction",
            ));
        }
        let mut transaction = Transaction {
            fault: &self.programming_fault,
            complete: false,
        };
        let mut replies = self.packets.subscribe();
        if !self.is_connected() {
            return Err(Error::new(ErrorKind::BrokenPipe, "PCI disconnected"));
        }
        let packet = Packet::PointToPoint {
            meta: Meta::new(true, 1),
            unit_address: unit,
            bridged: false,
            hops: vec![],
            cals: vec![Cal::Identify { attribute }],
        };
        let code = self
            .send(&packet, true, false)
            .await?
            .ok_or_else(|| Error::new(ErrorKind::InvalidInput, "IDENTIFY cannot be confirmed"))?;

        let result = tokio::time::timeout(REPLY_TIMEOUT, async {
            let mut confirmed = false;
            let mut collected = Vec::new();
            let mut quiet_deadline = None;
            loop {
                let next =
                    async {
                        match quiet_deadline {
                            Some(deadline) => tokio::time::timeout_at(deadline, replies.recv())
                                .await
                                .map_err(|_| Error::new(ErrorKind::TimedOut, "identify quiet"))?,
                            None => replies.recv().await,
                        }
                        .map_err(|_| Error::new(ErrorKind::BrokenPipe, "PCI response stream lost"))
                    };
                match next.await {
                    Err(error)
                        if error.kind() == ErrorKind::TimedOut && quiet_deadline.is_some() =>
                    {
                        return Ok(collected)
                    }
                    Err(error) => return Err(error),
                    Ok(None) => {
                        return Err(Error::new(
                            ErrorKind::BrokenPipe,
                            "PCI response stream lost",
                        ))
                    }
                    Ok(Some(Packet::Confirmation { code: got, success })) if got == code => {
                        if confirmed {
                            return Err(Error::new(
                                ErrorKind::InvalidData,
                                "duplicate IDENTIFY confirmation",
                            ));
                        }
                        if !success {
                            return Err(Error::other("PCI rejected IDENTIFY command"));
                        }
                        confirmed = true;
                        if stop_after_first && !collected.is_empty() {
                            return Ok(collected);
                        }
                        quiet_deadline = Some(Instant::now() + IDENTIFY_QUIET);
                    }
                    Ok(Some(packet)) => {
                        let cals = match packet {
                            Packet::PointToPoint { meta, cals, .. }
                                if meta.source_address == Some(unit) =>
                            {
                                cals
                            }
                            Packet::PointToPoint { meta, cals, .. }
                                if meta.source_address.is_none()
                                    && self.local_unit.load(Ordering::Acquire)
                                        == u16::from(unit) =>
                            {
                                cals
                            }
                            Packet::BareCal(cal)
                                if self.local_unit.load(Ordering::Acquire) == u16::from(unit) =>
                            {
                                vec![cal]
                            }
                            _ => continue,
                        };
                        if !cals.iter().any(|cal| {
                            matches!(cal, Cal::Reply { parameter, .. } if *parameter == attribute)
                        }) {
                            continue;
                        }
                        if cals.len() != 1 {
                            return Err(Error::new(
                                ErrorKind::InvalidData,
                                "IDENTIFY reply contains an ambiguous CAL chain",
                            ));
                        }
                        let Cal::Reply { data, .. } = cals.into_iter().next().unwrap() else {
                            unreachable!("matching reply checked above")
                        };
                        collected.push(data);
                        if stop_after_first && confirmed {
                            return Ok(collected);
                        }
                        if collected.len() >= IDENTIFY_MAX_REPLIES {
                            return Err(Error::new(
                                ErrorKind::InvalidData,
                                "IDENTIFY response count reached the collection limit",
                            ));
                        }
                        if confirmed {
                            quiet_deadline = Some(Instant::now() + IDENTIFY_QUIET);
                        }
                    }
                }
            }
        })
        .await
        .unwrap_or_else(|_| {
            Err(Error::new(
                ErrorKind::TimedOut,
                "IDENTIFY collection timed out",
            ))
        });

        if result.is_err() {
            let mut state = self.state.lock().unwrap();
            state.pending.remove(&code);
            state.codes_in_use.remove(&code);
        } else {
            transaction.complete = true;
        }
        result
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tokio::io::{AsyncBufReadExt, BufReader};

    async fn setup() -> (
        Arc<PciClient>,
        BufReader<tokio::io::DuplexStream>,
        mpsc::UnboundedReceiver<CBusEvent>,
    ) {
        let (client, remote) = tokio::io::duplex(8192);
        let (rd, wr) = tokio::io::split(client);
        let (tx, rx) = mpsc::unbounded_channel();
        let pci = PciClient::new(Box::new(rd), Box::new(wr), tx);
        pci.pci_reset().await.unwrap();
        let mut remote = BufReader::new(remote);
        for _ in 0..8 {
            let mut bytes = Vec::new();
            remote.read_until(b'\r', &mut bytes).await.unwrap();
        }
        (pci, remote, rx)
    }

    async fn line(remote: &mut BufReader<tokio::io::DuplexStream>) -> Vec<u8> {
        let mut bytes = Vec::new();
        remote.read_until(b'\r', &mut bytes).await.unwrap();
        bytes
    }

    async fn reply(remote: &mut BufReader<tokio::io::DuplexStream>, unit: u8, cal: &[u8]) {
        // Captured response route; independent of the request encoder.
        let mut bytes = vec![0x86, unit, 0x10, 0x01, 0x00];
        bytes.extend(cal);
        let sum = bytes.iter().fold(0u8, |acc, b| acc.wrapping_add(*b));
        bytes.push(0u8.wrapping_sub(sum));
        let wire = format!(
            "{}\r\n",
            bytes.iter().map(|b| format!("{b:02X}")).collect::<String>()
        );
        remote.get_mut().write_all(wire.as_bytes()).await.unwrap();
    }

    #[tokio::test(start_paused = true)]
    async fn memory_read_matches_source_and_assembles_fragments_without_stealing_mqtt() {
        let (pci, mut remote, mut events) = setup().await;
        let read = tokio::spawn(async move { pci.read_memory(5, 0x10000, 33).await });
        assert_eq!(line(&mut remote).await, b"\\46050900A6004100000100C4\r");
        reply(&mut remote, 4, &[0x32, 0, 0x41]).await;
        reply(&mut remote, 5, &[0x32, 0, 0x41]).await;
        assert_eq!(line(&mut remote).await, b"\\460509001A012170\r");
        // A real lighting event interleaved with CAL traffic still reaches MQTT.
        remote
            .get_mut()
            .write_all(b"05043800790145\r\n")
            .await
            .unwrap();
        reply(&mut remote, 4, &[0x82, 1, 0xff]).await;
        for range in [0..16, 16..32, 32..33] {
            let mut cal = vec![0x80 | (range.len() as u8 + 1), 1];
            cal.extend(range);
            reply(&mut remote, 5, &cal).await;
        }
        assert_eq!(read.await.unwrap().unwrap(), (0..33).collect::<Vec<u8>>());
        assert!(matches!(
            events.recv().await,
            Some(CBusEvent::LightingOn {
                source: Some(4),
                app: 56,
                group: 1
            })
        ));
    }

    #[tokio::test(start_paused = true)]
    async fn standard_parameter_recall_uses_declared_parameter_and_exact_length() {
        let (pci, mut remote, _) = setup().await;
        let worker = pci.clone();
        let read = tokio::spawn(async move { worker.recall_parameter(5, 0x22, 3).await });
        assert_eq!(line(&mut remote).await, b"\\4605001A220376\r");
        reply(&mut remote, 4, &[0x83, 0x22, 9, 9]).await;
        reply(&mut remote, 5, &[0x82, 0x22, 1]).await;
        reply(&mut remote, 5, &[0x83, 0x22, 2, 3]).await;
        assert_eq!(read.await.unwrap().unwrap(), vec![1, 2, 3]);
        assert_eq!(
            pci.recall_parameter(5, 1, 0).await.unwrap_err().kind(),
            ErrorKind::InvalidInput
        );
        assert_eq!(
            pci.recall_parameter(5, 1, 256).await.unwrap_err().kind(),
            ErrorKind::InvalidInput
        );
    }

    #[tokio::test(start_paused = true)]
    async fn standard_parameter_store_is_tagged_direct_and_read_back() {
        let (pci, mut remote, _) = setup().await;
        let worker = pci.clone();
        let data = [0xbe, 0xfd, 0xb1, 0xa3, 0x39, 0x1e];
        let write =
            tokio::spawn(async move { worker.store_parameter_verified(5, 0x2a, &data).await });
        assert_eq!(line(&mut remote).await, b"\\460500A82A00BEFDB1A3391E7D\r");
        reply(&mut remote, 4, &[0x32, 0x2a, 0]).await;
        reply(&mut remote, 5, &[0x32, 0x2a, 0]).await;
        assert_eq!(line(&mut remote).await, b"\\4605001A2A066B\r");
        reply(
            &mut remote,
            5,
            &[0x87, 0x2a, 0xbe, 0xfd, 0xb1, 0xa3, 0x39, 0x1e],
        )
        .await;
        write.await.unwrap().unwrap();
        assert_eq!(
            pci.store_parameter_verified(5, 1, &[])
                .await
                .unwrap_err()
                .kind(),
            ErrorKind::InvalidInput
        );
        assert_eq!(
            pci.store_parameter_verified(5, 255, &[1, 2])
                .await
                .unwrap_err()
                .kind(),
            ErrorKind::InvalidInput
        );
    }

    #[tokio::test(start_paused = true)]
    async fn oem_memory_store_uses_captured_tags_and_verifies_readback() {
        let (pci, mut remote, _) = setup().await;
        let worker = pci.clone();
        let write = tokio::spawn(async move {
            worker
                .write_memory_verified(5, 0x1000, &[0xaa, 0xbb, 0xcc])
                .await
        });
        assert_eq!(line(&mut remote).await, b"\\46050900A400410010B7\r");
        reply(&mut remote, 5, &[0x32, 0, 0x41]).await;
        assert_eq!(line(&mut remote).await, b"\\46050900A50142AABBCC93\r");
        reply(&mut remote, 4, &[0x32, 1, 0x42]).await;
        reply(&mut remote, 5, &[0x32, 1, 0x42]).await;
        assert_eq!(line(&mut remote).await, b"\\46050900A400410010B7\r");
        reply(&mut remote, 5, &[0x32, 0, 0x41]).await;
        assert_eq!(line(&mut remote).await, b"\\460509001A01038E\r");
        reply(&mut remote, 5, &[0x84, 1, 0xaa, 0xbb, 0xcc]).await;
        write.await.unwrap().unwrap();
        assert_eq!(
            pci.write_memory_verified(5, u32::MAX, &[1])
                .await
                .unwrap_err()
                .kind(),
            ErrorKind::InvalidInput
        );
    }

    #[tokio::test(start_paused = true)]
    async fn incomplete_read_poisoned_until_reconnect_and_does_not_write_memory() {
        let (pci, mut remote, _) = setup().await;
        let cloned = pci.clone();
        let read = tokio::spawn(async move { cloned.read_memory(5, 0x1000, 64).await });
        assert_eq!(line(&mut remote).await, b"\\46050900A400410010B7\r");
        reply(&mut remote, 5, &[0x32, 0, 0x41]).await;
        assert_eq!(line(&mut remote).await, b"\\460509001A014051\r");
        reply(&mut remote, 5, &[0x82, 1, 0x20]).await;
        assert_eq!(read.await.unwrap().unwrap_err().kind(), ErrorKind::TimedOut);
        assert!(pci
            .read_memory(5, 0x1000, 64)
            .await
            .unwrap_err()
            .to_string()
            .contains("reconnect"));
    }

    #[tokio::test(start_paused = true)]
    async fn negative_delivery_confirmation_is_error_and_never_retried() {
        let (pci, mut remote, _) = setup().await;
        let cloned = pci.clone();
        let command = tokio::spawn(async move {
            cloned
                .send_confirmed(&Packet::PointToMultipoint {
                    meta: Meta::new(true, 0),
                    application: 56,
                    sals: vec![Sal::LightingOn {
                        application: 56,
                        group_address: 1,
                    }],
                })
                .await
        });
        assert_eq!(line(&mut remote).await, b"\\053800790149h\r");
        remote.get_mut().write_all(b"h.").await.unwrap();
        assert!(command.await.unwrap().is_ok());
        assert!(pci.state.lock().unwrap().pending.is_empty());
        let cloned = pci.clone();
        let command = tokio::spawn(async move {
            cloned
                .send_confirmed(&Packet::PointToMultipoint {
                    meta: Meta::new(true, 0),
                    application: 56,
                    sals: vec![Sal::LightingOff {
                        application: 56,
                        group_address: 1,
                    }],
                })
                .await
        });
        line(&mut remote).await;
        remote.get_mut().write_all(b"i#").await.unwrap();
        assert!(command
            .await
            .unwrap()
            .unwrap_err()
            .to_string()
            .contains("rejected"));
        assert!(pci.state.lock().unwrap().pending.is_empty());
    }

    #[tokio::test(start_paused = true)]
    async fn identify_all_waits_for_quiet_and_preserves_distinct_replies() {
        let (pci, mut remote, mut events) = setup().await;
        let running = tokio::spawn({
            let pci = pci.clone();
            async move { pci.identify_all(5, 4).await }
        });
        let request = line(&mut remote).await;
        assert!(
            request.starts_with(b"\\4605002104"),
            "{}",
            String::from_utf8_lossy(&request)
        );
        let code = request[request.len() - 2];
        remote.get_mut().write_all(&[code, b'.']).await.unwrap();
        let first = vec![
            0x38, 0xff, 0xff, 0xff, 0xff, 0x18, 0xb1, 0x06, 0x16, 0xa2, 0x00, 0x05,
        ];
        let second = vec![
            0x38, 0xff, 0xff, 0xff, 0xff, 0x18, 0xb1, 0x06, 0x17, 0xa2, 0x00, 0x05,
        ];
        reply(
            &mut remote,
            5,
            &[
                0x8d, 4, first[0], first[1], first[2], first[3], first[4], first[5], first[6],
                first[7], first[8], first[9], first[10], first[11],
            ],
        )
        .await;
        remote
            .get_mut()
            .write_all(b"05043800790145\r\n")
            .await
            .unwrap();
        tokio::time::advance(Duration::from_millis(1500)).await;
        tokio::task::yield_now().await;
        assert!(!running.is_finished());
        reply(
            &mut remote,
            5,
            &[
                0x8d, 4, second[0], second[1], second[2], second[3], second[4], second[5],
                second[6], second[7], second[8], second[9], second[10], second[11],
            ],
        )
        .await;
        tokio::time::advance(IDENTIFY_QUIET).await;
        tokio::task::yield_now().await;
        assert_eq!(running.await.unwrap().unwrap(), vec![first, second]);
        assert!(matches!(
            events.recv().await,
            Some(CBusEvent::LightingOn {
                source: Some(4),
                app: 56,
                group: 1
            })
        ));
    }

    #[tokio::test(start_paused = true)]
    async fn identify_all_can_prove_no_reply_in_the_bounded_window() {
        let (pci, mut remote, _) = setup().await;
        let running = tokio::spawn(async move { pci.identify_all(99, 4).await });
        let request = line(&mut remote).await;
        let code = request[request.len() - 2];
        remote.get_mut().write_all(&[code, b'.']).await.unwrap();
        tokio::time::advance(IDENTIFY_QUIET).await;
        tokio::task::yield_now().await;
        assert!(running.await.unwrap().unwrap().is_empty());
    }

    #[tokio::test(start_paused = true)]
    async fn local_address_discovery_correlates_bare_identify_replies() {
        let (pci, mut remote, _) = setup().await;
        let discovery = tokio::spawn({
            let pci = pci.clone();
            async move { pci.discover_local_unit().await }
        });
        assert_eq!(line(&mut remote).await, b"@1A2001\r");
        remote.get_mut().write_all(b"8220104E\r\n").await.unwrap();
        assert_eq!(discovery.await.unwrap().unwrap(), 16);

        let running = tokio::spawn(async move { pci.identify_all(16, 4).await });
        let request = line(&mut remote).await;
        let code = request[request.len() - 2];
        remote.get_mut().write_all(&[code, b'.']).await.unwrap();
        let identity = vec![
            0xff, 0xff, 0xff, 0x00, 0x00, 0x18, 0xa6, 0x64, 0xa3, 0xb1, 0x00, 0x05,
        ];
        let mut raw = Cal::Reply {
            parameter: 4,
            data: identity.clone(),
        }
        .encode();
        raw = cbus_protocol::common::add_cbus_checksum(&raw);
        let mut wire = raw
            .iter()
            .flat_map(|byte| format!("{byte:02X}").into_bytes())
            .collect::<Vec<_>>();
        wire.extend_from_slice(b"\r\n");
        remote.get_mut().write_all(&wire).await.unwrap();
        tokio::task::yield_now().await;
        tokio::time::advance(IDENTIFY_QUIET).await;
        tokio::task::yield_now().await;
        assert_eq!(running.await.unwrap().unwrap(), vec![identity]);
    }

    #[tokio::test(start_paused = true)]
    async fn identify_all_buffers_data_until_positive_confirmation() {
        let (pci, mut remote, _) = setup().await;
        let cloned = pci.clone();
        let running = tokio::spawn(async move { cloned.identify_all(5, 4).await });
        let request = line(&mut remote).await;
        let code = request[request.len() - 2];
        let data = [
            0x38, 0xff, 0xff, 0xff, 0xff, 0x18, 0xb1, 0x06, 0x16, 0xa2, 0x00, 0x05,
        ];
        let mut cal = vec![0x8d, 4];
        cal.extend(data);
        reply(&mut remote, 5, &cal).await;
        tokio::task::yield_now().await;
        assert!(!running.is_finished());
        remote.get_mut().write_all(&[code, b'.']).await.unwrap();
        tokio::time::advance(IDENTIFY_QUIET).await;
        tokio::task::yield_now().await;
        assert_eq!(running.await.unwrap().unwrap(), vec![data.to_vec()]);
    }
}
