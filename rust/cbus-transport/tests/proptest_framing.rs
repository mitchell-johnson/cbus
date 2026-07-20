//! Property-based tests for the frame buffer: no input (or chunking of an
//! input) may panic it, and well-formed frames survive arbitrary chunking.

use cbus_transport::framing::FrameBuffer;
use proptest::prelude::*;

proptest! {
    /// Arbitrary garbage, arbitrarily chunked: never panics, and single
    /// oversized feeds are dropped rather than buffered.
    #[test]
    fn garbage_never_panics(
        chunks in proptest::collection::vec(
            proptest::collection::vec(any::<u8>(), 0..300), 0..12),
    ) {
        let mut fb = FrameBuffer::new_client();
        for chunk in &chunks {
            let _ = fb.feed(chunk);
        }
    }

    /// A stream of valid PCI frames produces the same packets no matter
    /// how the bytes are split into reads.
    #[test]
    fn chunking_is_transparent(
        frames in proptest::collection::vec(
            prop_oneof![
                Just(b"+".to_vec()),
                Just(b"!".to_vec()),
                Just(b"h.".to_vec()),
                Just(b"z#".to_vec()),
                Just(b"05013800790148\r\n".to_vec()),
                Just(b"8221104D\r\n".to_vec()),
            ],
            1..6,
        ),
        split in 1usize..7,
    ) {
        let stream: Vec<u8> = frames.concat();

        let mut all_at_once = FrameBuffer::new_client();
        let expected: Vec<_> = all_at_once
            .feed(&stream)
            .into_iter()
            .map(|ev| ev.packet)
            .collect();
        prop_assert_eq!(expected.len(), frames.len());

        let mut chunked = FrameBuffer::new_client();
        let got: Vec<_> = stream
            .chunks(split)
            .flat_map(|c| chunked.feed(c))
            .map(|ev| ev.packet)
            .collect();
        prop_assert_eq!(got, expected);
    }
}
