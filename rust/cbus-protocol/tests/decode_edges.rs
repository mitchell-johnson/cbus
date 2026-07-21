//! Decoder error paths and Python-parity quirks the golden vectors do not
//! individually reach: framing waits, strict/lenient checksum and
//! confirmation handling, malformed CAL/SAL streams, bridged packets and
//! the quirky bare-CAL consumed accounting.

use cbus_protocol::cal::Cal;
use cbus_protocol::common::add_cbus_checksum;
use cbus_protocol::decode::decode_packet;
use cbus_protocol::packet::{Meta, Packet};
use cbus_protocol::sal::Sal;

/// Body bytes -> the from-PCI wire form: checksummed, uppercase hex, CRLF.
fn pci_wire(body: &[u8]) -> Vec<u8> {
    let mut w = hex::encode_upper(add_cbus_checksum(body)).into_bytes();
    w.extend_from_slice(b"\r\n");
    w
}

fn decode_pci(wire: &[u8]) -> (Option<Packet>, usize) {
    decode_packet(wire, true, true, true)
}

// ------------------------------------------------------- incomplete input

#[test]
fn single_nonspecial_byte_waits_for_more() {
    assert_eq!(decode_pci(b"0"), (None, 0));
}

#[test]
fn hex_without_crlf_waits_for_more() {
    assert_eq!(decode_pci(b"05013800790148"), (None, 0));
}

#[test]
fn from_pci_needs_crlf_not_bare_cr() {
    // a lone CR is not a PCI terminator; the decoder keeps waiting
    assert_eq!(decode_pci(b"05013800790148\r"), (None, 0));
}

#[test]
fn empty_line_consumed_without_packet() {
    assert_eq!(decode_pci(b"\r\nrest"), (None, 2));
}

// ------------------------------------------------- malformed frame bodies

#[test]
fn lowercase_hex_is_invalid() {
    // the decoder accepts UPPERCASE base16 only
    assert_eq!(decode_pci(b"ab\r\n"), (Some(Packet::Invalid), 4));
}

#[test]
fn non_hex_character_is_invalid() {
    assert_eq!(decode_pci(b"0G\r\n"), (Some(Packet::Invalid), 4));
}

#[test]
fn odd_length_body_is_invalid() {
    assert_eq!(decode_pci(b"051\r\n"), (Some(Packet::Invalid), 5));
}

#[test]
fn bad_checksum_strict_is_invalid() {
    // last byte 0x00 is not the checksum of 050138007901
    assert_eq!(
        decode_pci(b"05013800790100\r\n"),
        (Some(Packet::Invalid), 16)
    );
}

#[test]
fn bad_checksum_lenient_still_decodes() {
    let (p, consumed) = decode_packet(b"05013800790100\r\n", true, false, true);
    assert_eq!(consumed, 16);
    match p {
        Some(Packet::PointToMultipoint { sals, .. }) => {
            assert_eq!(
                sals,
                vec![Sal::LightingOn {
                    application: 0x38,
                    group_address: 1
                }]
            );
        }
        other => panic!("expected PM packet, got {other:?}"),
    }
}

#[test]
fn checksum_only_body_strips_to_nothing_and_is_invalid() {
    // "00" validates as a checksum of the empty prefix, leaving no flags
    // byte (Python raises IndexError -> InvalidPacket)
    assert_eq!(decode_pci(b"00\r\n"), (Some(Packet::Invalid), 4));
}

// --------------------------------------------------------- from-PCI paths

#[test]
fn device_management_from_pci_with_source() {
    let wire = pci_wire(&[0xa3, 0x05, 0x21, 0x00, 0xff]);
    let (p, consumed) = decode_pci(&wire);
    assert_eq!(consumed, wire.len());
    let expected = Packet::DeviceManagement {
        meta: Meta {
            checksum: true,
            priority_class: 2,
            source_address: Some(5),
            confirmation: None,
        },
        parameter: 0x21,
        value: 0xff,
    };
    assert_eq!(p, Some(expected));
}

