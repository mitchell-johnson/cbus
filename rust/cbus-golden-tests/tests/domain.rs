//! Generated exhaustive-domain enumeration tests (see build.rs). Expected
//! values are literals computed by the build script with independent
//! mini-implementations of the checksum, manchester coding and topic
//! formats, so they act as a second oracle against the production code.

use cbus_mqtt::discovery::light_discovery;
use cbus_mqtt::topics::{set_topic, state_topic, topic_group_address};
use cbus_protocol::common::{cbus_checksum, ramp_rate_to_duration, validate_cbus_checksum};
use cbus_protocol::decode::decode_packet;
use cbus_protocol::packet::{Meta, Packet};
use cbus_protocol::report::{manchester_decode, manchester_encode};
use cbus_protocol::sal::{decode_sals, Sal};
use cbus_transport::framing::FrameBuffer;

/// Feed `wire` once whole and once split at `at`; the decoded packets and
/// consumed raw bytes must be identical. The whole-feed result must not be
/// empty (guards against a vacuously passing split).
fn assert_split_transparent(wire: &[u8], at: usize, server_side: bool) {
    fn collect(fb: &mut FrameBuffer, chunks: &[&[u8]]) -> (Vec<Option<Packet>>, Vec<Vec<u8>>) {
        let mut packets = Vec::new();
        let mut raws = Vec::new();
        for c in chunks {
            for ev in fb.feed(c) {
                packets.push(ev.packet);
                raws.push(ev.raw);
            }
        }
        (packets, raws)
    }
    let new = || {
        if server_side {
            FrameBuffer::new_server()
        } else {
            FrameBuffer::new_client()
        }
    };
    let (whole_packets, whole_raws) = collect(&mut new(), &[wire]);
    assert!(
        !whole_packets.is_empty(),
        "reference stream produced no frames at all"
    );
    let (split_packets, split_raws) = collect(&mut new(), &[&wire[..at], &wire[at..]]);
    assert_eq!(whole_packets, split_packets, "packets differ split at {at}");
    assert_eq!(whole_raws, split_raws, "raw frames differ split at {at}");
}

include!(concat!(env!("OUT_DIR"), "/domain_generated.rs"));
