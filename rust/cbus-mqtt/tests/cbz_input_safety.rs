//! Public project-input guards: bounded regular-file reads without FIFO hangs.

use cbus_mqtt::cbz::{load_xml, read_cbz_labels, CbzError, MAX_DOCUMENT_BYTES};
use std::fs::{self, File};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicUsize, Ordering};

static UNIQUE: AtomicUsize = AtomicUsize::new(0);

struct Scratch(PathBuf);

impl Scratch {
    fn new() -> Self {
        let number = UNIQUE.fetch_add(1, Ordering::Relaxed);
        let path =
            std::env::temp_dir().join(format!("cbz-input-safety-{}-{number}", std::process::id()));
        fs::create_dir(&path).unwrap();
        Self(path)
    }

    fn path(&self, name: &str) -> PathBuf {
        self.0.join(name)
    }
}

impl Drop for Scratch {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

const XML: &str = "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\r\n\
<Installation><Project><Network TagName=\"Local\">\
<Application Address=\"56\" TagName=\"Lighting\">\
<Group Address=\"1\" TagName=\"Café\"/>\
</Application></Network></Project></Installation>\r\n";

fn assert_project_preserved(path: &Path) {
    assert_eq!(load_xml(path).unwrap(), XML);
    let labels = read_cbz_labels(path, Some("Local")).unwrap();
    assert_eq!(labels[&56].0, "Lighting");
    assert_eq!(labels[&56].1[&1], "Café");
}

#[test]
fn regular_xml_preserves_exact_text_and_labels() {
    let scratch = Scratch::new();
    let path = scratch.path("project.xml");
    fs::write(&path, XML).unwrap();
    assert_project_preserved(&path);
}

#[test]
fn sparse_file_beyond_raw_limit_is_refused_before_xml_extraction() {
    let scratch = Scratch::new();
    let path = scratch.path("too-large.xml");
    File::create(&path)
        .unwrap()
        .set_len(MAX_DOCUMENT_BYTES as u64 + 1)
        .unwrap();
    assert!(
        matches!(load_xml(&path), Err(CbzError::Cbz(_))),
        "oversized raw input must fail in the loader, before XML parsing"
    );
}

#[cfg(unix)]
#[test]
fn regular_file_symlink_preserves_exact_text_and_labels() {
    let scratch = Scratch::new();
    let source = scratch.path("source.xml");
    let link = scratch.path("project.xml");
    fs::write(&source, XML).unwrap();
    std::os::unix::fs::symlink(&source, &link).unwrap();
    assert_project_preserved(&link);
}

#[cfg(unix)]
const CHILD_PATH: &str = "CBUS_MQTT_INPUT_SAFETY_CHILD_PATH";

/// Run a potentially blocking input in its own process so a regression cannot
/// hang the test runner. The child only invokes the local file-reading API.
#[cfg(unix)]
fn assert_refused_without_hanging(path: &Path) {
    use std::process::{Command, Stdio};
    use std::time::{Duration, Instant};

    let mut child = Command::new(std::env::current_exe().unwrap())
        .args(["--exact", "reject_special_file_child", "--nocapture"])
        .env(CHILD_PATH, path)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();
    let deadline = Instant::now() + Duration::from_secs(5);
    loop {
        if let Some(status) = child.try_wait().unwrap() {
            let output = child.wait_with_output().unwrap();
            assert!(
                status.success(),
                "input {} was not refused: {}{}",
                path.display(),
                String::from_utf8_lossy(&output.stdout),
                String::from_utf8_lossy(&output.stderr)
            );
            assert!(
                String::from_utf8_lossy(&output.stdout).contains("CBUS_INPUT_REFUSED"),
                "the expected child test did not run"
            );
            return;
        }
        if Instant::now() >= deadline {
            let _ = child.kill();
            let _ = child.wait();
            panic!("project input read blocked on {}", path.display());
        }
        std::thread::sleep(Duration::from_millis(10));
    }
}

#[cfg(unix)]
#[test]
fn reject_special_file_child() {
    let Some(path) = std::env::var_os(CHILD_PATH) else {
        return;
    };
    assert!(
        load_xml(Path::new(&path)).is_err(),
        "nonregular project input must be refused"
    );
    println!("CBUS_INPUT_REFUSED");
}

#[cfg(unix)]
#[test]
fn fifo_without_writer_is_refused_without_hanging() {
    use std::ffi::CString;
    use std::os::unix::ffi::OsStrExt;

    let scratch = Scratch::new();
    let path = scratch.path("project.xml");
    let name = CString::new(path.as_os_str().as_bytes()).unwrap();
    // SAFETY: name is a live NUL-terminated path in this test's owned directory.
    let result = unsafe { libc::mkfifo(name.as_ptr(), 0o600) };
    assert_eq!(result, 0, "mkfifo: {}", std::io::Error::last_os_error());
    assert_refused_without_hanging(&path);
}

#[cfg(unix)]
#[test]
fn character_device_is_refused_without_hanging() {
    assert_refused_without_hanging(Path::new("/dev/null"));
}
