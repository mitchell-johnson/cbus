//! Duplicate-preserving full-inventory collector over the shared PCI.
//!
//! This is the transport-layer primitive a future commissioning
//! coordinator needs: one sequential, read-only observation per
//! MMI-present address (IDENTIFY1 unit type, IDENTIFY2 firmware,
//! IDENTIFY4 serials). IDENTIFY4 serial replies are preserved with
//! multiplicity (observed order, duplicates kept, raw bytes verbatim);
//! IDENTIFY1/2 use first-reply semantics (the first unit-type and
//! firmware replies win, so conflicting duplicates collapse to the
//! first). It is the transport-layer answer to the
//! snapshot-collapses-duplicates gap for serials: duplicate serials
//! are preserved with multiplicity in this result. It never touches
//! the stored service model, never claims movement or persistence,
//! and never collapses serial observations to a single serial or an
//! empty string.
//!
//! Failure semantics (mirroring the Python `PCIInventoryCollector`):
//! contiguous MMI coverage is required first, per-address IDENTIFY
//! failures or timeouts are recorded as error entries while collection
//! continues (`partial = true`, never fatal), and an overall deadline
//! bounds the whole sequence. An MMI failure is an overall `Err`.
//!
//! Note: a failed IDENTIFY probe faults the shared programming lane
//! until reconnect (the `PciClient` safety rule against misattributing
//! late untagged replies), so addresses probed after a failure record
//! needs-reconnect errors. Reconnect the PCI before a fresh collection.

use crate::pci::PciClient;
use std::io::{Error, ErrorKind, Result};
use std::time::Duration;

/// Options for [`collect_full_inventory`].
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct InventoryOptions {
    /// Bound for all IDENTIFY work at one address (type + firmware +
    /// serial probes). Expiry records a per-address error entry and
    /// collection continues with the next address.
    pub per_address_timeout: Duration,
    /// Bound for the whole sequence (MMI + every per-address probe).
    /// Expiry is an overall `Err`; observations are sequential and
    /// non-atomic, so a coordinator retries with a fresh collection.
    pub total_deadline: Duration,
}

impl Default for InventoryOptions {
    fn default() -> Self {
        Self {
            per_address_timeout: Duration::from_secs(30),
            total_deadline: Duration::from_secs(300),
        }
    }
}

/// One IDENTIFY4 reply: the raw twelve-byte payload is always preserved
/// verbatim (multiplicity included) alongside its decoded serial.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SerialReply {
    /// Exact IDENTIFY4 reply bytes, preserved even when malformed or
    /// duplicated so no observation is ever lost.
    pub raw: Vec<u8>,
    /// Decoded `first.second` serial, or `None` when the unit reported
    /// unknown (packed zero/`u32::MAX`) or the payload was malformed.
    pub serial: Option<String>,
    /// Present when [`parse_serial_number`] rejected `raw`; `raw` still
    /// carries the evidence.
    pub parse_error: Option<String>,
}

/// Identity observed at one MMI-present address. Every IDENTIFY4
/// serial reply is kept in observed order (duplicates included);
/// IDENTIFY1/2 keep only the first reply. Nothing else here is
/// deduplicated, merged, or collapsed.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct UnitIdentity {
    /// Unit address from the MMI present set.
    pub address: u8,
    /// First IDENTIFY1 reply, when the unit answered.
    pub unit_type_raw: Option<Vec<u8>>,
    /// Decoded first IDENTIFY1 unit type, when the unit answered legibly.
    pub unit_type: Option<String>,
    /// First IDENTIFY2 reply, when the unit answered.
    pub firmware_raw: Option<Vec<u8>>,
    /// Decoded first IDENTIFY2 firmware version, when the unit answered legibly.
    pub firmware: Option<String>,
    /// Every IDENTIFY4 reply in observed order, duplicates included.
    pub serial_replies: Vec<SerialReply>,
    /// Per-address failures, timeouts, silences, and decode errors.
    /// Non-empty entries make the inventory partial, never fatal.
    pub errors: Vec<String>,
}

/// Serial-duplicate-preserving full-inventory result: one [`UnitIdentity`] per
/// MMI-present address, in ascending address order.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FullInventory {
    /// Per-address identities, ascending by address.
    pub units: Vec<UnitIdentity>,
    /// True when the opening MMI covered all 256 addresses
    /// contiguously (`install_mmi` guarantees this or errors).
    pub coverage_complete: bool,
    /// True when any address recorded an error entry (failure, timeout,
    /// silence, or malformed reply). Partial observations are still
    /// returned; only an MMI or total-deadline failure is an `Err`.
    pub partial: bool,
}

