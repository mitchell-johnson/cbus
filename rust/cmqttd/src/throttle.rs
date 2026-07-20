//! Port of `cbus/toolkit/periodic.py`: a single queue (cap 1000) drained at
//! one action per 0.2 s; order preserved; drop + warn when full. Actions run
//! concurrently with the pacing sleep (Python spawns a task per action).

use std::future::Future;
use std::pin::Pin;
use std::time::Duration;
use tokio::sync::mpsc;

pub const THROTTLE_PERIOD: Duration = Duration::from_millis(200);
pub const MAX_QUEUE_SIZE: usize = 1000;

pub type Action = Pin<Box<dyn Future<Output = ()> + Send + 'static>>;

#[derive(Clone)]
pub struct Throttle {
    tx: mpsc::Sender<Action>,
}

impl Throttle {
    pub fn new() -> Throttle {
        let (tx, mut rx) = mpsc::channel::<Action>(MAX_QUEUE_SIZE);
        tokio::spawn(async move {
            while let Some(action) = rx.recv().await {
                tokio::spawn(action);
                tokio::time::sleep(THROTTLE_PERIOD).await;
            }
        });
        Throttle { tx }
    }

    /// Non-blocking enqueue; drops the action with a warning when full.
    pub fn enqueue(&self, action: impl Future<Output = ()> + Send + 'static) {
        if self.tx.try_send(Box::pin(action)).is_err() {
            tracing::warn!("throttle queue full or shutting down, task not added");
        }
    }
}

impl Default for Throttle {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::sync::Arc;

    #[tokio::test]
    async fn preserves_order() {
        let t = Throttle::new();
        let order = Arc::new(std::sync::Mutex::new(Vec::new()));
        for i in 0..4 {
            let o = order.clone();
            t.enqueue(async move {
                o.lock().unwrap().push(i);
            });
        }
        tokio::time::sleep(Duration::from_millis(1000)).await;
        assert_eq!(*order.lock().unwrap(), vec![0, 1, 2, 3]);
    }

    #[tokio::test]
    async fn enqueue_never_blocks_when_full() {
        let t = Throttle::new();
        let start = std::time::Instant::now();
        // way past MAX_QUEUE_SIZE; overflow is dropped with a warning
        for _ in 0..(MAX_QUEUE_SIZE + 200) {
            t.enqueue(async {});
        }
        assert!(
            start.elapsed() < Duration::from_secs(1),
            "enqueue blocked: {:?}",
            start.elapsed()
        );
    }

    #[tokio::test]
    async fn paces_at_200ms() {
        let t = Throttle::new();
        let count = Arc::new(AtomicUsize::new(0));
        for _ in 0..5 {
            let c = count.clone();
            t.enqueue(async move {
                c.fetch_add(1, Ordering::SeqCst);
            });
        }
        tokio::time::sleep(Duration::from_millis(500)).await;
        let n = count.load(Ordering::SeqCst);
        // ~1 per 200ms: expect 2-4 done by 500ms, not all 5
        assert!((2..5).contains(&n), "ran {n} actions in 500ms");
        tokio::time::sleep(Duration::from_millis(700)).await;
        assert_eq!(count.load(Ordering::SeqCst), 5);
    }
}
