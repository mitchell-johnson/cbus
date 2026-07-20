//! Property-based tests for the wire codec.
//!
//! 1. Round trip: any encodable packet, framed the way the PCI (or a
//!    client) would frame it, decodes back to an identical packet.
//! 2. Robustness: the decoder and frame buffer never panic on arbitrary
//!    input, and their consumed/packet invariants hold.
//! 3. JSON: canonical JSON round-trips (`from_json(to_json(p)) == p`).

use cbus_protocol::cal::Cal;
use cbus_protocol::common::{add_cbus_checksum, cbus_checksum, validate_cbus_checksum};
use cbus_protocol::decode::decode_packet;
use cbus_protocol::json::{packet_from_json, packet_to_json, JsonObject};
use cbus_protocol::packet::{Meta, Packet};
use cbus_protocol::report::StatusReport;
use cbus_protocol::sal::Sal;
use proptest::prelude::*;

/// The exact ramp-rate durations; decode always yields one of these, so
/// round-trip identity needs generated durations drawn from the table.
const RAMP_DURATIONS: [u32; 16] = [
    0, 4, 8, 12, 20, 30, 40, 60, 90, 120, 180, 300, 420, 600, 900, 1020,
];

fn lighting_sal(app: u8) -> impl Strategy<Value = Sal> {
    prop_oneof![
        any::<u8>().prop_map(move |ga| Sal::LightingOn {
            application: app,
            group_address: ga
        }),
        any::<u8>().prop_map(move |ga| Sal::LightingOff {
            application: app,
            group_address: ga
        }),
        any::<u8>().prop_map(move |ga| Sal::LightingTerminateRamp {
            application: app,
            group_address: ga
        }),
        (0usize..16, any::<u8>(), any::<u8>()).prop_map(move |(di, ga, level)| {
            Sal::LightingRamp {
                application: app,
                group_address: ga,
                duration: RAMP_DURATIONS[di],
                level,
            }
        }),
    ]
}

fn clock_sal() -> impl Strategy<Value = Sal> {
    prop_oneof![
        Just(Sal::ClockRequest),
        (0u8..24, 0u8..60, 0u8..60).prop_map(|(hour, minute, second)| Sal::ClockUpdateTime {
            hour,
            minute,
            second
        }),
        // day capped at 28 so every generated (y, m, d) is a valid date
        (1u16..=9999, 1u8..=12, 1u8..=28).prop_map(|(year, month, day)| Sal::ClockUpdateDate {
            year,
            month,
            day
        }),
    ]
}

fn temperature_sal() -> impl Strategy<Value = Sal> {
    // temperatures are exact quarters (byte / 4.0)
    (any::<u8>(), any::<u8>()).prop_map(|(ga, quarters)| Sal::TemperatureBroadcast {
        group_address: ga,
        temperature: quarters as f64 / 4.0,
    })
}

fn enable_sal() -> impl Strategy<Value = Sal> {
    (any::<u8>(), any::<u8>())
        .prop_map(|(variable, value)| Sal::EnableSetNetworkVariable { variable, value })
}

fn status_request_sal() -> impl Strategy<Value = Sal> {
    // block start must be a multiple of 0x20 (encode masks with 0xE0)
    (any::<bool>(), 0u8..8, any::<u8>()).prop_map(|(level_request, block, app)| {
        Sal::StatusRequest {
            level_request,
            group_address: block * 0x20,
            child_application: app,
        }
    })
}

/// A PM packet whose SALs all belong to the packet's application.
fn arb_pm(priority: u8) -> impl Strategy<Value = Packet> {
    prop_oneof![
        (0x30u8..=0x5f).prop_flat_map(move |app| {
            proptest::collection::vec(lighting_sal(app), 1..5).prop_map(move |sals| {
                Packet::PointToMultipoint {
                    meta: Meta::new(true, priority),
                    application: app,
                    sals,
                }
            })
        }),
        proptest::collection::vec(clock_sal(), 1..4).prop_map(move |sals| {
            Packet::PointToMultipoint {
                meta: Meta::new(true, priority),
                application: 0xdf,
                sals,
            }
        }),
        proptest::collection::vec(temperature_sal(), 1..4).prop_map(move |sals| {
            Packet::PointToMultipoint {
                meta: Meta::new(true, priority),
                application: 0x19,
                sals,
            }
        }),
        proptest::collection::vec(enable_sal(), 1..4).prop_map(move |sals| {
            Packet::PointToMultipoint {
                meta: Meta::new(true, priority),
                application: 0xcb,
                sals,
            }
        }),
        proptest::collection::vec(status_request_sal(), 1..4).prop_map(move |sals| {
            Packet::PointToMultipoint {
                meta: Meta::new(true, priority),
                application: 0xff,
                sals,
            }
        }),
    ]
}