/// Decode one twelve-byte IDENTIFY4 reply to its `first.second` serial.
///
/// Bytes 5..9 hold the packed big-endian serial; packed zero and
/// `u32::MAX` mean the unit reports unknown (`Ok(None)`). Anything
/// other than twelve bytes is an `Err`.
///
/// This mirrors the service-side parse; the small pure duplication is
/// deliberate because a transport crate must not depend on the service.
pub fn parse_serial_number(data: &[u8]) -> Result<Option<String>> {
    if data.len() != 12 {
        return Err(Error::new(
            ErrorKind::InvalidData,
            "IDENTIFY4 reply must contain exactly twelve bytes",
        ));
    }
    let packed = u32::from_be_bytes(data[5..9].try_into().unwrap());
    if matches!(packed, 0 | u32::MAX) {
        return Ok(None);
    }
    Ok(Some(format!("{}.{}", packed >> 12, packed & 0xfff)))
}

/// Decode an IDENTIFY1/2 text reply (unit type or firmware version).
///
/// Mirrors the service-side identity decode: UTF-8, trimmed of spaces
/// and NULs, and non-empty afterwards. The duplication is deliberate
/// for the same layering reason as [`parse_serial_number`].
pub fn decode_identity_text(data: &[u8], field: &str) -> Result<String> {
    let value = std::str::from_utf8(data)
        .map_err(|_| Error::new(ErrorKind::InvalidData, format!("invalid {field}")))?
        .trim_matches([' ', '\0'])
        .to_string();
    if value.is_empty() {
        return Err(Error::new(ErrorKind::InvalidData, format!("empty {field}")));
    }
    Ok(value)
}

/// Collect a duplicate-preserving full inventory over a connected PCI.
///
/// `pci` must have completed `pci_reset`. MMI failure (or total-deadline
/// expiry) returns `Err`; per-address IDENTIFY failures, timeouts, and
/// silences are recorded in [`UnitIdentity::errors`] while collection
/// continues. Makes no movement or persistence claims: the returned
/// observations are sequential and non-atomic.
pub async fn collect_full_inventory(
    pci: &PciClient,
    options: InventoryOptions,
) -> Result<FullInventory> {
    if options.per_address_timeout.is_zero() || options.total_deadline.is_zero() {
        return Err(Error::new(
            ErrorKind::InvalidInput,
            "inventory deadlines must be greater than zero",
        ));
    }
    let inner = async {
        let states = pci.install_mmi().await?;
        let addresses: Vec<u8> = states
            .iter()
            .enumerate()
            .filter_map(|(address, state)| (*state != 0).then_some(address as u8))
            .collect();
        let mut units = Vec::with_capacity(addresses.len());
        for address in addresses {
            units.push(collect_unit(pci, address, options.per_address_timeout).await);
        }
        let partial = units.iter().any(|unit| !unit.errors.is_empty());
        Ok(FullInventory {
            units,
            coverage_complete: true,
            partial,
        })
    };
    tokio::time::timeout(options.total_deadline, inner)
        .await
        .unwrap_or_else(|_| {
            Err(Error::new(
                ErrorKind::TimedOut,
                "full inventory total deadline elapsed",
            ))
        })
}