#[test]
fn device_management_second_byte_must_be_zero() {
    let wire = pci_wire(&[0xa3, 0x05, 0x21, 0x01, 0xff]);
    assert_eq!(decode_pci(&wire), (Some(Packet::Invalid), wire.len()));
}

#[test]
fn device_management_payload_must_be_three_bytes() {
    let wire = pci_wire(&[0xa3, 0x05, 0x21, 0x00, 0xff, 0x00]);
    assert_eq!(decode_pci(&wire), (Some(Packet::Invalid), wire.len()));
}

#[test]
fn pm_routing_data_byte_must_be_zero() {
    let wire = pci_wire(&[0x05, 0x05, 0x38, 0x01, 0x79, 0x01]);
    assert_eq!(decode_pci(&wire), (Some(Packet::Invalid), wire.len()));
}

#[test]
fn pm_unregistered_application_is_invalid() {
    // 0x20 is not a registered application
    let wire = pci_wire(&[0x05, 0x05, 0x20, 0x00, 0x79, 0x01]);
    assert_eq!(decode_pci(&wire), (Some(Packet::Invalid), wire.len()));
}

#[test]
fn ppm_address_type_not_implemented() {
    // address type 0x03 (point-to-point-to-multipoint) without dp
    let wire = pci_wire(&[0x03, 0x05, 0x38, 0x00]);
    assert_eq!(decode_pci(&wire), (Some(Packet::Invalid), wire.len()));
}

#[test]
fn pp_truncated_after_source_is_invalid() {
    let wire = pci_wire(&[0x06, 0x05]);
    assert_eq!(decode_pci(&wire), (Some(Packet::Invalid), wire.len()));
}

#[test]
fn source_zero_stays_none() {
    let wire = pci_wire(&[0x05, 0x00, 0x38, 0x00, 0x79, 0x01]);
    let (p, _) = decode_pci(&wire);
    assert_eq!(p.unwrap().meta().unwrap().source_address, None);
}

#[test]
fn pm_multiple_sals_in_one_frame() {
    let wire = pci_wire(&[0x05, 0x05, 0x38, 0x00, 0x79, 0x01, 0x79, 0x02, 0x01, 0x03]);
    let (p, consumed) = decode_pci(&wire);
    assert_eq!(consumed, wire.len());
    match p.unwrap() {
        Packet::PointToMultipoint { sals, .. } => assert_eq!(
            sals,
            vec![
                Sal::LightingOn {
                    application: 0x38,
                    group_address: 1
                },
                Sal::LightingOn {
                    application: 0x38,
                    group_address: 2
                },
                Sal::LightingOff {
                    application: 0x38,
                    group_address: 3
                },
            ]
        ),
        other => panic!("expected PM packet, got {other:?}"),
    }
}

#[test]
fn lighting_stray_tail_byte_warns_and_stops() {
    // trailing lone 0x79 after a complete SAL: decoded SALs stop there
    let wire = pci_wire(&[0x05, 0x05, 0x38, 0x00, 0x79, 0x01, 0x79]);
    let (p, _) = decode_pci(&wire);
    match p.unwrap() {
        Packet::PointToMultipoint { sals, .. } => assert_eq!(
            sals,
            vec![Sal::LightingOn {
                application: 0x38,
                group_address: 1
            }]
        ),
        other => panic!("expected PM packet, got {other:?}"),
    }
}

#[test]
fn lighting_unknown_command_code_yields_empty_sals() {
    // 0x03 is neither on/off/terminate nor a ramp rate: warn + stop
    let wire = pci_wire(&[0x05, 0x05, 0x38, 0x00, 0x03, 0x01]);
    let (p, _) = decode_pci(&wire);
    match p.unwrap() {
        Packet::PointToMultipoint { sals, .. } => assert_eq!(sals, vec![]),
        other => panic!("expected PM packet, got {other:?}"),
    }
}

