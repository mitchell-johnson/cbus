//! Bounded mock TCP delivery. These are test-double resource policies, not
//! captured native C-Gate overflow statuses. An undeliverable receipt closes
//! the connection; a command may already have changed the shared model.

use std::io;
use std::sync::Arc;
use std::time::Duration;
use tokio::io::{AsyncBufRead, AsyncBufReadExt, AsyncWrite, AsyncWriteExt};
use tokio::sync::{mpsc, watch, OwnedSemaphorePermit, Semaphore};

pub(super) const MAX_BATCHES: usize = 512;
pub(super) const MAX_BYTES: usize = 32 * 1024 * 1024;
const WRITE_DEADLINE: Duration = Duration::from_secs(10);

struct Batch {
    // Discard spare String capacity before retaining the admitted payload.
    // Allocator metadata and queue/permit objects are separate small overhead.
    wire: Box<str>,
    // Include the active write in both budgets, not just channel contents.
    _count: OwnedSemaphorePermit,
    _bytes: OwnedSemaphorePermit,
}

#[derive(Clone)]
pub(super) struct Delivery {
    tx: mpsc::Sender<Batch>,
    count: Arc<Semaphore>,
    bytes: Arc<Semaphore>,
    stop: watch::Sender<Option<&'static str>>,
}

pub(super) struct Receiver {
    rx: mpsc::Receiver<Batch>,
    stop: watch::Receiver<Option<&'static str>>,
    signal: watch::Sender<Option<&'static str>>,
}

pub(super) fn channel() -> (Delivery, Receiver) {
    bounded_channel(MAX_BATCHES, MAX_BYTES)
}

fn bounded_channel(count: usize, bytes: usize) -> (Delivery, Receiver) {
    let (tx, rx) = mpsc::channel(count);
    let (stop, stopped) = watch::channel(None);
    let signal = Delivery {
        tx,
        count: Arc::new(Semaphore::new(count)),
        bytes: Arc::new(Semaphore::new(bytes)),
        stop,
    };
    (
        signal.clone(),
        Receiver {
            rx,
            stop: stopped,
            signal: signal.stop,
        },
    )
}

impl Delivery {
    pub(super) fn is_closed(&self) -> bool {
        self.stop.borrow().is_some() || self.tx.is_closed()
    }

    pub(super) fn subscribe(&self) -> watch::Receiver<Option<&'static str>> {
        self.stop.subscribe()
    }

    pub(super) fn close(&self, reason: &'static str) {
        close(&self.stop, reason);
    }

    /// No waiting here: callers hold the shared Hub model lock. A batch is
    /// admitted entirely or the connection becomes unusable immediately.
    pub(super) fn send(&self, wire: String) -> Result<(), ()> {
        if self.is_closed() {
            return Err(());
        }
        if wire.is_empty() {
            return Ok(());
        }
        let count = self.count.clone().try_acquire_owned().map_err(|_| {
            self.close("outbound batch capacity exceeded");
        })?;
        let size = u32::try_from(wire.len()).map_err(|_| {
            self.close("outbound byte capacity exceeded");
        })?;
        let bytes = self
            .bytes
            .clone()
            .try_acquire_many_owned(size)
            .map_err(|_| {
                self.close("outbound byte capacity exceeded");
            })?;
        self.tx
            .try_send(Batch {
                wire: wire.into_boxed_str(),
                _count: count,
                _bytes: bytes,
            })
            .map_err(|_| {
                self.close("outbound receiver unavailable");
            })
    }
}

impl Receiver {
    pub(super) async fn write_to<W: AsyncWrite + Unpin>(mut self, mut writer: W) {
        loop {
            let batch = tokio::select! {
                biased;
                _ = stopped(&mut self.stop) => break,
                batch = self.rx.recv() => match batch { Some(batch) => batch, None => break },
            };
            let result = tokio::select! {
                biased;
                _ = stopped(&mut self.stop) => break,
                result = tokio::time::timeout(WRITE_DEADLINE, writer.write_all(batch.wire.as_bytes())) => result,
            };
            match result {
                Ok(Ok(())) => {}
                Ok(Err(_)) => {
                    close(&self.signal, "outbound socket write failed");
                    break;
                }
                Err(_) => {
                    close(&self.signal, "outbound socket write timed out");
                    break;
                }
            }
        }
        // Drop writer and queued batches together. Do not wait to send a new
        // status on the same stalled/full socket or invent a success receipt.
    }
}

