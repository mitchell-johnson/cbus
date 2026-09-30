//! Frame-buffer boundary behaviour: the 256-byte overflow rule, the
//! consumed-beyond-buffer quirk (bare CALs), server-mode checksum
//! toggling and raw-byte bookkeeping.

use cbus_protocol::cal::Cal;
use cbus_protocol::packet::Packet;
use cbus_protocol::sal::Sal;
use cbus_transport::framing::FrameBuffer;

#[test]
fn exactly_256_bytes_is_accepted() {
    let mut fb = FrameBuffer::new_client();
    // no terminator: nothing decodes, but nothing is dropped either
    assert!(fb.feed(&[b'0'; 256]).is_empty());
    // ...proved by the next byte overflowing (256 + 1 > 256)
    assert!(fb.feed(b"0").is_empty());
    // after the overflow drop the buffer accepts fresh frames again
    let evs = fb.feed(b"h.");
    assert_eq!(evs.len(), 1);
}

#[test]
fn oversized_incomplete_frame_drops_pending_buffer() {
    let mut fb = FrameBuffer::new_client();
    assert!(fb.feed(b"05").is_empty()); // a partial addressed frame
    assert!(fb.feed(&[b'0'; 257]).is_empty()); // oversized: clears all
                                               // The pending frame is gone: a lone '.' waits for more bytes.
    assert!(fb.feed(b".").is_empty());
    // and a fresh full confirmation still works ('.' + 'i' make a bogus
    // pair, so clear first)
    fb.clear();
    let evs = fb.feed(b"i#");
    assert_eq!(evs.len(), 1);
    assert_eq!(
        evs[0].packet,
        Some(Packet::Confirmation {
            code: b'i',
            success: false
        })
    );
}

#[test]
fn bare_cal_consumed_overshoot_is_clamped_to_buffer() {
    // Decode reports consumed 9 for the 7-byte frame "002102\r" (the
    // quirk); the buffer must clamp the drain and not panic
    let mut fb = FrameBuffer::new_server();
    let evs = fb.feed(b"002102\r");
    assert_eq!(evs.len(), 1);
    assert_eq!(
        evs[0].packet,
        Some(Packet::BareCal(Cal::Identify { attribute: 2 }))
    );
    assert_eq!(evs[0].raw, b"002102\r");
    // buffer is empty again: the next frame parses cleanly ("~" consumes
    // one byte; the trailing CR becomes an empty consume-nothing event)
    let evs = fb.feed(b"~\r");
    let packets: Vec<Packet> = evs.into_iter().filter_map(|e| e.packet).collect();
    assert_eq!(packets, vec![Packet::Reset]);
}

#[test]
fn server_checksum_off_treats_ck_byte_as_payload() {
    // with SRCHK off the trailing 49 parses as SAL junk (warn + stop),
    // still a PM packet with the one leading SAL
    let mut fb = FrameBuffer::new_server();
    let evs = fb.feed(b"\\053800790149g\r");
    assert_eq!(evs.len(), 1);
    match evs[0].packet.as_ref().unwrap() {
        Packet::PointToMultipoint { sals, meta, .. } => {
            assert_eq!(
                sals,
                &vec![Sal::LightingOn {
                    application: 0x38,
                    group_address: 1
                }]
            );
            assert!(!meta.checksum);
            assert_eq!(meta.confirmation, Some(b'g'));
        }
        other => panic!("expected PM packet, got {other:?}"),
    }
}

#[test]
fn server_checksum_on_validates_and_strips() {
    let mut fb = FrameBuffer::new_server();
    fb.set_checksum(true);
    let evs = fb.feed(b"\\053800790149g\r");
    assert_eq!(evs.len(), 1);
    match evs[0].packet.as_ref().unwrap() {
        Packet::PointToMultipoint { sals, meta, .. } => {
            assert_eq!(sals.len(), 1);
            assert!(meta.checksum);
        }
        other => panic!("expected PM packet, got {other:?}"),
    }
    // and a corrupted checksum now decodes as Invalid
    fb.clear();
    let evs = fb.feed(b"\\053800790100g\r");
    assert_eq!(evs[0].packet, Some(Packet::Invalid));
}

