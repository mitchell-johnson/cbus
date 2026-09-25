//! Durable recovery-journal primitive for selected-serial
//! commissioning — exclusive create + atomic replace + fsync + bounded
//! guarded reads. NO apply/verify orchestration, NO PCI.
//!
//! Oracle: `toolkit-cli/src/cbus_toolkit/pci_selected_serial.py` `_Journal`
//! plus the `_json` write bound (`MAX_JOURNAL_BYTES` 16 MiB) and the
//! `last_update` evidence vocabulary (`initial_creation`, `file_synced`,
//! `replacement_attempted/completed`, `directory_synced`,
//! `disk_matches_proposed`, `failed`, cleanup errors).

use cbus_transport::journal::{RecoveryJournal, MAX_JOURNAL_BYTES, MAX_JOURNAL_DEPTH};
use serde_json::{json, Value};
use std::fs;
use std::path::PathBuf;
use std::sync::atomic::{AtomicU64, Ordering};

static COUNTER: AtomicU64 = AtomicU64::new(0);

fn tempdir() -> PathBuf {
    let dir = std::env::temp_dir().join(format!(
        "cbus-p3f-journal-{}-{}",
        std::process::id(),
        COUNTER.fetch_add(1, Ordering::SeqCst)
    ));
    fs::create_dir_all(&dir).expect("tempdir must be creatable");
    dir
}

fn canonical_bytes(text: &str) -> Vec<u8> {
    let mut raw = text.as_bytes().to_vec();
    raw.push(b'\n');
    raw
}

fn cleanup(dir: &PathBuf) {
    let _ = fs::remove_dir_all(dir);
}

fn new_journal(path: &PathBuf) -> RecoveryJournal {
    RecoveryJournal::new(path).expect("journal path must resolve")
}