#[test]
fn lighting_ramp_missing_level_byte_dropped() {
    // ramp code 0x0A + group but no level byte: SAL dropped
    let wire = pci_wire(&[0x05, 0x05, 0x38, 0x00, 0x0a, 0x01]);
    let (p, _) = decode_pci(&wire);
    match p.unwrap() {
        Packet::PointToMultipoint { sals, .. } => assert_eq!(sals, vec![]),
        other => panic!("expected PM packet, got {other:?}"),
    }
}

// --------------------------------------------------------- bridged frames

#[test]
fn bridged_pp_zero_hops_decodes() {
    let wire = pci_wire(&[0x06, 0x05, 0x0a, 0x09, 0x10, 0x21, 0x02]);
    let (p, consumed) = decode_pci(&wire);
    assert_eq!(consumed, wire.len());
    match p.unwrap() {
        Packet::PointToPoint {
            meta,
            unit_address,
            bridged,
            hops,
            cals,
        } => {
            assert_eq!(meta.source_address, Some(5));
            assert_eq!(unit_address, 0x10);
            assert!(bridged);
            assert_eq!(hops, Vec::<u8>::new());
            assert_eq!(cals, vec![Cal::Identify { attribute: 2 }]);
        }
        other => panic!("expected PP packet, got {other:?}"),
    }
}

#[test]
fn bridged_pp_one_hop_decodes() {
    let wire = pci_wire(&[0x06, 0x05, 0x0a, 0x12, 0x0b, 0x10, 0x21, 0x02]);
    let (p, _) = decode_pci(&wire);
    match p.unwrap() {
        Packet::PointToPoint {
            unit_address,
            bridged,
            hops,
            ..
        } => {
            assert_eq!(unit_address, 0x10);
            assert!(bridged);
            assert_eq!(hops, vec![0x0b]);
        }
        other => panic!("expected PP packet, got {other:?}"),
    }
}

#[test]
fn bad_bridge_length_code_is_invalid() {
    // 0x0A is not one of the 6 bridge length codes
    let wire = pci_wire(&[0x06, 0x05, 0x0a, 0x0a, 0x10, 0x21, 0x02]);
    assert_eq!(decode_pci(&wire), (Some(Packet::Invalid), wire.len()));
}

#[test]
fn bridge_address_zero_is_invalid() {
    let wire = pci_wire(&[0x06, 0x05, 0x00, 0x09, 0x10]);
    assert_eq!(decode_pci(&wire), (Some(Packet::Invalid), wire.len()));
}

#[test]
fn bridged_pp_truncated_hops_is_invalid() {
    // length code 0x24 promises 3 hops but the frame ends early
    let wire = pci_wire(&[0x06, 0x05, 0x0a, 0x24, 0x0b]);
    assert_eq!(decode_pci(&wire), (Some(Packet::Invalid), wire.len()));
}

// ------------------------------------------------------------ CAL streams

#[test]
fn truncated_reply_cal_is_invalid() {
    // 0x89 promises 9 data bytes; only 1 follows
    let wire = pci_wire(&[0x06, 0x05, 0x10, 0x00, 0x89, 0x01]);
    assert_eq!(decode_pci(&wire), (Some(Packet::Invalid), wire.len()));
}

#[test]
fn standard_status_cal_never_supported() {
    let wire = pci_wire(&[0x06, 0x05, 0x10, 0x00, 0xc5, 0x38, 0x00, 0x00, 0x00, 0x00]);
    assert_eq!(decode_pci(&wire), (Some(Packet::Invalid), wire.len()));
}

#[test]
fn unknown_cal_command_is_invalid() {
    let wire = pci_wire(&[0x06, 0x05, 0x10, 0x00, 0x77]);
    assert_eq!(decode_pci(&wire), (Some(Packet::Invalid), wire.len()));
}