fn close(signal: &watch::Sender<Option<&'static str>>, reason: &'static str) {
    signal.send_if_modified(|current| {
        if current.is_none() {
            *current = Some(reason);
            true
        } else {
            false
        }
    });
}

pub(super) async fn stopped(stop: &mut watch::Receiver<Option<&'static str>>) {
    loop {
        if stop.borrow().is_some() || stop.changed().await.is_err() {
            return;
        }
    }
}

pub(super) enum InputLine {
    Line(String),
    TooLong,
}

/// Unlike Lines::next_line, retain at most limit+1 bytes while finding a line.
/// Documents drain oversized rows to their delimiter; top-level commands can
/// close immediately. The extra byte permits an ordinary CRLF at the limit.
pub(super) async fn read_line<R: AsyncBufRead + Unpin>(
    reader: &mut R,
    limit: usize,
    drain_overlong: bool,
) -> io::Result<Option<InputLine>> {
    let mut bytes = Vec::new();
    let mut total = 0usize;
    loop {
        let chunk = reader.fill_buf().await?;
        if chunk.is_empty() {
            if total == 0 {
                return Ok(None);
            }
            break;
        }
        let end = chunk.iter().position(|byte| *byte == b'\n');
        let take = end.unwrap_or(chunk.len());
        total = total.saturating_add(take);
        let retain = take.min((limit + 1).saturating_sub(bytes.len()));
        bytes.extend_from_slice(&chunk[..retain]);
        reader.consume(take + usize::from(end.is_some()));
        if total > limit + 1 && !drain_overlong {
            return Ok(Some(InputLine::TooLong));
        }
        if end.is_some() {
            break;
        }
    }
    if total <= limit + 1 && bytes.last() == Some(&b'\r') {
        bytes.pop();
        total -= 1;
    }
    if total > limit {
        return Ok(Some(InputLine::TooLong));
    }
    String::from_utf8(bytes)
        .map(|line| Some(InputLine::Line(line)))
        .map_err(|error| io::Error::new(io::ErrorKind::InvalidData, error))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::pin::Pin;
    use std::sync::atomic::{AtomicBool, Ordering};
    use std::task::{Context, Poll};
    use tokio::io::AsyncReadExt;

    struct PendingWriter {
        entered: Option<tokio::sync::oneshot::Sender<()>>,
        dropped: Arc<AtomicBool>,
    }

    impl AsyncWrite for PendingWriter {
        fn poll_write(
            mut self: Pin<&mut Self>,
            _cx: &mut Context<'_>,
            _bytes: &[u8],
        ) -> Poll<io::Result<usize>> {
            if let Some(entered) = self.entered.take() {
                entered.send(()).unwrap();
            }
            // No bytes can be accepted before cancellation. The handshake
            // proves one batch is already held by write_to, outside the queue.
            Poll::Pending
        }

        fn poll_flush(self: Pin<&mut Self>, _cx: &mut Context<'_>) -> Poll<io::Result<()>> {
            Poll::Ready(Ok(()))
        }

        fn poll_shutdown(self: Pin<&mut Self>, _cx: &mut Context<'_>) -> Poll<io::Result<()>> {
            Poll::Ready(Ok(()))
        }
    }

    impl Drop for PendingWriter {
        fn drop(&mut self) {
            self.dropped.store(true, Ordering::SeqCst);
        }
    }

    #[tokio::test(start_paused = true)]
    async fn actual_count_cap_includes_one_active_write_and_511_queued_batches() {
        let vector: serde_json::Value = serde_json::from_str(include_str!(
            "../../testdata/vectors/cgate_mock_delivery_bounds.json"
        ))
        .unwrap();
        assert_eq!(MAX_BATCHES, 512);
        assert_eq!(
            MAX_BATCHES as u64,
            vector["bounds"]["outbound_batches"].as_u64().unwrap()
        );
        let (tx, rx) = channel();
        let wire = "event\r\n[1] 200 OK.\r\n";
        tx.send(wire.into()).unwrap();
        let (entered, active) = tokio::sync::oneshot::channel();
        let dropped = Arc::new(AtomicBool::new(false));
        let started = tokio::time::Instant::now();
        let pump = tokio::spawn(rx.write_to(PendingWriter {
            entered: Some(entered),
            dropped: dropped.clone(),
        }));
        active.await.unwrap();
        assert_eq!(tx.count.available_permits(), MAX_BATCHES - 1);
        for _ in 1..MAX_BATCHES {
            tx.send(wire.into()).unwrap();
        }
        assert_eq!(tx.count.available_permits(), 0);
        assert_eq!(
            tx.bytes.available_permits(),
            MAX_BYTES - MAX_BATCHES * wire.len()
        );
        assert!(tx.bytes.available_permits() > MAX_BYTES / 2);
        assert!(tx.send("event\r\n[rejected] 200 OK.\r\n".into()).is_err());
        assert_eq!(tx.count.available_permits(), 0);
        assert_eq!(
            tx.bytes.available_permits(),
            MAX_BYTES - MAX_BATCHES * wire.len()
        );
        assert_eq!(
            *tx.stop.borrow(),
            Some(vector["overflow"]["count_reason"].as_str().unwrap())
        );
        pump.await.unwrap();
        assert_eq!(tokio::time::Instant::now(), started);
        assert!(dropped.load(Ordering::SeqCst));
        assert_eq!(tx.count.available_permits(), MAX_BATCHES);
        assert_eq!(tx.bytes.available_permits(), MAX_BYTES);
    }

    #[tokio::test(start_paused = true)]
    async fn actual_byte_cap_includes_active_payload_with_count_capacity_remaining() {
        let vector: serde_json::Value = serde_json::from_str(include_str!(
            "../../testdata/vectors/cgate_mock_delivery_bounds.json"
        ))
        .unwrap();
        assert_eq!(
            MAX_BYTES as u64,
            vector["bounds"]["outbound_wire_bytes"].as_u64().unwrap()
        );
        let (tx, rx) = channel();
        tx.send("A".repeat(MAX_BYTES / 2)).unwrap();
        let (entered, active) = tokio::sync::oneshot::channel();
        let dropped = Arc::new(AtomicBool::new(false));
        let started = tokio::time::Instant::now();
        let pump = tokio::spawn(rx.write_to(PendingWriter {
            entered: Some(entered),
            dropped: dropped.clone(),
        }));
        active.await.unwrap();
        assert_eq!(tx.bytes.available_permits(), MAX_BYTES / 2);
        tx.send("B".repeat(MAX_BYTES / 2)).unwrap();
        assert_eq!(tx.bytes.available_permits(), 0);
        assert_eq!(tx.count.available_permits(), MAX_BATCHES - 2);
        assert!(tx.send("C".into()).is_err());
        assert_eq!(tx.bytes.available_permits(), 0);
        assert_eq!(tx.count.available_permits(), MAX_BATCHES - 2);
        assert_eq!(
            *tx.stop.borrow(),
            Some(vector["overflow"]["byte_reason"].as_str().unwrap())
        );
        pump.await.unwrap();
        assert_eq!(tokio::time::Instant::now(), started);
        assert!(dropped.load(Ordering::SeqCst));
        assert_eq!(tx.count.available_permits(), MAX_BATCHES);
        assert_eq!(tx.bytes.available_permits(), MAX_BYTES);
    }

    #[tokio::test]
    async fn whole_batches_are_ordered_and_count_inflight_bytes() {
        let vector: serde_json::Value = serde_json::from_str(include_str!(
            "../../testdata/vectors/cgate_mock_delivery_bounds.json"
        ))
        .unwrap();
        assert_eq!(
            MAX_BATCHES as u64,
            vector["bounds"]["outbound_batches"].as_u64().unwrap()
        );
        assert_eq!(
            MAX_BYTES as u64,
            vector["bounds"]["outbound_wire_bytes"].as_u64().unwrap()
        );
        assert_eq!(
            WRITE_DEADLINE.as_secs(),
            vector["bounds"]["write_seconds"].as_u64().unwrap()
        );
        let (tx, rx) = bounded_channel(2, 8);
        tx.send("12345".into()).unwrap();
        let (writer, mut reader) = tokio::io::duplex(1);
        let pump = tokio::spawn(rx.write_to(writer));
        tokio::task::yield_now().await;
        assert_eq!(tx.bytes.available_permits(), 3);
        tx.send("678".into()).unwrap();
        assert_eq!(tx.bytes.available_permits(), 0);
        let mut got = [0; 8];
        reader.read_exact(&mut got).await.unwrap();
        assert_eq!(&got, b"12345678");
        tx.close("test complete");
        pump.await.unwrap();
        assert_eq!(tx.bytes.available_permits(), 8);
        assert_eq!(tx.count.available_permits(), 2);
    }

    #[tokio::test]
    async fn count_overflow_cancels_without_partial_batch_or_waiting() {
        let (tx, rx) = bounded_channel(2, 100);
        tx.send("one\r\n".into()).unwrap();
        tx.send("two\r\n".into()).unwrap();
        assert!(tx.send("event\r\n[1] 200 OK.\r\n".into()).is_err());
        assert_eq!(*tx.stop.borrow(), Some("outbound batch capacity exceeded"));
        assert!(tx.send("later".into()).is_err());
        let (writer, mut reader) = tokio::io::duplex(100);
        rx.write_to(writer).await;
        let mut bytes = Vec::new();
        reader.read_to_end(&mut bytes).await.unwrap();
        assert!(
            bytes.is_empty(),
            "closed queue never reports queued successes"
        );
    }

    #[tokio::test]
    async fn byte_overflow_and_oversized_single_response_cancel_atomically() {
        for wires in [vec!["1234", "56789"], vec!["123456789"]] {
            let (tx, rx) = bounded_channel(10, 8);
            for wire in wires.iter().take(wires.len() - 1) {
                tx.send((*wire).into()).unwrap();
            }
            assert!(tx.send(wires.last().unwrap().to_string()).is_err());
            assert_eq!(*tx.stop.borrow(), Some("outbound byte capacity exceeded"));
            drop(rx);
            assert_eq!(tx.bytes.available_permits(), 8);
        }
    }

    #[tokio::test]
    async fn inflated_string_capacity_is_not_retained_outside_byte_budget() {
        let (tx, mut rx) = bounded_channel(2, 8);
        let mut wire = String::with_capacity(1024 * 1024);
        wire.push_str("short");
        assert!(wire.capacity() > 8);
        tx.send(wire).unwrap();
        let batch = rx.rx.try_recv().unwrap();
        let payload: &str = batch.wire.as_ref();
        assert_eq!(
            payload.len(),
            5,
            "boxed slice retains no spare String capacity"
        );
        assert_eq!(std::mem::size_of_val(payload), 5);
        assert_eq!(tx.bytes.available_permits(), 3);
        drop(batch);
        assert_eq!(tx.bytes.available_permits(), 8);
    }

    #[tokio::test(start_paused = true)]
    async fn stalled_write_has_finite_deadline_and_releases_every_permit() {
        let (tx, rx) = bounded_channel(2, 8);
        tx.send("12345678".into()).unwrap();
        let (writer, _reader) = tokio::io::duplex(1);
        rx.write_to(writer).await;
        assert_eq!(*tx.stop.borrow(), Some("outbound socket write timed out"));
        assert_eq!(tx.count.available_permits(), 2);
        assert_eq!(tx.bytes.available_permits(), 8);
    }

    #[tokio::test]
    async fn bounded_input_preserves_crlf_utf8_eof_and_document_resynchronization() {
        let mut reader = &b"abc\r\n\xc3\xa9\nlongline\nEND\nlast"[..];
        for expected in ["abc", "é"] {
            let Some(InputLine::Line(actual)) = read_line(&mut reader, 3, false).await.unwrap()
            else {
                panic!("line");
            };
            assert_eq!(actual, expected);
        }
        assert!(matches!(
            read_line(&mut reader, 3, true).await.unwrap(),
            Some(InputLine::TooLong)
        ));
        let Some(InputLine::Line(end)) = read_line(&mut reader, 3, true).await.unwrap() else {
            panic!("delimiter");
        };
        assert_eq!(end, "END");
        assert!(matches!(
            read_line(&mut reader, 3, false).await.unwrap(),
            Some(InputLine::TooLong)
        ));
        assert!(read_line(&mut reader, 3, false).await.unwrap().is_none());
        assert!(read_line(&mut &b"\xff\n"[..], 3, false).await.is_err());
    }

    #[tokio::test]
    async fn normal_sender_drop_drains_terminal_then_closes_writer() {
        let (tx, rx) = bounded_channel(2, 100);
        tx.send("event\r\n[1] 200 OK.\r\n".into()).unwrap();
        drop(tx);
        let (writer, mut reader) = tokio::io::duplex(100);
        rx.write_to(writer).await;
        let mut wire = String::new();
        reader.read_to_string(&mut wire).await.unwrap();
        assert_eq!(wire, "event\r\n[1] 200 OK.\r\n");
    }
}
