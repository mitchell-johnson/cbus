//! Correlated programming transactions over the same PCI as lighting/MQTT.
//! Pointer selection is volatile; memory reads never issue a memory write.

use super::*;
use std::io::{Error, ErrorKind, Result};
use std::sync::atomic::{AtomicBool, Ordering};

const REPLY_TIMEOUT: Duration = Duration::from_secs(10);

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
    ) -> Result<Vec<u8>> {
        let mut replies = self.packets.subscribe();
        let bytes = if matches!(request, Cal::Identify { .. }) {
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
                match replies.recv().await {
                    Ok(Some(Packet::PointToPoint { meta, cals, .. }))
                        if meta.source_address == Some(unit) =>
                    {
                        for cal in cals {
                            match cal {
                                Cal::Ack { parameter: p, data }
                                    if p == parameter && ack.is_some() =>
                                {
                                    if data == [ack.unwrap()] {
                                        return Ok(Vec::new());
                                    }
                                    return Err(Error::other("unit rejected programming selector"));
                                }
                                Cal::Reply { parameter: p, data }
                                    if p == parameter && ack.is_none() =>
                                {
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
                )
                .await?,
            );
        }
        transaction.complete = true;
        Ok(result)
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
            .programming_exchange(unit, Cal::Identify { attribute }, attribute, 0, None)
            .await?;
        transaction.complete = true;
        Ok(result)
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
}