#[test]
fn extended_status_bad_block_type_is_invalid() {
    // coding nibble 0x03 is neither binary (0) nor level (7)
    let wire = pci_wire(&[0x06, 0x05, 0x10, 0x00, 0xe4, 0x03, 0x38, 0x00, 0x00]);
    assert_eq!(decode_pci(&wire), (Some(Packet::Invalid), wire.len()));
}

#[test]
fn extended_status_odd_level_payload_is_invalid() {
    // level report payload must be manchester pairs (even byte count)
    let wire = pci_wire(&[0x06, 0x05, 0x10, 0x00, 0xe5, 0x07, 0x38, 0x00, 0xaa]);
    assert_eq!(decode_pci(&wire), (Some(Packet::Invalid), wire.len()));
}

// ------------------------------------------------------ client->PCI paths

#[test]
fn cancel_discards_up_to_question_mark() {
    assert_eq!(decode_packet(b"AB?CD\r", false, true, false), (None, 3));
}

#[test]
fn question_mark_after_cr_is_not_a_cancel() {
    // the '?' belongs to the *next* frame, so this one decodes normally
    let (p, consumed) = decode_packet(b"002102\r?\r", false, true, false);
    assert_eq!(p, Some(Packet::BareCal(Cal::Identify { attribute: 2 })));
    assert_eq!(consumed, 9);
}

#[test]
fn at_prefix_forces_basic_mode_no_checksum() {
    // '@' once-off basic mode: no checksum expected on the body
    let (p, consumed) = decode_packet(b"@A32200FF\r", true, true, false);
    assert_eq!(consumed, 10);
    let expected = Packet::DeviceManagement {
        meta: Meta::new(false, 2),
        parameter: 0x22,
        value: 0xff,
    };
    assert_eq!(p, Some(expected));
}

#[test]
fn bare_cal_consumed_includes_cal_length_quirk() {
    // A bare CAL frame is flags byte (dp clear) + CAL bytes. Python adds
    // the CAL length to the already-final consumed count (packet.py:
    // 246-247): the 7-byte frame reports consumed 9.
    let (p, consumed) = decode_packet(b"002102\r", false, true, false);
    assert_eq!(p, Some(Packet::BareCal(Cal::Identify { attribute: 2 })));
    assert_eq!(consumed, 9);
}

#[test]
fn client_confirmation_char_extracted() {
    let (p, consumed) = decode_packet(b"\\053800790149g\r", true, true, false);
    assert_eq!(consumed, 15);
    let meta = p.as_ref().unwrap().meta().unwrap();
    assert_eq!(meta.confirmation, Some(b'g'));
    assert_eq!(meta.source_address, None);
}

#[test]
fn invalid_confirmation_char_strict_is_invalid() {
    // 'a' is lowercase hex-ish but neither uppercase-hex nor a pool code
    assert_eq!(
        decode_packet(b"\\053800790149a\r", true, true, false),
        (Some(Packet::Invalid), 15)
    );
}

#[test]
fn invalid_confirmation_char_lenient_accepted() {
    let (p, _) = decode_packet(b"\\053800790149a\r", true, false, false);
    assert_eq!(p.unwrap().meta().unwrap().confirmation, Some(b'a'));
}

#[test]
fn empty_client_body_after_backslash_is_invalid() {
    assert_eq!(
        decode_packet(b"\\\r", true, true, false),
        (Some(Packet::Invalid), 2)
    );
}

// ------------------------------------------------- from-PCI confirmations

#[test]
fn any_non_dot_second_byte_is_failure() {
    // only '.' means success; anything else (not just '#') is a failure
    assert_eq!(
        decode_pci(b"hx"),
        (
            Some(Packet::Confirmation {
                code: b'h',
                success: false
            }),
            2
        )
    );
}

#[test]
fn last_pool_code_g_confirms() {
    assert_eq!(
        decode_pci(b"g."),
        (
            Some(Packet::Confirmation {
                code: b'g',
                success: true
            }),
            2
        )
    );
}
