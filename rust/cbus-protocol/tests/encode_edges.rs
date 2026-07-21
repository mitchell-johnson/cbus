//! Encoder error paths and boundary behaviour the vectors do not
//! individually pin: unencodable packets, value clamping/truncation and
//! flag-byte construction for every priority class.

use cbus_protocol::cal::Cal;
use cbus_protocol::packet::{Meta, Packet};
use cbus_protocol::report::StatusReport;
use cbus_protocol::sal::Sal;

fn pm(priority_class: u8, sals: Vec<Sal>) -> Packet {
    Packet::PointToMultipoint {
        meta: Meta::new(true, priority_class),
        application: 0x38,
        sals,
    }
}

fn on(group_address: u8) -> Sal {
    Sal::LightingOn {
        application: 0x38,
        group_address,
    }
}

#[test]
fn invalid_packet_cannot_encode() {
    assert!(Packet::Invalid.encode().is_err());
    assert!(Packet::Invalid.encode_packet().is_err());
}

#[test]
fn bare_cal_has_no_encode_packet() {
    let p = Packet::BareCal(Cal::Identify { attribute: 1 });
    assert_eq!(p.encode().unwrap(), vec![0x21, 0x01]);
    assert!(p.encode_packet().is_err());
}

#[test]
fn bridged_pp_cannot_encode() {
    let p = Packet::PointToPoint {
        meta: Meta::new(true, 0),
        unit_address: 0x10,
        bridged: true,
        hops: vec![0x0b],
        cals: vec![Cal::Identify { attribute: 1 }],
    };
    assert!(p.encode().is_err());
}

#[test]
fn priority_class_sets_top_flag_bits() {
    // PM flags: 0x05 | (priority << 6)
    for (pc, first_two) in [(0u8, "05"), (1, "45"), (2, "85"), (3, "C5")] {
        let enc = pm(pc, vec![on(1)]).encode_packet().unwrap();
        assert_eq!(
            &enc[..2],
            first_two.as_bytes(),
            "priority class {pc} flags byte"
        );
    }
}

#[test]
fn source_address_in_meta_is_emitted_after_flags() {
    let mut meta = Meta::new(true, 0);
    meta.source_address = Some(0x0b);
    let p = Packet::PointToMultipoint {
        meta,
        application: 0x38,
        sals: vec![on(1)],
    };
    // flags, then source byte 0B, then app
    assert!(p.encode_packet().unwrap().starts_with(b"050B3800"));
}

// ------------------------------------------------------------ temperature

#[test]
fn temperature_below_zero_rejected() {
    let s = Sal::TemperatureBroadcast {
        group_address: 1,
        temperature: -0.1,
    };
    assert!(s.encode().is_err());
}

#[test]
fn temperature_above_63_75_rejected() {
    let s = Sal::TemperatureBroadcast {
        group_address: 1,
        temperature: 63.76,
    };
    assert!(s.encode().is_err());
}

#[test]
fn temperature_63_75_is_byte_255() {
    let s = Sal::TemperatureBroadcast {
        group_address: 1,
        temperature: 63.75,
    };
    assert_eq!(s.encode().unwrap(), vec![0x02, 1, 255]);
}

#[test]
fn temperature_truncates_toward_zero() {
    // int(25.9 * 4) == int(103.6) == 103, like Python
    let s = Sal::TemperatureBroadcast {
        group_address: 1,
        temperature: 25.9,
    };
    assert_eq!(s.encode().unwrap(), vec![0x02, 1, 103]);
}

// ------------------------------------------------------------------ clock

#[test]
fn invalid_calendar_date_rejected() {
    let s = Sal::ClockUpdateDate {
        year: 2026,
        month: 2,
        day: 30,
    };
    assert!(s.encode().is_err());
}

#[test]
fn leap_day_encodes() {
    let s = Sal::ClockUpdateDate {
        year: 2024,
        month: 2,
        day: 29,
    };
    // 2024-02-29 is a Thursday: weekday byte 3 (Monday = 0)
    assert_eq!(s.encode().unwrap(), vec![0x0e, 0x02, 0x07, 0xe8, 2, 29, 3]);
}

#[test]
fn monday_is_weekday_zero() {
    let s = Sal::ClockUpdateDate {
        year: 2026,
        month: 7,
        day: 20,
    };
    assert_eq!(*s.encode().unwrap().last().unwrap(), 0);
}

#[test]
fn clock_time_dst_byte_always_ff() {
    let s = Sal::ClockUpdateTime {
        hour: 23,
        minute: 59,
        second: 58,
    };
    assert_eq!(s.encode().unwrap(), vec![0x0d, 0x01, 23, 59, 58, 0xff]);
}

// --------------------------------------------------------- status request

#[test]
fn status_request_masks_group_to_block_start() {
    // 0x21 is not a block boundary; encode masks with 0xE0 -> 0x20
    let s = Sal::StatusRequest {
        level_request: true,
        group_address: 0x21,
        child_application: 0x38,
    };
    assert_eq!(s.encode().unwrap(), vec![0x73, 0x07, 0x38, 0x20]);
}

#[test]
fn binary_status_request_short_form() {
    let s = Sal::StatusRequest {
        level_request: false,
        group_address: 0x40,
        child_application: 0x30,
    };
    assert_eq!(s.encode().unwrap(), vec![0x7a, 0x30, 0x40]);
}

// -------------------------------------------------------------- reply CAL

#[test]
fn reply_data_clipped_at_exactly_0x1e_bytes() {
    let c = Cal::Reply {
        parameter: 1,
        data: vec![0xaa; 0x1e],
    };
    let enc = c.encode();
    assert_eq!(enc.len(), 2 + 0x1e);
    assert_eq!(enc[0], 0x80 | 0x1f);
    // one byte more is silently clipped to the same wire form
    let c2 = Cal::Reply {
        parameter: 1,
        data: vec![0xaa; 0x1f],
    };
    assert_eq!(c2.encode(), enc);
}

// ----------------------------------------------------------- reports

#[test]
fn binary_report_pads_partial_byte_with_missing() {
    // 6 states -> 2 bytes, the tail padded with MISSING (0)
    let r = StatusReport::Binary(vec![1, 2, 1, 2, 1, 2]);
    assert_eq!(r.encode(), vec![0b10_01_10_01, 0b00_00_10_01]);
}

#[test]
fn empty_binary_report_encodes_empty() {
    assert_eq!(StatusReport::Binary(vec![]).encode(), Vec::<u8>::new());
}

#[test]
fn level_report_none_encodes_zero_pair() {
    let r = StatusReport::Level(vec![None, Some(255)]);
    assert_eq!(r.encode(), vec![0x00, 0x00, 0x55, 0x55]);
}

#[test]
fn pm_empty_sals_encodes_header_only() {
    // no SALs: just flags, app, 00 and the checksum
    let enc = pm(0, vec![]).encode_packet().unwrap();
    assert_eq!(enc, b"053800C3");
}

#[test]
fn pp_multiple_cals_concatenate() {
    let p = Packet::PointToPoint {
        meta: Meta::new(true, 0),
        unit_address: 0x10,
        bridged: false,
        hops: vec![],
        cals: vec![
            Cal::Identify { attribute: 1 },
            Cal::Recall {
                param: 0xfa,
                count: 4,
            },
        ],
    };
    // 06 10 00 | 21 01 | 1A FA 04 | ck
    let enc = p.encode().unwrap();
    assert_eq!(enc[..8], [0x06, 0x10, 0x00, 0x21, 0x01, 0x1a, 0xfa, 0x04]);
    assert_eq!(enc.len(), 9);
}
