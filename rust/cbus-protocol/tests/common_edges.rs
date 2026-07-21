//! Edges of the shared helpers: bridge length table, ramp snapping
//! extremes, checksum validation corner cases and manchester nibble
//! validity per position.

use cbus_protocol::common::{
    bridge_length, duration_to_ramp_rate, validate_cbus_checksum, CONFIRMATION_CODES,
};
use cbus_protocol::report::{manchester_decode, StatusReport};

#[test]
fn bridge_length_full_table() {
    assert_eq!(bridge_length(0x09), Some(0));
    assert_eq!(bridge_length(0x12), Some(1));
    assert_eq!(bridge_length(0x1b), Some(2));
    assert_eq!(bridge_length(0x24), Some(3));
    assert_eq!(bridge_length(0x2d), Some(4));
    assert_eq!(bridge_length(0x36), Some(5));
}

#[test]
fn bridge_length_rejects_off_by_one_codes() {
    for code in [0x00u8, 0x08, 0x0a, 0x11, 0x13, 0x35, 0x37, 0xff] {
        assert_eq!(bridge_length(code), None, "code {code:#04x}");
    }
}

#[test]
fn ramp_snap_negative_duration_is_instant() {
    assert_eq!(duration_to_ramp_rate(-1), 0x02);
    assert_eq!(duration_to_ramp_rate(i64::MIN), 0x02);
}

#[test]
fn ramp_snap_beyond_table_is_slowest() {
    assert_eq!(duration_to_ramp_rate(1021), 0x7a);
    assert_eq!(duration_to_ramp_rate(1_000_000), 0x7a);
    assert_eq!(duration_to_ramp_rate(i64::MAX), 0x7a);
}

#[test]
fn ramp_snap_exact_boundaries_keep_their_code() {
    // exact table durations snap to themselves, one more moves up
    assert_eq!(duration_to_ramp_rate(60), 0x3a);
    assert_eq!(duration_to_ramp_rate(61), 0x42);
    assert_eq!(duration_to_ramp_rate(900), 0x72);
    assert_eq!(duration_to_ramp_rate(901), 0x7a);
}

#[test]
fn validate_checksum_empty_is_false() {
    assert!(!validate_cbus_checksum(&[]));
}

#[test]
fn validate_checksum_single_zero_byte_is_true() {
    // checksum of the empty prefix is 0, so [0] "validates" — the quirk
    // behind the checksum-only-body Invalid packet
    assert!(validate_cbus_checksum(&[0]));
    assert!(!validate_cbus_checksum(&[1]));
}

#[test]
fn confirmation_pool_order_and_size() {
    // allocation order matters: 'h' first, 'g' last, 20 codes total
    assert_eq!(CONFIRMATION_CODES.len(), 20);
    assert_eq!(CONFIRMATION_CODES[0], b'h');
    assert_eq!(CONFIRMATION_CODES[19], b'g');
    let mut sorted = CONFIRMATION_CODES.to_vec();
    sorted.sort_unstable();
    sorted.dedup();
    assert_eq!(sorted.len(), 20, "codes must be distinct");
}

#[test]
fn manchester_invalid_nibble_in_each_position() {
    // 0x0 and 0xF are invalid manchester nibbles; poisoning any of the
    // four positions must yield None
    assert_eq!(manchester_decode(&[0xa0, 0xaa]), None); // low nibble b0
    assert_eq!(manchester_decode(&[0x0a, 0xaa]), None); // high nibble b0
    assert_eq!(manchester_decode(&[0xaa, 0xaf]), None); // low nibble b1
    assert_eq!(manchester_decode(&[0xaa, 0xfa]), None); // high nibble b1
}

#[test]
fn binary_report_decode_empty_is_empty() {
    assert_eq!(
        StatusReport::decode_binary(&[]),
        StatusReport::Binary(vec![])
    );
}

#[test]
fn level_report_decode_empty_is_empty() {
    assert_eq!(
        StatusReport::decode_level(&[]).unwrap(),
        StatusReport::Level(vec![])
    );
}

#[test]
fn binary_report_unpacks_lsb_first() {
    // 0b01_10_00_11: states [3, 0, 2, 1] reading two bits LSB-first
    let r = StatusReport::decode_binary(&[0b01_10_00_11]);
    assert_eq!(r, StatusReport::Binary(vec![3, 0, 2, 1]));
}