fn arb_report() -> impl Strategy<Value = StatusReport> {
    prop_oneof![
        // multiple-of-4 state count so encode's padding is a no-op
        proptest::collection::vec(0u8..4, 0..6).prop_map(|mut states| {
            let pad = (4 - states.len() % 4) % 4;
            states.extend(std::iter::repeat_n(0, pad));
            StatusReport::Binary(states)
        }),
        proptest::collection::vec(proptest::option::of(any::<u8>()), 0..=14)
            .prop_map(StatusReport::Level),
    ]
}

fn arb_cal() -> impl Strategy<Value = Cal> {
    prop_oneof![
        any::<u8>().prop_map(|attribute| Cal::Identify { attribute }),
        (any::<u8>(), any::<u8>()).prop_map(|(param, count)| Cal::Recall { param, count }),
        (
            any::<u8>(),
            proptest::collection::vec(any::<u8>(), 0..=0x1e)
        )
            .prop_map(|(parameter, data)| Cal::Reply { parameter, data }),
        (any::<bool>(), any::<u8>(), any::<u8>(), arb_report()).prop_map(
            |(externally_initiated, child_application, block_start, report)| Cal::ExtendedStatus {
                externally_initiated,
                child_application,
                block_start,
                report,
            }
        ),
    ]
}

fn arb_pp(priority: u8) -> impl Strategy<Value = Packet> {
    (any::<u8>(), proptest::collection::vec(arb_cal(), 1..4)).prop_map(move |(unit, cals)| {
        Packet::PointToPoint {
            meta: Meta::new(true, priority),
            unit_address: unit,
            bridged: false,
            hops: vec![],
            cals,
        }
    })
}

fn arb_dm(priority: u8) -> impl Strategy<Value = Packet> {
    (any::<u8>(), any::<u8>()).prop_map(move |(parameter, value)| Packet::DeviceManagement {
        meta: Meta::new(true, priority),
        parameter,
        value,
    })
}

fn arb_packet() -> impl Strategy<Value = Packet> {
    (0u8..4).prop_flat_map(|prio| prop_oneof![arb_pm(prio), arb_pp(prio), arb_dm(prio)])
}

proptest! {
    /// Client framing: `\<body><CR>` must decode back to the same packet.
    #[test]
    fn roundtrip_client_frame(p in arb_packet()) {
        let body = p.encode_packet().expect("encodable");
        let mut wire = vec![b'\\'];
        wire.extend_from_slice(&body);
        wire.push(b'\r');
        let (decoded, consumed) = decode_packet(&wire, true, true, false);
        prop_assert_eq!(consumed, wire.len());
        prop_assert_eq!(
            packet_to_json(decoded.as_ref()),
            packet_to_json(Some(&p)),
            "wire: {}", String::from_utf8_lossy(&wire)
        );
    }

    /// PCI framing: `<body><CR><LF>` with a source address byte must decode
    /// back to the same packet (source addresses 0 decode as null — excluded).
    #[test]
    fn roundtrip_pci_frame(p in arb_packet(), source in 1u8..=255) {
        let mut p = p;
        p.meta_mut().unwrap().source_address = Some(source);
        let body = p.encode_packet().expect("encodable");
        let mut wire = body;
        wire.extend_from_slice(b"\r\n");
        let (decoded, consumed) = decode_packet(&wire, true, true, true);
        prop_assert_eq!(consumed, wire.len());
        prop_assert_eq!(
            packet_to_json(decoded.as_ref()),
            packet_to_json(Some(&p)),
            "wire: {}", String::from_utf8_lossy(&wire)
        );
    }

    /// Canonical JSON round trip for every encodable packet.
    #[test]
    fn roundtrip_json(p in arb_packet()) {
        let v = packet_to_json(Some(&p));
        match packet_from_json(&v) {
            Ok(JsonObject::Packet(q)) => prop_assert_eq!(p, q),
            other => prop_assert!(false, "unexpected from_json result: {:?}", other),
        }
    }

    /// The decoder must never panic, and `consumed == 0` always means
    /// "no packet, wait for more data".
    #[test]
    fn decode_never_panics(
        data in proptest::collection::vec(any::<u8>(), 0..300),
        checksum: bool,
        strict: bool,
        from_pci: bool,
    ) {
        let (p, consumed) = decode_packet(&data, checksum, strict, from_pci);
        if consumed == 0 {
            prop_assert!(p.is_none());
        }
    }

    /// Checksum: appending the checksum always validates, and the byte sum
    /// of the checksummed frame is 0 mod 256.
    #[test]
    fn checksum_properties(data in proptest::collection::vec(any::<u8>(), 0..64)) {
        let full = add_cbus_checksum(&data);
        prop_assert!(validate_cbus_checksum(&full));
        let sum: u32 = full.iter().map(|&b| b as u32).sum();
        if !data.is_empty() {
            prop_assert_eq!(sum % 256, 0);
        }
        prop_assert_eq!(*full.last().unwrap(), cbus_checksum(&data));
    }
}