#[test]
fn journal_create_write_read_round_trip() {
    let dir = tempdir();
    let path = dir.join("recovery.json");
    let mut journal = new_journal(&path);
    let value = json!({"format": "probe", "n": 1});
    journal.write(&value).expect("initial write must succeed");
    let update = journal.last_update();
    assert!(
        update.initial_creation,
        "first write is an initial creation"
    );
    assert!(update.file_synced, "file descriptor must be fsynced");
    assert!(
        !update.replacement_attempted,
        "initial creation attempts no replacement"
    );
    assert!(
        !update.replacement_completed,
        "initial creation completes no replacement"
    );
    assert!(
        update.directory_synced,
        "parent directory must be fsynced after create"
    );
    assert_eq!(
        update.disk_matches_proposed,
        Some(true),
        "disk must match the proposed bytes"
    );
    assert!(
        !journal.failed(),
        "success must not mark the journal failed"
    );
    assert!(
        update.cleanup_errors.is_empty(),
        "no cleanup errors expected"
    );
    let raw = journal.read_current().expect("read-back must succeed");
    assert_eq!(
        raw,
        canonical_bytes(r#"{"format":"probe","n":1}"#),
        "identical Python-canonical bytes on disk"
    );
    assert_eq!(
        fs::read(&path).expect("direct read"),
        canonical_bytes(r#"{"format":"probe","n":1}"#)
    );
    cleanup(&dir);
}

#[test]
fn journal_second_writer_is_refused_exclusive() {
    let dir = tempdir();
    let path = dir.join("recovery.json");
    let mut first = new_journal(&path);
    first.write(&json!({"n": 1})).expect("first writer wins");
    let mut second = new_journal(&path);
    let error = second
        .write(&json!({"n": 2}))
        .expect_err("second exclusive create must fail");
    assert_eq!(
        error.reason(),
        "exclusive_exists",
        "unexpected reason: {error}"
    );
    assert!(second.failed(), "failed write must mark the journal failed");
    // The failure probe reports the winner's bytes, not the refused proposal.
    assert_eq!(
        second.last_update().disk_matches_proposed,
        Some(false),
        "probe must report disk differs from the refused proposal"
    );
    // The winner's bytes are untouched.
    assert_eq!(
        fs::read(&path).expect("direct read"),
        canonical_bytes(r#"{"n":1}"#)
    );
    cleanup(&dir);
}

#[test]
fn journal_external_change_refuses_replacement() {
    let dir = tempdir();
    let path = dir.join("recovery.json");
    let mut journal = new_journal(&path);
    journal.write(&json!({"n": 1})).expect("initial write");
    fs::write(&path, b"{\"n\":999}\n").expect("external modification");
    let error = journal
        .write(&json!({"n": 2}))
        .expect_err("replacement after external change must fail");
    assert_eq!(
        error.reason(),
        "external_change",
        "unexpected reason: {error}"
    );
    assert!(
        journal.failed(),
        "failed write must mark the journal failed"
    );
    assert_eq!(
        journal.last_update().disk_matches_proposed,
        Some(false),
        "probe must report the external bytes differ from the proposal"
    );
    let update = journal.last_update();
    assert!(
        !update.initial_creation,
        "second write is not an initial creation"
    );
    assert!(
        !update.replacement_completed,
        "tainted replacement must never complete"
    );
    // The external bytes win; the refused proposal was never installed.
    assert_eq!(fs::read(&path).expect("direct read"), b"{\"n\":999}\n");
    cleanup(&dir);
}

#[test]
fn journal_symlink_and_nonregular_reads_refused() {
    let dir = tempdir();
    #[cfg(unix)]
    {
        use std::os::unix::fs::symlink;
        let real = dir.join("real.json");
        fs::write(&real, b"{\"n\":1}\n").expect("real file");
        let link = dir.join("link.json");
        symlink(&real, &link).expect("symlink must be creatable");
        let journal = new_journal(&link);
        let error = journal
            .read_current()
            .expect_err("symlink read must be refused");
        assert!(
            ["symlink_refused", "not_regular_file"].contains(&error.reason()),
            "unexpected reason: {error}"
        );
    }
    // A directory is never a regular journal file.
    let journal = new_journal(&dir);
    let error = journal
        .read_current()
        .expect_err("directory read must be refused");
    assert_eq!(
        error.reason(),
        "not_regular_file",
        "unexpected reason: {error}"
    );
    // A FIFO must be refused without opening it (never block).
    let fifo = dir.join("fifo.json");
    if std::process::Command::new("mkfifo")
        .arg(&fifo)
        .output()
        .map(|out| out.status.success())
        .unwrap_or(false)
    {
        let journal = new_journal(&fifo);
        let error = journal
            .read_current()
            .expect_err("fifo read must be refused");
        assert_eq!(
            error.reason(),
            "not_regular_file",
            "unexpected reason: {error}"
        );
    }
    // An oversized file on disk is refused by the bounded read (16 MiB + 1).
    let huge = dir.join("huge.json");
    let chunk = vec![b'x'; 1024 * 1024];
    {
        let mut handle = fs::File::create(&huge).expect("huge file");
        for _ in 0..17 {
            use std::io::Write;
            handle.write_all(&chunk).expect("fill huge file");
        }
    }
    let journal = new_journal(&huge);
    let error = journal
        .read_current()
        .expect_err("oversized read must be refused");
    assert_eq!(
        error.reason(),
        "journal_too_large",
        "unexpected reason: {error}"
    );
    cleanup(&dir);
}

#[test]
fn journal_oversize_and_unencodable_values_refused() {
    let dir = tempdir();
    // Oversize: one string larger than the 16 MiB journal bound.
    let big = "x".repeat(MAX_JOURNAL_BYTES + 1);
    let path = dir.join("big.json");
    let mut journal = new_journal(&path);
    let error = journal
        .write(&Value::String(big))
        .expect_err("oversize write must fail");
    assert_eq!(error.reason(), "oversize", "unexpected reason: {error}");
    assert!(!path.exists(), "refused write must not create the file");
    // Oracle-exact: encoding is rejected before any state is touched, so a
    // refused value leaves `failed` and `last_update` alone (no I/O was
    // attempted, nothing to probe).
    assert!(
        !journal.failed(),
        "encode rejection attempts no I/O and must not poison the journal"
    );
    assert_eq!(
        journal.last_update().disk_matches_proposed,
        None,
        "no probe runs for a value rejected before I/O"
    );

    // Non-finite f64s are unrepresentable as `serde_json::Value` (the
    // constructors coerce to Null/None), so the encoder's finite-walk is
    // defense-in-depth mirroring `allow_nan=False`; deeply nested values
    // mirror the oracle's `RecursionError` rejection.
    let mut deep = json!(null);
    for _ in 0..1024 {
        deep = Value::Array(vec![deep]);
    }
    let path = dir.join("deep.json");
    let mut journal = new_journal(&path);
    let error = journal.write(&deep).expect_err("recursive write must fail");
    assert_eq!(
        error.reason(),
        "unencodable_value",
        "unexpected reason: {error}"
    );
    assert!(!path.exists(), "refused write must not create the file");
    cleanup(&dir);
}

#[test]
fn journal_nesting_boundary_matches_oracle() {
    assert_eq!(
        MAX_JOURNAL_DEPTH, 127,
        "oracle MAX_JSON_DEPTH is 127; depth > 127 must be rejected"
    );
    let dir = tempdir();
    // End with an empty container so the test proves that the container
    // itself counts, rather than relying on an over-depth scalar child.
    let mut too_deep = Value::Array(Vec::new());
    for _ in 1..128 {
        too_deep = Value::Array(vec![too_deep]);
    }
    let path = dir.join("too-deep.json");
    let mut journal = new_journal(&path);
    let error = journal
        .write(&too_deep)
        .expect_err("128-deep write must fail");
    assert_eq!(
        error.reason(),
        "unencodable_value",
        "unexpected reason: {error}"
    );
    assert!(!path.exists(), "refused write must not create the file");
    // 127-deep: accepted.
    let mut at_limit = Value::Array(Vec::new());
    for _ in 1..127 {
        at_limit = Value::Array(vec![at_limit]);
    }
    let path = dir.join("at-limit.json");
    let mut journal = new_journal(&path);
    journal
        .write(&at_limit)
        .expect("127-deep write must succeed");
    assert_eq!(
        journal.read_current().expect("read-back"),
        canonical_bytes(&format!("{}{}", "[".repeat(127), "]".repeat(127)))
    );
    cleanup(&dir);
}

#[test]
fn journal_replacement_produces_identical_bytes() {
    let dir = tempdir();
    let path = dir.join("recovery.json");
    let mut journal = new_journal(&path);
    journal.write(&json!({"n": 1})).expect("initial write");
    let second = json!({"n": 2, "nested": {"a": [1, 2, 3]}});
    journal
        .write(&second)
        .expect("replacement write must succeed");
    let update = journal.last_update();
    assert!(
        !update.initial_creation,
        "second write is a replacement, not a creation"
    );
    assert!(update.file_synced, "replacement temp file must be fsynced");
    assert!(
        update.replacement_attempted,
        "replacement must be attempted"
    );
    assert!(
        update.replacement_completed,
        "replacement must complete atomically"
    );
    assert!(
        update.directory_synced,
        "parent directory must be fsynced after replace"
    );
    assert_eq!(
        update.disk_matches_proposed,
        Some(true),
        "disk must match the proposed bytes"
    );
    assert!(
        !journal.failed(),
        "success must not mark the journal failed"
    );
    assert_eq!(
        fs::read(&path).expect("direct read"),
        canonical_bytes(r#"{"n":2,"nested":{"a":[1,2,3]}}"#),
        "replacement must install identical bytes"
    );
    // No stray temp files remain beside the journal.
    let leftovers: Vec<_> = fs::read_dir(&dir)
        .expect("read_dir")
        .map(|entry| entry.expect("entry").file_name())
        .collect();
    assert_eq!(
        leftovers,
        vec![std::ffi::OsString::from("recovery.json")],
        "temp file must be renamed away, never left behind"
    );
    cleanup(&dir);
}

#[test]
fn journal_bytes_match_python_for_unicode_controls_and_floats() {
    let dir = tempdir();
    let path = dir.join("canonical.json");
    let mut journal = new_journal(&path);
    let value = json!({
        "é": "é",
        "😀": "😀",
        "small": 1e-5,
        "scientific": 1e-6,
        "large": 1e16,
        "negative_zero": -0.0,
        "control": "\u{0000}\u{001f}\u{007f}\n\"\\/",
    });
    journal
        .write(&value)
        .expect("Python-representable JSON must be written");
    assert_eq!(
        fs::read(&path).expect("direct read"),
        canonical_bytes(
            r#"{"control":"\u0000\u001f\u007f\n\"\\/","large":1e+16,"negative_zero":-0.0,"scientific":1e-06,"small":1e-05,"\u00e9":"\u00e9","\ud83d\ude00":"\ud83d\ude00"}"#,
        ),
        "bytes must equal Python json.dumps(sort_keys=True, separators=(',', ':'), allow_nan=False)"
    );
    cleanup(&dir);
}

#[test]
fn journal_size_bound_includes_trailing_newline_exactly() {
    let dir = tempdir();
    let accepted_path = dir.join("accepted.json");
    let mut accepted = new_journal(&accepted_path);
    accepted
        .write(&Value::String("x".repeat(MAX_JOURNAL_BYTES - 3)))
        .expect("quotes plus payload plus newline exactly at the bound must fit");
    assert_eq!(
        fs::metadata(&accepted_path).expect("metadata").len(),
        MAX_JOURNAL_BYTES as u64
    );

    let rejected_path = dir.join("rejected.json");
    let mut rejected = new_journal(&rejected_path);
    let error = rejected
        .write(&Value::String("x".repeat(MAX_JOURNAL_BYTES - 2)))
        .expect_err("a complete record one byte over the bound must fail");
    assert_eq!(error.reason(), "oversize", "unexpected reason: {error}");
    assert!(
        !rejected_path.exists(),
        "oversize rejection must happen before I/O"
    );
    assert!(
        !rejected.failed(),
        "pre-I/O encode rejection must not poison the journal"
    );
    cleanup(&dir);
}