#[test]
fn clear_drops_partial_frame() {
    let mut fb = FrameBuffer::new_client();
    assert!(fb.feed(b"0501").is_empty());
    fb.clear();
    // the previously buffered prefix must not corrupt this full frame
    let evs = fb.feed(b"05013800790148\r\n");
    assert_eq!(evs.len(), 1);
    assert!(matches!(
        evs[0].packet,
        Some(Packet::PointToMultipoint { .. })
    ));
}

#[test]
fn raw_bytes_partition_the_stream_exactly() {
    let mut fb = FrameBuffer::new_client();
    let stream = b"h.05013800790148\r\ni#";
    let evs = fb.feed(stream);
    assert_eq!(evs.len(), 3);
    let concat: Vec<u8> = evs.iter().flat_map(|e| e.raw.clone()).collect();
    assert_eq!(concat, stream);
}

#[test]
fn client_init_burst_parses_on_server_side() {
    // the exact byte stream cmqttd emits during pci_reset
    let mut fb = FrameBuffer::new_server();
    let evs = fb.feed(b"~\r~\r~\r|\rA32100FFh\r");
    let packets: Vec<Packet> = evs.into_iter().filter_map(|e| e.packet).collect();
    assert_eq!(packets.len(), 5);
    assert_eq!(packets[0], Packet::Reset);
    assert_eq!(packets[1], Packet::Reset);
    assert_eq!(packets[2], Packet::Reset);
    assert_eq!(packets[3], Packet::SmartConnect);
    match &packets[4] {
        Packet::DeviceManagement {
            meta,
            parameter,
            value,
        } => {
            assert_eq!((*parameter, *value), (0x21, 0xff));
            assert_eq!(meta.confirmation, Some(b'h'));
        }
        other => panic!("expected DM packet, got {other:?}"),
    }
}

#[test]
fn toolkit_null_junk_is_swallowed() {
    let mut fb = FrameBuffer::new_server();
    let evs = fb.feed(b"null~\r");
    let packets: Vec<Packet> = evs.into_iter().filter_map(|e| e.packet).collect();
    assert_eq!(packets, vec![Packet::Reset]);
}

#[test]
fn large_read_preserves_every_complete_frame() {
    let mut fb = FrameBuffer::new_client();
    let stream = b"05013800790148\r\nh.i#".repeat(30);
    let events = fb.feed(&stream);
    assert_eq!(events.len(), 90);
    assert_eq!(
        events
            .iter()
            .flat_map(|event| event.raw.iter().copied())
            .collect::<Vec<_>>(),
        stream
    );
    assert!(events
        .iter()
        .all(|event| !matches!(event.packet, Some(Packet::Invalid))));
}

#[test]
fn pending_frame_near_capacity_survives_coalesced_following_frames() {
    let mut raw = vec![0x05, 0x01, 0x38, 0x00];
    for group in 0..60 {
        raw.extend_from_slice(&[0x79, group]);
    }
    let mut wire = hex::encode_upper(cbus_protocol::common::add_cbus_checksum(&raw)).into_bytes();
    wire.extend_from_slice(b"\r\n");
    assert_eq!(wire.len(), 252);
    let mut fb = FrameBuffer::new_client();
    assert!(fb.feed(&wire[..250]).is_empty());
    let mut remaining = wire[250..].to_vec();
    remaining.extend_from_slice(&b"h.".repeat(10));
    let events = fb.feed(&remaining);
    assert_eq!(events.len(), 11);
    assert_eq!(events[0].raw, wire);
    assert!(
        matches!(&events[0].packet, Some(Packet::PointToMultipoint { sals, .. }) if sals.len() == 60)
    );
}

#[test]
fn bare_cal_accounting_does_not_consume_the_next_frame() {
    let mut fb = FrameBuffer::new_server();
    let events = fb.feed(b"002102\r~\rA32100FFh\r");
    let packets = events
        .iter()
        .filter_map(|event| event.packet.clone())
        .collect::<Vec<_>>();
    assert_eq!(packets.len(), 3);
    assert_eq!(packets[0], Packet::BareCal(Cal::Identify { attribute: 2 }));
    assert_eq!(packets[1], Packet::Reset);
    assert_eq!(events[0].raw, b"002102\r");
    assert!(matches!(packets[2], Packet::DeviceManagement { .. }));
}
