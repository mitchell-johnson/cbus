//! Spawning and supervising the real workspace binaries under test.
//! The binary path comes from the calling test crate's
//! `env!("CARGO_BIN_EXE_<name>")` (only defined there, not here).

use std::path::PathBuf;
use std::process::{Child, Command, ExitStatus, Stdio};
use std::sync::atomic::{AtomicUsize, Ordering};
use std::time::{Duration, Instant};

static UNIQUE: AtomicUsize = AtomicUsize::new(0);

/// A unique scratch path for one test (under the system temp dir).
pub fn temp_path(tag: &str) -> PathBuf {
    let n = UNIQUE.fetch_add(1, Ordering::Relaxed);
    std::env::temp_dir().join(format!("cbus-test-{}-{n}-{tag}", std::process::id()))
}

/// A spawned binary under test; killed on drop. stderr is captured to a
/// file so tests can assert on log output after (or while) it runs.
pub struct Daemon {
    child: Child,
    stderr_path: PathBuf,
}

impl Daemon {
    /// Spawn `bin` with `args`; stderr goes to a capture file, stdout is
    /// discarded, stdin is null.
    pub fn spawn(bin: &str, args: &[&str]) -> Daemon {
        let stderr_path = temp_path("stderr.log");
        let stderr = std::fs::File::create(&stderr_path).expect("create stderr capture");
        let child = Command::new(bin)
            .args(args)
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(stderr)
            .spawn()
            .unwrap_or_else(|e| panic!("cannot spawn {bin}: {e}"));
        Daemon { child, stderr_path }
    }

    /// The OS process id.
    pub fn pid(&self) -> u32 {
        self.child.id()
    }

    /// Whether the process is still running.
    pub fn is_running(&mut self) -> bool {
        matches!(self.child.try_wait(), Ok(None))
    }

    /// Exit status if the process has already exited.
    pub fn try_exit(&mut self) -> Option<ExitStatus> {
        self.child.try_wait().ok().flatten()
    }

    /// Poll (20 ms) until exit or `timeout`; returns the status if it
    /// exited in time.
    pub async fn wait_exit(&mut self, timeout: Duration) -> Option<ExitStatus> {
        let deadline = Instant::now() + timeout;
        loop {
            if let Some(status) = self.try_exit() {
                return Some(status);
            }
            if Instant::now() >= deadline {
                return None;
            }
            tokio::time::sleep(Duration::from_millis(20)).await;
        }
    }

    /// Send a POSIX signal by name ("TERM", "INT", ...).
    pub fn signal(&self, name: &str) {
        let _ = Command::new("kill")
            .arg(format!("-{name}"))
            .arg(self.child.id().to_string())
            .status();
    }

    /// Everything the process wrote to stderr so far.
    pub fn stderr(&self) -> String {
        std::fs::read_to_string(&self.stderr_path).unwrap_or_default()
    }
}

impl Drop for Daemon {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
        let _ = std::fs::remove_file(&self.stderr_path);
    }
}

/// Run `bin` with `args` to completion (used for CLI-validation tests):
/// returns (exit status, stdout, stderr).
pub fn run(bin: &str, args: &[&str]) -> (ExitStatus, String, String) {
    let out = Command::new(bin)
        .args(args)
        .stdin(Stdio::null())
        .output()
        .unwrap_or_else(|e| panic!("cannot run {bin}: {e}"));
    (
        out.status,
        String::from_utf8_lossy(&out.stdout).into_owned(),
        String::from_utf8_lossy(&out.stderr).into_owned(),
    )
}