async fn collect_unit(pci: &PciClient, address: u8, per_address_timeout: Duration) -> UnitIdentity {
    let mut identity = UnitIdentity {
        address,
        unit_type_raw: None,
        unit_type: None,
        firmware_raw: None,
        firmware: None,
        serial_replies: Vec::new(),
        errors: Vec::new(),
    };
    let probe = async {
        match pci.identify_first(address, 1).await {
            Ok(Some(raw)) => match decode_identity_text(&raw, "unit type") {
                Ok(text) => {
                    identity.unit_type_raw = Some(raw);
                    identity.unit_type = Some(text);
                }
                Err(error) => {
                    identity.unit_type_raw = Some(raw);
                    identity.errors.push(format!(
                        "address {address} IDENTIFY1 decode failed: {error}"
                    ));
                }
            },
            Ok(None) => identity.errors.push(format!(
                "address {address} IDENTIFY1 silent: unit type unknown"
            )),
            Err(error) => identity
                .errors
                .push(format!("address {address} IDENTIFY1 failed: {error}")),
        }
        match pci.identify_first(address, 2).await {
            Ok(Some(raw)) => match decode_identity_text(&raw, "firmware version") {
                Ok(text) => {
                    identity.firmware_raw = Some(raw);
                    identity.firmware = Some(text);
                }
                Err(error) => {
                    identity.firmware_raw = Some(raw);
                    identity.errors.push(format!(
                        "address {address} IDENTIFY2 decode failed: {error}"
                    ));
                }
            },
            Ok(None) => identity.errors.push(format!(
                "address {address} IDENTIFY2 silent: firmware version unknown"
            )),
            Err(error) => identity
                .errors
                .push(format!("address {address} IDENTIFY2 failed: {error}")),
        }
        match pci.identify_all(address, 4).await {
            Ok(replies) => {
                if replies.is_empty() {
                    identity.errors.push(format!(
                        "address {address} IDENTIFY4 silent: no serial replies"
                    ));
                }
                for raw in replies {
                    match parse_serial_number(&raw) {
                        Ok(serial) => {
                            if serial.is_none() {
                                identity.errors.push(format!(
                                    "address {address} IDENTIFY4 reported an unknown serial"
                                ));
                            }
                            identity.serial_replies.push(SerialReply {
                                raw,
                                serial,
                                parse_error: None,
                            });
                        }
                        Err(error) => {
                            identity.errors.push(format!(
                                "address {address} IDENTIFY4 reply malformed: {error}"
                            ));
                            identity.serial_replies.push(SerialReply {
                                raw,
                                serial: None,
                                parse_error: Some(error.to_string()),
                            });
                        }
                    }
                }
            }
            Err(error) => identity
                .errors
                .push(format!("address {address} IDENTIFY4 failed: {error}")),
        }
    };
    if tokio::time::timeout(per_address_timeout, probe)
        .await
        .is_err()
    {
        identity.errors.push(format!(
            "address {address} probe timed out after {per_address_timeout:?}"
        ));
    }
    identity
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn serial_parse_decodes_packed_first_second() {
        let reply = vec![
            0x38, 0xff, 0xff, 0xff, 0xff, 0x18, 0xb1, 0x06, 0x16, 0xa2, 0x00, 0x05,
        ];
        assert_eq!(
            parse_serial_number(&reply).unwrap(),
            Some("101136.1558".to_string())
        );
        let distinct = vec![
            0x38, 0xff, 0xff, 0xff, 0xff, 0x18, 0xb1, 0x06, 0x17, 0xa2, 0x00, 0x05,
        ];
        assert_eq!(
            parse_serial_number(&distinct).unwrap(),
            Some("101136.1559".to_string())
        );
    }

    #[test]
    fn serial_parse_treats_zero_and_max_packed_as_unknown() {
        let zero = vec![0x38, 0xff, 0xff, 0xff, 0xff, 0, 0, 0, 0, 0xa2, 0x00, 0x05];
        assert_eq!(parse_serial_number(&zero).unwrap(), None);
        let max = vec![
            0x38, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xa2, 0x00, 0x05,
        ];
        assert_eq!(parse_serial_number(&max).unwrap(), None);
    }

    #[test]
    fn serial_parse_rejects_malformed_lengths() {
        for len in [0, 1, 11, 13, 24] {
            let error = parse_serial_number(&vec![0u8; len]).unwrap_err();
            assert_eq!(error.kind(), ErrorKind::InvalidData);
            assert!(
                error.to_string().contains("twelve bytes"),
                "unexpected error: {error}"
            );
        }
    }

    #[test]
    fn identity_text_decodes_and_trims_padding() {
        assert_eq!(
            decode_identity_text(b"DIMMER", "unit type").unwrap(),
            "DIMMER"
        );
        assert_eq!(
            decode_identity_text(b"  1.0.0\0\0", "firmware version").unwrap(),
            "1.0.0"
        );
    }

    #[test]
    fn identity_text_rejects_non_utf8_and_blank() {
        let error = decode_identity_text(&[0xff, 0xfe], "unit type").unwrap_err();
        assert_eq!(error.kind(), ErrorKind::InvalidData);
        assert!(error.to_string().contains("invalid unit type"));
        let error = decode_identity_text(b"   \0 ", "firmware version").unwrap_err();
        assert_eq!(error.kind(), ErrorKind::InvalidData);
        assert!(error.to_string().contains("empty firmware version"));
        let error = decode_identity_text(b"", "unit type").unwrap_err();
        assert_eq!(error.kind(), ErrorKind::InvalidData);
    }

    #[test]
    fn default_options_bound_every_probe_and_the_sequence() {
        let options = InventoryOptions::default();
        assert!(options.per_address_timeout > Duration::from_secs(0));
        assert!(options.total_deadline >= options.per_address_timeout);
    }

    #[tokio::test]
    async fn zero_deadlines_are_rejected_before_transport_use() {
        let (client, _remote) = tokio::io::duplex(64);
        let (reader, writer) = tokio::io::split(client);
        let (events, _) = tokio::sync::mpsc::unbounded_channel();
        let pci = PciClient::new(Box::new(reader), Box::new(writer), events);
        for options in [
            InventoryOptions {
                per_address_timeout: Duration::ZERO,
                total_deadline: Duration::from_secs(1),
            },
            InventoryOptions {
                per_address_timeout: Duration::from_secs(1),
                total_deadline: Duration::ZERO,
            },
        ] {
            let error = collect_full_inventory(&pci, options).await.unwrap_err();
            assert_eq!(error.kind(), ErrorKind::InvalidInput);
        }
    }
}
