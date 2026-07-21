//! Condition polling instead of fixed sleeps (keeps the system tests
//! non-flaky: a passing condition returns immediately, a failing one is
//! only declared after the full deadline).

use std::time::{Duration, Instant};

/// Poll `cond` every 20 ms until it returns true or `timeout` elapses.
/// Returns whether the condition became true.
pub async fn wait_until(timeout: Duration, mut cond: impl FnMut() -> bool) -> bool {
    let deadline = Instant::now() + timeout;
    loop {
        if cond() {
            return true;
        }
        if Instant::now() >= deadline {
            return false;
        }
        tokio::time::sleep(Duration::from_millis(20)).await;
    }
}

/// Like [`wait_until`] but panics with `what` on timeout — the standard
/// way system tests assert "this must eventually happen".
pub async fn require(timeout: Duration, what: &str, cond: impl FnMut() -> bool) {
    if !wait_until(timeout, cond).await {
        panic!("timed out after {timeout:?} waiting for: {what}");
    }
}
